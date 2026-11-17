/* "לכל ערך שהוא" — the builder's side of it.

   A status trigger named one value: "כאשר הסטטוס משתנה ל«אושר»". The rule
   people write first is the other one — "כשהסטטוס זז, רשום את תאריך העדכון" —
   and the catalog could not say it at all. The blank takes a wildcard now.

   Three things have to stay true:

   * it is offered on the TRIGGER half only. "שנה את הסטטוס לכל ערך שהוא" is
     not an instruction, and an action blank goes on offering values;
   * it leads the list. It is the general case, and a list that buries it
     under eleven statuses is one nobody finds;
   * the screen does not spell the sentinel out itself. It comes from the
     engine (automation-capabilities), so the day the engine stops accepting
     it the screen stops offering it — with nothing to remember.

   Runs the real Automations object out of index.html. Driven by
   tests/test_a_status_change_stamps_todays_date.py. */
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

const STAGE={id:'c_stage', type:'status', title:'שלב',
             options:[{id:'s1',label:'פתוח',color:'#00c875'},
                      {id:'s2',label:'סגור',color:'#0073ea'}]};
const BOARD_STATUSES=[{key:'done',he:'הושלם',c:'#00c875'},
                      {key:'in_progress',he:'בתהליך',c:'#fdab3d'}];

function build(caps){
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    {board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{}},boards:[]},
    x=>String(x==null?'':x), ()=>{}, {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>BOARD_STATUSES.slice(), ()=>[],
    ()=>[STAGE],
    col=>{ const c=(col&&typeof col==='object')?col:[STAGE].find(x=>x.id===col);
           return ((c&&c.options)||[]).map(o=>({id:o.id||null,label:o.label,color:o.color||'#c4c4c4'})); },
    ()=>false, ()=>1,
    async()=>({}), ()=>{}, ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelector:()=>null, querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}});
  A.caps=caps;
  return A;
}

const CAPS={any_status:'*', any_status_label:'כל ערך שהוא'};
const labels=items=>items.map(x=>x.label);

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

{
  const A=build(CAPS);
  const trig=A._optionsFor('status','','t_status','');
  ck('the trigger half offers it, at the head of the board\'s statuses',
     trig[0] && trig[0].v==='*' && trig[0].label==='כל ערך שהוא', labels(trig));
  ck('…and the board\'s own statuses are all still there',
     labels(trig).join()==='כל ערך שהוא,הושלם,בתהליך', labels(trig));

  const act=A._optionsFor('status','','a_status','');
  ck('the action half does not: "שנה את הסטטוס לכל ערך שהוא" is not an instruction',
     !act.some(x=>x.v==='*'), labels(act));

  const col=A._optionsFor('status','','t_status','c_stage');
  ck('a trigger pointed at a status COLUMN offers it too',
     col[0] && col[0].v==='*' && labels(col).join()==='כל ערך שהוא,פתוח,סגור', labels(col));
  const colAct=A._optionsFor('status','','a_status','c_stage');
  ck('…and that column\'s action half still does not',
     !colAct.some(x=>x.v==='*'), labels(colAct));

  const prio=A._optionsFor('status','','t_status',A.PRIORITY_AS_STATUS);
  ck('a trigger reading the priority as a status offers it as well',
     prio[0] && prio[0].v==='*', labels(prio));
}
{
  /* The engine is the authority. A screen that spelled the sentinel out would
     go on offering it the day the engine stopped accepting it — so with no
     capabilities in hand there is nothing extra to choose. */
  const A=build(null);
  const trig=A._optionsFor('status','','t_status','');
  ck('with no answer from the engine, nothing is invented',
     labels(trig).join()==='הושלם,בתהליך', labels(trig));
  ck('…and the sentinel is not written down in the screen\'s own code',
     !/any_status\s*[:=]\s*['"]\*['"]/.test(src));
}
{
  // an extra action's blank is keyed plainly "status", with no t_/a_ prefix
  const A=build(CAPS);
  const extra=A._optionsFor('status','','status','');
  ck('an extra action\'s status blank is an action blank',
     !extra.some(x=>x.v==='*'), labels(extra));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
