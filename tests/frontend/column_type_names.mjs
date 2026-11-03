/* What the column types are called, and that no two of them collide.

   The "חשבונות" type is now "קישור". The word was already spoken for — the
   cross-board type's default title was "קישור" too — so these check the two
   stayed apart after the rename, and that nothing user-facing still says
   "חשבונות" for a type that is no longer called that.
   Driven by tests/test_column_type_names.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabConst(name, open, close){
  const m = new RegExp(`^const ${name}=\\${open}`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf(open,m.index), d=0;
  for(let j=i;j<src.length;j++){
    if(src[j]===open)d++; else if(src[j]===close){d--; if(!d) return src.slice(m.index,j+1)+';'; }
  }
}
const TYPES    = grabConst('COLUMN_TYPES','[',']');
const DEFAULTS = grabConst('COL_DEFAULTS','{','}');
const FIELDS   = /^const FORM_FIELD_TYPE_HE=.*$/m.exec(src)[0];

const {COLUMN_TYPES, COL_DEFAULTS, FORM_FIELD_TYPE_HE} =
  new Function([TYPES, DEFAULTS, FIELDS,
                'return {COLUMN_TYPES, COL_DEFAULTS, FORM_FIELD_TYPE_HE};'].join('\n'))();

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

const accounts = COLUMN_TYPES.find(c=>c.type==='accounts');
const connect  = COLUMN_TYPES.find(c=>c.type==='connect');

ck('the accounts type is called קישור', accounts && accounts.he==='קישור', accounts&&accounts.he);
ck('a new one is titled that too', COL_DEFAULTS.accounts==='קישור', COL_DEFAULTS.accounts);
ck('the form builder calls it the same thing', FORM_FIELD_TYPE_HE.accounts==='קישור', FORM_FIELD_TYPE_HE.accounts);
ck('and its own cell editor no longer says חשבון', !/<h2>חשבון מקושר<\/h2>/.test(src));

// the word was already taken
ck('the cross-board type keeps its own name', connect && connect.he==='קישור בין לוחות', connect&&connect.he);
ck('and no longer defaults to the same title as this one',
   COL_DEFAULTS.connect!==COL_DEFAULTS.accounts,
   `${COL_DEFAULTS.connect} / ${COL_DEFAULTS.accounts}`);

// nothing else collides either
const labels = COLUMN_TYPES.map(c=>c.he);
ck('every type in the picker has a distinct name',
   new Set(labels).size===labels.length,
   labels.filter((l,i)=>labels.indexOf(l)!==i).join(', '));
const titles = Object.values(COL_DEFAULTS);
ck('and every default column title is distinct',
   new Set(titles).size===titles.length,
   titles.filter((t,i)=>titles.indexOf(t)!==i).join(', '));

/* A type the picker offers but COL_DEFAULTS never named was born under its own
   key: a long-text column on a Hebrew board came out headed "long_text", and
   "phone" was one entry short of the same. The title a new column starts with
   now falls back to the Hebrew name of its type. */
ck('a new column falls back to the Hebrew name of its type, not to the key',
   /const heName=\(COLUMN_TYPES\.find\(c=>c\.type===type\)\|\|\{\}\)\.he/.test(src) &&
   /const col=\{type,title:COL_DEFAULTS\[type\]\|\|heName\|\|type\}/.test(src));
const nameOf = t => COL_DEFAULTS[t] || (COLUMN_TYPES.find(c=>c.type===t)||{}).he;
ck('so a long-text column is headed טקסט ארוך', nameOf('long_text')==='טקסט ארוך', nameOf('long_text'));
ck('and a phone column טלפון', nameOf('phone')==='טלפון', nameOf('phone'));
const naked = COLUMN_TYPES.filter(c=>!nameOf(c.type));
ck('and no type in the picker is left to be born under its English key',
   naked.length===0, naked.map(c=>c.type).join(', '));

// the old word is still findable, because the type picker searches the blurb
ck('searching חשבון still finds it, through its description',
   (accounts.he+' '+accounts.desc+' '+accounts.type).includes('חשבון'),
   accounts.desc);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
