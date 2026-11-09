/* The screen's half of "an אורח does not take data out of the system".

   The server refuses — the board as an .xlsx, and the bytes of any attachment
   (tests/test_guest_cannot_take_data_out.py). This is what the screen owes on
   top of that, and each of the three is a different failure if it is missing:

   * a link that answers 403 reads as a BROKEN FILE, not as a permission that
     was never given. So no link is offered, and the row says why instead;
   * a thumbnail IS the file, fetched and drawn. Asking for one that will be
     refused puts a broken-image glyph on the screen where the picture was;
   * the action in the board menu is offered or it is not — a menu item that
     opens a toast saying no is a button that cannot do its job.

   One question behind all of them: hasCap('download_files') and
   hasCap('export_excel'), which read the same matrix the server reads. A
   system administrator turning either back on for אורח turns the screen back
   on with it, without a release.

   Driven by tests/test_guest_cannot_take_data_out.py. */
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
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── one question, asked of the matrix ─────────────────────────────────────
const may = grab('mayDownloadFiles');
ck('"may files be downloaded" is the matrix capability and nothing else',
   /hasCap\('download_files'\)/.test(may), may);
/* not the board role: a board EDITOR who is an אורח may edit the board and
   still not take its files, which is the whole distinction being drawn */
ck('…not the board role, which is a different question',
   !/isBoardAdmin|my_role/.test(may), may);
ck('and the matrix is what hasCap reads, so the server and the screen agree',
   /function hasCap\(cap\)\{[\s\S]{0,400}?st\.rolePerms/.test(src));

// ── no link where the bytes will be refused ───────────────────────────────
const attrs = grab('fileLinkAttrs');
ck('a file link is not built at all where files may not be downloaded',
   /if\(!mayDownloadFiles\(\)\)/.test(attrs), attrs);
ck('…and that is the first thing it asks, before any address is made',
   attrs.indexOf('mayDownloadFiles()') < attrs.indexOf('location.href'), attrs);
const refused = attrs.slice(attrs.indexOf('mayDownloadFiles()'),
                            attrs.indexOf('const u=String'));
ck('…what comes back carries no href, so there is nothing to click',
   !/href=/.test(refused), refused);
ck('…and says why, on the row itself',
   /אין לך הרשאה להוריד קבצים/.test(refused) && /aria-disabled="true"/.test(refused), refused);
ck('a refused row looks refused rather than merely dead',
   /a\[aria-disabled="true"\]\{[^}]*cursor:not-allowed/.test(src));

// ── every file on screen goes through that one function ───────────────────
/* the files cell, the list it opens, the item's files tab, a chat attachment —
   four places, one gate. A fifth that builds its own href is a way out. */
const hrefs = (src.match(/href="\/api\/files\//g)||[]).length;
ck('no file link is spelled out by hand anywhere else', hrefs===0, hrefs+' hand-built links');
ck('and the download arrow in the files tab goes with the link',
   /\$\{mayDownloadFiles\(\)\?'<i class="fa-solid fa-download fr-dl"><\/i>':''\}/.test(src));

// ── a thumbnail is the file ────────────────────────────────────────────────
ck('a picture preview is not asked for where it cannot be fetched',
   /if\(this\.isImg\(f\.name,f\.type\)&&mayDownloadFiles\(\)\) return `<a class="att-prev"/.test(src));
ck('…and the composer\'s own chips fall back to the type badge too',
   /const thumb=\(this\.isImg\(f\.name,f\.type\)&&mayDownloadFiles\(\)\)\?/.test(src));
/* what is left when the picture is not drawn still says what the file is */
ck('…which still says what the file is', /this\.extBadge\(f\.name,f\.type\)/.test(src));

// ── ייצוא לאקסל ───────────────────────────────────────────────────────────
ck('the board menu offers the export only where it is allowed',
   /item\('fa-file-excel','ייצוא לאקסל','exportBoardExcel\(\)',hasCap\('export_excel'\)/.test(src));
ck('…and a disabled row says what is missing rather than nothing',
   /hasCap\('export_excel'\),\s*\n?\s*'אין לך הרשאה לייצא לוח לאקסל/.test(src));
const exp = grab('exportBoardExcel');
ck('the export checks again before it sends, for a screen that went stale',
   /if\(!hasCap\('export_excel'\)\)\{ toast\(/.test(exp), exp);
ck('…ahead of the request, not after the refusal comes back',
   exp.indexOf("hasCap('export_excel')") < exp.indexOf('/export/xlsx'), exp);

// ── and nothing else was taken away ───────────────────────────────────────
/* the block is on taking files OUT. Putting one in, naming one, removing one
   from a cell are untouched — a guest is still working on the board. */
ck('uploading is not gated on it', !/mayDownloadFiles\(\)[\s\S]{0,60}uploadFileCell/.test(src));
ck('and neither is removing a file from a cell',
   /onclick="removeFile\(event,\$\{taskId\}/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
