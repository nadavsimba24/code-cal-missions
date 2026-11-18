/* "מיפוי השדות" is a word you can press, and behind it are the two boards.

   The blank used to answer "מיפוי שדות נערך דרך ה-API בשלב זה". For anybody
   without a terminal that meant the only cross-board rule they could write
   offered five fixed built-ins — סטטוס, עדיפות, תאריך יעד, אחראים, תיאור —
   however many columns the two boards actually had between them.

   What is checked here is the part the server cannot: that the blank opens a
   table of PAIRS, that each side is read off its own board (the source list
   from this board's capabilities, the target list fetched for the board the
   rule writes into), that the target side offers only what can hold what the
   source side holds, that a half-filled row is refused instead of quietly
   dropped, and that the dialog comes back to the half-built rule rather than
   closing over it.

   And beside it, the one-line text blank: a token picked off «ערך מהפריט» is
   shown by name and stored as the code. That split is the whole of the bug it
   was reported for — «{{שם הפריט}}» stored verbatim, the engine's TOKEN_RE
   matching ASCII and nothing else, and an item created with the token for a
   name.

   Driven by tests/test_cross_board_columns_are_the_boards_own.py. */
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

/* The SOURCE board — the one the rule lives on. Its columns reach the builder
   through automation-capabilities, which is also where their `kind` comes
   from: the screen must not have an opinion of its own about what a column
   type is, or it would offer a pair the engine then refuses. */
const SRC_COLS=[
  {id:'col_ref',  type:'text',   title:'מספר הפנייה', kind:'text'},
  {id:'col_when', type:'date',   title:'תאריך פתיחה', kind:'date'},
  {id:'col_lnk',  type:'connect',title:'מקושר',       kind:'text'},
  {id:'col_mir',  type:'mirror', title:'מראה',        kind:'text'},
];
/* …and the TARGET board's, which is a different board with different ids —
   the difference that makes this a mapping rather than a list of checkboxes. */
const DST_COLS=[
  {id:'col_ack',  type:'text',  title:'מספר אסמכתא', kind:'text'},
  {id:'col_due2', type:'date',  title:'יעד לטיפול',  kind:'date'},
  {id:'col_cost', type:'number',title:'עלות',        kind:'number'},
];
const BUILTINS=[{key:'title',label:'שם הפריט',kind:'text'},
                {key:'status',label:'סטטוס',kind:'status'},
                {key:'due',label:'תאריך יעד',kind:'date'}];

const st={board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{},
                 columns:SRC_COLS.slice(),tasks:[]},boards:[]};
let modals=[], pops=[], toasts=[], asked=[], host=null, txt=null;
let closed=0, modalEl=null, xBtn=null, overlayEl=null, htmlSet='';
const fakeEl=(...cls)=>({classList:{_s:new Set(cls),add(c){this._s.add(c);},
  remove(c){this._s.delete(c);},contains(c){return this._s.has(c);}}});

