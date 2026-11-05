/* בועית השיחה — כחולה כל עוד מישהו כותב בה, אפורה אחרי שהשתתקה.

   Three things are pinned here, and all three are decisions rather than
   mechanics:

     · only a bubble that was BLUE can go grey. An item nobody has ever
       written on has no conversation to have gone quiet, and a badge that is
       not drawn at all cannot be drawn in a colour that complains about it.
     · the threshold is the BOARD's (chat_stale_days, set by the "ללא עדכון
       בשיחה" automation), and seven days when the board has not said.
     · the greyed bubble says WHY in its title. A colour on its own is a
       change somebody notices and cannot account for.

   Driven by tests/test_chat_bubble_goes_grey.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabFn(name){
  const i = src.indexOf('function '+name+'(');
  if(i<0) throw new Error('not found: '+name);
  const open = src.indexOf('{', src.indexOf(')', i));
  let d=0;
  for(let j=open;j<src.length;j++){
    if(src[j]==='{')d++;
    else if(src[j]==='}'){ d--; if(!d) return src.slice(i,j+1); }
  }
  throw new Error('unbalanced: '+name);
}

const esc = s => String(s==null?'':s).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const st = {board:{}};
const api = new Function('st','esc',
  grabFn('chatStaleDays')+grabFn('chatIdleDays')+grabFn('chatBtnHTML')
  +'return {chatStaleDays,chatIdleDays,chatBtnHTML};')(st, esc);

let fails = 0;
function ok(what, cond){ if(!cond){ fails++; console.log('✗ '+what); } else console.log('✓ '+what); }

const ago = d => new Date(Date.now()-d*86400000).toISOString();

// ── a board that has said nothing greys after a week ──
st.board = {};
ok('ברירת המחדל היא שבעה ימים', api.chatStaleDays()===7);
ok('בועית שדיברו בה אתמול — כחולה',
   /class="chat-btn has"/.test(api.chatBtnHTML({id:1,comment_count:2,last_comment_at:ago(1)})));
ok('בועית ששתקה שמונה ימים — אפורה',
   /class="chat-btn has stale"/.test(api.chatBtnHTML({id:1,comment_count:2,last_comment_at:ago(8)})));
ok('בדיוק שבעה ימים כבר אפור',
   /stale/.test(api.chatBtnHTML({id:1,comment_count:1,last_comment_at:ago(7.01)})));
ok('שישה ימים עדיין כחול',
   !/stale/.test(api.chatBtnHTML({id:1,comment_count:1,last_comment_at:ago(6)})));

// ── a bubble that was never blue is never greyed ──
const none = api.chatBtnHTML({id:9,comment_count:0,last_comment_at:null});
ok('פריט בלי שיחה — אין מה להאפיר', !/stale/.test(none) && !/\bhas\b/.test(none));
ok('…וגם אין מספר בבועית', !/<span>/.test(none));

// ── the board's own threshold ──
st.board = {chat_stale_days:30};
ok('לוח שקבע שלושים — שמונה ימים עדיין כחולים',
   !/stale/.test(api.chatBtnHTML({id:1,comment_count:3,last_comment_at:ago(8)})));
ok('…ושלושים ואחד אפורים',
   /stale/.test(api.chatBtnHTML({id:1,comment_count:3,last_comment_at:ago(31)})));
st.board = {chat_stale_days:3};
ok('לוח שקבע שלושה — חמישה ימים אפורים',
   /stale/.test(api.chatBtnHTML({id:1,comment_count:3,last_comment_at:ago(5)})));
st.board = {chat_stale_days:0};
ok('ערך שאינו מספר חיובי נופל לברירת המחדל', api.chatStaleDays()===7);

// ── and it says why ──
st.board = {};
const grey = api.chatBtnHTML({id:4,comment_count:2,last_comment_at:ago(12)});
ok('הבועית האפורה אומרת כמה זמן עברה', /ללא עדכון כבר 12 ימים/.test(grey));
ok('הכחולה לא מתנצלת',
   /title="שיחה"/.test(api.chatBtnHTML({id:4,comment_count:2,last_comment_at:ago(1)})));

// ── a value nothing can be read out of is not a silence ──
ok('תאריך שאי אפשר לקרוא אינו שתיקה',
   !/stale/.test(api.chatBtnHTML({id:5,comment_count:1,last_comment_at:'לא תאריך'})));


console.log(fails ? `\n${fails} failed` : '\nall good');
process.exit(fails ? 1 : 0);
