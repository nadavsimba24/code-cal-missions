/* A filter is about the values, not about the ids it once answered with.

   The server can answer a filter, and its answer is a LIST OF ITEM IDS. A list
   of ids is a photograph: it cannot know that one of the items in it has since
   been edited. Filtering a board by סטטוס "בדיקה" and setting a row to "נבדק
   ותקין" left the row sitting on screen — its id was still in the answer — and
   the opposite was the same bug the other way round: a row edited INTO the
   filter stayed hidden.

   These checks are about the answer being retired the moment an item is
   written to, whoever wrote it, and about the window where two writes and one
   reply race each other.

   Driven by tests/test_filter_follows_an_edit.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i = src.indexOf('{', m.index), d = 0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index, j+1);} }
  throw new Error('unbalanced: '+name);
}
const konst = name => {
  const m = new RegExp(`^(?:const|let) ${name}\\s*=[\\s\\S]*?;$`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  return m[0];
};

/* The filter engine verbatim — the kinds table down to the id pattern — which
   is where advAskServer, advAnswerStale and advWrote live, with applyFilters
   taken from just below it. */
const engine = src.slice(src.indexOf('const ADV_KINDS = {'), src.indexOf('const IS_ITEM_ID='))
  + konst('IS_ITEM_ID') + '\n' + grab('applyFilters') + '\n';

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+JSON.stringify(x):''))); };

const STATUSES=[{key:'check',he:'בדיקה'},{key:'ok',he:'נבדק ותקין'}];

function world(){
  const st={
    board:{id:1, col_perms:{}, columns:[],
           tasks:[{id:1,title:'א',status:'check'},
                  {id:2,title:'ב',status:'check'},
                  {id:3,title:'ג',status:'ok'}]},
    users:[], me:{id:7}, colSort:null,
    filters:{q:'',people:[],status:'',priority:'',sort:'',
             links:{col:'',mode:'',item:0},adv:null,advIds:null},
  };
  const sent=[];                      // every call that went out through api()
  let reply=null;                     // what /items/query answers with next
  const api=async(p,o)=>{
    sent.push({p,m:((o||{}).method||'GET')});
    // the real api() retires the answer on the way out of a write
    f.advWrote(p,o);
    if(/items\/query$/.test(p)) return {item_ids:(reply||[]).slice()};
    return {};
  };
  const renders=[], said=[];
  const paged={on:false,rows:[],total:0};
  const f=new Function('st','meId','customColumns','boardStatusList','boardPriorityList',
    'boardPeople','statusColOpts','statusKeyOf','priorityKeyOf','api','withMe',
    'filterMode','renderView','refreshToolbar','reArrange','Paged','linkIdsOf',
    'linkNamesOf','colCompare','prioOrder','toast',
    engine + `;return {applyFilters,advAskServer,advAnswerStale,advWrote,advToggle,
                       advCount,advMatch,writes:()=>_advWrites,
                       pageOn:v=>{Paged.on=v;}};`)(
    st, ()=>st.me&&st.me.id, ()=>st.board.columns,
    ()=>STATUSES.map(s=>({key:s.key,he:s.he,c:'#ccc'})),
    ()=>[], ()=>[], ()=>[],
    t=>t.status||null, t=>t.priority||null,
    (p,o)=>api(p,o), b=>JSON.stringify(b||{}),
    ()=>'client', ()=>renders.push(1), ()=>{}, ()=>{},
    paged, ()=>[], ()=>[], ()=>0, ()=>0, m=>said.push(m));
  return {st, f, sent, renders, setReply:v=>{reply=v;}, toasts:()=>said};
}

const titles = (f,st) => f.applyFilters(st.board.tasks).map(t=>t.title).join(',');
const sleep = ms => new Promise(r=>setTimeout(r,ms));

// ── the reported bug ──────────────────────────────────────────────────────
{
  const {st,f,setReply} = world();
  f.advToggle('status','eq','check');          // סינון: הסטטוס הוא "בדיקה"
  setReply([1,2]);
  await f.advAskServer();
  ck('the server answers, and the board shows what it named', titles(f,st)==='א,ב', titles(f,st));

  st.board.tasks[0].status='ok';               // "בדיקה" → "נבדק ותקין"
  ck('…and the row still answers the old list until something retires it',
     titles(f,st)==='א,ב', titles(f,st));
  f.advWrote('/api/tasks/1',{method:'PATCH'});
  ck('a row edited out of the filter leaves the board', titles(f,st)==='ב', titles(f,st));
}
{
  /* The same bug the other way round, which is the half that would have been
     missed by keeping the id set and merely intersecting with it. */
  const {st,f,setReply} = world();
  f.advToggle('status','eq','check');
  setReply([1,2]);
  await f.advAskServer();
  st.board.tasks[2].status='check';            // ג edited INTO the filter
  f.advWrote('/api/tasks/3',{method:'PATCH'});
  ck('a row edited into the filter appears', titles(f,st)==='א,ב,ג', titles(f,st));
}

