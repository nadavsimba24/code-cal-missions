/* Under a filter on a big board, every group says how many matches it holds,
   and the rows under the first page are reached without scrolling the whole
   board.

   Past the client threshold the rows of a filtered board arrive through Paged,
   fifty at a time, group after group. The header of each group counted the
   rows that had arrived, so a group holding 78 matches read "50" — or "20",
   when the groups above it had used up most of the first page — where monday
   said 78. And the groups under it were either drawn as empty headers or not
   drawn at all, and nothing loaded until somebody scrolled to the very bottom
   of the board, past every one of them.

   The server now sends `group_matched` with every page, the per-group count
   over the whole answer, and the browser keeps it in Paged.group_matched.
   What is pinned here, all out of index.html with stubbed globals:

   * groupCountKnown reads group_matched for a narrowed server-mode board, and
     group_counts otherwise (or with `whole`); in client mode while narrowed
     it knows nothing (null), because there the rows in hand ARE the answer;
   * groupRowsMissing / firstIncompleteGroupKey say which groups still have
     rows on the server, and which one the next page goes to;
   * groupMoreRowHTML gives that first group a real button, the groups after
     it a plain "waiting" line with nothing to press, a complete group
     nothing — and nothing at all once the server says there is no more;
   * the group name in the button's aria-label is escaped;
   * groupsOf draws a group whose matches are all still on the server, and
     still hides a group with none;
   * Paged.watchMore asks for a page once per footer position ("gid:held"),
     never twice from the same place — driven with a stub
     IntersectionObserver and a stub document.

   Driven by tests/test_a_filtered_big_board_counts_and_loads_every_group.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(src);
  if (!m) throw new Error('not found: ' + name);
  let d = 0;
  for (let k = src.indexOf('{', m.index); k < src.length; k++){
    if (src[k] === '{') d++;
    else if (src[k] === '}'){ d--; if (!d) return src.slice(m.index, k + 1); }
  }
  throw new Error('unbalanced: ' + name);
}
/* A method of the Paged object literal, by the same brace count. Paged as a
   whole cannot be lifted out — it closes over half the app — but watchMore
   reads only `this`, document and IntersectionObserver. */
function grabMethod(name){
  const m = new RegExp(`^  ${name}\\(`, 'm').exec(src);
  if (!m) throw new Error('method not found: ' + name);
  let d = 0;
  for (let k = src.indexOf('{', m.index); k < src.length; k++){
    if (src[k] === '{') d++;
    else if (src[k] === '}'){ d--; if (!d) return src.slice(m.index, k + 1).trim(); }
  }
  throw new Error('unbalanced: ' + name);
}
// the real esc, so the escaping case is checked against what the app does
const escLine = /^const esc = .*$/m.exec(src);
if (!escLine) throw new Error('esc not found');
const esc = new Function(escLine[0] + '; return esc;')();

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

const EMPTY_F = {q:'', people:[], status:'', priority:'', sort:'', links:{col:'',mode:'',item:0}, adv:null};
const bundle = ['boardIsNarrowed','groupCountKnown','groupRowsMissing',
                'firstIncompleteGroupKey','groupMoreRowHTML','groupsOf'].map(grab).join('\n');

const rows = (n, gid, from) => Array.from({length:n}, (_, i) => ({id:from + i, group_id:gid, subtasks:[]}));

/* A board past the threshold: no rows of its own, the rows in Paged, and the
   per-group figures the server would send. */
function scene({groups, held = [], counts = null, matched = null, filters = {q:'חיפה'},
                mode = 'server', on = true, more = true}){
  const st = {board:{id:1, groups, tasks:[]}, filters:Object.assign({}, EMPTY_F, filters), colSort:null};
  if (counts) st.board.group_counts = counts;
  const Paged = {on, more, rows:held.slice(), group_matched:matched, _footerBusy:false};
  const env = {
    st, Paged, esc,
    advCount: n => (n && n.rules) ? n.rules.length : 0,
    filterMode: () => mode,
    // on a paged board the rows on screen ARE the server's answer
    applyFilters: ts => Paged.on ? Paged.rows.slice() : ts.slice(),
    totalCols: () => 5,
  };
  const names = Object.keys(env);
  const fns = new Function(...names, bundle +
    '; return {boardIsNarrowed,groupCountKnown,groupRowsMissing,firstIncompleteGroupKey,groupMoreRowHTML,groupsOf};')
    .apply(null, names.map(n => env[n]));
  return {st, Paged, ...fns};
}

