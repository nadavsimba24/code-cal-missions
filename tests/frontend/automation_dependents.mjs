/* דיאלוג המחיקה מראה מה תלוי במה — לפני, לא אחרי.

   The server answers the question; what is checked here is that the dialog
   ASKS it, and that the two ways of getting no answer are not drawn the same.
   "Nothing depends on this" is a safe thing to tell somebody about to delete a
   column. "I could not find out" is not, and a dialog that rendered both as an
   empty box would be telling the second as if it were the first. */
import fs from 'fs';
const SRC = fs.readFileSync(new URL('../../frontend/index.html', import.meta.url), 'utf8');

let pass = 0, fail = 0;
const ck = (what, ok) => { ok ? pass++ : fail++;
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${what}`); };

function grab(name) {
  let i = SRC.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('not found: ' + name);
  if (SRC.slice(i - 6, i) === 'async ') i -= 6;   // keep the async, or await throws
  const j = SRC.indexOf('\n}', i);
  return SRC.slice(i, j + 2);
}

const fn = grab('dependentsHTML');
const calls = [];
const api = async (p) => { calls.push(p); return api._next; };
const esc = x => String(x == null ? '' : x);
const st = { board: { id: 1 } };
const dependentsHTML = new Function('api', 'esc', 'st',
  fn + ' return dependentsHTML;')(api, esc, st);

api._next = { count: 0, dependents: [], note: 'n' };
ck('nothing depending on it draws nothing', (await dependentsHTML('column', 'col_a')) === '');
ck('...and it asked the right question',
   calls[0].includes('kind=column') && calls[0].includes('col_a'));

api._next = { count: 2, active: 1, note: 'לא ייבחר שדה חלופי לפי שם.', dependents: [
  { id: 1, name: 'סגירת קריאה', sentence: 's', board_id: 1, board_name: 'כאן',
    uses: ['גורם מפעיל'], owner_name: 'דנה', status: 'active', impact: 'תושהה — גורם מפעיל' },
  { id: 2, name: '', sentence: 'כלל בלי שם', board_id: 7, board_name: 'לוח אחר',
    uses: ['פעולה'], owner_name: '—', status: 'paused', impact: 'מושהית כבר' }]};
const html = await dependentsHTML('column', 'col_a');
ck('the count leads', html.includes('2 אוטומציות תלויות'));
ck('...and says how many are running', html.includes('1 פעילות יושהו'));
ck('each one is named', html.includes('סגירת קריאה'));
ck('...a rule with no name falls back to its sentence', html.includes('כלל בלי שם'));
ck('...with how it is used', html.includes('גורם מפעיל') && html.includes('פעולה'));
ck('...and who answers for it', html.includes('דנה'));
ck('...and what will happen to it', html.includes('תושהה — גורם מפעיל'));
ck('a rule on another board says which', html.includes('לוח אחר'));
ck('the promise not to guess a replacement is on screen',
   html.includes('לא ייבחר שדה חלופי לפי שם'));

api._next = null;
api.throws = true;
const broken = new Function('api', 'esc', 'st',
  fn + ' return dependentsHTML;')(async () => { throw new Error('down'); }, esc, st);
const sad = await broken('column', 'col_a');
ck('a question that could not be asked says so — it does not read as "nothing"',
   sad !== '' && sad.includes('לא ניתן'));

/* and the two dialogs actually ask */
ck('deleting a column asks first', grab('deleteColumn').includes("dependentsHTML('column'"));
ck('deleting a group asks first',
   SRC.slice(SRC.indexOf('async function deleteGroup('),
             SRC.indexOf('async function deleteGroup(') + 900).includes("dependentsHTML('group'"));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
