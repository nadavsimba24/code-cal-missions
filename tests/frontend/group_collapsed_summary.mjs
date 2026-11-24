/* A collapsed group says how much work it is hiding. Runs the real
   groupSummaryHTML out of index.html, and checks that the header can actually
   show it — collapsing toggles classes rather than re-rendering, so the line
   has to be in the DOM already and chosen by CSS.
   Driven by tests/test_group_collapsed_summary.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

/* The signature is matched loosely on purpose. It gained a second parameter —
   the group's own size as the server counted it — and the extractor pinned to
   `(tasks)` stopped matching, which threw before a single check ran: a harness
   that cannot find the function reports the same way as one whose every
   assertion failed. What this file is about is what the line SAYS, so it takes
   the function however it is declared. */
const m = /function groupSummaryHTML\(tasks[^)]*\)\{[\s\S]*?\n\}/.exec(src);
if(!m) throw new Error('groupSummaryHTML is gone');
/* `partial` stands in for boardRowsPartial() — whether rows are still arriving
   — and esc() for the app's own escaper: the item number now comes off the
   wire, so the function escapes it rather than interpolating it raw. Neither
   is in scope inside new Function, and an undefined esc would throw on every
   call. */
let partial = false;
const sum = new Function('esc','boardRowsPartial', m[0]+'; return groupSummaryHTML;')(
  s=>String(s), ()=>partial);
const text = (t,known) => sum(t,known).replace(/<[^>]*>/g,'').trim();

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

const t=n=>Array.from({length:n},()=>({subtasks:[]}));
const withSubs=(n,total)=>{const a=t(n); if(a.length) a[0].subtasks=Array.from({length:total}); return a;};

ck('both numbers, as the design asks', text(withSubs(83,10))==='83 פריטים / 10 תתי־פריטים', text(withSubs(83,10)));
ck('a group with no sub-items still shows the zero',
   text(t(3))==='3 פריטים / 0 תתי־פריטים', text(t(3)));
ck('one item is not "1 פריטים"', text(t(1))==='1 פריט / 0 תתי־פריטים', text(t(1)));
ck('one sub-item is not "1 תתי־פריטים"', text(withSubs(2,1))==='2 פריטים / 1 תת־פריט', text(withSubs(2,1)));
ck('an empty group says so in the same shape', text([])==='0 פריטים / 0 תתי־פריטים', text([]));
ck('the number leads either way, so a column of these lines stays a column',
   [text([]),text(t(1)),text(withSubs(83,10))].every(x=>/^\d/.test(x)));
ck('sub-items are summed across every item, not just the first',
   text([{subtasks:[1,2]},{subtasks:[3]},{subtasks:[]}])==='3 פריטים / 3 תתי־פריטים',
   text([{subtasks:[1,2]},{subtasks:[3]},{subtasks:[]}]));
ck('a task without the key at all does not throw',
   text([{},{subtasks:[1]}])==='2 פריטים / 1 תת־פריט', text([{},{subtasks:[1]}]));

/* the header has to carry both spellings at once: collapsing only toggles a
   class, so anything rendered per-state would freeze at whatever it was */
