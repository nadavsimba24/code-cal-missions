/* The delete action in the system-admin users table.
   Driven by tests/test_delete_user_ui.py.

   What matters here is that an irreversible action is presented as one: it is
   not offered for the account in hand, the dialog says what it takes with it
   rather than asking "are you sure?", and it names the alternative — because
   for somebody who simply left, deactivating is the right answer. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

const grabMethod = name => {
  const m = new RegExp(`\\n  ${name}\\(([^)]*)\\)\\{[\\s\\S]*?\\n  \\},`).exec(src);
  if(!m) throw new Error('not found: '+name);
  return m[0];
};

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

// ── the menu entry ──
let popped='';
const menu=grabMethod('rowMenu');
const runMenu=(uid,me)=>{
  popped='';
  new Function('openCellPop','esc','meId','ROLE_HE','st','closeCellPops','SysAdmin',
    'const o={users:[{id:9,name:"בוריס",email:"b@x.test",role:"member"}],'+menu.trim().replace(/,$/,'')+'}; o.rowMenu({stopPropagation(){},currentTarget:{}},'+uid+');')
    ((_a,html)=>{popped=html;}, x=>String(x==null?'':x), ()=>me,
     {admin:'מנהל',manager:'מנהל ביניים',member:'חבר',viewer:'צופה',guest:'אורח'},
     {depts:[]}, ()=>{}, {});
};
runMenu(9, 1);
ck('a user row offers a permanent delete', popped.includes('מחק משתמש לצמיתות'), popped);
ck('...wired to the handler', popped.includes('SysAdmin.deleteUser(9)'), popped);
ck('...marked as the destructive one', /sa-del/.test(popped), popped);
ck('...and separated from the everyday actions', popped.includes('sa-menu-sep'), popped);
ck('the ordinary actions are still there', popped.includes('ערוך פרופיל')&&popped.includes('תפקיד'));

runMenu(9, 9);
ck('it is NOT offered for the account in hand', !popped.includes('deleteUser'), popped);
ck('...while everything else still is', popped.includes('ערוך פרופיל'), popped);

// ── the dialog, and the call ──
let asked=null, called=null, toasted='', reopened=false;
const del=grabMethod('deleteUser');
const obj=new Function('askConfirm','api','toast','closeCellPops','withMe',
  'return {users:[{id:9,name:"בוריס",email:"b@x.test"}], open(){this._re=true;}, '+del.trim().replace(/,$/,'')+'};')(
  (msg,onYes,opts)=>{ asked={msg,opts,onYes}; },
  async(url,o)=>{ called={url,method:o.method}; return {affected:{"comments.user_id":{deleted:3},"tasks.created_by":{cleared:2}}}; },
  m=>{toasted=m;}, ()=>{}, b=>JSON.stringify(b));
obj.deleteUser(9);
ck('it asks before doing anything', !!asked && called===null);
ck('the question names the person', asked.msg.includes('בוריס'), asked.msg);
ck('the dialog says it cannot be undone', (asked.opts.note||'').includes('אינה הפיכה'), asked.opts.note);
ck('...lists what is erased, the messages and the log among it',
   /התגובות שכתב/.test(asked.opts.noteHTML) && /רשומות היומן/.test(asked.opts.noteHTML), asked.opts.noteHTML);
ck('...says what survives, so the work is not feared lost',
   /נשמרים/.test(asked.opts.noteHTML), asked.opts.noteHTML);
ck('...and offers deactivating instead, for somebody who merely left',
   /להשבית/.test(asked.opts.noteHTML), asked.opts.noteHTML);
ck('the button is not a bland "OK"', asked.opts.confirmText==='מחק לצמיתות', asked.opts.confirmText);

await asked.onYes();
ck('confirming calls DELETE on the user', called && called.method==='DELETE' && called.url==='/api/users/9',
   JSON.stringify(called));
ck('the toast reports how much was touched, not just "done"',
   toasted.includes('בוריס') && /5 רשומות/.test(toasted), toasted);
ck('...and the table is reloaded afterwards', obj._re===true);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
