/* המרת עמודה לעמודת "חיבור ללוח" — the three steps, and the cell that waits.

   Four things are pinned here, and every one of them is a way the screen can
   go wrong while the server stays perfectly correct:

   1. The wizard really is three steps, and they chain. Step 1 asks which board
      and which of its fields names a record; step 2 is the preview, which is
      the thing somebody agrees to; step 3 is the exception list, which is the
      work the conversion created. A "wizard" that renders step 2 and leaves
      the admin to find the exceptions in a column menu they have never opened
      is the version of this feature nobody finishes using.

   2. The preview is asked for WITH `multiple`. The server defaults it to true,
      so a screen that forgets it shows `too_many_values: 0` and then performs
      a conversion that produces exactly those exceptions. Flipping the
      single/multi switch has to ask the server again rather than edit the
      numbers already on screen — this is the one way step 2 and step 3 can
      disagree, and it is silent.

   3. A cell whose words nobody could match shows THOSE WORDS, not an empty
      cell. An empty cell is indistinguishable from "the conversion ate my
      data", and the original is still there — on the conversion row, waiting
      for somebody to say what it meant.

   4. The entries: "קישור ללוח" in the retype picker, and "טיפול בחריגות (n)"
      on a connect column with a conversion open — both board-admin only,
      because the server refuses everyone else and a button that always fails
      teaches people not to trust the menu.

   There is no DOM and no browser: the functions are pulled out of index.html
   as text and run with new Function over a sandbox. Driven by
   tests/test_column_becomes_a_link.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

/* ---- pulling the source apart ---- */
function balanced(from){
  let i = src.indexOf('{', from), d = 0;
  for(let j=i;j<src.length;j++){
    if(src[j]==='{') d++;
    else if(src[j]==='}'){ d--; if(!d) return src.slice(from, j+1); }
  }
  throw new Error('unbalanced from '+from);
}
function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(src);
  if(!m) throw new Error('not found: function '+name);
  return balanced(m.index);
}
function grabObj(name){
  const m = new RegExp(`^const ${name}\\s*=\\s*\\{`, 'm').exec(src);
  if(!m) throw new Error('not found: const '+name+'={');
  return balanced(m.index) + ';';
}
function konst(name){
  const m = new RegExp(`^const ${name}\\s*=[\\s\\S]*?;$`, 'm').exec(src);
  if(!m) throw new Error('not found: const '+name);
  return m[0];
}

let pass=0, fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n))
                        :(fail++,console.log('  FAIL '+n+(x?'  → '+JSON.stringify(String(x).slice(0,400)):''))); };

/* ---- the board the wizard is run against ---- */
const COL = {id:'col_cust', type:'text', title:'לקוחות'};
const CONNECT = {id:'col_cust', type:'connect', title:'לקוחות',
                 connect:{board_ids:[9], multiple:true, two_way:false, match_field:'title'}};

const FIELDS = {target_board_id:9, target_board_name:'לקוחות', records:7, fields:[
  {key:'title', label:'שם הפריט', type:'title', filled:7, distinct:6, duplicates:1},
  {key:'col_hp', label:'ח.פ.', type:'text', filled:5, distinct:5, duplicates:0}]};

const PREVIEW = (multiple)=>({
  col_id:'col_cust', title:'לקוחות', from:'text', target_board_id:9,
  target_board_name:'לקוחות', match_field:'title', multiple:!!multiple,
  total:8, empty:3, matched:multiple?3:2, unmatched:1, ambiguous:multiple?1:2,
  samples:[{task_id:20, item:'פרויקט א', before:'עיריית חיפה',
            after:{id:16, title:'עיריית חיפה'}}],
  exceptions:[
    {task_id:21, item:'פרויקט ב', before:'עיריה חיפה',
     outcome:'unmatched', reason:'no_match', candidates:[]},
    {task_id:22, item:'פרויקט ג', before:'מועצה',
     outcome:'ambiguous', reason:'several',
     candidates:[{id:17,title:'מועצה אזורית'},{id:18,title:'מועצה מקומית'}]},
  ].concat(multiple?[]:[{task_id:23, item:'פרויקט ד', before:'עיריית חיפה, רשות העתיקות',
                         outcome:'ambiguous', reason:'too_many_values',
                         candidates:[{id:16,title:'עיריית חיפה'}]}]),
  exceptions_total:multiple?2:3, forms:[]});

