/* Two things a drag must not do: claim a move that never happened, and take a
   row out of the group it belongs to.

   A drop back onto the row's own place used to POST a move, refetch the board
   and say "הפריט הועבר" — a success message for nothing, which is worse than
   silence because it teaches you the drag worked when it did not. The rule
   holds for all three things a board can drag — an item, a sub-item, a whole
   group — since it is the same false success in each.

   And a drag reorders a group; it does not re-file the item. Which group an
   item belongs to is a decision about the work, made in the item's menu or the
   bulk bar, so each group's tbody is a Sortable of its own with no shared group
   name: a row dragged at another group is refused and springs back. Nothing is
   folded away for the length of the gesture any more, because there is nothing
   further down the board to reach, and nothing is painted on the row once it
   lands — it is under the cursor that just let go of it.
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

// ── the board stays the board while the item is in the air ─────────────────
ck('nothing folds the board up for the length of a drag any more',
   !/dragging-item|dragging-fade|itemDragChrome|itemDragOpen/.test(src));
ck('and no group is opened or closed under the pointer',
   !/drag-open|drag-opened|dragRowIn/.test(src));
ck('the add-item line is an add-item line, not a strip to drop on',
   !/שחרר כאן/.test(src.slice(0, src.indexOf('#chat-panel.dnd-over'))));
ck('and nothing is painted on the row after it lands',
   !/just-moved|justMoved|markMovedRow/.test(src));

// ── how the list is wired ──────────────────────────────────────────────────
const body=(anchor,head)=>{ const i=src.indexOf(anchor); const j=src.indexOf(head,i); let d=0;
  for(let k=src.indexOf('{',j);k<src.length;k++){ if(src[k]==='{')d++; else if(src[k]==='}'){d--; if(!d)return src.slice(j,k+1);} } };
const itemList = body("el.querySelectorAll('.tbl tbody[data-gid]')",'sortableOn(tb,{');
const onEnd = body("el.querySelectorAll('.tbl tbody[data-gid]')",'onEnd:async(evt)=>{');
ck('each group is a list of its own — no shared group name to cross',
   !/group:/.test(itemList), itemList.slice(0,120));
ck('a row is still picked up by the row itself, with the interactive cells filtered',
   /draggable:'tr\[data-tid\]'/.test(itemList) && /filter:'input,textarea/.test(itemList));
ck('the drag records where the row started',
   /_itemDragFrom=itemSpot\(evt\.from,evt\.item\);/.test(itemList));
ck('a top-level item still refuses to land inside a sub-item panel',
   /onMove:evt=>!\(evt\.related&&evt\.related\.classList\.contains\('sub-wrap'\)\)/.test(itemList));
ck('nothing moved → no request and no message',
   onEnd.indexOf('sameSpot(from,spot)') > 0
   && onEnd.indexOf('sameSpot(from,spot)') < onEnd.indexOf("api('/api/tasks/'"),
   'guard at '+onEnd.indexOf('sameSpot(from,spot)'));
ck('a real reorder still says so',
   /toast\(wasSorted\?'סדר הפריטים עודכן — המיון לפי עמודה בוטל':'סדר הפריטים עודכן'\)/.test(onEnd));
ck('and the view is never scrolled anywhere on its own',
   !/scrollIntoView/.test(onEnd));
ck('the move is still sent as a neighbour, not as a row number',
   /group_id:spot\.gid,after_id:spot\.after/.test(onEnd));
/* the group cannot change, so neither can the status: an item is not restated
   as its group's status for being dragged past its neighbours */
ck('a reorder never rewrites the item\'s status',
   /JSON\.stringify\(\{group_id:spot\.gid,after_id:spot\.after,actor_id:meId\(\)\}\)/.test(onEnd)
   && !/status:/.test(onEnd));

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
