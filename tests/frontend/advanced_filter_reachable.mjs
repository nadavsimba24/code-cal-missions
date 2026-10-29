/* The advanced builder, reached from the foot of the filter panel.

   It had a button of its own in the toolbar, beside "סינון". Two buttons side
   by side were two doors into one filter — the panel and the builder edit the
   same condition tree — so the toolbar button is gone and the only way in is
   "מעבר לסינון מתקדם" at the foot of the panel.

   That makes this the check that nothing was lost with the button: the builder
   still opens, edits, applies and clears, and what it writes is what the panel
   reads back — and the other way round.

   Driven by tests/test_filter_by_column.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i = src.indexOf('{', m.index), d = 0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index, j+1);} }
  throw new Error('unbalanced: '+name);
}
const konst = name => {
  const m = new RegExp(`^const ${name}\\s*=[\\s\\S]*?;$`, 'm').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return m[0];
};
/* The Adv object itself, verbatim. */
function advObject(){
  const i = src.indexOf('const Adv = {');
  let d = 0;
  for(let j=src.indexOf('{', i); j<src.length; j++){
    if(src[j]==='{')d++; else if(src[j]==='}'){ d--; if(!d) return src.slice(i, j+1); }
  }
  throw new Error('unbalanced: Adv');
}

/* One box as it stands in the dialog: the outline, the select inside it that
   holds the value, and the chevron the pointer is now allowed to hit. */
function boxOf(options, sel_i, log){
  const options2 = options.map((o,i)=>({
    value:o.v, textContent:o.label, selected:i===sel_i,
    getAttribute:k=>(k in o ? o[k] : null)}));
  const sel = {options:options2, value:options[sel_i].v,
               dispatchEvent(e){ log.fired=(log.fired||[]).concat(e.type+':'+sel.value); }};
  return {offsetWidth:230, querySelector:q=>q==='select'?sel:null, _sel:sel};
}
const ev = () => ({target:null, preventDefault(){}, stopPropagation(){}});

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+JSON.stringify(x):''))); };

function world(){
  const st = {
    board:{id:1, col_perms:{}, members:[{id:3}],
      columns:[{id:'col_a', type:'status', title:'שלב',
                options:[{label:'בעבודה',color:'#fdab3d'},{label:'תקוע',color:'#e2445c'}]}],
      tasks:[]},
    users:[{id:3,name:'דנה'}], me:{id:3}, colSort:null,
    filters:{q:'',people:[],status:'',priority:'',sort:'',links:{col:'',mode:'',item:0},adv:null,advIds:null},
  };
  const log = {modals:0, closed:0, asked:0, toasts:[], redraws:0, quick:0};
  // the filter panel's control in the toolbar, open or not
  log.ctl = {_open:false, classList:{
    contains:c=>c==='open'&&log.ctl._open,
    add(c){ if(c==='open')log.ctl._open=true; },
    remove(c){ if(c==='open')log.ctl._open=false; }}};
  const names = ['advFields','advColHidden','customColumns','advCount','advPicked','advPickedAll',
                 'advSetPicked','advToggle','advFilterRoot','advLegacyPicks','advDropLegacy',
                 'advChoices','advPersonLabel','boardPeople','statusColOpts','advToAst'];
  const body = names.map(grab).join('\n') + '\n'
    + konst('advOwnGroup') + '\n' + konst('advField') + '\n' + konst('ADV_OPS') + '\n'
    + konst('ADV_KINDS') + '\n' + konst('advOps') + '\n' + konst('advOpArity') + '\n'
    + `const ADV_DATES=[['today','היום']];\n`;
  const Adv = new Function(
    'st','esc','showModal','closeModals','document','refreshToolbar','renderView',
    'advAskServer','toast','boardStatusList','boardPriorityList','filterMode','STATUS_OPTS',
    'advMatch','advIcon','avatarInner','Paged','togglePop','Views',
    'openCellPop','closeCellPops',
    body + '\n' + advObject() + '\nreturn Adv;')(
    st,
    x => String(x==null?'':x),
    () => { log.modals++; },
    () => { log.closed++; },
    /* The toolbar control the filter panel hangs off is a real enough element
       to be asked whether it is open: the way back from the builder opens the
       panel rather than toggling it, and a stub that always said "open" would
       hide a door that silently closes the thing it was asked to show. */
    {getElementById:id=>(id==='ctl-arrange'?log.ctl
        :{classList:{add(){},remove(){}}, set innerHTML(v){log.redraws++;}}),
     querySelector:()=>null},
    () => {}, () => {},
    () => { log.asked++; },
    m => log.toasts.push(m),
    () => [{key:'done',he:'בוצע',c:'#00c875'}],
    () => [{key:'high',he:'גבוהה',c:'#e2445c'}],
    () => 'client',
    [{label:'x',color:'#c4c4c4'}],
    // the engine, the column icon, a face and the paging flag — the builder
    // draws with all four, and a stub that lacks one hides a real error
    (t,node) => !node || !node.rules || !node.rules.length,
    f => 'fa-font',
    u => `<i data-face="${(u&&u.id)==null?'':u.id}"></i>`,
    {on:false,total:0},
    () => { log.quick++; },
    {active:null, update(){ log.viewSaved='update'; }, saveNew(){ log.viewSaved='new'; }},
    /* The menu a box opens — the system's own popover. Stubbed down to what
       the builder does with it: the markup it was handed, and the rows it
       then wires up. */
    (anchor,html,cls)=>{
      const btns=(html.match(/data-i="(\d+)"/g)||[])
        .map(m=>({dataset:{i:m.replace(/\D/g,'')}, onclick:null}));
      log.pop={anchor,html,cls,btns};
      return {querySelectorAll:()=>btns, querySelector:()=>null};
    },
    ()=>{ log.popClosed=(log.popClosed||0)+1; });
  /* The panel's own half of the same tree. advChanged is the redraw-and-ask
     step, which is not what these checks are about — they are about the two
     doors opening on one filter. */
  const panel = new Function('st','advChanged',
    names.slice(0,11).map(grab).join('\n') + '\n' + konst('advOwnGroup') + '\n'
    + konst('advField') + '\n' + konst('ADV_KINDS') + '\n'
    + ';return {advPicked,advPickedAll,advCount,advToggle};')(st, ()=>{});
  return [Adv, st, log, panel];
}

