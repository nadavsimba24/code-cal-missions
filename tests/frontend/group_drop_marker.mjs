/* A group in the air says where it is going to land.

   Sortable leaves the dragged group in the list as its own placeholder, so the
   landing slot is already the right shape and in the right place and follows
   the pointer as it changes its mind. All it wore was a fade, which against a
   board of groups is easy to miss — and on a folded board, where a group is a
   name and nothing more, there is barely anything there to fade. The slot is
   marked now: a dashed primary outline on a soft tint, the frame that "+ הוסף
   קבוצה" already wears on this board, with the group's own content faded inside
   it so you can still read which group is being placed and between what.

   Two of the rules it has to win to be seen at all — the blanket fade every
   Sortable placeholder gets, and the lift that belongs to the copy following
   the cursor — are asserted here, because losing either puts the marking back
   to what it was without anything failing.
   Driven by tests/test_group_drop_marker.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };
const rule = re => { const m=re.exec(src); return m?m[0]:null; };

// ── the slot ───────────────────────────────────────────────────────────────
const slot = rule(/\.group\.sortable-ghost\{[^}]*\}/);
ck('the placeholder has a rule of its own', !!slot);
ck('it is outlined, and dashed the way an empty slot is on this board',
   !!slot && /outline:2px dashed var\(--primary\)/.test(slot), slot);
ck('and tinted, so the slot reads as a place and not as a faint group',
   !!slot && /background:var\(--primary-soft\)/.test(slot), slot);
ck('the content inside it is what fades, not the marking',
   /\.group\.sortable-ghost>\*\{opacity:\.35\}/.test(src));
/* the header carries --bg so a sticky group name never shows rows through it.
   Left on the placeholder it paints over the tint — and a collapsed group is
   nothing but its header, so it would paint over all of it. */
ck('the header stops painting its own background over the tint',
   /\.group\.sortable-ghost \.group-head\{background:transparent\}/.test(src));

// ── the two rules it has to beat ───────────────────────────────────────────
const blanket = rule(/(?:^|\})\.sortable-ghost\{[^}]*\}/m);
ck('every Sortable placeholder still fades by default — kanban, sidebar, forms',
   !!blanket && /opacity:\.4/.test(blanket), blanket);
ck('but a group placeholder does not, or the marking would be 40% of itself',
   !!slot && /opacity:1/.test(slot), slot);

const chosen = /\.group\.drag-chosen\{[^}]*\}/.exec(src);
ck('the lifted look still exists for the copy that follows the cursor',
   !!chosen && /box-shadow:var\(--shadow\)/.test(chosen[0]));
ck('and the slot left behind does not wear it too',
   !!slot && /box-shadow:none/.test(slot), slot);
/* .group.drag-chosen and .group.sortable-ghost weigh exactly the same, so which
   box-shadow applies is decided by which is written last. The placeholder wears
   both classes at once, so this is the whole of why the slot is flat. */
ck('which only holds while the slot rule is written after the lifted one',
   !!chosen && src.indexOf(slot) > chosen.index,
   'chosen at '+(chosen&&chosen.index)+', slot at '+src.indexOf(slot));

// ── and the drag still hands out those two classes ─────────────────────────
const grp = (()=>{ const j=src.indexOf("new Sortable(el,{handle:'.g-handle'"); let d=0;
  for(let k=src.indexOf('{',j);k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){d--; if(!d)return src.slice(j,k+1);} } })();
ck('the group left in the list is the one marked as the slot',
   /ghostClass:'sortable-ghost'/.test(grp));
ck('and the copy following the cursor is a different class, so it stays a group',
   /dragClass:'sortable-drag'/.test(grp) && /chosenClass:'drag-chosen'/.test(grp));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
