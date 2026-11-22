/* The rows on screen, brought into line with a rename the server just ran.

   Renaming a status option is one server call over the whole board now, and
   one server call comes back with no rows. The old per-cell loop got the grid
   for free — it wrote each cell locally on its way to the PATCH — so without
   _csAdoptRenames the board goes on printing the OLD word on every row already
   drawn until something re-fetches it. Re-fetching is not available on a board
   of twenty-one thousand items, and it is not needed: the rewrite is a pure
   relabelling whose result is known here exactly.

   Which makes this a local copy of a server rule, and the two have to agree.
   So the same three cell shapes the server handles are run through it here —
   a bare label, {label,color} with no id, and the whole option — matched by id
   first and by the old label only then. The two that matter most are the ones
   no test had before: a bare string has to come out as the full option, and a
   cell sitting on a DIFFERENT option has to be left completely alone. Moving
   that one would be the browser showing a status change nobody made, over a
   server that did nothing of the kind.

   Driven by tests/test_a_renamed_status_reaches_every_cell.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d)return src.slice(m.index,j+1);} }
  throw new Error('unbalanced '+name);
}

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

const APPROVED={id:'o_app', label:'אושר סופית', color:'#00c875'};   // after the rename
const WAITING ={id:'o_wait',label:'ממתין',      color:'#fdab3d'};   // untouched

/* The real function, over the rows a test hands it. loadedRows() is what the
   grid is holding — one page of fifty on a paged board, the whole board on a
   small one; either way it is a list of items with custom_fields, and the
   sub-items under them are rows on screen too. */
function adopt(rows){
  const fn = new Function('loadedRows', grab('_csAdoptRenames')+'\nreturn _csAdoptRenames;')(()=>rows);
  const ren = new Map([['אושר', APPROVED]]);
  fn('col_st', ren);
  return rows;
}
const cell = t => t.custom_fields.col_st;
const same = (a,b) => JSON.stringify(a)===JSON.stringify(b);

// ── the three shapes a cell is written in ─────────────────────────────────
{
  const rows=[
    {id:1, custom_fields:{col_st:'אושר'}},                                  // a bare label
    {id:2, custom_fields:{col_st:{label:'אושר', color:'#00c875'}}},          // no id
    {id:3, custom_fields:{col_st:{id:'o_app', label:'אושר', color:'#00c875'}}},
  ];
  adopt(rows);
  ck('a cell holding nothing but the old word becomes the whole option',
     same(cell(rows[0]), APPROVED), JSON.stringify(cell(rows[0])));
  ck('a cell with a label and a colour and no id follows too',
     same(cell(rows[1]), APPROVED), JSON.stringify(cell(rows[1])));
  ck('and one that already carries the id is matched by it',
     same(cell(rows[2]), APPROVED), JSON.stringify(cell(rows[2])));
}

// ── matched by id FIRST, which is the half a label cannot do ──────────────
{
  // the server resolves by id before label, and so does this: a cell carrying
  // the renamed option's id is that option whatever word it happens to hold
  const rows=[{id:1, custom_fields:{col_st:{id:'o_app', label:'מילה ישנה אחרת',
                                            color:'#00c875'}}}];
  adopt(rows);
  ck('a cell carrying the option id follows even when its label says something else',
     same(cell(rows[0]), APPROVED), JSON.stringify(cell(rows[0])));
}

// ── a cell on a different option is not this rename's business ────────────
{
  const rows=[
    {id:1, custom_fields:{col_st:{id:'o_wait', label:'ממתין', color:'#fdab3d'}}},
    {id:2, custom_fields:{col_st:'ממתין'}},
    {id:3, custom_fields:{col_st:'נדחה'}},
    {id:4, custom_fields:{col_st:null}},
    {id:5, custom_fields:{col_st:''}},
    {id:6, custom_fields:{other:'אושר'}},            // the old word in ANOTHER column
    {id:7},                                          // a row with no cells at all
  ];
  adopt(rows);
  ck('a cell on another option is left exactly as it was',
     same(cell(rows[0]), WAITING) && cell(rows[1])==='ממתין' && cell(rows[2])==='נדחה',
     JSON.stringify(rows.slice(0,3)));
  ck('an empty cell is not given a status it never had',
     cell(rows[3])===null && cell(rows[4])==='',
     JSON.stringify([cell(rows[3]), cell(rows[4])]));
  ck('the same word in a different column is not touched',
     rows[5].custom_fields.other==='אושר' && rows[5].custom_fields.col_st===undefined);
  ck('a row with no custom_fields does not throw', rows[6].custom_fields===undefined);
}

// ── sub-items are rows on screen too ──────────────────────────────────────
{
  const rows=[{id:1, custom_fields:{col_st:'אושר'},
               subtasks:[{id:11, custom_fields:{col_st:'אושר'}},
                         {id:12, custom_fields:{col_st:'ממתין'}}]}];
  adopt(rows);
  ck('a sub-item on screen follows the rename as its parent does',
     same(rows[0].subtasks[0].custom_fields.col_st, APPROVED),
     JSON.stringify(rows[0].subtasks[0].custom_fields.col_st));
  ck('...and a sub-item on another option is still left alone',
     rows[0].subtasks[1].custom_fields.col_st==='ממתין');
}

// ── two renames at once ───────────────────────────────────────────────────
{
  const rows=[{id:1, custom_fields:{col_st:'אושר'}},
              {id:2, custom_fields:{col_st:'ממתין'}}];
  const fn = new Function('loadedRows', grab('_csAdoptRenames')+'\nreturn _csAdoptRenames;')(()=>rows);
  fn('col_st', new Map([['אושר', APPROVED], ['ממתין', {id:'o_wait', label:'בהמתנה', color:'#fdab3d'}]]));
  ck('a sitting that renamed two options carries both',
     same(cell(rows[0]), APPROVED)
       && same(cell(rows[1]), {id:'o_wait', label:'בהמתנה', color:'#fdab3d'}),
     JSON.stringify([cell(rows[0]), cell(rows[1])]));
}

// ── and it writes the shape the server stores ─────────────────────────────
{
  const rows=[{id:1, custom_fields:{col_st:'אושר'}}];
  adopt(rows);
  ck('the cell is written as {id,label,color} and nothing else',
     Object.keys(cell(rows[0])).sort().join()==='color,id,label',
     JSON.stringify(cell(rows[0])));
  // …so the NEXT rename finds it by id. Run the same rename again: idempotent,
  // exactly as the server's second call writes nothing.
  adopt(rows);
  ck('running it twice leaves the same cell', same(cell(rows[0]), APPROVED));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
