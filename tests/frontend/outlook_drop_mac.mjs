/* Dragging a mail attachment into the conversation, on a Mac.

   It worked on Windows and did nothing on a Mac, and the reason is in the two
   handlers that were bound to the same panel with different rules.

   Windows Outlook puts an attachment on the drag as CF_HDROP: the browser
   reports a "Files" type and hands over the bytes. macOS Outlook hands over a
   PROMISE — the bytes are not on the drag at all — so there is no "Files"
   type, and the panel's handler refused the drag at `dragover`. A dragover
   that does not preventDefault means the browser cancels the drop before it
   happens: no drop event, no feedback, nothing to explain itself. Only the
   composer strip at the bottom of the panel had the wider rule, and that is a
   target a few dozen pixels high.

   What is pinned here: the panel and the composer accept the same drags, both
   end in the same handler, and a macOS drag with no bytes is still turned into
   something — the mail as a .eml — rather than dropped.

   Driven by tests/test_outlook_drop_mac.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const at = src.indexOf('const Chat = {');
const chatSrc = src.slice(at, src.indexOf('\n};', at)) + '\n};';

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

// ── the drags, as each platform really presents them ──────────────────────
function drag({types, files=[], data={}}){
  const e = {
    _prevented:false, _stopped:false,
    preventDefault(){ this._prevented=true; },
    stopPropagation(){ this._stopped=true; },
    dataTransfer:{
      types, files,
      items: files.map(f=>({kind:'file', getAsFile:()=>f})),
      getData:k=>data[k]||'',
    },
  };
  return e;
}
const file = (name, type, body='x') => ({name, type, size:(body||'').length, _body:body});
// What macOS gives for a promised attachment: the name, and no bytes at all.
const promised = (name, type='') => ({name, type, size:0});

// Windows Outlook: the bytes come with the drag.
const WINDOWS = () => drag({
  types:['Files','FileGroupDescriptor','FileContents','text/html'],
  files:[file('דוח.pdf','application/pdf')],
  data:{'text/html':'<p>הדוח המצורף</p>'},
});
// macOS Outlook: a promised file. No "Files", no bytes — the mail's HTML only.
const MAC = () => drag({
  types:['text/html','text/plain','public.url'],
  data:{'text/html':'<p>שלום, מצורף הדוח</p>','text/plain':'הדוח הרבעוני\nשלום, מצורף'},
});
// macOS, nothing a browser can read at all
const MAC_EMPTY = () => drag({types:['public.file-url']});
/* And the real report: dragging from Outlook changed NOTHING on screen. At
   dragover the browser hides the bytes and, for a drag it cannot interpret,
   names no types either — so a rule written against type names answers "no",
   the dragover does not preventDefault, and the browser cancels the drop
   before it happens. No drop zone, no cursor, no drop event. */
const MAC_SILENT = () => drag({types:[]});

// ── the world ─────────────────────────────────────────────────────────────
function panelWorld({mayComment=true}={}){
  const w = {uploaded:[], toasts:[], inserted:[], listeners:{}, docListeners:{},
             classes:new Set(), dropHint:false};
  const panel = {
    classList:{add:c=>w.classes.add(c), remove:c=>w.classes.delete(c), contains:c=>w.classes.has(c)},
    addEventListener:(k,fn)=>{ w.listeners[k]=fn; },
    contains:()=>false,
  };
  /* `console` is injected rather than inherited: onDrop logs what the browser
     offered — the one line that tells a failed drag apart from another — and
     that belongs in the person's own console, not in these results. */
  const Chat = new Function('document','canComment','toast','File','Blob','console',
    chatSrc + '\nreturn Chat;')(
    {getElementById: id => id==='chat-panel' ? panel
       : id==='comp-drop' ? {classList:{add:()=>{w.dropHint=true;}, remove:()=>{w.dropHint=false;}}}
       : null,
     // Sortable's marker, present only while a row of our own is being dragged
     querySelector: () => w.internalDrag ? {} : null,
     /* A paste event is dispatched to the FOCUSED element and bubbles from
        there. With focus on <body> it never passes #chat-panel, so the
        listener has to sit on document — the one node every paste travels
        through. Captured here so the test can prove it is not on the panel. */
     addEventListener:(k,fn)=>{ w.docListeners[k]=fn; }},
    () => mayComment,
    m => w.toasts.push(m),
    function File(parts, name, opts){ return {name, type:(opts||{}).type||'', _parts:parts}; },
    function Blob(parts){ return {_parts:parts}; },
    {info:(...a)=>{ w.logged=(w.logged||[]).concat(a.join(' ')); }});
  Chat._upload = async f => { w.uploaded.push(f); return f; };
  Chat.insert = t => w.inserted.push(t);
  Chat.renderAtts = () => {};
  Chat.bindDnd();
  w.Chat = Chat; w.panel = panel;
  w.over = e => w.listeners.dragover(e);
  w.paste = items => w.docListeners.paste({clipboardData:{items}, preventDefault(){ w.pastePrevented=true; }});
  w.drop = async e => { w.listeners.drop(e); await Promise.resolve(); await Promise.resolve(); };
  return w;
}

