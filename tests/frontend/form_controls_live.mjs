/* כל רכיב בטופס — על שלושת המשטחים, לכל אחד עשר סוגי השאלה.

   "אף אחד מרכיבי הטופס לא עובד — לא אחראים, לא התאריך, והתיאור לא נותן
   להקליד." Six rounds of fixes shipped against that sentence, and the suite
   stayed green through every one of them, because what it asserted was that
   the RENDERER could draw a live control when a test asked it to. Nobody
   asserted that the PRODUCT asks it to.

   So this harness never invents its options. It reads the three real call
   sites — FormPaper.html(...) in frontend/index.html twice and in
   frontend/public-form.html once — and renders each surface with the option
   object that surface actually passes. A canvas that stops asking for
   `live:true`, or a renderer that stops reading it, fails here; both files
   are one program and this is the test that treats them as one.

   Then, per surface and per question type: the right ELEMENT (a date is an
   <input type=date>, a long text is a <textarea>, a multi select and an
   אחראים question are a tick box per option), and the control is usable
   where it should be and inert where it should be — no disabled, no
   readonly, no inert, no aria-disabled, no inline pointer-events:none.

   Driven by tests/test_form_controls_are_usable.py. */
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'frontend', 'index.html'), 'utf8');
const PUBLIC = fs.readFileSync(path.join(ROOT, 'frontend', 'public-form.html'), 'utf8');
const PAPER = fs.readFileSync(path.join(ROOT, 'frontend', 'form-paper.js'), 'utf8');

let pass = 0, fail = 0;
const ck = (n, c, x = '') => { c ? (pass++, console.log('  OK   ' + n))
                                 : (fail++, console.log('  FAIL ' + n + (x ? '  → ' + x : ''))); };

/* The renderer, run rather than read. It is a plain script that ends in a
   const, so a Function wrapper is the whole of "loading" it. */
const FormPaper = new Function(PAPER + ';return FormPaper;')();

// ── the three surfaces, taken off the product ────────────────────────

/* Where the comments are, so a call site that is being TALKED ABOUT is not
   mistaken for one that runs. index.html carries a note at the top about
   `FormPaper.html(doc, {live:true, ...})` and a stale cached renderer — the
   very hazard this file tests — and reading that as a fourth surface would
   be the test misreading the warning as the thing warned about.

   Ranges rather than a stripped copy: deleting /*…*​/ out of 19,600 lines of
   mixed CSS and JS can cut a real one in half when the opener is inside a
   string. The worst this can do is skip a real call site, which the count
   below catches. */
function commentRanges(src) {
  const out = [];
  for (const re of [/<!--[\s\S]*?-->/g, /\/\*[\s\S]*?\*\//g]) {
    let m;
    while ((m = re.exec(src))) out.push([m.index, m.index + m[0].length]);
  }
  return out;
}
const inAny = (ranges, i) => ranges.some(([a, b]) => i >= a && i < b);

/* The object literal that starts at `from`, by its braces. */
function literalAt(src, from) {
  let i = src.indexOf('{', from), d = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') d++;
    else if (src[j] === '}') { d--; if (!d) return src.slice(i, j + 1); }
  }
  throw new Error('unterminated options literal');
}

/* Every FormPaper.html(doc, {...}) in a shell file, as the keys it passes.
   The VALUES are not evaluated — `this.sel` and `this.form.name` mean
   nothing outside the editor — so a key is given the value its literal
   states when that is a boolean, and a stand-in otherwise. What is being
   reproduced is which switches the product throws, which is the thing that
   was wrong. */
