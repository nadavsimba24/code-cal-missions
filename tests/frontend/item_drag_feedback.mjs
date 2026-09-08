/* Three things a drag must not do: claim a move that never happened, make you
   scroll the whole board with a row held down, and move the board out from
   under the row while you hold it.

   A drop back onto the row's own place used to POST a move, refetch the board
   and say "הפריט הועבר" — a success message for nothing, which is worse than
   silence because it teaches you the drag worked when it did not. The rule
   holds for all three things a board can drag — an item, a sub-item, a whole
   group — since it is the same false success in each.

   And because a move between groups meant reaching the other group, the common
   way for a drag to end nowhere was running out of screen. So for the length of
   the gesture the board shrinks to its group names, each group's "+ הוסף פריט"
   line left showing as the strip to drop on, and the group under the pointer
   opens again. Everything in that shrinking is a frame of reference somebody is
   aiming with, so it is done in two steps, held still by the scroll offset, and
   waited on: the fold is not a frame, the row you hold does not move, and a
   group opens only once you have settled on it.
   Driven by tests/test_item_drag_feedback.py. */
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
const line = re => { const m=re.exec(src); if(!m) throw new Error('not found: '+re); return m[0]; };

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── where a row sits, in the terms the move is sent in ──────────────────────
const {itemSpot,sameSpot} = new Function(
  grab('itemSpot')+'\n'+grab('sameSpot')+'\nreturn {itemSpot,sameSpot};')();

/* rows as the DOM would hand them over, including — as Sortable really does —
   the copy of the dragged row parked in the same tbody, which the selector is
   expected to leave out */
const tbody=(gid,tids)=>{
  const rows=tids.map(t=>typeof t==='object'
    ? {dataset:{tid:String(t.clone)},cls:'sortable-drag'} : {dataset:{tid:String(t)}});
  return {dataset:{gid:gid===null?'':String(gid)},
          querySelectorAll:sel=>sel.includes(':not(.sortable-drag)')?rows.filter(r=>!r.cls):rows,
          rows};
};

const g=tbody(3,[11,22,33]);
ck('the first row follows nothing — it is the top',
   JSON.stringify(itemSpot(g,g.rows[0]))===JSON.stringify({gid:3,after:null}));
ck('any other row follows the one above it, by id and not by row number',
   itemSpot(g,g.rows[2]).after===22);
ck('the ללא קבוצה bucket has no group id',
   itemSpot(tbody(null,[1]),tbody(null,[1]).rows[0]).gid===null);

/* Sortable appends the flying copy of the row to the same tbody, and a drop at
   the end of a group lands the row after it — counted, it would say the item
   now follows itself, which is a move that never happened and a place that
   does not exist. */
const cl=tbody(3,[11,{clone:22},22]);
ck('the copy of the row that follows the cursor is not one of the rows',
   itemSpot(cl,cl.rows[2]).after===11, JSON.stringify(itemSpot(cl,cl.rows[2])));

const spot=(gid,after)=>({gid,after});
ck('a drop back onto the row\'s own place is not a move',
   sameSpot(spot(3,22),spot(3,22))===true);
ck('the same place in a different group is a move',
   sameSpot(spot(3,22),spot(4,22))===false);
ck('a different neighbour in the same group is a move',
   sameSpot(spot(3,22),spot(3,11))===false);
ck('moving to the top of a group is a move, null neighbour and all',
   sameSpot(spot(3,22),spot(3,null))===false);
ck('an unknown starting point is treated as a move, never swallowed',
   sameSpot(null,spot(3,22))===false);

/* the gesture end to end: lift row 22 out and put it back */
const before=itemSpot(g,g.rows[1]);
ck('picked up and dropped where it was → nothing to send',
   sameSpot(before,itemSpot(g,g.rows[1]))===true);
const other=tbody(4,[22]);
ck('picked up and dropped into another group → a move',
   sameSpot(before,itemSpot(other,other.rows[0]))===false);

// ── the board while the item is in the air ─────────────────────────────────
const cls=()=>{const s=new Set();return{add:c=>s.add(c),remove:(...c)=>c.forEach(x=>s.delete(x)),
  contains:c=>s.has(c),toggle:(c,on)=>{on?s.add(c):s.delete(c);}};};

/* A stage with time under our control: the fold and the opening of a group are
   both deliberately late, and "late" is the part worth testing. */
