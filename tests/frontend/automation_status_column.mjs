/* איזו עמודת סטטוס — the builder's side of it.

   A board has one built-in status and may carry columns of type status, each
   with a vocabulary of its own. Every `status` blank used to mean the built-in
   one, so a board that tracks its work in a "שלב" column could not fire a rule
   on it at all. Asking WHICH status is one more step, and it comes before the
   value rather than after it, because the value only means anything inside a
   vocabulary: «אושר» in "שלב תכנון" is not «אושר» in "שלב ביצוע" and is not the
   board status of that name.

   The step is only there when there is something to choose between. A board
   with no status column of its own sees exactly the screen it always saw —
   that is the requirement, not an optimisation.

   Runs the real Automations object out of index.html. Driven by
   tests/test_automation_status_column.py. */
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

/* Two status columns that share an option LABEL, because that is the case the
   ids exist for: "אושר" in one is not "אושר" in the other. */
const PLAN={id:'c_plan', type:'status', title:'שלב תכנון',
            options:[{id:'p1',label:'הוגש',color:'#00c875'},{id:'p2',label:'אושר',color:'#0073ea'}]};
const DO  ={id:'c_do',   type:'status', title:'שלב ביצוע',
            options:[{id:'d1',label:'אושר',color:'#fdab3d'}]};
/* a status column whose options carry no stable id — the engine matches an
   option by its id, so this one cannot hold a rule and must not be offered */
const OLD ={id:'c_old',  type:'status', title:'שלב ישן', options:['א','ב']};
const TXT ={id:'c_txt',  type:'text',   title:'הערה'};

const BOARD_STATUSES=[{key:'done',he:'הושלם',c:'#00c875'},
                      {key:'in_progress',he:'בתהליך',c:'#fdab3d'}];

let posted=null, toasts=[], pops=[], cols=[];

function build(which){
  posted=null; toasts=[]; pops=[]; cols=which.slice();
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    {board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{}},boards:[]},
    x=>String(x==null?'':x), m=>toasts.push(m), {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>BOARD_STATUSES.slice(), ()=>[],
    ()=>cols.slice(),
    col=>{ const c=(col&&typeof col==='object')?col:cols.find(x=>x.id===col);
           return ((c&&c.options)||[]).map(o=>typeof o==='string'
             ?{id:null,label:o,color:'#c4c4c4'}
             :{id:o.id||null,label:o.label,color:o.color||'#c4c4c4'}); },
    ()=>false, ()=>1,
    async(url,opt)=>{ if(opt&&opt.method==='POST'){ posted={url,body:JSON.parse(opt.body)}; return {}; } return {}; },
    (anchor,html)=>{ pops.push(html); },
    ()=>{}, ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelector:()=>null, querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}});
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[];
  A.data={can_manage:true,automations:[],people:[]};
  /* the catalog as the server sends it: the built-in wording, the wording for
     a named column, and which blanks may name one */
  A.acts=[{key:'set_status',label:'שנה את הסטטוס ל…',text:'שנה את הסטטוס ל{status}',
           text_col:'שנה את {col} ל{status}',
           fields:[{key:'status',type:'status',label:'סטטוס'}]},
          {key:'notify_assignees',label:'שלח התראה למשויכים',
           text:'שלח התראה למשויכים לפריט',text_col:'',fields:[]}];
  A.recipes=[{id:'status_notify_assignees',trigger:'status_changes_to',
              action:'notify_assignees',
              sentence:'כאשר הסטטוס משתנה ל{t_status}, שלח התראה למשויכים לפריט',
              sentence_parts:{trigger:'כאשר הסטטוס משתנה ל{t_status}',
                              trigger_col:'כאשר {t_status_col} משתנה ל{t_status}',
                              action:'שלח התראה למשויכים לפריט', action_col:''},
              status_fields:['t_status'],
              fields:[{key:'t_status',type:'status',label:'סטטוס'}],conditions:[]},
             /* the first recipe with a column-capable status on BOTH sides —
                the four readings of one sentence */
             {id:'status_set_status',trigger:'status_changes_to',action:'set_status',
              sentence:'כאשר הסטטוס משתנה ל{t_status}, שנה את הסטטוס ל{a_status}',
              sentence_parts:{trigger:'כאשר הסטטוס משתנה ל{t_status}',
                              trigger_col:'כאשר {t_status_col} משתנה ל{t_status}',
                              action:'שנה את הסטטוס ל{a_status}',
                              action_col:'שנה את {a_status_col} ל{a_status}'},
              status_fields:['t_status','a_status'],
              fields:[{key:'t_status',type:'status',label:'סטטוס'},
                      {key:'a_status',type:'status',label:'הסטטוס החדש'}],conditions:[]}];
  A.render=()=>{};
  A.pick('status_notify_assignees');
  return A;
}

const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
const last=()=>pops[pops.length-1]||'';

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

