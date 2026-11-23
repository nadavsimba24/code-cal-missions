/* A sub-item carries the same selection box an item does, and the bulk bar
   acts on it. Driven by tests/test_a_sub_item_can_be_ticked.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const fnSrc = name => {
  let i = src.indexOf('\nfunction '+name+'(');
  if (i < 0) i = src.indexOf('\nasync function '+name+'(');
  if (i < 0) throw new Error('not found: '+name);
  const j = src.indexOf('\n}\n', i);
  return src.slice(i+1, j+2);
};

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// a parent (1) with three sub-items, one of which (12) this person may not edit
const board = [{id:1, title:'P', subtasks:[{id:11,parent_id:1},{id:12,parent_id:1,ro:true},{id:13,parent_id:1}]},
               {id:2, title:'Q', subtasks:[{id:21,parent_id:2}]}];
const st = {selected:new Set()};
const findAnyTask = id => { for (const t of board){ if (t.id==id) return t; for (const s of t.subtasks) if (s.id==id) return s; } return null; };
const canEditItem = t => !t.ro;
const f = new Function('st','findAnyTask','canEditItem',
  fnSrc('subSelectable')+fnSrc('subGroupCheckHTML')+fnSrc('_selectedTopItems')+fnSrc('_selectedSubItems')
  +'\nreturn {subSelectable,subGroupCheckHTML,_selectedTopItems,_selectedSubItems};')(st, findAnyTask, canEditItem);

// ── the parent's box ──
ck('the header box covers the sub-items this person may edit, and only those',
   f.subSelectable(1).map(s=>s.id).join()==='11,13');
ck('a parent with nothing editable draws no box', f.subGroupCheckHTML(99)==='');
ck('unticked, the box is drawn unchecked', !/checked/.test(f.subGroupCheckHTML(1).replace('sub-grp-check','')));
st.selected = new Set([11,13]);
ck('every editable sub-item ticked → the box is checked', / checked /.test(f.subGroupCheckHTML(1)));
ck('the parent id lands in the markup as an integer — nothing past the digits gets in',
   !/alert/.test(f.subGroupCheckHTML('1)alert(1')) && /toggleSubGroupSelect\(event,1\)/.test(f.subGroupCheckHTML('1)alert(1')));

// ── the bar ──
st.selected = new Set([2, 11, 21]);
ck('a ticked sub-item is not a top item (move skips it)', f._selectedTopItems().map(t=>t.id).join()==='2');
ck('a ticked sub-item is one the bar deletes', f._selectedSubItems().map(t=>t.id).join()==='11');
ck('...but not when its parent is ticked too — the parent takes it along',
   !f._selectedSubItems().some(s=>s.id===21));

// ── where the page uses them ──
const row = fnSrc('subItemRowHTML');
ck('a sub-item row draws the item checkbox, wired to the same selection',
   /class="item-check"[^`]*toggleItemSelect\(event,\$\{sid\}\)/.test(row));
ck('...only where the person may edit the sub-item', /canEditItem\(s\)\?`<input type="checkbox"/.test(row));
ck('a ticked sub-item row is painted selected', /\$\{st\.selected\.has\(sid\)\?' row-sel':''\}/.test(row));
ck('the sub-item header draws the parent box', /\$\{subGroupCheckHTML\(parentId\)\}/.test(fnSrc('subHeadHTML')));
ck('bulk delete takes the ticked sub-items',
   /_selectedTopItems\(\)\.concat\(_selectedSubItems\(\)\)/.test(fnSrc('bulkDelete')));
const dup = fnSrc('bulkDuplicate');
ck('bulk duplicate copies a sub-item under its own parent', /parent_id:s\.parent_id/.test(dup));
ck('...and a selection of sub-items alone is not ignored', !/const items=_selectedTopItems\(\); if\(!items\.length\)return;/.test(dup));
ck('move tells a sub-item-only selection why it cannot move', /תת-פריט עובר יחד עם הפריט שלו/.test(fnSrc('bulkMoveMenu')));
const tog = fnSrc('toggleSubs');
ck('folding a panel takes its sub-items out of the selection', /if\(!open\)\{[\s\S]*st\.selected\.delete\(s\.id\)/.test(tog));
ck('clearing the selection empties the parent boxes too', /querySelectorAll\('\.sub-grp-check'\)/.test(fnSrc('clearSelection')));
ck('the group sync re-reads the parent boxes', /syncSubGroupChecks\(\);/.test(fnSrc('syncGroupChecks')));
ck('on a phone the parent box hides with the item box', /\.sub-grp-check\{display:none\}/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
