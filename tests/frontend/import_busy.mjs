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
    /* Every element the cover builds is registered, by reading the ids out of
       the markup it wrote. The stub used to know about imp-busy-t and nothing
       else, so the quieter second line — added later, looked up by id like the
       first — resolved to null here and the harness could not see it at all. */
    set innerHTML(v){this._html=v;
      for(const m of v.matchAll(/id="([^"]+)"/g)) nodes.set(m[1],{textContent:'',hidden:false});},
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
    grab('busyCover')+'\n'+grab('busyCoverDone')
    +'\nreturn {importBusy:busyCover,importBusyDone:busyCoverDone};')(document);

  importBusy('מעלה את הקובץ…');
  ck('the cover goes up', log.join()==='append:imp-busy', log.join());
  ck('and says what is happening',
     document.getElementById('imp-busy-t').textContent==='מעלה את הקובץ…');

  importBusy('בונה את הלוח…');
  ck('a second stage reuses the one cover instead of stacking another',
     log.filter(x=>x==='append:imp-busy').length===1, log.join());
  ck('and re-labels it', document.getElementById('imp-busy-t').textContent==='בונה את הלוח…');

  /* The second line is for the wait nobody can measure: once the file is up,
     the server is reading it and writing rows and there is no number to show,
     so the cover says what is happening and how long it can take instead of
     animating a bar towards a finish it cannot see. */
  // read through a miss rather than off it: a cover built without the second
  // line should fail this check, not crash the harness two checks early
  const sub = () => document.getElementById('imp-busy-s') || {textContent:null, hidden:null};
  importBusy('הקובץ הועלה — השרת בונה את הלוח…', 'קורא את הקובץ וכותב את הפריטים.');
  ck('a stage with no number to show says what is happening underneath',
     sub().textContent==='קורא את הקובץ וכותב את הפריטים.', String(sub().textContent));
  ck('...and the headline is still the headline',
     document.getElementById('imp-busy-t').textContent==='הקובץ הועלה — השרת בונה את הלוח…');
  importBusy('מצייר את הלוח — 259 פריטים…');
  ck('a stage with nothing to add leaves no stale second line behind',
     sub().textContent==='' && sub().hidden===true,
     `${String(sub().textContent)} / hidden=${String(sub().hidden)}`);

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

/* The ORDER of the three waits is the behaviour. How the file is sent is not.
   These checks used to anchor on fetch('/api/boards/import') and on
   await r.json(), and when the request moved to XMLHttpRequest — for the one
   thing fetch cannot report, the moment the last byte left — five of them went
   red without a single sentence on screen having changed. A harness that fails
   when the transport changes is pinning the transport.

   So the milestones are named by what they mean, and any transport that passes
   them in this order is fine: the file goes to the import endpoint, the board
   comes back in hand, the browser lays it out. */
