/* מצבים והודעות — ארבעה מסכים שנראים דומים ואינם, וכישלון שמירה.

   Offering the wrong way out of a state is worse than offering none: it is a
   button that cannot fix what the screen is complaining about. So each state
   gets its own message AND its own action, and the one case that is really
   two cases — "no results" — gets two, because inside a saved view "reset"
   means back to what the view says and outside one it means back to nothing.

   The save failure is pinned hardest. `base` is what "unsaved" is measured
   against, and advancing it on a save that did not happen is the worst bug
   available here: the screen says saved, the next person opens the tab and
   finds the old cut, and the adjustments are gone from the one place they
   still existed.

   Driven by tests/test_view_states.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + String(x).slice(0, 240) : ''))); };

const grab = name => {
  const m = new RegExp(`\\nfunction ${name}\\(`).exec(src);
  if (!m) throw new Error('not found: ' + name);
  let i = src.indexOf('{', m.index), d = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') d++;
    else if (src[j] === '}') { d--; if (!d) return src.slice(m.index + 1, j + 1); }
  }
};

function states(over = {}) {
  const env = Object.assign({
    Views: {active: null, openView: () => null, leave(){}, edit(){}, reset(){}},
    st: {board: {my_role: 'viewer', tasks: []}},
    isBoardAdmin: () => false,
    canEditItem: () => true,
    esc: x => String(x == null ? '' : x),
  }, over);
  const names = Object.keys(env);
  return new Function(...names,
    grab('stateHTML') + grab('clearCutAction') + grab('noMatchHTML') + grab('emptyBoardHTML')
    + grab('restrictedViewHTML') + grab('brokenViewHTML')
    + '; return {noMatchHTML, emptyBoardHTML, restrictedViewHTML, brokenViewHTML};'
  )(...names.map(n => env[n]));
}

// ── no results ─────────────────────────────────────────────────────────────
{
  const out = states().noMatchHTML();
  ck('zero results says it is the filter, not the board', /אין תוצאות לסינון הנוכחי/.test(out), out);
  ck('...and outside a view offers to clear the cut', /clearFilters\(\)/.test(out), out);

  const inView = states({Views: {active: 4, openView: () => ({id: 4}), leave(){}, edit(){}, reset(){}}}).noMatchHTML();
  ck('inside a view the offer is to reset the temporary changes',
     /Views\.reset\(\)/.test(inView) && /איפוס השינויים הזמניים/.test(inView), inView);
  ck('...and NOT to clear everything, which would throw the view away too',
     !/clearFilters\(\)/.test(inView), inView);
}

// ── empty board ────────────────────────────────────────────────────────────
{
  const viewer = states().emptyBoardHTML();
  ck('an empty board says so rather than blaming a filter',
     /אין עדיין פריטים בלוח/.test(viewer) && !/סינון/.test(viewer), viewer);
  ck('...and offers a viewer nothing to press', !/openNewItem/.test(viewer), viewer);

  const editor = states({st: {board: {my_role: 'editor', tasks: []}}}).emptyBoardHTML();
  ck('somebody who may add an item is offered it', /openNewItem\(null,true\)/.test(editor), editor);
}

// ── restricted ─────────────────────────────────────────────────────────────
{
  const out = states().restrictedViewHTML();
  ck('a restricted view says there is no permission', /אין לך הרשאה/.test(out), out);
  ck('...and sends them to the main table', /Views\.leave\(\)/.test(out), out);
  ck('...without naming the column', !/עמודה/.test(out), out);
}

// ── broken ─────────────────────────────────────────────────────────────────
{
  const mine = states().brokenViewHTML({id: 9, can_edit: true});
  ck('a broken view says the settings need fixing', /דורשות תיקון/.test(mine), mine);
  ck('...and offers the fix to whoever may edit it', /Views\.edit\(9\)/.test(mine), mine);
  ck('...and the main table as well', /Views\.leave\(\)/.test(mine), mine);

  const theirs = states().brokenViewHTML({id: 9, can_edit: false});
  ck('somebody who may not edit it is not offered the fix', !/Views\.edit/.test(theirs), theirs);
  ck('...but is still offered the way out', /Views\.leave\(\)/.test(theirs), theirs);
  ck('and the reason it shows nothing is stated, not implied',
     /תוצאות חלקיות/.test(theirs), theirs);
}

// ── a save that failed ─────────────────────────────────────────────────────
{
  const i = src.indexOf('const Views = {');
  const j = src.indexOf('\n};', i);
  const calls = [];
  const V = new Function('esc', 'st', 'api', 'withMe', 'renderTabs', 'toast', 'isMobile',
                         'closeCellPops', 'openCellPop', 'Router', 'Chat',
    'return ' + src.slice(i + 'const Views = '.length, j + 2))(
      x => String(x == null ? '' : x), {board: {id: 1}},
      async () => { throw {detail: 'נפילת רשת'}; },
      b => b, () => calls.push('render'), m => calls.push('toast:' + m), () => false,
      () => {}, () => {}, {set(){}}, {taskId: null});

  V.items = [{id: 1, name: 'x', can_edit: true, filters: {}}];
  V.active = 1;
  V.base = 'WHAT-WAS-OPENED';
  V.current = () => ({q: 'שונה'});

  await V.update();

  ck('a failed save does not claim success',
     !calls.some(c => c.startsWith('toast:') && /נשמר/.test(c)), calls);
  ck('...keeps the adjustments measurable as unsaved',
     V.base === 'WHAT-WAS-OPENED', V.base);
  ck('...says what went wrong', /נפילת רשת/.test(V.failed || ''), V.failed);
  ck('...and is not left looking like it is still saving', V.saving === false);

  const banner = V.failedHTML();
  ck('the failure is a banner, not a toast that disappears',
     /role="alert"/.test(banner), banner);
  ck('...carrying the retry', /Views\.update\(\)/.test(banner) && /ניסיון חוזר/.test(banner), banner);
  ck('...and saying the work is still on screen', /נשמרו במסך/.test(banner), banner);
  ck('a save that has not failed draws no banner', (V.failed = null, V.failedHTML() === ''));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
