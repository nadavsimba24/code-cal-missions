/* The five chart types, drawn headless out of index.html.
 *
 * What it pins is the geometry that is easy to get wrong in a way that still
 * looks like a chart: an axis that does not reach zero turns a 4% difference
 * into a doubling; a line interpolated over a missing period draws a trend
 * through months that have no answer; a pie over mixed signs draws a share
 * of a total that is not a total. And R08 throughout — every element a real
 * focusable control with a name, never colour alone.
 *
 * Driven by tests/test_dashboard_charts_ui.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');

const esc = s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const from = src.indexOf('const Charts = {');
const to = src.indexOf('/* ---- עורך הווידג׳ט (DASH-11) ----');
const Dash = {fmt:m=>m.result==null?'—':String(m.result)};
const {Charts} = new Function('esc','Dash', src.slice(from,to)+'\nreturn {Charts};')(esc,Dash);

let pass=0, fail=0;
const ck=(n,c,x='')=>{c?(pass++,console.log('  OK   '+n)):(fail++,console.log('  FAIL '+n+(x?'  → '+x:'')));};

const chart=(type,cats,series,extra={})=>({
  widget_id:7, type, legend:true,
  categories:cats.map((l,i)=>({key:'c'+i,label:l,color:'#0073ea'})),
  series:series.map((s,i)=>({key:'m'+(i?'::s'+i:''),label:s.label,metric:'m',
                             color:['#0073ea','#00c875'][i]||'#fdab3d',
                             points:s.points,precision:0})),
  ...extra});

/* ── DASH-23 · עמודות אנכיות ── */
const v1=chart('vbar',['א','ב'],[{label:'ספירה',points:[3,1]}]);
const vb=Charts.draw(v1);
ck('a vertical bar chart draws one element per value', (vb.match(/<rect /g)||[]).length===2);
ck('…each a focusable button', (vb.match(/role="button" tabindex="0"/g)||[]).length===2);
ck('…each named with its category, series and value', vb.includes('aria-label="א · ספירה: 3"'));
ck('…and each knows which cell it is', vb.includes('data-cat="c0"')&&vb.includes('data-ser="m"'));
ck('…and opens the records behind it', vb.includes('Dash.openDrill(7'));
ck('…by keyboard as well as by pointer', vb.includes("event.key==='Enter'"));

/* the axis includes zero — DASH-23.2 */
const d1=Charts.domain(chart('vbar',['א','ב'],[{label:'x',points:[100,104]}]));
ck('the value axis reaches zero, so 4% is not drawn as a doubling', d1.lo===0&&d1.hi===104);
const d2=Charts.domain(chart('vbar',['א'],[{label:'x',points:[-20]}]));
ck('…and negatives extend it the other way', d2.lo===-20&&d2.hi===0);

/* a single category equals the numbers widget — DASH-23.3 */
const one=chart('vbar',['הכל'],[{label:'סכום',points:[600]}]);
ck('a single category carries the whole figure', Charts.draw(one).includes('הכל · סכום: 600'));

/* ── DASH-24 · אופקיות ── */
const h1=chart('hbar',['קטגוריה ארוכה מאוד בעברית'],[{label:'ספירה',points:[5]}]);
const hb=Charts.draw(h1);
ck('a horizontal bar chart draws bars too', (hb.match(/<rect /g)||[]).length===1);
ck('…with the same labelling', hb.includes('aria-label="קטגוריה ארוכה מאוד בעברית · ספירה: 5"'));
ck('…and the same numbers as the vertical one',
   Charts.domain(h1).hi===Charts.domain(chart('vbar',['x'],[{label:'ספירה',points:[5]}])).hi);

/* ── DASH-25 · עוגה ודונאט ── */
const p1=chart('pie',['א','ב','ג'],[{label:'ספירה',points:[50,30,20]}]);
const pie=Charts.draw(p1);
ck('a pie draws one slice per category', (pie.match(/<path /g)||[]).length===3);
ck('…each a focusable button', (pie.match(/role="button"/g)||[]).length===3);
ck('…labelled with its share', pie.includes('50.0%'), 'the share carries one decimal');
const donut=Charts.draw(chart('donut',['א','ב'],[{label:'x',points:[1,1]}]));
// A ring, not a disc: each slice runs out along the arc, cuts in, and comes
// back along a SECOND arc. Asserted by shape rather than by radius — the
// radius follows the drawing surface, and pinning it pins the wrong thing.
const slice=/<path d="([^"]+)"/.exec(donut);
ck('a donut leaves a hole',
   slice && (slice[1].match(/A /g)||[]).length===2 && slice[1].includes('L '),
   slice && slice[1].slice(0,60));
