/* A list column's inactive options, and a rename, as the cell popover sees them.

   "Inactive" means kept on the items that already carry the word and not
   offered to anyone choosing a new one. So the list hides it — except in the
   one cell that already holds it, where it is shown greyed so it can still be
   taken off. Hiding a button must not renumber the others: toggleDropdown
   finds the word by its index in col.options, and a list that skipped one
   option and counted from screen position would tick the wrong word.

   A rename is carried into every cell by the server, but the rows already on
   screen were fetched before it — on a paged board, fifty out of thousands —
   so ddAdoptRename brings them into line locally, sub-items included, without
   leaving a cell holding the same word twice.

   The list is shown sorted — letters in alphabetical order, numbers as
   numbers — while the column keeps its saved order, so the index each
   button carries is still the option's place in col.options.

   Driven by tests/test_dropdown_inactive_and_renamed_options.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d)return src.slice(m.index,j+1);} }
  throw new Error('unbalanced '+name);
}
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function world(cellVals){
  const W={cols:[{id:'c_k',type:'dropdown',title:'קבלן',
            options:['אלפא','בטא','גמא'], inactive_options:['בטא','לא-קיים']}],
           task:{id:7,custom_fields:{c_k:cellVals}}, writes:[], rows:[]};
  const fns=['dropdownMatch','dropdownSortedIdx','dropdownOpts','dropdownInactive','dropdownListHTML','toggleDropdown','ddAdoptRename'];
  W.f=new Function('customColumns','findAnyTask','isBoardAdmin','esc','setCell','loadedRows','buildDropdownPop','dropdownDisp',
    'const _ddPending={};\n'+fns.map(grab).join('\n')+'\nreturn {'+fns.join(',')+'};')(
    ()=>W.cols, ()=>W.task, ()=>true, esc,
    (tid,cid,v)=>{ W.writes.push(v); W.task.custom_fields[cid]=v; },
    ()=>W.rows, ()=>{}, ()=>'');
  W.toggle=i=>W.f.toggleDropdown({stopPropagation(){},target:{closest:()=>null}},7,'c_k',i);
  return W;
}
const idxOf=(html,word)=>{ const m=new RegExp(`toggleDropdown\\(event,7,'c_k',(\\d+)\\)">${word}`).exec(html); return m?+m[1]:null; };

{ const W=world(['אלפא']);
  ck('a word in inactive_options that is no longer an option is ignored',
     JSON.stringify(W.f.dropdownInactive('c_k'))===JSON.stringify(['בטא']));
  const h=W.f.dropdownListHTML(7,'c_k');
  ck('an inactive option is not offered to a cell that does not hold it', !h.includes('בטא'), h);
  ck('the options after it keep their own index, not their place on screen',
     idxOf(h,'אלפא')===0 && idxOf(h,'גמא')===2, h);
}
{ const W=world(['בטא']);
  const h=W.f.dropdownListHTML(7,'c_k');
  ck('a cell holding an inactive option still shows it, marked as not active',
     idxOf(h,'בטא')===1 && /dd-inactive/.test(h) && h.includes('לא פעיל'), h);
  W.toggle(1);
  ck('…and it can be taken off', W.writes.length===1 && W.writes[0]===null);
  W.toggle(1);
  ck('but it cannot be put back on', W.writes.length===1, JSON.stringify(W.writes));
  W.toggle(2);
  ck('an active option is still picked as before', JSON.stringify(W.task.custom_fields.c_k)===JSON.stringify(['גמא']));
}
{ const W=world([]);
  W.cols[0].inactive_options=['אלפא','בטא','גמא'];
  ck('when every option is inactive the list says so instead of standing empty',
     W.f.dropdownListHTML(7,'c_k').includes('כל האפשרויות במצב לא פעיל'));
}
{ const W=world([]);
  W.rows=[{id:1,custom_fields:{c_k:['אלפא','גמא'],other:['אלפא']},
           subtasks:[{id:2,custom_fields:{c_k:['אלפא','בטא2']}}]},
          {id:3,custom_fields:{c_k:['אלפא','בטא2']}},
          {id:4,custom_fields:{}}];
  W.f.ddAdoptRename('c_k','אלפא','בטא2');
  ck('a renamed word follows into the rows on screen',
     JSON.stringify(W.rows[0].custom_fields.c_k)===JSON.stringify(['בטא2','גמא']));
  ck('another column of the same item is left alone',
     JSON.stringify(W.rows[0].custom_fields.other)===JSON.stringify(['אלפא']));
  ck('sub-items on screen follow it too, without the word appearing twice',
     JSON.stringify(W.rows[0].subtasks[0].custom_fields.c_k)===JSON.stringify(['בטא2']));
  ck('a row with no value in the column is untouched', !('c_k' in W.rows[2].custom_fields));
}
{ // shown in running order: letters alphabetically, numbers as numbers
  const W=world([]);
  W.cols[0].options=['מבנה 10','zeta','מבנה 2','Alpha','אבן','בטון']; W.cols[0].inactive_options=[];
  const h=W.f.dropdownListHTML(7,'c_k');
  const shown=[...h.matchAll(/'c_k',(\d+)\)">([^<]+?)(?: <|<\/button>)/g)].map(m=>[+m[1],m[2]]);
    // Hebrew collation puts Hebrew words first, then Latin, as the board list does
  ck('the list is sorted alphabetically, Hebrew then Latin, with "2" before "10"',
     JSON.stringify(shown.map(x=>x[1]))===JSON.stringify(['אבן','בטון','מבנה 2','מבנה 10','Alpha','zeta']),
     JSON.stringify(shown.map(x=>x[1])));
  ck('each button still carries the option\'s index in the saved list',
     shown.every(([i,w])=>W.cols[0].options[i]===w));
  ck('the column itself keeps the order it was saved in',
     W.cols[0].options[0]==='מבנה 10');
}
{ // the search field narrows the list to what was typed
  const W=world([]);
  W.cols[0].options=['א. שמש חברה שמירה ואבטחה','א.א.ארזי שמירה בע"מ','Dynamics Ltd','בטון']; W.cols[0].inactive_options=[];
  const words=h=>[...h.matchAll(/'c_k',(\d+)\)">([^<]+?)(?: <|<\/button>)/g)].map(m=>W.cols[0].options[+m[1]]);
  ck('a word anywhere in the option finds it, not only at its start',
     JSON.stringify(words(W.f.dropdownListHTML(7,'c_k','שמירה')).sort())===JSON.stringify(['א. שמש חברה שמירה ואבטחה','א.א.ארזי שמירה בע"מ'].sort()),
     W.f.dropdownListHTML(7,'c_k','שמירה'));
  ck('case and surrounding spaces do not matter',
     JSON.stringify(words(W.f.dropdownListHTML(7,'c_k','  dynamics ')))===JSON.stringify(['Dynamics Ltd']));
  ck('an empty search shows everything', words(W.f.dropdownListHTML(7,'c_k','')).length===4);
  ck('a search that finds nothing says so',
     W.f.dropdownListHTML(7,'c_k','zzz').includes('לא נמצאו אפשרויות תואמות'));
  ck('a found option still carries its own index',
     /'c_k',3\)">בטון/.test(W.f.dropdownListHTML(7,'c_k','בט')));
}
{ // a cell shows three words at most, and counts the rest
  const m=/^const DROPDOWN_CELL_MAX=(\d+);/m.exec(src);
  const disp=new Function('esc','const DROPDOWN_CELL_MAX='+(m?m[1]:'NaN')+';\n'+grab('dropdownDisp')+'\nreturn dropdownDisp;')(esc);
  const tags=h=>(h.match(/class="tag"/g)||[]).length;
  ck('three words are all shown, with no count', tags(disp(['א','ב','ג']))===3 && !disp(['א','ב','ג']).includes('tag-more'));
  const h=disp(['תשתיות','בניה','קיימות','חינוך','<b>x</b>','אנרגיה','ביטחון']);
  ck('seven words show the first three and "+4"', tags(h)===3 && />\+4<\/span>/.test(h), h);
  ck('the words behind the count are named in its tooltip, escaped',
     h.includes('title="חינוך, &lt;b&gt;x&lt;/b&gt;, אנרגיה, ביטחון"'), h);
  ck('four words already collapse to three and "+1"', tags(disp(['1','2','3','4']))===3 && disp(['1','2','3','4']).includes('>+1<'));
  ck('an empty cell still shows a dash', disp([]).includes('—') && disp(null).includes('—'));
}
ck('the form builder does not offer an inactive option',
   /col\.type==='dropdown'[^\n]*inactive/.test(src));
ck('a duplicated column keeps which of its options are inactive',
   /inactive_options:c\.inactive_options/.test(grab('duplicateColumn')));
ck('a refusal to delete a used option is shown, not swallowed',
   /e\.detail\.options/.test(grab('saveColumns')));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
