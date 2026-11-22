/* A page's connect-column display text, folded into the board's own map.

   A connect column can be told to show a FIELD of the linked record instead
   of its name, and the override map that says so — {col_id:{item_id:text}} —
   used to arrive with the board. Past the threshold the board arrives with no
   rows and therefore with an empty map, so each page now brings the overrides
   for its own rows and the browser merges them.

   Merging is the whole of it, and there is exactly one way to get it wrong
   that nobody would see: assigning the arriving map over st.board.link_display
   instead of folding it in. Page two's inner map is keyed by page two's item
   ids and knows nothing about page one's, so an assignment wipes the text for
   every row already on screen — and the cells it wipes do not break, they
   quietly go back to showing titles. So what is pinned here is that rows from
   an earlier page survive a later one, per column, with a second column beside
   the first.

   And the last two checks are about WHERE it is called from: only Paged.load,
   which is the only caller that asks for rows. Views.ask and advAskServer ask
   the same endpoint for ids (ids_only), and those answers carry no map at all
   — wiring the merge to one of them would be a call that always merges
   undefined, which is silent in exactly the same way.

   Driven by tests/test_a_page_carries_the_words_its_chips_show.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function slice(from){
  let i=src.indexOf('{',from), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d)return j+1;} }
  throw new Error('unbalanced');
}
function grabConst(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return src.slice(m.index, slice(m.index));
}
/* A method of an object literal, by name — `  ask(){` / `  mergeLinkDisplay(map){`.
   Used to read a function that is NOT being run, where what matters is what it
   does not contain. */
function grabMethod(objName, method){
  const obj = grabConst(objName);
  const m = new RegExp(`\\n  (?:async )?${method}\\(`).exec(obj);
  if(!m) throw new Error(`not found: ${objName}.${method}`);
  let i = obj.indexOf('{', m.index + m[0].length - 1), d = 0;
  for(let j=i;j<obj.length;j++){ if(obj[j]==='{')d++; else if(obj[j]==='}'){d--; if(!d)return obj.slice(m.index, j+1);} }
  throw new Error('unbalanced method '+method);
}
function grabFn(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  return src.slice(m.index, slice(m.index));
}

let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

/* The real Paged, with a board under it. Nothing else of the app is needed:
   mergeLinkDisplay reads st.board and writes st.board.link_display. */
function paged(board){
  const st={board:board, filters:{}};
  const env={st, api:async()=>({}), advQuery:()=>({}), withMe:o=>JSON.stringify(o||{}),
             renderView:()=>{}, refreshToolbar:()=>{}, toast:()=>{},
             document:{getElementById:()=>null}, filterMode:()=>'server'};
  const names=Object.keys(env);
  const {Paged}=new Function(...names, `
    let _pagedTimer=null;
    ${grabConst('Paged')};
    return {Paged};`)(...names.map(k=>env[k]));
  return {Paged, st};
}

// ── two pages, different rows, one column ─────────────────────────────────
{
  const {Paged, st} = paged({id:7, link_display:{}});
  Paged.mergeLinkDisplay({col_link:{'11':'חיפה · מועצה', '12':'עכו · עירייה'}});
  Paged.mergeLinkDisplay({col_link:{'13':'נהריה · עירייה'}});
  const m = st.board.link_display.col_link;
  ck('a row from the first page survives the second',
     m['11']==='חיפה · מועצה' && m['12']==='עכו · עירייה',
     JSON.stringify(st.board.link_display));
  ck('...and the second page is there too', m['13']==='נהריה · עירייה',
     JSON.stringify(st.board.link_display));
  ck('...and nothing else crept in', Object.keys(m).length===3, Object.keys(m).join());

  // the same record seen again on a later page is simply written again
  Paged.mergeLinkDisplay({col_link:{'11':'חיפה · מועצה'}});
  ck('a record both pages know is not duplicated or lost',
     Object.keys(m).length===3 && m['11']==='חיפה · מועצה');
}

// ── a second column coexists with the first ───────────────────────────────
{
  const {Paged, st} = paged({id:7, link_display:{}});
  Paged.mergeLinkDisplay({col_a:{'11':'א'}});
  Paged.mergeLinkDisplay({col_b:{'21':'ב'}});
  Paged.mergeLinkDisplay({col_a:{'12':'אא'}});
  const d = st.board.link_display;
  ck('two connect columns on one board keep their own maps',
     d.col_a && d.col_b && d.col_a['11']==='א' && d.col_a['12']==='אא' && d.col_b['21']==='ב',
     JSON.stringify(d));
  ck('...and merging one does not touch the other',
     Object.keys(d.col_b).length===1, JSON.stringify(d.col_b));
}

// ── before the first page there may be no map at all ──────────────────────
for(const [what, board] of [['undefined', {id:7}],
                            ['an empty object', {id:7, link_display:{}}],
                            ['a non-object', {id:7, link_display:null}]]){
  const {Paged, st} = paged(board);
  Paged.mergeLinkDisplay({col_link:{'11':'חיפה · מועצה'}});
  ck(`a board whose link_display is ${what} still ends up holding the page's text`,
     st.board.link_display && st.board.link_display.col_link
       && st.board.link_display.col_link['11']==='חיפה · מועצה',
     JSON.stringify(st.board.link_display));
}

// ── an answer with nothing in it changes nothing ──────────────────────────
{
  const {Paged, st} = paged({id:7, link_display:{col_link:{'11':'חיפה · מועצה'}}});
  for(const bad of [undefined, null, {}, 'nope', 42, {col_link:null}, {col_link:'x'}]){
    Paged.mergeLinkDisplay(bad);
  }
  ck('an older server, or a page with nothing to override, leaves the map alone',
     JSON.stringify(st.board.link_display)==='{"col_link":{"11":"חיפה · מועצה"}}',
     JSON.stringify(st.board.link_display));
}

// ── and with no board on screen there is nothing to merge into ────────────
{
  const {Paged, st} = paged(null);
  let threw=false;
  try{ Paged.mergeLinkDisplay({col_link:{'11':'x'}}); }catch(e){ threw=true; }
  ck('a page that lands after the board was closed does not throw',
     !threw && st.board===null);
}

// ── where it is called from ───────────────────────────────────────────────
{
  const load = grabMethod('Paged','load');
  ck('Paged.load folds each page in as it arrives',
     /this\.mergeLinkDisplay\(r\.link_display\)/.test(load),
     "nothing in Paged.load folds the page's words into the board — every connect "
     +"column told to show a field is back to showing titles");
  // …and it is merged BEFORE the board is drawn with those rows, or the first
  // render of the page prints titles and nothing re-renders to correct it
  ck('...before the rows it describes are drawn',
     load.indexOf('mergeLinkDisplay') < load.indexOf('renderView()'),
     'the page is rendered before its words are known');

  for(const [owner, body] of [['Views.ask', grabMethod('Views','ask')],
                              ['advAskServer', grabFn('advAskServer')]]){
    ck(`${owner} asks for ids, so it does not merge a map it was never sent`,
       !/mergeLinkDisplay/.test(body),
       owner+" merges a map that answer never carries — the call is on the wrong caller");
  }
  // the reason those two are exempt, said in the source rather than assumed
  ck('...because the ids answer is the other shape of the same endpoint',
     /ids_only/.test(grabFn('advQuery')), 'advQuery stopped asking for ids');
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
