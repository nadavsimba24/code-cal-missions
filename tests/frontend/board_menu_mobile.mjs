/* On a narrow screen the board log moves into the ⋯ menu, because its header
   button is hidden there. Runs the real boardMenu out of index.html.
   Driven by tests/test_board_head_mobile.py. */
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

let mobile=true, html='';
const st={board:{id:1,my_role:'admin',visibility:'private',environment_id:5,name:'לוח'}};
const ctx=new Function('st','isMobile','esc','openCellPop','Env','hasCap',
  grab('boardMenu')+'; return boardMenu;')(
  st, ()=>mobile, x=>String(x), (a,h)=>{html=h;},
  {items:[{id:5,can_manage:true}]}, ()=>true);

const ev={stopPropagation(){}};
const labels = () => [...html.matchAll(/<i class="fa-solid [^"]*"><\/i>\s*([^<]+)</g)].map(m=>m[1].trim());

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

mobile=true; ctx(ev,1);
const mob=labels();
ck('on a phone the menu offers the board log', mob.includes('לוג הלוח'), mob.join(' | '));
ck('...wired to BoardLog.open()', /BoardLog\.open\(\)/.test(html));
ck('...and it is not disabled', !/disabled[^>]*>\s*<i[^>]*><\/i>\s*לוג הלוח/.test(html));

mobile=false; ctx(ev,1);
const desk=labels();
ck('on desktop it is NOT duplicated into the menu', !desk.includes('לוג הלוח'), desk.join(' | '));
ck('...because the header button is still there on desktop',
   /class="bh-log"/.test(src) && /#boardhead \.bh-log,#boardhead \.bh-owner\{display:none\}/.test(src));

// the log must not have displaced anything
['אוטומציות','סל מחזור','הגדרת הרשאות','מחק לוח'].forEach(l=>{
  ck(`"${l}" still in the menu on a phone`, mob.includes(l));
});
// and the desktop-only entries stay desktop-only
ck('moving the board stays off the phone menu', !mob.includes('העברה לסביבה אחרת'));
ck('...but is there on desktop', desk.includes('העברה לסביבה אחרת'));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