function stage(){
  const timers=[];
  const setT=(fn,ms)=>timers.push({fn,ms})&&timers.length;
  const clearT=id=>{ if(id)timers[id-1]=null; };
  const tick=()=>{ const due=timers.slice(); timers.length=0;
    due.forEach(t=>{ if(t) t.fn(); }); };
  const pending=()=>timers.filter(Boolean).length;

  const view={scrollTop:500};
  const tds=[{dataset:{},textContent:'+ הוסף פריט'},{dataset:{},textContent:'+ הוסף פריט'}];
  /* two groups on screen; the lower one sits 340px further down for as long as
     the upper one is open, which is exactly the slide to be cancelled out */
  const top=i=>[400,560][i] + (i===1 && tbs[0].classList.contains('drag-open') ? 340 : 0);
  const tbs=[0,1].map(i=>({dataset:{gid:String(3+i)},classList:cls(),
    closest:()=>({isConnected:true,getBoundingClientRect:()=>({top:top(i)})})}));
  const doc={body:{classList:cls()},
    getElementById:id=>id==='view'?view:null,
    querySelectorAll:sel=>
      sel.includes('.add-row td')?tds : sel.startsWith('tbody.drag-open')?tbs.filter(t=>t.classList.contains('drag-open')||t.classList.contains('drag-opened'))
      : sel==='.tbl tbody[data-gid]'?tbs : []};
  const fns=new Function('document','setTimeout','clearTimeout',
    line(/^const DRAG_FADE_MS=.*$/m)+'\n'+line(/^let _dragShrinkT=.*$/m)+'\n'
    +grab('keepInPlace')+'\n'+grab('itemDragChrome')+'\n'+grab('itemDragOpen')+'\n'+grab('itemDragOpened')
    +'\nreturn {itemDragChrome,itemDragOpen,keepInPlace};')(doc,setT,clearT);
  /* the row being held: 400px down the board while the board is whole, 80px
     down once every group above it has folded away */
  const held={isConnected:true,
    getBoundingClientRect:()=>({top:doc.body.classList.contains('dragging-item')?80:400})};
  return {doc,view,tds,tbs,held,tick,pending,...fns};
}

let s=stage();
s.itemDragChrome(true,s.held);
ck('what is leaving dims where it stands before anything is taken out',
   s.doc.body.classList.contains('dragging-fade') && !s.doc.body.classList.contains('dragging-item'));
ck('and the board is still whole for that moment — no strip yet',
   s.tds.every(td=>td.textContent==='+ הוסף פריט'));
s.tick();
ck('then the fold: the rows leave the layout and the dimming with them',
   s.doc.body.classList.contains('dragging-item') && !s.doc.body.classList.contains('dragging-fade'));
ck('every group\'s add-item line becomes the strip to drop on',
   s.tds.every(td=>td.textContent==='שחרר כאן'));
ck('the row being held does not move while the board folds around it',
   s.view.scrollTop===180, 'scrollTop '+s.view.scrollTop);
s.keepInPlace(s.held,()=>s.itemDragChrome(false));
ck('and does not move when it unfolds either — the row is where it was let go',
   s.view.scrollTop===500, 'scrollTop '+s.view.scrollTop);
ck('the strip says what it said before once the drag is over',
   s.tds.every(td=>td.textContent==='+ הוסף פריט'), s.tds.map(t=>t.textContent).join('|'));
ck('and no mark of the drag is left on the board',
   !s.doc.body.classList.contains('dragging-item') && !s.doc.body.classList.contains('dragging-fade'));

s=stage();
s.itemDragChrome(true,s.held); s.itemDragChrome(false); s.tick();
ck('a drag let go of before the board has folded does not fold it afterwards',
   !s.doc.body.classList.contains('dragging-item') && s.tds.every(td=>td.textContent==='+ הוסף פריט'));

s=stage();
s.itemDragChrome(true,s.held); s.tick();
s.itemDragChrome(true,s.held); s.tick();      // a second drag in the same session
s.itemDragChrome(false);
ck('two drags in a row still restore the real label, not "שחרר כאן"',
   s.tds.every(td=>td.textContent==='+ הוסף פריט'), s.tds.map(t=>t.textContent).join('|'));

// ── a group opens only once the pointer has settled on it ──────────────────
s=stage();
s.itemDragChrome(true,s.held); s.itemDragOpen(s.tbs[0],true);
ck('the group the drag started in is open before the board folds, not after',
   s.tbs[0].classList.contains('drag-open'));
s.tick();
ck('so the fold leaves it open, with no moment of it shut in between',
   s.tbs[0].classList.contains('drag-open') && s.doc.body.classList.contains('dragging-item'));
ck('and it is not animated in — it never left the screen to be animated back',
   !s.tbs[0].classList.contains('drag-opened'));
s.itemDragOpen(s.tbs[1]);
ck('and it stays open until the pointer has settled somewhere else',
   s.tbs[0].classList.contains('drag-open') && !s.tbs[1].classList.contains('drag-open'));
