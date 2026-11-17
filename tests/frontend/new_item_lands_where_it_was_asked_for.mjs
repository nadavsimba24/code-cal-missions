/* הוספת פריט — הפריט נוחת במקום שהכפתור הבטיח.

   Two ways in, two places. The "+ הוסף פריט" line is the last row of a group
   and means the row after it; the "פריט חדש" button sits above the whole board
   and means the top of it. Only the second says so, by sending position 0.

   And the order the board draws: until now the rows were drawn in whatever
   order the tasks array happened to be in. That is the same as the board's own
   order right up to the moment something changes one without rebuilding the
   other — a bulk "העברה לקבוצה" writes the new positions from the server's
   answer and leaves the array alone, a new row is pushed onto the end of it
   whichever end of the group it belongs to — and then a re-render draws the
   group in an order nobody recognises, which is what adding an item does.

   Runs the real openNewItem, applyFilters and byPosition out of index.html.
   Driven by tests/test_a_new_item_lands_where_it_was_asked_for.py. */
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

const GID=7;
/* a group as it comes off the server: three items, in order, numbered */
const rows=()=>[{id:11,title:'א',group_id:GID,position:0,status:'backlog',assignees:[],custom_fields:{}},
                {id:12,title:'ב',group_id:GID,position:1,status:'backlog',assignees:[],custom_fields:{}},
                {id:13,title:'ג',group_id:GID,position:2,status:'backlog',assignees:[],custom_fields:{}}];

function world(tasks){
  const st={board:{id:1,groups:[{id:GID,task_status:'backlog'}],tasks},
            filters:{q:'',people:[],status:'',priority:'',sort:'',links:{col:'',mode:'',item:0}},
            view:'table',colSort:null};
  const log={posted:null};
  const api=async(url,opt)=>{
    log.posted=JSON.parse(opt.body);
    /* the server answers with the item it made, placed: position 0 when one
       was asked for, past the last of the group when none was */
    const sibs=st.board.tasks.filter(x=>x.group_id===log.posted.group_id&&!x.parent_id);
    const pos=log.posted.position!=null ? 0
            : sibs.reduce((m,x)=>Math.max(m,x.position==null?-1:x.position),-1)+1;
    return {id:42,title:'פריט חדש',group_id:log.posted.group_id,position:pos,
            status:'backlog',assignees:[],custom_fields:{status_unset:true}};
  };
  const fn=new Function('st','api','withMe','renderView','clearFilters','toast',
    'focusNewItemTitle','setTimeout','defaultGroupId','statusKeyOf','priorityKeyOf',
    'linkIdsOf','linkNamesOf','window','IS_ITEM_ID','setGroupCollapsed',
    'advCount','advMatch','Paged','customColumns',
    grab('cellWords')+grab('fdatePlain')+grab('cellSearchWords')+grab('searchWordsOf')+grab('searchRow')
    +grab('applyFilters')+grab('byPosition')+grab('filtersActive')+grab('openNewItem')
    +'; return {openNewItem, applyFilters};')(
    st, api, x=>JSON.stringify(x), ()=>{}, ()=>{}, ()=>{}, ()=>{}, f=>f(), ()=>GID,
    t=>t.status, t=>t.priority||'', ()=>[], ()=>[], {}, /^\d{3,}$/, ()=>{},
    ()=>0, ()=>true, {on:false,rows:[]}, ()=>[]);
  // what the group looks like on screen: the rows in the order they are drawn
  const drawn=()=>fn.applyFilters(st.board.tasks).filter(t=>t.group_id===GID).map(t=>t.title);
  return {st,log,drawn,add:fn.openNewItem};
}

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the line at the foot of a group ──
{
  const w=world(rows());
  await w.add(GID);
  ck('the group\'s own line asks for no place', w.log.posted.position===undefined,
     JSON.stringify(w.log.posted.position));
  ck('...and the new row is the last one', w.drawn().join()==='א,ב,ג,פריט חדש', w.drawn().join());
}

// ── the button above the board ──
{
  const w=world(rows());
  await w.add(null,true);
  ck('the button at the top of the board asks for the top', w.log.posted.position===0);
  ck('...and the new row is the first one', w.drawn().join()==='פריט חדש,א,ב,ג', w.drawn().join());
  ck('...with the group moved down to make room, not tied with it',
     w.st.board.tasks.filter(t=>t.id!==42).map(t=>t.position).join()==='1,2,3',
     w.st.board.tasks.map(t=>t.id+':'+t.position).join(' '));
}
{
  /* The tie this prevents: the new item and the item that was first both
     holding 0, broken by id — and the new row, whose id is the largest on the
     board, lands second under a button that promised the top. */
  const w=world(rows());
  await w.add(null,true);
  const first=w.st.board.tasks.find(t=>t.id===11);
  ck('nothing else is left claiming the top', first.position!==0, 'id 11 still at 0');
}

// ── the order the board draws, which is the board's own ──
{
  /* the array after a bulk "העברה לקבוצה": the positions are the server's
     answer, the array was never rebuilt from it */
  const scrambled=[{id:13,title:'ג',group_id:GID,position:2,assignees:[],custom_fields:{}},
                   {id:11,title:'א',group_id:GID,position:0,assignees:[],custom_fields:{}},
                   {id:12,title:'ב',group_id:GID,position:1,assignees:[],custom_fields:{}}];
  const w=world(scrambled);
  ck('a group is drawn in its own order, not the array\'s',
     w.drawn().join()==='א,ב,ג', w.drawn().join());
  await w.add(GID);
  ck('...and an item added to it is still the last row',
     w.drawn().join()==='א,ב,ג,פריט חדש', w.drawn().join());
}
{
  // two items left holding one number by a restore: the older one leads
  const tied=[{id:30,title:'ב',group_id:GID,position:1,assignees:[],custom_fields:{}},
              {id:20,title:'א',group_id:GID,position:1,assignees:[],custom_fields:{}}];
  const w=world(tied);
  ck('a tie is broken the way the server breaks it — by id',
     w.drawn().join()==='א,ב', w.drawn().join());
}
{
  // an item with no number at all sorts last rather than first
  const half=[{id:20,title:'ללא',group_id:GID,assignees:[],custom_fields:{}},
              {id:21,title:'א',group_id:GID,position:0,assignees:[],custom_fields:{}}];
  const w=world(half);
  ck('an item carrying no position is not promoted to the top',
     w.drawn().join()==='א,ללא', w.drawn().join());
}

// ── a sort somebody asked for still wins ──
{
  const w=world(rows());
  w.st.filters.sort='title';
  w.st.board.tasks[0].title='ת';          // last alphabetically, first by position
  ck('the toolbar\'s מיון comes before the board\'s own order',
     w.drawn().join()==='ב,ג,ת', w.drawn().join());
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
