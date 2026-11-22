/* A list column's options are typed one after another in the popover, Enter
   moving straight on to the next — and none of them is lost on the way.

   Adding an option used to be a browser prompt() per word, so the list closed
   behind every one. With the field kept open, a second Enter arrives while the
   first save is still in flight, and every save sends the WHOLE column list:
   two overlapping saves would let the slower one write back a list without
   the other's word. So the words queue in _ddPending and ddFlush sends them
   one save at a time. This drives the real ddAddKey / ddFlush over a
   saveColumns that answers slowly, and checks what the server ends up with.

   Driven by tests/test_dropdown_options_typed_in_a_row.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d)return src.slice(m.index,j+1);} }
  throw new Error('unbalanced '+name);
}
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

function world(){
  const W={board:{columns:[{id:'c_kind',type:'dropdown',title:'סוג',options:['תשתיות']}]},
           saves:[], toasts:[], closed:0, admin:true, refuse:false};
  const saveColumns=async(cols)=>{
    W.saves.push(cols.find(c=>c.id==='c_kind').options.slice());
    await new Promise(r=>setTimeout(r,30));          // the server is slow
    if(W.refuse) return false;
    W.board.columns=JSON.parse(JSON.stringify(cols)); // what it stored comes back
    return true;
  };
  const body=['dropdownOpts','ddAddKey','ddRefreshPop','ddFlush'].map(grab).join('\n');
  const api=new Function('customColumns','saveColumns','isBoardAdmin','toast','closeCellPops','document',
    'const _ddPending={}, _ddSaving={};\n'+body+'\nreturn {ddAddKey,ddFlush,_ddPending,_ddSaving};')(
    ()=>W.board.columns, saveColumns, ()=>W.admin, m=>W.toasts.push(m), ()=>W.closed++,
    {querySelector:()=>null});
  W.api=api;
  W.type=(word,key='Enter')=>{
    const inp={value:word, select(){}};
    const e={key, isComposing:false, target:inp, preventDefault(){}, stopPropagation(){}};
    api.ddAddKey(e,'c_kind'); return inp;
  };
  W.idle=async()=>{ while(api._ddSaving.c_kind) await new Promise(r=>setTimeout(r,5)); };
  return W;
}
const opts=W=>W.board.columns[0].options;

{ // three words, typed faster than the server answers
  const W=world();
  const a=W.type('גינון'), b=W.type('תאורה'), c=W.type('ניקיון');
  ck('Enter empties the field for the next word', a.value===''&&b.value===''&&c.value==='');
  await W.idle();
  ck('every word typed reaches the column, in order',
     JSON.stringify(opts(W))===JSON.stringify(['תשתיות','גינון','תאורה','ניקיון']), JSON.stringify(opts(W)));
  ck('the saves never overlap — the words behind the first go in one more save, not three',
     W.saves.length===2, JSON.stringify(W.saves));
  ck('nothing is left waiting', !(W.api._ddPending.c_kind||[]).length);
}
{ // the same word twice is refused, whatever its case or spacing
  const W=world();
  const inp=W.type('  תשתיות ');
  ck('a word the list already has is not added again', W.saves.length===0 && opts(W).length===1);
  ck('…and the person is told so, with the word left to fix', W.toasts.length===1 && inp.value==='  תשתיות ');
  W.type('Road'); W.type('road'); await W.idle();
  ck('a word still on its way counts as already there',
     JSON.stringify(opts(W))===JSON.stringify(['תשתיות','Road']), JSON.stringify(opts(W)));
}
{ // empty Enter, Escape, and someone who is not the admin
  const W=world();
  W.type('   '); ck('Enter on an empty field saves nothing', W.saves.length===0);
  W.type('x','Escape'); ck('Escape closes the list without saving', W.closed===1 && W.saves.length===0);
  W.admin=false; W.type('גינון'); await W.idle();
  ck('only the board admin adds options', W.saves.length===0 && opts(W).length===1);
}
{ // a refusal does not loop forever on the same body
  const W=world(); W.refuse=true;
  W.type('גינון'); await W.idle();
  ck('a refused save is tried once and the queue is cleared',
     W.saves.length===1 && !(W.api._ddPending.c_kind||[]).length);
}
{ // an imported column can hold a number, not the text of one
  const W=world(); W.board.columns[0].options=['תשתיות',3];
  let threw=null; try{ W.type('גינון'); }catch(e){ threw=e; }
  await W.idle();
  ck('a numeric option does not stop a word being added', !threw && opts(W).includes('גינון'), String(threw));
  W.type('3'); await W.idle();
  ck('and its text still counts as already in the list', opts(W).filter(o=>String(o)==='3').length===1, JSON.stringify(opts(W)));
}
ck('no option is added through a browser prompt any more', !/prompt\('אפשרות חדשה/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
