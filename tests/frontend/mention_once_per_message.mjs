/* A person is offered once per message, and no more.

   The menu went on offering somebody already tagged in the box, so a message
   could be written holding "@דנה לוי" three times. None of the repeats reaches
   anyone twice — the server makes a SET of the tags, from the explicit array
   and from every "@Name" it finds in the text (_mentioned in main.py) — so the
   only thing a second tag adds is a name in the text that reads as a fresh
   call on somebody's attention and is not one.

   What "already tagged" means is read off the TEXT, not off `mentions`. That
   array only ever grows; nothing prunes it when a tag is deleted, so reading
   it would leave a name the writer removed suppressed for the rest of the
   message with no way back to it.

   Driven by tests/test_mention_once_per_message.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const at = src.indexOf('const Chat = {');
const chatSrc = src.slice(at, src.indexOf('\n};', at)) + '\n};';

const ME = 7;
const PEOPLE = [{id:7, name:'רינה כהן'}, {id:8, name:'דנה לוי'}, {id:9, name:'יוסי מזרחי'}];

/* `text` is what sits in the composer. The harness hands back a stub textarea
   holding it, which is the one thing taggedAlready reads. */
function chat(text){
  const ta = {value: text === undefined ? '' : text};
  const c = new Function('boardPeople','meId','st','document','esc','avatarInner',
                         'closeCellPops','openCellPop',
                         chatSrc + '\nreturn Chat;')(
    () => PEOPLE.slice(),
    () => ME,
    {users: PEOPLE.slice(), board:{id:1, members: PEOPLE.slice()}},
    {getElementById: (id) => (id === 'comp-text' ? ta : {}), querySelector: () => null},
    x => String(x == null ? '' : x),
    () => '',
    () => {}, () => {});
  c.mentions = [];
  c._floated = '';
  c._float = (anchor, html) => { c._floated = html; };
  c._ta = ta;
  return c;
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

// ── an empty box offers everybody ──────────────────────────────────────────
{
  const c = chat('');
  c._openMention({query:'', start:0, pos:1});
  ck('nothing typed yet — the whole board is on offer',
     c._mention.matches.map(u=>u.id).sort().join()==='8,9',
     c._mention.matches.map(u=>u.name));
}

// ── somebody already in the text is not offered again ──────────────────────
{
  const c = chat('@דנה לוי שלום, ');
  c._openMention({query:'', start:15, pos:16});
  ck('a person already tagged is gone from the menu',
     c._mention.matches.map(u=>u.id).join()==='9',
     c._mention.matches.map(u=>u.name));
  ck('...and everybody else is still there',
     c._floated.includes('יוסי מזרחי') && !c._floated.includes('דנה לוי'), c._floated);
}
{
  const c = chat('@דנה לוי שלום, ');
  c._openMention({query:'דנה', start:15, pos:19});
  ck('asking for them by name offers nothing', c._mention.matches.length===0);
  ck('...and says they are already tagged, not that they are off the board',
     c._floated.includes('כבר מתויג'), c._floated);
}

// ── the text is the authority, not the mentions array ──────────────────────
{
  const c = chat('');
  c.mentions = [8];          // tagged, then the writer deleted the words
  c._openMention({query:'', start:0, pos:1});
  ck('a tag deleted from the text frees the name again',
     c._mention.matches.some(u=>u.id===8),
     c._mention.matches.map(u=>u.name));
}
{
  const c = chat('@דנה לוי ');
  ck('taggedAlready reads the box', c.taggedAlready().has(8));
  ck('...and nobody else', !c.taggedAlready().has(9));
}

// ── everybody matched is already tagged ────────────────────────────────────
{
  const c = chat('@דנה לוי ו@יוסי מזרחי ');
  c._openMention({query:'', start:21, pos:22});
  ck('with the board exhausted the menu offers nothing',
     c._mention.matches.length===0, c._mention.matches);
  ck('...and says so in the plural',
     c._floated.includes('כולם כבר מתויגים'), c._floated);
}

// ── the tag being written is not a tag already placed ──────────────────────
/* Caught by tests/frontend/mention_finished.mjs, which had been pinning it
   since before this rule existed: with "שלי" and "שלי פיינברג" both on the
   board, "@שלי " must keep offering the pair. Reading the half-written token
   as a finished tag of the shorter name took it off the menu mid-keystroke and
   decided for the writer which colleague they meant. */
{
  const c = chat('@דנה ');
  c._openMention({query:'דנה ', start:0, pos:5});
  ck('the half-written tag does not take its own name off the menu',
     c._mention.matches.some(u=>u.id===8), c._mention.matches.map(u=>u.name));
}
{
  const c = chat('@דנה לוי שלום @דנה');
  c._openMention({query:'דנה', start:14, pos:18});
  ck('...while the SAME name finished earlier in the box still removes it',
     c._mention.matches.length===0 && c._mention.allTaken,
     c._mention.matches.map(u=>u.name));
}

// ── what must NOT have changed ─────────────────────────────────────────────
{
  const c = chat('@דנה לוי ');
  ck('a finished tag is still read as finished', c.mentionSettled('דנה לוי ')===true);
  ck('a half-typed name is still unfinished', c.mentionSettled('דנה')===false);
  // mentionSettled leans on mentionPeople; filtering the already-tagged THERE
  // would make a finished tag look unfinished and reopen the menu over it.
  ck('mentionPeople still holds somebody already tagged',
     c.mentionPeople().some(u=>u.id===8), c.mentionPeople().map(u=>u.name));
}
{
  const c = chat('שלום לכולם ');
  c._openMention({query:'מישהו אחר', start:0, pos:10});
  ck('a sentence that names nobody still closes the menu', c._mention===null||!c._mention);
}
{
  const c = chat('');
  c._openMention({query:'כהן', start:0, pos:4});
  ck('your own name still gets its own note, not the tagged one',
     c._floated.includes('אי אפשר לתייג את עצמך'), c._floated);
}

// ── a message holding the same tag twice is not sent ───────────────────────
/* The menu cannot see a name typed out in full or pasted in, so the whole
   message is counted before it leaves (taggedTwice). Each "@" counts once,
   for the longest name after it, the server's rule (_tagged_twice). */
{
  const c = chat('');
  ck('one tag each is fine', c.taggedTwice('@דנה לוי ו@יוסי מזרחי').length===0);
  ck('the same person twice is caught, by name',
     c.taggedTwice('@דנה לוי שלום, @דנה לוי שוב').join()==='דנה לוי',
     c.taggedTwice('@דנה לוי שלום, @דנה לוי שוב'));
  ck('...named once however many times it repeats',
     c.taggedTwice('@דנה לוי @דנה לוי @דנה לוי').length===1);
  ck('an @ that names nobody is not a tag', c.taggedTwice('mail@x @ @').length===0);
}
{
  PEOPLE.push({id:10, name:'שלי'}, {id:11, name:'שלי פיינברג'});
  const c = chat('');
  ck('a name that starts a longer one is not counted inside it',
     c.taggedTwice('@שלי פיינברג ו@שלי').length===0, c.taggedTwice('@שלי פיינברג ו@שלי'));
  ck('...but the longer name twice is still twice',
     c.taggedTwice('@שלי פיינברג @שלי פיינברג').join()==='שלי פיינברג');
  PEOPLE.splice(-2, 2);
}
{
  ck('post refuses before it sends',
     /async post\(\)\{[\s\S]{0,900}refuseTaggedTwice\(content\)\)return;[\s\S]{0,400}api\('\/api\/tasks\/'/.test(chatSrc));
  ck('saveEdit refuses before it sends',
     /async saveEdit\(cid\)\{[\s\S]{0,900}refuseTaggedTwice\(content\)\)return;[\s\S]{0,300}api\('\/api\/comments\/'/.test(chatSrc));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
