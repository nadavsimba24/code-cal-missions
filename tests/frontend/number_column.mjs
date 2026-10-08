/* The number column: where its unit sits, and what a group of them adds up to.
   Runs the real fnum, groupSums and groupSumRowHTML out of index.html.
   Driven by tests/test_number_column.py. */
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
const LEAD = /const NUM_LEAD='([^']+)'/.exec(src)[1];
const fnum = new Function('NUM_LEAD', grab('numCfg')+grab('fnum')+'; return fnum;')(LEAD);

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

/* ── 1. the shekel leads, like every other currency sign ────────────────── */
const col=(unit,thousands=true)=>({number:{unit,thousands}});
ck('₪ is written before the digits', fnum(1234.5,col('₪'))==='₪1,234.5', fnum(1234.5,col('₪')));
ck('...and so is $, as before', fnum(1234.5,col('$'))==='$1,234.5', fnum(1234.5,col('$')));
ck('a unit that is a word still follows the number',
   fnum(1234.5,col('מ"ר'))==='1,234.5 מ"ר', fnum(1234.5,col('מ"ר')));
ck('no unit, no decoration', fnum(1234.5,col(''))==='1,234.5');
ck('the separator is still a choice', fnum(1234.5,col('₪',false))==='₪1234.5', fnum(1234.5,col('₪',false)));
ck('an empty cell stays empty', fnum(null,col('₪'))==='' && fnum('',col('₪'))==='');
ck('a debt is -₪50, not ₪-50',
   fnum(-50,col('₪'))==='-₪50', fnum(-50,col('₪')));
ck('...and a negative with a trailing unit is untouched',
   fnum(-50,col('מ"ר'))==='-50 מ"ר', fnum(-50,col('מ"ר')));
ck('a negative total reads the same way',
   fnum(-1234.5,col('$'))==='-$1,234.5', fnum(-1234.5,col('$')));
ck('the settings screen shows the shape the cell will have',
   /\['₪','ש"ח','₪1,234\.5'\]/.test(src), 'the preset example still shows the old side');
ck('typing over a formatted cell still strips the sign',
   /NUM_LEAD\+'%\]'/.test(src) && !/NUM_LEAD\+'₪%\]'/.test(src),
   'ש"ח is in NUM_LEAD now, so stripping it twice is noise');

/* ── 2. what the group adds up to ───────────────────────────────────────── */
const NUMS=[{id:'c1',type:'number'},{id:'c2',type:'number'},{id:'t',type:'text'}];
const sums = cols => new Function('customColumns', grab('groupSums')+'; return groupSums;')(()=>cols);

{
  const f=sums(NUMS);
  const got=f([{custom_fields:{c1:10}},{custom_fields:{c1:0.1}},{custom_fields:{c1:0.2}},
               {custom_fields:{}},{custom_fields:{c1:''}},{custom_fields:{c1:'abc'}}]);
  ck('it adds what is there and skips what is not',
     got.c1 && got.c1.sum===10.3 && got.c1.cells===3, JSON.stringify(got));
  ck('0.1 + 0.2 is 0.3 in a budget column', f([{custom_fields:{c1:0.1}},{custom_fields:{c1:0.2}}]).c1.sum===0.3);
  ck('a column nobody filled in says nothing, rather than 0',
     !('c2' in got), JSON.stringify(got));
  ck('a zero somebody did type is counted',
     f([{custom_fields:{c1:0}}]).c1.sum===0, JSON.stringify(f([{custom_fields:{c1:0}}])));
  ck('text columns are not summed', !('t' in f([{custom_fields:{t:'5'}}])));
  ck('an empty group has no totals', Object.keys(f([])).length===0);
}

/* ── 3. the row, in the columns it belongs to ───────────────────────────── */
function rowHTML(cols,tasks,admin=true){
  const ordered=[{id:'item',kind:'builtin',key:'item'}]
    .concat(cols.map(c=>({id:c.id,kind:'custom',col:c})));
  return new Function('customColumns','orderedColumns','fnum','esc','isBoardAdmin',
    grab('groupSums')+grab('groupSumRowHTML')+'; return groupSumRowHTML;')(
    ()=>cols, ()=>ordered, fnum, x=>String(x), ()=>admin)(tasks);
}
{
  const cols=[{id:'c1',type:'number',number:{unit:'₪',thousands:true}},
              {id:'c2',type:'number'},{id:'t',type:'text'}];
  const html=rowHTML(cols,[{custom_fields:{c1:1000}},{custom_fields:{c1:234.5}}]);
  ck('the total carries the column\'s own unit', html.includes('₪1,234.5'), html);
  ck('it is a tfoot, so the drag container above it is untouched',
     html.startsWith('<tfoot>') && html.trim().endsWith('</tfoot>'));
  ck('the row has one cell per column, in order',
     (html.match(/<td /g)||[]).length===1+cols.length+2, html);
  ck('a column with nothing in it gets an empty cell, not a gap',
     (html.match(/class="cell gs-cell"/g)||[]).length===3, html);
  ck('the label sits in the item column', /<td class="c-item gs-lbl"><span>סה"כ<\/span><\/td>/.test(html));
  ck('nothing to total, nothing drawn', rowHTML(cols,[])==='' && rowHTML([{id:'t',type:'text'}],[{custom_fields:{t:'x'}}])==='');
}

/* ── 4. where it hangs, and what it is counted off ──────────────────────── */
ck('the group draws it under its rows', /\$\{groupSumRowHTML\(g\.tasks\)\}/.test(src),
   'counted off g.tasks, so a filter is reflected in the total');
ck('it is styled as a reading, not as a row of the board',
   /\.tbl tfoot \.group-sum td\{border-top:1px solid var\(--border-strong\)/.test(src));
ck('the figures are tabular, so they line up down the column',
   /\.gs-num\{[^}]*font-variant-numeric:tabular-nums/.test(src.replace(/\n\s*/g,'')));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
