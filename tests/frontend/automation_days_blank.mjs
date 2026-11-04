/* "כל כמה ימים" — the blank behind the number, and what it says to the person
   filling it in.

   It was a bare number box carrying the blank's own label as a placeholder:
   text that repeated what the sentence behind it already said and vanished
   the moment anybody typed. Removing it leaves three things that are actually
   worth having, and this pins all three:

     · the floor is the FIELD's, not zero. "כל 0 ימים" is not a schedule, and
       the server quietly rounded it up to one — a value somebody chose being
       silently replaced is worse than one being refused, because nothing on
       screen says it happened.
     · a number alone does not say what it means. "7" in a popup is seven of
       something; the line under the box reads "כל 7 ימים", which is the
       sentence the rule will run under.
     · almost every answer is one of four. Typing is for the fifth.

   Hebrew has a word for two of something, so "2 ימים" is not a thing anybody
   says and the echo does not print it.

   Driven by tests/test_automation_days_blank.py. */
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

const st={board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{},
                 columns:[],tasks:[]},boards:[]};
let pops=[], box=null, echo=null, toasts=[];

function build(){
  pops=[]; toasts=[];
  box={value:'',focus(){},select(){}};
  echo={textContent:''};
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe','advCell',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    m=>toasts.push(m), {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>[], ()=>[], ()=>[], ()=>[], ()=>false, ()=>1, async()=>({}),
    (anchor,html)=>pops.push(html), ()=>{}, ()=>{},
    ()=>{}, ()=>{},
    {getElementById:id=>(id==='au-txt'?box:(id==='au-days-echo'?echo:null)),
     querySelector:()=>null, querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}},
    t=>t, (t,f)=>null);
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[];
  A.caps={fields:[],operator_labels:{},tokens:[]};
  A.data={can_manage:true,automations:[],people:[]};
  A.acts=[]; A.recipes=[RECIPE]; A.render=()=>{};
  A.pick(RECIPE.id);
  return A;
}
const RECIPE={id:'every_days_notify_assignees', trigger:'every_n_days',
  action:'notify_assignees',
  sentence:'כל {t_days} ימים, שלח {a_notice} למשויכים לפריט',
  fields:[{key:'t_days',type:'days',label:'כל כמה ימים',min:1},
          {key:'a_notice',type:'notice',label:'התראה'}],
  conditions:[]};
const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };
const last=()=>pops[pops.length-1]||'';

// ── the placeholder is gone ───────────────────────────────────────────────
{
  const A=build();
  await A.pickField(EV,'t_days');
  ck('the blank opens a picker', last().includes('au-days'), last().slice(0,120));
  ck('…with no placeholder in the box', !/placeholder=/.test(last()), last());
  /* …and with the question asked once, above the box. Taking the placeholder
     out of a bare number field would otherwise leave nothing on screen
     saying what the number is for. */
  ck('…and the blank still says what it is asking',
     last().includes('כל כמה ימים'), last());
  ck('…and the box is still labelled for a screen reader',
     /aria-label="כל כמה ימים"/.test(last()), last());
}

// ── the four answers that cover almost every rule ─────────────────────────
{
  const A=build();
  await A.pickField(EV,'t_days');
  for(const phrase of ['כל יום','כל 7 ימים','כל 14 ימים','כל 30 ימים'])
    ck('a quick answer is offered: '+phrase, last().includes('>'+phrase+'<'), last());
  ck('…and they carry the phrase, not a bare number',
     !/>7</.test(last()), last());
}
{
  // pressing one fills the blank and closes, with no second step
  const A=build();
  await A.pickField(EV,'t_days');
  A.setDays('t_days',7);
  ck('pressing one answers the blank', (A.building.values['t_days']||{}).v===7,
     JSON.stringify(A.building.values['t_days']));
}
{
  // the one already chosen is marked, so reopening shows where you are
  const A=build();
  A.setDays('t_days',14);
  await A.pickField(EV,'t_days');
  ck('reopening marks the answer already given',
     /class="au-day-chip on"[^>]*onclick="Automations.setDays\('t_days',14\)"/.test(last())
     || /setDays\('t_days',14\)[^>]*>כל 14 ימים/.test(last().replace(/\n/g,'')),
     last());
}

// ── the floor is the field's, and it is refused rather than rounded ──────
{
  const A=build();
  await A.pickField(EV,'t_days');
  box.value='0';
  A.setDays('t_days');
  ck('"כל 0 ימים" is not a schedule, and is refused',
     A.building.values['t_days']===undefined, JSON.stringify(A.building.values['t_days']));
  ck('…and the reason is said, not swallowed',
     toasts.some(t=>/יום אחד לפחות/.test(t)), JSON.stringify(toasts));
  ck('…and the box itself will not offer below the floor',
     /min="1"/.test(last()), last());
}
{
  // the same blank on a "days before" rule has no such floor: nought days
  // before the due date is the due date, which is a real answer
  const A=build();
  A.recipes=[Object.assign({},RECIPE,{id:'due', sentence:'{t_days}',
    fields:[{key:'t_days',type:'days',label:'ימים לפני'}]})];
  A.pick('due');
  await A.pickField(EV,'t_days');
  ck('a blank with no floor offers nought', /min="0"/.test(last()), last());
  A.setDays('t_days',0);
  ck('…and takes it', (A.building.values['t_days']||{}).v===0,
     JSON.stringify(A.building.values['t_days']));
}

// ── what the number means, in words ───────────────────────────────────────
{
  const A=build();
  const every={label:'כל כמה ימים',min:1}, before={label:'ימים לפני'}, after={label:'ימים אחרי'};
  const cases=[[every,1,'כל יום'],[every,2,'כל יומיים'],[every,7,'כל 7 ימים'],
               [before,1,'יום לפני'],[before,2,'יומיים לפני'],[before,7,'7 ימים לפני'],
               [after,3,'3 ימים אחרי'],
               // nought before or after the due date IS the due date, and
               // saying so plainly beats "0 ימים לפני", which reads like a
               // rule that is switched off
               [before,0,'באותו יום'],[after,0,'באותו יום']];
  for(const [f,n,want] of cases)
    ck(`"${want}"`, A.daysEcho(f,n)===want, A.daysEcho(f,n));
  ck('two of something has its own word', A.daysHe(2)==='יומיים', A.daysHe(2));
  ck('…and one does too', A.daysHe(1)==='יום', A.daysHe(1));
}
{
  // the line under the box follows the typing — it is the only thing in the
  // popup that says what the number means
  const A=build();
  await A.pickField(EV,'t_days');
  box.value='14'; A.echoDays();
  ck('the echo follows what is typed', echo.textContent==='כל 14 ימים', echo.textContent);
  box.value=''; A.echoDays();
  ck('…and says nothing when there is nothing', echo.textContent==='', echo.textContent);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
