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
                 'boardPeople','statusColOpts','advPickChip','colChipsHTML',
                 'qfCounts','advCell','advRuleMatch','advMatch','statusKeyOf',
                 'priorityKeyOf','advSpan','advDay','advIso'];
  const body = names.map(grab).join('\n')
    + '\n' + konst('advOwnGroup') + '\n' + konst('advField') + '\n' + konst('advEmpty') + '\n'
    + konst('colChipKey') + '\n' + konst('userName') + '\n'
    + `const COL_EMPTY_CHIPS=[{op:'filled',label:'אינו ריק',color:''},{op:'empty',label:'ריק',color:''}];\n`
    + `const ADV_DATES=[['today','היום'],['this_week','השבוע']];\n`
    + `const QF_COUNT_MAX=4000;\n`;
  const api = new Function('st','meId','esc','boardStatusList','boardPriorityList','ADV_KINDS',
    'STATUS_OPTS','refreshToolbar','reArrange','renderView','advAskServer','advChanged','Paged',
    body + `;return {advPicked,advPickedAll,advToggle,advSetPicked,advCount,advFields,
                     colFilterChips,colFilterSummary,advTextOf,advSetText,
                     advPickChip,colChipsHTML,qfCounts};`)(
    st,
    () => st.me && st.me.id,
    x => String(x==null?'':x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    () => [{key:'done',he:'בוצע',c:'#00c875'},{key:'stuck',he:'תקוע',c:'#e2445c'},
           {key:'backlog',he:'בתכנון',c:'#9699a6'}],
    () => [{key:'high',he:'גבוהה',c:'#e2445c'},{key:'low',he:'נמוכה',c:'#579bfc'}],
    {text:'text', status:'status', people:'people', date:'date', checkbox:'check',
     number:'number', dropdown:'status'},
    [{label:'ברירת מחדל',color:'#c4c4c4'}],
    ()=>{}, ()=>{}, ()=>{}, ()=>{}, ()=>{}, {on:false,rows:[],total:0});
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
     chips.map(c=>c.label).join()==='אני,דנה,רינה', chips.map(c=>c.label));
  ck('...and "אני" travels as the token, not as a user id', chips[0].v==='me');
}
{
  const [f] = world();
  ck('a text column offers no list of values to pick from',
     f.colFilterChips(f.advFields().find(x=>x.id==='col_c')).length===0);
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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