/* One row of each of the three kinds the resolver can be handed, and the
   third one is here because it was NOT and that cost a bug report.

   A `suggested` row renders differently (blue, lm-row-sug), carries the
   records the ladder proposed, and is the only kind that gets an "אשר"
   button — and none of that was ever rendered by this harness, so
   LinkMatch.accept and the whole suggestion affordance went untested while
   reading as covered. A user reported "אשר does nothing"; the code turned out
   to be right, but nothing here would have said so either way. */
const EXCEPTIONS = {conversion_id:1, col_id:'col_cust', target_board_id:9,
  target_board_name:'לקוחות', match_field:'title',
  open:3, resolved:0, total:3, offset:0, limit:50,
  rows:[{task_id:21, item:'פרויקט ב', before:'עיריה חיפה',
         outcome:'unmatched', reason:'no_match', linked_task_id:null, candidates:[]},
        {task_id:22, item:'פרויקט ג', before:'מועצה',
         outcome:'ambiguous', reason:'several', linked_task_id:null,
         candidates:[{id:17,title:'מועצה אזורית'},{id:18,title:'מועצה מקומית'}]},
        {task_id:77, item:'פרויקט ד', before:"חב' עירונית ראשון לציון",
         outcome:'suggested', reason:'abbrev', tier_he:'שם מקוצר',
         linked_task_id:null,
         candidates:[{id:88,title:'חברה עירונית ראשון לציון'}]}]};

/* ---- the sandbox ---- */
function makeSandbox(opts){
  opts = opts || {};
  const log = {modals:[], gets:[], posts:[], toasts:[], rendered:0};
  const sandbox = {
    log,
    st:{me:{id:1},
        board:{id:3, my_role:opts.role||'admin',
               columns:[opts.col||COL], col_perms:{}},
        boards:opts.boards!==undefined?opts.boards:[{id:3,name:'מקור'},{id:9,name:'לקוחות',icon:'🏢'}]},
    document:{querySelector:()=>null, getElementById:()=>null},
    showModal:h=>{ log.modals.push(h); },
    closeModals:()=>{ log.modals.push('__CLOSED__'); },
    openCellPop:(_a,h)=>{ log.modals.push(h); },
    toast:m=>{ log.toasts.push(m); },
    renderView:()=>{ log.rendered++; },
    askConfirm:()=>{},
    Views:{active:null},
    isSysAdmin:()=>false,
    connectDisp:()=>'__CONNECT_DISP__',
    cellValue:(t,id)=>(t.custom_fields||{})[id],
    api:(url,init)=>{
      if(init&&init.method==='POST'){
        log.posts.push({url, body:init.body});
        // a request that never settles, so `busy` stays true and a second
        // press hits the double-submit guard exactly as it would in a browser
        if(opts.hangPost) return new Promise(()=>{});
        return Promise.resolve(opts.applyAnswer||
          {conversion_id:1, columns:[CONNECT], matched:3, unmatched:1, ambiguous:1});
      }
      log.gets.push(url);
      if(url.includes('link-match/fields')) return Promise.resolve(FIELDS);
      if(url.includes('link-exceptions'))   return Promise.resolve(EXCEPTIONS);
      if(url.includes('link-match'))        return Promise.resolve(PREVIEW(/multiple=true/.test(url)));
      if(/^\/api\/boards\/\d+/.test(url))   return Promise.resolve({id:3, my_role:'admin', columns:[CONNECT]});
      return Promise.resolve({});
    },
  };
  const body = [
    konst('esc'), grab('customColumns'), grab('isBoardAdmin'), grab('meId'),
    grab('withMe'), grab('colTypeHe'), grab('linkPendingHTML'),
    grab('customCellHTML'), grab('colMenu'), grab('retypeColumn'),
    konst('COLUMN_TYPES'), konst('RETYPE_TYPES'), konst('RETYPE_RULE'),
    konst('LINK_MATCH_STEPS'), konst('LINK_MATCH_REASONS'),
    konst('LINK_MATCH_WHY_SHORT'), konst('LINK_MATCH_WHY'),
    /* Every LINK_* the page declares, discovered rather than listed: the tier
       ladder arrived with four more of them, and a harness that names them one
       by one goes red on the next one for no reason anybody can act on. */
    ...[...src.matchAll(/^const (LINK_[A-Z_]+)\s*=/gm)]
         .map(m => m[1])
         .filter(n => !['LINK_MATCH_STEPS','LINK_MATCH_REASONS',
                        'LINK_MATCH_WHY_SHORT','LINK_MATCH_WHY'].includes(n))
         .map(konst),
    grabObj('LinkMatch'),
  ].join('\n');
  /* Evaluated ONCE and handed back an evaluator, so LinkMatch keeps its state
     between calls. Rebuilding the body per call gave every step a brand-new
     LinkMatch with target 0, and the wizard silently never left step 1. */
  const factory = new Function('sandbox', `with(sandbox){ ${body}
    return expr=>eval(expr); }`);
  return {sandbox, log, run:factory(sandbox)};
}
const last = log => log.modals.filter(m=>m!=='__CLOSED__').slice(-1)[0] || '';

