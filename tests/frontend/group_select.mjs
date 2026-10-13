/* A checkbox at the group level, the one every item row already had.
   Driven by tests/test_group_select.py.

   Runs the real groupCheckHTML, toggleGroupSelect, syncGroupChecks,
   toggleItemSelect and clearSelection out of index.html against a stand-in DOM,
   because what matters is the arithmetic of the three states and what lands in
   st.selected — not how the box is painted. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const grab = name => {
  const m = new RegExp(`\\nfunction ${name}\\(([^)]*)\\)\\{[\\s\\S]*?\\n\\}`).exec(src);
  if(!m) throw new Error('not found: '+name);
  return m[0];
};
const code = ['groupSelectable','_gidAttr','groupCheckHTML','toggleGroupSelect',
              'syncGroupChecks','toggleItemSelect','clearSelection'].map(grab).join('\n');

/* The board: two groups of three, one item in the first locked for this person.
   `perm` stands in for the item-permission lookup the real canEditItem does. */
const TASKS=[{id:1,group_id:10,perm:'edit'},{id:2,group_id:10,perm:'edit'},{id:3,group_id:10,perm:'view'},
             {id:4,group_id:20,perm:'edit'},{id:5,group_id:20,perm:'edit'},{id:6,group_id:20,perm:'edit'}];
const st={selected:new Set(),board:{id:1,tasks:TASKS,groups:[{id:10,name:'א'},{id:20,name:'ב'}]}};

/* one <input> per group header and one per row, enough of the DOM for the
   functions to find what they reach for */
function mkBox(cls,gid){
  const box={checked:false,indeterminate:false,className:cls,dataset:{},
             closest:sel=>sel==='.group-head'?head:(sel==='.group'?group:null)};
  return box;
}
const rows=TASKS.map(t=>({dataset:{tid:String(t.id)},cls:new Set(),box:{checked:false},
  classList:{toggle(c,on){on?rows.find(r=>r.box===this._b).cls.add(c):0;}}}));
// a row object the functions can drive: classList.toggle and querySelector
TASKS.forEach((t,i)=>{
  const r=rows[i];
  r.classList={toggle:(c,on)=>{ on?r.cls.add(c):r.cls.delete(c); },
               remove:c=>r.cls.delete(c), add:c=>r.cls.add(c)};
  r.querySelector=sel=>sel==='.item-check'?r.box:null;
});
let group={querySelectorAll:sel=>sel==='tr[data-tid]'?rows.filter(r=>inScope.has(+r.dataset.tid)):[]};
let head={dataset:{gid:'10'},closest:sel=>sel==='.group'?group:null};
let inScope=new Set([1,2,3]);
const boxes={};                                 // the header boxes, by gid
['10','20'].forEach(g=>{ boxes[g]={checked:false,indeterminate:false,dataset:{gid:g},
  closest:sel=>sel==='.group'?group:null}; });

const doc={querySelectorAll:sel=>{
  if(sel==='.grp-check') return Object.values(boxes);
  if(sel==='tr.row-sel') return rows.filter(r=>r.cls.has('row-sel'));
  if(sel==='.item-check:checked') return rows.filter(r=>r.box.checked).map(r=>r.box);
  return [];
}};

const F=new Function('st','document','canEditItem','groupsOf','renderSelBar','closeCellPops','esc',
  code+`; return {groupCheckHTML,toggleGroupSelect,syncGroupChecks,toggleItemSelect,clearSelection,groupSelectable};`)(
  st, doc,
  t=>t.perm==='edit'||t.perm==='delete',
  ()=>[{id:10,name:'א',tasks:TASKS.filter(t=>t.group_id===10)},
       {id:20,name:'ב',tasks:TASKS.filter(t=>t.group_id===20)}],
  ()=>{}, ()=>{}, x=>String(x==null?'':x));

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the box itself ──
const g10={id:10,name:'א',tasks:TASKS.filter(t=>t.group_id===10)};
let h=F.groupCheckHTML(g10);
ck('a group gets a checkbox of its own', /class="grp-check"/.test(h), h);
ck('...that says what it does', h.includes('סימון כל הפריטים בקבוצה'), h);
ck('...and names its group, including the "ללא קבוצה" one as empty',
   h.includes("toggleGroupSelect(event,'10')") && h.includes('data-gid="10"') &&
   F.groupCheckHTML({id:null,tasks:[TASKS[0]]}).includes('data-gid=""'), h);
