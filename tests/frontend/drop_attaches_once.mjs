/* A file dropped on the chat composer is attached once.

   Two drop handlers cover the same pixels, by design: Chat.onDrop sits on the
   composer, where it can turn an Outlook drag with no file bytes into an .eml,
   and bindDnd listens on #chat-panel so a file can be dropped anywhere on the
   panel rather than only on the little composer strip. The composer is inside
   the panel, so a drop on it fires the inner handler and then bubbles to the
   outer one — and the file was uploaded twice. The two copies did not even
   match for an email: the outer handler uploads the raw file while the inner
   one gives it a name first (_normDropped).

   So the inner handler stops the event once it has taken it. This runs the real
   onDrop out of index.html against a fake drop and counts what it does.
   Driven by tests/test_drop_attaches_once.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

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
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:''))); };

// ── run the real onDrop ────────────────────────────────────────────────────
const body = grabMethod('async onDrop(e){');
const uploaded = [];
let stopped = 0, prevented = 0;
const Chat = new Function('document','toast', `return { ${body},
  _isImport(){ return true; },
  _normDropped(f){ return f; },
  _upload(f){ this.__up.push(f && f.name); },
  insert(){ this.__inserted = true; },
  __up: arguments.length ? [] : [] };`)(
  { getElementById: () => null }, () => {}
);
Chat.__up = uploaded;

const fakeEvent = files => ({
  preventDefault(){ prevented++; },
  stopPropagation(){ stopped++; },
  dataTransfer: {
    types: ['Files'],
    items: files.map(n => ({kind:'file', getAsFile: () => ({name:n})})),
    files,
    getData(){ return ''; },
  },
});

await Chat.onDrop(fakeEvent(['מהמייל.pdf']));
ck('the drop is taken: the file is uploaded', uploaded.length === 1, uploaded.join(','));
ck('...exactly once, not once per handler covering the composer',
   uploaded.length === 1, uploaded.length + ' uploads');
ck('the browser default is cancelled', prevented === 1);
ck('and the event is STOPPED, so #chat-panel does not attach it again',
   stopped === 1,
   'the panel listener in bindDnd would upload the same file a second time');

uploaded.length = 0;
await Chat.onDrop(fakeEvent(['a.pdf','b.pdf']));
ck('two files dropped together are still one upload each',
   uploaded.length === 2, uploaded.join(','));

// ── the outer handler is still there, and still uploads ────────────────────
// If it were gone, stopPropagation above would be pointless and this test
// would be pinning nothing at all.
const bind = grabMethod('bindDnd(){');
ck('bindDnd still listens for a drop on the whole panel',
   /panel\.addEventListener\('drop'/.test(bind), 'the panel-wide drop is gone');
ck('...and still uploads what lands there',
   /_upload\(/.test(bind), 'dropping on the panel no longer attaches anything');
ck('...which is why the composer has to stop the event rather than the panel '
   +'having to guess where the drop landed',
   /hasFiles\(e\)/.test(bind));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
