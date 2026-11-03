/* A filtered board shows the groups that answer it, and no others.

   groupsOf has always handed vTable every group on the board with its matching
   rows attached — so under a filter a board of twelve groups holding two
   results drew ten headings, ten rows of column names and ten "add item"
   lines over nothing. The two results were somewhere in the middle of it, and
   the screen read as a filter that had not worked.

   An empty group is still part of the board's structure, so it comes back the
   moment the filter is cleared — and a SORT is not a filter: it reorders the
   rows the board already holds and takes none of them away, so ordering a
   board never takes a group off it. That distinction is what boardIsNarrowed
   exists for, and getting it wrong is how "sort by status" would quietly
   delete the empty groups from the screen.

   Two things follow from hiding them, and both are checked here: the group
   order on screen is no longer the board's order, so the drag grip is not
   drawn; and "הוסף קבוצה" would create a group that is immediately invisible,
   so it is not offered either.

   Driven by tests/test_filter_hides_empty_groups.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(src);
  if (!m) throw new Error('not found: ' + name);
  let d = 0;
  for (let k = src.indexOf('{', m.index); k < src.length; k++){
    if (src[k] === '{') d++;
    else if (src[k] === '}'){ d--; if (!d) return src.slice(m.index, k + 1); }
  }
}

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

/* The real groupsOf and boardIsNarrowed, over a board of three groups where
   only one holds anything the filter wants. applyFilters is stubbed to the
   narrowing the filter describes — the engine itself is pinned elsewhere; what
   is on trial here is which groups survive it. */
const EMPTY_F = {q:'', people:[], status:'', priority:'', sort:'', links:{col:'',mode:'',item:0}, adv:null};
const TASKS = [
  {id:1, group_id:10, title:'alpha'},
  {id:2, group_id:10, title:'beta'},
  {id:3, group_id:30, title:'gamma'},
];
const GROUPS = [{id:10,name:'עשר'},{id:20,name:'עשרים'},{id:30,name:'שלושים'}];

function board(filters, tasks = TASKS, groups = GROUPS){
  const st = {board:{groups, tasks}, filters:Object.assign({}, EMPTY_F, filters), colSort:null};
  const env = {
    st,
    advCount: n => (n && n.rules) ? n.rules.length : 0,
    // the cut the filters describe, which is all groupsOf asks of it
    applyFilters: ts => st.filters.q ? ts.filter(t => (t.title||'').includes(st.filters.q)) : ts.slice(),
  };
  const names = Object.keys(env);
  const fns = grab('boardIsNarrowed') + ';' + grab('groupsOf') + '; return {groupsOf, boardIsNarrowed};';
  return {st, ...new Function(...names, fns).apply(null, names.map(n => env[n]))};
}

// ── the ask ───────────────────────────────────────────────────────────────
const filtered = board({q:'alpha'});
const names = filtered.groupsOf().map(g => g.name);
ck('a filtered board shows only the groups that have something in them',
   names.join(',') === 'עשר', JSON.stringify(names));

const all = board({}).groupsOf().map(g => g.name);
ck('...and with no filter on, every group is there as before',
   all.join(',') === 'עשר,עשרים,שלושים', JSON.stringify(all));

/* The group that matched keeps only its matching rows — hiding the empty ones
   must not have quietly changed what the surviving ones hold. */
ck('the group that survived carries its matching rows and no others',
   filtered.groupsOf()[0].tasks.map(t => t.id).join(',') === '1');

// ── an order is not a filter ──────────────────────────────────────────────
/* f.sort is in filtersActive, which is why boardIsNarrowed could not be it:
   a board put in a different order still holds every row and every group. */
const sorted = board({sort:'due'}).groupsOf().map(g => g.name);
ck('sorting the board does not take its empty groups away',
   sorted.join(',') === 'עשר,עשרים,שלושים', JSON.stringify(sorted));

const bySort = board({});
bySort.st.colSort = {key:'status', dir:'desc'};
ck('...and neither does a column sort',
   bySort.groupsOf().length === 3, 'groups=' + bySort.groupsOf().length);

// ── every narrowing counts, not just the search box ───────────────────────
for (const [label, f] of [['אנשים', {people:[7]}], ['סטטוס', {status:'done'}],
                          ['עדיפות', {priority:'high'}],
                          ['קישורים', {links:{col:'c1',mode:'has',item:0}}],
                          ['התנאי המתקדם', {adv:{rules:[{}]}}]]){
  ck('a cut by ' + label + ' narrows the board too', board(f).boardIsNarrowed());
}
ck('and an untouched toolbar does not', !board({}).boardIsNarrowed());

// ── a board with no groups at all is untouched ────────────────────────────
/* Everything lands in one unnamed bucket there, and a bucket holding nothing
   is the "no results" state — which vTable answers before it ever gets here. */
const flat = board({q:'nothing'}, TASKS, []).groupsOf();
ck('a board with no groups still answers with its single bucket',
   flat.length === 1 && flat[0].id === null, JSON.stringify(flat.map(g => g.name)));

// ── what follows from hiding them ─────────────────────────────────────────
/* The order on screen is no longer the board's order, and /api/groups/reorder
   is told the whole sequence — so the grip must not be there to drag. */
const gh = grab('groupHTML');
ck('the group head asks whether the board is narrowed before drawing a grip',
   /const mayDrag=!boardIsNarrowed\(\)/.test(gh));
ck('...and the grip is drawn only when it is not',
   /\$\{mayDrag\?'<i class="fa-solid fa-grip-vertical g-drag g-handle"/.test(gh));
ck('...as is the handle on the group name, which drags it just the same',
   /g-name\$\{mayDrag\?' g-handle':''\}/.test(gh));

const ag = grab('addGroupBtnHTML');
ck('"הוסף קבוצה" is not offered on a narrowed board — the new group would be born invisible',
   /if\(boardIsNarrowed\(\)\)return '';/.test(ag));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
