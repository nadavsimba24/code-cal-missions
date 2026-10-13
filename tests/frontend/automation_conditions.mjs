/* The "רק אם" block in the create screen, out of the real Automations object in
   index.html. Driven by tests/test_automation_conditions_ui.py.

   What matters here is what the screen puts on the wire: a condition reads as a
   phrase with its value in place, a condition that still has no value is
   refused before it is sent, and a rule with no conditions sends none — which
   is what keeps every rule written before today unchanged. */
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
}

const st={board:{id:1,name:'לוח תשתיות',groups:[{id:3,name:'רחובות',color:'#111'}],my_role:'admin'},boards:[]};
const stored={};
const localStorage={getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=String(v);}};
const toasts=[]; const posted=[];
/* save() finishes with a reload, so the POST is not the last call — only the
   calls that carry a body are the ones being asserted on here. */
const api=async(p,o)=>{ if(o&&o.body) posted.push({p,body:JSON.parse(o.body)}); return {automations:[],recipes:[],members:[]}; };
const lastPost=()=>posted[posted.length-1];
const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','avatarInner','boardStatusList',
  'boardPriorityList','customColumns','meId','api','openCellPop','closeCellPops','askConfirm',
  'showModal','closeModals','document','renderView','localStorage',
  grabConst('Automations')+' return Automations;')(
  st, x=>String(x==null?'':x), m=>toasts.push(m), {ago:()=>'עכשיו',goto(){}}, ()=>'01/01/2026',
  ()=>'01/01/2026',
  ()=>'', ()=>[{key:'done',he:'בוצע',c:'#00c875'}],
  ()=>[{key:'critical',he:'קריטית',c:'#e2445c'},{key:'low',he:'נמוכה',c:'#999'}],
  ()=>[], ()=>1, api, ()=>{}, ()=>{}, ()=>{},
  ()=>{}, ()=>{}, {getElementById:()=>null,querySelectorAll:()=>[]}, ()=>{}, localStorage);

A.data={can_manage:true,automations:[],people:[]};
A.members=[{user_id:5,name:'דנה'}];
A.recipes=[{id:'status_notify_person',trigger:'status_changes_to',action:'notify_person',
            sentence:'כאשר הסטטוס משתנה ל{t_status}, שלח התראה ל{a_person}',
            fields:[{key:'t_status',type:'status',label:'סטטוס'},{key:'a_person',type:'person',label:'נמען'}],
            conditions:[]},
           /* a template that arrives with its conditions — what the server sends
              for cond_status_prio_open_notify_assignees */
           {id:'cond_two',trigger:'status_changes_to',action:'notify_assignees',
            sentence:'כאשר הסטטוס משתנה ל{t_status}, שלח התראה למשויכים לפריט',
            fields:[{key:'t_status',type:'status',label:'סטטוס'}],
            conditions:[{kind:'priority_is',label:'העדיפות היא …',type:'priority',value_label:'עדיפות'},
                        {kind:'has_assignee',label:'יש אחראי לפריט',type:null,value_label:''}]}];
/* exactly what GET /api/automations/recipes serves for these */
A.conds=[{kind:'priority_is',label:'העדיפות היא …',type:'priority',value_label:'עדיפות'},
         {kind:'person_is',label:'… משויך לפריט',type:'person',value_label:'אדם'},
         {kind:'group_is',label:'הפריט בקבוצה …',type:'group',value_label:'קבוצה'},
         {kind:'has_assignee',label:'יש אחראי לפריט',type:null,value_label:''},
         {kind:'overdue',label:'תאריך היעד עבר',type:null,value_label:''}];
A.maxConds=3;

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── a rule under construction starts with no conditions ──
A.pick('status_notify_person');
ck('a new rule starts with no conditions', Array.isArray(A.building.conds) && !A.building.conds.length);
let h=A.condsHTML();
ck('the block says what it is for', h.includes('תנאים נוספים'), h);
ck('...and that an empty one changes nothing',
   h.includes('הכלל יפעל בכל פעם שהגורם המפעיל מתרחש'), h);
ck('a condition can be added', h.includes('Automations.pickCond(event)'), h);
ck('the build screen shows the block under the sentence',
   A.buildHTML().indexOf('au-conds') > A.buildHTML().indexOf('au-build'), 'block is not under the sentence');

