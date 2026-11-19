/* "כאשר הסטטוס משתנה, עדכן עמודת תאריך להיום" — the builder's half.

   The rule this template stands for could always be built from the general
   "עדכן את העמודה …" — three blanks and a token found in a menu, after which
   the blank showed {{תאריך ההפעלה}}, engine code in the middle of the one
   sentence somebody reads to check what the rule does. So:

     · the template starts filled: «כל ערך שהוא» and «היום»;
     · its column blank offers date columns only;
     · a date column's value is picked from a menu of days — today, tomorrow,
       N days on or back, a fixed day, another date column — never typed as a
       token, and the chip reads it in words;
     · a rule reopened for editing reads its date in the same words.

   Driven by tests/test_automation_status_stamps_a_date_column.py. */
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

const COLS = [{id:'col_d',  type:'date',     title:'תאריך עדכון'},
              {id:'col_d2', type:'date',     title:'תאריך יעד ללקוח'},
              {id:'col_t',  type:'text',     title:'הערה'},
              {id:'col_tl', type:'timeline', title:'ציר זמן'},
              {id:'col_s',  type:'status',   title:'שלב'}];
const st={board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{},
                 columns:[],tasks:[]},boards:[]};
let pops=[];

const STAMP={id:'status_stamp_date', trigger:'status_changes_to', action:'set_column',
  sentence:'כאשר הסטטוס משתנה ל{t_status}, עדכן את העמודה {a_column} ל{a_text}',
  sentence_parts:{trigger:'כאשר הסטטוס משתנה ל{t_status}',
                  action:'עדכן את העמודה {a_column} ל{a_text}',
                  trigger_col:'', action_col:'', trigger_col_kind:'', action_col_kind:''},
  status_fields:[],
  fields:[{key:'t_status',type:'status',label:'סטטוס',default:'*'},
          {key:'a_column',type:'column',label:'עמודת התאריך',col_kinds:['date']},
          {key:'a_text',type:'text',label:'התאריך',default:'{{now.date}}'}],
  conditions:[]};

function build(recipe){
  pops=[];
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe','advCell',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    ()=>{}, {ago:()=>'',goto(){}}, ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>[], ()=>[], ()=>COLS.slice(), ()=>[], ()=>false, ()=>1, async()=>({}),
    (anchor,html)=>pops.push(html), ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelector:()=>null, querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}}, t=>t, (t,f)=>null);
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[];
  A.caps={fields:[],operator_labels:{},any_status:'*',any_status_label:'כל ערך שהוא',
          tokens:[{token:'now.date',label:'תאריך ההפעלה',takes_column:false},
                  {token:'item.name',label:'שם הפריט',takes_column:false}]};
  A.data={can_manage:true,automations:[],people:[]};
  A.acts=[]; A.recipes=[recipe]; A.render=()=>{};
  A.pick(recipe.id);
  return A;
}
const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };
const last=()=>pops[pops.length-1]||'';

// ── the template starts where it is nearly always wanted ──────────────────
{
  const A=build(STAMP);
  const v=A.building.values;
  ck('the status starts on «כל ערך שהוא»',
     (v.t_status||{}).v==='*' && v.t_status.label==='כל ערך שהוא', JSON.stringify(v.t_status));
  ck('…and the date on «היום», not on the token',
     (v.a_text||{}).v==='{{now.date}}' && v.a_text.label==='היום', JSON.stringify(v.a_text));
  ck('the column is left for her to name', !v.a_column, JSON.stringify(v.a_column));
}

// ── the column blank offers date columns, and only those ─────────────────
{
  const A=build(STAMP);
  const got=A._blankCols('a_column').map(c=>c.id).join();
  ck('only plain date columns are offered', got==='col_d,col_d2', got);
}

// ── a date column's value is picked from a menu of days ──────────────────
{
  const A=build(STAMP);
  A.building.values.a_column={v:'col_d',label:'תאריך עדכון',color:''};
  A.pickField(EV,'a_text');
  const m=last();
  ck('pressing the value opens the date menu', m.includes('התאריך שייכתב לעמודה'), m.slice(0,300));
  ck('…offering today and tomorrow', m.includes('היום') && m.includes('מחר'));
  ck('…N days on or back', m.includes('au-date-n') && m.includes('לפני'));
  ck('…a fixed day', m.includes('type="date"'));
  ck('…and the item\'s other date columns', m.includes('תאריך יעד ללקוח'));
  ck('…but no text box to type a token into', !m.includes('id="au-txt"'));
  A.setFieldDate('{{now.date+7}}','בעוד 7 ימים');
  ck('a choice lands in the blank, stored as the token and read in words',
     A.building.values.a_text.v==='{{now.date+7}}' && A.building.values.a_text.label==='בעוד 7 ימים',
     JSON.stringify(A.building.values.a_text));
  ck('…and the sentence shows the words', A.buildHTML().includes('בעוד 7 ימים'));
  ck('…and not the token', !A.buildHTML().includes('now.date'));
}
{
  // a text column is not a date column: the ordinary box, tokens and all
  const A=build(STAMP);
  A.building.values.a_column={v:'col_t',label:'הערה',color:''};
  A.pickField(EV,'a_text');
  ck('a text column keeps the ordinary box', last().includes('id="au-txt"'), last().slice(0,300));
}

// ── a typed value is saved by a button, not by one more menu row ─────────
{
  const A=build(STAMP);
  A.pickField(EV,'a_text');
  const m=last();
  ck('with no column yet, the box says to choose the column first',
     m.includes('כדאי לבחור קודם את העמודה'), m.slice(0,300));
  ck('…and is saved with a real button beside it',
     m.includes('btn btn-primary au-txt-ok') && m.includes('>שמירה</button>'), m.slice(0,600));
  ck('…not with a "✓ אישור" drawn as a menu option', !m.includes('אישור</button>'));
  A.building.values.a_column={v:'col_t',label:'הערה',color:''};
  A.pickField(EV,'a_text');
  ck('once a column is named the note is gone', !last().includes('כדאי לבחור קודם'));
}

// ── the words ─────────────────────────────────────────────────────────────
{
  const A=build(STAMP);
  const cases=[['{{now.date}}','היום'],['{{תאריך ההפעלה}}','היום'],['{{now.date+1}}','מחר'],
               ['{{now.date-1}}','אתמול'],['{{now.date+14}}','בעוד 14 ימים'],
               ['{{now.date-3}}','לפני 3 ימים'],['עודכן {{now.date}}',''],['19/11/2026','']];
  for(const [v,want] of cases)
    ck(`${v} reads as «${want||'itself'}»`, A._dateLabel(v)===want, A._dateLabel(v));
  ck('a day counted from today is not an unknown token',
     A.unknownTokens('{{now.date+30}}').length===0, JSON.stringify(A.unknownTokens('{{now.date+30}}')));
}

// ── a rule reopened for editing reads its date in the same words ─────────
{
  const A=build(STAMP);
  const f={key:'a_text',type:'text',label:'התאריך'};
  ck('into a date column: «היום»',
     A._cellFor(f,'{{now.date}}',{a_column:'col_d'},{}).label==='היום');
  ck('into a text column the token keeps its name — it writes a date, not the word',
     A._cellFor(f,'{{now.date}}',{a_column:'col_t'},{}).label==='{{תאריך ההפעלה}}',
     A._cellFor(f,'{{now.date}}',{a_column:'col_t'},{}).label);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
