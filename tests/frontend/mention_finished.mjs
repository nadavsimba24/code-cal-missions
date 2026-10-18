/* A tag has an end: once a board member is picked, the rest of the line is the
   message.

   A name holds spaces, so the "@…" query allows them — which meant a picked tag
   was still being read as a query to the end of the line. Every further word
   reopened the autocomplete on the finished tag, the "no matching board members"
   note sat over the composer, and Enter was taken by the menu instead of
   inserting a newline. Pressing Enter first was the only way to type a message,
   because a query cannot cross a newline, and that is exactly how it was
   reported.

   Runs the real mentionCtx / mentionSettled / onType / _openMention /
   pickMention / keydown out of index.html under node, the same way
   tests/frontend/chat_date_year.mjs does. Driven by
   tests/test_mention_finished.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

// the composer's methods, brace-matched out of the Chat object literal
const chatStart = src.indexOf('const Chat = {');
const chat = src.slice(chatStart, src.indexOf('\n};', chatStart));
function grabMethod(name){
  const m = new RegExp(`^  ${name}\\(`,'m').exec(chat);
  if(!m) throw new Error('not found: '+name);
  let i = chat.indexOf('{', m.index + m[0].length - 1), d = 0;
  for(let j=i;j<chat.length;j++){
    if(chat[j]==='{')d++;
    else if(chat[j]==='}'){ d--; if(!d) return chat.slice(m.index, j+1)+','; }
  }
  throw new Error('unbalanced: '+name);
}
const METHODS = ['mentionCtx','mentionSettled','onType','_openMention','_closeMention',
                 'pickMention','keydown','insert','mentionPeople'].map(grabMethod).join('\n');

// ── the world the composer runs in ──
let PEOPLE = [];
/* Who is typing. The tag menu leaves the writer out of it — see
   tests/frontend/mention_self.mjs — so these cases name somebody who is not in
   PEOPLE, and every one of them reads exactly as it did before that rule. */
let ME = 0;
let ta = null;                       // the one textarea, faked
const mkTa = (value, pos) => ({
  value, selectionStart: pos==null?value.length:pos, selectionEnd: pos==null?value.length:pos,
  focus(){}, setSelectionRange(a,b){ this.selectionStart=a; this.selectionEnd=b; },
});
const doc = {
  getElementById: id => id==='comp-text' ? ta : (id==='mention-btn' ? {} : null),
  querySelector: () => null,
  querySelectorAll: () => [],
};
const build = () => new Function('boardPeople','meId','closeCellPops','document',
  `const Chat = {
     mentions: [], _mention: null, editing: null, _renders: 0,
     ${METHODS}
     _renderMentionMenu(){ this._renders++; },
     _float(){}, syncHL(){}, post(){ this._posted = true; }, saveDraft(){},
   }; return Chat;`)(
  also => {                                        // the real boardPeople's shape
    const out = PEOPLE.slice();
    (also||[]).forEach(id => { if(!out.some(u=>u.id===id)) out.push({id, name:'חבר אחר'}); });
    return out;
  },
  () => ME,
  () => {}, doc);

let Chat = build();
const reset = people => { PEOPLE = people; Chat = build(); };
// what a keystroke really does: the textarea takes the character, then oninput
const type = (text, pos) => { ta = mkTa(text, pos); Chat.onType({target: ta}); };
const open = () => !!(Chat._mention && Chat._mention.ctx);
const names = () => (Chat._mention ? Chat._mention.matches.map(u=>u.name) : []);
// Enter in the composer: did the menu take it, or does a newline happen?
const pressEnter = () => { let stopped=false; Chat.keydown({key:'Enter', target: ta, preventDefault(){stopped=true;}}); return stopped; };

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:''))); };

const SHELLY = {id:12, name:'שלי פיינברג'}, DANIT = {id:20, name:'דנית יגודה'}, AVI = {id:31, name:'Avi Levi'};

// ── writing a tag still offers the menu ──
reset([SHELLY, DANIT, AVI]);
type('@');
ck('a bare @ offers everyone on the board', open() && names().length===3, names().join('|'));
type('@של');
ck('and narrows as the name is typed', open() && names().join()==='שלי פיינברג', names().join('|'));
type('@שלי פיינ');
ck('a space inside the name does not end the query — names have spaces',
   open() && names().join()==='שלי פיינברג', names().join('|'));

