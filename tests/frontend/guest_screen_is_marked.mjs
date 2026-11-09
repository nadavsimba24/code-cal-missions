/* An אורח's screen carries their name, and refuses to print itself.

   The request was "do not let a guest take a screenshot", and that cannot be
   done — not here and not anywhere. A web page cannot see Cmd+Shift+4, cannot
   see the system's capture tool, cannot see a screen recording and cannot see
   a phone pointed at the monitor. The scripts that claim to block screenshots
   catch the PrintScreen key on Windows and nothing else, and believing one is
   worse than having none.

   What is actually built is the pair that works against the same worry:

   * the mark. The guest's own name, address and the date, faintly across
     everything, above every layer the app paints and taking no clicks. The
     screenshot still happens; it is simply no longer anonymous;
   * the print. "Save as PDF" is the same dialogue, and it is the whole board
     as a file — and it is the one copy the browser asks the page about before
     making it, so it is the one that can be refused.

   Both read the role matrix (`clean_screen`, `print_board`), so an
   administrator can hand either back without a release.
   Driven by tests/test_guest_screen_is_marked.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT,'frontend','index.html'),'utf8');

function grabObj(name){
  const m = new RegExp(`^const ${name}=\\{`,'m').exec(src);
  if(!m) throw new Error('not found: '+name);
  let i=src.indexOf('{',m.index), d=0;
  for(let j=i;j<src.length;j++){ if(src[j]==='{')d++; else if(src[j]==='}'){d--; if(!d) return src.slice(m.index,j+1);} }
}
const rule = re => { const m=re.exec(src); return m?m[0]:null; };
let pass=0, fail=0;
const ck=(n,c,extra='')=>{ c?(pass++,console.log('  OK   '+n)) : (fail++,console.log('  FAIL '+n+(extra?'  → '+extra:''))); };

const S = grabObj('Screen');

// ── who gets a marked screen ──────────────────────────────────────────────
ck('the mark is the matrix capability, not a role spelled out again',
   /hasCap\('clean_screen'\)/.test(S) && !/role==='guest'/.test(S), S);
ck('…and printing is its own capability, separately given',
   /hasCap\('print_board'\)/.test(S), S);
ck('a screen that may be clean carries nothing at all',
   /if\(hasCap\('clean_screen'\)\|\|!st\.me\)\{ if\(had\)had\.remove\(\); return; \}/.test(S), S);

// ── what the mark says ────────────────────────────────────────────────────
ck('it names the person, their address and the day',
   /st\.me\.name/.test(S) && /st\.me\.email/.test(S) && /toLocaleDateString\('he-IL'\)/.test(S), S);
/* a board name is stored XSS; a person's own name is no different */
ck('…and every one of those is escaped into the picture',
   /\$\{esc\(line\)\}/.test(S) && !/\$\{line\}/.test(S), S);
ck('the tile repeats itself rather than being drawn a few hundred times',
   /<pattern id="wm-p"/.test(S) && /fill="url\(#wm-p\)"/.test(S), S);
ck('…twice per tile and offset, so a crop still catches a whole line',
   (S.match(/<text /g)||[]).length===2, S);

// ── where it sits ─────────────────────────────────────────────────────────
const wm = rule(/#wm\{[^}]*\}/);
ck('the mark is fixed over the whole window', !!wm && /position:fixed/.test(wm) && /inset:0/.test(wm), wm);
/* above everything the app paints, or a screenshot of a modal has no mark on it */
const tops = [...src.matchAll(/z-index:(\d+)/g)].map(m=>+m[1]).filter(z=>z<99999);
const wmZ = +(/z-index:(\d+)/.exec(wm||'')||[])[1];
ck('…above every layer the app itself draws', wmZ>Math.max(...tops.filter(z=>z!==wmZ)),
   'mark '+wmZ+' vs highest '+Math.max(...tops.filter(z=>z!==wmZ)));
ck('…and in the way of nothing', !!wm && /pointer-events:none/.test(wm), wm);
ck('it is not a thing to select and delete out of the page either',
   !!wm && /user-select:none/.test(wm), wm);
ck('and it is hidden from a screen reader, which has no use for it',
   /aria-hidden","true"|aria-hidden','true'/.test(S.replace(/\s/g,'')), S);

// ── the print ─────────────────────────────────────────────────────────────
ck('the body is marked when printing is not allowed',
   /classList\.toggle\('no-print',!hasCap\('print_board'\)\)/.test(S), S);
const pr = rule(/@media print\{\s*body\.no-print[\s\S]*?\n\}/);
ck('a blocked print puts nothing on the page', !!pr && /body\.no-print \*\{display:none!important\}/.test(pr), pr);
/* a blank sheet reads as a broken feature and gets tried again — `*` cannot
   match body's own ::before, which is how the reason survives the blanking */
ck('…except the reason it refused', !!pr && /body\.no-print::before\{[^}]*content:"[^"]+"/.test(pr), pr);
ck('the keyboard shortcut is answered before the dialogue opens',
   /e\.key==='p'\|\|e\.key==='P'/.test(S) && /ctrlKey\|\|e\.metaKey/.test(S)
   && /e\.preventDefault\(\); toast\(/.test(S), S);
ck('…and it defers to the capability, not to anything of its own',
   /if\(hasCap\('print_board'\)\)return;/.test(S), S);
/* and it is answered inside the app's ONE keydown listener — a second global
   one is what tests/test_automation_mobile_a11y.py exists to keep out, because
   two of them makes the order a key is answered in a matter of load order */
ck('the shortcut is answered inside the app\'s single keydown listener',
   (src.match(/document\.addEventListener\('keydown',e=>\{/g)||[]).length===1
   && /document\.addEventListener\('keydown',e=>\{[\s\S]{0,460}?Screen\.key\(e\)/.test(src));
ck('…ahead of the Escape that listener is otherwise about',
   /Screen\.key\(e\); \}catch\(_\)\{ \}\n  if\(e\.key!=='Escape'/.test(src));

// ── and it keeps up ───────────────────────────────────────────────────────
ck('the screen is settled once the account and the matrix are both known',
   /renderMe\(\);\n\s*Screen\.sync\(\);/.test(src));
ck('…and again the moment an administrator changes the matrix',
   /st\.rolePerms\.matrix\[role\]=r\.matrix\[role\];[\s\S]{0,220}?Screen\.sync\(\)/.test(src));

// ── what it does NOT claim ────────────────────────────────────────────────
/* no key-trapping theatre: a "blocked" PrintScreen is a lock on a door that is
   not there, and the comment above the object says so in as many words */
ck('nothing pretends to catch a screenshot',
   !/key\s*===\s*['"]PrintScreen['"]/.test(src) && !/keyCode\s*===\s*44/.test(src)
   && !/clipboard\.writeText\(''\)/.test(src));
ck('and the reasoning is written down where the next person will look',
   /cannot see Cmd\+Shift\+4/.test(src));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
