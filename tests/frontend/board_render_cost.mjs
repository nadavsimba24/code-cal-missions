/* What drawing a board actually builds.
   Driven by tests/test_board_render_cost.py.

   Two things were paid for on every row of every board and nobody could see
   either of them:

   1. The sub-item panel — a whole table with a colgroup and a header cell per
      column — was built and then hidden with display:none, for every row,
      including rows with no sub-items at all. On a 687-item board with 29
      columns that is tens of thousands of invisible elements.
   2. The column model was derived from the board's settings again for every
      row that asked for it, three times a row.

   Both run the real functions out of index.html. */
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
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

// ── 1. the sub-item panel is not built until it is opened ──
const st = {board: {id: 1, groups: [{id: 3, color: '#579bfc'}], my_role: 'admin'},
            openSubs: new Set(), selected: new Set()};
const TASK = {id: 7, title: 'שורה', group_id: 3, comment_count: 0, subtasks: []};
const env = {
  st,
  esc: x => String(x == null ? '' : x),
  canEditItem: () => true,
  isBoardAdmin: () => true,
  totalCols: () => 29,
  sortedSubs: s => s || [],
  rowCellsAfterItem: () => '<td class="cell"></td>'.repeat(28),
  subPanelHTML: () => '<<<PANEL>>>',
  findAnyTask: () => TASK,
};
const names = Object.keys(env);
const make = code => new Function(...names, code).apply(null, names.map(n => env[n]));
// the row's conversation badge is its own function now (it reads the board's
// grey-after-how-many-days threshold), so it comes along — a stub here would
// be this harness drawing a cell the board does not
const itemRow = make(grab('chatStaleDays') + grab('chatIdleDays')
                     + grab('chatBtnHTML') + grab('itemRow') + '; return itemRow;');

let html = itemRow(TASK, '#579bfc');
ck('a closed row still carries its wrap, so lookups by data-parent keep working',
   /class="sub-wrap" data-parent="7"/.test(html), html.slice(-300));
ck('...and the wrap is hidden', /class="sub-wrap"[^>]*display:none/.test(html));
ck('...but the panel inside it was never built',
   !html.includes('<<<PANEL>>>'),
   'a table with a header cell per column, per row, that nobody can see');
ck('...and the row itself is complete', html.includes('שורה') && /data-tid="7"/.test(html));

st.openSubs.add(7);
html = itemRow(TASK, '#579bfc');
ck('a row that IS open renders its panel eagerly', html.includes('<<<PANEL>>>'), html.slice(-200));
ck('...and shows it', /class="sub-wrap"[^>]*display:table-row/.test(html));

// an item with sub-items, closed: still nothing built
st.openSubs.clear();
TASK.subtasks = [{id: 8}, {id: 9}];
html = itemRow(TASK, '#579bfc');
ck('an item WITH sub-items, closed, also builds nothing', !html.includes('<<<PANEL>>>'));
ck('...while still showing the badge that says how many there are',
   /class="sub-badge[^"]*"[\s\S]*?2</.test(html), html);

// ── 2. the column model is derived once per render, not once per row ──
let derived = 0;
const env2 = {
  st,
  isBoardAdmin: () => true,
  _orderedColumns: () => { derived++; return [{id: 'item'}, {id: 'c1'}, {id: 'c2'}]; },
  _subColumns: () => ({}),
  _colWidthMap: () => ({}),
};
const names2 = Object.keys(env2);
// the three wrappers are one-liners, so they are pulled by their exact text
// rather than by the brace-matching grab above
const line = re => { const m = re.exec(src); if (!m) throw new Error('not found: ' + re); return m[0]; };
const body = grab('_memoCols')
           + line(/function orderedColumns\(\)\{[^\n]*\}/)
           + line(/function totalCols\(\)\{[^\n]*\}/)
           + '\nreturn {orderedColumns, totalCols, open:()=>{_colsMemo={};}, close:()=>{_colsMemo=null;}};';
const api = new Function(...names2, 'let _colsMemo=null;\n' + body)
              .apply(null, names2.map(n => env2[n]));

