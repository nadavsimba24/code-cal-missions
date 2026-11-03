/* Reply, from anywhere in the conversation — and it tags who it answers.

   "הגב" was offered on a top-level message only. An answer to an answer had
   nowhere to go: the conversation's second level was where it stopped being
   a conversation, and the way round it was to write a new message at the
   bottom and name the person by hand.

   Two things are pinned here and the second is the one that matters.

   The button is on every message, and a reply to a reply joins the thread's
   ROOT rather than nesting under it. The thread stays one level deep because
   who is answering whom is carried by the tag and not by indentation — the
   same shape the importer already builds, and the only one that survives a
   phone screen at the fourth nesting.

   And the box opens with the author of the message being answered already
   tagged, registered in `mentions` as well as typed, so the notification
   does not depend on the text surviving an edit. Without it a reply three
   messages down reads as a remark to nobody, and the person it answers is
   not told at all — until now a reply reached them only if they happened to
   type their own name into it.

   Three it must NOT tag: an imported message, whose author has no account
   here to notify; yourself, which the server discards anyway; and somebody
   no longer a member of the board, who would be filtered out server-side and
   whose name in the box would be a promise nobody keeps.

   Driven by tests/test_reply_tags_whoever_it_answers.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const at = src.indexOf('const Chat = {');
const chatSrc = src.slice(at, src.indexOf('\n};', at)) + '\n};';

const ME = 7;
const PEOPLE = [{id:7,name:'רינה כהן'},{id:8,name:'דנה לוי'},{id:9,name:'יואב'}];
/* One thread: a root by דנה, a reply by יואב, a reply of mine, and a reply
   from somebody who has since left the board. Plus an imported message whose
   author is not a user here at all. */
const COMMENTS=[
  {id:1, user_id:8, user_name:'דנה לוי', parent_id:null, content:'שאלה', replies:[
    {id:2, user_id:9, user_name:'יואב',     parent_id:1, content:'תשובה'},
    {id:3, user_id:7, user_name:'רינה כהן', parent_id:1, content:'שלי'},
    {id:4, user_id:12,user_name:'מי שעזב',  parent_id:1, content:'ישנה'},
  ]},
  {id:5, user_id:null, user_name:'שם מהקובץ', parent_id:null, content:'יובאה',
   origin:{source:'monday',author:'שם מהקובץ'}, replies:[]},
];

function chat(){
  let area={value:'',focus(){},setSelectionRange(){}};
  const c = new Function('boardPeople','meId','st','document','esc','avatarInner',
                         'closeCellPops','openCellPop','canComment','fdatetimeY',
                         'ROLE_HE','toast',
                         chatSrc + '\nreturn Chat;')(
    () => PEOPLE.slice(),
    () => ME,
    {users: PEOPLE.slice(), board:{id:1, members: PEOPLE.slice()}, me:{id:ME,role:'member'}},
    {getElementById: id => (id==='comp-text'?area:null), querySelector: () => null,
     querySelectorAll: () => []},
    x => String(x == null ? '' : x).replace(/[&<>"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch])),
    () => '', () => {}, () => {},
    () => true, d => String(d), {}, () => {});
  c.mentions = [];
  c.comments = COMMENTS;
  c._commentsById = {};
  const flat = arr => arr.forEach(x => { c._commentsById[x.id]=x; if(x.replies) flat(x.replies); });
  flat(COMMENTS);
  c.syncHL = () => {};
  c.saveDraft = () => {};
  // the real one re-renders and resolves; the harness only needs the promise
  c.renderChat = () => Promise.resolve();
  c._area = area;
  return c;
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,300):''))); };

// ── the button is on every message ────────────────────────────────────────
{
  const c = chat();
  const root  = c.commentHTML(COMMENTS[0], false);
  const reply = c.commentHTML(COMMENTS[0].replies[0], true);
  ck('a top-level message offers הגב', /Chat\.startReply\(1,/.test(root), root);
  ck('and so does a reply', /Chat\.startReply\(2,/.test(reply), reply);
  ck('…which it did not before', !/isReply&&canComment/.test(src));
}

// ── a reply to a reply joins the thread's root ────────────────────────────
{
  const c = chat();
  await c.startReply(2,'יואב');
  ck('the reply is filed under the root, not under the reply', c.replyTo===1, c.replyTo);
  ck('…and the line above the box names who is being answered',
     c.replyToName==='יואב', c.replyToName);
}
{
  const c = chat();
  await c.startReply(1,'דנה לוי');
  ck('replying to a root message files it under that message', c.replyTo===1, c.replyTo);
}

// ── and the person being answered is tagged ───────────────────────────────
{
  const c = chat();
  await c.startReply(2,'יואב');
  ck('the box opens with them tagged', c._area.value==='@יואב ', JSON.stringify(c._area.value));
  ck('…and the tag is registered, not only typed', c.mentions.includes(9), c.mentions);
}
{
  const c = chat();
  await c.startReply(1,'דנה לוי');
  ck('a root message tags its own author', c._area.value==='@דנה לוי ', JSON.stringify(c._area.value));
  ck('…by id as well', c.mentions.includes(8), c.mentions);
}
{
  const c = chat();
  c._area.value='כבר כתבתי משהו';
  await c.startReply(2,'יואב');
  ck('the tag goes in front of what was already typed',
     c._area.value==='@יואב כבר כתבתי משהו', JSON.stringify(c._area.value));
}
{
  const c = chat();
  await c.startReply(2,'יואב');
  await c.startReply(2,'יואב');
  ck('replying to the same person twice does not tag them twice',
     c._area.value==='@יואב ' && c.mentions.filter(x=>x===9).length===1,
     JSON.stringify(c._area.value)+' '+c.mentions);
}

// ── the three it must not tag ─────────────────────────────────────────────
{
  const c = chat();
  await c.startReply(3,'רינה כהן');          // my own message
  ck('answering yourself tags nobody', c._area.value==='' && !c.mentions.length,
     JSON.stringify(c._area.value)+' '+c.mentions);
  ck('…but the reply still goes to the thread', c.replyTo===1, c.replyTo);
}
{
  const c = chat();
  await c.startReply(4,'מי שעזב');           // no longer on the board
  ck('somebody off the board is not tagged', c._area.value==='' && !c.mentions.length,
     JSON.stringify(c._area.value)+' '+c.mentions);
  ck('…and replying to them still works', c.replyTo===1, c.replyTo);
}
{
  const c = chat();
  await c.startReply(5,'שם מהקובץ');         // imported, no account here
  ck('an imported message tags nobody', c._area.value==='' && !c.mentions.length,
     JSON.stringify(c._area.value)+' '+c.mentions);
  ck('…and is still answerable', c.replyTo===5, c.replyTo);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
