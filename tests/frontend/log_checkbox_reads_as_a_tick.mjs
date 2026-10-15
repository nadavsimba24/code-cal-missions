/* A checkbox change in the activity log reads as a tick, not as "true".

   A checkbox column stores `true` when it is ticked and `null` when it is not,
   and the log printed those straight through: ticking a box read "— ← true" —
   the English word for a value, and an em-dash that everywhere else in this log
   means "nothing at all" standing in for a box somebody deliberately cleared.
   A checkbox has two states and no empty one, so both of them say what they are,
   and the board log draws the tick on whichever side is ticked, in the same
   green the cell itself uses.

   Runs the real _checkState / transVal / BoardLog.pill out of index.html.
   Driven by tests/test_log_checkbox_reads_as_a_tick.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

/* Counting braces does not survive this file: _decode holds the regex
   /^\s*[\[{"]/, whose `{` is inside a character class, and a counter walks
   straight past the end of the method. These methods are all indented two
   spaces inside their object literal, so the close is the first line that
   begins one. */
function grabMethod(header){
  const i = src.indexOf(header);
  if (i < 0) throw new Error('not found: ' + header);
  const nl = src.indexOf('\n', i);
  const first = src.slice(i, nl);
  const n = t => (first.match(t) || []).length;
  if (n(/\{/g) === n(/\}/g)) return first.replace(/,\s*$/, '');   // a one-liner
  const end = src.indexOf('\n  }', nl);
  if (end < 0) throw new Error('no close found for ' + header);
  return src.slice(i, end + 4);
}

const COLS = [{id: 'c_box', type: 'checkbox', title: 'האם נשמר'},
              {id: 'c_txt', type: 'text', title: 'הערה'}];
const mk = (names, extra) => new Function('customColumns', 'esc', 'Chat',
  `return { ${names.map(grabMethod).join(',\n')} ${extra || ''} };`
)(() => COLS, x => String(x == null ? '' : x), null);

const Chat = mk(['_decode(v){', '_checkState(f,v){', 'transVal(f,v){', 'short(v){']);
// the board log's pill calls back into Chat
const BoardLog = new Function('esc', 'Chat', `return { ${grabMethod('pill(field,v){')} };`)(
  x => String(x == null ? '' : x), Chat);

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

// ── the words ──────────────────────────────────────────────────────────────
ck('a ticked box says it is ticked', Chat.transVal('col:c_box', 'true') === 'מסומן',
   Chat.transVal('col:c_box', 'true'));
ck('...and never the word "true"', !/true/i.test(Chat.transVal('col:c_box', 'true')));
ck('an unticked box says so, instead of the em-dash that means "no value"',
   Chat.transVal('col:c_box', 'null') === 'לא מסומן', Chat.transVal('col:c_box', 'null'));
ck('a box that never held a value reads the same — for a checkbox they are one state',
   Chat.transVal('col:c_box', null) === 'לא מסומן', String(Chat.transVal('col:c_box', null)));
ck('an explicit false is unticked too', Chat.transVal('col:c_box', 'false') === 'לא מסומן');

// ── the drawing ────────────────────────────────────────────────────────────
const on = BoardLog.pill('col:c_box', 'true'), off = BoardLog.pill('col:c_box', 'null');
ck('the ticked pill carries a tick', /fa-square-check/.test(on), on);
ck('...in the green the cell itself uses', /var\(--green\)/.test(on), on);
ck('the unticked pill carries an empty box, not a tick',
   /fa-square(?!-check)/.test(off) && !/fa-square-check/.test(off), off);
ck('both still say which state they are, so the row reads without the icon font',
   on.includes('מסומן') && off.includes('לא מסומן'));

// ── and nothing else changed ───────────────────────────────────────────────
ck('a text column is untouched', Chat.transVal('col:c_txt', '"שלום"') === 'שלום',
   Chat.transVal('col:c_txt', '"שלום"'));
ck('an empty text column still reads as "no value"',
   Chat.transVal('col:c_txt', 'null') === '—');
ck('a column this board does not know falls through unchanged',
   Chat.transVal('col:gone', 'true') === 'true');
ck('a built-in field is not mistaken for a column',
   Chat._checkState('status', 'done') === null);
ck('the pill for anything else is still escaped text',
   BoardLog.pill('col:c_txt', '"שלום"') === 'שלום');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
