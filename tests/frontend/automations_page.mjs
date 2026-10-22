/* The automations page — three tabs, built out of the real Automations object
   in index.html. Driven by tests/test_automations_page.py.

   Only the HTML builders are exercised: they are where the three tabs differ,
   and they are pure given the object's own state. render() is a no-op here —
   it returns early when there is no open modal — so switching tabs is safe. */
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

const st={board:{id:1,name:'לוח תשתיות',groups:[],my_role:'admin'},boards:[]};
let lastPop='';
const stored={};
const localStorage={getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=String(v);}};
const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','avatarInner','boardStatusList',
  'boardPriorityList','customColumns','meId','api','openCellPop','closeCellPops','askConfirm',
  'showModal','closeModals','document','renderView','localStorage',
  grabConst('Automations')+' return Automations;')(
  st, x=>String(x==null?'':x), ()=>{}, {ago:()=>'עכשיו',goto(){}}, ()=>'01/01/2026',
  ()=>'01/01/2026',
  ()=>'', ()=>[], ()=>[],
  ()=>[{id:'col_a',type:'text',title:'אזור'},{id:'col_p',type:'people',title:'מלווה'}],
  ()=>1, async()=>({}), (a,html)=>{lastPop=String(html||'');}, ()=>{}, ()=>{},
  ()=>{}, ()=>{}, {getElementById:()=>null}, ()=>{}, localStorage);

const RULES=[
  {id:11,status:'active',is_active:true,trigger:'status_changes_to',action:'notify_person',
   sentence:'כאשר הסטטוס משתנה ל«בוצע», שלח התראה ל«דנה»',name:'סגירת קריאה',
   display_name:'סגירת קריאה',description:'מודיע לרכזת השירות שהקריאה נסגרה',
   importance:'critical',run_order:1,owner_id:5,owner_name:'דנה',owner_is_creator:false,
   created_by:4,created_by_name:'יואב',updated_by:4,updated_by_name:'יואב',
   updated_at:'2026-09-01T10:00:00',last_run_at:'2026-09-13T09:00:00',
   last_success_at:'2026-09-13T09:00:00',last_outcome:'ran',run_count:4,fail_count:1,
   skip_count:2,success_rate:80,needs_attention:false},
  {id:12,status:'paused',is_active:false,trigger:'item_created',action:'assign_person',
   sentence:'כאשר נוצר פריט חדש, שייך את «יואב»',name:'',
   display_name:'כאשר נוצר פריט חדש, שייך את יואב',description:'',
   importance:'normal',run_order:2,owner_id:4,owner_name:'יואב',owner_is_creator:true,
   created_by:4,created_by_name:'יואב',run_count:0,fail_count:0,skip_count:0,
   success_rate:null,last_outcome:'',needs_attention:false},
  {id:13,status:'draft',is_active:false,trigger:'item_created',action:'set_status',
   sentence:'כאשר נוצר פריט חדש, שנה את הסטטוס ל«בתהליך»',name:'טיוטה לבדיקה',
   display_name:'טיוטה לבדיקה',description:'',importance:'low',run_order:3,
   owner_id:4,owner_name:'יואב',owner_is_creator:true,created_by:4,created_by_name:'יואב',
   run_count:0,fail_count:0,skip_count:0,success_rate:null,last_outcome:'',needs_attention:false},
  {id:14,status:'paused_error',is_active:false,trigger:'status_changes_to',action:'set_priority',
   sentence:'כאשר הסטטוס משתנה ל«בסקירה», שנה את העדיפות ל«גבוהה»',name:'הקפצת עדיפות',
   display_name:'הקפצת עדיפות',description:'',importance:'high',run_order:4,
   owner_id:5,owner_name:'דנה',owner_is_creator:false,created_by:4,created_by_name:'יואב',
   run_count:2,fail_count:5,skip_count:0,success_rate:29,last_outcome:'failed',
   last_run_at:'2026-09-14T07:00:00',last_failure_at:'2026-09-14T07:00:00',needs_attention:true},
];
A.data={can_manage:true,automations:RULES.map(r=>({...r})),
        people:[{id:4,name:'יואב'},{id:5,name:'דנה'}],
        counts:{total:4,active:1,paused:2,paused_error:1,draft:1,deleting:0,needs_attention:1}};
A.recipes=[{id:'status_notify_person',trigger:'status_changes_to',action:'notify_person',
            sentence:'כאשר הסטטוס משתנה ל{t_status}, שלח התראה ל{a_person}',
            fields:[{key:'t_status',type:'status',label:'סטטוס'},{key:'a_person',type:'person',label:'נמען'}]},
           {id:'created_set_status',trigger:'item_created',action:'set_status',
            sentence:'כאשר נוצר פריט חדש, שנה את הסטטוס ל{a_status}',
            fields:[{key:'a_status',type:'status',label:'סטטוס'}]}];
A.blueprint=[{trigger:'status_changes_to',label:'כאשר הסטטוס משתנה ל…',
              actions:[{action:'notify_person',label:'שלח התראה ל…',recipe_id:'status_notify_person'}]},
             {trigger:'item_created',label:'כאשר נוצר פריט חדש',
              actions:[{action:'set_status',label:'שנה את הסטטוס ל…',recipe_id:'created_set_status'}]}];
A.trigLabels={status_changes_to:'כאשר הסטטוס משתנה ל…',item_created:'כאשר נוצר פריט חדש'};
A.actLabels={notify_person:'שלח התראה ל…',assign_person:'שייך את…',set_status:'שנה את הסטטוס ל…',
             set_priority:'שנה את העדיפות ל…'};
A.runs=[
  {id:1,outcome:'ran',sentence:'כאשר נוצר פריט חדש, שנה את הסטטוס ל«בתהליך»',task_id:7,
   task_title:'תיקון מדרכה',reason:'',depth:0,is_retry:false,can_retry:false,created_at:'2026-09-14T08:00:00'},
  {id:2,outcome:'skipped',sentence:'כאשר הסטטוס משתנה ל«בוצע», שלח התראה ל«דנה»',task_id:8,
   task_title:'החלפת תמרור',reason:'נמען ההתראה אינו חבר בלוח',depth:0,is_retry:false,
   can_retry:true,created_at:'2026-09-14T08:05:00'},
  {id:3,outcome:'failed',sentence:'כאשר נוצר פריט חדש, שייך את «יואב»',task_id:9,task_title:'גינון',
   reason:'ValueError: boom',depth:1,is_retry:true,retry_of:2,can_retry:true,created_at:'2026-09-14T08:09:00'},
];
A.runCounts={ran:1,skipped:1,failed:1,retried:1,total:3};

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the three tabs the board button opens ──
const tabs=A.tabsHTML();
['יצירה','ניהול','היסטוריית הפעלות'].forEach(t=>
  ck(`the page offers the "${t}" tab`, tabs.includes(t), tabs));
