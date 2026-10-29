"""רכיבי הטופס עובדים — בעורך, בתצוגה המקדימה ובדף הציבורי.

"אף אחד מרכיבי הטופס לא עובד — לא אחראים, לא התאריך, והתיאור לא נותן
להקליד." Six rounds of frontend fixes shipped against that sentence and the
suite stayed green through all six, so the gap is here and not there.

What the old coverage asserted was that the RENDERER could draw a live
control when a test asked it to: every check called ``FormPaper.html(doc,
{live: true})`` with options the test itself chose. Nobody asserted that the
PRODUCT asks for them, and nobody could see a control killed from outside
the markup — the whole suite is regexes over a rendered string, and
``pointer-events:none`` lives in a stylesheet, where no string test was
looking.

So this module pins three things no existing test could fail on:

* every question type is the right ELEMENT and is actually usable, on each
  of the three surfaces, rendered with the options the real call sites pass
  (tests/frontend/form_controls_live.mjs);
* no stylesheet rule on either page switches off a control that is meant to
  work;
* index.html, public-form.html and form-paper.js are ONE program in three
  files, and the server tells the browser so — a shell calling
  ``FormPaper.html(doc, {live:true})`` against a cached renderer that has
  never heard of ``live`` is precisely how a form editor can be dead in one
  browser and correct everywhere else, through six rounds of fixes.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "form_controls_live.mjs"
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
PAGE = (ROOT / "frontend" / "public-form.html").read_text(encoding="utf-8")
PAPER = (ROOT / "frontend" / "form-paper.js").read_text(encoding="utf-8")

SHELLS = (("index.html", INDEX), ("public-form.html", PAGE))


def test_every_form_control_is_usable_on_every_surface_it_is_drawn_on():
    """The harness: eleven question types across the three real surfaces."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


# ── מה שגיליון הסגנון עושה לפקד חי ───────────────────────────────────

# Anything a respondent presses, types into or ticks. A rule that takes the
# pointer off one of these is a control that looks perfect in the markup —
# which is all any other test here reads — and does nothing under a finger.
LIVE_SELECTORS = (".fv-in", ".fv-opt", ".fv-multi", ".fv-paper", ".fv-blk",
                  ".fv-q", ".fv-canvas", ".fv-blocks", ".fv-submit", ".fv-files")
# …unless the rule is scoped to the controls that are deliberately inert.
# :disabled is the renderer's own word for "this is a drawing", and letting
# the click through to the block beneath it is the only reason this rule
# exists; fv-opt-off is the same statement for a tick list.
INERT_SCOPES = (":disabled", "fv-opt-off", "fv-bgrip", "[disabled]")


def _rules(css):
    """(selector, body) for every flat CSS rule in a file.

    Crude on purpose — it is applied only to the rules that mention
    pointer-events, and those are all declarations in a stylesheet.
    """
    return re.findall(r"([^{}@;]+)\{([^{}]*)\}", css)


def test_no_stylesheet_rule_takes_the_pointer_off_a_live_form_control():
    """The blind spot that let six rounds of fixes ship and change nothing.

    Every other form test in this suite is a regex over the markup the
    renderer returns. A control switched off from a stylesheet is perfect in
    that markup and dead on the screen, and both pages carry a rule that
    does exactly that on purpose — ``.fv-paper input:disabled{pointer-
    events:none}``, so a press on the builder's drawing reaches the block
    beneath it and selects the question. Widen that selector by one class and
    the whole form goes quiet with nothing to see in any diff of the
    renderer.
    """
    for name, src in SHELLS:
        for selector, body in _rules(src):
            if "pointer-events" not in body:
                continue
            if not re.search(r"pointer-events\s*:\s*none", body):
                continue
            for one in selector.split(","):
                one = one.strip()
                if not any(s in one for s in LIVE_SELECTORS):
                    continue
                assert any(s in one for s in INERT_SCOPES), (
                    f"{name}: `{one}` takes the pointer off a form control that is "
                    f"meant to work — the markup will look perfect and nothing on "
                    f"the form will answer a press")


def test_neither_page_greys_out_a_control_that_is_not_greyed_out():
    """A control that READS as switched off is reported as broken.

    --text-light on something somebody is being asked to type into is the
    impression this screen spent six rounds giving, and the colour is a
    stylesheet's to give: the renderer cannot say it and no test over the
    markup can see it. The greying is kept for :disabled, which is the one
    place it is true.
    """
    for name, src in SHELLS:
        for selector, body in _rules(src):
            if not re.fullmatch(r"\s*\.fv-in\s*", selector):
                continue
            colour = re.search(r"(?<![-\w])color\s*:\s*([^;}]+)", body)
            if not colour:
                continue
            assert "text-light" not in colour.group(1), (
                f"{name}: .fv-in is drawn in the muted colour, so every field on "
                f"the form reads as switched off whether it is or not")


