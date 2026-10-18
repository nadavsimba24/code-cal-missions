/* Finding an item by the number in its "מזהה פריט" column.

   The id is the one thing about an item that travels outside the board — it is
   what a person reads out on the phone, pastes into a mail or quotes in a
   ticket, and the column exists to be copied off a row. Searching the board for
   it found nothing: the box looked at titles, descriptions, assignees and the
   names of linked items, and never at the number itself.

   The number is eleven digits, which is why the query has to look like an id
   before it is treated as one. Searching "5" would otherwise match nearly every
   item on the board — an id containing a 5 — and bury the item whose title has
   a 5 in it. Driven by tests/test_search_item_id.py. */
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
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

/* the real applyFilters, over the smallest board that can answer these */
const IS_ITEM_ID=/^const IS_ITEM_ID=.*$/m.exec(src)[0];
const st={filters:{q:'',people:[],status:'',priority:'',sort:'',links:{}},colSort:null,
          openSubs:new Set(), board:null};
const applyFilters=new Function(// applyFilters now also runs the advanced condition tree; these cases
// build none, so it counts nothing and matches everything
  // Paged: on a large board the rows on screen are the server's answer.
// These cases are a small board, so it is simply off.
  'st','linkNamesOf','linkIdsOf','statusKeyOf','priorityKeyOf','advCount','advMatch','Paged',
  IS_ITEM_ID+'\n'+grab('applyFilters')+'\nreturn applyFilters;')(
  st, t=>t.linkNames||[], ()=>[], t=>t.status, t=>t.priority, ()=>0, ()=>true, {on:false,rows:[]});

const BOARD=[
  {id:1, title:'תיקון מדרכה', item_uid:'20250611473'},
  {id:2, title:'החלפת תאורה', item_uid:'20250635198', description:'רחוב הרצל 5'},
  {id:3, title:'גיזום 5 עצים', item_uid:'44400000001', assignees:[{name:'רות לוי'}]},
  {id:4, title:'ללא מזהה', item_uid:null, linkNames:['היתר בנייה 137']},
  {id:5, title:'שיפוץ מגרש', item_uid:'70000000001',
   subtasks:[{id:51, title:'הזמנת חומרים', item_uid:'70000055500'}]},
];
const find=q=>{ st.filters.q=q; return applyFilters(BOARD).map(t=>t.id); };

// ── the id itself ──────────────────────────────────────────────────────────
ck('a whole id pasted into the box finds its item, and only it',
   find('20250611473').join()==='1', find('20250611473').join());
ck('a run of digits out of the middle of an id finds it too',
   find('611473').join()==='1', find('611473').join());
ck('the leading digits work, which is what a person reads out loud',
   find('202506').sort().join()==='1,2', find('202506').sort().join());
ck('an id that matches nothing finds nothing rather than everything',
   find('99999999999').length===0);
ck('an item with no id yet is simply not found by a number',
   !find('44400000001').includes(4));
ck('and an item with no id does not break the search either',
   find('היתר').join()==='4', find('היתר').join());

// ── and the digits that are not an id ──────────────────────────────────────
ck('one digit is not an id: it finds the item that says 5, not the whole board',
   find('5').sort().join()==='2,3', find('5').sort().join());
ck('two digits are not an id either',
   find('11').length===0, find('11').join());
ck('three digits are, since that is enough to mean one',
   find('444').join()==='3', find('444').join());
ck('a number with anything else in it is read as words, not as an id',
   find('473 ').join()==='1' && find('a473').length===0);

// ── nothing that used to be found stopped being found ─────────────────────
ck('by title', find('מדרכה').join()==='1');
ck('by description', find('הרצל').join()==='2');
ck('by the name of somebody it is assigned to', find('רות').join()==='3');
ck('by the name of an item it is linked to', find('בנייה').join()==='4');
ck('an empty box is not a filter', find('').length===5);

// ── a number copied off a sub-item's own row ───────────────────────────────
ck('the id of a sub-item finds the item that holds it',
   find('70000055500').join()==='5', find('70000055500').join());
ck('and the item is not dragged in by a sub-item id it does not hold',
   !find('70000099999').length);
ck('the item is still found by its own id, not only by its sub-items\'',
   find('70000000001').join()==='5');

/* the panel is opened for it, or the search answers with a row that does not
   carry the number that was searched for */
const setSearch=new Function('st','document','refreshToolbar','renderView',
  IS_ITEM_ID+'\n'+grab('setSearch')+'\nreturn setSearch;')(
  st, {getElementById:()=>null}, ()=>{}, ()=>{});
st.board={id:1,tasks:BOARD};
setSearch('70000055500');
ck('the item opens on the sub-item that answered the search',
   st.openSubs.has(5), [...st.openSubs].join());
st.openSubs.clear();
setSearch('שיפוץ');
ck('a search that is not a number opens nothing',
   st.openSubs.size===0);
st.openSubs.clear();
setSearch('70000000001');
ck('and neither does an id that belongs to the item itself',
   st.openSubs.size===0);

// ── the rule is stated where it is applied ────────────────────────────────
ck('what an id looks like is written down once, not in each place that asks',
   /^const IS_ITEM_ID=\/\^\\d\{3,\}\$\/;$/m.test(src)
   && (src.match(/IS_ITEM_ID/g)||[]).length===3);
ck('and the guard is what gates every id comparison',
   /const byId=IS_ITEM_ID\.test\(q\), hasId=x=>byId&&String\(x\.item_uid\|\|''\)\.includes\(q\)/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