ck('the line sits in the same column as the name, under it',
   (src.match(/<span class="g-nm">/g)||[]).length>=2 &&
   /\.group-head \.g-nm\{display:inline-flex;flex-direction:column/.test(src),
   'trailing off the end of the name is the layout this replaced');
ck('...on the "ללא קבוצה" header too', (src.match(/\$\{sum\}<\/span>/g)||[]).length>=2);
ck('CSS hides it while the group is open', /\.group-head \.g-sum\{display:none/.test(src));
ck('...and shows it, instead of the bare count, when collapsed',
   /\.group-head\.collapsed \.g-count\{display:none\}/.test(src) &&
   /\.group-head\.collapsed \.g-sum\{display:block\}/.test(src));
ck('the Hebrew line is left to the page direction, not pinned to LTR',
   !/\.group-head \.g-sum\{[^}]*direction:ltr/.test(src.replace(/\n\s*/g,'')),
   'direction:ltr would put the sub-item half first in an RTL header');
ck('a two-line header does not sit centred on its first line',
   /\.group-head\.collapsed\{align-items:flex-start/.test(src));
ck('the collapse handler still only toggles classes (so CSS is what must switch it)',
   /head\.classList\.toggle\('collapsed',shut\)/.test(src) &&
   !/renderView\(\)/.test(/function foldGroup\(head,shut\)\{[\s\S]*?\n\}/.exec(src)[0]));
ck('it is counted off the tasks the group draws, so filters apply',
   /groupSummaryHTML\(g\.tasks\b/.test(src),
   'the summary no longer reads the rows this group is drawing');

// ── the number, once the board stopped sending all its rows ──────────────
/* Past the paging threshold the rows arrive fifty at a time, so counting them
   made a collapsed group on a 21,187-item board read "0 פריטים" — the same
   untruth as an empty board, only small enough to be believed. The board now
   sends each group's size, counted in the database through the same
   permission filter as its own total, and that number is what the line
   states. It is passed in rather than looked up here so that the open header
   and the folded line cannot show two different sizes of one group. */
partial = true;
ck('a group on a paged board states the size the server counted, not the rows in hand',
   text(withSubs(2,1),1033).startsWith('1033 פריטים'), text(withSubs(2,1),1033));
/* The sub-item half is counted off the rows on screen and nothing on the wire
   says how many there really are. Printed beside an item count that IS the
   group's own, "1033 פריטים / 0 תתי־פריטים" reads as one statement and asserts
   something nobody on that screen knows. One true number beats two numbers
   where one of them is a fragment. */
ck('...and says nothing about sub-items while the rows it would count are still arriving',
   !/תת/.test(text(withSubs(2,1),1033)), text(withSubs(2,1),1033));
ck('...and does not then hedge the number it is sure of',
   !/נטענו/.test(text(withSubs(2,1),1033)), text(withSubs(2,1),1033));
/* and the board that sends no count of its own is still honest about it: the
   rows in hand, said to be the rows in hand */
ck('a paged board with no count from the server marks its numbers as what has arrived',
   text(t(2))==='2 פריטים / 0 תתי־פריטים · נטענו עד כה', text(t(2)));
partial = false;

ck('a board holding all its rows keeps both halves, both of them complete',
   text(withSubs(3,2),3)==='3 פריטים / 2 תתי־פריטים', text(withSubs(3,2),3));
ck('...and the server\'s number is what the item half says even then',
   text(withSubs(2,1),9)==='9 פריטים / 1 תת־פריט', text(withSubs(2,1),9));
ck('a group the server counted at zero says 0, not nothing',
   text([],0)==='0 פריטים / 0 תתי־פריטים', text([],0));

/* the two cases where the board's number answers the wrong question, and the
   rows on screen are the answer: a filtered board is showing a cut of itself,
   and an old backend sends no map at all. Both arrive here as a null `known`,
   which is the no-argument behaviour every check above this section pins. */
ck('a group under a filter counts what it is showing',
   text(withSubs(3,1),null)==='3 פריטים / 1 תת־פריט', text(withSubs(3,1),null));
// ── and which of the two it is: groupCountKnown, run ─────────────────────
/* One function answers "is there a number for this group, and what is it" for
   everything that prints one — the chip on the open header, the line above,
   and the delete dialog. Run here rather than read, because every one of its
   answers is a decision somebody sees: null means "fall back to the rows",
   and a null where a 0 belongs turns a genuinely empty group back into the
   ambiguity the "+" used to stand for. */
const gkSrc = (()=>{ const g=/function groupCountKnown\([^)]*\)\{[\s\S]*?\n\}/.exec(src);
  if(!g) throw new Error('groupCountKnown is gone'); return g[0]; })();
const known = (board,{narrowed=false,gid=5,whole=false}={}) =>
  new Function('st','boardIsNarrowed', gkSrc+'; return groupCountKnown;')(
    {board}, ()=>narrowed)(gid,whole);
const mapped = {group_counts:{'5':1033,'7':0,'null':4}};

ck('the board\'s own number is what a group reports', known(mapped)===1033);
ck('a group the board counted at zero reports 0, not "no number"',
   known(mapped,{gid:7})===0, String(known(mapped,{gid:7})));
ck('the "ללא קבוצה" bucket is looked up under the key the board files it as',
   known(mapped,{gid:null})===4, String(known(mapped,{gid:null})));
ck('a group the map says nothing about falls back to the rows',
   known(mapped,{gid:99})===null, String(known(mapped,{gid:99})));
ck('a board from a backend that sends no counts falls back to the rows',
   known({})===null, String(known({})));
ck('and so does a board narrowed by a filter, which is showing a cut of itself',
   known(mapped,{narrowed:true})===null, String(known(mapped,{narrowed:true})));
ck('...except for the caller that is about to delete the group, which is not about the cut',
   known(mapped,{narrowed:true,whole:true})===1033,
   String(known(mapped,{narrowed:true,whole:true})));

/* the header is read off the source — groupHTML cannot be run here, it draws
   rows, columns, menus and an estimated height — but what is worth saying
   about it is that it asks that same function, and that the chip and the
   folded line are handed the one answer rather than working it out twice */
const groupHTML = (()=>{ const i=src.indexOf('function groupHTML(g){');
  if(i<0) throw new Error('groupHTML is gone');
  let d=0; for(let j=src.indexOf('{',i);j<src.length;j++){
    if(src[j]==='{')d++; else if(src[j]==='}'&&!--d) return src.slice(i,j+1); } })();
ck('the header asks that function instead of counting the rows itself',
   /groupCountKnown\(g\.id\)/.test(groupHTML), groupHTML.slice(0,400));
ck('and the folded line is handed the same number the open header shows',
   /groupSummaryHTML\(g\.tasks,\s*(\w+)\)/.test(groupHTML) &&
   new RegExp('const count='+'[^\\n]*'+/groupSummaryHTML\(g\.tasks,\s*(\w+)\)/.exec(groupHTML)[1])
     .test(groupHTML),
   'the open count and the collapsed line come from different variables');

/* What keeps that number right between one board fetch and the next — the
   bookkeeping on the paths that change the board without refetching it — is a
   subject of its own, and lives in group_count_local_edits.mjs. */

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
