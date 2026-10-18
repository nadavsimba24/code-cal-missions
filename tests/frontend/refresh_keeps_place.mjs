/* A refresh leaves you where you were: the same workspace, the same board.

   Where you are is two things, and only one of them was being kept. The open
   board has been written to localStorage for a long time; the workspace never
   was — it lived in st.env and nowhere else, so a reload started from nothing
   and Env.load defaulted to the primary one.

   With a board open that was invisible: the URL carries #/board/N, and opening
   the board drags its workspace along behind it. The moment there is no board
   in the URL — the home screen, a cleared hash, a workspace switched into but
   not yet opened into — the reload landed in the primary workspace, and the
   remembered board was then measured against THAT workspace and thrown away
   for not belonging to it. A board in another department reopened as some
   board in the shared one.

   One thing is deliberately NOT changed: with no remembered workspace at all,
   the entry behaves exactly as it did. That is what keeps a new user — invited
   to a single board in somebody else's department — opening in the workspace
   everybody shares rather than inside that department. Remembering is the
   record of a choice; its absence is not a choice.

   Driven by tests/test_refresh_keeps_place.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

/* The real Env.select, lifted out of the object literal. Faking it is what
   made the first version of this file check its own stub: a harness that
   defines the behaviour it is testing proves nothing, and removing
   rememberEnv() from the real select went undetected. */
function grabMethod(header){
  const i=src.indexOf(header);
  if(i<0) throw new Error('not found: '+header);
  let d=0, j=src.indexOf('{', i);
  for(let k=j;k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){ d--; if(!d) return src.slice(i,k+1); } }
  throw new Error('unbalanced: '+header);
}

function grab(name){
  const m=new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
  throw new Error('unbalanced: '+name);
}

const PRIMARY={id:1,name:'סביבה ראשית',is_primary:true};
const OTHER={id:2,name:'בינוי'};
const THIRD={id:3,name:'חינוך'};
const BOARDS=[{id:30,environment_id:2},{id:10,environment_id:1},{id:11,environment_id:1},
              {id:40,environment_id:3}];

/* One browser session: localStorage survives the reload, st does not. */
function session(store){
  const mem={...store};
  return {
    store:mem,
    getItem:k=>(k in mem?mem[k]:null),
    setItem:(k,v)=>{ mem[k]=String(v); },
    removeItem:k=>{ delete mem[k]; },
  };
}

async function load({hash='', ls, envs=[PRIMARY,OTHER,THIRD], boards=BOARDS}){
  const opened=[]; const view={innerHTML:''};
  const st={boards:boards.slice(), env:null, me:{id:1}, board:null};
  const Env={items:[], renders:0,
    async load(){ this.items=envs.slice();
      const mine=st.env&&this.items.find(e=>e.id===st.env.id);
      st.env = mine || this.items.find(e=>e.is_primary) || this.items[0] || null; },
    active(){ return st.env||this.items[0]||null; },
    render(){ this.renders++; },
    _set(){}, };

  const made=new Function('st','Env','loadBoards','Router','localStorage','openBoard',
    'findAnyTask','Chat','document','Notif','setTimeout','showAgentHint','esc',
    'accessDeniedHTML','refreshBoardItems','renderView','toast',
    'renderSidebar','closeItemPanel',
    grab('rememberEnv')+grab('rememberedEnvId')+grab('followBoardEnv')
    +grab('entryEmptyHTML')+grab('openDeepLink')+grab('enterApp')
    // the real one, bound onto the fake Env below
    +'\nconst _select = {'+grabMethod('  select(id){')+'}.select;'
    +'; return {enterApp, rememberEnv, followBoardEnv, _select};')(
    st, Env, async()=>{},
    {parse:()=>{ const m=hash.match(/board\/(\d+)(?:\/item\/(\d+))?/);
      return m?{boardId:+m[1],itemId:m[2]?+m[2]:null}:{boardId:null,itemId:null}; }, set(){}},
    ls,
    async id=>{ opened.push(id); st.board={id,tasks:[]}; ls.setItem('cc_board', id); },
    ()=>null, {open(){},taskId:null,close(){}},
    {getElementById:()=>view}, {start(){}}, ()=>{}, ()=>{}, x=>String(x==null?'':x),
    m=>'DENIED '+m, async()=>{}, ()=>{}, ()=>{}, ()=>{},
    // leaving a workspace closes the open item's panel; these cases open none
    ()=>{});
  Env.select=made._select;                       // the page's own, not a stand-in
  await made.enterApp();
  return {board:opened[0]??null, env:st.env&&st.env.id, html:view.innerHTML, Env, st, made};
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,200):''))); };

// ── the report: a board in another workspace, reloaded with no link ────────
{
  const ls=session({cc_board:'30', cc_env:'2'});
  const r=await load({ls});
  ck('a reload with no link in the URL comes back to the same workspace',
     r.env===2, 'env '+r.env);
  ck('...and to the same board inside it', r.board===30, 'board '+r.board);
}
{
  // the same session, but the workspace was never written — the old behaviour,
  // and the one a new user depends on
  const ls=session({cc_board:'30'});
  const r=await load({ls});
  ck('with no remembered workspace the entry is unchanged: the shared one',
     r.env===1, 'env '+r.env);
  ck('...and a board belonging elsewhere does not drag the entry after it',
     r.board===10, 'board '+r.board);
}

// ── a link in the URL still wins over anything remembered ──────────────────
{
  const ls=session({cc_board:'11', cc_env:'1'});
  const r=await load({hash:'#/board/40', ls});
  ck('a link to a board elsewhere beats the remembered place', r.board===40, 'board '+r.board);
  ck('...and takes its workspace with it', r.env===3, 'env '+r.env);
  ck('...and that workspace is what the next reload comes back to',
     ls.getItem('cc_env')==='3', ls.store);
}

// ── switching workspace is itself remembered ───────────────────────────────
{
  const ls=session({cc_board:'11', cc_env:'1'});
  const r=await load({ls});
  r.Env.select(2);                                  // she picks another workspace
  ck('picking a workspace writes it down', ls.getItem('cc_env')==='2', ls.store);
  const again=await load({ls});
  ck('...so the next reload opens there', again.env===2, 'env '+again.env);
  ck('...on a board of that workspace', again.board===30, 'board '+again.board);
}

// ── a workspace that is no longer hers ─────────────────────────────────────
{
  const ls=session({cc_board:'30', cc_env:'2'});
  const r=await load({ls, envs:[PRIMARY], boards:[{id:10,environment_id:1}]});
  ck('a workspace she was removed from falls back to the shared one',
     r.env===1, 'env '+r.env);
  ck('...and the note is rewritten to where she actually ended up, so the '
     +'dead workspace is not retried on every reload',
     ls.getItem('cc_env')==='1', ls.store);
  ck('...landing on a board she does have', r.board===10, 'board '+r.board);
}

// ── and nothing of hers anywhere still says so ─────────────────────────────
{
  const ls=session({cc_board:'30', cc_env:'2'});
  const r=await load({ls, envs:[PRIMARY,OTHER], boards:[]});
  ck('no boards at all is still the empty screen, not a crash',
     r.board===null && r.html.includes('אין לוחות'), r.html.slice(0,120));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
