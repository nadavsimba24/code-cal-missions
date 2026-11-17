/* The board header is sized for a bar, not for a page heading.

   Opening a board cost some 170px of chrome before the first item of it was on
   screen — a title set at 23px like a page heading, 18px of padding above it,
   14px under it, and two strips below padded to match. On a page whose whole
   point is the table underneath, most of that was air.

   The three rows stayed three, by request: the actions read better on a line of
   their own than squeezed against the view tabs, and a strip the eye runs along
   in one direction is worth the row it costs. What came off is the air.

   Four things have to stay true or the saving turns into a bug:

   * the order along the action strip is the order of the work — make an item,
     find one, narrow the board, put it back. RTL reads the first of those at
     the right-hand end, which is where the eye starts;
   * the toolbar is a strip of its own under the tabs, with its own surface and
     its own rule — it is what closes the chrome off from the table;
   * the title line is a line: it holds the board's name, its owner and its
     three buttons side by side and nothing wraps out of it;
   * on a phone the strip scrolls sideways rather than wrapping, because a
     wrapped toolbar is another row of chrome on the screen with least of it.

   Driven by tests/test_board_header_compact.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };
const rule = re => { const m=re.exec(src); return m?m[0]:null; };

// ── the three rows, in order ───────────────────────────────────────────────
const head = /<div id="boardhead">([\s\S]*?)\n    <\/div>/.exec(src);
ck('the board header is one block', !!head);
const inside = head ? head[1] : '';
ck('the title keeps its own line', /<div class="bh-top">/.test(inside));
ck('…and the view tabs come under it',
   inside.indexOf('class="tabs"') > inside.indexOf('class="bh-top"'));
ck('the actions are a strip of their own, not folded into the header',
   !/<div id="toolbar">/.test(inside));
ck('…and that strip comes after the header, under the tabs',
   src.indexOf('<div id="toolbar">') > src.indexOf('<div class="tabs" id="tabs">'));
ck('…and before the board itself',
   src.indexOf('<div id="toolbar">') < src.indexOf('<div id="view">'));

/* The order of the work, read right to left: make an item, find one, narrow the
   board to a few, put it back. "נקה סינון" sits beside the filter it clears. */
const tb = /<div id="toolbar">([\s\S]*?)\n    <\/div>/.exec(src);
const order = ['openNewItem(','tb-search','ctl-arrange','tb-clear']
  .map(k => tb ? tb[1].indexOf(k) : -1);
ck('new item, then search, then filter, then clear-filter',
   order.every(i=>i>=0) && order.every((v,i)=>i===0||v>order[i-1]), String(order));

// ── the toolbar is a strip, and it draws the line under the chrome ─────────
const tbRule = rule(/\n#toolbar\{[^}]*\}/);
ck('the strip has a surface of its own', !!tbRule && /background:var\(--surface\)/.test(tbRule), tbRule);
ck('…and the rule that closes the chrome off from the table',
   !!tbRule && /border-bottom:1px solid var\(--border\)/.test(tbRule), tbRule);
ck('…and it is a single row of controls', !!tbRule && /display:flex/.test(tbRule), tbRule);

// ── the height actually came down ──────────────────────────────────────────
/* Whatever the polish block later says is what the user sees, so read the LAST
   declaration of each rather than the first. */
const last = re => { let m,v=null; const g=new RegExp(re.source,'g'); while((m=g.exec(src)))v=m[1]; return v===null?null:+v; };
const px = (name,re,cap) => ck(name, last(re)!==null && last(re)<=cap,
                               name+' = '+last(re)+'px, cap '+cap);
px('the header pads itself by less than the 18px it used to', /#boardhead\{padding:(\d+)px/, 12);
px('the title line is a line, not a banner', /#boardhead \.bh-top\{[^}]*margin-bottom:(\d+)px/, 6);
px('and the board name is sized for a header bar', /#boardhead h1\{[^}]*font-size:(\d+)px/, 19);
px('the tabs are tighter too', /\n\.tab\{padding:(\d+)px/, 9);
px('and so is the action strip', /\n#toolbar\{[^}]*padding:(\d+)px/, 9);

/* The title line holds the name, the owner chip and the three buttons side by
   side. It is given a floor so that a board with no owner — nothing but a short
   name on it — does not draw a shorter header than the board beside it. */
const top = rule(/#boardhead \.bh-top\{[^}]*\}/);
ck('the title row lays its parts out in a line',
   !!top && /display:flex/.test(top) && /align-items:center/.test(top), top);
ck('…and keeps one height whatever is on it',
   !!top && /min-height:\d+px/.test(top), top);

// ── a phone ────────────────────────────────────────────────────────────────
const mob = src.slice(src.indexOf('.tab-dd{display:flex'));
ck('on a phone the strip scrolls sideways rather than wrapping',
   /#toolbar\{[^}]*overflow-x:auto/.test(mob) && /#toolbar\{[^}]*flex-wrap:nowrap/.test(mob));
ck('…with nothing in it squeezed to fit', /#toolbar>\*\{flex-shrink:0\}/.test(mob));
ck('the full-width view picker is still a phone-only control',
   /\.tab-dd\{display:none\}/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
