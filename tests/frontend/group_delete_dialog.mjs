/* Deleting a group asks the way the rest of the app asks, and says why when it
   will not.

   Nothing ever stopped a group being removed — not the first one, not "בתכנון",
   not the one carrying the backlog status; the server deletes any of them and
   detaches their items (tests/test_group_delete_any.py holds that down). What
   made it look otherwise lived in this one function.

   The question was a native confirm(), the only dialog in the app that was not
   ours. A browser may suppress it — a second dialog in quick succession, or
   "prevent this page from creating more dialogs" once ticked — and a suppressed
   confirm() returns false, so the button did nothing whatsoever and explained
   none of it. And every refusal came back as "שגיאה במחיקה", so a board you may
   not edit read exactly like a group that cannot be deleted.
   Driven by tests/test_group_delete_dialog.py. */
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

const fn = grab('deleteGroup');

ck('the group deletion asks with the app\'s own dialog',
   /askConfirm\(/.test(fn));
ck('and not with a native confirm, which a browser is free to suppress',
   !/[^k]confirm\('/.test(fn), fn);
/* a suppressed native confirm() returns false, which this code read as "the
   user said no" — indistinguishable from a group that may not be deleted */
ck('nothing in it treats a falsy answer as a refusal to be swallowed',
   !/if\(!confirm/.test(fn));

ck('a refusal shows the reason the server gave',
   /toast\(\(e&&e\.detail\)\|\|'שגיאה במחיקה'\)/.test(fn), fn);
ck('and the blanket message is only the fallback, for when there is no reason',
   fn.indexOf('e.detail') < fn.indexOf("'שגיאה במחיקה'"));

ck('the group is named in the question, so it is clear which one is going',
   /askConfirm\('למחוק את הקבוצה'\+\(g\?` "\$\{g\.name\}"`:''\)/.test(fn), fn);
ck('and the items in it are counted, the way deleting an item counts its subs',
   /const n=\(st\.board\.tasks\|\|\[\]\)\.filter\(t=>t\.group_id===gid\)\.length/.test(fn));
ck('the note promises what the server actually does — detach, not delete',
   /יעברו ל״ללא קבוצה״ — הם לא נמחקים/.test(fn));
ck('an empty group says it is empty rather than counting nothing at you',
   /:'הקבוצה ריקה\.'/.test(fn), fn);
ck('it is a destructive dialog: red button, מחק on it',
   /confirmText:'מחק'/.test(fn) && /title:'מחיקת קבוצה'/.test(fn));

/* askConfirm closes the modal itself before running the action, so the edit
   dialog the מחק button sits in does not have to be closed again */
ck('the edit dialog is not closed twice',
   !/closeModals\(\)/.test(fn), fn);

// ── and no native dialog is left anywhere in the app ──────────────────────
/* a real call passes a message, so it is `confirm('…` — which also keeps the
   two mentions of confirm() in the prose above out of the count. askConfirm is
   excluded by the lookbehind: the character before it is a word character. */
const natives = [...src.matchAll(/(?<![\w.])confirm\(\s*['"`]/g)];
ck('no native confirm() is left in the app at all',
   natives.length===0, natives.length+' left: '+natives.map(m=>src.slice(m.index,m.index+40)).join(' | '));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
