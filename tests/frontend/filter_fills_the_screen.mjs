/* A filtered board that is shorter than the screen still reaches every match.

   Past filter_client_max the board shows the server's answer fifty rows at a
   time, and until now the only thing that ever asked for row fifty-one was the
   scroll handler on #view. A scroll event fires only on an element that HAS
   something to scroll, so a cut whose first page did not fill the screen
   stopped at fifty with no gesture left to make.

   Collapsed groups are the case that made it plain: a filter the builder had
   promised 131 items for applied, the board came back as two folded headers
   reading "48 פריטים" and "2 פריטים" — the page split between them, not the
   answer — and the other eighty-one were unreachable.

   Two things are pinned here:

     · Paged.fill asks for the next page when #view cannot scroll, keeps
       asking while that stays true, and stops the moment it can — a long
       board must not be pulled down whole just because the first page was
       drawn into a tall viewport.
     · The sentence prints `matched`, the server's count across every row,
       rather than dropping it. "מתוך 2069 פריטים" with no number in front of
       it is what let 131 read as 50.

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

/* The real object, out of the real file, over a stub of everything it leans
   on. Paged is a cache of one answer and nothing else, which is what makes
   standing it up like this honest: the parts being tested — when it asks for
   another page, and when it stops — are all in the object. */
const PAGED = cut('const Paged = {', '\n};', 'Paged');

function harness({matched, total, viewScrolls}){
  const asked = [];                       // every offset the object asked for
  const view = {scrollHeight: 0, clientHeight: 800, scrollTop: 0,
                addEventListener(){}, };
  const env = {
    st: {board: {id: 7, tasks: []}, filters: {}},
    document: {getElementById: id => (id === 'view' ? view : null)},
    advQuery: () => ({}),
    withMe: b => b,
    toast: () => {},
    renderView(){ /* rows are drawn, so the board gets taller */
      view.scrollHeight = viewScrolls(Paged.rows.length); },
    refreshToolbar(){},
    async api(_p, opt){
      const body = JSON.parse(JSON.stringify(opt.body));
      asked.push(body.offset);
      const items = [];
      for (let i = body.offset; i < Math.min(matched, body.offset + body.limit); i++)
        items.push({id: i + 1});
      return {items, next_offset: body.offset + items.length,
              has_more: body.offset + items.length < matched,
              matched, total};
    },
  };
  const keys = Object.keys(env);
  const Paged = new Function(...keys, 'let _pagedTimer=null;\n' + PAGED + '\nreturn Paged;')
                  (...keys.map(k => env[k]));
  return {Paged, asked, view};
}

// ── the bug, as reported: 131 match, the board cannot scroll ────────────────
{
  // collapsed groups draw headers and nothing else: the board never grows
  const {Paged, asked} = harness({matched: 131, total: 2069, viewScrolls: () => 120});
  await Paged.load(true);
  // the loads chain through the finally, so let them settle
  for (let i = 0; i < 20 && Paged.loading; i++) await new Promise(r => setTimeout(r, 0));
  ck('a board that cannot scroll keeps asking', asked.length > 1, 'asked ' + asked.join(','));
  ck('…until every match has arrived', Paged.rows.length === 131, String(Paged.rows.length));
  ck('…and then stops', Paged.more === false);
  ck('the server count is kept, not the page count', Paged.matched === 131);
}

// ── a page that DOES fill the screen is left to the scroll handler ──────────
{
  const {Paged, asked} = harness({matched: 9000, total: 9000,
                                  viewScrolls: n => n * 36});   // 50 rows ≫ 800px
  await Paged.load(true);
  for (let i = 0; i < 20 && Paged.loading; i++) await new Promise(r => setTimeout(r, 0));
  ck('one page that fills the screen asks for nothing more',
     asked.length === 1, 'asked ' + asked.join(','));
  ck('…and there is still more to scroll to', Paged.more === true);
}

// ── and a board that can never scroll is still bounded ─────────────────────
{
  const {Paged} = harness({matched: 15000, total: 15000, viewScrolls: () => 120});
  await Paged.load(true);
  for (let i = 0; i < 600 && Paged.loading; i++) await new Promise(r => setTimeout(r, 0));
  ck('a cut of fifteen thousand is not walked through one page at a time',
     Paged.rows.length <= Paged.FILL_MAX + 50, String(Paged.rows.length));
  ck('…and it got there, rather than stopping at the first page',
     Paged.rows.length >= Paged.FILL_MAX, String(Paged.rows.length));
}

// ── the sentence says how many matched ─────────────────────────────────────
{
  const CODE = cut('function qfShowing(){', '\n}', 'qfShowing');
  const Paged = {on: true, matched: 131, total: 2069};
  const st = {board: {tasks: new Array(2069)}};
  const applyFilters = () => [];
  const qfShowing = new Function('Paged', 'st', 'applyFilters',
                                 CODE + '\nreturn qfShowing;')(Paged, st, applyFilters);
  const s = qfShowing();
  ck('the number the server matched is printed', /131/.test(s), s);
  ck('…beside the number the board holds', /2069/.test(s), s);
  // and the cut that matches everything says so in the words it always has
  Paged.matched = 2069;
  ck('a cut that matches the whole board says so', /כל/.test(qfShowing()), qfShowing());
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
