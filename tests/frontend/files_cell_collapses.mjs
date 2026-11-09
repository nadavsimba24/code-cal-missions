/* A files cell holding three or more says the types, not three clipped names.

   The cell used to draw one chip per file, each chip a paperclip plus the
   first nine letters of the name. Three of those wrap the row onto three
   lines, and "דוח בטיחו…", "דוח בטיחו…", "דוח בטיחו…" tells a person neither
   what the files are nor how many there are — which is everything the column
   is for at a glance.

   From three up it collapses: the first three as an icon apiece, chosen by
   what the file IS, and a +X for whatever is left. The names did not vanish —
   they are all in the hover, which travels in data-tipf so our own box answers
   at once and keeps the line breaks, rather than in title, where the browser
   waits a second and a half and runs them together.

   The collapsed strip has no per-file × on it, so the list it opens is the
   only place a file can still be removed once a cell holds three. That is
   pinned here too: losing it would take the column's remove with it.
   Driven by tests/test_files_cell_collapses.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabFn(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
  throw new Error('unbalanced: '+name);
}
function grabTable(decl){
  const i=src.indexOf(decl);
  if(i<0) throw new Error('not found: '+decl);
  const open=src.indexOf('[',i);
  let d=0;
  for(let j=open;j<src.length;j++){
    if(src[j]==='[')d++;
    else if(src[j]===']'){ d--; if(!d) return src.slice(i,j+1)+';'; }
  }
  throw new Error('unbalanced: '+decl);
}
function grabArrow(name){
  const m = new RegExp(`^const ${name}=`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  const nl=src.indexOf('\n',m.index);
  return src.slice(m.index,nl)+';';
}

/* The real Chat.fileExt — the collapsed cell leans on it for a file whose name
   carries no extension, and a stub of it would pin nothing. */
const fileExt = new Function('return ('+/fileExt\(name,type\)\{[\s\S]*?\n  \},/.exec(src)[0].replace(/^fileExt/,'function fileExt').replace(/,$/,'')+')')();

let TASK={custom_fields:{}};
const build = () => new Function('esc','Chat','fileDeadWhy','findAnyTask','location',
  grabTable('const FILE_TYPE_ICONS=[')
  +grabFn('fileTypeIcon')
  +grabArrow('filesTip')
  +grabFn('fileLinkAttrs')
  +grabFn('filesDisp')
  +grabFn('buildFilesPop')
  +' return {filesDisp,buildFilesPop,fileTypeIcon};')(
  s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
  {fileExt}, f=>'הקובץ לא יובא', ()=>TASK,
  /* fileLinkAttrs resolves a file's address against the page's, so the page
     has to have one here. The host is arbitrary; what the tests turn on is
     whether the file's address resolves to the SAME one. */
  {href:'https://missions.example/boards/7', origin:'https://missions.example'});

