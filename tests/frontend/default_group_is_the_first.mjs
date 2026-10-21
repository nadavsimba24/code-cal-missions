/* Where "פריט חדש" at the top of the board puts the item.

   It is the board's FIRST group — the one at the top of the order somebody
   arranged. It used to be whichever group carried the backlog status, which on
   a board whose groups came out of the box is "בתכנון", falling back to the
   first group only when no group had it. On every board where the first group
   is something else — one reordered, one imported, one built by hand — the
   button filed the item somewhere down the page under a heading nobody had
   pointed at.

   A group's own "+ הוסף פריט" names its group and never asks this.

   Driven by tests/test_default_group_is_the_first.py. */
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
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x):''))); };

const pick = groups => new Function('st', grab('defaultGroupId')+'\nreturn defaultGroupId();')(
  {board: groups===null ? null : {id:1, groups}});

const g = (id, position, name, task_status) => ({id, position, name, task_status});

// ── the board as it comes out of the box ───────────────────────────────────
{
  const got = pick([g(1,0,'בתכנון','backlog'), g(2,1,'בביצוע','in_progress'), g(3,2,'הושלם','done')]);
  ck('the first group is the one, as it always was here', got===1);
}

// ── a board whose first group is NOT the backlog one ───────────────────────
{
  const got = pick([g(5,0,'דחוף','in_progress'), g(6,1,'בתכנון','backlog'), g(7,2,'הושלם','done')]);
  ck('the item goes to the group at the top of the order, not to "בתכנון"',
     got===5, 'landed in group '+got);
}
{
  /* The groups reordered after the board was built: "בתכנון" is now third, and
     its id is still the lowest. Neither of those decides anything. */
  const got = pick([g(3,0,'הושלם','done'), g(2,1,'בביצוע','in_progress'), g(1,2,'בתכנון','backlog')]);
  ck('a reorder moves the default with it', got===3, 'landed in group '+got);
}

// ── position is the order, whatever order the board hands them back in ─────
{
  const got = pick([g(9,2,'ג','done'), g(4,0,'א','in_progress'), g(6,1,'ב','backlog')]);
  ck('the list is read by position, not by the order it arrived in',
     got===4, 'landed in group '+got);
}
{
  const got = pick([g(9,undefined,'א'), g(4,1,'ב','backlog')]);
  ck('a group with no position of its own is treated as first', got===9);
}

// ── two groups on the same position ────────────────────────────────────────
{
  const a = pick([g(8,0,'א','done'), g(3,0,'ב','backlog')]);
  const b = pick([g(3,0,'ב','backlog'), g(8,0,'א','done')]);
  ck('a tie is broken the same way every time, whichever order they arrive in',
     a===3 && b===3, `${a} then ${b}`);
}

// ── a board with no groups at all ──────────────────────────────────────────
{
  ck('no groups: nowhere to put an item, and it says so', pick([])===null);
  ck('no board at all behaves the same', pick(null)===null);
}

// ── the status of a group decides nothing here ─────────────────────────────
{
  const withStatus = pick([g(5,0,'דחוף','in_progress'), g(6,1,'בתכנון','backlog')]);
  const without    = pick([g(5,0,'דחוף'), g(6,1,'בתכנון')]);
  ck('a board whose groups carry no status at all answers the same',
     withStatus===without && without===5);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