s.tick();
ck('then it folds away as the one being aimed at opens',
   !s.tbs[0].classList.contains('drag-open') && s.tbs[1].classList.contains('drag-open'));
ck('and that one does get animated in, since it is arriving into a folded board',
   s.tbs[1].classList.contains('drag-opened') && !s.tbs[0].classList.contains('drag-opened'));

s=stage();
s.itemDragOpen(s.tbs[1]);
ck('a group the pointer has only just reached stays shut',
   !s.tbs[1].classList.contains('drag-open'));
s.tick();
ck('and opens once it is clear that is where you are aiming',
   s.tbs[1].classList.contains('drag-open') && !s.tbs[0].classList.contains('drag-open'));

s=stage();
s.itemDragOpen(s.tbs[0]); s.itemDragOpen(s.tbs[1]); s.tick();
ck('sweeping past a group on the way down does not open it',
   !s.tbs[0].classList.contains('drag-open') && s.tbs[1].classList.contains('drag-open'));

s=stage();
s.itemDragOpen(s.tbs[1]); s.itemDragOpen(s.tbs[1]); s.itemDragOpen(s.tbs[1]);
ck('holding still over one group schedules the opening once, not once a frame',
   s.pending()===1, 'pending '+s.pending());

s=stage();
s.itemDragOpen(s.tbs[0]); s.tick();            // the group above is the open one
ck('opening a group below the fold moves nothing that was already placed',
   s.view.scrollTop===500, 'scrollTop '+s.view.scrollTop);
s.itemDragOpen(s.tbs[1]); s.tick();            // now aiming at the one under it
ck('the group being aimed at stays under the pointer while the one above shuts',
   s.view.scrollTop===160, 'scrollTop '+s.view.scrollTop);

s=stage();
s.itemDragOpen(s.tbs[1]); s.itemDragChrome(false); s.tick();
ck('letting go cancels an opening that had not happened yet',
   s.tbs.every(t=>!t.classList.contains('drag-open')));
s=stage();
s.itemDragOpen(s.tbs[1]); s.tick(); s.itemDragChrome(false);
ck('and an open group does not stay open after the drag',
   s.tbs.every(t=>!t.classList.contains('drag-open')));

