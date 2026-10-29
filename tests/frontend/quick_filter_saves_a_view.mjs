/* Keeping the cut made in the quick filter panel.

   The advanced builder has carried "שמירה כתצוגה" beside its title since it
   was built. The panel most filtering actually happens in did not: a person
   picked three chips, got the board they wanted, and the only ways to keep it
   were a button on the tab strip above the board or opening the builder for
   the one button in it that does the same thing.

   So the foot of the panel now offers it too, in the same words and through
   the same two calls. These checks are about the routing — which of the two
   saves is taken, and when nothing is taken at all — which is the half that
   cannot be seen by looking at the panel.

   Driven by tests/test_filter_by_column.py. */
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

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+JSON.stringify(x):''))); };

/* qfSaveView with the world around it stubbed: what it does is decided by
   boardIsCut and by whether a view is open, and it is recorded here as the
   call it ends in rather than as anything on screen. */
function run({cut, active}){
  const log = {update:0, saveNew:0, toasts:[], closed:0};
  const fn = new Function('Views','boardIsCut','toast','closePops',
    grab('qfSaveView') + '\nreturn qfSaveView;')(
      {active, update(){log.update++;}, saveNew(){log.saveNew++;}},
      () => cut,
      m => log.toasts.push(m),
      () => log.closed++);
  fn();
  return log;
}

console.log('— the save at the foot of the filter panel —');

const fresh = run({cut:true, active:null});
ck('a board cut with no view open is saved as a NEW view',
   fresh.saveNew===1 && fresh.update===0, fresh);

const onView = run({cut:true, active:7});
ck('with a view open the cut is written back onto it',
   onView.update===1 && onView.saveNew===0, onView);

const nothing = run({cut:false, active:null});
ck('a board that is neither filtered nor sorted saves nothing',
   nothing.saveNew===0 && nothing.update===0 && nothing.toasts.length===1, nothing);

ck('the panel is closed before the name dialog is asked for',
   fresh.closed===1 && nothing.closed===0, {fresh:fresh.closed, nothing:nothing.closed});

/* And the button itself: drawn in the foot, pressable only while there is
   something to save, and saying which of the two saves it would be. */
const foot = /<div class="arr-foot">[\s\S]*?<\/div>/.exec(src);
ck('the foot of the panel draws the save', !!foot && /qf-save/.test(foot[0]));
ck('it calls qfSaveView', !!foot && /onclick="qfSaveView\(\)"/.test(foot[0]));
ck('it is disabled while the board holds no cut', !!foot && /\$\{cut\?'':'disabled'\}/.test(foot[0]));
ck('it names which save it is', !!foot &&
   /שמירה בתצוגה זו/.test(foot[0]) && /שמירה כתצוגה/.test(foot[0]));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