ck('ניהול is badged with how many rules there are', /ניהול[\s\S]{0,80}au-count">4</.test(tabs), tabs);
ck('the history is badged with how many runs there are', /au-count">3</.test(tabs), tabs);

// ── יצירה: templates, and the same thing from scratch ──
A.tab='create'; A.mode='templates';
let c=A.createHTML();
ck('יצירה offers both a template and a from-scratch route',
   c.includes('תבניות') && c.includes('אוטומציה מאפס'), c.slice(0,300));
ck('the template list is the recipe catalog', (c.match(/class="au-recipe"/g)||[]).length===2);
ck('a template names its trigger as a heading', c.includes('כאשר הסטטוס משתנה ל…'));

A.setMode('scratch');
let s=A.createHTML();
ck('from scratch asks for the trigger first', s.includes('מה יפעיל את האוטומציה?'), s.slice(0,200));
ck('...and will not offer actions before one is chosen',
   s.includes('בחר קודם מה יפעיל את האוטומציה'));
A.setTrigger('status_changes_to');
s=A.createHTML();
ck('once a trigger is picked, its actions are offered', s.includes('שלח התראה ל…'), s);
ck('...and an action resolves to a recipe, exactly as a template does',
   s.includes("Automations.pick('status_notify_person')"), s);
ck('an action from another trigger is not offered', !s.includes('שנה את הסטטוס ל…'));

// a non-admin gets the tab, and a reason instead of a builder
A.data.can_manage=false;
A.pick('created_set_status');
let bd=A.buildHTML();
ck('a rule can be named and described as it is built',
   bd.includes('id="au-nm"') && bd.includes('id="au-ds"'), bd.slice(0,400));
ck('...and saved as a draft rather than switched straight on',
   bd.includes('Automations.save(true)') && bd.includes('שמור כטיוטה'), bd.slice(0,600));
A.cancelNew(); A.setMode('templates');

ck('a non-admin is told why there is nothing to build with',
   A.createHTML().includes('רק מנהל הלוח יכול ליצור אוטומציות'));
A.data.can_manage=true;

// ── ניהול: the default view, the tiles, the filters and the two densities ──
A.tab='manage'; A.clearF(); A.sort='order'; A.view='expanded';
let m=A.manageHTML();
ck('ניהול shows every rule by default, whatever its state',
   [11,12,13,14].every(id=>m.includes('Automations.menu(event,'+id+')')), m.slice(0,200));
[['סה״כ','4'],['פעילות','1'],['מושהות','2'],['טיוטות','1'],['דורשות טיפול','1']].forEach(([he,n])=>
  ck(`the head counts ${he}`, new RegExp('<b>'+n+'</b><span>'+he).test(m), m.slice(0,900)));
ck('the total tile is the one selected when nothing is filtered',
   /am-tile on[^>]*>\s*<b>4<\/b>/.test(m), m.slice(0,600));

// every filter the list has to support
['חיפוש בשם, במשפט ובתיאור','כל הסטטוסים','כל הבעלים','כל היוצרים','כל דרגות החשיבות',
 'כל הגורמים המפעילים','כל הפעולות','כל תוצאות ההפעלה האחרונה'].forEach(f=>
  ck(`the list can be narrowed by "${f}"`, m.includes(f), m.slice(0,1400)));

// what each rule shows in the expanded view
ck('a rule shows its name and its sentence', m.includes('סגירת קריאה') && m.includes('שלח התראה ל'));
ck('...its business description', m.includes('מודיע לרכזת השירות שהקריאה נסגרה'));
ck('...its state in words', m.includes('פעילה') && m.includes('טיוטה') && m.includes('מושהית עקב שגיאה'));
ck('...its owner alongside who wrote it',
   /בעלים: <b>דנה<\/b>/.test(m) && m.includes('נוצר ע"י יואב'), m.slice(0,2000));
ck('...that an owner who wrote it is both', m.includes('(גם היוצר)'));
ck('...its importance', m.includes('קריטית') && m.includes('נמוכה'));
ck('...where it sits in the running order', m.includes('סדר 1') && m.includes('סדר 4'));
ck('...and that the importance is NOT what decides that',
   /am-imp[^>]*title="[^"]*אינה משפיעה על סדר הביצוע/.test(m), m.slice(0,2500));
['עדכון אחרון','הפעלה אחרונה','הצלחה אחרונה','שיעור הצלחה','כשלים','דילוגים'].forEach(k=>
  ck(`...and its ${k}`, m.includes(k), m.slice(0,2500)));
ck('a rule that never ran says so instead of claiming 0% success',
   m.includes('<b>—</b>'), m.slice(0,2500));
ck('a rule with runs links to its own history', m.includes('Automations.historyFor(11)'));

// filtering
A.setF('status','draft'); m=A.manageHTML();
ck('filtering to drafts leaves only the draft',
   m.includes('טיוטה לבדיקה') && !m.includes('Automations.menu(event,11)'), m.slice(1200));
A.tile('paused'); m=A.manageHTML();
ck('"מושהות" covers a rule suspended by errors too',
   m.includes('Automations.menu(event,12)') && m.includes('Automations.menu(event,14)') && !m.includes('Automations.menu(event,11)'));
A.tile('attention'); m=A.manageHTML();
ck('"דורשות טיפול" is only what actually needs looking at',
   m.includes('Automations.menu(event,14)') && !m.includes('Automations.menu(event,12)'));
A.clearF(); A.setF('owner','5'); m=A.manageHTML();
ck('filtering by owner', m.includes('Automations.menu(event,11)') && !m.includes('Automations.menu(event,12)'));
A.clearF(); A.setF('creator','4'); m=A.manageHTML();
ck('filtering by creator keeps all four', [11,12,13,14].every(id=>m.includes('Automations.menu(event,'+id+')')));
A.clearF(); A.setF('importance','critical'); m=A.manageHTML();
ck('filtering by importance', m.includes('Automations.menu(event,11)') && !m.includes('Automations.menu(event,14)'));
A.clearF(); A.setF('trigger','item_created'); m=A.manageHTML();
ck('filtering by trigger', m.includes('Automations.menu(event,12)') && !m.includes('Automations.menu(event,11)'));
A.clearF(); A.setF('action','set_priority'); m=A.manageHTML();
ck('filtering by action', m.includes('Automations.menu(event,14)') && !m.includes('Automations.menu(event,11)'));
A.clearF(); A.setF('last','failed'); m=A.manageHTML();
ck('filtering by the last run result', m.includes('Automations.menu(event,14)') && !m.includes('Automations.menu(event,11)'));
A.clearF(); A.setF('last','none'); m=A.manageHTML();
ck('...including "never ran"', m.includes('Automations.menu(event,12)') && !m.includes('Automations.menu(event,11)'));
A.clearF(); A.f.q='רכזת'; m=A.listBody();
ck('search reaches the business description, not only the name',
   m.includes('Automations.menu(event,11)') && !m.includes('Automations.menu(event,12)'), m.slice(0,300));
A.f.q='שום דבר'; 
ck('a search with no hits says so', A.listBody().includes('אין אוטומציות בסינון הזה'));
A.clearF();
ck('clearing puts everything back', [11,12,13,14].every(id=>A.listBody().includes('Automations.menu(event,'+id+')')));

// sorting
const order=h=>[11,12,13,14].map(id=>({id,at:h.indexOf('Automations.menu(event,'+id+')')}))
  .filter(x=>x.at>=0).sort((a,b)=>a.at-b.at).map(x=>x.id);
A.sort='order';      ck('sorted by running order', String(order(A.listBody()))==='11,12,13,14');
A.sort='name';       ck('sorted by name', order(A.listBody())[0]!==undefined);
A.sort='success';    ck('sorted by success rate puts the best first', order(A.listBody())[0]===11);
A.sort='last_run';   ck('sorted by last run puts the most recent first', order(A.listBody())[0]===14);
A.sort='importance'; ck('sorted by importance puts the critical one first', order(A.listBody())[0]===11);
A.sort='order';

// the two densities
A.setView('compact');
let cp=A.manageHTML();
ck('the compact view is one line per rule, without the descriptions',
   !cp.includes('מודיע לרכזת השירות שהקריאה נסגרה') && (cp.match(/am-row compact/g)||[]).length===4, cp.slice(0,400));
ck('...and still shows state, flow, rate and last run',
   cp.includes('כאשר הסטטוס משתנה ל… → שלח התראה ל…') && cp.includes('80% הצלחה'), cp.slice(0,900));
A.setView('expanded');
ck('the view choice is remembered', stored['cc_au_view']==='expanded');

// acting on a rule
m=A.manageHTML();
ck('an active rule offers to be paused', m.includes('Automations.toggle(11,false)'));
ck('a paused one offers to be switched on', m.includes('Automations.toggle(12,true)'));
ck('each rule opens an actions menu', m.includes('Automations.menu(event,11)'));

// ── the actions menu ──
A._anchor={};
const menu=(id,which)=>A.menuHTML(RULES.find(r=>r.id===id),which);
let mm=menu(11,'main');
[['ערוך','Automations.edit(11)'],['שכפל','Automations.duplicate(11)'],
 ['השהה','Automations.toggle(11,false)'],['העבר בעלות',"Automations.showMenu(11,'owner')"],
 ['שנה חשיבות',"Automations.showMenu(11,'importance')"],
 ['שנה סדר ביצוע',"Automations.showMenu(11,'order')"],
 ['בדיקה על פריט (ללא שינוי)','Automations.startTest(11)'],['צפייה בגרסאות','Automations.versions(11)'],
 ['לוג הפעלות','Automations.historyFor(11)'],['מחק','Automations.del(11)']].forEach(([he,act])=>
  ck(`the menu offers "${he}"`, mm.includes(he) && mm.includes(act), mm.slice(0,900)));
ck('a paused rule is offered activation rather than pausing',
   menu(12,'main').includes('Automations.toggle(12,true)'));
ck('the owner submenu lists the board and marks the current owner',
   menu(11,'owner').includes('Automations.setOwner(11,4)') && menu(11,'owner').includes('fa-check'));
ck('the importance submenu offers all four',
   ['קריטית','גבוהה','רגילה','נמוכה'].every(x=>menu(11,'importance').includes(x)));
ck('...and says it does not change precedence',
   menu(11,'importance').includes('אינה משפיעה על סדר הביצוע'));
ck('the order submenu edits the number that actually decides precedence',
   menu(11,'order').includes('id="am-ordin"') && menu(11,'order').includes('קובע קדימות בפועל'));
ck('every submenu can get back to the menu', menu(11,'owner').includes("Automations.showMenu(11,'main')"));

// versions
A.viewing={id:11,a:RULES[0],rows:[
  {version:2,summary:'שונה: השם',sentence:'כאשר הסטטוס משתנה ל«בוצע», שלח התראה ל«דנה»',
   changed_by_name:'יואב',changed_at:'2026-09-01T10:00:00',
   snapshot:{name:'סגירת קריאה',status:'active',importance:'critical',run_order:1}},
  {version:1,summary:'נוצרה',sentence:'כאשר הסטטוס משתנה ל«בוצע», שלח התראה ל«דנה»',
   changed_by_name:'יואב',changed_at:'2026-08-01T10:00:00',snapshot:{name:'',status:'draft'}}]};
let vs=A.versionsHTML();
ck('the versions panel lists each version with what changed',
   vs.includes('v2') && vs.includes('שונה: השם') && vs.includes('נוצרה'), vs.slice(0,400));
ck('...who changed it and when', vs.includes('יואב') && vs.includes('01/01/2026'));
ck('...and the rule as it read at the time', vs.includes('שלח התראה ל'));
ck('a version can be restored where the data capability allows it',
   (A.data.can_export=true, A.data.can_manage=true,
    A.versionsHTML().includes('Automations.restore(11,1)')), A.versionsHTML().slice(0,300));
ck('...and the newest version offers no restore, being the current one',
   !A.versionsHTML().includes('Automations.restore(11,2)'));
ck('...and nothing is offered without the data capability',
   (A.data.can_export=false, !A.versionsHTML().includes('Automations.restore(')));
A.data.can_export=true;
A.viewing={id:11,a:RULES[0],rows:null};
ck('the versions panel waits rather than showing an empty history', A.versionsHTML().includes('spin'));
A.closePanel();

// a test on one item
A.testing={id:11,a:RULES[0],q:'',items:[{id:7,title:'תיקון מדרכה'}],result:null,busy:false,real:false};
let ts=A.testHTML();
ck('the test screen promises it changes nothing',
   ts.includes('אינה משנה מידע ואינה שולחת התראה'), ts.slice(0,700));
ck('...and offers the board\'s own items to run it on', ts.includes('Automations.runTest(7)'));
A.testing.result={verdict:'would_run',summary:'הכלל היה מתבצע',task_title:'תיקון מדרכה',
  retention_days:30,
  trigger:{label:'כאשר הסטטוס משתנה ל…',matches:true,note:'הסטטוס בפריט: בוצע'},
  conditions:[{label:'סטטוס',expected:'בוצע',actual:'בוצע',ok:true}],
  actions:[{what:'שליחת התראה',to:'דנה',from:'',no_op:false,note:'בבדיקה לא נשלחת התראה'}],
  missing_permissions:[],broken_dependencies:[],conflicts:[],loop_risk:[]};
ts=A.testHTML();
ck('the verdict is stated', ts.includes('הכלל היה מתבצע'), ts.slice(0,400));
ck('the trigger match is shown', ts.includes('גורם מפעיל') && ts.includes('הסטטוס בפריט: בוצע'));
ck('each condition is shown with expected and actual',
   ts.includes('תנאים') && ts.includes('בפריט: בוצע'));
ck('the actions and their expected values are shown',
   ts.includes('פעולות וערכים צפויים') && ts.includes('דנה'));
ck('...including that no notification is sent', ts.includes('לא נשלחת התראה'));
ck('the retention of the test log is stated', ts.includes('30 ימים'));
A.testing.result={verdict:'blocked',summary:'הכלל חסום',task_title:'תיקון מדרכה',retention_days:30,
  trigger:{label:'x',matches:true,note:''},conditions:[],actions:[],
  missing_permissions:['דנה אינו חבר בלוח'],broken_dependencies:['הקבוצה נמחקה'],
  conflicts:[{id:12,name:'כלל אחר'}],loop_risk:[{id:13,name:'כלל מחזיר',cycle:true}]};
ts=A.testHTML();
ck('a blocked test names the missing permission', ts.includes('הרשאות חסרות') && ts.includes('דנה אינו חבר בלוח'));
ck('...and the broken dependency', ts.includes('תלויות חסרות') && ts.includes('הקבוצה נמחקה'));
ck('...and warns about a conflict', ts.includes('התנגשות') && ts.includes('כלל אחר'));
ck('...and about a loop', ts.includes('סיכון ללולאה') && ts.includes('מזינה את האוטומציה הזאת בחזרה'));
A.testing.real=true;
A.testing.result={outcome:'ran',task_title:'תיקון מדרכה',reason:''};
ck('a manual run says it really happened', A.testHTML().includes('הכלל בוצע'));
ck('...and warns it will stay', A.testHTML().includes('נשארת'));

/* ── the manual run is confirmed against a preview of the item it would run
      on, and only a system admin is offered the condition override ── */
A.testing={id:11,a:A.testing.a,q:'',items:[],result:null,busy:false,real:true,
  pick:{id:7,title:'תיקון מדרכה'},ovr:false,reason:'',
  preview:{verdict:'would_run',summary:'הכלל היה מתבצע',task_title:'תיקון מדרכה',
    trigger:{label:'כאשר נוצר פריט חדש',matches:true,note:''},
    conditions:[{label:'העדיפות היא «קריטית»',expected:'קריטית',actual:'רגילה',ok:false}],
    actions:[{what:'שינוי סטטוס',to:'בוצע',from:'בתכנון',no_op:false,note:''}],
    missing_permissions:[],broken_dependencies:[],conflicts:[],loop_risk:[]}};
ts=A.testHTML();
ck('a manual run shows the preview before it runs', ts.includes('פעולות וערכים צפויים')
   && ts.includes('אישור הפעלה על'), ts.slice(0,400));
ck('...naming the item it would run on', ts.includes('תיקון מדרכה'));
ck('...and the button under it is the one that runs the rule',
   ts.includes('Automations.confirmRun()'));
ck('...with no "נשמרת בלוג הבדיקות" footnote — this one is not a test',
   !ts.includes('נשמרת בלוג הבדיקות'));
ck('a board admin is told the conditions hold and who may step over them',
   ts.includes('רק מנהל מערכת יכול לעקוף') && !ts.includes('עקוף את תנאי הכלל'));
st.me={id:1,role:'admin'};
ts=A.testHTML();
ck('a system admin is offered the override', ts.includes('עקוף את תנאי הכלל'));
A.setOverride(true);
ts=A.testHTML();
ck('...and has to write a reason for it', ts.includes('סיבה לעקיפה'));
A.testing.preview.missing_permissions=['דנה אינו חבר בלוח'];
ts=A.testHTML();
ck('a blocked preview offers no run at all', ts.includes('יש להסיר את החסימות')
   && ts.includes('disabled'));
ck('...and no override either — a reason does not restore a membership',
   !ts.includes('עקוף את תנאי הכלל'));
st.me={id:1,role:'member'};
A.closePanel();

// the impact preview, before switching a rule on
A.imp={id:11,then:'',data:{sentence:'כאשר נוצר פריט חדש, שייך את «דנה»',missing_fields:[],
  boards:[{id:7,name:'לוח תשתיות',mode:'read_write',why:'הלוח שהאוטומציה יושבת בו'},
          {id:9,name:'לוח יעד',mode:'write',why:'האוטומציה יוצרת בו פריטים'}],
  reads:['סטטוס'],writes:['אחראים'],
  links:[{kind:'connect',column:'קישור',two_way:true,boards:[{id:9,name:'לוח יעד'}]},
         {kind:'mirror',column:'מראה',through:'קישור',boards:[]}],
  recipients:[{name:'דנה',kind:'נמען מוגדר',ok:false}],
  missing_permissions:['דנה אינו חבר בלוח'],
  others:[{id:12,name:'כלל אחר',status:'active',fields:['אחראים'],runs_before:true}],
  loop_risk:[{id:13,name:'כלל מחזיר',cycle:true}]}};
let ip=A.impactHTML();
ck('the preview lists the boards and how each is touched',
   ip.includes('לוח תשתיות') && ip.includes('קורא ומעדכן') && ip.includes('לוח יעד') && ip.includes('מעדכן'));
ck('...the fields read and written', ip.includes('שדות נקראים') && ip.includes('שדות מתעדכנים'));
ck('...the connect and mirror dependencies',
   ip.includes('תלויות בקישור ובמראה') && ip.includes('דו־כיוונית') && ip.includes('עמודת מראה'));
ck('...who would be notified, and that they cannot be',
   ip.includes('נמעני התראות') && ip.includes('דנה') && ip.includes('אינו חבר בלוח'));
ck('...other automations writing the same fields',
   ip.includes('אוטומציות נוספות שמעדכנות אותם שדות') && ip.includes('רצה לפניה'));
ck('...and the loop risk', ip.includes('סיכון ללולאה'));
ck('the preview can lead straight into a test', ip.includes('Automations.startTest(11)'));
A.imp.data.missing_fields=['נמען'];
ck('a rule missing a required field cannot be activated from here',
   /disabled title="יש להשלים את שדות החובה"/.test(A.impactHTML()));
A.imp=null;

// the test log, separate from the run history
A.tlog={id:11,days:30,rows:[{id:1,automation_id:11,task_title:'תיקון מדרכה',
  sentence:'כאשר נוצר פריט חדש, שייך את «דנה»',verdict:'would_skip',summary:'לא היה עושה דבר',
  tested_by_name:'שלי',created_at:'2026-09-14T09:00:00'}]};
let tl=A.testLogHTML();
ck('the test log says it is not the run history', tl.includes('אינן בלוג ההפעלות'));
ck('...states the retention', tl.includes('30 ימים'));
ck('...and lists each test with its verdict', tl.includes('לא היה עושה דבר') && tl.includes('שלי'));
A.tlog={id:11,rows:[]};
ck('an empty test log says so', A.testLogHTML().includes('לא בוצעו בדיקות'));
A.tlog=null;

A.data.can_manage=false;
ck('a viewer gets the list but no controls',
   !A.manageHTML().includes('Automations.toggle(') && A.manageHTML().includes('סגירת קריאה'));
A.data.can_manage=true;

// the editor behind the pencil
A.edit(11);
let ed=A.editHTML();
[['שם האוטומציה','am-nm'],['סטטוס','am-st'],['בעלים','am-ow'],['חשיבות','am-im'],
 ['סדר ביצוע','am-or'],['תיאור עסקי','am-ds']].forEach(([he,id])=>
  ck(`the editor holds ${he}`, ed.includes(he) && ed.includes('id="'+id+'"'), ed.slice(0,400)));
ck('the editor offers all five states',
   ['טיוטה','פעילה','מושהית','מושהית עקב שגיאה','בתהליך מחיקה'].every(x=>ed.includes(x)));
ck('the editor names the creator as the unchangeable fact it is',
   ed.includes('נתון היסטורי שאינו משתנה'));
ck('the editor says the importance is for sorting only', ed.includes('למיון ולסינון בלבד'));
A.cancelEdit();
ck('cancelling the editor goes back to the list', A.manageHTML().includes('am-tiles'));

// an empty board
A.data.automations=[]; A.data.counts={total:0};
ck('a board with no rules is pointed at יצירה instead of a filter bar',
   A.manageHTML().includes('בנה את הראשונה') && !A.manageHTML().includes('am-bar'));
A.data.automations=RULES.map(r=>({...r}));
A.data.counts={total:4,active:1,paused:2,paused_error:1,draft:1,deleting:0,needs_attention:1};

// ── a draft version waiting to be published ──
A.data.automations[0].draft_version=4;
A.clearF(); A.view='expanded';
let pd=A.manageHTML();
ck('a waiting edit is announced', pd.includes('גרסה 4 ממתינה להפעלה'), pd.slice(0,500));
ck('...saying the live version keeps running', pd.includes('ממשיכה לפעול עד שתפעילו'));
ck('...and offers to publish, compare or discard',
   pd.includes('Automations.publish(11)') && pd.includes('Automations.compare(11)')
   && pd.includes('Automations.discard(11)'));
A.data.automations[0].draft_version=null;
ck('and nothing is announced when there is no draft', !A.manageHTML().includes('ממתינה להפעלה'));

// a draft that cannot be switched on says what it is missing
A.data.automations[1].status='draft';
A.data.automations[1].missing_fields=['נמען','סטטוס'];
ck('an incomplete draft lists the fields it needs',
   A.manageHTML().includes('חסרים שדות חובה: נמען, סטטוס'), A.manageHTML().slice(0,400));
A.data.automations[1].status='paused'; A.data.automations[1].missing_fields=[];

// the statuses say what they mean
ck('each status explains itself on hover',
   ['אינה מאזינה לאירועים','מאזינה לאירועים','נעצרה ידנית','לולאה','ממתינה להשלמת']
     .every(x=>Object.values(A.ST).some(v=>(v.what||'').includes(x))),
   JSON.stringify(Object.values(A.ST).map(v=>v.what)));

// the comparison, grouped the way the decision is made
A.cmp={id:11,data:{a:{version:2,is_draft:false,changed_at:'2026-09-01T10:00:00',sentence:''},
  b:{version:3,is_draft:true,changed_at:'2026-09-14T10:00:00',sentence:''},
  identical:false,
  groups:[{id:'conditions',label:'תנאים',changes:[{key:'t_status',label:'סטטוס',from:'בוצע',to:'בתהליך'}]},
          {id:'permissions',label:'הרשאות',changes:[{key:'a_person',label:'נמען',from:'יואב',to:'דנה'}]}]}};
let cm=A.compareHTML();
ck('the comparison names both versions', cm.includes('גרסה <b>2</b>') && cm.includes('גרסה <b>3</b>'));
ck('...marks the draft as one', cm.includes('(טיוטה)'));
ck('...groups the changes', cm.includes('תנאים') && cm.includes('הרשאות'));
ck('...shows each change as from → to', cm.includes('בוצע') && cm.includes('בתהליך')
   && cm.includes('יואב') && cm.includes('דנה'));
ck('...and offers to publish the draft from there', cm.includes('Automations.publish(11)'));
A.cmp={id:11,data:{a:{version:1,is_draft:false},b:{version:1,is_draft:false},identical:true,groups:[]}};
ck('two identical versions say so', A.compareHTML().includes('אין הבדל בין הגרסאות'));
A.cmp=null;

// ── ownership: an indicator, never a status change ──
A.data.automations[0].needs_owner=true;
A.data.automations[0].owner_problem='החשבון של דנה חסום';
A.data.counts.needs_owner=1;
A.clearF(); A.view='expanded';
let og=A.manageHTML();
ck('a rule that answers to nobody says so', og.includes('דורשת שיוך בעלים'), og.slice(0,400));
ck('...with the reason', og.includes('החשבון של דנה חסום'));
ck('...and is still shown as active, not suspended',
   /am-st on[\s\S]{0,140}?פעילה/.test(og), 'the indicator changed the status');
ck('there is a tile to find them by', og.includes("Automations.tile('needs_owner')"));
A.setF('status','needs_owner');
ck('...that filters to exactly those', A.listBody().includes('Automations.menu(event,11)')
   && !A.listBody().includes('Automations.menu(event,12)'));
A.clearF(); A.setView('compact');
ck('the compact row carries it too', A.manageHTML().includes('דורשת בעלים'));
A.setView('expanded');
A.data.automations[0].needs_owner=false; A.data.counts.needs_owner=0;
ck('and it is gone once someone owns it', !A.manageHTML().includes('דורשת שיוך בעלים'));

// ── היסטוריית הפעלות: runs, skips, failures, retries ──
A.tab='history'; A.runsLoading=false;
let h=A.historyHTML();
['הופעלו','דילוגים','כשלים','ניסיונות חוזרים'].forEach(t=>
  ck(`the history can be filtered to "${t}"`, h.includes(t), h.slice(0,400)));
ck('a run that worked is marked as such', /ah-out ok/.test(h));
ck('a skip is marked as a skip, not as a failure', /ah-out skip/.test(h));
ck('a failure is marked as a failure', /ah-out fail/.test(h));
ck('a skip says why it skipped', h.includes('נמען ההתראה אינו חבר בלוח'), h);
ck('a failure carries what went wrong', h.includes('ValueError: boom'));
ck('a retry is labelled as a retry', h.includes('ניסיון חוזר'));
ck('a cascaded run says it was cascaded', h.includes('שרשור'));
ck('the item each run touched is reachable', h.includes('BoardLog.goto(8)'));
ck('the log can be exported where the data capability allows it',
   (A.data.can_export=true, A.historyHTML().includes('Automations.exportRuns()')));
ck('...and is not offered where it does not',
   (A.data.can_export=false, !A.historyHTML().includes('Automations.exportRuns()')));
ck('a run that can be retried offers it', h.includes('Automations.retry(2)'));
ck('a run that already worked does not', !h.includes('Automations.retry(1)'), h);

A.data.can_manage=false;
ck('a non-admin cannot retry anything', !A.historyHTML().includes('Automations.retry('));
A.data.can_manage=true;

A.runs=[]; A.runCounts={total:0};
ck('an empty history says so rather than showing a blank list',
   A.historyHTML().includes('האוטומציות של הלוח עוד לא הופעלו'));
A.runOutcome='failed';
ck('...and an empty FILTER says that instead',
   A.historyHTML().includes('אין הפעלות בסינון הזה'));

// ── the way in: the board header ──
ck('the board header carries an automations button',
   /id="bh-auto"[^>]*onclick="Automations\.open\(\)"/.test(src), 'no bh-auto button');
ck('...styled and hidden on a phone like the log button beside it',
   /id="bh-auto"/.test(src) && /class="bh-log" id="bh-auto"/.test(src));
ck('...with the menu entry still there for the phone',
   src.includes("'אוטומציות','Automations.open()'"));
ck('the log button no longer wears the same icon as it',
   /id="bh-log"[^>]*>\s*<i class="fa-solid fa-clock-rotate-left">/.test(src),
   'two identical ⚡ buttons in the header');


/* ── ספריית התבניות ──────────────────────────────────────────────────────
   The catalog read as a library: the nine recommended at the top under their
   own names, a search box, the six filters, and a template the board cannot
   carry — still listed, not clickable, saying what is missing. */
A.tab='create'; A.mode='templates'; A.tq=''; A.ttags=new Set();
A.trigLabels={status_changes_to:'כאשר הסטטוס משתנה ל…', item_created:'כאשר נוצר פריט חדש'};
A.libTags=[{key:'status',label:'סטטוס',count:2},{key:'date',label:'תאריך',count:0},
           {key:'assign',label:'שיוך',count:1},{key:'subitem',label:'תת־פריט',count:1},
           {key:'link',label:'קישור',count:1},{key:'notify',label:'התראה',count:0}];
A.templates=[
  {id:'status_move_group',trigger:'status_changes_to',action:'move_to_group',
   sentence:'כאשר הסטטוס משתנה ל{t_status}, העבר את הפריט לקבוצה {a_group}',
   fields:[{key:'t_status',label:'סטטוס'},{key:'a_group',label:'קבוצה'}],conditions:[],
   title:'כאשר סטטוס משתנה ל״הושלם״, העבר את הפריט לקבוצת ״הושלמו״',
   recommended:true,order:0,tags:['status'],needs:['group'],version:1,
   available:true,missing:[]},
  {id:'subitem_done_set_status',trigger:'subitem_done',action:'set_status',
   sentence:'כאשר תת־פריט הושלם, שנה את הסטטוס ל{a_status}',
   fields:[{key:'a_status',label:'סטטוס בפריט האב'}],conditions:[],
   title:'כאשר תת־פריט הושלם, עדכן שדה בפריט האב',
   recommended:true,order:4,tags:['status','subitem'],needs:[],version:1,
   available:true,missing:[]},
  {id:'created_create_and_link',trigger:'item_created',action:'create_and_link',
   sentence:'כאשר נוצר פריט חדש, צור פריט בשם {a_text} בלוח {a_board}',
   fields:[{key:'a_text',label:'שם הפריט'},{key:'a_board',label:'לוח היעד'}],conditions:[],
   title:'כאשר נוצר פריט בלוח מקור, צור פריט בלוח יעד וקשר ביניהם',
   recommended:true,order:6,tags:['link'],needs:['connect'],version:1,
   available:false,missing:['עמודת קישור בלוח']},
  {id:'created_assign_person',trigger:'item_created',action:'assign_person',
   sentence:'כאשר נוצר פריט חדש, שייך את {a_person}',
   fields:[{key:'a_person',label:'אחראי'}],conditions:[],
   title:'',recommended:false,order:9,tags:['assign'],needs:['people'],version:1,
   available:true,missing:[]},
];
let lib=A.catalogHTML();
ck('the library opens with a search box', lib.includes('חיפוש תבנית'));
ck('...and the six filters', ['סטטוס','תאריך','שיוך','תת־פריט','קישור','התראה']
   .every(x=>lib.includes(x)), lib.slice(0,400));
ck('the recommended ones come first, under their own names',
   lib.indexOf('תבניות מומלצות') >= 0
   && lib.indexOf('כאשר תת־פריט הושלם, עדכן שדה בפריט האב') > lib.indexOf('תבניות מומלצות'));
ck('a usable template opens the builder',
   lib.includes(`Automations.pick('status_move_group')`));
ck('one the board cannot carry is still listed', lib.includes('created_create_and_link')
   || lib.includes('צור פריט בשם'));
ck('...but does not open', !lib.includes(`Automations.pick('created_create_and_link')`));
ck('...and says what the board is missing',
   lib.includes('לא זמינה בלוח הזה') && lib.includes('עמודת קישור בלוח'));
ck('a blank in the sentence is shown as the thing to fill',
   lib.includes('<span class="ph">קבוצה</span>'));

A.ttags=new Set(['subitem']);
lib=A.catalogHTML();
ck('filtering by a tag drops what is not about it',
   lib.includes('כאשר תת־פריט הושלם') && !lib.includes('העבר את הפריט לקבוצה'));
ck('...and offers a way back', lib.includes('Automations.clearTemplateFilters()'));
A.ttags=new Set(['subitem','link']);
ck('two filters narrow rather than widen', A.filteredTemplates().length===0);
A.ttags=new Set();
A.tq='קבוצ';
ck('search matches the wording', A.filteredTemplates().map(x=>x.id).join()==='status_move_group');
A.tq='שאיןכזהדבר';
ck('a search with no answer says so', A.catalogHTML().includes('אין תבנית שמתאימה לחיפוש'));
A.tq=''; A.ttags=new Set();

/* the two new kinds of blank */
A.copyFields=[{key:'status',label:'סטטוס'},{key:'priority',label:'עדיפות'},
              {key:'due',label:'תאריך יעד'}];
A.building={recipe:{id:'x',fields:[{key:'a_fields',type:'fields',label:'השדות להעתקה'}]},
            values:{},conds:[],acts:[]};
A._copyInto={key:'a_fields',into:null,anchor:null};
A.toggleCopyField('priority');
A.toggleCopyField('status');
ck('a copy-fields blank holds a set, in the catalog\'s order',
   JSON.stringify(A.building.values['a_fields'].v)==='["status","priority"]',
   JSON.stringify(A.building.values['a_fields']));
ck('...and reads back as one phrase',
   A.building.values['a_fields'].label==='סטטוס, עדיפות');
A.toggleCopyField('status'); A.toggleCopyField('priority');
ck('...and emptying it leaves the blank unfilled',
   A.building.values['a_fields']===undefined);


/* ── מקור השינוי ומזהה הפעולה הקבוצתית ───────────────────────────────────
   Two different questions a run row has to answer: what KIND of change set
   this off, and was it one of many. */
A.tab='history'; A.runsLoading=false; A.runOutcome=''; A.runAuto=0; A.batch=null;
A.runCounts={total:3,ran:3,skipped:0,failed:0,retried:0};
A.data={automations:[],can_manage:true,can_export:false};
const RUN=(id,over)=>Object.assign({id,outcome:'ran',sentence:'כאשר הפריט מועבר לקבוצה «הושלמו», שנה סטטוס',
  task_id:id*10,task_title:'פריט '+id,reason:'',depth:0,event_type:'moved_to_group',
  source:'bulk',batch_id:'b1',version:1,is_retry:false,retried_at:null,
  created_at:'2026-10-22T09:00:00',can_retry:false},over||{});
A.runs=[RUN(1),RUN(2),RUN(3,{source:'item',batch_id:''})];
let hist=A.historyHTML();
ck('a bulk change says where it came from', hist.includes('פעולה מרובה'));
ck('an ordinary edit is not badged — a badge on every row is one nobody reads',
   !hist.includes('>עריכה<'));
ck('a batch can be opened from the row', hist.includes(`Automations.showBatch('b1')`));
A.showBatch('b1');
hist=A.historyHTML();
ck('...and shows only the items of that one action', hist.includes('פריט 1')
   && hist.includes('פריט 2') && !hist.includes('פריט 3'));
ck('...saying how many there were', hist.includes('2 פריטים'));
ck('...and offering the way back', hist.includes('הצג הכל'));
A.showBatch('b1');
ck('pressing it again goes back', A.batch===null);
A.runs=[RUN(9,{source:'date',batch_id:'',event_type:'due_date_passed'})];
ck('the date sweep is named as a source of its own',
   A.historyHTML().includes('תאריך יעד'));
A.runs=[RUN(8,{source:'automation',batch_id:'',depth:1})];
hist=A.historyHTML();
ck('a cascade says both that it was one and that the engine wrote it',
   hist.includes('שרשור') && hist.includes('>אוטומציה<'));


/* ── which clock the date rules keep ────────────────────────────────────── */
A.data={automations:[],can_manage:true,can_export:false,
        timezone:'Asia/Jerusalem',timezone_own:false,due_default_hour:9};
A.runs=[]; A.runCounts={}; A.batch=null;
let tzh=A.historyHTML();
ck('the log says which zone the date rules keep', tzh.includes('Asia/Jerusalem'));
ck('...and whose decision that was', tzh.includes('של הארגון'));
ck('...and what a date with no time is scheduled for', tzh.includes('09:00'));
A.data.timezone_own=true;
ck('a board that named its own says so', A.historyHTML().includes('של הלוח'));
A.data={automations:[],can_manage:true,can_export:false};
ck('a payload without one says nothing rather than guessing',
   !A.historyHTML().includes('תזמון לפי אזור הזמן'));


/* ── הפעלת אוטומציות על פריטים שכבר בלוח ─────────────────────────────────
   An import sets nothing off. A manager can approve a run over what is there
   — after being shown what it comes to — and then watch it go out in slices. */
A.tab='manage'; A.f={status:'',q:'',owner:'',creator:'',importance:'',trigger:'',action:'',last:''};
A.view='full'; A.picked=new Set(); A.bulkRes=null; A.imprt=null;
A.data={automations:RULES,can_manage:true,counts:{total:4,active:2,paused:1,draft:1},
        people:[],can_export:false};
let mg=A.manageHTML();
ck('the manage tab offers to run the rules over what is already there',
   mg.includes('Automations.importOpen()'));
A.data.can_manage=false;
ck('...to a board admin only', !A.manageHTML().includes('Automations.importOpen()'));
A.data.can_manage=true;

A.imprt={items:400,rules:2,estimated_runs:800,estimate_is_a_floor:true,
         quota:{limit:20000,used:1200,left:18800},fits:true,pending:0,
         note:'ייבוא אינו מפעיל אוטומציות — אפשר לאשר הפעלה מבוקרת בנפרד'};
mg=A.manageHTML();
ck('the preview says how many items', mg.includes('400'));
ck('...how many runs that comes to, and that it is a floor',
   mg.includes('800') && mg.includes('לפחות'));
ck('...and what is left of the month', mg.includes('18800'));
ck('...and why it was not run already', mg.includes('ייבוא אינו מפעיל'));
ck('it can be approved', mg.includes('Automations.importApprove(false)'));

A.imprt.fits=false; A.imprt.quota.left=10;
mg=A.manageHTML();
ck('over the quota it says so', mg.includes('חורגת מהמכסה'));
ck('...and asks for a deliberate second answer',
   mg.includes('Automations.importApprove(true)') && mg.includes('אשר בכל זאת'));

A.imprt={queued:400,pending:150,done:250,quota:{}};
mg=A.manageHTML();
ck('while it runs it shows how far along it is',
   mg.includes('250 מתוך 400') && mg.includes('150 ממתינים'));
ck('...and says the screen may be left', mg.includes('אפשר לעזוב את המסך'));

A.imprt={items:3,rules:0,estimated_runs:0,estimate_is_a_floor:true,
         quota:{limit:20000,used:0,left:20000},fits:true,pending:0,note:''};
mg=A.manageHTML();
ck('a board with no created-rule says there is nothing to run',
   mg.includes('אין בלוח אוטומציה שמופעלת ביצירת פריט'));
ck('...and does not offer to', mg.includes('disabled'));
A.imprt=null;


/* ── פעולות וערכים דינמיים ────────────────────────────────────────────────
   Who a notification goes to, how long a rule waits, and a value taken from
   the item rather than typed into the rule. */
A.caps={recipients:[{key:'user',label:'משתמש קבוע',takes_value:true},
                    {key:'field',label:'אחראי משדה אנשים',takes_value:true},
                    {key:'actor',label:'המשתמש שביצע את השינוי'},
                    {key:'owner',label:'בעל האוטומציה'},
                    {key:'board_admin',label:'מנהל הלוח'}],
        tokens:[{token:'item.name',label:'שם הפריט'},{token:'now.date',label:'תאריך ההפעלה'},
                {token:'field.',label:'ערך של עמודה בפריט',takes_column:true}],
        wait:{min_minutes:1,max_days:30}};
A.members=[{user_id:4,name:'יואב'},{user_id:5,name:'דנה'}];
A.building={recipe:{id:'x',fields:[]},values:{},conds:[],acts:[]};
A._recInto=null;
A.pickRecipient({},'a_person',null);
ck('the recipient offers all five kinds',
   ['משתמש קבוע','אחראי משדה אנשים','המשתמש שביצע את השינוי','בעל האוטומציה','מנהל הלוח']
     .every(x=>lastPop.includes(x)), lastPop.slice(0,200));
A.pickRecipientKind('actor');
ck('one read off the event is chosen in a single step',
   JSON.stringify(A.building.values['a_person'].v)==='{"kind":"actor"}',
   JSON.stringify(A.building.values['a_person']));
ck('...and reads as what it is', A.building.values['a_person'].label==='המשתמש שביצע את השינוי');
A.pickRecipient({},'a_person',null);
A.pickRecipientKind('user');
A.setRecipient('user',1);
ck('a named person is chosen in two',
   JSON.stringify(A.building.values['a_person'].v)==='{"kind":"user","value":5}'
   && A.building.values['a_person'].label==='דנה');

A.building.values={};
A.pickWait({},'a_days',null);
ck('a wait is offered in the words people use', lastPop.includes('שלוש שעות'));
A.setWait(180);
ck('...and stored in minutes', A.building.values['a_days'].v===180);
ck('...reading back as hours', A.building.values['a_days'].label==='3 שעות',
   A.building.values['a_days'].label);
A.setWait(1);  ck('a minute is a minute', A.building.values['a_days'].label==='דקה');
A.setWait(2880); ck('two days are two days', A.building.values['a_days'].label==='יומיים');
A.setWait(99999); ck('and thirty days is the ceiling', A.building.values['a_days'].v===43200);

const tm=A.tokenMenuHTML();
ck('a text blank offers values from the item', tm.includes('ערך מהפריט')
   && tm.includes("Automations.putToken('item.name')"));
ck('...including the board\'s own columns', tm.includes("putToken('field."));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
