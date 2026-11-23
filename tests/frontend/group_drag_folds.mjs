/* Reordering groups by dragging, with the board open. The board folds for the
   length of the drag and unfolds into whatever it was. Runs the real foldGroup,
   foldGroupsForDrag and unfoldGroupsAfterDrag out of index.html against a stub
   DOM. Driven by tests/test_group_drag_folds.py. */
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
const gKey = /const _gKey=.*?;/.exec(src)[0];

/* ── a board of groups, as much DOM as these functions touch ───────────── */
function board(spec){           // [{gid:'7', open:true}, {gid:null, open:true}]
  const heads=[];
  spec.forEach(g=>{
    const cls=new Set(g.open?[]:['collapsed']);
    const table={style:{display:g.open?'':'none'}};
    const batt={hidden:!g.open};
    const grp={batt, orphan:g.gid===null, querySelector:sel=>sel==='.grp-batt'?batt:null};
    heads.push({_grp:grp, _table:table,
      dataset:g.gid===null?{}:{gid:String(g.gid)},
      classList:{toggle(c,on){on?cls.add(c):cls.delete(c)},contains:c=>cls.has(c)},
      nextElementSibling:table, closest:()=>grp});
  });
  const el={querySelectorAll:()=>heads};
  const document={querySelector:sel=>{
    if(sel==='.group[data-orphan] .group-head') return heads.find(h=>h._grp.orphan)||null;
    const m=/\[data-gid="([^"]*)"\]/.exec(sel);
    return m?(heads.find(h=>h.dataset.gid===m[1])||null):null;
  }};
  const st={collapsedGroups:new Set()};
  spec.forEach((g,i)=>{ if(!g.open) st.collapsedGroups.add(g.gid===null?'none':String(g.gid)); });
  const api=new Function('st','document','return (()=>{'+gKey+`
    function setGroupCollapsed(gid,shut){ if(shut)st.collapsedGroups.add(_gKey(gid)); else st.collapsedGroups.delete(_gKey(gid)); }
    let _groupFoldedForDrag=null;
    ${grab('foldGroup')}
    ${grab('foldGroupsForDrag')}
    ${grab('unfoldGroupsAfterDrag')}
    return {foldGroup,foldGroupsForDrag,unfoldGroupsAfterDrag,state:()=>_groupFoldedForDrag};
  })()`)(st,document);
  return {heads,el,st,...api,
    shut:()=>heads.map(h=>h.classList.contains('collapsed')),
    tables:()=>heads.map(h=>h._table.style.display),
    batts:()=>heads.map(h=>h._grp.batt.hidden)};
}

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

/* 1 — an open board folds whole for the drag, and comes back */
{
  const b=board([{gid:'7',open:true},{gid:'8',open:true}]);
  b.foldGroupsForDrag(b.el);
  ck('every open group folds when the drag is picked up', b.shut().every(Boolean), JSON.stringify(b.shut()));
  ck('...their tables are hidden with them', b.tables().every(d=>d==='none'));
  ck('...and the progress bars', b.batts().every(Boolean));
  ck('...and the state remembers it, so a re-render mid-drag agrees',
     [...b.st.collapsedGroups].sort().join()==='7,8', [...b.st.collapsedGroups].join());
  b.unfoldGroupsAfterDrag();
  ck('the drop gives the board back', b.shut().every(x=>!x), JSON.stringify(b.shut()));
  ck('...tables and bars too', b.tables().every(d=>d==='') && b.batts().every(h=>!h));
  ck('...and the state is clean', b.st.collapsedGroups.size===0, [...b.st.collapsedGroups].join());
}

/* 2 — a group the user had folded stays folded afterwards */
{
  const b=board([{gid:'7',open:true},{gid:'8',open:false}]);
  b.foldGroupsForDrag(b.el);
  ck('a board with one group already shut folds the rest', b.shut().every(Boolean));
  b.unfoldGroupsAfterDrag();
  ck('the group the user had closed is still closed', b.shut().join()==='false,true', b.shut().join());
  ck('...and it is still in the remembered state', [...b.st.collapsedGroups].join()==='8');
}

/* 3 — a press that never became a drag */
{
  const b=board([{gid:'7',open:true}]);
  b.foldGroupsForDrag(b.el);
  b.unfoldGroupsAfterDrag();
  ck('a click on the name leaves the board exactly as it was', !b.shut()[0] && b.st.collapsedGroups.size===0);
}

/* 4 — unfolding twice, which is what a drop does (onUnchoose and onEnd both) */
{
  const b=board([{gid:'7',open:true}]);
  b.foldGroupsForDrag(b.el);
  b.unfoldGroupsAfterDrag();
  b.unfoldGroupsAfterDrag();
  ck('restoring twice is harmless', !b.shut()[0] && b.state()===null);
}

/* 5 — folding twice inside one drag does not lose the original state */
{
  const b=board([{gid:'7',open:true},{gid:'8',open:false}]);
  b.foldGroupsForDrag(b.el);
  b.foldGroupsForDrag(b.el);          // a second choose event
  b.unfoldGroupsAfterDrag();
  ck('a second choose does not swallow which groups were open',
     b.shut().join()==='false,true', b.shut().join());
}

/* 6 — the group with no id of its own ("ללא קבוצה") */
{
  const b=board([{gid:'7',open:true},{gid:null,open:true}]);
  b.foldGroupsForDrag(b.el);
  ck('the orphan group folds under its own key', b.st.collapsedGroups.has('none'));
  b.unfoldGroupsAfterDrag();
  ck('...and is found again to be unfolded', !b.shut()[1] && b.st.collapsedGroups.size===0);
}

/* 7 — the wiring */
ck('the fold happens on choose, before the clone is cut',
   // the drag also switches text selection off on the same press (ItemDrag)
   /onChoose:\(\)=>\{ (?:ItemDrag\.noSelect\(true\); )?foldGroupsForDrag\(el\); \}/.test(src),
   'onStart would drag a full open table around the screen');
ck('the restore happens on unchoose as well as on the drop',
   /onUnchoose:\(\)=>\{ (?:ItemDrag\.noSelect\(false\); )?unfoldGroupsAfterDrag\(\); \}/.test(src));
ck('onEnd restores before anything re-renders from the state',
   /unfoldGroupsAfterDrag\(\);\s*\/\/ before any renderView/.test(src));
ck('the caret goes through the same one place',
   /foldGroup\(h,!h\.classList\.contains\('collapsed'\)\)/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
