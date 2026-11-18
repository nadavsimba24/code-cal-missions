/* The × on the last link chip, and what the cell shows after it.

   The × wrote the removal and the server obeyed it, and the chip stayed on
   screen anyway. The reason is in the answer, not in the request: a PATCH
   replies with the item's WHOLE custom_fields, and a column the server no
   longer holds is simply absent from it. The cell merged that answer over
   itself with Object.assign, which can add a key and overwrite a key and can
   never remove one — so the array that had just been emptied was put straight
   back, and renderView drew the chip it had been told to drop.

   Taking one link off a cell holding several always worked, because then the
   answer did carry the shorter list. It was the LAST one that would not go,
   which is also the only one most cells ever have. Two-way columns hid it
   again by refetching the whole board; a new "קישור בין לוחות" column is
   one-way unless somebody ticks the box, so this was the default.

   Runs the real unlinkFromCell and connectDisp out of index.html.
   Driven by tests/test_the_x_on_a_link_chip_empties_the_cell.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabFn(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
  throw new Error('unbalanced: '+name);
}

const esc = s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* The world the two functions run in. COLS is what the board says the column
   is; SENT is every request body the cell produced, so the test can check what
   the × asked for as well as what it did with the reply. */
let COLS=[], TASK=null, SENT=[], TOASTS=[], RENDERS=0, REPLY=null, BOARD_FETCHES=0;

function build(){
  return new Function('esc','findAnyTask','api','withMe','toast','customColumns',
    'renderView','st','canEditCol','linkInfo','linkText','openLinkedItem','resolveLinks',
    grabFn('applyCellResponse')
    +grabFn('unlinkFromCell')
    +grabFn('linkChipHTML')
    +grabFn('deletedWhy')
    +grabFn('connectDisp')
    +' return {unlinkFromCell,connectDisp,applyCellResponse};')(
    esc,
    () => TASK,
    async (url,opt)=>{
      if(/^\/api\/boards\//.test(url)){ BOARD_FETCHES++; return {id:1,columns:COLS,tasks:[]}; }
      SENT.push(JSON.parse(opt.body));
      if(REPLY instanceof Error) throw REPLY;
      return REPLY;
    },
    b=>JSON.stringify(b),
    m=>TOASTS.push(m),
    ()=>COLS,
    ()=>RENDERS++,
    {board:{id:1}},
    ()=>true,
    id=>({id,title:'פריט '+id,board_name:'לוח יעד'}),
    id=>'פריט '+id,
    ()=>{}, async ()=>{});
}

const F = build();
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+String(extra):''))); };
const EV={stopPropagation(){}};

function scene(colExtra,cell,reply){
  COLS=[Object.assign({id:'c_link',type:'connect',title:'קישור',
                       connect:{board_ids:[2],multiple:true}},colExtra||{})];
  TASK={id:7,custom_fields:{c_link:cell.slice()}};
  SENT=[]; TOASTS=[]; RENDERS=0; BOARD_FETCHES=0; REPLY=reply;
}

/* The answer a cleared cell really gets back: no key for the column at all.
   Written out rather than stubbed as "whatever was sent", because the absent
   key IS the thing this file exists for. */
const CLEARED = {id:7,group_id:null,custom_fields:{status_unset:true},event_ids:[]};

// ── the last link ─────────────────────────────────────────────────────────
scene(null,[42],CLEARED);
await F.unlinkFromCell(EV,7,'c_link',42);
ck('the × asks for the cell to be emptied',
   SENT.length===1 && SENT[0].custom_fields.c_link===null, JSON.stringify(SENT));
ck('and the cell is empty once the answer is in',
   !(TASK.custom_fields.c_link||[]).length, JSON.stringify(TASK.custom_fields));
ck('so the column goes back to offering a link, not to showing the one removed',
   /קשר פריט/.test(F.connectDisp(TASK.custom_fields.c_link,7,'c_link')),
   F.connectDisp(TASK.custom_fields.c_link,7,'c_link'));
ck('and the grid is redrawn', RENDERS===1, RENDERS);

// ── one of several — the case that always worked, kept working ────────────
scene(null,[42,43],{id:7,custom_fields:{c_link:[43]}});
await F.unlinkFromCell(EV,7,'c_link',42);
ck('taking one of two off sends the rest',
   SENT[0].custom_fields.c_link.join()==='43', JSON.stringify(SENT));
ck('and the other one stays in the cell',
   TASK.custom_fields.c_link.join()==='43', JSON.stringify(TASK.custom_fields));
ck('which is the only chip the cell now draws',
   (F.connectDisp(TASK.custom_fields.c_link,7,'c_link').match(/class="link-chip"/g)||[]).length===1,
   F.connectDisp(TASK.custom_fields.c_link,7,'c_link'));

// ── a two-way column is not reconciled from the answer ────────────────────
/* Its links live in item_links and never appear in custom_fields, so the
   answer cannot speak for the column at all. Clearing one of its cells is
   settled by the board it refetches — and dropping the key here on the
   strength of an answer that was never going to mention it would empty a
   two-way cell that still has links in it. */
scene({connect:{board_ids:[2],multiple:true,two_way:true}},[42],CLEARED);
await F.unlinkFromCell(EV,7,'c_link',42);
ck('a two-way cell is not rewritten from an answer that cannot mention it',
   (TASK.custom_fields.c_link||[]).join()==='42', JSON.stringify(TASK.custom_fields));
ck('it takes the board fresh instead, and renders from that',
   BOARD_FETCHES===1 && RENDERS===1, BOARD_FETCHES+'/'+RENDERS);

// ── a write that did not land leaves the cell alone ───────────────────────
scene(null,[42],new Error('nope'));
await F.unlinkFromCell(EV,7,'c_link',42);
ck('a failed removal keeps the link on screen',
   (TASK.custom_fields.c_link||[]).join()==='42', JSON.stringify(TASK.custom_fields));
ck('and says so', TOASTS.length===1 && /נכשלה/.test(TOASTS[0]), TOASTS);
ck('rather than redrawing a grid nothing changed in', RENDERS===0, RENDERS);

// ── applyCellResponse on its own: it adds, overwrites and removes ─────────
const t={custom_fields:{c_link:[1],other:'נשאר'}};
COLS=[{id:'c_link',type:'connect',connect:{board_ids:[2]}}];
F.applyCellResponse(t,{custom_fields:{other:'נשאר',extra:3}},['c_link']);
ck('a column absent from the answer is a column the cell lets go',
   !('c_link' in t.custom_fields), JSON.stringify(t.custom_fields));
ck('and a column nobody wrote to is left exactly where it was',
   t.custom_fields.other==='נשאר' && t.custom_fields.extra===3, JSON.stringify(t.custom_fields));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
