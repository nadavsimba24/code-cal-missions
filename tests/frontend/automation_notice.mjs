/* "התראה" is a word you can press, and behind it is what the notice says.

   The notification said one thing: the rule's name, what happened, the item,
   the board, the time and a link. Right for "something happened", wrong for
   the thing people actually send — a sentence addressed to a colleague, with
   the item's own values in it.

   So the word in the sentence is a blank like the recipient beside it. What
   is checked here is the part the server cannot: that the word opens a
   TEXTAREA and not the one-line box every other text blank uses, that the
   columns are offered by TITLE (the person writing is choosing "שם הנוהל" and
   should never have to know it is col_7a1), that the two boxes on two
   different dialogs each get their own tokens, and that an empty box means
   the default notice rather than a notice that says nothing.

   Driven by tests/test_automation_notice_wording.py. */
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

const COLS=[
  {id:'col_7a1', type:'text',   title:'שם הנוהל'},
  {id:'col_b2',  type:'status', title:'שלב', options:[]},
  {id:'col_lnk', type:'connect',title:'מקושר'},
];
// what customColumns() answers, so a case can add a column mid-test
let COLS_NOW=COLS.slice();
const st={board:{id:1,name:'לוח',groups:[],my_role:'admin',col_perms:{},
                 columns:COLS.slice(),tasks:[]},boards:[]};
let modals=[], area=null, mailBox=null;
/* The notice dialog and the rule being written share ONE #modal — showModal
   rewrites it — so the only way to tell "went back to the rule" from "threw
   the rule away" is to watch whether closeModals was called and whether the
   element kept the class the automations window is sized by. */
let closed=0, modalEl=null, xBtn=null, overlayEl=null;
const fakeEl=(...cls)=>({classList:{_s:new Set(cls),add(c){this._s.add(c);},
  remove(c){this._s.delete(c);},contains(c){return this._s.has(c);}}});

function build(){
  modals=[]; COLS_NOW=COLS.slice(); closed=0;
  modalEl=fakeEl('open','modal-80'); overlayEl=fakeEl('open');
  xBtn={attr:{},setAttribute(k,v){this.attr[k]=v;}};
  area={value:'',focus(){},setSelectionRange(){}};
  mailBox={checked:false};
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe','advCell',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    ()=>{}, {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>[], ()=>[],
    ()=>COLS_NOW.slice(), ()=>[], ()=>false, ()=>1, async()=>({}),
    ()=>{}, ()=>{}, ()=>{},
    h=>modals.push(h), ()=>{closed++;},
    {getElementById:id=>(id==='au-notice'?area:(id==='au-notice-mail'?mailBox
                        :(id==='modal'?modalEl:(id==='overlay'?overlayEl:null)))),
     querySelector:sel=>(sel==='#modal .modal-x'?xBtn:null), querySelectorAll:()=>[]},
    ()=>{}, {getItem:()=>null,setItem(){}},
    t=>t, (t,f)=>null);
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[{user_id:3,name:'דנה'}];
  A.caps={fields:[],operator_labels:{},
          tokens:[{token:'item.name',label:'שם הפריט'},
                  {token:'now',label:'זמן ההפעלה'},
                  {token:'field.',label:'ערך של עמודה',takes_column:true}]};
  A.data={can_manage:true,automations:[],people:[]};
  A.acts=[{key:'notify_person', label:'שלח התראה ל…', text:'שלח {notice} ל{person}',
           fields:[{key:'person',type:'recipient',label:'נמען'},
                   {key:'notice',type:'notice',label:'התראה'}]}];
  A.recipes=[RECIPE]; A.render=()=>{};
  A.pick(RECIPE.id);
  return A;
}
const RECIPE={id:'every_days_notify_person', trigger:'every_n_days', action:'notify_person',
  sentence:'כל {t_days} ימים, שלח {a_notice} ל{a_person}',
  fields:[{key:'t_days',type:'days',label:'כל כמה ימים',min:1},
          {key:'a_person',type:'recipient',label:'נמען'},
          {key:'a_notice',type:'notice',label:'התראה'}],
  conditions:[]};

const EV={preventDefault(){},stopPropagation(){},currentTarget:{}};
let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,340):''))); };
const last=()=>modals[modals.length-1]||'';

// ── the word in the sentence is the blank ─────────────────────────────────
{
  const A=build();
  const chip=A.blankHTML({key:'a_notice',type:'notice',label:'התראה'});
  ck('an unset blank reads as the word itself', /&gt;התראה<\/button>|>התראה<\/button>/.test(chip), chip);
  ck('…and it is pressable', chip.includes("Automations.pickField(event,'a_notice')"), chip);
}

