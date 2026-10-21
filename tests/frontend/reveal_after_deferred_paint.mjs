/* Arriving at a record from outside: the board has to go to it, not just open
   the conversation over wherever it was.

   A board does not paint in one go. The first group is built now and the rest
   one frame later, behind a spacer (see the table renderer). A jump that asks
   for its row in between — which is every jump that opened the board itself,
   and therefore every link followed from an e-mail — found nothing in the
   document and silently gave up. The panel opened, the row was marked once the
   late groups arrived, and the board behind stayed exactly where it was: the
   record was somewhere below, unseen.

   From a notification the same code usually worked, because a notification
   points at the board already on screen and already drawn in full. That is the
   whole of the difference the two had to stop having.

   Driven by tests/test_reveal_after_deferred_paint.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

/* One method of the Chat object, verbatim, by brace matching from its name. */
function method(name){
  const m = new RegExp(`^  ${name}\\(`, 'm').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i = src.indexOf('{', m.index), d = 0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index, j+1);} }
  throw new Error('unbalanced: '+name);
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

/* A board drawn the way the real one is: `early` is what the first paint puts
   in the document, `late` what the deferred frame adds. `paint()` is that
   frame. Rows report themselves as being below the fold, which is what a row
   in a later group is. */
function board({tasks, early, late, openGroups=[]}){
  const w = {scrolled:[], rendered:0, marked:null, collapsed:new Set(), nodes:new Map()};
  const node = id => {
    const n = {id, classes:new Set(),
      classList:{add:c=>n.classes.add(c), remove:c=>n.classes.delete(c),
                 contains:c=>n.classes.has(c)},
      getBoundingClientRect:()=>({top:4000, bottom:4040}),
      scrollIntoView:o=>w.scrolled.push({id, block:o&&o.block})};
    return n;
  };
  tasks.forEach(t=>{ w.nodes.set(t.id, node(t.id));
                     (t.subtasks||[]).forEach(s=>w.nodes.set(s.id, node(s.id))); });
  let present = new Set(early);
  w.paint = () => { present = new Set([...early, ...late]); };
  const document = {
    querySelector: sel => {
      const id = +(/\[data-(?:tid|sid|id)="(\d+)"\]/.exec(sel)||[])[1];
      return present.has(id) ? w.nodes.get(id) : null;
    },
    querySelectorAll: () => [...w.nodes.values()].filter(n=>n.classes.has('chat-open')),
    /* `view` is the scrolling pane the rows live in; a row at y=4000 is below
       its bottom edge, which is what "in a later group" means on screen. */
    getElementById: () => ({classList:{add(){},remove(){},contains:()=>true},
                            style:{}, textContent:'', scrollIntoView(){},
                            getBoundingClientRect:()=>({top:0, bottom:800})}),
  };
  const st = {board:{id:1, tasks}, openSubs:new Set(openGroups)};
  const Chat = new Function(
    'st','document','renderView','groupCollapsed','setGroupCollapsed','W',
    `return {taskId:null,_reveal:null,
       ${method('rowOf')},
       ${method('markOpenRow')},
       ${method('revealOpenRow')},
       ${method('finishReveal')}};`)(
    st, document,
    () => { w.rendered++; },
    gid => w.collapsed.has(gid),
    (gid,on) => { if(on) w.collapsed.add(gid); else w.collapsed.delete(gid); },
    w);
  w.st = st; w.doc = document; w.Chat = Chat;
  return w;
}

const item = (id, group_id, subs) => ({id, group_id, subtasks: subs||[]});
const TASKS = [item(41,1), item(42,1), item(77,3), item(78,3, [item(91,3)])];
const openOf = w => [...w.nodes.values()].filter(n=>n.classes.has('chat-open')).map(n=>n.id);

