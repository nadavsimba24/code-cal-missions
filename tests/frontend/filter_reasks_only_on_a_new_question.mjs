/* A filtered board asks the server again when the QUESTION changes — and not
   when a page of the answer arrives.

   Bug 231, reported on production: "בסינון מתקדם בוחרים בעמודה בדיקות בסטטוס
   פתוח. בחלון כתוב 128, ואחרי החלה יש 48 + 2 בשתי קבוצות", and scrolling
   brought nothing back either.

   Paged.load ends in renderView() + refreshToolbar(), and refreshToolbar — on
   any board past filter_client_max with a filter on — armed a fresh
   Paged.load(true) 250ms later. A FRESH load throws away every row it holds
   and starts again at offset zero. So every page that arrived armed the thing
   that would discard it, and the loop fed itself: load → render → re-ask →
   load, several times a second, for as long as the board was left open.

   Whether it SHOWED was a race between that timer and the answer, which is
   why it never appeared in development and never failed a test:

     · the answer comes back before the timer — Paged.fill walks the whole cut
       down and the board reaches every match. That is the local machine, and
       it is also tests/frontend/filter_fills_the_screen.mjs, which stubs
       refreshToolbar to a no-op and so could never see this at all.
     · the timer fires first — the board is pinned to its first page for ever.
       A cut of 128 shows as two folded groups reading "48 פריטים" and
       "2 פריטים", and a scroll that does fetch the next page has it wiped a
       quarter-second later.

   Production is the second case: a query over a couple of thousand rows,
   their cells, their people and their permissions does not come back in a
   quarter of a second.

   ── why this harness drives its own clock ──────────────────────────────

   The first version of this file used real timers and a server stub that
   slept. It passed alone and failed inside the suite, because it was racing
   the same quarter-second the bug races — under load the timers land in a
   different order and the test reports on the machine rather than on the
   code. A test for a race must not contain one.

   So time here is a number this file advances, and the server answers when
   this file says so. "The server is slower than the debounce" becomes one
   explicit line — advance past 250ms, THEN answer — and it means the same
   thing on an idle laptop and on a loaded CI box.

   What is pinned:

     · a page arriving does not re-ask, however slowly it arrived
     · the board reaches every match when the server is slower than the
       debounce — the production case, and the whole of the bug
     · a question that genuinely changed still re-asks, debounced as before

   The re-ask block is lifted verbatim out of refreshToolbar rather than
   transcribed, so a change to it is a change to what this covers.

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

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

const PAGED = cut('const Paged = {', '\n};', 'Paged');
// the re-ask, exactly as refreshToolbar runs it
const REASK = cut("  if(st.board && filterMode()==='server'){", '\n  }', 'the re-ask');

// let every pending .then run — the only real timer in the file, and nothing
// is racing it
const drain = () => new Promise(r => setTimeout(r, 0));

/* One board past filter_client_max, one filter, and a server that answers
   when this file tells it to. The two halves are wired to each other exactly
   as the app wires them: every load ends in the re-ask block, and the re-ask
   block is what arms the next load. */
