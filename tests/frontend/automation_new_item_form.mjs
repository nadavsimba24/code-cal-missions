/* «צור פריט בלוח …» — the item itself is one blank, and behind it the
   target board's own fields.

   "באוטומציה אני רוצה שזה יהיה צור פריט חדש ובלחיצה עליו ייפתח לי חלון
   שבוחר את השדות שיהיה לפריט שנוצר ולא מיפוי בנפרד". The action asked about
   the new item in three blanks strung through the sentence — name, group,
   and a separate "מיפוי עמודות" read from the source side. It is said now as
   «צור [פריט] בלוח [X]», and «פריט» opens a form of the TARGET board's fields
   as the item will have them, each with what fills it beside it.

   Pinned here: the sentence and an extra action both read that way; the form
   lists the target board's columns, each offering only source fields of a
   kind that can hold it; the answers land in the SAME blanks the rule has
   always stored (target_group, text, map — the server and every older rule
   read them unchanged); a missing group or name is refused in words; the
   blank reads back what was chosen; and there is no way in before the board.

   Driven by tests/test_automation_new_item_form.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabConst(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1)+';';} }
  throw new Error('unbalanced: '+name);
}
function grabTable(decl){
  const i=src.indexOf(decl);
  if(i<0) throw new Error('not found: '+decl);
  const open=src.indexOf(decl.includes('[')?'[':'{', i), close=decl.includes('[')?']':'}';
  let d=0;
  for(let j=open;j<src.length;j++){
    if(src[j]===src[open])d++;
    else if(src[j]===close){ d--; if(!d) return src.slice(i,j+1)+';'; }
  }
  throw new Error('unbalanced: '+decl);
}


const SRC_COLS=[
  {id:'col_mk',  type:'status', title:'מכרז',       kind:'status'},
  {id:'col_num', type:'text',   title:'מספר נוהל',  kind:'text'},
  {id:'col_due', type:'date',   title:'תאריך חתימה', kind:'date'},
];
const DST_COLS=[
  {id:'col_mk2',  type:'status', title:'מכרז',            kind:'status'},
  {id:'col_full', type:'text',   title:'מספר נוהל (מלא)', kind:'text'},
  {id:'col_sup',  type:'text',   title:'ספק',             kind:'text'},
  {id:'col_mir',  type:'mirror', title:'מראה',            kind:'text'},
];
const BUILTINS=[{key:'title',label:'שם הפריט',kind:'text'},
                {key:'status',label:'סטטוס',kind:'status'}];
const GROUPS=[{id:41,name:'נחתמה ועדה'},{id:42,name:'בתכנון'}];
const RECIPE={id:'status_create_in_board_and_move',trigger:'status_changes_to',
  action:'create_in_board',then:['move_to_group'],sentence:'',
  sentence_parts:{trigger:'כאשר הסטטוס משתנה ל{t_status}',
    action:'צור פריט בשם {a_text} בקבוצה {a_target_group} בלוח {a_board} · {a_map}',
    trigger_col:'',action_col:'',trigger_col_kind:'',action_col_kind:''},
  fields:[{key:'t_status',type:'status',label:'סטטוס'},
          {key:'a_board',type:'board',label:'לוח היעד'},
          {key:'a_target_group',type:'target_group',label:'הקבוצה בלוח היעד'},
          {key:'a_text',type:'text',label:'שם הפריט החדש'},
          {key:'a_map',type:'map',label:'מיפוי עמודות (לא חובה)',optional:true}],
  status_fields:[],conditions:[]};
const ACT={key:'create_in_board',label:'צור פריט בשם … בקבוצה … בלוח …',
  text:'צור פריט בשם {text} בקבוצה {target_group} בלוח {board} · {map}',text_col:'',
  fields:[{key:'board',type:'board',label:'לוח היעד'},
          {key:'target_group',type:'target_group',label:'הקבוצה בלוח היעד'},
          {key:'text',type:'text',label:'שם הפריט החדש'},
          {key:'map',type:'map',label:'מיפוי עמודות (לא חובה)',optional:true}]};

const st={board:{id:1,name:'H2 נהלים',groups:[],my_role:'admin',col_perms:{},
                 columns:SRC_COLS.slice(),tasks:[]},boards:[]};
let modals=[], toasts=[], asked=[], els={}, picks={};
const fakeEl=(...cls)=>({classList:{_s:new Set(cls),add(c){this._s.add(c);},
  remove(c){this._s.delete(c);},contains(c){return this._s.has(c);}}});
const last=()=>modals[modals.length-1]||'';
/* The form's selects, as the page would hold them: one per data-to in the
   last dialog drawn, set to whatever `picks` says for that field. */
