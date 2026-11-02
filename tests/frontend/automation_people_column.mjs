/* A rule about "רכזת" is offered the people who are in רכזת.

   A board here carries several people columns — אחראי, מנהל פרויקט, רכזת —
   and a rule about any of them was offered every member of the board. The
   member list is not wrong, it is just not the answer: the question is who
   is IN that column, and on a board with forty members the one name that
   matters sits somewhere in the middle of the other thirty-nine.

   Two sections, not one filtered list. Nine rules out of ten are about
   somebody already in the column; the tenth is written ahead of the first
   time anyone is put there, and a rule is forward-looking. Cutting the menu
   down to the current occupants would make that tenth rule impossible to
   write at all, which is a worse failure than a long menu.

   The other half is the action. "עדכן את «רכזת» ל…" asked for a column and
   then for "הערך החדש" as a text box, whatever the column was — so writing
   a people column meant typing somebody's name exactly right, and a typo
   was a rule that silently did nothing: the server refuses a name it cannot
   match to a board member and says so only in the run history, which is not
   where anybody looks for a rule that never seemed to run.

   Driven by tests/test_automation_people_column.py. */
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

/* Three people columns, which is the whole point: a rule about one of them
   must not be answered with the other two's people. */
const COLS=[
  {id:'c_owner', type:'people', title:'אחראי'},
  {id:'c_pm',    type:'people', title:'מנהל פרויקט'},
  {id:'c_coord', type:'people', title:'רכזת'},
  {id:'c_stage', type:'status', title:'שלב', options:[{id:'o1',label:'הוגש',color:'#00c875'}]},
];
const MEMBERS=[{user_id:3,name:'דנה'},{user_id:4,name:'יואב'},
               {user_id:5,name:'רינה'},{user_id:6,name:'אבי'}];
/* רכזת holds רינה twice and דנה once. יואב is in another people column, and
   אבי is on the board and in none of them — both must still be reachable. */
const TASKS=[
  {id:1, custom_fields:{c_coord:[5], c_owner:[4]}},
  {id:2, custom_fields:{c_coord:[5]}},
  {id:3, custom_fields:{c_coord:[3], c_pm:[4]}},
  {id:4, custom_fields:{}},
];
const st={board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{},
                 columns:COLS.slice(),tasks:TASKS},boards:[]};
let pops=[];

function build(recipe){
  pops=[];
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe','advCell',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x), ()=>{}, {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    u=>`<i>${(u&&u.name)||''}</i>`, ()=>[], ()=>[],
    ()=>COLS.slice(),
    col=>{ const c=(col&&typeof col==='object')?col:COLS.find(x=>x.id===col);
           return ((c&&c.options)||[]).map(o=>typeof o==='string'
             ?{id:null,label:o,color:'#c4c4c4'}
             :{id:o.id||null,label:o.label,color:o.color||'#c4c4c4'}); },
    ()=>false, ()=>1, async()=>({}),
    (anchor,html)=>{ pops.push(html); },
    ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>({value:'',focus(){},select(){}}), querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}},
    t=>t,
    // advCell for a custom column is the cell itself — the one definition the
    // board filter reads values through
    (t,f)=>((t.custom_fields||{})[f.id]));
  A.conds=[{kind:'column_is', label:'העמודה … היא …', type:'column', value_label:'ערך'}];
  A.maxConds=3; A.maxActs=4; A.members=MEMBERS.slice();
  A.caps={fields:[],operator_labels:{}};
  A.data={can_manage:true,automations:[],people:[]};
  A.acts=[{key:'set_column', label:'עדכן את … ל…', text:'עדכן את {column} ל{text}',
           fields:[{key:'column',type:'column',label:'עמודה'},
                   {key:'text',type:'text',label:'הערך החדש'}]}];
  A.recipes=[recipe]; A.render=()=>{};
  A.pick(recipe.id);
  return A;
}
const COND={id:'created_set_priority', trigger:'item_created', action:'set_priority',
  sentence:'כאשר נוצר פריט חדש, שנה את העדיפות ל{a_priority}',
  fields:[{key:'a_priority',type:'priority',label:'עדיפות'}], conditions:[]};
const SETCOL={id:'created_set_column', trigger:'item_created', action:'set_column',
  sentence:'כאשר נוצר פריט חדש, עדכן את {a_column} ל{a_text}',
  fields:[{key:'a_column',type:'column',label:'עמודה'},
          {key:'a_text',type:'text',label:'הערך החדש'}], conditions:[]};

