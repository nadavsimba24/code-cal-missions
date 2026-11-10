/* The browser's formula engine, lifted out of index.html for comparison.
 *
 * It exists so the server's engine can be compared with it rather than
 * assumed equal to it — see tests/test_formula_parity.py. Nothing is
 * re-implemented here: every function is the real one, cut out of the page
 * by name, so a change to the page is a change to what this runs.
 *
 * Reads a JSON array of {src, refs} on argv[2] and prints a JSON array of
 * {ok, value} / {ok:false, error}. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

/* Why these cut on a closing brace at column 0 rather than by counting
 * braces: the functions wanted here contain braces that are not structure.
 * `_fdate` holds /^(\d{4})-(\d{2})/ and `formulaTokens` holds the literals
 * '{' and '}' — a counter walks straight into them and stops in the middle
 * of a function. This file puts every top-level closing brace in column 0,
 * which is a fact about its formatting and a reliable one; the naive
 * counter is not. */
function cutAt(startIdx, closer){
  const end = src.indexOf('\n' + closer, startIdx);
  if(end < 0) throw new Error('unterminated at ' + startIdx);
  return src.slice(startIdx, end + 1 + closer.length);
}
function grabFn(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(src);
  if(!m) throw new Error('not found: ' + name);
  return cutAt(m.index, '}') + '\n';
}
function grabConstObj(name){
  const m = new RegExp(`^const ${name} = \\{`, 'm').exec(src);
  if(!m) throw new Error('not found: ' + name);
  return cutAt(m.index, '};') + '\n';
}
function grabLine(name){
  const m = new RegExp(`^const ${name} = .*$`, 'm').exec(src);
  if(!m) throw new Error('not found: ' + name);
  return m[0] + '\n';
}

const engine =
    grabConstObj('FORMULA_FUNCS')
  + grabLine('_fpad')
  + grabLine('_fflat')
  + grabFn('_fnum')
  + grabFn('_ftext')
  + grabFn('_ftruthy')
  + grabFn('_fdate')
  + grabFn('_fround')
  + grabFn('_fceilfloor')
  + grabFn('formulaTokens')
  + grabFn('_fcmp')
  + grabFn('formulaEval')
  + 'return {formulaEval};';

const {formulaEval} = new Function(engine)();

const cases = JSON.parse(process.argv[2] || '[]');
const out = cases.map(c => {
  try {
    const lookup = ref => {
      if(!(ref in (c.refs || {}))) throw new Error('אין עמודה בשם ' + ref);
      return c.refs[ref];
    };
    const v = formulaEval(c.src, lookup);
    return {ok: true, value: v === undefined ? null : v};
  } catch (e) {
    return {ok: false, error: String(e && e.message || e)};
  }
});
process.stdout.write(JSON.stringify(out));