// ── the record is in a group the first paint has not built yet ─────────────
{
  const w = board({tasks:TASKS, early:[41,42], late:[77,78,91]});
  w.Chat.taskId = 77;
  w.Chat.revealOpenRow(true);
  ck('nothing is scrolled while the row does not exist', w.scrolled.length===0);
  ck('...and the jump is remembered rather than dropped', w.Chat._reveal===77);
  w.paint();                       // the frame that builds the rest of the board
  w.Chat.markOpenRow(); w.Chat.finishReveal();
  ck('the board goes to the record once its row is painted',
     w.scrolled.length===1 && w.scrolled[0].id===77, JSON.stringify(w.scrolled));
  ck('...centred, the way a deliberate jump is',
     !!w.scrolled[0] && w.scrolled[0].block==='center');
  ck('...and the record is marked', openOf(w).join()==='77');
  ck('...and the jump is spent, not left armed', w.Chat._reveal===null);
}

// ── the record is in the first group: unchanged, and not done twice ────────
{
  const w = board({tasks:TASKS, early:[41,42], late:[77,78,91]});
  w.Chat.taskId = 42;
  w.Chat.revealOpenRow(true);
  ck('a row that is already painted is scrolled to at once',
     w.scrolled.length===1 && w.scrolled[0].id===42);
  ck('...with nothing left pending', w.Chat._reveal===null);
  w.paint(); w.Chat.markOpenRow(); w.Chat.finishReveal();
  ck('...and the deferred paint does not move the board a second time',
     w.scrolled.length===1, JSON.stringify(w.scrolled));
}

// ── opening the conversation from a row you are looking at ─────────────────
{
  const w = board({tasks:TASKS, early:[41,42], late:[77,78,91]});
  w.Chat.taskId = 77;
  w.Chat.revealOpenRow(false);     // the chat bubble on a row, not a jump
  w.paint(); w.Chat.markOpenRow(); w.Chat.finishReveal();
  ck('a click that is not a jump never moves the board', w.scrolled.length===0,
     JSON.stringify(w.scrolled));
}

// ── somebody opens another record before the frame lands ───────────────────
{
  const w = board({tasks:TASKS, early:[41,42], late:[77,78,91]});
  w.Chat.taskId = 77;
  w.Chat.revealOpenRow(true);
  w.Chat.taskId = 41;              // they moved on; Chat.open clears the pending jump
  w.Chat._reveal = null;
  w.paint(); w.Chat.markOpenRow(); w.Chat.finishReveal();
  ck('the board is not pulled to the record they just left', w.scrolled.length===0);
  ck('...and the record they are on is the marked one', openOf(w).join()==='41');
}
{
  const w = board({tasks:TASKS, early:[41,42], late:[77,78,91]});
  w.Chat.taskId = 77;
  w.Chat.revealOpenRow(true);
  w.Chat.taskId = 41;              // a stale pending jump, left armed by mistake
  w.paint(); w.Chat.markOpenRow(); w.Chat.finishReveal();
  ck('a jump for an item that is no longer open is refused outright',
     w.scrolled.length===0, JSON.stringify(w.scrolled));
}

// ── a sub-item whose parent's list is closed, in a late group ──────────────
{
  const w = board({tasks:TASKS, early:[41,42], late:[77,78,91]});
  w.Chat.taskId = 91;
  w.Chat.revealOpenRow(true);
  ck('the parent\'s sub-items are opened', w.st.openSubs.has(78));
  ck('...the board is redrawn for the row that did not exist', w.rendered===1);
  ck('...and the jump survives that redraw too', w.Chat._reveal===91);
  w.paint(); w.Chat.markOpenRow(); w.Chat.finishReveal();
  ck('...so the sub-item is reached and marked',
     w.scrolled.length===1 && w.scrolled[0].id===91 && openOf(w).join()==='91');
}

// ── an item that is not on this board at all ───────────────────────────────
{
  const w = board({tasks:TASKS, early:[41,42], late:[77,78,91]});
  w.Chat.taskId = 500;
  w.Chat.revealOpenRow(true);
  w.paint(); w.Chat.markOpenRow(); w.Chat.finishReveal();
  ck('nothing is scrolled to and nothing is armed',
     w.scrolled.length===0 && w.Chat._reveal===null);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
