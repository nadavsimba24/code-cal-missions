/* A number column that says what the number is: a unit beside the figure, and
   thousands that are grouped or not.

   The line this draws is between the value and its presentation. The cell
   stores a number and only a number — so the board can be sorted on it, a
   formula can add it up, and the export hands Excel something it will treat as
   a figure rather than as the string "1,234 ₪". Everything here is about how
   that number is read, and nothing here changes what is kept.
   Driven by tests/test_number_format.py. */
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
const LEAD = /^const NUM_LEAD=.*$/m.exec(src)[0];

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── how a figure is written ────────────────────────────────────────────────
const {fnum,numCfg} = new Function(
  [LEAD, grab('numCfg'), grab('fnum'), 'return {fnum,numCfg};'].join('\n'))();
const col = (unit,thousands)=>({number:{unit,thousands}});

ck('a plain number column is still a plain number',
   fnum(1234.5,{})==='1234.5', fnum(1234.5,{}));
ck('the shekel sign follows the figure, the way it is written in Hebrew',
   fnum(1234,col('₪',false))==='1234 ₪', fnum(1234,col('₪',false)));
ck('the dollar sign leads it, the way it is written in English',
   fnum(1234,col('$',false))==='$1234', fnum(1234,col('$',false)));
ck('a unit of someone\'s own follows the figure',
   fnum(90,col('מ"ר',false))==='90 מ"ר', fnum(90,col('מ"ר',false)));
ck('the euro, the pound and the yen lead as well',
   ['€','£','¥'].every(u=>fnum(5,col(u,false))===u+'5'));

ck('the thousands are grouped when asked for',
   fnum(1234567,col('',true))==='1,234,567', fnum(1234567,col('',true)));
ck('and left alone when not',
   fnum(1234567,col('',false))==='1234567', fnum(1234567,col('',false)));
ck('a unit and a separator together',
   fnum(1234567.5,col('₪',true))==='1,234,567.5 ₪', fnum(1234567.5,col('₪',true)));
ck('the decimals survive the grouping — a budget is not rounded for being shown',
   fnum(1234.56,col('',true))==='1,234.56', fnum(1234.56,col('',true)));
ck('a long decimal is not cut off either',
   fnum(0.123456789,col('',true))==='0.123456789', fnum(0.123456789,col('',true)));
ck('a negative figure keeps its sign in front of the digits',
   fnum(-1234,col('₪',true))==='-1,234 ₪', fnum(-1234,col('₪',true)));
ck('zero is a number and is shown', fnum(0,col('₪',true))==='0 ₪', fnum(0,col('₪',true)));

/* an empty cell is empty — not "0", and not "0 ₪", which would read as a
   budget of nothing where there is no budget entered at all */
ck('an empty cell stays empty', fnum(null,col('₪',true))==='' && fnum('',col('₪',true))==='');
ck('and so does a cell holding nothing numeric',
   fnum('שלום',col('₪',true))==='שלום', fnum('שלום',col('₪',true)));
ck('a column that was never configured formats as a plain number',
   fnum(1234,{number:null})==='1234' && fnum(1234,undefined)==='1234');

// ── and what is stored is still the number ─────────────────────────────────
const calls=[], toasts=[];
const setNumCell = new Function('setCell','toast',
  [LEAD, grab('setNumCell'), 'return setNumCell;'].join('\n'))(
    (...a)=>calls.push(a), m=>toasts.push(m));
const cell = v => ({value:v, dataset:{}, focus(){}});
const {numFocus} = new Function(grab('numFocus')+'\nreturn {numFocus};')();

let el=cell('1234'); await setNumCell(1,'c',el);
ck('a typed figure is stored as a number, not as a string',
   calls.length===1 && calls[0][2]===1234 && typeof calls[0][2]==='number',
   JSON.stringify(calls[0]));

calls.length=0; el=cell('1,234,567');  await setNumCell(1,'c',el);
ck('a figure pasted out of a spreadsheet brings its commas and loses them here',
   calls[0][2]===1234567, JSON.stringify(calls[0]));

calls.length=0; el=cell('1,234 ₪');  await setNumCell(1,'c',el);
ck('typing over the formatted value means the figure inside it',
   calls[0][2]===1234, JSON.stringify(calls[0]));

calls.length=0; el=cell('$1,234.5'); await setNumCell(1,'c',el);
ck('and so does typing over a leading symbol',
   calls[0][2]===1234.5, JSON.stringify(calls[0]));

