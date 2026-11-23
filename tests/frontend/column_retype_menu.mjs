/* "שינוי סוג עמודה" — who is offered it, and on which columns.

   The entry has to be decided in the browser, before the server is asked
   anything: a menu that offers a conversion the server would refuse with a
   400 is a menu that teaches people not to trust it. So the browser carries
   its own copy of the convertible types (RETYPE_TYPES), and the column menu
   reads it.

   Two mistakes are easy here and both are silent. Offering it on a column
   that holds nothing of its own — a formula, a mirror, a מזהה פריט, a files
   column — where there is no value to carry across and the conversion could
   only ever empty the cells. And offering it to an editor, who is not
   allowed to change a column at all and would get a 403 after being invited
   to press the button.

   Driven by tests/test_column_type_conversion.py. */
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
  {id:'c_time',   type:'timeline',   title:'טווח'},
  {id:'c_check',  type:'checkbox',   title:'הושלם'},
  {id:'c_people', type:'people',     title:'בודק'},
  {id:'c_drop',   type:'dropdown',   title:'רשימה', options:['א']},
  {id:'c_files',  type:'files',      title:'קבצים'},
  {id:'c_conn',   type:'connect',    title:'מקושר'},
  {id:'c_form',   type:'formula',    title:'חישוב'},
  {id:'c_mir',    type:'mirror',     title:'מראה'},
  {id:'c_iid',    type:'item_id',    title:'מזהה'},
  {id:'c_made',   type:'created_at', title:'נוצר'},
  {id:'c_by',     type:'created_by', title:'יוצר'},
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
    // does a formula answer with a number — pinned by
    // tests/test_a_numeric_formula_is_shown_like_a_number.py, not here
    formulaIsNumeric:()=>false,
  };
  const body = [grab('colMenu'), grab('customColumns'), grab('isBoardAdmin'),
                konst('RETYPE_TYPES')].join('\n');
  const run = new Function('sandbox', `with(sandbox){ ${body}
    colMenu({stopPropagation(){}, currentTarget:null}, ${JSON.stringify(colId)}); }`);
  run(sandbox);
  return html;
}
const offers = (colId, role='admin') => menuFor(colId, role).includes('retypeColumn');

// ── the columns that hold a value of their own ──
for(const id of ['c_text','c_long','c_num','c_status','c_rate','c_date',
                 'c_time','c_check','c_people','c_drop'])
  ck('offered on '+id, offers(id));

// ── and the ones that hold nothing of their own ──
for(const id of ['c_files','c_conn','c_form','c_mir','c_iid','c_made','c_by'])
  ck('not offered on '+id, !offers(id));

// ── and only to the board admin ──
ck('an editor is not offered it', !offers('c_text','editor'));
ck('a viewer is not offered it',  !offers('c_text','viewer'));

// ── the entry says what it does, and is not the deletion ──
const m = menuFor('c_text','admin');
ck('the menu names it in the board’s language', m.includes('שינוי סוג עמודה'), m);
ck('and it is not styled as the destructive one',
   !/color:var\(--red\)[^>]*retypeColumn/.test(m));
ck('the delete entry is still the only red one',
   (m.match(/color:var\(--red\)/g)||[]).length===1);

// ── the picker never offers the type the column already is ──
const picker = new Function('COLUMN_TYPES','RETYPE_TYPES','c',
  'return COLUMN_TYPES.filter(t=>RETYPE_TYPES.includes(t.type)&&t.type!==c.type)'
  +'.sort((a,b)=>a.he.localeCompare(b.he,"he")).map(t=>t.type);');
const TYPES = new Function(konst('COLUMN_TYPES')+'\nreturn COLUMN_TYPES;')();
const RT = new Function(konst('RETYPE_TYPES')+'\nreturn RETYPE_TYPES;')();
for(const t of RT){
  const shown = picker(TYPES, RT, {type:t});
  ck(`the picker for a ${t} column omits ${t}`, !shown.includes(t), shown.join(','));
  ck(`and offers the other ${RT.length-1}`, shown.length===RT.length-1, shown.length);
}

// ── the two lists cannot drift apart unnoticed ──
ck('every convertible type is a type the picker can create',
   RT.every(t=>src.includes(`{type:'${t}',he:`)),
   RT.filter(t=>!src.includes(`{type:'${t}',he:`)));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
