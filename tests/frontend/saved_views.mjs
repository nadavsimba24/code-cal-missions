/* תצוגות שמורות — a named cut of the board, kept as a tab.

   What the browser is responsible for is the round trip: the cut it saves has
   to be the cut it restores. A view that comes back with the filters but not
   the base view, or with the condition tree flattened, is worse than no view
   at all — it opens a board that looks right and is answering a different
   question.

   The permission model belongs to the server (tests/test_saved_views.py).
   What is checked here is that the strip DRAWS it: a lock or a group of
   people on every tab, and the pencil only where the server said can_edit.

   Driven by tests/test_saved_views.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const at = src.indexOf('const Views = {');
const viewsSrc = src.slice(at, src.indexOf('\n};', at)) + '\n};';

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,240):''))); };

function world(){
  const w={rendered:0, tabs:0, asked:0, toasts:[]};
  const st={board:{id:5, my_role:'editor'}, view:'table',
            filters:{q:'',people:[],status:'',priority:'',sort:'',
                     links:{col:'',mode:'',item:0},adv:null,advIds:null}};
  /* Router: the open view is now in the address, so a shared link opens the
     board already filtered. Captured here so the cases below can read what
     the URL would say. */
  w.url=[];
  const V=new Function('st','api','withMe','meId','toast','showModal','closeModals',
    'askConfirm','renderTabs','renderView','refreshToolbar','boardViews','esc',
    'document','advQuery','filtersActive','setTimeout','Router','Chat','advPrune',
    viewsSrc+'\nreturn Views;')(
    st, async(url)=>(url.includes('/views')?{views:w.serverViews||[]}:{item_ids:[1,2]}),
    x=>JSON.stringify(x), ()=>7,
    m=>w.toasts.push(m), ()=>{}, ()=>{}, ()=>{},
    ()=>w.tabs++, ()=>w.rendered++, ()=>{},
    ()=>['table','kanban'], x=>String(x==null?'':x),
    {getElementById:()=>null, querySelector:()=>null},
    n=>({filter:n}), ()=>true, f=>f(),
    {set:(b,i,v)=>w.url.push('#/board/'+b+(v?'/view/'+v:'')+(i?'/item/'+i:''))},
    {taskId:null},
    /* A rule whose column was deleted is pruned before the view is applied.
       These cases are about the round trip, so nothing is pruned here —
       tests/frontend/filter_edge_cases.mjs runs the real advPrune. */
    n=>({tree:n, removed:w.pruned||[], denied:w.denied||[]}));
  return {w, st, V};
}

// ── the round trip: what is saved is what comes back ──────────────────────
{
  const {st,V}=world();
  st.view='kanban';
  st.filters={q:'באג', people:[7,8], status:'', priority:'high', sort:'due',
              links:{col:'c1',mode:'has',item:0},
              adv:{op:'or',rules:[{op:'and',rules:[{field:'status',op:'ne',v:'done'}]}]},
              advIds:new Set([1])};
  const cut=V.current();
  ck('the cut carries the toolbar filters',
     cut.q==='באג' && cut.priority==='high' && cut.sort==='due', JSON.stringify(cut));
  ck('...the people, as a copy rather than the live array',
     cut.people.join()==='7,8' && cut.people!==st.filters.people);
  ck('...the condition tree, nesting and all',
     cut.adv.rules[0].rules[0].field==='status', JSON.stringify(cut.adv));
  ck('...and the base view, because the same cut on a kanban is a different '
     +'thing to look at', cut.view==='kanban');
  ck('what the server answered is NOT saved — it is an answer, not a question',
     cut.advIds===undefined, JSON.stringify(Object.keys(cut)));
}
{
  const {w,st,V}=world();
  const saved={view:'kanban', q:'באג', people:[7], status:'', priority:'high',
               sort:'due', links:{col:'c1',mode:'has',item:0},
               adv:{op:'and',rules:[{field:'priority',op:'eq',v:'high'}]}};
  V.items=[{id:9,name:'באגים דחופים',visibility:'public',filters:saved,can_edit:true}];
  V.apply(9);
  ck('opening a tab restores the filters', st.filters.q==='באג' && st.filters.priority==='high');
  ck('...and the base view it was saved on', st.view==='kanban');
  ck('...and the condition tree', st.filters.adv.rules[0].v==='high');
  ck('...and the tab is the one lit', V.active===9);
  ck('...the board is redrawn', w.rendered>0);
  ck('a stale answer from a previous filter is dropped, not carried over',
     st.filters.advIds===null);
}
{
  // a view saved on a view this board no longer offers
  const {st,V}=world();
  V.items=[{id:1,name:'ישנה',visibility:'private',filters:{view:'gantt',q:'x'},can_edit:true}];
  V.apply(1);
  ck('a view saved on a board view since switched off keeps the current one',
     st.view==='table', st.view);
  ck('...and still restores what it can', st.filters.q==='x');
}