ck('…while a pie is a wedge from the centre',
   /<path d="M [\d.]+,[\d.]+ L/.test(Charts.draw(chart('pie',['א'],[{label:'x',points:[1]}]))));
const neg=Charts.draw(chart('pie',['א','ב'],[{label:'x',points:[5,-2]}]));
ck('a negative value prevents the pie rather than being dropped',
   neg.includes('ערכים שליליים')&&neg.includes('עמודות'));
ck('…and nothing is drawn', !neg.includes('<path'));
const zero=Charts.draw(chart('pie',['א'],[{label:'x',points:[0]}]));
ck('a non-positive total prevents it too', zero.includes('אינו חיובי'));

/* ── DASH-26 · מוערמות ── */
const st=chart('stacked',['א'],[{label:'ס1',points:[3]},{label:'ס2',points:[2]}]);
const sb=Charts.draw(st);
ck('a stack draws a segment per series', (sb.match(/<rect /g)||[]).length===2);
ck('…and each segment names its own series', sb.includes('א · ס1: 3')&&sb.includes('א · ס2: 2'));
const dst=Charts.domain(st,{stacked:true});
ck('the stacked domain is the total of the stack, not the tallest piece', dst.hi===5);

/* ── DASH-27 · קו ── */
const ln=chart('line',['ינואר','פברואר','מרץ'],[{label:'ממוצע',points:[10,null,30]}]);
const line=Charts.draw(ln);
ck('a line breaks at a gap instead of crossing it', (line.match(/<polyline /g)||[]).length===0,
   'a single polyline would have bridged the hole');
ck('…and draws only the periods that have a value', (line.match(/<circle /g)||[]).length===2);
const full=Charts.draw(chart('line',['א','ב','ג'],[{label:'x',points:[1,2,3]}]));
ck('…while an unbroken series is one line', (full.match(/<polyline /g)||[]).length===1);

/* ── R08 · the table and the legend ── */
const tbl=Charts.table(v1);
ck('every chart has a data table with headers', tbl.includes('<th scope="col">א</th>')&&tbl.includes('scope="row"'));
ck('…whose cells open the same records', (tbl.match(/Dash\.openDrill\(7/g)||[]).length===2);
ck('…and which says so to a screen reader', tbl.includes('<caption class="sr-only">'));
ck('a gap in the table is a dash, never a zero', Charts.table(ln).includes('>—<'));
const leg=Charts.legend(st);
ck('the legend names every series beside its swatch', leg.includes('ס1')&&leg.includes('ס2'));
ck('…so colour is never the only difference', (leg.match(/<li>/g)||[]).length===2);

/* ── the chart has to be readable, not only correct ──
 * Reported as "בחרתי בהתפלגות לפי עובד משכ״י וקיבלתי ריבוע אחד כחול". The
 * numbers were right; the picture had no text in it at all — the labels
 * lived only in aria-label, the title and the legend — and a bar at the
 * domain's maximum filled the whole plot. One category drew one full-height
 * unlabelled rectangle, which is a blue square. */
const lone = chart('vbar',['עובד משכ״י'],[{label:'ספירה',points:[1]}]);
const s1 = Charts.draw(lone);
const box = Charts.plot();
const rect = /<rect[^>]*y="([\d.]+)"[^>]*height="([\d.]+)"/.exec(s1);
ck('a single bar does not fill the whole plot',
   rect && (box.h - (+rect[2])) > 4, rect && rect[2]);
ck('…and its category is written on the chart', s1.includes('עובד משכ״י'));
ck('the chart draws the category names', (s1.match(/class="ch-cat"/g)||[]).length === 1);
ck('…and a value axis, so a height is a quantity',
   (s1.match(/class="ch-tick"/g)||[]).length >= 2);
ck('the surface scales as a whole, so the text is not stretched',
   !Charts.frame({},'').includes('preserveAspectRatio="none"'));

const many = Charts.draw(chart('vbar',['א','ב','ג'],[{label:'x',points:[3,1,2]}]));
ck('every category is named', (many.match(/class="ch-cat"/g)||[]).length === 3);
const horiz = Charts.draw(chart('hbar',['קטגוריה ארוכה מאוד בעברית'],[{label:'x',points:[5]}]));
ck('a horizontal chart names its rows too', (horiz.match(/class="ch-cat"/g)||[]).length === 1);
ck('…and a long name is cut in the picture, not run across it',
   horiz.includes('…') && horiz.includes('<title>קטגוריה ארוכה מאוד בעברית</title>'));
const months = Charts.draw(chart('line',
  ['ינו','פבר','מרץ','אפר','מאי','יוני','יולי','אוג','ספט','אוק','נוב','דצמ'],
  [{label:'x',points:[1,2,3,4,5,6,7,8,9,10,11,12]}]));
ck('a crowded axis thins its labels instead of overprinting them',
   (months.match(/class="ch-cat"/g)||[]).length < 12);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
