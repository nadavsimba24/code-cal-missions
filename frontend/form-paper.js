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
  /* The ten kinds of question the specification names. Anything else is a
     board column a form can display and not one it can collect — see
     inputHTML, which says so on the page rather than drawing a box that does
     nothing. */
  FILLABLE: ['text','long_text','number','status','dropdown',
             'checkbox','date','phone','email','files'],

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
    const pick = ed?` onclick="FormEditor.select(${c.id})"`:'';
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
    return `<div class="fv-blk fv-q${sel?' sel':''}${hidden?' hid':''}${gone?' gone':''}"
      id="fvb-${c.id}" data-id="${c.id}"${pick}>${grip}
      <label class="fv-q-l" ${opts.fill?`for="${id}"`:''}><span id="fvq-${c.id}-l">${
        fpEsc(c.label||'(ללא נוסח)')}</span>${
        c.required?'<span class="fv-req" aria-label="שדה חובה">*</span>':''}${
        hidden?'<span class="fv-hid-t">מוסתר</span>':''}${
        gone?'<span class="fv-hid-t fv-gone-t">השדה נמחק מהלוח</span>':''}</label>
      ${c.description?`<div class="fv-q-d" id="${id}-d">${fpEsc(c.description)}</div>`:''}
      ${this.inputHTML(c, opts)}
      ${opts.fill?`<div class="fv-err" id="${id}-e" role="alert" hidden></div>`:''}
    </div>`;
  },

  inputHTML(c, opts){
    opts = opts || {};
    const fill = !!opts.fill, type = c.type, ph = fpEsc(c.placeholder||'');
    const id = 'fa-' + c.id;
    // what every input carries in both modes, so the two cannot drift
    const A = `class="fv-in" id="${id}" data-q="${c.id}" data-type="${fpEsc(type||'')}"`
      + (c.required?' aria-required="true"':'')
      + (c.description?` aria-describedby="${id}-d"`:'')
      + (fill?'':' disabled');
    if(fill && this.FILLABLE.indexOf(type) < 0)
      return `<div class="fv-in fv-unsupported">שדה מסוג זה אינו נתמך במילוי טופס.</div>`;
    if(type === 'checkbox')
      return `<input type="checkbox" ${A.replace('class="fv-in"','class="fv-in fv-in-cb"')}>`;
    if(type === 'long_text')
      return `<textarea ${A} rows="3" placeholder="${ph}"></textarea>`;
    if(type === 'phone')
      return `<input ${A} type="tel" dir="ltr" placeholder="${ph}">`;
    if(type === 'files')
      return `<div class="fv-files" id="${id}-wrap">
        <input type="file" ${A} ${c.settings&&c.settings.multiple===false?'':'multiple'}>
        <div class="fv-files-list" id="${id}-list"></div></div>`;
    if(type === 'rating') return `<div class="fv-in fv-stars">★★★★★</div>`;
    if(type === 'people') return `<div class="fv-in fv-people">בחירת אנשים</div>`;
    const opt = c.options || [];
    /* Multi select is several values out of a plain list, and a <select
       multiple> is the control nobody can work on a phone. Checkboxes say
       what they are and are a thumb-sized target each. */
    if(type === 'dropdown' && opt.length)
      return `<div class="fv-in fv-multi" id="${id}" data-q="${c.id}" data-type="dropdown">${
        opt.map((o,i)=>`<label class="fv-opt"><input type="checkbox" ${fill?'':'disabled'}
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
        missing.push({id:c.id, label:c.label||''});
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
    if(t === 'dropdown' && (c.options||[]).length){
      const ok = (c.options||[]).map(o => String(o.value));
      if((Array.isArray(val)?val:[val]).some(v => ok.indexOf(String(v)) < 0))
        return 'אחת האפשרויות שנבחרו כבר אינה קיימת';
    }
    return '';
  },
};
