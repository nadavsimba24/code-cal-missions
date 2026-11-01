/* Sorting by a column you had to scroll to must leave you where you were.

   renderView remembers the offset and puts it back, and it always had — but
   an offset can only be applied as far as the content allows. Ask for -1800
   while the table is still 600px wide and the browser gives back whatever
   fits and keeps no memory of the rest. A board reaches full width in
   stages (rows, then syncItemColWidth, then fitLinkChipsSoon 60ms later), so
   a single frame of grace lost the difference — in proportion to the
   distance. A column near the right-hand edge needs a small offset and came
   back fine; one you had to scroll to find did not, and the board snapped to
   the right-hand edge. That is the bug, and the clamp is the mechanism.

   This runs the real restore loop out of index.html against a stand-in
   element that clamps exactly the way a browser does and grows late, which
   is the only part a source-reading test could not tell you.

   Driven by tests/test_sort_keeps_scroll.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const from = src.indexOf('const want=()=>{ el.scrollTop=top; el.scrollLeft=left; };');
if (from < 0) throw new Error('the restore loop was not found — has renderView changed?');
/* The LAST of the two — the first is the one inside settle, scheduling its
   own next try, and cutting there would slice the closure in half. */
const END = '};\n    requestAnimationFrame(settle);';
const to = src.indexOf(END, from) + END.length;
if (to < END.length) throw new Error('the restore loop ends somewhere new');
const RESTORE = src.slice(from, to);

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

/* RTL: scrollLeft runs from -(scrollWidth-clientWidth) up to 0, and assigning
   past the end is silently clamped rather than refused. `room` is how far it
   may go right now, and it grows as the table finishes laying itself out. */
function fakeView(room){
  let sl = 0, st = 0;
  return {
    room,
    get scrollLeft(){ return sl; },
    set scrollLeft(v){ sl = Math.max(-this.room, Math.min(0, v)); },
    get scrollTop(){ return st; },
    set scrollTop(v){ st = Math.max(0, v); },
  };
}

function run({wanted, roomAtFirst, roomLater, growsAfter, maxFrames = 40}){
  const el = fakeView(roomAtFirst);
  const queue = [];
  const requestAnimationFrame = fn => queue.push(fn);
  const top = 0, left = wanted;
  new Function('el', 'top', 'left', 'requestAnimationFrame', RESTORE)
    (el, top, left, requestAnimationFrame);
  let frames = 0;
  while (queue.length && frames < maxFrames) {
    if (frames === growsAfter) el.room = roomLater;   // the table finishes widening
    queue.shift()();
    frames++;
  }
  return {landed: el.scrollLeft, frames};
}

// ── the bug, as reported ──────────────────────────────────────────────────
const far = run({wanted: -1800, roomAtFirst: 300, roomLater: 2000, growsAfter: 3});
ck('an offset the table cannot take yet is not lost', far.landed === -1800,
   'landed at ' + far.landed);
ck('...and it is recovered once the columns finish widening', far.frames > 1);

/* The near case always worked, which is why the bug looked like it only hit
   far columns. It must keep working, and without spending frames on it. */
const near = run({wanted: -80, roomAtFirst: 300, roomLater: 2000, growsAfter: 3});
ck('a column near the edge still lands first time', near.landed === -80);
ck('...and costs a single frame', near.frames <= 1, 'frames=' + near.frames);

// ── it has to stop ────────────────────────────────────────────────────────
/* A board that genuinely cannot scroll that far — a column was deleted, the
   window was made wider — must settle, not spin for the life of the page. */
const impossible = run({wanted: -5000, roomAtFirst: 400, roomLater: 400, growsAfter: 99});
ck('an unreachable offset gives up instead of spinning',
   impossible.frames <= 12, 'frames=' + impossible.frames);
ck('and leaves the board as far over as it can actually go',
   impossible.landed === -400, 'landed at ' + impossible.landed);

// ── no scroll to restore is not a reason to do anything ───────────────────
const none = run({wanted: 0, roomAtFirst: 2000, roomLater: 2000, growsAfter: 99});
ck('an unscrolled board stays put', none.landed === 0);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
