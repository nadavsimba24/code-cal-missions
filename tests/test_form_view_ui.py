"""תצוגת טופס במנגנון התצוגות — "+ הוספת תצוגה", הטאב, העורך, והדרך חזרה.

A form is a view of the board. That sentence is the whole feature, and most
of it is wiring rather than drawing: the "+" offers it beside a table, the
strip carries it by the name somebody gave it, clicking it opens an editor
instead of applying a cut, and leaving it puts the board back.

The drawing half runs under node against the real functions pulled out of
index.html — tests/frontend/form_view.mjs. The wiring half is asserted here,
on the source, because the three places it lives in (Views.apply, Views.leave,
renderView) are reached through objects too large to stand up in a harness and
too important to leave unpinned.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "form_view.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _method(obj, name):
    """One method's source out of one named object literal."""
    o = re.search(rf"^const {obj}\s*=\s*{{", SRC, re.M)
    assert o, f"const {obj} moved"
    i, depth = SRC.index("{", o.start()), 0
    for j in range(i, len(SRC)):
        if SRC[j] == "{":
            depth += 1
        elif SRC[j] == "}":
            depth -= 1
            if not depth:
                span = SRC[o.start():j + 1]
                break
    m = re.search(rf"^  (?:async )?{name}\(", span, re.M)
    assert m, f"{obj}.{name} moved"
    i, depth = span.index("{", m.start()), 0
    for j in range(i, len(span)):
        if span[j] == "{":
            depth += 1
        elif span[j] == "}":
            depth -= 1
            if not depth:
                return span[m.start():j + 1]
    raise AssertionError("unterminated " + name)


def test_the_form_view_ui_behaves():
    """The harness: the menu, the editor, two forms, the tab, the way back."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


# ── the wiring ───────────────────────────────────────────────────────

def test_opening_a_form_view_opens_its_editor_and_not_a_cut():
    """A form has no filters. Applying one as a cut would clear the board's."""
    body = _method("Views", "apply")
    assert "v.kind==='form'" in body, "Views.apply does not recognise a form"
    assert "FormEditor.open(" in body, "a form row does not open the editor"
    i = body.index("v.kind==='form'")
    assert "const c=v.filters" in body and body.index("const c=v.filters") > i, \
        "a form reaches the cut-restoring code"
    assert "return;" in body[i:body.index("const c=v.filters")], \
        "the form branch does not stop before the cut is applied"


def test_leaving_a_view_leaves_an_open_form_too():
    body = _method("Views", "leave")
    assert "FormEditor.isOpen()" in body and "FormEditor.close()" in body, \
        "clicking a board view while a form is open leaves the form on screen"


def test_the_editor_is_drawn_instead_of_the_board():
    m = re.search(r"function renderView\(\)\{(.{0,2000})", SRC, re.S)
    assert m, "renderView moved"
    head = m.group(1)
    assert "FormEditor.isOpen()" in head and "FormEditor.paint(el)" in head, \
        "the form editor is not drawn from renderView"
    assert head.index("FormEditor.paint(el)") < head.index("el.innerHTML=''"), \
        "the board is torn down before the form short-circuits it"


def test_a_form_tab_offers_only_what_the_server_accepts():
    """Lock, pin and duplicate are written through the view endpoint, which
    refuses a form. An action that would be refused is not drawn."""
    body = _method("Views", "actionsFor")
    assert "v.kind==='form'" in body, "a form's tab menu is the cut's menu"
    i = body.index("v.kind==='form'")
    # the form branch alone — up to where the cut's own list resumes
    tail = body[i:body.index("if(v.can_edit) out.push", i)]
    assert "'rename'" in tail and "'delete'" in tail, "a form cannot be renamed or deleted"
    assert "duplicate" not in tail and "lock" not in tail and "pin" not in tail, \
        "a form's menu offers an action the server refuses"


def test_renaming_and_deleting_a_form_go_through_the_form_endpoint():
    save, dele = _method("Views", "save"), _method("Views", "del")
    assert "/api/forms/'+row.form_id" in save, "a form is renamed through the view endpoint"
    assert "/api/forms/'+v.form_id" in dele, "a form is deleted through the view endpoint"


