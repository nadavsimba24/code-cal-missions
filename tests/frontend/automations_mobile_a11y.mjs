/* סעיף 15 — שימוש בנייד ונגישות.

   Two things are being checked and they pull in opposite directions. On a
   phone the module has to be READABLE — the rules, who owns them, what state
   they are in, what ran and what broke — and it must not be WRITABLE, because
   a rule is a sentence with eight blanks and filling those on a phone is how
   somebody switches on a thing they did not mean. The one write that stays is
   the one somebody reaches for a phone to do: stopping a rule that is doing
   damage, and that one asks first.

   And underneath, the things that decide whether any of it is usable at all:
   a name for everything a screen reader lands on, a state that is never only
   a colour, and a sentence that reads as a sentence rather than as a row of
   highlighted fragments. */
import fs from 'fs';
const SRC = fs.readFileSync(new URL('../../frontend/index.html', import.meta.url), 'utf8');

let pass = 0, fail = 0;
const ck = (what, ok) => { ok ? pass++ : fail++;
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${what}`); };

function grabConst(name) {
  const i = SRC.indexOf(`const ${name} = {`);
  const j = SRC.indexOf('\n};', i);
  if (i < 0) throw new Error('not found: ' + name);
  return SRC.slice(i, j + 3);
}

const st = { board: { id: 1, name: 'לוח תשתיות', groups: [], my_role: 'admin' }, boards: [] };
const stored = {};
const localStorage = { getItem: k => stored[k] || null, setItem: (k, v) => { stored[k] = String(v); } };
const esc = x => String(x == null ? '' : x).replace(/&/g, '&amp;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function build(mobile) {
  const A = new Function('st', 'esc', 'toast', 'BoardLog', 'fdatetime', 'fdatetimeY',
    'avatarInner', 'boardStatusList', 'boardPriorityList', 'customColumns', 'meId',
    'api', 'openCellPop', 'closeCellPops', 'askConfirm', 'showModal', 'closeModals',
    'document', 'renderView', 'localStorage', 'isMobile',
    grabConst('Automations') + ' return Automations;')(
    st, esc, () => {}, { ago: () => 'עכשיו', goto() {} }, () => '01/01/2026',
    () => '01/01/2026', () => '', () => [], () => [],
    () => [{ id: 'col_a', type: 'text', title: 'אזור' }],
    () => 1, async () => ({}), () => {}, () => {}, () => {}, () => {}, () => {},
    { getElementById: () => null }, () => {}, localStorage, () => mobile);
  A.data = { automations: [], can_manage: true, can_export: true, people: [] };
  A.runCounts = {}; A.picked = new Set();
  return A;
}

const RULE = {
  id: 11, status: 'active', is_active: true, trigger: 'status_changes_to',
  action: 'notify_person', display_name: 'סגירת קריאה', name: 'סגירת קריאה',
  sentence: 'כאשר הסטטוס משתנה ל«בוצע», שלח התראה ל«דנה»',
  description: '', importance: 'critical', run_order: 1,
  owner_id: 5, owner_name: 'דנה', owner_is_creator: false, needs_owner: false,
  created_by: 4, created_by_name: 'יואב', updated_by_name: '',
  last_outcome: 'ran', run_count: 4, fail_count: 1, skip_count: 2,
  success_rate: 80, needs_attention: false, missing_fields: [],
};

/* ── מה אפשר בנייד ───────────────────────────────────────────────────── */
{
  const M = build(true), D = build(false);
  M.data.automations = [RULE]; D.data.automations = [RULE];

  const mt = M.tabsHTML(), dt = D.tabsHTML();
  ck('on a phone there is no "create" tab', !mt.includes(">יצירה<") && !mt.includes('יצירה'));
  ck('...and on a desktop there is', dt.includes('יצירה'));
  ck('the phone still gets the list, the history and the audit',
     mt.includes('ניהול') && mt.includes('היסטוריית הפעלות') && mt.includes('Audit'));

  M.tab = 'create';
  const mc = M.createHTML();
  ck('asking for the builder on a phone explains instead of half-working',
     mc.includes('בדסקטופ') && !mc.includes('Automations.pick('));

  M.tab = 'manage';
  const row = M.rowHTML ? M.rowHTML(RULE, true) : M.ruleRow(RULE, true);
  ck('a rule still shows its sentence on a phone', row.includes('בוצע'));
  ck('...its owner', row.includes('דנה'));
  ck('...and its state', row.includes('פעילה'));
  ck('the phone offers the pause', row.includes('Automations.toggle(11,false)'));
  ck('...and nothing that edits', !row.includes('Automations.edit(')
     && !row.includes('Automations.del('));
  const drow = D.ruleRow(RULE, true);
  ck('the desktop keeps the full menu', drow.includes('Automations.menu('));
  ck('...which the phone does not', !row.includes('Automations.menu('));
}

/* ── השהיה מבקשת אישור ──────────────────────────────────────────────── */
{
  const asked = [];
  const A = new Function('st', 'esc', 'toast', 'BoardLog', 'fdatetime', 'fdatetimeY',
    'avatarInner', 'boardStatusList', 'boardPriorityList', 'customColumns', 'meId',
    'api', 'openCellPop', 'closeCellPops', 'askConfirm', 'showModal', 'closeModals',
    'document', 'renderView', 'localStorage', 'isMobile',
    grabConst('Automations') + ' return Automations;')(
    st, esc, () => {}, { ago: () => 'עכשיו', goto() {} }, () => '', () => '',
    () => '', () => [], () => [], () => [], () => 1,
    async (p, o) => { asked.push(p + ' ' + ((o || {}).method || 'GET')); return {}; },
    () => {}, () => {}, (msg, yes, opts) => { asked.push('CONFIRM ' + ((opts || {}).title || '')); },
    () => {}, () => {}, { getElementById: () => null }, () => {}, localStorage,
    () => true);
  A.data = { automations: [RULE], can_manage: true, people: [] };
  A.load = async () => {}; A.render = () => {};
  A.toggle(11, false);
  ck('pausing from a phone asks first', asked.some(x => x.startsWith('CONFIRM')));
  ck('...and sends nothing until it is answered',
     !asked.some(x => x.includes('PATCH')));
}

/* ── נגישות ─────────────────────────────────────────────────────────── */
{
  const D = build(false);
  D.data.automations = [RULE];
  const tabs = D.tabsHTML();
  ck('the tabs are a tablist', tabs.includes('role="tablist"') && tabs.includes('role="tab"'));
  ck('...and say which one is on', tabs.includes('aria-selected="true"'));

  const row = D.ruleRow(RULE, true);
  ck('the sentence is also there as one plain readable line',
     row.includes('aria-label="כאשר הסטטוס משתנה ל') && row.includes('שלח התראה ל'));
  ck('...without the quoting marks a screen reader would spell out',
     !/aria-label="[^"]*«/.test(row));
  ck('every icon-only control has a name',
     !/<button[^>]*class="am-ico"(?![^>]*aria-label)/.test(row));
  ck('the state is words and an icon, never only a colour',
     row.includes('פעילה') && row.includes('fa-'));
  ck('the state carries its meaning for a reader too', row.includes('aria-label="סטטוס'));

  D.tab = 'history'; D.runsLoading = false; D.runOutcome = ''; D.runStatus = '';
  D.runQ = ''; D.runAuto = 0; D.batch = null; D.chain = null; D.tl = null;
  D.runStatuses = []; D.incidents = [];
  D.runCounts = { total: 1, ran: 1, skipped: 0, failed: 0, retried: 0 };
  D.runs = [{ id: 1, outcome: 'failed', status: 'failed_permanent',
              status_he: 'נכשלה - קבוע', sentence: 'כאשר נוצר פריט, שנה עדיפות',
              task_id: 5, task_title: 'מקור', reason: 'אין פריט מקושר', depth: 0,
              event_type: 'item_created', source: 'item', batch_id: '', chain_id: 'c1',
              event_id: 'e1', version: 1, is_retry: false, retried_at: null,
              attempt: 1, error_code: 'refused', ref: 'run:1', result: {},
              created_at: '2026-10-25T09:00:00', can_retry: true }];
  const hist = D.historyHTML();
  ck('a failure in the log says so in words, not in red alone',
     hist.includes('נכשלה - קבוע') && hist.includes('אין פריט מקושר'));
  ck('the outcome is announced, not merely coloured', hist.includes('role="status"'));
  ck('the filter chips say whether they are on', hist.includes('aria-pressed="true"'));
  ck('the search box has a name', hist.includes('aria-label="חיפוש'));
}

/* ── RTL ועברית/אנגלית מעורבות ──────────────────────────────────────── */
{
  const D = build(false);
  const mixed = Object.assign({}, RULE, {
    display_name: 'Sync to GIS',
    sentence: 'כאשר הסטטוס משתנה ל«Done», שלח התראה ל«Dana R.»',
  });
  D.data.automations = [mixed];
  const row = D.ruleRow(mixed, true);
  ck('a Latin value inside a Hebrew sentence is isolated, so the line does not flip',
     row.includes('<bdi>') || row.includes('dir="auto"'));
  ck('...and the rule name is isolated too',
     /(<bdi>|dir="auto")[^<]*Sync to GIS|Sync to GIS[^<]*<\/bdi>/.test(row)
     || row.includes('<bdi>Sync to GIS</bdi>'));
}

/* ── חלופה לכל גרירה ────────────────────────────────────────────────── */
{
  const D = build(false);
  D.ord = { can: true, importance: false,
            rows: [{ id: 1, name: 'א', run_order: 1, status: 'active' },
                   { id: 2, name: 'Sync to GIS', run_order: 2, status: 'active' }] };
  const ord = D.orderHTML();
  ck('ordering is done with buttons', ord.includes('Automations.orderMove('));
  ck('...and never by dragging', !ord.includes('draggable') && !ord.includes('sortable'));
  ck('the move buttons are named for a reader',
     ord.includes('aria-label="העבר למעלה') || ord.includes('aria-label="העבר למטה'));
  const body = SRC.slice(SRC.indexOf('const Automations = {'),
                         SRC.indexOf('\n};', SRC.indexOf('const Automations = {')));
  ck('no screen in the module relies on a drag at all',
     !body.includes('sortableOn(') && !body.includes('ondragstart'));
}

/* ── מקלדת ──────────────────────────────────────────────────────────── */
{
  /* Everything that acts is a <button> or an <input>, which is what makes the
     screen reachable at all — a <div onclick> is invisible to a keyboard.
     Checked over the module's source rather than one rendered row, because
     the one place somebody writes a clickable div is the place nobody tests. */
  const i = SRC.indexOf('const Automations = {');
  const body = SRC.slice(i, SRC.indexOf('\n};', i));
  const acting = (body.match(/<(div|span)[^>]*\sonclick="[^"]*"/g) || [])
    .filter(x => !/onclick="event\.stopPropagation\(\)"/.test(x))   // a wrapper, not a control
    .filter(x => !/class="modal-back"/.test(x))                      // backdrop: Escape does it
    .filter(x => !/role="button"/.test(x));
  ck('nothing in the module acts on a click without being focusable',
     acting.length === 0, acting.slice(0, 2));
  ck('the one backdrop has a keyboard way out',
     SRC.includes('Automations.closeTimeline(); return;'));

  /* and the way out: Escape closed nothing before — a dialog reachable by
     keyboard and dismissible only by mouse is a trap */
  const esc = SRC.slice(SRC.indexOf("document.addEventListener('keydown',e=>{"),
                        SRC.indexOf('function closeModals()'));
  ck('Escape closes an open dialog', esc.includes('closeModals()'));
  ck('...and leaves a field that has its own Escape alone',
     esc.includes("tag==='input'") && esc.includes('isContentEditable'));
  ck('...and closes a confirmation before the screen under it',
     esc.indexOf('_confirmCancel') < esc.indexOf('closeModals()'));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