/* ════ 1. the three steps exist and chain ════ */
{
  const {log, run} = makeSandbox();
  const steps = run('LINK_MATCH_STEPS');
  ck('the wizard declares exactly three steps', steps.length===3, steps);

  run("LinkMatch.start('col_cust')");
  const s1 = last(log);
  ck('step 1 renders', !!s1 && s1.includes('המרה לעמודת קישור ללוח'), s1.slice(0,120));
  ck('step 1 names all three steps in the crumb',
     steps.every(s=>s1.includes(s)), steps.filter(s=>!s1.includes(s)));
  ck('step 1 marks itself as the step it is', s1.includes('<b>'+steps[0]+'</b>'));
  ck('step 1 offers every other board the person may open',
     s1.includes('לקוחות') && s1.includes('LinkMatch.chooseBoard(9)'), s1.slice(0,300));
  ck('step 1 says plainly that nothing is guessed', s1.includes('אין ניחושים'));
  ck('step 1 carries the single/multi and one-way/two-way switches',
     s1.includes('id="lm-multi"') && s1.includes('id="lm-two"'));
  ck('and it cannot be left before a board is chosen',
     /onclick="LinkMatch.toStep2\(\)" disabled/.test(s1), s1.slice(s1.indexOf('toStep2')-40, s1.indexOf('toStep2')+60));

  /* the fields of the chosen board, and the duplicate count that decides it */
  await run('LinkMatch.chooseBoard(9)');
  const s1b = last(log);
  ck('choosing a board asks the server which fields identify a record',
     log.gets.some(u=>u.includes('link-match/fields?target_board_id=9')), log.gets);
  ck('each field says how well it identifies one',
     s1b.includes('ח.פ.') && s1b.includes('7 רשומות עם ערך'), s1b.slice(0,200));
  ck('a field with repeats says so, in words, before it is chosen',
     s1b.includes('לא ניתן לזהות לפיו רשומה אחת'), s1b.slice(0,200));
  ck('and the field with none does not',
     (s1b.match(/לא ניתן לזהות לפיו רשומה אחת/g)||[]).length===1);
  ck('now it can be left', !/onclick="LinkMatch.toStep2\(\)" disabled/.test(s1b));

  /* step 2 */
  await run('LinkMatch.toStep2()');
  const s2 = last(log);
  ck('step 2 renders and is step 2', s2.includes('<b>'+steps[1]+'</b>'), s2.slice(0,200));
  ck('step 2 shows the four counts as a summary strip',
     s2.includes('יקושרו') && s2.includes('לא נמצאה רשומה')
     && s2.includes('יותר מרשומה אחת') && s2.includes('תאים ריקים'));
  ck('step 2 shows the matched samples as before → after rows',
     s2.includes('rt-before') && s2.includes('rt-after')
     && s2.includes('עיריית חיפה'), s2.slice(0,200));
  ck('step 2 groups the exceptions by the reason they failed',
     s2.includes('לא נמצאה רשומה') && s2.includes('יותר מרשומה אחת'));
  /* Step 1 still says "אין ניחושים" outright. Step 2 restates it for the
     ladder, and has to: with smart matching on, the honest version of the
     promise is not "nothing is found" but "nothing found this way is
     WRITTEN" — it is proposed and waits for the admin. Pinning the old blanket
     wording here would have forced the screen to keep a sentence that is no
     longer the whole truth. */
  ck('step 2 promises the smart matches are proposed and not written',
     s2.includes('מוצעת ואינה נכתבת'), s2.slice(0, 600));
  ck('and that no record is created on the target board',
     s2.includes('אף רשומה חדשה אינה נוצרת'), s2.slice(0, 600));
  ck('step 2 can go back to step 1', s2.includes('LinkMatch.step1()'));
  ck('and its confirm is the only thing that writes', s2.includes('LinkMatch.apply()'));

  /* step 3, reached from step 2 */
  await run('LinkMatch.apply()');
  ck('confirming posts the conversion',
     log.posts.length===1 && log.posts[0].url.includes('/link-match'), log.posts);
  const sent = JSON.parse(log.posts[0].body||'{}');
  ck('and posts the board, the field and the cardinality it previewed',
     sent.target_board_id===9 && sent.match_field==='title'
     && sent.multiple===true && sent.two_way===false, sent);
  const s3 = last(log);
  ck('step 3 opens by itself when the conversion left work behind',
     s3.includes('טיפול בחריגות ההמרה') && s3.includes('<b>'+steps[2]+'</b>'), s3.slice(0,200));
  ck('step 3 shows one row per exception, with the ORIGINAL text',
     s3.includes('עיריה חיפה') && s3.includes('מועצה'), s3.slice(0,400));
  ck('step 3 says why each one is waiting',
     s3.includes('לא נמצאה רשומה') && s3.includes('יותר מרשומה אחת'));
  ck('step 3 offers the candidates it already found',
     s3.includes('LinkMatch.resolve(22,17)'), s3.slice(0,400));
  /* "השאר ריק" is what this button used to say, and it was a promise the
     action does not keep: the server drops the dead ends of the cell and
     nothing else, so a link somebody chose by hand between the apply and this
     screen survives. It answers the ROW — this value has no record, stop
     asking — which is what the label now says. */
  ck('step 3 offers a search and "סמן כלא מותאם" for every row',
     s3.includes('LinkMatch.pick(21)') && s3.includes('LinkMatch.clear(21)'));
  /* Read off the button itself rather than the whole dialog: the markup
     carries a source comment quoting the old label, and a dialog-wide search
     would pass on that and go on passing if the button were reverted. */
  const clearBtn = /<button[^>]*LinkMatch\.clear\(21\)[^>]*>([\s\S]*?)<\/button>/.exec(s3);
  ck('the button that answers the row is there at all', !!clearBtn, s3.slice(0, 300));
  ck('and it no longer promises to empty the cell',
     !!clearBtn && clearBtn[1].includes('סמן כלא מותאם')
     && !clearBtn[1].includes('השאר ריק'), clearBtn && clearBtn[1]);
  ck('step 3 offers "ביטול ההמרה" while the conversion is open',
     s3.includes('ביטול ההמרה') && s3.includes('LinkMatch.revert()'));
  ck('and it says how much is left', s3.includes('ממתינים') && s3.includes('טופלו'));

  /* ── the suggestion row, which nothing here used to render ──
     A `suggested` row is a different affordance from an exception: the ladder
     already found the record, so the question is not "which one" but "yes or
     no". It is drawn blue, it names what it proposes and why, and it carries
     the one button that answers it. All of that went untested until a user
     reported the button as dead. */
  const sugRow = /<div class="lm-row[^"]*"[^>]*id="lm-row-77"[\s\S]*?<\/div>\s*<\/div>/.exec(s3);
  ck('a suggested row is rendered at all', !!sugRow, s3.slice(0, 300));
  const SR = sugRow ? sugRow[0] : '';
  ck('and is drawn as a suggestion rather than an exception',
     SR.includes('lm-row-sug'), SR.slice(0, 200));
  ck('it shows the record the ladder proposed',
     SR.includes('חברה עירונית ראשון לציון'), SR);
  ck('and says which kind of match proposed it',
     SR.includes('שם מקוצר'), SR);
  ck('it still shows the value the cell holds',
     SR.includes("חב' עירונית ראשון לציון"), SR);

  ck('the אשר button is on the suggestion row',
     /onclick="LinkMatch\.accept\(77\)"/.test(SR) && SR.includes('אשר'), SR);
  const excRow = /<div class="lm-row[^"]*"[^>]*id="lm-row-21"[\s\S]*?<\/div>\s*<\/div>/.exec(s3);
  ck('and nowhere near a row that matched nothing',
     !!excRow && !excRow[0].includes('LinkMatch.accept('), excRow && excRow[0]);

  /* The candidate quick-links are the unmatched/ambiguous affordance — "we
     found several, pick one". On a suggestion they would be a second, worse
     way to answer the same question: resolve(task,id) writes ONE record, and
     a multi-value cell can have had two proposed to it. */
  ck('the candidate quick-links are suppressed on a suggestion',
     !SR.includes('LinkMatch.resolve('), SR);
  ck('and are still offered on the ambiguous row',
     /LinkMatch\.resolve\(22,17\)/.test(s3), s3.slice(0, 400));
  ck('"סמן כלא מותאם" is offered on a suggestion too',
     /onclick="LinkMatch\.clear\(77\)"/.test(SR), SR);
}

