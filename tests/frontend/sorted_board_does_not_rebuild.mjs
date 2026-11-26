/* Changing a cell on a sorted board rebuilds the board only when it has to.

   refreshRow fell back to a full renderView whenever a sort was active — for
   any change at all. A sort only moves a row when the value it sorts BY is the
   one that changed: sorted by one column and editing another, the row stays
   exactly where it is. Rebuilding anyway threw away every group on the board
   and had them re-measured from their height estimates, which is what flickered
   across the whole screen after every status change.

   Measured on a real board, same session, alternating: the old condition gave
   1 rebuild and a 60px height wobble, the new one 0 and 0, and the old one
   again 1 and 60.
   Driven by tests/test_sorted_board_does_not_rebuild.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(src);
  if (!m) throw new Error('not found: ' + name);
  let d = 0;
  for (let k = src.indexOf('{', m.index); k < src.length; k++){
    if (src[k] === '{') d++;
    else if (src[k] === '}'){ d--; if (!d) return src.slice(m.index, k + 1); }
  }
}

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

const TASK = {id: 7, parent_id: null, group_id: 3};
let rebuilds = 0, patched = 0;
const st = {colSort: null};
const Live = {dropsOutOfView: () => false, patchRow: () => { patched++; return true; }};
const env = {st, Live, findAnyTask: id => (id === 7 ? TASK : null), renderView: () => { rebuilds++; }};
const names = Object.keys(env);
const refreshRow = new Function(...names, grab('refreshRow') + '; return refreshRow;')
  .apply(null, names.map(n => env[n]));

const run = (sort, ...args) => { st.colSort = sort; rebuilds = 0; patched = 0; refreshRow(...args); };

run(null, 7, false, 'col_status');
ck('no sort: the row is patched, the board is not rebuilt', rebuilds === 0 && patched === 1);

run({key: 'title', dir: 'asc'}, 7, false, 'col_status');
ck('sorted by ANOTHER column: still just the row',
   rebuilds === 0 && patched === 1, `rebuilds=${rebuilds}`);

run({key: 'col_status', dir: 'asc'}, 7, false, 'col_status');
ck('sorted BY the column that changed: the row must move, so rebuild',
   rebuilds === 1 && patched === 0, `rebuilds=${rebuilds}`);

run({key: 'title', dir: 'asc'}, 7, false);
ck('a caller that does not say what changed keeps the old behaviour',
   rebuilds === 1, 'the relaxation must not apply on a guess');

// ── the paths that have always needed the whole board ──────────────────────
run(null, 7, true, 'col_status');
ck('forceWhole still rebuilds', rebuilds === 1);
run(null, 999, false, 'col_status');
ck('an item that is not on the board rebuilds', rebuilds === 1);

Live.dropsOutOfView = () => true;
run(null, 7, false, 'col_status');
ck('a row the filter now excludes rebuilds — it has to leave', rebuilds === 1);
Live.dropsOutOfView = () => false;

Live.patchRow = () => { patched++; return false; };
run(null, 7, false, 'col_status');
ck('and a patch that could not be applied falls back to the rebuild',
   rebuilds === 1 && patched === 1);
Live.patchRow = () => { patched++; return true; };

// ── the callers have to say what changed, or none of this takes effect ─────
/* line-based: one call carries a nested `!!(...)`, so stopping at the first
   closing paren truncates it */
const callLines = src.split('\n')
  .filter(l => /\brefreshRow\(/.test(l) && !/function refreshRow/.test(l))
  .map(l => l.trim());
/* The count is deliberately a thing somebody has to come here and change: a
   new caller that forgets its third argument silently rebuilds the whole board
   on every edit, which is the flicker this file exists to keep out. The fourth
   is the conversion resolver — it answers one exception at a time, and without
   it every press repainted the board behind the dialog and lost its scroll.
   Five more came from cells that used to rebuild the board for one value — an
   assignee, a star rating, a file added or removed, a link — which on a heavy
   board was a flash and a jump back to the start after each of them. The
   tenth is setCell itself, redrawing the row when a rule wrote another of its
   columns in the same request (see applyWriteEcho) — it names the column. */
ck('there are ten callers and no more', callLines.length === 10, JSON.stringify(callLines));
ck('every one of them names the field or column that changed',
   callLines.every(l => /refreshRow\([^;]*,[^;]*,[^;]*\)/.test(l)),
   JSON.stringify(callLines));
ck('...and the status cell is one of them',
   /refreshRow\(taskId,false,colId\)/.test(src));
ck('...as is the built-in field path',
   /refreshRow\(id, _wholeView \|\| [^,]+, field\)/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
