/* הרצועה: מה כל לשונית אומרת על עצמה, ומה התפריט שלה מציע.

   A tab is how somebody chooses which cut to open, so what it says before it
   is opened is the whole of its job. Three things are pinned here.

   The ICONS are not decoration. A locked view and a pinned one behave
   differently from the tab beside them — one cannot be saved over, the other
   sits first for everyone — and each carries a real label rather than a title
   attribute, which a screen reader on a touch device never sees.

   The MENU is built from the server's own flags and nothing else. Deriving
   what somebody may do from their role here would be a second copy of the
   permission matrix, and the two would disagree the first time either moved.
   An action nobody may perform is not drawn greyed out; it is not drawn, and
   a view with no actions gets no menu button rather than one that opens
   nothing.

   Driven by tests/test_view_strip.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + String(x).slice(0, 220) : ''))); };

/* The real Views object, lifted out of the page. A stub would prove only that
   this file agrees with itself. */
const i = src.indexOf('const Views = {');
const j = src.indexOf('\n};', i);
const Views = new Function('esc', 'st', 'isMobile', 'toast', 'closeCellPops', 'openCellPop',
  'return ' + src.slice(i + 'const Views = '.length, j + 2))(
    x => String(x == null ? '' : x), {board: {id: 1}}, () => false, () => {}, () => {}, () => {});

const V = (over = {}) => Object.assign({
  id: 7, name: 'דחופים', locked: false, pinned: false, blocked: false, needs_fix: [],
  can_edit: true, can_lock: false, can_duplicate: true,
}, over);

// ── the icons, and their labels ────────────────────────────────────────────
{
  ck('a plain view carries no icon at all', Views.tabIcons(V()) === '', Views.tabIcons(V()));

  const locked = Views.tabIcons(V({locked: true}));
  ck('a locked view is marked', /fa-lock/.test(locked), locked);
  ck('...with a label, not a title', /aria-label="תצוגה נעולה"/.test(locked), locked);

  const pinned = Views.tabIcons(V({pinned: true}));
  ck('a pinned view is marked', /fa-thumbtack/.test(pinned), pinned);
  ck('...with a label of its own', /aria-label="תצוגה מוצמדת"/.test(pinned), pinned);

  const both = Views.tabIcons(V({locked: true, pinned: true}));
  ck('and both at once say both', /fa-lock/.test(both) && /fa-thumbtack/.test(both), both);

  const blocked = Views.tabIcons(V({blocked: true}));
  ck('a view this reader cannot open says so', /aria-label="התצוגה אינה זמינה לך"/.test(blocked), blocked);
  ck('...and does not name a column', !/עמודה/.test(blocked), blocked);

  const broken = Views.tabIcons(V({needs_fix: ['col_x']}));
  ck('a view needing a fix says so', /aria-label="התצוגה דורשת תיקון"/.test(broken), broken);
  ck('...and a blocked view says only that it is blocked',
     !/דורשת תיקון/.test(Views.tabIcons(V({blocked: true, needs_fix: ['col_x']}))),
     'the block is about this reader; the fix is about the board');
}

// ── the menu offers exactly what the server allows ─────────────────────────
const keys = v => Views.actionsFor(v).map(a => a[0]);
{
  ck('a viewer is offered nothing', keys(V({can_edit: false, can_lock: false, can_duplicate: false})).length === 0);

  const ed = keys(V({can_edit: true, can_lock: false, can_duplicate: true}));
  ck('an editor renames, duplicates and deletes',
     ed.includes('rename') && ed.includes('duplicate') && ed.includes('delete'), ed);
  ck('...and is not offered the lock', !ed.includes('lock') && !ed.includes('unlock'), ed);
  ck('...nor the pin', !ed.includes('pin') && !ed.includes('unpin'), ed);

  const owner = keys(V({can_edit: true, can_lock: true, can_duplicate: true}));
  ck('the board owner is offered the lock and the pin',
     owner.includes('lock') && owner.includes('pin'), owner);

  ck('a locked view offers unlocking rather than locking',
     keys(V({locked: true, can_lock: true})).includes('unlock'), keys(V({locked: true, can_lock: true})));
  ck('a pinned view offers unpinning',
     keys(V({pinned: true, can_lock: true})).includes('unpin'), keys(V({pinned: true, can_lock: true})));

  /* Somebody who may copy a view they cannot edit — a locked one — is still
     offered the copy, because that is the route the spec gives them. */
  const reader = keys(V({can_edit: false, can_lock: false, can_duplicate: true}));
  ck('a locked view can still be copied by whoever may create one',
     reader.length === 1 && reader[0] === 'duplicate', reader);
}

// ── and the tab draws no menu button when there is no menu ─────────────────
{
  const none = Views.tabsHTML.call(
    {items: [V({can_edit: false, can_lock: false, can_duplicate: false})], active: null,
     dirty: () => false, tabIcons: Views.tabIcons, actionsFor: Views.actionsFor});
  ck('a view with no actions gets no menu button', !/tab-view-menu/.test(none), none);

  const some = Views.tabsHTML.call(
    {items: [V()], active: 7, dirty: () => true, tabIcons: Views.tabIcons,
     actionsFor: Views.actionsFor});
  ck('a view with actions gets one', /tab-view-menu/.test(some));
  ck('...labelled with the view it belongs to',
     /aria-label="פעולות לתצוגה דחופים"/.test(some), some);
  ck('the open tab is marked for assistive tech too', /aria-current="page"/.test(some), some);
  ck('and unsaved temporary changes are announced, not only dotted',
     /aria-label="יש שינויים זמניים שלא נשמרו"/.test(some), some);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