// ── it opens, and on what ─────────────────────────────────────────────────
{
  const [Adv, st, log] = world();
  Adv.open();
  ck('the builder opens', log.modals===1);
  /* On one empty condition rather than on the sentence "אין תנאים": the first
     thing anybody does here is pick a column, and asking for the row first is
     a click that answers nothing. */
  ck('...on one empty condition, ready to be filled in',
     Adv.draft.rules.length===1 && Adv.draft.rules[0].v==='', Adv.draft);
  ck('...on a copy, so closing with ✕ leaves the board as it was',
     st.filters.adv===null, st.filters.adv);
}
{
  /* …and an empty row costs nothing, because an unfinished condition never
     reaches the board: it matches every item, so applying it would buy a
     badge counting a question nobody is asking. */
  const [Adv, st] = world();
  Adv.open();
  Adv.apply();
  ck('opening and applying without filling anything in filters nothing',
     st.filters.adv===null, st.filters.adv);
  Adv.open();
  Adv.setField('0','col_a'); Adv.setRuleOp('0','eq'); Adv.setV('0','v','תקוע');
  Adv.addRule('');                       // …and a second one left half-built
  Adv.apply();
  ck('the finished condition is applied and the half-built one is dropped',
     st.filters.adv && st.filters.adv.rules.length===1
     && st.filters.adv.rules[0].v==='תקוע', st.filters.adv);
}
{
  const [Adv, st] = world();
  st.filters.adv={op:'and',rules:[{field:'col_a',op:'eq',v:'תקוע',v2:''}]};
  Adv.open();
  ck('a filter that already has conditions opens on those, not on a blank row',
     Adv.draft.rules.length===1 && Adv.draft.rules[0].v==='תקוע', Adv.draft);
}
{
  const [Adv, st, log] = world();
  st.board = null;
  Adv.open();
  ck('with no board open it says so instead of opening on nothing',
     log.modals===0 && log.toasts.length===1, log.toasts);
}

// ── every edit the builder offers ─────────────────────────────────────────
{
  const [Adv, st, log] = world();
  Adv.open();                              // …which already offers one row
  Adv.addRule('');
  ck('a condition can be added', Adv.draft.rules.length===2, Adv.draft);
  Adv.setField('0','col_a');
  Adv.setRuleOp('0','eq');
  Adv.setV('0','v','תקוע');
  ck('...its column, its operator and its value can all be set',
     Adv.draft.rules[0].field==='col_a' && Adv.draft.rules[0].op==='eq'
     && Adv.draft.rules[0].v==='תקוע', Adv.draft.rules[0]);
  Adv.addGroup('');
  ck('a group can be added', Adv.draft.rules.length===3 && Adv.draft.rules[2].rules, Adv.draft);
  Adv.addRule('2');
  Adv.setField('2.0','status');
  ck('...and a condition inside it', Adv.draft.rules[2].rules.length===1
     && Adv.draft.rules[2].rules[0].field==='status', Adv.draft.rules[2]);
  Adv.setOp('2','or');
  ck('...with וגם/או of its own', Adv.draft.rules[2].op==='or');
  Adv.del('2');
  ck('anything can be deleted', Adv.draft.rules.length===2, Adv.draft);
}