const ABC = [{id:1, name:'א'}, {id:2, name:'ב'}, {id:3, name:'ג'}];
// A holds 78 matches of which the first page brought 50; B's 30 are all
// still on the server; C matched nothing.
const GM = {'1':78, '2':30, '3':0};
const ALL = {'1':400, '2':300, '3':200};
const big = () => scene({groups:ABC, held:rows(50, 1, 1), counts:ALL, matched:{...GM}});

// ── (a) the header count ──────────────────────────────────────────────────
{
  const s = big();
  ck('a filtered big board\'s header reads the server\'s count of matches, not the 50 rows held',
     s.groupCountKnown(1) === 78, String(s.groupCountKnown(1)));
  ck('...and a group none of whose rows has arrived reads its matches, not 0',
     s.groupCountKnown(2) === 30, String(s.groupCountKnown(2)));
  ck('a group nothing matched in reads 0, not unknown',
     s.groupCountKnown(3) === 0, String(s.groupCountKnown(3)));
  ck('asked for the whole group, it still answers with the board\'s own size',
     s.groupCountKnown(1, true) === 400, String(s.groupCountKnown(1, true)));

  const nullBucket = scene({groups:ABC, held:[], counts:{...ALL, 'null':9}, matched:{...GM, 'null':4}});
  ck('the «ללא קבוצה» bucket is looked up under "null"',
     nullBucket.groupCountKnown(null) === 4, String(nullBucket.groupCountKnown(null)));

  const unnarrowed = scene({groups:ABC, held:rows(50, 1, 1), counts:ALL, matched:{...GM}, filters:{}});
  ck('with no filter on, the header reads the board\'s group_counts',
     unnarrowed.groupCountKnown(1) === 400, String(unnarrowed.groupCountKnown(1)));

  const client = scene({groups:ABC, held:[], counts:ALL, matched:{...GM}, mode:'client', on:false, more:false});
  ck('a narrowed board filtered in the browser knows no count of its own (null)',
     client.groupCountKnown(1) === null, String(client.groupCountKnown(1)));

  const noMap = scene({groups:ABC, held:rows(50, 1, 1), counts:ALL, matched:null});
  ck('a narrowed server board whose answer carried no group_matched knows no count (null)',
     noMap.groupCountKnown(1) === null, String(noMap.groupCountKnown(1)));
}