// ── a board with no status column of its own is untouched ─────────────────
{
  const A=build([TXT]);
  ck('a board with no status column has no source to choose', A._statusCols().length===0);
  A.pickField(EV,'t_status');
  ck('...so the status blank asks for a value straight away, as it always did',
     last().includes('הושלם') && !last().includes('על איזה סטטוס'), last());
  ck('...and the sentence is the one it always was',
     A.buildHTML().includes('כאשר הסטטוס משתנה'), '');
}

// ── a column whose options have no ids cannot hold a rule ─────────────────
{
  const A=build([OLD]);
  ck('a status column with no stable option ids is not offered',
     A._statusCols().length===0, JSON.stringify(A._statusCols()));
}

// ── with status columns, which status is asked first ──────────────────────
{
  const A=build([PLAN,DO]);
  A.pickField(EV,'t_status');
  const menu=last();
  ck('the first question is WHICH status', menu.includes('על איזה סטטוס'), menu);
  ck('...the board\'s own among them, and first',
     menu.indexOf('הסטטוס של הלוח')>0
     && menu.indexOf('הסטטוס של הלוח')<menu.indexOf('שלב תכנון'), menu);
  ck('...and each status column by its title',
     menu.includes('שלב תכנון') && menu.includes('שלב ביצוע'), menu);
}

/* Which source, by NAME. The list is the board's own status, then עדיפות —
   a board-defined vocabulary like any other, offered as a source of its own —
   then the status columns. Indexing into it made these cases depend on the
   order of a list none of them is about, and the list grew. */
const SRC=(A,label)=>{
  const i=A._statusSources().findIndex(x=>x.label===label);
  if(i<0) throw new Error('no such status source: '+label);
  return i;
};

// ── choosing a column changes both the options and the sentence ───────────
{
  const A=build([PLAN,DO]);
  A.pickField(EV,'t_status');
  /* By NAME, not by position. The list of sources is the board's own status,
     then עדיפות — which is a board-defined vocabulary like any other and is
     offered as a source of its own — then the status columns. Indexing into
     it made this test about the order of that list rather than about what
     picking a column does. */
  A.setStatusSource('t_status',SRC(A,'שלב תכנון'));
  ck('the column is kept beside the value',
     (A.building.values['t_status_col']||{}).v==='c_plan',
     JSON.stringify(A.building.values));
  A.pickField(EV,'t_status');
  const menu=last();
  ck("the value picker then offers THAT column's own vocabulary",
     menu.includes('הוגש') && menu.includes('אושר') && !menu.includes('בתהליך'), menu);
  A.setField('t_status',1);                        // אושר
  ck('...and the option is stored by its id, which survives a rename',
     A.building.values['t_status'].v==='p2', JSON.stringify(A.building.values));
  const html=A.buildHTML();
  ck('the sentence is the one about a column, not about "הסטטוס"',
     html.includes('משתנה ל') && !html.includes('כאשר הסטטוס משתנה'), '');
  ck('...and the column has a blank of its own in it',
     html.includes('data-k="t_status_col"') && html.includes('שלב תכנון'), '');
}

// ── asked once: the second click is about the value ───────────────────────
{
  const A=build([PLAN,DO]);
  A.pickField(EV,'t_status'); A.setStatusSource('t_status',SRC(A,'שלב תכנון'));
  A.pickField(EV,'t_status');
  ck('a blank already told which status goes straight to the values',
     !last().includes('על איזה סטטוס'), last());
  ck('...and carries the way back to that question',
     last().includes("pickField(event,'t_status_col')")
     && last().includes('שלב תכנון'), last());
}

// ── two columns sharing a label stay apart ────────────────────────────────
{
  const A=build([PLAN,DO]);
  A.pickField(EV,'t_status'); A.setStatusSource('t_status',SRC(A,'שלב תכנון'));
  A.pickField(EV,'t_status'); A.setField('t_status',1);          // אושר → p2
  A.pickField(EV,'t_status_col'); A.setStatusSource('t_status',SRC(A,'שלב ביצוע'));
  ck('changing the column drops the value chosen for the previous one',
     A.building.values['t_status']===undefined, JSON.stringify(A.building.values));
  A.pickField(EV,'t_status'); A.setField('t_status',0);          // אושר → d1
  ck('...and the same label in the other column is a different option',
     A.building.values['t_status'].v==='d1', JSON.stringify(A.building.values));
}

// ── back to the board's own status ────────────────────────────────────────
{
  const A=build([PLAN]);
  A.pickField(EV,'t_status'); A.setStatusSource('t_status',SRC(A,'שלב תכנון'));
  A.pickField(EV,'t_status_col'); A.setStatusSource('t_status',SRC(A,'הסטטוס של הלוח'));
  ck('choosing the board\'s own status names no column',
     A.building.values['t_status_col'].v==='', JSON.stringify(A.building.values));
  ck('...and the sentence is the built-in one again',
     A.buildHTML().includes('כאשר הסטטוס משתנה'), '');
  A.pickField(EV,'t_status');
  ck('...and the way back is still there, which is the only way back there is',
     last().includes("pickField(event,'t_status_col')")
     && last().includes('הושלם'), last());
}

