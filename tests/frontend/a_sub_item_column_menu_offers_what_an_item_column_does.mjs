/* The sub-item column menu offers what the item column menu offers for the
   same column — change of type, number settings, statuses — and no longer
   carries "בחר עמודות תת-פריט" in every column.
   Driven by tests/test_a_sub_item_column_menu_offers_what_an_item_column_does.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const fnSrc = name => {
  const i = src.indexOf('\nfunction '+name+'(');
  if (i < 0) throw new Error('not found: '+name);
  const j = src.indexOf('\n}\n', i);
  return src.slice(i+1, j+2);
};
const RETYPE = /const RETYPE_TYPES\s*=\s*\[[^\]]*\]/.exec(src);
if (!RETYPE) throw new Error('RETYPE_TYPES not found');

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

const cols = [
  {id:'c_num', title:'עלות', type:'number'},
  {id:'c_txt', title:'הערה', type:'text'},
  {id:'c_st',  title:'שלב', type:'status'},
  {id:'c_own', title:'רק כאן', type:'number'},
];
const st = {board:{my_role:'admin', columns:cols, sub_only:['c_own']}};
let opened = '';
const subCols = [
  {kind:'builtin', id:'item', key:'item'},
  {kind:'builtin', id:'status', key:'status', label:'סטטוס'},
  {kind:'builtin', id:'due', key:'due', label:'תאריך'},
  ...cols.map(c=>({kind:'custom', id:c.id, col:c})),
];
const F = new Function('st','customColumns','isBoardAdmin','subColumns','openCellPop','esc','formulaIsNumeric','Views',
  RETYPE[0]+';\n'+fnSrc('colTypeOptsHTML')+fnSrc('colMenu')+fnSrc('subColMenu')
  +'\nreturn {colMenu, subColMenu};')(
    st, () => cols, () => true, () => subCols, (_a, html) => { opened = html; },
    s => String(s), () => false, undefined);
const ev = {stopPropagation(){}, currentTarget:{}};
const sub = id => { opened=''; F.subColMenu(ev, id, 7); return opened; };
const item = id => { opened=''; F.colMenu(ev, id); return opened; };

// ── 1. change of type ──
ck('a sub-item column offers "שינוי סוג עמודה"', sub('c_txt').includes('שינוי סוג עמודה'), sub('c_txt'));
ck('...wired to the same retype as the item header', sub('c_txt').includes("retypeColumn('c_txt')"));

// ── 2. number settings ──
ck('a sub-item number column offers "הגדרות עמודת מספר"', sub('c_num').includes('הגדרות עמודת מספר'), sub('c_num'));
ck('...wired to the same dialog', sub('c_num').includes("numberSettings('c_num')"));
ck('a sub-item-only number column offers it too', sub('c_own').includes("numberSettings('c_own')"));
ck('a text column does not offer number settings', !sub('c_txt').includes('numberSettings'));
ck('a sub-item status column offers its labels', sub('c_st').includes("manageColStatuses('c_st')"));
ck('the built-in status column offers the board statuses', sub('status').includes('manageStatuses()'));

// ── the two menus agree, because they are one list ──
for (const id of ['c_num','c_txt','c_st']) {
  const opts = h => (h.match(/onclick="[^"]*(numberSettings|retypeColumn|manageColStatuses|editFormula|openMirrorConfig|openConnectConfig)\(/g)||[]).sort().join('|');
  ck(`the sub menu and the item menu offer the same type options for ${id}`, opts(sub(id))===opts(item(id)), opts(sub(id))+' vs '+opts(item(id)));
}

// ── 3. "בחר עמודות תת-פריט" ──
ck('"בחר עמודות תת-פריט" is no longer in a column\'s menu', !sub('c_num').includes('בחר עמודות תת-פריט') && !sub('due').includes('subColsConfig'));
ck('...it is still on the gear in the "תת-פריט" header', /subColsConfig\(\)/.test(fnSrc('subHeadHTML')));

// ── a shared column says it is shared ──
ck('a column shared with the items warns that a change applies to both', sub('c_num').includes('משותפת לפריטים ולתתי-הפריטים'));
ck('a sub-item-only column does not', !sub('c_own').includes('משותפת'));
ck('a column with nothing type-specific carries no warning', !sub('due').includes('משותפת'));

// ── and delete is still the sub-item's own ──
ck('deleting a shared column only takes it off the sub-items', sub('c_num').includes("removeSubCol(event,'c_num')"));
ck('deleting a sub-item-only column deletes it', sub('c_own').includes("deleteColumn(event,'c_own')"));

// ── a member gets nothing ──
const savedAdmin = st.board.my_role;
const G = new Function('st','customColumns','isBoardAdmin','subColumns','openCellPop','esc','formulaIsNumeric','Views',
  RETYPE[0]+';\n'+fnSrc('colTypeOptsHTML')+fnSrc('subColMenu')+'\nreturn {subColMenu};')(
    st, () => cols, () => false, () => subCols, (_a, html) => { opened = html; }, s=>String(s), ()=>false, undefined);
opened=''; G.subColMenu(ev,'c_num',7);
ck('a member who is not a board admin gets no sub-item column menu', opened==='');
st.board.my_role = savedAdmin;

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
