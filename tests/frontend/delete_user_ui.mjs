/* The users table must NOT offer permanent deletion.

   The capability exists and is tested (DELETE /api/users/{uid}, system admin
   only — tests/test_delete_user.py). It was built with a button in the
   system-admin screen, used once for an account that should never have existed
   here, and the button was then taken out on purpose: erasing a person is
   irreversible, and one click away from a rename is the wrong place for it.

   So this is a regression guard, not a feature test — it fails if anybody puts
   the affordance back. Driven by tests/test_delete_user_ui.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── nothing in the page reaches the endpoint ──
ck('no handler calls DELETE on a user', !/\/api\/users\/[^'"`]*['"`]?\s*,\s*\{method:\s*['"]DELETE/.test(src)
   && !/SysAdmin\.deleteUser/.test(src), 'a delete path is wired up again');
ck('no "מחק משתמש" affordance anywhere', !src.includes('מחק משתמש'), 'the button is back');
ck('...and its styling is gone with it', !/\.sa-del\{/.test(src) && !/\.sa-menu-sep\{/.test(src));

// ── the row menu is back to what it was: edit, role, department ──
const menu=/\n  rowMenu\(([^)]*)\)\{[\s\S]*?\n  \},/.exec(src);
ck('the users row menu is still there', !!menu);
const m=menu[0];
ck('it offers editing the profile', m.includes('SysAdmin.editUser('), m);
ck('...the role', m.includes('SysAdmin.setRole('), m);
ck('...the department', m.includes('SysAdmin.setDept('), m);
ck('and nothing destructive', !/trash|מחק|deleteUser/.test(m), m);
ck('the comment says why it is absent, so it is not re-added as an oversight',
   /No permanent-delete entry here, deliberately/.test(m), m);

// ── what IS offered for taking access away ──
ck('revoking a guest is still available, which is the reversible answer',
   /SysAdmin\.revokeGuest\(/.test(src));
ck('...and deactivating an account, from the profile editor',
   /SysAdmin\.setActive\(|is_active/.test(/\n  editUser\(([^)]*)\)\{[\s\S]*?\n  \},/.exec(src)[0]));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
