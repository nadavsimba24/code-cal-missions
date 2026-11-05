/* The board header is two rows, not three.

   Opening a board used to cost some 170px of chrome before the first item of
   it was on screen: a title line, a line of view tabs with nothing else on it,
   and a separate strip of actions below that. On the page whose whole point is
   the table underneath, that is two rows of nothing.

   The tabs and the actions share one bar now — views at the start, search,
   filter and "פריט חדש" at the far end — and the title line above it is short.
   Nothing was removed; the header is re-seated, and the table starts higher.

   Three things have to stay true or the saving turns into a bug:

   * #toolbar lives inside #boardhead. Anywhere else and it is a strip again.
   * The tabs never shrink — a half-drawn tab strip is unreadable — so the
     toolbar is what gives when the row is crowded, and inside it the search
     box, which has a floor and nothing else to lose.
   * On a phone there is no room for both, so .bh-bar unstacks into the two
     rows it used to be. The view picker there is a full-width field; beside a
     toolbar it would be unusable.

   Driven by tests/test_board_header_one_bar.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };
const rule = re => { const m=re.exec(src); return m?m[0]:null; };

// ── the markup: one bar, inside the header ─────────────────────────────────
const head = /<div id="boardhead">([\s\S]*?)\n    <\/div>/.exec(src);
ck('the board header is still one block', !!head);
const inside = head ? head[1] : '';
ck('and the actions are inside it, not a strip of their own',
   /<div id="toolbar">/.test(inside));
ck('the view tabs and the actions are in the same bar',
   /<div class="bh-bar">\s*<div class="tabs" id="tabs"><\/div>\s*<div id="toolbar">/.test(inside));
ck('the title keeps its own line above the bar',
   /<div class="bh-top">[\s\S]*?<\/div>\s*(<!--[\s\S]*?-->\s*)?<div class="bh-bar">/.test(inside));

/* The order along the bar is the order of the question being asked: which view,
   then how it is cut, then the one thing you came here to do. "פריט חדש" is
   last so it lands at the far end of the row with nothing competing with it. */
const tb = /<div id="toolbar">([\s\S]*?)\n        <\/div>/.exec(src);
const order = ['tb-search','ctl-arrange','tb-clear','openNewItem()']
  .map(k => tb ? tb[1].indexOf(k) : -1);
ck('search, then filter, then the new-item button at the end',
   order.every(i=>i>=0) && order.every((v,i)=>i===0||v>order[i-1]), String(order));

// ── the bar gives in the right order when it is crowded ────────────────────
const bar = rule(/\.bh-bar\{[^}]*\}/);
ck('the bar is a flex row', !!bar && /display:flex/.test(bar), bar);
const tabsInBar = rule(/\.bh-bar>\.tabs\{[^}]*\}/);
ck('the tab strip never shrinks', !!tabsInBar && /flex:0 0 auto/.test(tabsInBar), tabsInBar);
const tbInBar = rule(/\.bh-bar>#toolbar\{[^}]*\}/);
ck('the actions are pushed to the far end of the bar',
   !!tbInBar && /margin-inline-start:auto/.test(tbInBar), tbInBar);
ck('…and they are what gives way when the row runs out of room',
   !!tbInBar && /flex:0 1 auto/.test(tbInBar) && /min-width:0/.test(tbInBar), tbInBar);
const search = rule(/\.tb-search\{[^}]*\}/);
ck('inside them the search box shrinks',
   !!search && /flex:0 1 \d+px/.test(search), search);
ck('…but not past the point of being a search box',
   !!search && /min-width:\d+px/.test(search), search);

// ── the toolbar stopped being a strip ──────────────────────────────────────
const tbRule = rule(/\n#toolbar\{[^}]*\}/);
ck('the toolbar draws no rule of its own any more',
   !!tbRule && !/border-bottom/.test(tbRule), tbRule);
ck('nor a background — it sits on the header’s surface',
   !!tbRule && !/background/.test(tbRule), tbRule);
ck('and the header is what separates the chrome from the table',
   /#boardhead\{[^}]*border-bottom:1px solid var\(--border\)/.test(src));

// ── the height actually came down ──────────────────────────────────────────
/* Whatever the polish block later says is what the user sees, so read the last
   declaration of each rather than the first. */
const last = re => { let m,v=null; const g=new RegExp(re.source,'g'); while((m=g.exec(src)))v=m[1]; return v?+v:null; };
ck('the header pads itself by less than the 18px it used to',
   last(/#boardhead\{padding:(\d+)px/) <= 12, String(last(/#boardhead\{padding:(\d+)px/)));
ck('the title line is a line, not a banner',
   last(/#boardhead \.bh-top\{[^}]*margin-bottom:(\d+)px/) <= 6);
ck('and the board name is sized for a header bar',
   last(/#boardhead h1\{[^}]*font-size:(\d+)px/) <= 19);
ck('the tabs are tighter too',
   last(/\n\.tab\{padding:(\d+)px/) <= 9);

// ── a phone gets the two rows back ─────────────────────────────────────────
const mob = src.slice(src.indexOf('.tab-dd{display:flex'));
ck('on a phone the bar unstacks into the rows it used to be',
   /\.bh-bar\{[^}]*flex-direction:column/.test(mob));
ck('…and the actions span the width rather than hugging an end',
   /\.bh-bar>#toolbar\{[^}]*margin-inline-start:0/.test(mob));
ck('the full-width view picker is still a phone-only control',
   /\.tab-dd\{display:none\}/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
