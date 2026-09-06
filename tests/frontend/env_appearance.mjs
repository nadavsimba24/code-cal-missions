/* An environment's badge, and the picker that sets it.

   A new environment is created with no icon at all and wears its creator's
   avatar — the colour-and-initials circle that already identifies that person
   everywhere else — instead of the same 🏢 every other environment had. The
   system-admin table is where it gets a face of its own afterwards: a colour,
   a glyph on that colour, or a picture.

   Runs the real envIconHTML and the real SysAdmin picker out of index.html.
   Driven by tests/test_env_appearance.py. */
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
function grabObject(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1)+';'; } }
}
const GLYPHS = /^const ENV_GLYPHS=[\s\S]*?\];/m.exec(src)[0];
const COLORS = /^const ENV_COLORS=[\s\S]*?\];/m.exec(src)[0];

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

const esc = s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ── the badge ──
function iconFor(env, users=[]){
  return new Function('st','esc','initials', grab('envIconHTML')+'; return envIconHTML;')
    ({users}, esc, n=>(n||'?').trim().split(/\s+/).slice(0,2).map(w=>w[0]).join(''))(env);
}

{
  const glyph=iconFor({icon:'fa:bolt', color:'#10b981'});
  ck('a glyph is drawn on the environment colour',
     glyph.includes('fa-bolt') && glyph.includes('#10b981'), glyph);

  const img=iconFor({icon:'/api/files/abc123'});
  ck('an uploaded picture is drawn as an image',
     /<img src="\/api\/files\/abc123"/.test(img), img);
  ck('and nothing else is treated as a URL',
     !iconFor({icon:'🏛️'}).includes('<img'), iconFor({icon:'🏛️'}));

  const emoji=iconFor({icon:'🏛️'});
  ck('an emoji still shows, for every row set before this existed',
     emoji.includes('🏛️'), emoji);

  ck('an emoji sits on the environment colour too, so a colour pick shows there',
     iconFor({icon:'🏛️', color:'#f59e0b'}).includes('#f59e0b'));

  const av=iconFor({icon:'', created_by:7, color:'#e2445c'}, [{id:7,name:'שלי פיינברג'}]);
  ck('with no icon it wears the creator’s initials',
     av.includes('שפ'), av);
  ck('on the environment colour, which is what the editor sets',
     av.includes('#e2445c'), av);
  ck('and a missing icon field counts as none',
     iconFor({created_by:7}, [{id:7,name:'שלי פיינברג'}]).includes('שפ'));
  ck('a real photo still wins, as it does everywhere a person appears',
     iconFor({icon:'', created_by:7}, [{id:7,name:'שלי',avatar_url:'/api/files/pic'}]).includes('<img'));
  ck('a creator not in the directory yet leaves a mark, not a hole',
     iconFor({icon:'', created_by:99, color:'#10b981'}, [{id:7,name:'שלי'}]).includes('?'));
  ck('whitespace is not an icon',
     iconFor({icon:'   ', created_by:7}, [{id:7,name:'שלי פיינברג'}]).includes('שפ'));
}

// ── the picker ──
function makePicker({env={id:3,name:'אגף החינוך',icon:'',color:'#6366f1',can_manage:true,created_by:7},
                     sysadmin=true, patchThrows=null}={}){
  const log={modal:null, toasts:[], patched:null, reloaded:0, envLoaded:0, closed:0, html:{}};
  const els={};
  const el=id=>els[id]||(els[id]={innerHTML:''});
  ['el-preview','el-colors','el-icons'].forEach(el);
  // the modal element itself: the picker narrows it by class
  els['modal']={classList:{_s:new Set(), add(c){this._s.add(c);}, remove(){}, contains(c){return this._s.has(c);}}};
  const window={};
  const api=new Function(
    'window','document','showModal','closeModals','api','toast','meId','isSysAdmin',
    'envIconHTML','esc','Env','authHeaders','FormData','fetch',
    [GLYPHS, COLORS, grabObject('SysAdmin'), 'return SysAdmin;'].join('\n'))(
    window,
    {getElementById:id=>els[id]||null, createElement:()=>({click(){}, style:{}}),
     addEventListener(){}, removeEventListener(){}, querySelectorAll:()=>[]},
    html=>{ log.modal=html; },
    ()=>{ log.closed++; },
    async (p,o)=>{ log.patched={path:p, body:JSON.parse(o.body)};
                   if(patchThrows) throw patchThrows; return {}; },
    t=>log.toasts.push(t),
    ()=>1, ()=>sysadmin,
    e=>`[icon ${e.icon||'avatar'} on ${e.color}]`,
    esc,
    {load:async()=>{ log.envLoaded++; }},
    ()=>({}), function(){}, async()=>({ok:false}));   // the palettes come from the grabbed consts
  api.envs=[env];
  api.reloadEnvs=async()=>{ log.reloaded++; };
  return {sa:api, log, els, window};
}

