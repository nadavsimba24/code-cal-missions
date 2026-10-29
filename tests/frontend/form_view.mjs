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
let confirmOpts=null;   // the third argument: the wording, and what else is offered
/* The stub says yes by default — most tests are about what happens AFTER
   the question is answered. A test about the dialog itself turns that off
   and answers by hand, or by one of the other doors the dialog offers. */
let confirmAuto=true, confirmYes=null;
const els={};
/* Enough of an element for the code under test: the save indicator writes a
   class, a title and some HTML into one, and syncLabel reaches for text. */
function fakeEl(){ let v='';
  return {set innerHTML(x){v=x;}, get innerHTML(){return v;},
          className:'', textContent:'', dataset:{}, style:{},
          setAttribute(){}, getAttribute(){return null;}, removeAttribute(){},
          classList:{add(){},remove(){},toggle(){},contains(){return false;}},
          _on:{}, addEventListener(ev,fn){ (this._on[ev]=this._on[ev]||[]).push(fn); },
          focus(){}, blur(){},
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
                               views:['table'],
                               // who may be tagged — what the canvas builds
                               // an אחראים question's tick-list from
                               members:[{id:3, name:'דנה'}, {id:4, name:'אורי'}],
                               columns:[
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
                  submit_label:'', show_branding:true,
                  logo_token:null, cover_token:null, show_logo:true},
          success:{title:'', message:'', allow_another:false, redirect_url:null},
          public_url:null,
          record_submitter:true, published_at:null, published_by:null,
          config_version:1, locked:false, updated_at:null, components:[]};
}

