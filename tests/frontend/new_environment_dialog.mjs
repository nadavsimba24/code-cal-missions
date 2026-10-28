/* Creating an environment — the dialog, and what it sends.

   It was `prompt('שם הסביבה החדשה:')` in two different places: the browser's
   grey box, in a product with a house modal for everything else. It now goes
   through editPrompt, the app's own styled single-field dialog, which had been
   sitting in this file unused. One field: the name.

   Runs the real Env object out of index.html against stubs.
   Driven by tests/test_new_environment_dialog.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

/* `const Env = { … };` — brace-matched from the opening brace of the literal */
function grabObject(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1)+';'; } }
}

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

function makeHarness({typed='אגף החינוך', cap=true, mobile=false, createResult={id:9}, createThrows=null}={}){
  const log={asked:null, toasts:[], posted:null, selected:null, loaded:0};
  const env=new Function(
    'document','editPrompt','api','toast','meId','mobileBlocked','hasCap',
    'renderSidebar','closeSidebarMobile','st','showModal','closeModals','esc','avatarColor',
    [grabObject('Env'), 'return Env;'].join('\n'))(
    {addEventListener(){}, removeEventListener(){}, getElementById:()=>null, querySelectorAll:()=>[]},
    async o=>{ log.asked=o; return typed; },
    async (p,o)=>{ log.posted={path:p, body:JSON.parse(o.body)};
                   if(createThrows) throw createThrows;
                   return createResult; },
    t=>log.toasts.push(t),
    ()=>1, ()=>mobile, ()=>cap, ()=>{}, ()=>{}, {env:null, me:{id:1,name:'שלי פיינברג'}},
    ()=>{}, ()=>{}, s=>String(s==null?'':s),
    n=>n==='שלי פיינברג'?'#e2445c':'#000000');   // the avatar palette, stubbed
  env.items=[{id:1,name:'ראשית'}];
  env.load=async()=>{ log.loaded++; };
  env.select=id=>{ log.selected=id; };
  env.render=()=>{};
  return {env, log};
}

// ── it asks with the house dialog, not the browser's ──
{
  const h=makeHarness();
  await h.env.add();
  ck('it opens the styled single-field dialog', !!h.log.asked);
  ck('titled for what it is doing', h.log.asked.title==='סביבה חדשה', h.log.asked.title);
  ck('the field is labelled', h.log.asked.label==='שם הסביבה', h.log.asked.label);
  ck('the button says create, not save', h.log.asked.confirmText==='צור סביבה', h.log.asked.confirmText);
  ck('the name is capped', h.log.asked.maxlength===60, String(h.log.asked.maxlength));
  ck('it suggests what a name looks like', !!h.log.asked.placeholder, h.log.asked.placeholder);
  ck('it asks for nothing else — no icon, no colour',
     !('icons' in h.log.asked) && !('colors' in h.log.asked));
  ck('and wears no coloured disc: that belongs to a warning, not to a name',
     !h.log.asked.icon, h.log.asked.icon);
}

// ── what it sends ──
{
  const h=makeHarness({typed:'אגף החינוך'});
  await h.env.add();
  ck('it posts to the environments endpoint', h.log.posted.path==='/api/environments');
  ck('the name is what was typed', h.log.posted.body.name==='אגף החינוך', h.log.posted.body.name);
  ck('no icon is chosen here — that is the creator\u2019s avatar\u2019s job',
     !('icon' in h.log.posted.body), JSON.stringify(h.log.posted.body));
  /* The colour is not something the dialog asks for; it is the colour the
     creator already wears, sent so the badge opens looking like their avatar
     and so the editor has a colour of the palette to mark. */
  ck('but the creator\u2019s own avatar colour travels with it',
     h.log.posted.body.color==='#e2445c', h.log.posted.body.color);
  ck('the list is reloaded', h.log.loaded===1);
  ck('and it lands in the environment just created', h.log.selected===9, String(h.log.selected));
  ck('and says so', h.log.toasts.includes('הסביבה נוצרה'), h.log.toasts.join('|'));
}

// ── cancelling ──
{
  const h=makeHarness({typed:null});     // editPrompt resolves null on Esc/ביטול,
  await h.env.add();                     // and on a name that is only spaces
  ck('cancelling creates nothing', h.log.posted===null);
  ck('and says nothing', h.log.toasts.length===0, h.log.toasts.join('|'));
  ck('and reloads nothing', h.log.loaded===0);
}

