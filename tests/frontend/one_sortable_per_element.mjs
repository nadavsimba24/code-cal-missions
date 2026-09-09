/* Dragging a group stopped working the longer a board stayed open.

   Sortable hangs its listeners on the element and keeps only a reference to
   itself there, so constructing a second one on the same element overwrites
   the reference and leaves the first bound and listening. Most lists here are
   rebuilt from innerHTML — a new element every render, nothing to collide with
   — but the board view is not: renderView empties #view and never replaces it,
   and #view is the container the GROUPS are dragged inside. Every re-render of
   a board therefore added another instance to it, and a board re-renders
   constantly: a cell edited, a filter changed, a sort, a live update, a drag
   landing. Two instances then raced to drag the same group on one pointerdown,
   then three, then four.

   Item drag was never affected, because its tbody is thrown away and rebuilt
   each render — which is exactly why this presented as a fault in group
   dragging alone, and why looking at the group drag code found nothing.
   Driven by tests/test_one_sortable_per_element.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grab(name){
  const m = new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

// ── the helper does what it says ───────────────────────────────────────────
/* a stand-in Sortable that records what happened to it, the way the real one
   behaves: the newest instance is the one the element hands back */
function stubEnv(){
  const log=[];
  const bound=new Map();                       // element → live instances
  function Sortable(el,opts){
    this.el=el; this.opts=opts; this.dead=false;
    log.push('new');
    bound.set(el,(bound.get(el)||[]).concat(this));
    el.__s=this;                               // Sortable.get reads this
  }
  Sortable.prototype.destroy=function(){
    this.dead=true; log.push('destroy');
    bound.set(this.el,(bound.get(this.el)||[]).filter(x=>x!==this));
    this.el.__s=null;
  };
  Sortable.get=el=>el&&el.__s;
  const live=el=>(bound.get(el)||[]).filter(x=>!x.dead).length;
  return {Sortable,log,live};
}
const env=stubEnv();
const sortableOn=new Function('window','Sortable',grab('sortableOn')+'; return sortableOn;')(
  {Sortable:env.Sortable}, env.Sortable);

const view={};                                  // one element, rendered over and over
const a=sortableOn(view,{tag:'first'});
ck('the first render binds one instance', env.live(view)===1);
const b=sortableOn(view,{tag:'second'});
ck('a second render still leaves exactly one', env.live(view)===1, 'live '+env.live(view));
ck('and it is the new one — the old is destroyed, not merely forgotten',
   a.dead===true && b.dead===false);
for(let i=0;i<20;i++) sortableOn(view,{tag:'again'});
ck('twenty renders of the same board leave one instance, not twenty',
   env.live(view)===1, 'live '+env.live(view));
ck('each render destroyed exactly the one before it',
   env.log.filter(x=>x==='new').length===22 && env.log.filter(x=>x==='destroy').length===21,
   env.log.join(',').slice(0,60));

const fresh={};
sortableOn(fresh,{tag:'x'});
ck('a brand-new element is bound without destroying anything of its own',
   env.live(fresh)===1);
ck('a missing element is not an error — the caller need not check',
   sortableOn(null,{})===null);

// ── and every list goes through it ─────────────────────────────────────────
/* the one place `new Sortable` is allowed to appear is inside the helper */
const raw=[...src.matchAll(/new Sortable\(/g)];
ck('nothing constructs a Sortable directly any more',
   raw.length===1, raw.length+' direct constructions');
ck('and the one that does is the helper',
   /function sortableOn\(el,opts\)\{[\s\S]{0,200}?return new Sortable\(el,opts\);/.test(src));
ck('the helper destroys what was there before constructing',
   /const prev=Sortable\.get\(el\); if\(prev\)prev\.destroy\(\);/.test(grab('sortableOn')));

const lists=[["the groups, on the view that outlives them","handle:'.g-handle'"],
             ["the items","draggable:'tr[data-tid]'"],
             ["the sub-items","draggable:'tr[data-sid]'"],
             ["the kanban columns","group:'kanban'"],
             ["the sidebar folders","group:'sb-folders'"],
             ["the sidebar boards","group:'sb-boards'"],
             ["the form builder's rows","handle:'.fb-drag'"]];
for(const [what,marker] of lists){
  const i=src.indexOf(marker);
  const before=src.slice(Math.max(0,i-260), i);
  ck(`${what} go through it`, /sortableOn\($/.test(before.trimEnd()) || /sortableOn\([^;]*$/.test(before),
     before.slice(-70));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