function callSites(src, file) {
  const out = [], skip = commentRanges(src);
  const re = /FormPaper\.html\(/g;
  let m;
  while ((m = re.exec(src))) {
    if (inAny(skip, m.index)) continue;
    const lit = literalAt(src, m.index);
    const opts = {}, raw = {};
    /* keys at depth one of the literal: `key:` preceded by { , or whitespace */
    let d = 0;
    for (let j = 0; j < lit.length; j++) {
      const ch = lit[j];
      if (ch === '{' || ch === '(' || ch === '[') d++;
      else if (ch === '}' || ch === ')' || ch === ']') d--;
      if (d !== 1) continue;
      const k = /^([A-Za-z_$][\w$]*)\s*:/.exec(lit.slice(j));
      if (!k || !/[{,\s]/.test(lit[j - 1] || '')) continue;
      const rest = lit.slice(j + k[0].length);
      const val = /^\s*(true|false)\b/.exec(rest);
      raw[k[1]] = (val ? val[1] : rest.split(/[,\n}]/)[0].trim());
      opts[k[1]] = val ? val[1] === 'true' : ('__' + k[1] + '__');
      j += k[0].length - 1;
    }
    out.push({file, opts, raw, src: lit});
  }
  return out;
}

const sites = [...callSites(INDEX, 'index.html'), ...callSites(PUBLIC, 'public-form.html')];
ck('the product calls the one renderer from three places', sites.length === 3,
   sites.length + ' call sites: ' + sites.map(s => s.file + ' ' + JSON.stringify(s.raw)).join(' | '));

function surfaceNamed(file, wants) {
  const s = sites.filter(x => x.file === file && wants.every(k => k in x.opts));
  return s.length === 1 ? s[0] : null;
}
const CANVAS = surfaceNamed('index.html', ['editable']);
const PREVIEW = surfaceNamed('index.html', ['fill']);
const PAGE = surfaceNamed('public-form.html', ['fill']);
ck('…the builder’s canvas among them', !!CANVAS);
ck('…the builder’s preview among them', !!PREVIEW);
ck('…and the page a stranger fills in', !!PAGE);
if (!CANVAS || !PREVIEW || !PAGE) { console.log(`\n${pass} passed, ${fail} failed`); process.exit(1); }

/* The hazard this file exists for: two files, one program. index.html may
   pass `live:true` to a renderer that has never heard of `live` — which is
   exactly what a browser holding yesterday's cached form-paper.js was
   running — and every string test over either file alone still passes. */
const paperSkip = commentRanges(PAPER);
const reads = new Set([...PAPER.matchAll(/opts\.([A-Za-z_$][\w$]*)/g)]
  .filter(m => !inAny(paperSkip, m.index)).map(m => m[1]));
for (const s of sites)
  for (const k of Object.keys(s.opts))
    ck(`the renderer implements \`${k}\`, which ${s.file} asks for`, reads.has(k),
       'form-paper.js never reads opts.' + k);
for (const k of reads)
  ck(`…and \`${k}\`, which the renderer reads, is passed by somebody`,
     sites.some(s => k in s.opts), 'no shell passes opts.' + k);
/* The same agreement for the members, not just the options. */
for (const [file, src] of [['index.html', INDEX], ['public-form.html', PUBLIC]]) {
  const skip = commentRanges(src);
  for (const m of new Set([...src.matchAll(/FormPaper\.([A-Za-z_$][\w$]*)/g)]
      .filter(x => !inAny(skip, x.index)).map(x => x[1])))
    ck(`FormPaper.${m}, which ${file} calls, exists`, typeof FormPaper[m] !== 'undefined');
}

// ── the document: every kind of question the product supports ────────

const WHO = [{value: 3, label: 'דנה'}, {value: 4, label: 'אורי'}];
const CHOICES = [{value: 'א', label: 'א'}, {value: 'ב', label: 'ב'}];

/* type → what the respondent must find on the page. `multi` is a tick box
   per option, which is what a multi select and an אחראים question both are:
   a <select multiple> is the control nobody can work on a phone.

   `upload` is the one that is not the renderer's to decide alone. Uploading
   belongs to the HOST — it owns the address the bytes go to and the policy
   they are checked against — so a file question is a picker exactly where
   the surface says it wired one (opts.upload) and says why where it did
   not. A picker on a surface with nothing behind it would take a file, show
   nothing and send nothing, which is this file's whole subject. */
const KINDS = [
  {type: 'text',      el: 'input',    attr: 'text'},
  {type: 'long_text', el: 'textarea'},
  {type: 'number',    el: 'input',    attr: 'number'},
  {type: 'status',    el: 'select',   options: CHOICES},
  /* A priority is a labelled, board-defined vocabulary — the same shape as a
     status, and drawn by the same branch. It was missing from FILLABLE alone,
     so the question reached the page and drew the refusal meant for a column
     a form genuinely cannot collect. */
  {type: 'priority',  el: 'select',   options: CHOICES},
  {type: 'dropdown',  el: 'multi',    options: CHOICES},
  {type: 'checkbox',  el: 'input',    attr: 'checkbox'},
  {type: 'date',      el: 'input',    attr: 'date'},
  {type: 'phone',     el: 'input',    attr: 'tel'},
  {type: 'email',     el: 'input',    attr: 'email'},
  {type: 'files',     el: 'upload',   attr: 'file'},
  {type: 'people',    el: 'multi',    options: WHO},
];
ck('every type the renderer calls fillable is covered here',
   JSON.stringify([...FormPaper.FILLABLE].sort()) === JSON.stringify(KINDS.map(k => k.type).sort()),
   'FILLABLE: ' + FormPaper.FILLABLE.join(',') + '  covered: ' + KINDS.map(k => k.type).join(','));

const DOC = {design: {}, components: KINDS.map((k, i) => ({
  id: i + 1, kind: 'question', type: k.type, label: 'שאלה ' + k.type,
  description: 'הסבר', required: false, settings: {},
  ...(k.options ? {options: k.options} : {}),
}))};

/* One question's markup out of a rendered form. fv-blk is emitted only at
   the top of a block, so slicing on it cannot cut a control in half. */
function blocks(html) {
  const parts = html.split('<div class="fv-blk');
  const out = {};
  for (const p of parts.slice(1)) {
    const id = /id="fvb-(\d+)"/.exec(p);
    if (id) out[id[1]] = '<div class="fv-blk' + p;
  }
  return out;
}
const controls = b => [...b.matchAll(/<(input|textarea|select)\b([^>]*)>/g)]
  .map(m => ({tag: m[1], attrs: m[2], all: m[0]}));
const DEAD = [/\bdisabled\b/, /\breadonly\b/, /\binert\b/,
              /aria-disabled="true"/, /pointer-events\s*:\s*none/];

/* Each of the three, rendered with the options that surface really passes.

   There is no second mode here any more. All three call sites ask for live
   controls, so a `live: false` branch inside this function would be code no
   surface reaches — the renderer's drawing mode is a contract rather than a
   screen, and it is pinned as one, by itself, in section 4. What is asserted
   instead is the thing that was wrong: that the surface asks for a form that
   works, and that every control on it then does. */
function surface(name, site) {
  const html = FormPaper.html(DOC, site.opts);
  const bs = blocks(html);
  console.log(`\n── ${name} — ${site.file} ${JSON.stringify(site.raw)} ──`);
  ck(`${name}: asks the renderer for controls that work`,
     !!(site.opts.live || site.opts.fill), JSON.stringify(site.raw));
  ck('every question is drawn', Object.keys(bs).length === KINDS.length,
     Object.keys(bs).length + ' of ' + KINDS.length);

  KINDS.forEach((k, i) => {
    const b = bs[String(i + 1)] || '';
    const cs = controls(b);
    const tag = t => cs.filter(c => c.tag === t);
    const where = `${name}/${k.type}`;

    if (k.el === 'upload') {
      /* The one control the renderer does not decide alone. A picker where
         the host wired an upload; where it did not, a sentence that says so
         — and one that still carries the question's id, because collect()
         finds a question by that id and a REQUIRED file question has to be
         refused beside the field rather than by the server. */
      if (site.opts.upload) {
        ck(`${where}: a picker, because this surface wired one`,
           tag('input').length === 1 && tag('input')[0].attrs.includes('type="file"'),
           b.slice(0, 220));
      } else {
        ck(`${where}: no picker, because there is nowhere here to put a file`,
           !tag('input').length, b.slice(0, 220));
        ck(`${where}: …and it says why instead of looking broken`,
           /class="fv-in fv-files-off"[^>]*>\s*[^<]{12,}/.test(b), b.slice(0, 220));
        ck(`${where}: …still answering to the question's own id, so a required `
           + `one is refused beside the field and not by the server`,
           b.includes(`id="fa-${i + 1}"`), b.slice(0, 220));
      }
    } else if (k.el === 'multi') {
      ck(`${where}: a tick box per option, not a control nobody can work on a phone`,
         /class="fv-in fv-multi"/.test(b)
         && tag('input').length === k.options.length
         && tag('input').every(c => /type="checkbox"/.test(c.attrs)),
         b.slice(0, 260));
      ck(`${where}: each box carries its own value`,
         k.options.every(o => b.includes(`value="${o.value}"`)));
    } else if (k.el === 'textarea') {
      ck(`${where}: a <textarea>, so more than one line can be typed`,
         tag('textarea').length === 1 && !tag('input').length, b.slice(0, 200));
    } else if (k.el === 'select') {
      ck(`${where}: a <select> carrying its choices`,
         tag('select').length === 1
         && k.options.every(o => b.includes(`value="${o.value}"`)), b.slice(0, 220));
    } else {
      ck(`${where}: an <input type="${k.attr}">`,
         tag('input').length === 1 && tag('input')[0].attrs.includes(`type="${k.attr}"`),
         b.slice(0, 200));
    }

    /* and whether it can be used. A control that is there and dead is the
       bug this whole file is about — it looks exactly like a control. */
    for (const re of DEAD) {
      const hit = cs.filter(c => re.test(c.all));
      ck(`${where}: nothing on it is ${String(re)}`, !hit.length, (hit[0] || {}).all);
    }
    /* `for` only where there is something to point at: a tick list is a
       group of boxes and not one control, and `for` naming the <div> that
       holds them is ignored by every browser and every screen reader alike,
       so those are named through the group instead. */
    ck(`${where}: its label points at the control, so the label is a target too`,
       /class="fv-q-l" for="fa-/.test(b) || k.el === 'multi', b.slice(0, 160));
  });

  return html;
}

// ── 1 · the builder's canvas: live controls, and nothing that sends ──
/* It draws the local model. Typing into it saves nothing and sends nothing;
   what it must do is WORK, because trying your own form where you are
   building it is the first thing anybody does and was the one thing they
   could not do. */
const canvas = surface('קנבס העריכה', CANVAS);
ck('the canvas has no send button', !/id="fv-send"/.test(canvas));
ck('…and no error slot, because nothing is validated where nothing is sent',
   !/class="fv-err"/.test(canvas));
ck('…and a press still selects the question for the settings pane',
   (canvas.match(/FormEditor\.select\(/g) || []).length === KINDS.length);
ck('…and not one control on the whole canvas is disabled', !/\bdisabled\b/.test(canvas),
   (/.{0,80}\bdisabled\b.{0,80}/.exec(canvas) || [''])[0]);

// ── 2 · the builder's preview, and 3 · the page a stranger gets ──────
/* The same renderer in the same mode, and that is the point: a preview that
   is a second rendering of the form agrees with the published one by luck. */
const preview = surface('תצוגה מקדימה', PREVIEW);
const page = surface('הדף הציבורי', PAGE);

for (const [name, html] of [['תצוגה מקדימה', preview], ['הדף הציבורי', page]]) {
  ck(`${name}: there is a send button`, /id="fv-send"/.test(html));
  ck(`${name}: …and an error slot per question, beside the field`,
     (html.match(/class="fv-err"/g) || []).length === KINDS.length);
  ck(`${name}: …and nothing is selectable, because nobody is editing it`,
     !/FormEditor\.select\(/.test(html));
  ck(`${name}: …and not one control is disabled`, !/\bdisabled\b/.test(html),
     (/.{0,80}\bdisabled\b.{0,80}/.exec(html) || [''])[0]);
}

/* The two fill surfaces are the same drawing wherever the RENDERER decides,
   and they may differ only where the HOST does. Two things are the host's:
   the logo's address — the app's attachment route inside the app, the route
   a stranger may fetch on the public page — and whether an upload is wired.
   Handed the same answers to both, the renderer has to produce the same
   page, or a builder is checking something a respondent will not get. */
ck('the preview and the published page are one drawing, told the same things',
   FormPaper.html(DOC, {...PREVIEW.opts, upload: true}) === FormPaper.html(DOC, PAGE.opts),
   'the two fill surfaces differ by more than the host they are drawn in');
/* …and the one difference the builder actually sees is explained on screen.
   The preview's submit is a door that writes nothing, so a picker there
   would take a file, upload it to a record that is never created and leave
   it behind. The sentence is how that stops being a field that "does
   nothing" — the complaint this whole file exists for. */
ck('…and the difference is the file question, which the preview cannot host',
   /type="file"/.test(page) && !/type="file"/.test(preview));
ck('…which the preview says out loud rather than drawing a dead picker',
   /fv-files-off/.test(preview) && !/fv-files-off/.test(page));

// ── 4 · the third mode is still there: a drawing ─────────────────────
/* Nothing in the product asks for it today. It is the renderer's contract
   and the reason `live` had to exist at all, so it is pinned here rather
   than left to be discovered by whoever removes it. */
{
  const drawn = FormPaper.html(DOC, {editable: true});
  const bs = blocks(drawn);
  const every = Object.values(bs).flatMap(controls);
  ck('asked for a drawing, every control comes back switched off',
     every.length > 0 && every.every(c => /\bdisabled\b/.test(c.attrs)));
  ck('…and a greyed tick list says it is a drawing rather than a dead control',
     /class="fv-opt fv-opt-off"/.test(drawn));
  ck('…and it still has no send button', !/id="fv-send"/.test(drawn));
}

// ── 5 · אחראים with nobody to offer ──────────────────────────────────
/* The server decides per reader whether this question may have options at
   all (_form_people_options): a stranger on a public link gets none. An
   empty tick list is a box that does nothing when pressed, which is what
   this used to be, so the page says why instead. */
{
  const q = {id: 1, kind: 'question', type: 'people', label: 'אחראים', settings: {}, options: []};
  const none = FormPaper.html({design: {}, components: [q]}, PAGE.opts);
  ck('nobody to offer: the page says why rather than drawing an empty box',
     /class="fv-in fv-people"/.test(none) && /חבר בלוח/.test(none)
     && !/<input/.test(none.slice(none.indexOf('fv-people'))), none.slice(0, 240));
  const onCanvas = FormPaper.html({design: {}, components: [q]}, CANVAS.opts);
  ck('…and so does the canvas, which is reading the same answer',
     /class="fv-in fv-people"/.test(onCanvas) && !/<input/.test(
       onCanvas.slice(onCanvas.indexOf('fv-people'))));
}

// ── 6 · a column type a form cannot collect ──────────────────────────
/* On a fill surface it is refused in words. On the canvas it is drawn, so
   the builder can see what the question is — the refusal belongs where
   somebody is being asked to answer. */
{
  const odd = {design: {}, components: [
    {id: 1, kind: 'question', type: 'rating', label: 'דירוג', settings: {}}]};
  ck('a type a form cannot collect is refused on the page in words',
     /fv-unsupported/.test(FormPaper.html(odd, PAGE.opts)));
  ck('…and the canvas draws it instead of refusing it',
     !/fv-unsupported/.test(FormPaper.html(odd, CANVAS.opts)));
}

// ── 7 · what the person typed comes back out ─────────────────────────
/* collect() is the other half of a usable control: a field that takes a
   value and does not give it back is a field that does not work either. */
{
  /* Keyed by the question's TYPE and resolved to its id, not written out as
     numbers. The ids come from a KIND's position in the list, so a type added
     in the middle used to renumber every answer after it and the stub went on
     quietly handing the wrong value to the wrong question. */
  const ID = t => DOC.components.find(c => c.type === t).id;
  const by = {text: 'שורה', long_text: 'פסקה', number: '7', status: 'א',
              priority: 'א', checkbox: true, date: '2026-10-28',
              phone: '050-1234567', email: 'a@b.co', files: null};
  const vals = {}; for (const t in by) vals[ID(t)] = by[t];
  const ticked = {[ID('dropdown')]: [{value: 'ב'}], [ID('people')]: [{value: '4'}]};
  const MULTI = [ID('dropdown'), ID('people')];
  const root = {querySelector(sel) {
    const id = +sel.replace('#fa-', '');
    if (MULTI.indexOf(id) >= 0) return {
      classList: {contains: c => c === 'fv-multi'},
      querySelectorAll: () => ticked[id]};
    if (id === ID('files')) return {_tokens: [{token: 'tk'}]};
    if (id === ID('checkbox')) return {checked: true,
                                       classList: {contains: () => false}};
    return {value: vals[id] == null ? '' : vals[id], classList: {contains: () => false}};
  }};
  const got = FormPaper.collect(DOC, root);
  ck('every answered question comes back out of the form',
     Object.keys(got.answers).length === KINDS.length, JSON.stringify(got.answers));
  ck('…a number as a number', got.answers[ID('number')] === 7);
  ck('…a ticked box as true, not as nothing', got.answers[ID('checkbox')] === true);
  ck('…a multi select as its values', JSON.stringify(got.answers[ID('dropdown')]) === '["ב"]');
  ck('…a person as an id, which is a number', JSON.stringify(got.answers[ID('people')]) === '[4]');
  ck('…a file as the token the upload answered with',
     JSON.stringify(got.answers[ID('files')]) === '["tk"]');
  ck('…and nothing was refused', !got.bad.length && !got.missing.length,
     JSON.stringify(got.bad) + JSON.stringify(got.missing));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
