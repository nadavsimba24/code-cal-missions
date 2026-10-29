/* A deletion somebody may not perform is refused before the dialog, not after.

   The menu offered "מחק פריט" to everybody. The confirmation dialog then
   warned, truthfully, that the item could not be restored — and somebody who
   had no delete permission confirmed it, because nothing had told them
   otherwise. The server refused with 403, bulkDelete swallowed that in a bare
   catch, and the only thing the screen said was "0 פריטים נמחקו": a count,
   with no reason in it and nobody to ask.

   Pinned here: the reason is computed from the permission the item already
   carries, it distinguishes a board role from a per-item override, and all
   three delete paths consult it BEFORE askConfirm is reached.

   Runs the real itemPerm / canDeleteItem / deleteBlockReason out of
   index.html. Driven by tests/test_delete_without_permission.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function grabFn(name){
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('not found: ' + name);
  const nl = src.indexOf('\n', i);
  const first = src.slice(i, nl);
  const n = t => (first.match(t) || []).length;
  if (n(/\{/g) === n(/\}/g)) return first;        // a one-liner
  const end = src.indexOf('\n}', nl);
  if (end < 0) throw new Error('no close found for ' + name);
  return src.slice(i, end + 2);
}

const ME = 7;
const api = new Function('meId',
  ['itemPerm', 'canDeleteItem', 'deleteBlockReason'].map(grabFn).join('\n') +
  '\nreturn {itemPerm, canDeleteItem, deleteBlockReason};')(() => ME);

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

// ── who may, and who may not ───────────────────────────────────────────────
ck('somebody with delete permission is not stopped',
   api.deleteBlockReason({my_perm: 'delete'}) === '');
for (const p of ['edit', 'view', 'none']) {
  ck(`"${p}" on the board is refused, and the words name the board`,
     api.deleteBlockReason({my_perm: p}) === 'אין לך הרשאה מתאימה למחיקה בלוח זה',
     api.deleteBlockReason({my_perm: p}));
}

/* The two reasons must not be confused. Telling somebody whose board role DOES
   allow deleting that they lack permission "בלוח זה" sends them to argue with
   the wrong person about a restriction that was placed on one item. */
ck('a per-item override says the item, not the board',
   api.deleteBlockReason({my_perm: 'view', permissions: {[String(ME)]: 'view'}})
     === 'אין לך הרשאה מתאימה למחיקה של פריט זה');
ck('somebody else\'s override is not mine and still reads as the board',
   api.deleteBlockReason({my_perm: 'view', permissions: {'999': 'none'}})
     === 'אין לך הרשאה מתאימה למחיקה בלוח זה');
ck('an override that grants delete does not refuse at all',
   api.deleteBlockReason({my_perm: 'delete', permissions: {[String(ME)]: 'delete'}}) === '');

/* itemPerm defaults to 'edit' for an item that carries no permission at all —
   an older payload, or a board that never set one. That default must not be
   read as permission to delete. */
ck('an item with no permission on it is not deletable by default',
   api.deleteBlockReason({}) !== '');

// ── the three doors all check before they open the dialog ──────────────────
/* The whole function, not a fixed window — bulkDelete outgrew 900 characters
   the moment it learned to count refusals, and a short slice would have made
   this read as a missing feature rather than a short slice. */
const body = f => {
  const i = src.indexOf(f);
  if (i < 0) throw new Error('not found: ' + f);
  const end = src.indexOf('\n}', i);
  if (end < 0) throw new Error('no close found for ' + f);
  return src.slice(i, end + 2);
};
for (const [fn, label] of [['async function deleteItem(e,id){', 'an item'],
                           ['function deleteSubItem(e,id){', 'a sub-item']]) {
  const b = body(fn);
  ck(`${label}: the reason is consulted`, /deleteBlockReason\(/.test(b));
  ck(`${label}: and it is consulted BEFORE askConfirm`,
     b.indexOf('deleteBlockReason(') < b.indexOf('askConfirm('));
}
const bulk = body('async function bulkDelete(){');
ck('a selection is filtered to what may actually be deleted',
   /items\.filter\(canDeleteItem\)/.test(bulk));
ck('a selection nobody may delete never reaches the dialog',
   bulk.indexOf('deleteBlockReason(') < bulk.indexOf('askConfirm('));
ck('the dialog counts what will really go, not what was selected',
   /למחוק \$\{allowed\.length\} פריטים/.test(bulk));
ck('a 403 arriving anyway is reported as a refusal, not as a count of zero',
   /refused\+\+/.test(bulk) && /ללא הרשאה/.test(bulk));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
