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
const stored={};
const localStorage={getItem:k=>stored[k]||null,setItem:(k,v)=>{stored[k]=String(v);}};
const A=new Function('st','esc','toast','BoardLog','fdatetime','avatarInner','boardStatusList',
  'boardPriorityList','customColumns','meId','api','openCellPop','closeCellPops','askConfirm',
  'showModal','closeModals','document','renderView','localStorage',
  grabConst('Automations')+' return Automations;')(
  st, x=>String(x==null?'':x), ()=>{}, {ago:()=>'עכשיו',goto(){}}, ()=>'01/01/2026',
  ()=>'', ()=>[], ()=>[], ()=>[], ()=>1, async()=>({}), ()=>{}, ()=>{}, ()=>{},
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
 ['בדיקה על פריט','Automations.startTest(11)'],['צפייה בגרסאות','Automations.versions(11)'],
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
A.viewing={id:11,a:RULES[0],rows:null};
ck('the versions panel waits rather than showing an empty history', A.versionsHTML().includes('spin'));
A.closePanel();

// a test on one item
A.testing={id:11,a:RULES[0],q:'',items:[{id:7,title:'תיקון מדרכה'}],result:null,busy:false};
let ts=A.testHTML();
ck('the test screen promises the run will be undone',
   ts.includes('תרוץ באמת') && ts.includes('מיד תבוטל'), ts.slice(0,600));
ck('...and offers the board\'s own items to run it on', ts.includes('Automations.runTest(7)'));
A.testing.result={outcome:'skipped',task_title:'תיקון מדרכה',reason:'נמען ההתראה אינו חבר בלוח'};
ts=A.testHTML();
ck('a test that would do nothing says so, with the reason',
   ts.includes('הכלל לא היה עושה דבר') && ts.includes('נמען ההתראה אינו חבר בלוח'), ts.slice(0,900));
A.testing.result={outcome:'ran',task_title:'תיקון מדרכה',reason:''};
ck('a test that would work says that instead', A.testHTML().includes('הכלל היה מתבצע'));
A.closePanel();

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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