// ── the strip ─────────────────────────────────────────────────────────────
{
  const {V}=world();
  V.items=[
    {id:1,name:'שלי',visibility:'private',owner_name:'רינה',can_edit:true,filters:{}},
    {id:2,name:'לכולם',visibility:'public',owner_name:'דנה',can_edit:false,filters:{}},
  ];
  const html=V.tabsHTML();
  ck('a private tab is marked with a lock', /fa-lock[^]*שלי/.test(html), html);
  ck('a public tab is marked as everybody’s', /fa-users[^]*לכולם/.test(html), html);
  ck('the pencil is drawn only where the server said it may be',
     (html.match(/tab-view-edit/g)||[]).length===1, html);
  ck('...and it does not also open the view it edits',
     /event\.stopPropagation\(\);Views\.edit\(1\)/.test(html), html);
  ck('whose view it is, is in reach', html.includes('דנה'), html);
  V.active=2;
  ck('the open one is lit', /tab-view active[^]*לכולם/.test(V.tabsHTML()));
  ck('an empty strip draws nothing at all', (V.items=[], V.tabsHTML()===''));
}

// ── leaving a view ────────────────────────────────────────────────────────
{
  const {st,V}=world();
  V.items=[{id:3,name:'x',visibility:'private',filters:{q:'באג'},can_edit:true}];
  V.apply(3);
  V.leave();
  ck('leaving a view unlights the tab', V.active===null);
  ck('...and does NOT clear the board — somebody editing a cut has not asked '
     +'for their work to vanish', st.filters.q==='באג');
}

// ── saving ────────────────────────────────────────────────────────────────
{
  const {w,V}=world();
  V.saveNew();
  ck('saving with nothing filtered says so instead of keeping an empty view',
     true);   // filtersActive() is true in this world; the real guard is below
  const guard=src.slice(src.indexOf('  saveNew(){'), src.indexOf('  edit(id)'));
  ck('...and the guard is really there',
     /filtersActive\(\)/.test(guard) && /אין מה לשמור/.test(guard), guard);
}

