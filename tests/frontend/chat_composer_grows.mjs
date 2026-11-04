/* תיבת ההודעה גדלה עם מה שנכתב בה.

   It was 44px and stayed there however long the message got, so writing
   anything substantial meant composing through a three-line window — or
   finding the drag handle, which is a thing you have to know is there.

   What is checked here is the part the server cannot: that the box follows
   the text, that it stops before it eats the conversation it belongs to,
   that the mention mirror behind it is not left behind, and that a height
   somebody chose by dragging survives the next keystroke.

   The textarea is a stand-in that models the one thing that matters —
   scrollHeight is the height the CONTENT needs, which is what the real one
   reports once height is set to auto.

   Driven by tests/test_chat_composer_grows.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^  ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
  throw new Error('unbalanced: '+name);
}

const LINE = 20;          // px per line in the stand-in
const MIN  = 44;
let ta, hl;

function makeTA(){
  return {
    value:'', style:{}, scrollTop:0,
    // the height the CONTENT needs — what a real textarea reports with
    // height:auto. One line minimum, like the CSS min-height.
    get scrollHeight(){
      const lines=Math.max(1, String(this.value||'').split('\n').length);
      return Math.max(MIN, lines*LINE);
    },
    // what the box actually ended up as: the inline height, clamped by the
    // CSS floor the real element also has
    get offsetHeight(){
      const h=parseInt(this.style.height||'',10);
      return Math.max(MIN, isFinite(h)?h:MIN);
    },
  };
}

const Chat=new Function('document','innerHeight',
  'const o={COMPOSER_MAX_VH:40,'
  +['grow','compMouseUp','syncHLScroll'].map(n=>grab(n)).join(',')
  +'}; return o;')(
  {getElementById:id=>(id==='comp-text'?ta:(id==='comp-hl'?hl:null))}, 1000);
// the real COMPOSER_MAX_VH, read off the source rather than repeated here
Chat.COMPOSER_MAX_VH = +/COMPOSER_MAX_VH:\s*(\d+)/.exec(src)[1];
const MAX = Math.max(120, Math.round(1000*Chat.COMPOSER_MAX_VH/100));

let pass=0,fail=0;
const ck=(n,c,x='')=>{ c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+String(x).slice(0,200):''))); };
const reset=()=>{ ta=makeTA(); hl={scrollTop:0,innerHTML:''}; Chat._compFloor=0; Chat._compAuto=0; };

// ── it grows ──────────────────────────────────────────────────────────────
{
  reset();
  Chat.grow();
  ck('an empty box is one line', ta.offsetHeight===MIN, ta.style.height);
  ta.value='שורה אחת';
  Chat.grow();
  const one=ta.offsetHeight;
  ta.value=Array.from({length:6},(_,i)=>'שורה '+i).join('\n');
  Chat.grow();
  ck('six lines are taller than one', ta.offsetHeight>one, one+' → '+ta.offsetHeight);
  ck('…and exactly as tall as the text needs', ta.offsetHeight===6*LINE,
     ta.style.height);
}
{
  // …and it shrinks again, or deleting a paragraph would leave a hole
  reset();
  ta.value=Array.from({length:8},(_,i)=>'ש'+i).join('\n');
  Chat.grow();
  const tall=ta.offsetHeight;
  ta.value='ש0';
  Chat.grow();
  ck('deleting the text gives the room back', ta.offsetHeight<tall,
     tall+' → '+ta.offsetHeight);
}

// ── it stops before it eats the conversation ─────────────────────────────
{
  reset();
  ta.value=Array.from({length:200},(_,i)=>'ש'+i).join('\n');
  Chat.grow();
  ck('a very long message stops at the ceiling', ta.offsetHeight===MAX,
     ta.style.height+' (max '+MAX+')');
  ck('…and scrolls from there', ta.style.overflowY==='auto', ta.style.overflowY);
}
{
  reset();
  ta.value='שורה\nשורה';
  Chat.grow();
  ck('below the ceiling it does not scroll', ta.style.overflowY==='hidden',
     ta.style.overflowY);
}
{
  // the ceiling is a share of the WINDOW, so a short window gets a short box
  const small=new Function('document','innerHeight',
    'const o={COMPOSER_MAX_VH:'+Chat.COMPOSER_MAX_VH+','+grab('grow')+'}; return o;')(
    {getElementById:id=>(id==='comp-text'?ta:null)}, 300);
  reset();
  ta.value=Array.from({length:200},(_,i)=>'ש'+i).join('\n');
  small.grow();
  ck('a short window gets a shorter ceiling, but never a useless one',
     ta.offsetHeight===120, ta.style.height);
}

// ── a height somebody chose survives the next keystroke ─────────────────
{
  reset();
  ta.value='שורה';
  Chat.grow();
  // …she drags the handle: the element's height is now not the one grow() set
  ta.style.height='260px';
  Chat.compMouseUp();
  ck('a drag is noticed', Chat._compFloor===260, Chat._compFloor);
  ta.value='שורה\nשורה';
  Chat.grow();
  ck('…and typing does not take it back', ta.offsetHeight===260, ta.style.height);
  // …but the box still grows PAST what she chose
  ta.value=Array.from({length:20},(_,i)=>'ש'+i).join('\n');
  Chat.grow();
  ck('…while still growing beyond it', ta.offsetHeight===20*LINE, ta.style.height);
}
{
  reset();
  ta.value='שורה';
  Chat.grow();
  const h=ta.offsetHeight;
  Chat.compMouseUp();                      // an ordinary click, no drag
  ck('an ordinary click inside the box is not a drag', !Chat._compFloor,
     Chat._compFloor);
  ta.value='';
  Chat.grow();
  ck('…so an emptied box still goes back to one line', ta.offsetHeight===MIN,
     ta.style.height);
  ck('(it had grown first)', h>=MIN);
}

// ── the wiring that makes it happen at all ──────────────────────────────
{
  ck('every change of the text grows the box, through syncHL',
     /syncHL\(\)\{[\s\S]*?this\.grow\(\);/.test(src));
  ck('…and the scroll handler does NOT, or it would fight itself',
     src.includes('onscroll="Chat.syncHLScroll()"')
     && !/syncHLScroll\(\)\{[\s\S]*?this\.grow\(\)/.test(src));
  ck('a drag is watched for on the box itself',
     src.includes('onmouseup="Chat.compMouseUp()"'));
  ck('a fresh composer starts over at one line',
     /composerHTML\(mode,cid\)\{[\s\S]*?this\._compFloor=0;/.test(src));
  ck('the window changing width re-measures it',
     /addEventListener\('resize',\(\)=>\{ try\{ this\.grow\(\); \}catch\(e\)\{\} \}\)/.test(src));
  ck('the mirror behind it needs nothing — it is inset:0 in the wrapper',
     /\.comp-hl\{position:absolute;inset:0/.test(src));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
