/* סינון מתקדם — a tree of conditions over the board's own columns.

   The toolbar's filters answer one question each: this person, that status.
   An advanced filter answers a question made of several, and the shape that
   expresses it is a tree — "A and (B or C)" is a different question from
   "(A and B) or C", and a flat list cannot tell them apart.

   What is pinned here is the ENGINE, because the engine is what can be
   silently wrong: a filter that hides the wrong rows looks exactly like a
   filter that works, and the rows it hides are the ones nobody goes looking
   for. Each column type offers the operators the spec gives it, each operator
   answers what it says it answers, and the two kinds of value that are not
   literals — [אני] and the dynamic dates — resolve when the filter RUNS and
   not when it was built.

   Driven by tests/test_advanced_filter.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

/* The whole engine block, verbatim: from the kinds table down to advCount. */
const from = src.indexOf('const ADV_KINDS = {');
const to   = src.indexOf('const IS_ITEM_ID=');
if(from<0||to<0||to<from) throw new Error('the advanced-filter engine is no longer where this can read it');
const engine = src.slice(from, to);

const ME = 7;
const STATUSES = [{key:'todo',he:'לביצוע'},{key:'in_progress',he:'בטיפול'},{key:'done',he:'בוצע'}];
const PRIORITIES = [{key:'low',he:'נמוכה'},{key:'high',he:'גבוהה'}];
const PEOPLE = [{id:7,name:'רינה'},{id:8,name:'דנה'}];
const COLUMNS = [
  {id:'c_txt',  title:'הערה',   type:'text'},
  {id:'c_num',  title:'תקציב',  type:'number'},
  {id:'c_sta',  title:'שלב',    type:'status', options:[{label:'א'},{label:'ב'}]},
  {id:'c_ppl',  title:'מבצע',   type:'people'},
  {id:'c_date', title:'מועד',   type:'date'},
  {id:'c_chk',  title:'אושר',   type:'checkbox'},
  {id:'c_link', title:'מקושר',  type:'connect'},     // nothing to ask of it yet
  // the two the system fills in by itself — nothing of theirs is in
  // custom_fields, and they are asked about all the same
  {id:'c_made', title:'מועד יצירה',  type:'created_at'},
  {id:'c_by',   title:'יוצר הרשומה', type:'created_by'},
];

const api = new Function('st','meId','customColumns','boardStatusList','boardPriorityList',
  'boardPeople','statusColOpts','statusKeyOf','priorityKeyOf',
  engine + `
  return {ADV_OPS, ADV_DATES, advOps, advOpArity, advSpan, advIso, advFields, advField,
          advChoices, advCell, advRuleMatch, advMatch, advCount};`)(
  {board:{columns:COLUMNS}},
  ()=>ME,
  ()=>COLUMNS,
  ()=>STATUSES.map(s=>({key:s.key,he:s.he})),
  ()=>PRIORITIES.map(s=>({key:s.key,he:s.he})),
  ()=>PEOPLE.slice(),
  col=>{ const c=(col&&typeof col==='object')?col:COLUMNS.find(x=>x.id===col);
         return ((c&&c.options)||[]).map(o=>({id:null,label:o.label,color:'#ccc'})); },
  t=>((t.custom_fields||{}).status_unset?null:(t.status||null)),
  t=>((t.custom_fields||{}).priority_unset?null:(t.priority||null)));

const {advOps, advSpan, advFields, advField, advChoices, advCell, advIso,
       advRuleMatch, advMatch, advCount, ADV_DATES} = api;

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,220):''))); };

const item = (o={}) => ({id:o.id||1, title:o.title||'פריט', status:o.status, priority:o.priority,
  due_date:o.due, assignees:(o.people||[]).map(id=>({id})), custom_fields:o.cf||{},
  created_at:o.made, created_by:o.by});
const m = (t,field,op,v,v2) => advRuleMatch(t,{field,op,v,v2});

