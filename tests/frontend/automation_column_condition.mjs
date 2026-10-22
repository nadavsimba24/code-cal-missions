/* "רק אם" over one of the board's own columns — the builder's side of it.

   The conditions that existed asked about the four things every board has. A
   board's own columns hold most of what it means, and asking about one takes
   three answers in a fixed order, because each decides the next: the KIND of
   column, then the column, then the value — a value picker cannot be offered
   before the column is known, since the column is what decides whether the
   answer is a status label, a number, a person or a date.

   Runs the real Automations object out of index.html. Driven by
   tests/test_automation_column_condition.py. */
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
/* ADV_KINDS, ADV_DATES and COLUMN_TYPES are the page's own tables — grabbed,
   not retyped, so a column type added to the app is a column type this case
   sees. */
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

const COLS=[
  {id:'c_budget', type:'number',   title:'תקציב'},
  {id:'c_stage',  type:'status',   title:'שלב', options:[{id:'o1',label:'הוגש',color:'#00c875'},
                                                         {id:'o2',label:'נדחה',color:'#e2445c'}]},
  {id:'c_kind',   type:'dropdown', title:'סוג פנייה', options:['תשתיות','גינון']},
  {id:'c_super',  type:'people',   title:'מפקח'},
  {id:'c_due',    type:'date',     title:'תאריך אספקה'},
  {id:'c_ok',     type:'checkbox', title:'אושר'},
  {id:'c_link',   type:'connect',  title:'לוח מקושר'},     // asked about the link
  {id:'c_mir',    type:'mirror',   title:'שם אצלם',
   mirror_of:{connect:'c_link', field:'title'}},          // read, never listened to
];
const MEMBERS=[{user_id:4,name:'יואב'},{user_id:5,name:'דנה'}];
const st={board:{id:1,name:'לוח תשתיות',groups:[],my_role:'admin',col_perms:{}},boards:[]};

let posted=null, toasts=[], pops=[], fieldValue='';

function build(){
  posted=null; toasts=[]; pops=[]; fieldValue='';
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage',
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
    ()=>{}, {getItem:()=>null,setItem(){}});
  /* the catalog as the server sends it, with the two column kinds in it */
  A.conds=[
    {kind:'status_is',   label:'הסטטוס הוא …', type:'status', value_label:'סטטוס'},
    {kind:'no_assignee', label:'אין אחראי לפריט', type:null, value_label:''},
    {kind:'column_is',     label:'העמודה … היא …',  type:'column', value_label:'ערך'},
    {kind:'column_is_not', label:'העמודה … אינה …', type:'column', value_label:'ערך'},
  ];
  A.maxConds=3; A.acts=[]; A.maxActs=4; A.members=MEMBERS.slice();
  A.colKinds={text:['text'],status:['status','dropdown'],number:['number'],
              people:['people'],date:['date'],check:['checkbox']};
  A.multiCols=['dropdown','people','files'];
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

/* Add a condition the way the UI does: open the menu, pick from it. */
function addCond(A,kind){
  A.pickCond(EV);
  const i=(A._condOffer||[]).findIndex(x=>x.kind===kind);
  if(i<0) return false;
  A.addCond(i);
  return true;
}
function chooseCol(A,i,type,colId){
  A.pickCondColOf(EV,i,type);
  const j=(A._condColOffer||[]).findIndex(c=>c.id===colId);
  if(j<0) return false;
  A.setCondCol(i,j);
  return true;
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,260):''))); };

// ── the condition is offered at all ────────────────────────────────────────
{
  const A=build();
  A.pickCond(EV);
  const kinds=(A._condOffer||[]).map(x=>x.kind);
  ck('"רק אם" offers a condition about a column', kinds.includes('column_is')
     && kinds.includes('column_is_not'), kinds);
}

// ── step 1: the kind of column, and only kinds this board has ─────────────
{
  const A=build();
  addCond(A,'column_is');
  A.pickCondCol(EV,0);
  const menu=pops[pops.length-1];
  ck('the first question is what KIND of column', menu.includes('pickCondColOf'), menu);
  ['מספר','סטטוס','רשימה נפתחת','אנשים','תאריך','תיבת סימון'].forEach(he=>
    ck('...offering '+he, menu.includes(he), menu));
  ck('a column with nothing to compare is not offered at all',
     !menu.includes('קישור בין לוחות'), menu);
  ck('and each kind says how many such columns the board has',
     /<small[^>]*>1<\/small>/.test(menu), menu);
}