/* ════ the suggestion is accepted as a SUGGESTION, not as one of its ids ════
   This is the whole reason `accept` exists as an action of its own. A cell
   reading two values can have been proposed two records, and answering with
   {item_id:…} would link the first and silently drop the second — which is
   exactly the bug `accept` was added to make impossible. Nothing pinned the
   distinction until a report of the button doing nothing sent somebody
   looking for the test that covered it. */
{
  const {log, run} = makeSandbox({col:CONNECT});
  await run("LinkMatch.openExceptions('col_cust')");
  log.posts.length = 0;
  await run('LinkMatch.accept(77)');
  ck('accepting issues exactly one request', log.posts.length===1, log.posts);
  const post = log.posts[0] || {};
  ck('to that row of the exception list',
     /\/columns\/col_cust\/link-exceptions\/77$/.test(post.url||''), post.url);
  const sent = JSON.parse(post.body||'{}');
  ck("and says {action:'accept'}", sent.action==='accept', sent);
  ck('and does NOT pick one candidate by id — that would drop the others',
     !('item_id' in sent), sent);

  const {log:l2, run:r2} = makeSandbox({col:CONNECT});
  await r2("LinkMatch.openExceptions('col_cust')");
  l2.posts.length = 0;
  await r2('LinkMatch.clear(77)');
  ck('marking a suggestion unmatched still sends {action:"clear"}',
     JSON.parse((l2.posts[0]||{}).body||'{}').action==='clear', l2.posts);
}

