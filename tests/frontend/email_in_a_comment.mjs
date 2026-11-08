/* An e-mail address in an item's conversation is an address, not a tag.

   The comment renderer ran three passes over the same line: links, then tags.
   The tag pass had only "@" to go on, so in "shelly@mashcal.co.il" it coloured
   "@mashcal" — up to the first dot — in tag blue, which reads as a tag of
   somebody who does not exist, and left the address itself dead text. The same
   bare "@" also reached inside the href the link pass had just written.

   So: one pass, each stretch of the line claimed once; an address becomes a
   mailto: link; and a tag has to start a word, which is the rule mentionCtx
   already applies before it offers the tag menu.

   Runs the real inline / markMentions / highlightMentions / renderContent and
   the real esc out of index.html. Driven by tests/test_email_in_a_comment.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

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
// the address pattern is a property rather than a method, and it is the thing
// under test — taken from the file too, never retyped here
const MAIL = /^  MAIL:(\/.*\/),$/m.exec(chat);
if(!MAIL) throw new Error('not found: MAIL');

const METHODS = ['inline','markMentions','highlightMentions','renderContent'].map(grabMethod).join('\n');
const ESC = /^const esc = .*$/m.exec(src)[0];

let PEOPLE = [];
const Chat = new Function('boardPeople',
  ESC + `; const Chat = { MAIL:${MAIL[1]}, ${METHODS} }; return Chat;`)(() => PEOPLE);

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the address itself ────────────────────────────────────────────────────
PEOPLE = [{id:1,name:'שלי פיינברג'}];
{
  const h = Chat.inline('shelly@mashcal.co.il');
  ck('an address becomes a mailto link',
     h === '<a href="mailto:shelly@mashcal.co.il" dir="ltr">shelly@mashcal.co.il</a>', h);
  ck('and carries no tag highlight at all', !h.includes('class="mention"'), h);
}
{
  const h = Chat.inline('שלחי ל shelly@mashcal.co.il בבקשה');
  ck('an address inside a Hebrew sentence is linked where it stands',
     h === 'שלחי ל <a href="mailto:shelly@mashcal.co.il" dir="ltr">shelly@mashcal.co.il</a> בבקשה', h);
}
{
  // the dash of "ל-" is a character an address may hold, so it used to be
  // swallowed into the local part and the link began one character too early
  const h = Chat.inline('כתבי ל-dana@mashcal.co.il.');
  ck('a Hebrew prefix hyphen stays outside the address',
     h === 'כתבי ל-<a href="mailto:dana@mashcal.co.il" dir="ltr">dana@mashcal.co.il</a>.', h);
}
{
  const h = Chat.inline('a@b.co, c@d.co');
  ck('two addresses on a line are two links',
     h === '<a href="mailto:a@b.co" dir="ltr">a@b.co</a>, <a href="mailto:c@d.co" dir="ltr">c@d.co</a>', h);
}
{
  ck('a bare "@" with no domain is not an address',
     !Chat.inline('מחיר @ 50').includes('mailto:'), Chat.inline('מחיר @ 50'));
}

// ── tags still work, and still only where a tag can start ─────────────────
{
  const h = Chat.inline('היי @שלי פיינברג מה קורה');
  ck('a full name is still coloured as a tag',
     h === 'היי <span class="mention">@שלי פיינברג</span> מה קורה', h);
}
{
  const h = Chat.inline('@שלי פיינברג בבקשה');
  ck('...including at the very start of a line',
     h.startsWith('<span class="mention">@שלי פיינברג</span>'), h);
}
{
  const h = Chat.inline('(@שלי פיינברג)');
  ck('...and after a bracket, which no address ends with',
     h === '(<span class="mention">@שלי פיינברג</span>)', h);
}
{
  const h = Chat.inline('@דני ו@שלי פיינברג');
  ck('two tags in a row are both coloured',
     (h.match(/class="mention"/g)||[]).length===2, h);
}

// ── links, and the tag pass that used to reach inside them ────────────────
{
  const h = Chat.inline('https://monday.com/boards/@me/1');
  ck('a URL is one link and nothing is coloured inside it',
     h === '<a href="https://monday.com/boards/@me/1" target="_blank">https://monday.com/boards/@me/1</a>', h);
}
{
  const h = Chat.inline('https://x.co/u/a@b.co');
  ck('an address inside a URL stays part of the URL',
     h === '<a href="https://x.co/u/a@b.co" target="_blank">https://x.co/u/a@b.co</a>', h);
}
{
  const h = Chat.inline('ראי https://x.co ואז a@b.co');
  ck('a link and an address on one line are each themselves',
     h === 'ראי <a href="https://x.co" target="_blank">https://x.co</a> ואז <a href="mailto:a@b.co" dir="ltr">a@b.co</a>', h);
}

// ── nothing typed gets through unescaped ──────────────────────────────────
{
  const h = Chat.inline('<img src=x onerror=alert(1)> a@b.co');
  ck('markup in a comment is still escaped',
     h.startsWith('&lt;img src=x onerror=alert(1)&gt;') && !h.includes('<img'), h);
}
{
  const h = Chat.inline('"><script>bad()</script>@שלי פיינברג');
  ck('...and an escaped quote before a tag does not break out of anything',
     !h.includes('<script'), h);
}

// ── the live composer answers the same question ───────────────────────────
{
  ck('the composer does not light up an address either',
     !Chat.highlightMentions('shelly@mashcal.co.il').includes('class="mention"'),
     Chat.highlightMentions('shelly@mashcal.co.il'));
  ck('...and still lights up a tag',
     Chat.highlightMentions('@שלי פיינברג').includes('class="mention"'));
  /* The overlay sits character-for-character behind the textarea, so the
     highlighted copy must hold exactly the text that was typed — anything
     added or dropped slides the colour off the word it belongs to. */
  const txt='כתבי ל shelly@mashcal.co.il ול@שלי פיינברג';
  const plain=Chat.highlightMentions(txt).replace(/<[^>]+>/g,'');
  ck('the composer overlay still mirrors the text exactly', plain===txt, JSON.stringify(plain));
}

// ── a whole comment, through renderContent ────────────────────────────────
{
  const h = Chat.renderContent('☑ לשלוח ל dana@mashcal.co.il\n@שלי פיינברג תודה', 5);
  ck('an address inside a checklist row is a link too', h.includes('mailto:dana@mashcal.co.il'), h);
  ck('...and the tag on the next line is still a tag', h.includes('class="mention"'), h);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
