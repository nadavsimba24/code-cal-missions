/* What the import report says about sub-items that arrived as names only.

   The old line read "<column> אינה עמודה כאן — מה שהיה בה יובא כתתי־פריטים של
   הפריטים עצמם" and was printed whether or not a single sub-item had been
   created. Over a board that got none it is the loss named as the feature, and
   over a board whose sub-items came from names alone it promises columns and a
   conversation that are not there.

   Driven by tests/test_import_subitems_named.py. */
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
/* `b` is the import's own answer — the board — and `r` its report; the sub-item
   count is on the board, which is why it is passed beside. */
const run = (r, b={}) => { shown=''; report({name:'לוח', items:3, ...b, report:r}); return shown; };
/* the sub-items section — the one headed by the column, not the hierarchy one
   above it, which carries the same icon */
const sec = h => {
  const at=h.lastIndexOf('fa-diagram-project');
  if(at<0) return '';
  let i=-1, m, next=h.length, re=/<div class="imp-sec(?:"| imp-warn")/g;
  while((m=re.exec(h))){ if(m.index<at) i=m.index; else { next=m.index; break; } }
  return i<0?'':h.slice(i, next);
};

// ── the sub-items came as rows, the way the file should carry them ─────────
{
  const h = sec(run({as_subitems:['Subitems'], subitems_named:0},
                    {subitems:7}));
  ck('the column is explained as the sub-items themselves',
     h.includes('Subitems') && h.includes('אינה עמודה כאן'), h);
  ck('...and the count is the sub-items that came', h.includes('(7)'), h);
  ck('...with nothing said about names', !h.includes('רק בשמם'), h);
}

// ── they came as names, because the file carried no rows for them ──────────
{
  const h = sec(run({as_subitems:['Subitems'], subitems_named:12},
                    {subitems:12}));
  ck('the report says they arrived by name only', h.includes('רק בשמם'), h);
  ck('...how many were created that way', h.includes('12 תתי־פריטים'), h);
  ck('...and what they are missing',
     h.includes('בלי העמודות שלהם') && h.includes('בלי השיחות'), h);
  ck('...it no longer claims the column simply became the sub-items',
     !h.includes('מה שהיה בה יובא'), h);
  ck('...and it says what to do to get the rest', h.includes('מה עושים'), h);
  ck('...including that a name with a comma in it split in two',
     h.includes('פסיק'), h);
}

// ── where the rest can be fetched from, which differs by file ──────────────
{
  const h = sec(run({as_subitems:['Subitems'], subitems_named:4,
                     mapping:[{title:'שלב', from:'status', to:'status'}]}, {subitems:4}));
  ck('a monday response is told which field to add to the query',
     h.includes('subitems'), h);
  ck('...and which file to re-run', h.includes('monday_export.graphql'), h);
}
{
  const h = sec(run({as_subitems:['Subitems'], subitems_named:4},
                    {subitems:4}));
  ck('a spreadsheet is told to re-export with the sub-items open',
     h.includes('מייצאים מחדש ממאנדיי'), h);
  ck('...and is not told to edit a GraphQL query',
     !h.includes('monday_export.graphql'), h);
}

// ── a board with no sub-items column at all ────────────────────────────────
{
  const h = run({groups:1, groups_from:'sheet', group_names:['קבוצה']});
  ck('a file with no sub-items column says nothing about one',
     !h.includes('אינה עמודה כאן'), h);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
