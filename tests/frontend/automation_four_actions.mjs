/* The "ואז גם" block in the automation builder — up to four actions in one rule.

   A recipe pairs one trigger with ONE action, so four things that had to happen
   on one event were four rules listening to the same trigger. The builder now
   carries the rest of the "then": the sentence's own action is the first, and up
   to maxActs-1 more are listed under it, two to a row, each as its own phrase
   with its blanks as chips — the same chips, pickers and wording the conditions
   block uses, because they are the same kind of thing.

   Runs the real Automations object out of index.html. Driven by
   tests/test_automation_four_actions.py. */
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

/* The catalog the server sends (automations.actions_catalog): `text` carries
   the blanks so each one becomes a chip, `label` is the same line with "…" for
   the picker that offers it. */
const CATALOG=[
  {key:'notify_person',   label:'שלח התראה ל…',           text:'שלח התראה ל{person}',
   fields:[{key:'person',type:'person',label:'נמען'}]},
  {key:'notify_assignees',label:'שלח התראה למשויכים לפריט',text:'שלח התראה למשויכים לפריט',fields:[]},
  {key:'assign_person',   label:'שייך את …',               text:'שייך את {person}',
   fields:[{key:'person',type:'person',label:'אחראי'}]},
  {key:'set_status',      label:'שנה את הסטטוס ל…',        text:'שנה את הסטטוס ל{status}',
   fields:[{key:'status',type:'status',label:'סטטוס'}]},
  {key:'set_priority',    label:'שנה את העדיפות ל…',       text:'שנה את העדיפות ל{priority}',
   fields:[{key:'priority',type:'priority',label:'עדיפות'}]},
  {key:'move_to_group',   label:'העבר את הפריט לקבוצה …',  text:'העבר את הפריט לקבוצה {group}',
   fields:[{key:'group',type:'group',label:'קבוצה'}]},
  {key:'create_subitem',  label:'צור תת־פריט בשם …',       text:'צור תת־פריט בשם {text}',
   fields:[{key:'text',type:'text',label:'שם תת־הפריט'}]},
];

const GROUPS=[{id:7,name:'בעבודה',color:'#0073ea'},{id:8,name:'הושלם',color:'#00c875'}];
const MEMBERS=[{user_id:4,name:'יואב'},{user_id:5,name:'דנה'}];
const st={board:{id:1,name:'לוח תשתיות',groups:GROUPS,my_role:'admin'},boards:[]};

let posted=null, toasts=[], popHTML='', textValue='';
const stored={};

function build(){
  posted=null; toasts=[]; popHTML='';
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','avatarInner',
    'boardStatusList','boardPriorityList','customColumns','meId','api','openCellPop',
    'closeCellPops','askConfirm','showModal','closeModals','document','renderView','localStorage',
    grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x), m=>toasts.push(m), {ago:()=>'',goto(){}},
    ()=>'', ()=>'', ()=>'',
    ()=>[{key:'done',he:'בוצע',c:'#00c875'},{key:'in_progress',he:'בתהליך',c:'#fdab3d'}],
    ()=>[{key:'high',he:'גבוהה',c:'#e2445c'},{key:'low',he:'נמוכה',c:'#579bfc'}],
    ()=>[], ()=>1,
    async(url,opt)=>{ if(opt&&opt.method==='POST'){ posted={url,body:JSON.parse(opt.body)}; return {}; } return {}; },
    (anchor,html)=>{ popHTML=html; }, ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>({value:textValue,focus(){},select(){}}), querySelectorAll:()=>[]},
    ()=>{}, {getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=String(v);}});
  A.acts=CATALOG.map(x=>({...x})); A.maxActs=4;
  A.conds=[]; A.maxConds=3; A.members=MEMBERS.slice();
  A.data={can_manage:true,automations:[],people:[]};
  A.recipes=[{id:'created_set_priority',trigger:'item_created',action:'set_priority',
              sentence:'כאשר נוצר פריט חדש, שנה את העדיפות ל{a_priority}',
              fields:[{key:'a_priority',type:'priority',label:'עדיפות'}],conditions:[]}];
  A.render=()=>{};
  A.pick('created_set_priority');
  A.building.values['a_priority']={v:'high',label:'גבוהה',color:'#e2445c'};
  return A;
}

/* Add one action the way the UI does: open the menu, then choose from it. The
   offer list is the real one, so what cannot be added is not addable here
   either. */
function add(A,key){
  A.pickAct({preventDefault(){},stopPropagation(){},currentTarget:{}});
  const i=(A._actOffer||[]).findIndex(x=>x.key===key);
  if(i<0) return false;
  A.addAct(i);
  return true;
}

function setVal(A,i,fkey,optIdx){
  A.pickActValue({preventDefault(){},stopPropagation(){},currentTarget:{}}, i, fkey);
  A.setActValue(i,fkey,optIdx);
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,240):''))); };

// ── the block, before anything is added ────────────────────────────────────
{
  const A=build();
  const h=A.moreActsHTML();
  ck('a rule with one action says so rather than showing an empty frame',
     h.includes('אין פעולות נוספות'), h);
  ck('...and offers to add one', h.includes('Automations.pickAct(event)'), h);
  ck('the heading says how many a rule may carry', h.includes('עד 4 פעולות'), h);
}

