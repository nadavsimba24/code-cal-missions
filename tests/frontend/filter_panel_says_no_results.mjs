/* חלון הסינון מסתיר את מצב "אין תוצאות" — אז הוא אומר אותו בעצמו.

   The panel hangs from the toolbar: position:absolute, up to 74vh of it, at
   z-index 120 over the board area. The board's own answer to a cut that
   matches nothing — "אין תוצאות לסינון הנוכחי", with the button that clears
   it — is rendered into that same area and sits behind the panel. Somebody
   who narrows a filter down to nothing while the panel is open therefore sees
   a strip of columns and no answer at all.

   So the panel carries the notice too, with the same way out, and the two
   offers come from one function so they cannot drift apart.

   Driven by tests/test_filter_panel_says_no_results.py. */
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
  throw new Error('unbalanced: '+name);
}

const TASKS=[{id:1,title:'א',status:'done',assignees:[],custom_fields:{}},
             {id:2,title:'ב',status:'done',assignees:[],custom_fields:{}}];

function world({tasks=TASKS, matched=null, views=null, paged={on:false,total:0}}={}){
  const st={board:{id:1,name:'לוח',tasks:tasks.slice(),columns:[],groups:[],
                   my_role:'admin',col_perms:{},col_hidden:[]},
            users:[], me:{id:1}, filters:{}};
  const fns = new Function('st','Paged','Views','applyFilters','esc',
    grab('cutMatchesNothing')+'\n'+grab('clearCutAction')+'\n'
    +';return {cutMatchesNothing,clearCutAction};')(
      st, paged, views, rows=>(matched===null?rows:rows.slice(0,matched)),
      x=>String(x==null?'':x));
  return [fns, st];
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,220):''))); };

// ── when the panel must speak ──────────────────────────────────────────────
{
  const [f]=world({matched:0});
  ck('a cut that answers with nothing is reported', f.cutMatchesNothing()===true);
}
{
  const [f]=world({matched:1});
  ck('...and one that answers with something is not', f.cutMatchesNothing()===false);
}
{
  /* An empty board is not a failed filter — saying "אין תוצאות" over one sends
     somebody looking for a filter to clear that was never on. The board's own
     state has always drawn this line; the panel has to draw the same one. */
  const [f]=world({tasks:[], matched:0});
  ck('an empty board is not a failed filter', f.cutMatchesNothing()===false);
}
{
  // on a server-paged board the count is the server's, not the page's
  const [f]=world({paged:{on:true,total:0}, matched:null});
  ck('a paged board with no total answers nothing', f.cutMatchesNothing()===true);
  const [g]=world({paged:{on:true,total:7}, matched:0});
  ck('...and one with a total does not, whatever this page holds',
     g.cutMatchesNothing()===false);
}

// ── the way out is the same offer the board makes ─────────────────────────
{
  const [f]=world({matched:0, views:{active:null}});
  const a=f.clearCutAction();
  ck('outside a view the offer is to clear the cut',
     a.includes('clearFilters()') && a.includes('ניקוי חיפוש וסינון'), a);
}
{
  const [f]=world({matched:0, views:{active:3}});
  const a=f.clearCutAction();
  ck('inside a view it is to drop the temporary changes instead',
     a.includes('Views.reset()') && a.includes('איפוס השינויים הזמניים'), a);
  ck('...and never the other promise', !a.includes('clearFilters()'), a);
}
{
  const [f]=world({matched:0, views:{active:null}});
  ck('the panel can ask for its own styling without a second wording',
     f.clearCutAction('qf-none-act').includes('class="qf-none-act"'));
}

// ── the notice is actually rendered, and above the scrolling strip ────────
{
  const i=src.indexOf('const none=cutMatchesNothing()');
  ck('the panel builds the notice', i>0);
  const head=src.indexOf('<span class="qf-showing">');
  const strip=src.indexOf('<div class="qf-cols"');
  const slot=src.indexOf('${none}');
  ck('...and places it after the heading and before the column strip',
     slot>head && slot<strip, {head,slot,strip});
  ck('...carrying the same way out', src.includes("clearCutAction('qf-none-act')"));
  ck('...and announced to a screen reader', /class="qf-none" role="status"/.test(src));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
