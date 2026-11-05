/* What a group tells the browser it will come to, before the browser has laid
   it out. Driven by tests/test_group_height_estimate.py.

   Off-screen groups are skipped by content-visibility (see .group in the CSS),
   and a skipped group occupies exactly what its estimate says it does. When
   the estimate is wrong the group grows or shrinks the moment it is scrolled
   towards, and everything after it moves — which is read, correctly, as the
   board jumping under the hand.

   One constant could not be right for every board, and that is why it only
   jumped on some of them:
     · a group whose number column has values in it draws a סה"כ row under the
       rows, on the boards that have a number column and on no others;
     · an open sub-item panel is a nested table with a header and an add-row,
       and it was counted as nothing at all.

   The real functions out of index.html. */
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
const constLine = name => {
  const m = new RegExp(`\\n(const ${name}=[\\s\\S]*?;)\\n`).exec(src);
  if (!m) throw new Error('not found: const ' + name);
  return m[1];
};

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

const st = {board: {id: 1, columns: []}, openSubs: new Set(), collapsedGroups: new Set()};
const env = {
  st,
  customColumns: () => st.board.columns,
  groupCollapsed: gid => st.collapsedGroups.has(gid),
};
const names = Object.keys(env);
const api = new Function(...names,
  constLine('ROW_H_EST') + '\n' + constLine('_est')
  + '\nlet _estNext=null;\n'
  + grab('rowHeightEst') + grab('groupChromeEst') + grab('sumRowEst')
  + grab('subPanelEst') + grab('groupHasSum') + grab('groupEst') + grab('groupSlot')
  + '; return {groupEst,groupSlot,groupHasSum,subPanelEst,ROW_H_EST,GROUP_CHROME_EST,SUM_ROW_EST,GROUP_GAP,SUB_ROW_EST,SUB_CHROME_EST};')
  .apply(null, names.map(n => env[n]));

const rows = n => Array.from({length: n}, (_, i) => ({id: i + 1, custom_fields: {}, subtasks: []}));
const GROUP = {id: 3, tasks: rows(10)};
const plain = api.groupEst(GROUP);

// ── 1. the rows ──
ck('a group is its rows plus its own furniture',
   plain === 10 * api.ROW_H_EST + api.GROUP_CHROME_EST, 'said ' + plain);
ck('...and one more row is one more row of height',
   api.groupEst({id: 3, tasks: rows(11)}) - plain === api.ROW_H_EST);

// ── 2. the סה"כ row, which is what made it a bug on SOME boards ──
st.board.columns = [{id: 'c1', type: 'number'}];
ck('a number column with nothing filled in draws no total, and costs nothing',
   api.groupEst(GROUP) === plain, 'said ' + api.groupEst(GROUP));

const summing = {id: 3, tasks: rows(10)};
summing.tasks[4].custom_fields = {c1: '12'};
ck('...but one filled-in cell draws the total row, and it is counted',
   api.groupEst(summing) === plain + api.SUM_ROW_EST,
   'said ' + api.groupEst(summing) + ', expected ' + (plain + api.SUM_ROW_EST));
ck('...which is the question groupSumRowHTML answers by building one',
   api.groupHasSum(summing) === true && api.groupHasSum(GROUP) === false);

st.board.columns = [{id: 'c1', type: 'text'}];
ck('a text column that happens to hold a number is not a total',
   api.groupEst(summing) === plain, 'said ' + api.groupEst(summing));
st.board.columns = [{id: 'c1', type: 'number'}];
summing.tasks[4].custom_fields = {c1: 'לא מספר'};
ck('...nor is a number column holding something that is not one',
   api.groupEst(summing) === plain, 'said ' + api.groupEst(summing));

// ── 3. the open sub-item panel ──
st.board.columns = [];
const withSubs = {id: 3, tasks: rows(10)};
withSubs.tasks[2].subtasks = rows(4);
ck('a closed sub-item panel is not built, so it takes no room',
   api.groupEst(withSubs) === plain, 'said ' + api.groupEst(withSubs));
st.openSubs.add(withSubs.tasks[2].id);
ck('...and an open one is a nested table of its own, counted as one',
   api.groupEst(withSubs) === plain + 4 * api.SUB_ROW_EST + api.SUB_CHROME_EST,
   'said ' + api.groupEst(withSubs));
st.openSubs.clear();

// ── 4. a folded group, and the gap under an open one ──
st.collapsedGroups.add(3);
ck('a collapsed group is a name and nothing else',
   api.groupEst(GROUP) < 100, 'said ' + api.groupEst(GROUP));
ck('...and carries no gap under it — the CSS turns its margin off',
   api.groupSlot(GROUP) === api.groupEst(GROUP));
st.collapsedGroups.clear();
ck('the room a group takes in the list is the group plus the gap under it',
   api.groupSlot(GROUP) === plain + api.GROUP_GAP, 'said ' + api.groupSlot(GROUP));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
