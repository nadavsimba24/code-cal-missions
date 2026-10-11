/* What switches item drag off, and what must never switch it off.

   An item is grabbed by the row itself, so on a touch screen the drag gesture
   and the scroll swipe are the same press-and-move — hence the rule. The rule
   was written as "narrow window", which is a different question: a browser
   zoomed to 175% on a 1440px screen reports 823 CSS pixels, and item drag
   turned itself off on a desktop, with a mouse, silently.

   Also guards the date cell, whose invisible input covers the whole cell: if it
   can be a click target, the row's own drag filter (.cc-inp) matches it and a
   row grabbed there never lifts. Driven by tests/test_item_drag_enabled.py. */
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
const TOUCH_Q = /^const TOUCH_Q=.*$/m.exec(src)[0];

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

/* the real isTouch, over a stub that answers one media query honestly */
function isTouchWhen(queries){
  const win={matchMedia:q=>({matches:!!queries[q]})};
  return new Function('window', TOUCH_Q+'\n'+grab('isTouch')+'; return isTouch;')(win)();
}

ck('a finger switches item drag off',
   isTouchWhen({'(pointer:coarse)':true}) === true);
ck('a mouse leaves it on',
   isTouchWhen({'(pointer:coarse)':false}) === false);
ck('a narrow window with a mouse leaves it on — zoom is not a phone',
   isTouchWhen({'(pointer:coarse)':false, '(max-width:820px)':true}) === false);
ck('a browser too old for matchMedia leaves it on rather than off',
   new Function('window', TOUCH_Q+'\n'+grab('isTouch')+'; return isTouch;')({})() === false);

// ── the lists themselves ──
const disabled = src.match(/disabled:is\w+\(\)/g) || [];
ck('every draggable item list asks the pointer, not the width',
   disabled.length===3 && disabled.every(d=>d==='disabled:isTouch()'), disabled.join(' '));
ck('and the live re-sync asks the same question',
   /function syncItemDrag\(\)\{[\s\S]*?const off=isTouch\(\);/.test(src));

/* ── the date cell must not eat the row's drag ──
   The native input covers the whole cell, so if it could be the click target
   the entire date cell became undraggable and a row grabbed there never
   lifted. It takes no clicks at all now: the typable box and the calendar
   button are what the cell offers, and the native input is only the value and
   the picker's anchor. */
const rule = /\.cc-datewrap \.cc-date\{[^}]*\}/.exec(src);
ck('the date input cannot be a click target at rest',
   rule && rule[0].includes('pointer-events:none'), rule&&rule[0]);
ck('and only takes the pointer back where showPicker cannot be asked at all',
   /\.cc-datewrap\.cc-fallback \.cc-date\{[^}]*pointer-events:auto/.test(src));
ck('what the cell offers instead is a typable box and a calendar button',
   src.includes('class="cc-inp cc-date-txt"') && src.includes('class="cc-date-cal"')
   && src.includes('onclick="dateCellPick(event)"'));
ck('the row drag filter still skips real inputs',
   /filter:'input,textarea,select,button,a,\[contenteditable\],\.cc-inp/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