ck('a group with nothing this person may edit shows no box',
   F.groupCheckHTML({id:30,tasks:[{id:9,perm:'view'}]})==='' , F.groupCheckHTML({id:30,tasks:[{id:9,perm:'view'}]}));
ck('an empty group shows no box', F.groupCheckHTML({id:31,tasks:[]})==='');

// ── ticking it ──
const tick=(gid,on)=>{ const b=boxes[gid]; b.checked=on;
  inScope=new Set(TASKS.filter(t=>t.group_id===+gid).map(t=>t.id));
  F.toggleGroupSelect({stopPropagation(){},
    currentTarget:{checked:on,dataset:{gid},closest:s=>s==='.group'?group:null}},gid); };

tick('10',true);
ck('ticking a group selects its items', st.selected.has(1)&&st.selected.has(2));
ck('...but never one the person may not edit — it has no box of its own', !st.selected.has(3),
   [...st.selected].join(','));
ck('...and nothing in another group', !st.selected.has(4));
ck('the rows it covers are painted as selected',
   rows[0].cls.has('row-sel')&&rows[1].cls.has('row-sel')&&!rows[2].cls.has('row-sel'));
ck('...and their own boxes are ticked', rows[0].box.checked&&rows[1].box.checked&&!rows[2].box.checked);
ck('the group box reads as full, not partial',
   boxes['10'].checked===true&&boxes['10'].indeterminate===false,
   JSON.stringify(boxes['10']));

// ── the third state ──
rows[1].box.checked=false;
F.toggleItemSelect({stopPropagation(){},currentTarget:{checked:false,closest:s=>s==='tr'?rows[1]:null}},2);
ck('unticking one row leaves the group partially selected',
   boxes['10'].checked===false&&boxes['10'].indeterminate===true,
   JSON.stringify(boxes['10']));
ck('...and the row itself is no longer painted', !rows[1].cls.has('row-sel'));

// ── untick the group ──
tick('10',false);
ck('unticking the group drops its items from the selection', st.selected.size===0,
   [...st.selected].join(','));
ck('...and the box is neither full nor partial',
   boxes['10'].checked===false&&boxes['10'].indeterminate===false);

// ── two groups at once, and clearing ──
tick('10',true); tick('20',true);
ck('two groups can be selected together', st.selected.size===5, [...st.selected].join(','));
ck('both boxes read full', boxes['10'].checked&&boxes['20'].checked);
F.clearSelection();
ck('clearing empties the selection', st.selected.size===0);
ck('...and resets every group box, the partial one included',
   Object.values(boxes).every(b=>!b.checked&&!b.indeterminate));
ck('...and unpaints the rows', rows.every(r=>!r.cls.has('row-sel')));

// ── wiring that only the source can answer ──
ck('the box lives in the column-headers row, in the item column',
   /const box=c\.key==='item'&&sel\?`<span class="th-sel">\$\{sel\}<\/span>`:''/.test(src), 'not in the item <th>');
ck('...which is where the header row asks for it',
   /columnHeadersHTML\(col,g\)/.test(src) && /class="col-head-row">\$\{columnHeadersHTML/.test(src));
ck('the group header no longer carries one', !/\$\{groupCheckHTML\(g\)\}\s*\n\s*<span class="g-nm">/.test(src));
ck('it is placed at the column start, where the item checkboxes are',
   /\.th-sel\{position:absolute;inset-inline-start:12px/.test(src) &&
   /\.tbl \.c-item\{position:relative;font-weight:500;padding:6px 12px/.test(src),
   'the box and the boxes under it are in one column only if both sit at 12px');
ck('each box carries its own group, so sync needs no ancestor',
   /data-gid="\$\{_gidAttr\(g\)\}"/.test(src) && /box\.dataset\.gid/.test(src));
ck('a click on it never folds the group or starts a drag',
   /function toggleGroupSelect\(e,gid\)\{\s*\n\s*e\.stopPropagation\(\)/.test(src));
ck('the three states are re-derived after every render',
   /syncGroupChecks\(\);\s*\/\/ indeterminate/.test(src));
ck('ticking a row keeps the group box honest', /renderSelBar\(\); syncGroupChecks\(\);/.test(src));
ck('the phone hides it, like the row boxes beside it',
   /\.grp-check\{display:none\}/.test(src) && /\.item-check\{display:none\}/.test(src));
ck('a group holding part of the selection stays visible without a hover',
   /\.grp-check:indeterminate\{?/.test(src) &&
   /\.col-head-row:hover \.grp-check,\.grp-check:checked,\.grp-check:indeterminate/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
