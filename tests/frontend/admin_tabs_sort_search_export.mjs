/* ניהול מערכת — the six tabs sort, filter and export as ONE table.

   Six tabs had grown six half-tables and the first one that learned to sort
   made the other five look broken, so the chrome is shared: a COLS table per
   tab, sortOf/sortBy/sortRows, a live search box, a count, and a client-side
   CSV. Shared machinery means a single mistake breaks all six at once, which is
   what this harness is for.

   Four of the checks are regression guards rather than feature tests:

   · autoRowsHTML must EXIST. bodyHTML routes the automations tab to it, and the
     reference was written before the method was — the first admin to click a
     column header on that tab would have got a TypeError and an empty table.

   · repaint() must not assign to #sa-body. Rebuilding the body between two
     keystrokes takes the search input out of the DOM and the caret with it —
     the trap the comment on setAutoQ has been warning about since the
     automations filter. repaint touches #sa-rows and #sa-count, nothing else.

   · the empty-state colspan must equal the real column count. It was a
     hardcoded 7 on the users tab, and the moment "מועד הזמנה למערכת" was added
     the "no results" cell stopped spanning the table.

   · a blank sorts LAST in both directions. A plain comparator puts the empty
     rows first the moment the arrow flips, and an admin reversing a column
     wants the other end of the data, not a screenful of rows with nothing.

   Driven by tests/test_admin_tabs_sort_search_export.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

/* ── the object itself, lifted out of the page and run ──
   The literal has no load-time dependency on the rest of the SPA: every
   reference to esc/ROLE_HE/st lives inside a method or inside one of the COLS
   arrows, so it is enough to hand those in as parameters. Closing on the first
   column-zero "};" — brace counting does not survive this file. */
function lift(){
  const i = src.indexOf('const SysAdmin = {');
  if (i < 0) throw new Error('SysAdmin object not found');
  const end = src.indexOf('\n};', i);
  if (end < 0) throw new Error('SysAdmin object does not close');
  return src.slice(i, end + 3);
}
const BODY = lift();

/* close on the first line indented two spaces — same trick the other harnesses
   use, see login_time_is_israel_time.mjs */
function grabMethod(header){
  const i = BODY.indexOf(header);
  if (i < 0) return '';
  const nl = BODY.indexOf('\n', i);
  const end = BODY.indexOf('\n  }', nl);
  return BODY.slice(i, end + 4);
}

const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                   .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const ROLE_HE = {admin: 'מנהל מערכת', manager: 'מנהל', member: 'חבר', viewer: 'צופה', guest: 'אורח'};
const st = {depts: []};

// whatever a row renderer reaches for on its way to markup
const stubs = {
  esc, ROLE_HE, st,
  avatarInner: () => 'A',
  envIconHTML: () => '<i></i>',
  canAdminEnvs: () => true,
  BoardLog: {ago: v => String(v)},
  fdatetimeY: v => String(v),
  meId: () => 1,
  hasCap: () => true,
  // the CSV writer's three collaborators; the Blob keeps what it was handed
  Blob: class { constructor(parts){ this.text = parts.join(''); lastBlob = this; } },
  URL: {createObjectURL: () => 'blob:x', revokeObjectURL: () => {}},
  document: {createElement: () => ({click(){ clicked = {href: this.href, download: this.download}; }}),
             getElementById: () => null, querySelectorAll: () => []},
  setTimeout: () => 0,
};
let lastBlob = null, clicked = null;

const keys = Object.keys(stubs);
const SA = new Function(...keys, BODY + '\nreturn SysAdmin;')(...keys.map(k => stubs[k]));
ck('the system-admin object lifts out of the page and evaluates', !!SA && typeof SA === 'object');

const TABS = ['users', 'guests', 'depts', 'envs', 'autos', 'history'];

/* ── every tab declares its columns, and every tab is routed ── */
ck('all six tabs declare columns', TABS.every(t => Array.isArray(SA.COLS[t]) && SA.COLS[t].length),
   JSON.stringify(TABS.filter(t => !(SA.COLS[t] || []).length)));
ck('and nothing else sneaked into COLS', Object.keys(SA.COLS).length === 6, Object.keys(SA.COLS).join(','));

