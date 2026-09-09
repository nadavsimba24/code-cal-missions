/* Adding a group belongs to the board's admin.

   A group is structure — the same kind of decision as a column, which this
   board already treats as the admin's. An editor fills the board in: items,
   values, who is on what. What shelves the board has is not theirs.

   The server is the rule (tests/test_authz.py holds that down). This is about
   the two things the screen owes on top of it: not offering a button whose
   answer is always no, and — when it is reached anyway, because a role can be
   taken away while the board sits open — saying which permission is missing
   rather than reporting a failure that reads like a fault.
   Driven by tests/test_add_group_is_admin_only.py. */
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

// ── the button is not offered to someone who may not use it ────────────────
const btn = /isBoardAdmin\(\)\s*\?\s*`<button class="add-group-btn"[\s\S]{0,200}?:\s*''/.exec(src);
ck('the board renders "+ הוסף קבוצה" only for a board admin', !!btn, btn&&btn[0].slice(0,80));
/* one call site, and it is that button — a second entry point would be a way in
   that neither the guard above nor the hidden button covers */
const calls = (src.match(/(?<!function )addGroup\(\)/g)||[]);
ck('and there is no other way in — one button, one call site',
   calls.length===1 && (src.match(/add-group-btn"/g)||[]).length===1,
   calls.length+' call sites');

// ── and the function refuses anyway ────────────────────────────────────────
const fn = grab('addGroup');
ck('addGroup checks the role itself, ahead of the request',
   /if\(!isBoardAdmin\(\)\)\{ toast\('רק מנהל הלוח יכול להוסיף קבוצות'\); return; \}/.test(fn), fn);
ck('the check runs before anything is sent',
   fn.indexOf('isBoardAdmin()') < fn.indexOf("api('/api/groups'"));
ck('and a refusal from the server is shown in its own words',
   /toast\(\(e&&e\.detail\)\|\|'שגיאה ביצירת קבוצה'\)/.test(fn), fn);

/* the role is read from the board the server sent, so it follows a change of
   role on the next load rather than from anything the client decided */
ck('"board admin" means what the server said the role is',
   /function isBoardAdmin\(\)\{return !!\(st\.board&&st\.board\.my_role==='admin'\);\}/.test(src));

// ── what an editor keeps ───────────────────────────────────────────────────
/* the line between structure and content: editing a group that exists, and
   working the items in it, are not gated here — only bringing a new one into
   being. Renaming and deleting stay where they were, on purpose and on record. */
ck('editing an existing group is still offered to whoever can open the menu',
   /<button class="g-menu-btn" title="עריכת קבוצה" onclick="editGroup\(/.test(src));
ck('and adding an item is not gated on being an admin',
   !/isBoardAdmin\(\)[\s\S]{0,40}openNewItem/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
