/* A group can be added from the top of the board, not only from the foot of it.

   "+ הוסף קבוצה" lived at the very bottom of the board, past every row of it.
   On a board of any size the way to add a shelf was a scroll away from the
   board's own actions — and the group it made then appeared down there too,
   away from where the eye was.

   The way in is now the caret on "פריט חדש": the same two-door shape the filter
   beside it already wears — the button goes on doing what it says, the caret
   drops the one thing it does not, הוספת קבוצה — and a group made from there
   lands at the TOP of the board.

   Four things have to stay true:

   * the button still makes an item on its own. The caret is a second door, not
     a replacement for the first one;
   * the caret is not offered to somebody who cannot add a group — an editor.
     A narrowed board is NOT one of those cases, and that is the point of this
     line: the caret used to go when a filter went on, and a caret that comes
     and goes reads as the button having turned back into the old one rather
     than as a filter being on. A group born empty is still not drawable on a
     narrowed board, which is why addGroup clears the cut on its way out
     instead — and why the button at the FOOT of the board, which is drawn
     among the groups, still goes with them;
   * position 0 is not enough to BE first. Every other group goes on claiming
     the position it had, so the order is stated in full afterwards;
   * the button at the foot of the board is untouched — it is still the way in
     for somebody already down there.

   Driven by tests/test_add_group_from_the_toolbar.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── the control: one button, two doors ─────────────────────────────────────
const ctl = /<div class="tb-ctl" id="ctl-new">([\s\S]*?id="pop-new"><\/div>)/.exec(src);
ck('the new-item button is a control with a popup of its own', !!ctl);
const inside = ctl ? ctl[1] : '';
ck('…and the button itself still makes an item, unasked',
   /<button class="btn btn-primary" onclick="openNewItem\(\)"/.test(inside), inside.slice(0,90));
ck('…with the caret as the second door, beside it and after it',
   /class="btn btn-primary tb-caret-pri"/.test(inside)
   && inside.indexOf('openNewItem()') < inside.indexOf('tb-caret-pri'));
ck('the caret opens the menu rather than doing anything by itself',
   /tb-caret-pri[\s\S]{0,260}?onclick="togglePop\('new'\)"/.test(inside), inside);
ck('…and says what it is to a screen reader',
   /aria-label="[^"]+"/.test(inside) && /aria-haspopup="true"/.test(inside));
ck('the popup is the one the control carries', /<div class="tb-pop" id="pop-new">/.test(inside));
/* the halves are framed together, and the popup is NOT inside that frame: the
   frame clips what is in it, and a dropdown clipped to the height of a button
   is a menu that opens into nothing */
ck('…and the two halves are framed together, with the popup outside the frame',
   /<div id="new-split">[\s\S]*?openNewItem\(\)[\s\S]*?tb-caret-pri[\s\S]*?<\/div>/.test(inside)
   && inside.indexOf('id="pop-new"') > inside.indexOf('</div>'), inside);
ck('the caret wears a chevron', /fa-chevron-down/.test(inside));

// ── it is still the first thing on the strip ───────────────────────────────
const tb = /<div id="toolbar">([\s\S]*?)\n    <\/div>/.exec(src);
const order = ['openNewItem()','tb-search','ctl-arrange'].map(k => tb ? tb[1].indexOf(k) : -1);
ck('making an item is still the first thing on the action strip',
   order.every(i=>i>=0) && order.every((v,i)=>i===0||v>order[i-1]), String(order));

// ── the menu ───────────────────────────────────────────────────────────────
const pop = /if\(name==='new'\)\{([\s\S]*?)\n  \}/.exec(src);
ck('the menu has contents', !!pop);
const menu = pop ? pop[1] : '';
ck('הוספת קבוצה is in it', /הוספת קבוצה/.test(menu));
/* And it is the only thing in it. The menu used to open with the item, which
   is what the button the caret hangs off already does — a second copy of the
   first half of the same control, one click further in. The caret is for what
   the button cannot do.

   Read off what is RENDERED and not off the whole branch: the comment above
   the call is free to name the row that was taken out, and saying so must not
   read as the row still being there. */
const drawn = (/setHTML\(el,([\s\S]*?)\);/.exec(menu) || ['', ''])[1];
ck('…and it is the only row: the item is the button, not a menu entry',
   !!drawn && !/הוספת פריט/.test(drawn) && !/openNewItem\(\)/.test(drawn), drawn);
ck('the group row asks for one at the top of the board',
   /onclick="closePops\(\);addGroup\(true\)"/.test(menu));
ck('the group row is only there where a group can be added',
   /canAddGroupHere\(\)\s*\?/.test(menu), menu);

// ── and the caret itself goes when there is nothing to drop ────────────────
const canAdd = grab('canAddGroupHere');
ck('"can a group be added here" is the role, and only the role',
   /isBoardAdmin\(\)/.test(canAdd) && !/boardIsNarrowed/.test(canAdd), canAdd);
