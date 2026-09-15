/* Bulk actions on a board's automations, and the organisational view — run out
   of the real objects in index.html. Driven by tests/test_automations_org_ui.py. */
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

let POP='';                        // what the last popup was asked to render
let PAINT='';                      // what the org tab painted
const fakeBody={ set innerHTML(v){ PAINT=v; }, get innerHTML(){ return PAINT; } };
const st={board:{id:7,name:'לוח',groups:[],my_role:'admin'},boards:[]};

const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','avatarInner',
  'boardStatusList','boardPriorityList','customColumns','meId','api','openCellPop','closeCellPops',
  'askConfirm','showModal','closeModals','document','renderView','localStorage',
  grabConst('Automations')+' return Automations;')(
  st, x=>String(x==null?'':x), ()=>{}, {ago:()=>'עכשיו',goto(){}}, ()=>'01/01/2026', ()=>'01/01/2026',
  ()=>'', ()=>[], ()=>[], ()=>[], ()=>1, async()=>({}), (a,h)=>{POP=h;}, ()=>{}, ()=>{}, ()=>{}, ()=>{},
  {getElementById:()=>null}, ()=>{}, {getItem:()=>null,setItem(){}});

const RULE=(id,name,extra)=>({id,status:'active',is_active:true,trigger:'item_created',
  action:'set_status',sentence:'כאשר נוצר פריט חדש, שנה את הסטטוס ל«בתהליך»',name,display_name:name,
  description:'',importance:'normal',run_order:id,owner_id:4,owner_name:'יואב',owner_is_creator:true,
  created_by:4,created_by_name:'יואב',run_count:2,fail_count:0,skip_count:0,success_rate:100,
  last_outcome:'ran',needs_attention:false,...extra});
A.data={can_manage:true,
        automations:[RULE(11,'א'),RULE(12,'ב',{status:'paused',is_active:false})],
        people:[{id:4,name:'יואב',is_board_admin:true},{id:5,name:'דנה',is_board_admin:false}],
        counts:{total:2,active:1,paused:1,paused_error:0,draft:0,deleting:0,needs_attention:0}};
A.trigLabels={item_created:'כאשר נוצר פריט חדש'}; A.actLabels={set_status:'שנה את הסטטוס ל…'};
A.tab='manage'; A.clearF(); A.sort='order'; A.view='expanded'; A.picked=new Set(); A.bulkRes=null;

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── selecting ───────────────────────────────────────────────────────────────
let m=A.manageHTML();
ck('every rule can be picked', (m.match(/au-pick-box/g)||[]).length===2);
ck('nothing is offered before anything is picked', !m.includes('au-bulk'));
ck('there is a select-all', m.includes('Automations.pickAll()'));

A.picked=new Set([11]); m=A.manageHTML();
ck('picking one shows the bar with the count', m.includes('au-bulk') && m.includes('1 נבחרו'));
['השהה','הפעל לאחר בדיקת תקינות','העבר בעלות','ייצוא הרשימה'].forEach(x=>
  ck(`the bar offers "${x}"`, m.includes(x)));
const bar=m.slice(m.indexOf('au-bulk'), m.indexOf('au-bulk')+1100);
ck('...and offers no bulk delete', !/מחק|למחוק|delete/i.test(bar), bar.slice(0,200));

A.pickAll(); ck('select-all picks every shown rule', A.picked.size===2);
A.pickAll(); ck('...and clears them when all are picked', A.picked.size===0);
A.picked=new Set([11,12]);
ck('the count follows the selection', A.manageHTML().includes('2 נבחרו'));
A.setTab('history'); ck('leaving the tab drops the selection', A.picked.size===0);
A.setTab('manage');

// a rule the filter hides is not picked by "select all"
A.picked=new Set(); A.setF('status','paused'); A.pickAll();
ck('select-all takes what is shown, not what is filtered out',
   A.picked.size===1 && A.picked.has(12), [...A.picked].join());
A.clearF(); A.picked=new Set();

A.data.can_manage=false;
ck('a viewer cannot select anything', !A.manageHTML().includes('au-pick-box'));
ck('...and gets no bulk bar even with a stale selection',
   (A.picked=new Set([11]), !A.manageHTML().includes('au-bulk')));
A.data.can_manage=true;

// ── handing ownership over ──────────────────────────────────────────────────
A.picked=new Set([11]);
A.bulkOwner({preventDefault(){},stopPropagation(){},currentTarget:{}});
ck('the owner menu offers a board admin', POP.includes('יואב') && POP.includes("Automations.bulk('transfer',4)"), POP);
ck('...and not an editor, which the server refuses anyway', !POP.includes('דנה'), POP);
ck('...and says what the rule is', POP.includes('מנהל לוח מורשה'));

// ── the results, one line per rule ──────────────────────────────────────────
A.bulkRes={action:'activate',affected:2,ok:1,failed:1,results:[
  {id:11,name:'א',ok:true,message:'הופעלה'},
  {id:12,name:'ב',ok:false,message:'דנה אינו חבר בלוח'}]};
const res=A.bulkResHTML();
ck('every rule gets its own line', (res.match(/au-res-row/g)||[]).length===2);
ck('the one that worked is marked as such', res.includes('fa-circle-check ok'));
ck('the one that did not says why',
   res.includes('fa-circle-xmark no') && res.includes('אינו חבר בלוח'));
ck('the heading counts both', res.includes('(1 מתוך 2)'), res.slice(0,140));
ck('the results appear in the manage tab', A.manageHTML().includes('au-res-row'));
A.pickClear();
ck('closing the results clears them', !A.manageHTML().includes('au-res-row'));

