/* Two things a drag must not do: claim a move that never happened, and make
   you scroll the whole board with a row held down.

   A drop back onto the row's own place used to POST a move, refetch the board
   and say "הפריט הועבר" — a success message for nothing, which is worse than
   silence because it teaches you the drag worked when it did not. And because
   a move between groups meant reaching the other group, the common way for a
   drag to end nowhere was running out of screen. So for the length of the
   gesture the board shrinks to its group names, each group's "+ הוסף פריט"
   line left showing as the strip to drop on, and the group under the pointer
   opens again.

   The "nothing moved, nothing announced" rule holds for all three things that
   can be dragged on a board — an item, a sub-item, a whole group — since it is
   the same false success in each. Driven by tests/test_item_drag_feedback.py. */
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
const cls=()=>{const s=new Set();return{add:c=>s.add(c),remove:c=>s.delete(c),
  contains:c=>s.has(c),toggle:(c,on)=>{on?s.add(c):s.delete(c);}};};
function stage(){
  const tds=[{dataset:{},textContent:'+ הוסף פריט'},{dataset:{},textContent:'+ הוסף פריט'}];
  const tbs=[{dataset:{gid:'3'},classList:cls()},{dataset:{gid:'4'},classList:cls()}];
  const doc={body:{classList:cls()},querySelectorAll:sel=>
    sel.includes('.add-row td')?tds : sel==='tbody.drag-open'?tbs.filter(t=>t.classList.contains('drag-open'))
    : sel==='.tbl tbody[data-gid]'?tbs : []};
  const fns=new Function('document',grab('itemDragChrome')+'\n'+grab('itemDragOpen')
    +'\nreturn {itemDragChrome,itemDragOpen};')(doc);
  return {doc,tds,tbs,...fns};
}

let s1=stage();
s1.itemDragChrome(true);
ck('the board is marked as having an item in the air',
   s1.doc.body.classList.contains('dragging-item'));
ck('every group\'s add-item line becomes the strip to drop on',
   s1.tds.every(td=>td.textContent==='שחרר כאן'));
s1.itemDragChrome(false);
ck('and says what it said before once the drag is over',
   s1.tds.every(td=>td.textContent==='+ הוסף פריט'),
   s1.tds.map(t=>t.textContent).join('|'));
ck('the mark comes off with it — a finished drag leaves no shrunk board',
   !s1.doc.body.classList.contains('dragging-item'));

s1=stage();
s1.itemDragChrome(true); s1.itemDragChrome(true);   // onStart can fire twice in a session
s1.itemDragChrome(false);
ck('two drags in a row still restore the real label, not "שחרר כאן"',
   s1.tds.every(td=>td.textContent==='+ הוסף פריט'),
   s1.tds.map(t=>t.textContent).join('|'));

const s2=stage();
s2.itemDragOpen(s2.tbs[1]);
ck('the group under the pointer opens, so a place inside it can still be chosen',
   !s2.tbs[0].classList.contains('drag-open') && s2.tbs[1].classList.contains('drag-open'));
s2.itemDragOpen(s2.tbs[0]);
ck('and only one is ever open — moving on shuts the last one',
   s2.tbs[0].classList.contains('drag-open') && !s2.tbs[1].classList.contains('drag-open'));
s2.itemDragOpen(null);
ck('the drag starts with every group shut',
   s2.tbs.every(t=>!t.classList.contains('drag-open')));
const s3=stage();
s3.itemDragOpen(s3.tbs[0]); s3.itemDragChrome(false);
ck('an open group does not stay open after the drag',
   s3.tbs.every(t=>!t.classList.contains('drag-open')));

// ── the rules that do the shrinking ────────────────────────────────────────
const at=re=>{const m=re.exec(src);return m?m.index:-1;};
const hide=/body\.dragging-item \.tbl tbody\[data-gid\]>tr\[data-tid\]([^{]*)\{display:none\}/.exec(src);
ck('the item rows are hidden while an item is in the air', !!hide);
ck('except the placeholder, which is where the row will land',
   hide && hide[1].includes(':not(.sortable-ghost)'), hide&&hide[0]);
ck('and except the copy that follows the cursor — Sortable parks it in the same tbody',
   hide && hide[1].includes(':not(.sortable-drag)'), hide&&hide[0]);
ck('the opened group shows its rows again',
   /body\.dragging-item \.tbl tbody\[data-gid\]\.drag-open>tr\[data-tid\]\{display:table-row\}/.test(src));
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

// ── how the list is wired to all of it ─────────────────────────────────────
const onEnd = (()=>{ const i=src.indexOf("group:'board-items'");
  const j=src.indexOf('onEnd:async(evt)=>{',i); let d=0;
  for(let k=src.indexOf('{',j);k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){d--; if(!d)return src.slice(j,k+1);} } })();
const start = /onStart:evt=>\{ _itemDragFrom=itemSpot\(evt\.from,evt\.item\); itemDragOpen\(null\); itemDragChrome\(true\); \}/.test(src);
ck('the drag records where the row started, and shrinks the board', start);
ck('the board comes back before anything else happens at the end',
   /^onEnd:async\(evt\)=>\{\s*itemDragChrome\(false\);/.test(onEnd));
ck('the group under the pointer is opened from onMove',
   /onMove:evt=>\{ itemDragOpen\(evt\.to\);/.test(src));
ck('nothing moved → no request and no message',
   onEnd.indexOf('sameSpot(from,spot)') > 0
   && onEnd.indexOf('sameSpot(from,spot)') < onEnd.indexOf("api('/api/tasks/'"),
   'guard at '+onEnd.indexOf('sameSpot(from,spot)'));
ck('a real move still says so',
   /toast\(wasSorted\?'הפריט הועבר — המיון לפי עמודה בוטל':'הפריט הועבר'\)/.test(onEnd));
ck('the move is still sent as a neighbour, not as a row number',
   /const body=\{group_id:gid,after_id:spot\.after\}/.test(onEnd));

const subEnd = (()=>{ const i=src.indexOf("'.sub-body[data-parent]'");
  const j=src.indexOf('onEnd:async(evt)=>{',i); let d=0;
  for(let k=src.indexOf('{',j);k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){d--; if(!d)return src.slice(j,k+1);} } })();
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
const grpEnd = (()=>{ const i=src.indexOf("draggable:'.group'");
  const j=src.indexOf('onEnd:async()=>{',i); let d=0;
  for(let k=src.indexOf('{',j);k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){d--; if(!d)return src.slice(j,k+1);} } })();
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