// ── the lock: whose view is it, and what may be saved ─────────────────────
/* The creator of a public view is its owner. Anybody else may read it and
   may build on it, and the only thing they are offered is a copy. A tab
   other people rely on must not be rewritten by somebody who was adjusting
   what they were looking at — the damage is invisible to everyone it affects
   until they next open the tab and find it answering another question. */
{
  const {st,V}=world();
  const cut={view:'table',q:'באג',people:[],status:'',priority:'',sort:'',
             links:{col:'',mode:'',item:0},adv:null};
  V.items=[{id:4,name:'של דנה',visibility:'public',owner_name:'דנה',
            can_edit:false,is_owner:false,filters:cut}];
  V.apply(4);
  ck('a view just opened is not "changed"', V.dirty()===false);
  st.filters.q='אחר';
  ck('...and changing a filter makes it so', V.dirty()===true);
}
{
  const {w,st,V}=world();
  V.items=[{id:4,name:'של דנה',visibility:'public',owner_name:'דנה',
            can_edit:false,is_owner:false,
            filters:{view:'table',q:'באג',people:[],status:'',priority:'',sort:'',
                     links:{col:'',mode:'',item:0},adv:null}}];
  V.apply(4);
  st.filters.q='אחר';
  w.toasts.length=0;
  await V.update();
  ck('update on somebody else’s view refuses and says why',
     w.toasts.length===1 && /אינה שלך|עותק/.test(w.toasts[0]), w.toasts);
}
{
  const {w,st,V}=world();
  V.items=[{id:5,name:'שלי',visibility:'public',owner_name:'רינה',
            can_edit:true,is_owner:true,
            filters:{view:'table',q:'באג',people:[],status:'',priority:'',sort:'',
                     links:{col:'',mode:'',item:0},adv:null}}];
  w.serverViews=V.items;            // what a reload of the strip answers
  V.apply(5);
  st.filters.q='אחר';
  w.toasts.length=0;
  await V.update();
  ck('a view you own can be written over', /עודכנה/.test(w.toasts.join()), w.toasts);
  ck('...and it stops being "changed" afterwards', V.dirty()===false);
}
{
  // the strip itself: what the two cases offer
  // searched FORWARD from the anchor: getElementById('tabs') appears earlier
  // in the file too, and an end before the start silently slices to ''
  const _at=src.indexOf('const openV=Views.openView()');
  const strip=src.slice(_at, src.indexOf("getElementById('tabs').innerHTML", _at));
  if(!strip) throw new Error('the tab-strip save block is no longer where this can read it');
  ck('an owner is offered an update AND a copy',
     /can_edit[\s\S]*עדכן תצוגה/.test(strip) && /שמור כתצוגה חדשה/.test(strip), strip.slice(0,200));
  ck('...and the update is drawn only when can_edit', /openV\.can_edit\s*\n?\s*\?/.test(strip));
  ck('a reader is told whose it is', /tab-locked/.test(strip));
  ck('nothing is offered until the cut has actually changed',
     /openV&&changed/.test(strip), strip.slice(0,160));
}

// ── the view in the address ───────────────────────────────────────────────
{
  const {w,V}=world();
  V.items=[{id:9,name:'x',visibility:'public',can_edit:true,filters:{}}];
  V.apply(9);
  ck('opening a view puts it in the address, so the link can be shared',
     w.url[w.url.length-1]==='#/board/5/view/9', w.url);
  V.leave();
  ck('leaving it takes it out again', w.url[w.url.length-1]==='#/board/5', w.url);
}
{
  // the parser, as the page defines it
  const R=new Function('location','history','Views','openDeepLink','st','Chat',
    src.slice(src.indexOf('const Router={'), src.indexOf('\n};', src.indexOf('const Router={')))+'\n};\nreturn Router;')(
    {hash:'#/board/3/view/9/item/42'}, {replaceState(){}}, {active:null}, null, {}, {});
  const r=R.parse();
  ck('a link can carry the board, the view and the item at once',
     r.boardId===3 && r.viewId===9 && r.itemId===42, JSON.stringify(r));
  const R2=new Function('location','history','Views','openDeepLink','st','Chat',
    src.slice(src.indexOf('const Router={'), src.indexOf('\n};', src.indexOf('const Router={')))+'\n};\nreturn Router;')(
    {hash:'#/board/3/item/42'}, {replaceState(){}}, {active:null}, null, {}, {});
  ck('...and the old two-part links still read the same',
     JSON.stringify(R2.parse())===JSON.stringify({boardId:3,viewId:null,itemId:42}),
     JSON.stringify(R2.parse()));
}
{
  /* Router.set takes two arguments everywhere it was already called —
     paintBoard, Chat.open, Chat.close — and none of them is about the view.
     Without the default, opening an item would drop the view out of the
     address and the shared link would stop being the one that was shared. */
  let got='';
  const R=new Function('location','history','Views','openDeepLink','st','Chat',
    src.slice(src.indexOf('const Router={'), src.indexOf('\n};', src.indexOf('const Router={')))+'\n};\nreturn Router;')(
    {hash:''}, {replaceState:(a,b,h)=>{got=h;}}, {active:9}, null, {}, {});
  R.set(3, 42);
  ck('opening an item keeps the view in the address', got==='#/board/3/view/9/item/42', got);
  R.set(3, null, null);
  ck('...and it can still be cleared on purpose', got==='#/board/3', got);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