// ── the organisational view ─────────────────────────────────────────────────
const S=new Function('st','esc','toast','BoardLog','fdatetimeY','api','meId','openCellPop',
  'closeCellPops','askConfirm','showModal','closeModals','document','openBoard','Automations',
  'mobileBlocked','hasCap','envIconHTML','avatarInner','fdatetime',
  grabConst('SysAdmin')+' return SysAdmin;')(
  st, x=>String(x==null?'':x), ()=>{}, {ago:()=>'לפני יום'}, ()=>'01/01/2026', async()=>({}),
  ()=>1, (a,h)=>{POP=h;}, ()=>{}, ()=>{}, h=>{POP=h;}, ()=>{}, {getElementById:()=>fakeBody},
  async()=>{}, {open(){}}, ()=>false, ()=>true, ()=>'', ()=>'', ()=>'01/01/2026');

S.auto={rows:[{id:1,board_id:7,board_name:'לוח תשתיות',department_name:'אגף הנדסה',
   display_name:'כלל',sentence:'כאשר נוצר פריט חדש, שייך את «דנה»',status:'active',
   importance:'critical',owner_name:'דנה',ownerless:false,last_run_at:'2026-09-14T09:00:00',
   stale:false,stale_days:1,success_rate:80,fail_count:1,needs_attention:true},
  {id:2,board_id:8,board_name:'לוח גינון',department_name:'אגף שפ״ע',display_name:'כלל יתום',
   sentence:'כאשר נוצר פריט חדש, שנה סטטוס',status:'paused',importance:'low',owner_name:'',
   ownerless:true,last_run_at:null,stale:true,stale_days:null,success_rate:null,
   fail_count:0,needs_attention:false}],
 totals:{total:9,active:5,paused:2,draft:2,ownerless:3,needs_attention:1,stale:4,boards:3,failures:7},
 quota:{period:'2026-09',used:1200,limit:20000,percent:6,ran:1000,failed:20,skipped:180,
        top_boards:[{board_id:7,board_name:'לוח תשתיות',runs:900}]},
 freezes:[],boards:[{id:7,name:'לוח תשתיות'}],departments:[{id:1,name:'אגף הנדסה'}],
 environments:[{id:1,name:'סביבה'}],owners:[{id:5,name:'דנה'}],stale_days:90};
S.autoF={board_id:0,department_id:0,environment_id:0,owner_id:0,status:'',flag:'',q:''};
S.paintAutos();
const o=PAINT;
[['סה״כ','9'],['פעילות','5'],['מושהות','2'],['ללא בעלים','3'],['דורשות טיפול','1']].forEach(([he,n])=>
  ck(`the head counts ${he}`, new RegExp('<b>'+n+'</b><span>'+he).test(o), o.slice(0,900)));
ck('there is a tile for what has not run in 90 days', o.includes('לא הופעלו 90 ימים'));
ck('a row names its board and its organisational unit',
   o.includes('לוח תשתיות') && o.includes('אגף הנדסה'));
ck('a rule with no owner is called out', o.includes('ללא בעלים'));
ck('a rule that never ran says so', o.includes('טרם הופעלה'));
ck('failures are shown per rule', /oa-num bad">1</.test(o), o.slice(o.indexOf('oa-num bad')-40,o.indexOf('oa-num bad')+40));
ck('the quota is shown against its limit',
   o.includes('צריכת מכסה') && o.includes('20,000') && o.includes('1,200'), o.slice(0,1200));
ck('...with the boards consuming the most of it', o.includes('לוח תשתיות (900)'));
['כל הלוחות','כל היחידות הארגוניות','כל הסביבות','כל הבעלים','כל הסטטוסים'].forEach(f=>
  ck(`the list can be narrowed by "${f}"`, o.includes(f)));
ck('the filtered list can be exported', o.includes('SysAdmin.exportAutos()'));
ck('an emergency stop is reachable', o.includes('SysAdmin.freezeDialog()'));

// a freeze in force is stated at the top, with its reason and who imposed it
S.auto.freezes=[{id:3,scope:'org',board_name:null,reason:'תקלה רוחבית',
                 created_by_name:'שלי',created_at:'2026-09-14T09:00:00'}];
S.paintAutos();
ck('a freeze in force is announced', PAINT.includes('האוטומציות בכל הארגון מושהות'));
ck('...with its reason and who imposed it', PAINT.includes('תקלה רוחבית') && PAINT.includes('שלי'));
ck('...and can be released from there', PAINT.includes('SysAdmin.release(3)'));
S.auto.freezes=[{id:4,scope:'board',board_name:'לוח גינון',reason:'לופ',created_by_name:'שלי',
                 created_at:'2026-09-14T09:00:00'}];
S.paintAutos();
ck('a board freeze names the board', PAINT.includes('האוטומציות בלוח לוח גינון מושהות'));

// the dialog asks for a reason, and for a second confirmation when it is org-wide
S.freezeDialog();
ck('the freeze dialog asks for a reason', POP.includes('fz-reason') && POP.includes('Audit'));
ck('...offers one board or the whole organisation',
   POP.includes('value="board"') && POP.includes('value="org"'));
ck('...carries a second confirmation for the organisation', POP.includes('fz-ok') &&
   POP.includes('אישור נוסף להשבתה ארגונית'));
ck('...and says it does not expire by itself', POP.includes('אינה מתבטלת מעצמה'));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