// ── step 2: the column itself ─────────────────────────────────────────────
{
  const A=build();
  addCond(A,'column_is');
  A.pickCondColOf(EV,0,'number');
  const menu=pops[pops.length-1];
  ck('the second question is which column of that kind',
     menu.includes('setCondCol(0,0)') && menu.includes('תקציב'), menu);
  ck('...and not one of another kind', !menu.includes('שלב'), menu);
  A.setCondCol(0,0);
  const c=A.building.conds[0];
  ck('the column, and the kind of column it is, are both kept on the condition',
     c.col==='c_budget' && c.colType==='number' && c.colLabel==='תקציב', JSON.stringify(c));
}

// ── step 3: the value, and the column is what decides the question ────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'status','c_stage');
  A.pickCondValue(EV,0);
  const menu=pops[pops.length-1];
  ck("a status column offers that column's OWN labels",
     menu.includes('הוגש') && menu.includes('נדחה'), menu);
  A.setCondValue(0,0);
  ck('...and the chosen one becomes the chip, in its own colour',
     A.building.conds[0].v==='הוגש' && A.building.conds[0].color==='#00c875',
     JSON.stringify(A.building.conds[0]));
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'dropdown','c_kind');
  A.pickCondValue(EV,0);
  ck('a dropdown offers its own options', pops[pops.length-1].includes('תשתיות'),
     pops[pops.length-1]);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'people','c_super');
  A.pickCondValue(EV,0);
  ck('a people column offers the board members', pops[pops.length-1].includes('דנה'),
     pops[pops.length-1]);
  A.setCondValue(0,1);
  ck('...and stores the person', A.building.conds[0].v===5, A.building.conds[0]);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'checkbox','c_ok');
  A.pickCondValue(EV,0);
  ck('a checkbox offers the two answers it has',
     pops[pops.length-1].includes('מסומן') && pops[pops.length-1].includes('לא מסומן'),
     pops[pops.length-1]);
  A.setCondValue(0,1);
  ck('...and "לא מסומן" is false and not an empty value',
     A.building.conds[0].v===false, A.building.conds[0]);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'date','c_due');
  A.pickCondValue(EV,0);
  const menu=pops[pops.length-1];
  ck('a date column offers the dynamic dates, so "היום" stays "היום"',
     menu.includes('היום') && menu.includes('השבוע'), menu);
  ck('...and a specific day can be typed instead', menu.includes('type="date"'), menu);
  A.setCondValue(0,0);
  ck('a token is stored as the token', A.building.conds[0].v==='today', A.building.conds[0]);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'number','c_budget');
  A.pickCondValue(EV,0);
  ck('a number column asks for a number to be typed',
     pops[pops.length-1].includes('au-cv') && pops[pops.length-1].includes('type="number"'),
     pops[pops.length-1]);
  fieldValue='1000';
  A.setColCondText(0);
  ck('...and stores it as a number, not as text', A.building.conds[0].v===1000,
     JSON.stringify(A.building.conds[0]));
}

// ── the row reads as the sentence it is ───────────────────────────────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'number','c_budget');
  fieldValue='1000'; A.pickCondValue(EV,0); A.setColCondText(0);
  const h=A.condsHTML();
  ck('the condition reads with its two blanks filled',
     h.includes('תקציב') && h.includes('1000') && h.includes('רק אם'), h);
  ck('...each of them still clickable, to be changed',
     h.includes('pickCondCol(event,0)') && h.includes('pickCondValue(event,0)'), h);
}

// ── changing the column clears a value chosen for the old one ─────────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'status','c_stage');
  A.pickCondValue(EV,0); A.setCondValue(0,0);
  chooseCol(A,0,'dropdown','c_kind');
  ck('a label from the previous column is not kept as this one\'s answer',
     A.building.conds[0].v===null && A.building.conds[0].label==='',
     JSON.stringify(A.building.conds[0]));
}

// ── an unfinished column condition is an unfinished rule ──────────────────
{
  const A=build();
  addCond(A,'column_is');                        // no column, no value
  ck('"צור והפעל" is disabled while the column is unchosen',
     /disabled title="יש להשלים/.test(A.buildHTML()), A.buildHTML().slice(-600));
  A.save();
  ck('...and saving says which half is missing',
     posted===null && toasts.some(t=>t.includes('עמודה')), toasts);
}
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'number','c_budget');
  A.save();
  ck('a chosen column with no value is refused too',
     posted===null && toasts.some(t=>t.includes('הערך')), toasts);
}

const conds0=A=>(A.building||A.scratch).conds[0];

