/* מקרי קצה — a column that was deleted, and a person who left.

   Both are the same shape of problem: a saved filter outlives the thing it
   names. They are handled in opposite ways, and the opposition is the point.

   A DELETED COLUMN takes its rule out of the tree. Letting it answer true
   instead is the obvious shortcut and it is wrong: inside an "וגם" group the
   two are identical, and inside an "או" group they are opposites — one
   deleted column would make the group true and quietly show the whole board,
   with the filter still lit and the badge still counting.

   A DEPARTED PERSON keeps their rule. The column still exists, and somebody
   leaving does not unassign them from what they were working on — "what was
   אורית doing before she left" is a question asked precisely because she
   left. Only the label changes. The failure here is subtler: a <select>
   drawn without an option for its own value shows the placeholder, and the
   next redraw writes that placeholder back. Nobody would decide to drop her
   from the filter; the filter would just forget her.

   Driven by tests/test_filter_edge_cases.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const from = src.indexOf('const ADV_KINDS = {');
const engine = src.slice(from, src.indexOf('const IS_ITEM_ID='));

const ME=7;
// רינה is on the board; אורית left (deactivated); דנה was taken off the board
const ALL=[{id:7,name:'רינה'},{id:8,name:'דנה'},{id:9,name:'אורית',is_active:false}];
const ONBOARD=[{id:7,name:'רינה'}];
let COLUMNS=[
  {id:'c_pri', title:'עדיפות משנית', type:'status', options:[{label:'א'},{label:'ב'}]},
  {id:'c_ppl', title:'מבצע', type:'people'},
  {id:'c_bud', title:'תקציב', type:'number'},      // closed to this reader
];
// the board states each column's permission once, for every item
const COL_PERMS={c_pri:'edit', c_ppl:'edit', c_bud:'none'};

const api=new Function('st','meId','customColumns','boardStatusList','boardPriorityList',
  'boardPeople','statusColOpts','statusKeyOf','priorityKeyOf',
  engine + `
  return {advFields, advField, advChoices, advPrune, advPersonLabel,
          advRuleMatch, advMatch, advCount, advColHidden, advKnownField};`)(
  {board:{columns:COLUMNS, col_perms:COL_PERMS}, users:ALL},
  ()=>ME, ()=>COLUMNS,
  ()=>[{key:'todo',he:'לביצוע'},{key:'done',he:'בוצע'}],
  ()=>[{key:'high',he:'גבוהה'}],
  ()=>ONBOARD.slice(),
  col=>{ const c=(col&&typeof col==='object')?col:COLUMNS.find(x=>x.id===col);
         return ((c&&c.options)||[]).map(o=>({id:null,label:o.label,color:'#ccc'})); },
  t=>t.status||null, t=>t.priority||null);

const {advPrune, advChoices, advField, advPersonLabel, advMatch, advCount,
       advColHidden, advKnownField} = api;

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,220):''))); };

const item=o=>({id:o.id||1, title:o.title||'פריט', status:o.status, priority:o.priority,
  assignees:(o.people||[]).map(id=>({id})), custom_fields:o.cf||{}});

// ── 1. a column that was deleted ──────────────────────────────────────────
{
  const tree={op:'and',rules:[
    {field:'status',op:'eq',v:'done'},
    {field:'c_gone',op:'eq',v:'x'},          // deleted since
  ]};
  const {tree:t,removed}=advPrune(tree);
  ck('the rule whose column is gone is removed from the tree',
     t.rules.length===1 && t.rules[0].field==='status', JSON.stringify(t));
  ck('...and it is named, so the person can be told', removed.join()==='c_gone', removed);
  ck('...and the badge stops counting it', advCount(t)===1);
}
{
  /* The case that makes removing different from answering true. */
  const or={op:'or',rules:[
    {field:'status',op:'eq',v:'done'},
    {field:'c_gone',op:'eq',v:'x'},
  ]};
  const {tree:t}=advPrune(or);
  const open=item({status:'todo'}), done=item({status:'done'});
  ck('inside "או", pruning leaves the remaining alternative deciding',
     advMatch(done,t)===true && advMatch(open,t)===false,
     JSON.stringify({done:advMatch(done,t), open:advMatch(open,t)}));
  ck('...which is the opposite of what answering true would have done — '
     +'one deleted column showing the entire board',
     advMatch(open,or)===true, 'the unpruned tree matches everything, as expected');
}
{
  const nested={op:'and',rules:[
    {field:'status',op:'eq',v:'done'},
    {op:'or',rules:[{field:'c_gone',op:'eq',v:'1'},{field:'c_also_gone',op:'eq',v:'2'}]},
  ]};
  const {tree:t,removed}=advPrune(nested);
  ck('a group left empty by the pruning goes too — an empty group matches '
     +'everything, which is the same bug one level up',
     t.rules.length===1 && t.rules[0].field==='status', JSON.stringify(t));
  ck('...and both are reported', removed.length===2, removed);
}
{
  const {tree:t,removed}=advPrune({op:'and',rules:[{field:'status',op:'eq',v:'done'}]});
  ck('a tree with nothing missing is left exactly as it was',
     removed.length===0 && t.rules.length===1);
  ck('an empty tree prunes to an empty tree, not to null',
     advPrune({op:'and',rules:[]}).tree.rules.length===0);
  ck('nothing at all is nothing at all', advPrune(null).tree===null);
}
{
  // every rule gone: the board must show, not vanish
  const {tree:t}=advPrune({op:'and',rules:[{field:'c_gone',op:'eq',v:'1'}]});
  ck('a view whose every rule is gone shows the whole board',
     advMatch(item({}),t)===true && advCount(t)===0, JSON.stringify(t));
}

