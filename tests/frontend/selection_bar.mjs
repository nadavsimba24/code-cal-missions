/* Ticking an item, opening "העברה", then unticking used to leave the
   destination menu floating over the board. The bar's menus are appended to
   <body> so the table cannot clip them, so hiding the bar did not take them
   along. Run by tests/test_selection_bar.py.

   The DOM here is a stub: only the handful of operations renderSelBar actually
   performs, which is enough to run the real function unmodified. */
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

// ── a DOM small enough to reason about, real enough to run the code ──
function mkEl(id){ return { id, _cls:new Set(), _attrs:{}, _kids:[], _parent:null, _anchor:null,
  classList:{ add(c){this._o._cls.add(c)}, remove(c){this._o._cls.delete(c)},
              toggle(c,on){ on?this._o._cls.add(c):this._o._cls.delete(c) },
              contains(c){return this._o._cls.has(c)} },
  setAttribute(k,v){this._attrs[k]=v},
  contains(n){ let p=n; while(p){ if(p===this) return true; p=p._parent; } return false; },
  remove(){ POPS = POPS.filter(x=>x!==this); this._removed=true; } }; }
function wire(e){ e.classList._o=e; return e; }

let POPS=[];
const bar=wire(mkEl('sel-bar'));
const barBtn=wire(mkEl('bulk-move-btn')); barBtn._parent=bar;
const someCell=wire(mkEl('a-cell-elsewhere'));      // not in the bar
const nEl=wire(mkEl('sel-n'));

global.document={
  getElementById:id=>({'sel-bar':bar,'sel-n':nEl}[id]||null),
  querySelectorAll:sel=>{ if(sel==='.cell-pop') return POPS.slice(); return []; },
};
const st={selected:new Set()};
const renderSelBar=new Function('document','st', grab('renderSelBar')+'; return renderSelBar;')(global.document,st);

const openBarMenu=()=>{ const p=wire(mkEl('move-menu')); p._anchor=barBtn; POPS.push(p); return p; };
const openOtherPop=()=>{ const p=wire(mkEl('other-pop')); p._anchor=someCell; POPS.push(p); return p; };

let pass=0,fail=0; const ck=(n,c)=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n));};

// ── the reported bug ──
st.selected.add(101); renderSelBar();
ck('ticking an item shows the bar', bar._cls.has('show'));
const menu=openBarMenu();
ck('the move menu is open', POPS.includes(menu));
st.selected.delete(101); renderSelBar();               // user changes their mind
ck('unticking hides the bar', !bar._cls.has('show'));
ck('...and the move menu goes with it', !POPS.includes(menu));
ck('...and the bar is hidden from assistive tech', bar._attrs['aria-hidden']==='true');

// ── it must not close popovers that are not the bar's ──
st.selected.add(202); renderSelBar();
const mine=openOtherPop(); const barMenu=openBarMenu();
st.selected.delete(202); renderSelBar();
ck('an unrelated cell popover is left open', POPS.includes(mine));
ck('the bar menu is still closed', !POPS.includes(barMenu));

// ── reducing the selection without emptying it keeps the menu ──
st.selected.add(1); st.selected.add(2); renderSelBar();
const m2=openBarMenu();
st.selected.delete(1); renderSelBar();
ck('going 2 -> 1 keeps the menu open (still a valid selection)', POPS.includes(m2));
ck('...and the bar stays visible', bar._cls.has('show'));
st.selected.delete(2); renderSelBar();
ck('going 1 -> 0 finally closes it', !POPS.includes(m2));

// ── switching boards clears the selection (openBoard, line ~2375) ──
st.selected.add(7); renderSelBar(); const m3=openBarMenu();
st.selected.clear(); renderSelBar();
ck('leaving the board with the menu open also closes it', !POPS.includes(m3));

// ── the count shown to the user tracks the selection ──
st.selected.add(1); st.selected.add(2); st.selected.add(3); renderSelBar();
ck('the bar reports the right count', nEl.textContent===3);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
