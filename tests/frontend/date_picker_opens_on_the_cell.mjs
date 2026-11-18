/* The calendar opens over the cell that was pressed, not in the corner of the
   screen.

   A date cell holds no `<input type="date">` of its own — one per cell is
   three and a half thousand browser widgets in a single group of board 114 —
   so dateCellPick builds one on the press and takes it away again afterwards.
   It then called showPicker() on it in the very next statement.

   An element appended one statement earlier has no box. Style and layout have
   not run for it, so it has no layout object, the anchor rect the picker asks
   for comes back empty, and Chrome puts the calendar at the top-LEFT of the
   screen — on an RTL board, the far side from the cell. The press after it
   worked, because that one found the widget already there and already
   measured, which is why it was reported as happening "sometimes".

   Pinned here: the widget is measured BEFORE it is opened. A fake DOM is
   enough and a real browser would not be — the fault is an ordering between
   two calls, and the harness watches the order.

   Driven by tests/test_a_date_picker_opens_on_its_cell.py. */
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

const CODE = cut('function dateCellPick(e){', '\n}', 'dateCellPick');

/* The rect the widget reports. A laid-out cell by default; the section at the
   foot of this file sets the empty one a skipped group answers with. */
let RECT = {width: 120, height: 28, top: 300, left: 400};
/* Timers the code arms, so a test can fire them at the moment the real 200ms
   would have elapsed — which is the whole of the second bug here. */
let timers = new Map(), timerSeq = 0;
const fireTimers = () => { const due = [...timers.values()]; timers.clear(); due.forEach(f => f()); };

/* A date cell, as much of one as the function touches. The widget it builds
   records the order it was used in: appended, measured, opened. */
function cell({held = null, sharedLog = null} = {}){
  const log = sharedLog || [];
  const value = {value: '2026-03-04', dispatchEvent(){ log.push('saved'); }};
  const wrap = {
    kids: held ? [held] : [],
    classList: {add(){ log.push('fallback'); }, contains: () => false},
    querySelector(sel){
      if (sel === 'input.cc-date') return value;
      if (sel === 'input.cc-date-native') return wrap.kids.find(k => k.born) || null;
      return null;
    },
    appendChild(k){ log.push('appended'); wrap.kids.push(k); },
  };
  const made = [];
  if (held) held.onblur = held.onblur || (() => {});
  const env = {
    log,
    document: {createElement(){
      const el = {born: true, type: '', className: '', value: '',
                  /* What the code asks for, and the one knob these tests turn:
                     RECT is the answer a browser gives when it knows where the
                     widget is, and the empty one is what a group skipped by
                     content-visibility gives back. */
                  getBoundingClientRect(){ log.push('measured'); return RECT; },
                  showPicker(){ log.push('opened'); },
                  focus(){ log.push('focused'); },
                  remove(){ log.push('removed'); wrap.kids = wrap.kids.filter(k => k !== el); }};
      made.push(el); return el;
    }},
    fdateVal: v => v,
    setTimeout: (fn) => { const id = ++timerSeq; timers.set(id, fn); return id; },
    clearTimeout: (id) => { if (id != null && timers.delete(id)) log.push('disarmed'); },
    Event: class { constructor(t){ this.type = t; } },
  };
  const keys = Object.keys(env);
  const fn = new Function(...keys, CODE + '\nreturn dateCellPick;')(...keys.map(k => env[k]));
  fn({stopPropagation(){}, currentTarget: {closest: () => wrap}});
  return {log, made};
}

// ── the bug, as reported ───────────────────────────────────────────────────
{
  const {log} = cell();
  ck('a widget built on the press is opened', log.includes('opened'), log.join(' → '));
  ck('…after it has been measured, not before',
     log.indexOf('measured') > -1 && log.indexOf('measured') < log.indexOf('opened'),
     log.join(' → '));
  ck('…and the measure comes after it is in the document, where it has a box',
     log.indexOf('appended') < log.indexOf('measured'), log.join(' → '));
}

// ── a cell still holding one from a previous press ─────────────────────────
{
  const held = {born: true, _m: 0,
                getBoundingClientRect(){ this._m++; return RECT; },
                showPicker(){ this.opened = this._m; }, focus(){}, remove(){}};
  cell({held});
  ck('a widget already in the cell is not built again', held.opened !== undefined);
  ck('…and it too is measured first', held.opened === 1, String(held.opened));
}

/* ── press, press again ─────────────────────────────────────────────────────
   The widget is taken out of the row 200ms after it loses focus, so a picker
   somebody dismissed does not leave a control behind in every cell it was
   ever opened from. But pressing the button again is itself what blurs it:
   press, press again, and the second calendar is opened against an element
   the armed removal then takes out of the document underneath it. The removal
   is for a DISMISSED widget, and a cell being pressed is not a dismissal. */
{
  const {log, made} = cell();
  const nat = made[0];
  log.length = 0;
  nat.onblur();                       // pressing again is what blurs it
  cell({held: nat, sharedLog: log});
  ck('a press inside the removal window disarms the removal',
     log.includes('disarmed'), log.join(' → '));
  ck('…and still opens the calendar', log.includes('opened'), log.join(' → '));
  fireTimers();
  ck('…so the anchor is not taken out from under the open calendar',
     !log.includes('removed'), log.join(' → '));
}

/* The disarm must not cost what the timeout is for: one widget per cell ever
   opened is the weight this whole design exists to avoid. */
{
  const {log, made} = cell();
  made[0].onblur();
  log.length = 0;
  fireTimers();
  ck('a widget dismissed and left alone is still taken out of the row',
     log.includes('removed'), log.join(' → '));
}

/* ── no box, no picker ──────────────────────────────────────────────────────
   Forcing layout is a request, not a guarantee. A group off screen is skipped
   whole by content-visibility, and a cell in one can be pressed in the frame
   it is scrolled into. A calendar in the corner of the screen is the bug being
   reported — the cell's own control is drawn where the cell is, so that is the
   honest answer to "I could not work out where to put this". */
for (const [what, rect] of [['no width or height', {width: 0, height: 0, top: 0, left: 0}],
                            ['a box with no height', {width: 120, height: 0, top: 300, left: 400}]]){
  RECT = rect;
  const {log} = cell();
  ck(`a cell reporting ${what} opens no picker`, !log.includes('opened'), log.join(' → '));
  ck(`…and is handed its own control instead`,
     log.includes('fallback') && log.includes('focused'), log.join(' → '));
  RECT = {width: 120, height: 28, top: 300, left: 400};
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
