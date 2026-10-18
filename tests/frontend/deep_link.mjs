/* The link in the mail: a board, and the conversation open on one record.

   "שוייכת לרשומה" and "תוייגת בשיחה" are mails sent to somebody who is NOT
   looking at the board, so the button in them is the whole of the feature —
   it has to land on that record's conversation, and when it cannot, it has to
   say which of the three reasons it was:

     * the board is not theirs to see. The entry used to fall through to
       whichever board they had open last, so the link opened SOME board and
       nothing anywhere said it was the wrong one;
     * the item is not in what the board just handed us — a board painted from
       the in-memory cache can predate the record the mail is about;
     * the item is gone.

   Driven by tests/test_item_mail_link.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i = src.indexOf('{', m.index), d = 0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index, j+1);} }
  throw new Error('unbalanced: '+name);
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

/* The world openDeepLink acts on. `boards` is what this person may see, and
   `rows` is what the board hands back — the two are deliberately separate,
   because every failure here is one of them disagreeing with the link. */
function world({boards=[1], rows=[], afterRefresh=null, boardOpens=true}={}){
  const w = {
    view:'', toasts:[], opened:null, closed:0, refreshed:0, rendered:0, env:null,
    st:{boards:boards.map(id=>({id, environment_id:1})), board:null},
  };
  const findAnyTask = id => (w.st.board ? (w.st.board.tasks||[]).find(t=>t.id===id) ||
    (w.st.board.tasks||[]).flatMap(t=>t.subtasks||[]).find(t=>t.id===id) : null) || null;
  const fn = new Function(
    'st','document','accessDeniedHTML','followBoardEnv','openBoard','findAnyTask',
    'refreshBoardItems','renderView','Chat','toast',
    grab('openDeepLink') + '\nreturn openDeepLink;')(
      w.st,
      {getElementById: () => ({set innerHTML(v){ w.view = v; }, get innerHTML(){ return w.view; }})},
      msg => 'ACCESS-DENIED: ' + msg,
      id => { w.env = id; },
      async id => { if(boardOpens) w.st.board = {id, tasks: rows}; },
      findAnyTask,
      async () => { w.refreshed++; if(afterRefresh) w.st.board.tasks = afterRefresh; },
      () => { w.rendered++; },
      {taskId:null, open(id){ w.opened = id; this.taskId = id; }, close(){ w.closed++; this.taskId = null; }},
      m => w.toasts.push(m));
  return [fn, w];
}

const item = (id, subs) => ({id, title:'רשומה '+id, subtasks: subs||[]});

// ── the ordinary case ──────────────────────────────────────────────────────
{
  const [go, w] = world({rows:[item(41), item(42)]});
  await go(1, 42);
  ck('the board opens and the conversation opens on the record', w.st.board.id===1 && w.opened===42);
  ck('...and the workspace follows the board', w.env===1);
  ck('...with nothing said that did not need saying', !w.toasts.length && !w.view);
}
{
  const [go, w] = world({rows:[item(41, [item(99)])]});
  await go(1, 99);
  ck('a sub-item is a record like any other', w.opened===99, w.toasts);
}
{
  const [go, w] = world({rows:[item(41)]});
  w.st.board = {id:1, tasks:[item(41)]};
  await go(1, null);
  ck('a link to the board alone opens no conversation', w.opened===null);
}

// ── the board is not theirs ────────────────────────────────────────────────
{
  const [go, w] = world({boards:[1,2], rows:[item(41)]});
  await go(7, 41);
  ck('a board they cannot see says so', w.view.startsWith('ACCESS-DENIED'), w.view);
  ck('...and does not open some other board instead', w.st.board===null && w.opened===null);
  ck('...naming the thing that can have changed since the mail went out',
     /הרשאה|הוזמנת/.test(w.view), w.view);
}

// ── the record is not in what the board handed back ────────────────────────
{
  const [go, w] = world({rows:[item(41)], afterRefresh:[item(41), item(42)]});
  await go(1, 42);
  ck('a record the board did not bring is asked for again', w.refreshed===1);
  ck('...and the conversation opens once it arrives', w.opened===42, w.toasts);
  ck('...with the board redrawn so the row is there behind it', w.rendered===1);
}
{
  const [go, w] = world({rows:[item(41)]});
  await go(1, 777);
  ck('a record that is really gone is said to be gone', w.toasts.length===1 &&
     /נמחקה|לא נמצאה/.test(w.toasts[0]), w.toasts);
  ck('...on the board, not on an error page', w.st.board.id===1 && !w.view);
  ck('...having asked the server before saying it', w.refreshed===1);
}

// ── not doing it twice ─────────────────────────────────────────────────────
{
  const [go, w] = world({rows:[item(41)]});
  w.st.board = {id:1, tasks:[item(41)]};
  await go(1, 41);
  ck('a conversation already open is left alone', w.opened===41);
  const again = w.refreshed;
  await go(1, 41);
  ck('...and following the same link again does nothing', w.refreshed===again);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