const bodyHTML = grabMethod('bodyHTML(tab){');
const rowsOf = grabMethod('rowsOf(tab){');
ck('bodyHTML routes every tab to a renderer',
   ['guests', 'depts', 'envs', 'history', 'autos'].every(t => bodyHTML.includes(`'${t}'`)) && /rowsHTML\(\)/.test(bodyHTML),
   bodyHTML);
ck('rowsOf knows where every tab keeps its rows',
   TABS.every(t => rowsOf.includes(`'${t}'`)), rowsOf);

/* the regression: bodyHTML calls autoRowsHTML, so autoRowsHTML has to be there */
ck('autoRowsHTML exists — the automations tab had a renderer that was only referenced',
   typeof SA.autoRowsHTML === 'function', 'bodyHTML calls a method nobody defined');
ck('...and bodyHTML is what calls it', /autoRowsHTML\(\)/.test(bodyHTML), bodyHTML);

// every renderer reads view(), so the body, the count and the export agree
for (const [m, tab] of [['rowsHTML(){', 'users'], ['guestRowsHTML(){', 'guests'], ['deptRowsHTML(){', 'depts'],
                        ['envRowsHTML(){', 'envs'], ['histRowsHTML(){', 'history'], ['autoRowsHTML(){', 'autos']]) {
  const m0 = grabMethod(m);
  ck(`the ${tab} rows come from view('${tab}'), not from the raw list`,
     m0.includes(`view('${tab}')`), m0.slice(0, 200));
}

/* ── sortRows ── */
const by = (rows, key, dir, get) => SA.sortRows(rows, key, dir, get).map(r => r.k);
ck('numbers sort numerically, not as text',
   by([{k: 10, n: 10}, {k: 9, n: 9}, {k: 100, n: 100}], 'n', 1, r => r.n).join(',') === '9,10,100',
   by([{k: 10, n: 10}, {k: 9, n: 9}, {k: 100, n: 100}], 'n', 1, r => r.n).join(','));
ck('...and reverse really reverses them',
   by([{k: 10, n: 10}, {k: 9, n: 9}, {k: 100, n: 100}], 'n', -1, r => r.n).join(',') === '100,10,9');
ck('text is compared with Hebrew collation, not by code point',
   /localeCompare\([^)]*,\s*'he'\)/.test(grabMethod('sortRows(rows,key,dir,get){')),
   grabMethod('sortRows(rows,key,dir,get){'));
ck('...so ת sorts after א and not before it',
   by([{k: 'ת', s: 'תמר'}, {k: 'א', s: 'אבי'}], 's', 1, r => r.s).join('') === 'את');
// a blank is nothing to read, so it belongs at the end whichever way the arrow points
const withBlanks = [{k: 'b', s: 'ב'}, {k: '-', s: ''}, {k: 'a', s: 'א'}, {k: 'n', s: null}];
ck('a blank sorts last ascending', by(withBlanks, 's', 1, r => r.s).slice(0, 2).join('') === 'ab',
   by(withBlanks, 's', 1, r => r.s).join(','));
ck('...and last descending too — reversing gives the other end of the DATA',
   by(withBlanks, 's', -1, r => r.s).slice(0, 2).join('') === 'ba',
   by(withBlanks, 's', -1, r => r.s).join(','));
ck('timestamps sort chronologically, not as strings',
   by([{k: 'late', d: '2026-10-15T08:00:00+00:00'}, {k: 'early', d: '2026-02-03T23:00:00+00:00'}], 'd', 1, r => r.d)
     .join(',') === 'early,late');
ck('a naive timestamp is read as UTC, the one place that rule lives',
   !isNaN(SA._ms('2026-10-15T08:22:02')) && SA._ms('2026-10-15T08:22:02') === SA._ms('2026-10-15T08:22:02Z'));
ck('sorting does not mutate the list it was handed', (() => {
  const rows = [{n: 3}, {n: 1}, {n: 2}];
  SA.sortRows(rows, 'n', 1);
  return rows.map(r => r.n).join(',') === '3,1,2';
})());
ck('importance sorts by urgency, not by where its Hebrew label falls in the alphabet',
   SA.AUTO_IMP_RANK.critical < SA.AUTO_IMP_RANK.high
   && SA.AUTO_IMP_RANK.high < SA.AUTO_IMP_RANK.normal
   && SA.AUTO_IMP_RANK.normal < SA.AUTO_IMP_RANK.low);

