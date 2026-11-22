/* The first page of a board too big to arrive whole — asked for once.

   Past the client threshold the board is handed over with no rows at all, so
   something has to ask for the first fifty. It is asked for from the RENDER,
   because there are several ways a board reaches the screen and a hook in
   openBoard would cover one of them. That is the right place and it is also
   the dangerous one: a render that asks, an answer that renders, and an answer
   that resets would pull the same fifty rows down forever, against the server,
   on every board anybody opens. Nothing on screen would look wrong while it
   happened.

   So what is pinned here is the number of requests, not the rows: one for a
   large board, and still one after any number of further renders. And the
   other end of it — a first page that never arrives must leave a sentence and
   a button rather than a board that looks empty under a toast that has already
   faded, because up here there is nothing else on screen to contradict it.

   Driven by tests/test_a_big_board_asks_for_its_first_page_once.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function slice(from){
  let i=src.indexOf('{',from), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d)return j+1;} }
  throw new Error('unbalanced');
}
function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  return src.slice(m.index, slice(m.index));
}
function grabConst(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return src.slice(m.index, slice(m.index));
}
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };
const tick=()=>new Promise(r=>setTimeout(r,0));

/* The world a render runs in, with one thing real at a time. `api` is the
   only way out of it, so counting its calls counts requests exactly. */
function world({answer, fails}){
  const seen={requests:[], renders:0, toasts:[]};
  const st={board:{id:7, item_count:21187, tasks:[]}, filters:{}, view:'table'};
  const api=async(url,opt)=>{
    seen.requests.push(JSON.parse(opt.body));   // withMe writes the body as JSON
    if(fails) throw {detail:'הסינון בשרת נכשל'};
    return answer;
  };
  const document={getElementById:()=>null};   // nothing to measure, so fill() stops
  const env = {
    st, api, document,
    // the real pair: advQuery writes the filter half of the question, withMe
    // signs it and turns it into the body — a stub that skipped the stringify
    // would be testing a request shape the app never sends
    advQuery:()=>({}), withMe:o=>JSON.stringify({...(o||{}), user_id:1}),
    renderView:()=>{ seen.renders++; },
    refreshToolbar:()=>{},
    toast:t=>seen.toasts.push(t),
    filterMode:()=>'server',
  };
  const names=Object.keys(env);
  const made=new Function(...names, `
    let _pagedTimer=null;
    ${grabConst('Paged')};
    ${grab('ensurePagedRows')}
    return {Paged, ensurePagedRows};`)(...names.map(k=>env[k]));
  return Object.assign(made, {seen, st, env});
}

// ── one board, one request, however many renders ──────────────────────────
{
  const w = world({answer:{items:Array.from({length:50},(_,i)=>({id:i+1})),
                           next_offset:50, has_more:true, matched:21187, total:21187}});
  ck('a board that arrived without its rows asks for the first page',
     w.ensurePagedRows()===true && w.seen.requests.length===1,
     `${w.seen.requests.length} requests`);
  ck('...from offset zero, and fifty at a time',
     w.seen.requests[0].offset===0 && w.seen.requests[0].limit===50,
     JSON.stringify(w.seen.requests[0]));

  for(let i=0;i<5;i++) w.ensurePagedRows();
  ck('a render while the page is in flight does not ask a second time',
     w.seen.requests.length===1, `${w.seen.requests.length} requests`);

  await tick(); await tick();
  ck('the page arrives', w.Paged.on===true && w.Paged.rows.length===50,
     `on=${w.Paged.on} rows=${w.Paged.rows.length}`);
  ck('...and it draws the board once it has it', w.seen.renders>=1);

  const after=w.seen.requests.length;
  for(let i=0;i<10;i++) w.ensurePagedRows();
  await tick(); await tick();
  ck('and ten more renders ask for nothing at all',
     w.seen.requests.length===after,
     `${w.seen.requests.length-after} extra requests — the render→fetch→render loop is back`);
}

