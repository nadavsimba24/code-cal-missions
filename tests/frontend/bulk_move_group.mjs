/* Moving a selection to a group costs ONE request, and the board is not
   refetched afterwards.

   It used to be a round trip per item — each renumbering the group the item
   left and the group it joined — and then GET /api/boards/{id} for the whole
   board. That is the slowness. The calls could not be fired together either:
   two renumbering one group at once leave two items claiming one position, and
   a row springs back. So the server does the set in one transaction and answers
   with the new order of every group it touched; this checks the client asks
   once and places its rows from that answer.
   Runs the real bulkMoveToGroup out of index.html.
   Driven by tests/test_bulk_move_group_frontend.py. */
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

async function move({answer, fail=false}){
  const calls=[];
  const tasks=[{id:1,group_id:10,position:0},{id:2,group_id:10,position:1},
               {id:3,group_id:11,position:0},{id:9,group_id:20,position:0}];
  const st={board:{id:5,tasks}};
  const log={renders:0, cleared:0, toasts:[]};
  const fn=new Function('st','api','withMe','_selectedTopItems','findAnyTask',
    'clearSelection','renderView','toast','closeCellPops',
    grab('bulkMoveToGroup')+'; return bulkMoveToGroup;')(
    st,
    async(url,opt)=>{ calls.push({url, method:(opt||{}).method, body:JSON.parse((opt||{}).body||'{}')});
                      if(fail) throw new Error('500');
                      return answer; },
    x=>JSON.stringify(x),
    ()=>[tasks[0],tasks[1],tasks[2]],
    id=>tasks.find(t=>t.id===id)||null,
    ()=>{log.cleared++;}, ()=>{log.renders++;}, m=>log.toasts.push(m), ()=>{});
  await fn({stopPropagation(){}}, 20);
  return {calls, tasks, log};
}

const ANSWER={
  moved:[{id:1,group_id:20,position:1},{id:2,group_id:20,position:2},{id:3,group_id:20,position:3}],
  unchanged:[], missing:[],
  order:[{group_id:20, ids:[9,1,2,3]}, {group_id:10, ids:[]}, {group_id:11, ids:[]}],
};

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

{
  const r=await move({answer:ANSWER});
  ck('three items cost exactly one request', r.calls.length===1,
     r.calls.map(c=>c.url).join(' | '));
  ck('...to the bulk endpoint of this board',
     r.calls[0].url==='/api/boards/5/items/move' && r.calls[0].method==='POST', r.calls[0].url);
  ck('...carrying every selected id and the target group',
     JSON.stringify(r.calls[0].body.ids)==='[1,2,3]' && r.calls[0].body.group_id===20,
     JSON.stringify(r.calls[0].body));
  ck('the board is NOT refetched afterwards',
     !r.calls.some(c=>c.url.startsWith('/api/boards/5?')||c.url==='/api/boards/5'),
     r.calls.map(c=>c.url).join(' | '));
  ck('every moved row is placed from the answer',
     r.tasks.filter(t=>[1,2,3].includes(t.id)).every(t=>t.group_id===20),
     JSON.stringify(r.tasks));
  ck('...in the positions the answer gives, dense and in order',
     [9,1,2,3].every((id,i)=>r.tasks.find(t=>t.id===id).position===i),
     JSON.stringify(r.tasks));
  ck('and the selection is cleared and the view drawn once',
     r.log.cleared===1 && r.log.renders===1);
  ck('the toast counts what moved', r.log.toasts[0].includes('3'), r.log.toasts.join('|'));
}
{
  // the answer says two of three were already there
  const r=await move({answer:{moved:[{id:3,group_id:20,position:1}], unchanged:[1,2], missing:[],
                              order:[{group_id:20,ids:[9,3]}]}});
  ck('a partial move says so rather than claiming them all',
     /1/.test(r.log.toasts[0]) && r.log.toasts[0].includes('כבר בקבוצה'), r.log.toasts.join('|'));
}
{
  const r=await move({answer:null, fail:true});
  ck('a refusal is reported and nothing is silently half-applied',
     r.log.toasts.some(t=>t.includes('שגיאה')) && r.tasks[0].group_id===10,
     r.log.toasts.join('|')+' '+JSON.stringify(r.tasks[0]));
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
