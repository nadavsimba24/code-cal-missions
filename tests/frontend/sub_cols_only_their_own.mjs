/* Which columns a sub-item row shows, when the board gives them columns of
   their own.

   board.sub_cols is the SHARED subset — the item columns the sub-items also
   show — and board.sub_only is the set that exists on sub-item rows and nowhere
   else. An empty shared subset used to mean one thing only: "never configured,
   inherit every item column". That is right for a stale ["item"], and wrong for
   a monday sub-item board, whose columns are its own by design: the sub-items
   then showed a dozen empty item columns in front of the ones that are filled.

   Runs the real _subColumns out of index.html. Driven by
   tests/test_sub_cols_only_their_own.py. */
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
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(x?'  → '+x:''))); };

const col = (id,title) => ({kind:'custom', id, col:{id,title,type:'text'}});
const NAME = {kind:'builtin', id:'item', key:'item', label:'פריט'};
const ITEMS = [NAME, col('owner','אחראי'), col('budget','תקציב')];
const ONLY  = [col('stage','שלב'), col('hours','שעות')];

const st = {board:{}};
const run = board => {
  st.board = board;
  const f = new Function('orderedColumns','subOnlyColumns','st',
                          grab('_subColumns')+'; return _subColumns;')(
    ()=>ITEMS.slice(), ()=>ONLY.filter(c=>((st.board.sub_only)||[]).map(String).includes(String(c.id))), st);
  return f().map(c=>c.kind==='builtin'?c.label:c.col.title);
};

// never configured → the sub-items mirror the item columns, as before
ck('a board that never configured its sub-items inherits the item columns',
   run({}).join('|')==='פריט|אחראי|תקציב', run({}).join('|'));

// a shared subset, as the column picker saves it
ck('a configured subset is the name plus what was picked, and its own columns after',
   run({sub_cols:['item','owner'], sub_only:['stage']}).join('|')==='פריט|אחראי|שלב',
   run({sub_cols:['item','owner'], sub_only:['stage']}).join('|'));

// THE CASE: nothing shared, and columns of their own
const own = run({sub_cols:['item'], sub_only:['stage','hours']});
ck('sub-items that share nothing with the item show their name and their own columns',
   own.join('|')==='פריט|שלב|שעות', own.join('|'));
ck('...and not a single item column they have no value for',
   !own.includes('אחראי') && !own.includes('תקציב'), own.join('|'));

// and the protection that case rode in on is still there: an empty subset with
// no columns of its own is a stale list, not an answer
ck('an empty subset with no columns of its own still inherits, so nothing vanishes',
   run({sub_cols:['item']}).join('|')==='פריט|אחראי|תקציב', run({sub_cols:['item']}).join('|'));
ck('...and so does a subset whose ids were all since removed',
   run({sub_cols:['item','gone']}).join('|')==='פריט|אחראי|תקציב',
   run({sub_cols:['item','gone']}).join('|'));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
