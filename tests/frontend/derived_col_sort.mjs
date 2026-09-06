/* The derived columns — מזהה פריט, מועד יצירה, יוצר הרשומה, נוסחה, שדה מראה —
   hold nothing in custom_fields, so a comparator that only reads custom_fields
   scores every row the same and the click does nothing at all. Runs the real
   customSortVal / sortVal / colCompare out of index.html against stub items.
   Driven by tests/test_derived_col_sort.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}

// ── stubs: everything the three real functions reach for ──
const st = {users:[{id:1,name:'דנה'},{id:2,name:'אבי'}], linkCache:{}};
const COLUMNS = [];
const customColumns = () => COLUMNS;
const colStatusOrder = () => 0;
const connectIsMulti = () => true;
// one formula column in this fixture: the item's number field, doubled
const evalFormula = (col,t) => (t.custom_fields||{}).n==null ? '' : (t.custom_fields||{}).n*2;
const statusOrder = () => 0, prioOrder = () => 0;

const api = new Function(
  'st','customColumns','colStatusOrder','connectIsMulti','evalFormula','statusOrder','prioOrder',
  [grab('customSortVal'), grab('sortVal'), grab('colCompare'),
   'return {customSortVal, sortVal, colCompare};'].join('\n'))
  (st, customColumns, colStatusOrder, connectIsMulti, evalFormula, statusOrder, prioOrder);

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

/* sort the way the board does: colCompare, times -1 for descending */
function order(items, col, dir='asc'){
  COLUMNS.length=0; COLUMNS.push(col);
  const s = dir==='desc' ? -1 : 1;
  return items.slice().sort((a,b)=>api.colCompare(a,b,col.id)*s).map(t=>t.id);
}

// ── מזהה פריט: the column she reported ──
const idCol = {id:'sys_item_id', type:'item_id', title:'מספר מזהה'};
const byId = [
  {id:'c', item_uid:30000000002},
  {id:'a', item_uid:10000000001},
  {id:'b', item_uid:20000000003},
];
ck('item_id ascending is by the identifier',
   String(order(byId,idCol))==='a,b,c', String(order(byId,idCol)));
ck('item_id descending is the reverse',
   String(order(byId,idCol,'desc'))==='c,b,a', String(order(byId,idCol,'desc')));
// a uid is issued asynchronously, so a fresh item can be without one
ck('an item with no identifier sorts last ascending',
   String(order(byId.concat([{id:'z'}]),idCol))==='a,b,c,z',
   String(order(byId.concat([{id:'z'}]),idCol)));
// 11-digit ids compare the same as text; different lengths are the real test
ck('identifiers of different lengths compare as numbers',
   String(order([{id:'ten',item_uid:10},{id:'two',item_uid:2}],idCol))==='two,ten');
// the bug itself: every row scoring the same is what made the button look dead
ck('rows do not all score the same',
   new Set(byId.map(t=>api.sortVal(t,idCol.id))).size===3);

// ── the other four derived columns, broken the same way ──
const created = {id:'c1', type:'created_at', title:'מועד יצירה'};
ck('created_at sorts by the timestamp',
   String(order([{id:'new',created_at:'2026-09-05T10:00:00'},
                 {id:'old',created_at:'2024-01-02T08:00:00'}],created))==='old,new');
ck('an item with no timestamp sorts last ascending',
   String(order([{id:'x'},{id:'old',created_at:'2024-01-02T08:00:00'}],created))==='old,x');

const author = {id:'c2', type:'created_by', title:'יוצר הרשומה'};
ck('created_by sorts by the name, not the user id',
   String(order([{id:'dana',created_by:1},{id:'avi',created_by:2}],author))==='avi,dana');
ck('an item whose author is unknown sorts last ascending',
   String(order([{id:'none',created_by:99},{id:'dana',created_by:1}],author))==='dana,none');

const formula = {id:'c3', type:'formula', title:'נוסחה'};
ck('a formula sorts by what it evaluates to',
   String(order([{id:'big',custom_fields:{n:9}},{id:'small',custom_fields:{n:3}}],formula))==='small,big');
ck('an empty formula sorts last ascending',
   String(order([{id:'empty',custom_fields:{}},{id:'small',custom_fields:{n:3}}],formula))==='small,empty');

const mirror = {id:'c4', type:'mirror', title:'שדה מראה'};
ck('a mirror sorts by the text it shows',
   String(order([{id:'bet',custom_fields:{c4:[{text:'ב'}]}},
                 {id:'alef',custom_fields:{c4:[{text:'א'}]}}],mirror))==='alef,bet');
ck('an empty mirror sorts last ascending',
   String(order([{id:'empty',custom_fields:{c4:[]}},
                 {id:'alef',custom_fields:{c4:[{text:'א'}]}}],mirror))==='alef,empty');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
