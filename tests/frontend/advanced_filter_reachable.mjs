/* The advanced builder, reached from the foot of the filter panel.

   It had a button of its own in the toolbar, beside "סינון". Two buttons side
   by side were two doors into one filter — the panel and the builder edit the
   same condition tree — so the toolbar button is gone and the only way in is
   "מעבר לסינון מתקדם" at the foot of the panel.

   That makes this the check that nothing was lost with the button: the builder
   still opens, edits, applies and clears, and what it writes is what the panel
   reads back — and the other way round.

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
const konst = name => {
  const m = new RegExp(`^const ${name}\\s*=[\\s\\S]*?;$`, 'm').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return m[0];
};
/* The Adv object itself, verbatim. */
function advObject(){
  const i = src.indexOf('const Adv = {');
  let d = 0;
  for(let j=src.indexOf('{', i); j<src.length; j++){
    if(src[j]==='{')d++; else if(src[j]==='}'){ d--; if(!d) return src.slice(i, j+1); }
  }
  throw new Error('unbalanced: Adv');
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+JSON.stringify(x):''))); };

function world(){
  const st = {
    board:{id:1, col_perms:{}, members:[{id:3}],
      columns:[{id:'col_a', type:'status', title:'שלב',
                options:[{label:'בעבודה',color:'#fdab3d'},{label:'תקוע',color:'#e2445c'}]}],
      tasks:[]},
    users:[{id:3,name:'דנה'}], me:{id:3}, colSort:null,
    filters:{q:'',people:[],status:'',priority:'',sort:'',links:{col:'',mode:'',item:0},adv:null,advIds:null},
  };
  const log = {modals:0, closed:0, asked:0, toasts:[], redraws:0};
  const names = ['advFields','advColHidden','customColumns','advCount','advPicked','advPickedAll',
                 'advSetPicked','advToggle','advFilterRoot','advLegacyPicks','advDropLegacy',
                 'advChoices','advPersonLabel','boardPeople','statusColOpts','advToAst'];
  const body = names.map(grab).join('\n') + '\n'
    + konst('advOwnGroup') + '\n' + konst('advField') + '\n' + konst('ADV_OPS') + '\n'
    + konst('ADV_KINDS') + '\n' + konst('advOps') + '\n' + konst('advOpArity') + '\n'
    + `const ADV_DATES=[['today','היום']];\n`;
  const Adv = new Function(
    'st','esc','showModal','closeModals','document','refreshToolbar','renderView',
    'advAskServer','toast','boardStatusList','boardPriorityList','filterMode','STATUS_OPTS',
    body + '\n' + advObject() + '\nreturn Adv;')(
    st,
    x => String(x==null?'':x),
    () => { log.modals++; },
    () => { log.closed++; },
    {getElementById:()=>({classList:{add(){},remove(){}}, set innerHTML(v){log.redraws++;}})},
    () => {}, () => {},
    () => { log.asked++; },
    m => log.toasts.push(m),
    () => [{key:'done',he:'בוצע',c:'#00c875'}],
    () => [{key:'high',he:'גבוהה',c:'#e2445c'}],
    () => 'client',
    [{label:'x',color:'#c4c4c4'}]);
  /* The panel's own half of the same tree. advChanged is the redraw-and-ask
     step, which is not what these checks are about — they are about the two
     doors opening on one filter. */
  const panel = new Function('st','advChanged',
    names.slice(0,11).map(grab).join('\n') + '\n' + konst('advOwnGroup') + '\n'
    + konst('advField') + '\n' + konst('ADV_KINDS') + '\n'
    + ';return {advPicked,advPickedAll,advCount,advToggle};')(st, ()=>{});
  return [Adv, st, log, panel];
}

// ── it opens, and on what ─────────────────────────────────────────────────
{
  const [Adv, st, log] = world();
  Adv.open();
  ck('the builder opens', log.modals===1);
  ck('...on a copy, so closing with ✕ leaves the board as it was',
     JSON.stringify(Adv.draft)==='{"op":"and","rules":[]}', Adv.draft);
}
{
  const [Adv, st, log] = world();
  st.board = null;
  Adv.open();
  ck('with no board open it says so instead of opening on nothing',
     log.modals===0 && log.toasts.length===1, log.toasts);
}

// ── every edit the builder offers ─────────────────────────────────────────
{
  const [Adv, st, log] = world();
  Adv.open();
  Adv.addRule('');
  ck('a condition can be added', Adv.draft.rules.length===1, Adv.draft);
  Adv.setField('0','col_a');
  Adv.setRuleOp('0','eq');
  Adv.setV('0','v','תקוע');
  ck('...its column, its operator and its value can all be set',
     Adv.draft.rules[0].field==='col_a' && Adv.draft.rules[0].op==='eq'
     && Adv.draft.rules[0].v==='תקוע', Adv.draft.rules[0]);
  Adv.addGroup('');
  ck('a group can be added', Adv.draft.rules.length===2 && Adv.draft.rules[1].rules, Adv.draft);
  Adv.addRule('1');
  Adv.setField('1.0','status');
  ck('...and a condition inside it', Adv.draft.rules[1].rules.length===1
     && Adv.draft.rules[1].rules[0].field==='status', Adv.draft.rules[1]);
  Adv.setOp('1','or');
  ck('...with וגם/או of its own', Adv.draft.rules[1].op==='or');
  Adv.del('1');
  ck('anything can be deleted', Adv.draft.rules.length===1, Adv.draft);
}

// ── applying, and clearing ────────────────────────────────────────────────
{
  const [Adv, st, log] = world();
  Adv.open();
  Adv.addRule(''); Adv.setField('0','col_a'); Adv.setRuleOp('0','eq'); Adv.setV('0','v','תקוע');
  Adv.apply();
  ck('applying puts the conditions on the board',
     st.filters.adv && st.filters.adv.rules.length===1, st.filters.adv);
  ck('...closes the window', log.closed>=1);
  ck('...and asks the server the same question', log.asked===1);
  Adv.clear();
  ck('clearing empties the filter', st.filters.adv===null && st.filters.advIds===null);
}
{
  const [Adv, st] = world();
  Adv.open();
  Adv.apply();
  ck('a builder closed with nothing in it does not leave an empty filter behind',
     st.filters.adv===null, st.filters.adv);
}

// ── the two doors open on the same filter ─────────────────────────────────
{
  const [Adv, st, log, panel] = world();
  panel.advToggle('col_a','eq','תקוע');            // picked in the quick panel
  Adv.open();
  ck('what the panel picked opens in the builder as the condition it is',
     Adv.draft.rules.length===1 && Adv.draft.rules[0].rules[0].v==='תקוע', Adv.draft);
  Adv.addRule('');                                  // and a second, by hand
  Adv.setField('1','col_a'); Adv.setRuleOp('1','eq'); Adv.setV('1','v','בעבודה');
  Adv.apply();
  ck('...and what the builder applies, the panel reads back as picked',
     panel.advPickedAll('col_a').map(p=>p.v).sort().join()==='בעבודה,תקוע',
     panel.advPickedAll('col_a'));
  ck('...with the count the badge shows covering both', panel.advCount(st.filters.adv)===2);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
