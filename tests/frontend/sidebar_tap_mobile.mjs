/* Tapping a board in the sidebar, on a phone: the tap opens the board, nothing
   in the row claims it first, and the drawer closes on the tap rather than when
   the board has finished loading. Runs the real openBoard, syncSidebarDrag and
   closeSidebarMobile out of index.html.
   Driven by tests/test_sidebar_tap_mobile.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab2(method){   /* a method on an object literal, e.g. Folders.initSort */
  const m = new RegExp(`^\\s*${method}\\(\\)\\{`,'m').exec(src);
  if(!m) throw new Error('not found: '+method);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}
function grabM(method){   /* an object-literal method WITH arguments, e.g. Folders.toggle */
  const m = new RegExp(`^\\s*${method}\\(([^)]*)\\)\\{`,'m').exec(src);
  if(!m) throw new Error('not found: '+method);
  let i=src.indexOf('{',m.index+m[0].length-1), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return 'function '+src.slice(m.index,j+1).trim();} }
}
function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}

/* the body's class list, and an element stub for everything openBoard touches */
const body={_c:new Set(['sb-open']),
  classList:{add(c){body._c.add(c)},remove(c){body._c.delete(c)},
             contains(c){return body._c.has(c)},
             toggle(c,on){on?body._c.add(c):body._c.delete(c)}}};
const open = () => body._c.has('sb-open');
const el = () => ({innerHTML:'',textContent:'',value:'',classList:{add(){},remove(){},toggle(){}}});
const document={body,getElementById:()=>el(),querySelectorAll:()=>[]};

let releaseBoard, boardCall;
const st={board:null,boards:[{id:1},{id:2}],openSubs:new Set(),selected:new Set(),
          collapsedGroups:new Set(),filters:{},users:[]};
const noop=()=>{};
const run = new Function('st','document','isMobile','closePops','closeSidebarMobile','api',
  'refreshUsers','renderSidebar','renderBoardHead','renderTabs','refreshToolbar','renderView',
  'Router','localStorage','accessDeniedHTML',
  grab('openBoard')+'; return openBoard;');

function ctx(opts={}){
  return run(st, document, ()=>true, noop,
    grab('closeSidebarMobile') && new Function('document', grab('closeSidebarMobile')+'; return closeSidebarMobile;')(document),
    (url)=> (url.indexOf('/seen')>=0 ? Promise.resolve({}) :
             opts.deny ? Promise.reject(new Error('403'))
                       : new Promise(res=>{releaseBoard=()=>res({id:1,name:'לוח',groups:[],tasks:[]});})),
    ()=>Promise.resolve(), noop, opts.throwOnRender?()=>{throw new Error('render')}:noop,
    noop, noop, opts.throwOnRender?()=>{throw new Error('render')}:noop,
    {set:noop}, {setItem:noop,getItem:()=>null}, ()=>'');
}

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

/* 1 — the drawer closes before the board has come back */
body._c.add('sb-open');
let p = ctx()(1);
ck('the drawer is closed while the board is still loading', !open());
releaseBoard && releaseBoard();
await p.catch(()=>{});
ck('...and stays closed once it arrives', !open());

/* 2 — a board the server refuses still closes the drawer */
body._c.add('sb-open');
await ctx({deny:true})(2).catch(()=>{});
ck('a board that answers 403 closes the drawer too', !open());

/* 3 — a render that throws cannot leave it open */
body._c.add('sb-open');
p = ctx({throwOnRender:true})(1);
ck('a throw below the fetch cannot reopen it', !open());
releaseBoard && releaseBoard();
await p.catch(()=>{});
ck('...still closed after the throw', !open());

/* 4 — the close itself does not depend on the window still being narrow */
body._c.add('sb-open');
new Function('document', grab('closeSidebarMobile')+'; return closeSidebarMobile;')(document)();
ck('closeSidebarMobile does not ask whether the screen is narrow', !open());
ck('...and the source has no isMobile() guard left on it',
   !/if\s*\(\s*isMobile\(\)\s*\)/.test(grab('closeSidebarMobile')),
   'a guard here leaves the drawer armed behind a window that stopped being narrow');

/* ── the tap itself: nothing in the row may claim it on a touch screen ───── */

/* 5 — drag-to-reorder is off while the pointer is coarse */
{
  const made=[];
  const fake={get:el=>el._s||null};
  const el=(id)=>({id,_s:{opts:{},option(k,v){this.opts[k]=v}}});
  const lists=[el('#sb-folders'), el('#sb-root'), el('#f3')];
  lists.forEach(l=>{ l._s.opts={}; });
  const doc={querySelectorAll:()=>lists};
  /* the selector constant is part of what is being tested: it has to name the
     containers initSort actually builds Sortables on */
  const SEL = /const SB_DRAG_SEL='([^']+)'/.exec(src)[1];
  const sync = (coarse) => new Function('window','Sortable','document','isTouch','SB_DRAG_SEL',
      grab('syncSidebarDrag')+'; return syncSidebarDrag;')(
      {Sortable:fake}, fake, doc, ()=>coarse, SEL)();

  sync(true);
  ck('a coarse pointer disables the sidebar sortables',
     lists.every(l=>l._s.opts.disabled===true),
     JSON.stringify(lists.map(l=>l._s.opts)));
  sync(false);
  ck('...and a mouse gets dragging back',
     lists.every(l=>l._s.opts.disabled===false));
}

{
  const SEL = /const SB_DRAG_SEL='([^']+)'/.exec(src)[1];
  const built = grab2('initSort');
  const bare = p => p.trim().replace('#board-list ','').replace(/^#/,'');
  ck('the selector names the containers initSort builds Sortables on',
     SEL.split(',').every(part=>built.includes(bare(part))),
     SEL+'  vs  '+built.replace(/\s+/g,' ').slice(0,160));
}

