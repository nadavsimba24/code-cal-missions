/* Where the app opens. The main URL opens the primary workspace — the one
   every user is in — and it stays there even when the person can see no board
   inside it, which is the ordinary case for somebody new: a board in the shared
   workspace is private until they are invited to it. The entry used to fall
   back to a board in another workspace and let the switcher follow, so a new
   user invited to one departmental board opened the app inside that department
   and never saw the shared workspace at all.
   A link to a board still wins and still takes its workspace with it.
   Runs the real enterApp, followBoardEnv and entryEmptyHTML out of index.html.
   Driven by tests/test_primary_env_entry.py. */
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

const PRIMARY={id:1,name:'סביבה ראשית',is_primary:true};
const OTHER={id:2,name:'בינוי'};

async function enter({hash='', saved=null, boards, envs=[PRIMARY,OTHER], loaded=true}){
  const opened=[];
  const view={innerHTML:''};
  /* `loaded` is "Env.load already ran" — and a load that has run has ALWAYS
     settled st.env (see Env.load: it points st.env at the primary when nothing
     is chosen). Leaving it null here let a case pass only because opening a
     board happened to set it on the way through. */
  const st={boards:boards.slice(), env:null, me:{id:1}};
  if(loaded) st.env=envs.find(e=>e.is_primary)||envs[0]||null;
  const Env={items:loaded?envs.slice():[], renders:0,
    async load(){ this.items=envs.slice(); if(!st.env) st.env=this.items.find(e=>e.is_primary)||this.items[0]||null; },
    active(){ return st.env||this.items[0]||null; },
    render(){ this.renders++; }};
  /* openDeepLink is grabbed too, not stubbed: a link in the URL is answered by
     it alone now, and stubbing it would leave the thing these cases are about
     untested. Its own dependencies join the list below. */
  const fn=new Function('st','Env','loadBoards','Router','localStorage','openBoard',
    'findAnyTask','Chat','document','Notif','setTimeout','showAgentHint','esc',
    'accessDeniedHTML','refreshBoardItems','renderView','toast',
    // rememberEnv/rememberedEnvId: where you were is kept across a reload now,
    // and both enterApp and followBoardEnv call them. See
    // tests/frontend/refresh_keeps_place.mjs — these cases are the OTHER half,
    // the entry with nothing remembered, so localStorage below answers null.
    grab('rememberEnv')+grab('rememberedEnvId')
    +grab('followBoardEnv')+grab('entryEmptyHTML')+grab('openDeepLink')+grab('enterApp')
    +'; return enterApp;')(
    st, Env, async()=>{}, {parse:()=>{
      const m=hash.match(/board\/(\d+)(?:\/item\/(\d+))?/);
      return m?{boardId:+m[1],itemId:m[2]?+m[2]:null}:{boardId:null,itemId:null};
    }},
    {getItem:k=>(k==='cc_env'?null:(saved===null?null:String(saved))),
     setItem(){}, removeItem(){}},
    async id=>{opened.push(id); st.board={id, tasks:[]};}, ()=>null, {open(){}},
    {getElementById:()=>view}, {start(){}}, ()=>{}, ()=>{}, x=>String(x==null?'':x),
    msg=>'ACCESS-DENIED: '+msg, async()=>{}, ()=>{}, ()=>{});
  await fn();
  return {opened, env:st.env, Env, html:view.innerHTML};
}

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

const BOARDS=[{id:30,environment_id:2},{id:10,environment_id:1},{id:11,environment_id:1}];

{
  const r=await enter({boards:BOARDS});
  ck('the main URL opens a board of the primary workspace, not whatever is first',
     r.opened[0]===10, JSON.stringify(r.opened));
  ck('...and the switcher is on the primary workspace', r.env===PRIMARY, r.env&&r.env.name);
}
{
  const r=await enter({boards:BOARDS, saved:30});
  ck('a board remembered from another workspace does not drag the entry with it',
     r.opened[0]===10, JSON.stringify(r.opened));
}
{
  const r=await enter({boards:BOARDS, saved:11});
  ck('the board you were on is kept when it is in the workspace that opens',
     r.opened[0]===11, JSON.stringify(r.opened));
}
{
  const r=await enter({hash:'#/board/30', boards:BOARDS, saved:11});
  ck('a link to a board elsewhere wins over everything', r.opened[0]===30, JSON.stringify(r.opened));
  ck('...and the workspace follows the board', r.env===OTHER, r.env&&r.env.name);
}
{
  // the new user: invited to one board, in somebody else's workspace
  const r=await enter({boards:[{id:30,environment_id:2}], saved:30});
  ck('one board in another workspace does NOT become the place they land',
     r.opened.length===0, JSON.stringify(r.opened));
  ck('...the switcher stays on the workspace everybody shares',
     r.env===PRIMARY, r.env&&r.env.name);
  ck('...and the screen names the workspace that does hold their board',
     r.html.includes('בינוי'), r.html);
  ck('...with one click to open it there',
     r.html.includes('Env.select(2)') && r.html.includes('openBoard(30)'), r.html);
  ck('...and says why it is empty rather than just that it is',
     r.html.includes('הרשאות הלוח'), r.html);
}
{
  const r=await enter({boards:[], saved:null});
  ck('somebody invited to nothing at all is told that, not shown a workspace list',
     r.html.includes('אין לוחות שהוזמנת אליהם') && r.opened.length===0, r.html);
}
{
  // a remembered board elsewhere is no different: the default is the default
  const r=await enter({boards:[{id:30,environment_id:2},{id:10,environment_id:1}], saved:30});
  ck('a remembered board elsewhere does not win over the default workspace',
     r.opened[0]===10 && r.env===PRIMARY, JSON.stringify(r.opened));
}
{
  const r=await enter({boards:BOARDS, loaded:false});
  ck('the workspaces are awaited, not left to whichever render fires first',
     r.opened[0]===10 && r.env===PRIMARY, JSON.stringify(r.opened));
}
ck('enterApp waits for Env.load before it chooses',
   /if\(!\(Env\.items\|\|\[\]\)\.length\) await Env\.load\(\);/.test(src));
ck('a workspace with nothing open still defaults to the primary one',
   /this\.items\.find\(e=>e\.is_primary\)/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
