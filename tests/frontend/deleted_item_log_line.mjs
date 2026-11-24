/* A deleted item stays in the board's log, and its line can bring it back.

   Deleting an item used to erase it from the log entirely — not because the
   row was missing, but because the log scopes its task rows to the board's
   item list, and the deleted item is not on it. The row recording the
   deletion was filtered out by the very act it recorded, so from the log's
   point of view the item had never existed.

   Two things have to be right once it is visible. The name must not be a
   button: the item is in the bin, and offering to open it leads nowhere —
   the same trap the column lines already avoid. And the restore button must
   follow the server's answer, because restoring is a board edit and the
   log's isMgr is a different question.

   Driven by tests/test_deleted_item_log_line.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n)) : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

/* One log line is drawn by BoardLog.lineHTML — shared by the first page and
   every "טען עוד" page after it, so both draw a deleted item the same way. */
const tpl = src.slice(src.indexOf('  lineHTML(a){'),
                      src.indexOf('  lineHTML(a){') + 2200);

// ── the name ──────────────────────────────────────────────────────────────
ck('a live item is still a button that opens it',
   /a\.task_id&&!a\.task_deleted/.test(tpl) && /BoardLog\.goto\(/.test(tpl));
ck('a deleted item is drawn plain, not as a button that opens nothing',
   /lg-dead/.test(tpl) && tpl.indexOf('lg-dead') < tpl.indexOf('lg-board'));
ck('and it says where the item went', /בסל המחזור/.test(tpl));
ck('a board line keeps its own treatment', /lg-board/.test(tpl));

// ── the button ────────────────────────────────────────────────────────────
ck('the restore offer comes from the server, not from the action name',
   /a\.can_restore_item/.test(tpl));
ck('it calls restore with the item, not with the log row',
   /BoardLog\.restoreItem\(\$\{a\.task_id\}\)/.test(tpl));
/* isMgr gates undo because undo is a manager's power. Restoring an item is a
   board edit, and the server already decided whether this viewer has it —
   re-gating on isMgr here would hide the button from an editor who may. */
const seg = tpl.slice(tpl.indexOf('a.can_restore_item'), tpl.indexOf('a.can_undo'))
  .replace(/\/\*[\s\S]*?\*\//g, '');   // the comment beside it says the word too
ck('an editor is not locked out by the manager gate', !/isMgr/.test(seg), seg.trim().slice(0, 120));
ck('a column line still gets its own restore button', /BoardLog\.restoreColumn\(/.test(tpl));
ck('an ordinary undoable row still gets undo', /a\.can_undo\b/.test(tpl) && /BoardLog\.undo\(/.test(tpl));

// ── the action ────────────────────────────────────────────────────────────
const fn = src.slice(src.indexOf('async restoreItem(taskId){'),
                     src.indexOf('async restoreItem(taskId){') + 1200);
ck('it asks before acting', /askConfirm\(/.test(fn));
ck('it uses the recycle bin\'s own endpoint rather than a second mechanism',
   /'\/api\/tasks\/'\+taskId\+'\/restore'/.test(fn));
ck('the board is re-read, because a row reappearing changes the view',
   /api\('\/api\/boards\/'\+st\.board\.id\)/.test(fn) && /renderView\(\)/.test(fn));
ck('a refusal is told apart from an item that is already gone', /404/.test(fn));

// ── the struck-through name has a rule to be struck through by ────────────
ck('.lg-dead is styled', /\.lg-dead\{[^}]*line-through/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
