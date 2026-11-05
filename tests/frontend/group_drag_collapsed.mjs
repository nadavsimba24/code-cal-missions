/* A folded board can still be put in order.

   A group in its collapsed state is a name and nothing else — some 28px of
   header — and the gap that separates it from the next group was margin.
   Margin belongs to no element, so a pointer in it hit-tests to the board
   rather than to a group, and Sortable, asked what the row is being dragged
   over, is told "nothing". With almost half of every slot answering that way, a
   drag down a folded board responds in stripes: it jumps at the names and goes
   dead in between, which is what "you cannot reorder collapsed groups" looks
   like from the outside.

   Padding is the same spacing on screen and part of the group's own box, so the
   slot answers to the pointer along its whole height. Only collapsed groups are
   changed: an expanded group's gap sits under a tall table, not in the middle
   of the list, and there is nothing there for a pointer to fall through.
   Driven by tests/test_group_drag_collapsed.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

const rule = re => { const m=re.exec(src); return m?m[0]:null; };

// ── the gap under a collapsed group belongs to the group ───────────────────
const collapsed = rule(/\.group:has\(>\.grp-stick>\.group-head\.collapsed\)\{[^}]*\}/);
ck('a collapsed group has a rule of its own', !!collapsed);
ck('and the gap under it is padding — inside the box the pointer can hit',
   !!collapsed && /padding-bottom:\d+px/.test(collapsed), collapsed);
ck('with the margin that used to hold that space taken back off',
   !!collapsed && /margin-bottom:0/.test(collapsed), collapsed);

/* The two together are what keeps the board looking identical: the margin an
   expanded group spaces itself with, traded for the same number of pixels of
   padding, so nothing on screen moves when a group folds. The number itself is
   a design decision and has changed since — what is pinned here is that the two
   stay equal, not which value they settled on. */
const gap = s => { const m=/(\d+)px/.exec(s||''); return m?+m[1]:null; };
const base = rule(/\.group\{[^}]*\}/);
ck('an expanded group still spaces itself with margin, untouched',
   !!base && /margin-bottom:\d+px/.test(base) && !/padding-bottom/.test(base), base);
ck('and the space taken is the same either way, so the board does not shift',
   gap(base)===gap(collapsed), base+' vs '+collapsed);

/* the class is put on and taken off by the caret without a re-render, and :has
   follows it live — which is the whole reason the rule keys on the header's
   class rather than on something rendered into the group once */
ck('the collapsed state is a class on the header, which :has can follow',
   /head\.classList\.toggle\('collapsed',shut\)/.test(src));
ck('and it is written into the markup too, so a re-render keeps the hit area',
   /class="group-head\$\{shut\?' collapsed':''\}"/.test(src));

// ── and the drag itself is still wired the way it was ──────────────────────
const grp = (()=>{ const j=src.indexOf("sortableOn(el,{handle:'.g-handle'"); let d=0;
  for(let k=src.indexOf('{',j);k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){d--; if(!d)return src.slice(j,k+1);} } })();
ck('a group is still dragged by its grip or its name',
   /handle:'\.g-handle'/.test(grp) && /draggable:'\.group'/.test(grp));
/* Both are written conditionally now — a narrowed board does not draw all of
   its groups, so it does not offer to reorder the ones it does draw (see
   filter_hides_empty_groups) — but when they ARE drawn they are drawn in the
   header, which is the whole of what a collapsed group shows. */
ck('and both of those sit in the header, which is all a collapsed group shows',
   /<i class="fa-solid fa-grip-vertical g-drag g-handle"/.test(src)
   && /class="g-name\$\{mayDrag\?' g-handle':''\}"/.test(src));
ck('collapsing is still the caret alone, so grabbing a name never folds a group',
   /if\(!e\.target\.closest\('\.caret'\)\)return;/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
