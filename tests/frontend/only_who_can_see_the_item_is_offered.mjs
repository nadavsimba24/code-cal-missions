/* מי שלא רואה את הרשומה — לא מוצע לתיוג עליה.

   An assigned_only member of a board sees only the items they are assigned to.
   Offering them in an item's @-menu, or in one of its people columns, offered a
   tag the server now drops: the name vanished on save and nothing said why.
   So for one item the pickers leave out an assigned_only member who is not
   assigned to it — except in the board's permission column, because putting
   somebody THERE is how they are given the item in the first place.

   Pinned here, through boardPeople(alsoInclude, ctx) exactly as the page calls
   it: the @-menu (ctx without a col), a people column that is not the
   permission column, the permission column itself, a sub-item that follows its
   parent, a board whose permission column is one of its own people columns,
   and the board-wide pickers (no ctx) that must not change at all.

   Driven by tests/test_only_a_person_who_can_see_the_item_is_tagged_in_the_browser.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabFn(name){
  const m=new RegExp(`^function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){
    if(src[j]==='{')d++;
    else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);}
  }
  throw new Error('unbalanced: '+name);
}

const ED=2, AE=3, AO=4, AO2=5;
function world(settings, tasks){
  const st={board:{id:1, settings:settings||{}, members:[
      {id:1,  name:'מנהלת',        role:'admin'},
      {id:ED, name:'עורך',         role:'editor'},
      {id:AE, name:'עורך משויכים', role:'assigned_editor'},
      {id:AO, name:'משויך בלבד',   role:'assigned_only'},
      {id:AO2,name:'משויך שני',    role:'assigned_only'}]},
    users:[]};
  st.users=st.board.members.map(m=>({id:m.id, name:m.name}));
  const byId=new Map((tasks||[]).map(t=>[t.id,t]));
  const findAnyTask=id=>byId.get(id);
  return new Function('st','findAnyTask',
    grabFn('boardPermColumn')+'\n'+grabFn('itemPermHolders')+'\n'+grabFn('boardPeople')
    +'\n;return {boardPeople};')(st, findAnyTask);
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,240):''))); };
const ids = list => list.map(u=>u.id);

// ── the built-in assignees are the permission column (the default) ────────
{
  const theirs={id:10, assignees:[{id:AO}], custom_fields:{}};
  const hidden={id:11, assignees:[], custom_fields:{}};
  const w=world({}, [theirs, hidden]);

  const atHidden=ids(w.boardPeople([], {item:hidden}));
  ck('the @-menu of an item they cannot see leaves out assigned_only',
     !atHidden.includes(AO) && !atHidden.includes(AO2), JSON.stringify(atHidden));
  ck('…and still offers everybody who can see it, assigned_editor included',
     [1,ED,AE].every(i=>atHidden.includes(i)), JSON.stringify(atHidden));

  const atTheirs=ids(w.boardPeople([], {item:theirs}));
  ck('the @-menu of an item assigned to them offers them',
     atTheirs.includes(AO), JSON.stringify(atTheirs));
  ck('…but not the other assigned_only member, who is not on it',
     !atTheirs.includes(AO2), JSON.stringify(atTheirs));

  const otherCol=ids(w.boardPeople([], {item:hidden, col:'ppl'}));
  ck('a people column that is not the permission column leaves them out',
     !otherCol.includes(AO), JSON.stringify(otherCol));

  const permCol=ids(w.boardPeople([], {item:hidden, col:'assignees'}));
  ck('the permission column offers them — that is how they are given the item',
     permCol.includes(AO) && permCol.includes(AO2), JSON.stringify(permCol));

  const boardWide=ids(w.boardPeople());
  ck('a board-wide picker (filter, form) is not narrowed at all',
     [1,ED,AE,AO,AO2].every(i=>boardWide.includes(i)), JSON.stringify(boardWide));
}

// ── a sub-item follows its parent ────────────────────────────────────────
{
  const parent={id:20, assignees:[{id:AO}], custom_fields:{}};
  const sub={id:21, parent_id:20, assignees:[], custom_fields:{}};
  const w=world({}, [parent, sub]);
  const at=ids(w.boardPeople([], {item:sub}));
  ck('a sub-item of their item offers them, though nobody is on the sub-item',
     at.includes(AO), JSON.stringify(at));
  ck('…and still not somebody who is on neither',
     !at.includes(AO2), JSON.stringify(at));
}

// ── a board whose permission column is its own people column ─────────────
{
  const viaCol={id:30, assignees:[], custom_fields:{ppl:[AO]}};
  const viaAssignees={id:31, assignees:[{id:AO}], custom_fields:{}};
  const w=world({perm_column:'ppl'}, [viaCol, viaAssignees]);
  ck('the board\'s own permission column decides who is on the item',
     ids(w.boardPeople([], {item:viaCol})).includes(AO));
  ck('…and the built-in assignees stop counting',
     !ids(w.boardPeople([], {item:viaAssignees})).includes(AO));
  ck('under ppl, the built-in assignees column is the one that leaves them out',
     !ids(w.boardPeople([], {item:viaAssignees, col:'assignees'})).includes(AO));
  ck('…and ppl is the one that offers them',
     ids(w.boardPeople([], {item:viaAssignees, col:'ppl'})).includes(AO));
}

// ── a tag already on the item can still be found and removed ─────────────
{
  /* alsoInclude is how a stored name stays in its own cell's picker (the
     server allows removal for the same reason). The narrowing must not take
     that away, or a tag written before the rule could never be cleared. */
  const hidden={id:40, assignees:[], custom_fields:{ppl:[AO]}};
  const w=world({}, [hidden]);
  const at=ids(w.boardPeople([AO], {item:hidden, col:'ppl'}));
  ck('a name already stored in the cell is still offered, so it can be removed',
     at.includes(AO), JSON.stringify(at));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
