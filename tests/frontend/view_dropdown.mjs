/* On a narrow screen the view picker is a button opening the app's own popover
   — not a native <select>, whose option list the platform draws and this
   stylesheet cannot reach. Runs the real renderTabs and openViewPicker out of
   index.html. Driven by tests/test_view_dropdown.py. */
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
const VIEWS = /const VIEWS = \[[\s\S]*?\n\];/.exec(src)[0];

let tabsHTML='', popHTML='', formsOpened=0;
global.document={ getElementById:()=>({ set innerHTML(v){ tabsHTML=v; }, get innerHTML(){ return tabsHTML; } }) };
const st={view:'table',board:{views:['table','kanban','calendar','map'],form:null}};

const ctx = new Function('document','st','esc','renderView','openForms','openCellPop','closeCellPops', `
  ${VIEWS}
  const VIEW_META=Object.fromEntries(VIEWS.map(v=>[v.id,v]));
  ${grab('boardViews')}
  ${grab('renderTabs')}
  ${grab('openViewPicker')}
  function setView(v){ st.view=v; renderTabs(); }
  return {renderTabs,openViewPicker,setView};
`)(global.document, st, x=>String(x), ()=>{}, ()=>{formsOpened++;},
   (a,h)=>{popHTML=h;}, ()=>{});

const ev={stopPropagation(){},currentTarget:{}};
// every row's visible label, as the user would read it
const rowLabels = () => [...popHTML.matchAll(/<span class="rm-grow">([^<]*)<\/span>/g)].map(m=>m[1].trim());
const onClicks  = () => [...popHTML.matchAll(/onclick="([^"]*)"/g)].map(m=>m[1]);

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the trigger ──
ctx.renderTabs();
ck('the trigger is a button, not a native select', /<button class="tab-dd"/.test(tabsHTML) && !/<select/.test(tabsHTML));
ck('the trigger shows the current view NAME', /<span class="tab-dd-lbl">טבלה ראשית<\/span>/.test(tabsHTML));
ck('the trigger shows the current view icon', /fa-table-list tab-dd-ic/.test(tabsHTML));
ck('it is labelled for screen readers', /aria-label="בחירת תצוגה"/.test(tabsHTML));
ck('the tab strip is still rendered for wide screens', /<div class="tab /.test(tabsHTML));

// ── the list — the thing that came up blank ──
ctx.openViewPicker(ev);
ck('every row carries readable text', rowLabels().length===4 && rowLabels().every(l=>l.length>0), JSON.stringify(rowLabels()));
ck('the rows are the board\'s views, in order', rowLabels().join(',')==='טבלה ראשית,קנבן,לוח שנה,מפה', rowLabels().join(','));
ck('each row carries its view icon', (popHTML.match(/fa-solid fa-/g)||[]).length>=4);
ck('the current view is marked', /class="rm-item on"/.test(popHTML));
ck('...exactly once', (popHTML.match(/rm-item on/g)||[]).length===1);
ck('...and carries a checkmark', /rm-check/.test(popHTML));
ck('a view the board does not have is not offered', !rowLabels().includes('ניתוח שטח'));
ck('choosing a row closes the menu before switching', onClicks().every(o=>o.startsWith('closeCellPops();')));

// ── switching ──
ctx.setView('kanban');
ck('the trigger follows the switch', /<span class="tab-dd-lbl">קנבן<\/span>/.test(tabsHTML));
ctx.openViewPicker(ev);
const marked=/<button class="rm-item on"[^>]*>[\s\S]*?<span class="rm-grow">([^<]*)<\/span>/.exec(popHTML);
ck('...and so does the mark in the list', !!marked && marked[1].trim()==='קנבן', marked?marked[1]:'nothing marked');

// ── forms is listed but is not a view ──
st.board.form={}; ctx.renderTabs(); ctx.openViewPicker(ev);
ck('a board with a form offers it', rowLabels().includes('טפסים'));
ck('...separated from the views', /rm-sep/.test(popHTML));
ck('...and it never becomes the button label', !/tab-dd-lbl">טפסים/.test(tabsHTML));

// ── a board with only the table ──
st.view='table'; st.board={views:['table'],form:null};
ctx.renderTabs(); ctx.openViewPicker(ev);
ck('a single-view board still gets a working list', rowLabels().join(',')==='טבלה ראשית');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
