/* The pinned column shows item names, and nothing else, ever.

   With enough columns the board scrolls sideways and the item column stays at
   the start of the viewport — `.tbl td.c-item` is sticky, with a background of
   its own so the cells sliding beneath it do not show through.

   That holds for a row that HAS such a cell. Two rows did not: "+ הוסף פריט"
   and the sub-item panel's wrapper each spanned the whole table in one cell,
   so nothing in them was pinned — the panel began 46px from the table's start,
   inside the pinned column's strip, and slid sideways across it in full view
   behind the item names. Covering the strip would have hidden the start of the
   panel at rest too (and the sub-item NAMES are the first thing in it), so the
   panel starts after the column instead and scrolls under it and out of sight.

   The invariant is the point, not the two rows: every row the board draws
   begins with a cell in the pinned column. Driven by
   tests/test_pinned_column.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const grab = name => {
  const m = new RegExp(`\\n(?:async )?function ${name}\\(([^)]*)\\)\\{[\\s\\S]*?\\n\\}`).exec(src);
  if (!m) throw new Error('not found: ' + name);
  return m[0];
};

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + String(x).slice(0, 240) : ''))); };

// ── the rows the board actually builds ─────────────────────────────────────
const st = {board: {id: 1, groups: [{id: 3, color: '#579bfc'}], my_role: 'admin'},
            openSubs: new Set([7]), selected: new Set()};
const TASK = {id: 7, title: 'שורה', group_id: 3, comment_count: 0,
              subtasks: [{id: 71, title: 'תת-פריט'}]};
const env = {
  st,
  esc: x => String(x == null ? '' : x),
  canEditItem: () => true,
  isBoardAdmin: () => true,
  totalCols: () => 29,
  sortedSubs: s => s || [],
  rowCellsAfterItem: () => '<td class="cell"></td>'.repeat(28),
  subPanelHTML: () => '<div class="sub-panel"><table class="tbl subtbl">PANEL</table></div>',
  findAnyTask: () => TASK,
};
const names = Object.keys(env);
const make = code => new Function(...names, code).apply(null, names.map(n => env[n]));
const itemRow = make(grab('itemRow') + '; return itemRow;');

const html = itemRow(TASK, '#579bfc');

/* Every row, as the markup the browser gets: the tag, and the first cell in it. */
function rows(markup){
  return [...markup.matchAll(/<tr\b[^>]*>\s*(<t[dh]\b[^>]*>)/g)].map(m => ({row: m[0], first: m[1]}));
}
const pinned = first => /class="[^"]*\bc-item\b/.test(first) || /\bdata-fixed\b/.test(first);

{
  const all = rows(html);
  ck('the item row and its sub-item wrapper are both drawn', all.length === 2, all.length + ' rows');
  all.forEach(r => ck('a row the board draws starts in the pinned column',
                      pinned(r.first), r.row));
}
{
  const wrap = /<tr class="sub-wrap"[\s\S]*?<\/tr>/.exec(html)[0];
  ck('the sub-item panel sits AFTER that cell, not inside the strip',
     wrap.indexOf('c-item') < wrap.indexOf('sub-wrap-cell'), wrap);
  ck('...and the row still spans the whole table, as it did',
     /sub-wrap-cell" colspan="29"/.test(wrap), wrap);
  ck('...with the panel itself untouched', wrap.includes('sub-panel'), wrap);
  ck('the pinned cell of that row holds nothing — there is no item here',
     /<td class="c-item sub-pin" aria-hidden="true"><\/td>/.test(wrap), wrap);
}

// ── "+ הוסף פריט" ──────────────────────────────────────────────────────────
/* Rendered inside groupHTML, which pulls in the battery, the headers and the
   group's own wrapper — so this one is read off the template rather than run.
   What matters is the same invariant: the row's first cell is the pinned one,
   and the label is IN it, which is what keeps it on screen while the board is
   scrolled sideways. */
{
  const m = /<tr class="add-row"[^>]*>(<td[^>]*>)([^<]*)<\/td><td colspan="\$\{totalCols\(\)\}"><\/td>/.exec(src);
  ck('"+ הוסף פריט" starts with a cell in the pinned column', !!m && pinned(m[1]),
     m && m[1]);
  ck('...and the label is in that cell, so it stays where the item names are',
     !!m && m[2].includes('הוסף פריט'), m && m[2]);
}

// ── the summary row and the header were already pinned; they stay that way ──
{
  const sum = /<tfoot><tr class="group-sum">\s*(<td[^>]*>)/.exec(src);
  ck('the group total row starts in the pinned column', !!sum && pinned(sum[1]), sum && sum[1]);
  ck('the header cell of that column is pinned on both axes',
     /\.tbl th\[data-fixed\]\{inset-inline-start:calc\(-1 \* var\(--view-pad/.test(src));
}

// ── and the cell that does the pinning is still opaque ─────────────────────
{
  ck('the pinned cell sticks',
     /\.tbl td\.c-item\{position:sticky;inset-inline-start:calc\(-1 \* var\(--view-pad/.test(src));
  /* ...and comes to rest where the board is CUT OFF, not where its content
     box ends. A sticky cell in a scroll container rests against the content
     edge; the container clips at the padding edge. Between the two sat a strip
     as wide as #view's inline padding, outside the pinned column and inside
     the clip, and the columns sliding under it were in plain view there —
     measured in Chrome at a scrolled board: the pinned cell ended at 990, the
     clip at 1016, and the cell behind it ran 979..1129. The rest position is
     pulled out by exactly that padding, so the two edges coincide. */
  const pads = [...src.matchAll(/#view\{(?:[^}]*?)padding:0 var\(--view-pad\)/g)].length;
  const decls = [...src.matchAll(/#view\{[^}]*--view-pad:\s*\d+px/g)].length;
  ck('every padding the view can have is declared as that one value',
     pads === 3 && decls === 3, pads + ' paddings, ' + decls + ' declarations');
  ck('...and the three things pinned to the start edge all read it',
     ['.tbl th[data-fixed]{inset-inline-start:calc(-1 * var(--view-pad',
      '.tbl td.c-item{position:sticky;inset-inline-start:calc(-1 * var(--view-pad',
      '.gh-in{position:sticky;inset-inline-start:calc(-1 * var(--view-pad']
       .every(sel => src.includes(sel)),
     'the group name and the pinned column must rest at the same edge');
  ck('...and paints over what slides beneath it',
     /\.tbl td\.c-item\{background:var\(--surface\)\}/.test(src));
  ck('...in every state the row can be in',
     ['tr:hover td.c-item', 'tr.row-sel td.c-item', 'tr.chat-open td.c-item',
      'tr.sub-wrap td.c-item', '.add-row td.c-item']
       .every(sel => src.includes(sel)),
     'a row state with no background on the pinned cell shows the board through it');
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
