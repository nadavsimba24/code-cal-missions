/* Filtering a board by its own columns.

   The filter button used to open three fixed sections — אדם, סטטוס, עדיפות —
   which are three of a board's columns and not the board's columns. Everything
   somebody had added to their own board could only be filtered through the
   advanced builder, by building a sentence (column, operator, value) in order
   to ask a question with one answer.

   It now opens the columns THIS board has, each offering the values it holds.
   What it writes is the same condition tree the advanced builder edits and the
   server evaluates (backend/filter_ast.py) — so one model answers a small
   board in the browser, a large one in the database, and travels inside a
   saved view. These checks are about that tree being written correctly, which
   is the half that cannot be seen by looking at the panel.

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

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+JSON.stringify(x):''))); };

/* The board: two built-in columns and three of its own. `st.filters` is the
   live filter the panel reads and writes. */
function world(){
  const st = {
    board:{id:1, col_perms:{},
      columns:[{id:'col_a', type:'status', title:'שלב',
                options:[{id:'o1',label:'בעבודה',color:'#fdab3d'},
                         {id:'o2',label:'הושלם',color:'#00c875'},
                         {id:'o3',label:'תקוע',color:'#e2445c'}]},
               {id:'col_b', type:'people', title:'בודק'},
               {id:'col_c', type:'text',   title:'הערות'},
               {id:'col_d', type:'connect',title:'מקושר'}],
      members:[{id:3},{id:4}],
      tasks:[{id:1,status:'done',assignees:[{id:3}],custom_fields:{col_a:{label:'הושלם'}}},
             {id:2,status:'stuck',assignees:[{id:4}],custom_fields:{col_a:{label:'תקוע'}}},
             {id:3,status:'done',assignees:[{id:3}],custom_fields:{col_a:{label:'הושלם'}}},
             {id:4,status:'done',assignees:[],custom_fields:{}}]},
    users:[{id:3,name:'דנה'},{id:4,name:'רינה'}],
    me:{id:3},
    filters:{q:'',people:[],status:'',priority:'',sort:'',links:{col:'',mode:'',item:0},adv:null,advIds:null},
  };
  const names = ['advFilterRoot','advPicked','advSetPicked','advToggle','advLegacyPicks',
                 'advDropLegacy','advPickedAll','advCount','advFields','advColHidden',
                 'colFilterChips','colFilterSummary','advTextOf','advSetText','customColumns',
                 'boardPeople','statusColOpts','advPickChip','colChipsHTML','colAssigned','colEmptyChips',
                 'qfCounts','advCell','advRuleMatch','advMatch','statusKeyOf',
                 'priorityKeyOf','advSpan','advDay','advIso'];
  const body = names.map(grab).join('\n')
    + '\n' + konst('advOwnGroup') + '\n' + konst('advField') + '\n' + konst('advEmpty') + '\n'
    + konst('colChipKey') + '\n' + konst('userName') + '\n'
    + konst('COL_EMPTY_CHIPS') + '\n' + konst('COL_EMPTY_WORDS') + '\n'
    + `const ADV_DATES=[['today','היום'],['this_week','השבוע']];\n`
    + `const QF_COUNT_MAX=4000;\n`;
  const api = new Function('st','meId','esc','boardStatusList','boardPriorityList','ADV_KINDS',
    'STATUS_OPTS','refreshToolbar','reArrange','renderView','advAskServer','advChanged','Paged',
    'avatarInner',
    body + `;return {advPicked,advPickedAll,advToggle,advSetPicked,advCount,advFields,
                     colFilterChips,colFilterSummary,advTextOf,advSetText,
                     advPickChip,colChipsHTML,qfCounts,colAssigned,colEmptyChips};`)(
    st,
    () => st.me && st.me.id,
    x => String(x==null?'':x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    () => [{key:'done',he:'בוצע',c:'#00c875'},{key:'stuck',he:'תקוע',c:'#e2445c'},
           {key:'backlog',he:'בתכנון',c:'#9699a6'}],
    () => [{key:'high',he:'גבוהה',c:'#e2445c'},{key:'low',he:'נמוכה',c:'#579bfc'}],
    {text:'text', status:'status', people:'people', date:'date', checkbox:'check',
     number:'number', dropdown:'status'},
    [{label:'ברירת מחדל',color:'#c4c4c4'}],
    ()=>{}, ()=>{}, ()=>{}, ()=>{}, ()=>{}, {on:false,rows:[],total:0},
    u=>`<i data-face="${(u&&u.id)==null?'':u.id}"></i>`);
  return [api, st];
}

// ── the columns offered are the board's own ───────────────────────────────
{
  const [f] = world();
  const ids = f.advFields().map(x=>x.id);
  ck('the built-in columns are offered',
     ['status','priority','assignees','due','title'].every(k=>ids.includes(k)), ids);
  ck('...and every column this board added', ids.includes('col_a') && ids.includes('col_b')
     && ids.includes('col_c'), ids);
  ck('a column with nothing to ask about yet is not offered', !ids.includes('col_d'), ids);
}
{
  const [f, st] = world();
  st.board.col_perms = {col_a:'none'};
  ck('a column this person may not see is not offered to filter by',
     !f.advFields().map(x=>x.id).includes('col_a'));
}

// ── what one column offers ────────────────────────────────────────────────
{
  const [f] = world();
  const col = f.advFields().find(x=>x.id==='col_a');
  const chips = f.colFilterChips(col);
  ck('a status column offers its own words, in its own colours',
     chips.map(c=>c.label).join()==='בעבודה,הושלם,תקוע'
     && chips[2].color==='#e2445c', chips);
  ck('...each one as the rule it writes', chips[0].op==='eq' && chips[0].v==='בעבודה');
}
{
  const [f] = world();
  const chips = f.colFilterChips(f.advFields().find(x=>x.id==='col_b'));
  ck('a people column offers "אני" first, then the board\'s members',
     chips.map(c=>c.label).join()==='אני,רינה', chips.map(c=>c.label));
  ck('...and "אני" travels as the token, not as a user id', chips[0].v==='me');
  ck('the person looking is listed once, as "אני" and not also by name',
     !chips.some(c=>c.label==='דנה'), chips.map(c=>c.label));
}
{
  /* …unless a rule already names them by id. That is somebody's deliberate
     "this person specifically", and the panel has to show what is filtering. */
  const [f, st] = world();
  st.filters.adv={op:'and',rules:[{op:'or',rules:[{field:'col_b',op:'has',v:3,v2:''}]}]};
  const chips = f.colFilterChips(f.advFields().find(x=>x.id==='col_b'));
  ck('a rule naming the viewer by id still shows their name',
     chips.map(c=>c.label).join()==='אני,דנה,רינה', chips.map(c=>c.label));
}
{
  const [f, st] = world();
  st.me=null;                       // nobody signed in: no token to offer
  const chips = f.colFilterChips(f.advFields().find(x=>x.id==='col_b'));
  ck('with no "אני" to offer, everyone is listed by name',
     chips.map(c=>c.label).join()==='דנה,רינה', chips.map(c=>c.label));
}
{
  const [f] = world();
  ck('a text column offers no list of values to pick from',
     f.colFilterChips(f.advFields().find(x=>x.id==='col_c')).length===0);
}

// ── a people column: the face, who is still on the board, and who has left ──
{
  const [f] = world();
  const chips = f.colFilterChips(f.advFields().find(x=>x.id==='col_b'));
  ck('every person chip carries the person it names, so a face can be drawn',
     chips.every(c=>c.av!=null) && String(chips[0].av.id)==='3'
     && String(chips[1].av.id)==='4', chips.map(c=>c.av));
  ck('a status chip still travels as a colour and not as a person',
     f.colFilterChips(f.advFields().find(x=>x.id==='col_a')).every(c=>c.av==null));
}
{
  /* Somebody whose account was switched off is no longer a board member, and
     their items are still on the board. Offering only members would leave
     those rows reachable by no chip at all. */
  const [f, st] = world();
  st.users.push({id:5, name:'אורית', is_active:false});
  st.board.tasks[1].custom_fields.col_b=[5];
  const chips = f.colFilterChips(f.advFields().find(x=>x.id==='col_b'));
  ck('a deactivated person who is on an item of this board is still offered',
     chips.some(c=>String(c.v)==='5'), chips.map(c=>c.label));
  ck('...and is marked as deactivated rather than listed as a colleague',
     chips.find(c=>String(c.v)==='5').off===true, chips);
  ck('...while the board\'s own members are not marked',
     chips.filter(c=>String(c.v)==='4').every(c=>!c.off), chips);
}
{
  const [f, st] = world();
  st.users.push({id:6, name:'מי שעזבה', is_active:false});   // no items here
  const chips = f.colFilterChips(f.advFields().find(x=>x.id==='col_b'));
  ck('a deactivated person with nothing on this board is not offered',
     !chips.some(c=>String(c.v)==='6'), chips.map(c=>c.label));
}
{
  const [f, st] = world();
  st.users.push({id:5, name:'אורית', is_active:false});
  st.board.tasks[0].assignees=[{id:3},{id:5}];
  const chips = f.colFilterChips(f.advFields().find(x=>x.id==='assignees'));
  ck('the built-in אחראים column counts who is on its items the same way',
     chips.some(c=>String(c.v)==='5'&&c.off===true), chips.map(c=>c.label));
  f.advPickChip('assignees', chips.findIndex(c=>String(c.v)==='5'));
  ck('...and picking a person who has left writes the same rule as anyone else',
     f.advPicked('assignees').map(p=>p.op+':'+p.v).join()==='has:5',
     st.filters.adv);
}

// ── ריק, in the words of the column being asked ──────────────────────────
{
  const [f] = world();
  const people = f.colEmptyChips(f.advFields().find(x=>x.id==='col_b'));
  ck('a people column asks about a person, not about emptiness',
     people.map(c=>c.label).join()==='משויך,ללא שיוך', people.map(c=>c.label));
  ck('"ללא שיוך" is the last thing the column offers',
     people[people.length-1].op==='empty');
  const text = f.colEmptyChips(f.advFields().find(x=>x.id==='col_c'));
  ck('every other column still says ריק / אינו ריק',
     text.map(c=>c.label).join()==='אינו ריק,ריק', text.map(c=>c.label));
}
{
  /* The words changed and the conditions did not: a filter written by one
     name is the same filter read back under the other. */
  const [f, st] = world();
  const col = f.advFields().find(x=>x.id==='col_b');
  const i = f.colFilterChips(col).length + 1;          // the last chip: ללא שיוך
  f.advPickChip('col_b', i);
  ck('"ללא שיוך" writes the plain "empty" condition',
     f.advPicked('col_b').map(p=>p.op).join()==='empty', st.filters.adv);
  ck('...and reads back as picked, so clicking it again turns it off',
     f.colFilterSummary(col)==='ללא שיוך', f.colFilterSummary(col));
}

// ── what the panel actually draws ────────────────────────────────────────
{
  const [f, st] = world();
  st.users.push({id:5, name:'אורית', is_active:false});
  st.board.tasks[1].custom_fields.col_b=[5];
  const col = f.advFields().find(x=>x.id==='col_b');
  const html = f.colChipsHTML(col, f.advPickedAll('col_b'), null);
  ck('a person is drawn with their avatar', html.includes('data-face="4"'), html.slice(0,200));
  ck('...and nobody is drawn with a colour dot', !html.includes('class="dot"'));
  ck('a deactivated person is greyed and says so',
     html.includes('qf-v off') && html.includes('qf-v-off'), html);
  ck('and the column ends with ללא שיוך', html.lastIndexOf('ללא שיוך')>html.lastIndexOf('משויך'));
}

// ── picking values writes the tree ────────────────────────────────────────
{
  const [f, st] = world();
  f.advToggle('col_a','eq','בעבודה');
  ck('one value is one condition',
     f.advCount(st.filters.adv)===1, st.filters.adv);
  ck('...held in a group of its own column', st.filters.adv.op==='and'
     && st.filters.adv.rules[0].op==='or'
     && st.filters.adv.rules[0].rules[0].field==='col_a', st.filters.adv);

  f.advToggle('col_a','eq','תקוע');
  ck('two values in one column are alternatives — "or" inside it',
     st.filters.adv.rules.length===1 && st.filters.adv.rules[0].op==='or'
     && st.filters.adv.rules[0].rules.length===2, st.filters.adv);

  f.advToggle('col_b','has',4);
  ck('two columns narrow together — "and" between them',
     st.filters.adv.op==='and' && st.filters.adv.rules.length===2, st.filters.adv);
  ck('...and the panel reads back what is picked',
     f.advPicked('col_a').map(p=>p.v).join()==='בעבודה,תקוע'
     && String(f.advPicked('col_b')[0].v)==='4');
}
{
  const [f, st] = world();
  f.advToggle('col_a','eq','בעבודה');
  f.advToggle('col_a','eq','בעבודה');          // the same chip again
  ck('picking a value twice turns it off', f.advCount(st.filters.adv)===0, st.filters.adv);
  ck('...and the filter is emptied rather than left as a group matching everything',
     st.filters.adv===null, st.filters.adv);
}

// ── ריק / אינו ריק, and a word to look for ────────────────────────────────
{
  const [f, st] = world();
  f.advToggle('col_c','empty');
  ck('"ריק" is a condition with no value', st.filters.adv.rules[0].rules[0].op==='empty');
  f.advSetText('col_c','חוזה');
  ck('a text column takes a word, beside what is already picked',
     f.advPicked('col_c').map(p=>p.op).sort().join()==='empty,has', f.advPicked('col_c'));
  ck('...and the word is read back into the box', f.advTextOf('col_c')==='חוזה');
  f.advSetText('col_c','');
  ck('clearing the box leaves the rest of the column alone',
     f.advPicked('col_c').map(p=>p.op).join()==='empty');
}

// ── the toolbar's own three, from a saved view made before this panel ─────
{
  const [f, st] = world();
  st.filters.status='done';
  st.filters.people=[3];
  ck('an old view\'s status shows as picked on its column',
     f.advPickedAll('status').map(p=>p.op+':'+p.v).join()==='eq:done');
  ck('...and its people on theirs', f.advPickedAll('assignees').map(p=>String(p.v)).join()==='3');
  ck('...and the column says so in its header', f.colFilterSummary(
     f.advFields().find(x=>x.id==='status'))==='בוצע');

  f.advToggle('status','eq','stuck');
  ck('touching that column moves it into the tree', st.filters.status==='',
     st.filters.status);
  ck('...carrying what was already picked, plus the new value',
     f.advPicked('status').map(p=>p.v).sort().join()==='done,stuck', f.advPicked('status'));
  ck('...and leaves the other legacy field alone', st.filters.people.join()==='3');
}

// ── rules somebody built by hand are not the panel's to rewrite ───────────
{
  const [f, st] = world();
  // "(סטטוס = בוצע or עדיפות = גבוהה)" — one group, two columns: not a shape
  // the panel writes, and not one it may take apart
  st.filters.adv={op:'and',rules:[{op:'or',rules:[
    {field:'status',op:'eq',v:'done',v2:''},{field:'priority',op:'eq',v:'high',v2:''}]}]};
  ck('a mixed group is not read as any one column\'s selection',
     f.advPicked('status').length===0 && f.advPicked('priority').length===0);
  f.advToggle('col_a','eq','הושלם');
  ck('...and it survives a pick on another column untouched',
     st.filters.adv.rules.length===2 && st.filters.adv.rules[0].rules.length===2,
     st.filters.adv);
  ck('...so the count is what both together say', f.advCount(st.filters.adv)===3);
}
{
  const [f, st] = world();
  // an "or" tree somebody built: adding a column must narrow it, not widen it
  st.filters.adv={op:'or',rules:[{field:'status',op:'eq',v:'done',v2:''},
                                 {field:'priority',op:'eq',v:'high',v2:''}]};
  f.advToggle('col_a','eq','תקוע');
  ck('an "or" filter is kept whole as one branch of the new "and"',
     st.filters.adv.op==='and' && st.filters.adv.rules[0].op==='or'
     && st.filters.adv.rules[0].rules.length===2, st.filters.adv);
  ck('...with the column beside it', st.filters.adv.rules.length===2);
}

// ── a value with an apostrophe in it ──────────────────────────────────────
{
  const [f, st] = world();
  st.board.columns[0].options.push({id:'o4',label:"ג'ובים",color:'#784bd1'});
  const col = f.advFields().find(x=>x.id==='col_a');
  const html = f.colChipsHTML(col, []);
  ck('a chip hands back its position, not the word written on it',
     html.includes("advPickChip('col_a',3)") && !html.includes("'ג'ובים'"), html.slice(0,200));
  f.advPickChip('col_a', 3);
  ck('...and clicking it filters by that word', f.advPicked('col_a').map(p=>p.v).join()==="ג'ובים",
     f.advPicked('col_a'));
  f.advPickChip('col_a', 4);          // the first of the two that follow the values
  ck('...and the chips after the values are "אינו ריק" and "ריק"',
     f.advPicked('col_a').map(p=>p.op).sort().join()==='eq,filled', f.advPicked('col_a'));
}

// ── how many items carry each value ───────────────────────────────────────
{
  const [f] = world();
  const n = f.qfCounts();
  ck('a status column counts the items on each of its words',
     n.col_a['eq|הושלם']===2 && n.col_a['eq|תקוע']===1, n.col_a);
  ck('...a built-in column too', n.status['eq|done']===3 && n.status['eq|stuck']===1, n.status);
  ck('a people column counts the items each person is on',
     n.assignees['has|3']===2 && n.assignees['has|4']===1, n.assignees);
  ck('..."אני" counts the person looking', n.assignees['has|me']===2, n.assignees);
  ck('every column counts ריק and אינו ריק',
     n.col_a['empty|']===1 && n.col_a['filled|']===3, n.col_a);
  ck('a cell with nothing in it is not counted as a value of its own',
     !Object.keys(n.col_a).includes('eq|'), Object.keys(n.col_a));
}
{
  const [f, st] = world();
  st.board.tasks = [];
  ck('a board with no items counts nothing rather than failing',
     f.qfCounts().status['eq|done']===undefined);
}
{
  const [f, st] = world();
  st.filters.status='done';
  const n = f.qfCounts();
  ck('the numbers say what the BOARD holds, not what is left after filtering',
     n.status['eq|stuck']===1, n.status);
}

// ── the rows carry the number, and the picked one is marked ───────────────
{
  const [f, st] = world();
  const col = f.advFields().find(x=>x.id==='col_a');
  const html = f.colChipsHTML(col, f.advPickedAll('col_a'), f.qfCounts());
  ck('each value shows its count beside it', html.includes('>2<') && html.includes('qf-v-n'),
     html.slice(0,160));
  f.advToggle('col_a','eq','הושלם');
  const lit = f.colChipsHTML(col, f.advPickedAll('col_a'), f.qfCounts());
  ck('a picked value is marked, for the eye and for a screen reader',
     lit.includes('qf-v sel') && lit.includes('aria-pressed="true"'));
}

// ── moving along the strip ────────────────────────────────────────────────
/* scrollLeft counts away from the starting edge, which in RTL is the right
   one, and runs NEGATIVE as the strip moves. Both arrows are decided by how
   far it has travelled, which is that number's absolute value — the one shape
   of this arithmetic that is the same in both directions. */
{
  const nodes = {};
  const el = {scrollLeft:0, clientWidth:600, scrollWidth:1400,
              style:{}, scrollBy(o){ this.scrollLeft += o.left; }};
  const doc = {getElementById:id=>id==='qf-cols'?el:(nodes[id]=nodes[id]||
    {classes:new Set(), classList:{toggle:(c,on)=>on?nodes[id].classes.add(c):nodes[id].classes.delete(c)}})};
  const fns = new Function('document','_qfScroll',
    grab('qfArrows')+grab('qfScroll')+grab('qfRestore')
    +';return {qfArrows,qfScroll,qfRestore,get scroll(){return _qfScroll;}};')(doc, 0);
  const shown = id => nodes[id] && nodes[id].classes.has('show');

  fns.qfArrows();
  ck('at the first column only the "more columns" arrow shows',
     !shown('qf-prev') && shown('qf-next'));

  el.scrollLeft = -400;                     // moved along, in RTL's own sign
  fns.qfArrows();
  ck('in the middle both arrows show', shown('qf-prev') && shown('qf-next'));

  el.scrollLeft = -(el.scrollWidth - el.clientWidth);
  fns.qfArrows();
  ck('at the last column the "more columns" arrow is gone',
     shown('qf-prev') && !shown('qf-next'), [...(nodes['qf-next'].classes)]);

  el.scrollLeft = 0; el.scrollWidth = 600;  // every column already on screen
  fns.qfArrows();
  ck('a strip that fits shows no arrows at all', !shown('qf-prev') && !shown('qf-next'));
}
{
  const el = {scrollLeft:0, clientWidth:600, scrollWidth:1400, style:{},
              scrollBy(o){ this.scrollLeft += o.left; }};
  const doc = {getElementById:()=>el};
  const fns = new Function('document','_qfScroll',
    grab('qfArrows')+grab('qfScroll')+grab('qfRestore')
    +';return {qfScroll,qfArrows};')(doc, 0);
  fns.qfScroll(-1);
  ck('one press moves about a screenful, toward the far columns',
     el.scrollLeft < -400 && el.scrollLeft > -600, el.scrollLeft);
  const was = el.scrollLeft;
  fns.qfScroll(1);
  ck('and the other arrow brings it back', el.scrollLeft > was);
}

// ── a mouse wheel over the strip ──────────────────────────────────────────
{
  const mk = (scrollLeft, scrollWidth) => {
    const el = {scrollLeft, clientWidth:540, scrollWidth, style:{}, scrollBy(){}};
    const fns = new Function('document','_qfScroll',
      grab('qfWheel')+grab('qfArrows')+';return {qfWheel};')(
      {getElementById:id=>id==='qf-cols'?el:({classList:{toggle(){}}})}, 0);
    return [fns, el];
  };
  const ev = d => { let stopped=false;
    return {deltaY:d, deltaX:0, preventDefault(){stopped=true;}, get taken(){return stopped;}}; };

  let [f, el] = mk(0, 1400);
  let e = ev(120);
  f.qfWheel(e);
  ck('a wheel down moves the strip toward the far columns',
     e.taken && el.scrollLeft < 0, el.scrollLeft);

  [f, el] = mk(-400, 1400);
  e = ev(-120);
  f.qfWheel(e);
  ck('...and a wheel up brings it back', e.taken && el.scrollLeft > -400, el.scrollLeft);

  [f, el] = mk(-(1400-540), 1400);
  e = ev(120);
  f.qfWheel(e);
  ck('at the last column the wheel is handed back to the panel',
     !e.taken && el.scrollLeft === -(1400-540), el.scrollLeft);

  [f, el] = mk(0, 1400);
  e = ev(-120);
  f.qfWheel(e);
  ck('and at the first column too, in the other direction', !e.taken);

  [f, el] = mk(0, 500);
  e = ev(120);
  f.qfWheel(e);
  ck('a strip with every column on screen never takes the wheel', !e.taken);

  [f, el] = mk(0, 1400);
  e = ev(99999);
  f.qfWheel(e);
  ck('one enormous wheel event cannot scroll past the last column',
     el.scrollLeft >= -(1400-540), el.scrollLeft);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
