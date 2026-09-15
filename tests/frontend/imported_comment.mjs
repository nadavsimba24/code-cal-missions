/* An imported message in the conversation: it carries the name of whoever wrote
   it where it came from, says so, and offers no profile that does not exist.
   Driven by tests/test_import_conversation_ui.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabMethod(obj, name){
  const m = new RegExp(`^const ${obj} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: '+obj);
  let i=src.indexOf('{',m.index), d=0, end=-1;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d){end=j;break;}} }
  const body=src.slice(i,end);
  const k=new RegExp(`\\n  ${name}\\(([^)]*)\\)\\s*\\{`).exec(body);
  if(!k) throw new Error('not found: '+obj+'.'+name);
  let a=body.indexOf('{',k.index+k[0].length-1), dd=0;
  for(let j=a;j<body.length;j++){ if(body[j]==='{')dd++; else if(body[j]==='}'){dd--; if(!dd)
    return {args:k[1], code:body.slice(a,j+1)};} }
  throw new Error('unbalanced: '+name);
}

const {args, code} = grabMethod('Chat','commentHTML');
const stub={commentHTML:(c,r)=>fn.call(stub,c,r),composerHTML:()=>'',renderContent:t=>String(t),
            attPreview:()=>'',seenPop(){},seenPopClose(){},editing:null};
const fn = new Function('esc','avatarInner','fdatetimeY','ROLE_HE','canComment','Chat','st','meId',
  `return function(${args})${code}`)(
  x=>String(x==null?'':x), ()=>'AV', ()=>'01/01/2026', {}, ()=>false,
  stub, {board:{},me:{role:'admin'}}, ()=>1);

let pass=0,fail=0; const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

const mine={id:1,user_id:4,user_name:'יואב לוי',content:'הודעה רגילה',created_at:'2026-01-01T09:00:00'};
const imported={id:2,user_id:null,user_name:'מישהי מהעירייה',content:'הודעה מיובאת',
                created_at:'2026-01-01T09:00:00',origin:{source:'monday',author:'מישהי מהעירייה',matched:false}};
const importedFile={...imported,id:3,origin:{source:'xlsx',author:'רינה',matched:false}};
const matched={id:4,user_id:4,user_name:'יואב לוי',content:'יובאה אך מזוהה',
               created_at:'2026-01-01T09:00:00',origin:{source:'monday',author:'יואב לוי',matched:true}};

const R=x=>fn.call(stub,x,false);
const a=R(mine), b=R(imported), c=R(importedFile), d=R(matched);
ck('an ordinary message is unchanged', !a.includes('מיובאת') && a.includes('Profile.open(4)'), a);
ck('an imported message names the person who actually wrote it',
   b.includes('מישהי מהעירייה'), b);
ck('...and is marked as imported', b.includes('מיובאת'), b);
ck('...saying which import it came from', b.includes('יובאה ממאנדיי'), b);
ck('a message imported from a file says that instead', c.includes('יובאה מקובץ'), c);
ck('an author with no account offers no profile to open',
   !b.includes('Profile.open'), b);
ck('...and never offers Profile.open(null)', !b.includes('Profile.open(null)'));
ck('a message whose author WAS matched behaves like any other',
   d.includes('Profile.open(4)') && !d.includes('מיובאת'), d);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