// ── which opens a textarea, not a one-line box ────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_notice');
  ck('the word opens the notice editor', last().includes('נוסח ההתראה'), last().slice(0,120));
  ck('…with room for paragraphs', last().includes('<textarea id="au-notice"'), last());
  ck('…and not the one-line value box', !last().includes('id="au-txt"'), last());
  ck('…offering to send it by mail as well', last().includes('au-notice-mail'), last());
  ck('…and the placeholder shows what one looks like, in words',
     last().includes('{{שם הפריט}}'), last());
  ck('…and never in the engine\'s own spelling',
     !last().includes('{{item.name}}'), last());
}

// ── the columns are offered by name ───────────────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_notice');
  ck('a column is offered by its title', last().includes('ערך של «שם הנוהל»'), last());
  ck('…and inserts its id, which nobody has to know',
     last().includes("putToken('field.col_7a1','au-notice')"), last());
  ck('a connect column is not offered — it has no single value',
     !last().includes('«מקושר»'), last());
  ck('and the plain tokens are there too',
     last().includes("putToken('item.name','au-notice')"), last());
}

// ── writing one, and clearing it ──────────────────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_notice');
  area.value='היי,\nלרשות: {{item.name}}\n';
  mailBox.checked=true;
  A.saveNotice();
  const v=A.building.values['a_notice'];
  ck('the wording is stored', v && v.v.text.includes('לרשות: {{item.name}}'), JSON.stringify(v));
  ck('…and so is the mail switch', v && v.v.mail===true, JSON.stringify(v));
  ck('the chip now says there IS a wording, not what it says',
     v && v.label==='התראה מותאמת', JSON.stringify(v));
}
{
  const A=build();
  await A.pickField(EV,'a_notice');
  area.value='   ';
  mailBox.checked=true;
  A.saveNotice();
  ck('an empty box means the default notice, not a notice saying nothing',
     A.building.values['a_notice']===undefined,
     JSON.stringify(A.building.values['a_notice']));
}
{
  const A=build();
  await A.pickField(EV,'a_notice');
  area.value='משהו'; A.saveNotice();
  await A.pickField(EV,'a_notice');
  ck('an existing wording offers the way back to the default',
     last().includes('clearNotice'), last());
  A.clearNotice();
  ck('…and taking it clears the blank', A.building.values['a_notice']===undefined);
}

// ── the token insertion lands in the right box ────────────────────────────
{
  const A=build();
  await A.pickField(EV,'a_notice');
  area.value='לרשות: '; area.selectionStart=area.selectionEnd=7;
  A.putToken('item.name','au-notice');
  ck('a token is inserted at the caret, in the notice box',
     area.value==='לרשות: {{שם הפריט}}', JSON.stringify(area.value));
}