def test_the_add_view_menu_offers_a_form():
    body = re.search(r"function renderAddViewPop\(\)\{(.*?)\n\}", SRC, re.S).group(1)
    assert "FormEditor.create()" in body, "the + menu does not offer a form"
    assert "mayAdd" in body, "the form row is offered to people who may not add one"


def test_the_board_setting_that_held_the_old_form_is_gone():
    """One form per board, four flags per field, rebuilt from the live columns
    on every open. Replaced, not kept beside the new one."""
    for dead in ("toggleBoardForms", "st.board.form", "openForms(", "formSchema("):
        assert dead not in SRC, f"the old form mechanism is still here: {dead}"


def _editor():
    """The FormEditor object's source, by its braces."""
    i = SRC.index("const FormEditor={")
    j, depth = SRC.index("{", i), 0
    for k in range(j, len(SRC)):
        if SRC[k] == "{":
            depth += 1
        elif SRC[k] == "}":
            depth -= 1
            if not depth:
                return SRC[i:k + 1]
    raise AssertionError("FormEditor unterminated")


def test_the_editor_is_hebrew_and_rtl():
    block = _editor()
    for word in ("חזרה ללוח", "רכיבי הטופס", "מסך הצלחה", "טוען את הטופס", "נסו שוב"):
        assert word in block, f"missing Hebrew: {word}"
    assert "fa-arrow-right" in block and "fa-arrow-left" not in block, \
        "the back arrow points the LTR way"
    assert 'aria-label="שם התצוגה"' in block, "the name field is unlabelled"


# ── המבנה: סרגל, Outline, WYSIWYG, הגדרות רכיב ──────────────────────

def test_the_editor_has_its_four_parts():
    block = _editor()
    for part, mark in (("a top bar", 'class="fv-bar"'),
                       ("an outline", 'class="fv-outline"'),
                       ("a canvas", 'class="fv-canvas"'),
                       ("a settings pane", 'class="fv-inspect"')):
        assert mark in block, f"the editor has no {part}"
    # the outline is drawn first, so in an RTL page it sits on the right
    assert block.index('class="fv-outline"') < block.index('class="fv-canvas"') \
        < block.index('class="fv-inspect"'), "the panes are in the wrong order for RTL"


def test_the_top_bar_carries_everything_it_was_asked_to():
    block = _editor()
    i = block.index("barHTML(){")
    bar = block[i:block.index("outlineHTML(){", i)]
    for what, mark in (("the view name", 'id="fv-name"'),
                       ("a way back", "FormEditor.close()"),
                       ("a preview", "FormEditor.togglePreview()"),
                       ("settings", "fa-sliders"),
                       ("publish and share", "FormEditor.share()"),
                       ("a save indicator", 'id="fv-save"')):
        assert mark in bar, f"the top bar is missing {what}"
    assert 'aria-live="polite"' in bar, "the save state is not announced to a screen reader"


def test_the_canvas_previews_from_the_public_projection():
    """What the preview shows has to BE what the respondent gets, not a
    second rendering of it that agrees by luck."""
    block = _editor()
    assert "/preview'" in block, "the preview does not ask the server for the public form"
    assert "this.pub" in block, "the public answer is not what the canvas draws"


# ── Autosave ─────────────────────────────────────────────────────────

def test_a_save_is_debounced_and_single_flight():
    block = _editor()
    assert "FORM_AUTOSAVE_MS" in SRC and "setTimeout(()=>this.flush()" in block, \
        "edits are not debounced"
    flush = block[block.index("async flush()"):]
    assert "if(s.inflight) return;" in flush, \
        "two saves can be in the air at once, and then their order is the network's to decide"


def test_an_older_answer_cannot_overwrite_a_newer_edit():
    """The rule Paged.load already follows, applied to writes."""
    block = _editor()
    assert "mine<s.acked" in block, "an answer older than one already seen is not dropped"
    merge = block[block.index("mergeForm(f, fid)"):]
    assert "if(k in pend) return;" in merge, \
        "a save's answer overwrites fields edited since it was sent"


def test_a_failed_save_keeps_the_work_and_says_so():
    block = _editor()
    flush = block[block.index("async flush()"):block.index("async retry()")]
    assert "catch(e)" in flush and "s.state='error'" in flush, "a failed save is not reported"
    caught = flush[flush.index("catch(e)"):]
    # the failed batch goes back UNDER anything that arrived since, so a field
    # edited again while the save was failing keeps the newer value
    assert "Object.assign({}, form, s.form)" in caught, \
        "a failed save drops the fields it was carrying, or puts them back over newer ones"
    assert "s.state='saved'" not in caught, "a failure can still end up reading as saved"


