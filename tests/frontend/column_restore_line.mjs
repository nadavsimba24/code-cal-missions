/* The log line that deleted a column offers to put it back.

   A deletion line could say what had happened and nothing else. The data for
   it was never gone — removing a column takes it out of the board's settings
   and leaves every item's value in custom_fields, keyed by the column id — so
   the only thing standing between the line and an undo was the definition,
   which nothing kept.

   Pinned here: the line is labelled for whichever of the two it is, the
   button appears only when the server says the entry is still restorable,
   and the restore is an admin action that asks before it acts.

   Runs the real BoardLog.fieldLabel out of index.html and reads the row
   template and BoardLog.restoreColumn beside it.
   Driven by tests/test_column_restore.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function grabMethod(header){
  const i = src.indexOf(header);
  if (i < 0) throw new Error('not found: ' + header);
  const nl = src.indexOf('\n', i);
  const first = src.slice(i, nl);
  const n = t => (first.match(t) || []).length;
  if (n(/\{/g) === n(/\}/g)) return first.replace(/,\s*$/, '');
  const end = src.indexOf('\n  }', nl);
  if (end < 0) throw new Error('no close found for ' + header);
  return src.slice(i, end + 4);
}

const Chat = new Function('customColumns', `return { ${grabMethod('fieldHe(f){')} };`)(() => []);
const BoardLog = new Function('customColumns', 'Chat',
  `return { ${grabMethod('fieldLabel(a){')} };`)(() => [], Chat);

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

// ── the two lines read as the two different events ────────────────────────
const del = {action: 'delete', field: 'column', old: 'תקציב'};
const res = {action: 'restore', field: 'column', new: 'תקציב'};
ck('a deleted column still says it was deleted', BoardLog.fieldLabel(del) === 'עמודה נמחקה');
ck('a restored column says it was restored', BoardLog.fieldLabel(res) === 'עמודה שוחזרה',
   BoardLog.fieldLabel(res));
ck('...and is not reported as another deletion',
   BoardLog.fieldLabel(res) !== 'עמודה נמחקה');
/* The built-in columns have their own pair of sentences and they are about a
   different thing — taken off the board rather than destroyed. */
ck('a built-in column keeps its own wording',
   BoardLog.fieldLabel({action: 'restore', field: 'builtin_column'}) === 'עמודה הוחזרה ללוח');
/* Three actions now share this field, and the generic fallbacks below would
   answer for two of them: a create would read 'פריט נוצר' and anything else
   'עמודה נמחקה', which on a line that just ADDED a column is the opposite of
   what happened. */
const add = {action: 'create', field: 'column', new: 'תקציב'};
ck('an added column says it was added', BoardLog.fieldLabel(add) === 'עמודה נוספה',
   BoardLog.fieldLabel(add));
ck('...and is not reported as a deletion', BoardLog.fieldLabel(add) !== 'עמודה נמחקה');
ck('...nor as a new item', BoardLog.fieldLabel(add) !== 'פריט נוצר');

// ── the button ────────────────────────────────────────────────────────────
const rowTpl = src.slice(src.indexOf('${a.can_restore_column'), src.indexOf('${a.can_restore_column') + 600);
ck('the button is drawn from the server\'s flag, not guessed from the action',
   /a\.can_restore_column&&isMgr/.test(rowTpl));
ck('and only for a manager', rowTpl.indexOf('isMgr') > -1);
// undo is gated by the server's flag alone, which it sets only for the board's
// admin — the same person undo_activity lets through
ck('an ordinary undoable row still gets its undo button',
   /a\.can_undo\b/.test(rowTpl) && /BoardLog\.undo\(/.test(rowTpl));
// "a manager" is the BOARD's admin, not the account's system role: st.me.role
// showed both buttons to a manager on boards they did not run, and hid them
// from the admin of this one
const lineFn = src.slice(src.indexOf('  lineHTML(a){'), src.indexOf('${a.can_restore_column'));
ck('...and the manager gate is the board admin, not the system role',
   /const isMgr=isBoardAdmin\(\)/.test(lineFn) && !/st\.me\.role/.test(lineFn), lineFn.slice(0, 200));

const fn = src.slice(src.indexOf('async restoreColumn(logId){'),
                     src.indexOf('async restoreColumn(logId){') + 1400);
ck('restoring asks first', /askConfirm\(/.test(fn));
ck('it posts the log line it came from', /columns\/restore/.test(fn) && /log_id:logId/.test(fn));
ck('a 409 is told apart from a refusal', /409/.test(fn) && /404/.test(fn));
ck('the board is re-read, because a column reappearing moves every row',
   /api\('\/api\/boards\/'\+st\.board\.id\)/.test(fn) && /renderView\(\)/.test(fn));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