/* ── the code is what is stored; the name is what she reads ───────────────
   She picked "שם הנוהל" off the menu and then had to read {{field.col_7a1}}
   back out of the box: unreadable, unverifiable, and — the part that costs —
   uneditable, because there is no way to tell at a glance whether the rule
   names the right column.

   The stored form is deliberately unchanged. {{field.col_7a1}} is what the
   engine resolves, what every rule written before now holds, and what
   survives the column being RENAMED, which is the whole reason the code and
   not the title is what is kept. */
{
  const A=build();
  ck('a column goes in by its name', A.tokensToNames('ל: {{field.col_7a1}}')==='ל: {{שם הנוהל}}',
     A.tokensToNames('ל: {{field.col_7a1}}'));
  ck('…and so does a built-in', A.tokensToNames('{{item.name}}')==='{{שם הפריט}}');
  ck('…and comes back out as the code', A.namesToTokens('ל: {{שם הנוהל}}')==='ל: {{field.col_7a1}}');
  const round='היי {{שם הפריט}} / {{שם הנוהל}} / {{זמן ההפעלה}}';
  ck('…round trip, unchanged', A.tokensToNames(A.namesToTokens(round))===round,
     A.tokensToNames(A.namesToTokens(round)));
  // the column was deleted since the rule was written: there is no name to
  // show, and a line that quietly vanished is worse than one that looks wrong
  ck('a value this board cannot name is left exactly as it is',
     A.tokensToNames('{{field.col_gone}}')==='{{field.col_gone}}');
  ck('…and survives the way back', A.namesToTokens('{{field.col_gone}}')==='{{field.col_gone}}');
}
{
  /* A name that names two things cannot stand for either. Both sides are
     dropped, not just the second: a column titled "שם הפריט" must not
     silently become the item's name, and the item's name must not silently
     become that column. */
  const A=build();
  COLS_NOW=COLS.concat([{id:'col_dup',type:'text',title:'שם הפריט'}]);
  ck('a shared name is not used for either side',
     A.tokensToNames('{{item.name}} {{field.col_dup}}')==='{{item.name}} {{field.col_dup}}',
     A.tokensToNames('{{item.name}} {{field.col_dup}}'));
  ck('…and typing it stores nothing by guesswork',
     A.namesToTokens('{{שם הפריט}}')==='{{שם הפריט}}');
  COLS_NOW=COLS.slice();
}
{
  /* A column titled with somebody else's CODE. Odd but allowed, and without
     the guard, typing {{item.name}} — the spelling anybody who has seen the
     stored form would reach for — would quietly store that column instead.
     A rule about the wrong column does not look like a failure; it looks
     like a rule about something else. */
  const A=build();
  COLS_NOW=COLS.concat([{id:'col_sneak',type:'text',title:'item.name'}]);
  ck('a column named after a code does not capture it',
     A.namesToTokens('{{item.name}}')==='{{item.name}}',
     A.namesToTokens('{{item.name}}'));
  ck('…and the built-in still reads as its own name',
     A.tokensToNames('{{item.name}}')==='{{שם הפריט}}');
  COLS_NOW=COLS.slice();
}
{
  /* The whole point, through the real dialog: she types a name, the wire
     gets the code — and renaming the column afterwards changes what she
     reads without touching what is stored. That is why the code and not the
     title is what is kept, and this is the case that proves it. */
  const A=build();
  await A.pickField(EV,'a_notice');
  area.value='לרשות: {{שם הפריט}}\nשם הנוהל: {{שם הנוהל}}';
  A.saveNotice();
  const stored=(A.building.values['a_notice']||{}).v||{};
  ck('what is saved is the code, not the name',
     stored.text==='לרשות: {{item.name}}\nשם הנוהל: {{field.col_7a1}}',
     JSON.stringify(stored.text));
  // …the admin renames the column
  COLS_NOW=[{id:'col_7a1',type:'text',title:'שם ההליך'}].concat(COLS.slice(1));
  await A.pickField(EV,'a_notice');
  ck('…so a renamed column reads by its new name, with nothing re-saved',
     last().includes('שם הנוהל: {{שם ההליך}}'), last().slice(last().indexOf('textarea'),400));
  COLS_NOW=COLS.slice();
}
{
  // an unknown name holds the save rather than storing a line that resolves
  // to nothing at three in the morning
  const A=build();
  await A.pickField(EV,'a_notice');
  area.value='{{עמודה שאין}}';
  A.saveNotice();
  ck('a value nobody can answer does not get saved',
     A.building.values['a_notice']===undefined, JSON.stringify(A.building.values['a_notice']));
}
{
  // a word nobody recognises is caught while the text is still on screen,
  // rather than coming back as a rejected save with the dialog closed
  const A=build();
  const said=[];
  ck('an unknown value is named', A.unknownTokens('{{שם הנוהל}}').length===1,
     JSON.stringify(A.unknownTokens('{{שם הנוהל}}')));
  ck('…and a real one is not', A.unknownTokens('{{field.col_7a1}} {{item.name}}').length===0);
  ck('…nor is a prefixed one', A.unknownTokens('{{field.anything}}').length===0);
  // the catalog is fetched; one that has not landed must not hold a good save
  A.caps={fields:[],operator_labels:{},tokens:[]};
  ck('with no catalog loaded nothing is called unknown',
     A.unknownTokens('{{שם הנוהל}} {{item.name}}').length===0);
}

