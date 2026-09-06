/* The "סביבה חדשה" dialog — built out of the real Env object.

   It replaced a native prompt() that could only ask for a name, so the two
   things the API also takes (icon, colour) were always the server's choice.
   These run the real Env.add / _pickIcon / _pickColor / _preview / create
   against a stub DOM, and check the dialog is the house shape, that its
   default colour is the one the server would have picked anyway, and that
   what it sends is what was chosen. Driven by tests/test_new_environment_dialog.py. */
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
const ENV_ICONS  = /^const ENV_ICONS=.*$/m.exec(src)[0];
const ENV_COLORS = /^const ENV_COLORS=.*$/m.exec(src)[0];

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

/* ── a stub DOM just wide enough for this dialog ── */
function makeHarness({envCount=3, cap=true, mobile=false, createResult={id:9}, createThrows=null}={}){
  const log={modal:null, toasts:[], posted:null, selected:null, loaded:0, closed:0, focused:0};
  const els={};
  const mkEl=(id,tag)=>{
    const e={id, tagName:tag||'DIV', value:'', textContent:'', className:'',
             dataset:{}, classList:{
               _s:new Set(),
               add(c){this._s.add(c);}, remove(c){this._s.delete(c);},
               contains(c){return this._s.has(c);},
               toggle(c,on){ on?this._s.add(c):this._s.delete(c); }},
             focus(){log.focused++;}};
    els[id]=e; return e;
  };
  const document={
    addEventListener(){}, removeEventListener(){},
    getElementById:id=>els[id]||null,
    querySelectorAll:sel=>{
      // only the two grids the dialog re-marks
      const html=log.modal||'';
      const cls=sel.includes('icon-sw')?'ic':'c';
      const attr=cls==='ic'?'data-ic':'data-c';
      const out=[];
      const re=new RegExp(`${attr}="([^"]+)"`,'g'); let m;
      while((m=re.exec(html))) out.push({dataset:{[cls==='ic'?'ic':'c']:m[1]}, classList:{toggle(){}}});
      return out;
    },
  };
  const window={};
  const env=new Function(
    'window','document','showModal','closeModals','api','toast','meId','mobileBlocked',
    'hasCap','renderSidebar','closeSidebarMobile','st','setTimeout','esc',
    [ENV_ICONS, ENV_COLORS, grabObject('Env'), 'return Env;'].join('\n'))(
    window, document,
    // showModal puts the dialog on the page, so the ids in its markup start
    // existing — that is what focus and the preview reach for
    html=>{ log.modal=html; ['ne-name','ne-pv-ic','ne-pv-name'].forEach(id=>mkEl(id, id==='ne-name'?'INPUT':'SPAN')); },
    ()=>{ log.closed++; },
    async (p,o)=>{ log.posted={path:p, body:JSON.parse(o.body)};
                   if(createThrows) throw createThrows;
                   return createResult; },
    t=>log.toasts.push(t),
    ()=>1,
    ()=>mobile,
    ()=>cap,
    ()=>{}, ()=>{}, {env:null},
    fn=>fn(),                       // run the focus timeout inline
    s=>String(s==null?'':s));
  env.items=Array.from({length:envCount},(_,i)=>({id:i+1,name:'env'+i}));
  env.load=async()=>{ log.loaded++; };
  env.select=id=>{ log.selected=id; };
  env.render=()=>{};
  return {env, log, els, mkEl, window, document};
}