// ── adding one that needs a value ──
A._condOffer=A.conds;
A.addCond(0);                                  // priority_is
h=A.condsHTML();
ck('the first condition reads "רק אם"', /au-cond-and">רק אם</.test(h), h);
ck('its value is a blank inside the phrase, not a separate row',
   /העדיפות היא <button class="au-blank/.test(h), h);
ck('the blank names what belongs there', h.includes('>עדיפות<'), h);

A._popItems=[{v:'critical',label:'קריטית',color:'#e2445c'}];
A.setCondValue(0,0);
h=A.condsHTML();
ck('a filled condition shows the value', h.includes('קריטית'), h);
ck('...as a filled chip in the value\'s own colour',
   /au-blank filled[\s\S]{0,80}#e2445c/.test(h), h);

// ── a second condition is ANDed, in words ──
A.addCond(3);                                  // has_assignee, nothing to fill
h=A.condsHTML();
ck('the second condition reads "וגם"', /au-cond-and">וגם</.test(h), h);
ck('a condition that needs nothing shows no blank',
   !/יש אחראי לפריט <button class="au-blank/.test(h), h);

// ── what reaches the server ──
A.building.values={t_status:{v:'done',label:'בוצע'},a_person:{v:5,label:'דנה'}};
const built=A.building;                        // save() clears it on success
await A.save();
let body=lastPost().body;
ck('the conditions travel inside the rule\'s own config',
   Array.isArray(body.config.conditions) && body.config.conditions.length===2, JSON.stringify(body.config));
ck('a value-taking condition sends its value',
   body.config.conditions[0].kind==='priority_is' && body.config.conditions[0].value==='critical',
   JSON.stringify(body.config.conditions[0]));
ck('a condition that takes none sends none',
   body.config.conditions[1].kind==='has_assignee' && !('value' in body.config.conditions[1]),
   JSON.stringify(body.config.conditions[1]));
A.building=built;                              // same rule, one more condition
A.addCond(1); A._popItems=[{v:5,label:'דנה'}]; A.setCondValue(2,0);
await A.save();
body=lastPost().body;
ck('a person condition is sent as a number, like every other person field',
   body.config.conditions[2].kind==='person_is' && body.config.conditions[2].value===5,
   JSON.stringify(body.config.conditions[2]));

// ── the ceiling, and the refusals ──
A.building=built;
h=A.condsHTML();
ck('at the maximum it stops offering more', !h.includes('Automations.pickCond(event)'), h);
ck('...and says why', h.includes('מספר התנאים המקסימלי'), h);

A.dropCond(2); A.dropCond(1);
ck('a condition can be removed', A.building.conds.length===1);
A.addCond(2);                                  // group_is, left without a value
const before=posted.length; toasts.length=0;
await A.save();
ck('a condition with no value is not sent', posted.length===before, 'it was sent anyway');
ck('...and the screen says what is missing', toasts.some(t=>t.includes('להשלים את הערך בתנאי')), toasts.join('|'));

// ── a rule with no conditions is the rule it always was ──
A.pick('status_notify_person');
A.building.values={t_status:{v:'done',label:'בוצע'},a_person:{v:5,label:'דנה'}};
await A.save();
body=lastPost().body;
ck('no conditions means no conditions key at all', !('conditions' in body.config), JSON.stringify(body.config));

// ── the scratch flow: the condition is a step of its own, visible from the start
A.building=null; A.mode='scratch'; A.scratch={trigger:'',conds:[]};
let sc=A.scratchHTML();
ck('the from-scratch flow asks what fires the rule', sc.includes('מה יפעיל את האוטומציה'), sc);
ck('...then the conditions, as step 2', /au-step-n">2<\/span> ורק אם/.test(sc), sc);
ck('...and the action last, as step 3', /au-step-n">3<\/span> ומה יקרה אז/.test(sc), sc);
ck('the condition step is offered before any trigger is chosen',
   sc.indexOf('Automations.pickCond(event)') > -1, sc);
ck('the step reads as one sentence, without a second heading of its own',
   !/au-conds-h/.test(sc), sc);

A._condOffer=A.conds; A.addCond(4);            // overdue, nothing to fill
ck('a condition chosen here is held on the scratch rule', A.scratch.conds.length===1);
A.setTrigger('status_changes_to');
ck('...and survives changing what starts the rule', A.scratch.conds.length===1);
A.pick('status_notify_person');
ck('...and is carried into the rule the action completes',
   A.building.conds.length===1 && A.building.conds[0].kind==='overdue',
   JSON.stringify(A.building.conds));
A.building.values={t_status:{v:'done',label:'בוצע'},a_person:{v:5,label:'דנה'}};
await A.save();
ck('...all the way to the server', lastPost().body.config.conditions[0].kind==='overdue',
   JSON.stringify(lastPost().body.config));

// ── templates that arrive with their conditions ──
A.mode='templates'; A.building=null;
const cat=A.catalogHTML();
ck('a conditioned template shows its conditions on the row', cat.includes('רק אם'), cat);
ck('...badged with how many there are', /au-ccount">2 תנאים</.test(cat), cat);
ck('...with the value still shown as a blank to fill', /au-recipe-if[\s\S]{0,160}class="ph">עדיפות</.test(cat), cat);
ck('a template with no conditions keeps its single line',
   (cat.match(/au-recipe-if/g)||[]).length===1, cat);

A.pick('cond_two');
ck('picking it seeds the conditions it came with',
   A.building.conds.length===2 && A.building.conds[0].kind==='priority_is',
   JSON.stringify(A.building.conds));
ck('...with their values left to fill', A.building.conds[0].v===null);
A.building.values={t_status:{v:'done',label:'בוצע'}};
let bh=A.buildHTML();
ck('the rule cannot be switched on while a seeded condition is empty',
   /disabled title="יש להשלים/.test(bh), 'it offered to create an unfinished rule');
A._popItems=[{v:'critical',label:'קריטית',color:'#e2445c'}];
A.setCondValue(0,0);
ck('...and can be once it is filled', !/disabled title="יש להשלים/.test(A.buildHTML()));
await A.save();
ck('the template\'s conditions reach the server with the values filled',
   JSON.stringify(lastPost().body.config.conditions)===
   JSON.stringify([{kind:'priority_is',value:'critical'},{kind:'has_assignee'}]),
   JSON.stringify(lastPost().body.config));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