// ── the catalogue: what can be asked, and of what ─────────────────────────
{
  const ids = advFields().map(f=>f.id);
  ck('the built-in columns can all be filtered',
     ['title','status','priority','assignees','due'].every(i=>ids.includes(i)), ids.join(','));
  ck('...and so can every custom column with a kind',
     ['c_txt','c_num','c_sta','c_ppl','c_date','c_chk'].every(i=>ids.includes(i)), ids.join(','));
  ck('...including the ones the system fills in on its own',
     ids.includes('c_made') && ids.includes('c_by'), ids.join(','));
  ck('a column with nothing to ask of it is not offered rather than offered broken',
     !ids.includes('c_link'), ids.join(','));
}
{
  const ops = k => advOps(k).map(o=>o[1]);
  // the spec, column type by column type
  ck('טקסט offers exactly the six operators of the spec',
     ops('text').join(',')==='שווה ל,לא שווה ל,מכיל,לא מכיל,ריק,אינו ריק', ops('text'));
  ck('סטטוס offers equals, not-equals and the two emptiness ones',
     ops('status').join(',')==='שווה ל,לא שווה ל,ריק,אינו ריק', ops('status'));
  ck('מספרים offers the comparisons and a range',
     ops('number').join(',').startsWith('שווה ל,לא שווה ל,גדול מ,קטן מ,בטווח'), ops('number'));
  ck('אנשים offers assigned-to and not-assigned-to',
     ops('people').slice(0,2).join(',')==='מוקצה ל,לא מוקצה ל', ops('people'));
  ck('תאריכים offers on/before/after and a range',
     ops('date').join(',').startsWith('ביום,לפני,אחרי,בטווח'), ops('date'));
}
{
  const byId = id => advField(id).kind;
  ck('a status column and a dropdown ask the same questions', byId('c_sta')==='status');
  ck('a rating and a number too', advField('c_num').kind==='number');
}

// ── text ──────────────────────────────────────────────────────────────────
{
  const t = item({title:'גשר הרצל', cf:{c_txt:'דחוף מאוד'}});
  ck('שווה ל is the whole value, not a part of it',
     m(t,'title','eq','גשר הרצל') && !m(t,'title','eq','גשר'));
  ck('מכיל is the part', m(t,'title','has','הרצל') && !m(t,'title','has','ביאליק'));
  ck('לא מכיל is its opposite', !m(t,'title','nhas','הרצל') && m(t,'title','nhas','ביאליק'));
  ck('matching ignores case', m(item({title:'Bridge'}),'title','has','bridge'));
  ck('ריק and אינו ריק read the cell, not the rule',
     m(item({cf:{}}),'c_txt','empty') && m(t,'c_txt','filled'));
  ck('an empty cell is not "not equal to" nothing — it IS not equal',
     m(item({cf:{}}),'c_txt','ne','דחוף'));
  ck('a rule with no value yet hides nothing',
     m(t,'title','eq','') && m(t,'title','has',''));
}

// ── status ────────────────────────────────────────────────────────────────
{
  const t = item({status:'in_progress', cf:{c_sta:'ב'}});
  ck('a built-in status matches by key, not by the Hebrew beside it',
     m(t,'status','eq','in_progress') && !m(t,'status','eq','done'));
  ck('...and לא שווה ל is its complement', m(t,'status','ne','done') && !m(t,'status','ne','in_progress'));
  ck('a status COLUMN matches by the label the board shows',
     m(t,'c_sta','eq','ב') && !m(t,'c_sta','eq','א'));
  ck('an item with nothing chosen is ריק',
     m(item({cf:{status_unset:true}}),'status','empty'));
  ck('the choices offered are the board own statuses',
     advChoices(advField('status')).map(c=>c.v).join(',')==='todo,in_progress,done');
}

// ── numbers ───────────────────────────────────────────────────────────────
{
  const t = item({cf:{c_num:120}});
  ck('גדול מ and קטן מ are strict', m(t,'c_num','gt',100) && !m(t,'c_num','gt',120)
     && m(t,'c_num','lt',200) && !m(t,'c_num','lt',120));
  ck('בטווח includes both ends', m(t,'c_num','between',120,200) && m(t,'c_num','between',100,120));
  ck('...and does not care which end was typed first', m(t,'c_num','between',200,100));
  ck('an empty cell is outside every range and every comparison',
     !m(item({cf:{}}),'c_num','gt',1) && !m(item({cf:{}}),'c_num','between',0,999));
  ck('...but it is ריק', m(item({cf:{}}),'c_num','empty'));
  ck('a number written as text still compares as a number',
     m(item({cf:{c_num:'120'}}),'c_num','eq',120));
  ck('zero is a value, not an empty cell',
     !m(item({cf:{c_num:0}}),'c_num','empty') && m(item({cf:{c_num:0}}),'c_num','lt',1));
}