// ── picking it, and then writing the message (the bug) ──
Chat.pickMention(12);
ck('picking writes the whole name and a space', ta.value==='@שלי פיינברג ', JSON.stringify(ta.value));
ck('the caret lands after that space', ta.selectionStart===ta.value.length, String(ta.selectionStart));
ck('the person is tagged', Chat.mentions.join()==='12', Chat.mentions.join());
ck('and the menu is shut', !open());

type('@שלי פיינברג ב');
ck('THE BUG: a letter typed after the tag does not reopen the menu', !open(), names().join('|'));
type('@שלי פיינברג בבקשה תסתכלי על הפריט');
ck('nor does a whole sentence', !open(), names().join('|'));
ck('and Enter is a newline again, not a second pick', pressEnter()===false);
ck('the sentence survives Enter untouched',
   ta.value==='@שלי פיינברג בבקשה תסתכלי על הפריט', JSON.stringify(ta.value));
ck('no one else got tagged along the way', Chat.mentions.join()==='12', Chat.mentions.join());

// ── and coming back to a finished tag (a re-render, a click back in) ──
type('@שלי פיינברג ');
ck('a finished tag does not reopen the menu by itself', !open(), names().join('|'));
ck('so Enter there starts a line instead of silently picking the same person again',
   pressEnter()===false, JSON.stringify(ta.value));

// ── which is what the newline workaround was for ──
type('@שלי פיינברג\nבבקשה תסתכלי');
ck('the old workaround (a line of its own) still behaves', !open());

// ── a second tag on the same line still works ──
type('@שלי פיינברג תודה @דנ');
ck('a second tag after a finished one opens', open() && names().join()==='דנית יגודה', names().join('|'));
Chat.pickMention(20);
ck('and it replaces only its own @…, leaving the message alone',
   ta.value==='@שלי פיינברג תודה @דנית יגודה ', JSON.stringify(ta.value));
ck('both people are tagged now', Chat.mentions.join()==='12,20', Chat.mentions.join());

// ── going back to fix a tag ──
type('@שלי פיינברג בבקשה', 3);       // caret inside the name itself
ck('a caret moved back into the tag offers the menu again', open(), names().join('|'));

// ── one name being the start of another ──
reset([{id:9, name:'שלי'}, SHELLY]);
type('@שלי ');
ck('a short name that is the start of a longer one keeps the menu open',
   open() && names().join()==='שלי,שלי פיינברג', names().join('|'));
type('@שלי פיינברג ');
ck('...and closes once the longer one is written in full', !open(), names().join('|'));
reset([{id:9, name:'שלי'}, DANIT]);
type('@שלי ');
ck('a short name nobody extends ends the tag at its space', !open(), names().join('|'));

// ── a name nobody has ──
reset([SHELLY, DANIT]);
type('@מישהו');
ck('an unknown word still says so while it is one word',
   open() && names().length===0, names().join('|'));
type('@מישהו אחר לגמרי');
ck('but the note does not sit there while a message is written', !open(), names().join('|'));

// ── a tag must start a word, or an email address becomes a menu ──
type('shellyf@mashcal');
ck('an email address is not a tag', !open(), names().join('|'));

// ── case, for the Latin names on the board ──
reset([AVI, DANIT]);
type('@avi levi ');
ck('a name typed in another case still ends the tag', !open(), names().join('|'));
type('@Avi');
ck('and matching is still case-insensitive while typing',
   open() && names().join()==='Avi Levi', names().join('|'));

// ── the menu, while it IS open, still takes Enter (that is how you pick) ──
reset([SHELLY]);
type('@של');
ck('Enter picks while the menu is open', pressEnter()===true);
ck('and that pick is what lands in the box', ta.value==='@שלי פיינברג ', JSON.stringify(ta.value));

// ── and the writer is never one of the names offered ───────────────────────
{
  reset([{id:1,name:'דנה לוי'},{id:2,name:'רינה כהן'}]);
  ME = 2;                                   // "רינה כהן" is the one typing
  type('@רינה');
  ck('typing the start of your own name offers nobody', open() && names().length===0,
     names().join());
  type('@דנה');
  ck('...while somebody else is offered as before', names().join()==='דנה לוי', names().join());
  ME = 0;
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