def test_the_save_indicator_has_all_four_states():
    assert "FORM_SAVE_HE" in SRC
    i = SRC.index("const FORM_SAVE_HE")
    line = SRC[i:SRC.index("}", i)]
    for state in ("pending", "saving", "saved", "error"):
        assert state in line, f"the indicator cannot say {state}"


def test_typing_does_not_repaint_the_pane_it_is_typed_into():
    """A full render on every keystroke takes the focus out of the field."""
    block = _editor()
    bar = block[block.index("paintBar(){"):block.index("html(){")]
    assert "getElementById('fv-save')" in bar, "the indicator is not updated on its own"
    assert "renderView()" not in bar, "updating the indicator repaints the whole editor"
    touch = block[block.index("touch(){"):block.index("async flushNow()")]
    assert "renderView()" not in touch, "every keystroke repaints the editor"


def test_leaving_with_unsaved_work_is_not_silent():
    block = _editor()
    close = block[block.index("async close()"):block.index("leave(){")]
    assert "await this.flush()" in close, "leaving does not try to save first"
    assert "askConfirm" in close, "leaving with a failed save says nothing"
    assert "FormEditor" in SRC[SRC.index("beforeunload"):SRC.index("beforeunload") + 300], \
        "a refresh with unsaved work is not caught"


# ── רכיבי תוכן והסדר ─────────────────────────────────────────────────

def test_one_order_is_dragged_from_two_places():
    """The outline and the paper are the same list drawn twice."""
    block = _editor()
    sort = block[block.index("attachSort(){"):block.index("css(){")]
    assert "'fv-list'" in sort and "'fv-blocks'" in sort, \
        "only one of the two lists can be dragged"
    assert sort.count("sortableOn(") == 1, \
        "two wirings of the same thing will disagree the first time either moves"
    assert "this.reorder(" in sort, "a drag does not go through the one reorder"
    assert "if(this.preview) return;" in sort, "the respondent's form is draggable"


def test_the_two_views_are_drawn_from_the_one_array():
    """Not patched up afterwards — redrawn, both of them, from components."""
    block = _editor()
    reorder = block[block.index("async reorder(order)"):block.index("async setStatus")]
    assert "this.form.components=" in reorder and "renderView()" in reorder, \
        "a reorder does not redraw from the model"


def test_a_content_block_carries_no_field_settings():
    block = _editor()
    i = block.index("inspectComp(c){")
    comp = block[i:block.index("setVisible(cid, on){")]
    # the content branch: from the test for it, to where the question's own
    # settings start (fv-bound names the board field, which only a question has)
    head = comp[comp.index("if(c.kind!=='question')"):comp.index("fv-bound")]
    assert "fv-c-content" in head, "a content block cannot be edited at all"
    assert "required" not in head and "field_key" not in head, \
        "a content block is offered question settings"


def test_typing_into_one_block_reaches_that_block():
    """`.fv-blk-heading` is every heading on the page; the id is this one."""
    block = _editor()
    sync = block[block.index("syncLabel(cid){"):block.index("inspectForm(){")]
    assert "getElementById('fvb-'+cid)" in sync, \
        "the canvas is updated by class, so two headings share one"


# ── עיצוב: מנגנון תצוגה אחד, וקבוצות סגורות ─────────────────────────

def _paper():
    """The renderer is its own file now — loaded by the editor and by the
    public fill page, which is what makes "one display mechanism" true."""
    return (ROOT / "frontend" / "form-paper.js").read_text(encoding="utf-8")


def test_one_renderer_draws_the_editor_the_preview_and_the_published_form():
    paper, editor = _paper(), _editor()
    canvas = editor[editor.index("canvasHTML(){"):editor.index("optionsFor(key, type){")]
    assert canvas.count("FormPaper.html(") == 2, \
        "the editor and the preview are not drawn by the same function"
    assert "this.doc()" in canvas, \
        "the editor draws from its own shape instead of the published one"
    # the editor's working copy is normalised INTO the published shape
    doc = editor[editor.index("doc(){"):editor.index("canvasHTML(){")]
    for k in ("type:", "options:", "settings:"):
        assert k in doc, f"doc() does not resolve {k} — the two shapes differ"