calls.length=0; el=cell('-1,234'); await setNumCell(1,'c',el);
ck('a negative figure is stored negative', calls[0][2]===-1234, JSON.stringify(calls[0]));

calls.length=0; el=cell('   '); await setNumCell(1,'c',el);
ck('clearing the cell clears the value rather than storing a zero',
   calls.length===1 && calls[0][2]===null, JSON.stringify(calls[0]));

calls.length=0; toasts.length=0;
el=cell('לא מספר'); el.dataset.raw='99'; await setNumCell(1,'c',el);
ck('something that is not a figure is refused, not stored as NaN', calls.length===0);
ck('the person is told why', toasts.length===1, JSON.stringify(toasts));
ck('the last good figure is left where it was', el.dataset.raw==='99', el.dataset.raw);
/* and the typo stays on screen: reformatting it back to 99 on the way out
   would throw away the keystrokes the toast just asked to have corrected */
const {numBlur} = new Function('fnum','numColOf',
  grab('numBlur')+'\nreturn {numBlur};')(()=>'99',()=>({}));
numBlur(el);
ck('and the cell keeps the keystrokes so they can be corrected',
   el.value==='לא מספר', el.value);
const fixed=cell('לא מספר'); fixed.dataset={raw:'99',bad:'1'};
numFocus(fixed);
ck('clicking back into it does not wipe them either', fixed.value==='לא מספר', fixed.value);
numBlur(Object.assign(fixed,{dataset:{raw:'99'}}));
ck('once it is corrected the cell formats again', fixed.value==='99', fixed.value);

calls.length=0; el=cell('12.5'); await setNumCell(1,'c',el);
ck('the cell remembers the bare figure for the next time it is edited',
   el.dataset.raw==='12.5', el.dataset.raw);

// ── the way in and the way out of an edit ──────────────────────────────────
const e2={value:'1,234 ₪',dataset:{raw:'1234'}};
numFocus(e2);
ck('clicking into a cell shows the figure, which is what can be typed over',
   e2.value==='1234', e2.value);

// ── the screen that sets it ────────────────────────────────────────────────
ck('the column menu offers the settings on a number column, and only there',
   /c\.type==='number'\?`<button[^`]*numberSettings/.test(src));
const dlg = grab('numberSettings');
for(const [name,re] of [['ללא',/'',\s*'ללא'/],['ש"ח',/'₪',\s*'ש"ח'/],
                        ['דולר',/'\$',\s*'דולר'/]])
  ck(`the dialog offers ${name}`, re.test(src));
ck('and a unit of your own', /בחירה חופשית/.test(dlg) && /id="num-free"/.test(dlg));
ck('the free-text unit is capped rather than being any length at all',
   /maxlength="6"/.test(dlg));
ck('the thousands separator is its own choice, not tied to the unit',
   /id="num-thou"/.test(dlg) && /type="checkbox"/.test(dlg));
ck('a preview shows what the cell will look like before it is saved',
   /id="num-prev"/.test(dlg) && /numPrevUpd/.test(src));

const {numDlgCfg} = new Function('document',
  grab('numDlgCfg')+'\nreturn {numDlgCfg};')({
    querySelector:()=>({value:'custom'}),
    getElementById:id=>id==='num-free'?{value:'  טון  '}:{checked:true}});
ck('a unit of your own is trimmed before it is stored',
   numDlgCfg().unit==='טון', JSON.stringify(numDlgCfg()));

/* the default is stored as nothing: a board nobody configured should not carry
   {unit:"",thousands:false} on every one of its number columns */
const save = grab('saveNumberSettings');
ck('a column set back to a plain number stores nothing at all',
   /\(cfg\.unit\|\|cfg\.thousands\)\?cfg:null/.test(save), save.slice(0,200));
ck('and the grid is redrawn, so the change is visible without a reload',
   /renderView\(\)/.test(save));
ck('duplicating a column carries how it is shown',
   /duplicateColumn[\s\S]{0,600}?number:c\.number/.test(src));

// ── what the presentation must not touch ───────────────────────────────────
const exp = src.slice(src.indexOf("case 'number':"), src.indexOf("case 'number':")+120);
ck('the export writes the number itself, so Excel sees a figure',
   /Number\(v\)/.test(exp) && !/fnum/.test(exp), exp.slice(0,90));
ck('the cell reads left-to-right, so the digits and the symbol keep their order',
   /\.cc-num\{[^}]*direction:ltr/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