const selects=()=>[...last().matchAll(/data-to="([^"]+)"/g)].map(m=>({
  value:picks[m[1]]||'', getAttribute:()=>m[1]}));

function build(){
  modals=[]; toasts=[]; asked=[]; picks={};
  els={modal:fakeEl('open','modal-80'), overlay:fakeEl('open'),
       'au-item-group':{value:'',focus(){}},
       'au-item-name':{value:'',focus(){},select(){},selectionStart:null,selectionEnd:null}};
  const A=new Function('st','esc','toast','BoardLog','fdatetime','fdatetimeY','fdate',
    'avatarInner','boardStatusList','boardPriorityList','customColumns','statusColOpts',
    'advColHidden','meId','api','openCellPop','closeCellPops','askConfirm','showModal',
    'closeModals','document','renderView','localStorage','colTypeHe','advCell','setHTML',
    grabTable('const ADV_KINDS = {')+grabTable('const ADV_DATES = [')
    +grabTable('const COLUMN_TYPES=[')
    +grabConst('Automations')+' return Automations;')(
    st, x=>String(x==null?'':x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
    m=>toasts.push(m), {ago:()=>'',goto(){}},
    ()=>'', ()=>'', d=>String(d),
    ()=>'', ()=>[], ()=>[],
    ()=>SRC_COLS.slice(), ()=>[], ()=>false, ()=>1,
    async(u)=>{ asked.push(u);
                if(/automation-capabilities/.test(u)) return {columns:DST_COLS.slice()};
                if(/^\/api\/boards\/9/.test(u)) return {groups:GROUPS.slice()};
                return {}; },
    ()=>{}, ()=>{}, ()=>{},
    h=>modals.push(h), ()=>{},
    {getElementById:id=>els[id]||null,
     querySelector:sel=>(sel==='#modal .modal-x'?{setAttribute(){}}:null),
     querySelectorAll:sel=>(sel==='#modal select[data-to]'?selects():[])},
    ()=>{}, {getItem:()=>null,setItem(){}},
    t=>t, (t,f)=>null, ()=>{});
  A.conds=[]; A.maxConds=3; A.maxActs=4; A.members=[];
  A.caps={fields:[],operator_labels:{},columns:SRC_COLS.slice(),
          map:{max_pairs:20,builtins:BUILTINS},
          tokens:[{token:'item.name',label:'שם הפריט'},
                  {token:'field.',label:'ערך של עמודה',takes_column:true}]};
  A.data={can_manage:true,automations:[],people:[]};
  A.acts=[ACT]; A.recipes=[RECIPE]; A.render=()=>{};
  A.pick(RECIPE.id);
  return A;
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,340):''))); };
const sentence=A=>{ const h=A.buildHTML(); const m=h.match(/<div class="au-build">([\s\S]*?)<\/div>/); return m?m[1]:h; };

// ── the sentence ─────────────────────────────────────────────────────────
{
  const A=build();
  const s=sentence(A);
  ck('the sentence says «צור פריט בלוח», with «פריט» as one blank',
     /צור <button[^>]*pickNewItem\(-1\)[^>]*>פריט<\/button> בלוח <button[^>]*a_board/.test(s), s);
  ck('…and no longer strings the name, the group and a pairing through it',
     !/data-k="a_text"|data-k="a_target_group"|data-k="a_map"/.test(s), s);
}

// ── no way in before the board ───────────────────────────────────────────
{
  const A=build();
  await A.pickNewItem(-1);
  ck('pressing «פריט» before the board asks for the board first',
     toasts.includes('בחר תחילה את לוח היעד') && !modals.length, toasts.join(' | '));
}

