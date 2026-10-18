/* What the import report says about how the board came out divided.

   A board that arrives as one long list of 320 items looks like a board nobody
   ever organised. Twice it was not: monday writes the group name on a line of
   its own above the header, and an export that was never asked for `groups`
   carries no division at all. Both are things only the report can say, and the
   three cases read differently — read FROM the file, read from a group column,
   and not in the file at all.

   Driven by tests/test_import_groups.py. */
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
/* importReport now keeps the report it built (st._impReport) for the three
   things its ✕ offers, and re-points that ✕ at the asking. Neither is what these
   checks are about, so both are stubbed: an object to hold it, and a document
   that owns no ✕. */
const st={};
const report = new Function('esc','showModal','st','document',
  grab('importReport')+'\nreturn importReport;')(
  x=>String(x==null?'':x), h=>{shown=h;}, st, {querySelector:()=>null});

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(x?'  → '+x.slice(0,400):''))); };
const run = r => { shown=''; report({name:'לוח', items:r.items||3, report:r}); return shown; };
/* the groups section on its own, so "is it a warning?" is asked of it and not
   of the whole report — every import of a monday file has a warning somewhere */
const sec = h => {
  const at=h.indexOf('fa-layer-group');
  if(at<0) return '';
  // `imp-sec-t` is the section's own title div and starts with the same string,
  // so the opening tag is matched by what follows the class rather than by a
  // prefix of it — the section's class is where `imp-warn` lives.
  let i=-1, m, re=/<div class="imp-sec(?:"| imp-warn")/g;
  while((m=re.exec(h)) && m.index<at) i=m.index;
  return i<0?'':h.slice(i, h.indexOf('</div>', at));
};

// ── the division the file stated ───────────────────────────────────────────
{
  const h = run({items:37, groups:4, groups_from:'sheet', summary_rows:4,
                 group_names:['עליה לאוויר','חבילה 1','חבילה 2','חבילה 3']});
  ck('the groups are counted', h.includes('4 קבוצות'), h);
  ck('and named, so the division can be checked against the board',
     ['עליה לאוויר','חבילה 1','חבילה 2','חבילה 3'].every(n=>h.includes(n)), h);
  ck('it says where the division was read from',
     h.includes('שורות הקבוצה שבין הפריטים'), h);
  ck('a summary line monday writes under a group is not counted as an item',
     h.includes('4 שורות הסיכום'), h);
  ck('a division that came in is not flagged as a problem',
     sec(h).length > 40 && !sec(h).includes('imp-warn'), sec(h));
}

// ── the division a column stated ───────────────────────────────────────────
{
  const h = run({groups:2, groups_from:'column', groups_column:'קבוצה',
                 group_names:['תשתיות','חינוך']});
  ck('a group column is named as the source', h.includes('עמודת הקבוצה שבקובץ'), h);
  ck('and the column itself is quoted', h.includes('"קבוצה"'), h);
}

// ── no division in the file at all ─────────────────────────────────────────
{
  const h = run({groups:0, groups_from:'default', group_names:['בתכנון','בביצוע','הושלם']});
  ck('a flat file is told it was flat', h.includes('אינו מחלק את הלוח לקבוצות'), h);
  ck('and what to do to divide it', h.includes('עמודה בשם "קבוצה"'), h);
  ck('three default groups are not reported as three groups from the file',
     !h.includes('3 קבוצות'), h);
}

// ── an export that was never asked for the groups ──────────────────────────
{
  const h = run({items:320, groups:0, groups_need_reexport:true});
  ck('the file that cannot say how the board is divided says so',
     h.includes('הקובץ אינו אומר איך הלוח מחולק'), h);
  ck('...as a warning, not a footnote', sec(h).includes('imp-warn'), sec(h));
  ck('...saying nothing was lost', h.includes('שום דבר לא נמחק'), h);
  ck('...naming the two fields to ask for',
     h.includes('groups { id title color }') && h.includes('group { id title color }'), h);
  ck('...and the file to run it from', h.includes('monday_export.graphql'), h);
  ck('it does not also claim the file had no division to begin with',
     !h.includes('אינו מחלק את הלוח לקבוצות'), h);
}

// ── the colours the groups came in wearing ─────────────────────────────────
{
  const h = run({groups:3, groups_from:'file', group_names:['דחוף','בעבודה','הושלם'],
                 group_hex:['#e2445c','#fdab3d','#00c875'], group_colors:3});
  ck('the colours are said to have come from the file',
     h.includes('צבעי הקבוצות יובאו מהקובץ'), h);
  ck('...and each group is shown as the chip it is on the board',
     h.includes('background:#e2445c') && h.includes('background:#00c875'), h);
  ck('...without being called a default', !h.includes('ברירת מחדל'), h);
}
{
  const h = run({groups:3, groups_from:'file', group_names:['דחוף','בעבודה','הושלם'],
                 group_hex:['#1AC877','#FBAA47','#DB2D4C'], group_colors:0});
  ck('a file carrying no colours says the colours are this app\'s',
     h.includes('צבעי ברירת מחדל'), h);
  ck('...and says how to bring the real ones over',
     h.includes('groups { id title color }'), h);
}
{
  const h = run({groups:3, groups_from:'sheet', group_names:['א','ב','ג'],
                 group_hex:['#e2445c','#FBAA47','#DB2D4C'], group_colors:1});
  ck('a file that coloured some of its groups says how many',
     h.includes('1 מתוך 3'), h);
  ck('...and does not tell a sheet to re-run a monday query',
     !h.includes('groups { id title color }'), h);
}

// ── monday's own sub-item header ───────────────────────────────────────────
{
  const h = run({hierarchy:'band', groups:1, group_names:['קבוצה']});
  ck('the hierarchy read from the band is described as that, not as indentation',
     h.includes('כותרות תתי־הפריטים שמאנדיי כותב') && !h.includes('נקראה מההזחה'), h);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