def test_a_form_control_shows_where_the_keyboard_is():
    """Tab reaches the canvas like it reaches everything else, and a control
    nobody can see the focus on is a control nobody can use without a mouse."""
    for name, src in SHELLS:
        assert re.search(r"\.fv-in:focus[^{]*\{[^}]*outline\s*:", src), (
            f"{name}: a focused form field is invisible to somebody tabbing")


def test_a_tick_on_a_form_is_a_target_a_finger_can_hit():
    """The editor opens on a phone too, and its canvas is a real form now."""
    for name, src in SHELLS:
        row = re.search(r"\.fv-opt\{([^}]*)\}", src)
        assert row, f"{name}: no rule for a tick row at all"
        got = re.search(r"min-height\s*:\s*(\d+)px", row.group(1))
        assert got and int(got.group(1)) >= 32, (
            f"{name}: a tick row is {row.group(1)} — not something a thumb hits")


# ── תוכנית אחת בשלושה קבצים ──────────────────────────────────────────

def _comment_spans(src):
    """Where the comments are, so a call site being TALKED ABOUT is not read
    as one that runs — index.html carries a note about this very hazard."""
    spans = []
    for pat in (r"<!--[\s\S]*?-->", r"/\*[\s\S]*?\*/"):
        spans += [m.span() for m in re.finditer(pat, src)]
    return spans


def _outside_comments(src, pattern):
    spans = _comment_spans(src)
    return [m for m in re.finditer(pattern, src)
            if not any(a <= m.start() < b for a, b in spans)]


def _top_level_keys(literal):
    """The keys of an object literal, and not of anything nested in it — a
    value's own fields are that value's business, not an option."""
    keys, depth = [], 0
    for i, ch in enumerate(literal):
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        if depth != 1 or not re.match(r"[{,\s]", literal[i - 1] if i else "{"):
            continue
        m = re.match(r"([A-Za-z_$][\w$]*)\s*:", literal[i:])
        if m:
            keys.append(m.group(1))
    return keys


def test_the_shells_ask_the_renderer_for_nothing_it_does_not_implement():
    """The split-file hazard, stated once in Python as well as in the harness.

    A shell may pass an option the renderer has never heard of and nothing
    throws: `opts.live` on an object that has no `live` is `undefined`, which
    is a perfectly good `false`. Every control comes out disabled, the editor
    is dead, and both files pass every test that reads either one alone.
    """
    reads = {m.group(1) for m in _outside_comments(PAPER, r"opts\.([A-Za-z_$][\w$]*)")}
    assert reads, "the renderer takes no options at all — has it been replaced?"
    for name, src in SHELLS:
        for call in _outside_comments(src, r"FormPaper\.html\("):
            i = src.index("{", call.start())
            depth, end = 0, None
            for j in range(i, len(src)):
                if src[j] == "{":
                    depth += 1
                elif src[j] == "}":
                    depth -= 1
                    if not depth:
                        end = j
                        break
            literal = src[i:end + 1]
            for key in _top_level_keys(literal):
                assert key in reads, (
                    f"{name} passes `{key}` to a renderer that never reads opts.{key}")


def test_the_shells_call_nothing_on_the_renderer_that_is_not_there():
    for name, src in SHELLS:
        for m in _outside_comments(src, r"FormPaper\.([A-Za-z_$][\w$]*)"):
            member = m.group(1)
            assert re.search(rf"^\s+{re.escape(member)}\s*[:(]", PAPER, re.M), (
                f"{name} calls FormPaper.{member}, which form-paper.js does not define")


def test_the_renderer_is_told_to_revalidate_because_the_shell_is(client):
    """The other half of "one program in three files", from the outside.

    index.html is text/html and has always been served `no-cache`, so a
    deploy reaches the browser on the next entry. form-paper.js is not, and a
    static mount hands it an ETag with no Cache-Control at all — the browser
    then guesses, and may serve yesterday's copy for hours without asking.
    That is how a brand-new shell calling FormPaper.html(doc, {live:true})
    ended up running against a renderer that had never heard of `live`: the
    form editor was dead in one browser and correct on the server, through
    six rounds of "it still doesn't work".
    """
    for path in ("/form-paper.js", "/", "/index.html"):
        r = client.get(path)
        assert r.status_code == 200, path
        cache = r.headers.get("cache-control", "")
        assert "no-cache" in cache or "max-age=0" in cache, (
            f"{path} may be served from cache without asking us: {cache!r}")
    # …and the renderer really is javascript, not the shell under another name
    assert "javascript" in client.get("/form-paper.js").headers["content-type"]