// ── adding, numbering, and the two-to-a-row layout ─────────────────────────
{
  const A=build();
  ck('an action can be added', add(A,'set_status'));
  setVal(A,0,'status',0);
  ck('...and is stored as the action and its own values',
     A.building.acts.length===1 && A.building.acts[0].key==='set_status'
     && A.building.acts[0].values.status.v==='done', JSON.stringify(A.building.acts));
  const h=A.moreActsHTML();
  ck('it is numbered 2 — the sentence\'s own action is 1',
     h.includes('<span class="au-act-n">2</span>'), h);
  ck('the value is a chip in the value\'s own colour, as the sentence shows it',
     h.includes('au-blank filled') && h.includes('#00c875'), h);
  ck('two to a row', h.includes('au-acts-grid'), h);
  ck('and it can be removed again', h.includes('Automations.dropAct(0)'), h);
  A.dropAct(0);
  ck('removing it leaves the rule with its sentence alone', A.building.acts.length===0);
}

// ── the ceiling ────────────────────────────────────────────────────────────
{
  const A=build();
  add(A,'set_status');      setVal(A,0,'status',0);
  add(A,'notify_person');   setVal(A,1,'person',1);
  add(A,'move_to_group');   setVal(A,2,'group',0);
  ck('three extras fill the rule to four actions', A.building.acts.length===3);
  const h=A.moreActsHTML();
  ck('...and the fourth is not offered', !h.includes('Automations.pickAct(event)'), h);
  ck('...which it says, instead of a button that does nothing',
     h.includes('מספר הפעולות המקסימלי (4)'), h);
  ck('every one of them is numbered in the order it runs',
     ['2','3','4'].every(n=>h.includes('<span class="au-act-n">'+n+'</span>')), h);
}

// ── what may not be added ──────────────────────────────────────────────────
{
  const A=build();
  A.pickAct({preventDefault(){},stopPropagation(){},currentTarget:{}});
  const offered=(A._actOffer||[]).map(x=>x.key);
  ck('the action the sentence already performs is not offered a second time',
     !offered.includes('set_priority'), offered);
  ck('...while everything else is', offered.includes('set_status')
     && offered.includes('notify_person'), offered);
}
{
  const A=build();
  add(A,'set_status'); setVal(A,0,'status',0);
  A.pickAct({preventDefault(){},stopPropagation(){},currentTarget:{}});
  const offered=(A._actOffer||[]).map(x=>x.key);
  ck('an action that writes a field the rule already writes is not offered twice',
     !offered.includes('set_status'), offered);
  ck('...but two notifications to two people are allowed',
     offered.includes('notify_person'), offered);
}

// ── an unfinished action is an unfinished rule ─────────────────────────────
{
  const A=build();
  add(A,'notify_person');                       // the recipient is still blank
  const b=A.buildHTML();
  ck('"צור והפעל" is disabled while an added action has a blank',
     /disabled title="יש להשלים/.test(b), b.slice(-700));
  A.save();
  ck('...and saving says what is missing instead of sending it',
     posted===null && toasts.some(t=>t.includes('פעולות הנוספות')), toasts);
}

// ── what is sent ───────────────────────────────────────────────────────────
{
  const A=build();
  add(A,'set_status');    setVal(A,0,'status',1);
  add(A,'assign_person'); setVal(A,1,'person',0);
  await A.save();
  ck('the extra actions travel in the rule\'s own config, beside the conditions',
     !!posted && Array.isArray(posted.body.config.actions), posted&&posted.body);
  ck('...each as its action and its values',
     JSON.stringify((posted&&posted.body.config.actions)||null)===JSON.stringify(
       [{key:'set_status',values:{status:'in_progress'}},
        {key:'assign_person',values:{person:4}}]),
     posted&&JSON.stringify(posted.body.config.actions));
  const sent=((posted&&posted.body.config.actions)||[])[1]||{values:{}};
  ck('a person is sent as a number, as everywhere else',
     typeof sent.values.person==='number', JSON.stringify(sent));
  ck('and the rule itself is unchanged by any of it',
     posted.body.recipe_id==='created_set_priority'
     && posted.body.config.a_priority==='high', posted.body.config);
}

// ── a draft may be left half-built ─────────────────────────────────────────
{
  const A=build();
  add(A,'notify_person');                       // no recipient
  await A.save(true);
  ck('a draft keeps the action and leaves the blank blank',
     !!posted && posted.body.status==='draft'
     && JSON.stringify(posted.body.config.actions)==='[{"key":"notify_person","values":{}}]',
     posted&&JSON.stringify(posted.body.config));
}

// ── a text blank is typed, not picked ──────────────────────────────────────
{
  const A=build();
  add(A,'create_subitem');
  textValue='בדיקת מעבדה';
  A.pickActValue({preventDefault(){},stopPropagation(){},currentTarget:{}},0,'text');
  ck('a text field opens a box to type in', popHTML.includes('au-txt'), popHTML);
  A.setActText(0,'text');
  ck('...and the typed value becomes the chip',
     A.building.acts[0].values.text.label==='בדיקת מעבדה', A.building.acts[0].values);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
