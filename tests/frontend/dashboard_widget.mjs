/* The dashboard widget, drawn headless.
 *
 * What it pins is the half of R04 and DASH-15 that lives in the browser: a
 * figure is rounded for DISPLAY and never in the data, and no state that is
 * not a number is ever allowed to look like one. "0" and "there is nothing
 * to show" and "you may not see this" and "this is broken" are four
 * different answers, and the whole point of the card is that a reader can
 * tell them apart — in words and an icon, never by colour alone (R08).
 *
 * Driven by tests/test_dashboard_frontend.py. */
import fs from 'fs'; import path from 'path'; import {fileURLToPath} from 'url';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..','..');
const src=fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');
const from=src.indexOf('const Dash = {'), to=src.indexOf('/* ============ CEO City Dashboard ============ */');
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const code=src.slice(from,to);
const f=new Function('esc','api','st','renderView','showModal','closeModals','toast','setHTML','window','document','openBoard','Chat','sessionStorage',code+'\nreturn {Dash,CALC_HE};');
const stub=()=>{};
const {Dash,CALC_HE}=f(esc,stub,{view:'dash',boards:[]},stub,stub,stub,stub,stub,
  {innerWidth:1400},{getElementById:()=>null,querySelector:()=>null,createElement:()=>({}),body:{appendChild:stub}},stub,{},{setItem:stub,getItem:()=>null});
let pass=0,fail=0; const ck=(n,c)=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n));};
// DASH-15 formatting
ck('a plain number groups thousands', Dash.fmt({result:1234567,format:'number',precision:0,thousands:true}).includes('1,234,567'));
ck('precision is honoured', Dash.fmt({result:1/3,format:'number',precision:2})==='0.33');
ck('a 0-1 percent is shown as a percent', Dash.fmt({result:0.5,format:'percent',scale:'0-1',precision:0})==='50%');
ck('a 0-100 percent is not doubled', Dash.fmt({result:50,format:'percent',scale:'0-100',precision:0})==='50%');
ck('currency leads with its unit', Dash.fmt({result:1200,format:'currency',unit:'₪',precision:0}).startsWith('₪'));
ck('no result shows a dash, never a zero', Dash.fmt({result:null})==='—');
ck('the full value is kept beside the rounded one', Dash.full({result:1/3})===String(1/3));
// states never render a bare 0
const blocked=Dash.body({id:1},{state:'blocked',metrics:[]});
ck('a blocked widget says so in words', blocked.includes('הרשאות')&&!blocked.includes('>0<'));
const err=Dash.body({id:1},{state:'error',metrics:[]});
ck('an error offers a retry', err.includes('ניסיון חוזר'));
const nodata=Dash.metric({id:1},{state:'no_data',calc:'avg'},{});
ck('no data is not a zero', nodata.includes('אין נתונים')&&!/>\s*0\s*</.test(nodata));
const fix=Dash.metric({id:1},{state:'needs_fix',failed:3,calc:'sum'},{can_fix:true});
ck('needs_fix names how many failed', fix.includes('3 רשומות'));
ck('the repair link is only for whoever may fix it',
   Dash.metric({id:1},{state:'needs_fix',calc:'sum'},{can_fix:false}).indexOf('תקן')<0);
// R08 — a state is never carried by colour alone: each one brings an icon
for(const [name,html] of [['blocked',blocked],['error',err],['no data',nodata],['needs fix',fix]])
  ck(`${name} carries an icon and a word, not a colour`, /<i class="fa-/.test(html)&&/[\u0590-\u05FF]/.test(html));
// the figure is a real control: focusable, labelled, and says what it opens
const ok=Dash.metric({id:7,title:'ט'},{key:'m',state:'ok',result:42,calc:'count',records:5,values:5,precision:0},{});
ck('the figure is a button with an accessible name', ok.includes('<button')&&ok.includes('aria-label='));
ck('the figure says what clicking it does', ok.includes('פתיחת פירוט'));
ck('the full value is on the title for touch and focus', ok.includes('title="42'));
ck('a count reports how many records it counted', ok.includes('5 רשומות'));
// DASH-19.3 — the mobile column follows the saved reading order
const ws=[{id:3,position:2},{id:1,position:0},{id:2,position:1}];
ck('widgets are ordered by their saved position', Dash.order(ws).map(w=>w.id).join()==='1,2,3');
// R08 — editing controls are desktop-only, and that is decided in JS and not
// only hidden in CSS
Dash.d={can_edit:true,widgets:[],sources:[]};
ck('a narrow window is not an editing surface',(()=>{const w=Dash.isWide;Dash.isWide=()=>false;
  const card=Dash.card({id:1,title:'x'}); Dash.isWide=w; return !card.includes('dash-w-menu');})());
/* ── DASH-18.3 · the way back from an item opened out of a dashboard ──
 * Reported as "עולה כפתור חזרה לדשבורד במיקום לא הגיוני". It was a
 * position:fixed button at 70px from the top and 16px from the start edge,
 * which is where the board writes its own NAME — so the return from a
 * drill-down covered the name of the board it had just returned to. It
 * belongs in the header line, before the name, where RTL reads it first. */
const fakeDom=()=>{
  const byId={};
  const el=t=>({tag:t,style:{cssText:''},innerHTML:'',attrs:{},children:[],
    set id(v){this._id=v; byId[v]=this;}, get id(){return this._id||'';},
    setAttribute(k,v){this.attrs[k]=v;},
    prepend(c){this.children.unshift(c);}, appendChild(c){this.children.push(c);},
    remove(){ this.children=[];
      for(const k of Object.keys(byId)) if(byId[k]===this) delete byId[k];
      for(const h of [head,body]) h.children=h.children.filter(x=>x!==this); }});
  const head=el('div'), body=el('body');
  head.appendChild(el('h1'));                       // the board's own name
  return {head, body, byId, doc:{
    body, createElement:t=>el(t),
    getElementById:id=>byId[id]||null,
    querySelector:sel=>sel==='#boardhead .bh-top'?head:null}};
};
const dom=fakeDom();
const {Dash:D2}=f(esc,stub,{view:'board',boards:[]},stub,stub,stub,stub,stub,
  {innerWidth:1400},dom.doc,stub,{},{setItem:stub,getItem:()=>null});
D2.showReturn();
const back=dom.byId['dash-back'];
ck('the way back is drawn in the board header, not floated over it',
   !!back && dom.body.children.length===0);
ck('…before the board name, which is what it used to cover',
   dom.head.children[0]===back && dom.head.children[1].tag==='h1');
ck('…so it carries no fixed position of its own',
   !!back && !/fixed/.test(back.style.cssText||''));
ck('…and says what it is to a screen reader',
   !!back && back.attrs['aria-label']==='חזרה לדשבורד');
D2.showReturn();
ck('…and is offered once, not once per visit', dom.head.children.length===2);
D2.clearReturn();
ck('arriving at the dashboard takes the offer away again',
   !dom.byId['dash-back'] && dom.head.children.length===1);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