function harness({matched = 128, total = 2069} = {}){
  const asked = [];                     // every offset that went to the server
  const waiting = [];                   // requests the server has not answered
  const view = {scrollHeight: 120,      // collapsed groups: nothing to scroll
                clientHeight: 800, scrollTop: 0, addEventListener(){}};
  const filters = {q: '', people: [], status: '', priority: '', sort: '',
                   links: null, adv: {op: 'and', rules: [{field: 'c_b', op: 'eq', v: 'פתוח'}]}};
  /* refreshToolbar is called from inside Paged, and the re-ask block it runs
     is built below — so the two are tied together through this rather than
     through a closure neither of them can see. */
  let reask = () => {};

  // ── the clock this file owns ──
  let now = 0, nextId = 0;
  const timers = new Map();
  const setT = (fn, ms) => { timers.set(++nextId, {fn, due: now + ms}); return nextId; };
  const clearT = id => { timers.delete(id); };
  /* Move time forward and run whatever that makes due, oldest first, letting
     each one's promises settle before the next — a timer that arms another
     timer inside the window must still fire inside it. */
  async function advance(ms){
    const until = now + ms;
    for (;;){
      let id = null, best = Infinity;
      for (const [k, t] of timers) if (t.due <= until && t.due < best) { best = t.due; id = k; }
      if (id === null) break;
      const t = timers.get(id); timers.delete(id);
      now = t.due; t.fn(); await drain();
    }
    now = until;
  }

  const env = {
    st: {board: {id: 7, tasks: [], item_count: total, filter_client_max: 1000}, filters},
    document: {getElementById: id => (id === 'view' ? view : null)},
    advQuery: node => ({filter: node, today: '2026-11-18', tz_offset: 120, ids_only: true}),
    withMe: b => b,
    toast: () => {},
    renderView(){},
    refreshToolbar(){ reask(); },
    setTimeout: setT, clearTimeout: clearT,
    api(_p, opt){
      const body = JSON.parse(JSON.stringify(opt.body));
      asked.push(body.offset);
      return new Promise(res => waiting.push(() => {
        const items = [];
        for (let i = body.offset; i < Math.min(matched, body.offset + body.limit); i++)
          items.push({id: i + 1});
        res({items, next_offset: body.offset + items.length,
             has_more: body.offset + items.length < matched, matched, total});
      }));
    },
  };
  const keys = Object.keys(env);
  const made = new Function(...keys, 'filterMode', 'filtersActive',
    'let _pagedTimer=null;\n' + PAGED + '\n' +
    'function REASK_FN(){\n' + REASK + '\n}\n' +
    'return {Paged, REASK_FN};')
    (...keys.map(k => env[k]), () => 'server', () => true);
  reask = made.REASK_FN;

  /* Answer everything outstanding, and everything the answers go on to ask
     for — a page arriving is what triggers the next one. */
  async function answer(){
    for (let i = 0; i < 40 && waiting.length; i++){
      waiting.shift()(); await drain();
    }
  }
  return {...made, asked, filters, answer, advance, pendingTimers: () => timers.size};
}

// ── the answer comes back before the debounce: the old best case ───────────
{
  const h = harness();
  h.Paged.load(true);
  await drain();
  await h.answer();                      // every page, back to back
  ck('every match arrives', h.Paged.rows.length === 128, String(h.Paged.rows.length));
  ck('…in one request per page', h.asked.join(',') === '0,50,100', 'asked ' + h.asked.join(','));
  await h.advance(5000);                 // and now let any armed timer fire
  ck('…and nothing re-asks afterwards, ever', h.asked.join(',') === '0,50,100',
     'asked ' + h.asked.join(','));
  ck('…leaving no timer armed', h.pendingTimers() === 0, String(h.pendingTimers()));
}

// ── production: the server is slower than the 250ms debounce ───────────────
{
  const h = harness();
  h.Paged.load(true);
  await drain();
  // the first page is still in flight when the debounce would have fired
  await h.advance(250);
  ck('a slow first page is not thrown away before it lands',
     h.asked.join(',') === '0', 'asked ' + h.asked.join(','));
  await h.answer();                      // it lands, and fill walks the rest down
  ck('the whole cut arrives', h.Paged.rows.length === 128, String(h.Paged.rows.length) + ' rows');
  ck('…without ever restarting at offset zero', h.asked.join(',') === '0,50,100',
     'asked ' + h.asked.join(','));
  // the number beside it was always right; it was the board that was short
  ck('…and the count is the server’s, across every row', h.Paged.matched === 128,
     String(h.Paged.matched));
  await h.advance(5000);
  ck('…and it stays put', h.Paged.rows.length === 128 && h.asked.length === 3,
     h.Paged.rows.length + ' rows, asked ' + h.asked.join(','));
}

// ── but a question that really changed still re-asks, debounced ────────────
{
  const h = harness();
  h.Paged.load(true);
  await drain(); await h.answer();
  const before = h.asked.length;
  h.filters.q = 'חיפה';                  // somebody types in the search box
  h.REASK_FN();                          // which is where every filter ends up
  ck('a keystroke does not go out at once', h.asked.length === before);
  await h.advance(250);
  ck('…it goes out after the debounce', h.asked.length > before,
     'before ' + before + ', after ' + h.asked.length);
  ck('…and starts again from the top', h.asked[before] === 0, String(h.asked[before]));
}

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
