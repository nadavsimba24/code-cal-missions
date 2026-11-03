/* A cell that could not show all of its value says the rest on hover.

   This started as the browser's own `title`, which is the obvious way and the
   wrong one twice over. First, a title on the <span> holding the name answers
   only a pointer that landed exactly on the letters — and the name cell is
   mostly checkbox, menu, caret and chat button, so hovering "the name" usually
   hit nothing at all. Second, the browser waits about a second and a half
   before it shows a title, which is long enough that the value looks like it
   was never there: the feature was reported as not working twice before the
   delay turned out to be the whole of it.

   So the value hangs on the CELL as well as on the text inside it, it travels
   in data-tipf rather than in title — an element carrying both would answer
   twice, ours at once and the browser's a second later on top of it — and a
   delegated listener on the document draws it.
   Driven by tests/test_cell_hover_full_value.py. */
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

// ── the value is on the cell, not only on the text ────────────────────────
ck('the item-name cell carries the whole title',
   /<td class="c-item"[^>]*\sdata-tipf="\$\{esc\(t\.title\)\}"/.test(src));
ck('and so does the sub-item name cell',
   /<td class="sub-name-cell" data-tipf="\$\{esc\(s\.title\)\}">/.test(src));
ck('the name itself carries it too, with the "what a click does" line',
   (src.match(/<span class="item-title editable" data-tipf="\$\{esc\([ts]\.title\)\}" data-tiph="[^"]+"/g)||[]).length===2);
ck('a text cell hangs it on the <td> and on the <input>',
   /if\(c\.type==='text'\)\s+return `<td class="cell cell-custom" data-tipf="[^"]+"><input class="cc-inp"[^>]*\sdata-tipf="/.test(src));
ck('and so does a long-text cell',
   /if\(c\.type==='long_text'\) return `<td class="cell cell-custom" data-tipf="[^"]+"><input class="cc-inp"[^>]*\sdata-tipf="/.test(src));
/* typing into the cell moves the value; a tooltip still showing what was there
   before is worse than no tooltip at all */
ck('typing updates both of them',
   (src.match(/oninput="this\.dataset\.tipf=this\.value;this\.parentNode\.dataset\.tipf=this\.value"/g)||[]).length===2);

// ── and the browser's own slow one is not left on top of ours ─────────────
const nameRow = /<td class="c-item"[\s\S]{0,2000}?<\/div><\/td>/.exec(src);
ck('the item name has no `title` left to fire a second time, a second later',
   !!nameRow && !/<span class="item-title editable"[^>]*\stitle=/.test(nameRow[0]),
   nameRow && (/<span class="item-title editable"[^>]*>/.exec(nameRow[0])||[''])[0]);
ck('neither do the text cells',
   !/c\.type==='(?:text|long_text)'\)\s*return `<td class="cell cell-custom"[^`]*\stitle=/.test(src));

// ── the listener is delegated, and quick ──────────────────────────────────
ck('one listener on the document, so a re-rendered grid needs no re-binding',
   /document\.addEventListener\('mouseover',\s*e=>\{[\s\S]{0,300}?closest\('\[data-tipf\]'\)/.test(src));
const delay = /cellTipShow\(el\);?\s*\},\s*(\d+)\s*\)/.exec(src);
ck('and it draws far sooner than the browser would', !!delay && +delay[1]<=300,
   delay?delay[1]+'ms':'no delay found');
ck('scrolling or pressing takes the box away with the cell',
   /addEventListener\('mousedown',cellTipHide,true\)/.test(src) &&
   /addEventListener\('scroll',cellTipHide,true\)/.test(src));

// ── the drawing itself, run for real ──────────────────────────────────────
const show = eval('(' + grab('cellTipShow').replace(/^function cellTipShow/,'function') + ')');
function draw(txt,hint,rect,w,h,dir='rtl'){
  const box={className:'',id:'',innerHTML:'',style:{},offsetWidth:220,offsetHeight:70};
  globalThis.document={createElement:()=>box, body:{appendChild(){}},
                       documentElement:{getAttribute:()=>dir}};
  globalThis.window={innerWidth:w,innerHeight:h};
  globalThis.esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  show({getAttribute:k=>k==='data-tipf'?txt:(k==='data-tiph'?hint:null),
        getBoundingClientRect:()=>rect});
  return box;
}
const R = {top:100,bottom:140,left:300,right:600};
const b1 = draw('שם ארוך מאוד של פריט','לחץ לעריכת השם',R,1200,800);
ck('the box holds the whole value and the hint under it',
   b1.innerHTML.includes('שם ארוך מאוד של פריט') && /cell-tip-h">לחץ לעריכת השם</.test(b1.innerHTML),
   b1.innerHTML);
/* an item named <img onerror=...> is a stored XSS the moment the tooltip
   trusts it — the box is built with innerHTML, so the value is escaped */
const b2 = draw('<img src=x onerror=alert(1)>','',R,1200,800);
ck('a value that looks like markup is escaped, not run',
   b2.innerHTML.includes('&lt;img') && !b2.innerHTML.includes('<img'), b2.innerHTML);
ck('no hint line when there is nothing to hint', !b2.innerHTML.includes('cell-tip-h'));
ck('nothing is drawn for an empty value',
   draw('   ','',R,1200,800).innerHTML==='');

// position: below the cell normally, above it when the window ends first
ck('the box sits under the cell', draw('x','',R,1200,800).style.top==='146px');
ck('and flips above it near the bottom of the window',
   draw('x','',{top:700,bottom:740,left:300,right:600},1200,760).style.top==='624px',
   draw('x','',{top:700,bottom:740,left:300,right:600},1200,760).style.top);
/* RTL reads from the cell's right edge, so the box starts there and not at the
   far side of a wide cell */
ck('in RTL it starts at the cell\'s right edge', draw('x','',R,1200,800).style.left==='380px');
ck('in LTR it starts at the left one', draw('x','',R,1200,800,'ltr').style.left==='300px');
ck('and it never leaves the window',
   draw('x','',{top:10,bottom:50,left:-40,right:60},1200,800,'ltr').style.left==='6px');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