// ── the form ─────────────────────────────────────────────────────────────
{
  const A=build();
  A.building.values.a_board={v:9,label:'H3 חוזים',color:''};
  await A.pickNewItem(-1);
  const f=last();
  ck('the form opens on the target board, its groups and its columns read from there',
     asked.some(u=>/^\/api\/boards\/9/.test(u)) && asked.some(u=>/board_id=9/.test(u)), asked.join(' | '));
  ck('it lists the group, the name, and each of the target board\'s columns',
     f.includes('id="au-item-group"') && f.includes('id="au-item-name"')
     && f.includes('data-to="col_full"') && f.includes('data-to="col_sup"') && f.includes('data-to="col_mk2"'), f);
  ck('…the built-in status of the target board among them',
     f.includes('data-to="status"'), f);
  ck('…and not the name a second time, nor a column the engine cannot write',
     !f.includes('data-to="title"') && !f.includes('data-to="col_mir"'), f);
  const row=(to)=>{ const i=f.indexOf('data-to="'+to+'"'); return f.slice(i,f.indexOf('</select>',i)); };
  ck('a text column is offered the text fields of this item, and nothing else',
     row('col_full').includes('value="col_num"') && row('col_full').includes('value="title"')
     && !row('col_full').includes('value="col_due"') && !row('col_full').includes('value="col_mk"'),
     row('col_full'));
  ck('a status column is offered statuses only',
     row('col_mk2').includes('value="col_mk"') && !row('col_mk2').includes('value="col_num"'), row('col_mk2'));
  ck('every field can be left empty', row('col_sup').includes('נשאר ריק'));
  ck('the groups of the target board are in the group picker',
     f.includes('נחתמה ועדה') && f.includes('בתכנון'));
  ck('the name can be built from a value of this item', f.includes('ערך מהפריט'));
}

// ── saving it: the same blanks the rule has always stored ────────────────
{
  const A=build();
  A.building.values.a_board={v:9,label:'H3 חוזים',color:''};
  await A.pickNewItem(-1);
  els['au-item-group'].value='41';
  els['au-item-name'].value='{{שם הפריט}}';
  picks={col_full:'col_num', col_mk2:'col_mk'};
  A.saveNewItem();
  const v=A.building.values;
  ck('the group lands in a_target_group', v.a_target_group&&v.a_target_group.v===41, JSON.stringify(v.a_target_group));
  ck('the name lands in a_text, stored as the code and shown by name',
     v.a_text&&v.a_text.v==='{{item.name}}'&&v.a_text.label==='{{שם הפריט}}', JSON.stringify(v.a_text));
  ck('the filled fields land in a_map as pairs from this item to the target',
     JSON.stringify((v.a_map||{}).v)===JSON.stringify([{from:'col_mk',to:'col_mk2'},{from:'col_num',to:'col_full'}])
     || JSON.stringify((v.a_map||{}).v)===JSON.stringify([{from:'col_num',to:'col_full'},{from:'col_mk',to:'col_mk2'}]),
     JSON.stringify(v.a_map));
  const s=sentence(A);
  ck('the blank reads back what was chosen',
     s.includes('פריט «{{שם הפריט}}» ב«נחתמה ועדה» · 2 שדות') && /au-blank filled[^>]*pickNewItem/.test(s), s);

  // …and reopening it shows the same answers
  await A.pickNewItem(-1);
  const f=last();
  const row=(to)=>{ const i=f.indexOf('data-to="'+to+'"'); return f.slice(i,f.indexOf('</select>',i)); };
  ck('reopened, the form shows the fields as they were filled',
     /value="col_num" selected/.test(row('col_full')) && /value="col_mk" selected/.test(row('col_mk2'))
     && /value="41" selected/.test(f), row('col_full'));

  // …and emptying every field clears the pairing rather than storing nothing
  els['au-item-group'].value='41'; els['au-item-name'].value='חוזה';
  picks={};
  A.saveNewItem();
  ck('a form with no field filled leaves no pairing behind', !A.building.values.a_map,
     JSON.stringify(A.building.values.a_map));
}

