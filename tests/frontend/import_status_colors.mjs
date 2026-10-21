/* What the import report says about the colours the statuses came in wearing.

   A status is read as its colour before it is read as a word, so a vocabulary
   that arrived in this app's palette is a board that reads differently from the
   one it came from — and the only moment that can be said is the report. The
   three cases read differently: every colour came from the file, some of them
   did, and none of them did.

   Driven by tests/test_import_status_colors.py. */
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
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(x?'  → '+x.slice(0,400):''))); };
const run = r => { shown=''; report({name:'לוח', items:r.items||3, report:r}); return shown; };
/* the statuses' own section, so what is asked of it is not answered by the
   groups' section three paragraphs above — both talk about colour */
const sec = h => {
  const at=h.indexOf('fa-circle-half-stroke');
  if(at<0) return '';
  let i=-1, m, next=h.length, re=/<div class="imp-sec(?:"| imp-warn")/g;
  while((m=re.exec(h))){ if(m.index<at) i=m.index; else { next=m.index; break; } }
  return i<0?'':h.slice(i, next);
};

// ── every colour came out of the file ──────────────────────────────────────
{
  const h = sec(run({status_cols:2, status_options:5, status_colors:5}));
  ck('the status columns and their words are counted',
     h.includes('2 עמודות סטטוס') && h.includes('5 סטטוסים'), h);
  ck('the colours are said to have come from the file',
     h.includes('צבעי הסטטוסים יובאו מהקובץ'), h);
  ck('...without being called a default', !h.includes('ברירת מחדל'), h);
}

// ── some of them did ───────────────────────────────────────────────────────
{
  const h = sec(run({status_cols:1, status_options:4, status_colors:3}));
  ck('a file that coloured some of its statuses says how many',
     h.includes('3 מתוך 4'), h);
  ck('...and that the rest are defaults', h.includes('ברירת מחדל'), h);
}

// ── none of them did ───────────────────────────────────────────────────────
{
  const h = sec(run({status_cols:1, status_options:3, status_colors:0}));
  ck('a file carrying no status colours says the colours are this app\'s',
     h.includes('אינו נושא את צבעי הסטטוסים'), h);
  ck('...and does not claim any of them came from the file',
     !h.includes('יובאו מהקובץ'), h);
}

// ── where the colours can be fetched from, and where they cannot ───────────
{
  const h = sec(run({status_cols:1, status_options:3, status_colors:0,
                     mapping:[{title:'שלב', from:'status', to:'status'}]}));
  ck('a monday response is told which field to ask for next time',
     h.includes('settings_str'), h);
}
{
  const h = sec(run({status_cols:1, status_options:3, status_colors:0}));
  ck('a spreadsheet is not told to re-run a monday query',
     !h.includes('settings_str'), h);
}

// ── a board with no status column at all ───────────────────────────────────
{
  const h = run({status_cols:0, status_options:0, status_colors:0, groups:1,
                 groups_from:'sheet', group_names:['קבוצה']});
  ck('a file with no status column says nothing about status colours',
     !h.includes('עמודות סטטוס'), h);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
