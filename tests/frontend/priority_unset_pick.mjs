/* Picking "טרם הוגדר" in the built-in priority column.
   Driven by tests/test_priority_unset_pick.py.

   The sibling of tests/frontend/status_unset_pick.mjs, for the column beside
   it. Runs the real fieldPicker and setField out of index.html: what is pinned
   is what the picker offers, what it ticks, and what setField puts on the wire
   — an explicit null plus priority_unset, the only pair the API reads as
   "nobody has chosen" — plus the one thing the status column does NOT share,
   the neutral engine value a cleared priority falls back to. */
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

// the five defaults, plus one the board defined itself (base !== key)
const MAP={low:{he:'נמוכה',c:'#579bfc'},critical:{he:'קריטית',c:'#e2445c'},
           x_blocker:{he:'חוסם',c:'#FD5AC3',base:'high'}};
const ENTRIES={low:{key:'low',he:'נמוכה',c:'#579bfc'},
               critical:{key:'critical',he:'קריטית',c:'#e2445c'},
               x_blocker:{key:'x_blocker',he:'חוסם',c:'#FD5AC3',base:'high'}};
const TASK={id:7,status:'todo',priority:'critical',custom_fields:{},parent_id:null,group_id:3};
let posted=null, popped='';
const env={
  STATUS_UNSET:{label:'טרם הוגדר',color:'#c4c4c4'},
  STATUS_UNSET_KEY:'__unset',
  esc:x=>String(x==null?'':x),
  findAnyTask:()=>TASK,
  canEditItem:()=>true,
  isBoardAdmin:()=>false,
  statusKeyOf:t=>t.status,
  priorityKeyOf:t=>((t.custom_fields||{}).priority_unset?null:(t.custom_fields||{}).priority_key||t.priority),
  statusEntry:()=>null,
  priorityEntry:k=>ENTRIES[k]||null,
  openCellPop:(_a,html)=>{ popped=html; },
  closeCellPops:()=>{},
  POP_GRID_FROM:6,
  withMe:b=>JSON.stringify(b),   // the real one serialises, and api() parses
  api:async(_u,o)=>{ posted=JSON.parse(o.body); return {}; },
  refreshRow:()=>{},
  toast:()=>{},
  findParent:()=>null,
  statusColOpts:()=>[],
};
const names=Object.keys(env);
const make = code => new Function(...names, code).apply(null, names.map(n=>env[n]));
const fieldPicker = make(grab('fieldPicker')+'; return fieldPicker;');
const setField    = make(grab('setField')+'; return setField;');

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the picker ──
fieldPicker({stopPropagation(){},currentTarget:{}},7,'priority',MAP);
ck('the picker still offers the board priorities',
   popped.includes('נמוכה')&&popped.includes('קריטית')&&popped.includes('חוסם'));
ck('...and now "טרם הוגדר" as well', popped.includes('טרם הוגדר'), popped);
ck('...in its own grey, the colour the cell already shows it in',
   /#c4c4c4/.test(popped), popped);
ck('...last, after the board\'s own priorities',
   popped.indexOf('c4c4c4')>popped.indexOf('קריטית'), popped);
ck('...and the SAME size as them — not spanning the row like the manage link',
   !/pop-span[^>]*#c4c4c4/.test(popped) && !/#c4c4c4[^>]*pop-span/.test(popped),
   'a grey button three times the width of every priority reads as something else');
ck('it is wired to the priority field and the sentinel, not to a priority key',
   popped.includes("pickField(event,7,'priority','__unset')"), popped);
ck('the item has a priority, so the grey option is NOT ticked',
   (popped.split('טרם הוגדר')[1]||'').indexOf('fa-check')===-1, popped);
ck('...and the priority it does have is', /קריטית <i class="fa-solid fa-check">/.test(popped), popped);

// an item nobody has decided on: the tick is on the grey one
TASK.custom_fields={priority_unset:true};
fieldPicker({stopPropagation(){},currentTarget:{}},7,'priority',MAP);
ck('an undecided item ticks "טרם הוגדר"',
   /טרם הוגדר<i class="fa-solid fa-check">|טרם הוגדר <i class="fa-solid fa-check">/.test(popped), popped);
ck('...and ticks none of the priorities', !/קריטית <i class="fa-solid fa-check">/.test(popped), popped);

// ── what goes on the wire ──
TASK.custom_fields={priority_key:'x_blocker',priority_label:'חוסם',priority_color:'#FD5AC3'};
TASK.priority='high';
await setField(7,'priority','__unset');
ck('picking it sends an explicit null', posted && posted.priority===null, JSON.stringify(posted));
ck('...with the flag that says nobody chose', posted.custom_fields.priority_unset===true, JSON.stringify(posted));
ck('...and clears a board-defined priority it was carrying',
   posted.custom_fields.priority_key===null && posted.custom_fields.priority_label===null &&
   posted.custom_fields.priority_color===null, JSON.stringify(posted));
ck('...and says nothing about the status column, which is not being cleared',
   !('status' in posted) && !('status_unset' in posted.custom_fields), JSON.stringify(posted));
ck('the row on screen drops the old label and colour straight away',
   !('priority_key' in TASK.custom_fields) && !('priority_label' in TASK.custom_fields));
ck('...shows the undecided state', TASK.custom_fields.priority_unset===true);
ck('...and holds `medium`, where a new item\'s priority sits — never a null the sort cannot order',
   TASK.priority==='medium', 'priority='+TASK.priority);

// ── a normal pick is untouched, including the board-defined one ──
await setField(7,'priority','x_blocker');
ck('choosing a board priority still sends the engine value it behaves as',
   posted.priority==='high', JSON.stringify(posted));
ck('...with its own label and colour riding along',
   posted.custom_fields.priority_key==='x_blocker'&&posted.custom_fields.priority_label==='חוסם',
   JSON.stringify(posted));
ck('...and takes the undecided flag off', posted.custom_fields.priority_unset===null);
ck('...leaving nothing of it on the row', !('priority_unset' in TASK.custom_fields));

await setField(7,'priority','low');
ck('and a plain one of the five sends itself', posted.priority==='low', JSON.stringify(posted));
ck('...carrying no leftover key', posted.custom_fields.priority_key===null);

// ── the status column still behaves exactly as it did ──
// one `unsetTo` now serves both columns; a mix-up would send the wrong neutral
TASK.custom_fields={}; TASK.status='done';
await setField(7,'status','__unset');
ck('clearing a status still falls back to `todo`, not to the priority neutral',
   TASK.status==='todo' && posted.status===null, 'status='+TASK.status);
ck('...and still sets its own flag', posted.custom_fields.status_unset===true, JSON.stringify(posted));

env.isBoardAdmin=()=>true;
const adminPicker = make(grab('fieldPicker')+'; return fieldPicker;');
adminPicker({stopPropagation(){},currentTarget:{}},7,'priority',MAP);
ck('the manage shortcut DOES still span — it is an exit, not a value',
   /cell-pop-manage pop-span[^>]*>\s*<i[^>]*><\/i> ניהול עדיפויות/.test(popped), popped);
ck('...and it comes after the grey option, not before it',
   popped.indexOf('ניהול עדיפויות')>popped.indexOf('c4c4c4'), popped);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