// ── people, and [אני] ─────────────────────────────────────────────────────
{
  const mine = item({people:[ME,8]}), hers = item({people:[8]});
  ck('מוקצה ל matches the person named', m(mine,'assignees','has','8') && !m(item({people:[ME]}),'assignees','has','8'));
  ck('לא מוקצה ל is its complement', m(hers,'assignees','nhas',String(ME)));
  ck('[אני] is the person running the filter, not an id frozen into it',
     m(mine,'assignees','has','me') && !m(hers,'assignees','has','me'));
  ck('a people COLUMN works the same', m(item({cf:{c_ppl:[ME]}}),'c_ppl','has','me'));
  ck('...including when the cell holds objects rather than ids',
     m(item({cf:{c_ppl:[{id:ME,name:'רינה'}]}}),'c_ppl','has','me'));
  ck('nobody assigned is ריק', m(item({people:[]}),'assignees','empty'));
  ck('[אני] is offered first, above the names',
     advChoices(advField('assignees'))[0].v==='me');
}

// ── dates, fixed and dynamic ──────────────────────────────────────────────
{
  const iso=d=>{const x=new Date();x.setHours(0,0,0,0);x.setDate(x.getDate()+d);
    const p=n=>String(n).padStart(2,'0');
    return `${x.getFullYear()}-${p(x.getMonth()+1)}-${p(x.getDate())}`;};
  const today=item({due:iso(0)}), yest=item({due:iso(-1)}), soon=item({due:iso(3)});

  ck('ביום with a fixed date is that one day',
     m(today,'due','on',iso(0)) && !m(yest,'due','on',iso(0)));
  ck('לפני and אחרי are strict', m(yest,'due','before',iso(0)) && !m(today,'due','before',iso(0))
     && m(soon,'due','after',iso(0)) && !m(today,'due','after',iso(0)));
  ck('בטווח includes both ends', m(today,'due','between',iso(0),iso(3))
     && m(soon,'due','between',iso(0),iso(3)));
  ck('היום resolves when the filter runs', m(today,'due','on','today') && !m(yest,'due','on','today'));
  ck('אתמול too', m(yest,'due','on','yesterday'));
  ck('השבוע is a span of days, so every day of it matches',
     m(today,'due','on','this_week'));
  ck('"לפני היום" is everything before the start of today, not before this instant',
     m(yest,'due','before','today') && !m(today,'due','before','today'));
  ck('"אחרי השבוע" is after the whole week, not after one of its days',
     !m(today,'due','after','this_week'));
  ck('7 הימים האחרונים includes today and reaches back',
     m(today,'due','on','last_7') && m(yest,'due','on','last_7') && !m(soon,'due','on','last_7'));
  ck('an empty date is ריק and matches no comparison',
     m(item({}),'due','empty') && !m(item({}),'due','on','today'));
  ck('a timeline answers by its start', m(item({cf:{c_date:{from:iso(0),to:iso(9)}}}),'c_date','on','today'));
  ck('a date with a time on it still matches the day',
     m(item({due:iso(0)+'T14:30:00'}),'due','on','today'));
  ck('every dynamic date resolves to a span',
     ADV_DATES.every(d=>{const s=advSpan(d[0]); return s&&s.from<=s.to;}),
     ADV_DATES.filter(d=>!advSpan(d[0])).map(d=>d[0]).join(','));
}

// ── the tree ──────────────────────────────────────────────────────────────
{
  const mineDone = item({people:[ME], status:'done'});
  const mineOpen = item({people:[ME], status:'todo'});
  const hersOpen = item({people:[8],  status:'todo'});
  const AND = {op:'and',rules:[{field:'assignees',op:'has',v:'me'},{field:'status',op:'eq',v:'todo'}]};
  const OR  = {op:'or', rules:[{field:'assignees',op:'has',v:'me'},{field:'status',op:'eq',v:'todo'}]};
  ck('וגם needs both', advMatch(mineOpen,AND) && !advMatch(mineDone,AND) && !advMatch(hersOpen,AND));
  ck('או needs one', advMatch(mineDone,OR) && advMatch(hersOpen,OR));

  /* The reason a tree exists at all: these two have the same three rules and
     ask different questions. */
  const a = {op:'and',rules:[{field:'assignees',op:'has',v:'me'},
            {op:'or',rules:[{field:'status',op:'eq',v:'todo'},{field:'priority',op:'eq',v:'high'}]}]};
  const b = {op:'or',rules:[{op:'and',rules:[{field:'assignees',op:'has',v:'me'},
            {field:'status',op:'eq',v:'todo'}]},{field:'priority',op:'eq',v:'high'}]};
  const hersHigh = item({people:[8], status:'done', priority:'high'});
  ck('"שלי וגם (פתוח או דחוף)" does not match somebody else דחוף', !advMatch(hersHigh,a));
  ck('..."(שלי וגם פתוח) או דחוף" does — which is why the nesting is kept',
     advMatch(hersHigh,b));

  ck('an unfinished filter shows the whole board rather than hiding it',
     advMatch(hersOpen,{op:'and',rules:[]}) && advMatch(hersOpen,null)
     && advMatch(hersOpen,{op:'and',rules:[{op:'or',rules:[]}]}));
  ck('the count is what the toolbar badge shows, nesting included',
     advCount(a)===3 && advCount({op:'and',rules:[]})===0 && advCount(null)===0, advCount(a));
}
{
  // a column deleted after the filter was built must not empty the board
  ck('a rule on a column that no longer exists stops filtering instead of hiding everything',
     advRuleMatch(item({}),{field:'c_gone',op:'eq',v:'x'}));
}

