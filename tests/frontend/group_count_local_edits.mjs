/* The number on a group header stays true between one board fetch and the
   next.

   The board counts each group when it is opened and sends the figures with it,
   and on a board past the client threshold that figure is the ONLY thing that
   knows how big the group is: the rows arrive a page at a time, so anything
   recomputed from them is a count of what has scrolled past. But the board is
   deliberately not fetched again after every change — on a board this size the
   refetch is the flash the paging exists to avoid — so an item created,
   deleted or moved leaves the figure that arrived wrong by exactly one.

   Both halves are run here out of index.html: bumpGroupCount, which corrects
   the figure, and refreshGroupStats, which is what redraws the header after a
   row is taken out of the table in place. Before this they disagreed in the
   worst possible direction — the header of a group holding 942 items dropped
   to "2" the first time anything was deleted from it, because the redraw
   counted the rows it could see.

   Driven by tests/test_a_group_header_stays_true_between_board_fetches.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let d=0;
  for(let j=src.indexOf('{',m.index); j<src.length; j++){
    if(src[j]==='{')d++; else if(src[j]==='}'&&!--d) return src.slice(m.index,j+1);
  }
  throw new Error('unbalanced: '+name);
}
let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(x?'  → '+x:''))); };

/* The real functions, in the order they call each other. None of them touches
   the DOM except refreshGroupStats, which is handed a stub below: everything
   it reads is a count, and everything it writes is one node's text. */
const bundle = ['loadedRows','bumpGroupCount','groupCountKnown','groupSummaryHTML',
                'removeTaskLocal','refreshGroupStats'].map(grab).join('\n');

function scene({counts=null, rows=[], paged=false, narrowed=false, partial=false, gid=5}={}){
  const st={board:{id:1, tasks:paged?[]:rows.slice()}};
  if(counts) st.board.group_counts=counts;
  const Paged={on:paged, rows:paged?rows.slice():[], more:partial, matched:999};
  const chip={textContent:''}, line={outerHTML:''};
  const grp={querySelector:s=> s==='.g-count'?chip : s==='.g-sum'?line : null};
  const tbody={dataset:{gid:gid==null?'':String(gid)}, closest:()=>grp};
  const here=()=>(paged?Paged.rows:st.board.tasks).filter(t=>(t.group_id??null)===gid);
  const fns=new Function('st','Paged','boardIsNarrowed','boardRowsPartial','esc',
                         'groupsOf','battery',
                         bundle+'; return {removeTaskLocal,refreshGroupStats,bumpGroupCount};')(
    st, Paged, ()=>narrowed, ()=>partial, s=>String(s),
    ()=>[{id:gid, tasks:here()}], ()=>'');
  return {st, Paged, chip, line, tbody, ...fns,
          /* what the header says after a row has been dropped out of the table
             in place — the deletion path, end to end */
          deleteItem(id){ this.removeTaskLocal(id); this.refreshGroupStats(tbody);
                          return String(chip.textContent); }};
}

const rows=(n,gid=5,from=1)=>Array.from({length:n},(_,i)=>({id:from+i,group_id:gid,subtasks:[]}));

// ── the bug this was written for ─────────────────────────────────────────
/* A group of 942 on a paged board, two of whose rows have been scrolled to.
   Delete one: the group holds 941, and the two rows on screen have nothing to
   do with it. */
const big = scene({counts:{'5':942}, rows:rows(2), paged:true, partial:true});
const after = big.deleteItem(1);
ck('deleting a row off a paged board leaves the group\'s real size, less one',
   after==='941', after);
ck('...and not the number of rows this browser happens to be holding',
   after!=='1' && after!=='2', after);
ck('the board\'s own figure is what was corrected, so the next edit builds on it',
   big.st.board.group_counts['5']===941, JSON.stringify(big.st.board.group_counts));
ck('the folded line is redrawn from the same number',
   /941 פריטים/.test(big.line.outerHTML), big.line.outerHTML);
/* and a second deletion goes to 940, not back to 941 — the correction is
   applied to the corrected figure, which is the part that would not show up
   until somebody deleted twice */
ck('two deletions take it down two',
   big.deleteItem(2)==='940', String(big.chip.textContent));

// ── the ordinary board, where the rows are all there ─────────────────────
const small = scene({counts:{'5':3}, rows:rows(3)});
ck('a board holding all its rows counts down the same way',
   small.deleteItem(2)==='2', String(small.chip.textContent));
ck('...and its collapsed line still carries both halves',
   /2 פריטים \/ 0 תתי־פריטים/.test(small.line.outerHTML), small.line.outerHTML);

/* an older backend sends no counts at all; there the rows in hand are all
   there is, which is what this header always used to show */
const blind = scene({rows:rows(3)});
ck('with no figure from the server the header falls back to the rows it has',
   blind.deleteItem(2)==='2', String(blind.chip.textContent));

// ── what must NOT move the number ────────────────────────────────────────
const subs = scene({counts:{'5':942}, rows:rows(1), paged:true});
subs.Paged.rows[0].subtasks=[{id:77}];
const beforeSub = subs.deleteItem(77);
ck('a sub-item is not a row of any group, so deleting one changes no group count',
   subs.st.board.group_counts['5']===942, JSON.stringify(subs.st.board.group_counts));
ck('...and the header is redrawn with the figure it already had',
   beforeSub==='942', beforeSub);

const orphan = scene({counts:{'null':6}, rows:rows(2,null), paged:true, gid:null});
ck('the "ללא קבוצה" heading keeps its own bucket right',
   orphan.deleteItem(1)==='5', String(orphan.chip.textContent));

// ── the correction itself ────────────────────────────────────────────────
const bumpOnly = scene({counts:{'5':10}});
const counts = bumpOnly.st.board.group_counts;
bumpOnly.bumpGroupCount(5,1);
ck('an item added to a group puts it up by one', counts['5']===11, JSON.stringify(counts));
bumpOnly.bumpGroupCount(5,-1);
ck('...and one taken out puts it back down', counts['5']===10, JSON.stringify(counts));
bumpOnly.bumpGroupCount(7,1);
ck('a group the board left out of the map — made since it was opened — starts at one',
   counts['7']===1, JSON.stringify(counts));
bumpOnly.bumpGroupCount(9,-1);
ck('but a missing key is never invented downwards, where there is no base to subtract from',
   counts['9']===undefined, JSON.stringify(counts));
bumpOnly.bumpGroupCount(5,-99);
ck('and no count goes negative whatever the arithmetic was told',
   counts['5']===0, JSON.stringify(counts));
const noMap = scene({rows:rows(1)});
noMap.bumpGroupCount(5,1);
ck('a board that was sent no map is not given one by the bookkeeping',
   noMap.st.board.group_counts===undefined, JSON.stringify(noMap.st.board.group_counts));

// ── every path that changes the board without refetching it ──────────────
/* These four are the ways a group's size changes while the board stays where
   it is. One of them forgetting to say so is a header that is wrong until the
   next fetch — and on a paged board "the next fetch" can be tomorrow. */
for(const [fn,what] of [['removeTaskLocal','a row leaving the board'],
                        ['openNewItem','an item added to a group'],
                        ['bulkMoveToGroup','a selection moved between groups'],
                        ['bulkDuplicate','a selection duplicated']])
  ck(`${what} tells the count about it`, /bumpGroupCount\(/.test(grab(fn)), fn);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