// ── refusals, in words ───────────────────────────────────────────────────
{
  const A=build();
  A.building.values.a_board={v:9,label:'H3 חוזים',color:''};
  await A.pickNewItem(-1);
  els['au-item-group'].value=''; els['au-item-name'].value='חוזה';
  A.saveNewItem();
  ck('no group is refused, and nothing is written',
     toasts.includes('יש לבחור קבוצה בלוח היעד') && !A.building.values.a_text, toasts.join(' | '));
  els['au-item-group'].value='42'; els['au-item-name'].value='';
  A.saveNewItem();
  ck('no name is refused', toasts.includes('יש להזין טקסט') && !A.building.values.a_target_group,
     toasts.join(' | '));
}

// ── as a further action ──────────────────────────────────────────────────
{
  const A=build();
  A.building.acts=[{key:'create_in_board',values:{board:{v:9,label:'H4 תיקים',color:''}}}];
  const h=A.moreActsHTML();
  ck('a further «צור פריט בלוח» reads the same way, with its own «פריט»',
     /צור <button[^>]*pickNewItem\(0\)[^>]*>פריט<\/button> בלוח/.test(h)
     && !/data-k="text"|data-k="map"/.test(h), h);
  await A.pickNewItem(0);
  els['au-item-group'].value='42'; els['au-item-name'].value='תיק';
  picks={col_full:'col_num'};
  A.saveNewItem();
  const v=A.building.acts[0].values;
  ck('its answers land in that action\'s own blanks, without the a_ prefix',
     v.target_group&&v.target_group.v===42 && v.text&&v.text.v==='תיק'
     && JSON.stringify(v.map.v)===JSON.stringify([{from:'col_num',to:'col_full'}])
     && !A.building.values.a_target_group, JSON.stringify(v));
}

// ── every action that makes an item, not only "צור פריט בלוח אחר" ───────
const LINK_ACT={key:'create_and_link',label:'',text:'צור פריט בשם {text} בלוח {board} וקשר אותו לפריט המקור בעמודה {connect} · {map}',
  text_col:'',fields:[{key:'connect',type:'connect',label:'עמודת הקישור'},{key:'board',type:'board',label:'לוח היעד'},
  {key:'text',type:'text',label:'שם הפריט החדש'},{key:'map',type:'map',label:'מיפוי',optional:true}]};
const HERE_ACT={key:'create_item',label:'',text:'צור פריט בשם {text} בקבוצה {group} · {map}',text_col:'',
  fields:[{key:'text',type:'text',label:'שם הפריט'},{key:'group',type:'group',label:'קבוצה'},
          {key:'map',type:'map',label:'מיפוי',optional:true}]};