/* 6 — a freshly rendered sidebar starts in the right state, not the default */
ck('initSort settles the drag state on the Sortables it just built',
   grab2('initSort').includes('syncSidebarDrag()'),
   'a re-render would arm dragging again until the pointer changed');

/* 7 — and a pointer that changes under a live page flips it */
ck('a change of pointer re-syncs the sidebar, not only the item rows',
   /matchMedia\(TOUCH_Q\)\.addEventListener\('change',\(\)=>\{[^}]*syncSidebarDrag\(\)/.test(src.replace(/\n/g,'')));

/* 8 — the row's ⋮ is visible wherever :hover never comes */
ck('the row menu button is shown on a coarse pointer',
   /@media \(pointer:coarse\)\{\s*\.sb-item \.sb-more,\.sb-folder-head \.sb-more\{opacity:1\}/.test(src),
   'an invisible button at the end of the row still takes the tap');

/* ── folding a folder open and shut, by finger ───────────────────────────── */
{
  const store={};
  const st2={};
  const toggle=new Function('st','localStorage','renderSidebar',
    grabM('toggle')+'; return toggle;')(
    st2, {setItem:(k,v)=>{store[k]=v;}, getItem:k=>store[k]||null}, ()=>{});

  toggle(4);
  ck('a tap on a folder head folds it shut', st2._foldersCollapsed.has(4));
  ck('...and the state outlives the re-render it triggers',
     JSON.parse(store['cc_folders_collapsed']||'[]').includes(4), store['cc_folders_collapsed']);
  toggle(4);
  ck('a second tap opens it again', !st2._foldersCollapsed.has(4));
  ck('...and that is remembered too',
     !JSON.parse(store['cc_folders_collapsed']||'[]').includes(4), store['cc_folders_collapsed']);
  toggle(4); toggle(9);
  ck('folders are remembered one by one, not all or nothing',
     st2._foldersCollapsed.has(4) && st2._foldersCollapsed.has(9));
}
/* The folder head is BOTH the tap target that folds it and the handle that drags
   it. That is only safe because the sidebar's sortables are disabled wherever
   the pointer is coarse (tested above) — so the selector that disables them has
   to cover the folder list, or a finger on a folder head is a drag attempt and
   the fold never happens. */
{
  const SEL = /const SB_DRAG_SEL='([^']+)'/.exec(src)[1];
  ck('the drag-disabling selector covers the folder list',
     SEL.includes('#sb-folders'), SEL);
  ck('...and the folder sortable is indeed handled by the head that takes the tap',
     /sortableOn\(fwrap,\{[^}]*handle:'\.sb-folder-head'/.test(src));
}
/* ── a board inside a folder is the same tap as one at the root ──────────── */
ck('a board row carries its open-the-board tap wherever it is rendered',
   (src.match(/class="sb-item \$\{st\.board&&st\.board\.id===b\.id\?'active':''\}" data-bid="\$\{b\.id\}" onclick="openBoard\(\$\{b\.id\}\)"/g)||[]).length===1,
   'boardItem is one template used for folders and the root alike');

/* ── switching workspace must not look like you are finished ─────────────── */
{
  body._c.add('sb-open');
  const st2={env:null};
  const closed=[];
  const select=new Function('st','closeSidebarMobile','renderSidebar',
    grabM('select')+'; return select;')(
    st2, ()=>closed.push(1), ()=>{});
  // `this` is the Env object: items to choose from, and _set closes the dropdown
  const envObj={items:[{id:1,name:'סביבה ראשית'},{id:2,name:'בינוי'}],_setCalls:[],
                _set(v){ this._setCalls.push(v); }};
  select.call(envObj, 2);
  ck('choosing a workspace leaves the drawer open, so a board can still be picked',
     open() && closed.length===0, 'closes='+closed.length);
  ck('...the workspace itself did change', st2.env && st2.env.id===2, JSON.stringify(st2.env));
  ck('...and the dropdown over it closed', envObj._setCalls[0]===false, JSON.stringify(envObj._setCalls));
  ck('the source no longer closes the drawer when a workspace is chosen',
     !/closeSidebarMobile\(\)/.test(grabM('select')), grabM('select'));
}
/* and the drawer still closes on the thing that IS a choice: the board */
{
  body._c.add('sb-open');
  const p2 = ctx()(1);
  ck('tapping a board after the switch closes the drawer', !open());
  releaseBoard && releaseBoard();
  await p2.catch(()=>{});
}

/* ── opening a new browser tab from the sidebar ──────────────────────────── */
{
  const foot=/<div class="sb-foot">[\s\S]*?<\/div>\s*<\/aside>/.exec(src);
  const help=foot?foot[0]:'';
  // the prose around it may well say the words "window.open"; what must not
  // exist is a row that CALLS it
  ck('the link out of the app is an anchor, not a div calling window.open',
     /<a class="sb-item"[^>]*href="https:\/\//.test(help) && !/onclick="window\.open/.test(help),
     help.slice(0,200));
  ck('...it opens in a new tab, safely',
     /target="_blank"/.test(help) && /rel="noopener noreferrer"/.test(help));
  ck('...and it closes the drawer it was tapped in',
     /onclick="closeSidebarMobile\(\)"/.test(help));
  ck('an anchor in that row is not left looking like a link',
     /\.sb-item\{[^}]*text-decoration:none/.test(src),
     'no global anchor reset exists here, so .sb-item must say it');
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
