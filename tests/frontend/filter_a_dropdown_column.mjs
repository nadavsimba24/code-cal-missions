/* סינון על עמודת "רשימה נפתחת" — העמודה שמחזיקה כמה ערכים בתא אחד.

   A dropdown column is asked about as a status (ADV_KINDS maps both to
   'status', so both offer שווה ל / לא שווה ל / ריק / אינו ריק) and is not
   shaped like one. A status cell holds ONE option — `{label,color}` or a
   bare string. A dropdown cell holds the LIST of options ticked in it, which
   is the entire reason the type exists.

   advCell's status branch asked `typeof v === 'object'`, which an array
   answers yes to, then read `.label` off it and found nothing: every cell of
   every dropdown column on the board came back null. The column was drawn,
   its options were offered as chips, and picking one matched no rows at all
   — while "ריק" matched the whole board. A filter that looks like it did not
   run.

   What is pinned here: the cell reads as the list it is, a value matches when
   it is ONE OF the things ticked, "לא שווה ל" is the exact negation of that,
   emptiness is about the list and not about its repr, and the counts beside
   the chips tally each ticked value rather than the joined list.

   Driven by tests/test_filter_a_dropdown_column.py. */
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
/* A `const NAME = …;` declaration, taken to the first semicolon that is not
   inside anything — advEmpty and DERIVED_CELL both span lines. */
function grabConst(name){
  const m = new RegExp(`^const ${name}\\s*=`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  let d=0;
  for(let j=m.index;j<src.length;j++){
    const ch=src[j];
    if('([{'.includes(ch))d++;
    else if(')]}'.includes(ch))d--;
    else if(ch===';'&&d===0) return src.slice(m.index,j+1);
  }
  throw new Error('unbalanced: const '+name);
}

/* The column under test, in the shape the board holds one. "מי ביקש" is the
   real column this was reported on. */
const COL={id:'c_who',title:'מי ביקש',type:'dropdown',
           options:['ראש העיר','מהנדס העיר','תושב']};

const ROWS=[
  {id:1,title:'נזילה',        custom_fields:{c_who:['ראש העיר']}},
  {id:2,title:'מדרכה',        custom_fields:{c_who:['מהנדס העיר','ראש העיר']}},
  {id:3,title:'תאורה',        custom_fields:{c_who:['מהנדס העיר']}},
  {id:4,title:'לא נשאל',      custom_fields:{c_who:null}},
  {id:5,title:'נוקה',         custom_fields:{c_who:[]}},
];

function world(rows=ROWS,cols=[COL]){
  const st={board:{id:1,name:'לוח',tasks:rows.slice(),columns:cols,
                   groups:[],my_role:'admin',col_perms:{},col_hidden:[]},
            users:[],me:{id:1},filters:{}};
  const code=[
    grabConst('ADV_KINDS'), grab('advFields'), grab('advColGone'), grab('advColHidden'),
    grabConst('advField'), grabConst('DERIVED_CELL'), grab('advCell'),
    grabConst('advEmpty'), grab('advRuleMatch'), grab('advMatch'),
    grabConst('QF_COUNT_MAX'), grab('qfCounts'),
    ';return {advCell,advRuleMatch,advMatch,advFields,qfCounts};',
  ].join('\n');
  return new Function('st','customColumns','Paged','ADV_DATES','meId',
                      'statusKeyOf','priorityKeyOf','advDay','advSpan','advColHiddenX',
                      code)(
    st, ()=>cols, {on:false}, [], ()=>1,
    t=>t.status||null, t=>t.priority||null, v=>v, ()=>null, null);
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,220):''))); };
const F=world();
const field=F.advFields().find(f=>f.id==='c_who');
const titles=r=>ROWS.filter(t=>F.advRuleMatch(t,r)).map(t=>t.title);

// ── the cell reads as the list it is ──────────────────────────────────────
{
  ck('the column is offered, as a status', field&&field.kind==='status', JSON.stringify(field));
  const c=F.advCell(ROWS[1],field);
  ck('a cell with two options ticked reads as both',
     Array.isArray(c)&&c.length===2&&c.includes('ראש העיר')&&c.includes('מהנדס העיר'),
     JSON.stringify(c));
}

// ── שווה ל — "it is one of the things ticked" ─────────────────────────────
{
  const got=titles({field:'c_who',op:'eq',v:'ראש העיר'});
  ck('שווה ל finds every row that ticked it, alone or beside another',
     got.length===2&&got.includes('נזילה')&&got.includes('מדרכה'), JSON.stringify(got));
}
{
  const got=titles({field:'c_who',op:'eq',v:'מהנדס העיר'});
  ck('…and the same for the other option',
     got.length===2&&got.includes('מדרכה')&&got.includes('תאורה'), JSON.stringify(got));
}
{
  const got=titles({field:'c_who',op:'eq',v:'תושב'});
  ck('an option nobody ticked finds nothing', got.length===0, JSON.stringify(got));
}

// ── לא שווה ל is the exact negation, over the same board ──────────────────
{
  const yes=titles({field:'c_who',op:'eq',v:'ראש העיר'});
  const no =titles({field:'c_who',op:'ne',v:'ראש העיר'});
  ck('שווה ל and לא שווה ל divide the board between them',
     yes.length+no.length===ROWS.length && !yes.some(t=>no.includes(t)),
     JSON.stringify({yes,no}));
  ck('…and a row that ticked it is not in the "לא" half', !no.includes('נזילה'),
     JSON.stringify(no));
}

// ── ריק / אינו ריק are about the list, not its repr ───────────────────────
{
  const got=titles({field:'c_who',op:'empty'});
  ck('ריק catches a cell never filled AND one cleared back to []',
     got.length===2&&got.includes('לא נשאל')&&got.includes('נוקה'), JSON.stringify(got));
}
{
  const got=titles({field:'c_who',op:'filled'});
  ck('אינו ריק is the three that have something ticked',
     got.length===3&&!got.includes('נוקה'), JSON.stringify(got));
}

// ── a single-value status column is untouched by all of this ──────────────
{
  const S={id:'c_st',title:'סטטוס משני',type:'status',
           options:[{id:'o1',label:'בוצע',color:'#00c875'}]};
  const rows=[{id:1,title:'עם ערך',custom_fields:{c_st:{id:'o1',label:'בוצע'}}},
              {id:2,title:'מחרוזת',custom_fields:{c_st:'בוצע'}},
              {id:3,title:'ריק',   custom_fields:{c_st:null}}];
  const G=world(rows,[S]);
  const f=G.advFields().find(x=>x.id==='c_st');
  ck('a status object still reads as its label', G.advCell(rows[0],f)==='בוצע',
     JSON.stringify(G.advCell(rows[0],f)));
  const hit=rows.filter(t=>G.advRuleMatch(t,{field:'c_st',op:'eq',v:'בוצע'})).map(t=>t.title);
  ck('…and one option still matches by equality, object or string',
     hit.length===2&&hit.includes('עם ערך')&&hit.includes('מחרוזת'), JSON.stringify(hit));
}

// ── the counts beside the chips ───────────────────────────────────────────
{
  const n=F.qfCounts()['c_who'];
  ck('each ticked option is counted on its own chip',
     n['eq|ראש העיר']===2 && n['eq|מהנדס העיר']===2, JSON.stringify(n));
  ck('…and nothing is counted under the joined list',
     !Object.keys(n).some(k=>k.includes(',')), JSON.stringify(Object.keys(n)));
  ck('ריק counts the two empty cells', n['empty|']===2, JSON.stringify(n));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
