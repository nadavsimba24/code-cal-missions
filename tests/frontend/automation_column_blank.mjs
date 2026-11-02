/* Which column — asked the same way wherever a rule names one.

   A rule points at a column in three places: a condition ("רק אם «תחום» הוא
   …"), a blank in its own sentence ("כאשר הערך ב«תחום» משתנה"), and a blank
   in an extra action ("עדכן את «תחום» ל…"). The condition asked two
   questions — what KIND of column, and then which one — and the other two
   handed over every column on the board at once. On a board carrying thirty
   columns that second list is not a question anybody wants to read, and a
   person met whichever version the rule they happened to be writing used.

   One picker now, so the two cannot drift apart. What is pinned here is the
   picker's own behaviour and the thing it is easy to get wrong when sharing
   it: WHICH columns each caller is allowed to offer. Listening to a column
   and writing to one are not the same list — מזהה פריט, מועד יצירה and יוצר
   הרשומה are derived from the item and store nothing, so a rule pointed at
   one would write a cell the board never reads. An extra action's field is
   keyed plainly "column" with no a_ prefix, which is exactly how those three
   used to be offered there as somewhere to write to.

   Driven by tests/test_automation_column_blank.py. */
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
function grabFn(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
  throw new Error('unbalanced: '+name);
}

/* A board with two columns of one kind — so "pick the kind" is a real
   narrowing and not a one-item list — and one of each thing the pickers are
   supposed to leave out. */
const COLS=[
  {id:'c_area',  type:'text',       title:'אזור'},
  {id:'c_field', type:'text',       title:'תחום'},
  {id:'c_stage', type:'status',     title:'שלב', options:[{id:'o1',label:'הוגש',color:'#00c875'}]},
  {id:'c_due',   type:'date',       title:'תאריך יעד'},
  {id:'c_uid',   type:'item_id',    title:'מזהה פריט'},
  {id:'c_made',  type:'created_at', title:'מועד יצירה'},
  {id:'c_by',    type:'created_by', title:'יוצר הרשומה'},
  {id:'c_link',  type:'connect',    title:'לוח מקושר'},
  {id:'c_mir',   type:'mirror',     title:'שם אצלם'},
  {id:'c_calc',  type:'formula',    title:'חישוב'},
];
const st={board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{}},boards:[]};
let pops=[], toasts=[];

function build(recipe){
  pops=[]; toasts=[];
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabFn('colTypeHe')
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
    async()=>({}),
    (anchor,html)=>{ pops.push(html); },
    ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>({value:'',focus(){},select(){}}), querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}});
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[];
  A.data={can_manage:true,automations:[],people:[]};
  A.caps={fields:[],operator_labels:{}};
  // the "פעולה נוספת" catalog as the server sends it — `acts`, which is what
  // pickAct reads
  A.acts=[{key:'set_column', label:'עדכן את … ל…', text:'עדכן את {column} ל{value}',
           fields:[{key:'column',type:'column',label:'עמודה'},
                   {key:'value',type:'text',label:'ערך'}]}];
  A.recipes=[recipe]; A.render=()=>{};
  A.pick(recipe.id);
  return A;
}
const LISTEN={id:'col_changed_notify', trigger:'column_changed', action:'notify',
  sentence:'כאשר הערך ב{t_column} משתנה, שלח התראה',
  fields:[{key:'t_column',type:'column',label:'עמודה'}], conditions:[]};
const WRITE={id:'created_set_column', trigger:'item_created', action:'set_column',
  sentence:'כאשר נוצר פריט חדש, עדכן את {a_column}',
  fields:[{key:'a_column',type:'column',label:'עמודה'}], conditions:[]};

const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

// ── the blank in the rule's own sentence asks the kind first ───────────────
{
  const A=build(LISTEN);
  A.pickField(EV,'t_column');
  const menu=pops[pops.length-1];
  ck('a column blank asks what KIND of column first', menu.includes('colPickType'), menu);
  ck('...and does not hand over the whole board at once',
     !menu.includes('setField('), menu);
  ck('offering only kinds this board has a column of',
     menu.includes('טקסט') && menu.includes('סטטוס') && menu.includes('תאריך'), menu);
  ck('with a count beside each', /<small[^>]*>2<\/small>/.test(menu), menu);
  ck('a formula has no value of its own to listen to', !menu.includes('נוסחה'), menu);
  ck('a mirror and a link are not offered either',
     !menu.includes('שדה מראה') && !menu.includes('קישור בין לוחות'), menu);
}

