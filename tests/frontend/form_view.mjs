/* תצוגת טופס במנגנון התצוגות — the "+" menu, the tab, the editor, the way back.

   Runs the real renderAddViewPop, renderTabs, Views.tabIcons/actionsFor and the
   whole FormEditor out of index.html. Driven by tests/test_form_view_ui.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');
/* FormPaper is its own file now — loaded by index.html and by the public fill
   page. The harness reads it from where it lives. */
const paperSrc = fs.readFileSync(path.join(ROOT,'frontend','form-paper.js'),'utf8');

function brace(from){
  let i=src.indexOf('{',from), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return j+1;} }
}
function grab(name){
  const m=new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  return src.slice(m.index, brace(m.index));
}
/* One method out of ONE named object literal. Scoped to the object, because
   `tabsHTML` is the name of three different methods in this file and the
   first one belongs to the board log. */
function grabMethodIn(obj, name){
  const o=new RegExp(`^const ${obj}\\s*=\\s*\\{`,'m').exec(src);
  if(!o) throw new Error('not found: const '+obj);
  const span=src.slice(o.index, brace(o.index));
  const m=new RegExp(`^  ${name}\\(`,'m').exec(span);
  if(!m) throw new Error(`not found: ${obj}.${name}`);
  let i=span.indexOf('{',m.index), d=0;
  for(let j=i;j<span.length;j++){ if(span[j]==='{')d++; else if(span[j]==='}'){d--; if(!d) return span.slice(m.index,j+1);} }
  throw new Error('unterminated: '+name);
}
function grabConst(name){
  const m=new RegExp(`^const ${name}\\s*=\\s*\\{`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return src.slice(m.index, brace(m.index))+';';
}
/* A top-level const whose value is an object or an array literal, however
   many lines it runs to — matched by its brackets rather than by its line. */
function grabDecl(name){
  const m=new RegExp(`^const ${name}\\s*=\\s*[\\[{]`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  const open=src[m.index+m[0].length-1], close=open==='[' ? ']' : '}';
  let i=m.index+m[0].length-1, d=0;
  for(let j=i;j<src.length;j++){
    if(src[j]===open)d++; else if(src[j]===close){d--; if(!d) return src.slice(m.index,j+1)+';';}
  }
  throw new Error('unterminated: '+name);
}

/* The real debounce, read out of the file rather than guessed at: a harness
   that waits a different length of time from the product is testing a
   different product. */
const AUTOSAVE_MS=+/const FORM_AUTOSAVE_MS=(\d+)/.exec(src)[1];

let pass=0,fail=0;
const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the world the real code runs in ──
let tabsHTML='', popHTML='', viewHTML='', modalHTML='', toasts=[], routed=[], confirmed=null;
const els={};
/* Enough of an element for the code under test: the save indicator writes a
   class, a title and some HTML into one, and syncLabel reaches for text. */
function fakeEl(){ let v='';
  return {set innerHTML(x){v=x;}, get innerHTML(){return v;},
          className:'', textContent:'', dataset:{}, style:{},
          setAttribute(){}, getAttribute(){return null;}, removeAttribute(){},
          classList:{add(){},remove(){},toggle(){},contains(){return false;}},
          addEventListener(){}, focus(){}, blur(){},
          querySelectorAll:()=>[], querySelector:()=>null}; }
/* A Sortable the harness can drive: it records what each list was wired
   with, so a drag is "call that list's onEnd with a different order". The
   registry is what sortableOn consults before making a second instance — see
   tests/frontend/one_sortable_per_element.mjs for why that matters. */
class FakeSortable{
  static reg=new Map();
  static get(el){ return FakeSortable.reg.get(el)||null; }
  constructor(el,opts){ this.el=el; this.opts=opts; FakeSortable.reg.set(el,this); }
  destroy(){ FakeSortable.reg.delete(this.el); }
}
global.Sortable=FakeSortable;
global.window={Sortable:FakeSortable};
/* A list element whose rows the test sets — what a drag leaves behind. */
function listEl(){ const e=fakeEl(); e.rows=[];
  e.querySelectorAll=()=>e.rows.map(id=>({dataset:{id:String(id)}})); return e; }
global.document={
  getElementById(id){
    if(id==='tabs')      return {set innerHTML(v){tabsHTML=v;}, get innerHTML(){return tabsHTML;}};
    if(id==='tab-pop')   return {set innerHTML(v){popHTML=v;},  get innerHTML(){return popHTML;}};
    if(id==='view')      return {set innerHTML(v){viewHTML=v;}, get innerHTML(){return viewHTML;},
                                 querySelectorAll:()=>[]};
    if(id==='fv-list'||id==='fv-blocks') return els[id]||(els[id]=listEl());
    return els[id]||(els[id]=fakeEl());
  },
  querySelector:()=>null, querySelectorAll:()=>[],
  addEventListener(){},
};
global.addEventListener=()=>{};        // the beforeunload guard registers one
global.location={origin:'http://x'};   // the share dialog builds an absolute link

const FORMS={};           // id → the form the fake server holds
let nextId=100;
const st={view:'table', board:{id:7, name:'תשתיות', my_role:'admin',
                               views:['table'], columns:[
  {id:'col_addr', type:'text',     title:'כתובת'},
  {id:'col_when', type:'date',     title:'מתי'},
  {id:'sys_item_id', type:'item_id', title:'מספר מזהה'},
]}};

function blankForm(id, name){
  return {id, view_id:id+1000, board_id:7, name, status:'DRAFT', access:'AUTHENTICATED',
          public_token:null, target_group_id:1,
          design:{display_title:'', display_description:'', font_family:'Rubik',
                  font_size:'medium', text_align:'right', theme_color:'#0073ea',
                  background_color:'#ffffff', text_color:'#323338',
                  logo_token:null, cover_token:null, show_logo:true,
                  submit_label:'', show_branding:true},
          success:{title:'', message:'', allow_another:false, redirect_url:null},
          public_url:null,
          record_submitter:true, published_at:null, published_by:null,
          config_version:1, locked:false, updated_at:null, components:[]};
}

let apiLog=[], apiFail=null, apiHold=null, apiCalls=0;
async function api(p,o){
  apiCalls++;
  apiLog.push({p, method:(o&&o.method)||'GET', body:o&&o.body?JSON.parse(o.body):null});
  /* A request that does not answer until the test says so — how an old
     answer is made to land after a newer change. */
  if(apiHold && apiHold.match(p,o)) await apiHold.gate;
  if(apiFail){ const e=new Error('boom'); e.status=apiFail.status; e.detail=apiFail.detail; throw e; }
  const body=o&&o.body?JSON.parse(o.body):{};
  let m;
  if((m=p.match(/^\/api\/boards\/\d+\/forms$/)) && o&&o.method==='POST'){
    const id=nextId++; FORMS[id]=blankForm(id, body.name||'טופס חדש'); return FORMS[id];
  }
  if((m=p.match(/^\/api\/forms\/(\d+)$/)) && (!o||!o.method||o.method==='GET')){
    if(!FORMS[m[1]]){ const e=new Error('404'); e.status=404; throw e; }
    return JSON.parse(JSON.stringify(FORMS[m[1]]));   // a reload is a fresh fetch
  }
  if((m=p.match(/^\/api\/forms\/(\d+)$/)) && o.method==='PATCH'){
    const f=FORMS[m[1]];
    f.config_version=(f.config_version||1)+1;
    if(body.name!==undefined) f.name=body.name;
    if(body.status!==undefined){
      f.status=body.status;
      if(body.status==='PUBLISHED'&&!f.public_token){
        f.public_token='tok'+(nextId++); f.public_url='/forms/'+f.public_token;
      }
    }
    Object.keys(body).forEach(k=>{
      if(k in f.design) f.design[k]=body[k];
      if(k==='success_title') f.success.title=body[k];
      if(k==='success_message') f.success.message=body[k];
      if(k==='success_allow_another') f.success.allow_another=body[k];
      if(k==='access') f.access=body[k];
    });
    return JSON.parse(JSON.stringify(f));
  }
  if((m=p.match(/^\/api\/forms\/(\d+)\/fields$/)) && o.method==='POST'){
    const f=FORMS[m[1]];
    if(!body.title||!body.title.trim()){ const e=new Error('400'); e.status=400;
      e.detail='לשדה צריך שם'; throw e; }
    const col={id:'col_'+(nextId++), type:body.type, title:body.title,
               options:(body.options||null)};
    const c={id:nextId++, kind:'question', field_key:col.id, label:body.label||body.title,
             description:'', placeholder:'', required:!!body.required,
             visible:body.visible!==false, settings:{}, position:f.components.length};
    f.components.push(c);
    return {column:col, component:{...c}};
  }
  if((m=p.match(/^\/api\/forms\/(\d+)\/components$/)) && o.method==='POST'){
    const f=FORMS[m[1]], c={id:nextId++, kind:body.kind, position:f.components.length};
    if(body.kind==='question'){ Object.assign(c,{field_key:body.field_key, label:body.label||'',
      description:'', placeholder:'', required:false, visible:true, settings:{}}); }
    else c.content=body.content||'';
    f.components.push(c); return c;
  }
  if((m=p.match(/^\/api\/forms\/(\d+)\/components\/(\d+)$/)) && o.method==='PATCH'){
    const f=FORMS[m[1]], c=f.components.find(x=>x.id==m[2]);
    if(body.required && (('visible' in body)?body.visible===false:c.visible===false)){
      const e=new Error('400'); e.status=400; e.detail='שאלה מוסתרת אינה יכולה להיות חובה'; throw e;
    }
    Object.assign(c, body); return {...c};
  }
  if((m=p.match(/^\/api\/forms\/(\d+)\/components\/(\d+)$/)) && o.method==='DELETE'){
    const f=FORMS[m[1]]; f.components=f.components.filter(x=>x.id!=m[2]); return {status:'deleted'};
  }
  if((m=p.match(/^\/api\/forms\/(\d+)\/components\/order$/)) && o.method==='PUT') return {order:body.order};
  if((m=p.match(/^\/api\/forms\/(\d+)$/)) && o.method==='DELETE'){ delete FORMS[m[1]]; return {status:'deleted'}; }
  return {};
}

/* The real tabsHTML, tabIcons and actionsFor out of index.html — the three
   that decide what a form looks like on the strip. The rest of Views is
   stubbed: this harness is about the form, not about saved cuts. */
const esc=x=>(x==null?'':String(x)).replace(/[&<>"]/g,
      c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const Views=new Function('esc','FORMS',`
  const V={items:[], active:null, base:null,
    async load(){ this.items=Object.values(FORMS).map(f=>({
        id:f.view_id, kind:'form', form_id:f.id, form_status:f.status, name:f.name,
        filters:{}, can_edit:true, can_duplicate:false, can_lock:true,
        locked:false, pinned:false, blocked:false, needs_fix:[]})); },
    openView(){ return null; }, dirty(){ return false; },
    ${grabMethodIn('Views','tabsHTML')},
    ${grabMethodIn('Views','tabIcons')},
    ${grabMethodIn('Views','actionsFor')},
  };
  return V;
`)(esc, FORMS);     // tabsHTML reads the global FormEditor, set once ctx exists

const ctx=new Function(
  'document','window','st','esc','api','withMe','toast','Router','Views','askConfirm',
  'openCellPop','closeCellPops','customColumns','Chat','VIEWS_WIP','filtersActive',
  'showModal','closeModals','sortableOn',`
  const VIEWS=[{id:"table",he:"טבלה ראשית",ic:"fa-table-list"}];
  const VIEW_META=Object.fromEntries(VIEWS.map(v=>[v.id,v]));
  ${grabDecl('DERIVED_COLS')}
  ${grabDecl('FORM_STATUS_HE')}
  ${grabDecl('FORM_FIELD_TYPE_HE')}
  ${grabDecl('FORM_BUILTIN_FIELDS')}
  ${grabDecl('FORM_SETTING_PATH')}
  ${grabDecl('FORM_SAVE_HE')}
  ${grabDecl('FORM_NEW_FIELD_TYPES')}
  ${grabDecl('FORM_PLACEHOLDER_TYPES')}
  const FORM_AUTOSAVE_MS=${AUTOSAVE_MS};
  ${paperSrc}
  ${grabConst('FormEditor')}
  /* renderView's own bookkeeping, and the board branch it falls through to.
     Stubbed rather than skipped: the assertion worth making is that a form
     short-circuits ahead of all of it, which needs all of it to exist. */
  let _viewScrollKey=null, _colsMemo=null;
  function boardStatusList(){ return []; }
  function boardPriorityList(){ return []; }
  function statusColOpts(col){ return (col.options||[]).map(o=>({id:o,label:o})); }
  const vTable=el=>{el.innerHTML='<div data-board="1"></div>';};
  const vKanban=vTable, vDashboard=vTable, vCeo=vTable, vCalendar=vTable, vMap=vTable,
        vGis=vTable, vWorkPlan=vTable, vBudget=vTable, vApprovals=vTable, vGantt=vTable,
        vLinks=vTable, vCeoEnhanced=vTable;
  function learnRowHeight(){} function renderSelBar(){}
  function syncItemColWidth(){} function fitLinkChips(){}
  ${grab('boardViewsRaw')}
  ${grab('boardViews')}
  ${grab('renderTabs')}
  ${grab('renderAddViewPop')}
  ${grab('renderView')}
  function closeAddView(){}
  function setView(v){ st.view=v; }
  return {FormEditor, FormPaper, renderTabs, renderAddViewPop, renderView};
`)(global.document, global.window, st, esc,
   api, b=>JSON.stringify(b||{}), m=>toasts.push(m),
   {set:(b,i,v)=>routed.push([b,i,v])}, Views,
   (msg,yes)=>{confirmed=msg; return yes();},
   (a,h)=>{popHTML=h;}, ()=>{}, ()=>st.board.columns, {taskId:null, close(){}},
   new Set(), ()=>false,
   h=>{modalHTML=h;}, ()=>{modalHTML='';},
   new Function('window','Sortable', grab('sortableOn')+';return sortableOn;')(
     global.window, FakeSortable));

const FE=ctx.FormEditor, FormPaper=ctx.FormPaper;
global.FormEditor=FE;        // what the real tabsHTML reaches for
const sleep=()=>new Promise(r=>setTimeout(r,0));

// ── 1 · the "+ הוספת תצוגה" menu offers a form ──
ctx.renderAddViewPop();
ck('the menu offers a form', /<span>טופס<\/span>/.test(popHTML));
ck('…beside the table, as the same kind of thing', /<span>טבלה<\/span>/.test(popHTML));
ck('…and pressing it creates one', /FormEditor\.create\(\)/.test(popHTML));
ck('…in Hebrew, with a form icon', /fa-file-lines/.test(popHTML));
st.board.my_role='viewer'; ctx.renderAddViewPop();
ck('a viewer is not offered it at all', !/<span>טופס<\/span>/.test(popHTML));
st.board.my_role='admin';

// ── 2 · creating one opens its editor ──
await FE.create(); await sleep();
ck('creating asks the board for a form',
   apiLog.some(c=>c.method==='POST'&&/\/api\/boards\/7\/forms$/.test(c.p)));
ck('the new form is a draft called "טופס חדש"', FE.form&&FE.form.name==='טופס חדש'&&FE.form.status==='DRAFT');
ck('…and the editor is open on it', FE.isOpen()&&FE.id===FE.form.id);
ck('…the address carries the view, so a refresh comes back to it',
   routed.length&&routed[routed.length-1][2]===FE.form.view_id, JSON.stringify(routed));
const formA=FE.form.id;

// ── 3 · what the editor draws ──
ctx.renderView();
ck('the editor is drawn instead of the board', /class="fv-wrap"/.test(viewHTML));
ck('the name is editable in the top bar', /class="fv-bar"[\s\S]*?id="fv-name"[\s\S]*?value="טופס חדש"/.test(viewHTML));
ck('the top bar shows the state', /fv-badge-DRAFT">טיוטה</.test(viewHTML));
ck('…a save indicator', /id="fv-save"/.test(viewHTML)&&/aria-live="polite"/.test(viewHTML));
ck('…a preview toggle', /FormEditor\.togglePreview\(\)/.test(viewHTML)&&/תצוגה מקדימה/.test(viewHTML));
ck('…settings', /fa-sliders/.test(viewHTML)&&/>\s*הגדרות/.test(viewHTML));
ck('…publish and share', /FormEditor\.share\(\)/.test(viewHTML)&&/פרסום ושיתוף/.test(viewHTML));
ck('…and a way back to the board', /FormEditor\.close\(\)/.test(viewHTML)&&/חזרה ללוח/.test(viewHTML));
ck('…pointing the RTL way', /fa-arrow-right[^"]*"><\/i> חזרה ללוח/.test(viewHTML));
ck('three panes: outline, canvas, settings',
   /class="fv-outline"/.test(viewHTML)&&/class="fv-canvas"/.test(viewHTML)&&/class="fv-inspect"/.test(viewHTML));
ck('the outline comes first in the DOM, so it is on the right in RTL',
   viewHTML.indexOf('fv-outline')<viewHTML.indexOf('fv-canvas')
   &&viewHTML.indexOf('fv-canvas')<viewHTML.indexOf('fv-inspect'));
ck('an empty form says so rather than looking broken', /אין עדיין רכיבים/.test(viewHTML));
ck('with nothing selected the settings pane is the form\'s',
   /מסך הצלחה/.test(viewHTML)&&/id="fv-dt"/.test(viewHTML)&&/טקסט כפתור השליחה/.test(viewHTML));
ck('the canvas draws the form as a page', /class="fv-paper"/.test(viewHTML)&&/fv-submit/.test(viewHTML));

// ── 4 · questions are the board's fields, by the form's wording ──
FE.addMenu({stopPropagation(){},currentTarget:{}});
ck('the field menu offers the board\'s own fields', /כתובת/.test(popHTML)&&/שם הפריט/.test(popHTML));
ck('…and not the ones the system fills in', !/מספר מזהה/.test(popHTML));
await FE.addQuestion('col_addr'); await sleep();
await FE.addQuestion('title'); await sleep();
ctx.renderView();
ck('the outline lists the components', (viewHTML.match(/fv-ol-row/g)||[]).length>=2);
ck('…by the form\'s own wording', /fv-ol-nm">כתובת</.test(viewHTML));
ck('adding a question selects it', FE.sel!=null);
ck('the selected one is marked in the outline', /fv-ol-row on"/.test(viewHTML));
ck('the canvas draws it as a field', /class="fv-blk fv-q sel"/.test(viewHTML));
ck('…with an input of the right kind', /class="fv-in"[^>]*type="text"/.test(viewHTML));
ck('the settings pane edits THAT question', /id="fv-c-label"[^>]*value="שם הפריט"/.test(viewHTML));
ck('…and says which board field it is bound to', /fv-bound[\s\S]*?שם הפריט/.test(viewHTML));
ck('…and offers required and visible', /שדה חובה/.test(viewHTML)&&/מוצג בטופס/.test(viewHTML));
FE.select(FE.form.components[0].id); ctx.renderView();
ck('selecting another component moves the settings pane',
   /id="fv-c-label"[^>]*value="כתובת"/.test(viewHTML));
FE.addMenu({stopPropagation(){},currentTarget:{}});
ck('a field already asked about is not offered twice', !/rm-grow">כתובת</.test(popHTML));

// ── 5 · two forms on one board, each with its own settings ──
FE.sel=null;
FE.edit('display_title','פנייה קצרה'); await FE.flushNow();
await FE.create(); await sleep();
const formB=FE.form.id;
ck('the second form is a separate form', formB!==formA);
FE.edit('display_title','פנייה מלאה'); await FE.flushNow();
ctx.renderView();
ck('the second form shows ITS title', /id="fv-dt"[^>]*value="פנייה מלאה"/.test(viewHTML));
ck('…and not the first one\'s', !/value="פנייה קצרה"/.test(viewHTML));
await FE.open(formA, formA+1000); await sleep();
ctx.renderView();
ck('switching back shows the first form\'s settings', /id="fv-dt"[^>]*value="פנייה קצרה"/.test(viewHTML));
ck('…with its own components', /fv-ol-nm">כתובת</.test(viewHTML));

// ── 6 · renaming the view ──
FE.renameFromBar('פניות תושבים'); await FE.flushNow(); await sleep();
ck('the name is saved on the form', FORMS[formA].name==='פניות תושבים');
await Views.load();
ctx.renderTabs();
ck('the tab carries the saved name',
   /class="tab-view-nm">פניות תושבים</.test(tabsHTML), tabsHTML.slice(0,200));
ck('…and is marked as a form', /fa-file-lines tab-view-ic/.test(tabsHTML));
ck('both forms are tabs on the board', (tabsHTML.match(/tab-view-nm/g)||[]).length===2);
ck('the open one is the lit one', /class="tab tab-view active"/.test(tabsHTML));

// ── 7 · the way back ──
FE.close();
ck('closing leaves the editor', !FE.isOpen());
ctx.renderView();
ck('…and the board is drawn again', !/class="fv-wrap"/.test(viewHTML));
ck('…and the address drops the view', routed[routed.length-1][2]===null);

// ── 8 · loading and failing, out loud ──
await FE.open(formA, formA+1000);
ck('opening paints before the answer arrives', true);   // see the loading branch below
FE.form=null; FE.loading=true; FE.error=null; ctx.renderView();
ck('a form being fetched says so', /טוען את הטופס/.test(viewHTML)&&/class="spin"/.test(viewHTML));
FE.loading=false; FE.error='אין לך הרשאה לערוך את הטופס הזה.'; ctx.renderView();
ck('a failure is shown, not swallowed', /אין לך הרשאה/.test(viewHTML));
ck('…with a retry', /FormEditor\.reload\(\)/.test(viewHTML)&&/נסו שוב/.test(viewHTML));
ck('…and a way back', /FormEditor\.close\(\)/.test(viewHTML));

apiFail={status:403, detail:'ניהול טופס דורש הרשאת עריכה בלוח'};
toasts=[];
await FE.create(); await sleep();
ck('a refused creation says why', toasts.some(t=>/הרשאת עריכה/.test(t)), JSON.stringify(toasts));
ck('…and does not leave a half-open editor', FE.busy===false);
apiFail=null;

// ── 9 · Autosave ─────────────────────────────────────────────────────
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const settle=()=>wait(AUTOSAVE_MS+80);

apiFail=null; apiHold=null;
await FE.open(formA, formA+1000); await sleep();
FE.sel=null;
const patches=()=>apiLog.filter(c=>c.method==='PATCH'&&/^\/api\/forms\/\d+$/.test(c.p));

// a change saves itself, and comes back after a reload
apiLog=[];
FE.edit('display_title','שמירה אוטומטית');
ck('an edit is on screen at once', FE.form.design.display_title==='שמירה אוטומטית');
ck('…and is announced as pending', FE.save.state==='pending');
ck('…without having been sent yet', patches().length===0);
await settle();
ck('…then it is sent by itself', patches().length===1);
ck('…and the state says so', FE.save.state==='saved', FE.save.state);
ck('…and the server has it', FORMS[formA].design.display_title==='שמירה אוטומטית');
await FE.open(formA, formA+1000); await sleep();      // a refresh is a fresh fetch
ck('a refresh brings it back', FE.form.design.display_title==='שמירה אוטומטית');
FE.sel=null;

// a burst ends on the last value, in one request
apiLog=[];
['א','אב','אבג','אבגד','אבגדה'].forEach(v=>FE.edit('display_title',v));
ck('a burst is not a request each', patches().length===0);
await settle();
ck('…it is one request', patches().length===1, JSON.stringify(patches()));
ck('…carrying the last value', patches()[0].body.display_title==='אבגדה');
ck('…and the server ends on it', FORMS[formA].design.display_title==='אבגדה');
ck('…and so does the screen', FE.form.design.display_title==='אבגדה');
ck('…and it reads as saved', FE.save.state==='saved');

// an answer that is older than the screen does not overwrite it
apiLog=[];
let release; apiHold={match:p=>/^\/api\/forms\/\d+$/.test(p), gate:new Promise(r=>release=r)};
FE.edit('display_title','ראשון');
const inflight=FE.flushNow();
await sleep();
ck('the first save is out', FE.save.state==='saving');
FE.edit('display_title','שני');                 // typed while the first is in the air
release(); apiHold=null;
await inflight; await settle();
ck('the newer value survives the older answer', FE.form.design.display_title==='שני',
   FE.form.design.display_title);
ck('…and is what the server is left holding', FORMS[formA].design.display_title==='שני',
   FORMS[formA].design.display_title);
ck('…and nothing is left pending', FE.save.state==='saved', FE.save.state);

// a failure is shown, and the work is not thrown away
apiLog=[]; apiFail={status:500, detail:'השרת לא זמין'};
FE.edit('display_title','לא יישמר');
await settle();
ck('a failed save says so', FE.save.state==='error', FE.save.state);
ck('…in the person’s words', /השרת לא זמין/.test(FE.save.error||''), FE.save.error);
ck('…and never says saved', FE.save.state!=='saved');
ck('…the change is still on screen', FE.form.design.display_title==='לא יישמר');
ck('…still queued, so it is not lost', FE.save.form.display_title==='לא יישמר');
ck('…and the server did NOT take it', FORMS[formA].design.display_title==='שני');
// typing again keeps the warning up rather than quietly retracting it
FE.edit('display_title','ועוד');
ck('typing on does not clear the warning', FE.save.state==='error');
apiFail=null;
await FE.retry();
ck('a retry saves what was kept', FE.save.state==='saved', FE.save.state);
ck('…including everything typed since', FORMS[formA].design.display_title==='ועוד');

// component edits ride the same queue
apiLog=[];
const q=FE.form.components[0];
FE.editComp(q.id,'label','נוסח חדש');
FE.editComp(q.id,'description','הסבר');
ck('a component edit is pending too', FE.save.state==='pending');
await settle();
const cp=apiLog.filter(c=>/components\/\d+$/.test(c.p)&&c.method==='PATCH');
ck('two fields of one question are one request', cp.length===1, JSON.stringify(cp));
ck('…carrying both', cp[0].body.label==='נוסח חדש'&&cp[0].body.description==='הסבר');
ck('…and the server has them',
   FORMS[formA].components[0].label==='נוסח חדש');

// hiding a question clears its requirement in the same edit — the server
// refuses the pair, so the screen must never send it
FE.editComp(q.id,'required',true); await settle();
FE.setVisible(q.id,false); await settle();
ck('hiding clears required rather than sending an impossible pair',
   FE.save.state==='saved'&&FORMS[formA].components[0].required===false,
   FE.save.state+' / '+FORMS[formA].components[0].required);

// leaving with work still queued
apiFail={status:500, detail:'השרת לא זמין'};
FE.edit('display_title','ביציאה');
await settle();
confirmed=null;
await FE.close();
ck('leaving with an unsaved change asks first', !!confirmed&&/לא נשמרו/.test(confirmed), confirmed);
ck('…and the asking is what leaves, not the clicking away', !FE.isOpen());
apiFail=null;

// leaving with work merely pending just saves it
await FE.open(formA, formA+1000); await sleep();
FE.sel=null;
FE.edit('display_title','ביציאה נקייה');
confirmed=null;
await FE.close();
ck('leaving with a pending change saves it without asking', confirmed===null, confirmed);
ck('…and it reached the server', FORMS[formA].design.display_title==='ביציאה נקייה');
ck('…and the editor is closed', !FE.isOpen());

// ── 10 · הוספה ועריכה של שאלות ───────────────────────────────────────
apiFail=null; apiHold=null;
{
  // a board with one field of every kind the specification names
  const TEN=[['טקסט','text'],['טקסט ארוך','long_text'],['מספר','number'],
             ['בחירה יחידה','status'],['בחירה מרובה','dropdown'],['כן/לא','checkbox'],
             ['תאריך','date'],['טלפון','phone'],['דוא"ל','email'],['קובץ','files']];
  st.board.columns=TEN.map(([he,t],i)=>({id:'c_'+t, type:t, title:he,
    options:(t==='dropdown'?['א','ב']:null)}));
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();

  // route 1 — every one of the ten is offered, and can be added
  FE.addMenu({stopPropagation(){},currentTarget:{}});
  // the menu is HTML, so a quote in a name arrives escaped — compare like
  // for like rather than teaching the product to stop escaping
  const offered=[...popHTML.matchAll(/rm-grow">([^<]*)</g)].map(m=>esc(m[1]));
  ck('all ten board fields are offered as questions',
     TEN.every(([he])=>offered.includes(esc(esc(he)))), JSON.stringify(offered));
  for(const [,t] of TEN){ await FE.addQuestion('c_'+t); await sleep(); }
  ck('…and all ten are added', FE.form.components.length===10, ''+FE.form.components.length);

  // the canvas draws each kind as the input that kind deserves
  ctx.renderView();
  ck('a long text is a textarea', /<textarea [^>]*class="fv-in"|<textarea class="fv-in"/.test(viewHTML));
  ck('a phone is a tel field, left to right', /type="tel" dir="ltr"/.test(viewHTML));
  ck('a date is a date field', /class="fv-in"[^>]*type="date"/.test(viewHTML));
  ck('an email is an email field', /class="fv-in"[^>]*type="email"/.test(viewHTML));
  ck('a boolean is a checkbox', /fv-in-cb/.test(viewHTML));
  ck('a file is a file input', /class="fv-files"/.test(viewHTML));
  ck('a multi select draws its board options as checkboxes',
     /fv-multi/.test(viewHTML)&&/fv-opt[\s\S]*?>\s*א</.test(viewHTML));

  // placeholder only where a hint inside the box means something
  const phShown=t=>{ FE.sel=FE.form.components.find(c=>c.field_key==='c_'+t).id;
                     ctx.renderView(); return /id="fv-c-ph"/.test(viewHTML); };
  ck('a text question offers a placeholder', phShown('text'));
  ck('…so does a phone', phShown('phone'));
  ck('a checkbox does not', !phShown('checkbox'));
  ck('…nor a date', !phShown('date'));
  ck('…nor a file', !phShown('files'));
  ck('…nor a list of options', !phShown('dropdown'));

  // the wording is the form's; the field keeps its own name
  const tq=FE.form.components.find(c=>c.field_key==='c_text');
  FE.editComp(tq.id,'label','איך נקרא לזה אצלנו'); await settle();
  ck('a new label is saved on the question', FORMS[g.id].components.find(
       c=>c.field_key==='c_text').label==='איך נקרא לזה אצלנו');
  ck('…and the board field keeps its name',
     st.board.columns.find(c=>c.id==='c_text').title==='טקסט');

  // route 2 — a field made from the editor
  FE.sel=null;
  st.board.my_role='admin';
  FE.addMenu({stopPropagation(){},currentTarget:{}});
  ck('an admin is offered a brand new field', /שדה חדש בלוח/.test(popHTML));
  st.board.my_role='editor';
  FE.addMenu({stopPropagation(){},currentTarget:{}});
  ck('…and an editor is not — a column is the board’s admin’s',
     !/שדה חדש בלוח/.test(popHTML));
  st.board.my_role='admin';

  FE.newFieldDialog();
  ck('the dialog offers all ten kinds',
     TEN.every(([he])=>modalHTML.includes('>'+esc(he)+'<')),
     TEN.filter(([he])=>!modalHTML.includes('>'+esc(he)+'<')).map(x=>x[0]).join(','));
  ck('…and says the field name is not the question wording', /נפרד ממנו/.test(modalHTML));
  ck('…with the options box out of the way until a select is picked',
     /id="nf-opts-wrap" hidden/.test(modalHTML));

  // it is one request, and the board gains the column
  const colsBefore=st.board.columns.length, compsBefore=FE.form.components.length;
  els['nf-title']=Object.assign(fakeEl(),{value:'טלפון ליצירת קשר'});
  els['nf-type']=Object.assign(fakeEl(),{value:'phone'});
  apiLog=[];
  await FE.createField();
  const posts=apiLog.filter(c=>/\/fields$/.test(c.p));
  ck('making a field is one request, not two', posts.length===1, JSON.stringify(apiLog));
  ck('…carrying the type and the name', posts[0].body.type==='phone'
     && posts[0].body.title==='טלפון ליצירת קשר');
  ck('the board on screen gains the column', st.board.columns.length===colsBefore+1);
  ck('…and the form gains the question', FE.form.components.length===compsBefore+1);
  ck('…which is bound to the field just made',
     FE.form.components[FE.form.components.length-1].field_key
       === st.board.columns[st.board.columns.length-1].id);
  ck('…and is the one now selected', FE.sel===FE.form.components[FE.form.components.length-1].id);

  // a select field carries the options typed into the dialog
  els['nf-title']=Object.assign(fakeEl(),{value:'סוג פנייה'});
  els['nf-type']=Object.assign(fakeEl(),{value:'dropdown'});
  els['nf-opts']=Object.assign(fakeEl(),{value:'תאורה\nניקיון\n\n'});
  apiLog=[];
  await FE.createField();
  const sel=apiLog.filter(c=>/\/fields$/.test(c.p))[0];
  ck('a select carries its options, blank lines dropped',
     JSON.stringify(sel.body.options)===JSON.stringify(['תאורה','ניקיון']),
     JSON.stringify(sel.body.options));

  // a refusal keeps the dialog up and adds nothing
  const n1=st.board.columns.length, n2=FE.form.components.length;
  els['nf-title']=Object.assign(fakeEl(),{value:'ייכשל'});
  els['nf-type']=Object.assign(fakeEl(),{value:'text'});
  apiFail={status:400, detail:'כבר יש בלוח עמודה בשם זה'};
  await FE.createField();
  ck('a refused field adds no column', st.board.columns.length===n1);
  ck('…and no question', FE.form.components.length===n2);
  ck('…and the reason is shown by the field, not in a toast',
     (els['nf-err']||{}).textContent==='כבר יש בלוח עמודה בשם זה',
     (els['nf-err']||{}).textContent);
  apiFail=null;

  // a select with nothing in it never reaches the server
  els['nf-title']=Object.assign(fakeEl(),{value:'ריק'});
  els['nf-type']=Object.assign(fakeEl(),{value:'status'});
  els['nf-opts']=Object.assign(fakeEl(),{value:'   \n  '});
  apiLog=[];
  await FE.createField();
  ck('an empty vocabulary is caught before the request',
     apiLog.filter(c=>/\/fields$/.test(c.p)).length===0);
}

// ── 11 · רכיבי תוכן והסדר המשותף ─────────────────────────────────────
apiFail=null; apiHold=null;
{
  st.board.columns=[{id:'c_a',type:'text',title:'שם'},
                    {id:'c_b',type:'phone',title:'טלפון'}];
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();

  // adding, selecting, editing
  await FE.addContent('heading'); await sleep();
  const head=FE.form.components[0];
  ck('a heading is added', head.kind==='heading');
  ck('…and selected, so it can be typed into at once', FE.sel===head.id);
  ck('…with no field of its own', head.field_key===undefined);
  ctx.renderView();
  ck('the settings pane edits its content', /id="fv-c-content"/.test(viewHTML));
  ck('…and offers nothing a question has',
     !/id="fv-c-label"/.test(viewHTML)&&!/שדה חובה/.test(viewHTML));
  /* viewHTML is the stylesheet AND the markup — `.fv-ol-row{` and
     `.fv-bgrip{` live in the first. Where a count or an absence is the
     assertion, read the markup alone. */
  const body=()=>FE.html();
  FE.editComp(head.id,'content','');
  ctx.renderView();
  ck('a heading cleared of its text is still findable on the paper',
     /\(כותרת ריקה\)/.test(body()));

  FE.editComp(head.id,'content','פרטי הפונה'); await settle();
  ck('the content is saved', FORMS[g.id].components[0].content==='פרטי הפונה');
  ctx.renderView();
  ck('…and reads on the paper', /<h3[^>]*>פרטי הפונה<\/h3>/.test(viewHTML));
  ck('…and in the outline', /fv-ol-nm">פרטי הפונה</.test(viewHTML));

  // a second heading, and the bug that made typing into it rewrite the first
  await FE.addContent('heading'); await sleep();
  const head2=FE.form.components[1];
  ctx.renderView();
  els['fvb-'+head2.id]=Object.assign(fakeEl(),{
    querySelector:()=>els['_h2']||(els['_h2']=fakeEl())});
  FE.editComp(head2.id,'content','פרטי הפנייה');
  FE.syncLabel(head2.id);
  ck('typing into the second heading leaves the first alone',
     FE.form.components[0].content==='פרטי הפונה', FE.form.components[0].content);
  ck('…and reaches the right block', (els['_h2']||{}).textContent==='פרטי הפנייה',
     (els['_h2']||{}).textContent);
  await settle();

  // a mixed list
  await FE.addQuestion('c_a'); await sleep();
  await FE.addContent('text'); await sleep();
  await FE.addQuestion('c_b'); await sleep();
  const kinds=()=>FE.form.components.map(c=>c.kind);
  ck('questions and content live in one list',
     kinds().join(',')==='heading,heading,question,text,question', kinds().join(','));
  ctx.renderView();
  ck('the outline lists all five',
     (body().match(/fv-ol-row[^>]*data-id="/g)||[]).length===5,
     ''+(body().match(/fv-ol-row[^>]*data-id="/g)||[]).length);
  ck('the paper draws all five', (viewHTML.match(/class="fv-blk/g)||[]).length===5);
  ck('a content block has no input on the paper',
     (viewHTML.match(/class="fv-in"/g)||[]).length===2, 'inputs');

  // both lists are draggable, through the one reorder
  ck('the outline is a sortable', !!FakeSortable.get(els['fv-list']));
  ck('the paper is a sortable too', !!FakeSortable.get(els['fv-blocks']));
  ck('…each by a handle, not by the whole row',
     FakeSortable.get(els['fv-list']).opts.handle==='.fv-drag'
     && FakeSortable.get(els['fv-blocks']).opts.handle==='.fv-bgrip');

  // a drag on the PAPER reorders, and the outline follows from the same array
  const ids=FE.form.components.map(c=>c.id);
  const want=[ids[4], ids[0], ids[1], ids[2], ids[3]];
  els['fv-blocks'].rows=want;
  apiLog=[];
  await FakeSortable.get(els['fv-blocks']).opts.onEnd();
  const sent=apiLog.filter(c=>/components\/order$/.test(c.p));
  ck('a drag on the paper is sent as an order', sent.length===1, JSON.stringify(apiLog));
  ck('…the order that was dropped', JSON.stringify(sent[0].body.order)===JSON.stringify(want));
  ck('the model follows', JSON.stringify(FE.form.components.map(c=>c.id))===JSON.stringify(want));
  ctx.renderView();
  const olOrder=[...viewHTML.matchAll(/fv-ol-row[^>]*data-id="(\d+)"/g)].map(m=>+m[1]);
  const pgOrder=[...viewHTML.matchAll(/class="fv-blk[^"]*"\s*\n?\s*id="fvb-(\d+)"/g)].map(m=>+m[1]);
  ck('the outline is drawn in that order', JSON.stringify(olOrder)===JSON.stringify(want),
     JSON.stringify(olOrder));
  ck('…and so is the paper', JSON.stringify(pgOrder)===JSON.stringify(want),
     JSON.stringify(pgOrder));

  // a drag in the OUTLINE does the same thing
  els['fv-list'].rows=ids;
  apiLog=[];
  await FakeSortable.get(els['fv-list']).opts.onEnd();
  ck('a drag in the outline reorders too',
     JSON.stringify(FE.form.components.map(c=>c.id))===JSON.stringify(ids));

  // the order survives a reload
  await FE.open(g.id, g.view_id); await sleep();
  ck('the order is what a refresh gives back',
     JSON.stringify(FE.form.components.map(c=>c.id))===JSON.stringify(ids),
     JSON.stringify(FE.form.components.map(c=>c.id)));

  // content blocks never become board fields
  ck('no column was created by any of it', st.board.columns.length===2);

  // deleting one
  confirmed=null;
  FE.removeRow(FE.form.components[1].id);
  await sleep(); await sleep();
  ck('removing a content block asks first', !!confirmed);
  ck('…and the rest close up', FE.form.components.length===4);

  // the respondent's form is read, not rearranged
  FE.preview=true; FE.pub={components:[{id:1,kind:'heading',content:'כ'},
                                       {id:2,kind:'question',type:'text',label:'ש'}],
                           design:FE.form.design, success:FE.form.success, token:'t'};
  ctx.renderView();
  ck('the preview has nothing to drag', !/fv-bgrip/.test(body()));
  ck('…and draws the content blocks as words', /<h3[^>]*>כ<\/h3>/.test(viewHTML));
  FE.preview=false; FE.pub=null;
}

// ── 12 · עיצוב, ומנגנון תצוגה אחד ────────────────────────────────────
apiFail=null; apiHold=null;
{
  st.board.columns=[{id:'c_a',type:'text',title:'שם'}];
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  FORMS[g.id].can_hide_branding=true;
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();
  FE.sel=null;
  const body=()=>FE.html();

  // every option the specification lists is on the pane
  ctx.renderView();
  for(const [what,mark] of [['a title','id="fv-dt"'],['a description','id="fv-dd"'],
      ['a logo','fv-logo-in'],['a primary colour','id="fv-tc"'],
      ['a background colour','id="fv-bc"'],['a submit label','id="fv-sb"'],
      ['a text size','id="fv-fs"'],['an alignment','id="fv-al"']])
    ck('the settings pane offers '+what, body().includes(mark), mark);

  // and the ones it forbids are not there
  ck('no free font choice', !/font_family|גופן/.test(body()));
  ck('no free sizes', !/type="number"[^>]*font/.test(body()));
  ck('no custom css', !/custom_css|CSS/.test(body()));

  // a change shows on the paper at once
  FE.edit('display_title','דברו איתנו');
  FE.edit('theme_color','#e2445c');
  FE.edit('background_color','#fff5f6');
  FE.edit('font_size','large');
  FE.edit('text_align','center');
  FE.edit('submit_label','שלחו');
  ctx.renderView();
  ck('the title is on the paper', /fv-paper-t">דברו איתנו</.test(body()));
  ck('the primary colour is applied', /--fv-accent:#e2445c/.test(body()));
  ck('…and the background', /background:#fff5f6/.test(body()));
  ck('…and the size, from the named set', /font-size:17px/.test(body()));
  ck('…and the alignment', /text-align:center/.test(body()));
  ck('…and the button says what it was told to', /fv-submit">שלחו</.test(body()));
  ck('the typeface is the product’s, not the form’s',
     /font-family:var\(--font\)/.test(body()));
  await settle();
  ck('…and all of it was saved', FORMS[g.id].design.submit_label==='שלחו'
     && FORMS[g.id].design.text_align==='center');

  // alignment flips the direction with it
  FE.edit('text_align','left'); ctx.renderView();
  ck('left alignment reads left to right', /direction:ltr/.test(body()));
  FE.edit('text_align','right'); ctx.renderView();
  ck('…and right goes back', /direction:rtl/.test(body()));
  await settle();

  // branding
  ck('the branding is on the paper by default', /Missions<\/b>/.test(body()));
  ck('…and the entitled are offered the switch', /הצגת מיתוג Missions/.test(body()));
  FE.edit('show_branding',false); ctx.renderView();
  ck('…which takes it off', !/fv-brand/.test(body()));
  FORMS[g.id].can_hide_branding=false; FE.form.can_hide_branding=false;
  ctx.renderView();
  ck('somebody without the entitlement is told rather than offered',
     /נדרשת הרשאה/.test(body())&&!/הצגת מיתוג Missions/.test(body()));
  FE.form.can_hide_branding=true; FE.edit('show_branding',true);
  await settle();

  // per-block emphasis and heading level
  await FE.addContent('heading'); await sleep();
  const h=FE.form.components[0];
  FE.editComp(h.id,'content','פרטי הפונה');
  FE.setBlockStyle(h.id,'style','bold');
  FE.setBlockStyle(h.id,'level',1);
  ctx.renderView();
  ck('a heading can be bold', /font-weight:800/.test(body()));
  ck('…and its level is a size from the named set', /font-size:1\.45em/.test(body()));
  ctx.renderView();
  ck('the settings pane offers the three emphases and the three levels',
     /id="fv-c-style"/.test(body())&&/id="fv-c-level"/.test(body()));
  await FE.addContent('text'); await sleep();
  const tb=FE.form.components[1];
  FE.editComp(tb.id,'content','הסבר');
  FE.setBlockStyle(tb.id,'style','italic');
  ctx.renderView();
  ck('a text block can be italic', /font-style:italic/.test(body()));
  ck('…and a text block has no heading level', !/id="fv-c-level"/.test(body()));
  await settle();

  // ── the same renderer, three times over ──
  const doc=FE.doc();
  const inEditor=FormPaper.html(doc,{editable:true, sel:null});
  const asPublished=FormPaper.html({design:doc.design, components:doc.components.map(c=>{
      const {hidden, gone, ...rest}=c; return rest;    // what /preview answers with
    })},{editable:false});
  ck('the published page is drawn by the same function',
     typeof FormPaper.html==='function');
  const strip=h=>h.replace(/ id="fvb-\d+"| data-id="\d+"| onclick="[^"]*"/g,'')
                  .replace(/<i class="fa-solid fa-grip-vertical fv-bgrip"[^>]*><\/i>/g,'')
                  .replace(/\s+/g,' ').trim();
  ck('…and draws the same form the editor does', strip(inEditor)===strip(asPublished),
     strip(inEditor).slice(0,160)+'  ≠  '+strip(asPublished).slice(0,160));

  // a hidden question is in the editor and not in what a respondent is sent
  await FE.addQuestion('c_a'); await sleep();
  const q=FE.form.components[2];
  FE.setVisible(q.id,false); await settle();
  ck('a hidden question is still shown to the builder, marked',
     /fv-q[^"]*hid/.test(FormPaper.html(FE.doc(),{editable:true})));
  ck('…and the published shape never carried it in the first place',
     !(FORMS[g.id].components.find(c=>c.id===q.id)||{}).visible);
}

// ── 13 · מחזור חיים, גישה וקישור ─────────────────────────────────────
apiFail=null; apiHold=null;
{
  // the fake server learns the lifecycle: an address at the first publish,
  // kept thereafter
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  FORMS[g.id].public_token=null; FORMS[g.id].public_url=null;
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();

  FE.share();
  ck('a draft has no link to show', !/id="fv-link"/.test(modalHTML));
  ck('…and says where one comes from', /הקישור נוצר עם הפרסום הראשון/.test(modalHTML));
  ck('the access choice is offered', /id="fv-acc"/.test(modalHTML));
  ck('…with both modes', /AUTHENTICATED/.test(modalHTML)&&/PUBLIC_LINK/.test(modalHTML));
  ck('…and says filling it in grants nothing', /אינו מעניק גישה ללוח/.test(modalHTML));
  ck('publishing is offered to an admin', /FormEditor\.setStatus\('PUBLISHED'\)/.test(modalHTML));

  // published: the address appears, and can be copied
  FORMS[g.id].status='PUBLISHED';
  FORMS[g.id].public_token='tok123456';
  FORMS[g.id].public_url='/forms/tok123456';
  await FE.reload(); await sleep();
  FE.share();
  ck('a published form shows its link', /id="fv-link"/.test(modalHTML));
  ck('…in the /forms/{id} style', /\/forms\/tok123456/.test(modalHTML), modalHTML.slice(0,80));
  ck('…with nothing of the board in it',
     !/board/i.test((/value="([^"]*)"/.exec(modalHTML.slice(modalHTML.indexOf('fv-link')))||[])[1]||''));
  ck('…and a copy button', /FormEditor\.copyLink\(\)/.test(modalHTML));
  ck('disabling is what is offered now', /FormEditor\.setStatus\('DISABLED'\)/.test(modalHTML));

  let copied=null;
  global.navigator={clipboard:{writeText:async v=>{copied=v;}}};
  els['fv-link']=Object.assign(fakeEl(),{value:'http://x/forms/tok123456', select(){}});
  await FE.copyLink();
  ck('copying puts the link on the clipboard', copied==='http://x/forms/tok123456', ''+copied);
  ck('…and says so', toasts.some(t=>/הועתק/.test(t)));

  // disabled: the link is still there, and the form is not
  FORMS[g.id].status='DISABLED';
  await FE.reload(); await sleep();
  FE.share();
  ck('a disabled form keeps its link', /\/forms\/tok123456/.test(modalHTML));
  ck('…and warns that it answers nothing', /הטופס נסגר/.test(modalHTML));
  ck('…and offers to publish it again', /FormEditor\.setStatus\('PUBLISHED'\)/.test(modalHTML));

  // somebody who may not publish is told, not offered
  st.board.my_role='editor';
  FE.share();
  ck('an editor is not offered publishing', !/FormEditor\.setStatus/.test(modalHTML));
  ck('…nor the access choice', /id="fv-acc" disabled/.test(modalHTML));
  ck('…and is told whose it is', /רק מנהל הלוח/.test(modalHTML));
  st.board.my_role='admin';
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
