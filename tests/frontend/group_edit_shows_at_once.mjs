/* A group renamed or recoloured says so immediately, not after a reload.

   openBoard paints a board it has already seen from memory BEFORE it asks the
   server anything — that is what makes going back to a board instant. So a
   group edit that only reached the server came back onto a screen drawn from a
   copy that still held the old name. Two things had to be true for it to be
   wrong for as long as it was:

     · saveGroup never applied its own change anywhere locally. The PATCH had
       succeeded, so there was nothing to guess about, and nothing read it.
     · boardStamp COUNTED the groups instead of looking at them, so the recheck
       that follows decided nothing had changed and did not redraw either —
       which is why the old name survived until the page was reloaded by hand.

   The stamp half is pinned in board_cache.mjs. This one is about the first:
   the change is on the board the moment the server says yes.

   Driven by tests/test_group_edit_shows_at_once.py. */
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

/* The real saveGroup and addGroup, over a board held the way the app holds
   one. Everything they reach for is stubbed except the board itself — what is
   on trial is whether the board ends up carrying the change. */
function harness(fields, colour = '#00c875'){
  const st = {board:{id:5, groups:[{id:1,name:'ראשונה',color:'#0073ea',position:0},
                                   {id:2,name:'שנייה', color:'#00c875',position:1},
                                   {id:3,name:'שלישית',color:'#fdab3d',position:2}]}};
  const calls = [];
  const env = {
    st,
    GROUP_COLORS: ['#0073ea','#00c875'],
    meId: () => 7,
    toast: () => {},
    closeModals: () => {},
    isBoardAdmin: () => true,
    opened: 0,
    openBoard: async () => { env.opened++; },
    // the one thing a stub must get right: the create route answers with the group
    api: async (p, o) => { calls.push([(o&&o.method)||'GET', p]);
                           return p === '/api/groups' ? {id:9, name:'קבוצה חדשה', color:'#00c875', position:3} : {}; },
    document: {getElementById: id => ({value: fields[id]})},
    // the swatch the person clicked, parked where pickGroupColor leaves it
    window: {_gColor: colour},
  };
  const names = Object.keys(env);
  const fns = grab('saveGroup') + ';' + grab('addGroup') + '; return {saveGroup, addGroup};';
  return {st, calls, env, ...new Function(...names, fns).apply(null, names.map(n => env[n]))};
}

// ── the ask ───────────────────────────────────────────────────────────────
const h = harness({'g-name':'  שם חדש  ', 'g-pos':'0'});
await h.saveGroup(2);
const g2 = h.st.board.groups.find(g => g.id === 2);
ck('the new name is on the board as soon as the server has taken it',
   g2.name === 'שם חדש', JSON.stringify(g2));
ck('...and so is the colour', g2.color === '#00c875');
ck('...and the name is trimmed, the way it was sent', !/^\s|\s$/.test(g2.name));
ck('the board is still repainted afterwards', h.env.opened === 1);

/* A move is applied through the sorted COPY of the list — slice() copies the
   array and not the groups in it, so the positions written through it are
   written on the board's own groups. Get that wrong and a reorder shows only
   after a reload, exactly as the rename did. */
const order = h.st.board.groups.slice().sort((a,b)=>a.position-b.position).map(g=>g.id);
ck('a group moved to the top is at the top of the board, not only of the server',
   order.join(',') === '2,1,3', JSON.stringify(order));
ck('...and the reorder was sent', h.calls.some(c => c[1] === '/api/groups/reorder'));

// ── nothing moved, nothing sent ───────────────────────────────────────────
const same = harness({'g-name':'שנייה', 'g-pos':'1'});
await same.saveGroup(2);
ck('a group left where it is does not ask the server to reorder anything',
   !same.calls.some(c => c[1] === '/api/groups/reorder'), JSON.stringify(same.calls));

// ── an empty name is the one the server is told about ─────────────────────
const blank = harness({'g-name':'   ', 'g-pos':'1'});
await blank.saveGroup(2);
ck('a name left empty becomes "ללא שם" on the board too, not just in the request',
   blank.st.board.groups.find(g => g.id === 2).name === 'ללא שם');

// ── adding one ────────────────────────────────────────────────────────────
const add = harness({});
await add.addGroup();
ck('a group just created is on the board, out of the answer that created it',
   add.st.board.groups.some(g => g.id === 9), JSON.stringify(add.st.board.groups.map(g => g.id)));
ck('...and the board is repainted after it', add.env.opened === 1);

/* A refusal must not leave the board claiming a group it does not have. */
const refused = harness({});
refused.env.api = async () => { throw {detail:'רק מנהל הלוח יכול להוסיף קבוצות'}; };
const names2 = Object.keys(refused.env);
const again = new Function(...names2, grab('addGroup') + '; return addGroup;')
  .apply(null, names2.map(n => refused.env[n]));
await again();
ck('a refused creation adds nothing to the board', refused.st.board.groups.length === 3);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
