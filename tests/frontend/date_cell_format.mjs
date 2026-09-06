/* A date column must read the same to everyone looking at the board.

   `<input type="date">` renders the day/month order from the *browser's*
   locale — the page cannot set it — so the date columns, and only the date
   columns, said 31/12/2026 to a Hebrew Chrome and 12/31/2026 to an English
   one. These check that the cell carries its own text, in the DD/MM/YYYY the
   rest of the board already uses, and that the input is still there to pick
   and type with. Driven by tests/test_date_cell_format.py. */
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
/* fdate is a one-liner whose body holds semicolons of its own, so this takes
   the whole line rather than stopping at the first one. */
function grabConst(name){
  const m = new RegExp(`^const ${name} = .*$`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return m[0];
}

// the real fdate and the real cell builders, nothing stubbed but esc/canEditItem
const api = new Function('esc','canEditItem','cellValue',
  [grabConst('fdate'), grab('dateCellHTML'), grab('builtinCellHTML'), grab('customCellHTML'),
   'return {fdate, dateCellHTML, builtinCellHTML, customCellHTML};'].join('\n'))
  (s=>String(s==null?'':s), ()=>true, (t,id)=>(t.custom_fields||{})[id]);

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── the cell says the date itself ──
const cell = api.dateCellHTML('2026-12-31', 'noop()');
ck('the cell carries day/month/year text of its own',
   cell.includes('31/12/2026'), cell);
ck('and never the American order',
   !cell.includes('12/31/2026'), cell);
ck('the native input is still there to pick and type with',
   /<input type="date"[^>]*value="2026-12-31"/.test(cell), cell);
ck('the input keeps the class the drag filter looks for',
   /class="cc-inp cc-date"/.test(cell), cell);
ck('clicking the cell asks for the picker',
   cell.includes('dateCellPick(event)'), cell);
ck('the change handler is wired through',
   cell.includes('noop()'), cell);

// ── an empty cell ──
const empty = api.dateCellHTML('', 'noop()');
ck('an empty date shows a dash, not a blank',
   empty.includes('—'), empty);
ck('and its input is empty rather than absent',
   /<input type="date"[^>]*value=""/.test(empty), empty);

// ── a full ISO timestamp is trimmed to the day ──
const stamped = api.dateCellHTML('2026-01-05T00:00:00', 'noop()');
ck('a timestamp still reads as one day',
   stamped.includes('05/01/2026'), stamped);

// ── both board columns go through it ──
const due = api.builtinCellHTML('due', {id:7, due_date:'2026-12-31'});
ck('the built-in due-date column draws its own text',
   due.includes('31/12/2026') && due.includes('cc-datewrap'), due);
ck('the due-date change still calls setDue for that item',
   due.includes('setDue(7,'), due);

const col = api.customCellHTML({id:'c9', type:'date'}, {id:7, custom_fields:{c9:'2026-12-31'}});
ck('a custom date column draws its own text',
   col.includes('31/12/2026') && col.includes('cc-datewrap'), col);
ck('the custom-column change still calls setCell for that column',
   col.includes("setCell(7,'c9'"), col);

// ── and the read-only due cell, which was already right, still is ──
const ro = new Function('esc','canEditItem','cellValue','fdate','dateCellHTML',
  grab('builtinCellHTML')+'; return builtinCellHTML;')
  (s=>String(s==null?'':s), ()=>false, ()=>null, api.fdate, api.dateCellHTML)
  ('due', {id:7, due_date:'2026-12-31'});
ck('a viewer who may not edit sees the same order',
   ro.includes('31/12/2026'), ro);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