// ── 2. a person who left ──────────────────────────────────────────────────
{
  const tree={op:'and',rules:[{field:'assignees',op:'has',v:'9'}]};
  const {removed}=advPrune(tree);
  ck('a rule naming somebody who left is NOT pruned — the column still exists',
     removed.length===0, removed);
  ck('...and it keeps answering: what they were assigned to is still theirs',
     advMatch(item({people:[9]}),tree)===true && advMatch(item({people:[7]}),tree)===false);
}
{
  const f=advField('assignees');
  const offered=advChoices(f).map(c=>c.v);
  ck('the picker does not offer somebody who left for a NEW rule',
     !offered.includes('9'), offered.join(','));
  const withHer=advChoices(f,'9');
  ck('...but a rule that already names her keeps an option for her, or the '
     +'next redraw would write the placeholder back over her id',
     withHer.some(c=>c.v==='9'), withHer.map(c=>c.v).join(','));
  ck('...labelled so it is obvious why she is not in the list',
     /לא פעיל/.test(withHer.find(c=>c.v==='9').label),
     withHer.find(c=>c.v==='9').label);
  ck('...and marked as gone, so the field can be drawn differently',
     withHer.find(c=>c.v==='9').gone===true);
}
{
  ck('somebody deactivated is "לא פעיל"', /לא פעיל/.test(advPersonLabel(9)));
  ck('...and keeps their name beside it, because the rule has to stay readable',
     advPersonLabel(9).includes('אורית'), advPersonLabel(9));
  ck('somebody merely taken off the board reads the same way',
     /לא פעיל/.test(advPersonLabel(8)) && advPersonLabel(8).includes('דנה'), advPersonLabel(8));
  ck('an id nobody has ever heard of still says something',
     /לא פעיל/.test(advPersonLabel(999)) && advPersonLabel(999).includes('999'),
     advPersonLabel(999));
  ck('somebody still on the board is just their name',
     advPersonLabel(7)==='רינה', advPersonLabel(7));
}
{
  // the same protection for a status option that was deleted
  const f=advField('c_pri');
  ck('a status value no longer offered keeps its option too',
     advChoices(f,'ג').some(c=>c.v==='ג'), advChoices(f,'ג').map(c=>c.v).join(','));
  ck('...and says it is gone', /אינו קיים/.test(advChoices(f,'ג').find(c=>c.v==='ג').label));
  ck('a value that IS offered adds nothing',
     advChoices(f,'א').length===2, advChoices(f,'א').map(c=>c.v).join(','));
}

// ── 3. a column this person may not see ──────────────────────────────────
/* Dropping the rule is the SAFE direction, and the reason is the opposite of
   the intuitive one: applying it is the leak. "תקציב גדול מ-מיליון", run for
   somebody who cannot see budgets, hands them the figures as a row set —
   they read the answer off which rows survived. Dropping it hands them
   nothing at all. */
{
  ck('a column closed to this reader is not offered for a new rule',
     !api.advFields().map(f=>f.id).includes('c_bud'),
     api.advFields().map(f=>f.id).join(','));
  ck('...while the columns they may see still are',
     api.advFields().map(f=>f.id).includes('c_pri'));
  ck('advColHidden reads the board’s own permission map',
     advColHidden('c_bud')===true && advColHidden('c_pri')===false);
}
{
  const tree={op:'and',rules:[
    {field:'status',op:'eq',v:'done'},
    {field:'c_bud',op:'gt',v:1000000},
  ]};
  const {tree:t,removed,denied}=advPrune(tree);
  ck('the rule over the closed column does not run for them',
     t.rules.length===1 && t.rules[0].field==='status', JSON.stringify(t));
  ck('...and it is reported as a permission, not as a deletion',
     denied.join()==='c_bud' && removed.length===0,
     JSON.stringify({denied,removed}));
  ck('...so they see MORE rows than the author meant, and nothing about the '
     +'column itself',
     advMatch(item({status:'done', cf:{c_bud:5}}),t)===true);
}
{
  // the two reasons are told apart, which is the point of keeping both lists
  const {removed,denied}=advPrune({op:'and',rules:[
    {field:'c_bud',op:'gt',v:1},       // exists, closed
    {field:'c_vanished',op:'eq',v:'x'}, // does not exist at all
  ]});
  ck('"you may not see it" and "it was deleted" are different answers',
     denied.join()==='c_bud' && removed.join()==='c_vanished',
     JSON.stringify({denied,removed}));
  ck('advKnownField is what separates them',
     advKnownField('c_bud')===true && advKnownField('c_vanished')===false);
}
{
  const src2=src.slice(src.indexOf('  apply(v){'), src.indexOf('  async ask(){'));
  ck('the reader is told which of the two happened, in different words',
     /העמודות שלהם נמחקו/.test(src2) && /אין לך הרשאת צפייה/.test(src2), src2.slice(0,200));
  ck('and the stricter policy refuses to open the view at all',
     /filter_column_policy[\s\S]*block[\s\S]*return;/.test(src2), src2.slice(0,400));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