function build(){
  modals=[]; pops=[]; toasts=[]; asked=[]; closed=0; htmlSet='';
  modalEl=fakeEl('open','modal-80'); overlayEl=fakeEl('open');
  xBtn={attr:{},setAttribute(k,v){this.attr[k]=v;}};
  // the rows live in #au-map-rows and are rewritten in place rather than by
  // reopening the dialog, so the selects keep their scroll and their focus
  host={id:'au-map-rows'};
  txt={value:'',focus(){},select(){},selectionStart:null,selectionEnd:null};
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe','advCell','setHTML',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    m=>toasts.push(m), {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>[], ()=>[],
    ()=>SRC_COLS.slice(), ()=>[], ()=>false, ()=>1,
    async(u)=>{ asked.push(u);
                if(/automation-capabilities/.test(u)) return {columns:DST_COLS.slice()};
                return {}; },
    (anchor,h)=>pops.push(h), ()=>{}, ()=>{},
    h=>modals.push(h), ()=>{closed++;},
    {getElementById:id=>(id==='au-map-rows'?host
                        :(id==='au-txt'?txt
                        :(id==='modal'?modalEl:(id==='overlay'?overlayEl:null)))),
     querySelector:sel=>(sel==='#modal .modal-x'?xBtn:null), querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}},
    t=>t, (t,f)=>null,
    (el,h)=>{htmlSet=h;});
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[];
  A.caps={fields:[],operator_labels:{},columns:SRC_COLS.slice(),
          map:{max_pairs:20,builtins:BUILTINS},
          tokens:[{token:'item.name',label:'שם הפריט'},
                  {token:'now',label:'זמן ההפעלה'},
                  {token:'field.',label:'ערך של עמודה',takes_column:true}]};
  A.data={can_manage:true,automations:[],people:[]};
  A.acts=[]; A.recipes=[RECIPE]; A.render=()=>{};
  A.pick(RECIPE.id);
  // the target board is chosen before the mapping is — the mapping question
  // has no meaning until there are two boards to ask it about
  A.building.values['a_board']={v:9,label:'לוח היעד',color:''};
  return A;
}
const RECIPE={id:'status_create_mapped_and_link', trigger:'status_changes_to',
  action:'create_mapped_and_link',
  sentence:'כאשר הסטטוס משתנה ל{t_status}, צור פריט בשם {a_text} בקבוצה {a_target_group} '
          +'בלוח {a_board}, מפה {a_map} וקשר אותו לפריט המקור בעמודה {a_connect}',
  fields:[{key:'t_status',type:'status',label:'סטטוס'},
          {key:'a_connect',type:'connect',label:'עמודת הקישור'},
          {key:'a_board',type:'board',label:'לוח היעד'},
          {key:'a_target_group',type:'target_group',label:'הקבוצה בלוח היעד'},
          {key:'a_text',type:'text',label:'שם הפריט החדש'},
          {key:'a_map',type:'map',label:'מיפוי השדות'}],
  conditions:[]};

const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,340):''))); };
const last=()=>modals[modals.length-1]||'';

// ── הבלנק נפתח לטבלה, לא להודעה שתלך ל-API ───────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_map');
  ck('the blank opens the mapping editor', last().includes('מיפוי השדות'), last().slice(0,140));
  ck('…and nobody is sent to a terminal',
     !toasts.some(t=>/API/.test(t)), JSON.stringify(toasts));
  ck('…with a side for each board', last().includes('השדה בפריט המקור')
     && last().includes('השדה בלוח היעד'), last());
  ck('the target board\'s own columns were fetched',
     asked.some(u=>/automation-capabilities\?board_id=9/.test(u)), JSON.stringify(asked));
}

// ── בלי לוח יעד אין בכלל שאלה ─────────────────────────────────────────────
{
  const A=build();
  delete A.building.values['a_board'];
  await A.pickField(EV,'a_map');
  ck('without a target board the question is not asked yet',
     modals.length===0 && toasts.join().includes('בחר תחילה את לוח היעד'),
     JSON.stringify(toasts));
}

// ── כל צד מהלוח שלו ───────────────────────────────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_map');
  ck('the source side offers this board\'s column', htmlSet.includes('מספר הפנייה'), htmlSet);
  ck('…and the target side the other board\'s', htmlSet.includes('מספר אסמכתא'), htmlSet);
  ck('…which is a column this board does not have',
     !SRC_COLS.some(c=>c.title==='מספר אסמכתא'));
  ck('the built-ins are on both sides', (htmlSet.match(/שם הפריט/g)||[]).length>=2, htmlSet);
  ck('a connect column is not offered — the engine will not write one',
     !htmlSet.includes('מקושר'), htmlSet);
  ck('…nor a mirror, which is somebody else\'s value',
     !htmlSet.includes('>מראה<'), htmlSet);
}

// ── ורק מה שיכול להחזיק את מה שנבחר ───────────────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_map');
  A.setMapSide(0,'from','col_when');            // a date on the source board
  ck('a date offers the other board\'s date', htmlSet.includes('יעד לטיפול'), htmlSet);
  ck('…and not its number', !htmlSet.includes('עלות'), htmlSet);
  ck('…nor its text', !htmlSet.includes('מספר אסמכתא'), htmlSet);
}
{
  const A=build();
  await A.pickField(EV,'a_map');
  A.setMapSide(0,'from','col_ref');
  A.setMapSide(0,'to','col_ack');
  A.setMapSide(0,'from','col_when');            // …and then changes her mind
  ck('a target the new source cannot reach is let go rather than carried',
     A._mapDraft[0].to==='', JSON.stringify(A._mapDraft));
}

