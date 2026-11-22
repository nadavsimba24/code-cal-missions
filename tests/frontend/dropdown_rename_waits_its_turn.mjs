/* A rename of a list option waits its turn behind the column's other saves,
   and a rename field that leaves the page is not taken as a rename.

   Every option save sends the whole column, so whatever runs second wins.
   A rename used to go straight to the server while an add or a deactivate,
   started a moment later, sent a column built from the list as it was before
   the rename: on the server that read as the new word being deleted — a 409
   about an option nobody deleted, or worse, a column put back to the old word
   while its cells already said the new one. Now every save takes the same
   per-column turn (ddTakeTurn), and the ones queued behind a rename follow the
   option to its new name.

   The second half is the redraw: rebuilding the edit rows removes the focused
   field, Chromium fires blur on a field it removes, and blur commits a rename
   — so a half-typed word was renamed onto every item on the board.

   Driven by tests/test_dropdown_rename_waits_its_turn.py. */
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
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

function world(){
  const W={log:[], toasts:[]};
  /* The server: one column, stored. A whole-column save that drops a word
     items wear is refused, as the real column PATCH refuses it. */
  W.server={id:'c',type:'dropdown',options:['A','B'],inactive_options:[]};
  const worn=new Set(['A','A2']);
  W.st={board:{id:1,columns:[JSON.parse(JSON.stringify(W.server))]}};
  const saveColumns=async cols=>{
    const c=cols[0]; W.log.push('PATCH '+c.options.join(',')+(c.inactive_options.length?' inactive='+c.inactive_options:''));
    await sleep(20);
    const dropped=W.server.options.filter(o=>!c.options.includes(o));
    if(dropped.some(o=>worn.has(o))){ W.log.push('409'); return false; }
    W.server=JSON.parse(JSON.stringify(c)); W.st.board.columns=[JSON.parse(JSON.stringify(c))]; return true;
  };
  const api=async(p,o)=>{
    const b=JSON.parse(o.body); W.log.push('RENAME '+b.from+'->'+b.to); await sleep(50);
    W.server={...W.server,options:W.server.options.map(x=>x===b.from?b.to:x),
              inactive_options:W.server.inactive_options.map(x=>x===b.from?b.to:x)};
    return {column:JSON.parse(JSON.stringify(W.server)),items:3,from:b.from,to:b.to};
  };
  const fns=['dropdownOpts','dropdownInactive','ddAddKey','ddRefreshPop','ddFlush','ddTakeTurn','ddSaveCol',
             'ddRenameCommit','ddAdoptRename','ddCurrentWord','ddToggleActive'];
  W.f=new Function('st','api','saveColumns','customColumns','isBoardAdmin','toast','closeCellPops','document',
    'withMe','loadedRows','renderView','buildDropdownPop',
    'const _ddPending={},_ddSaving={},_ddRenamed={};let _ddRedrawing=0;\n'+fns.map(grab).join('\n')
    +'\nreturn {'+fns.join(',')+',_ddSaving,_ddPending};')(
    W.st, api, saveColumns, ()=>W.st.board.columns, ()=>true, m=>W.toasts.push(m), ()=>{},
    {querySelector:()=>null, activeElement:null}, JSON.stringify, ()=>[], ()=>{}, ()=>{});
  W.idle=async()=>{ while(W.f._ddSaving.c) await sleep(5); };
  return W;
}

{ // rename A→A2 in flight, then add C, then deactivate A
  const W=world();
  const inp={defaultValue:'A',value:'A2',isConnected:true,select(){}};
  const pr=W.f.ddRenameCommit(inp,'c',true);
  await sleep(5);
  W.f.ddAddKey({key:'Enter',isComposing:false,target:{value:'C',select(){}},preventDefault(){},stopPropagation(){}},'c');
  const pop={isConnected:false,_ddMenu:'A',closest(){return pop;}};
  const tg=W.f.ddToggleActive({stopPropagation(){},target:pop},'c');
  await pr; await tg; await W.idle();
  ck('the rename goes first and nothing is sent while it is in flight',
     W.log[0]==='RENAME A->A2' && W.log.length>1 && W.log[1].startsWith('PATCH'), JSON.stringify(W.log));
  ck('no save is refused for deleting a word nobody deleted', !W.log.includes('409'), JSON.stringify(W.log));
  ck('the word typed during the rename is saved, next to the renamed one',
     JSON.stringify(W.server.options)===JSON.stringify(['A2','B','C']), JSON.stringify(W.server));
  ck('the deactivate queued behind the rename follows the option to its new name',
     JSON.stringify(W.server.inactive_options)===JSON.stringify(['A2']), JSON.stringify(W.server));
  ck('nothing is left waiting', !(W.f._ddPending.c||[]).length && !W.f._ddSaving.c);
}
{ // a field the redraw removed is not a rename
  const W=world();
  const gone={defaultValue:'A',value:'Ur',isConnected:false,select(){}};
  await W.f.ddRenameCommit(gone,'c',false);
  await sleep(80);
  ck('a rename field no longer on the page sends nothing', W.log.length===0, JSON.stringify(W.log));
  ck('…and the column keeps its word', JSON.stringify(W.server.options)===JSON.stringify(['A','B']));
}

{ // a numeric option, from an import
  const W=world();
  W.server={...W.server,options:['A',3]}; W.st.board.columns=[JSON.parse(JSON.stringify(W.server))];
  await W.f.ddRenameCommit({defaultValue:'A',value:'B2',isConnected:true,select(){}},'c',true);
  await W.idle();
  ck('a numeric option elsewhere in the column does not stop a rename',
     W.log[0]==='RENAME A->B2' && JSON.stringify(W.server.options)===JSON.stringify(['B2',3]), JSON.stringify(W.log));
  await W.f.ddRenameCommit({defaultValue:'3',value:'שלוש',isConnected:true,select(){}},'c',true);
  await W.idle();
  ck('the numeric option itself can be renamed from the text the field holds',
     W.log.includes('RENAME 3->שלוש'), JSON.stringify(W.log));
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
