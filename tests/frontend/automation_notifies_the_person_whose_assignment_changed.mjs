/* "הודע לאחראי שהתווסף או הוסר" — the builder's side of it.

   The recipient list had five answers and none of them was the person the
   event is about. "המשתמש שביצע את השינוי" is whoever did the assigning —
   the manager, not the one put on the job — and "למשויכים לפריט" is the
   wrong list when somebody is added and an empty promise when somebody is
   removed, because by then they are no longer among them.

   Three things have to stay true on this side:

   * it is offered only where the event HAS such a person — under "כאשר משויך
     אדם" and "כאשר מוסר שיוך", and under nothing else. The server refuses the
     other pairs on save, so offering it everywhere is offering a choice that
     comes back as an error;
   * which triggers it belongs to comes from the engine, not from this screen.
     A second copy of the pairing here is how the two come to disagree;
   * once chosen it reads as itself in the sentence — a blank that renders as
     "event_person" is a rule nobody can check.

   Runs the real Automations object out of index.html. Driven by
   tests/test_an_automation_notifies_the_person_whose_assignment_changed.py. */
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

const popped={html:''};
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
    ()=>'', ()=>[], ()=>[],
    ()=>[],
    ()=>[],
    ()=>false, ()=>1,
    async()=>({}), (a,html)=>{popped.html=String(html||'');}, ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelector:()=>null, querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}});
  A.caps=caps;
  A.members=[];
  A.render=()=>{};                 // the sentence redraws into a DOM there is none of
  return A;
}

/* exactly what recipients_catalog() serves */
const CAPS={recipients:[
  {key:'user',label:'משתמש קבוע',takes_value:true,triggers:[]},
  {key:'field',label:'אחראי משדה אנשים',takes_value:true,triggers:[]},
  {key:'actor',label:'המשתמש שביצע את השינוי',takes_value:false,triggers:[]},
  {key:'owner',label:'בעל האוטומציה',takes_value:false,triggers:[]},
  {key:'board_admin',label:'מנהל הלוח',takes_value:false,triggers:[]},
  {key:'event_person',label:'האחראי שהתווסף או הוסר',takes_value:false,
   triggers:['person_assigned','person_unassigned']}]};

const THE_ONE='האחראי שהתווסף או הוסר';
const offered=(A,trigger)=>{
  A.building={recipe:{trigger:trigger},values:{},acts:[]};
  popped.html='';
  A.pickRecipient(null,'a_person',null);
  return popped.html;
};

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,400):''))); };

{
  const A=build(CAPS);
  const on=offered(A,'person_assigned');
  ck('a שיוך rule is offered the person the event is about', on.includes(THE_ONE), on);
  ck('…beside the five that were always there',
     ['משתמש קבוע','אחראי משדה אנשים','המשתמש שביצע את השינוי','בעל האוטומציה','מנהל הלוח']
       .every(x=>on.includes(x)), on);
  ck('a הסרת שיוך rule is offered it too — the case it exists for',
     offered(A,'person_unassigned').includes(THE_ONE));

  /* Everywhere else there is no such person, and the server refuses the pair
     on save. A menu that offered it anyway would be offering an error. */
  for(const t of ['item_created','status_changes_to','due_date_arrives',
                  'column_changed','every_n_days','moved_to_group']){
    const html=offered(A,t);
    ck(`«${t}» is not offered a person its event does not carry`,
       !html.includes(THE_ONE), html);
  }
  ck('a rule with no trigger yet is not offered it either', !offered(A,'').includes(THE_ONE));
}
{
  /* The pairing belongs to the engine. A screen holding its own copy is how
     the two come to disagree — so a catalog that stops restricting it is
     followed, and one that restricts something else is followed too. */
  const A=build({recipients:[{key:'event_person',label:THE_ONE,triggers:[]},
                             {key:'owner',label:'בעל האוטומציה',
                              triggers:['item_created']}]});
  ck('an unrestricted entry is offered everywhere the engine says it is',
     offered(A,'item_created').includes(THE_ONE));
  ck('…and a restriction the engine puts on another kind is obeyed as well',
     offered(A,'item_created').includes('בעל האוטומציה')
     && !offered(A,'status_changes_to').includes('בעל האוטומציה'));
}
{
  /* With no answer from the engine the screen falls back to its own list,
     which must carry the same pairing rather than quietly dropping it. */
  const A=build(null);
  ck('the fallback list knows it belongs to a שיוך rule',
     offered(A,'person_assigned').includes(THE_ONE));
  ck('…and knows it belongs to nothing else',
     !offered(A,'item_created').includes(THE_ONE));
}
{
  /* Chosen, it has to read as itself. A sentence that says "event_person" is
     a rule nobody can check before switching it on. */
  const A=build(CAPS);
  A.building={recipe:{trigger:'person_unassigned'},values:{},acts:[]};
  A._recInto={key:'a_person',into:null,anchor:null};
  A._applyRecipient({kind:'event_person'},
                    CAPS.recipients.find(k=>k.key==='event_person'));
  const cell=A.building.values.a_person;
  ck('the blank holds the kind, with no value beside it',
     !!cell && cell.v && cell.v.kind==='event_person' && cell.v.value===undefined,
     JSON.stringify(cell));
  ck('…and reads as itself in the sentence', !!cell && cell.label===THE_ONE,
     JSON.stringify(cell));

  /* and with no catalog in hand, the label still comes out in Hebrew */
  const B=build(null);
  B.building={recipe:{trigger:'person_assigned'},values:{},acts:[]};
  B._recInto={key:'a_person',into:null,anchor:null};
  B._applyRecipient({kind:'event_person'},null);
  ck('…even when the engine answered nothing',
     (B.building.values.a_person||{}).label===THE_ONE,
     JSON.stringify(B.building.values.a_person));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
