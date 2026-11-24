/* The "משתתפים" button in the board header, and the dialog behind it.

   Two things are pinned here, both of them about what a browser DRAWS — the
   server is asked again on every write, and tests/test_the_board_header_counts
   _its_participants.py pins that half.

     1. The header button says how many people are on the board, and everybody
        gets it. The chip it replaced named the board's admins and nothing else.
     2. The dialog is read-only for anyone the server did not call a manager:
        no role picker, no remove button, no invitation — and it says why,
        rather than quietly losing its controls.
     3. The invitation picker is a list of names in the order a list of names
        is read in — א׳–ת׳ — with a search line above it, because the server
        answers in account-creation order and an environment with eighty
        colleagues turned "invite דנה" into a scroll.

   Runs the real membersChipHTML and the real Members object out of index.html.
   Driven by tests/test_the_board_header_counts_its_participants.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function braces(from){
  let i=src.indexOf('{',from), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return j+1;} }
  throw new Error('unbalanced');
}
function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: function '+name);
  return src.slice(m.index, braces(m.index));
}
function grabObj(name){
  const m = new RegExp(`^const ${name} = \\{`,'m').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return src.slice(m.index, braces(m.index));
}

let pass=0,fail=0;
const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
                                 .replace(/>/g,'&gt;').replace(/"/g,'&quot;');

/* ── 1. the header button ───────────────────────────────────────────── */
const st={board:{id:1,name:'לוח הבדיקה',my_role:'viewer',notifications_enabled:true,
                 members:[{id:1,name:'משה'},{id:2,name:'דנה'},{id:3,name:'עידו'}]}};
const chip=new Function('st','esc','boardMemberCount',
  grab('membersChipHTML')+'; return membersChipHTML;')(
  st, esc, new Function('st', grab('boardMemberCount')+'; return boardMemberCount;')(st));

const chipHTML=chip();
ck('the header draws a button, not a label', /<button[^>]*class="bh-members"/.test(chipHTML), chipHTML);
ck('...labelled משתתפים', /משתתפים/.test(chipHTML));
ck('...carrying the count of the board\'s people', /class="bh-mem-n">3</.test(chipHTML), chipHTML);
ck('...which opens the members dialog', /onclick="Members\.open\(\)"/.test(chipHTML));
ck('...and names itself to a screen reader', /aria-label="משתתפי הלוח — 3"/.test(chipHTML), chipHTML);
ck('a viewer gets the same button as an admin — my_role is not consulted',
   !/my_role/.test(grab('membersChipHTML')));

/* ── 2. the dialog, in both modes ───────────────────────────────────── */
const MEMBERS=[{user_id:1,name:'משה',email:'m@x.test',role:'admin'},
               {user_id:2,name:'דנה',email:'d@x.test',role:'editor'},
               {user_id:3,name:'עידו',email:'i@x.test',role:'viewer',is_active:false}];

async function dialog(can_manage){
  let shown='';
  const api=async()=>({members:MEMBERS,
                       available:can_manage?[{id:9,name:'אורח'}]:[],
                       can_manage});
  const M=new Function('st','esc','api','showModal','meId','avatarInner','BROLE_HE','BROLE_WHAT',
                       'document','renderBoardHead',
    grabObj('Members')+'; return Members;')(
    st, esc, api, h=>{shown=h;}, ()=>2, m=>esc(m.name),
    {admin:'ניהול',editor:'עריכה',viewer:'צפייה בלבד'},
    {admin:'מנהל לוח — תוכן, הרשאות והזמנת משתתפים',
     editor:'עריכה — הוספה ועריכה של פריטים',
     viewer:'צפייה בלבד — ללא עריכה'},
    {getElementById:()=>null}, ()=>{});
  await M.open();
  return shown;
}

const manage=await dialog(true), ro=await dialog(false);

