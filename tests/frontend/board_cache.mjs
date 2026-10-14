/* Going back to a board she just left.
   Driven by tests/test_board_cache.py.

   Switching boards rebuilt everything from nothing every time — a request, all
   the items, every cell — even returning to a board she had left ten seconds
   earlier. A working day is mostly switching between the same two or three
   boards, so most of that work was being redone for an answer that had not
   changed.

   What is pinned here is the part that can be got wrong quietly: that the
   cache holds a bounded number of boards and evicts the one she has not
   looked at longest, and that the stamp which decides "nothing changed, do
   not redraw" actually notices every kind of change. A stamp that misses a
   change means she sits looking at a board that is out of date, which is far
   worse than a slow one. */
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
const line = re => { const m = re.exec(src); if (!m) throw new Error('not found: ' + re); return m[0]; };

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

const api = new Function(
  line(/const BOARD_CACHE_MAX=\d+;/) + '\nconst _boardCache=new Map();\n'
  + grab('cacheBoard') + grab('dropCachedBoard') + grab('boardStamp')
  + '\nreturn {cacheBoard, dropCachedBoard, boardStamp, cache:_boardCache, MAX:BOARD_CACHE_MAX};')();

// ── what it remembers ──
const b = id => ({id, name: 'לוח ' + id, my_role: 'admin', tasks: [], groups: [], columns: []});
for (let i = 1; i <= api.MAX + 3; i++) api.cacheBoard(b(i));
ck('it remembers a bounded number of boards, not every board she ever opened',
   api.cache.size === api.MAX, 'holds ' + api.cache.size);
ck('...and the ones it dropped are the ones she looked at longest ago',
   !api.cache.has(1) && !api.cache.has(2) && !api.cache.has(3) && api.cache.has(api.MAX + 3),
   [...api.cache.keys()].join(','));

api.cacheBoard(b(4));                        // revisited
api.cacheBoard(b(99));
ck('a board she returns to is treated as recent, not as old',
   api.cache.has(4), 'a revisit did not refresh its place in the queue');

api.dropCachedBoard(4);
ck('a board can be forgotten outright — a deleted one must not come back',
   !api.cache.has(4));
api.cacheBoard(b(4));
ck('...and caching it again works afterwards', api.cache.has(4));
ck('nothing is remembered for a board with no id', (()=>{
  const before = api.cache.size; api.cacheBoard({name: 'x'}); api.cacheBoard(null);
  return api.cache.size === before;
})());

// ── what it notices ──
const base = {id: 5, name: 'לוח', my_role: 'admin',
              groups: [{id: 1}, {id: 2}], columns: [{id: 'a'}, {id: 'b'}],
              tasks: [{id: 1, updated_at: '2026-10-14T09:00:00', subtasks: []},
                      {id: 2, updated_at: '2026-10-14T08:00:00', subtasks: [
                        {id: 3, updated_at: '2026-10-14T07:00:00'}]}]};
const clone = () => JSON.parse(JSON.stringify(base));
const stamp = api.boardStamp;

ck('the same board twice is the same stamp — so nothing is redrawn for nothing',
   stamp(base) === stamp(clone()));

const checks = [
  ['an item was edited',        x => { x.tasks[0].updated_at = '2026-10-14T10:00:00'; }],
  ['a SUB-item was edited',     x => { x.tasks[1].subtasks[0].updated_at = '2026-10-14T10:00:00'; }],
  ['an item was added',         x => { x.tasks.push({id: 9, updated_at: '', subtasks: []}); }],
  ['an item was removed',       x => { x.tasks.pop(); }],
  ['a sub-item was added',      x => { x.tasks[0].subtasks.push({id: 8, updated_at: ''}); }],
  ['a group was added',         x => { x.groups.push({id: 3}); }],
  ['a column was added',        x => { x.columns.push({id: 'c'}); }],
  ['the board was renamed',     x => { x.name = 'אחר'; }],
  ['her role on it changed',    x => { x.my_role = 'viewer'; }],
];
for (const [what, mutate] of checks) {
  const x = clone(); mutate(x);
  ck('it notices that ' + what, stamp(x) !== stamp(base),
     'the board would stay on screen out of date');
}

// ── the shape of the open path ──
ck('a board she has seen is painted BEFORE the server is consulted',
   /st\.board=seen;\s*\n\s*paintBoard\(id\);[\s\S]{0,200}revalidateBoard\(id/.test(src),
   'the cached path must not wait on the network');
// On HTTP/1.1 — which is what prod serves — a request fired alongside the
// board's own competes with it for one of six connections, and the leftover
// from the last switch is still holding one during the next.
ck('nothing is requested until the board is on screen: not the recheck',
   /whenIdle\(\(\)=>revalidateBoard\(id/.test(src), 'the recheck races the board');
ck('...and not the "נצפה לאחרונה" receipt',
   /whenIdle\(\(\)=>api\('\/api\/boards\/'\+id\+'\/seen'/.test(src),
   'the receipt races the board');
ck('whenIdle falls back where requestIdleCallback is missing, and never waits forever',
   /function whenIdle\(fn,ms\)\{[\s\S]*?requestIdleCallback[\s\S]*?timeout:ms\|\|\d+[\s\S]*?setTimeout\(fn/.test(src));
ck('...and no spinner is put up for one', /if\(!seen\) document\.getElementById\('view'\)\.innerHTML='<div class="spin">/.test(src));
ck('an unchanged board is not redrawn', /if\(!changed\)\{[^}]*return;/.test(src));
ck('a changed one is, and keeps her scroll (renderView does)',
   /st\.board=fresh;[\s\S]{0,120}renderView\(\);/.test(src));
ck('a board that is gone, or no longer hers, is forgotten rather than shown',
   /catch\(e\)\{ dropCachedBoard\(id\); return; \}/.test(src));
ck('a switch that happens mid-check does not redraw the board she moved to',
   /if\(st\.board&&st\.board\.id!==id\)return;/.test(src));
ck('both paths put the board on screen through the same function',
   (src.match(/paintBoard\(id\);/g) || []).length >= 2);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
