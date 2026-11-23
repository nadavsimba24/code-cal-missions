/* A sub-item column has a width of its own, and only a board admin drags it.
   Driven by tests/test_a_board_admin_resizes_sub_item_columns.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const fnSrc = name => {
  const i = src.indexOf('function '+name+'(');
  if (i < 0) throw new Error('not found: '+name);
  const j = src.indexOf('\n}\n', i);
  return src.slice(i, j+2);
};

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// the page's own functions, over a stand-in board
const make = (board, admin) => new Function('st','colWidthMap','isBoardAdmin','esc',
  fnSrc('subColWidth')+fnSrc('subColgroupHTML')+fnSrc('subResizerHTML')
  +'\nreturn {subColWidth, subColgroupHTML, subResizerHTML};')(
    {board}, () => ({item: 330, status: 180}), () => admin,
    s => String(s).replace(/[&<>"']/g, c => '&#'+c.charCodeAt(0)+';'));

const item = {id:'item', kind:'builtin'}, status = {id:'status', kind:'builtin'}, c7 = {id:'c7', kind:'custom'};

// ── nothing resized yet: exactly what it was before ──
let f = make({}, true);
ck('an unresized sub-item name stays 260px, whatever the item column is', f.subColWidth(item)===260);
ck('an unresized sub-item column takes the item table\'s width for it', f.subColWidth(status)===180);
ck('a column with no width anywhere is 140px', f.subColWidth(c7)===140);

// ── resized on the sub-table: its own width, the item table untouched ──
f = make({sub_col_widths:{item:410, status:95}}, true);
ck('the sub-item name takes its own saved width', f.subColWidth(item)===410);
ck('a sub-item column takes its own saved width over the item table\'s', f.subColWidth(status)===95);
ck('a column not resized on the sub-table still falls back', f.subColWidth(c7)===140);
const cg = f.subColgroupHTML([item,status,c7], true);
ck('every sub <col> names its column, so a drag can find it',
   /data-subkey="item" style="width:410px"/.test(cg) && /data-subkey="status" style="width:95px"/.test(cg), cg);

// ── the handle ──
ck('a board admin gets the handle', /class="sub-col-resizer" data-subkey="status"/.test(f.subResizerHTML('status')));
ck('a member does not', make({}, false).subResizerHTML('status')==='');
ck('the handle is not a .col-resizer — the item table\'s binder would grab it and resize the ITEM column',
   !/col-resizer"/.test(f.subResizerHTML('status').replace('sub-col-resizer','')));
ck('a column id is escaped into the attribute', !/<x>/.test(f.subResizerHTML('<x>')));

// ── the header draws it, the page listens for it, the drop saves it ──
const head = fnSrc('subHeadHTML');
ck('the sub-item name header carries a handle', /\$\{subResizerHTML\('item'\)\}<\/th>/.test(head));
ck('every other sub-item header carries one', /\$\{subResizerHTML\(c\.id\)\}<\/th>/.test(head));
ck('one delegated listener is installed at start-up', /\n  initSubColResizers\(\);/.test(src));
const init = fnSrc('initSubColResizers');
ck('the drop saves sub_col_widths, not col_widths',
   /body:withMe\(\{sub_col_widths:/.test(init) && !/col_widths:st\.board\.col_widths/.test(init));
ck('the drag is clamped to 60..600, like the server', /Math\.max\(60,Math\.min\(600,/.test(init));
ck('the handle is anchored to its header cell', /\.subtbl thead th\{position:relative\}/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