derived = 0;
api.close();
api.orderedColumns(); api.orderedColumns(); api.orderedColumns();
ck('outside a render every caller computes for itself, exactly as before',
   derived === 3, 'derived ' + derived + ' times');

derived = 0;
api.open();
for (let i = 0; i < 700; i++) { api.orderedColumns(); api.totalCols(); }
api.close();
ck('inside one render, seven hundred rows derive the column model once',
   derived === 1, 'derived ' + derived + ' times for 700 rows');

derived = 0;
api.open(); api.orderedColumns(); api.close();
api.open(); api.orderedColumns(); api.close();
ck('...and the next render derives it again — a changed column is not stale',
   derived === 2, 'derived ' + derived + ' times across two renders');

// ── 3. the board she is looking at is drawn before the rest of it ──
// A board is three to seven groups; only the first is on screen when it opens.
const GROUPS=[{id:1,tasks:new Array(100).fill(0)},
              {id:2,tasks:new Array(223).fill(0)},
              {id:3,tasks:new Array(223).fill(0)}];
let wired=0, deferred=null;
const env3={
  st:{board:{tasks:new Array(546).fill(0)}},
  groupsOf:()=>GROUPS,
  noMatchHTML:()=>'NOMATCH',
  // a search still running on the server is not "no results" — see vTable.
  // This board is not waiting for one.
  searchPending:()=>false,
  searchingHTML:()=>'SEARCHING',
  Paged:{on:false},
  groupHTML:g=>`<div class="group" data-g="${g.id}"></div>`,
  // the slot a group takes in the list: the group itself plus the gap under
  // it. vTable asks for the slot and not the bare height on purpose — a
  // spacer standing in for a dozen groups stands in for their gaps too.
  groupSlot:g=>g.tasks.length*47+160+16,
  addGroupBtnHTML:()=>'<button class="add-group-btn"></button>',
  wireTable:()=>{ wired++; },
  fitLinkChips:()=>{},
  Chat:{markOpenRow:()=>{}},
  requestAnimationFrame:fn=>{ deferred=fn; },
  setTimeout:fn=>{ deferred=fn; },
};
const names3=Object.keys(env3);
const vTable=new Function(...names3,'let _colsMemo=null, _vtToken=0;\n'+grab('vTable')+'; return vTable;')
               .apply(null,names3.map(n=>env3[n]));

let painted='';
const view={ set innerHTML(v){ painted=v; }, get innerHTML(){ return painted; },
             querySelector:sel=>sel==='.grp-reserve'?null:null };
vTable(view);
const drawn=(painted.match(/data-g="(\d+)"/g)||[]).map(x=>x.replace(/\D/g,''));
ck('the first frame draws the group on screen and no other',
   drawn.length===1 && drawn[0]==='1', 'drew groups: '+drawn.join(','));
ck('...and the rest is queued, not dropped', typeof deferred==='function');
const res=/class="grp-reserve" style="height:(\d+)px"/.exec(painted);
ck('...with a spacer holding exactly the height they will need',
   !!res && +res[1]===(223*47+160+16)*2,
   res?('reserved '+res[1]+'px, expected '+((223*47+160+16)*2)):painted);
ck('...so the scrollbar is the right length from the first frame, not growing later',
   !!res);
ck('the wiring ran for what was drawn', wired===1, 'wired '+wired+' times');

// a board of one group has nothing to defer and no spacer to leave behind
const ONE=[{id:9,tasks:new Array(12).fill(0)}];
env3.groupsOf=()=>ONE;
const vTable1=new Function(...names3,'let _colsMemo=null, _vtToken=0;\n'+grab('vTable')+'; return vTable;')
                .apply(null,names3.map(n=>env3[n]));
deferred=null; painted='';
vTable1(view);
ck('a single-group board defers nothing', deferred===null, 'something was queued');
ck('...and leaves no spacer behind', !painted.includes('grp-reserve'), painted);
ck('...and still offers "add group"', painted.includes('add-group-btn'));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