// ── what reaches the server ───────────────────────────────────────────────
{
  const A=build([PLAN]);
  A.pickField(EV,'t_status'); A.setStatusSource('t_status',SRC(A,'שלב תכנון'));
  A.pickField(EV,'t_status'); A.setField('t_status',0);          // הוגש → p1
  await A.save(false);
  ck('the column is sent beside the value',
     posted && posted.body.config.t_status==='p1'
            && posted.body.config.t_status_col==='c_plan',
     JSON.stringify(posted&&posted.body));
}
{
  const A=build([PLAN]);
  A.pickField(EV,'t_status'); A.setStatusSource('t_status',SRC(A,'הסטטוס של הלוח'));
  A.pickField(EV,'t_status'); A.setField('t_status',0);          // הושלם
  await A.save(false);
  ck('and an empty one is not sent at all — empty IS the board\'s own status',
     posted && posted.body.config.t_status==='done'
            && !('t_status_col' in posted.body.config),
     JSON.stringify(posted&&posted.body));
}

// ── an extra action asks the same question ────────────────────────────────
{
  const A=build([PLAN,DO]);
  A.pickField(EV,'t_status'); A.setField('t_status',0);
  A.pickAct(EV);
  const i=(A._actOffer||[]).findIndex(x=>x.key==='set_status');
  ck('"שנה את הסטטוס" is offered as an extra action', i>=0);
  A.addAct(i);
  A.pickActValue(EV,0,'status');
  ck('an extra action asks which status too', last().includes('על איזה סטטוס'), last());
  A.setActStatusSource(0,'status',SRC(A,'שלב ביצוע'));
  A.pickActValue(EV,0,'status');
  ck("...then offers that column's options",
     last().includes('אושר') && !last().includes('בתהליך'), last());
  A.setActValue(0,'status',0);
  const html=A.moreActsHTML();
  ck('the action reads about the column it writes',
     html.includes('שלב ביצוע') && !html.includes('שנה את הסטטוס'), html);
  await A.save(false);
  const act=(posted.body.config.actions||[])[0];
  ck('and it is sent with its column',
     act && act.values.status==='d1' && act.values.status_col==='c_do',
     JSON.stringify(act));
}

// ── a status on BOTH sides: four readings of one sentence ────────────────
{
  /* `src` is the source's NAME. It used to be its position, which made every
     case below depend on the order of a list that is not what any of them is
     about — and the list grew: עדיפות is a board-defined vocabulary like any
     other and is offered as a source of its own now. */
  const pick=(A,key,src,valIdx)=>{
    A.pickField(EV,key); A.setStatusSource(key,SRC(A,src));
    A.pickField(EV,key); A.setField(key,valIdx);
  };
  const OWN='הסטטוס של הלוח';
  {
    const A=build([PLAN,DO]); A.pick('status_set_status');
    pick(A,'t_status',OWN,0); pick(A,'a_status',OWN,1);
    const h=A.buildHTML();
    ck('neither side names a column — the sentence is the built-in one',
       h.includes('כאשר הסטטוס משתנה') && h.includes('שנה את הסטטוס'), '');
  }
  {
    const A=build([PLAN,DO]); A.pick('status_set_status');
    pick(A,'t_status',OWN,0);                  // the board's own status
    pick(A,'a_status','שלב ביצוע',0);
    const h=A.buildHTML();
    ck('a column on the ACTION side only leaves the trigger half alone',
       h.includes('כאשר הסטטוס משתנה') && !h.includes('שנה את הסטטוס')
       && h.includes('data-k="a_status_col"') && h.includes('שלב ביצוע'), '');
    ck('...and the trigger keeps no column blank it never asked for',
       !h.includes('data-k="t_status_col"'), '');
  }
  {
    const A=build([PLAN,DO]); A.pick('status_set_status');
    pick(A,'t_status','שלב תכנון',1);          // → אושר
    pick(A,'a_status',OWN,0);                  // the board's own status
    const h=A.buildHTML();
    ck('a column on the TRIGGER side only leaves the action half alone',
       !h.includes('כאשר הסטטוס משתנה') && h.includes('שנה את הסטטוס')
       && h.includes('data-k="t_status_col"') && !h.includes('data-k="a_status_col"'), '');
  }
  {
    const A=build([PLAN,DO]); A.pick('status_set_status');
    pick(A,'t_status','שלב תכנון',1);          // → אושר
    pick(A,'a_status','שלב ביצוע',0);          // → אושר
    const h=A.buildHTML();
    ck('and one column on each side reads about both',
       h.includes('data-k="t_status_col"') && h.includes('data-k="a_status_col"')
       && h.includes('שלב תכנון') && h.includes('שלב ביצוע')
       && !h.includes('הסטטוס משתנה'), '');
    await A.save(false);
    const c=posted.body.config;
    ck('...and both columns reach the server, each with its own value',
       c.t_status_col==='c_plan' && c.t_status==='p2'
       && c.a_status_col==='c_do' && c.a_status==='d1', JSON.stringify(c));
  }
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
