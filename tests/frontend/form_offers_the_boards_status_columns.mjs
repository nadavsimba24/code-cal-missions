/* אילו שדות הטופס מציע — ולמה עמודה שאינה על הלוח אינה אחד מהם.

   FormEditor.available() is the list somebody picks a question from. The
   five built-in fields were offered unconditionally, and that is wrong on
   any board whose admin has taken one of them off — and wrong on EVERY
   imported board, because the monday import hides אחראים, סטטוס, עדיפות and
   תאריך יעד outright: the file fills none of them, and left showing they are
   four columns of "טרם הוגדר" standing in front of the board that was
   actually imported.

   What that cost, in the words it was reported in: a board whose own
   "עדיפות" is a status column offered TWO fields called עדיפות — the hidden
   built-in first, the real column under it, nothing on either row to tell
   them apart. Choosing the top one bound the question to a column the board
   does not draw.

   Pinned here: a hidden built-in is not offered, "שם הפריט" is never
   dropped, every status column of the board IS offered, and a question
   already bound to a built-in that was hidden afterwards is left alone.

   Driven by tests/test_form_offers_the_boards_status_columns.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabConst(name){
  const m = new RegExp(`^const ${name}\\s*=`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  let d=0;
  for(let j=m.index;j<src.length;j++){
    const ch=src[j];
    if('([{'.includes(ch))d++;
    else if(')]}'.includes(ch))d--;
    else if(ch===';'&&d===0) return src.slice(m.index,j+1);
  }
  throw new Error('unbalanced: const '+name);
}
function grabMethod(name){
  const m = new RegExp(`^  ${name}\\(\\)\\{`,'m').exec(src);
  if(!m) throw new Error('not found: method '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){
    if(src[j]==='{')d++;
    else if(src[j]==='}'){d--; if(!d) return 'function '+src.slice(m.index+2,j+1);}
  }
  throw new Error('unbalanced: method '+name);
}

const COLS=[
  {id:'col_a',type:'status', title:'עדיפות',      options:[{id:'o1',label:'גבוהה'}]},
  {id:'col_b',type:'status', title:'סטטוס טיפול'},
  {id:'col_c',type:'text',   title:'מבקש'},
  {id:'col_d',type:'formula',title:'חישוב'},
];

/* `available` is a method on FormEditor and reads `this.form`, so it is
   called with a stand-in carrying the components already in the form. */
function offered({hidden=[], cols=COLS, components=[]}={}){
  const st={board:{id:1, columns:cols, col_hidden:hidden, col_perms:{}}};
  /* The name-map is grabbed leniently so that a source without it fails on
     what it DOES — offering a column the board has taken off — rather than
     on a missing symbol. A failure that reads "not found: const" says
     nothing about the behaviour under test. */
  let nameMap;
  try{ nameMap=grabConst('FORM_BUILTIN_COL_KEY'); }
  catch(e){ nameMap='const FORM_BUILTIN_COL_KEY={};'; }
  const code=[grabConst('FORM_BUILTIN_FIELDS'), nameMap,
              grabConst('DERIVED_COLS'), grabMethod('available'),
              ';return available;'].join('\n');
  const fn=new Function('st','customColumns',code)(st,()=>cols);
  return fn.call({form:{components}});
}
const keys = o => o.map(f=>f.key);
const labels = o => o.map(f=>f.label);

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,240):''))); };

// ── a board that shows all five built-ins ─────────────────────────────────
{
  const got=offered();
  ck('every built-in is offered on a board that shows them all',
     ['title','assignees','status','priority','due_date'].every(k=>keys(got).includes(k)),
     JSON.stringify(keys(got)));
  ck('…alongside every column of the board a form can collect',
     keys(got).includes('col_a')&&keys(got).includes('col_b')&&keys(got).includes('col_c'),
     JSON.stringify(keys(got)));
  ck('…and never a derived column',!keys(got).includes('col_d'),JSON.stringify(keys(got)));
}

// ── the imported board from the report ────────────────────────────────────
{
  const got=offered({hidden:['assignees','status','priority','due']});
  ck('a hidden built-in is not offered',
     !keys(got).some(k=>['assignees','status','priority','due_date'].includes(k)),
     JSON.stringify(keys(got)));
  ck('there is exactly one field called עדיפות, and it is the board\'s column',
     labels(got).filter(l=>l==='עדיפות').length===1
       && got.find(f=>f.label==='עדיפות').key==='col_a',
     JSON.stringify(got));
  ck('שם הפריט survives — the board cannot hide the item itself',
     keys(got).includes('title'), JSON.stringify(keys(got)));
  ck('every status column of the board is still offered',
     ['col_a','col_b'].every(k=>keys(got).includes(k)), JSON.stringify(keys(got)));
}

// ── the due date, whose two names differ ──────────────────────────────────
{
  /* col_hidden calls it `due`; a form field calls it `due_date`. Looked up
     by the form's own key the lookup misses, and the one built-in whose two
     names differ goes on being offered after it was taken off the board. */
  const got=offered({hidden:['due']});
  ck('תאריך יעד is dropped although the board spells it `due`',
     !keys(got).includes('due_date'), JSON.stringify(keys(got)));
  ck('…and nothing else was dropped with it',
     ['assignees','status','priority'].every(k=>keys(got).includes(k)),
     JSON.stringify(keys(got)));
}

// ── a question already in the form ────────────────────────────────────────
{
  /* Hiding is reversible and a form outlives the board's layout. A question
     already bound to a built-in that was hidden afterwards must keep
     working — it is simply not offered a second time, which `used` already
     decided before any of this. */
  const got=offered({hidden:['priority'],
                     components:[{kind:'question',field_key:'priority'}]});
  ck('a built-in already asked for is not offered again',
     !keys(got).includes('priority'), JSON.stringify(keys(got)));
}

// ── a board with nothing hidden at all ────────────────────────────────────
{
  const got=offered({hidden:undefined});
  ck('a board with no col_hidden at all is not narrowed by this',
     keys(got).length===8, JSON.stringify(keys(got)));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
