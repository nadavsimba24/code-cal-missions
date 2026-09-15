/* A date inside an item's conversation carries its year.
   Driven by tests/test_chat_date_year.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

// the two formatters, exactly as the page defines them
const grab = re => { const m = re.exec(src); if(!m) throw new Error('not found: '+re); return m[0]; };
const {fdatetime, fdatetimeY} = new Function(
  grab(/function _utc\(d\)\{[^\n]+/) + '\n' +
  grab(/const fdatetime = [^\n]+/) + '\n' +
  grab(/const fdatetimeY = [^\n]+/) + '\nreturn {fdatetime, fdatetimeY};')();

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the formatter ──
const old2024 = fdatetimeY('2024-02-03T18:40:00');
ck('a date with the year names the year', /2024/.test(old2024), old2024);
ck('...and keeps the day, the month and the time',
   /^03\/02\/2024, \d\d:\d\d$/.test(old2024), old2024);
ck('the yearless format is still yearless (other places use it)',
   !/2024/.test(fdatetime('2024-02-03T18:40:00')));
ck('an empty date stays empty', fdatetimeY('')==='' && fdatetimeY(null)==='');

// ── where the conversation uses it ──
const chat = src.slice(src.indexOf('const Chat = {'), src.indexOf('\n};', src.indexOf('const Chat = {')));
const uses = [...chat.matchAll(/fdatetime(Y?)\(/g)].map(m=>m[1]==='Y');
ck('every date in the item panel carries the year',
   uses.length>0 && uses.every(Boolean), `${uses.filter(Boolean).length}/${uses.length}`);
ck('the message timestamp is one of them',
   /class="cmt-time">\$\{fdatetimeY\(c\.created_at\)\}/.test(chat), 'the message still has no year');
ck('so is the item log', /class="log-time">\$\{fdatetimeY\(a\.created_at\)\}/.test(chat));
ck('so is a file in the conversation', /fdatetimeY\(f\.created_at\)/.test(chat));

// ── and an imported message, which is the reason this matters ──
ck('a message imported from another year reads as that year',
   fdatetimeY('2024-02-03T18:40:00') !== fdatetimeY('2026-02-03T18:40:00'));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
