/* ה"+" מוסיף תצוגת טבלה, וחלונית היצירה אומרת מה לא בסדר ליד השדה.

   The "+" used to toggle the board's view TYPES — table, kanban, map — and
   with the other six held back by VIEWS_WIP that list was one disabled row.
   The button opened a menu with nothing in it anybody could press. What this
   version actually adds is a saved TABLE view, and since that is the only
   kind there is, there is no type to pick first.

   Two rules about what a new view is made OF, and they pull in opposite
   directions on purpose:

     "+"                  starts from the MAIN table's stored configuration.
                          Somebody who adjusted the board and then pressed +
                          was not asking to freeze those adjustments.
     "שמור כתצוגה חדשה"   starts from what is on screen, adjustments included.
                          That is the button that means it.

   And neither carries the search text, ever.

   Driven by tests/test_view_create.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + String(x).slice(0, 240) : ''))); };

function views(over = {}) {
  const calls = [];
  const env = Object.assign({
    esc: x => String(x == null ? '' : x),
    st: {board: {id: 1, my_role: 'editor'}, filters: {q: 'חיפוש זמני', sort: 'due'}, view: 'table'},
    showModal: h => calls.push(['modal', h]),
    closeModals: () => calls.push(['close']),
    toast: m => calls.push(['toast', m]),
    api: async () => ({id: 9, name: 'חדשה'}),
    withMe: b => b, renderTabs: () => {}, isMobile: () => false,
    closeCellPops: () => {}, openCellPop: () => {}, setTimeout: () => {},
    document: {getElementById: () => null, querySelector: () => null},
    Router: {set(){}}, Chat: {taskId: null},
  }, over);
  const names = Object.keys(env);
  const i = src.indexOf('const Views = {');
  const j = src.indexOf('\n};', i);
  const V = new Function(...names, 'return ' + src.slice(i + 'const Views = '.length, j + 2))
              (...names.map(n => env[n]));
  V.calls = calls;
  return V;
}

// ── what a new view is made of ─────────────────────────────────────────────
{
  const V = views();
  V.items = [{id: 1, kind: 'main', name: 'טבלה ראשית',
              filters: {view: 'table', sort: 'title', cols: {widths: {item: 300}}, q: 'ישן'}}];
  V.createTable();

  ck('the + opens the creation dialog', V.calls.some(c => c[0] === 'modal'), V.calls);
  const made = V._pending;
  ck('a new view starts from the MAIN table, not from the screen',
     made.sort === 'title', made);
  ck('...carrying its stored column layout', made.cols.widths.item === 300, made);
  ck('...and never a search, not even the main table’s own',
     !('q' in made), made);
  ck('the dialog says where the settings came from',
     /מהגדרות הטבלה הראשית/.test(V.calls.find(c => c[0] === 'modal')[1]));
}
{
  /* The other direction: save-as-new is explicitly the screen, adjustments
     and all — that is what distinguishes it from the + beside it. */
  const V = views();
  V.items = [];
  V._dialog(null, {});
  ck('save as new has no prepared cut, so it uses what is on screen',
     V._pending === null);
}

// ── the dialog ─────────────────────────────────────────────────────────────
{
  const V = views();
  V._dialog(null, {});
  const html = V.calls.find(c => c[0] === 'modal')[1];
  ck('there is no "who sees it" choice left', !/vw-vis/.test(html), html);
  ck('...because every view is shared and the question has one answer',
     !/אישית/.test(html) && !/ציבורית/.test(html), html);
  ck('the error has a place beside the field', /id="vw-err"/.test(html), html);
  ck('...and the field points at it for a screen reader',
     /aria-describedby="vw-err"/.test(html), html);
  ck('the error is announced when it appears', /role="alert"/.test(html), html);
  ck('cancel is offered beside save', /closeModals\(\)/.test(html) && /ביטול/.test(html));
}

// ── a refused save says so where the typing is ─────────────────────────────
{
  const shown = [];
  const V = views({
    api: async () => { throw {detail: 'כבר יש תצוגה בשם הזה בלוח'}; },
    document: {getElementById: id => id === 'vw-name' ? {value: 'דחופים'} : null,
               querySelector: () => null},
  });
  V._err = m => shown.push(m);
  V._pending = {view: 'table'};
  await V.save(null);

  ck('a duplicate name is reported beside the field, not in a toast',
     shown.length === 1 && /כבר יש תצוגה בשם/.test(shown[0]), shown);
  ck('...and the dialog is not closed over it',
     !V.calls.some(c => c[0] === 'close'), V.calls);
  ck('...and nothing claims a view was created',
     !V.calls.some(c => c[0] === 'toast' && /נוצרה/.test(c[1])), V.calls);
}
{
  const shown = [];
  const V = views({document: {getElementById: id => id === 'vw-name' ? {value: '   '} : null,
                              querySelector: () => null}});
  V._err = m => shown.push(m);
  await V.save(null);
  ck('an empty name never reaches the server', /צריך שם/.test(shown[0] || ''), shown);
}

// ── renaming sends the name and nothing else ───────────────────────────────
{
  let sent = null;
  const V = views({
    api: async (_u, o) => { sent = o.body; return {id: 3, name: 'אחרי'}; },
    document: {getElementById: id => id === 'vw-name' ? {value: 'אחרי'} : null,
               querySelector: () => null},
  });
  V.items = [{id: 3, name: 'לפני', filters: {}}];
  await V.save(3);
  ck('a rename sends the name', sent && sent.name === 'אחרי', sent);
  ck('...and NOT the cut on screen — "fix a typo" is not "save my adjustments '
     + 'for everybody"', sent && !('filters' in sent), sent);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
