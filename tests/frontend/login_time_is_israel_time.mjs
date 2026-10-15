/* The "כניסה אחרונה" column reads in Israel's time.

   Two separate faults, and only one of them was about zones. The server's
   timestamps are UTC and used to arrive with nothing marking them as such, and
   ECMAScript reads a date-time with no offset as LOCAL time — so every login
   showed three hours early. The API says +00:00 now, and a bare timestamp is
   still read as UTC here so an old cached payload cannot disagree with a fresh
   one.

   Then the formatting: the column is read by people in Israel, so it is drawn
   in Israel's time rather than in whatever zone the viewer's machine is set to.
   A laptop still on a holiday's clock would otherwise quietly report the wrong
   hour to an admin checking who logged in when.
   Driven by tests/test_login_time_is_israel_time.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

/* close on the first line indented two spaces — counting braces does not
   survive this file (see log_checkbox_reads_as_a_tick.mjs) */
function grabMethod(header){
  const i = src.indexOf(header);
  if (i < 0) throw new Error('not found: ' + header);
  const nl = src.indexOf('\n', i);
  const end = src.indexOf('\n  }', nl);
  return src.slice(i, end + 4);
}
const TZ = /TZ:'([^']+)'/.exec(src);
const fdt = new Function('esc', `return { TZ:'${TZ ? TZ[1] : ''}', ${grabMethod('fdt(iso){')} };`)(
  x => String(x == null ? '' : x)).fdt;

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

ck('the column names the zone it draws in', TZ && TZ[1] === 'Asia/Jerusalem', TZ && TZ[1]);

// 08:22 UTC in October is 11:22 in Israel (IDT, UTC+3)
const SUMMER = '2026-10-15T08:22:02.410696';
ck('a bare timestamp is read as UTC, not as the machine\'s own time',
   fdt(SUMMER).includes('11:22'), fdt(SUMMER));
ck('...and a marked one lands on the same minute',
   fdt(SUMMER + '+00:00') === fdt(SUMMER) && fdt('2026-10-15T08:22:02Z').includes('11:22'),
   fdt(SUMMER + '+00:00'));
ck('...so a cached payload cannot disagree with a fresh one',
   fdt(SUMMER) === fdt(SUMMER + '+00:00'));

// 08:22 UTC in January is 10:22 in Israel (IST, UTC+2) — the offset is not a constant
const WINTER = '2026-01-15T08:22:02+00:00';
ck('winter is +2, not the +3 of summer — the zone is applied, not an offset',
   fdt(WINTER).includes('10:22'), fdt(WINTER));

// a viewer whose machine is somewhere else entirely still reads Israel time
const TOKYO = '2026-10-15T08:22:02+09:00';   // 23:22 the day before, UTC
ck('an offset other than UTC is honoured and converted',
   fdt(TOKYO).includes('02:22') && fdt(TOKYO).includes('15.10.2026'), fdt(TOKYO));

ck('the date is day-first, as Hebrew reads it', /^\d{2}\.\d{2}\.\d{4}/.test(fdt(SUMMER)), fdt(SUMMER));
ck('never logged in says so, rather than showing an epoch',
   /מעולם לא/.test(fdt(null)) && /מעולם לא/.test(fdt('')), fdt(null));
ck('an unparseable value is shown as it came, not as "Invalid Date"',
   fdt('לא תאריך') === 'לא תאריך', fdt('לא תאריך'));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