def _editor_method(name):
    """One method's source out of the FormEditor object literal, by braces."""
    i = INDEX.index("const FormEditor={")
    depth, span = 0, None
    for k in range(INDEX.index("{", i), len(INDEX)):
        if INDEX[k] == "{":
            depth += 1
        elif INDEX[k] == "}":
            depth -= 1
            if not depth:
                span = INDEX[i:k + 1]
                break
    m = re.search(rf"^  (?:async )?{name}\(", span, re.M)
    assert m, f"FormEditor.{name} moved"
    depth = 0
    for k in range(span.index("{", m.start()), len(span)):
        if span[k] == "{":
            depth += 1
        elif span[k] == "}":
            depth -= 1
            if not depth:
                return span[m.start():k + 1]
    raise AssertionError("unterminated " + name)


def test_pressing_a_field_on_the_canvas_does_not_redraw_the_field():
    """"התיאור לא נותן להקליד" is what a repaint-on-click looks like.

    Every block on the canvas carries an onclick that selects the question,
    and a control lives inside that block — so every press on a field runs
    it. If selecting redraws the canvas, the node being typed into is
    replaced mid-keystroke: the caret goes, the character goes, and the field
    reads as one that refuses to accept anything. The selection is painted
    onto the existing nodes instead, and that is a rule about two files at
    once — the renderer writes the handler, the shell implements it — so it
    is pinned where both are read.
    """
    assert re.search(r"FormEditor\.select\(\$\{c\.id\},\s*event\)", PAPER), (
        "the canvas selects without the event, so select() cannot tell a press on "
        "a text field from a press on the block and toggles the pane shut under it")
    select = _editor_method("select")
    assert re.search(r"select\(cid,\s*\w+\)", select), \
        "select() does not take the event the canvas hands it"
    assert "input,textarea,select" in select, \
        "select() does not look at what was actually pressed"
    for method in ("select", "paintSel"):
        body = _editor_method(method)
        assert "canvasHTML()" not in body, (
            f"FormEditor.{method} redraws the canvas, which replaces the field "
            f"being typed into with a fresh empty one")
        assert "innerHTML=this.html()" not in body
    # the selection is moved by touching classes, not by rebuilding the paper
    assert "classList.toggle('sel'" in _editor_method("paintSel")


def test_a_press_inside_a_question_does_not_start_a_drag_instead():
    """The canvas is a sortable list AND a form somebody types into.

    Those two want the same gesture. A Sortable with no handle takes the
    mousedown anywhere in the row, so pressing a text field begins dragging
    the question instead of putting a caret in it — a field that cannot be
    typed into, with nothing wrong in the markup and nothing wrong in the
    renderer. The grip is the handle; and because the grip is invisible until
    hover, the room for it is reserved with a LOGICAL padding, or in an RTL
    page it lies across the first centimetre of the question itself.
    """
    sort = _editor_method("attachSort")
    wires = re.findall(r"wire\(document\.getElementById\('([\w-]+)'\),\s*'([^']+)',"
                       r"\s*'([^']+)'\)", sort)
    by_list = {w[0]: w for w in wires}
    assert "fv-blocks" in by_list, "the paper is not the draggable list at all"
    assert by_list["fv-blocks"][2].strip(), (
        "the canvas is dragged by the whole question, so pressing a field drags it")
    assert "handle" in sort, "sortableOn is never given a handle"
    grip = re.search(r"\.fv-bgrip\{([^}]*)\}", INDEX)
    assert grip, "the grip has no rule"
    assert "inset-inline-start" in grip.group(1), \
        "the grip is placed with a physical edge, which in RTL is the other one"
    block = re.search(r"\.fv-blk\{([^}]*)\}", INDEX)
    assert block and "padding-inline" in block.group(1), (
        "the block reserves room for the grip physically — in RTL the invisible "
        "handle then sits on top of the question's own first characters")


def test_the_renderer_is_loaded_and_never_copied():
    """Two copies of it is the same bug with the versions reversed."""
    assert "const FormPaper" in PAPER
    for name, src in SHELLS:
        assert "const FormPaper" not in src, f"{name} carries a second renderer"
        assert re.search(r'<script src="/?form-paper\.js"', src), \
            f"{name} does not load the renderer at all"