// ── the rule the two handlers now share ───────────────────────────────────
{
  const w = panelWorld();
  ck('the panel and the composer accept exactly the same drags',
     [WINDOWS(), MAC(), MAC_EMPTY()].every(e => w.Chat._isImport(e) === w.Chat._isImport(e)));
  ck('a macOS Outlook drag is accepted by the panel', w.Chat._isImport(MAC()));
  ck('...and so is a Windows one', w.Chat._isImport(WINDOWS()));
}
{
  const w = panelWorld();
  const e = MAC();
  w.over(e);
  ck('dragover over the conversation is NOT left to the browser to cancel',
     e._prevented === true, 'the drop never happens without this');
  ck('...and the panel says it will take it', w.classes.has('dnd-over'));
}
{
  const w = panelWorld();
  const e = WINDOWS();
  w.over(e);
  ck('a Windows drag is still accepted, exactly as before', e._prevented === true);
}

{
  const w = panelWorld();
  const e = MAC_SILENT();
  w.over(e);
  ck('a drag the browser describes as NOTHING still turns the panel on',
     e._prevented === true, 'without preventDefault the drop never happens');
  ck('...and "שחרר כאן כדי לצרף לשיחה" appears, which is what was missing',
     w.classes.has('dnd-over'));
}
{
  // the one drag that must not be taken: a row of our own being reordered
  const w = panelWorld();
  w.internalDrag = true;
  const e = drag({types:['Files'], files:[file('x.pdf','application/pdf')]});
  w.over(e);
  ck('dragging a row of the board around is not an attachment',
     e._prevented === false && !w.classes.has('dnd-over'));
}

// ── what lands ────────────────────────────────────────────────────────────
{
  const w = panelWorld();
  await w.drop(WINDOWS());
  ck('a Windows attachment dropped on the panel is uploaded',
     w.uploaded.length === 1 && w.uploaded[0].name === 'דוח.pdf',
     w.uploaded.map(f=>f.name));
}
{
  const w = panelWorld();
  await w.drop(MAC());
  ck('a macOS drag with no bytes still attaches the mail',
     w.uploaded.length === 1, w.toasts.concat(w.uploaded.map(f=>f.name)));
  ck('...as a .eml anybody can reopen',
     /\.eml$/.test((w.uploaded[0]||{}).name||''), (w.uploaded[0]||{}).name);
  ck('...named after the mail, not "attachment"',
     ((w.uploaded[0]||{}).name||'').includes('הדוח'), (w.uploaded[0]||{}).name);
}
{
  const w = panelWorld();
  await w.drop(MAC_EMPTY());
  ck('a drag the browser gave nothing for says so instead of failing in silence',
     w.toasts.length === 1, w.toasts);
  ck('...and names the way round it on a Mac',
     /⌘C|להדביק/.test(w.toasts[0]||''), w.toasts[0]);
}
{
  const w = panelWorld({mayComment:false});
  await w.drop(WINDOWS());
  ck('somebody who may not comment cannot attach by dropping',
     w.uploaded.length === 0 && w.toasts.length === 1, w.toasts);
}

// ── the promise: a name, and not one byte behind it ───────────────────────
{
  // Chrome turns a macOS promise into a File of size 0. Read as a file, it was
  // uploaded as an empty attachment and the mail — which the drag DOES carry —
  // was never looked at. From outside: "dragging from the mail does nothing",
  // while the same file dragged out of Finder works.
  const e = drag({
    types:['Files','public.file-url','text/html','text/plain'],
    files:[promised('הדוח הרבעוני.pdf','application/pdf')],
    data:{'text/html':'<p>מצורף הדוח</p>','text/plain':'הדוח הרבעוני'},
  });
  const w = panelWorld();
  await w.drop(e);
  ck('a file with no bytes is not uploaded as a file',
     !w.uploaded.some(f=>/\.pdf$/.test(f.name||'')), w.uploaded.map(f=>f.name));
  ck('...the mail behind it is attached instead',
     w.uploaded.length===1 && /\.eml$/.test(w.uploaded[0].name||''), w.uploaded.map(f=>f.name));
  ck('...under the name the promise did carry',
     (w.uploaded[0]||{}).name === 'הדוח הרבעוני.eml', (w.uploaded[0]||{}).name);
}
{
  // the promise with nothing else on the drag: all that is left is to say so
  const w = panelWorld();
  await w.drop(drag({types:['Files'], files:[promised('חשבונית.pdf')]}));
  ck('a promise with nothing behind it names the file it failed on',
     (w.toasts[0]||'').includes('חשבונית.pdf'), w.toasts);
  ck('...and still points at the paste route', /⌘C/.test(w.toasts[0]||''), w.toasts[0]);
}
{
  // a real file and a promise together: the real one must not be lost
  const w = panelWorld();
  await w.drop(drag({types:['Files'],
                     files:[promised('ריק.pdf'), file('אמיתי.pdf','application/pdf','bytes')]}));
  ck('a real file dropped beside a promise is still uploaded',
     w.uploaded.length===1 && w.uploaded[0].name==='אמיתי.pdf', w.uploaded.map(f=>f.name));
}

