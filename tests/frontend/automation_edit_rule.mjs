/* A rule that already exists can be opened and changed.

   "ערוך" used to open the name, the description, the owner and the running
   order — everything ABOUT the rule and nothing the rule DOES. The sentence
   itself was fixed at creation: a trigger pointed at the wrong column, or a
   status picked by mistake, meant deleting the rule and building it again,
   which throws away its history, its owner, its order and its id.

   The server has taken a changed configuration all along. What was missing
   was a builder opened on a rule that exists — and the hard half of that is
   not the screen, it is reading a stored configuration back into the blanks
   without losing anything on the way out again.

   So what is pinned here is the ROUND TRIP: load a rule, save it untouched,
   and get the same configuration back. Including the parts the builder does
   not model — a field mapping is edited through the API and nowhere else,
   and a save that rebuilt the configuration from the screen alone would
   delete it without saying so.

   Driven by tests/test_automation_edit_rule.py. */
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

const COLS=[
  {id:'c_stage', type:'status', title:'שלב',
   options:[{id:'o1',label:'הוגש',color:'#00c875'},{id:'o2',label:'נדחה',color:'#e2445c'}]},
  {id:'c_coord', type:'people', title:'רכזת'},
  {id:'c_note',  type:'text',   title:'הערה'},
];
const MEMBERS=[{user_id:3,name:'דנה'},{user_id:4,name:'יואב'}];
const GROUPS=[{id:7,name:'בטיפול',color:'#0073ea'},{id:8,name:'הושלם',color:'#00c875'}];
const st={board:{id:1,name:'לוח',groups:GROUPS,my_role:'admin',col_perms:{},
                 columns:COLS.slice(),tasks:[{id:1,custom_fields:{c_coord:[3]}}]},boards:[]};

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
    ()=>[{key:'done',he:'הושלם',c:'#00c875'},{key:'stuck',he:'תקוע',c:'#e2445c'}],
    ()=>[{key:'high',he:'גבוהה',c:'#e2445c'}],
    ()=>COLS.slice(),
    col=>{ const c=(col&&typeof col==='object')?col:COLS.find(x=>x.id===col);
           return ((c&&c.options)||[]).map(o=>typeof o==='string'
             ?{id:null,label:o,color:'#c4c4c4'}
             :{id:o.id||null,label:o.label,color:o.color||'#c4c4c4'}); },
    ()=>false, ()=>1,
    async(url,opt)=>{ sent.push({url,method:(opt&&opt.method)||'GET',
                                 body:opt&&opt.body?JSON.parse(opt.body):null});
                      return {versions:[{version:4,snapshot:{config:DRAFT_CFG}}],id:9}; },
    ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}},
    t=>t, (t,f)=>((t.custom_fields||{})[f.id]));
  A.conds=[
    {kind:'status_is',  label:'הסטטוס הוא …', type:'status', value_label:'סטטוס'},
    {kind:'column_is',  label:'העמודה … היא …', type:'column', value_label:'ערך'},
    {kind:'no_assignee',label:'אין אחראי לפריט', type:null, value_label:''}];
  A.maxConds=3; A.maxActs=4; A.members=MEMBERS.slice();
  A.caps={fields:[],operator_labels:{},operators_with_two_values:['between'],
          operators_without_value:['empty','filled']};
  A.copyFields=[{key:'title',label:'שם הפריט'},{key:'status',label:'סטטוס'}];
  A.data={can_manage:true,automations:[A_ROW],people:[]};
  A.acts=[{key:'set_column', label:'עדכן את … ל…', text:'עדכן את {column} ל{text}',
           fields:[{key:'column',type:'column',label:'עמודה'},
                   {key:'text',type:'text',label:'הערך החדש'}]},
          {key:'wait', label:'המתן …', text:'המתן {days}',
           fields:[{key:'days',type:'wait',label:'המתנה'}]}];
  A.recipes=[RECIPE]; A.render=()=>{};
  return A;
}

const RECIPE={id:'status_assign', trigger:'status_changes_to', action:'assign_person',
  sentence:'כאשר הסטטוס משתנה ל{t_status}, שייך את {a_person}',
  sentence_parts:{trigger:'כאשר הסטטוס משתנה ל{t_status}',
                  trigger_col:'כאשר «{t_status_col}» משתנה ל{t_status}',
                  action:'שייך את {a_person}', action_col:''},
  status_fields:['t_status'],
  fields:[{key:'t_status',type:'status',label:'סטטוס'},
          {key:'a_person',type:'person',label:'אחראי'}],
  conditions:[]};

/* A rule with something of every awkward kind in it: a status that belongs
   to a column's vocabulary, a person, two conditions (one about a column),
   two extra actions, and a key the builder has no screen for. */
const CFG={
  t_status:'o1', t_status_col:'c_stage', a_person:4,
  conditions:[{kind:'status_is',value:'done'},
              {kind:'column_is',value:{col:'c_coord',type:'people',op:'eq',value:3}}],
  conditions_op:'or',
  actions:[{key:'set_column',values:{column:'c_note',text:'נבדק'}},
           {key:'wait',values:{days:1440}}],
  field_map:{from:'a',to:'b'},            // no screen edits this one
};
const DRAFT_CFG={...CFG, a_person:3};
const A_ROW={id:9, recipe_id:'status_assign', config:CFG, name:'הכלל', description:'תיאור',
             status:'active', etag:11, draft_version:null};

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,400):''))); };
const patched=()=>(sent.find(r=>r.method==='PATCH')||{}).body;
/* Key order is not part of a JSON object's meaning, and the round trip does
   not preserve it: the stored configuration is spread in first and the three
   keys the builder owns are re-added after. Compared by content. */