// ── what is sent ──────────────────────────────────────────────────────────
{
  const A=build();
  addCond(A,'column_is'); chooseCol(A,0,'people','c_super');
  A.pickCondValue(EV,0); A.setCondValue(0,0);
  await A.save();
  ck('a column condition travels as its three answers',
     !!posted && JSON.stringify(posted.body.config.conditions)===JSON.stringify(
       [{kind:'column_is',value:{col:'c_super',type:'people',value:4}}]),
     posted&&JSON.stringify(posted.body.config.conditions));
}
{
  const A=build();
  addCond(A,'column_is_not'); chooseCol(A,0,'status','c_stage');
  A.pickCondValue(EV,0); A.setCondValue(0,1);
  addCond(A,'no_assignee');
  await A.save();
  ck('and sits beside a condition of the old kind, in one rule',
     !!posted && JSON.stringify(posted.body.config.conditions)===JSON.stringify(
       [{kind:'column_is_not',value:{col:'c_stage',type:'status',value:'נדחה'}},
        {kind:'no_assignee'}]),
     posted&&JSON.stringify(posted.body.config.conditions));
}


/* ── the operators, the group, and a mirror's any/all ──────────────────────
   What may be asked of a column is the column's own business, and the
   capabilities service is what says so. */
{
  const A=build();
  A.caps={fields:[{type:'number',kind:'number',condition:true,
                   operators:['eq','ne','gt','lt','between','empty','filled']},
                  {type:'text',kind:'text',condition:true,
                   operators:['eq','ne','has','nhas','empty','filled']},
                  {type:'mirror',kind:'text',condition:true,
                   operators:['eq','ne','has','nhas','empty','filled']}],
          operator_labels:{eq:'שווה',ne:'אינו שווה',has:'מכיל',nhas:'אינו מכיל',
                           empty:'ריק',filled:'אינו ריק',gt:'גדול מ',lt:'קטן מ',between:'בטווח'},
          operators_without_value:['empty','filled','yes','no','linked','not_linked'],
          operators_with_two_values:['between'],group_operators:['and','or']};
  addCond(A,'column_is'); chooseCol(A,0,'number','c_budget');
  ck('a column with operators offers them', A.capOps('number').length===7);
  ck('...and one is chosen for it', conds0(A).op==='eq');
  let html=A.condsHTML({bare:true});
  ck('the operator is a blank of its own in the phrase', html.includes('Automations.pickCondOp(event,0)'));
  ck('...reading in words', html.includes('שווה'));

  A.setCondOp2(0,'between');
  html=A.condsHTML({bare:true});
  ck('a range asks for a second value', html.includes('ועד')
     && html.includes('Automations.pickCondValue(event,0,true)'));
  A.setCondOp2(0,'empty');
  html=A.condsHTML({bare:true});
  ck('"ריק" asks for no value at all', !html.includes('Automations.pickCondValue(event,0)'));
  ck('...and clears the one that was there', conds0(A).v===null);
}
{
  const A=build();
  A.caps={fields:[{type:'text',kind:'text',condition:true,operators:['eq','ne']}],
          operator_labels:{eq:'שווה'},
          operators_without_value:[],operators_with_two_values:[],group_operators:['and','or']};
  addCond(A,'column_is'); chooseCol(A,0,'text','c_a');
  let html=A.condsHTML({bare:true});
  ck('one condition is not offered a group operator', !html.includes('Automations.setCondOp('));
  addCond(A,'no_assignee');
  html=A.condsHTML({bare:true});
  ck('two of them are', html.includes(`Automations.setCondOp('or')`));
  ck('...and it starts as AND', A.condGroupOp()==='and' && html.includes('וגם'));
  A.setCondOp('or');
  html=A.condsHTML({bare:true});
  ck('switching the group changes how the rule reads',
     A.condGroupOp()==='or' && html.includes('או') && html.includes('לפחות אחד'));
}
{
  const A=build();
  A.caps={fields:[{type:'mirror',kind:'text',condition:true,operators:['eq','ne']}],
          operator_labels:{eq:'שווה'},
          operators_without_value:[],operators_with_two_values:[],group_operators:['and','or']};
  addCond(A,'column_is'); chooseCol(A,0,'mirror','c_mir');
  let html=A.condsHTML({bare:true});
  ck('a mirror asks how many of the linked items must match',
     html.includes('Automations.toggleCondMatch(0)') && html.includes('לפחות באחד'));
  A.toggleCondMatch(0);
  ck('...and can be asked for all of them',
     A.condsHTML({bare:true}).includes('בכל הפריטים'));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
