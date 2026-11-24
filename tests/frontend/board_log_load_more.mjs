/* The board log pages: "טען עוד" fetches the next page with the same filters
   and appends it.

   The log used to make one request and draw what came back, and the server
   only ever returned the newest 400 lines — on a busy board, two days of a
   history that went back months, with nothing on the page to say there was
   more. Now the server sends `next_cursor`, and the modal must (a) offer the
   button only while there is more, (b) carry the active person/day filter
   onto every next page so a filtered list is not spliced with other lines,
   (c) not append a stale page after the filter changed, and (d) be a real
   <button> that keeps keyboard focus when it is redrawn.

   Driven by tests/test_the_board_log_pages_back_through_its_whole_history.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };
const body = (sig, n = 2400) => { const i = src.indexOf(sig); return i < 0 ? '' : src.slice(i, i + n); };

const render = body('  async renderActivity(){');
const more = body('  moreHTML(){', 400);
const load = body('  async loadMore(btn){', 1800);
const fq = body('  filterQs(){', 400);

ck('the first page remembers the cursor only when the server says there is more',
   /this\._cursor=d\.has_more\?d\.next_cursor:null/.test(render));
ck('the list is followed by the load-more slot', /logs-list">\$\{rows\}<\/div>\$\{this\.moreHTML\(\)\}/.test(render));
ck('the button is drawn only while a cursor is held', /this\._cursor\s*\?/.test(more));
ck('it is a real button with the Hebrew label', /<button type="button"[^>]*lg-more/.test(more) && /טען עוד/.test(more));
ck('the filters are encoded once, for both requests',
   /encodeURIComponent\(this\.user\)/.test(fq) && /encodeURIComponent\(this\.date\)/.test(fq)
   && /this\.filterQs\(\)/.test(render) && /this\.filterQs\(\)/.test(load));
ck('the next page is asked for with the cursor', /'cursor='\+encodeURIComponent\(this\._cursor\)/.test(load));
ck('a page that lands after the filter changed is dropped',
   /const gen=this\._gen;/.test(load) && /if\(gen!==this\._gen\)return;/.test(load)
   && /this\._gen=\(this\._gen\|\|0\)\+1/.test(render));
ck('new lines are appended, not redrawn over the old ones',
   /insertAdjacentHTML\('beforeend'/.test(load) && /this\.lineHTML\(a\)/.test(load));
ck('the button is disabled while its request is in flight', /btn\.disabled=true/.test(load));
ck('a failure gives the button back', /btn\.disabled=false/.test(load));
ck('focus moves to the redrawn button', /\.lg-more'\);\s*\n?\s*if\(next\)next\.focus\(\)/.test(load));
ck('the button spans the width on a phone', /@media \(max-width:600px\)\{#modal \.lg-more-wrap \.lg-more\{inline-size:100%/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
