/* The pinned column shows item names, and nothing else, ever.

   With enough columns the board scrolls sideways and the item column stays at
   the start of the viewport — `.tbl td.c-item` is sticky, with a background of
   its own so the cells sliding beneath it do not show through.

   "+ הוסף פריט" spanned the whole table in one cell and now has a cell in that
   column, so the label stays where the item names are. It is a label and
   nothing else, so pinning it moved nothing.

   The sub-item wrapper was given one too and has had it taken back out. A
   row's content begins after the cell before it, so a pinned cell as wide as
   the פריט column pushed the whole panel out by that column's width — 280px by
   default — and the sub-items sat a third of the way across the board. The
   light 46px indent was asked for back.

   Both cannot be had: 46px is INSIDE the pinned column's 280px, so the panel
   either begins there and shows in that strip on a sideways scroll, or begins
   after the column and is pushed out by it. What shows in the strip is this
   panel in its own band of rows — never an item's name, because every item row
   carries its own opaque pinned cell.

   Driven by tests/test_pinned_column.py. */
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
  ck('the item row itself starts in the pinned column', pinned(all[0].first), all[0].row);
}
{
  const wrap = /<tr class="sub-wrap"[\s\S]*?<\/tr>/.exec(html)[0];
  /* The one that is deliberately NOT pinned. A cell in that column here is as
     wide as the פריט column and pushes the panel out by its whole width — the
     280px of indent this row was changed back to get rid of. Pinned again by
     someone reading only the rule above, the indent comes straight back. */
  ck('the sub-item wrapper spans the table in one cell, as it always did',
     !/c-item/.test(wrap) && /sub-wrap-cell" colspan="30"/.test(wrap), wrap);
  ck('...so the panel keeps its light indent and is not pushed out by a column',
     wrap.includes('sub-panel'), wrap);
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
      '.add-row td.c-item']
       .every(sel => src.includes(sel)),
     'a row state with no background on the pinned cell shows the board through it');
}

// ── and nothing that scrolls under it paints over it ───────────────────────
/* Opacity is only half of it. The pinned cell is a sticky element with a
   z-index, so what slides beneath it must have a LOWER one — a tie is broken
   by document order, and everything in a row comes after the pinned cell.

   The sub-item panel's accent bar was declared level with it, at 2, and
   therefore slid across the item names on a sideways scroll: an opaque cell
   does not help when the thing is painted on top of it.

   Read as numbers rather than matched as text, so the case still means this
   when either value is changed. */
{
  const zOf = sel => {
    const re = new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{[^}]*?z-index:(\\d+)');
    const m = re.exec(src);
    return m ? +m[1] : null;
  };
  const pin = zOf('.tbl td.c-item');
  const bar = zOf('.sub-panel::before');
  ck('the pinned column declares a z-index at all', pin !== null, pin);
  ck('the sub-item panel\'s accent bar passes UNDER it, not over',
     bar !== null && pin !== null && bar < pin, 'bar '+bar+' vs column '+pin);
  /* The header cells are the one thing allowed above: they are the pinned
     column's own row, and the corner cell above them again. */
  ck('...while the sticky header still sits above the rows it heads',
     zOf('.tbl th') > pin && zOf('.tbl th[data-fixed]') > zOf('.tbl th'),
     zOf('.tbl th') + ' / ' + zOf('.tbl th[data-fixed]'));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