{
  const p=makePicker();
  p.sa.editLook(3);
  const m=p.log.modal||'';
  ck('the picker opens as a modal in the house shape',
     m.includes('<h2>מראה הסביבה</h2>') && m.includes('class="mbody"') && m.includes('class="mfoot"'));
  ck('it has a colour section and an icon section',
     m.includes('צבע רקע') && m.includes('אייקון'), m.slice(0,80));
  ck('and a way to upload your own', m.includes('העלאת אייקון משלך'));
  ck('and a way back to the creator’s avatar', m.includes('אפס לאווטאר של היוצר'));
  ck('the modal is put into its narrow form', p.els['modal'].classList.contains('modal-narrow'));
  ck('the reset sits with the icons, not in a footer too narrow for three buttons',
     m.indexOf('ep-reset') < m.indexOf('mfoot') && (m.match(/class="btn /g)||[]).length===2);
  ck('the modal is narrowed for a picker',
     /\.modal\.modal-narrow\{width:340px\}/.test(src));
  ck('the swatches and tiles are sized in pixels, not stretched to the grid',
     /\.ep-colors\{[^}]*repeat\(8,26px\)/.test(src) && /\.ep-icons\{[^}]*repeat\(5,44px\)/.test(src));
  ck('and the narrow class is cleared for whatever opens next',
     /showModal\(html\)\{[^}]*modal-narrow/.test(src) && /function closeModals\(\)\{[^}]*modal-narrow/.test(src));

  ck('every colour is offered',
     (p.els['el-colors'].innerHTML.match(/class="ep-color/g)||[]).length===24,
     String((p.els['el-colors'].innerHTML.match(/class="ep-color/g)||[]).length));
  ck('every glyph is offered',
     (p.els['el-icons'].innerHTML.match(/class="ep-icon/g)||[]).length===20);
  ck('the current colour is the one marked, with a check like the design',
     /class="ep-color sel"[^>]*background:#6366f1[^>]*>\s*<i class="fa-solid fa-check">/.test(p.els['el-colors'].innerHTML),
     p.els['el-colors'].innerHTML.slice(0,160));
  ck('exactly one swatch is marked', (p.els['el-colors'].innerHTML.match(/ep-color sel/g)||[]).length===1);
  ck('the glyph tiles wear the chosen colour',
     p.els['el-icons'].innerHTML.includes('background:#6366f1'));
}

// ── a colour off the grid is still shown as the one in effect ──
{
  // #e2698e is in the avatar palette and not in the picker's own
  const p=makePicker({env:{id:3,name:'x',icon:'',color:'#e2698e',can_manage:true,created_by:7}});
  p.sa.editLook(3);
  const html=p.els['el-colors'].innerHTML;
  ck('an off-grid colour is added rather than left unmarked', html.includes('#e2698e'), html.slice(0,120));
  ck('and it is the marked one', /class="ep-color sel"[^>]*background:#e2698e/.test(html));
  ck('exactly one swatch is marked', (html.match(/ep-color sel/g)||[]).length===1);
  ck('and it is offered first, where the eye starts',
     html.indexOf('#e2698e') < html.indexOf('#6366f1'));
}

// ── picking, and what gets written ──
{
  const p=makePicker();
  p.sa.editLook(3);
  p.sa.pickColor('#ef4444');
  ck('picking a colour repaints the glyph tiles under it',
     p.els['el-icons'].innerHTML.includes('background:#ef4444'));
  ck('and marks the new colour', p.els['el-colors'].innerHTML.includes('class="ep-color sel" style="background:#ef4444"'));
  ck('and the preview badge changes with it — the point of picking a colour',
     p.els['el-preview'].innerHTML.includes('#ef4444'), p.els['el-preview'].innerHTML);
  p.sa.pickGlyph('fa:crown');
  ck('picking a glyph marks it', p.els['el-icons'].innerHTML.includes('class="ep-icon sel"'));
  ck('nothing is written until שמור', p.log.patched===null);

  await p.sa.saveLook();
  ck('save patches the environment', p.log.patched.path==='/api/environments/3');
  ck('with the chosen glyph', p.log.patched.body.icon==='fa:crown', p.log.patched.body.icon);
  ck('and the chosen colour', p.log.patched.body.color==='#ef4444', p.log.patched.body.color);
  ck('the table is refreshed', p.log.reloaded===1);
  ck('and the switcher too, because it wears the same badge', p.log.envLoaded===1);
  ck('and it closes', p.log.closed===1);
}

// ── resetting to the avatar is a real, storable choice ──
{
  const p=makePicker({env:{id:3,name:'x',icon:'fa:bolt',color:'#10b981',can_manage:true,created_by:7}});
  p.sa.editLook(3);
  p.sa.pickGlyph('');
  await p.sa.saveLook();
  ck('an empty icon is sent, not dropped',
     'icon' in p.log.patched.body && p.log.patched.body.icon==='',
     JSON.stringify(p.log.patched.body));
}

// ── who may open it ──
{
  const p=makePicker({env:{id:3,name:'x',icon:'',color:'#6366f1',can_manage:false,created_by:7}, sysadmin:false});
  p.sa.editLook(3);
  ck('someone who manages neither the system nor the environment is refused',
     p.log.modal===null && p.log.toasts.length===1, p.log.toasts.join('|'));

  const p2=makePicker({sysadmin:false});     // can_manage true → the env's own manager
  p2.sa.editLook(3);
  ck('the environment’s own manager may open it', !!p2.log.modal);
}

// ── a failing save says so and changes nothing ──
{
  const p=makePicker({patchThrows:Object.assign(new Error('403'),{detail:'רק מנהל מערכת או מנהל הסביבה'})});
  p.sa.editLook(3);
  await p.sa.saveLook();
  ck('a refusal is shown in the server’s own words',
     p.log.toasts.includes('רק מנהל מערכת או מנהל הסביבה'), p.log.toasts.join('|'));
  ck('and the picker stays open', p.log.closed===0);
  ck('and nothing is refreshed behind it', p.log.reloaded===0 && p.log.envLoaded===0);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