const refresh = grab('refreshToolbar');
ck('the toolbar settles the caret on every redraw of itself',
   /ctl-new[\s\S]{0,120}?no-caret',!canAddGroupHere\(\)/.test(refresh), refresh);
ck('…and a control with no caret is a button again, with its padding back',
   /#ctl-new\.no-caret \.tb-caret-pri\{display:none\}/.test(src)
   && /#ctl-new\.no-caret \.btn-primary\{padding-inline-end:/.test(src));

// ── one button, not two glued together ────────────────────────────────────
/* Two elements, because the halves do two different things — and nothing on
   screen may give that away. Each of these is a place the seam showed.

   The radius belongs to the FRAME and to nothing else. Squaring each half's
   inner corners instead means naming which corner faces the seam, which is a
   question about the inline direction — and it came back the wrong way round,
   putting the square corners on the outside of the control. A frame that clips
   cannot get that wrong, so nothing here may put a radius back on a half. */
const ctlCss = (src.match(/#(?:ctl-)?new-?split?[^{]*\{[^}]*\}|#ctl-new[^{]*\{[^}]*\}/g)||[]).join('');
ck('the halves touch rather than standing apart',
   /#new-split\{[^}]*display:inline-flex/.test(src) && !/#new-split\{[^}]*gap:/.test(src));
ck('…and one frame rounds them both, by clipping them to its own corners',
   /#new-split\{[^}]*border-radius:8px/.test(src) && /#new-split\{[^}]*overflow:hidden/.test(src));
ck('…so neither half carries a corner of its own',
   /#new-split>\.btn-primary\{border-radius:0/.test(src)
   && !/radius:8px/.test(ctlCss.replace(/#new-split\{[^}]*\}/,'')), ctlCss);
ck('…with no rule drawn down the middle of it',
   !/border-inline-start:/.test(ctlCss), ctlCss);
ck('…one shadow for the whole control, not one per half',
   /#new-split\{[^}]*box-shadow:/.test(ctlCss)
   && /#new-split>\.btn-primary\{[^}]*box-shadow:none/.test(ctlCss), ctlCss);
/* the one that turns a single button back into two the moment it is missing:
   without it the pointer colours the half it is over and nothing else */
ck('…and a hover anywhere on it lights all of it',
   /#new-split:hover>\.btn-primary\{background:var\(--primary-hover\)\}/.test(ctlCss), ctlCss);
/* a frame that clips cuts off an outline drawn outside it — the ring goes in */
ck('…and the keyboard ring is drawn inside the frame, where it survives the clip',
   /#new-split>\.btn-primary:focus-visible\{outline:[^}]*outline-offset:-\d/.test(ctlCss), ctlCss);
/* logical properties — the strip is read right-to-left */
ck('…and padded in logical directions',
   !/padding-right|padding-left/.test(ctlCss)
   && /padding-inline-end/.test(ctlCss) && /padding-inline:/.test(ctlCss));

// ── a phone: the strip scrolls, so the menu cannot hang inside it ──────────
const mob = src.slice(src.indexOf('.tab-dd{display:flex'));
ck('on a phone the menu is a bottom sheet, out of the scrolling strip',
   /#pop-new\{position:fixed/.test(mob) && /#pop-new\{[^}]*bottom:0/.test(mob));

// ── what addGroup does with "at the top" ───────────────────────────────────
const fn = grab('addGroup');
ck('addGroup is told where the group goes', /^async function addGroup\(atTop\)/.test(fn));
ck('the role is still checked first, ahead of anything sent',
   fn.indexOf('isBoardAdmin()') < fn.indexOf("api('/api/groups'"));
ck('a group asked for at the top is asked for at position 0',
   /if\(atTop\)body\.position=0;/.test(fn), fn);
ck('the order as it stands is read before the group is made',
   fn.indexOf('const was=') < fn.indexOf("api('/api/groups'"));
ck('…and stated in full afterwards, because position 0 alone ties with the first group',
   /const order=\[made\.id\]\.concat\(was\)/.test(fn)
   && /api\('\/api\/groups\/reorder'/.test(fn), fn);
ck('the board on screen is moved too, not left waiting for the reload',
   /order\.forEach\(\(id,i\)=>\{const g=\(st\.board\.groups\|\|\[\]\)\.find\(x=>x\.id===id\); if\(g\)g\.position=i;\}\)/.test(fn), fn);
ck('"added, but not at the top" is said as itself, not as a failure to add',
   /said='הקבוצה נוספה, אך לא בראש הלוח'/.test(fn), fn);
/* the group exists by the time the reorder goes out, so a reorder that fails
   must not be reported as "the group was not created" — its own catch */
const tail = fn.slice(fn.indexOf('const order='));
ck('…and the reorder answers for itself, so a group that exists is not reported as a failure',
   /try\{[\s\S]*?api\('\/api\/groups\/reorder'[\s\S]*?\}catch\(e\)\{ said=/.test(tail), tail);
ck('a board with no groups yet needs no reordering',
   /if\(atTop&&made&&made\.id&&was\.length\)/.test(fn), fn);
ck('a plain addGroup() still appends, as the foot of the board always did',
   !/body\.position/.test(fn.slice(0, fn.indexOf('if(atTop)'))), fn);
/* the other half of letting the caret stay while the board is narrowed: the
   group is made, the cut goes, and the clearing is said rather than silently
   happening under her */
ck('a group added on a narrowed board clears the cut, and says so',
   /boardIsNarrowed\(\)[\s\S]{0,80}said='קבוצה נוספה, הסינון נוקה'/.test(fn), fn);
ck('…and the board is reopened afterwards, which is what resets the filters',
   fn.indexOf('openBoard(st.board.id)') > fn.indexOf('boardIsNarrowed()'), fn);

// ── a role that changes under an open board brings the caret back ─────────
const reval = grab('revalidateBoard');
ck('a revalidate that found a change settles the toolbar before the rows',
   /refreshToolbar\(\);[\s\S]{0,80}renderView\(\)/.test(reval), reval);

// ── the foot of the board is untouched ────────────────────────────────────
ck('"+ הוסף קבוצה" is still at the foot of the board',
   (src.match(/add-group-btn"/g)||[]).length===1
   && /onclick="addGroup\(\)"/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