/* ── sortBy toggles, and a header answers to the keyboard ── */
SA.repaint = () => {};          // no DOM here; the toggle is the subject
SA.tab = 'users';
SA.sort = {};
SA.sortBy('name');
ck('the first click on a column sorts it ascending',
   SA.sortOf('users').key === 'name' && SA.sortOf('users').dir === 1, JSON.stringify(SA.sortOf('users')));
SA.sortBy('name');
ck('...and the second reverses it', SA.sortOf('users').dir === -1);
SA.sortBy('email');
ck('...and a different column starts over, ascending',
   SA.sortOf('users').key === 'email' && SA.sortOf('users').dir === 1);
ck('each tab remembers its own sort', (() => {
  SA.tab = 'depts'; SA.sortBy('user_count');
  return SA.sortOf('users').key === 'email' && SA.sortOf('depts').key === 'user_count';
})());
SA.tab = 'users';
SA.sort = {};

/* ── the header markup: a real button inside a cell that is still a cell ──
   The sort control used to be the <th> itself, wearing role="button",
   tabindex="0" and a hand-rolled onkeydown. An explicit ARIA role REPLACES the
   implicit one, so the cell stopped being a columnheader — and aria-sort is
   only honoured on a columnheader. The sort state syncHeads() so carefully
   maintains was therefore announced to nobody, and every cell underneath lost
   its header association into the bargain.

   It is now a native <button class="sa-th-btn"> INSIDE the th. The th keeps its
   class, its data-k and its aria-sort; the button takes the title and the
   click. A native button already fires click on Enter and on Space, so the
   keyboard handler went away with the role that made it necessary. */
/* Scoped to the <th>: role="button" on a <span> elsewhere in the page is
   right, because a span has no implicit role to destroy. A th has one. */
ck('no column header claims to be a button — that is what stopped it being a columnheader',
   !/<th[^>]*role=/.test(src) && !/role=/.test(grabMethod('headHTML(tab){')),
   (/<th[^>]*role="button"[^>]*>/.exec(src) || [''])[0]);
ck('...and the hand-rolled key handler went with it, because a real button needs none',
   typeof SA.thKey === 'undefined' && !/thKey/.test(src), 'thKey is still in the page');

