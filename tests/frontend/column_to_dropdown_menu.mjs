/* "המרה לרשימה נפתחת" — who is offered it, and on which columns.

   The entry has to be decided in the browser, before the server is asked
   anything: a menu that offers a conversion the server would refuse with a
   400 is a menu that teaches people not to trust it. So the browser carries
   its own copy of the convertible types (DROPDOWN_SOURCES), and the column
   menu reads it.

   Two mistakes are easy here and both are silent. Offering it on a date, a
   person or a מזהה פריט column — none of which holds a vocabulary, so the
   conversion could only ever throw the cells away. And offering it to an
   editor, who is not allowed to change a column at all and would get a 403
   after being invited to press the button.

   Driven by tests/test_column_becomes_a_dropdown.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i = src.indexOf('{', m.index), d = 0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index, j+1);} }
  throw new Error('unbalanced: '+name);
}
const konst = name => {
  const m = new RegExp(`^const ${name}\\s*=[\\s\\S]*?;$`, 'm').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return m[0];
};

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+JSON.stringify(x):''))); };

const COLS = [
  {id:'c_text',   type:'text',       title:'תחום'},
  {id:'c_long',   type:'long_text',  title:'תיאור'},
  {id:'c_num',    type:'number',     title:'אזור'},
  {id:'c_status', type:'status',     title:'שלב', options:[]},
  {id:'c_rate',   type:'rating',     title:'ציון'},
  {id:'c_date',   type:'date',       title:'יעד'},
  {id:'c_people', type:'people',     title:'בודק'},
  {id:'c_files',  type:'files',      title:'קבצים'},
  {id:'c_iid',    type:'item_id',    title:'מזהה'},
  {id:'c_made',   type:'created_at', title:'נוצר'},
  {id:'c_drop',   type:'dropdown',   title:'כבר רשימה', options:['א']},
];

/* The menu, run for one column, as one role. Returns the HTML it would open:
   openCellPop is the only thing it touches outside itself. */
function menuFor(colId, role){
  let html='';
  const sandbox = {
    st:{board:{id:1, my_role:role, columns:COLS, col_perms:{}}},
    openCellPop:(_a,h)=>{ html=h; },
    esc:s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    Views:{active:null},
    isSysAdmin:()=>false,
  };
  const body = [grab('colMenu'), grab('customColumns'), grab('isBoardAdmin'),
                konst('DROPDOWN_SOURCES')].join('\n');
  const run = new Function('sandbox', `with(sandbox){ ${body}
    colMenu({stopPropagation(){}, currentTarget:null}, ${JSON.stringify(colId)}); }`);
  run(sandbox);
  return html;
}
const offers = (colId, role='admin') => menuFor(colId, role).includes('convertColToDropdown');

// ── the types that hold a list ──
for(const id of ['c_text','c_long','c_num','c_status','c_rate'])
  ck('offered on '+id, offers(id));

// ── and the ones that do not ──
for(const id of ['c_date','c_people','c_files','c_iid','c_made'])
  ck('not offered on '+id, !offers(id));

ck('not offered on a column that is already a list', !offers('c_drop'));

// ── and only to the board admin ──
ck('an editor is not offered it', !offers('c_text','editor'));
ck('a viewer is not offered it',  !offers('c_text','viewer'));

// ── the entry says what it does, and is not the deletion ──
const m = menuFor('c_text','admin');
ck('the menu names it in the board’s language', m.includes('המרה לרשימה נפתחת'), m);
ck('and it is not styled as the destructive one',
   !/color:var\(--red\)[^>]*convertColToDropdown/.test(m));
ck('the delete entry is still the only red one',
   (m.match(/color:var\(--red\)/g)||[]).length===1);

// ── the two lists cannot drift apart unnoticed ──
const inBrowser = JSON.parse(konst('DROPDOWN_SOURCES')
  .replace(/^const DROPDOWN_SOURCES\s*=\s*/,'').replace(/;$/,'').replace(/'/g,'"'));
ck('every convertible type is a type the picker can create',
   inBrowser.every(t=>/\{type:'(\w+)'/.test(src) && src.includes(`{type:'${t}',he:`)),
   inBrowser.filter(t=>!src.includes(`{type:'${t}',he:`)));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
