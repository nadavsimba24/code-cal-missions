/* The bell, on an event from somebody else.

   bumpNotifications called `Notifications.load()` — an object that does not
   exist in index.html — from inside a try/catch, so every bump since the event
   stream was added threw and was swallowed in silence. The badge therefore only
   ever moved on the five-minute reconcile or when the list was opened, which is
   the difference between a like "popping" and a like appearing eventually.
   Driven by tests/test_notif_bump.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

const bump=/bumpNotifications\(\)\{[\s\S]*?\n  \},/.exec(src);
ck('the bump is still there', !!bump);
ck('it calls the object that exists', /Notif\.load\(\)/.test(bump[0]), bump[0]);
ck('...and not the one that never did', !/Notifications\.load\(/.test(src), 'Notifications is not defined anywhere');
ck('an object by that name is still nowhere in the page',
   !/\b(const|let|var|window\.)Notifications\s*=/.test(src));

/* run the real thing: a fake Notif records the call, and a throw would be
   swallowed exactly as it was before — so the recorded call is the only proof */
const m=/bumpNotifications\(\)\{([\s\S]*?)\n  \},/.exec(src);
let loaded=0;
const self={_notifT:null};
const fn=new Function('Notif','setTimeout','clearTimeout',
  'return function(){'+m[1]+'};').call(self,{load:()=>{loaded++;}},f=>f(),()=>{});
fn.call(self);
ck('a bump actually reaches the loader', loaded===1, 'loaded='+loaded);

// the event that carries a like must not drag the board along with it
const onEv=/onEvent\(ev\)\{[\s\S]*?\n  \},/.exec(src)[0];
ck('a like still bumps the bell', /if\(ev\.actor_id!==meId\(\)\) this\.bumpNotifications\(\);/.test(onEv));
ck('...and stops there, since no row or column changed',
   /if\(ev\.type==='comment\.liked'\)return;/.test(onEv), onEv);
ck('the bump comes before that return, not after',
   onEv.indexOf('bumpNotifications') < onEv.indexOf("ev.type==='comment.liked'"));

// the new notification has a face of its own in the list
ck('a like notification gets its own icon',
   /n\.type==='comment_like'\?'fa-thumbs-up'/.test(src), 'it would fall back to the bell');
ck('...and its own colour', /\.notif-ic\.comment_like\{background:#fdab3d\}/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
