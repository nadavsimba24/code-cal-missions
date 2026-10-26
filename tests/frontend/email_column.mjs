/* The e-mail column, as a type of its own rather than text that happens to
   hold an address.

   Two things separate it from a text column, and both are the reason it
   exists: the address reads left-to-right on a right-to-left board, and it is
   a link you can actually write to. A third is what it refuses — an address
   that is not an address is not stored, because a mailto: built on a typo is a
   dead link that looks live.
   Driven by tests/test_email_column.py. */
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
function grabConst(name, open, close){
  const m = new RegExp(`^const ${name}=\\${open}`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf(open,m.index), d=0;
  for(let j=i;j<src.length;j++){
    if(src[j]===open)d++; else if(src[j]===close){d--; if(!d) return src.slice(m.index,j+1)+';'; }
  }
}

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── it is offered as a type at all ─────────────────────────────────────────
const {COLUMN_TYPES, COL_DEFAULTS, FORM_FIELD_TYPE_HE} = new Function(
  [grabConst('COLUMN_TYPES','[',']'), grabConst('COL_DEFAULTS','{','}'),
   /^const FORM_FIELD_TYPE_HE=.*$/m.exec(src)[0],
   'return {COLUMN_TYPES, COL_DEFAULTS, FORM_FIELD_TYPE_HE};'].join('\n'))();

const t = COLUMN_TYPES.find(c=>c.type==='email');
ck('the type is offered in the column picker', !!t);
ck('with a name, an icon and a description',
   !!(t && t.he && t.ic && t.desc), JSON.stringify(t));
ck('a new e-mail column starts with a title of its own', !!COL_DEFAULTS.email);
ck('and a form field on one is labelled, not left as a bare type name',
   !!FORM_FIELD_TYPE_HE.email);
ck('no other type answers to the same name',
   COLUMN_TYPES.filter(c=>c.he===t.he).length===1);

// ── the address is refused, kept, or written to ────────────────────────────
const EMAIL_RE = new Function('return '+/const EMAIL_RE=(\/.*?\/);/.exec(src)[1])();
for(const good of ['a@b.co','reuto@mashcal.co.il','bhaa@abugosh.muni.il'])
  ck(`an address is an address: ${good}`, EMAIL_RE.test(good));
for(const bad of ['לא מייל','a@b','a b@c.co','@b.co','a@','plain text'])
  ck(`and this is not: ${JSON.stringify(bad)}`, !EMAIL_RE.test(bad));

// what the cell does with each
const calls=[]; const toasts=[];
const RE_SRC = /const EMAIL_RE=\/.*?\/;/.exec(src)[0];
const setEmailCell = new Function('setCell','toast','refreshRow',
  RE_SRC+'\n'+grab('setEmailCell')+'\nreturn setEmailCell;')(
    (...a)=>calls.push(a), m=>toasts.push(m), ()=>{});

await setEmailCell(7,'col_x',{value:' a@b.co ',focus(){}});
ck('a good address is trimmed and saved',
   calls.length===1 && calls[0][2]==='a@b.co', JSON.stringify(calls));
await setEmailCell(7,'col_x',{value:'',focus(){}});
ck('clearing the cell clears the value rather than storing an empty string',
   calls.length===2 && calls[1][2]===null, JSON.stringify(calls[1]));

calls.length=0;
await setEmailCell(7,'col_x',{value:'לא מייל',focus(){}});
ck('a typo is refused, not stored', calls.length===0);
ck('and the person is told why', toasts.length===1 && /דוא/.test(toasts[0]), toasts[0]);
let focused=false;
await setEmailCell(7,'col_x',{value:'oops',focus(){focused=true;}});
ck('the cell keeps the keystrokes so they can be corrected', focused);

// ── how the cell is drawn ──────────────────────────────────────────────────
/* the branch is one line, and its template literal has nested backticks —
   matching to the end of the line is the only reading that survives them */
const cell = /^\s*if\(c\.type==='email'\).*$/m.exec(src);
ck('the grid draws an e-mail cell of its own', !!cell);
const html = cell ? cell[0] : '';
ck('the address reads left-to-right on this right-to-left board',
   /direction:ltr/.test(src.slice(src.indexOf('.cc-mailwrap'), src.indexOf('.cc-mailwrap')+220)));
ck('and it is a link you can write to, not just text',
   /href="mailto:/.test(html));
ck('the envelope appears only once there is an address',
   /\$\{v\?`<a class="cc-mail"/.test(html));
ck('clicking the envelope opens the mail client instead of editing the cell',
   /event\.stopPropagation\(\)/.test(html));
ck('the value goes through the setter that validates it',
   /setEmailCell\(/.test(html) && !/setCell\(/.test(html));
ck('the browser is told what kind of field this is',
   /type="email"/.test(html));

// ── it leaves the board the way it came in ─────────────────────────────────
const exp = src.slice(src.indexOf("case 'text':"), src.indexOf("case 'text':")+140);
ck('an export writes the address, not [object Object]',
   /case 'email':/.test(exp), exp.slice(0,80));

// ── a type the server does not know must not vanish in silence ─────────────
/* The server keeps its own allow-list and drops anything outside it with a 200.
   A browser holding a newer index.html than the running server then offers a
   type that will be discarded, and the column simply never appears — which is
   indistinguishable, from the outside, from a broken picker. */
function grabAsync(name){
  const m=new RegExp(`^async function ${name}\\(`,'m').exec(src);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}
const saveWith=returned=>new Function('api','st','toast','refreshBoardItems','renderView','withMe',
  grabAsync('saveColumns')+'\nreturn saveColumns;')(
    async()=>({columns:returned}), {board:{id:1}}, t=>toasts.push(t), async()=>{}, ()=>{}, x=>x);

toasts.length=0;
await saveWith([{type:'text'},{type:'email'}])([{type:'text'},{type:'email'}]);
ck('a save the server kept in full says nothing', toasts.length===0, JSON.stringify(toasts));

toasts.length=0;
await saveWith([{type:'text'}])([{type:'text'},{type:'email'}]);
ck('a column the server dropped is named rather than lost',
   /email/.test(toasts[0]||''), JSON.stringify(toasts));

toasts.length=0;
await saveWith([{type:'text'}])([{type:'text'},{type:'text'}]);
ck('one of two columns of the same type going missing still counts',
   /text/.test(toasts[0]||''), JSON.stringify(toasts));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
