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

/* A date cell, as much of one as the function touches. The widget it builds
   records the order it was used in: appended, measured, opened. */
function cell({held = null} = {}){
  const log = [];
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
  const env = {
    log,
    document: {createElement(){
      const el = {born: true, type: '', className: '', value: '',
                  get offsetWidth(){ log.push('measured'); return 120; },
                  showPicker(){ log.push('opened'); },
                  focus(){ log.push('focused'); }, remove(){}};
      made.push(el); return el;
    }},
    fdateVal: v => v,
    setTimeout: () => 0,
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
                get offsetWidth(){ this._m++; return 120; },
                showPicker(){ this.opened = this._m; }, focus(){}, remove(){}};
  cell({held});
  ck('a widget already in the cell is not built again', held.opened !== undefined);
  ck('…and it too is measured first', held.opened === 1, String(held.opened));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
