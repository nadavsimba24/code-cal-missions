/* Adding an item puts it on screen — whatever the board is filtered to.

   A new item has nobody assigned, no priority, no link, no status anyone chose
   and a placeholder title, so it answers almost no filter and almost no search.
   With one active it used to be created and hidden in the same breath: no row
   appeared, the inline rename had nothing to open, and clicking again just made
   a second one. Runs the real openNewItem, applyFilters and filtersActive out
   of index.html. Driven by tests/test_new_item_visible.py. */
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

const GROUP={id:7, task_status:'backlog'};

async function add({filters, group=7}){
  const st={board:{id:1, groups:[GROUP], tasks:[{id:1, title:'קיים', status:'done',
                    assignees:[{id:9,name:'דנה'}], custom_fields:{}}]},
            filters:Object.assign({q:'',people:[],status:'',priority:'',sort:'',
                                   links:{col:'',mode:'',item:0}}, filters),
            colSort:null};
  const log={rendered:0, cleared:0, toasts:[], focused:[], posted:null, unfolded:[]};
  const made={id:42, title:'פריט חדש', group_id:group, status:'backlog',
              assignees:[], custom_fields:{status_unset:true}};
  const fn=new Function('st','api','withMe','renderView','clearFilters','toast',
    'focusNewItemTitle','setTimeout','defaultGroupId','statusKeyOf','priorityKeyOf',
    'linkIdsOf','linkNamesOf','window','IS_ITEM_ID','setGroupCollapsed',
    // applyFilters and filtersActive now also consult the advanced condition
    // tree; these cases build none, so it counts nothing and matches all
    'advCount','advMatch','Paged',
    // …and the search box reads the board's own cells now. This board carries
    // no columns, so searchWordsOf comes back to the title and the description.
    'customColumns',
    grab('cellWords')+grab('fdatePlain')+grab('cellSearchWords')+grab('searchWordsOf')+grab('searchRow')
    +grab('applyFilters')+grab('filtersActive')+grab('openNewItem')+'; return openNewItem;')(
    st,
    async(url,opt)=>{ log.posted=JSON.parse(opt.body); return made; },
    x=>JSON.stringify(x),
    ()=>{log.rendered++;},
    ()=>{log.cleared++; st.filters={q:'',people:[],status:'',priority:'',sort:'',links:{col:'',mode:'',item:0},adv:null};},
    m=>log.toasts.push(m),
    id=>log.focused.push(id),
    f=>f(),
    ()=>7,
    t=>t.status, t=>t.priority||'', ()=>[], ()=>[], {}, /^\d{3,}$/,
    (gid,shut)=>log.unfolded.push([gid,shut]),
    ()=>0, ()=>true, {on:false,rows:[]}, ()=>[]);
  await fn(group);
  return {log, st, visible:st.board.tasks.length};
}

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

{
  const r=await add({filters:{}});
  ck('with no filter the board simply re-renders', r.log.rendered===1 && r.log.cleared===0);
  ck('and the new item opens for renaming', r.log.focused[0]===42);
  ck('nothing is said that does not need saying', r.log.toasts.length===0, r.log.toasts.join('|'));
}
{
  // the filter that bit: someone else's items only, so a new item has no chance
  const r=await add({filters:{people:[9]}});
  ck('a people filter that would hide the new item is cleared', r.log.cleared===1);
  ck('...and it is said out loud', r.log.toasts.some(t=>t.includes('הסינון נוקה')), r.log.toasts.join('|'));
  ck('...so the rename still has a row to open', r.log.focused[0]===42);
}
{
  const r=await add({filters:{q:'תשתית'}});
  ck('a search the new title cannot match is cleared too', r.log.cleared===1, JSON.stringify(r.log.toasts));
}
{
  const r=await add({filters:{status:'done'}});
  ck('so is a status filter the new item does not answer', r.log.cleared===1);
}
{
  // a filter the new item DOES satisfy is left alone — clearing it would be rude
  const r=await add({filters:{q:'פריט'}});
  ck('a filter the new item answers is kept', r.log.cleared===0 && r.log.rendered===1,
     JSON.stringify(r.log.toasts));
}
{
  const r=await add({filters:{sort:'title'}});
  ck('an arrangement is not a filter and is never cleared', r.log.cleared===0);
}
{
  const r=await add({filters:{}});
  ck('the group it lands in is opened, in case it was folded shut',
     r.log.unfolded.some(([gid,shut])=>gid===7 && shut===false), JSON.stringify(r.log.unfolded));
}
{
  const r=await add({filters:{}, group:7});
  ck('the item is created in the group whose row was clicked',
     r.log.posted.group_id===7 && r.log.posted.status==='backlog', JSON.stringify(r.log.posted));
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
