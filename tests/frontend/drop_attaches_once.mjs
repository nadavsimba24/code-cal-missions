/* A file reaches the conversation exactly once — however it got there.

   Three roads lead to one upload, and every one of them has produced a double
   at some point:

     * a drop on the composer. Chat.onDrop sits on the composer, where it can
       turn an Outlook drag carrying no file bytes into an .eml; bindDnd also
       listens on #chat-panel so a file can be dropped anywhere on the panel
       and not only on the composer strip. The composer is INSIDE the panel, so
       a drop on it fires the inner handler and then bubbles to the outer one —
       and the file was uploaded twice, under two different names, because the
       panel uploaded the raw file while the composer named it first.
     * a drop on the panel outside the composer. One handler, and it must stay
       one.
     * a paste. It lived on the textarea (onpaste=…), then briefly on the
       panel — where a paste with focus on <body> never travels — and now on
       document, which is the only node every paste passes. A listener on
       document is global and PERMANENT: if bindDnd ever ran twice, every
       paste in the session would upload twice, for good.

   So this does not call the handlers directly. It builds the listener graph
   the page really builds — a composer inside a panel inside a document, with
   bubbling and stopPropagation — dispatches one event, and counts.

   Driven by tests/test_drop_attaches_once.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const at = src.indexOf('const Chat = {');
const chatSrc = src.slice(at, src.indexOf('\n};', at)) + '\n};';

/* an object METHOD, not a function declaration — brace-match from its header */
function grabMethod(header){
  const i = src.indexOf(header);
  if(i < 0) throw new Error('not found: '+header);
  let d = 0, j = src.indexOf('{', i);
  for(let k = j; k < src.length; k++){
    if(src[k] === '{') d++;
    else if(src[k] === '}'){ d--; if(!d) return src.slice(i, k+1); }
  }
  throw new Error('unbalanced: '+header);
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

/* ── a DOM with just enough of one: parents, listeners, bubbling ────────── */
function node(name, parent){
  const n = {
    name, parent, _on:{}, classes:new Set(),
    classList:{add:c=>n.classes.add(c), remove:c=>n.classes.delete(c),
               contains:c=>n.classes.has(c)},
    addEventListener:(k,fn)=>{ (n._on[k]=n._on[k]||[]).push(fn); },
    contains:other=>{ for(let p=other;p;p=p.parent) if(p===n) return true; return false; },
  };
  return n;
}
function dispatch(target, type, ev){
  // the real path: the target, then every ancestor, until somebody stops it
  ev.type=type; ev.target=target;
  for(let n=target; n; n=n.parent){
    for(const fn of (n._on[type]||[])){ fn(ev); if(ev._stopped) return ev; }
    if(ev._stopped) return ev;
  }
  return ev;
}

function world(){
  const w = {uploads:[], toasts:[]};
  const doc = node('document', null);
  const panel = node('#chat-panel', doc);
  const composer = node('.composer', panel);
  panel.classes.add('open');
  doc.getElementById = id => id==='chat-panel' ? panel : null;
  doc.querySelector = () => null;              // no Sortable drag in flight
  doc.addEventListener = (k,fn)=>{ (doc._on[k]=doc._on[k]||[]).push(fn); };

  const Chat = new Function('document','canComment','toast','File','Blob','console',
    chatSrc + '\nreturn Chat;')(
    doc, ()=>true, m=>w.toasts.push(m),
    function File(parts,name,opts){ return {name, size:(opts||{}).size||1, type:(opts||{}).type||''}; },
    function Blob(parts){ return {_parts:parts}; },
    {info(){}, debug(){}});
  Chat._upload = async f => { w.uploads.push(f && f.name); };
  Chat.renderAtts = () => {};
  Chat.insert = () => {};
  Chat.bindDnd();
  // the composer's own inline handlers, exactly as composerHTML writes them
  composer.addEventListener('drop', e=>Chat.onDrop(e));
  Object.assign(w, {Chat, doc, panel, composer});
  return w;
}

const ev = files => ({
  _stopped:false, _prevented:false,
  preventDefault(){ this._prevented=true; },
  stopPropagation(){ this._stopped=true; },
  dataTransfer:{
    types:['Files'],
    items: files.map(n=>({kind:'file', getAsFile:()=>({name:n, size:1024})})),
    files: files.map(n=>({name:n, size:1024})),
    getData(){ return ''; },
  },
});
const pasteEv = files => ({
  _stopped:false,
  preventDefault(){},
  stopPropagation(){ this._stopped=true; },
  clipboardData:{ items: files.map(n=>({kind:'file', type:'application/pdf',
                                        getAsFile:()=>({name:n, size:2048, type:'application/pdf'})})) },
});
const settle = () => new Promise(r=>setTimeout(r,0));

// ── a drop on the composer: the inner handler takes it, the panel must not ──
{
  const w = world();
  dispatch(w.composer, 'drop', ev(['מהמייל.pdf']));
  await settle();
  ck('a file dropped on the composer is uploaded exactly once',
     w.uploads.length === 1, w.uploads.join(', '));
  ck('...under one name, not the raw one and the normalised one',
     new Set(w.uploads).size === 1, w.uploads.join(', '));
}

// ── a drop on the panel, where the composer is not ──────────────────────────
{
  const w = world();
  dispatch(w.panel, 'drop', ev(['מהשולחן.docx']));
  await settle();
  ck('a file dropped on the conversation away from the composer is uploaded once',
     w.uploads.length === 1, w.uploads.join(', '));
}

// ── two files are two uploads, not four ────────────────────────────────────
{
  const w = world();
  dispatch(w.composer, 'drop', ev(['a.pdf','b.pdf']));
  await settle();
  ck('two files dropped together are one upload each',
     w.uploads.join(',') === 'a.pdf,b.pdf', w.uploads.join(','));
}

// ── paste, from anywhere ───────────────────────────────────────────────────
{
  const w = world();
  dispatch(w.doc, 'paste', pasteEv(['מודבק.pdf']));
  await settle();
  ck('a pasted file is uploaded exactly once', w.uploads.length === 1, w.uploads.join(','));
}
{
  // the caret inside the composer: the event starts there and bubbles to
  // document. One listener on the path means one upload, still.
  const w = world();
  dispatch(w.composer, 'paste', pasteEv(['מודבק.pdf']));
  await settle();
  ck('...and once too when the caret is inside the composer it starts from',
     w.uploads.length === 1, w.uploads.join(','));
}

// ── the one that would double every paste for the rest of the session ──────
{
  /* bindDnd listens on `document`, and a document listener is global and
     permanent: it is not swept away when the panel re-renders. Chat.open calls
     bindDnd every single time a conversation is opened, so without the guard
     the tenth conversation of the day would attach every pasted file ten
     times. */
  const w = world();
  for(let i=0;i<5;i++) w.Chat.bindDnd();          // as if the chat were reopened
  dispatch(w.doc, 'paste', pasteEv(['שוב.pdf']));
  await settle();
  ck('reopening the conversation does not add a second paste listener',
     w.uploads.length === 1, w.uploads.length + ' uploads after 6 binds');
  w.uploads.length = 0;
  dispatch(w.panel, 'drop', ev(['שוב.pdf']));
  await settle();
  ck('...nor a second drop listener', w.uploads.length === 1, w.uploads.length + ' uploads');
}

// ── and a paste while no conversation is open belongs to nobody ────────────
{
  const w = world();
  w.panel.classList.remove('open');
  dispatch(w.doc, 'paste', pasteEv(['רחוק.pdf']));
  await settle();
  ck('a paste with no conversation open attaches nothing',
     w.uploads.length === 0, w.uploads.join(','));
}

// ── the handlers are still the ones the page wires, not a copy ─────────────
{
  const bind = grabMethod('bindDnd(){');
  ck('the panel still takes a drop anywhere on the conversation',
     /panel\.addEventListener\('drop'/.test(bind));
  ck('...and routes it to the same onDrop rather than uploading on its own',
     /this\.onDrop\(e\)/.test(bind) && !/_upload\(/.test(bind), bind);
  ck('...which is why onDrop stops the event: both roads lead to it, and a '
     +'drop on the composer must travel only one',
     /stopPropagation/.test(grabMethod('async onDrop(e){')));
  ck('paste is bound once, on document, behind the open check',
     /document\.addEventListener\('paste'/.test(bind)
     && /_dndBound/.test(bind) && /contains\('open'\)/.test(bind), bind);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
