/* "שייך את מי שמופיע בעמודת המראה" — the two blanks, on screen.

   A mirror is the one column type a rule READS without being able to listen
   to it or to write it, so it is absent from the list every other column
   blank offers (_blankCols) and has a list of its own. The other blank is the
   people column the names land in, which is the same blank «שייך את X»
   already shows — standing at the board's own אחראים until somebody says
   otherwise, and only on a board that HAS people columns.

   Driven by tests/test_automation_mirror_to_people_column.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabConst(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1)+';';} }
}
function grabTable(decl){
  const i=src.indexOf(decl);
  const open=src.indexOf(decl.includes('[')?'[':'{', i), close=decl.includes('[')?']':'}';
  let d=0;
  for(let j=open;j<src.length;j++){
    if(src[j]===src[open])d++;
    else if(src[j]===close){ d--; if(!d) return src.slice(i,j+1)+';'; }
  }
}

/* the board the rule is written on: a connect column, two mirrors over it,
   two people columns, and one of each of the kinds a mirror must not be
   confused with */
const WITH = [{id:'col_conn',type:'connect',title:'המקור'},
              {id:'col_mir', type:'mirror', title:'אחראי מהמקור'},
              {id:'col_mir2',type:'mirror', title:'סטטוס מהמקור'},
              {id:'col_pm',  type:'people', title:'מנהל פרויקט'},
              {id:'col_rk',  type:'people', title:'רכזת'},
              {id:'col_t',   type:'text',   title:'הערה'}];
let COLS = WITH.slice();
const st={board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{},
                 columns:[],tasks:[]},boards:[]};
let pops=[];

/* the recipe as the server sends it — both readings of the action half,
   because the people column is chosen separately from the mirror */
const MIRROR={id:'link_added_assign_from_mirror', trigger:'link_added',
  action:'assign_from_mirror',
  sentence:'כאשר נוצר קשר לפריט בלוח אחר, שייך לאחראים את האנשים שבעמודת המראה {a_mirror}, {a_write}',
  sentence_parts:{trigger:'כאשר נוצר קשר לפריט בלוח אחר',
                  action:'שייך לאחראים את האנשים שבעמודת המראה {a_mirror}, {a_write}',
                  trigger_col:'',
                  action_col:'שייך ל{a_person_col} את האנשים שבעמודת המראה {a_mirror}, {a_write}',
                  trigger_col_kind:'', action_col_kind:'people'},
  status_fields:[],
  fields:[{key:'a_mirror',type:'mirror',label:'עמודת המראה'},
          {key:'a_write',type:'pick',label:'מה לעשות עם מי שכבר בעמודה'}],
  conditions:[]};

function build(recipe){
  pops=[]; COLS=WITH.slice();
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe','advCell',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    ()=>{}, {ago:()=>'',goto(){}}, ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>[], ()=>[], ()=>COLS.slice(), ()=>[], ()=>false, ()=>1, async()=>({}),
    (anchor,html)=>pops.push(html), ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelector:()=>null, querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}}, t=>t, (t,f)=>null);
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[{user_id:3,name:'רות לוי'}];
  // the picks the server serves, which is where "בנוסף / במקום" comes from
  A.caps={fields:[],operator_labels:{},tokens:[],
          write:{options:['add','replace'], default:'add',
                 labels:{add:'בנוסף למי שכבר שם', replace:'במקום מי שכבר שם'}}};
  A.data={can_manage:true,automations:[],people:[]};
  A.acts=[{key:'assign_from_mirror', label:'שייך את מי שמופיע בעמודת המראה …',
           text:'שייך לאחראים את האנשים שבעמודת המראה {mirror}, {write}',
           text_col:'שייך ל{col} את האנשים שבעמודת המראה {mirror}, {write}',
           fields:[{key:'mirror',type:'mirror',label:'עמודת המראה'},
                   {key:'write',type:'pick',label:'מה לעשות עם מי שכבר בעמודה'}]}];
  A.recipes=[recipe]; A.render=()=>{};
  A.pick(recipe.id);
  return A;
}
const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };
const last=()=>pops[pops.length-1]||'';

// ── the list the mirror blank offers ──────────────────────────────────────
{
  const A=build(MIRROR);
  const got=A._optionsFor('mirror','','a_mirror','');
  ck('every mirror on the board is offered',
     got.map(o=>o.label).join()==='אחראי מהמקור,סטטוס מהמקור', got.map(o=>o.label).join());
  ck('…and nothing that is not one',
     got.every(o=>['col_mir','col_mir2'].includes(o.v)), JSON.stringify(got));
  /* the other half of the same decision: a mirror is read, never listened to
     and never written, so it stays out of the list every other blank uses */
  ck('a mirror is still not somewhere to listen or to write',
     !A._blankCols('t_column').some(c=>c.type==='mirror')
     && !A._blankCols('a_column',true).some(c=>c.type==='mirror'));
}

// ── the sentence shows both blanks, and the people column from the start ──
{
  const A=build(MIRROR);
  const html=A.buildHTML();
  ck('the mirror blank is pressable', html.includes("'a_mirror'"), html.slice(0,500));
  ck('…and so is the people column it writes into',
     html.includes("'a_person_col'"), html.slice(0,500));
  ck('…standing at the board\'s own אחראים until somebody says otherwise',
     html.includes('>אחראים<'), html.slice(0,500));
  ck('the mode is there too', html.includes("'a_write'"), html.slice(0,500));
}
{
  // a board with no mirror has nothing to offer, and says so rather than
  // showing an empty menu with no explanation
  const A=build(MIRROR);
  COLS=[{id:'col_t',type:'text',title:'הערה'},{id:'col_pm',type:'people',title:'מנהל פרויקט'}];
  A.pickField(EV,'a_mirror');
  ck('a board with no mirror is told so', last().includes('אין אפשרויות זמינות'), last());
  COLS=WITH.slice();
}

// ── choosing one ──────────────────────────────────────────────────────────
{
  const A=build(MIRROR);
  A.pickField(EV,'a_mirror');
  ck('pressing the blank lists the mirrors', last().includes('אחראי מהמקור'), last());
  A.setField('a_mirror',0);
  ck('…and the choice is kept', (A.building.values['a_mirror']||{}).v==='col_mir',
     JSON.stringify(A.building.values['a_mirror']));
  ck('…and shown by its title', A.buildHTML().includes('אחראי מהמקור'),
     A.buildHTML().slice(0,500));
}
{
  const A=build(MIRROR);
  A.pickField(EV,'a_person_col');
  ck('the people column is chosen the way it always was',
     last().includes('מנהל פרויקט'), last());
  A.setPeopleSource('a',1);
  ck('…and kept under the key the server reads',
     A._peopleColOf(A.building.values,'a')==='col_pm',
     JSON.stringify(A.building.values['a_person_col']));
}
{
  const A=build(MIRROR);
  A.pickField(EV,'a_write');
  ck('"בנוסף / במקום" comes from the server, not from the screen',
     last().includes('בנוסף למי שכבר שם') && last().includes('במקום מי שכבר שם'), last());
}

// ── the same action added as an EXTRA action ──────────────────────────────
{
  const A=build(MIRROR);
  A.building.acts=[{key:'assign_from_mirror',values:{}}];
  const html=A.moreActsHTML();
  ck('an extra action names its people column too',
     html.includes("'person_col'") && html.includes('>אחראים<'), html.slice(0,600));
  ck('…and its mirror', html.includes("'mirror'"), html.slice(0,600));
  A.pickActValue(EV,0,'mirror');
  ck('…offering the same list', last().includes('אחראי מהמקור'), last());
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