const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,340):''))); };
const last=()=>pops[pops.length-1];
const addCond=(A,kind)=>{ A.pickCond(EV); A.addCond((A._condOffer||[]).findIndex(x=>x.kind===kind)); };
const chooseCol=(A,i,type,colId)=>{
  A.pickCondCol(EV,i); A.colPickType(EV,type);
  A.colPickOne(((A._colPick||{}).offer||[]).findIndex(c=>c.id===colId));
  // on screen setCondCol clicks the next blank for you; the harness has no
  // DOM for that timeout to find, so the value question is asked here
  A.pickCondValue(EV,i);
};

// ── the kind, then the column: three people columns, all offered ──────────
{
  const A=build(COND);
  addCond(A,'column_is');
  A.pickCondCol(EV,0);
  ck('אנשים is offered as a kind', last().includes('אנשים'), last());
  ck('…and says the board has three of them', /<small[^>]*>3<\/small>/.test(last()), last());
  A.colPickType(EV,'people');
  ['אחראי','מנהל פרויקט','רכזת'].forEach(t=>
    ck('the specific column is offered: '+t, last().includes(t), last()));
  ck('and not a column of another kind', !last().includes('שלב'), last());
}

// ── then the values, from that column ─────────────────────────────────────
{
  const A=build(COND);
  addCond(A,'column_is'); chooseCol(A,0,'people','c_coord');
  const menu=last();
  ck('the menu is headed by the column it is about', menu.includes('רכזת'), menu);
  ck('the people IN רכזת come first',
     menu.indexOf('רינה')<menu.indexOf('אבי')&&menu.indexOf('דנה')<menu.indexOf('אבי'), menu);
  ck('…most-carried first', menu.indexOf('רינה')<menu.indexOf('דנה'), menu);
  ck('…with how many items carry each', /<small[^>]*>2<\/small>/.test(menu), menu);
  ck('the rest of the board is under a line, not missing',
     menu.includes('שאר חברי הלוח')&&menu.includes('אבי')&&menu.includes('יואב'), menu);
  ck('a rule can still be written about somebody not in the column yet',
     (A._popItems||[]).some(x=>x.label==='אבי'), (A._popItems||[]).map(x=>x.label));
  // the order the menu shows is the order the handler indexes
  const j=(A._popItems||[]).findIndex(x=>x.label==='רינה');
  A.setCondValue(0,j);
  const c=A.building.conds[0];
  ck('picking one answers the condition', c.v===5&&c.label==='רינה', JSON.stringify(c));
}

// ── a different people column, a different list ───────────────────────────
{
  const A=build(COND);
  addCond(A,'column_is'); chooseCol(A,0,'people','c_owner');
  const menu=last();
  ck('אחראי is answered with אחראי’s person', menu.indexOf('יואב')<menu.indexOf('שאר חברי הלוח'), menu);
  ck('…and רינה, who is only in רכזת, is below the line',
     menu.indexOf('רינה')>menu.indexOf('שאר חברי הלוח'), menu);
}

// ── a people column with nobody in it is still answerable ─────────────────
{
  const A=build(COND);
  addCond(A,'column_is'); chooseCol(A,0,'people','c_pm');
  const menu=last();
  ck('a column holding one person lists them first', menu.indexOf('יואב')<menu.indexOf('שאר חברי הלוח'), menu);
  ck('…and the whole board is still reachable',
     ['דנה','רינה','אבי'].every(n=>menu.includes(n)), menu);
}

// ── and the action writes a person instead of asking for one to be typed ──
{
  const A=build(SETCOL);
  A.pickField(EV,'a_column');
  A.colPickType(EV,'people');
  A.colPickOne(((A._colPick||{}).offer||[]).findIndex(c=>c.id==='c_coord'));
  A.pickField(EV,'a_text');
  const menu=last();
  ck('"הערך החדש" for a people column is a picker, not a text box',
     !menu.includes('au-txt')&&menu.includes('setFieldPerson'), menu);
  ck('…headed by that column, with its people first',
     menu.indexOf('רכזת')<menu.indexOf('רינה'), menu);
  const j=(A._popItems||[]).findIndex(x=>x.label==='רינה');
  A.setFieldPerson('a_text',j);
  const v=A.building.values['a_text'];
  ck('and stores the name, which is what the server writes a people cell from',
     v&&v.v==='רינה'&&v.label==='רינה', JSON.stringify(v));
}

// ── a text column's value is still typed ──────────────────────────────────
{
  const A=build(SETCOL);
  A.pickField(EV,'a_column');
  A.colPickType(EV,'status');
  A.colPickOne(0);
  A.pickField(EV,'a_text');
  ck('a column that is not people keeps its text box', last().includes('au-txt'), last());
}
{
  const A=build(SETCOL);
  A.pickField(EV,'a_text');          // no column chosen yet
  ck('and so does the blank before any column is named', last().includes('au-txt'), last());
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
