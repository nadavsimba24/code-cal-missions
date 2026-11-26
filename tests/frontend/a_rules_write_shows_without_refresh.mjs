/* "כאשר הסטטוס משתנה, עדכן את «תאריך עדכון» להיום" — the date on screen.
   Driven by tests/test_a_rules_write_shows_without_refresh.py.

   Runs the real setField, setCell and applyWriteEcho out of index.html. The
   rule runs inside the PATCH, so the answer already carries the date it
   wrote; the grid used to read only group_id out of that answer and wait for
   the live stream, and when the stream's event did not arrive the date showed
   only after F5. What is pinned: the date in the answer reaches the row and
   the row is redrawn, for the built-in status and for a status column alike,
   and the answer never undoes the cell the person themselves just wrote. */
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

let TASK, answer, redrawn;
const st={colSort:null};
const env={
  st,
  STATUS_UNSET_KEY:'__unset',
  findAnyTask:()=>TASK,
  canEditCol:()=>true,
  statusEntry:k=>({done:{key:'done',he:'בוצע',c:'#1AC877',base:'done'}})[k]||null,
  priorityEntry:()=>null,
  withMe:b=>JSON.stringify(b),
  api:async()=>answer,
  refreshRow:(id,whole,changed)=>{ redrawn.push({id,whole,changed}); },
  toast:()=>{},
  Live:{busy:()=>false},
};
const names=Object.keys(env);
const make = code => new Function(...names, code).apply(null, names.map(n=>env[n]));
const helpers = grab('applyWriteEcho');
const setField = make(helpers+grab('setField')+'; return setField;');
const setCell  = make(helpers+grab('setCell')+'; return setCell;');

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};
const TODAY='2026-11-26';

// ── the built-in status, the second change of the day after a manual edit ──
TASK={id:7,status:'in_progress',group_id:3,parent_id:null,custom_fields:{col_date1:'2020-01-01'}};
answer={id:7,group_id:3,custom_fields:{col_date1:TODAY}};
redrawn=[];
await setField(7,'status','done');
ck('the date the rule wrote is on the row at once', TASK.custom_fields.col_date1===TODAY,
   JSON.stringify(TASK.custom_fields));
ck('...and the row is drawn again after the answer', redrawn.length===1, JSON.stringify(redrawn));

// ── a status column ──
TASK={id:8,status:'todo',group_id:3,parent_id:null,custom_fields:{col_stat0:{id:'a'}}};
answer={id:8,group_id:3,custom_fields:{col_stat0:{id:'b'},col_date1:TODAY}};
redrawn=[];
await setCell(8,'col_stat0',{id:'b'});
ck('a status column\'s rule lands the same way', TASK.custom_fields.col_date1===TODAY,
   JSON.stringify(TASK.custom_fields));
ck('...and redraws the row', redrawn.length===1, JSON.stringify(redrawn));

// ── nothing else moved: no extra redraw ──
TASK={id:9,status:'todo',group_id:3,parent_id:null,custom_fields:{}};
answer={id:9,group_id:3,custom_fields:{col_txt:'x'}};
redrawn=[];
await setCell(9,'col_txt','x');
ck('an answer that only repeats the edit redraws nothing', redrawn.length===0, JSON.stringify(redrawn));

// ── the answer to an older request does not undo a newer keystroke ──
TASK={id:10,status:'todo',group_id:3,parent_id:null,custom_fields:{col_txt:'newer'}};
const moved=make(helpers+'; return applyWriteEcho;')(TASK,{custom_fields:{col_txt:'older',col_date1:TODAY}},'col_txt');
ck('the person\'s own cell is left as they last typed it', TASK.custom_fields.col_txt==='newer');
ck('...while the rule\'s column is taken', TASK.custom_fields.col_date1===TODAY && moved.join()==='col_date1');

// ── sorted by the stamped column: the row may move, so the whole view ──
st.colSort={key:'col_date1'};
TASK={id:11,status:'todo',group_id:3,parent_id:null,custom_fields:{}};
answer={id:11,group_id:3,custom_fields:{col_date1:TODAY}};
redrawn=[];
await setField(11,'status','done');
ck('sorted by the date the rule wrote, the whole view is redrawn',
   redrawn.length===1 && redrawn[0].whole===true, JSON.stringify(redrawn));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