// ── and the paste route, which is the one that works on a Mac ─────────────
function pasteWorld(items){
  const w = {uploaded:[], prevented:false};
  const Chat = new Function('document','canComment','toast','File','Blob','console',
    chatSrc + '\nreturn Chat;')(
    {getElementById:()=>null, querySelector:()=>null}, ()=>true,
    m => { w.toasts = (w.toasts||[]).concat(m); },
    function File(parts, name, opts){ return {name, type:(opts||{}).type||'', _parts:parts}; },
    function Blob(parts){ return {_parts:parts}; }, {info(){}});
  Chat._upload = async f => { w.uploaded.push(f); };
  Chat.renderAtts = () => {};
  Chat.onPaste({clipboardData:{items}, preventDefault(){ w.prevented=true; }});
  return w;
}
const clip = (type, name) => ({kind:'file', type, getAsFile:()=>({name:name||'', type})});
{
  const w = pasteWorld([clip('image/png')]);
  ck('a pasted screenshot still becomes a screenshot',
     /^screenshot-.*\.png$/.test((w.uploaded[0]||{}).name||''), (w.uploaded[0]||{}).name);
}
{
  const w = pasteWorld([clip('application/pdf','דוח.pdf')]);
  ck('a pasted PDF is attached too — it was silently ignored for not being an image',
     (w.uploaded[0]||{}).name === 'דוח.pdf', w.uploaded);
  ck('...and the paste is taken over from the textarea', w.prevented === true);
}
{
  const w = pasteWorld([{kind:'string', type:'text/plain'}]);
  ck('pasting plain text is left alone', w.uploaded.length === 0 && w.prevented === false);
  ck('...and says nothing, because an ordinary paste is not an event',
     (w.toasts||[]).length === 0, w.toasts);
}
{
  /* Neither a file nor text. Right after being told "copy it in Outlook and
     press ⌘V", silence here is indistinguishable from the shortcut not being
     wired up at all — which is what it actually was, twice. */
  const w = pasteWorld([]);
  ck('a clipboard with nothing on it says so instead of staying silent',
     (w.toasts||[]).length === 1 && /אין קובץ בלוח/.test(w.toasts[0]||''), w.toasts);
}
{
  const w = pasteWorld([clip('application/pdf','דוח.pdf'), clip('image/png')]);
  ck('a clipboard carrying both prefers the image, as it always did',
     /^screenshot-/.test((w.uploaded[0]||{}).name||''), (w.uploaded[0]||{}).name);
}

// ── what a failed drag leaves behind to read ──────────────────────────────
/* The per-drop log that used to live in onDrop is gone: the window-level
   diagnostic prints a fuller line for the same event, and two lines per drop
   is one line of noise. What matters is that the diagnostic is bound at the
   window — measured on her Mac, a Finder drag printed enter/over/drop with the
   file and its size, and an Outlook drag printed nothing at all. That is the
   whole finding, and it is checked in tests/test_outlook_drop_mac.py. */

// ── ⌘V anywhere on the conversation, not only inside the text box ─────────
{
  /* Paste was bound on the textarea alone, so ⌘V did nothing unless the caret
     was inside it — and after dragging a file around, it is not. On a Mac that
     is not a small annoyance: paste is the ONLY route that works for a mail
     attachment, and it was being recommended for a shortcut that silently did
     nothing unless you clicked the right box first. */
  const w = panelWorld();
  ck('paste is listened for on document, the one node every paste passes',
     typeof w.docListeners.paste === 'function', Object.keys(w.docListeners).join(','));
  ck('...and not on the panel, which a paste with focus on <body> never reaches',
     typeof w.listeners.paste !== 'function', Object.keys(w.listeners).join(','));
  w.classes.add('open');
  w.paste([{kind:'file', type:'application/pdf', getAsFile:()=>({name:'דוח.pdf', type:'application/pdf'})}]);
  ck('...so a file pasted with the caret nowhere near the box is attached',
     w.uploaded.length === 1 && w.uploaded[0].name === 'דוח.pdf', w.uploaded.map(f=>f.name));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