/* ════ a second press while one is in flight ════
   The guard used to `return` in silence, and that is the worst thing this
   screen can do: a button that does nothing is indistinguishable from a
   broken one, so somebody presses it five more times and reports the feature
   as dead — which is precisely what happened. Both halves are pinned: no
   second request, and the person is told why. */
{
  const {log, run} = makeSandbox({col:CONNECT, hangPost:true});
  await run("LinkMatch.openExceptions('col_cust')");
  log.posts.length = 0; log.toasts.length = 0;
  run('LinkMatch.accept(77)');          // deliberately not awaited: it hangs
  ck('the first press goes out', log.posts.length===1, log.posts);
  run('LinkMatch.accept(77)');
  ck('the second does not double-submit', log.posts.length===1, log.posts);
  ck('and it says why rather than doing nothing at all',
     log.toasts.length===1 && /\S/.test(log.toasts[0]||''), log.toasts);
}

/* ════ 2. the preview is asked for with the cardinality it is about to apply ════ */
{
  const {log, run} = makeSandbox();
  run("LinkMatch.start('col_cust')");
  await run('LinkMatch.chooseBoard(9)');
  await run('LinkMatch.toStep2()');
  const first = log.gets.filter(u=>/\/link-match\?/.test(u)).slice(-1)[0];
  ck('the preview call carries `multiple`', /multiple=/.test(first||''), first);
  ck('and it carries the board and the field too',
     /target_board_id=9/.test(first) && /match_field=title/.test(first), first);
  const before = last(log);
  ck('with multiple on, the overflow exception is not in the list',
     !before.includes('יותר מערך אחד בתא'), before.slice(0,200));

  await run('LinkMatch.flipMulti(false)');
  const second = log.gets.filter(u=>/\/link-match\?/.test(u)).slice(-1)[0];
  ck('flipping the switch asks the server again rather than editing the numbers',
     /multiple=false/.test(second||''), second);
  const after = last(log);
  ck('and the answer changes what step 2 says',
     after.includes('יותר מערך אחד בתא'), after.slice(0,200));
  ck('the counts on screen are the ones that came back',
     after.includes('>2</b><small>יקושרו') , after.slice(after.indexOf('lm-sum'), after.indexOf('lm-sum')+300));

  await run('LinkMatch.apply()');
  const sent = JSON.parse(log.posts[0].body||'{}');
  ck('and the apply posts the SAME cardinality the preview was taken with',
     sent.multiple===false, sent);
}