// ── an unset notice does not hold the create button ───────────────────────
{
  const A=build();
  A.building.values['t_days']={v:7,label:'7'};
  A.building.values['a_person']={v:{kind:'user',value:3},label:'דנה'};
  const html=A.buildHTML();
  ck('a rule is complete without a wording', !/disabled title="יש להשלים/.test(html),
     html.slice(html.indexOf('btn-primary'),html.indexOf('btn-primary')+160));
}
{
  const A=build();
  A.building.values['t_days']={v:7,label:'7'};
  const html=A.buildHTML();
  ck('…but not without the recipient', /disabled title="יש להשלים/.test(html));
}

// ── an extra action's notice is its own ───────────────────────────────────
{
  const A=build();
  A.pickAct(EV);
  A.addAct((A._actOffer||[]).findIndex(x=>x.key==='notify_person'));
  await A.pickActValue(EV,0,'notice');
  ck('an extra action opens the same editor', last().includes('נוסח ההתראה'), last().slice(0,120));
  area.value='של הפעולה הנוספת'; A.saveNotice();
  const v=((A.building.acts[0]||{}).values||{}).notice;
  ck('…and stores it on that action', v && v.v.text==='של הפעולה הנוספת', JSON.stringify(v));
  ck('…and not on the sentence', A.building.values['a_notice']===undefined);
}

/* ── every way out of the dialog goes back to the rule ────────────────────
   The dialog is not a window of its own: it took the automations window over.
   So the save button called closeModals(), the whole thing shut, render()
   found the modal closed and returned without drawing anything — and the
   trigger, the conditions and every blank filled in up to that point were
   still sitting in `building` with no screen left to show them. It read as
   "pressing שמור נוסח deletes the automation". ביטול did the same. */
{
  const A=build();
  await A.pickField(EV,'a_notice');
  ck('ביטול goes back to the rule', last().includes('onclick="Automations._noticeBack()">ביטול'), last());
  ck('…and nothing in the dialog still closes the window',
     !/onclick="closeModals\(\)"/.test(last()), last());
  ck('the × of the sub-screen goes back too, not out',
     xBtn.attr.onclick==='Automations._noticeBack()', JSON.stringify(xBtn.attr));
}
{
  const A=build();
  await A.pickField(EV,'a_notice');
  let drawn=0; A.render=()=>drawn++;
  area.value='היי,\nלרשות: {{שם הפריט}}';
  A.saveNotice();
  ck('saving the wording does not shut the window', closed===0, 'closeModals ×'+closed);
  ck('…it draws the rule again', drawn===1, drawn);
  ck('…the rule being written is still the one it was',
     A.building && A.building.recipe===RECIPE, A.building&&A.building.recipe);
  ck('…the wording it just saved is on it',
     (A.building.values['a_notice']||{}).label==='התראה מותאמת');
  ck('…and the window is back at the size the automations screen uses',
     modalEl.classList.contains('modal-80'));
}
{
  const A=build();
  await A.pickField(EV,'a_notice');
  area.value='משהו'; A.saveNotice();
  await A.pickField(EV,'a_notice');
  let drawn=0; A.render=()=>drawn++;
  A.clearNotice();
  ck('«חזרה לנוסח הרגיל» also comes back to the rule', closed===0 && drawn===1,
     'closeModals ×'+closed+', render ×'+drawn);
  ck('…having cleared the blank', A.building.values['a_notice']===undefined);
}
{
  const A=build();
  await A.pickField(EV,'a_notice');
  let drawn=0; A.render=()=>drawn++;
  A._noticeBack();
  ck('going back twice in a row does not reopen anything', modals.length===1, modals.length);
  ck('…and the dialog it left is forgotten, so a stray save cannot land',
     A._noticeInto===null, A._noticeInto);
  A.saveNotice();
  ck('…a save with no dialog behind it changes nothing', drawn===1, drawn);
}

/* ── and the two doors that were not buttons ──────────────────────────────
   «שמור נוסח», ביטול and the × were each repaired one at a time. Dismissing
   is not a button, though: the page backdrop and Escape both ran closeModals
   straight, which shut the automations window and read as the half-built rule
   being thrown away — the same complaint, through the openings the repair did
   not cover. Both give the open sub-screen first refusal now.

   dismissModal lives outside Automations, so it is lifted out of the source
   and run against a stub rather than through build(). */
{
  const fn = /function dismissModal\(\)\{[\s\S]*?\n\}/.exec(src);
  ck('there is one place that decides what a dismissal means', !!fn);
  ck('the page backdrop asks it rather than closing outright',
     /id="overlay" onclick="dismissModal\(\)"/.test(src),
     (/id="overlay" onclick="[^"]*"/.exec(src)||[])[0]);
  ck('…and so does Escape',
     /Automations\.closeTimeline\(\); return; \}\n  dismissModal\(\);/.test(src));

  /* Guarded rather than left to throw: a harness that dies names nothing, and
     the whole point of these lines is to say which door was left open. */
  const run = !fn ? () => ({back:-1, shut:-1}) : (notice) => {
    let back=0, shut=0;
    const f = new Function('window','closeModals', fn[0]+' return dismissModal;')
      ({Automations:{_noticeInto:notice, _noticeBack(){back++;}}}, ()=>{shut++;});
    f(); return {back, shut};
  };
  let r = run({key:'a_notice',into:null});
  ck('with the notice editor open a dismissal goes back to the rule',
     r.back===1 && r.shut===0, JSON.stringify(r));
  r = run(null);
  ck('…and with nothing in front of it, it closes as it always did',
     r.back===0 && r.shut===1, JSON.stringify(r));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
