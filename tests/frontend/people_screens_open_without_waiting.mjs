/* The two people screens answer the click, not the network.

   ניהול מערכת → משתמשים asked for the users, then — only once they had
   landed — for the departments, and drew nothing until both were back: two
   round trips in a row with the button looking dead. And in חברים והרשאות,
   every role change and every removal waited for a second request — the whole
   member list fetched again — before the row moved, to be told what the
   server's "yes" had already said.

   Pinned here:
     · SysAdmin.open draws the dialog before /api/users answers, asks for the
       users and the departments together, and fills the table when they land;
     · an answer that lands after the dialog was reopened draws nothing;
     · a tab with rows of its own is not held up by the people list;
     · Members.setRole redraws from what it has, with no refetch;
     · Members.remove takes the row off at once, and still asks the server who
       may now be invited — without waiting for it.

   Driven by tests/test_people_screens_open_without_waiting.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabMethodIn(obj,name){
  const o=new RegExp(`^const ${obj} = \\{|^const ${obj}=\\{`,'m').exec(src);
  if(!o) throw new Error('not found: '+obj);
  const m=new RegExp(`^  (?:async )?${name}\\(`,'m').exec(src.slice(o.index));
  if(!m) throw new Error('not found: '+obj+'.'+name);
  const from=o.index+m.index;
  let i=src.indexOf('{',from), d=0;
  for(let j=i;j<src.length;j++){
    if(src[j]==='{')d++;
    else if(src[j]==='}'){d--; if(!d) return src.slice(from,j+1);}
  }
  throw new Error('unbalanced: '+name);
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,240):''))); };
const tick=()=>new Promise(r=>setTimeout(r,0));

/* A request that answers only when the test says so. */
function deferred(){ let res; const p=new Promise(r=>{res=r;}); return {p,res}; }

// ── ניהול מערכת ───────────────────────────────────────────────────────────
function sysWorld(){
  const log=[], pending={};
  const st={depts:[]};
  const api=u=>{ log.push('api '+u); const d=deferred(); pending[u]=d; return d.p; };
  const body={innerHTML:''};
  const doc={getElementById:id=>(id==='modal'?{classList:{add(){}}}:(id==='sa-body'?body:null))};
  const SysAdmin=new Function('st','api','showModal','mobileBlocked','hasCap','closeCellPops',
    'robotIcon','toast','document',
    'return {'+grabMethodIn('SysAdmin','open')+','
    +'go(t){ this.tab=t; log.push("go "+t+(this._usersLoading?" (loading)":" ("+this.users.length+" users)")); }};')(
    st, api, ()=>log.push('modal'), ()=>false, ()=>true, ()=>{}, ()=>'', ()=>{}, doc);
  // `log` is reached from inside go() through the closure below
  globalThis.log=log;
  return {SysAdmin,log,pending,st,body};
}

{
  const w=sysWorld();
  const opening=w.SysAdmin.open('users');
  await tick();
  ck('the dialog is drawn before /api/users answers',
     w.log.indexOf('modal')>=0 && w.log.indexOf('modal')<w.log.length, w.log.join(' | '));
  ck('…and shows the table as loading rather than as empty',
     w.log.includes('go users (loading)'), w.log.join(' | '));
  ck('users and departments are asked for together, not one after the other',
     !!w.pending['/api/users'] && !!w.pending['/api/departments'], Object.keys(w.pending).join(','));
  w.pending['/api/departments'].res([{id:1,name:'הנדסה'}]);
  w.pending['/api/users'].res([{id:7,name:'דנה'},{id:8,name:'רון'}]);
  await opening;
  ck('the table is filled when the people land',
     w.log[w.log.length-1]==='go users (2 users)', w.log.join(' | '));
  ck('the departments are kept for the row menu', w.st.depts.length===1);
}

{
  const w=sysWorld();
  w.st.depts=[{id:1,name:'הנדסה'}];
  const first=w.SysAdmin.open('users');
  await tick();
  const firstUsers=w.pending['/api/users'];
  ck('departments already loaded are not asked for again',
     !w.pending['/api/departments'], Object.keys(w.pending).join(','));
  const second=w.SysAdmin.open('users');
  await tick();
  const secondUsers=w.pending['/api/users'];
  firstUsers.res([{id:1,name:'ישן'}]);
  await first;
  ck('an answer for a dialog that was opened again since draws nothing',
     !w.log.includes('go users (1 users)'), w.log.join(' | '));
  secondUsers.res([{id:1,name:'א'},{id:2,name:'ב'},{id:3,name:'ג'}]);
  await second;
  ck('…and the latest one does', w.log[w.log.length-1]==='go users (3 users)', w.log.join(' | '));
}

