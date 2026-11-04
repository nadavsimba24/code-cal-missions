/* What the import report says when the FILE is short of the board.

   A monday board of 2,069 items imported as 2,000 and read as finished. The
   number that would have said otherwise — monday's own `items_count` — was in
   the file and in nobody's report, and the gap was found a day later by
   counting the group in monday: 1,819 there, 1,748 here.

   The cursor already covers an export that stopped at the END. The case it
   cannot see is a merge that lost a page out of the MIDDLE: the file ends on a
   null cursor and reads as complete. So the report states both counts and the
   difference, inside the warning block — not as a line of prose somewhere
   under thirty others.

   Driven by tests/test_import_short_file_notice.py. */
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
  throw new Error('unbalanced: '+name);
}

let shown='';
const st={};
const report = new Function('esc','showModal','st','document',
  grab('importReport')+'\nreturn importReport;')(
  x=>String(x==null?'':x), h=>{shown=h;}, st, {querySelector:()=>null});

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(x?'  → '+x.slice(0,500):''))); };
const run = r => { shown=''; report({name:'ערבויות', items:r.items||3, report:r}); return shown; };

/* the warning block on its own — "הקובץ אינו הלוח המלא" — so the counts are
   asked of the place a short file is announced, and not of the report at large */
const warn = h => {
  const at = h.indexOf('הקובץ אינו הלוח המלא');
  if(at < 0) return '';
  const i = h.lastIndexOf('<div class="imp-sec imp-warn">', at);
  return i < 0 ? '' : h.slice(i, h.indexOf('</div></div>', at) + 12);
};

// ── the real board, with its real numbers ─────────────────────────────────
{
  const h = run({items:1748, items_expected:1817, items_missing:69,
                 groups:2, groups_from:'file', group_names:['בדיקת ערבויות','ערבויות ששוחררו']});
  const w = warn(h);
  ck('a short file is announced as a short file', w !== '', h);
  ck('monday’s own count is stated', w.includes('1817'), w);
  ck('and what the file actually carried, beside it', w.includes('1748'), w);
  ck('and the difference, so it need not be worked out', w.includes('69'), w);
  ck('it says what to do about it', w.includes('cursor'), w);
}

// ── the middle page the cursor cannot see ─────────────────────────────────
{
  const h = run({items:20, items_expected:30, items_missing:10, truncated:false});
  const w = warn(h);
  ck('a clean cursor does not make a short file read as a whole one', w !== '', h);
  ck('the counts are there without the cursor warning',
     w.includes('30') && w.includes('20') && !w.includes('נעצר לפני סוף הלוח'), w);
}

// ── a whole file says nothing ─────────────────────────────────────────────
{
  const h = run({items:2069, items_expected:2069, items_missing:0, groups:2});
  ck('a file that brought the whole board raises no warning about its size',
     !h.includes('הקובץ אינו הלוח המלא'), h);
}

// ── a file that never stated a count ──────────────────────────────────────
{
  const h = run({items:12, items_expected:null, items_missing:0});
  ck('a query that never asked for items_count is not accused of being short',
     !h.includes('הקובץ אינו הלוח המלא'), h);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
