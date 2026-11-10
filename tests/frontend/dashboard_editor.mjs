/* The widget editor, drawn headless out of index.html.
 *
 * It exists because of one report — "אני לא רואה את האופציה לבחור עמודה" —
 * and the cause was not a missing picker. The default calculation is a
 * count, a count needs no column (R03: "ספירת רשומות אינה מושפעת מריק
 * בעמודה"), so the picker is genuinely absent until somebody chooses a sum
 * or an average. Absent and unexplained reads as broken, which is what this
 * now pins: the picker appears when it should, and when it does not there is
 * a sentence saying why.
 *
 * The other two emptinesses are here for the same reason — a dashboard with
 * no source boards, and a board with no numeric column.
 *
 * Driven by tests/test_dashboard_editor.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const esc = s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const from = src.indexOf('Dash.Editor = {');
const code = src.slice(from, src.indexOf('\n};', from) + 3);

let html = '';
const stub = () => {};
const Dash = {fmt: m => String(m.result), chartBody: () => '<chart/>',
              listBody: () => '<list/>', _onBoard: false,
              onBoard(){ return this._onBoard; }};
new Function('esc','Dash','document','setHTML','showModal','closeModals','toast','api','st',
  code + '\nreturn 0;')(
  esc, Dash, {getElementById: id => (id === 'dw-body' ? {} : null)},
  (_el, h) => { html = h; }, stub, stub, stub, stub, {});
const E = Dash.Editor;

let pass = 0, fail = 0;
const ck = (n, c, x='') => { c ? (pass++, console.log('  OK   ' + n))
                               : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

const BOARD = {name:'הלוח שלי', cols:[{id:'c1', title:'H20 פתיחת שנה', type:'number'}], dates:[]};
function draw(calc, {boards, sources, onBoard} = {}){
  Dash._onBoard = !!onBoard;
  Dash.d = {id:1, config_version:1, can_edit:true,
            sources: sources === undefined ? [{board_id:7, groups:null}] : sources};
  E.boards = boards === undefined ? {7: BOARD} : boards;
  E.draft = E.blank();
  E.draft.metrics[0].calc = calc;
  if(calc !== 'count') E.draft.metrics[0].field = 'amount';
  html = '';
  E.paint();
  return html;
}

// ── the report: a count has no column picker, and must say so ──
const counting = draw('count');
ck('a count shows no column picker', !counting.includes('בחר עמודה'));
ck('…and says why, rather than leaving a hole',
   counting.includes('ספירה סופרת רשומות ואינה זקוקה לעמודה'));
ck('…and says what to choose to get one',
   counting.includes('בחרי חישוב אחר'));

// ── and the two that do ──
for(const calc of ['sum','avg']){
  const h = draw(calc);
  ck(`a ${calc} asks for a column`, h.includes('בחר עמודה'));
  ck(`…and offers the board's own numeric column`, h.includes('H20 פתיחת שנה'));
  ck(`…naming the board it is on`, h.includes('הלוח שלי'));
  ck(`…and says the mapping has to be approved`,
     h.includes('יש לאשר את המיפוי'));
}

// ── the two other emptinesses ──
const noBoards = draw('sum', {sources: []});
ck('a dashboard with no source boards says so', noBoards.includes('לא נבחרו לוחות מקור'));
ck('…and offers the picker', noBoards.includes('Dash.sourcesPanel()'));
ck('…instead of an empty column list', !noBoards.includes('בחר עמודה'));

const noCols = draw('sum', {boards: {7: {name:'לוח ריק', cols:[], dates:[]}}});
ck('a board with no numeric column says so', noCols.includes('אין בלוח עמודה מספרית'));
ck('…naming the three kinds that can be summed',
   noCols.includes('מספר, נוסחה או מראה'));
ck('…instead of a select with one empty row', !noCols.includes('בחר עמודה'));

// ── switching the calculation is what reveals it ──
Dash.d = {id:1, config_version:1, can_edit:true, sources:[{board_id:7, groups:null}]};
E.boards = {7: BOARD};
E.draft = E.blank();
html = ''; E.paint();
const before = html.includes('בחר עמודה');
html = ''; E.calc('sum');
ck('choosing a sum reveals the picker', !before && html.includes('בחר עמודה'));
ck('…and clears whatever mapping the count was carrying',
   Object.keys(E.draft.mapping).length === 0);

// ── the third widget kind: a list of the records themselves ──
const LBOARD = {name:'הלוח שלי',
  cols:[{id:'c1', title:'H20 פתיחת שנה', type:'number'}], dates:[],
  all:[{id:'c1', title:'H20 פתיחת שנה', type:'number'},
       {id:'c2', title:'הערה', type:'text'}]};
function drawList({boards, sources, onBoard} = {}){
  Dash._onBoard = !!onBoard;
  Dash.d = {id:1, config_version:1, can_edit:true,
            sources: sources === undefined ? [{board_id:7, groups:null}] : sources};
  E.boards = boards === undefined ? {7: LBOARD} : boards;
  E.draft = E.blank();
  E.kind('list');
  html = ''; E.paint();
  return html;
}
const list = drawList();
ck('a list offers the board\'s columns to show', list.includes('הערה') && list.includes('H20 פתיחת שנה'));
ck('…and no calculation, because it measures nothing', !list.includes('עמודה בכל לוח מקור'));
ck('…and says how many rows it will show', list.includes('כמה שורות להציג'));
ck('…and why a link column is not on offer', list.includes('נפתחות מתוך הפריט עצמו'));
const listNoSrc = drawList({sources: []});
ck('a list with no source board says so too', listNoSrc.includes('לא נבחרו לוחות מקור'));

// ticking a column puts it in the draft, under its board
E.listCol(7, 'c2', true);
ck('ticking a column records it under its board',
   (E.draft.display.columns['7'] || []).includes('c2'));
E.listCol(7, 'c2', false);
ck('…and unticking takes it out', !(E.draft.display.columns['7'] || []).includes('c2'));

// switching kinds does not leak one kind's settings into another
E.draft = E.blank(); E.kind('chart');
ck('a chart sends no list settings', E.body().display && Object.keys(E.body().display).length === 0);
E.kind('list');
ck('a list sends no chart settings', E.body().chart && Object.keys(E.body().chart).length === 0);

// ── a board dashboard reads the board it is a tab on, and says nothing
//    about sources — DASH-06.1, "הלוח המארח יהיה המקור היחיד והקבוע" ──
const onBoard = draw('count', {onBoard:true});
ck('a board dashboard draws no sources section', !onBoard.includes('מקורות'));
ck('…but still asks which records', onBoard.includes('אוכלוסיית רשומות'));
const standalone = draw('count');
ck('a standalone one does draw it', standalone.includes('מקורות'));

// ── the condition builder ──
const CB = {name:'הלוח שלי',
  cols:[{id:'n1', title:'תקציב', type:'number'}], dates:[], all:[],
  filt:[{id:'n1', title:'תקציב', type:'number'},
        {id:'d1', title:'מועד פגישה', type:'date'}],
  statuses:[{key:'done', label:'בוצע'}],
  members:[{id:4, name:'דנה'}], groups:[]};
function drawConds(){
  Dash._onBoard = true;
  Dash.d = {id:1, config_version:1, can_edit:true, sources:[{board_id:7, groups:null}]};
  E.boards = {7: CB};
  E.draft = E.blank();
  html=''; E.paint();
  return html;
}
drawConds();
ck('the filter section offers to add a condition', html.includes('הוספת תנאי'));
const fields = E.filterFields().map(f=>f.key);
ck('…over the four built-ins', ['title','status','assignees','due'].every(k=>fields.includes(k)));
ck('…and the board\'s own filterable columns', fields.includes('n1') && fields.includes('d1'));

// "מספר פגישות של משתמש מסוים"
E.addRule(); E.ruleSet(0,'field','assignees'); E.ruleSet(0,'operator','has');
E.ruleSet(0,'value','4');
let r = E.rules()[0];
ck('a condition on a person is a people/has rule',
   r.field==='assignees' && r.operator==='has' && r.value==='4');
ck('…and the person is picked from the board, not typed', html.includes('דנה'));

// "פגישה אחרי תאריך מסוים"
E.addRule(); E.ruleSet(1,'field','d1'); E.ruleSet(1,'operator','after');
E.ruleSet(1,'value','2026-03-01');
r = E.rules()[1];
ck('a condition on a date offers after', r.operator==='after' && r.value==='2026-03-01');
ck('…and a board column is mapped so the server can run it',
   (E.draft.mapping['7']||{}).d1 === 'd1');
ck('…and relative periods are offered beside an exact date', html.includes('7 הימים האחרונים'));

// the shape the server reads
const adv = E.body().filters.adv;
ck('the conditions are one AND group', adv && adv.operator==='and' && adv.rules.length===2);
ck('…and every rule carries field, operator and value',
   adv.rules.every(x=>x.type==='rule' && x.field && x.operator));
E.dropRule(1); E.dropRule(0);
ck('removing the last condition clears the filter entirely',
   !E.body().filters.adv);

// ── finding the distribution at all ──
// The report that produced this: "ניסיתי ליצור לפי עמודה מנהלת תפעול ואני
// לא רואה אופציה". The column WAS offered — under a widget kind she had not
// chosen, with nothing saying the kind is where that lives.
const PB = {name:'הלוח', cols:[], dates:[], all:[], filt:[], hidden:[],
            statuses:[], members:[], groups:[],
            dims:[{id:'p1', title:'מנהלת תפעול', type:'people'},
                  {id:'s1', title:'שלב', type:'status'}]};
function drawKind(kind){
  Dash._onBoard = true;
  Dash.d = {id:1, config_version:1, can_edit:true, sources:[{board_id:7, groups:null}]};
  E.boards = {7: PB};
  E.draft = E.blank();
  E.kind(kind);
  html=''; E.paint();
  return html;
}
const asNumbers = drawKind('numbers');
ck('the three kinds are shown as a choice, not hidden in a select',
   asNumbers.includes('av-card') && asNumbers.includes('aria-pressed'));
ck('…and each says what it produces', asNumbers.includes('כמה בכל ערך של עמודה'));
ck('…so a distribution is findable from the kind that makes one',
   asNumbers.includes('התפלגות'));
const asChart = drawKind('chart');
ck('choosing it asks what to distribute by', asChart.includes('התפלגות לפי'));
ck('…and offers the board\'s own people column', asChart.includes('מנהלת תפעול'));
ck('…and its status column', asChart.includes('שלב'));
ck('…grouped apart from the four built-in kinds', asChart.includes('עמודות הלוח'));
ck('a numbers widget offers no distribution, which is why it is said above',
   !asNumbers.includes('התפלגות לפי'));

// choosing a column dimension maps it, so the server can resolve it
E.dim('p1');
ck('choosing a column names it per board', (E.draft.mapping['7']||{}).p1 === 'p1');

// ── the built-ins a board has taken off itself ──
// "העמודות שמופיעות הם אינם העמודות של הלוח הנבחר". A monday import switches
// all four built-in columns off (`col_hidden`), and three of the four
// built-in distributions ARE those fields — so on an imported board the list
// named סטטוס, אדם and תאריך יעד above the board's own columns, and grouping
// by one of them drew the default status, nobody, or one "ללא ערך" bar.
const HID = {name:'לוח מיובא', cols:[], all:[], filt:[],
             hidden:['assignees','status','priority','due'],
             statuses:[], members:[], groups:[],
             dates:[{id:'d1', title:'מועד', type:'date'}],
             dims:[{id:'d1', title:'מועד', type:'date'},
                   {id:'s1', title:'שלב', type:'status'}]};
function drawChart(board, chart){
  Dash._onBoard = true;
  Dash.d = {id:1, config_version:1, can_edit:true, sources:[{board_id:7, groups:null}]};
  E.boards = {7: board};
  E.draft = E.blank();
  E.kind('chart');
  if(chart) E.draft.chart = chart;
  html=''; E.paint();
  return html;
}
const hid = drawChart(HID);
const dims = E.dimOptions().map(([v])=>v);
ck('a board that hides סטטוס is not offered a status distribution', !dims.includes('status'));
ck('…nor one by person when it hides אחראים', !dims.includes('person'));
ck('…while קבוצה stays, because a board cannot hide its groups', dims.includes('group'));
ck('…and the board\'s own columns are still there', hid.includes('שלב') && hid.includes('מועד'));
ck('…with a line saying why the built-ins are absent',
   hid.includes('ההתפלגות היא לפי העמודות של הלוח עצמו'));
ck('…naming them', hid.includes('סטטוס ואחראים'));
ck('a split by a hidden built-in is not offered either',
   !E.splitOptions().map(([v])=>v).includes('status')
   && !E.splitOptions().map(([v])=>v).includes('person'));
ck('…while לוח מקור and קבוצה are',
   E.splitOptions().map(([v])=>v).join() === ',group,board');

// The date dimension reads the due date only while nothing better is named.
ck('תאריך survives on a board that has a date column of its own',
   E.dimOptions().map(([v])=>v).includes('date'));
const dated = drawChart(HID, {type:'vbar', dimension:'date'});
ck('…and the mapping stops offering the due date it does not have',
   !dated.includes('>תאריך יעד<') && dated.includes('בחרי עמודת תאריך'));
const NODATE = {...HID, dates:[], dims:[{id:'s1', title:'שלב', type:'status'}]};
drawChart(NODATE);
ck('a board with neither a due date nor a date column loses תאריך too',
   !E.dimOptions().map(([v])=>v).includes('date'));

// A widget already configured with one keeps its option, and says what is
// wrong with it — dropping it would show one grouping and compute another.
drawChart(HID, {type:'pie', dimension:'status'});
ck('a widget already grouped by a hidden built-in still shows it',
   E.dimOptions().some(([v,l])=>v==='status' && l.includes('אינו מוצג בלוח')));

// …and none of this touches a board that shows its built-ins.
drawChart(PB);
ck('a board that shows them is offered all four',
   E.dimOptions().map(([v])=>v).join() === 'group,status,person,date');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
