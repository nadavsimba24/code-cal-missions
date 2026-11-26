/* The Excel export of a large board holds the whole board, not its first page.

   Past the client threshold the rows arrive fifty at a time, and the export is
   built from the rows on screen. Opening board h3 and exporting straight away
   gave a file of 50 items over a board of hundreds — the group headers had been
   fixed to count the whole answer, and the file was now the one place still
   holding a page. Paged.loadAll pulls every remaining page down before the grid
   is built.

   Pinned here, against the real Paged: every page is fetched until the server
   says there is no more, at the largest page size it serves; a question that
   changes while it runs stops it rather than appending another answer's rows;
   and the export calls it before exportGrid, not after. */
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
function grabConst(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return src.slice(m.index, slice(m.index));
}
function grabFn(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  return src.slice(m.index, slice(m.index));
}

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

/* A server holding `total` rows, answering pages the way /items/query does. */
function server(total, hook){
  const calls=[];
  const api=async(url,opt)=>{
    const q=JSON.parse(opt.body); calls.push(q);
    if(hook) await hook(calls.length);
    const items=[]; for(let i=q.offset;i<Math.min(total,q.offset+q.limit);i++)items.push({id:i+1,group_id:1});
    return {items, matched:total, total, next_offset:q.offset+items.length,
            has_more:q.offset+items.length<total, group_matched:{'1':total}};
  };
  return {api, calls};
}
function paged(api){
  const st={board:{id:7, link_display:{}}, filters:{}};
  let renders=0;
  const env={st, api, advQuery:()=>({}), withMe:o=>JSON.stringify(o||{}),
             renderView:()=>{renders++;}, refreshToolbar:()=>{}, toast:()=>{},
             document:{getElementById:()=>null, querySelectorAll:()=>[]}, filterMode:()=>'server'};
  const names=Object.keys(env);
  const {Paged}=new Function(...names, `
    let _pagedTimer=null;
    ${grabConst('Paged')};
    return {Paged};`)(...names.map(k=>env[k]));
  return {Paged, st, renders:()=>renders};
}

// ── the board as it is right after opening: one page of 50 in hand ─────────
{
  const s=server(478);
  const {Paged, renders}=paged(s.api);
  await Paged.load(true);
  ck('opening the board holds the first page only', Paged.rows.length===50 && Paged.more);
  const before=renders();
  const got=[];
  const ok=await Paged.loadAll((have,of)=>got.push([have,of]));
  ck('loadAll says the board is whole', ok===true);
  ck('every row of the board is now in hand', Paged.rows.length===478, Paged.rows.length);
  ck('…each one once', new Set(Paged.rows.map(r=>r.id)).size===478);
  ck('and there is nothing left to ask for', !Paged.more && !Paged.loading);
  ck('the rest is asked for at the server\'s largest page', s.calls.slice(1).every(q=>q.limit===200),
     JSON.stringify(s.calls.map(q=>q.limit)));
  ck('…from where the first page ended', s.calls[1].offset===50);
  ck('progress is reported as rows arrive', got.length===3 && got[2][0]===478 && got[2][1]===478,
     JSON.stringify(got));
  ck('the board is redrawn once at the end, not per page', renders()-before===1, renders()-before);
}

// ── a board that has not answered yet starts from the first page ──────────
{
  const s=server(120);
  const {Paged}=paged(s.api);
  const ok=await Paged.loadAll();
  ck('a board with nothing in hand is loaded whole too', ok && Paged.rows.length===120, Paged.rows.length);
}

// ── an already whole board asks nothing ───────────────────────────────────
{
  const s=server(30);
  const {Paged}=paged(s.api);
  await Paged.load(true);
  const n=s.calls.length;
  ck('a board already whole is not asked again', (await Paged.loadAll())===true && s.calls.length===n);
}

// ── a filter typed while it runs stops it ─────────────────────────────────
{
  let P;
  const s=server(1000, n=>{ if(n===3) P.seq++; });   // a new question arrives mid-way
  const {Paged}=paged(s.api); P=Paged;
  await Paged.load(true);
  const ok=await Paged.loadAll();
  ck('a question that changed mid-way stops the load', ok===false);
  ck('…without appending the old answer\'s rows', Paged.rows.length<1000, Paged.rows.length);
}

// ── a failing page is reported, not swallowed into a short file ───────────
{
  const s=server(400, n=>{ if(n===2) throw new Error('boom'); });
  const {Paged}=paged(s.api);
  await Paged.load(true);
  ck('a page that fails makes loadAll say the board is not whole', (await Paged.loadAll())===false);
  ck('…and leaves the board able to load again', !Paged.loading);
}

// ── the export uses it, and before it builds the file ─────────────────────
{
  const exp=grabFn('exportBoardExcel');
  ck('the export loads the rest of the board', /Paged\.loadAll\(/.test(exp));
  ck('…before the grid is built', exp.indexOf('Paged.loadAll(') < exp.indexOf('exportGrid()'));
  ck('…and still asks before a short file if the load did not finish',
     exp.indexOf('exportGrid()') < exp.lastIndexOf('boardRowsPartial()') && /ייצוא חלקי/.test(exp));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
