/* The formula an imported column carries, in the column menu.

   An imported formula column is a TEXT column holding the value monday worked
   out, with the expression kept on the column. Kept somewhere nobody can reach
   is the same as not kept, so the menu shows it and offers turning the column
   into a live formula column — for a column that has one, and never for a
   column that is already one.

   Driven by tests/test_import_formula.py. */
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

let cols=[], shown='';
/* colMenu also reads RETYPE_TYPES — the column types "שינוי סוג עמודה" is
   offered on. Passed in rather than stubbed so this harness keeps exercising
   the real menu; what the entry does is pinned by
   tests/frontend/column_retype_menu.mjs. */
const RETYPE_TYPES = new Function(
  /^const RETYPE_TYPES=[\s\S]*?;$/m.exec(src)[0]+'\nreturn RETYPE_TYPES;')();
/* …and formulaIsNumeric, which asks whether a formula answers with a number
   (the "הגדרות תצוגת מספר" entry). Stubbed: what it decides is pinned by
   tests/test_a_numeric_formula_is_shown_like_a_number.py. */
const colMenu = new Function('customColumns','st','isBoardAdmin','esc','openCellPop','ColPerms',
  'RETYPE_TYPES','formulaIsNumeric',
  grab('colMenu')+'\nreturn colMenu;')(
  ()=>cols, {board:{my_role:'admin'}}, ()=>true, x=>String(x==null?'':x),
  (el,html)=>{shown=html;}, {open(){}}, RETYPE_TYPES, ()=>false);

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(x?'  → '+x.slice(0,300):''))); };
const menu = c => { cols=[c]; shown=''; colMenu({stopPropagation(){},currentTarget:{}}, c.id); return shown; };

// ── a text column that came in carrying a formula ──────────────────────────
{
  const h = menu({id:'col_a', type:'text', title:'ימים לעליה לאויר',
                  formula:'DAYS({תאריך יעד}, TODAY())'});
  ck('the menu says the column carries an imported formula', h.includes('נוסחה מיובאת'), h);
  ck('and shows the expression itself, left-to-right',
     h.includes('DAYS({תאריך יעד}, TODAY())') && /dir="ltr"/.test(h), h);
  ck('it offers turning the column into a computing one',
     h.includes('makeFormulaCol(&#39;col_a&#39;)') || h.includes("makeFormulaCol('col_a')"), h);
  ck('and editing the formula', h.includes("editFormula(event,'col_a')"), h);
}

// ── a plain text column has none of it ─────────────────────────────────────
{
  const h = menu({id:'col_b', type:'text', title:'הערה'});
  ck('a column with no formula is not offered one',
     !h.includes('נוסחה מיובאת') && !h.includes('makeFormulaCol'), h);
}

// ── a column that is already a formula column ──────────────────────────────
{
  const h = menu({id:'col_c', type:'formula', title:'מחושבת', formula:'{א} * 2'});
  ck('it keeps its own "ערוך נוסחה" and is not offered the conversion',
     h.includes('ערוך נוסחה') && !h.includes('makeFormulaCol'), h);
  ck('and is not described as an imported formula', !h.includes('נוסחה מיובאת'), h);
}

// ── the conversion itself ──────────────────────────────────────────────────
const body = grab('makeFormulaCol');
ck('it asks with the app\'s own dialog, not a native confirm()',
   body.includes('askConfirm(') && !/\bconfirm\(/.test(body.replace(/askConfirm\(/g,'')), body);
ck('it names the column and shows the formula in the question',
   body.includes('c.title') && body.includes('esc(c.formula)'), body);
ck('it says the imported values are kept',
   body.includes('הערכים שמאנדיי חישב נשמרים'), body);
ck('it only changes the type — nothing about the cells is rewritten',
   /\{\.\.\.x,type:'formula'\}/.test(body) && !body.includes('custom_fields'), body);
ck('a column with no formula cannot be converted', /if\(!c\|\|!c\.formula\)return;/.test(body), body);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