// ── below the threshold it is not this function's business ────────────────
{
  // the same real Paged, asked by a browser that is filtering locally — so a
  // request going out here is one nobody asked for at all
  const w = world({answer:{items:[], has_more:false}});
  const small = new Function('st','filterMode','Paged',
    grab('ensurePagedRows')+'\nreturn ensurePagedRows;')(w.st, ()=>'client', w.Paged);
  ck('a board small enough to filter locally asks for no page',
     small()===false && w.seen.requests.length===0);
  const none = new Function('st','filterMode','Paged',
    grab('ensurePagedRows')+'\nreturn ensurePagedRows;')({board:null}, ()=>'server', w.Paged);
  ck('and with no board on screen there is nothing to ask about', none()===false);
}

// ── a first page that never arrives ───────────────────────────────────────
{
  const w = world({fails:true});
  w.ensurePagedRows();
  await tick(); await tick();
  ck('a first page that fails is remembered as a failure',
     w.Paged.failed===true && w.Paged.on===false,
     `failed=${w.Paged.failed} on=${w.Paged.on}`);
  ck('...and the board is redrawn, so the failure can be SHOWN',
     w.seen.renders>=1,
     'past the threshold the toast is the only thing that happened, over a board that looks empty');
  ck('...and it is said out loud as well', w.seen.toasts.length===1, w.seen.toasts.join());
  ck('...and nothing is left looking like a request still in flight',
     w.Paged.loading===false && w.Paged.pending===false,
     `loading=${w.Paged.loading} pending=${w.Paged.pending}`);

  const after=w.seen.requests.length;
  for(let i=0;i<10;i++) w.ensurePagedRows();
  await tick(); await tick();
  ck('a board the server keeps refusing is not hammered once per render',
     w.seen.requests.length===after,
     `${w.seen.requests.length-after} extra requests — ten renders, ten failed fetches`);

  // the retry is the person's: pagedFailedHTML clears the flag and asks again
  w.Paged.failed=false;
  ck('and clearing the failure is all it takes to ask again',
     w.ensurePagedRows()===true && w.seen.requests.length===after+1);
}

// ── what is on screen while, and after, the page does not come ────────────
{
  const {pagedFailedHTML, loadingRowsHTML} = new Function('boardRowCount',
    grab('stateHTML')+'\n'+grab('loadingRowsHTML')+'\n'+grab('pagedFailedHTML')
    +'\nreturn {pagedFailedHTML, loadingRowsHTML};')(()=>21187);
  const failed=pagedFailedHTML(), waiting=loadingRowsHTML();
  ck('the failed board says it could not load the items',
     /לא הצלחנו לטעון/.test(failed), failed.slice(0,120));
  ck('...and offers something to press, which is the whole point of the state',
     /<button[^>]*>[\s\S]*?נסה שוב/.test(failed), failed);
  ck('...which clears the failure and asks again',
     /Paged\.failed=false;\s*Paged\.load\(true\)/.test(failed), failed);
  ck('...and it is not the spinner that says the rows are on their way',
     !/fa-spin/.test(failed) && /fa-spin/.test(waiting));
  ck('while they ARE on their way, the board says so rather than saying it is empty',
     /טוען את הפריטים/.test(waiting) && /21,187/.test(waiting), waiting.slice(0,160));
}

/* And the branch that chooses between them. It lives in the middle of two
   very large render functions, which is exactly why it is read here rather
   than run: what matters is that neither view can reach "the board is empty"
   with a failed fetch behind it. */
for(const fn of ['vTable','vKanban']){
  const body=grab(fn);
  ck(`${fn} tells a failed page apart from a page still coming`,
     /Paged\.failed\s*\?\s*pagedFailedHTML\(\)\s*:\s*loadingRowsHTML\(\)/.test(body),
     body.slice(0,80));
  ck(`...and asks the board's own count before it calls it empty`,
     /boardRowCount\(\)/.test(body) || /typeof boardRowCount==='function'/.test(body));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
