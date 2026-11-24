/* Deleting a group asks the way the rest of the app asks, and says why when it
   will not.

   Nothing ever stopped a group being removed — not the first one, not "בתכנון",
   not the one carrying the backlog status; the server deletes any of them and
   detaches their items (tests/test_group_delete_any.py holds that down). What
   made it look otherwise lived in this one function.

   The question was a native confirm(), the only dialog in the app that was not
   ours. A browser may suppress it — a second dialog in quick succession, or
   "prevent this page from creating more dialogs" once ticked — and a suppressed
   confirm() returns false, so the button did nothing whatsoever and explained
   none of it. And every refusal came back as "שגיאה במחיקה", so a board you may
   not edit read exactly like a group that cannot be deleted.
   Driven by tests/test_group_delete_dialog.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

const fn = grab('deleteGroup');

ck('the group deletion asks with the app\'s own dialog',
   /askConfirm\(/.test(fn));
ck('and not with a native confirm, which a browser is free to suppress',
   !/[^k]confirm\('/.test(fn), fn);
/* a suppressed native confirm() returns false, which this code read as "the
   user said no" — indistinguishable from a group that may not be deleted */
ck('nothing in it treats a falsy answer as a refusal to be swallowed',
   !/if\(!confirm/.test(fn));

ck('a refusal shows the reason the server gave',
   /toast\(\(e&&e\.detail\)\|\|'שגיאה במחיקה'\)/.test(fn), fn);
ck('and the blanket message is only the fallback, for when there is no reason',
   fn.indexOf('e.detail') < fn.indexOf("'שגיאה במחיקה'"));

ck('the group is named in the question, so it is clear which one is going',
   /askConfirm\('למחוק את הקבוצה'\+\(g\?` "\$\{g\.name\}"`:''\)/.test(fn), fn);
ck('the note promises what the server actually does — detach, not delete',
   /יעברו ל״ללא קבוצה״ — הם לא נמחקים/.test(fn));
ck('it is a destructive dialog: red button, מחק on it',
   /confirmText:'מחק'/.test(fn) && /title:'מחיקת קבוצה'/.test(fn));

/* askConfirm closes the modal itself before running the action, so the edit
   dialog the מחק button sits in does not have to be closed again */
ck('the edit dialog is not closed twice',
   !/closeModals\(\)/.test(fn), fn);

// ── what the note actually says, for a board in each state it can be in ───
/* The number in this note is read immediately before somebody presses מחק, so
   it is the one count in the app where being wrong is dangerous rather than
   untidy. It used to be `st.board.tasks` filtered by group — the rows this
   browser happens to hold — which past the paging threshold is a page of
   fifty and can be none at all: "הקבוצה ריקה" printed over a group holding
   three thousand items, and the person believing it.

   So the note is run rather than read. deleteGroup is pulled out of
   index.html and called with a board in each state — paged with the server's
   counts, fully loaded, empty, and a board from a backend that sends no
   counts at all — and what the dialog was handed is inspected. The checks
   below are about the sentence the reader gets, not about how it is built,
   which is what the assertion they replace was pinning. */
/* groupCountKnown comes along rather than being stubbed: it is the function
   that decides whether there is a number to state at all, and the dialog is
   the one caller that asks it for the group's WHOLE size — a board narrowed by
   a filter is showing a cut, but the delete is not about the cut, and the
   items that do not match the filter are going to move with the rest. Stubbing
   it would leave that unasked. */
const known = (()=>{ const g=/function groupCountKnown\([^)]*\)\{[\s\S]*?\n\}/.exec(src);
  if(!g) throw new Error('groupCountKnown is gone'); return g[0]; })();

async function note(board,{partial=false,narrowed=false,gid=5,dep=''}={}){
  let asked=null;
  const run = new Function('st','dependentsHTML','askConfirm','api','meId',
                           'toast','esc','boardRowsPartial','boardIsNarrowed',
                           known+'\n'+fn+'; return deleteGroup;')(
    {board},
    async()=>dep,
    (msg,act,o)=>{ asked={msg,...(o||{})}; },
    async()=>({}), ()=>1, ()=>{}, s=>String(s),
    ()=>partial, ()=>narrowed);
  await run(gid);
  if(!asked) throw new Error('no dialog was asked for');
  return String(asked.note||asked.noteHTML||'');
}

const rows=(n,gid=5)=>Array.from({length:n},()=>({group_id:gid}));

/* the case the change is for: 1033 items in the group, two of them in hand */
const paged = await note({id:1,groups:[{id:5,name:'ג'}],tasks:rows(2),
                          group_counts:{'5':1033}},{partial:true});
ck('on a paged board the note states the group\'s real size, not the rows in hand',
   /1033/.test(paged) && !/\b2 הפריטים/.test(paged), paged);
ck('...and it does not hedge when the server has told it the number',
   !/לא ניתן להציג/.test(paged), paged);
ck('...and it still promises the items move rather than die',
   /לא נמחקים/.test(paged), paged);

const loaded = await note({id:1,groups:[{id:5,name:'ג'}],tasks:rows(3),
                           group_counts:{'5':3}});
ck('a board holding all its rows says the same number the same way',
   /3 הפריטים/.test(loaded), loaded);

const empty = await note({id:1,groups:[{id:5,name:'ג'}],tasks:[],
                          group_counts:{'5':0}});
ck('an empty group says it is empty rather than counting nothing at you',
   /^הקבוצה ריקה\.$/.test(empty), empty);

/* the one case where no number can honestly be given: an older backend sends
   no group_counts, and the rows are still arriving */
const blind = await note({id:1,groups:[{id:5,name:'ג'}],tasks:rows(2)},{partial:true});
ck('with no count from the server and rows still arriving, it says so instead of guessing',
   /לא ניתן להציג/.test(blind) && !/\d/.test(blind), blind);
ck('...and never calls such a group empty',
   !/הקבוצה ריקה/.test(blind), blind);

const old = await note({id:1,groups:[{id:5,name:'ג'}],tasks:rows(2)});
ck('with no count from the server but every row in hand, it counts the rows as it always did',
   /2 הפריטים/.test(old), old);

/* A filter narrows what is on screen and nothing else: the items it hides are
   in the group and they move with it. Everywhere else a narrowed board counts
   what it is showing — here that would understate, in the dialog, what is
   about to happen. */
const filtered = await note({id:1,groups:[{id:5,name:'ג'}],tasks:rows(1),
                             group_counts:{'5':40}},{narrowed:true});
ck('under a filter the dialog still states the whole group, not the part that matches',
   /40 הפריטים/.test(filtered), filtered);

/* the orphan heading is a group as far as this dialog is concerned, and the
   board files its count under a key of its own */
const orphan = await note({id:1,groups:[],tasks:[],group_counts:{'null':6}},{gid:null});
ck('the "ללא קבוצה" heading reads its own bucket rather than counting nothing',
   /6 הפריטים/.test(orphan), orphan);

// ── and no native dialog is left anywhere in the app ──────────────────────
/* a real call passes a message, so it is `confirm('…` — which also keeps the
   two mentions of confirm() in the prose above out of the count. askConfirm is
   excluded by the lookbehind: the character before it is a word character. */
const natives = [...src.matchAll(/(?<![\w.])confirm\(\s*['"`]/g)];
ck('no native confirm() is left in the app at all',
   natives.length===0, natives.length+' left: '+natives.map(m=>src.slice(m.index,m.index+40)).join(' | '));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
