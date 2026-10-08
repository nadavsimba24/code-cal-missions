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

const m = /function groupSummaryHTML\(tasks\)\{[\s\S]*?\n\}/.exec(src);
if(!m) throw new Error('groupSummaryHTML is gone');
const sum = new Function(m[0]+'; return groupSummaryHTML;')();
const text = t => sum(t).replace(/<[^>]*>/g,'').trim();

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
   /const sum=groupSummaryHTML\(g\.tasks\);/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
