/* Picking "טרם הוגדר" in the built-in status column.
   Driven by tests/test_status_unset_pick.py.

   Runs the real fieldPicker and setField out of index.html. What is pinned is
   what the picker offers, what it ticks, and what setField puts on the wire:
   an explicit null plus status_unset, which is the only pair the API reads as
   "nobody has chosen". */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const grab = name => {
  const m = new RegExp(`\\n(?:async )?function ${name}\\(([^)]*)\\)\\{[\\s\\S]*?\\n\\}`).exec(src);
  if(!m) throw new Error('not found: '+name);
  return m[0];
};

const MAP={done:{he:'בוצע',c:'#1AC877'},in_progress:{he:'בטיפול',c:'#FBAA47'}};
const TASK={id:7,status:'done',custom_fields:{},parent_id:null,group_id:3};
let posted=null, popped='';
const env={
  STATUS_UNSET:{label:'טרם הוגדר',color:'#c4c4c4'},
  STATUS_UNSET_KEY:'__unset',
  esc:x=>String(x==null?'':x),
  findAnyTask:()=>TASK,
  canEditItem:()=>true,
  isBoardAdmin:()=>false,
  statusKeyOf:t=>((t.custom_fields||{}).status_unset?null:(t.custom_fields||{}).status_key||t.status),
  priorityKeyOf:t=>t.priority,
  statusEntry:k=>({done:{key:'done',he:'בוצע',c:'#1AC877'},
                   in_progress:{key:'in_progress',he:'בטיפול',c:'#FBAA47'}})[k]||null,
  priorityEntry:()=>null,
  openCellPop:(_a,html)=>{ popped=html; },
  closeCellPops:()=>{},
  POP_GRID_FROM:6,
  withMe:b=>JSON.stringify(b),   // the real one serialises, and api() parses
  api:async(_u,o)=>{ posted=JSON.parse(o.body); return {}; },
  refreshRow:()=>{},
  toast:()=>{},
  findParent:()=>null,
};
const names=Object.keys(env);
const make = code => new Function(...names, code).apply(null, names.map(n=>env[n]));
const fieldPicker = make(grab('fieldPicker')+'; return fieldPicker;');
const setField    = make(grab('setField')+'; return setField;');

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the picker ──
fieldPicker({stopPropagation(){},currentTarget:{}},7,'status',MAP);
ck('the picker still offers the board statuses', popped.includes('בוצע')&&popped.includes('בטיפול'));
ck('...and now "טרם הוגדר" as well', popped.includes('טרם הוגדר'), popped);
ck('...in its own grey, the colour the cell already shows it in',
   /#c4c4c4/.test(popped), popped);
ck('...last, after the board\'s own statuses',
   popped.indexOf('c4c4c4')>popped.indexOf('בוצע'), popped);
ck('...and the SAME size as them — not spanning the row like the manage link',
   !/pop-span[^>]*#c4c4c4/.test(popped) && !/#c4c4c4[^>]*pop-span/.test(popped),
   'a grey button three times the width of every status reads as something else');
ck('it is wired to the sentinel, not to a status key',
   popped.includes("pickField(event,7,'status','__unset')"), popped);
ck('the item has a status, so the grey option is NOT ticked',
   (popped.split('טרם הוגדר')[1]||'').indexOf('fa-check')===-1, popped);
ck('...and the status it does have is', /בוצע <i class="fa-solid fa-check">/.test(popped), popped);

// an item nobody has decided on: the tick is on the grey one
TASK.custom_fields={status_unset:true};
fieldPicker({stopPropagation(){},currentTarget:{}},7,'status',MAP);
ck('an undecided item ticks "טרם הוגדר"',
   /טרם הוגדר<i class="fa-solid fa-check">|טרם הוגדר <i class="fa-solid fa-check">/.test(popped), popped);
ck('...and ticks none of the statuses', !/בוצע <i class="fa-solid fa-check">/.test(popped), popped);

// ── what goes on the wire ──
TASK.custom_fields={status_key:'x_frozen',status_label:'הקפאה',status_color:'#FD5AC3'};
TASK.status='on_hold';
await setField(7,'status','__unset');
ck('picking it sends an explicit null', posted && posted.status===null, JSON.stringify(posted));
ck('...with the flag that says nobody chose', posted.custom_fields.status_unset===true, JSON.stringify(posted));
ck('...and clears a board-defined status it was carrying',
   posted.custom_fields.status_key===null && posted.custom_fields.status_label===null &&
   posted.custom_fields.status_color===null, JSON.stringify(posted));
ck('the row on screen drops the old label and colour straight away',
   !('status_key' in TASK.custom_fields) && !('status_label' in TASK.custom_fields));
ck('...shows the undecided state', TASK.custom_fields.status_unset===true);
ck('...and holds the neutral engine value, never a null the kanban cannot group by',
   TASK.status==='todo', 'status='+TASK.status);

// ── and a normal pick is untouched ──
await setField(7,'status','done');
ck('choosing a status still sends the status', posted.status==='done', JSON.stringify(posted));
ck('...and takes the undecided flag off', posted.custom_fields.status_unset===null);
ck('...leaving nothing of it on the row', !('status_unset' in TASK.custom_fields));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
