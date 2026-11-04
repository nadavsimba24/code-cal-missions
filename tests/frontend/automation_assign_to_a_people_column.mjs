/* "שייך את X ל«מנהל פרויקט»" — the column before the value, on screen.

   The status blank asks "which status?" by being PRESSED: there is a blank
   in the sentence to press. "כאשר משויך אדם לפריט" has no blank at all, so
   a people half shows its column reading from the start, standing at the
   board's own אחראים until somebody says otherwise — and only on a board
   that HAS people columns, where the choice is a real one.

   Driven by tests/test_automation_assign_to_a_people_column.py. */
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

const WITH = [{id:'col_pm',type:'people',title:'מנהל פרויקט'},
              {id:'col_rk',type:'people',title:'רכזת'},
              {id:'col_t', type:'text',  title:'הערה'}];
let COLS = WITH.slice();
const st={board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{},
                 columns:[],tasks:[]},boards:[]};
let pops=[];

/* the recipe as the server now sends it: both readings of each half, and
   which KIND of column each half offers */
const ASSIGN={id:'created_assign_person', trigger:'item_created', action:'assign_person',
  sentence:'כאשר נוצר פריט חדש, שייך את {a_person}',
  sentence_parts:{trigger:'כאשר נוצר פריט חדש', action:'שייך את {a_person}',
                  trigger_col:'', action_col:'שייך את {a_person} ל{a_person_col}',
                  trigger_col_kind:'', action_col_kind:'people'},
  status_fields:[], fields:[{key:'a_person',type:'person',label:'אחראי'}],
  conditions:[]};
const ONSTATUS={id:'status_notify_person', trigger:'status_changes_to', action:'notify_person',
  sentence:'כאשר הסטטוס משתנה ל{t_status}, שלח {a_notice} ל{a_person}',
  sentence_parts:{trigger:'כאשר הסטטוס משתנה ל{t_status}',
                  action:'שלח {a_notice} ל{a_person}',
                  trigger_col:'כאשר {t_status_col} משתנה ל{t_status}', action_col:'',
                  trigger_col_kind:'status', action_col_kind:''},
  status_fields:['t_status'],
  fields:[{key:'t_status',type:'status',label:'סטטוס'},
          {key:'a_person',type:'recipient',label:'נמען'},
          {key:'a_notice',type:'notice',label:'התראה'}],
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
  A.caps={fields:[],operator_labels:{},tokens:[]};
  A.data={can_manage:true,automations:[],people:[]};
  A.acts=[{key:'assign_person', label:'שייך את …', text:'שייך את {person}',
           text_col:'שייך את {person} ל{col}',
           fields:[{key:'person',type:'person',label:'אחראי'}]}];
  A.recipes=[recipe]; A.render=()=>{};
  A.pick(recipe.id);
  return A;
}
const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };
const last=()=>pops[pops.length-1]||'';

// ── the lists the picker offers ───────────────────────────────────────────
{
  const A=build(ASSIGN);
  ck('the board\'s people columns are found',
     A._peopleCols().map(c=>c.title).join()==='מנהל פרויקט,רכזת',
     A._peopleCols().map(c=>c.title).join());
  const srcs=A._peopleSources();
  ck('…offered under the board\'s own אחראים', srcs[0].label==='אחראים'&&srcs[0].v==='',
     JSON.stringify(srcs[0]));
  ck('…with every column after it', srcs.map(s=>s.label).join()==='אחראים,מנהל פרויקט,רכזת',
     srcs.map(s=>s.label).join());
  ck('and the half knows which list it wants',
     A._colKind('a')==='people' && A._colKind('t')==='', A._colKind('a')+'/'+A._colKind('t'));
}

// ── the blank is there from the start, standing at אחראים ────────────────
{
  const A=build(ASSIGN);
  const html=A.buildHTML();
  ck('the sentence names where the person goes', /ל<button[^>]*>אחראים</.test(html)
     || html.includes('>אחראים<'), html.slice(0,400));
  ck('…and the blank is pressable', html.includes("'a_person_col'"), html.slice(0,400));
}
{
  // a board with no people columns is not offered a choice that does not exist
  const A=build(ASSIGN);
  COLS=[{id:'col_t',type:'text',title:'הערה'}];
  const html=A.buildHTML();
  ck('a board with no people columns is not asked',
     !html.includes("'a_person_col'"), html.slice(0,300));
  COLS=WITH.slice();
}

// ── choosing one ──────────────────────────────────────────────────────────
{
  const A=build(ASSIGN);
  A.pickField(EV,'a_person_col');
  ck('pressing it asks which column', last().includes('באיזו עמודת אנשים מדובר?'), last());
  ck('…offering the built-in first', last().indexOf('אחראים')<last().indexOf('מנהל פרויקט'), last());
  A.setPeopleSource('a',1);
  ck('…and the choice is kept', A._peopleColOf(A.building.values,'a')==='col_pm',
     JSON.stringify(A.building.values['a_person_col']));
  const html=A.buildHTML();
  ck('…and shown by its title', html.includes('מנהל פרויקט'), html.slice(0,400));
}
{
  /* The board's own אחראים is RECORDED as a choice rather than left absent:
     the two are the same thing to the engine and to save(), which sends
     neither, but on screen an absence reads as a question nobody answered. */
  const A=build(ASSIGN);
  A.pickField(EV,'a_person_col');
  A.setPeopleSource('a',0);
  ck('the built-in is recorded as an answer, not as an absence',
     A.building.values['a_person_col'] !== undefined
     && A._peopleColOf(A.building.values,'a')==='',
     JSON.stringify(A.building.values['a_person_col']));
}

// ── the status half is untouched by any of this ──────────────────────────
{
  const A=build(ONSTATUS);
  ck('a status half still offers status columns', A._colKind('t')==='status');
  ck('…and is not shown until it is pressed', !(A.buildHTML())
     .includes("'t_person_col'"));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