// ── what counts as a write ────────────────────────────────────────────────
{
  const {st,f,setReply} = world();
  f.advToggle('status','eq','check');
  setReply([1,2]);
  await f.advAskServer();
  const answered = () => st.filters.advIds instanceof Set;
  f.advWrote('/api/tasks/1',{});
  ck('reading an item is not writing to it', answered());
  f.advWrote('/api/boards/1/views',{method:'POST'});
  ck('…and neither is saving a view', answered());
  f.advWrote('/api/tasks',{method:'POST'});
  ck('creating an item retires the answer', !answered());
  await f.advAskServer();
  f.advWrote('/api/tasks/1/assignees?x=1',{method:'POST'});
  ck('…so does a write under the item, query string and all', !answered());
  await f.advAskServer();
  f.advWrote('/api/tasks/1',{method:'DELETE'});
  ck('…and so does deleting one', !answered());
}
{
  /* The filter's own question must not retire the filter's own answer: it is
     a POST, and a rule written by matching "any POST" would have looped. */
  const {st,f,setReply} = world();
  f.advToggle('status','eq','check');
  setReply([1,2]);
  await f.advAskServer();
  ck('asking the server does not retire what it just answered',
     st.filters.advIds instanceof Set);
}

// ── two writes and one reply ──────────────────────────────────────────────
{
  /* An answer that was asked for BEFORE a write describes the board before
     that write. Storing it would put the stale list back a moment after it was
     dropped — the reported bug again, with a delay on it. */
  const {st,f,setReply} = world();
  f.advToggle('status','eq','check');
  setReply([1,2]);
  const inflight = f.advAskServer();
  st.board.tasks[0].status='ok';
  f.advWrote('/api/tasks/1',{method:'PATCH'});   // …while the question is out
  await inflight;
  ck('an answer overtaken by a write is refused', !(st.filters.advIds instanceof Set));
  ck('…and the board goes on reading the values it has', titles(f,st)==='ב', titles(f,st));
}

// ── and it asks again, once the typing stops ──────────────────────────────
{
  const {st,f,sent,setReply} = world();
  f.advToggle('status','eq','check');
  setReply([1,2]);
  await f.advAskServer();
  const before = sent.filter(c=>/items\/query$/.test(c.p)).length;
  for(const id of [1,2,3]) f.advWrote('/api/tasks/'+id,{method:'PATCH'});
  await sleep(700);
  const after = sent.filter(c=>/items\/query$/.test(c.p)).length;
  ck('a burst of writes asks the server once more, not once each',
     after===before+1, {before,after});
}
{
  const {f,sent} = world();           // nothing is filtering
  f.advWrote('/api/tasks/1',{method:'PATCH'});
  await sleep(700);
  ck('with no filter on, a write asks nothing at all',
     !sent.some(c=>/items\/query$/.test(c.p)), sent);
}

{
  /* On a board the server is paging, re-asking means fetching the FIRST page
     again — two hundred rows of scrolling thrown away on every cell somebody
     touches. The rows there are the server's answer and this browser holds one
     page of them; the board still needs a refresh to follow an edit, and that
     is the trade being made rather than an oversight. */
  const {st,f,sent,setReply} = world();
  f.advToggle('status','eq','check');
  setReply([1,2]);
  await f.advAskServer();
  const before = sent.filter(c=>/items\/query$/.test(c.p)).length;
  f.pageOn(true);
  f.advWrote('/api/tasks/1',{method:'PATCH'});
  await sleep(700);
  ck('a paged board is not re-fetched from the top on every edit',
     sent.filter(c=>/items\/query$/.test(c.p)).length===before);
}

// ── when the two halves of the app disagree ───────────────────────────────
{
  /* The server's list can only REMOVE rows here — these are the rows this
     browser already holds. Removing every one of them while the engine here
     matched some is not an answer: it is a server that has not been restarted
     onto this version, or a column one of them knows about and the other does
     not. An empty board is the one outcome that looks like a correct answer
     and is not, and on screen it is unarguable — the filter panel goes on
     counting the items the board holds while the board shows none. */
  const {st,f,setReply,toasts} = world();
  f.advToggle('status','eq','check');
  setReply([]);                                  // the stale server: nothing
  await f.advAskServer();
  ck('the board shows what the browser can see, not an empty board',
     titles(f,st)==='א,ב', titles(f,st));
  ck('…and the disagreement is said out loud', toasts().length===1, toasts());
  f.applyFilters(st.board.tasks); f.applyFilters(st.board.tasks);
  ck('…once per answer, not once per render', toasts().length===1, toasts());
}
{
  /* An empty answer to a filter nothing matches is a correct answer, and must
     stay silent — otherwise every genuinely empty cut cries wolf. */
  const {st,f,setReply,toasts} = world();
  f.advToggle('status','eq','nothing-matches-this');
  setReply([]);
  await f.advAskServer();
  ck('a cut that really matches nothing shows nothing, quietly',
     titles(f,st)==='' && toasts().length===0, toasts());
}
{
  /* And an ordinary disagreement — the server keeping some of them — is still
     the server's to answer. It is the authority; what it may not do is empty
     the board behind a count that says otherwise. */
  const {st,f,setReply} = world();
  f.advToggle('status','eq','check');
  setReply([1]);
  await f.advAskServer();
  ck('the server still narrows where it answered with something',
     titles(f,st)==='א', titles(f,st));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
