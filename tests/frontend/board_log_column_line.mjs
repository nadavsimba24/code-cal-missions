/* A deleted column in the board log is a line about the BOARD.

   Every other line in this log is about an item: it opens with the item's
   name as a button, and pressing it opens that item. A column deletion has no
   item behind it — it happened to the board, and took a field off every item
   at once — so the server sends it with task_id null and the board's name in
   task_title. Drawn with the same button, the line would offer to open an
   item that does not exist, and the row's own words ("נמחק") would read as a
   deleted ITEM under a title that is really a board.

   So two things are pinned here: the row draws a button only when there is
   something to open, and fieldLabel says which kind of thing was deleted
   BEFORE the generic 'נמחק' can answer for it.

   Runs the real BoardLog.fieldLabel / fieldIcon out of index.html.
   Driven by tests/test_board_log_column_line.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

/* Same trick as log_checkbox_reads_as_a_tick.mjs: brace counting does not
   survive this file, and these methods are two spaces inside an object
   literal, so the close is the first line that begins one. */
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

const BoardLog = new Function('customColumns', 'Chat',
  `return { ${['fieldLabel(a){', 'fieldIcon(a){'].map(grabMethod).join(',\n')} };`
)(() => [], {fieldHe: () => ''});

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

// ── what the line says ─────────────────────────────────────────────────────
const col = {action: 'delete', field: 'column', old: 'תקציב'};
ck('a deleted column says it was a column', BoardLog.fieldLabel(col) === 'עמודה נמחקה',
   BoardLog.fieldLabel(col));
ck('...and not the bare "נמחק" that means a deleted item',
   BoardLog.fieldLabel(col) !== 'נמחק');
ck('a deleted ITEM still says what it always said',
   BoardLog.fieldLabel({action: 'delete', field: 'item'}) === 'נמחק');

/* A built-in column is a column of the item and cannot truly be dropped — the
   "..." menu calls it מחק עמודה, and what it does is take it off the board. */
const bi = {action: 'delete', field: 'builtin_column', old: 'תאריך יעד'};
ck('a built-in column was removed from the board, not destroyed',
   BoardLog.fieldLabel(bi) === 'עמודה הוסרה מהלוח', BoardLog.fieldLabel(bi));
ck('and bringing it back says so rather than reading as a restored item',
   BoardLog.fieldLabel({...bi, action: 'restore'}) === 'עמודה הוחזרה ללוח',
   BoardLog.fieldLabel({...bi, action: 'restore'}));
ck('a restored ITEM still says what it always said',
   BoardLog.fieldLabel({action: 'restore', field: 'item'}) === 'שוחזר');

// ── and the icon agrees with the word, the way the menu's own does ─────────
ck('a deleted column carries the trash can', BoardLog.fieldIcon(col) === 'fa-trash');
ck('a restored one carries the way back',
   BoardLog.fieldIcon({...bi, action: 'restore'}) === 'fa-rotate-left');

// ── nothing to open, so nothing to press ───────────────────────────────────
ck('the row draws the item button only when there is an item',
   /\$\{a\.task_id\s*\n?\s*\?\s*`<button class="lg-item"/.test(src));
ck('and a board line instead, which is not a button',
   /<span class="lg-item lg-board"/.test(src));
const board = /\.lg-board\{[^}]*\}/.exec(src);
ck('drawn as text and not as something to press', !!board && /cursor:default/.test(board[0]),
   board && board[0]);
const hov = /\.lg-board:hover\{[^}]*\}/.exec(src);
ck('with no link underline waiting under the mouse',
   !!hov && /text-decoration:none/.test(hov[0]), hov && hov[0]);
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
