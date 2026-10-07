/* What the ✕ of the import report does.

   The report is the only account of what a migration brought and what it left
   behind, and it is built from a response that is gone the moment it closes:
   re-importing the same file does not reproduce it, it makes a second board. So
   the ✕ asks — and the asking offers the two things people actually wanted
   beside the closing: keep it as a file, or move it into its own window and go
   on working with the board behind it.

   Driven by tests/test_import_report_close.py. */
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
  throw new Error('unbalanced: '+name);
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(x?'  → '+x.slice(0,300):''))); };

/* The three functions under test, with the page around them stubbed: a store to
   keep the report in, a modal that records what it was asked to show, a
   stylesheet with one rule the report uses and one it does not, and the two
   ways a browser hands a file over. */
let shown='', toasted='', closed=0, downloaded=null, opened=null;
const st={};
const sheets=[{cssRules:[
  {selectorText:'.imp-why', cssText:'.imp-why{color:#676879}'},
  {selectorText:':root', cssText:':root{--primary:#0073ea}'},
  {selectorText:'.sb-item', cssText:'.sb-item{padding:9px}'},     // not the report's
]},{get cssRules(){ throw new Error('cross-origin'); }}];          // the CDN sheet
const made=[];
const doc={
  styleSheets:sheets,
  querySelector:()=>null,
  createElement:t=>{ const el={tag:t,style:{},click(){ downloaded={href:el.href,name:el.download}; },
                                remove(){}, setAttribute(){}}; made.push(el); return el; },
  body:{appendChild(){}},
};
const win={open:()=>(opened={written:'',document:{write(h){opened.written=h;},close(){}}})};
const env = new Function('st','document','showModal','closeModals','toast','esc','window','setTimeout','Date',
  [grab('importReportClose'),grab('importReportName'),grab('importReportDoc'),
   grab('importReportSave'),grab('importReportWindow'),
   'return {importReportClose,importReportName,importReportDoc,importReportSave,importReportWindow};'].join('\n'))(
  st, doc, h=>{shown=h;}, ()=>{closed++;}, t=>{toasted=t;}, x=>String(x==null?'':x),
  win, ()=>{}, Date);

// ── the ✕ asks, and names three things ─────────────────────────────────────
st._impReport={title:'לוח ניהול פרויקטים 2025', body:'<div class="imp-why">320 פריטים</div>'};
env.importReportClose();
ck('the ✕ offers saving as a PDF', shown.includes('שמירת הדוח כ-PDF'), shown);
ck('the ✕ offers a new window', shown.includes('פתיחה בחלון חדש'), shown);
ck('the ✕ offers closing', shown.includes('סגירה'), shown);
ck('and says why it is worth asking', shown.includes('אינו ניתן לשחזור'), shown);
ck('nothing closed on its own', closed===0);

// ── with nothing kept, the ✕ is just a ✕ ───────────────────────────────────
st._impReport=null; shown=''; closed=0;
env.importReportClose();
ck('no report kept → it closes rather than asking', closed===1&&shown==='');

// ── the standalone page ────────────────────────────────────────────────────
st._impReport={title:'לוח ניהול פרויקטים 2025', body:'<div class="imp-why">320 פריטים</div>'};
const html=env.importReportDoc();
ck('is a document of its own', /^<!doctype html>/i.test(html)&&html.includes('</html>'));
ck('reads right to left, in Hebrew', html.includes('dir="rtl"')&&html.includes('lang="he"'));
ck('carries the board name and the body', html.includes('לוח ניהול פרויקטים 2025')&&html.includes('320 פריטים'));
ck('lifts the report\'s own rules off the page', html.includes('.imp-why{color:#676879}'));
ck('and the colours they are written in', html.includes('--primary:#0073ea'));
ck('leaves the rest of the app\'s CSS behind', !html.includes('.sb-item'), html);
ck('survives a stylesheet it may not read', html.length>0);
ck('re-links the icons and the Hebrew faces', html.includes('font-awesome')&&html.includes('fonts.googleapis.com'));
ck('is stamped with when it was made', html.includes('דוח ייבוא ·'));
ck('the on-screen copy does not print itself', !html.includes('window.print()'), html.slice(0,120));

// ── saving it, which is printing it ────────────────────────────────────────
/* Printed, not drawn: a PDF of Hebrew is only right if a real text engine lays
   it out. The dialogue takes its suggested filename from the printed document's
   own title — which is why the title of the print copy IS the filename, and why
   this goes through a window of its own rather than a hidden frame, where the
   app's title would be printed instead. */
opened=null;
env.importReportSave();
ck('prints a document of its own', !!opened&&opened.written.includes('<!doctype html>'));
ck('and prints it itself, once the fonts are there',
   opened.written.includes('window.print()')&&opened.written.includes('document.fonts'), opened.written.slice(0,200));
ck('on paper it is A4 with margins', opened.written.includes('@page{size:A4'));
ck('a section is not split across a page break', opened.written.includes('break-inside:avoid'));
ck('the colours survive the printer', opened.written.includes('print-color-adjust:exact'));
ck('closes itself once the dialogue is answered', opened.written.includes('onafterprint'));
ck('the title is the filename it will suggest',
   /<title>דוח-ייבוא-לוח ניהול פרויקטים 2025-\d{4}-\d{2}-\d{2}<\/title>/.test(opened.written),
   (opened.written.match(/<title>[^<]*/)||[''])[0]);
ck('says what to pick, and closes', toasted.includes('שמירה כ-PDF')&&closed===2);
ck('and lets the report go', st._impReport===null);

// a name a filesystem would refuse is not one we hand it
st._impReport={title:'a/b:c*d?e"f<g>h|i', body:''};
ck('a title full of path characters is made safe', !/[\\/:*?"<>|]/.test(env.importReportName()), env.importReportName());

// a blocked popup is not silence
st._impReport={title:'לוח', body:''}; toasted=''; closed=0;
const realOpen=win.open; win.open=()=>null;
env.importReportSave();
ck('a blocked window says so and keeps the report',
   toasted.includes('חלונות קופצים')&&st._impReport!==null&&closed===0, toasted);
win.open=realOpen;

// ── the new window ─────────────────────────────────────────────────────────
st._impReport={title:'לוח', body:'<div class="imp-why">x</div>'};
env.importReportWindow();
ck('writes the same page into a new window', !!opened&&opened.written.includes('<!doctype html>'));
ck('and closes the modal behind it', st._impReport===null);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