const canon=v=>Array.isArray(v)?v.map(canon)
  :(v&&typeof v==='object')?Object.keys(v).sort().reduce((o,k)=>(o[k]=canon(v[k]),o),{})
  :v;
const same=(a,b)=>JSON.stringify(canon(a))===JSON.stringify(canon(b));

// ── the stored rule reads back as chips, not as ids ───────────────────────
{
  const A=build();
  await A.editRule(9);
  const b=A.building;
  ck('the builder opens on the rule', !!b&&b.recipe.id==='status_assign');
  ck('and knows it is an edit', !!(b&&b.edit)&&b.edit.id===9&&b.edit.status==='active',
     JSON.stringify(b&&b.edit));
  ck('the status column is named', (b.values.t_status_col||{}).label==='שלב',
     JSON.stringify(b.values.t_status_col));
  ck('the status reads as its own label and not its id',
     (b.values.t_status||{}).label==='הוגש', JSON.stringify(b.values.t_status));
  ck('the person reads as a name', (b.values.a_person||{}).label==='יואב',
     JSON.stringify(b.values.a_person));
  ck('both conditions came back', (b.conds||[]).length===2, JSON.stringify(b.conds));
  ck('…the column one knows its column', b.conds[1].col==='c_coord'
     && b.conds[1].colLabel==='רכזת', JSON.stringify(b.conds[1]));
  ck('…and reads its value as a person', b.conds[1].label==='דנה', JSON.stringify(b.conds[1]));
  ck('the group operator survived', b.condOp==='or', b.condOp);
  ck('both extra actions came back', (b.acts||[]).length===2, JSON.stringify(b.acts));
  ck('…a column blank in one of them is named',
     ((b.acts[0].values||{}).column||{}).label==='הערה', JSON.stringify(b.acts[0]));
  ck('…and a wait is read in the words people use',
     ((b.acts[1].values||{}).days||{}).label==='יום', JSON.stringify(b.acts[1]));
  ck('the name and description are the rule’s', b.meta.name==='הכלל'&&b.meta.description==='תיאור');
}

// ── and saves back to exactly what it read ────────────────────────────────
{
  const A=build();
  await A.editRule(9);
  await A.save();
  const body=patched();
  ck('an edit PATCHes the rule rather than creating another',
     !!body && sent.some(r=>r.method==='PATCH'&&/\/api\/automations\/9/.test(r.url)),
     JSON.stringify(sent.map(r=>r.method+' '+r.url)));
  ck('…carrying the version it was written against', body&&body.etag===11, JSON.stringify(body));
  ck('the configuration round-trips unchanged', same(body.config,CFG),
     JSON.stringify(body.config));
  ck('…including the key no screen edits',
     body.config.field_map&&body.config.field_map.from==='a', JSON.stringify(body.config));
  ck('and the person is told the live rule did not change',
     toasts.some(t=>t.includes('ממתינה')), toasts);
}

// ── a change is a change, and a removal is a removal ──────────────────────
{
  const A=build();
  await A.editRule(9);
  A.building.values.a_person={v:3,label:'דנה',color:''};
  A.dropCond(0);
  await A.save();
  const cfg=patched().config;
  ck('the changed blank is sent', cfg.a_person===3, JSON.stringify(cfg));
  ck('the removed condition is gone and not merged back',
     (cfg.conditions||[]).length===1&&cfg.conditions[0].kind==='column_is',
     JSON.stringify(cfg.conditions));
}
{
  const A=build();
  await A.editRule(9);
  A.dropCond(0); A.dropCond(0);
  await A.save();
  const cfg=patched().config;
  ck('removing every condition removes the key itself',
     !('conditions' in cfg)&&!('conditions_op' in cfg), JSON.stringify(cfg));
}
{
  const A=build();
  await A.editRule(9);
  A.dropAct(0); A.dropAct(0);
  await A.save();
  ck('and so does removing every extra action', !('actions' in patched().config),
     JSON.stringify(patched().config));
}

// ── a pending draft is what the edit continues ────────────────────────────
{
  const A=build();
  A.data.automations=[{...A_ROW, draft_version:4}];
  await A.editRule(9);
  ck('the versions were read', sent.some(r=>/\/versions/.test(r.url)),
     JSON.stringify(sent.map(r=>r.url)));
  ck('and the draft is what opened, not the live rule',
     (A.building.values.a_person||{}).label==='דנה',
     JSON.stringify(A.building.values.a_person));
  ck('…and the screen says so', !!A.building.edit.fromDraft);
}

// ── creating is untouched ─────────────────────────────────────────────────
{
  const A=build();
  A.pick('status_assign');
  ck('a new rule has no edit marker', !A.building.edit);
  ck('…and starts empty', Object.keys(A.building.values).length===0,
     JSON.stringify(A.building.values));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