// ── (b) who gets which footer ─────────────────────────────────────────────
{
  const s = big();
  const gs = s.groupsOf();
  const [A, B, C] = [1, 2, 3].map(id => gs.find(g => g.id === id));
  ck('the filtered board draws A and B, and not C', !!A && !!B && !C,
     JSON.stringify(gs.map(g => g.id)));

  ck('A is missing 28 rows', s.groupRowsMissing(A, 78) === 28, String(s.groupRowsMissing(A, 78)));
  ck('B is missing all 30', s.groupRowsMissing(B, 30) === 30, String(s.groupRowsMissing(B, 30)));
  ck('a missing count reads its own known figure when none is passed',
     s.groupRowsMissing(A) === 28, String(s.groupRowsMissing(A)));
  const Cg = {id:3, name:'ג', tasks:[]};
  ck('C, with nothing matched, is missing nothing', s.groupRowsMissing(Cg, 0) === 0);

  const first = s.firstIncompleteGroupKey(gs);
  ck('the first incomplete group is A, by its key', first === '1', JSON.stringify(first));

  const aHtml = s.groupMoreRowHTML(A, 78, first);
  ck('A ends in a footer row', /<tr class="grp-more-row">/.test(aHtml), aHtml);
  ck('...with a real button that asks Paged for the next page',
     /<button type="button" class="grp-more"/.test(aHtml) && /onclick="Paged\.loadFromFooter\(this\)"/.test(aHtml), aHtml);
  ck('...which says how many are shown out of how many',
     aHtml.includes('מוצגים 50 מתוך 78 · טען עוד'), aHtml);
  ck('...and carries the gid:held key the loop guard uses',
     /data-key="1:50"/.test(aHtml), aHtml);

  const bHtml = s.groupMoreRowHTML(B, 30, first);
  ck('B, further down, gets the waiting line',
     /<tr class="grp-more-row grp-more-wait">/.test(bHtml) && /<span class="grp-wait">/.test(bHtml), bHtml);
  ck('...saying how many are still to come',
     bHtml.includes('עוד 30 פריטים ממתינים לטעינה'), bHtml);
  ck('...and offering nothing to press', !/<button/.test(bHtml) && !/loadFromFooter/.test(bHtml), bHtml);

  ck('C gets no footer at all', s.groupMoreRowHTML(Cg, 0, first) === '');

  // one row still to come reads in the singular
  const one = scene({groups:ABC, held:rows(50, 1, 1), counts:ALL, matched:{'1':78, '2':1, '3':0}});
  const B1 = one.groupsOf().find(g => g.id === 2);
  const b1Html = one.groupMoreRowHTML(B1, 1, '1');
  ck('a group with a single row waiting says so in the singular',
     b1Html.includes('עוד פריט אחד ממתין לטעינה') && !b1Html.includes('עוד 1 '), b1Html);

  // with no firstKey passed, it works it out from groupsOf
  ck('left to work out the first key itself, A still gets the button',
     /class="grp-more"/.test(s.groupMoreRowHTML(A, 78)), s.groupMoreRowHTML(A, 78));
  ck('...and B still gets the waiting line',
     /grp-more-wait/.test(s.groupMoreRowHTML(B, 30)), s.groupMoreRowHTML(B, 30));

  // a full group above the incomplete one does not take the button from it
  const fullFirst = scene({groups:ABC, held:rows(10, 1, 1).concat(rows(40, 2, 100)),
                           counts:ALL, matched:{'1':10, '2':70, '3':0}});
  const fg = fullFirst.groupsOf();
  ck('a group whose matches are all in hand is passed over for the first incomplete one',
     fullFirst.firstIncompleteGroupKey(fg) === '2', fullFirst.firstIncompleteGroupKey(fg));
  ck('...and has no footer of its own',
     fullFirst.groupMoreRowHTML(fg.find(g => g.id === 1), 10, '2') === '');

  // the «ללא קבוצה» bucket is keyed 'null'
  const orphan = scene({groups:ABC, held:rows(3, 1, 1), counts:ALL, matched:{'1':3, '2':0, '3':0, 'null':12}});
  ck('when only the «ללא קבוצה» bucket is incomplete, its key is \'null\'',
     orphan.firstIncompleteGroupKey(orphan.groupsOf()) === 'null',
     JSON.stringify(orphan.firstIncompleteGroupKey(orphan.groupsOf())));

  const whole = scene({groups:ABC, held:rows(50, 1, 1), counts:ALL, matched:{'1':50, '2':0, '3':0}});
  ck('when every group is whole there is no first incomplete key',
     whole.firstIncompleteGroupKey(whole.groupsOf()) === null);
}

// ── (c) once the server says there is no more ─────────────────────────────
{
  const s = big();
  s.Paged.more = false;
  const A = {id:1, name:'א', tasks:rows(50, 1, 1)}, B = {id:2, name:'ב', tasks:[]};
  ck('with Paged.more false, nothing is missing from any group',
     s.groupRowsMissing(A, 78) === 0 && s.groupRowsMissing(B, 30) === 0);
  ck('...no group is the first incomplete one', s.firstIncompleteGroupKey([A, B]) === null);
  ck('...and no group has a footer',
     s.groupMoreRowHTML(A, 78, '1') === '' && s.groupMoreRowHTML(B, 30, '1') === '' &&
     s.groupMoreRowHTML(A, 78) === '' && s.groupMoreRowHTML(B, 30) === '');

  const off = big();
  off.Paged.on = false;
  ck('a board not paged at all has no footers either', off.groupMoreRowHTML(A, 78, '1') === '');

  const blind = big();
  ck('a group with no known count has no footer (nothing to compare against)',
     blind.groupRowsMissing(A, null) === 0 && blind.groupMoreRowHTML(A, null, '1') === '');
}

// ── (d) the group name is escaped ─────────────────────────────────────────
{
  const evil = '<script>alert(1)</script>"x';
  const s = scene({groups:[{id:1, name:evil}, ...ABC.slice(1)], held:rows(50, 1, 1), counts:ALL, matched:{...GM}});
  const A = s.groupsOf().find(g => g.id === 1);
  const html = s.groupMoreRowHTML(A, 78, '1');
  const aria = (/aria-label="([^"]*)"/.exec(html) || [])[1] || '';
  ck('a group name with <script> reaches the aria-label escaped',
     aria.includes('&lt;script&gt;alert(1)&lt;/script&gt;&quot;x'), aria);
  ck('...and no raw <script> appears anywhere in the footer', !/<script/i.test(html), html);
  ck('...and the quote in it does not close the attribute early',
     aria.endsWith('מוצגים 50 מתוך 78 · טען עוד'), aria);
}

