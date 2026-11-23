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
const base = {id: 5, name: 'לוח', my_role: 'admin', icon: '📋',
              groups: [{id: 1, name: 'ראשונה', color: '#0073ea', position: 0},
                       {id: 2, name: 'שנייה',  color: '#00c875', position: 1}],
              columns: [{id: 'a', name: 'עמודה', type: 'text'},
                        {id: 'b', name: 'סטטוס', type: 'status', options: ['א']}],
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
  /* Counting the groups and the columns was the bug. None of these moves an
     item's updated_at and none of them changes how many there are, so the
     stamp said "nothing changed", the board was not redrawn, and what she had
     just renamed went on showing its old name until the page was reloaded by
     hand. Renaming a group straight after creating it is how it was found. */
  ['a group was RENAMED',       x => { x.groups[0].name = 'אחרת'; }],
  ['a group was RECOLOURED',    x => { x.groups[1].color = '#e2445c'; }],
  ['a group was MOVED',         x => { x.groups[0].position = 5; }],
  ['a column was RENAMED',      x => { x.columns[0].name = 'אחרת'; }],
  ['a column was RETYPED',      x => { x.columns[0].type = 'number'; }],
  ['a status option was added', x => { x.columns[1].options.push('ב'); }],
  ['the board icon changed',    x => { x.icon = '🚀'; }],
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
/* …and what is remembered is what is ON SCREEN. Where the stamp says the two
   agree, keeping the server's copy threw away whatever had been applied to the
   one on screen since — a group renamed a moment ago — so the next open of
   this board came out of memory without it. */
ck('an unchanged board keeps the copy she is looking at, not the one just fetched',
   /cacheBoard\(changed\?fresh:st\.board\);/.test(src));
/* Anchored to the reopen path itself. It used to look for "st.board=fresh;"
   followed by renderView() anywhere in the file within 120 characters — and
   the only place that ever matched was the item drag's drop handler, so this
   check was passing on code that has nothing to do with the cache, and went
   red the day that handler grew a comment. */
{ const at=src.indexOf('cacheBoard(changed?fresh:st.board);');
  const tail=at<0?'':src.slice(at, at+3000);
  ck('a changed one is, and keeps her scroll (renderView does)',
     /^cacheBoard\(changed\?fresh:st\.board\);\s*if\(!changed\)\{[^}]*return;\s*\}\s*st\.board=fresh;[\s\S]*?renderView\(\);/.test(tail),
     tail.slice(0,160)); }
ck('a board that is gone, or no longer hers, is forgotten rather than shown',
   /catch\(e\)\{ dropCachedBoard\(id\); return; \}/.test(src));
ck('a switch that happens mid-check does not redraw the board she moved to',
   /if\(st\.board&&st\.board\.id!==id\)return;/.test(src));
ck('both paths put the board on screen through the same function',
   (src.match(/paintBoard\(id\);/g) || []).length >= 2);

// ── the quiet work: warming the boards she has not asked for yet ──
// Prod is HTTP/1.1, so background work that is not polite becomes the problem
// it was meant to solve.
const pf = new Function('st','api','meId','whenIdle','cacheBoard','_boardCache','navigator','_boardFetches',
  line(/const PREFETCH_MAX=\d+;/) + grab('prefetchBoards')
  + '\nreturn {prefetchBoards, PREFETCH_MAX};');

function runPrefetch(opts){
  const asked=[]; let idleQueue=[];
  const cache=new Map((opts.cached||[]).map(id=>[id,{id}]));
  const api=(u)=>{ asked.push(u); return opts.reject?Promise.reject(new Error('403')):Promise.resolve({id:+(/\/(\d+)/.exec(u)||[])[1]}); };
  const h=pf({boards:(opts.boards||[]).map(id=>({id})), board:{id:opts.open}},
             api, ()=>1, (fn)=>idleQueue.push(fn), b=>cache.set(b.id,b), cache,
             opts.navigator||{}, opts.inFlight||0);
  h.prefetchBoards();
  // drain the idle queue the way a quiet browser would
  for(let i=0;i<40 && idleQueue.length;i++){ const q=idleQueue; idleQueue=[]; q.forEach(fn=>fn()); }
  return {asked, cache, max:h.PREFETCH_MAX};
}

let r=runPrefetch({boards:[1,2,3,4,5,6,7,8,9], open:1});
ck('it warms the boards she has not opened yet', r.asked.length>0, 'asked for nothing');
ck('...a few at a time, not every board she has', r.asked.length<=r.max,
   'asked for '+r.asked.length+', cap is '+r.max);
ck('...never the one already on screen',
   !r.asked.some(u=>/\/api\/boards\/1\?|\/api\/boards\/1$/.test(u)), r.asked.join(' '));

r=runPrefetch({boards:[1,2,3], open:1, cached:[2,3]});
ck('...and never one it already has', r.asked.length===0, r.asked.join(' '));

r=runPrefetch({boards:[1,2,3,4], open:1, inFlight:1});
ck('it stands aside while she is waiting for a board she asked for',
   r.asked.length===0, 'it competed with the board she wanted');

r=runPrefetch({boards:[1,2,3,4], open:1, navigator:{connection:{saveData:true}}});
ck('it does nothing on a connection asking to be spared', r.asked.length===0);
r=runPrefetch({boards:[1,2,3,4], open:1, navigator:{connection:{effectiveType:'2g'}}});
ck('...nor on a 2g one', r.asked.length===0);

r=runPrefetch({boards:[1,2,3,4], open:1, reject:true});
ck('a board she may not see is not an error worth stopping for',
   r.asked.length>0, 'it gave up on the first refusal');

// ── the people list ──
ck('the people list is not refetched on every switch',
   /const USERS_TTL_MS=\d+;/.test(src) && /if\(!force && _usersAt/.test(src),
   'it competed with the board for one of six connections, to re-learn names');
ck('...but changing a photograph or adding a person still refetches at once',
   (src.match(/refreshUsers\(true\)/g)||[]).length>=2);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