// ── שורות נוספות, ושורה שנמחקה ────────────────────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_map');
  ck('one empty row to start with', A._mapDraft.length===1, JSON.stringify(A._mapDraft));
  ck('…and a way to add another', htmlSet.includes('addMapPair'), htmlSet);
  A.addMapPair();
  ck('which adds one', A._mapDraft.length===2);
  A.dropMapPair(1); A.dropMapPair(0);
  ck('removing the last row leaves one to fill in, not an empty dialog',
     A._mapDraft.length===1, JSON.stringify(A._mapDraft));
}

// ── מה שנשמר ──────────────────────────────────────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_map');
  A.setMapSide(0,'from','col_ref'); A.setMapSide(0,'to','col_ack');
  A.addMapPair();
  A.setMapSide(1,'from','title');   A.setMapSide(1,'to','col_due2');
  A.saveMap();
  ck('a pair the engine cannot carry is refused where it was written',
     toasts.join().includes('אינם מסוג תואם'), JSON.stringify(toasts));
  ck('…and the blank is not filled with it',
     A.building.values['a_map']===undefined, JSON.stringify(A.building.values['a_map']));
}
{
  const A=build();
  await A.pickField(EV,'a_map');
  A.setMapSide(0,'from','col_ref'); A.setMapSide(0,'to','col_ack');
  A.addMapPair(); A.setMapSide(1,'from','col_when');
  A.saveMap();
  ck('a row with one side filled is a question somebody did not finish',
     toasts.join().includes('שני הצדדים'), JSON.stringify(toasts));
}
{
  const A=build();
  await A.pickField(EV,'a_map');
  A.setMapSide(0,'from','col_ref'); A.setMapSide(0,'to','col_ack');
  A.addMapPair(); A.setMapSide(1,'from','title'); A.setMapSide(1,'to','col_ack');
  A.saveMap();
  ck('the same target twice is refused', toasts.join().includes('פעמיים'),
     JSON.stringify(toasts));
}
{
  const A=build();
  await A.pickField(EV,'a_map');
  A.setMapSide(0,'from','col_ref'); A.setMapSide(0,'to','col_ack');
  A.addMapPair();
  A.setMapSide(1,'from','col_when'); A.setMapSide(1,'to','col_due2');
  A.saveMap();
  const v=A.building.values['a_map'];
  ck('the pairs are stored as the engine reads them',
     JSON.stringify((v||{}).v)===JSON.stringify([{from:'col_ref',to:'col_ack'},
                                                 {from:'col_when',to:'col_due2'}]),
     JSON.stringify(v));
  ck('the chip says how many, not what they are', (v||{}).label==='2 שדות',
     JSON.stringify(v));
  ck('…and it comes back to the rule rather than closing over it',
     closed===0 && modalEl.classList.contains('modal-80'));
}
{
  const A=build();
  await A.pickField(EV,'a_map');
  A.saveMap();
  ck('an empty table leaves the question open instead of storing nothing',
     A.building.values['a_map']===undefined,
     JSON.stringify(A.building.values['a_map']));
}
{
  // reopening it finds the pairs where they were left
  const A=build();
  A.building.values['a_map']={v:[{from:'col_ref',to:'col_ack'}],label:'שדה אחד',color:''};
  await A.pickField(EV,'a_map');
  ck('a saved mapping reopens as itself',
     A._mapDraft.length===1 && A._mapDraft[0].to==='col_ack',
     JSON.stringify(A._mapDraft));
  ck('…and one pair reads as one field', A.mapLabel([{from:'a',to:'b'}])==='שדה אחד');
}

