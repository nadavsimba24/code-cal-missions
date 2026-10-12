/* A date column must read the same to everyone looking at the board, and must
   take a date somebody types.

   `<input type="date">` renders the day/month order from the *browser's*
   locale — the page cannot set it — so the date columns, and only the date
   columns, said 31/12/2026 to a Hebrew Chrome and 12/31/2026 to an English
   one. Its segments cannot really be typed into either, so a date was
   something you could only click your way to.

   These check that the cell carries its own text in the DD/MM/YYYY the rest of
   the board already uses, that the text sits in a box that can be typed into,
   that what it reads back is that same format, and that the native input is
   still behind it holding the value and the picker. Driven by
   tests/test_date_cell_format.py. */
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
/* fdateVal is an arrow whose body runs over several lines — brace-match it the
   way grab() does a function, so the harness runs the real one. */
function grabArrow(name){
  const m = new RegExp(`^const ${name} = `,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1)+';';} }
}

// the real formatters and cell builders, nothing stubbed but esc/canEditItem
const api = new Function('esc','canEditItem','cellValue',
  [grabConst('fdate'), grabArrow('fdateVal'), grab('parseTypedDate'),
   grab('dateCellHTML'), grab('builtinCellHTML'), grab('customCellHTML'),
   'return {fdate, fdateVal, parseTypedDate, dateCellHTML, builtinCellHTML, customCellHTML};'].join('\n'))
  (s=>String(s==null?'':s), ()=>true, (t,id)=>(t.custom_fields||{})[id]);

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── the cell says the date itself ──
const cell = api.dateCellHTML('2026-12-31', 'noop()');
ck('the cell carries day/month/year text of its own',
   cell.includes('31/12/2026'), cell);
ck('and never the American order',
   !cell.includes('12/31/2026'), cell);
ck('that text sits in a box someone can type into',
   /<input class="cc-inp cc-date-txt" value="31\/12\/2026"/.test(cell), cell);
ck('which says what it will take',
   cell.includes('placeholder="DD/MM/YYYY"'), cell);
ck('the typable box keeps the class the drag filter looks for',
   /class="cc-inp cc-date-txt"/.test(cell), cell);
ck('the value is carried by a hidden input, which costs the row nothing',
   /<input type="hidden"[^>]*class="cc-date" value="2026-12-31"/.test(cell), cell);
/* The performance invariant, and the reason the hidden input exists at all: an
   `<input type="date">` is a browser widget with its own shadow tree, and a
   board with fifteen date columns had three and a half thousand of them in one
   group — all laid out the moment it was expanded. The real control is borrowed
   for the length of a pick (dateCellPick) and never lives in a row. */
ck('and the cell holds no date WIDGET — 15 columns × 237 rows of them is the cost',
   !/type="date"/.test(cell), cell);
ck('the calendar is a button of its own, and it asks for the picker',
   cell.includes('cc-date-cal') && cell.includes('dateCellPick(event)'), cell);
ck('the change handler is wired through',
   cell.includes('noop()'), cell);

// ── an empty cell ──
const empty = api.dateCellHTML('', 'noop()');
ck('an empty date offers the format rather than a blank',
   empty.includes('placeholder="DD/MM/YYYY"') && /class="cc-inp cc-date-txt" value=""/.test(empty), empty);
ck('and its carrier is empty rather than absent',
   /<input type="hidden"[^>]*class="cc-date" value=""/.test(empty), empty);

// ── a full ISO timestamp is trimmed to the day ──
const stamped = api.dateCellHTML('2026-01-05T00:00:00', 'noop()');
ck('a timestamp still reads as one day',
   stamped.includes('05/01/2026'), stamped);

// ── what the cell reads back is the format it draws ──
ck('DD/MM/YYYY is taken as written',
   api.parseTypedDate('31/12/2026')==='2026-12-31');
ck('and so are the near misses of it',
   ['1/2/26','1.2.2026','1-2-2026','01022026','010226'].every(s=>api.parseTypedDate(s)==='2026-02-01'));
ck('an ISO date pasted in from elsewhere is understood too',
   api.parseTypedDate('2026-12-31')==='2026-12-31');
ck('the American order is NOT silently accepted',
   api.parseTypedDate('12/13/2026')==='');
ck('a day that does not exist is refused',
   api.parseTypedDate('31/02/2026')==='' && api.parseTypedDate('29/02/2023')==='');
ck('a leap day that does exist is not',
   api.parseTypedDate('29/02/2024')==='2024-02-29');
ck('and text is not a date',
   ['abc','','123','99/99/9999'].every(s=>api.parseTypedDate(s)===''));
ck('fdateVal draws the plain text the box holds, and nothing for an empty day',
   api.fdateVal('2026-12-31')==='31/12/2026' && api.fdateVal('')==='' && api.fdateVal(null)==='');

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

// ── the timeline picker's two boxes, the last pair of bare date inputs ──
const box = api.dateCellHTML('2026-09-27', "Timeline.typed('from',this.value)",
                             {id:'tl-from', cls:'tl-datewrap'});
ck('מתאריך draws its own text as well',
   box.includes('27/09/2026'), box);
ck('and keeps the id the picker addresses it by',
   box.includes('id="tl-from"'), box);
ck('and still reports typing back to the picker',
   box.includes("Timeline.typed('from',this.value)"), box);
ck('the picker box carries its own modifier class',
   box.includes('class="cc-datewrap tl-datewrap"'), box);

// the two boxes themselves, not whatever render() the file happens to hold first
const picker = /<div class="tl-inputs">[\s\S]*?<\/div>/.exec(src);
ck('neither picker box is a bare date input any more',
   picker && !/<input type="date"/.test(picker[0]), picker&&picker[0]);
ck('both boxes go through the same helper',
   picker && (picker[0].match(/dateCellHTML\(/g)||[]).length===2, picker&&picker[0]);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
