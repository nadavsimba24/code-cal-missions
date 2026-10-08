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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