// ── applying, and clearing ────────────────────────────────────────────────
{
  const [Adv, st, log] = world();
  Adv.open();
  Adv.addRule(''); Adv.setField('0','col_a'); Adv.setRuleOp('0','eq'); Adv.setV('0','v','תקוע');
  Adv.apply();
  ck('applying puts the conditions on the board',
     st.filters.adv && st.filters.adv.rules.length===1, st.filters.adv);
  ck('...closes the window', log.closed>=1);
  ck('...and asks the server the same question', log.asked===1);
  Adv.clear();
  ck('clearing empties the filter', st.filters.adv===null && st.filters.advIds===null);
}
{
  const [Adv, st] = world();
  Adv.open();
  Adv.apply();
  ck('a builder closed with nothing in it does not leave an empty filter behind',
     st.filters.adv===null, st.filters.adv);
}

// ── the two doors open on the same filter ─────────────────────────────────
{
  const [Adv, st, log, panel] = world();
  panel.advToggle('col_a','eq','תקוע');            // picked in the quick panel
  Adv.open();
  ck('what the panel picked opens in the builder as the condition it is',
     Adv.draft.rules.length===1 && Adv.draft.rules[0].rules[0].v==='תקוע', Adv.draft);
  Adv.addRule('');                                  // and a second, by hand
  Adv.setField('1','col_a'); Adv.setRuleOp('1','eq'); Adv.setV('1','v','בעבודה');
  Adv.apply();
  ck('...and what the builder applies, the panel reads back as picked',
     panel.advPickedAll('col_a').map(p=>p.v).sort().join()==='בעבודה,תקוע',
     panel.advPickedAll('col_a'));
  ck('...with the count the badge shows covering both', panel.advCount(st.filters.adv)===2);
}