const F = build();
const file=(name,extra)=>Object.assign({name,url:'/api/files/'+name},extra||{});
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── under three, the names are still spelled out ──────────────────────────
const two = F.filesDisp([file('תוכנית.pdf'),file('מצגת.pptx')],7,'c_f');
ck('two files are still two named chips',
   (two.match(/class="file-chip/g)||[]).length===2 && !/file-icons/.test(two), two);
ck('and each of them keeps its own ×',
   (two.match(/removeFile\(event,7,'c_f',\d\)/g)||[]).length===2, two);

// ── three is where it collapses ───────────────────────────────────────────
const three = F.filesDisp([file('תוכנית.pdf'),file('תקציב.xlsx'),file('חזית.png')],7,'c_f');
ck('three files collapse to a strip of icons', /class="file-icons"/.test(three) && !/file-chip/.test(three), three);
ck('one icon per file, and the icon says what the file is',
   (three.match(/class="file-ic"/g)||[]).length===3
   && /fa-file-pdf/.test(three) && /fa-file-excel/.test(three) && /fa-file-image/.test(three), three);
ck('with nothing left over, there is no +X to show',
   !/file-more/.test(three), three);
ck('every icon is still the file\'s own link, and opening one is not opening the list',
   (three.match(/<a class="file-ic" href="[^"]+" download="[^"]*" onclick="event\.stopPropagation\(\)"/g)||[]).length===3, three);

/* Clicking a file takes the file. It used to be target=_blank, which for
   anything the server refuses to serve inline flashed a tab open and shut
   again, and for a PDF left a tab standing. download + ?dl=1 saves it where
   the browser saves things and leaves the board where it was. */
ck('a file is a download, not a new tab',
   !/target="_blank"/.test(three) && (three.match(/download="/g)||[]).length===3, three);
ck('and the server is asked for it as an attachment too',
   (three.match(/href="\/api\/files\/[^"]*\?dl=1"/g)||[]).length===3, three);
ck('the saved name is the file\'s own',
   /download="תקציב\.xlsx"/.test(three), three);

/* How the address is SPELLED must not decide this. A board exported from here
   and imported back carries its file cells as absolute addresses, and the
   first version of fileLinkAttrs matched a leading slash and nothing else —
   so those files alone went on opening in a window, which reads as "it works
   for some people and not others" rather than as two spellings of one
   address. */
const abs = F.filesDisp([{name:'מפרט.pdf',url:'https://missions.example/api/files/abc123'},
                         {name:'ב.pdf',url:'/api/files/b'},
                         {name:'ג.pdf',url:'/api/files/c'}],7,'c_f');
ck('a file written as a full address is still our own file',
   !/target="_blank"/.test(abs) && (abs.match(/download="/g)||[]).length===3, abs);
ck('and it is linked by path, so the download attribute applies to it',
   /href="\/api\/files\/abc123\?dl=1"/.test(abs), abs);

/* The other direction: an imported link still pointing at monday is not ours.
   download is honoured same-origin only — left on, the click would navigate
   the board away instead of saving anything — so that one keeps its tab. */
const far = F.filesDisp([{name:'מפרט.pdf',url:'https://files.monday.com/x/y.pdf'},
                         {name:'ב.pdf',url:'/api/files/b'},
                         {name:'ג.pdf',url:'/api/files/c'}],7,'c_f');
ck('a file that lives somewhere else keeps the new tab',
   (far.match(/target="_blank"/g)||[]).length===1
   && (far.match(/download="/g)||[]).length===2, far);
ck('and it is not sent our ?dl=1, which means nothing there',
   !/files\.monday\.com[^"]*dl=1/.test(far), far);

// ── four and up: three icons, then how many more ──────────────────────────
const six = F.filesDisp([file('א.pdf'),file('ב.docx'),file('ג.zip'),file('ד.mp4'),file('ה.txt'),file('ו.dwg')],7,'c_f');
ck('six files are three icons and a +3',
   (six.match(/class="file-ic"/g)||[]).length===3 && /<span class="file-more">\+3<\/span>/.test(six), six);
ck('the icons are the first three, in the order the files are in',
   six.indexOf('fa-file-pdf')<six.indexOf('fa-file-word')
   && six.indexOf('fa-file-word')<six.indexOf('fa-file-zipper')
   && !/fa-file-video|fa-file-lines|fa-compass-drafting/.test(six), six);
ck('a cell that collapsed can still be added to',
   /class="file-add"[^>]*onclick="uploadFileCell\(7,'c_f'\)"/.test(six), six);

// ── the hover names them, all of them ─────────────────────────────────────
const tip = /data-tipf="([^"]*)"/.exec(six);
ck('the hover carries every name, not only the three on screen',
   !!tip && ['א.pdf','ב.docx','ג.zip','ד.mp4','ה.txt','ו.dwg'].every(n=>tip[1].includes(n)), tip&&tip[1]);
ck('one per line, so six names do not arrive as one sentence',
   !!tip && tip[1].split('\n').length===6, tip&&JSON.stringify(tip[1]));
ck('and it is data-tipf, not the browser\'s slow title',
   !/<span class="file-icons"[^>]*\stitle=/.test(six), six);
ck('a name with a quote or a tag in it cannot break out of the attribute',
   !/<b>/.test(F.filesDisp([file('<b>"x".pdf'),file('ב.pdf'),file('ג.pdf')],7,'c_f')));

// ── an imported file whose bytes never arrived is not offered as a link ───
const dead = F.filesDisp([file('מפרט.pdf',{dead:true,why:'expired'}),file('ב.pdf'),file('ג.pdf')],7,'c_f');
ck('a dead attachment shows as broken, and not as something to click',
   /class="file-ic file-dead-ic"><i class="fa-solid fa-link-slash"/.test(dead)
   && (dead.match(/<a class="file-ic"/g)||[]).length===2, dead);
ck('the hover says why it is dead',
   /data-tipf="[^"]*מפרט\.pdf — הקובץ לא יובא/.test(dead), dead);

// ── the strip opens the list, which is where a file is removed ────────────
ck('the strip opens the list', /onclick="openFilesList\(event,7,'c_f'\)"/.test(six), six);
TASK={custom_fields:{c_f:[file('א.pdf'),file('ב.docx'),file('ג.zip'),file('ד.mp4')]}};
const pop={innerHTML:''};
F.buildFilesPop(pop,7,'c_f');
ck('the list names all four in full — the three on screen and the one behind the +1',
   ['א.pdf','ב.docx','ג.zip','ד.mp4'].every(n=>pop.innerHTML.includes(n)), pop.innerHTML);
ck('and every one of them can be removed from there',
   (pop.innerHTML.match(/removeFileFromList\(event,7,'c_f',\d\)/g)||[]).length===4, pop.innerHTML);
ck('the list takes another file too, without leaving itself open over a redrawn grid',
   /closeCellPops\(\);uploadFileCell\(7,'c_f'\)/.test(pop.innerHTML), pop.innerHTML);
ck('and a row in the list downloads its file rather than opening a tab',
   (pop.innerHTML.match(/<a class="file-pop-row" href="\/api\/files\/[^"]*\?dl=1" download="/g)||[]).length===4
   && !/target="_blank"/.test(pop.innerHTML), pop.innerHTML);

console.log(`\n  ${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
