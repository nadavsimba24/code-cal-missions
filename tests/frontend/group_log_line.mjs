/* A group in the log: created, deleted, and an item that moved between two.

   Three events share one field name and must not share one sentence. A group
   created or deleted happened to the BOARD — the row carries the board's name
   where an item's name would be, so the generic 'נמחק' would read there as a
   deleted item, exactly the trap the column work found. An 'update' on the
   same field is the opposite kind of thing: an ITEM moved, and the line wants
   the ordinary old → new pills with the two group names in them.

   Runs the real BoardLog.fieldLabel and Chat.fieldHe out of index.html.
   Driven by tests/test_board_log_records_groups.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

/* Brace counting does not survive this file; these methods sit two spaces
   inside an object literal, so the close is the first line that begins one. */
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

const Chat = new Function('customColumns',
  `return { ${grabMethod('fieldHe(f){')} };`)(() => []);
const BoardLog = new Function('customColumns', 'Chat',
  `return { ${grabMethod('fieldLabel(a){')} };`)(() => [], Chat);

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

// ── the board's own events ────────────────────────────────────────────────
const made = {action: 'create', field: 'group', new: 'תכנון'};
const gone = {action: 'delete', field: 'group', old: 'תכנון'};
ck('a new group says a group was created', BoardLog.fieldLabel(made) === 'קבוצה נוצרה',
   BoardLog.fieldLabel(made));
ck('a deleted group says a group was deleted', BoardLog.fieldLabel(gone) === 'קבוצה נמחקה',
   BoardLog.fieldLabel(gone));
ck('...and not the bare "נמחק", which on a board line reads as a deleted item',
   BoardLog.fieldLabel(gone) !== 'נמחק');
ck('...nor "פריט נוצר", which is what a create used to fall through to',
   BoardLog.fieldLabel(made) !== 'פריט נוצר');

// ── the item's event, which is a different sentence on the same field ─────
const moved = {action: 'update', field: 'group', old: 'תכנון', new: 'בביצוע'};
ck('an item that moved is labelled by the field, not by the board wording',
   BoardLog.fieldLabel(moved) === 'קבוצה', BoardLog.fieldLabel(moved));
ck('it is not mistaken for a group that was created or deleted',
   !['קבוצה נוצרה', 'קבוצה נמחקה'].includes(BoardLog.fieldLabel(moved)));
ck('the item log names the field too, so its sentence is not the raw key',
   Chat.fieldHe('group') === 'קבוצה', Chat.fieldHe('group'));

// ── nothing else moved ────────────────────────────────────────────────────
ck('a deleted ITEM still says what it always said',
   BoardLog.fieldLabel({action: 'delete', field: 'item'}) === 'נמחק');
ck('a deleted column still says what the column work made it say',
   BoardLog.fieldLabel({action: 'delete', field: 'column', old: 'תקציב'}) === 'עמודה נמחקה');
ck('the other field names are untouched', Chat.fieldHe('status') === 'סטטוס'
   && Chat.fieldHe('title') === 'כותרת' && Chat.fieldHe('due_date') === 'תאריך יעד');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