const SENT   = /['"]\/api\/boards\/import['"]/;   // the file is on its way
const ANSWER = /const b\s*=\s*await/;             // ...and the built board is in hand
const DRAWN  = /openBoard\(/;                     // ...and the browser lays it out
/* Likewise the wording: the stage that holds the screen up has been "בונה" and
   is now "מצייר", because the server's build and the browser's draw are two
   different waits and calling both of them "building" was the confusion this
   whole cover exists to end. What has to be true is that it names a wait and
   says how big it is — not which verb this month's wording uses. */
const DRAW_STAGE = /importBusy\('[^']*— '\+\(b\.items\|\|0\)/;

ck('the cover is up before the file is sent',
   at(/importBusy\('מעלה/) > 0 && at(/importBusy\('מעלה/) < at(SENT));
ck('and the page is given a frame to draw it in, before the wait starts',
   at(/paintFirst\(\)/) > at(/importBusy\('מעלה/) && at(/paintFirst\(\)/) < at(SENT),
   body.slice(at(/importBusy\('מעלה/), at(SENT)));
ck('the last stage is announced before the board is drawn, not after',
   at(DRAW_STAGE) > 0 && at(DRAW_STAGE) < at(DRAWN) && at(DRAW_STAGE) > at(ANSWER),
   `stage ${at(DRAW_STAGE)}, answer ${at(ANSWER)}, draw ${at(DRAWN)}`);
ck('and it too is painted before the work that blocks the thread',
   body.slice(at(DRAW_STAGE), at(DRAWN)).includes('paintFirst()'));
ck('the stage that holds the screen up says how many items it is drawing',
   DRAW_STAGE.test(body) && /פריטים/.test(body.slice(at(DRAW_STAGE), at(DRAW_STAGE)+90)),
   body.slice(at(DRAW_STAGE), at(DRAW_STAGE)+90));

// ── while the bytes are moving, there IS a number, and it is shown ─────────
/* The cover said "מעלה את הקובץ…" for the whole request, and most of the
   request is not the upload: on a 12MB gzip of a 21,187-item board it is 0.04s
   to decompress, 1.6s to parse and some thirteen seconds writing rows, all of
   it under a sentence promising the file was still on its way. It was reported
   as "the upload is slow" — the sentence the screen had taught. So the upload
   is counted while it can be counted, and the moment it cannot, it stops being
   what the cover talks about. */
const upAt = body.indexOf('upload.onprogress');
const upEnd = body.indexOf('upload.on', upAt + 10);
const upProgress = upAt < 0 ? '' : body.slice(upAt, upEnd > 0 ? upEnd : upAt + 400);
ck('the upload is counted while the bytes are moving',
   /e\.loaded\s*\/\s*e\.total/.test(upProgress) && /importBusy\(/.test(upProgress)
   && /%/.test(upProgress),
   upProgress ? upProgress.slice(0,180) : 'no upload progress handler at all');
ck('...off a total the browser actually has, rather than a guess',
   /lengthComputable/.test(upProgress), upProgress.slice(0,180));
ck('...and it never reaches 100 before the server has answered',
   /Math\.min\(99/.test(upProgress),
   'a counter that hits 100% and then sits there is the freeze it was meant to explain');

const upDone = /upload\.on(?:load|loadend)\s*=\s*\(\)\s*=>\s*importBusy\(\s*'([^']*)'\s*(?:,\s*'([^']*)')?/
  .exec(body);
ck('and it stops naming the upload once the last byte is gone',
   !!upDone && !/מעלה את הקובץ/.test(upDone[1]),
   upDone ? upDone[1] : 'nothing re-labels the cover when the upload ends');
ck('...naming instead the wait that has no number — the server reading the file',
   !!upDone && !!upDone[2] && upDone[2].length > 10,
   upDone ? String(upDone[2]) : '');

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

// ── every other upload gets the same treatment ─────────────────────────────
// Picking a file and watching nothing happen is the same wait wherever it is
// done, so the cover is not the importer's private property.
ck('the import keeps its own names for the cover',
   /const importBusy=busyCover, importBusyDone=busyCoverDone;/.test(src));
for(const [what, fn, label] of [
      ['a file column', grab('uploadFileCell'), /busyCover\('מעלה את '/],
      ['a workspace icon', src.slice(src.indexOf('uploadLook(){'), src.indexOf('uploadLook(){')+1200), /busyCover\('מעלה את התמונה/],
      ['a profile photo', src.slice(src.indexOf('async uploadAvatar(userId,file){'), src.indexOf('async uploadAvatar(userId,file){')+2200), /busyCover\('מעלה את התמונה/]]){
  ck(`${what} says it is uploading, before it uploads`,
     label.test(fn) && fn.search(label) < (fn.search(/fetch\(|api\(/)>=0?fn.search(/fetch\(|api\(/):1e9), fn.slice(0,200));
  ck(`...gives the page a frame to draw that in`, /paintFirst\(\)/.test(fn));
  ck(`...and never leaves the page covered`, /finally\{ busyCoverDone\(\);/.test(fn), fn.slice(-200));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