def test_the_design_choices_are_closed_sets_in_the_renderer_too():
    paper = _paper()
    for name in ("SIZES", "LEVELS"):
        assert name + ": {" in paper or name + ":{" in paper, \
            f"{name} is not a named set"
    assert "var(--font)" in paper, "the form picks a typeface of its own"
    # three sizes, three levels — no arithmetic on a number from the form
    assert paper.count("small:") == 1 and paper.count("large:") == 1
    assert "px'" in paper and "em'" in paper
    # …and it is loaded rather than copied, in both places
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "public-form.html").read_text(encoding="utf-8")
    assert 'src="form-paper.js"' in index and 'src="form-paper.js"' in page


def test_the_form_settings_pane_offers_only_what_the_spec_allows():
    block = _editor()
    pane = block[block.index("inspectForm(){"):block.index("repaint(){")]
    for what, mark in (("a title", 'id="fv-dt"'), ("a description", 'id="fv-dd"'),
                       ("a logo", "fv-logo-in"), ("a primary colour", 'id="fv-tc"'),
                       ("a background colour", 'id="fv-bc"'),
                       ("a submit label", 'id="fv-sb"'),
                       ("a text size", 'id="fv-fs"'), ("an alignment", 'id="fv-al"')):
        assert mark in pane, f"the settings pane is missing {what}"
    assert "font_family" not in pane, "a free font choice is offered"
    assert "custom_css" not in pane and "style=\\\"" not in pane


def test_taking_the_branding_off_is_offered_only_to_the_entitled():
    pane = _editor()
    pane = pane[pane.index("inspectForm(){"):pane.index("repaint(){")]
    assert "can_hide_branding" in pane, "the switch is drawn regardless of entitlement"
    assert "נדרשת הרשאה" in pane, "somebody who may not is not told why"


def test_a_design_change_repaints_the_paper_and_not_the_field_being_typed_in():
    block = _editor()
    rep = block[block.index("repaint(){"):block.index("async uploadLogo(input)")]
    assert "querySelector('.fv-canvas')" in rep, "a design change repaints everything"
    assert "canvasHTML()" in rep


def test_the_editor_survives_a_narrow_screen():
    i = SRC.index("const FormEditor={")
    css = SRC[i:SRC.index("</style>", i)]
    assert "@media(max-width:1100px)" in css, "the three panes never stack"
    assert "@media(max-width:620px)" in css, "there is no phone layout at all"
    phone = css[css.index("@media(max-width:620px)"):]
    for mark in (".fv-paper{padding", ".fv-row2{grid-template-columns:1fr",
                 ".fv-bgrip{opacity"):
        assert mark in phone, f"the phone layout does not adjust {mark}"


# ── מחזור חיים וגישה ─────────────────────────────────────────────────

def test_the_public_link_is_the_one_the_server_built():
    """One constant for the address, so the copied link and the route that
    answers it cannot drift apart."""
    import re as _re
    assert 'FORM_PUBLIC_PATH = "/forms/"' in (ROOT / "backend" / "main.py").read_text(
        encoding="utf-8"), "the public path is not stated once"
    share = _editor()
    share = share[share.index("share(){"):share.index("async setAccess(access)")]
    assert "f.public_url" in share, "the screen assembles the address itself"
    assert "/forms/" not in share, "the address is spelled out in the client too"


def test_the_share_dialog_offers_only_what_the_server_would_accept():
    block = _editor()
    share = block[block.index("share(){"):block.index("async setAccess(access)")]
    assert "my_role==='admin'" in share, "publishing is offered regardless of role"
    assert "רק מנהל הלוח" in share, "somebody who may not publish is not told why"
    assert "FormEditor.copyLink()" in share, "the link cannot be copied"
    assert "אינו מעניק גישה ללוח" in share, "the access note does not say what filling in means"


def test_copying_falls_back_where_the_clipboard_api_is_not_there():
    block = _editor()
    copy = block[block.index("async copyLink()"):block.index("  // ── painting ──")]
    assert "navigator.clipboard" in copy and "execCommand" in copy, \
        "an http origin or an older browser gets nothing"
