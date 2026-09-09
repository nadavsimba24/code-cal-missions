/* The exported grid: each run of sub-items opens with a header of its own.

   Sub-items have a column structure that is not a subset of the item's — a
   board can give them columns that exist nowhere else (board.sub_only). The
   grid laid every sub-item out under the ITEM's headers and wrote a value only
   where the two structures shared a column id, so exactly those sub-item-only
   columns — the ones whose values exist nowhere else either — were dropped from
   the file with nothing to say they had been.

   Each block of sub-items is now introduced by a header naming its own columns,
   and its rows are read against that header. This runs the real exportGrid over
   a stub board. Driven by tests/test_export_subitem_band.py. */
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

/* A board whose sub-items carry a column the items do not have at all: "שעות"
   is sub-only, which is the case the old grid could not represent. */
const col = (id,title) => ({kind:'custom', id, col:{id,title,type:'text'}});
const ITEM_COLS = [{kind:'builtin',id:'item',key:'item',label:'פריט'}, col('status','סטטוס'), col('budget','תקציב')];
const SUB_COLS  = [{kind:'builtin',id:'item',key:'item',label:'פריט'}, col('status','סטטוס'), col('hours','שעות')];

const sub = (title,hours) => ({title, custom_fields:{status:'הושלם', hours}});
const GROUPS = [{id:1, name:'בביצוע', tasks:[
  {title:'גשר הרצל', custom_fields:{status:'בתהליך', budget:125000}, subtasks:[sub('מדידות',12), sub('מכרז',40)]},
  {title:'ללא תתי-פריטים', custom_fields:{status:'בתהליך', budget:5}, subtasks:[]},
]}];

const exportGrid = new Function(
  'orderedColumns','subColumns','groupsOf','sortedSubs','exportCell','subColLabel',
  grab('exportGrid')+'; return exportGrid;')(
    ()=>ITEM_COLS, ()=>SUB_COLS, ()=>GROUPS, s=>s,
    (c,t)=> c.kind==='builtin' ? (t.title||'') : ((t.custom_fields||{})[c.col.id] ?? ''),
    c=> c.kind==='builtin' ? c.label : (c.col&&c.col.title)||'');

const g = exportGrid();
const kinds = g.rows.map(r=> r.group?'group' : r.subhead?'subhead' : 'L'+r.level);
ck('a run of sub-items is introduced by a header of its own',
   kinds.join(' ')==='group L1 subhead L2 L2 L1', kinds.join(' '));

const band = g.rows[2], first = g.rows[3];
ck('the header names the sub-item columns, not the item ones',
   band.cells.join('|')==='|פריט|סטטוס|שעות', band.cells.join('|'));
ck('and the sub-item column that exists nowhere else is one of them',
   band.cells.includes('שעות'));
ck('a sub-item row is read against that header',
   first.cells.join('|')==='|מדידות|הושלם|12', first.cells.join('|'));
ck('so the value in the sub-only column reaches the file',
   first.cells.includes(12), first.cells.join('|'));
/* the old grid wrote sub-items under the item headers, which put a sub-item's
   value in whatever column shared its id — and dropped the rest */
ck('and it is not filed under an item column that happens to share a position',
   g.columns[3]===undefined || g.rows[3].cells[3]!==125000);

ck('both the header and its rows fold into the item above them',
   band.level===2 && first.level===2);
ck('an item with no sub-items gets no header for none',
   g.rows[5].level===1 && g.rows.filter(r=>r.subhead).length===1);

// ── one width for the sheet ────────────────────────────────────────────────
const width = g.columns.length;
ck('the item header is padded to the width the sheet needs',
   width===Math.max(ITEM_COLS.length, SUB_COLS.length+1), 'width '+width);
ck('and every row is that same width — no ragged rows to misalign',
   g.rows.every(r=>r.cells.length===width), g.rows.map(r=>r.cells.length).join(','));
ck('the item columns keep their names, the padding is blank',
   g.columns.slice(0,3).join('|')==='פריט|סטטוס|תקציב' && g.columns[3]==='', g.columns.join('|'));
/* the sub-item band is indented one column so it reads as belonging to the item
   above it, which is why the sheet needs one more column than the sub-items have */
ck('the band starts one column in, under the item it belongs to',
   band.cells[0]==='' && first.cells[0]==='');

// ── a group header is still a group header ────────────────────────────────
ck('the group row is untouched by any of this',
   g.rows[0].group===true && g.rows[0].cells[0]==='בביצוע'
   && g.rows[0].cells.slice(1).every(x=>x===''));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