/* ════ 3. a cell waiting to be matched shows what it used to say ════ */
{
  const {run} = makeSandbox({col:CONNECT});
  const pending = run(`customCellHTML(${JSON.stringify(CONNECT)},
    {id:21, custom_fields:{}, link_pending:{col_cust:'עיריה חיפה'}})`);
  ck('an unresolved exception draws its original text, not an empty cell',
     pending.includes('עיריה חיפה') && !pending.includes('__CONNECT_DISP__'), pending);
  ck('and marks it as unfinished rather than as a value',
     pending.includes('לא הותאם — ממתין לטיפול'), pending);
  ck('and clicking it opens the resolver for that row',
     pending.includes("LinkMatch.openExceptions('col_cust',21)"), pending);

  const linked = run(`customCellHTML(${JSON.stringify(CONNECT)},
    {id:20, custom_fields:{col_cust:[16]}})`);
  ck('a cell that got its link is drawn as a link',
     linked.includes('__CONNECT_DISP__') && !linked.includes('לא הותאם'), linked);

  const plain = run(`customCellHTML(${JSON.stringify(CONNECT)},
    {id:23, custom_fields:{}})`);
  ck('a connect cell with nothing pending is the ordinary empty one',
     plain.includes('__CONNECT_DISP__'), plain);

  /* a resolved row can still be in the payload for a moment; a cell that has
     both a link and a pending value is a link */
  const both = run(`customCellHTML(${JSON.stringify(CONNECT)},
    {id:24, custom_fields:{col_cust:[16]}, link_pending:{col_cust:'עיריה חיפה'}})`);
  ck('a cell that already holds a link is not redrawn as waiting',
     both.includes('__CONNECT_DISP__'), both);

  const nasty = run(`linkPendingHTML('<img src=x onerror=alert(1)>')`);
  ck('the original text is escaped — it is a value a stranger may have typed',
     !nasty.includes('<img') && nasty.includes('&lt;img'), nasty);
}

/* ════ 4. the two ways in, and who is offered them ════ */
{
  const {log, run} = makeSandbox();
  run("retypeColumn('col_cust')");
  const m = last(log);
  ck('the retype picker offers "קישור ללוח"', m.includes('קישור ללוח'), m.slice(0,200));
  ck('and it goes to the wizard, not through retypePreview',
     m.includes("LinkMatch.start('col_cust')"), m.slice(0,200));
}
{
  const {log, run} = makeSandbox({role:'editor'});
  // retypeColumn refuses an editor outright; canOffer is the guard that matters
  ck('an editor is not offered the conversion', run('LinkMatch.canOffer()')===false);
  run("LinkMatch.start('col_cust')");
  ck('and starting it anyway is refused in the browser too',
     log.modals.length===0 && log.toasts.length===1, {m:log.modals.length, t:log.toasts});
}
{
  const {run} = makeSandbox({boards:[{id:3,name:'מקור'}]});
  ck('with no other board to link to, it is not offered',
     run('LinkMatch.canOffer()')===false);
}
{
  const WITH = {...CONNECT, conversion:{id:1, open:3, resolved:1, total:4,
                                        target_board_id:9, match_field:'title'}};
  const {log, run} = makeSandbox({col:WITH});
  run(`colMenu({stopPropagation(){}, currentTarget:null}, 'col_cust')`);
  const menu = last(log);
  ck('a column mid-conversion offers "טיפול בחריגות" with the count',
     menu.includes('טיפול בחריגות (3)'), menu.slice(0,400));
  ck('and it opens step 3 for that column',
     menu.includes("LinkMatch.openExceptions('col_cust')"), menu.slice(0,400));

  const {log:l2, run:r2} = makeSandbox({col:CONNECT});
  r2(`colMenu({stopPropagation(){}, currentTarget:null}, 'col_cust')`);
  ck('a connect column with no conversion does not',
     !last(l2).includes('טיפול בחריגות'), last(l2).slice(0,300));

  const {log:l3, run:r3} = makeSandbox({col:WITH, role:'editor'});
  r3(`colMenu({stopPropagation(){}, currentTarget:null}, 'col_cust')`);
  ck('and an editor is never shown it', !last(l3).includes('טיפול בחריגות'));
}

/* ════ 5. the reasons the server can send all have words here ════ */
{
  const {run} = makeSandbox();
  const reasons = run('LINK_MATCH_REASONS');
  const short = run('LINK_MATCH_WHY_SHORT'), why = run('LINK_MATCH_WHY');
  for(const r of ['no_match','partial','several','too_many_values','target_deleted']){
    ck(`${r} is a reason the screen knows`, reasons.includes(r), reasons);
    ck(`${r} has a short name and an explanation`, !!short[r] && !!why[r], {s:short[r], w:why[r]});
  }
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
