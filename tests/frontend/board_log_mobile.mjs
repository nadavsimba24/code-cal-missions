/* The board log on a phone.

   The log row was laid out for a wide dialog: when · who · item · column · what
   changed · undo, six things side by side wanting some 750px. A phone has half
   that, so every part shrank to its minimum at once — and the two value pills,
   which are the reason anyone opens a log, were capped at 118px and crushed to
   an ellipsis first. You could see that something changed and not what.

   It wraps now, and the wrapping needed something to wrap onto: the field, the
   change and the undo are one element. On a wide screen that element is
   display:contents — not a box at all, its children laid out as direct flex
   items of the row exactly as before, so the desktop layout is unchanged. The
   mobile block turns it into a real box, and it becomes the second line.
   Driven by tests/test_board_log_mobile.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

/* the phone rules, and only those: everything asserted below has to live inside
   the max-width:820px block, or it would change the desktop dialog too */
const mq = /@media \(max-width:820px\)\{[\s\S]*?\n\}/.exec(src);
if(!mq) throw new Error('the mobile media query was not found');
const M = mq[0];
const rule = (re, where) => { const m=re.exec(where); return m?m[0]:null; };

// ── the second line exists, and only on a phone ────────────────────────────
ck('the row has a wrapper around what changed', /<span class="lg-l2">/.test(src));
ck('which is not a box on a wide screen — the desktop row is untouched',
   /\.lg-l2\{display:contents\}/.test(src));
const l2 = rule(/\.lg-l2\{[^}]*\}/, M);
ck('and becomes a real box on a phone', !!l2 && /display:flex/.test(l2), l2);
ck('taking a line of its own', !!l2 && /flex:1 1 100%/.test(l2), l2);
ck('the row is allowed to wrap at all', /\.lg-row\{[^}]*flex-wrap:wrap/.test(M));

// ── the pills get the line ─────────────────────────────────────────────────
const pillDesk = rule(/\.lg-pill\{[^}]*\}/, src);
ck('the 118px cap is still there for the six-column desktop row',
   !!pillDesk && /max-width:118px/.test(pillDesk), pillDesk);
ck('and lifted on a phone, where the pills have a line to themselves',
   /\.lg-pill\{[^}]*max-width:none/.test(M));
ck('the change reads from the start of its line instead of the far end',
   /\.lg-change\{[^}]*justify-content:flex-start/.test(M));
ck('and can shrink rather than force the line wider than the screen',
   /\.lg-change\{[^}]*min-width:0/.test(M));

// ── the title is readable ──────────────────────────────────────────────────
const item = rule(/\.lg-item\{[^}]*\}/, M);
ck('the item title wraps instead of ending in an ellipsis on the first line',
   !!item && /white-space:normal/.test(item), item);
ck('to two lines, not without limit',
   !!item && /-webkit-line-clamp:2/.test(item), item);

// ── the spacer has nothing left to align ───────────────────────────────────
ck('the undo spacer goes — there is no column for it to hold open',
   /\.lg-undo-gap\{display:none\}/.test(M));
ck('and the undo button sits at the end of its own line',
   /\.lg-undo\{margin-inline-start:auto\}/.test(M));

// ── filters and chrome ─────────────────────────────────────────────────────
ck('the four filter controls stack instead of splitting one line',
   /#modal \.log-filters\{[^}]*flex-wrap:wrap/.test(M));
ck('the people menu takes a full line of its own',
   /#modal \.log-filters select\{flex:1 1 100%\}/.test(M));
ck('and the export button stops being pushed to the far edge',
   /#modal \.log-filters \.btn\{margin-inline-start:0/.test(M));
/* 20px of dialog padding and 12px of list padding, doubled for both sides, is a
   sixth of a 390px screen — on the one screen with none to spare */
ck('the dialog body gives its padding back to the content',
   /#modal\.modal-80 \.mbody\{padding:12px\}/.test(M));
ck('and so does the list',
   /#modal \.logs-list\{padding:0\}/.test(M));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
