/* Sorting by a column you had to scroll to must leave you where you were —
   and must not pass through the right-hand edge on the way back.

   renderView remembers the offset and puts it back, and it always had. The
   trouble is that it is put back into a board that is not yet as wide as the
   one it was taken from: every group is rebuilt, a fresh
   content-visibility:auto element starts SKIPPED, and a board of skipped
   groups measures empty across. Asking for -1800 there is clamped to
   whatever fits and the rest is forgotten — the board paints at the
   right-hand edge, and the loop that recovers it does so over the following
   frames, which are painted too. That is the jump.

   So the board is HELD at the width it had (#view.restoring-x, a zero-height
   block of the old width) until the real columns can carry the offset
   themselves. The offset then applies on the very first try, before anything
   is painted, and the holder is let go the moment it is no longer load-bearing.

   This runs the real restore loop out of index.html against a stand-in
   element that clamps exactly the way a browser does, starts narrow and grows
   late, and honours the holder — which is the only part a source-reading test
   could not tell you.

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
   past the end is silently clamped rather than refused. The content starts
   narrow — the groups have not been found to be on screen yet — and widens
   late. `restoring-x` plus `--restore-x` is the holder, exactly as the CSS
   spends it: a block of that width inside the scroller, so the board can be
   scrolled that far whether or not its own columns are there yet. */
const CLIENT_W = 600;
function fakeView(room){
  let sl = 0, stp = 0;
  const cls = new Set();
  return {
    contentW: CLIENT_W + room,
    holdW: 0,
    clientWidth: CLIENT_W,
    classList: { add: c => cls.add(c), remove: c => cls.delete(c), has: c => cls.has(c) },
    // filled in by `holder` below, which needs the element this is part of
    style: {setProperty(){}, removeProperty(){}},
    get scrollWidth(){ return Math.max(this.contentW, cls.has('restoring-x') ? this.holdW : 0); },
    get room(){ return Math.max(0, this.scrollWidth - this.clientWidth); },
    get held(){ return cls.has('restoring-x'); },
    get scrollLeft(){ return sl; },
    set scrollLeft(v){ sl = Math.max(-this.room, Math.min(0, v)); },
    get scrollTop(){ return stp; },
    set scrollTop(v){ stp = Math.max(0, v); },
  };
}

/* `el.style.setProperty('--restore-x', …)` is how the loop sizes the holder,
   so the stand-in has to answer it the way a style declaration does. */
function holder(el){
  el.style.setProperty = (k, v) => { if (k === '--restore-x') el.holdW = parseFloat(v) || 0; };
  el.style.removeProperty = k => { if (k === '--restore-x') el.holdW = 0; };
  return el;
}

function run({wanted, roomAtFirst, roomLater, growsAfter, wide, maxFrames = 40}){
  const el = holder(fakeView(roomAtFirst));
  const queue = [];
  const requestAnimationFrame = fn => queue.push(fn);
  const top = 0, left = wanted;
  // what #view measured before the rebuild — the width the offset belongs to
  const W = wide === undefined ? CLIENT_W + roomLater : wide;
  new Function('el', 'top', 'left', 'wide', 'requestAnimationFrame', RESTORE)
    (el, top, left, W, requestAnimationFrame);
  const atOnce = el.scrollLeft;          // what the first paint would have shown
  let frames = 0;
  while (queue.length && frames < maxFrames) {
    if (frames === growsAfter) el.contentW = CLIENT_W + roomLater;   // the groups come on screen
    queue.shift()();
    frames++;
  }
  return {landed: el.scrollLeft, frames, atOnce, stillHeld: el.held, holdW: el.holdW};
}

// ── the bug, as reported ──────────────────────────────────────
const far = run({wanted: -1800, roomAtFirst: 0, roomLater: 2000, growsAfter: 3});
ck('an offset the rebuilt board cannot take yet is applied in full anyway',
   far.atOnce === -1800, 'the first paint would have been at ' + far.atOnce);
ck('...so the board is never once painted at the right-hand edge', far.atOnce !== 0);
ck('...and it is still there when the columns arrive', far.landed === -1800,
   'landed at ' + far.landed);
ck('...with the holder let go once they can carry it', !far.stillHeld && far.holdW === 0);

/* The near case always worked, which is why the bug looked like it only hit
   far columns. It must keep working, and without spending frames on it. */
const near = run({wanted: -80, roomAtFirst: 300, roomLater: 2000, growsAfter: 3});
ck('a column near the edge still lands first time', near.landed === -80);
ck('...and costs a single frame', near.frames <= 1, 'frames=' + near.frames);
ck('...and leaves nothing propping the board open', !near.stillHeld);

// ── it has to stop ──────────────────────────────────────────────
/* A board that genuinely cannot scroll that far — a column was deleted, the
   window was made wider — must settle, not spin for the life of the page,
   and must not be left propped open by a holder nothing will ever release. */
const impossible = run({wanted: -5000, roomAtFirst: 400, roomLater: 400, growsAfter: 99,
                        wide: 5600});
ck('an unreachable offset gives up instead of spinning',
   impossible.frames <= 12, 'frames=' + impossible.frames);
ck('and leaves the board as far over as it can actually go',
   impossible.landed === -400, 'landed at ' + impossible.landed);
ck('and takes the holder away with it',
   !impossible.stillHeld && impossible.holdW === 0);

// ── no scroll to restore is not a reason to do anything ───────────────
const none = run({wanted: 0, roomAtFirst: 2000, roomLater: 2000, growsAfter: 99});
ck('an unscrolled board stays put', none.landed === 0);
ck('...and is never held', !none.stillHeld && none.holdW === 0);

// ── the holder is only as wide as the board it is standing in for ──────
/* Over-wide would leave the board scrollable past its own columns for a few
   frames; too narrow and the clamp is back. It is the width #view measured
   a moment ago, which is the width the offset was taken from. */
const held = (() => {
  const el = holder(fakeView(0));
  new Function('el', 'top', 'left', 'wide', 'requestAnimationFrame', RESTORE)
    (el, 0, -1800, 2600, () => {});
  return el.holdW;
})();
ck('the holder stands in at exactly the width the board had', held === 2600, 'holdW=' + held);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
