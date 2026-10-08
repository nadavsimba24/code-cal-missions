/* Where the app opens. The main URL opens the primary workspace; a link to a
   board somewhere else opens that board, and takes its workspace with it.
   Runs the real enterApp and followBoardEnv out of index.html.
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
  const st={boards:boards.slice(), env:null, me:{id:1}};
  const Env={items:loaded?envs.slice():[], renders:0,
    async load(){ this.items=envs.slice(); if(!st.env) st.env=this.items.find(e=>e.is_primary)||this.items[0]||null; },
    active(){ return st.env||this.items[0]||null; },
    render(){ this.renders++; }};
  const fn=new Function('st','Env','loadBoards','Router','localStorage','openBoard',
    'findAnyTask','Chat','document','Notif','setTimeout','showAgentHint',
    grab('followBoardEnv')+grab('enterApp')+'; return enterApp;')(
    st, Env, async()=>{}, {parse:()=>{
      const m=hash.match(/board\/(\d+)(?:\/item\/(\d+))?/);
      return m?{boardId:+m[1],itemId:m[2]?+m[2]:null}:{boardId:null,itemId:null};
    }},
    {getItem:()=>saved===null?null:String(saved), setItem(){}},
    async id=>{opened.push(id);}, ()=>null, {open(){}},
    {getElementById:()=>({innerHTML:''})}, {start(){}}, ()=>{}, ()=>{});
  await fn();
  return {opened, env:st.env, Env};
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
  const r=await enter({boards:[{id:30,environment_id:2}], saved:30});
  ck('nothing of theirs in the primary workspace is not an empty screen',
     r.opened[0]===30, JSON.stringify(r.opened));
  ck('...and the switcher says where that board actually is', r.env===OTHER, r.env&&r.env.name);
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
