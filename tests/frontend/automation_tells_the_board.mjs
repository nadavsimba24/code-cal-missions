/* The creation screen asks who should hear about the new rule.

   A new automation announces itself to its author and to the board's
   managers. Sometimes that is the wrong list — a rule everybody's work runs
   through is the whole board's business — and the person writing it is the
   only one who knows which kind it is. So the creation screen carries one
   box, and the answer rides along with the rule being created.

   What is pinned here is the three things that box has to be:

   · unticked when the screen opens, because telling forty people is a
     decision and never a default;
   · present only when a rule is being CREATED — an edit announces nothing,
     so there is nothing on that screen to decide;
   · and actually sent. A box that sets a flag the save does not read is the
     worst of the three failures, because the screen looks right.

   Driven by tests/test_a_new_automation_tells_the_board.py. */
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

const COLS=[{id:'c_note', type:'text', title:'הערה'}];
const GROUPS=[{id:7,name:'בטיפול',color:'#0073ea'}];
const st={board:{id:1,name:'לוח',groups:GROUPS,my_role:'admin',col_perms:{},
                 columns:COLS.slice(),tasks:[]},boards:[]};

const RECIPE={id:'created_set_status', trigger:'item_created', action:'set_status',
  sentence:'כאשר נוצר פריט חדש, שנה את הסטטוס ל{a_status}',
  sentence_parts:{trigger:'כאשר נוצר פריט חדש', trigger_col:'',
                  action:'שנה את הסטטוס ל{a_status}', action_col:''},
  status_fields:['a_status'],
  fields:[{key:'a_status',type:'status',label:'סטטוס'}],
  conditions:[]};
const A_ROW={id:9, recipe_id:'created_set_status', config:{a_status:'done'},
             name:'הכלל', description:'', status:'draft', etag:3, draft_version:null};

let sent=[], toasts=[];
function build(){
  sent=[]; toasts=[];
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe','advCell',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x), m=>toasts.push(m), {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    u=>`<i>${(u&&u.name)||''}</i>`,
    ()=>[{key:'done',he:'הושלם',c:'#00c875'}],
    ()=>[{key:'high',he:'גבוהה',c:'#e2445c'}],
    ()=>COLS.slice(),
    ()=>[],
    ()=>false, ()=>1,
    async(url,opt)=>{ sent.push({url,method:(opt&&opt.method)||'GET',
                                 body:opt&&opt.body?JSON.parse(opt.body):null});
                      return {automations:[],can_manage:true,people:[],id:9}; },
    ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}},
    t=>t, (t,f)=>((t.custom_fields||{})[f.id]));
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[];
  A.caps={fields:[],operator_labels:{},operators_with_two_values:[],
          operators_without_value:[]};
  A.copyFields=[]; A.acts=[];
  A.data={can_manage:true,automations:[A_ROW],people:[]};
  A.recipes=[RECIPE]; A.render=()=>{};
  return A;
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,400):''))); };
const posted=()=>(sent.find(r=>r.method==='POST')||{}).body;
const LABEL='שליחת התראה לכל חברי הלוח על יצירת האוטומציה';
/* The box's own tag, cut out of the screen: everything between the <input>
   that owns it and the handler that names the flag. "checked" can only be in
   there if the box is drawn ticked — the word appears again further along, in
   `this.checked`, which is why the cut stops short of it. */
const boxTag=h=>{ const i=h.indexOf('notifyAll=this.checked');
                  return i<0?'':h.slice(h.lastIndexOf('<input',i), i); };

// ── the screen, when a rule is being created ──────────────────────────────
{
  const A=build();
  A.pick('created_set_status');
  const html=A.buildHTML();
  ck('the creation screen offers the box', html.includes(LABEL), html.slice(-900));
  ck('…and it is not ticked', !boxTag(html).includes('checked')
     && A.building.meta.notifyAll===false, boxTag(html));
  ck('…and says who hears about it without one', html.includes('ולמנהלי הלוח בלבד'),
     html.slice(-900));
  A.building.meta.notifyAll=true;
  ck('…and the screen remembers an answer once it is given',
     boxTag(A.buildHTML()).includes('checked'), boxTag(A.buildHTML()));
}

// ── …and not when one is being edited ─────────────────────────────────────
{
  const A=build();
  await A.editRule(9);
  ck('an edit is not a birth, so it asks nothing', !A.buildHTML().includes(LABEL));
}

// ── the answer travels with the rule ──────────────────────────────────────
{
  const A=build();
  A.pick('created_set_status');
  A.building.values.a_status={v:'done',label:'הושלם',color:'#00c875'};
  await A.save();
  const b=posted();
  ck('creating a rule posts it', !!b && /\/api\/boards\/1\/automations/.test(
       (sent.find(r=>r.method==='POST')||{}).url), JSON.stringify(sent.map(r=>r.method+' '+r.url)));
  ck('an untouched box says so out loud rather than by silence',
     b && b.notify_all_members===false, JSON.stringify(b));
}

{
  const A=build();
  A.pick('created_set_status');
  A.building.values.a_status={v:'done',label:'הושלם',color:'#00c875'};
  A.building.meta.notifyAll=true;
  await A.save();
  ck('a ticked box reaches the server', (posted()||{}).notify_all_members===true,
     JSON.stringify(posted()));
}

// ── and an edit never carries it ──────────────────────────────────────────
{
  const A=build();
  await A.editRule(9);
  await A.save();
  const patched=(sent.find(r=>r.method==='PATCH')||{}).body||{};
  ck('an edit PATCHes and asks nobody anything',
     !('notify_all_members' in patched), JSON.stringify(patched));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