// ── (e) the waiting group is drawn under a filter ─────────────────────────
{
  const s = big();
  const ids = s.groupsOf().map(g => g.id);
  ck('a group whose matches are all still on the server is drawn under a filter',
     ids.includes(2), JSON.stringify(ids));
  ck('...with no rows in it yet', s.groupsOf().find(g => g.id === 2).tasks.length === 0);
  ck('a group with 0 matches is still hidden', !ids.includes(3), JSON.stringify(ids));

  const orphan = scene({groups:ABC, held:rows(50, 1, 1), counts:ALL, matched:{...GM, 'null':5}});
  ck('the «ללא קבוצה» bucket is drawn too while its matches are waiting',
     orphan.groupsOf().some(g => g.id === null), JSON.stringify(orphan.groupsOf().map(g => g.id)));

  const done = big(); done.Paged.more = false;
  const dids = done.groupsOf().map(g => g.id);
  ck('once everything has arrived, a group with no rows held is hidden again',
     dids.join(',') === '1', JSON.stringify(dids));

  const client = scene({groups:ABC, held:[], counts:ALL, matched:{...GM}, mode:'client', on:false, more:false});
  ck('a board filtered in the browser does not draw a group for a stale server count',
     client.groupsOf().length === 0, JSON.stringify(client.groupsOf().map(g => g.id)));

  const plain = scene({groups:ABC, held:rows(50, 1, 1), counts:ALL, matched:{...GM}, filters:{}});
  ck('with no filter on, every group is drawn as before',
     plain.groupsOf().map(g => g.id).join(',') === '1,2,3');
}

// ── (f) the loop guard in Paged.watchMore ─────────────────────────────────
/* A stub IntersectionObserver that keeps its callback, so the test can say
   "this footer came into view" as many times as it likes; a stub document
   whose #view holds the footer buttons. watchMore is the real method, bound
   to a Paged-shaped object whose load() just counts. */
{
  let lastIO = null;
  class IO {
    constructor(cb){ this.cb = cb; this.targets = []; lastIO = this; }
    observe(t){ this.targets.push(t); }
    disconnect(){ this.targets = []; }
    fire(t){ this.cb([{isIntersecting:true, target:t}]); }
  }
  const btn = (gid, key) => ({dataset:{gid, key}, closest:() => null, focus(){}});
  const view = {buttons:[], querySelectorAll(s){ return s === '.grp-more' ? this.buttons : []; },
                querySelector(){ return null; }};
  const document = {getElementById:id => id === 'view' ? view : null,
                    activeElement:null, body:{}, contains:() => true};
  const method = grabMethod('watchMore');
  const make = new Function('document', 'IntersectionObserver',
    `return { on:true, more:true, loading:false, _io:null, _refocus:null, _footerBusy:false,
              _autoAsked:new Set(), asked:0, load(){ this.asked++; }, ${method} };`);
  const P = make(document, IO);

  const a50 = btn('1', '1:50');
  view.buttons = [a50];
  P.watchMore(null);
  ck('watchMore observes the footer button', !!lastIO && lastIO.targets.includes(a50));
  lastIO.fire(a50);
  ck('a footer coming into view asks for the next page', P.asked === 1, 'asked=' + P.asked);
  lastIO.fire(a50);
  ck('the same footer seen again does not ask a second time', P.asked === 1, 'asked=' + P.asked);

  /* the render after the page re-attaches: the same group with the same rows
     in it (the page went elsewhere) is the same key, and must not ask again */
  const a50again = btn('1', '1:50');
  view.buttons = [a50again];
  P.watchMore(null);
  lastIO.fire(a50again);
  ck('after a re-render, a footer at the same "gid:held" place does not ask again',
     P.asked === 1, 'asked=' + P.asked);

  // the same group with more rows in it is a new place, and does ask
  const a78 = btn('1', '1:100');
  view.buttons = [a78];
  P.watchMore(null);
  lastIO.fire(a78);
  ck('the same group with more rows held is a new key and asks once more',
     P.asked === 2, 'asked=' + P.asked);

  // nothing asked while a page is already loading, and the key is not spent
  const b0 = btn('2', '2:0');
  view.buttons = [b0];
  P.loading = true;
  P.watchMore(null);
  lastIO.fire(b0);
  ck('a footer seen while a page is loading asks nothing', P.asked === 2, 'asked=' + P.asked);
  P.loading = false;
  lastIO.fire(b0);
  ck('...and can still ask once that page is in', P.asked === 3, 'asked=' + P.asked);

  // no more pages → no observer at all
  P.more = false;
  lastIO = null;
  view.buttons = [btn('3', '3:0')];
  P.watchMore(null);
  ck('when the server has no more, watchMore observes nothing', lastIO === null);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
