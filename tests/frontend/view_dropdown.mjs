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

let tabsHTML='', popHTML='';
global.document={ getElementById:()=>({ set innerHTML(v){ tabsHTML=v; }, get innerHTML(){ return tabsHTML; } }) };
const st={view:'table',board:{views:['table','kanban','calendar','map']}};

/* VIEWS_WIP is injected rather than read from the file. This harness is about
   how the picker DRAWS a list, so it wants the board's four views in it; the
   gate that hides unfinished ones is a separate question, asked at the bottom
   with a set of its own. */
/* `Views` and `filtersActive`: renderTabs now also draws the board's saved
   cuts after its own views, and the "save this cut" button when something is
   filtered. These cases are about the base views and the picker, so the
   strip is given no saved cuts and nothing filtered — which is the state the
   assertions below were written against. */
const build = (wip, state) => new Function('document','st','esc','renderView','openCellPop','closeCellPops','VIEWS_WIP','Views','filtersActive','FormEditor', `
  ${VIEWS}
  const VIEW_META=Object.fromEntries(VIEWS.map(v=>[v.id,v]));
  ${grab('boardViewsRaw')}
  ${grab('boardViews')}
  ${grab('renderTabs')}
  ${grab('openViewPicker')}
  function setView(v){ st.view=v; renderTabs(); }
  return {renderTabs,openViewPicker,setView};
`)(global.document, state, x=>String(x), ()=>{},
   (a,h)=>{popHTML=h;}, ()=>{}, wip,
   {items:[], tabsHTML:()=>'', openView:()=>null, dirty:()=>false, active:null},
   ()=>false, {isOpen:()=>false});
const ctx = build(new Set(), st);

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

/* ── a form is a tab, not a row in this picker ──
   Forms used to be listed here, below a separator, because a form was a panel
   over the board rather than a view of it. It is a view now: it lives on the
   strip beside the saved cuts, with a name somebody gave it. This picker
   answers "how am I looking at this board", which a form does not change. */
ctx.renderTabs(); ctx.openViewPicker(ev);
ck('a form is not offered as a way of drawing the board', !rowLabels().includes('טפסים'));
ck('...and the picker needs no separator any more', !/rm-sep/.test(popHTML));

// ── a board with only the table ──
st.view='table'; st.board={views:['table']};
ctx.renderTabs(); ctx.openViewPicker(ev);
ck('a single-view board still gets a working list', rowLabels().join(',')==='טבלה ראשית');

// ── and the gate that hides the views still being built ──
// Same picker, same board, a set that holds everything but the table: what the
// board has turned on is unchanged, what it OFFERS is one view.
const st2={view:'kanban',board:{views:['table','kanban','calendar','map']}};
const wip=build(new Set(['kanban','calendar','map','dashboard','gis','links']), st2);
wip.renderTabs(); wip.openViewPicker(ev);
ck('a view still in development is not offered', rowLabels().join(',')==='טבלה ראשית',
   rowLabels().join(','));
ck('...and the board it was turned on for keeps it',
   st2.board.views.join(',')==='table,kanban,calendar,map', st2.board.views.join(','));
ck('...and somebody left on a hidden view lands on the table', st2.view==='table', st2.view);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
