/* The bin beside a status that items wear is out of reach, and says why.

   The server refuses the deletion (see _status_in_use_409), and a refusal is
   the wrong place for a person to learn this: by then they have renamed three
   statuses, recoloured a fourth and pressed שמור, and the 409 throws all of it
   back at them. So the editor asks how many items wear each status BEFORE it
   paints a row, draws that number beside the status, and disables the bin.

   What is pinned here is the drawing and the second gate behind it:

     · the bin of a status nobody wears stays live;
     · the bin of a status somebody wears is disabled, and its tooltip says
       how many wear it — the row itself stays a name, a colour and an order,
       with no number drawn into it;
     · _stRemove / _csRemove refuse the same thing again, for every way into
       them that is not that button.

   Driven by tests/test_a_status_in_use_cannot_be_deleted.py. */
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
}

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

const esc = s => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* One row of the painted modal, found by the label inside its input. */
function row(html, label){
  const parts = html.split('class="st-row"');
  const hit = parts.find(p => p.includes(`value="${label}"`));
  if (!hit) throw new Error('no row for ' + label + ' in:\n' + html);
  return hit;
}
const binDisabled = r => /class="st-del"[^>]*\bdisabled\b/.test(r);

function base(extra){
  const env = {
    esc,
    swatchBtn: () => '<button class="sw-btn"></button>',
    showModal: h => { env.painted = h; },
    toast: m => { env.toasts.push(m); },
    toasts: [],
    painted: '',
    STATUS_COL_MAX: 30,
    BOARD_STATUS_MAX: 30,
    st: {board: {id: 5, name: 'לוח'}},
    ...extra,
  };
  return env;
}
function build(env, ...names){
  const keys = Object.keys(env);
  const body = names.map(grab).join(';') + `; return {${names.join(',')}};`;
  return new Function(...keys, body).apply(null, keys.map(k => env[k]));
}

// ── the board's own statuses ──────────────────────────────────────────────
function boardEditor(use){
  const env = base({
    _stDraft: [{key:'todo', label:'לביצוע', color:'#c4c4c4', base:'todo'},
               {key:'done', label:'הושלם', color:'#00c875', base:'done'},
               {key:'x_1',  label:'הקפאה', color:'#fd5ac3', base:'on_hold'}],
    _stUse: use,
  });
  return {env, ...build(env, '_stDelTitle', '_renderStatusModal', '_stRemove')};
}

let h = boardEditor({done: 4});
h._renderStatusModal();
ck('the bin of the status four items wear is disabled',
   binDisabled(row(h.env.painted, 'הושלם')), row(h.env.painted, 'הושלם'));
ck('...and the bin says how many wear it',
   /לא ניתן למחוק — 4 פריטים/.test(row(h.env.painted, 'הושלם')));
ck('...and the count is nowhere in the row itself',
   !/>4</.test(row(h.env.painted, 'הושלם').split('class="st-del"')[0]),
   row(h.env.painted, 'הושלם'));
ck('the bin of a status nobody wears is live',
   !binDisabled(row(h.env.painted, 'לביצוע')));
ck('...and its bin offers the plain word', row(h.env.painted, 'לביצוע').includes('title="הסר"'));
ck('a board-defined status is counted by its own key, not by its base',
   !binDisabled(row(h.env.painted, 'הקפאה')));

h = boardEditor({done: 4});
h._stRemove(1);
ck('_stRemove refuses the status four items wear', h.env._stDraft.length === 3);
ck('...and says so', h.env.toasts.some(t => /שימוש/.test(t) && /4/.test(t)),
   JSON.stringify(h.env.toasts));
h._stRemove(0);
ck('...while the one nobody wears goes', h.env._stDraft.length === 2 &&
   !h.env._stDraft.some(s => s.key === 'todo'));

// ── a status column's own vocabulary ──────────────────────────────────────
function colEditor(use){
  const col = {id: 'col_1', type: 'status', title: 'שלב',
               options: [{id:'o_1', label:'תכנון', color:'#0073ea'},
                         {id:'o_2', label:'ביצוע', color:'#00c875'}]};
  const env = base({
    _csCol: 'col_1',
    _csDraft: col.options.map(o => ({id:o.id, label:o.label, color:o.color, orig:o.label})),
    _csUse: use,
    customColumns: () => [col],
  });
  return {env, ...build(env, '_stDelTitle', '_renderColStatusModal', '_csRemove')};
}

let c = colEditor({o_2: 2});
c._renderColStatusModal();
ck('a column option two items wear has a dead bin, and no number drawn beside it',
   binDisabled(row(c.env.painted, 'ביצוע')) &&
   !/>2</.test(row(c.env.painted, 'ביצוע').split('class="st-del"')[0]),
   row(c.env.painted, 'ביצוע'));
ck('...and the option nobody wears is removable',
   !binDisabled(row(c.env.painted, 'תכנון')));
ck('the screen no longer promises that a removed status survives on the items',
   !/יישאר בפריטים הקיימים/.test(c.env.painted));
c._csRemove(1);
ck('_csRemove refuses it too', c.env._csDraft.length === 2 &&
   c.env.toasts.some(t => /שימוש/.test(t)));

// ── the server's refusal, in the editor's words ───────────────────────────
const msg = build(base({}), 'statusUseMsg').statusUseMsg(
  {message: 'לא ניתן למחוק סטטוס שיש בו שימוש — העבר תחילה את הפריטים לסטטוס אחר',
   statuses: [{key:'done', label:'הושלם', items:4}, {key:'x_1', label:'הקפאה', items:1}]});
ck('the 409 is read back as a sentence naming the status and the count',
   msg.includes('הושלם') && msg.includes('4'), msg);
ck('...and says how many others there were rather than listing them',
   msg.includes('ועוד 1'), msg);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
