/* The formula engine, run exactly as index.html defines it.
   Driven by tests/test_formula_engine.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const from = src.indexOf('/* ===== formula column =====');
const to   = src.indexOf('function findAnyTask(id){');
if(from < 0 || to < 0) throw new Error('formula engine not found');
const {formulaEval, FORMULA_FUNCS, evalFormula, setBoard} = new Function(
  'customColumns','cellValue',
  src.slice(from, to) + '\nreturn {formulaEval, FORMULA_FUNCS, evalFormula};')(
  () => COLS, (t, id) => (t.custom_fields||{})[id]);

let COLS = [];
let pass=0, fail=0;
const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};
const ev=(f,refs={})=>formulaEval(f, k => (k in refs ? refs[k] : null));
const eq=(name,f,want,refs)=>{ let got; try{ got=ev(f,refs); }catch(e){ got='⚠ '+e.message; }
  ck(`${name}: ${f}`, String(got)===String(want), `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`); };

// ── arithmetic, as before ──
eq('plus','1 + 2', 3);
eq('precedence','2 + 3 * 4', 14);
eq('brackets','(2 + 3) * 4', 20);
eq('unary minus','-3 + 10', 7);
eq('decimals','1.5 * 2', 3);
eq('a reference','{שעות} * 2', 42, {'שעות':21});
eq('two references','{א} - {ב}', 4, {'א':10,'ב':6});
ck('division by zero is refused rather than answered Infinity',
   (()=>{ try{ ev('1/0'); return false; }catch(e){ return true; } })());

// ── the functions a monday board actually arrives with ──
eq('IF true','IF({ימים} < 30, "בזמן", "באיחור")', 'בזמן', {'ימים':12});
eq('IF false','IF({ימים} < 30, "בזמן", "באיחור")', 'באיחור', {'ימים':44});
eq('IF on a status label','IF({סטטוס} = "בוצע", 1, 0)', 1, {'סטטוס':'בוצע'});
eq('IF with one arm answers nothing when it is false','IF({x} > 1, "כן")', null, {'x':0});
eq('ROUND','ROUND(3.14159, 2)', 3.14);
eq('ROUND to integer','ROUND(2.6)', 3);
eq('ROUNDUP','ROUNDUP(2.1)', 3);
eq('ROUNDDOWN','ROUNDDOWN(2.9)', 2);
eq('ABS','ABS(0 - 7)', 7);
eq('SUM','SUM({א}, {ב}, 5)', 20, {'א':10,'ב':5});
eq('AVERAGE','AVERAGE(2, 4, 6)', 4);
eq('MIN/MAX','MAX(1, 9) - MIN(1, 9)', 8);
eq('POWER','POWER(2, 10)', 1024);
eq('SQRT','SQRT(81)', 9);
eq('DIVIDE guards zero','DIVIDE(10, 0)', null);
eq('CONCATENATE','CONCATENATE({א}, " - ", {ב})', 'ראשון - שני', {'א':'ראשון','ב':'שני'});
eq('LEN','LEN("שלום")', 4);
eq('LEFT/RIGHT','CONCATENATE(LEFT("abcdef", 2), RIGHT("abcdef", 2))', 'abef');
eq('UPPER','UPPER("abc")', 'ABC');
eq('TRIM','TRIM("  x  ")', 'x');
eq('SEARCH found','SEARCH("cd", "abcdef")', 3);
eq('SEARCH missing','SEARCH("zz", "abcdef")', 0);
eq('AND','AND(1 = 1, 2 > 1)', true);
eq('OR','OR(1 = 2, 2 > 1)', true);
eq('NOT','NOT(1 = 2)', true);
eq('nested','IF(AND({א} > 0, {ב} > 0), ROUND({א} / {ב}, 1), "—")', 3.3, {'א':10,'ב':3});

// ── dates ──
eq('DAYS','DAYS("2026-01-31", "2026-01-01")', 30);
eq('YEAR','YEAR("2026-09-14")', 2026);
eq('MONTH','MONTH("2026-09-14")', 9);
eq('DAY','DAY("2026-09-14")', 14);
eq('ADD_DAYS','ADD_DAYS("2026-01-01", 31)', '2026-02-01');
eq('FORMAT_DATE','FORMAT_DATE("2026-09-14")', '14/09/2026');
ck('TODAY is today', /^\d{4}-\d{2}-\d{2}$/.test(ev('TODAY()')));

// ── comparisons pick the right kind ──
eq('numbers compare as numbers','IF(9 > 10, "a", "b")', 'b');
eq('text compares as text','IF("בוצע" = "בוצע", "כן", "לא")', 'כן');
eq('a blank reference is not a crash','IF({x} = "", "ריק", "מלא")', 'ריק', {});

// ── what must NOT happen ──
const bad=(name,f)=>{ let threw=false; try{ ev(f); }catch(e){ threw=true; }
  ck(name, threw, 'it did not refuse: '+f); };
bad('an unknown function is refused, not guessed', 'VLOOKUP(1,2,3)');
bad('code is not code', 'constructor("return 1")()');
bad('property access is not a formula', 'window.alert');
bad('an unclosed bracket is refused', '(1 + 2');
bad('trailing junk is refused', '1 + 2)');
const code = src.slice(from, to).replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
ck('no eval and no Function in the engine ITSELF, comments aside',
   !/[^a-zA-Z]eval\s*\(|new\s+Function/.test(code), code.slice(0,60));

// ── the column, end to end ──
COLS=[{id:'c1',title:'שעות',type:'number'},{id:'c2',title:'בוצע',type:'checkbox'},
      {id:'c3',title:'סטטוס',type:'status'},{id:'f',title:'תוצאה',type:'formula'}];
const task={custom_fields:{c1:21, c2:true, c3:'בוצע'}};
ck('a formula column computes from the item',
   evalFormula({id:'f',title:'תוצאה',formula:'{שעות} * 2'}, task)===42);
ck('a checkbox reads as 1 or 0',
   evalFormula({id:'f',formula:'IF({בוצע} = 1, "כן", "לא")'}, task)==='כן');
ck('a status reads as its label',
   evalFormula({id:'f',formula:'IF({סטטוס} = "בוצע", "סגור", "פתוח")'}, task)==='סגור');
ck('a broken formula shows nothing rather than an error',
   evalFormula({id:'f',formula:'IF(('}, task)===null);
ck('a formula naming a column that is not here shows nothing',
   evalFormula({id:'f',formula:'{אין כזו} * 2'}, task)===null);
ck('a formula cannot read its own column',
   evalFormula({id:'f',title:'תוצאה',formula:'{תוצאה} + 1'}, task)===null);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