{
  const w=sysWorld();
  const opening=w.SysAdmin.open('envs');
  await tick();
  ck('a tab with rows of its own opens without waiting for the people list',
     w.log.includes('go envs (loading)'), w.log.join(' | '));
  const n=w.log.length;
  w.pending['/api/users'].res([]); w.pending['/api/departments'].res([]);
  await opening;
  ck('…and is not redrawn over when the people list lands',
     w.log.slice(n).every(x=>!x.startsWith('go ')), w.log.slice(n).join(' | '));
}

// ── חברים והרשאות ─────────────────────────────────────────────────────────
function memWorld(){
  const calls=[];
  const st={board:{id:5}};
  const api=(u,o)=>{ calls.push(((o&&o.method)||'GET')+' '+u); return Promise.resolve({status:'ok'}); };
  const Members=new Function('st','api','toast','meId','askConfirm','document',
    'return {'+grabMethodIn('Members','setRole')+','+grabMethodIn('Members','remove')+','
    +'_redraw(){ this.redrawn=(this.redrawn||0)+1; },'
    +'refresh(){ this.refreshed=(this.refreshed||0)+1; return Promise.resolve(); }};')(
    st, api, ()=>{}, ()=>1, (msg,cb)=>cb(), {getElementById:()=>null});
  Members.data={can_manage:true, available:[],
    members:[{user_id:1,name:'אני',role:'admin'},{user_id:2,name:'דנה',role:'editor'}]};
  return {Members,calls};
}

{
  const w=memWorld();
  await w.Members.setRole(2,'viewer');
  ck('a role change is one request', w.calls.length===1 && w.calls[0].startsWith('PATCH'), w.calls.join(' | '));
  ck('…the row says the new role', w.Members.data.members.find(m=>m.user_id===2).role==='viewer');
  ck('…redrawn from what is already here, with no refetch',
     w.Members.redrawn===1 && !w.Members.refreshed, `redrawn=${w.Members.redrawn} refreshed=${w.Members.refreshed}`);
}

{
  const w=memWorld();
  await w.Members.remove(2);
  await tick();
  ck('a removal takes the row off at once',
     !w.Members.data.members.some(m=>m.user_id===2) && w.Members.redrawn===1);
  ck('…and still asks the server who may now be invited', w.Members.refreshed===1);
}

{
  // one's OWN role is the exception: only the server knows that an admin who
  // made themselves an editor may no longer manage the board (meId() is 1)
  const w=memWorld();
  await w.Members.setRole(1,'editor');
  ck('demoting oneself asks the server again, for can_manage',
     w.Members.refreshed===1 && !w.Members.redrawn, `redrawn=${w.Members.redrawn} refreshed=${w.Members.refreshed}`);
}

// ── the real refresh: only the latest answer draws ────────────────────────
{
  const pend=[];
  const api=()=>{ const d=deferred(); pend.push(d); return d.p; };
  const M=new Function('st','api','document',
    'return {'+grabMethodIn('Members','refresh')+','
    +'_redraw(){ this.drawn=(this.drawn||[]).concat([this.data.members.length]); }};')(
    {board:{id:5}}, api, {getElementById:()=>null});
  M.data={members:[{user_id:1},{user_id:2},{user_id:3}]};
  const a=M.refresh(), b=M.refresh();
  pend[1].res({members:[{user_id:1}]});          // the later request, answered first
  await b;
  pend[0].res({members:[{user_id:1},{user_id:3}]}); // the earlier one, read before the second removal
  await a;
  ck('an older refresh answering last does not bring a removed row back',
     M.data.members.length===1 && JSON.stringify(M.drawn)==='[1]', JSON.stringify(M.drawn));
}

// ── the real go(): the users tab says it is loading, not that nobody exists ─
{
  const body={innerHTML:''};
  const S=new Function('document',
    'return {'+grabMethodIn('SysAdmin','go')+','
    +'usersHTML(){ return "TABLE"; }, syncHeads(){}};')(
    {getElementById:id=>(id==='sa-body'?body:null), querySelectorAll:()=>[]});
  S._usersLoading=true; S.go('users');
  ck('while the people are on their way the users tab reads «טוען…»',
     body.innerHTML.includes('טוען') && !body.innerHTML.includes('TABLE'), body.innerHTML);
  S._usersLoading=false; S.go('users');
  ck('…and the table once they are here', body.innerHTML==='TABLE', body.innerHTML);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