// ── the system-admin table opens the same dialog, with its own ending ──
{
  const h=makeHarness();
  let refreshed=0;
  await h.env.add({done:()=>{ refreshed++; }});
  ck('the admin screen gets the same dialog, not a second one',
     h.log.asked && h.log.asked.title==='סביבה חדשה');
  ck('its own list is what gets refreshed', refreshed===1);
  ck('and the admin is not moved into the new environment', h.log.selected===null,
     String(h.log.selected));
  ck('while the switcher is still brought up to date', h.log.loaded===1);
}

// ── the server's own refusal is what the user is told ──
{
  const h=makeHarness({createThrows:Object.assign(new Error('403'),{detail:'אין לך הרשאה ליצור סביבה'})});
  await h.env.add();
  ck('a refusal from the server is shown in its own words',
     h.log.toasts.includes('אין לך הרשאה ליצור סביבה'), h.log.toasts.join('|'));
  ck('and nothing is reloaded behind it', h.log.loaded===0);
}

// ── the guards run before anything opens ──
{
  const h=makeHarness({cap:false});
  await h.env.add();
  ck('without the capability nothing is asked', h.log.asked===null);
  ck('and it says why', h.log.toasts.includes('אין לך הרשאה ליצור סביבה'));

  const h2=makeHarness({mobile:true});
  await h2.env.add();
  ck('on a phone it stops before the permission check',
     h2.log.asked===null && !h2.log.toasts.length);
}

// ── the dialog it leans on is really there, and behaves ──
{
  ck('editPrompt exists in the page', /^function editPrompt\(opts\)\{/m.test(src));
  ck('its disc is drawn only when a caller asks for one',
     /\$\{opts\.icon\?`<div class="confirm-ic">/.test(src));
  ck('while confirm and alert keep theirs',
     (src.match(/<div class="confirm-ic/g)||[]).length>=3);
  ck('Enter finishes it', /ev\.key==='Enter'\)\{ ev\.preventDefault\(\); window\._editPromptSave/.test(src));
  ck('Esc cancels it', /ev\.key==='Escape'\)\{ ev\.preventDefault\(\); window\._editPromptCancel/.test(src));
  ck('it hands back a trimmed value, or nothing at all',
     /finish\(\(i\?i\.value:''\)\.trim\(\)\|\|null\)/.test(src));
  ck('no environment is made through a browser prompt any more',
     !/prompt\('שם הסביבה החדשה/.test(src));
  /* dir="auto" on an input takes its direction from the first strong character
     of the value, and with no value the fallback is ltr — so the field opened
     left-aligned in a right-to-left app and jumped on the first letter. */
  ck('the field inherits the page direction instead of guessing at it',
     /<input id="edit-prompt-inp"[^>]*>/.test(src) &&
     !/<input id="edit-prompt-inp"[^>]*dir=/.test(src),
     (/<input id="edit-prompt-inp"[^>]*>/.exec(src)||[''])[0]);
  ck('and the field block still aligns to the start edge',
     /\.ep-field\{[^}]*text-align:start/.test(src));
}

// ── the environments table shows no colour any more ──
{
  const table=/async renderEnvs\(\)\{[\s\S]*?<\/table><\/div>`;/.exec(src);
  ck('the environments admin table is found', !!table);
  ck('its rows carry no colour dot', table && !/dp-swatch/.test(table[0]));
  ck('and no empty column is left holding its place',
     table && !/<th style="width:34px"><\/th>/.test(table[0]));
  /* The empty state used to be written inline here with colspan="3" in it. The
     six admin tabs now share one emptyRow(tab,none), which spans
     cols(tab).length — so the thing to pin is that the span FOLLOWS the column
     count rather than that it says a particular number. A literal is exactly
     what drifted when the colour column was taken out of this table. */
  const envCols=/\n    envs:\[([\s\S]*?)\n    \],/.exec(src);
  ck('the environments table still declares three columns — name, boards, actions',
     !!envCols && (envCols[1].match(/\{/g)||[]).length===3,
     envCols?envCols[1]:'COLS.envs not found');
  ck('the empty-state spans the columns that are actually there',
     /colspan="\$\{this\.cols\(tab\)\.length\|\|1\}"/.test(src),
     (/colspan="[^"]*"/.exec(src)||[''])[0]);
  ck('the departments table keeps its own dot — a different screen, not asked about',
     /dp-swatch/.test(src));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