for(const [who,html] of [['a manager',manage],['a viewer',ro]]){
  ck(`${who} sees every participant`, MEMBERS.every(m=>html.includes(m.name)), html.slice(0,200));
  ck(`${who} sees what each role permits`,
     html.includes('עריכה — הוספה ועריכה של פריטים')
     && html.includes('צפייה בלבד — ללא עריכה'));
  ck(`${who} sees a deactivated member flagged`, /לא פעיל/.test(html));
  /* The dialog carries no close button and no footer of its own. showModal
     puts a × in the corner of every modal, Escape closes it and so does the
     backdrop, so a footer holding one "סגור" and nothing else was a band of
     height repeating what was already on screen — directly above the
     invitation, which is the one control people open this dialog to reach. */
  ck(`${who} is given no close button of its own`,
     !/closeModals\(\)/.test(html) && !/class="mfoot"/.test(html), html.slice(-300));
}

ck('a manager gets a role picker per member',
   (manage.match(/Members\.setRole\(/g)||[]).length===MEMBERS.length,
   String((manage.match(/Members\.setRole\(/g)||[]).length));
ck('a manager gets a remove button per member',
   (manage.match(/Members\.remove\(/g)||[]).length===MEMBERS.length);
ck('a manager gets a הזמנת משתתפים button',
   /id="mem-invite-btn"[^>]*>[^<]*<i[^>]*><\/i> הזמנת משתתפים/.test(manage), manage);
ck('...folded away until pressed', /id="mem-invite"[^>]*hidden/.test(manage), manage);
ck('...and it offers who may still be invited', /value="9"/.test(manage));
/* Deleting a board is deliberately NOT offered here, for either role. This
   dialog is about who may use the board, and the most destructive action in
   the product has no business at the bottom of a screen people open to change
   somebody's role — one slip on the way out. It is still reachable where it
   reads as a decision about the board: the header menu and the sidebar's own
   context menu, both of which have their own tests. */
ck('nobody is offered the board\'s deletion from here',
   !/Members\.deleteBoard\(\)/.test(manage) && !/מחק לוח/.test(manage), manage);
ck('a manager can still switch the board\'s notifications', /Members\.toggleNotif\(/.test(manage));

ck('a viewer gets no role picker', !/Members\.setRole\(/.test(ro));
ck('a viewer gets no remove button', !/Members\.remove\(/.test(ro));
/* The phrase itself is not the test: "הזמנת משתתפים" is also in the sentence
   that says what a board admin may do, which every reader of this dialog sees
   under the admin's name. What a viewer must not get is the control. */
ck('a viewer gets no invitation at all',
   !/mem-invite-btn/.test(ro) && !/Members\.add\(\)/.test(ro) && !/mem-user/.test(ro));
ck('a viewer cannot switch the board\'s notifications', !/Members\.toggleNotif\(/.test(ro));
ck('a viewer is told it is read-only', /תצוגה בלבד/.test(ro));
ck('a viewer still reads the role as text, not as a dead control',
   /class="mem-role-ro"/.test(ro) && !/<select/.test(ro), ro);

/* A request that did not land must fall back to the read-only half: drawing
   the controls off a missing answer is how a viewer gets an invite box that
   403s on every press. */
let shownFail='';
const MFail=new Function('st','esc','api','showModal','meId','avatarInner','BROLE_HE','BROLE_WHAT',
                         'document','renderBoardHead',
  grabObj('Members')+'; return Members;')(
  st, esc, async()=>{throw new Error('network');}, h=>{shownFail=h;}, ()=>2, m=>esc(m.name),
  {admin:'ניהול',editor:'עריכה',viewer:'צפייה בלבד'}, {}, {getElementById:()=>null}, ()=>{});
await MFail.open();
ck('a failed fetch still opens the dialog', /משתתפי הלוח/.test(shownFail), shownFail.slice(0,160));
ck('...read-only, because nothing said otherwise',
   !/mem-invite-btn/.test(shownFail) && !/Members\.setRole\(/.test(shownFail));

/* ── 3. the invitation: sorted, and searchable ──────────────────────── */
/* Deliberately handed to the dialog in the order that reads worst: ת before
   א, and two names sharing a prefix, so a test that passed on an accident of
   the input could not pass here. */
const AVAIL=[{id:4,name:'תמר לוי'},{id:7,name:'דנה כהן'},{id:9,name:'אורי שגב'},
             {id:5,name:'דני ברק'},{id:8,name:'משה פרץ'}];

/* The real document the dialog writes into, small enough to be read back:
   only the three elements the search touches exist, and each one keeps what
   was written to it. */
function docStub(){
  const els={'mem-user':{innerHTML:''},'mem-add-btn':{disabled:false},'mem-user-q':{value:''},
             'mem-invite':{_h:true,hasAttribute:function(){return this._h;},
                           removeAttribute:function(){this._h=false;},
                           setAttribute:function(){this._h=true;}}};
  els['mem-invite-btn']={setAttribute:()=>{}};
  els['mem-user'].focus=()=>{}; els['mem-user-q'].focus=function(){this.focused=true;};
  els['mem-list']={innerHTML:''};
  return {els, getElementById(id){ return this.els[id]||null; }};
}

const dstub=docStub();
let inviteHTML='';
const MI=new Function('st','esc','api','showModal','meId','avatarInner','BROLE_HE','BROLE_WHAT',
                      'document','renderBoardHead',
  grabObj('Members')+'; return Members;')(
  st, esc, async()=>({members:MEMBERS,available:AVAIL,can_manage:true}),
  h=>{inviteHTML=h;}, ()=>2, m=>esc(m.name),
  {admin:'ניהול',editor:'עריכה',viewer:'צפייה בלבד'}, {}, dstub, ()=>{});
await MI.open();

const optOrder=h=>(h.match(/<option value="\d+">([^<]*)<\/option>/g)||[])
  .map(o=>o.replace(/<option value="\d+">|<\/option>/g,''));
const order=optOrder(inviteHTML);
ck('the invitation lists everybody who may still be invited', order.length===AVAIL.length,
   JSON.stringify(order));
ck('...in א׳–ת׳ order, not in the order the server sent them',
   JSON.stringify(order)===JSON.stringify(AVAIL.map(u=>u.name)
     .sort((a,b)=>a.localeCompare(b,'he'))), JSON.stringify(order));
ck('...with a search line above the picker',
   /id="mem-user-q"[^>]*oninput="Members\.searchAvail\(this\.value\)"/.test(inviteHTML),
   inviteHTML.slice(inviteHTML.indexOf('mem-invite')));
ck('...which a screen reader can name and tie to the picker it narrows',
   /id="mem-user-q"[^>]*aria-label="חיפוש משתתף לפי שם"/.test(inviteHTML)
   && /id="mem-user-q"[^>]*aria-controls="mem-user"/.test(inviteHTML));
ck('...and Enter in it sends the invitation rather than reloading the page',
   /id="mem-user-q"[^>]*onkeydown="[^"]*preventDefault\(\);Members\.add\(\);/.test(inviteHTML),
   inviteHTML.slice(inviteHTML.indexOf('mem-user-q')));

MI.searchAvail('דנ');
ck('typing narrows the picker to the names that match',
   JSON.stringify(optOrder(dstub.els['mem-user'].innerHTML))===JSON.stringify(
     ['דני ברק','דנה כהן'].sort((a,b)=>a.localeCompare(b,'he'))),
   dstub.els['mem-user'].innerHTML);
ck('...and the matches stay in א׳–ת׳ order too',
   optOrder(dstub.els['mem-user'].innerHTML).join()===
   ['דנה כהן','דני ברק'].join());
ck('...the invite button stays live while something matches',
   dstub.els['mem-add-btn'].disabled===false);

/* The filtering rebuilds the options rather than hiding them, because a
   hidden <option> is still reachable with the arrow keys — and an invitation
   would go to a name that is not on screen. */
MI.searchAvail('דנ');
ck('...and the narrowing is a rebuild, not a display:none',
   !/display:\s*none/.test(dstub.els['mem-user'].innerHTML)
   && (dstub.els['mem-user'].innerHTML.match(/<option/g)||[]).length===2,
   dstub.els['mem-user'].innerHTML);

MI.searchAvail('זזזז');
ck('a search that matches nobody says so, and does not offer a dead name',
   /אין שם שמתאים לחיפוש/.test(dstub.els['mem-user'].innerHTML)
   && !/value="[1-9]/.test(dstub.els['mem-user'].innerHTML),
   dstub.els['mem-user'].innerHTML);
ck('...and the invite button goes dead with it',
   dstub.els['mem-add-btn'].disabled===true);

/* The two empty states are not the same sentence: nobody left to invite is a
   fact about the environment, no match is a fact about what was typed. */
let emptyHTML='';
const ME=new Function('st','esc','api','showModal','meId','avatarInner','BROLE_HE','BROLE_WHAT',
                      'document','renderBoardHead',
  grabObj('Members')+'; return Members;')(
  st, esc, async()=>({members:MEMBERS,available:[],can_manage:true}),
  h=>{emptyHTML=h;}, ()=>2, m=>esc(m.name),
  {admin:'ניהול',editor:'עריכה',viewer:'צפייה בלבד'}, {}, docStub(), ()=>{});
await ME.open();
ck('an environment with nobody left to invite says that instead',
   /אין חברי סביבה שאפשר להוסיף/.test(emptyHTML)
   && !/אין שם שמתאים לחיפוש/.test(emptyHTML), emptyHTML.slice(emptyHTML.indexOf('mem-invite')));

/* Opening the dialog again must not come up still filtered by what was typed
   into it the last time — the query lives for one opening. */
await MI.open();
ck('a reopened dialog offers everybody again', optOrder(inviteHTML).length===AVAIL.length,
   JSON.stringify(optOrder(inviteHTML)));

/* And pressing the search line is what the invitation opens on: the way to
   reach a name among eighty is to type it. */
const d2=docStub();
const MT=new Function('st','esc','api','showModal','meId','avatarInner','BROLE_HE','BROLE_WHAT',
                      'document','renderBoardHead',
  grabObj('Members')+'; return Members;')(
  st, esc, async()=>({members:MEMBERS,available:AVAIL,can_manage:true}),
  ()=>{}, ()=>2, m=>esc(m.name),
  {admin:'ניהול',editor:'עריכה',viewer:'צפייה בלבד'}, {}, d2, ()=>{});
await MT.open();
MT.toggleInvite();
ck('unfolding the invitation puts the caret in the search line, not the picker',
   d2.els['mem-user-q'].focused===true);

/* ── the dialog opens on the click, not when the answer lands ─────────────
   It used to wait for /members before drawing anything, and on production
   that request took seconds — the button looked dead. Now the frame (and a
   spinner) is up at once; the list fills in when the answer arrives. And an
   answer that arrives after the dialog was closed draws nothing: it must not
   reopen a dialog she has already left. */
{
  const shows=[]; let release;
  const pending=new Promise(r=>{ release=r; });
  const modal={open:true, classList:{contains:c=>c==='open'&&modal.open}};
  const doc={getElementById:id=>id==='modal'?modal
             :id==='mem-loading'?(shows.length===1?{}:null):null};
  const MW=new Function('st','esc','api','showModal','meId','avatarInner','BROLE_HE','BROLE_WHAT',
                        'document','renderBoardHead',
    grabObj('Members')+'; return Members;')(
    st, esc, ()=>pending, h=>{shows.push(h);}, ()=>2, m=>esc(m.name),
    {admin:'ניהול',editor:'עריכה',viewer:'צפייה בלבד'}, {}, doc, ()=>{});
  const done=MW.open();
  ck('the dialog is on screen before the members have arrived',
     shows.length===1 && /aria-busy="true"/.test(shows[0]) && shows[0].includes('חברים והרשאות'),
     shows.join(' | ').slice(0,200));
  release({members:MEMBERS, available:[], can_manage:false});
  await done;
  ck('...and the answer fills it in', shows.length===2 && MEMBERS.every(m=>shows[1].includes(m.name)));

  // closed before the answer came back
  shows.length=0; let release2;
  const pending2=new Promise(r=>{ release2=r; });
  const MC=new Function('st','esc','api','showModal','meId','avatarInner','BROLE_HE','BROLE_WHAT',
                        'document','renderBoardHead',
    grabObj('Members')+'; return Members;')(
    st, esc, ()=>pending2, h=>{shows.push(h);}, ()=>2, m=>esc(m.name),
    {admin:'ניהול',editor:'עריכה',viewer:'צפייה בלבד'}, {}, doc, ()=>{});
  modal.open=true;
  const done2=MC.open();
  modal.open=false;                         // she closed it while it was loading
  release2({members:MEMBERS, available:[], can_manage:false});
  await done2;
  ck('an answer that lands after the dialog was closed does not reopen it', shows.length===1,
     shows.length+' dialogs drawn');
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
