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

async function add({filters, group=7, view='table', paged=null}){
  const st={board:{id:1, groups:[GROUP], tasks:[{id:1, title:'קיים', status:'done',
                    assignees:[{id:9,name:'דנה'}], custom_fields:{}}]},
            filters:Object.assign({q:'',people:[],status:'',priority:'',sort:'',
                                   links:{col:'',mode:'',item:0}}, filters),
            view, colSort:null};
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
    +grab('applyFilters')+grab('byPosition')+grab('filtersActive')+grab('openNewItem')+'; return openNewItem;')(
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
    ()=>0, ()=>true, paged||{on:false,rows:[]}, ()=>[]);
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
{
  /* Past the client-filter threshold the rows on screen are the server's answer
     to the filter and the new item is not in it — and applyFilters, with the
     paging on, hands that page straight back whatever it is asked about. The
     old test "is the new row visible?" therefore answered yes about a row that
     was nowhere, and the item was created and hidden by the one route the
     clearing exists to prevent. */
  const r=await add({filters:{q:'תשתית'}, paged:{on:true, rows:[{id:1,title:'קיים'}]}});
  ck('a paged board clears its filter — the server page cannot hold the new item',
     r.log.cleared===1, JSON.stringify(r.log.toasts));
  ck('...and the rename still has a row to open', r.log.focused[0]===42);
}
{
  /* Only a table has rows, and the inline rename is a row. On a kanban board
     the item used to appear as a card already named "פריט חדש", with nothing
     to type into — the one thing the button promises. */
  const r=await add({filters:{}, view:'kanban'});
  ck('a view with no rows in it gives way to the table', r.st.view==='table');
  ck('...and that is said out loud',
     r.log.toasts.some(t=>t.includes('התצוגה הוחלפה לטבלה')), r.log.toasts.join('|'));
  ck('...and the rename is still what happens next', r.log.focused[0]===42);
}
{
  const r=await add({filters:{}, view:'table'});
  ck('the table is left alone', r.st.view==='table' && r.log.toasts.length===0,
     r.log.toasts.join('|'));
}
{
  // both at once is one sentence, because there is one toast element and the
  // second call would wipe the first before anybody read it
  const r=await add({filters:{people:[9]}, view:'gantt'});
  ck('a view change and a cleared filter are said together',
     r.log.toasts.length===1 && r.log.toasts[0]==='התצוגה הוחלפה לטבלה והסינון נוקה כדי להציג את הפריט החדש',
     JSON.stringify(r.log.toasts));
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
