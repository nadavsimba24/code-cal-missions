/* ============ FormPaper — the one renderer ============

   The form as it is read: in the editor's middle pane, in its preview, and on
   the public page somebody fills it in on. One function, in one file loaded by
   both pages, because "the same display mechanism in the editor, in Preview
   and in the published form" is not something two renderers stay.

   It takes the shape the PUBLIC endpoint answers with — design + components,
   each component carrying its own type, options and settings — and nothing
   else. The editor normalises its working copy into that shape before calling
   (FormEditor.doc), which is what makes the editor a preview of the published
   page rather than a drawing that resembles one.

   Three modes, one renderer:
     editable   the builder's: selection, drag handles, hidden questions shown
     (neither)  a preview: exactly what a respondent sees, and not fillable
     fill       the public page: the same, with the inputs switched on

   And two switches that are about what the HOST page can do rather than
   about what the form is: `live` (the controls work, see inputHTML) and
   `upload` (there is somewhere for a file to go, see the files branch).

   Its own `esc`, because it is loaded beside a page that has one and beside a
   page that does not. */
const fpEsc = s => (s == null ? '' : String(s))
  .replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const FormPaper = {
  /* The sizes a form may be, by name. No free sizes — "אין להוסיף … גדלים
     חופשיים" — so a form cannot hold a number the stylesheet has no rule for. */
  SIZES: {small:'13px', medium:'15px', large:'17px'},
  /* A heading's level, as a size relative to the form's own. Three, named,
     for the same reason. */
  LEVELS: {1:'1.45em', 2:'1.18em', 3:'1em'},
  /* The kinds of question the specification names. Anything else is a board
     column a form can display and not one it can collect — see inputHTML,
     which says so on the page rather than drawing a box that does nothing.

     `priority` was missing from this list and from nothing else. The server
     offers it as one of the five built-in fields the plan names, serves it
     with the board's own priority vocabulary, and checks a submitted answer
     against that vocabulary; the two places in this file that render a
     vocabulary and validate against one both already name it beside
     `status`. Only this list did not — so a priority question reached the
     page and drew "שדה מסוג זה אינו נתמך במילוי טופס" over a question the
     whole rest of the stack was ready to answer. */
  FILLABLE: ['text','long_text','number','status','priority','dropdown',
             'checkbox','date','phone','email','files','people'],

  /* The product's own font stack and nothing else — Figtree for the Latin,
     Rubik for the Hebrew (CONVENTIONS.md). A form picks its size and its
     alignment; it does not pick a typeface. */
  styleAttr(d){
    d = d || {};
    const align = {right:'right',center:'center',left:'left'}[d.text_align] || 'right';
    return `--fv-accent:${fpEsc(d.theme_color||'#0073ea')};`
      + `--fv-paper:${fpEsc(d.background_color||'#ffffff')};`
      + `color:${fpEsc(d.text_color||'#323338')};`
      + `background:${fpEsc(d.background_color||'#ffffff')};`
      + `text-align:${align};`
      + `direction:${align==='left'?'ltr':'rtl'};`
      + `font-size:${this.SIZES[d.font_size]||this.SIZES.medium};`
      + `font-family:var(--font)`;
  },
  /* normal | bold | italic, and nothing a stylesheet has to be written for. */
  emphasis(st){
    const s = (st||{}).style;
    return s==='bold' ? 'font-weight:800' : s==='italic' ? 'font-style:italic' : '';
  },

  html(doc, opts){
    opts = opts || {};
    const d = (doc && doc.design) || {}, cs = (doc && doc.components) || [];
    const body = cs.length
      ? cs.map(c => this.blockHTML(c, opts)).join('')
      : `<div class="fv-empty">${opts.editable
          ? 'הוסיפו שאלה כדי לראות את הטופס.' : 'אין שאלות מוצגות בטופס.'}</div>`;
    /* The logo's address is the caller's to give: inside the app it is the
       ordinary attachment route, and on the public page it is the one the
       respondent is allowed to fetch. The renderer does not decide who is
       reading it. */
    const src = d.logo_token
      ? (opts.logoSrc || ('/api/files/' + encodeURIComponent(d.logo_token))) : '';
    return `<div class="fv-paper" style="${this.styleAttr(d)}">
      ${src?`<div class="fv-logo-wrap"><img class="fv-logo" src="${fpEsc(src)}" alt=""></div>`:''}
      <div class="fv-paper-h">
        <div class="fv-paper-t">${fpEsc(d.display_title||opts.fallbackTitle||'')}</div>
        ${d.display_description?`<div class="fv-paper-d">${fpEsc(d.display_description)}</div>`:''}
      </div>
      <div id="fv-blocks" class="fv-blocks">${body}</div>
      <div class="fv-paper-f">${opts.fill
        ? `<button type="button" class="fv-submit" id="fv-send">${fpEsc(d.submit_label||'שליחה')}</button>`
        : `<span class="fv-submit">${fpEsc(d.submit_label||'שליחה')}</span>`}</div>
      ${d.show_branding===false?''
        :`<div class="fv-brand">מופעל באמצעות <b>Missions</b></div>`}
    </div>`;
  },

  blockHTML(c, opts){
    const ed = !!opts.editable, sel = ed && opts.sel === c.id;
    const grip = ed?'<i class="fa-solid fa-grip-vertical fv-bgrip" aria-hidden="true"></i>':'';
    /* The event travels with the id. The editor needs to know WHERE inside
       the block the click landed: a press on a control selects the question
       and must never unselect it, because the second press inside a text
       field is not a request to close the settings pane. See
       FormEditor.select, which is also where the far worse half of this
       used to live. */
    const pick = ed?` onclick="FormEditor.select(${c.id},event)"`:'';
    if(c.kind !== 'question'){
      const empty = !(c.content||'').trim();
      const txt = empty ? (c.kind==='heading'?'(כותרת ריקה)':'(טקסט ריק)') : fpEsc(c.content);
      const em = this.emphasis(c.settings);
      const lvl = (c.settings||{}).level || 2;
      const inner = c.kind==='heading'
        ? `<h3 style="font-size:${this.LEVELS[lvl]||this.LEVELS[2]};${em}">${txt}</h3>`
        : `<p style="${em}">${txt}</p>`;
      return `<div class="fv-blk fv-blk-${c.kind}${sel?' sel':''}${empty?' fv-blk-empty':''}"
        id="fvb-${c.id}" data-id="${c.id}"${pick}>${grip}${inner}</div>`;
    }
    const hidden = ed && c.hidden, gone = ed && c.gone;
    const id = 'fa-' + c.id;
    /* `for` only where there is something for it to point AT.

       אחראים and בחירה מרובה are a list of boxes and not one control, so
       what carries the question's id is a <div>. `for` naming a <div> is
       ignored outright — by every browser and by every screen reader — so
       pressing the word "אחראים" did nothing at all, and the question went
       unnamed to anybody listening. Those two are named through the group
       instead (see inputHTML), and the label stays a label. */
    const grp = this.isGroup(c);
    return `<div class="fv-blk fv-q${sel?' sel':''}${hidden?' hid':''}${gone?' gone':''}"
      id="fvb-${c.id}" data-id="${c.id}"${pick}>${grip}
      <label class="fv-q-l" ${(opts.fill||opts.live)&&!grp?`for="${id}"`:''}><span id="fvq-${c.id}-l">${
        fpEsc(c.label||'(ללא נוסח)')}</span>${
        c.required?'<span class="fv-req" aria-label="שדה חובה">*</span>':''}${
        hidden?'<span class="fv-hid-t">מוסתר</span>':''}${
        gone?'<span class="fv-hid-t fv-gone-t">השדה נמחק מהלוח</span>':''}</label>
      ${c.description?`<div class="fv-q-d" id="${id}-d">${fpEsc(c.description)}</div>`:''}
      ${this.inputHTML(c, opts)}
      ${opts.fill?`<div class="fv-err" id="${id}-e" role="alert" hidden></div>`:''}
    </div>`;
  },

  /* Is this question answered by a LIST of controls rather than by one?

     אחראים always is: it draws a tick per person, and when the reader may
     not be told who the people are it draws a sentence instead — neither of
     which is a thing a <label for> can address. בחירה מרובה is one whenever
     it has a vocabulary to draw; without one it falls through to a <select>,
     which is a single control and keeps its label. */
  isGroup(c){
    const t = c && c.type;
    return t === 'people' || (t === 'dropdown' && ((c.options||[]).length > 0));
  },

  inputHTML(c, opts){
    opts = opts || {};
    /* Two different questions, and they used to be one.

       `fill` is "this page IS a form": it has a send button, somewhere to
       put an error beside each question, and a refusal for a column type a
       form cannot collect at all.

       `live` is "these controls work". The builder's canvas sets it, and
       nothing there is sent anywhere — it is how somebody tries their own
       form where they are building it. Keying the controls off `fill` alone
       meant the canvas was a picture of a form in which nothing could be
       pressed: not a date, not a tick, not a line of text. Every one of
       those was reported as broken, which is what it looked like.

       A click still reaches the block and still selects the question — an
       input does not swallow what it does not handle, so filling and
       selecting are the same gesture rather than rivals for it. */
    const live = !!opts.fill || !!opts.live;
    const fill = !!opts.fill, type = c.type, ph = fpEsc(c.placeholder||'');
    const id = 'fa-' + c.id;
    // what every input carries in both modes, so the two cannot drift
    const A = `class="fv-in" id="${id}" data-q="${c.id}" data-type="${fpEsc(type||'')}"`
      + (c.required?' aria-required="true"':'')
      + (c.description?` aria-describedby="${id}-d"`:'')
      + (live?'':' disabled');
    if(fill && this.FILLABLE.indexOf(type) < 0)
      return `<div class="fv-in fv-unsupported">שדה מסוג זה אינו נתמך במילוי טופס.</div>`;
    if(type === 'checkbox')
      return `<input type="checkbox" ${A.replace('class="fv-in"','class="fv-in fv-in-cb"')}>`;
    if(type === 'long_text')
      return `<textarea ${A} rows="3" placeholder="${ph}"></textarea>`;
    if(type === 'phone')
      return `<input ${A} type="tel" dir="ltr" placeholder="${ph}">`;
    /* A file question is a picker only where something is actually wired to
       take the file. Uploading belongs to the HOST page — it owns the
       address the bytes go to and the policy they are checked against — so
       the renderer is TOLD whether that wiring exists rather than inferring
       it from `fill`.

       The published page wires it and says so (public-form.html, wireFiles).
       The editor has no upload of its own: there is no `_tokens` anywhere in
       index.html, and the preview's submit is a door that writes nothing, so
       a picker on the canvas would take a file, show nothing, send nothing
       and leave an unclaimed upload behind. A control that does nothing is
       the whole complaint this screen exists to answer, so it says what it
       is instead.

       The sentence carries the question's id and not just an explanation:
       collect() finds a question by that id, so a REQUIRED file question is
       reported beside the field as one that cannot be answered here, rather
       than passing the page's own check and coming back as a refusal from
       the server. tabindex, because the page moves the focus to the first
       thing it complains about and a plain <div> cannot take it. */
    if(type === 'files')
      return `<div class="fv-files" id="${id}-wrap">${opts.upload
        ? `<input type="file" ${A} ${c.settings&&c.settings.multiple===false?'':'multiple'}>`
        : `<div class="fv-in fv-files-off" id="${id}" data-q="${c.id}" data-type="files"
             tabindex="-1"${c.description?` aria-describedby="${id}-d"`:''}>${live
             ? 'צירוף קבצים אפשרי בטופס המפורסם בלבד — כאן אין לקובץ לאן לעלות.'
             : 'צירוף קבצים'}</div>`}
        <div class="fv-files-list" id="${id}-list"></div></div>`;
    if(type === 'rating') return `<div class="fv-in fv-stars">★★★★★</div>`;
    /* אחראים. The same tick-list the multi select is, and for the same
       reason: several values out of a plain list, each a thumb-sized target,
       nothing the browser draws for us.

       The list is whoever the SERVER was willing to name to this particular
       reader (_form_people_options) — so it is empty for a stranger on a
       public link, and then the page says why rather than drawing an empty
       box. It used to always be empty and always be a box: that is the
       field that did nothing when you clicked it. */
    if(type === 'people'){
      const who = c.options || [];
      /* Nobody to tick, and the sentence carries the question's id anyway.

         It used to carry none, and collect() looks a question up by exactly
         that id: it found nothing, returned before the `required` check, and
         a required אחראים that this particular reader may not answer sailed
         through the page's own validation and came back as a refusal from
         the server — the precise opposite of what the comment on collect
         promises. The id is what lets it be reported beside the field, with
         the reason, before anything crosses the wire. tabindex because the
         page moves the focus to the first thing it complains about, and
         focus() on a plain <div> does nothing at all. */
      if(!who.length)
        return `<div class="fv-in fv-people" id="${id}" data-q="${c.id}" data-type="people"
          tabindex="-1"${c.description?` aria-describedby="${id}-d"`:''}>${live
          ? 'בחירת אחראים פתוחה למי שחבר בלוח — לא ניתן לענות על השאלה הזאת כאן.'
          : 'בחירת אחראים'}</div>`;
      return `<div class="fv-in fv-multi" id="${id}" data-q="${c.id}" data-type="people"
        role="group" aria-labelledby="fvq-${c.id}-l"${
        c.required?' aria-required="true"':''}${
        c.description?` aria-describedby="${id}-d"`:''}>${
        who.map(o=>`<label class="fv-opt${live?'':' fv-opt-off'}"><input type="checkbox" ${live?'':'disabled'}
          value="${fpEsc(o.value)}"> ${fpEsc(o.label)}</label>`).join('')}</div>`;
    }
    const opt = c.options || [];
    /* Multi select is several values out of a plain list, and a <select
       multiple> is the control nobody can work on a phone. Checkboxes say
       what they are and are a thumb-sized target each.

       It carries the same three attributes the אחראים group above carries,
       and for the same reason: both are one control made of many boxes, so
       whatever is true of one list of ticks is true of the other. They
       drifted once, and בחירה מרובה quietly lost its "required" and its
       description to anybody listening rather than looking. */
    if(type === 'dropdown' && opt.length)
      return `<div class="fv-in fv-multi" id="${id}" data-q="${c.id}" data-type="dropdown"
        role="group" aria-labelledby="fvq-${c.id}-l"${
        c.required?' aria-required="true"':''}${
        c.description?` aria-describedby="${id}-d"`:''}>${
        opt.map((o,i)=>`<label class="fv-opt${live?'':' fv-opt-off'}"><input type="checkbox" ${live?'':'disabled'}
          value="${fpEsc(o.value)}"> ${fpEsc(o.label)}</label>`).join('')}</div>`;
    if(opt.length)
      return `<select ${A}><option value="">—</option>${
        opt.map(o=>`<option value="${fpEsc(o.value)}">${fpEsc(o.label)}</option>`).join('')}</select>`;
    if(type==='status'||type==='priority'||type==='dropdown')
      return `<select ${A}><option value="">—</option></select>`;
    const t = {date:'date', number:'number', email:'email'}[type] || 'text';
    return `<input ${A} type="${t}" placeholder="${ph}">`;
  },

  /* What the person typed, keyed by component id — the only identifier the
     respondent was ever given. Returns {answers, missing}: everything, and
     the labels of the required questions that are still empty. The server
     checks the same thing again and is the one that decides; this is so
     somebody is told before the round trip, not instead of it. */
  collect(doc, root){
    const answers = {}, missing = [], bad = [];
    (doc.components||[]).forEach(c=>{
      if(c.kind !== 'question') return;
      const el = root.querySelector('#fa-' + c.id);
      if(!el) return;
      let val = null;
      const type = c.type;
      /* A box that is not ticked is `false`, which is an ANSWER. Sending
         null instead is how "no" became "left blank": the cell ended up
         absent rather than false. Same reasoning for 0 below. */
      if(type === 'checkbox') val = !!el.checked;
      else if(type === 'dropdown' && el.classList.contains('fv-multi')){
        val = [...el.querySelectorAll('input:checked')].map(x=>x.value);
        if(!val.length) val = null;
      }
      /* People travel as ids and not as names, so they are numbers here —
         the server matches them against _can_be_assigned, which compares to
         an integer column. A people question nobody may answer draws no
         boxes at all, and falls out of this as null: if it was required the
         person is told beside the field, rather than by a refusal after the
         round trip. */
      else if(type === 'people'){
        /* querySelectorAll and not a check for the boxes first: where there
           are none the element IS the explanatory sentence, it answers with
           an empty list, and that falls out below as null — which is what
           makes it reportable as missing instead of invisible. */
        val = [...el.querySelectorAll('input:checked')].map(x=>Number(x.value));
        if(!val.length) val = null;
      }
      else if(type === 'files') val = (el._tokens && el._tokens.length)
        ? el._tokens.map(t=>t.token) : null;
      else if(type === 'number') val = el.value === '' ? null : Number(el.value);
      else val = el.value || null;
      /* Emptiness spelled out, never inferred from truthiness: `0` and
         `false` are values, and `if(!val)` would call both of them blank. */
      const empty = val === null || val === undefined
        || (typeof val === 'string' && !val.trim())
        || (Array.isArray(val) && !val.length);
      /* A required checkbox is a box that has to be ticked. An unticked one
         is `false` — an answer, and the wrong one — so it is refused by its
         own rule rather than by being mistaken for nothing. */
      if(c.required && (empty || (type === 'checkbox' && val === false))){
        missing.push({id:c.id, label:c.label||'', why:this.cannotAnswer(el)});
        return;
      }
      if(!empty){
        const why = this.badValue(c, val);
        if(why){ bad.push({id:c.id, label:c.label||'', why}); return; }
        answers[String(c.id)] = val;
      }
    });
    return {answers, missing, bad};
  },

  /* Why this required question could not be answered AT ALL, as against
     merely not having been — '' when it simply was not.

     Two questions are drawn as a sentence rather than as a control: אחראים
     where the reader may not be told who the people are, and a file question
     on a page with nothing wired to take an upload. "שדה חובה" beside a
     thing there is no way to fill is an instruction nobody can follow, so
     the reason is said instead. Read off the element the renderer drew,
     because the element is what knows which of the two shapes it became. */
  cannotAnswer(el){
    const cl = el && el.classList;
    if(!cl || !cl.contains) return '';
    if(cl.contains('fv-people')) return 'לא ניתן לבחור אחראים בטופס הזה';
    if(cl.contains('fv-files-off')) return 'אפשר לצרף קבצים בטופס המפורסם בלבד';
    return '';
  },

  /* Why this value is not one the field can take, or '' if it is.

     A courtesy and not the rule: every one of these runs again on the
     server, against the COLUMN rather than against what the page was told,
     and that is the one that decides. This exists so somebody is told before
     the round trip and beside the field, not instead of being told. */
  badValue(c, val){
    const t = c.type;
    if(t === 'email' && !/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(String(val)))
      return 'כתובת דוא"ל לא תקינה';
    if(t === 'phone'){
      const v = String(val);
      if(!/^[0-9+()\-. ]{6,24}$/.test(v) || (v.match(/\d/g)||[]).length < 6)
        return 'מספר טלפון לא תקין';
    }
    if(t === 'number' && !isFinite(Number(val))) return 'נדרש מספר';
    if(t === 'date'){
      if(isNaN(new Date(String(val)).getTime())) return 'תאריך לא תקין';
      const s = c.settings || {};
      if(s.min && String(val) < String(s.min)) return 'התאריך מוקדם מ‎-' + s.min;
      if(s.max && String(val) > String(s.max)) return 'התאריך מאוחר מ‎-' + s.max;
    }
    /* A value that is not one of the options can only come from a page gone
       stale, or from somebody editing it. The server refuses it either way;
       saying so here is faster and lands beside the field. */
    if((t === 'status' || t === 'priority') && (c.options||[]).length
        && !(c.options||[]).some(o => String(o.value) === String(val)))
      return 'האפשרות שנבחרה כבר אינה קיימת';
    if((t === 'dropdown' || t === 'people') && (c.options||[]).length){
      const ok = (c.options||[]).map(o => String(o.value));
      if((Array.isArray(val)?val:[val]).some(v => ok.indexOf(String(v)) < 0))
        return 'אחת האפשרויות שנבחרו כבר אינה קיימת';
    }
    return '';
  },
};
