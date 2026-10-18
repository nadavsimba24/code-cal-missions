/* The item's panel closes when you leave the board or the workspace it
   belongs to.

   The conversation, the files and the log are three tabs of one panel, opened
   from one item. Switching board left it open: the panel of an item that is
   no longer anywhere on screen, floating over a board it has nothing to do
   with. paintBoard then rewrote the URL to #/board/<the new one>, so the
   address said one thing and the panel showed another — and a reload closed
   it without being asked to, which is the app disagreeing with itself.

   Two rules, and the second is what keeps the first from being destructive:
   it closes where the board CHANGES, and nowhere else. Reopening the same
   board — a revalidation, a deep link landing where you already are — must
   leave an open conversation exactly as it was, with whatever is typed in it.

   Driven by tests/test_item_panel_closes.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m=new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
  throw new Error('unbalanced: '+name);
}
function grabMethod(header){
  const i=src.indexOf(header);
  if(i<0) throw new Error('not found: '+header);
  let d=0, j=src.indexOf('{', i);
  for(let k=j;k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){ d--; if(!d) return src.slice(i,k+1); } }
  throw new Error('unbalanced: '+header);
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,200):''))); };

/* A Chat stub that records what the real code asks of it. The panel's own
   close() is pinned separately, in tests/frontend/chat_* — what matters here
   is only whether it is asked to close, and when. */
function world({board=null, openItem=null}={}){
  const w = {closes:0, drafts:0, cached:[], painted:[], env:null};
  const st = {board: board && {id:board, tasks:[]}, boards:[{id:1,environment_id:1},{id:2,environment_id:2}],
              env:null, openSubs:new Set(), selected:new Set(), collapsedGroups:new Set(),
              filters:{}, view:'table'};
  const Chat = {taskId:openItem, close(){ w.closes++; w.drafts++; this.taskId=null; }};
  const made = new Function('Chat','st','localStorage','Env','renderSidebar','closeItemPanelRef',
    grab('closeItemPanel') + '; return {closeItemPanel};')(
      Chat, st, {setItem(){},getItem:()=>null,removeItem(){}},
      {items:[],render(){}}, ()=>{}, null);
  return {w, st, Chat, closeItemPanel: made.closeItemPanel};
}

// ── the helper itself ──────────────────────────────────────────────────────
{
  const t = world({openItem:7});
  t.closeItemPanel();
  ck('an open item panel is closed', t.w.closes===1);
}
{
  const t = world({openItem:null});
  t.closeItemPanel();
  ck('...and nothing happens when none is open', t.w.closes===0);
}

// ── where openBoard calls it, and where it must not ────────────────────────
{
  const body = grab('openBoard');
  ck('openBoard closes the panel', /closeItemPanel\(\)/.test(body), body.slice(0,300));
  ck('...only when the board actually changes — reopening the same board must '
     +'leave an open conversation and its draft alone',
     /st\.board && st\.board\.id!==id\)\{? ?closeItemPanel\(\)/.test(body),
     (body.match(/.*closeItemPanel.*/)||[''])[0]);
  // the CALL, not the mention of it in the comment above — matching prose is
  // how an assertion ends up checking the explanation instead of the code
  ck('...and before the new board is painted over the old one',
     body.indexOf('closeItemPanel()') < body.indexOf('paintBoard(id)'), 'order');
}

// ── and where Env.select calls it ──────────────────────────────────────────
{
  const sel = grabMethod('  select(id){');
  ck('switching workspace closes it too', /closeItemPanel\(\)/.test(sel), sel);
  ck('...and still remembers the workspace it moved to',
     /rememberEnv\(\)/.test(sel), sel);
}

// ── the real Env.select, run ───────────────────────────────────────────────
{
  const w = {closes:0, remembered:[]};
  const st = {env:null, board:{id:1}};
  // an object METHOD: it has to be put back inside a literal to be callable
  const select = new Function('st','rememberEnv','closeItemPanel','renderSidebar',
    'return {' + grabMethod('  select(id){') + '}.select;')(
      st, ()=>w.remembered.push(st.env&&st.env.id), ()=>w.closes++, ()=>{});
  const Env = {items:[{id:1,name:'ראשית'},{id:2,name:'בינוי'}], _set(){}};
  select.call(Env, 2);
  ck('running the page own select closes the panel once',
     w.closes===1, 'closes='+w.closes);
  ck('...having switched the workspace', st.env && st.env.id===2, JSON.stringify(st.env));
  ck('...and written it down', w.remembered.join()==='2', w.remembered.join());
}

// ── the panel's close is the one that saves the draft ──────────────────────
{
  const close = grabMethod('  close(){');
  ck('closing saves whatever was typed before clearing the item',
     close.indexOf('saveDraft()') < close.indexOf('this.taskId=null'), close);
  ck('...and takes the item out of the URL, so the address matches the screen',
     /Router\.set\(st\.board&&st\.board\.id, *null\)/.test(close), close);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
