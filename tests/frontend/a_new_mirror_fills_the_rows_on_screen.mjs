/* A new mirror column fills the rows already on screen.

   A mirror's value is computed by the server when an item is READ, so rows
   fetched before the column existed carry nothing for it. saveColumns took
   the new column list and re-rendered the rows it already had — every row
   that was already linked showed "—" under the new mirror until the page was
   reloaded, which reads exactly as a mirror that does not work.

   And the other half: saving an unrelated column change must NOT reload the
   whole board, which on a board of hundreds of items is a real wait.

   Driven by tests/test_mirror_fields.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabFn(name){
  const i = src.indexOf(`async function ${name}(`);
  if(i<0) throw new Error('missing '+name);
  let open = src.indexOf('{', src.indexOf(')', i)), d = 0;
  for(let j=open;j<src.length;j++){
    if(src[j]==='{')d++; else if(src[j]==='}'){ d--; if(!d) return src.slice(i,j+1); }
  }
}

let refreshed = 0, serverCols = null;
const st = {board:{id:1, columns:[]}};
const api = async () => ({columns: serverCols});
const withMe = b => b, renderView = () => {}, toast = () => {};
const refreshBoardItems = async () => { refreshed++; };
const saveColumns = eval('(' + grabFn('saveColumns') + ')');

let fails = 0;
async function check(label, before, after, want){
  st.board.columns = before; serverCols = after; refreshed = 0;
  await saveColumns(after);
  const ok = (refreshed > 0) === want;
  console.log(`${ok?'ok  ':'FAIL'} ${label} (refreshed ${refreshed})`);
  if(!ok) fails++;
}

const conn = {id:'c1', type:'connect', title:'קישור'};
const mir  = {id:'m1', type:'mirror', title:'מנהל', mirror_of:{connect:'c1', field:'f1'}};
const txt  = {id:'t1', type:'text', title:'הערה'};

await check('adding a mirror reloads the rows', [conn], [conn, mir], true);
await check('pointing a mirror at another field reloads the rows',
  [conn, mir], [conn, {...mir, mirror_of:{connect:'c1', field:'f2'}}], true);
await check('renaming a mirror does not', [conn, mir], [conn, {...mir, title:'אחר'}], false);
await check('adding a text column does not', [conn, mir], [conn, mir, txt], false);

process.exit(fails ? 1 : 0);