// ── and then which column of that kind ─────────────────────────────────────
{
  const A=build(LISTEN);
  A.pickField(EV,'t_column');
  A.colPickType(EV,'text');
  const menu=pops[pops.length-1];
  ck('the second question lists that kind only',
     menu.includes('אזור') && menu.includes('תחום'), menu);
  ck('...and not a column of another kind', !menu.includes('שלב'), menu);
  ck('with a way back to the kinds', menu.includes('colPickBack'), menu);
  A.colPickOne(1);
  const v=A.building.values['t_column'];
  ck('picking one fills the blank with the column', v && v.v==='c_field'
     && v.label==='תחום', JSON.stringify(v));
}

// ── the way back really goes back ──────────────────────────────────────────
{
  const A=build(LISTEN);
  A.pickField(EV,'t_column');
  A.colPickType(EV,'text');
  A.colPickBack(EV);
  const menu=pops[pops.length-1];
  ck('"סוג אחר" returns to the kinds', menu.includes('colPickType')
     && !menu.includes('colPickOne'), menu);
}

// ── listening is a wider question than writing ─────────────────────────────
{
  const A=build(LISTEN);
  ck('a rule may listen to מזהה פריט',
     A._blankCols('t_column').some(c=>c.id==='c_uid'));
  ck('...and to מועד יצירה and יוצר הרשומה',
     A._blankCols('t_column').some(c=>c.id==='c_made')
     && A._blankCols('t_column').some(c=>c.id==='c_by'));
  ck('but never to a mirror, a link or a formula',
     !A._blankCols('t_column').some(c=>['mirror','connect','formula'].includes(c.type)),
     A._blankCols('t_column').map(c=>c.type).join(','));
}
{
  const A=build(WRITE);
  const ids=A._blankCols('a_column').map(c=>c.id);
  ck('a rule may not WRITE to the three the system issues',
     !ids.includes('c_uid') && !ids.includes('c_made') && !ids.includes('c_by'), ids.join(','));
  A.pickField(EV,'a_column');
  const menu=pops[pops.length-1];
  ck('so the write blank never offers them as a kind',
     !menu.includes('מזהה פריט') && !menu.includes('מועד יצירה')
     && !menu.includes('יוצר הרשומה'), menu);
}

// ── an extra action writes too, and its field is keyed plainly "column" ────
{
  const A=build(LISTEN);
  // added the way the screen does: open the "פעולה נוספת" menu, then pick
  A.pickAct(EV);
  A.addAct((A._actOffer||[]).findIndex(x=>x.key==='set_column'));
  const a=(A.building.acts||[])[0];
  ck('the extra action was added', !!a, JSON.stringify(A.building.acts));
  if(a){
    A.pickActValue(EV,0,'column');
    const menu=pops[pops.length-1];
    ck('an extra action asks the kind first as well', menu.includes('colPickType'), menu);
    ck('and does not offer the three the system issues — the key has no a_ prefix,'
       +' which is how it used to', !menu.includes('מזהה פריט')
       && !menu.includes('מועד יצירה') && !menu.includes('יוצר הרשומה'), menu);
    A.colPickType(EV,'status');
    A.colPickOne(0);
    const v=((A.building.acts[0]||{}).values||{}).column;
    ck('and picking one fills the action’s blank', v && v.v==='c_stage'
       && v.label==='שלב', JSON.stringify(v));
  }
}

// ── a board with nothing to offer says so ──────────────────────────────────
{
  const A=build(LISTEN);
  A.colPickOpen({}, [], ()=>{}, 'אין בלוח עמודות מתאימות');
  const menu=pops[pops.length-1];
  ck('an empty list is a sentence, not an empty menu',
     menu.includes('אין בלוח עמודות מתאימות'), menu);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
