/* The wait an import makes you sit through.

   An import is three waits in a row and only the middle one is the server's —
   0.1s for a 259-item file, measured. The file goes up, the board comes back,
   and then the browser lays out every row of it in one go. That last one is the
   longest, and it is the one that reads as the machine having stopped: a main
   thread building a grid cannot repaint or answer a click while it does it.
   Nothing was on screen for any of it except a toast that had already faded.

   What is asserted here is that the wait is stated while it happens, that the
   cover is painted BEFORE the blocking work rather than in the same frame as
   it, and that no path — success, failure, or a server that refuses the file —
   leaves the page covered. Driven by tests/test_import_busy.py. */
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

/* a DOM small enough to watch: every append, every removal, and every frame the
   page was actually given a chance to paint in */
function stubDom(log){
  const nodes=new Map();
  const mk=()=>({id:'',className:'',_html:'',children:[],
    set innerHTML(v){this._html=v; if(/imp-busy-t/.test(v))nodes.set('imp-busy-t',{textContent:''});},
    get innerHTML(){return this._html;},
    remove(){ nodes.delete(this.id); log.push('remove:'+this.id); }});
  return {
    nodes,
    createElement:()=>mk(),
    getElementById:id=>nodes.get(id)||null,
    body:{appendChild(el){ nodes.set(el.id,el); log.push('append:'+el.id); }},
  };
}

// ── the cover itself ───────────────────────────────────────────────────────
{
  const log=[]; const document=stubDom(log);
  const {importBusy,importBusyDone} = new Function('document',
    grab('importBusy')+'\n'+grab('importBusyDone')+'\nreturn {importBusy,importBusyDone};')(document);

  importBusy('מעלה את הקובץ…');
  ck('the cover goes up', log.join()==='append:imp-busy', log.join());
  ck('and says what is happening',
     document.getElementById('imp-busy-t').textContent==='מעלה את הקובץ…');

  importBusy('בונה את הלוח…');
  ck('a second stage reuses the one cover instead of stacking another',
     log.filter(x=>x==='append:imp-busy').length===1, log.join());
  ck('and re-labels it', document.getElementById('imp-busy-t').textContent==='בונה את הלוח…');

  importBusyDone();
  ck('it comes off', !document.getElementById('imp-busy'));
  importBusyDone();
  ck('and taking it off twice is not an error', true);
}

// ── the frame it is painted in ─────────────────────────────────────────────
ck('the cover waits two frames before the work starts',
   /const paintFirst=\(\)=>new Promise\(r=>requestAnimationFrame\(\(\)=>requestAnimationFrame\(r\)\)\)/.test(src),
   'one frame is not enough — the cover would never be drawn');

const body = grab('importBoardFile');
const at = re => body.search(re);
ck('the cover is up before the file is sent',
   at(/importBusy\('מעלה/) > 0 && at(/importBusy\('מעלה/) < at(/fetch\('\/api\/boards\/import'/));
ck('and the page is given a frame to draw it in, before the wait starts',
   at(/paintFirst\(\)/) > at(/importBusy\('מעלה/) && at(/paintFirst\(\)/) < at(/fetch\('\/api\/boards\/import'/),
   body.slice(at(/importBusy\('מעלה/), at(/fetch/)));
ck('the second stage is announced before the board is drawn, not after',
   at(/importBusy\('בונה/) < at(/openBoard\(/) && at(/importBusy\('בונה/) > at(/await r\.json\(\)/));
ck('and it too is painted before the work that blocks the thread',
   body.slice(at(/importBusy\('בונה/), at(/openBoard\(/)).includes('paintFirst()'));
ck('the stage that holds the screen up says how many items it is drawing',
   /importBusy\('בונה את הלוח — '\+\(b\.items\|\|0\)/.test(body));

// ── nothing leaves the page covered ────────────────────────────────────────
ck('the cover comes off on every path, not only the one that worked',
   /finally\{ importBusyDone\(\);/.test(body), body.slice(-260));
ck('and it is off before the report opens, or the report opens behind it',
   at(/importBusyDone\(\);\n\s*if\(b\.report\)/) > 0 ||
   body.indexOf('importBusyDone()') < at(/if\(b\.report\)/));
ck('the toast that had already faded by the time anything happened is gone',
   !/toast\('מייבא את הקובץ…'\)/.test(src));

// ── it covers the dialog it replaces, and takes the clicks ─────────────────
const css = src.slice(src.indexOf('.imp-busy{'), src.indexOf('.imp-busy{')+400);
const z = /z-index:(\d+)/.exec(css);
ck('it sits above the modal the file was chosen from', z && +z[1] > 300, css.slice(0,90));
ck('it covers the whole page, so a click cannot reach the board behind it',
   /position:fixed;inset:0/.test(css));
ck('and the pointer says the page is busy rather than broken',
   /cursor:progress/.test(css));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
