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
const FIELDS   = /^const FIELD_TYPE_HE=.*$/m.exec(src)[0];

const {COLUMN_TYPES, COL_DEFAULTS, FIELD_TYPE_HE} =
  new Function([TYPES, DEFAULTS, FIELDS,
                'return {COLUMN_TYPES, COL_DEFAULTS, FIELD_TYPE_HE};'].join('\n'))();

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

const accounts = COLUMN_TYPES.find(c=>c.type==='accounts');
const connect  = COLUMN_TYPES.find(c=>c.type==='connect');

ck('the accounts type is called קישור', accounts && accounts.he==='קישור', accounts&&accounts.he);
ck('a new one is titled that too', COL_DEFAULTS.accounts==='קישור', COL_DEFAULTS.accounts);
ck('the form builder calls it the same thing', FIELD_TYPE_HE.accounts==='קישור', FIELD_TYPE_HE.accounts);
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

// the old word is still findable, because the type picker searches the blurb
ck('searching חשבון still finds it, through its description',
   (accounts.he+' '+accounts.desc+' '+accounts.type).includes('חשבון'),
   accounts.desc);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
