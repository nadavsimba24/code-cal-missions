/* מנהל לוח מוסיף משתתף — ואפשר לתייג אותו מיד, בלי רענון יזום.

   Every picker on the board draws from boardPeople(), and boardPeople()
   reads st.board.members — the list that came down with the board when it
   was loaded. The members dialog fetched its own list and redrew its own
   rows, and touched nothing else. So an admin invited somebody, watched the
   name appear in the dialog, closed it, and then could not tag them in a
   people column, in the assignee menu, in the filter's people chips, in a
   form's אנשים question or with @ in the chat. Only F5 fixed it.

   The live stream could not cover this one. Live.onEvent drops an event
   whose actor is me, on the grounds that I can already see what I did —
   true of a row I just edited, and not true of a picker I am not looking at.
   So the browser repairs its own list, and the server's board.changed is for
   everybody else.

   Pinned here: the list is rebuilt from the dialog's own answer, in the
   shape and by the rules the board payload uses — active only, by name —
   and boardPeople() offers the new person immediately.

   Driven by tests/test_a_new_member_is_taggable_at_once.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabMethodIn(obj,name){
  const o=new RegExp(`^const ${obj} = \\{|^const ${obj}=\\{`,'m').exec(src);
  if(!o) throw new Error('not found: '+obj);
  const m=new RegExp(`^  (?:async )?${name}\\(`,'m').exec(src.slice(o.index));
  if(!m) throw new Error('not found: '+obj+'.'+name);
  const from=o.index+m.index;
  let i=src.indexOf('{',from), d=0;
  for(let j=i;j<src.length;j++){
    if(src[j]==='{')d++;
    else if(src[j]==='}'){d--; if(!d) return src.slice(from,j+1);}
  }
  throw new Error('unbalanced: '+name);
}
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

/* The board as it was loaded: two members, and the picker that reads them. */
function world(){
  const st={board:{id:1, name:'לוח', members:[
      {id:2, name:'אבי כהן',  avatar_url:'/a2.png'},
      {id:3, name:'גלית לוי', avatar_url:null}]},
    users:[]};
  const fns=new Function('st',
    grabFn('boardPeople')+'\n'
    +'const Members={data:{members:[],available:[]},'
    + grabMethodIn('Members','_syncBoardPeople')
    +'};\n;return {boardPeople,Members,st};')(st);
  return fns;
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,240):''))); };
const names = w => w.boardPeople().map(u=>u.name);

// ── the invitation ────────────────────────────────────────────────────────
{
  const w=world();
  ck('before: the new person is not offered',
     !names(w).includes('דנה שפירא'), JSON.stringify(names(w)));
  // the answer the dialog gets back from /api/boards/{id}/members
  w.Members.data={members:[
    {user_id:2,name:'אבי כהן', role:'admin', is_active:true, avatar_url:'/a2.png'},
    {user_id:3,name:'גלית לוי',role:'editor',is_active:true, avatar_url:null},
    {user_id:9,name:'דנה שפירא',role:'editor',is_active:true,avatar_url:'/a9.png'}],
    available:[]};
  w.Members._syncBoardPeople();
  ck('after: she is taggable at once, with no reload',
     names(w).includes('דנה שפירא'), JSON.stringify(names(w)));
  ck('…and nobody was lost on the way',
     names(w).includes('אבי כהן')&&names(w).includes('גלית לוי'), JSON.stringify(names(w)));
  ck('…and her face came with her',
     (w.st.board.members.find(m=>m.id===9)||{}).avatar_url==='/a9.png',
     JSON.stringify(w.st.board.members));
}

// ── the rules the board payload itself follows ────────────────────────────
{
  const w=world();
  w.Members.data={members:[
    {user_id:9,name:'דנה שפירא',role:'editor',is_active:true},
    {user_id:2,name:'אבי כהן',  role:'admin', is_active:true},
    {user_id:7,name:'מושבת',    role:'viewer',is_active:false}],
    available:[]};
  w.Members._syncBoardPeople();
  ck('a deactivated member is not offered to any picker',
     !names(w).includes('מושבת'), JSON.stringify(names(w)));
  ck('the list is by name, as the board payload orders it',
     JSON.stringify(names(w))===JSON.stringify(['אבי כהן','דנה שפירא']),
     JSON.stringify(names(w)));
  /* The board payload's members[] carries each member's role since the
     assigned_editor / assigned_only roles: a picker narrowing to the people
     who can see one item has to know who is assigned_only. So the rebuilt
     list carries it too — a list without it would make a just-invited
     assigned_only member taggable on every item until the next reload. */
  ck('…and the shape is the board\'s own {id,name,avatar_url,role}',
     w.st.board.members.every(m=>'id' in m && 'name' in m && 'avatar_url' in m
                                && !('user_id' in m) && 'role' in m),
     JSON.stringify(w.st.board.members));
}

// ── removal is the same list, the other way ───────────────────────────────
{
  const w=world();
  w.Members.data={members:[{user_id:2,name:'אבי כהן',role:'admin',is_active:true}],
                  available:[]};
  w.Members._syncBoardPeople();
  ck('somebody taken off the board stops being offered',
     !names(w).includes('גלית לוי'), JSON.stringify(names(w)));
}

// ── a server that has not been restarted into the new payload ─────────────
{
  /* The avatar is new in this answer. Against a process that predates it the
     field is simply absent, and the face already held must not be thrown
     away for an undefined. */
  const w=world();
  w.Members.data={members:[{user_id:2,name:'אבי כהן',role:'admin',is_active:true}],
                  available:[]};
  w.Members._syncBoardPeople();
  ck('an answer with no avatar keeps the face already held',
     (w.st.board.members.find(m=>m.id===2)||{}).avatar_url==='/a2.png',
     JSON.stringify(w.st.board.members));
}

// ── a failed fetch must not empty the board ───────────────────────────────
{
  /* The hazard this change brings with it, and the floor under it. Both
     callers swallow a failed request; the empty default they would otherwise
     fall back to is indistinguishable, at this function, from an answer.

     A board you can SEE always has at least one member — you — so a list
     with nobody on it is never a true answer about it. Written through, one
     timed-out request would take every person off every picker on the board:
     the people column, the assignee menu, the chat's @ menu, all empty, and
     nothing on screen to say why. */
  const w=world();
  const before=names(w).slice();
  w.Members.data={members:[],available:[]};
  w.Members._syncBoardPeople();
  ck('an empty answer is a failed fetch, and leaves the board\'s people alone',
     JSON.stringify(names(w))===JSON.stringify(before),
     JSON.stringify({before,after:names(w)}));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