// ── והדלת האחורית: Escape ורקע ────────────────────────────────────────────
{
  const i=src.indexOf('function dismissModal(){');
  const fn=src.slice(i,src.indexOf('\n}',i)+2);
  const run=(notice,map)=>{
    let back=0, mapBack=0, shut=0;
    new Function('window','closeModals', fn+' return dismissModal;')
      ({Automations:{_noticeInto:notice,_mapInto:map,
                     _noticeBack(){back++;},_mapBack(){mapBack++;}}}, ()=>{shut++;})();
    return {back,mapBack,shut};
  };
  let r=run(null,{key:'a_map',into:null});
  ck('with the mapping open a dismissal goes back to the rule',
     r.mapBack===1 && r.shut===0, JSON.stringify(r));
  r=run(null,null);
  ck('…and with nothing in front of it, it closes as it always did',
     r.mapBack===0 && r.shut===1, JSON.stringify(r));
}

/* ── ולידה: הערך הדינמי בשם הפריט החדש ───────────────────────────────────
   The reported bug. She picks «שם הפריט» off «ערך מהפריט», the box shows
   {{שם הפריט}} — and until now that is exactly what was stored, so the rule
   created an item called "{{שם הפריט}}" instead of one named after the item
   that set it off. */
{
  const A=build();
  await A.pickField(EV,'a_text');
  ck('the text blank offers the values from the item',
     (pops[pops.length-1]||'').includes('ערך מהפריט'), pops[pops.length-1]);
  txt.value='בדיקה ל'; txt.selectionStart=txt.selectionEnd=7;
  A.putToken('item.name','au-txt');
  ck('…and inserting one writes the NAME into the box',
     txt.value==='בדיקה ל{{שם הפריט}}', JSON.stringify(txt.value));
  A.setText('a_text');
  const v=A.building.values['a_text'];
  ck('what is stored is the code the engine resolves',
     (v||{}).v==='בדיקה ל{{item.name}}', JSON.stringify(v));
  ck('…and what she goes on reading is the name',
     (v||{}).label==='בדיקה ל{{שם הפריט}}', JSON.stringify(v));
}
{
  const A=build();
  await A.pickField(EV,'a_text');
  txt.value='היי {{אין כזה ערך}}';
  A.setText('a_text');
  ck('a value nobody can answer is refused while the caret is still in it',
     A.building.values['a_text']===undefined && toasts.join().includes('אין ערך בשם'),
     JSON.stringify(toasts));
}
{
  // and the rule reopened for editing reads its own stored codes back by name
  const A=build();
  const cell=A._cellFor({key:'a_text',type:'text'},'בדיקה ל{{item.name}}',{},{});
  ck('a stored token is shown by its name when the rule is reopened',
     cell.label==='בדיקה ל{{שם הפריט}}', JSON.stringify(cell));
  ck('…while the code is what stays on the wire',
     cell.v==='בדיקה ל{{item.name}}', JSON.stringify(cell));
}

/* ── ומי שעומד מול הקיר הישן שומע לאן ללכת ───────────────────────────────
   The older cross-board rule goes on offering the five built-ins, and it has
   to: its action can carry nothing else, and a rule somebody already built is
   not re-asked a question it was never asked. What it should not do is leave
   the person who came looking for «מספר הפנייה» staring at five fields that
   are not it with nothing saying why — the template that CAN say it is one
   line away in the library. */
{
  const A=build();
  A.copyFields=[{key:'status',label:'סטטוס'},{key:'due',label:'תאריך יעד'}];
  A.building.recipe={id:'status_create_in_group_and_link',
                     action:'create_in_group_and_link',fields:[]};
  A.pickCopyFields({},'a_fields');
  const p=pops[pops.length-1]||'';
  ck('the five are still what that rule offers', p.includes('toggleCopyField'), p);
  ck('…and the blank names the pairing that sits in the same sentence',
     p.includes('מיפוי עמודות'), p);
}
{
  // …and a copy that stays on one board has no second column list to point at
  const A=build();
  A.copyFields=[{key:'status',label:'סטטוס'}];
  A.building.recipe={id:'link_added_copy_to_linked',action:'copy_to_linked',fields:[]};
  A.pickCopyFields({},'a_fields');
  const p=pops[pops.length-1]||'';
  ck('a same-board copy is not pointed at a pairing it does not have',
     !p.includes('מיפוי עמודות'), p);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