const MAPPED_ACT={key:'create_mapped_and_link',label:'',text:'צור פריט בשם {text} בקבוצה {target_group} בלוח {board}, מפה {map} וקשר אותו לפריט המקור בעמודה {connect}',
  text_col:'',fields:[{key:'connect',type:'connect',label:'עמודת הקישור'},{key:'board',type:'board',label:'לוח היעד'},
  {key:'target_group',type:'target_group',label:'הקבוצה'},{key:'text',type:'text',label:'שם'},{key:'map',type:'map',label:'מיפוי'}]};
{
  const A=build(); A.acts=[ACT,LINK_ACT,HERE_ACT,MAPPED_ACT];
  A.building.acts=[{key:'create_and_link',values:{board:{v:9,label:'H3 חוזים',color:''}}}];
  const h=A.moreActsHTML();
  ck('"צור פריט וקשר" reads «צור [פריט] בלוח [X] וקשר…», with the link column still its own blank',
     /צור <button[^>]*pickNewItem\(0\)[^>]*>פריט<\/button> בלוח <button[^>]*data-k="board"/.test(h)
     && /data-k="connect"/.test(h) && !/data-k="text"|data-k="map"/.test(h), h);
  await A.pickNewItem(0);
  ck('…its form has no group row — the item lands in the target board\'s first group',
     !last().includes('id="au-item-group"') && last().includes('id="au-item-name"'), last());
  els['au-item-name'].value='חוזה'; picks={col_full:'col_num'};
  A.saveNewItem();
  const v=A.building.acts[0].values;
  ck('…and saving needs only the name', v.text&&v.text.v==='חוזה'&&!v.target_group
     && JSON.stringify(v.map.v)===JSON.stringify([{from:'col_num',to:'col_full'}]), JSON.stringify(v)+toasts.join('|'));
  ck('…after which the blank reads as done', /au-blank filled[^>]*pickNewItem\(0\)/.test(A.moreActsHTML()));
}
{
  const A=build(); A.acts=[ACT,LINK_ACT,HERE_ACT,MAPPED_ACT];
  st.board.groups=[{id:7,name:'קבלה'},{id:8,name:'טיפול'}];
  A.building.acts=[{key:'create_item',values:{}}];
  const h=A.moreActsHTML();
  ck('"צור פריט" on this board reads «צור [פריט]»',
     /צור <button[^>]*pickNewItem\(0\)[^>]*>פריט<\/button>/.test(h) && !/data-k="group"/.test(h), h);
  asked.length=0;
  await A.pickNewItem(0);
  ck('…with no board to choose first, its form reads THIS board\'s columns and groups',
     asked.some(u=>/automation-capabilities\?board_id=1/.test(u)) && !asked.some(u=>/^\/api\/boards\//.test(u))
     && last().includes('קבלה') && last().includes('טיפול'), asked.join(' | '));
  els['au-item-group'].value='8'; els['au-item-name'].value='המשך'; picks={};
  A.saveNewItem();
  const v=A.building.acts[0].values;
  ck('…and its group lands in the action\'s own "group" blank', v.group&&v.group.v===8&&v.text.v==='המשך'&&!v.map,
     JSON.stringify(v));
  st.board.groups=[];
}
{
  const A=build(); A.acts=[ACT,LINK_ACT,HERE_ACT,MAPPED_ACT];
  A.building.acts=[{key:'create_mapped_and_link',values:{board:{v:9,label:'H3',color:''}}}];
  await A.pickNewItem(0);
  els['au-item-group'].value='41'; els['au-item-name'].value='x'; picks={};
  A.saveNewItem();
  ck('the action whose pairing is its whole point refuses a form with no field filled',
     toasts.includes('יש לבחור לפחות שדה אחד למילוי') && !A.building.acts[0].values.text, toasts.join(' | '));
}
{
  // sub-items and duplicates are deliberately not drawn this way
  const A=build();
  ck('a sub-item and a duplicate keep their own wording',
     !A.ITEM_FORM.create_subitem && !A.ITEM_FORM.duplicate_item);
}

// ── the look: each field wears its type's icon, and a filled one is tinted ─
{
  const A=build();
  A.building.values.a_board={v:9,label:'H3 חוזים',color:''};
  A.building.values.a_map={v:[{from:'col_num',to:'col_full'}],label:'שדה אחד',color:''};
  await A.pickNewItem(-1);
  const f=last();
  const lab=(to)=>{ const i=f.indexOf('data-to="'+to+'"'); const j=f.lastIndexOf('<label',i); return f.slice(j,i); };
  ck('a status column wears the status icon, tinted green',
     lab('col_mk2').includes('fa-circle-half-stroke') && lab('col_mk2').includes('--ic:var(--green)'), lab('col_mk2'));
  ck('a text column wears the text icon', lab('col_full').includes('fa-font'), lab('col_full'));
  ck('the group and the name have icons of their own',
     f.includes('fa-layer-group') && /for="au-item-name">[^]*?fa-font/.test(f));
  ck('the icons are decoration, hidden from a screen reader — the label still names the field',
     /class="au-item-ic"[^>]*aria-hidden="true"/.test(f) && f.includes('for="au-item-f'));
  ck('the target board is named at the top', f.includes('au-item-board') && f.includes('H3 חוזים'));
  ck('a field already filled is drawn tinted; an empty one is not',
     /class="lm-sel au-item-val on" data-to="col_full"/.test(f) && /class="lm-sel au-item-val" data-to="col_sup"/.test(f));
  ck('the columns card says how many are filled', /id="au-item-count">1 \/ \d+</.test(f), f.match(/au-item-count[^<]*/));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