// ── the dialog is the house shape ──
{
  const h=makeHarness();
  h.env.add();
  const m=h.log.modal||'';
  ck('it opens a modal at all', !!m);
  ck('titled like every other create dialog', m.includes('<h2>סביבה חדשה</h2>'), m.slice(0,60));
  ck('body and footer use the modal classes', m.includes('class="mbody"') && m.includes('class="mfoot"'));
  ck('the primary action comes first in the footer',
     m.indexOf('btn-primary') < m.indexOf('btn-ghost'));
  ck('it offers every icon in the list', (m.match(/class="icon-sw/g)||[]).length===16);
  ck('and every colour in the palette', (m.match(/class="color-sw/g)||[]).length===8);
  ck('the name field is capped and direction-aware',
     m.includes('maxlength="60"') && m.includes('dir="auto"'));
  ck('Enter creates, so the dialog can be finished from the keyboard',
     m.includes("if(event.key==='Enter')Env.create()"));
  ck('the name field takes focus', h.log.focused===1);
  ck('it shows a preview of the switcher row', m.includes('ne-preview') && m.includes('ne-pv-name'));
}

// ── the default colour is the one the server would have assigned ──
{
  // backend: _ENV_COLORS[count % len] — with 3 environments that is index 3
  const h=makeHarness({envCount:3});
  h.env.add();
  ck('the colour it opens on is the one the server would have picked',
     h.window._newEnv.color==='#f59e0b', h.window._newEnv.color);
  ck('and that swatch is the one marked selected',
     /class="color-sw sel" data-c="#f59e0b"/.test(h.log.modal), h.log.modal.match(/color-sw sel[^>]*/));

  const h2=makeHarness({envCount:8});     // wraps around the palette
  h2.env.add();
  ck('the palette wraps rather than running out',
     h2.window._newEnv.color==='#6366f1', h2.window._newEnv.color);
}

// ── what it sends is what was chosen ──
{
  const h=makeHarness();
  h.env.add();
  h.els['ne-name'].value='  אגף החינוך  ';
  h.env._pickIcon('🎓');
  h.env._pickColor('#10b981');
  await h.env.create();
  ck('it posts to the environments endpoint', h.log.posted.path==='/api/environments');
  ck('the name is trimmed', h.log.posted.body.name==='אגף החינוך', h.log.posted.body.name);
  ck('the chosen icon is sent', h.log.posted.body.icon==='🎓', h.log.posted.body.icon);
  ck('the chosen colour is sent', h.log.posted.body.color==='#10b981', h.log.posted.body.color);
  ck('the dialog closes', h.log.closed===1);
  ck('the list is reloaded', h.log.loaded===1);
  ck('and it lands in the environment just created', h.log.selected===9, String(h.log.selected));
  ck('and says so', h.log.toasts.includes('הסביבה נוצרה'), h.log.toasts.join('|'));
}

// ── an empty name is refused, without closing what was typed away ──
{
  const h=makeHarness();
  h.env.add();
  h.els['ne-name'].value='   ';
  await h.env.create();
  ck('a blank name creates nothing', h.log.posted===null);
  ck('the dialog stays open', h.log.closed===0);
  ck('and the field is handed back', h.log.focused===2);
  ck('with a reason', h.log.toasts.includes('צריך שם לסביבה'), h.log.toasts.join('|'));
}

// ── the server's own refusal is what the user is told ──
{
  const h=makeHarness({createThrows:Object.assign(new Error('403'),{detail:'אין לך הרשאה ליצור סביבה'})});
  h.env.add();
  h.els['ne-name'].value='חדשה';
  await h.env.create();
  ck('a refusal from the server is shown as it was written',
     h.log.toasts.includes('אין לך הרשאה ליצור סביבה'), h.log.toasts.join('|'));
  ck('and nothing is closed or reloaded behind it', h.log.closed===0 && h.log.loaded===0);
}

// ── the permission and the phone are checked before anything opens ──
{
  const h=makeHarness({cap:false});
  h.env.add();
  ck('without the capability no dialog opens', h.log.modal===null);
  ck('and it says why', h.log.toasts.includes('אין לך הרשאה ליצור סביבה'));

  const h2=makeHarness({mobile:true});
  h2.env.add();
  ck('on a phone it is blocked before the permission check', h2.log.modal===null && !h2.log.toasts.length);
}

// ── the system-admin table opens the same dialog, with its own ending ──
{
  const h=makeHarness();
  let refreshed=0;
  h.env.add({done:()=>{ refreshed++; }});
  ck('the admin screen gets the same dialog, not a second one',
     (h.log.modal||'').includes('<h2>סביבה חדשה</h2>'));
  h.els['ne-name'].value='אגף התחבורה';
  await h.env.create();
  ck('its own list is what gets refreshed', refreshed===1);
  ck('and the admin is not moved into the new environment', h.log.selected===null,
     String(h.log.selected));
  ck('while the switcher is still brought up to date', h.log.loaded===1);
  ck('and the callback never leaks into the request body',
     !('done' in h.log.posted.body), JSON.stringify(h.log.posted.body));
}

// ── the preview echoes text, never markup ──
{
  const h=makeHarness();
  h.env.add();
  const name=h.els['ne-name'], pv=h.els['ne-pv-name'];
  name.value='<img src=x onerror=alert(1)>';
  h.env._preview();
  ck('the preview sets text, so a typed tag stays a typed tag',
     pv.textContent==='<img src=x onerror=alert(1)>', pv.textContent);
  name.value='   ';
  h.env._preview();
  ck('an empty name falls back to the placeholder', pv.textContent==='סביבה חדשה');
  ck('and the placeholder is marked as one', pv.classList.contains('ghost'));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