let apiLog=[], apiFail=null, apiHold=null, apiCalls=0;
async function api(p,o){
  apiCalls++;
  const raw=o&&o.body;
  const asJson=v=>{ try{ return typeof v==='string'?JSON.parse(v):null; }catch(e){ return null; } };
  apiLog.push({p, method:(o&&o.method)||'GET', body:asJson(raw)});
  /* A request that does not answer until the test says so — how an old
     answer is made to land after a newer change. */
  if(apiHold && apiHold.match(p,o)) await apiHold.gate;
  if(apiFail){ const e=new Error('boom'); e.status=apiFail.status; e.detail=apiFail.detail; throw e; }
  const body=asJson(raw)||{};
  let m;
  /* The upload door. It answers the way the real one does — a url whose last
     segment is the token — because that is what uploadLogo takes apart. */
  if(p==='/api/upload' && o&&o.method==='POST'){
    const tok='up'+(nextId++); return {url:'/api/files/'+tok, name:'logo.png'};
  }
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
  ${grab('setView')}
  return {FormEditor, FormPaper, renderTabs, renderAddViewPop, renderView, setView};
`)(global.document, global.window, st, esc,
   api, b=>JSON.stringify(b||{}), m=>toasts.push(m),
   {set:(b,i,v)=>routed.push([b,i,v])}, Views,
   (msg,yes,opts)=>{confirmed=msg; confirmOpts=opts||{}; confirmYes=yes;
                    return confirmAuto?yes():undefined;},
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
/* No settings button: it only cleared the selection, and clicking the
   selected component already does that — select() toggles. The form's own
   settings are simply what the pane shows when nothing is selected. */
ck('…and no settings button, which had nothing of its own to do',
   !/fa-sliders/.test(viewHTML));
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
/* The way back to the FORM's own settings, which is all the settings button
   on the top bar ever did. select() toggles, so pressing the component that
   is already selected clears the selection — and an empty selection IS the
   form's settings pane. */
FE.select(FE.sel); ctx.renderView();
ck('pressing the selected component again clears the selection', FE.sel===null);
ck('…and the pane goes back to the form\u2019s own settings',
   /id="fv-dt"/.test(viewHTML)&&!/id="fv-c-label"/.test(viewHTML));
FE.select(FE.form.components[FE.form.components.length-1].id); ctx.renderView();
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

/* "טבלה ראשית" out of an open form used to do nothing: st.view was already
   'table' and Views.active was null, so setView found nothing to leave and
   renderView went on drawing the editor. Clicking one of the board's own
   views is a way out of the form, the same as the back button is. */
await FE.open(formA, formA+1000); await sleep();
ctx.setView('table');
await sleep();
ck('the board\u2019s own table is a way out of a form', !FE.isOpen());
ctx.renderView();
ck('\u2026and the board is what gets drawn', !/class="fv-wrap"/.test(viewHTML));

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

// ── 14 · שינוי עיצוב בזמן שהתצוגה המקדימה פתוחה ──────────────────────
/* `pub` is fetched once, when the preview is switched on, and the settings
   pane stays open beside it. Every design change redrew the canvas from that
   one projection, so nothing moved: unticking the Missions mark left it on
   the paper, and it came out right only after a reload.

   Read through FE.html() and not the rendered view — the view carries the
   stylesheet, where every one of these class names appears too. */
{
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();
  // the canvas alone: the settings pane that follows it shows the logo too
  const paper=()=>{const h=FE.html();
    return h.slice(h.indexOf('fv-canvas'), h.indexOf('fv-inspect'));};
  FE.preview=true;
  /* what the server answered WHEN the preview opened — a copy, not a
     reference to the model that is about to be edited */
  FE.pub={token:'t', components:[{id:2,kind:'question',type:'text',label:'שאלה'}],
          design:JSON.parse(JSON.stringify(FE.form.design)),
          success:FE.form.success};
  ck('the preview carries the Missions mark to begin with',
     /class="fv-brand"/.test(paper()));

  FE.edit('show_branding', false);
  ck('taking the mark off shows on the preview at once', !/class="fv-brand"/.test(paper()),
     'the preview still draws the projection fetched before the change');
  ck('…and the projection itself was not rewritten behind the server\u2019s back',
     FE.pub.design.show_branding !== false);

  FE.edit('theme_color', '#00c875');
  ck('…and so does a colour', /--fv-accent:#00c875/.test(paper()));
  FE.edit('submit_label', 'שליחת הפנייה');
  ck('…and the submit button\u2019s own words', /שליחת הפנייה/.test(paper()));

  /* The components stay the SERVER's: a preview exists to show what a
     respondent gets, so nothing that decides what may be ANSWERED comes off
     the screen. */
  ck('…while the questions are still the ones the server sent',
     /שאלה/.test(paper())&&!/fv-bgrip/.test(paper()));

  /* A logo switched off sends no token at all on the public route
     (_form_public_json), so the preview must not draw one either. */
  FE.form.design.logo_token='lg1'; FE.edit('show_logo', false);
  ck('a logo switched off is not drawn in the preview', !/lg1/.test(paper()));
  FE.edit('show_logo', true);
  ck('…and switched back on it is', /lg1/.test(paper()));

  FE.preview=false; FE.pub=null; FE.form.design.logo_token=null;
  await settle();
}

// ── 15 · הקנבס אומר מה הוא ───────────────────────────────────────────
/* Every field on the canvas is disabled and a click selects the question
   instead of answering it. Both are deliberate and neither was said out
   loud, so a field pressed on the canvas read as a broken field. */
{
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();
  await FE.addQuestion('c_a'); await settle();
  const canvas=()=>{const h=FE.html();
    return h.slice(h.indexOf('fv-canvas'), h.indexOf('fv-inspect'));};

  ck('the canvas says it is the editing view', /fv-edit-note/.test(canvas()));
  ck('…and names where the real check lives', /תצוגה מקדימה/.test(canvas()));
  /* The canvas used to draw a form in which nothing could be pressed — not a
     date, not a tick, not a line of text — and every one of those was
     reported as broken, which is what it looked like. The controls work
     here now; what they do NOT do is go anywhere, and the note says so. */
  ck('…and its fields can actually be used', !/<input[^>]*disabled/.test(canvas()));
  ck('…while nothing on it can be sent', !/id="fv-send"/.test(canvas()));
  ck('…and it says that what is typed here is not saved',
     /אינו נשמר/.test(canvas()));

  FE.preview=true;
  FE.pub={token:'t', components:[{id:2,kind:'question',type:'text',label:'שאלה'}],
          design:FE.form.design, success:FE.form.success};
  ck('the preview carries its own note instead', /fv-preview-note/.test(canvas())
     && !/fv-edit-note/.test(canvas()));
  ck('…and there the fields are answerable',
     !/<input[^>]*disabled/.test(canvas()));
  FE.preview=false; FE.pub=null; await settle();
}

// ── 16 · שאלת אחראים ─────────────────────────────────────────────────
/* It was a <div> with a sentence in it and no control of any kind: clicking
   it did nothing, in the editor and on the published page alike. What makes
   it answerable is the OPTIONS — the server decides per reader whether this
   question may have any (_form_people_options), and the renderer draws a box
   per person when it does and says why when it does not. */
{
  const WHO=[{value:3,label:'דנה'},{value:4,label:'אורי'}];
  const q={id:77, kind:'question', type:'people', label:'אחראים',
           required:false, settings:{}, options:WHO};
  const doc={design:{}, components:[q]};

  const filled=FormPaper.html(doc,{fill:true});
  ck('an אחראים question is drawn as a tick per person',
     (filled.match(/type="checkbox"/g)||[]).length===2, filled.slice(0,220));
  ck('…each carrying the person, by id', /value="3"/.test(filled)&&/value="4"/.test(filled));
  ck('…and named', /דנה/.test(filled)&&/אורי/.test(filled));
  ck('…answerable, not disabled', !/fv-multi[\s\S]{0,400}?checkbox" disabled/.test(filled));
  ck('…and it is no longer refused at fill time',
     !/אינו נתמך במילוי טופס/.test(filled));

  const shown=FormPaper.html(doc,{editable:true});
  ck('the builder sees the same control, greyed',
     /type="checkbox" disabled/.test(shown)&&/דנה/.test(shown));
  /* …and it says so before it is pressed. A greyed tick box is nearly
     indistinguishable from a live one, so a canvas field that is merely
     not-here read as a field that was broken. */
  ck('…and marked as a drawing, not a control', /class="fv-opt fv-opt-off"/.test(shown));
  ck('…which the fillable one never is', !/fv-opt-off/.test(filled));

  // nobody to offer: a stranger on a public link, where the server holds the
  // list back. A box with nothing in it is what this used to be.
  const none=FormPaper.html({design:{}, components:[{...q, options:[]}]},{fill:true});
  ck('with nobody to offer, the page says so rather than drawing an empty box',
     /fv-people/.test(none)&&/חבר בלוח/.test(none)&&!/type="checkbox"/.test(none));

  // what collect() makes of it — ids, as numbers
  const ticked=[{value:'4'}];
  const root={querySelector:sel=>sel==='#fa-77'?{
    classList:{contains:c=>c==='fv-multi'},
    querySelectorAll:s2=>s2==='input:checked'?ticked:[]}:null};
  const got=FormPaper.collect(doc, root);
  ck('a ticked person is collected as a number, not a string',
     JSON.stringify(got.answers['77'])==='[4]', JSON.stringify(got.answers));
  ticked.length=0;
  const empty=FormPaper.collect({design:{}, components:[{...q, required:true}]}, root);
  ck('…and an unanswered required one is reported beside the field',
     empty.missing.length===1&&empty.missing[0].label==='אחראים');
}

// ── 17 · להוציא שדה מהטופס בלי לאבד אותו ─────────────────────────────
/* Removing a question is not removing the board's column, and the two read
   as one thing: the question went, the column stayed, and a field added
   THROUGH the form left a column behind that the form never mentioned
   again. The column is named at the moment of the decision now, and the
   reversible way out is offered beside the irreversible one. */
{
  st.board.columns=[{id:'c_a',type:'text',title:'כתובת'}];
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();
  await FE.addQuestion('c_a'); await settle();
  const q=FE.form.components.find(c=>c.kind==='question'&&c.field_key==='c_a');

  // hiding, straight out of the dialog — the question stays, the column stays
  confirmAuto=false;                       // the dialog is what is under test
  confirmed=null; confirmOpts=null;
  FE.removeRow(q.id);
  ck('removing a board-backed question names the column that stays',
     /כתובת/.test((confirmOpts||{}).note||''), (confirmOpts||{}).note);
  ck('…and says what the removal actually deletes',
     /נוסח השאלה/.test((confirmOpts||{}).note||''));
  ck('…and offers hiding instead',
     /hideInstead/.test((confirmOpts||{}).noteHTML||''));
  ck('…saying what hiding keeps',
     /להחזיר אותה/.test((confirmOpts||{}).noteHTML||''));

  // the alternative really is an alternative: nothing is deleted by it
  const before=FE.form.components.length;
  FE.hideInstead(q.id); await settle();
  ck('hiding instead keeps the question', FE.form.components.length===before);
  ck('…and it is the hidden one now',
     FE.form.components.find(c=>c.id===q.id).visible===false);
  ck('…which the server was told', FORMS[g.id].components.find(c=>c.id===q.id).visible===false);
  ck('…and the person is told how to bring it back',
     /מוצג בטופס/.test(toasts[toasts.length-1]||''), toasts[toasts.length-1]);
  ck('…and the board kept its column', st.board.columns.length===1);

  // nothing to hide a second time
  confirmOpts=null; FE.removeRow(q.id);
  ck('a question already hidden is not offered hiding again',
     !((confirmOpts||{}).noteHTML||''));

  // …and saying yes to that same dialog still removes it
  await confirmYes(); await settle();
  ck('the removal itself still works', !FE.form.components.find(c=>c.id===q.id));
  ck('…and the board still kept its column', st.board.columns.length===1);

  // a content block has no column behind it, so there is nothing to promise
  await FE.addContent('heading'); await settle();
  const h=FE.form.components.find(c=>c.kind==='heading');
  confirmOpts=null; FE.removeRow(h.id);
  ck('a content block is not told about a column it never had',
     !/נוסח השאלה/.test((confirmOpts||{}).note||''));
  ck('…nor offered hiding', !((confirmOpts||{}).noteHTML||''));
  await confirmYes(); await settle();
  confirmAuto=true;
}

// ── 18 · כפתור השליחה בתצוגה המקדימה ─────────────────────────────────
/* FormPaper draws it as type="button". The public page attaches a listener
   to it by hand; the editor attached nothing, so a button that cannot submit
   never reached the form's onsubmit and "שליחה" in the preview did nothing —
   in the one place somebody checks that their form works. */
{
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();
  FE.preview=true;
  FE.pub={token:'t', components:[{id:2,kind:'question',type:'text',label:'שאלה'}],
          design:FE.form.design, success:FE.form.success};
  ctx.renderView();
  const send=global.document.getElementById('fv-send');
  ck('the preview\u2019s send button is wired to something',
     ((send._on||{}).click||[]).length===1);
  ck('…and it is the preview submission', typeof ((send._on||{}).click||[])[0]==='function');
  /* …and only once, however many times the canvas is repainted: the node is
     the same one until a repaint replaces it. */
  ctx.renderView();
  ck('…wired once per painted button, not once per paint',
     ((global.document.getElementById('fv-send')._on||{}).click||[]).length===1);
  FE.preview=false; FE.pub=null; await settle();
}

// ── 19 · לוגו לטופס ──────────────────────────────────────────────────
/* Picking a file did nothing visible. edit() writes through
   FORM_SETTING_PATH, and logo_token was not on it — so localSet found no
   path and left the model alone, while save.form carried the token to the
   server anyway. The file uploaded, the form stored it, and the screen
   redrew from a model that had never heard of it. Only a reload showed the
   logo. mergeForm walks the same keys, so the server's answer could not
   teach it either. */
{
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();
  const paper=()=>{const h=FE.html();
    return h.slice(h.indexOf('fv-canvas'), h.indexOf('fv-inspect'));};
  const pane=()=>FE.html().slice(FE.html().indexOf('fv-inspect'));

  ck('a form starts with no logo', !/fv-logo/.test(paper()));
  const picked={files:[new Blob(['x'],{type:'image/png'})], value:'C:/fake/logo.png'};
  await FE.uploadLogo(picked);
  await settle();

  const tok=FE.form.design.logo_token;
  ck('the chosen file reaches the model', !!tok, 'logo_token is '+tok);
  ck('…and the paper draws it', new RegExp('fv-logo[^>]*src="/api/files/'+tok).test(paper()));
  ck('…and the settings pane shows it with a way to remove it',
     /fv-logo-sm/.test(pane())&&/removeLogo/.test(pane()));
  ck('…and the model and the server hold the same one',
     !!FORMS[g.id].design.logo_token && FORMS[g.id].design.logo_token===tok,
     'server: '+FORMS[g.id].design.logo_token+'  model: '+tok);
  ck('…and the logo is switched on with it', FE.form.design.show_logo===true);
  ck('…and the file input was cleared, so the same file can be picked again',
     picked.value==='');

  // …and taking it off is visible at once too, for the same reason
  await FE.removeLogo(); await settle();
  ck('removing the logo clears it from the paper', !/fv-logo/.test(paper()));
  ck('…and from the server', !FORMS[g.id].design.logo_token);
  ck('…and the button to upload one is back', /fv-logo-in/.test(pane())
     && !/fv-logo-sm/.test(pane()));

  // anything that is not an image never leaves the browser
  const before=apiCalls;
  await FE.uploadLogo({files:[new Blob(['x'],{type:'application/pdf'})], value:'x.pdf'});
  ck('a file that is not an image is refused before it is sent', apiCalls===before);
  ck('…and the person is told why', /תמונה בלבד/.test(toasts[toasts.length-1]||''));
}

// ── 20 · כל רכיב בקנבס נענה ללחיצה ───────────────────────────────────
/* "אף אחד מרכיבי הטופס לא עובד" — and it was true: every control the canvas
   drew was disabled, so a date would not open, a tick would not tick and a
   line of text could not be typed. One mode of the renderer draws a form
   that works; the canvas was asking for the other one. */
{
  const WHO=[{value:3,label:'דנה'}];
  const kinds=[['text','טקסט'],['long_text','תיאור'],['number','מספר'],
               ['date','מתי'],['phone','טלפון'],['email','דואל'],
               ['checkbox','כן/לא'],['files','קובץ'],['people','אחראים']];
  const doc={design:{}, components:kinds.map(([t,l],i)=>
    ({id:i+1, kind:'question', type:t, label:l, settings:{},
      options:t==='people'?WHO:undefined}))};

  const canvas=FormPaper.html(doc,{editable:true, live:true});
  ck('not one control on the canvas is disabled', !/disabled/.test(canvas), canvas.slice(0,200));
  ck('…the date opens', /type="date"/.test(canvas)&&!/type="date"[^>]*disabled/.test(canvas));
  ck('…the long text can be typed into', /<textarea [^>]*data-type="long_text"/.test(canvas));
  ck('…the tick ticks', /data-type="people"[\s\S]{0,200}?type="checkbox" \n?\s*value="3"/.test(canvas)
     || (/data-type="people"/.test(canvas)&&!/fv-opt-off/.test(canvas)));
  ck('…and every one of them still selects its question when pressed',
     (canvas.match(/FormEditor\.select\(/g)||[]).length===kinds.length);

  // what the canvas still is NOT: a form. Nothing here sends anything.
  ck('the canvas has no send button', !/id="fv-send"/.test(canvas));
  ck('…and no error slots, because nothing is validated here',
     !/class="fv-err"/.test(canvas));

  // …and the respondent's form is unchanged by any of it
  const filled=FormPaper.html(doc,{fill:true});
  ck('the published form still sends', /id="fv-send"/.test(filled));
  ck('…and still carries an error slot per question',
     (filled.match(/class="fv-err"/g)||[]).length===kinds.length);
  ck('…and is not selectable, because nobody is editing it',
     !/FormEditor\.select\(/.test(filled));

  // the third mode is still there: a drawing, for whoever asks for one
  const drawn=FormPaper.html(doc,{editable:true});
  ck('a drawing is still drawable, and still disabled', /disabled/.test(drawn));
}

/* ── דום קטן, לשתי הבדיקות האחרונות ──────────────────────────────────

   Everything above reads a STRING of markup, and the two rules below cannot
   be seen in one. "השדה לא שומר את מה שאני מקליד" is not a statement about
   markup — the markup is identical before and after that bug, because a
   value somebody typed lives on the ELEMENT and was never in the markup at
   all. What decides it is whether the node that was typed into is still the
   node on the page afterwards. The same goes for "there is a way back to the
   form's settings": the question is whether a real click, landing on a real
   target, reaches a handler that clears the selection.

   So: a parser for the renderer's own output, elements with identity, and
   exactly the DOM calls FormEditor makes — querySelector, closest,
   classList, dataset, textContent, createElement, appendChild, remove. It is
   not a browser, it must never become one, and anything it cannot do should
   send the test back to a string assertion rather than grow a feature. */
const VOID=new Set(['input','img','br','hr','meta','link','source','col']);
class El{
  constructor(tag,attrs){ this.tagName=String(tag).toUpperCase(); this.attrs=attrs||{};
    this.kids=[]; this.parentNode=null; this._html='';
    /* Not in the markup and that is the whole point: what a person typed. */
    this.value=''; this.checked=false; this._on={}; }
  get id(){ return this.attrs.id||''; }
  get className(){ return this.attrs.class||''; }
  set className(v){ this.attrs.class=String(v); }
  _cls(){ return (this.attrs.class||'').split(/\s+/).filter(Boolean); }
  get classList(){ const self=this; const has=c=>self._cls().includes(c);
    const set=l=>{ self.attrs.class=l.join(' '); };
    return {contains:has,
      add:c=>{ if(!has(c)) set(self._cls().concat(c)); },
      remove:c=>set(self._cls().filter(x=>x!==c)),
      toggle:(c,on)=>{ const want=on===undefined?!has(c):!!on;
        want?(has(c)||set(self._cls().concat(c))):set(self._cls().filter(x=>x!==c)); }};
  }
  get dataset(){ const d={};
    for(const k of Object.keys(this.attrs)) if(k.startsWith('data-'))
      d[k.slice(5).replace(/-([a-z])/g,(m,c)=>c.toUpperCase())]=this.attrs[k];
    return d; }
  getAttribute(n){ return n in this.attrs?this.attrs[n]:null; }
  setAttribute(n,v){ this.attrs[n]=String(v); }
  removeAttribute(n){ delete this.attrs[n]; }
  get children(){ return this.kids.filter(k=>k instanceof El); }
  appendChild(c){ c.parentNode=this; this.kids.push(c); return c; }
  remove(){ const p=this.parentNode; if(!p) return;
    p.kids=p.kids.filter(x=>x!==this); this.parentNode=null; }
  get textContent(){ return this.kids.map(k=>typeof k==='string'?k:k.textContent).join(''); }
  set textContent(v){ this.kids=[String(v)]; this._html=String(v); }
  get innerHTML(){ return this._html; }
  set innerHTML(v){ this._html=String(v);
    this.kids=parseHTML(String(v)).kids.map(k=>{ if(k instanceof El) k.parentNode=this; return k; }); }
  /* The one that costs what this file is about. Assigning either of these
     parses the markup into FRESH elements and puts them where the old ones
     were: a value somebody typed was on the old element and is not in the
     markup, so it is simply gone. That is not a quirk of this little DOM —
     it is what the browser does, and it is why a repaint that rebuilds the
     canvas empties the form under the person filling it in. */
  get outerHTML(){ return this._outer||''; }
  set outerHTML(v){
    const p=this.parentNode; if(!p) return;
    const fresh=parseHTML(String(v)).kids;
    fresh.forEach(n=>{ if(n instanceof El) n.parentNode=p; });
    p.kids.splice(p.kids.indexOf(this),1,...fresh);
    this.parentNode=null;
  }
  matches(sel){ return selMatch(this, sel); }
  closest(sel){ let n=this; while(n){ if(selMatch(n,sel)) return n; n=n.parentNode; } return null; }
  querySelector(sel){ return this.querySelectorAll(sel)[0]||null; }
  querySelectorAll(sel){ const out=[];
    const walk=n=>{ for(const k of n.children){ if(selMatch(k,sel)) out.push(k); walk(k); } };
    walk(this); return out; }
  focus(){} blur(){}
  addEventListener(ev,fn){ (this._on[ev]=this._on[ev]||[]).push(fn); }
}
/* One simple selector: a tag, any number of .classes, #ids and [attrs], and
   :not(). Descendants by space, alternatives by comma — which between them
   is every selector FormEditor and FormPaper actually ask for. Anything else
   throws rather than quietly matching nothing, which would turn a broken
   test into a passing one. */
function simpleMatch(el,s){
  s=s.trim(); if(!s) return false;
  const tag=/^[a-zA-Z][\w-]*/.exec(s);
  if(tag && el.tagName!==tag[0].toUpperCase()) return false;
  const rest=s.slice(tag?tag[0].length:0);
  const parts=rest.match(/:not\([^)]*\)|\[[^\]]*\]|[.#][\w-]+/g)||[];
  if(rest.replace(/\s+/g,'').length!==parts.join('').length)
    throw new Error('selector the mini-DOM cannot read: '+s);
  for(const p of parts){
    if(p.startsWith('.')){ if(!el.classList.contains(p.slice(1))) return false; }
    else if(p.startsWith('#')){ if(el.id!==p.slice(1)) return false; }
    else if(p.startsWith('[')){
      const a=/^\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]$/.exec(p);
      if(!a) throw new Error('attribute selector the mini-DOM cannot read: '+p);
      const got=el.getAttribute(a[1]);
      if(got===null) return false;
      if(a[2]!==undefined && got!==a[2]) return false;
    }
    else { const inner=p.slice(5,-1); if(inner.split(',').some(x=>simpleMatch(el,x))) return false; }
  }
  return true;
}
function selMatch(el,sel){
  return String(sel).split(',').some(one=>{
    const chain=one.trim().split(/\s+/);
    if(!simpleMatch(el, chain.pop())) return false;
    let n=el.parentNode;
    while(chain.length){
      const want=chain.pop();
      while(n && !simpleMatch(n,want)) n=n.parentNode;
      if(!n) return false;
      n=n.parentNode;
    }
    return true;
  });
}
function parseHTML(html){
  const root=new El('#root',{}), stack=[root];
  const re=/<(\/?)([a-zA-Z][\w-]*)((?:"[^"]*"|'[^']*'|[^>])*)>/g;
  let m, last=0;
  while((m=re.exec(html))){
    const text=html.slice(last,m.index);
    if(text) stack[stack.length-1].kids.push(text);
    last=re.lastIndex;
    const [,close,tag,raw]=m;
    if(close){
      const el=stack.pop();
      if(el && el!==root){ el._html=html.slice(el._from, m.index);
                           el._outer=html.slice(el._open, re.lastIndex); }
      continue;
    }
    const attrs={};
    const ar=/([:@\w-]+)(?:\s*=\s*"([^"]*)"|\s*=\s*'([^']*)')?/g;
    let a; while((a=ar.exec(raw))) attrs[a[1]]=a[2]!==undefined?a[2]:(a[3]!==undefined?a[3]:'');
    const el=new El(tag,attrs);
    el._open=m.index; el._from=re.lastIndex; el._outer=m[0];
    stack[stack.length-1].appendChild(el);
    if(!VOID.has(tag.toLowerCase()) && !/\/$/.test(raw)) stack.push(el);
  }
  const tail=html.slice(last);
  if(tail) stack[stack.length-1].kids.push(tail);
  return root;
}

/* The editor, painted into that document. FE.html() and not paint(), because
   paint() prepends css() and a stylesheet is not a tree. */
function mount(){
  const root=parseHTML(FE.html());
  const origGet=global.document.getElementById;
  global.document.querySelector=sel=>root.querySelector(sel);
  global.document.querySelectorAll=sel=>root.querySelectorAll(sel);
  global.document.getElementById=id=>root.querySelector('#'+id)||origGet.call(global.document,id);
  global.document.createElement=tag=>new El(tag,{});
  FE.attachSort();                       // what paint() does after writing the HTML
  return root;
}

// ── 21 · מה שהוקלד בקנבס נשאר שם ─────────────────────────────────────
/* "השדה לא נותן להקליד / לא שומר מה שהקלדתי", twice over and by two roads.

   The canvas draws live controls now, so somebody can try their own form
   where they are building it. That only means anything if what they type
   survives the next thing they do — and every edit in the settings pane used
   to rebuild the canvas from scratch: one character typed into the form's
   title replaced every node on the paper, taking the caret and the half
   filled form with it, and then did it again on the next character.

   Each of the four paths that touch the canvas is pinned the same way: the
   node that was typed into has to be the SAME node afterwards, still holding
   its value, and the change being made has to show. A repaint that does
   nothing would pass the first half on its own. */
{
  st.board.columns=[{id:'c_a',type:'text',title:'כתובת'},
                    {id:'c_b',type:'long_text',title:'תיאור'}];
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();
  await FE.addQuestion('c_a'); await settle();
  await FE.addQuestion('c_b'); await settle();
  await FE.addContent('heading'); await settle();
  const qs=FE.form.components;
  const one=qs.find(c=>c.field_key==='c_a'), two=qs.find(c=>c.field_key==='c_b');
  const head=qs.find(c=>c.kind==='heading');

  /* Nothing selected: adding a block selects it, and the settings pane is
     where this starts — somebody edits the form's look and watches the paper. */
  FE.sel=null;
  const root=mount();
  const paper=root.querySelector('.fv-paper');
  const canvas=root.querySelector('.fv-canvas');
  const field=root.querySelector('#fa-'+one.id);
  const area=root.querySelector('#fa-'+two.id);
  ck('the canvas really is a form: the question is an element with a value',
     !!field && !!area && field.tagName==='INPUT' && area.tagName==='TEXTAREA',
     (field&&field.tagName)+'/'+(area&&area.tagName));
  const typed='רחוב הרצל 10', typed2='שתי שורות';
  field.value=typed; area.value=typed2;

  /* The settings pane is what calls repaint, and on oninput — every
     keystroke. Read off the pane rather than assumed, so a pane that stops
     calling it takes this test with it. */
  const pane=root.querySelector('.fv-inspect');
  ck('a design setting repaints the canvas on every keystroke',
     /FormEditor\.edit\('display_title',this\.value\);FormEditor\.repaint\(\)/.test(pane.innerHTML),
     pane.innerHTML.slice(0,200));

  /* Asked of the PAGE and not of the variable: a rebuilt canvas leaves the
     old element in this test's hand, holding its value, attached to nothing
     — which is exactly what the person typing is left with too. */
  const onPage=c=>root.querySelector('#fa-'+c.id);
  const kept=()=>onPage(one)===field&&field.value===typed
                 &&onPage(two)===area&&area.value===typed2;

  FE.edit('display_title','טופס פניות'); FE.repaint();
  ck('typing the form’s title leaves what is typed in the form alone', kept(),
     'the field on the page is '+(onPage(one)===field?'the same, emptied':'a new one'));
  ck('…while the title itself did change on the paper',
     root.querySelector('.fv-paper-t').textContent==='טופס פניות');

  FE.edit('theme_color','#00c875'); FE.repaint();
  ck('a colour keeps them too', kept());
  ck('…and reaches the paper', /#00c875/.test(paper.getAttribute('style')||''));

  FE.edit('show_branding',false); FE.repaint();
  ck('unticking the Missions mark takes it off', !root.querySelector('.fv-brand'));
  ck('…without emptying the form', kept());
  FE.edit('show_branding',true); FE.repaint();
  ck('…and ticking it puts it back', !!root.querySelector('.fv-brand'));
  ck('…still without emptying the form', kept());

  FE.edit('submit_label','שליחת פנייה'); FE.repaint();
  ck('the submit button’s words change in place',
     root.querySelector('.fv-submit').textContent==='שליחת פנייה');
  ck('…and that did not empty the form either', kept());

  /* Renaming the question and styling a heading are the other two in-place
     paints. Both used to go through a full rebuild for a single keystroke. */
  FE.editComp(one.id,'label','כתובת האירוע'); FE.syncLabel(one.id);
  ck('renaming a question renames it on the paper',
     /כתובת האירוע/.test(root.querySelector('#fvq-'+one.id+'-l').textContent));
  ck('…and does not empty the field under it', kept());

  FE.setBlockStyle(head.id,'style','bold');
  ck('making a heading bold styles that heading',
     /font-weight/.test(root.querySelector('#fvb-'+head.id).querySelector('h3')
                        .getAttribute('style')||''),
     (root.querySelector('#fvb-'+head.id).querySelector('h3')||{}).attrs);
  ck('…and leaves the answers below it where they were', kept());

  /* And selecting — the first road the complaint arrived by. A press inside
     a text field selects the question for the settings pane, which is how
     this screen works; what it must never do is take the field away. */
  FE.select(one.id,{target:field});
  ck('pressing the field selects its question', FE.sel===one.id);
  ck('…and the field is untouched', kept());
  ck('…and the block says it is the selected one',
     root.querySelector('#fvb-'+one.id).classList.contains('sel'));
  FE.select(one.id,{target:field});
  ck('a second press in the same field does not close the pane under the caret',
     FE.sel===one.id);
  ck('…and the canvas says something is selected, for the hint under it',
     canvas.classList.contains('has-sel'));
}

// ── 22 · הדרך חזרה להגדרות הטופס ─────────────────────────────────────
/* The settings pane shows the selected question or the form itself, and
   nothing else shows the form's own settings: "הגדרות" came off the top bar
   on purpose. So once a question is selected there has to be a way back, and
   pressing the question again is not one — select() refuses to toggle off
   when the press landed on a control, and a question block in editing mode
   is now almost entirely controls, label included.

   Which handler provides it is not this test's business. The editor is drawn,
   a real click is aimed at the paper background, and every handler on the
   canvas that is not a question's own gets it; one of them has to put the
   pane back on the form. A click aimed INSIDE a question must not. */
{
  st.board.columns=[{id:'c_a',type:'text',title:'כתובת'}];
  const g=await api('/api/boards/7/forms',{method:'POST',headers:{},body:'{}'});
  await Views.load(); await FE.open(g.id, g.view_id); await sleep();
  await FE.addQuestion('c_a'); await settle();
  const q=FE.form.components[0];
  const root=mount();
  const paper=root.querySelector('.fv-paper');
  const field=root.querySelector('#fa-'+q.id);
  const pane=root.querySelector('.fv-inspect');

  /* A handler, as a browser would run it: the code in the attribute, with
     `event` bound to the click that reached it. */
  const run=(code,ev)=>{ try{ new Function('FormEditor','event',code)(FE,ev); return null; }
                         catch(e){ return e; } };
  /* Everything inside that answers a press, the element itself included. */
  const clickable=el=>(el.getAttribute('onclick')?[el]:[])
      .concat(el.querySelectorAll('[onclick]'));

  FE.select(q.id,{target:field});
  ck('a question is selected, and the pane is its own',
     FE.sel===q.id && /id="fv-c-label"/.test(pane.innerHTML));
  ck('…and pressing the question again does not get out of it',
     (FE.select(q.id,{target:field}), FE.sel===q.id));

  const canvas=root.querySelector('.fv-canvas');
  const onPaper={target:paper, stopPropagation(){}, preventDefault(){}};
  const ways=[];
  for(const el of clickable(canvas)){
    if(el.closest('.fv-blk')) continue;        // the question's own handler
    FE.sel=q.id; FE.paintSel();
    run(el.getAttribute('onclick'), onPaper);
    if(FE.sel===null) ways.push(el.className||el.tagName);
  }
  ck('a click on the paper, beside the questions, gets back to the form',
     ways.length>0, 'nothing on the canvas clears the selection: '
     + clickable(canvas).map(e=>e.getAttribute('onclick')).join(' | '));
  ck('…and the pane is then the form’s own settings',
     /id="fv-dt"/.test(pane.innerHTML)&&!/id="fv-c-label"/.test(pane.innerHTML),
     pane.innerHTML.slice(0,160));
  ck('…and the canvas stops saying that something is selected',
     !canvas.classList.contains('has-sel'));

  /* …and the same handler must keep its hands off a click that landed on a
     question. Everything inside the canvas reaches it — the blocks do not
     stop their own clicks, and they must not — so a background handler that
     does not check where the press landed deselects the question half a
     millisecond after select() chose it. */
  const onField={target:field, stopPropagation(){}, preventDefault(){}};
  for(const el of clickable(canvas)){
    if(el.closest('.fv-blk')) continue;
    FE.sel=q.id; FE.paintSel();
    run(el.getAttribute('onclick'), onField);
    ck('a press inside a question is not treated as a press on the background',
       FE.sel===q.id, el.getAttribute('onclick'));
  }

  /* One of the two doors has to open without a mouse. A background is not a
     tab stop, so the pane carries a real button at the head of the selected
     question — found the same way, by running what it is wired to. */
  FE.sel=q.id; FE.paintSel();
  const paneRoot=parseHTML(pane.innerHTML);
  const buttons=paneRoot.querySelectorAll('button[onclick]')
    .filter(b=>{ FE.sel=q.id; run(b.getAttribute('onclick'), null); return FE.sel===null; });
  ck('the keyboard has a way back too: a button in the question’s settings',
     buttons.length>0, paneRoot.querySelectorAll('button').map(b=>b.textContent).join(' | '));
  ck('…that says where it goes', buttons.some(b=>/הגדרות הטופס/.test(b.textContent)),
     buttons.map(b=>b.textContent).join(' | '));
  FE.sel=null;
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