for (const tab of TABS) {
  const head = SA.headHTML(tab);
  const labelled = SA.COLS[tab].filter(c => c.key && c.label);
  const ths = head.match(/<th\b/g) || [];
  ck(`the ${tab} header draws one cell per column`, ths.length === SA.COLS[tab].length,
     `${ths.length} <th> for ${SA.COLS[tab].length} columns`);
  ck(`...every sortable ${tab} header holds exactly one real button`,
     (head.match(/<button type="button" class="sa-th-btn"/g) || []).length === labelled.length, head);
  ck(`...which is operable from the keyboard by BEING a button, not by a tabindex`,
     !/tabindex=/.test(head), head);
  ck(`...the ${tab} th keeps aria-sort, which is only honoured on a columnheader`,
     (head.match(/<th class="sa-th"[^>]*aria-sort="none"/g) || []).length === labelled.length, head);
  ck(`...and data-k, which is how syncHeads finds the cell again`,
     (head.match(/data-k="/g) || []).length === labelled.length, head);
  ck(`...the sort is on the button, never on the cell`,
     (head.match(/onclick="SysAdmin\.sortBy\(/g) || []).length === labelled.length
     && !/<th[^>]*onclick/.test(head), head);
  ck(`...and the caret rides inside the button, with the label it belongs to`,
     (head.match(/sa-caret"><\/i><\/button>/g) || []).length === labelled.length, head);
  // a column with no label carries no data (the ⋮ menu, the swatch, the actions)
  const unlabelled = SA.COLS[tab].filter(c => !c.key || !c.label);
  ck(`...and the ${unlabelled.length} column(s) with nothing to sort are not offered as sortable`,
     (head.match(/class="sa-th"/g) || []).length === labelled.length);
}
ck('syncHeads still addresses the th, which is the element carrying aria-sort',
   /#sa-body \.sa-th/.test(grabMethod('syncHeads(){')), grabMethod('syncHeads(){'));
ck('syncHeads marks the live column and tells a screen reader which way',
   /aria-sort[^)]*ascending[^)]*descending/.test(grabMethod('syncHeads(){')), grabMethod('syncHeads(){'));

/* ── the colspan of the empty row is the real column count ──
   Rendered, not read off the source: the hardcoded 7 on the users tab survived
   a column being added precisely because nothing compared it to the table. */
const ROWS = {
  users: () => { SA.users = [{id: 2, name: 'דנה', email: 'd@x.co', role: 'member', department_name: 'הנדסה',
                              created_at: '2026-01-02T08:00:00+00:00', last_login: '2026-10-01T08:00:00+00:00',
                              is_active: true}]; return SA.rowsHTML(); },
  guests: () => { SA.guests = {enabled: true, configured: true, guests: [{id: 3, name: 'יעל', email: 'y@p.co',
                               invite_state: 'accepted', department_name: '—'}]}; return SA.guestRowsHTML(); },
  depts: () => { st.depts = [{id: 1, name: 'הנדסה', color: '#0073ea', user_count: 4, active_user_count: 2}];
                 return SA.deptRowsHTML(); },
  envs: () => { SA.envs = [{id: 1, name: 'ראשית', board_count: 3, is_primary: true}]; return SA.envRowsHTML(); },
  history: () => { SA.history = [{user_id: 2, user_name: 'דנה', logged_in_at: '2026-10-01T08:00:00+00:00',
                                  ip: '1.2.3.4', user_agent: 'Chrome'}]; return SA.histRowsHTML(); },
  autos: () => { SA.auto = {rows: [{board_id: 1, board_name: 'לוח', display_name: 'כלל', sentence: 'כש«א» אז «ב»',
                                    status: 'active', importance: 'high', owner_name: 'דנה',
                                    last_run_at: '2026-10-01T08:00:00+00:00', success_rate: 98, fail_count: 0}],
                            totals: {total: 1}, quota: {}}; return SA.autoRowsHTML(); },
};
for (const tab of TABS) {
  SA.tab = tab; SA.query = {};
  const row = ROWS[tab]();
  const tds = (row.match(/<td\b/g) || []).length;
  ck(`a ${tab} row has one cell per declared column`, tds === SA.COLS[tab].length,
     `${tds} <td> for ${SA.COLS[tab].length} columns`);
  const span = /colspan="(\d+)"/.exec(SA.emptyRow(tab, 'ריק'));
  ck(`...and the "nothing here" cell spans the whole ${tab} table`,
     !!span && +span[1] === SA.COLS[tab].length, span ? span[1] : 'no colspan');
}
ck('an empty search says it was the search, not that the directory is empty', (() => {
  SA.tab = 'users'; SA.query = {users: 'אין כזה'};
  const e = SA.emptyRow('users', 'אין משתמשים');
  SA.query = {};
  return e.includes('אין כזה') && !e.includes('אין משתמשים');
})());

/* ── the search box: it filters as you type, with nothing to press ── */
const bar = grabMethod('barHTML(tab,actions,placeholder){');
ck('the box filters on input', /oninput="SysAdmin\.setQ\(this\.value\)"/.test(bar), bar);
ck('...and there is no Enter to press, nor a button gating it',
   !/onkeydown|onkeyup|onchange|onsubmit/.test(bar) && !/onclick="SysAdmin\.setQ/.test(bar), bar);
ck('...it is labelled for a screen reader', /aria-label="חיפוש/.test(bar), bar);
ck('...and typing goes straight to a repaint',
   /setQ\(v\)\{[^}]*this\.query\[this\.tab\]=v;[^}]*this\.repaint\(\)/.test(BODY.replace(/\n/g, '')),
   /setQ\(v\)\{.*/.exec(BODY)[0]);

SA.tab = 'users'; SA.sort = {}; SA.query = {};
SA.users = [
  {id: 1, name: 'משה כהן', email: 'moshe@hod.gov.il', role: 'admin', department_name: 'הנדסה', is_active: true},
  {id: 2, name: 'דנה לוי', email: 'dana@hod.gov.il', role: 'member', department_name: 'חינוך', is_active: true},
  {id: 3, name: 'Yael Partner', email: 'yael@partner.co.il', role: 'guest', department_name: null, is_active: false},
];
const found = q => { SA.query = {users: q}; const r = SA.view('users').map(u => u.id); SA.query = {}; return r; };
ck('the search finds a name', found('דנה').join(',') === '2');
ck('...a mail address', found('partner.co.il').join(',') === '3');
ck('...a department', found('חינוך').join(',') === '2');
ck('...the role as it is STORED, in English', found('admin').join(',') === '1', found('admin').join(','));
ck('...and the role as it is SHOWN, in Hebrew', found('מנהל מערכת').join(',') === '1', found('מנהל מערכת').join(','));
ck('...case does not matter', found('YAEL').join(',') === '3', found('YAEL').join(','));
ck('a deactivated person is still findable — the directory includes them',
   found('Yael').join(',') === '3');
ck('a timestamp column is not searched — a bare "10" must not match every login',
   SA.COLS.users.find(c => c.key === 'last_login').find === false
   && SA.COLS.users.find(c => c.key === 'created_at').find === false);
ck('the filter and the sort compose', (() => {
  SA.query = {users: 'hod.gov.il'}; SA.sort = {users: {key: 'name', dir: -1}};
  const r = SA.view('users').map(u => u.id).join(',');
  SA.query = {}; SA.sort = {};
  return r === '1,2';                      // משה before דנה, descending Hebrew
})(), (() => { SA.query = {users: 'hod.gov.il'}; SA.sort = {users: {key: 'name', dir: -1}};
               const r = SA.view('users').map(u => u.name).join(','); SA.query = {}; SA.sort = {}; return r; })());

/* ── the count: one number normally, "50/60" while something is filtering ── */
const plain = SA.countBox(60, 60, 'משתמשים');
const narrow = SA.countBox(50, 60, 'משתמשים');
ck('unfiltered there is only the one number',
   plain.includes('>60<') && !plain.includes('sa-tot') && !/\/\s*60/.test(plain), plain);
ck('...and no filter icon', !plain.includes('fa-filter') && !/class="sa-count on/.test(plain), plain);
ck('filtered it reads 50/60', narrow.includes('>50<') && narrow.includes('/60'), narrow);
ck('...and says, unmistakably, that something is narrowing it',
   narrow.includes('fa-filter') && narrow.includes('sa-count on'), narrow);
ck('the ratio is isolated so RTL cannot reorder it into 60/50',
   /\.sa-count \.sa-ratio\{[^}]*direction:ltr[^}]*unicode-bidi:isolate/.test(src));
SA.tab = 'users'; SA.query = {users: 'hod.gov.il'};
ck('the count on screen counts what the table is showing',
   SA.countHTML('users').includes('>2<') && SA.countHTML('users').includes('/3'), SA.countHTML('users'));
SA.query = {};
ck('the automations count takes its total from the server, which did the filtering',
   /totals[^;]*total/.test(grabMethod('countHTML(tab){')), grabMethod('countHTML(tab){'));
ck('every tab has a noun to count', TABS.every(t => !!SA.NOUN[t]), JSON.stringify(SA.NOUN));
/* The server hands back the most recent hundred logins, not all of them, so a
   bare "87 התחברויות" over that list is a claim nobody made — and an admin
   who read it as the total concluded that people had stopped signing in. */
ck('the history tab counts RECENT logins, because that is all the server sent',
   SA.NOUN.history === 'התחברויות אחרונות', SA.NOUN.history);
ck('...and the count box on that tab says so', SA.countBox(87, 87, SA.NOUN.history).includes('אחרונות'));

/* ── repaint touches the rows and the count. Not the body. ──
   This is the focus rule: the search input lives in #sa-body, so rebuilding
   #sa-body between two keystrokes removes the element being typed into. */
const repaint = grabMethod('repaint(){');
ck('repaint paints the rows', /getElementById\('sa-rows'\)/.test(repaint), repaint);
ck('...and the count', /getElementById\('sa-count'\)/.test(repaint), repaint);
ck('...and NEVER rebuilds #sa-body, which is where the search input lives',
   !/sa-body/.test(repaint), repaint);
ck('...and re-marks the headers in place rather than re-rendering them',
   /syncHeads\(\)/.test(repaint) && !/headHTML/.test(repaint), repaint);
ck('a row-level edit repaints rather than rebuilding, so the filter survives it',
   /this\.repaint\(\)/.test(grabMethod('async _patch(uid,body,okMsg){')), grabMethod('async _patch(uid,body,okMsg){'));

/* ── the CSV ── */
lastBlob = null; clicked = null;
SA.exportCSV('x.csv', ['שם', 'הערה'], [['דנה', 'אמרה "שלום", ואז יצאה'], ['יעל', 'a,b']]);
const csv = lastBlob && lastBlob.text;
ck('the file is written at all', !!csv, String(csv));
ck('it opens in Excel in Hebrew — the UTF-8 BOM is there', csv.charCodeAt(0) === 0xFEFF,
   'first char is ' + csv.charCodeAt(0).toString(16));
ck('rows end with CRLF, which is what Excel expects', csv.includes('\r\n') && !/[^\r]\n/.test(csv),
   JSON.stringify(csv));
ck('...including the last one, so appending does not glue two rows together', csv.endsWith('\r\n'));
ck('an embedded quote is doubled rather than closing the field',
   csv.includes('"אמרה ""שלום"", ואז יצאה"'), JSON.stringify(csv));
ck('every field is quoted, so a comma inside one cannot split the row',
   csv.split('\r\n')[2] === '"יעל","a,b"', JSON.stringify(csv.split('\r\n')[2]));
ck('the headers are the first line', csv.indexOf('"שם","הערה"') === 1);
ck('the download is named, not left to the browser', clicked && clicked.download === 'x.csv',
   JSON.stringify(clicked));
ck('the blob is released, so a session of exports does not pin every file',
   /revokeObjectURL/.test(grabMethod('exportCSV(filename,headers,rows){')));
ck('the file is named with the admin\'s own date, not UTC\'s',
   /^\d{4}-\d{2}-\d{2}$/.test(SA.today()) && /getFullYear|getMonth|getDate/.test(grabMethod('today(){'))
   && !/getUTC/.test(grabMethod('today(){')), SA.today());

/* ── a name is not a program ──
   A field opening with = + - or @ is a FORMULA to Excel, quotes and all. These
   are names and notes typed by users, so a person who calls themselves
   =HYPERLINK("http://…") is writing code that runs on the machine of the admin
   who exports the directory. The leading apostrophe is Excel's own "this is
   text" marker and is consumed on open, so the cell still reads as what was
   typed. Tab, CR and LF are stripped from the front before the test, because
   Excel ignores them when it decides that a cell is a formula. */
lastBlob = null;
SA.exportCSV('f.csv', ['h'], [['=HYPERLINK("http://evil","לחצי כאן")'], ['+1'], ['-2'], ['@me'],
                              ['\t=cmd|calc'], ['a@b.co.il'], ['דנה לוי'], ['2026-10-28'], ['—'],
                              ['+cmd|calc'], ['-1+cmd|calc']]);
const F = lastBlob.text.split('\r\n');
ck('a formula is neutralised with Excel\'s own text marker', F[1].startsWith('"\'=HYPERLINK'), F[1]);
/* A leading + or - in front of a NUMBER is a number, and the marker would turn
   a figure into a string Excel can no longer sum — the same exemption the
   server's _csv_safe makes, so the two exports agree about what is dangerous. */
ck('a signed number is left alone so it still sums in Excel', F[2] === '"+1"', F[2]);
ck('...and so is a negative one', F[3] === '"-2"', F[3]);
ck('...while a leading + in front of anything else is still marked',
   F[10] === '"\'+cmd|calc"', F[10]);
ck('...and so is a leading - that is not a number', F[11] === '"\'-1+cmd|calc"', F[11]);
ck('...a leading @', F[4] === '"\'@me"', F[4]);
ck('...and one hidden behind a tab, which Excel ignores when it decides',
   F[5] === '"\'\t=cmd|calc"', JSON.stringify(F[5]));
ck('a mail address is NOT a formula — the @ has to be leading', F[6] === '"a@b.co.il"', F[6]);
ck('...nor is an ordinary name', F[7] === '"דנה לוי"', F[7]);
ck('...nor a date', F[8] === '"2026-10-28"', F[8]);
/* The em dash this screen writes into an empty cell is NOT a formula character
   and needs no marker; the ASCII hyphen a person can type into a name is. */
ck('the — written into every empty cell is left exactly as it is', F[9] === '"—"', F[9]);
lastBlob = null;
SA.exportCSV('d.csv', ['h'], [['-1 מדרגה']]);
ck('...while a typed hyphen at the front still gets one',
   lastBlob.text.split('\r\n')[1] === '"\'-1 מדרגה"', JSON.stringify(lastBlob.text.split('\r\n')[1]));
// the guard runs BEFORE the quoting, so an injected quote cannot escape either
lastBlob = null;
SA.exportCSV('g.csv', ['h'], [['=A1&"x"']]);
const G = lastBlob.text.split('\r\n')[1];
ck('the apostrophe goes on first and the doubling still happens after it',
   G === '"\'=A1&""x"""', JSON.stringify(G));
lastBlob = null;
SA.exportCSV('h.csv', ['שם'], [['דנה, לוי']]);
ck('and the BOM, the CRLF, the comma and the Hebrew all survived the guard',
   lastBlob.text.charCodeAt(0) === 0xFEFF && lastBlob.text.endsWith('\r\n')
   && lastBlob.text.includes('"דנה, לוי"'), JSON.stringify(lastBlob.text));

const exportTab = grabMethod('exportTab(){');
ck('the automations tab hands its export to the server, which did the filtering',
   /tab==='autos'[\s\S]*exportAutos\(\)/.test(exportTab), exportTab);
ck('every other tab exports exactly the rows on screen', /this\.view\(tab\)/.test(exportTab), exportTab);
ck('...and exports the plain sentence, never the markup',
   /c\.text\(r\)/.test(exportTab) && !/RowsHTML|innerHTML/.test(exportTab), exportTab);
for (const tab of TABS) {
  ck(`the ${tab} tab offers an export`, !!(SA.FILE[tab] || tab === 'autos'), tab);
}
lastBlob = null; clicked = null;
SA.tab = 'users'; SA.query = {}; SA.sort = {};
SA.exportTab();
const users = lastBlob.text.split('\r\n');
ck('the users export carries the new invitation-date column',
   users[0].includes('מועד הזמנה למערכת'), users[0]);
ck('...one column per labelled users column, no more',
   users[0].split('","').length === SA.COLS.users.filter(c => c.label && c.text).length, users[0]);
ck('...and one line per person on screen, plus the header', users.length === 1 + SA.users.length + 1,
   JSON.stringify(users));
ck('...with the role in Hebrew, as the column reads it', users[1].includes('מנהל מערכת'), users[1]);
lastBlob = null;
SA.query = {users: 'hod.gov.il'};
SA.exportTab();
ck('an export of a filtered table carries the filtered rows and nothing else',
   lastBlob.text.split('\r\n').filter(Boolean).length === 3, JSON.stringify(lastBlob.text));
SA.query = {};

/* ── the depts tab says who actually showed up ── */
ck('the depts tab shows the assigned count and the active one as two columns',
   SA.COLS.depts.some(c => c.key === 'user_count') && SA.COLS.depts.some(c => c.key === 'active_user_count'));
ck('...and a unit with nobody in it shows a dash, not "0 מתוך 0"',
   SA.COLS.depts.find(c => c.key === 'active_user_count').text({user_count: 0, active_user_count: 0}) === '—');
ck('...while a populated one shows the share',
   SA.COLS.depts.find(c => c.key === 'active_user_count').text({user_count: 4, active_user_count: 2}) === '2 מתוך 4');
ck('the screen says what "פעיל" means here, in words', /30 הימים האחרונים/.test(grabMethod('async renderDepts(){')));
ck('the active column sorts on the number, not on the sentence "2 מתוך 4"',
   SA.COLS.depts.find(c => c.key === 'active_user_count').val({user_count: 4, active_user_count: 2}) === 2);
ck('the users tab carries the invitation date, formatted through the one formatter',
   SA.COLS.users.some(c => c.key === 'created_at')
   && /fdtx\(u\.created_at\)/.test(BODY), 'created_at column missing');
ck('...and an account with no recorded date shows a dash rather than "Invalid Date"',
   SA.COLS.users.find(c => c.key === 'created_at').text({}) === '—');

/* ── the guest state is decided once, as text, so it can be sorted and exported ── */
ck('the guest state column sorts on the sentence, not on the name of a CSS class',
   SA.COLS.guests.find(c => c.key === 'state').val({is_active: false}) === 'גישה בוטלה',
   SA.COLS.guests.find(c => c.key === 'state').val({is_active: false}));
ck('...and the badge draws the same sentence',
   SA.guestState({is_active: false}).includes('גישה בוטלה'));

/* ── the new styling ── */
/* The toolbar's own rules, from the sortable header down to .sa-sub. The
   narrow-screen rule is deliberately NOT here: it lives in the one canonical
   @media (max-width:820px) block, because a second @media at the same
   breakpoint is indistinguishable from the first to anything reading the
   stylesheet and the mobile tests duly read the wrong one. */
const CSS = src.slice(src.indexOf('/* A sortable header.'),
                      src.indexOf('.sa-sub{') + 80);
ck('the new styling was found', CSS.length > 400 && CSS.includes('.sa-th{'), String(CSS.length));
ck('no purple anywhere in it',
   !/purple|violet|indigo|#8b5cf6|#a855f7|#6366f1|#7c3aed|#9333ea/i.test(CSS), CSS);
ck('...and no colour outside the monday palette is hardcoded',
   !/#[0-9a-f]{3,8}/i.test(CSS.replace(/var\(--[^)]*\)/g, '')), (CSS.match(/#[0-9a-f]{3,8}/ig) || []).join(','));
ck('RTL-first: the search icon is placed with a logical property',
   /inset-inline-start/.test(CSS) && /padding-inline-start/.test(CSS), CSS);
ck('...and nothing in it says left or right',
   !/(^|[;{\s])(left|right)\s*:/m.test(CSS), (CSS.match(/.{0,20}(left|right)\s*:.{0,20}/g) || []).join(' | '));
ck('a header reached with the keyboard is visibly focused',
   /\.sa-th-btn:focus-visible\{[^}]*outline/.test(CSS), CSS);
/* The padding moved from the cell to the button so the control fills the cell
   and the whole header is the target — a button that only covered its text
   left a dead strip along the edge of every column. */
ck('...and the control fills the cell rather than sitting in a corner of it',
   /\.sa-th\{padding:0\}/.test(CSS) && /\.sa-th-btn\{[^}]*width:100%/.test(CSS)
   && /\.sa-th-btn\{[^}]*padding:8px 10px/.test(CSS), CSS);
ck('...wearing none of the chrome a button brings, so it still reads as a th',
   /\.sa-th-btn\{[^}]*font:inherit/.test(CSS) && /\.sa-th-btn\{[^}]*background:none/.test(CSS)
   && /\.sa-th-btn\{[^}]*border:0/.test(CSS), CSS);
ck('...and aligned to the start edge, not to the left one',
   /\.sa-th-btn\{[^}]*text-align:start/.test(CSS), CSS);
ck('the caret is always in the markup and merely hidden, so the header cannot jump sideways',
   /\.sa-caret\{[^}]*visibility:hidden/.test(CSS) && /\.sa-th\.on \.sa-caret\{[^}]*visibility:visible/.test(CSS), CSS);
ck('the toolbar wraps rather than squeezing the search box', /\.sa-bar\{[^}]*flex-wrap:wrap/.test(CSS), CSS);
// and the phone rule belongs to the ONE 820px block — a duplicate at the same
// breakpoint sent the mobile tests reading a block with nothing in it
const MOBILE = src.slice(src.indexOf('@media (max-width:820px){'),
                         src.indexOf('@media (max-width:820px) and (display-mode:standalone)'));
ck('below the breakpoint the search box takes the whole line, from the one 820px block',
   /\.sa-search\{flex:1 1 100%\}/.test(MOBILE), MOBILE.slice(0, 400));
ck('...and there is exactly one @media at that breakpoint',
   (src.match(/@media \(max-width:820px\)\{/g) || []).length === 1,
   String((src.match(/@media \(max-width:820px\)\{/g) || []).length));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
