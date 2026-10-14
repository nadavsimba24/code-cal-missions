/* A deactivated account is not offered anywhere on the screen.

   The server is the rule (tests/test_inactive_user_is_not_offered.py holds that
   down). This is the screen's half: a picker that lists somebody the server will
   refuse is an invitation to a dead end, and the reason it failed would read as
   a fault in the app rather than as a deactivated account.

   The three invite dropdowns are built from the server's `available` list, which
   no longer contains them, so there is nothing to assert here beyond the lists
   this file *does* build itself:
     · boardPeople()  — the assignee circles, the people cells, the @-menu and
                        the new-item form all render from it
     · Automations.members — the person field of a rule and of a condition
     · permUsers()    — the per-user item/column override rows
   Each keeps anyone who already holds a value, so an old tag or grant can still
   be cleared by hand.
   Driven by tests/test_inactive_user_pickers.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── boardPeople(): run the real function ───────────────────────────────────
const LIVE={id:1,name:'פעילה',is_active:true}, OFF={id:2,name:'מושבת',is_active:false},
      LEGACY={id:3,name:'ותיק'};          // is_active absent → never deactivated
const st={users:[LIVE,OFF,LEGACY],
          board:{members:[{id:1},{id:2},{id:3}]}};
const boardPeople = new Function('st', grab('boardPeople')+'; return boardPeople;')(st);

const offered = boardPeople().map(u=>u.id);
ck('a deactivated member is not offered in a people picker', !offered.includes(OFF.id),
   'got ['+offered+']');
ck('an active member still is', offered.includes(LIVE.id));
ck('a user who was never deactivated (no flag at all) still is',
   offered.includes(LEGACY.id), 'a NULL is_active must not read as blocked');

const withTag = boardPeople([OFF.id]).map(u=>u.id);
ck('someone already tagged is kept, so the tag can be removed',
   withTag.includes(OFF.id), 'got ['+withTag+']');
ck('and is listed once, not twice',
   withTag.filter(x=>x===OFF.id).length===1);

// ── the automation person picker filters the same way ──────────────────────
const autoLoad = /this\.members\s*=\s*\(\(await api\('\/api\/boards\/'\+bid\+'\/members'\)\)\.members\|\|\[\]\)\s*\n?\s*\.filter\(m=>m\.is_active!==false\)/.test(src);
ck('Automations loads its person picker without deactivated members', autoLoad);
/* both person pickers read this.members — if one grew its own source it would
   go round the filter above */
const personPickers = (src.match(/items=this\.members\.map\(/g)||[]).length;
const otherSource = /items=\(st\.users\|\|\[\]\)\.map\(u=>\(\{v:u\.id/.test(src);
ck('and both person pickers read that one list', personPickers===2 && !otherSource,
   personPickers+' pickers');

// ── per-user overrides ─────────────────────────────────────────────────────
const permUsers = new Function('st', grab('permUsers')+'; return permUsers;')(st);
const grantable = permUsers({}).map(u=>u.id);
ck('a deactivated user is not offered a new item/column override',
   !grantable.includes(OFF.id), 'got ['+grantable+']');
const held = permUsers({[OFF.id]:'edit'}).map(u=>u.id);
ck('one who already holds an override stays listed, so it can be cleared',
   held.includes(OFF.id));
/* the two override modals must render from permUsers, not from st.users */
ck('both override modals build their rows from it',
   (src.match(/\$\{permUsers\(perms\)\.map\(u=>`<div class="mem-row">/g)||[]).length===2);

// ── the member screens say why a listed member is in no picker ─────────────
ck('a deactivated member is badged on the board/workspace/environment screens',
   (src.match(/m\.is_active===false\?' <span class="sa-badge off">לא פעיל<\/span>'/g)||[]).length===3);

// ── a refusal is shown in the server's own words ───────────────────────────
const toasts = (src.match(/e&&e\.status===400&&e\.detail\?e\.detail:/g)||[]).length;
ck('an invite refused with 400 reports what the server said', toasts===3, toasts+' handlers');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