// ── the builder: paths, which is where a tree editor goes wrong ───────────
/* Every handler addresses a node by a path string — '' the root, '2' its
   third child, '2.0' the first child of that group — because a redraw rebuilds
   the whole tree and an object reference would point at a node that no longer
   exists. A path that resolves to the wrong node edits somebody else's rule,
   and nothing on screen says so. */
{
  const advSrc = src.slice(src.indexOf('const Adv = {'), src.indexOf('\nfunction refreshToolbar(){'));
  const Adv = new Function('st','esc','toast','showModal','closeModals','document',
    'advFields','advField','advOps','advOpArity','advChoices','advMatch','advCount','ADV_DATES',
    'refreshToolbar','renderView','advIcon','avatarInner','Paged','togglePop','Views',
    advSrc + '\nreturn Adv;')(
    {board:{columns:COLUMNS, tasks:[item({people:[ME]}), item({id:2,people:[8]})]},
     filters:{}, me:{id:ME}},
    x=>String(x==null?'':x), ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelector:()=>null},
    advFields, advField, advOps, api.advOpArity, advChoices, advMatch, advCount, ADV_DATES,
    ()=>{}, ()=>{}, f=>'fa-font', u=>`<i data-face="${(u&&u.id)==null?'':u.id}"></i>`,
    {on:false,total:0}, ()=>{}, {active:null,update(){},saveNew(){}});

  Adv.draft={op:'and',rules:[]};
  Adv.addRule('');
  Adv.addGroup('');
  Adv.addRule('1');
  Adv.addRule('1');
  ck('the tree is built where the path says',
     Adv.draft.rules.length===2 && Adv.draft.rules[1].rules.length===2,
     JSON.stringify(Adv.draft));

  Adv.setField('1.1','c_num');
  ck('setting a field reaches the nested rule and not its sibling',
     Adv.draft.rules[1].rules[1].field==='c_num' && Adv.draft.rules[1].rules[0].field==='title',
     JSON.stringify(Adv.draft.rules[1]));
  ck('...and the operator moves to one the new column actually offers',
     Adv.draft.rules[1].rules[1].op==='eq');

  Adv.setRuleOp('1.1','between');
  Adv.setV('1.1','v',5); Adv.setV('1.1','v2',9);
  ck('both ends of a range are kept', Adv.draft.rules[1].rules[1].v===5 && Adv.draft.rules[1].rules[1].v2===9);
  Adv.setRuleOp('1.1','gt');
  ck('...and the second is dropped when the operator stops needing it',
     Adv.draft.rules[1].rules[1].v2==='');

  Adv.setField('1.1','title');
  ck('changing column clears a value that belonged to the old one',
     Adv.draft.rules[1].rules[1].v==='');

  Adv.del('1.0');
  ck('deleting removes the one addressed, and the rest close up',
     Adv.draft.rules[1].rules.length===1 && Adv.draft.rules[1].rules[0].field==='title',
     JSON.stringify(Adv.draft.rules[1]));

  Adv.setOp('1','and');
  ck('a nested group has its own and/or', Adv.draft.rules[1].op==='and' && Adv.draft.op==='and');

  const html=Adv.bodyHTML();
  ck('the builder draws a row per rule and a box per group',
     (html.match(/class="adv-rule/g)||[]).length===2
     && (html.match(/class="adv-grp /g)||[]).length===2, html.slice(0,200));
  /* The count sits beside the dialog's title rather than under a list that
     scrolls, so it is preview() that has to answer — and it answers about the
     DRAFT, before anything is applied, which is what makes it worth showing. */
  ck('...and says how many items survive, before anything is applied',
     /\d+ מתוך \d+ פריטים|את כל \d+ הפריטים/.test(Adv.preview()), Adv.preview());
  /* A condition with no value yet matches every item. It used to do that in
     silence; now the row says so and the top of the tree counts them. */
  ck('a condition still missing its value is marked as not filtering',
     /class="adv-rule adv-todo"/.test(html) && /adv-warn/.test(html), html.slice(0,200));

  Adv.del('1');
  ck('a whole group can be removed', Adv.draft.rules.length===1);
}

// ── the spec's own example, built and run ────────────────────────────────
/* "(Group A: Status=Done AND Date=This Week) OR (Group B: Priority=High)"

   Two groups side by side under an OR root, each with its own AND inside.
   It is written out here exactly as the spec writes it, because a tree
   builder that can express every shape EXCEPT the one the specification uses
   as its illustration is a builder nobody will trust. */
{
  const iso=d=>{const x=new Date();x.setHours(0,0,0,0);x.setDate(x.getDate()+d);
    const p=n=>String(n).padStart(2,'0');
    return `${x.getFullYear()}-${p(x.getMonth()+1)}-${p(x.getDate())}`;};
  // "this week" starts on Sunday; a day inside it, whichever day today is
  const inWeek=iso(-new Date().getDay());
  const outWeek=iso(-new Date().getDay()-7);

  const SPEC = {op:'or', rules:[
    {op:'and', rules:[{field:'status',op:'eq',v:'done'},
                      {field:'due',op:'on',v:'this_week'}]},     // Group A
    {op:'and', rules:[{field:'priority',op:'eq',v:'high'}]},     // Group B
  ]};

  const doneThisWeek  = item({status:'done', due:inWeek,  priority:'low'});
  const doneLastWeek  = item({status:'done', due:outWeek, priority:'low'});
  const openHigh      = item({status:'todo', due:outWeek, priority:'high'});
  const openLowOld    = item({status:'todo', due:outWeek, priority:'low'});
  const doneThisHigh  = item({status:'done', due:inWeek,  priority:'high'});

  ck('Group A alone: done AND this week', advMatch(doneThisWeek,SPEC));
  ck('...done but not this week fails Group A', !advMatch(doneLastWeek,SPEC));
  ck('Group B alone: priority=high passes on its own', advMatch(openHigh,SPEC));
  ck('neither group matches, so the item is out', !advMatch(openLowOld,SPEC));
  ck('both groups matching is still a match, not a double one', advMatch(doneThisHigh,SPEC));
  ck('the badge counts the three conditions across both groups', advCount(SPEC)===3, advCount(SPEC));

  /* And the shape itself survives being BUILT rather than written down —
     a root switched to OR with two groups added under it, which is what the
     person actually does. */
  const advSrc = src.slice(src.indexOf('const Adv = {'), src.indexOf('\nfunction refreshToolbar(){'));
  const Adv = new Function('st','esc','toast','showModal','closeModals','document',
    'advFields','advField','advOps','advOpArity','advChoices','advMatch','advCount','ADV_DATES',
    'refreshToolbar','renderView','advIcon','avatarInner','Paged','togglePop','Views',
    advSrc + '\nreturn Adv;')(
    {board:{columns:COLUMNS, tasks:[doneThisWeek, doneLastWeek, openHigh, openLowOld]},
     filters:{}, me:{id:ME}},
    x=>String(x==null?'':x), ()=>{}, ()=>{}, ()=>{},
    {getElementById:()=>null, querySelector:()=>null},
    advFields, advField, advOps, api.advOpArity, advChoices, advMatch, advCount, ADV_DATES,
    ()=>{}, ()=>{}, f=>'fa-font', u=>`<i data-face="${(u&&u.id)==null?'':u.id}"></i>`,
    {on:false,total:0}, ()=>{}, {active:null,update(){},saveNew(){}});

  Adv.draft={op:'and',rules:[]};
  Adv.setOp('','or');                       // the root becomes OR
  Adv.addGroup(''); Adv.addGroup('');       // Group A and Group B
  Adv.setOp('0','and'); Adv.setOp('1','and');
  Adv.addRule('0'); Adv.setField('0.0','status');   Adv.setV('0.0','v','done');
  Adv.addRule('0'); Adv.setField('0.1','due');      Adv.setRuleOp('0.1','on'); Adv.setV('0.1','v','this_week');
  Adv.addRule('1'); Adv.setField('1.0','priority'); Adv.setV('1.0','v','high');
  ck('the builder produces exactly the spec’s tree',
     JSON.stringify(Adv.draft)===JSON.stringify({op:'or',rules:[
       {op:'and',rules:[{field:'status',op:'eq',v:'done',v2:''},
                        {field:'due',op:'on',v:'this_week',v2:''}]},
       {op:'and',rules:[{field:'priority',op:'eq',v:'high',v2:''}]}]}),
     JSON.stringify(Adv.draft));
  ck('...and it filters the board the same way the written one does',
     [doneThisWeek,doneLastWeek,openHigh,openLowOld].map(t=>advMatch(t,Adv.draft)).join()
     === [doneThisWeek,doneLastWeek,openHigh,openLowOld].map(t=>advMatch(t,SPEC)).join());

  // a group inside a group inside a group — the "Nested Groups" is plural
  Adv.addGroup('0'); Adv.addRule('0.2'); Adv.setField('0.2.0','c_num');
  ck('groups nest further than one level',
     Adv.draft.rules[0].rules[2].rules[0].field==='c_num',
     JSON.stringify(Adv.draft.rules[0].rules[2]));
  ck('...and the builder draws every level of them',
     (Adv.bodyHTML().match(/class="adv-grp /g)||[]).length===4,
     (Adv.bodyHTML().match(/class="adv-grp /g)||[]).length);

  /* Named the way the spec names them. A tree of unnamed boxes is readable
     at two and stops being readable at four, and "the second condition in
     the third group" is not something anybody should count out on screen. */
  ck('the two top groups are Group A and Group B, as the spec calls them',
     Adv.label('0')==='A' && Adv.label('1')==='B');
  ck('a group inside A is AA, so its name says where it sits',
     Adv.label('0.2')==='AA', Adv.label('0.2'));
  ck('...and the names are drawn', /קבוצה A<|קבוצה B</.test(Adv.bodyHTML()),
     (Adv.bodyHTML().match(/קבוצה .{1,3}</g)||[]).join(' '));
  ck('the root is not a group within itself, so it carries no name',
     Adv.label('')==='');
  /* Lettered among the GROUPS, not among all the rules: adding a plain
     condition beside a group must not rename it. */
  Adv.addRule('');
  ck('adding a condition beside the groups does not rename them',
     Adv.label('0')==='A' && Adv.label('1')==='B', Adv.label('1'));
}


/* ── the columns nobody types ──────────────────────────────────────────────
   מועד יצירה and יוצר הרשומה are not in custom_fields: they are derived from
   the item, the same way the cell on screen is drawn. Read as custom fields
   they came back undefined for EVERY row, which is not "no value here" but
   "no value anywhere" — "ריק" answered with the whole board and every other
   question with none of it. The first looks like a filter that never ran and
   the second like one that broke the board; they were the same missing
   lookup. */
{
  const made = item({made:'2026-03-05T08:00:00Z'});
  ck('מועד יצירה is read off the item', advCell(made, advField('c_made'))==='2026-03-05');
  ck('...and answers "ביום" for the day it names',
     m(made,'c_made','on','2026-03-05') && !m(made,'c_made','on','2026-03-04'));
  ck('...and before/after around it',
     m(made,'c_made','before','2026-03-06') && m(made,'c_made','after','2026-03-04'));
  ck('an item created in the evening belongs to the day the VIEWER is having',
     advCell(item({made:'2026-03-05T22:30:00Z'}), advField('c_made'))
       === advIso(new Date('2026-03-05T22:30:00Z')));
  ck('an item with no creation time recorded is the empty one',
     m(item({}),'c_made','empty') && !m(item({}),'c_made','filled'));
  ck('...and one with a creation time is not — which it was for every row',
     m(made,'c_made','filled') && !m(made,'c_made','empty'));
}
{
  const mine = item({by:ME}), hers = item({by:8});
  ck('יוצר הרשומה is read off the item, as a people column answers',
     JSON.stringify(advCell(mine, advField('c_by')))==='['+ME+']');
  ck('...so "מוקצה ל" finds what somebody created',
     m(mine,'c_by','has',ME) && !m(hers,'c_by','has',ME));
  ck('..."אני" means the person looking, here too', m(mine,'c_by','has','me'));
  ck('...and its opposite is the other way round',
     m(hers,'c_by','nhas',ME) && !m(mine,'c_by','nhas',ME));
  ck('an item with no creator recorded is the empty one',
     m(item({}),'c_by','empty') && !m(mine,'c_by','empty'));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