// ── it reads as a sentence, and says what it is doing ─────────────────────
{
  /* A stack of boxes with an unexplained gap above the first one is a form.
     The first condition of every group opens with "כאשר" and the rest carry
     the group's own word, so the filter reads straight down. */
  const [Adv] = world();
  Adv.open();                              // …which already offers one row
  Adv.addRule('');
  const html = Adv.bodyHTML();
  ck('the first condition opens with כאשר', /adv-joiner">כאשר</.test(html), html.slice(0,300));
  /* …and every one after it carries the group's own word, as the word itself
     in the same column. It is the and/or: one fact, shown where it is read,
     rather than a toggle in a header a line above saying the same thing. */
  ck('…and the next carries the group\'s own word, as the and/or itself',
     (html.match(/adv-joiner-sel/g)||[]).length===1
     && /<option value="and" selected>וגם<\/option>/.test(html), html.slice(0,300));
  Adv.setOp('','or');
  ck('…which follows the group when it is switched',
     /<option value="or" selected>או<\/option>/.test(Adv.bodyHTML()));
  ck('…and picking it on any row sets the group it is in',
     (()=>{ Adv.setOp('','and'); return Adv.draft.op==='and'; })());
}
{
  /* A condition whose value is still empty matches EVERY item: it widens the
     filter rather than narrowing it, and it used to do that in silence. */
  const [Adv] = world();
  Adv.open();                              // the row it opens on is one of these
  ck('a condition with no value is counted as not filtering', Adv.todo(Adv.draft)===1);
  ck('…and says so on its own row', /adv-rule adv-todo/.test(Adv.bodyHTML()));
  ck('…and once above the tree, for the row that scrolled off',
     /adv-warn/.test(Adv.bodyHTML()));
  Adv.setV('0','v','תקוע');
  ck('…and stops saying it once the value is there',
     Adv.todo(Adv.draft)===0 && !/adv-todo/.test(Adv.bodyHTML())
     && !/adv-warn/.test(Adv.bodyHTML()), Adv.bodyHTML().slice(0,200));
  Adv.setRuleOp('0','empty');
  ck('a question that takes no value is finished without one',
     Adv.todo(Adv.draft)===0, Adv.draft.rules[0]);
}
{
  /* The count is the whole point of the dialog, so it sits beside the title
     where the eye already is. It answers about the DRAFT — before anything is
     applied — which is what makes it worth looking at while building. */
  const [Adv, st] = world();
  st.board.tasks=[{id:1,title:'א'},{id:2,title:'ב'},{id:3,title:'ג'}];
  Adv.open();
  /* …counted against the tree as it will be ASKED. The row it opens on has no
     value yet, so it is not part of the question and the count must not
     pretend it is. */
  ck('with nothing filled in yet, the whole board survives',
     /את כל 3 הפריטים/.test(Adv.preview()), Adv.preview());
  ck('…and the count is drawn beside the title, not under the list',
     /id="adv-count"/.test(Adv.html()) && !/id="adv-count"/.test(Adv.bodyHTML()));
}

// ── the door turns both ways ──────────────────────────────────────────────
{
  /* The quick panel's foot opens this builder. Without a way back, returning
     to picking values meant closing the dialog and finding the filter button
     again — and what had been built would have been thrown away on the trip. */
  const [Adv, st, log] = world();
  Adv.open();
  Adv.addRule(''); Adv.setField('0','col_a'); Adv.setRuleOp('0','eq'); Adv.setV('0','v','תקוע');
  /* The click that makes the trip, watched for the two things that used to
     decide whether the panel survived it. */
  const ev = {stopped:0, stopPropagation(){ this.stopped++; }};
  Adv.toQuick(ev);
  /* Opened WITHIN the click, not after it. It used to wait for the filter to
     be confirmed by the server, so the panel appeared whenever the answer did
     — and when there was nothing to ask about, that was one microtask into a
     click still on its way to the document, where every open popup is closed.
     The panel was opened and shut inside the same click. */
  ck('going back to the quick panel opens it, within the click itself', log.quick===1);
  ck('…and that click is kept from the closer that empties every popup',
     ev.stopped===1, ev.stopped);
  ck('…and takes what was built along rather than dropping it',
     st.filters.adv && st.filters.adv.rules.length===1, st.filters.adv);
  /* The door turns one way. Pressed while the panel is somehow already open,
     a toggle would have closed the very thing it was asked to show. */
  log.ctl.classList.add('open');
  Adv.toQuick(ev);
  ck('…and never closes a panel that is already open', log.quick===1, log.quick);
}

// ── the look the dialog is meant to have ─────────────────────────────────
{
  /* Three plain controls on the dialog's own white, each in its own outline —
     not a card with a grey fill holding them. Every filled box is another
     rectangle competing with the thing being looked for, and the row already
     has four. */
  const [Adv] = world();
  Adv.open();
  Adv.addRule('');
  const html = Adv.bodyHTML();
  ck('each control is its own outlined box', (html.match(/class="adv-box /g)||[]).length>=3, html.slice(0,200));
  ck('…with the chevron drawn here rather than by the browser',
     (html.match(/adv-cv/g)||[]).length>=2, (html.match(/adv-cv/g)||[]).length);
  ck('…and no card wrapped around the three of them',
     !/class="adv-rule[^"]*"[^>]*>\s*<(?!span class="adv-box)/.test(html) || /adv-rule/.test(html));
}
{
  /* A chosen value is drawn as the board draws it: a person by their face, a
     status in its own colour. It stopped being a line of plain text
     indistinguishable from the question beside it. */
  const [Adv] = world();
  Adv.open();
  Adv.addRule(''); Adv.setField('0','col_a'); Adv.setRuleOp('0','eq'); Adv.setV('0','v','תקוע');
  const html = Adv.bodyHTML();
  ck('a chosen status is a chip in its own colour',
     /adv-chip/.test(html) && /adv-chip-dot/.test(html), html.slice(0,200));
  ck('…with an × that clears it', /adv-chip-x/.test(html));
  ck('…and the list behind it reduced to its chevron', /adv-box-val picked/.test(html));
  const [Adv2] = world();
  Adv2.open();
  Adv2.addRule(''); Adv2.setField('0','assignees'); Adv2.setRuleOp('0','has'); Adv2.setV('0','v','me');
  ck('a chosen person is a chip with their face',
     /adv-chip/.test(Adv2.bodyHTML()) && /data-face/.test(Adv2.bodyHTML()),
     Adv2.bodyHTML().slice(0,300));
}
{
  /* Adding reads as two words under the conditions, where the next one will
     appear — not as buttons in the header, a line above where it lands. */
  const [Adv] = world();
  Adv.open();
  const html = Adv.bodyHTML();
  ck('adding is offered under the conditions, in words',
     /adv-grp-foot/.test(html) && /סינון חדש/.test(html) && /קבוצה חדשה/.test(html));
  ck('…and the way back sits under a divider, as the last thing on the panel',
     html.indexOf('adv-sep') < html.indexOf('מעבר לסינון מהיר')
     && html.indexOf('adv-grp-foot') < html.indexOf('adv-sep'));
}
{
  /* The window's own two actions sit opposite the title: clearing as a word,
     saving as the one outlined thing up there. */
  const [Adv, st, log] = world();
  Adv.open();
  const head = Adv.html();
  ck('the title row carries the count and the two actions',
     /id="adv-count"/.test(head) && /נקה הכול/.test(head)
     && /adv-save/.test(head), head.slice(0,400));
  ck('…and nothing else — the ? that showed no hover is gone',
     !/adv-help/.test(head), head.slice(0,400));
  ck('…and the foot is down to applying and cancelling',
     /החל סינון/.test(head) && /ביטול/.test(head) && !/mfoot[\s\S]*נקה הכול/.test(head));
}
{
  /* Saving applies first, deliberately: a view holds the filter the BOARD is
     under, and storing a draft the board was never shown under would save a
     cut nobody has seen. */
  const [Adv, st, log] = world();
  Adv.open();
  Adv.addRule(''); Adv.setField('0','col_a'); Adv.setRuleOp('0','eq'); Adv.setV('0','v','תקוע');
  await Adv.saveView();
  ck('saving as a view applies the draft first',
     st.filters.adv && st.filters.adv.rules.length===1, st.filters.adv);
  ck('…and with no view open, makes a new one', log.viewSaved==='new', log.viewSaved);
}

// ── the box opens the list, all of it ────────────────────────────────────
{
  /* The chevron is part of the control, not an ornament beside it. Clicking
     the words opened the list and clicking the arrow two pixels away did
     nothing, which is a control that works in one half of itself. The click
     is taken by the BOX now, so every part of it opens the same menu. */
  const [Adv] = world();
  Adv.open();
  Adv.setField('0','col_a');          // a column whose value is picked from a list too
  const html = Adv.bodyHTML();
  const boxes = html.match(/class="adv-box adv-sel[^"]*"[^>]*/g) || [];
  ck('every box that holds a list takes the click itself',
     boxes.length>=3 && boxes.every(b=>/onclick="Adv\.pick\(event,this\)"/.test(b)), boxes[0]);
  ck('…including the chevron inside it, which is not an ornament',
     /adv-cv/.test(html) && !/adv-cv[^>]*onclick/.test(html));
}
{
  /* …and what opens is OUR menu, in the system's own styling — .row-menu and
     .rm-item, the rows every other menu in the product is made of. The
     browser's native list could not be styled at all: a grey OS rectangle
     with no colours, no faces and no tick, in a dialog built out of all three. */
  const [Adv, st, log] = world();
  Adv.open();
  const box = boxOf([{v:'',label:'בחרו ערך…'},
                     {v:'תקוע',label:'תקוע','data-color':'#e2445c'},
                     {v:'בעבודה',label:'בעבודה','data-color':'#fdab3d'}], 1, log);
  Adv.pick(ev(), box);
  ck('the list is the system\'s own menu, not the browser\'s',
     /class="row-menu adv-menu/.test(log.pop.html) && /rm-item adv-opt/.test(log.pop.html),
     log.pop.html.slice(0,160));
  ck('…every value drawn as the board draws it, in its own colour',
     (log.pop.html.match(/adv-chip-dot/g)||[]).length===2, log.pop.html);
  ck('…the one in force marked as such', /adv-opt on/.test(log.pop.html));
  ck('…and the list no narrower than the box it came out of',
     /min-width:230px/.test(log.pop.html));
}
{
  /* Choosing writes back to the select and fires its change — the handler
     that was already on the row. One source of what can be picked, and no
     second copy of it to drift. */
  const [Adv, st, log] = world();
  Adv.open();
  const box = boxOf([{v:'',label:'בחרו ערך…'},{v:'תקוע',label:'תקוע'}], 0, log);
  Adv.pick(ev(), box);
  log.pop.btns[1].onclick();
  ck('choosing a row sets the value and fires the row\'s own handler',
     box._sel.value==='תקוע' && (log.fired||[]).join()==='change:תקוע', log.fired);
  ck('…and closes the menu behind it', log.popClosed===1, log.popClosed);
}
{
  /* A person is a face in the list as well as in the box, and a column is its
     own type's icon — the same two things the row beside it is drawn with. */
  const [Adv] = world();
  Adv.open();
  const html = Adv.bodyHTML();
  ck('the column list carries each column\'s icon', /<option value="col_a" data-ic="fa-font"/.test(html), html.slice(0,400));
  Adv.setField('0','assignees'); Adv.setRuleOp('0','has');
  ck('…and the people list carries who each one is',
     /data-uid="me"/.test(Adv.bodyHTML()), Adv.bodyHTML().slice(0,400));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
