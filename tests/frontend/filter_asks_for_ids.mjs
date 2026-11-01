/* The browser asks the filter question in the shape whose answer is complete.

   /api/boards/{id}/items/query answers two ways. A board the browser filters
   itself wants the IDS — it holds every row already and is only missing which
   of them survive. A board too large to hold wants a PAGE of rows, because the
   page is what will be drawn. The caller says which by sending ids_only, and
   the small-board path sent neither — so it got the page, fifty ids, and
   applyFilters kept only the rows named in it. Every match past the fiftieth
   left the board with nothing on screen to say so.

   Two things are pinned here, and neither can be read off the server:

     · advQuery, the body the browser sends, carries ids_only — and Paged's
       own copy turns it back off, because there the rows ARE the answer.
     · advServerIds refuses a list the server marked `truncated`. A cut list
       used as the whole answer is the same disappearance one order of
       magnitude further along, and the engine in this browser has matched
       every row it holds.

   Driven by tests/test_filter_returns_every_matching_item.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function cut(start, end, what){
  const i = src.indexOf(start);
  if (i < 0) throw new Error('not found — has ' + what + ' changed? ' + start);
  const j = src.indexOf(end, i);
  if (j < 0) throw new Error('no end for ' + what);
  return src.slice(i, j + end.length);
}

// the real functions, out of the real file
const CODE = [
  cut('function advIso(d){', '\n}', 'advIso'),
  cut('function advToAst(node){', '\n}', 'advToAst'),
  cut('function advQuery(node){', '\n}', 'advQuery'),
  cut('function advServerIds(r){', '\n}', 'advServerIds'),
].join('\n');
const {advQuery, advServerIds} =
  new Function(CODE + '\nreturn {advQuery, advServerIds};')();

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

const MINE = {op:'and', rules:[{field:'assignees', op:'has', v:'me', v2:''}]};

// ── the body the browser sends ───────────────────────────────────────────
const q = advQuery(MINE);
ck('the filter query asks for ids, not for a page', q.ids_only === true, JSON.stringify(q));
ck('the tree still travels with it', q.filter && q.filter.rules.length === 1);
ck("'me' goes as the token it is", q.filter.rules[0].value === 'me');
ck('and the clock to resolve tokens against', /^\d{4}-\d{2}-\d{2}$/.test(q.today));

/* Paged's own body, read from the source rather than run: it is a method on an
   object full of state this harness has no business standing up. What matters
   is that it says ids_only at all — the default is now true, so a page of rows
   is something that has to be asked for. */
const paged = cut('  query(){', '  },', 'Paged.query');
ck('the paged board turns ids_only back off', /ids_only\s*:\s*false/.test(paged), paged);

// ── which answers the board may be narrowed by ───────────────────────────
const ids = advServerIds({item_ids:[4, 9], truncated:false});
ck('a complete answer becomes the set of ids to keep',
   ids instanceof Set && ids.has(4) && ids.has(9) && ids.size === 2);
ck('a truncated list is refused — the browser answers instead',
   advServerIds({item_ids:[4, 9], truncated:true}) === null);
ck('an answer with no list at all is refused too',
   advServerIds({matched:3}) === null);
ck('…and so is no answer', advServerIds(null) === null);
ck('an empty list is an answer: nothing matched',
   advServerIds({item_ids:[], truncated:false}) instanceof Set);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
