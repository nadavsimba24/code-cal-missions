/* "להשוות לעמודה אחרת" — the builder's side of a column-to-column condition.

   A column condition asked about one of the board's columns and compared it
   with a value somebody typed while writing the rule. The question people
   arrive with once a board holds two columns that mean something to each other
   — "רק אם «תאריך סיום» אחרי «תאריך התחלה»" — has no such value: what the rule
   compares against is whatever the second column says on that item, and that
   is only known when it runs.

   So the value blank now offers a column as well. What this case is really
   about is that it is offered exactly where the engine would accept it and
   nowhere else — the capabilities service says which kinds may be compared at
   all, the two ends must be the same kind, and a column may not be compared
   with itself. A choice the server would refuse must never be reachable here.

   Runs the real Automations object out of index.html. Driven by
   tests/test_automation_column_vs_column_ui.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabConst(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1)+';';} }
  throw new Error('unbalanced: '+name);
}
function grabTable(decl){
  const i=src.indexOf(decl);
  if(i<0) throw new Error('not found: '+decl);
  const open=src.indexOf(decl.includes('[')?'[':'{', i), close=decl.includes('[')?']':'}';
  let d=0;
  for(let j=open;j<src.length;j++){
    if(src[j]===src[open])d++;
    else if(src[j]===close){ d--; if(!d) return src.slice(i,j+1)+';'; }
  }
  throw new Error('unbalanced: '+decl);
}

/* Two of several kinds on purpose: a kind with only ONE column on the board
   has nothing to be compared with, and that is a case of its own. */
const COLS=[
  {id:'c_start',  type:'date',     title:'תאריך התחלה'},
  {id:'c_end',    type:'date',     title:'תאריך סיום'},
  {id:'c_mid',    type:'date',     title:'אבן דרך'},
  {id:'c_plan',   type:'number',   title:'מתוכנן'},
  {id:'c_real',   type:'number',   title:'בפועל'},
  {id:'c_only',   type:'checkbox', title:'אושר'},
  {id:'c_kind',   type:'dropdown', title:'סוג פנייה', options:['תשתיות','גינון']},
];
const MEMBERS=[{user_id:4,name:'יואב'},{user_id:5,name:'דנה'}];
const st={board:{id:1,name:'לוח תשתיות',groups:[],my_role:'admin',col_perms:{}},boards:[]};

/* The capabilities service as the server answers it — including the list this
   change added, which is what decides whether the choice is offered at all. */
const CAPS={
  fields:[
    {type:'date',    kind:'date',   condition:true, operators:['on','before','after','between','empty','filled']},
    {type:'number',  kind:'number', condition:true, operators:['eq','ne','gt','lt','between','empty','filled']},
    {type:'checkbox',kind:'check',  condition:true, operators:['yes','no']},
    {type:'dropdown',kind:'status', condition:true, operators:['eq','ne','empty','filled']},
  ],
  operator_labels:{on:'בתאריך',before:'לפני',after:'אחרי',between:'בטווח',
                   eq:'שווה',ne:'אינו שווה',gt:'גדול מ',lt:'קטן מ',
                   empty:'ריק',filled:'אינו ריק',yes:'מסומן',no:'אינו מסומן'},
  operators_without_value:['empty','filled','yes','no'],
  operators_with_two_values:['between'],
  group_operators:['and','or'],
  compare_to_column:['text','number','date','status','people'],
};

let posted=null, toasts=[], pops=[], fieldValue='';

function build(){
  posted=null; toasts=[]; pops=[]; fieldValue='';
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x), m=>toasts.push(m), {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>[], ()=>[],
    ()=>COLS.slice(),
    col=>{ const c=(col&&typeof col==='object')?col:COLS.find(x=>x.id===col);
           return ((c&&c.options)||[]).map(o=>typeof o==='string'
             ?{id:null,label:o,color:'#c4c4c4'}
             :{id:o.id||null,label:o.label,color:o.color||'#c4c4c4'}); },
    ()=>false, ()=>1,
    async(url,opt)=>{ if(opt&&opt.method==='POST'){ posted={url,body:JSON.parse(opt.body)}; return {}; } return {}; },
    (anchor,html)=>{ pops.push(html); },
    ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>({value:fieldValue,focus(){},select(){}}),
     querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}},
    t=>t);
  A.conds=[
    {kind:'column_is',     label:'העמודה … היא …',  type:'column', value_label:'ערך'},
    {kind:'column_is_not', label:'העמודה … אינה …', type:'column', value_label:'ערך'},
  ];
  A.caps=JSON.parse(JSON.stringify(CAPS));
  A.maxConds=3; A.acts=[]; A.maxActs=4; A.members=MEMBERS.slice();
  A.data={can_manage:true,automations:[],people:[]};
  A.recipes=[{id:'created_set_priority',trigger:'item_created',action:'set_priority',
              sentence:'כאשר נוצר פריט חדש, שנה את העדיפות ל{a_priority}',
              fields:[{key:'a_priority',type:'priority',label:'עדיפות'}],conditions:[]}];
  A.render=()=>{};
  A.pick('created_set_priority');
  A.building.values['a_priority']={v:'high',label:'גבוהה',color:'#e2445c'};
  return A;
}

const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};

function addCond(A,kind){
  A.pickCond(EV);
  const i=(A._condOffer||[]).findIndex(x=>x.kind===kind);
  if(i<0) return false;
  A.addCond(i);
  return true;
}
function chooseCol(A,i,type,colId){
  A.pickCondCol(EV,i);
  A.colPickType(EV,type);
  const j=((A._colPick||{}).offer||[]).findIndex(c=>c.id===colId);
  if(j<0) return false;
  A.colPickOne(j);
  return true;
}
/* The whole flow, the way a person walks it: open the value blank, take the
   line at the bottom of it, pick the kind, pick the column. */
