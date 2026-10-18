/* You are not in your own tag menu.

   Tagging yourself was an option the menu offered and the server then threw
   away — add_comment does `mentioned.discard(user.id)` before it notifies
   anybody — so picking yourself inserted "@your name" into the message and
   notified nobody. Now that a tag also sends mail, the option is the same
   nothing, only louder: a mail to yourself about your own message.

   boardPeople is deliberately NOT changed. It also feeds the אחראי picker and
   the people columns, and putting yourself on a record is ordinary.

   Driven by tests/test_mention_self.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const at = src.indexOf('const Chat = {');
const chatSrc = src.slice(at, src.indexOf('\n};', at)) + '\n};';

const ME = 7;
const PEOPLE = [{id:7, name:'רינה כהן'}, {id:8, name:'דנה לוי'}, {id:9, name:'רינה אחרת'}];
// "רינה" matches me and one other; "כהן" matches me alone; "דנה" matches
// somebody else alone. One word each — a query that runs past a space and
// matches nobody closes the menu rather than noting anything, which is how
// every unmatched sentence has always behaved.

function chat(){
  const c = new Function('boardPeople','meId','st','document','esc','avatarInner',
                         'closeCellPops','openCellPop',
                         chatSrc + '\nreturn Chat;')(
    () => PEOPLE.slice(),
    () => ME,
    {users: PEOPLE.slice(), board:{id:1, members: PEOPLE.slice()}},
    {getElementById: () => ({}), querySelector: () => null},
    x => String(x == null ? '' : x),
    () => '',
    () => {}, () => {});
  c.mentions = [];
  c._floated = '';
  c._float = (anchor, html) => { c._floated = html; };
  return c;
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

// ── the list the menu is built from ────────────────────────────────────────
{
  const c = chat();
  const ids = c.mentionPeople().map(u=>u.id);
  ck('the person writing is not in their own tag list', !ids.includes(ME), ids);
  ck('...and everybody else on the board still is',
     ids.includes(8) && ids.includes(9), ids);
}

// ── the menu itself ────────────────────────────────────────────────────────
{
  const c = chat();
  c._openMention({query:'', start:0, pos:1});
  ck('an empty @ offers the board without you',
     c._mention.matches.every(u=>u.id!==ME) && c._mention.matches.length===2,
     c._mention.matches.map(u=>u.name));
  ck('...and your name is nowhere in what is drawn',
     !c._floated.includes('רינה כהן') && c._floated.includes('דנה לוי'), c._floated);
}
{
  const c = chat();
  c._openMention({query:'רינה', start:0, pos:5});
  ck('a query matching you and somebody else offers only the somebody else',
     c._mention.matches.map(u=>u.id).join()==='9', c._mention.matches.map(u=>u.name));
}
{
  const c = chat();
  c._openMention({query:'כהן', start:0, pos:4});
  ck('a query that only matches you offers nothing', c._mention.matches.length===0);
  ck('...and says why, instead of claiming you are not on the board',
     c._floated.includes('אי אפשר לתייג את עצמך'), c._floated);
}
{
  const c = chat();
  c._openMention({query:'מישהו', start:0, pos:6});
  ck('somebody who really is not on the board still gets the board message',
     c._floated.includes('הוזמן ללוח'), c._floated);
}

// ── picking, and finishing a tag ───────────────────────────────────────────
{
  const c = chat();
  c._mention = {ctx:{query:'רינה כהן', start:0, pos:9}, matches:[], idx:0};
  c.insert = () => { c._inserted = true; };
  c.pickMention(ME);
  ck('your own id cannot be picked even if something asks for it',
     !c.mentions.includes(ME) && !c._inserted, c.mentions);
}
{
  const c = chat();
  ck('a finished tag of somebody else is still read as finished',
     c.mentionSettled('דנה לוי ') === true);
  ck('a half-typed name of somebody else is still unfinished',
     c.mentionSettled('דנה') === false);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
