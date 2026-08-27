/* On a phone the pinned item column gives back up to 40% of its width as the
   user scrolls sideways, and never more. Runs the real syncItemColWidth out of
   index.html against a stub layout. Driven by tests/test_item_col_shrink.py. */
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
const consts = /const ITEM_COL_SHRINK=[\s\S]*?const ITEM_COL_RAMP=\d+;/.exec(src)[0];

// ── stub layout ──
const BASE = 280;
let mobile = true, scrollLeft = 0, clientWidth = 390, fullTableWidth = 1200;
const cols = [ {style:{width:BASE+'px'}}, {style:{width:BASE+'px'}} ];   // two groups
const view = {
  querySelectorAll: () => cols,
  get clientWidth(){ return clientWidth; },
  get scrollLeft(){ return scrollLeft; },
  // the table is as wide as it is, minus whatever the column has given back
  get scrollWidth(){ return fullTableWidth - (BASE - parseFloat(cols[0].style.width)); },
};
global.document = { getElementById: id => (id==='view' ? view : null) };

const sync = new Function('document','colWidthMap','isMobile',
  consts + '\n' + grab('syncItemColWidth') + '; return syncItemColWidth;')
  (global.document, ()=>({item:BASE}), ()=>mobile);

const width = () => parseFloat(cols[0].style.width);
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── opens at full width ──
scrollLeft = 0; sync();
ck(`opens at its full width (${width()}px)`, width()===BASE, `got ${width()}`);

// ── gives width back as you scroll ──
scrollLeft = 70; sync();
const half = width();
ck(`halfway across it has given some back (${half}px)`, half<BASE && half>BASE*0.6, `got ${half}`);

scrollLeft = 140; sync();
ck(`fully scrolled it is at 60% (${width()}px of ${BASE})`, width()===Math.round(BASE*0.6), `got ${width()}`);

// ── the 40% floor is a floor ──
scrollLeft = 5000; sync();
ck('scrolling far past the ramp never shrinks it further', width()===Math.round(BASE*0.6), `got ${width()}`);
ck('it never gives back more than 40%', (BASE-width())/BASE <= 0.40+1e-9);

// ── monotonic: it must not jitter as the finger moves ──
let prev=BASE, monotonic=true;
for(let x=0; x<=200; x+=7){ scrollLeft=x; sync(); if(width()>prev+0.001) monotonic=false; prev=width(); }
ck('the width only ever decreases as the scroll advances', monotonic);

// ── scrolling back restores it ──
scrollLeft = 0; sync();
ck('scrolling back to the start restores the full width', width()===BASE, `got ${width()}`);

// ── RTL: scrollLeft is negative, the behaviour must be identical ──
scrollLeft = -140; sync();
ck('RTL negative scrollLeft shrinks the same way', width()===Math.round(BASE*0.6), `got ${width()}`);

// ── desktop is untouched ──
mobile=false; scrollLeft=140; sync();
ck('on desktop the column keeps its full width', width()===BASE, `got ${width()}`);
mobile=true;

// ── a board that barely overflows must not oscillate ──
fullTableWidth = clientWidth + 60;      // less overflow than give(112) + ramp(140)
scrollLeft = 0; sync();
const settled = width();
ck('a barely-overflowing board does not shrink at all', settled===BASE, `got ${settled}`);
scrollLeft = 50; sync();
ck('...and stays put when scrolled', width()===BASE, `got ${width()}`);
// run it repeatedly at a fixed scroll position: the width must reach a fixed point
fullTableWidth = 1200; scrollLeft = 140;
const seen=[]; for(let i=0;i<6;i++){ sync(); seen.push(width()); }
ck('repeated recomputation settles instead of flip-flopping', new Set(seen).size===1, seen.join(','));

// ── every group's table is kept in step ──
ck('all the group tables get the same width', cols.every(c=>c.style.width===cols[0].style.width));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
