/* ההתראה בפעמון קוראת לפריט בשמו הנוכחי.

   A notification's body is frozen when it is sent. The one a rule on "כאשר
   נוצר פריט חדש" sends is written while the row still carries the name the app
   gives a new item, so the bell showed «פריט חדש» for an item that had been
   given a real name hours before.

   The server now sends `item_title` beside every notification — the item's
   name as it is right now, and only where the reader may still open it (that
   half is tests/test_notification_names_the_item_now.py). This is the screen's
   half: the line is added where the frozen sentence does not already carry the
   name, it is escaped, and it does not displace the body.

   Driven by tests/test_notification_names_the_item_now.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

/* One method off the Notif object — it is not a top-level function, so the
   braces are counted from its own signature. */
function method(name){
  const m = new RegExp(`\\n  ${name}\\(`).exec(src);
  if (!m) throw new Error('not found: ' + name);
  let d = 0;
  for (let k = src.indexOf('{', m.index); k < src.length; k++){
    if (src[k] === '{') d++;
    else if (src[k] === '}'){ d--; if (!d) return src.slice(m.index + 1, k + 1); }
  }
}

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

// the real esc, so the escaping check is about the app's own and not a stub
const esc = new Function('return ' + /const esc = (s=>[^\n]+);/.exec(src)[1])();
const itemLine = new Function('esc', 'return {' + method('itemLineHTML') + '};')(esc).itemLineHTML;

// ── the case that was reported ────────────────────────────────────────────
const renamed = itemLine({body: 'שויכת לפריט חדש, שטרם ניתן לו שם.\nלוח: לוח',
                          item_title: 'שיקום כביש רמתיים'});
ck('a notification whose words do not name the item gets the live name',
   renamed.includes('שיקום כביש רמתיים'), renamed);
ck('…under a label, so it reads as the item and not as another sentence',
   /פריט:/.test(renamed), renamed);

// ── and no name said twice ────────────────────────────────────────────────
ck('a sentence that already names the item is left alone',
   itemLine({body: 'דנה שייך/ה אותך למשימה «תיקון מדרכה».',
             item_title: 'תיקון מדרכה'}) === '');
ck('…including the automation notice, which carries its own "פריט:" line',
   itemLine({body: 'כלל\nשליחת התראה\nפריט: הפריט שלי\nלוח: לוח',
             item_title: 'הפריט שלי'}) === '');

// ── nothing to say ────────────────────────────────────────────────────────
ck('a notification about no item at all adds no line',
   itemLine({body: 'הוסרת מהלוח.', item_title: null}) === '');
ck('…and neither does an item whose name is withheld',
   itemLine({body: 'שויכת לפריט חדש, שטרם ניתן לו שם.', item_title: ''}) === '');
ck('…or one that is only spaces', itemLine({body: 'משהו', item_title: '   '}) === '');
ck('a missing body is not a crash', itemLine({item_title: 'שם'}).includes('שם'));

// ── an item name is a stored value, and goes through esc ──────────────────
const nasty = itemLine({body: 'שויכת לפריט חדש, שטרם ניתן לו שם.',
                        item_title: '<img src=x onerror=alert(1)>'});
ck('an item called "<img src=x onerror=alert(1)>" is text, not a tag',
   !/<img/.test(nasty) && /&lt;img/.test(nasty), nasty);

// ── the row draws it, without losing anything it already drew ─────────────
const row = method('rowHTML');
ck('the row asks for the line', /this\.itemLineHTML\(n\)/.test(row), row);
ck('…after the body and before the time, where the item belongs',
   row.indexOf('notif-body') < row.indexOf('itemLineHTML')
   && row.indexOf('itemLineHTML') < row.indexOf('notif-time'), row);
ck('…and the body is still drawn', /notif-body/.test(row), row);
ck('…and the row still opens the item it names',
   /onclick="Notif\.click\(/.test(row), row);

// ── the line is readable, and does not stretch the popup ──────────────────
const css = /\.notif-item\{[^}]*\}/.exec(src);
ck('the line has a style of its own', !!css);
ck('…and a long item name is cut rather than widening the bell',
   !!css && /text-overflow:ellipsis/.test(css[0]) && /overflow:hidden/.test(css[0]), css && css[0]);

// ── the server half has to send it ────────────────────────────────────────
const py = fs.readFileSync(path.join(ROOT, 'backend', 'main.py'), 'utf8');
ck('the serializer carries item_title', /"item_title": item_title/.test(py));
ck('…resolved for the whole list at once', /_live_item_titles\(db, items, user_id\)/.test(py));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