function compareWith(A,i,type,colId,second){
  A.pickCondValue(EV,i,second);
  A.pickCondCmpCol(EV,i);
  A.colPickType(EV,type);
  const j=((A._colPick||{}).offer||[]).findIndex(c=>c.id===colId);
  if(j<0) return false;
  A.colPickOne(j);
  return true;
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

// ── the choice is offered, and where ───────────────────────────────────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'date','c_end');
  A.pickCondValue(EV,0);
  const menu=pops[pops.length-1];
  ck('the value blank offers a column as well as a value',
     menu.includes('pickCondCmpCol(event,0)') && menu.includes('להשוות לעמודה אחרת'), menu);
  ck('...under the fixed values, which are still the common answer',
     menu.indexOf('היום') < menu.indexOf('להשוות לעמודה אחרת'), menu);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'number','c_plan');
  A.pickCondValue(EV,0);
  ck('a number column, whose value is typed, offers it too',
     pops[pops.length-1].includes('pickCondCmpCol(event,0)'), pops[pops.length-1]);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'checkbox','c_only');
  A.pickCondValue(EV,0);
  ck('a checkbox does not — its questions take no value at all',
     !pops[pops.length-1].includes('pickCondCmpCol'), pops[pops.length-1]);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'dropdown','c_kind');
  A.pickCondValue(EV,0);
  ck('nor does the only column of its kind — there is nothing to compare with',
     !pops[pops.length-1].includes('pickCondCmpCol'), pops[pops.length-1]);
}
{
  const A=build();
  A.caps.compare_to_column=['number'];          // the service narrows it
  addCond(A,'column_is'); chooseCol(A,0,'date','c_end');
  A.pickCondValue(EV,0);
  ck('a kind the service does not list is not offered, whatever the board holds',
     !pops[pops.length-1].includes('pickCondCmpCol'), pops[pops.length-1]);
}

// ── which columns it may be compared with ─────────────────────────────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'date','c_end');
  A.pickCondValue(EV,0); A.pickCondCmpCol(EV,0);
  const menu=pops[pops.length-1];
  ck('the same two questions the left-hand side asks — kind, then column',
     menu.includes('colPickType'), menu);
  ck('...offering only the kind that can answer', menu.includes('תאריך')
     && !menu.includes('מספר'), menu);
  A.colPickType(EV,'date');
  const list=pops[pops.length-1];
  ck('and the columns of that kind', list.includes('תאריך התחלה')
     && list.includes('אבן דרך'), list);
  ck('...never the column being asked about, which would always be true',
     !list.includes('תאריך סיום'), list);
}

// ── choosing one ──────────────────────────────────────────────────────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'date','c_end');
  ck('the flow lands on a column', compareWith(A,0,'date','c_start'));
  const c=A.building.conds[0];
  ck('the value IS the column, in the shape the server stores',
     JSON.stringify(c.v)===JSON.stringify({col:'c_start',type:'date'}), JSON.stringify(c));
  ck('...and the chip reads its name', c.label==='תאריך התחלה', JSON.stringify(c));
  const html=A.condsHTML({bare:true});
  ck('which is marked as a column and not as text being searched for',
     html.includes('fa-table-columns') && html.includes('תאריך התחלה'), html);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'number','c_plan');
  A.setCondOp2(0,'gt');
  compareWith(A,0,'number','c_real');
  ck('a comparison is not coerced to a number on its way out',
     JSON.stringify(A.building.conds[0].v)===JSON.stringify({col:'c_real',type:'number'}),
     JSON.stringify(A.building.conds[0]));
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'date','c_end');
  compareWith(A,0,'date','c_start');
  fieldValue='2026-01-05';
  A.pickCondValue(EV,0); A.setColCondText(0);
  ck('and a fixed value can be put back in its place',
     A.building.conds[0].v==='2026-01-05', JSON.stringify(A.building.conds[0]));
}

// ── both ends of a range ──────────────────────────────────────────────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'date','c_mid');
  A.setCondOp2(0,'between');
  compareWith(A,0,'date','c_start');
  compareWith(A,0,'date','c_end',true);
  const c=A.building.conds[0];
  ck('a range may name a column on each end',
     JSON.stringify(c.v)===JSON.stringify({col:'c_start',type:'date'})
     && JSON.stringify(c.v2)===JSON.stringify({col:'c_end',type:'date'}), JSON.stringify(c));
  ck('...and both chips read their column', c.label==='תאריך התחלה'
     && c.label2==='תאריך סיום', JSON.stringify(c));
}

// ── what reaches the server ───────────────────────────────────────────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'date','c_end');
  A.setCondOp2(0,'after');
  compareWith(A,0,'date','c_start');
  await A.save();
  ck('the condition travels with a reference where the value used to be',
     !!posted && JSON.stringify(posted.body.config.conditions)===JSON.stringify(
       [{kind:'column_is',value:{col:'c_end',type:'date',op:'after',
                                 value:{col:'c_start',type:'date'}}}]),
     posted&&JSON.stringify(posted.body.config.conditions));
}

// ── and it comes back to be edited ────────────────────────────────────────
{
  const A=build();
  const c=A._condFrom({kind:'column_is',
                       value:{col:'c_end',type:'date',op:'after',
                              value:{col:'c_start',type:'date'}}});
  ck('a stored comparison reads back as the column it names',
     c.label==='תאריך התחלה'
     && JSON.stringify(c.v)===JSON.stringify({col:'c_start',type:'date'}), JSON.stringify(c));
  ck('...with the operator it was written with', c.op==='after', JSON.stringify(c));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