// ── the rules that do the shrinking ────────────────────────────────────────
const hide=/body\.dragging-item \.tbl tbody\[data-gid\]>tr\[data-tid\]([^{]*)\{display:none\}/.exec(src);
ck('the item rows are hidden while an item is in the air', !!hide);
ck('except the placeholder, which is where the row will land',
   hide && hide[1].includes(':not(.sortable-ghost)'), hide&&hide[0]);
ck('and except the copy that follows the cursor — Sortable parks it in the same tbody',
   hide && hide[1].includes(':not(.sortable-drag)'), hide&&hide[0]);
ck('the same rows dim first, and the dimming is a transition and not a state',
   /body\.dragging-fade[^{]*\{opacity:0;transition:opacity [.\d]+s/.test(src));
ck('the group that is staying open is not dimmed on the way in and lit again after',
   /body\.dragging-fade \.tbl tbody\[data-gid\]:not\(\.drag-open\)>tr\[data-tid\]/.test(src));
ck('the opened group fades its rows in rather than making them appear',
   /body\.dragging-item \.tbl tbody\[data-gid\]\.drag-opened>tr\[data-tid\]\{animation:dragRowIn/.test(src)
   && /@keyframes dragRowIn\{from\{opacity:0\}/.test(src));
ck('a group the user had collapsed takes part too, instead of being undroppable',
   /body\.dragging-item \.grp-stick>\.tbl\{display:table!important;/.test(src));
ck('and the pull that hides under the column header goes with the header',
   /body\.dragging-item \.grp-stick>\.tbl\{[^}]*margin-bottom:0\}/.test(src));
ck('an open sub-item panel gets out of the way — its inline display needs !important',
   /body\.dragging-item \.tbl tr\.sub-wrap\{display:none!important\}/.test(src));
ck('the column headers and the battery go, so a group is its name and the strip',
   /body\.dragging-item \.grp-batt,body\.dragging-item \.tbl thead\{display:none\}/.test(src));
ck('the strip reads as a drop target rather than as a row',
   /body\.dragging-item \.add-row td\{[^}]*dashed var\(--primary\)/.test(src));
ck('where the item landed is marked long enough to be seen',
   /tr\.just-moved>td\{animation:justMoved/.test(src) && /@keyframes justMoved\{/.test(src));

// ── how the list is wired to all of it ─────────────────────────────────────
const body=(anchor,head)=>{ const i=src.indexOf(anchor); const j=src.indexOf(head,i); let d=0;
  for(let k=src.indexOf('{',j);k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){d--; if(!d)return src.slice(j,k+1);} } };
const onEnd = body("group:'board-items'",'onEnd:async(evt)=>{');
ck('the drag records where the row started',
   /_itemDragFrom=itemSpot\(evt\.from,evt\.item\);/.test(src));
ck('the group the row came from is open before the fold, not sprung back after it',
   /itemDragOpen\(evt\.from,true\); \}/.test(src)
   && src.indexOf('itemDragChrome(true,()=>document') < src.indexOf('itemDragOpen(evt.from,true)'));
ck('the placeholder is what the fold is held still against',
   /itemDragChrome\(true,\(\)=>document\.querySelector\('tr\.sortable-ghost'\)\|\|evt\.item\)/.test(src));
ck('the board comes back before anything else happens at the end',
   /keepInPlace\(it,\(\)=>itemDragChrome\(false\)\);/.test(onEnd)
   && onEnd.indexOf('itemDragChrome(false)') < onEnd.indexOf('sameSpot(from,spot)'));
ck('and it unfolds around the dropped row, not back to where the drag began',
   !/_dragScrollTop/.test(src));
ck('the group under the pointer is opened from onMove',
   /onMove:evt=>\{ itemDragOpen\(evt\.to\);/.test(src));
ck('nothing moved → no request and no message',
   onEnd.indexOf('sameSpot(from,spot)') > 0
   && onEnd.indexOf('sameSpot(from,spot)') < onEnd.indexOf("api('/api/tasks/'"),
   'guard at '+onEnd.indexOf('sameSpot(from,spot)'));
ck('a real move still says so, and marks where it went',
   /toast\(wasSorted\?'הפריט הועבר — המיון לפי עמודה בוטל':'הפריט הועבר'\)/.test(onEnd)
   && /renderView\(\); markMovedRow\(tid\);/.test(onEnd));
ck('and the view is never scrolled anywhere on its own',
   !/scrollIntoView/.test(grab('markMovedRow')));
ck('the move is still sent as a neighbour, not as a row number',
   /const body=\{group_id:gid,after_id:spot\.after\}/.test(onEnd));

const subEnd = body("'.sub-body[data-parent]'",'onEnd:async(evt)=>{');
ck('a sub-item put back in its own place is not a reorder either',
   /if\(was!==null&&ids\.join\(','\)===was\)return;/.test(subEnd)
   && subEnd.indexOf('===was)return') < subEnd.indexOf("api('/api/tasks/'"));
/* the same copy, in the sub-item table: it carries the id of the row being
   dragged, so counting it both duplicates an id in the posted order and makes
   the before/after comparison differ every single time */
const subOrder=new Function(grab('subOrder')+'\nreturn subOrder;')();
const sub=(sids)=>({querySelectorAll:sel=>{
  const rows=sids.map(x=>typeof x==='object'?{dataset:{sid:String(x.clone)},cls:'sortable-drag'}:{dataset:{sid:String(x)}});
  return sel.includes(':not(.sortable-drag)')?rows.filter(r=>!r.cls):rows;}});
ck('and the flying copy is not counted among the sub-items either',
   subOrder(sub([5,6,{clone:6}])).join(',')==='5,6', subOrder(sub([5,6,{clone:6}])).join(','));
ck('both ends of the sub-item comparison read the order the same way',
   (subEnd.match(/subOrder\(/g)||[]).length===1 && /_subDragFrom=subOrder\(evt\.from\)/.test(src));

// ── and a group put back where it came from ────────────────────────────────
const grpEnd = body("draggable:'.group'",'onEnd:async()=>{');
ck('a group dropped back into its own place is not a reorder either',
   /if\(was!==null&&ids\.join\(','\)===was\)\{ renderView\(\); return; \}/.test(grpEnd)
   && grpEnd.indexOf('===was)') < grpEnd.indexOf("api('/api/groups/reorder'"));
ck('and it records the order it started from',
   /onStart:\(\)=>\{ _groupDragFrom=groupOrder\(el\)\.join\(','\); \}/.test(src));
ck('both ends read the group order the same way',
   (grpEnd.match(/groupOrder\(el\)/g)||[]).length===1);

const groupOrder=new Function(grab('groupOrder')+'\nreturn groupOrder;')();
const view=(gids)=>({querySelectorAll:sel=>{
  const heads=gids.map(x=>typeof x==='object'
    ? {dataset:{gid:String(x.clone)},cls:'sortable-drag'} : {dataset:{gid:String(x)}});
  return sel.includes(':not(.sortable-drag)')?heads.filter(h=>!h.cls):heads;}});
ck('the flying copy of the group is not one of the groups',
   groupOrder(view([7,8,{clone:8}])).join(',')==='7,8',
   groupOrder(view([7,8,{clone:8}])).join(','));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
