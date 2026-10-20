/* Only "טבלה ראשית" is offered while the other views are still being built.

   TEMPORARY, and the point of the shape is that undoing it is deleting lines.
   The filter sits where the screen OFFERS a view and nowhere else: a board that
   has קנבן turned on still has it turned on in the database, so taking an id
   out of VIEWS_WIP brings that view back exactly as each board had it. The one
   place this could have gone wrong is toggleBoardView, which writes the setting
   back — starting it from the filtered list would have quietly deleted every
   hidden view from the board the first time anybody toggled anything.
   Driven by tests/test_views_in_progress_are_hidden.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const grab = name => {
  const m = new RegExp(`\\n(?:async )?function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`).exec(src);
  if (!m) throw new Error('not found: ' + name);
  return m[0];
};
const wipLine = /const VIEWS_WIP=new Set\(\[([^\]]*)\]\)/.exec(src);

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

ck('the work-in-progress list exists', !!wipLine);
const WIP = new Set((wipLine ? wipLine[1] : '').split(',').map(s => s.trim().replace(/^'|'$/g, '')).filter(Boolean));
ck('...and "table" is NOT in it — the one view that stays', !WIP.has('table'), [...WIP].join(','));

// a board with everything turned on, which is what the real ones look like
const ALL = ['table', 'kanban', 'dashboard', 'calendar', 'map', 'gis', 'links'];
const VIEW_META = Object.fromEntries(ALL.map(id => [id, {id, he: id, ic: 'x'}]));
const st = {board: {id: 1, views: ALL.slice()}, view: 'table'};
const env = {st, VIEW_META, VIEWS_WIP: WIP};
const names = Object.keys(env);
const make = code => new Function(...names, code).apply(null, names.map(n => env[n]));
const boardViewsRaw = make(grab('boardViewsRaw') + '; return boardViewsRaw;');
const boardViews = make(grab('boardViewsRaw') + grab('boardViews') + '; return boardViews;');

ck('only the main table is offered', JSON.stringify(boardViews()) === JSON.stringify(['table']),
   boardViews().join(','));
ck('...while the board keeps every view it had turned on',
   boardViewsRaw().length === ALL.length, boardViewsRaw().join(','));

// ── the three places that must agree ──────────────────────────────────────
ck('the tab strip is built from the filtered list',
   /const enabled=boardViews\(\)/.test(grab('renderTabs')));
ck('...and lands on the table when the view it held is hidden',
   /if\(!enabled\.includes\(st\.view\)\)st\.view='table'/.test(grab('renderTabs')));
/* The popover's list grew a second exclusion — the main table, which is not
   something to switch on and off — so this asks for the WIP filter being
   APPLIED rather than for one exact expression. Pinning the spelling meant a
   case that failed the first time the line was edited for an unrelated
   reason, which is noise rather than protection. */
ck('the "+" popover does not offer a view that would have no tab',
   /VIEWS\.filter\(v=>[^)]*!VIEWS_WIP\.has\(v\.id\)/.test(grab('renderAddViewPop')),
   'an admin could turn on a view and see nothing appear');
ck('...and the "+" offers the one thing this version can add',
   /Views\.createTable\(\)/.test(grab('renderAddViewPop')),
   'the + opened a menu with nothing in it anybody could press');
ck('the mobile picker is built from the same filtered list',
   /boardViews\(\)\.map/.test(grab('openViewPicker')));

// ── and the setting itself is never rewritten from the filtered list ──────
const toggle = grab('toggleBoardView');
ck('toggling a view starts from the board\'s own setting, not the filtered one',
   /boardViewsRaw\(\)\.slice\(\)/.test(toggle),
   'hiding a view would delete it from the board on the next toggle');
ck('...so nothing in the write path reads the filtered list',
   !/=boardViews\(\)\.slice\(\)/.test(toggle));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
