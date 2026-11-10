"""The dashboard card, drawn headless, and the page it lives in.

Two halves. The first runs `tests/frontend/dashboard_widget.mjs`, which pulls
the real `Dash` object out of index.html and draws cards with it — so what is
asserted is the code that ships, not a description of it. What it pins is the
half of R04 and DASH-15 that lives in the browser: rounding is display and
never data, and no state that is not a number may look like one.

The second half reads the page as text, for the rules that are about what is
NOT there — a stray colour outside the palette, a left/right property in an
RTL layout, an interpolation that forgot esc().
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "dashboard_widget.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _dash_css():
    i = SRC.index("/* ===== דשבורדים =====")
    return SRC[i:SRC.index("</style>", i)]


def _dash_js():
    i = SRC.index("const Dash = {")
    return SRC[i:SRC.index("/* ============ CEO City Dashboard ============ */", i)]


def test_the_widget_draws_every_state_the_way_the_spec_requires():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_dashboard_uses_only_the_monday_palette():
    """Invariant 7 — no purple, and no colour invented beside the variables
    that already exist."""
    css = _dash_css()
    hexes = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,6}", css)}
    allowed = {"#0073ea", "#00c875", "#fdab3d", "#e2445c", "#579bfc",
               "#ffcb00", "#c4c4c4", "#fff6e5", "#8a5a00"}
    assert hexes <= allowed, f"colours outside the palette: {sorted(hexes - allowed)}"


def test_the_dashboard_is_written_in_logical_properties():
    """Invariant 9 — RTL-first. `left`/`right` pin a layout to one direction;
    the logical properties follow the document."""
    css = _dash_css()
    bad = re.findall(r"(?<![-\w])(margin|padding|border|inset)-(left|right)\s*:", css)
    assert not bad, f"physical direction properties: {bad}"


def _strip_esc(fragment):
    """The fragment with every balanced esc(...) call removed.

    Whatever is left was printed raw. Doing it by removal rather than by
    looking backwards from each reference is the difference between a test
    that answers the question and one that answers "is the word esc
    somewhere nearby".
    """
    out = fragment
    while True:
        i = out.find("esc(")
        if i < 0:
            return out
        depth, j = 0, i + 3
        while j < len(out):
            if out[j] == "(":
                depth += 1
            elif out[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= len(out):
            return out[:i]          # unbalanced — stop rather than loop
        out = out[:i] + out[j + 1:]


def test_every_user_written_name_the_dashboard_prints_is_escaped():
    """Invariant 10 — an unescaped widget or board name is stored XSS, and a
    widget title is typed by one person and read by everybody on the
    dashboard, which is exactly the shape that matters.

    Checked by naming the properties that carry somebody's text, stripping
    the esc() calls out of each interpolation, and asking whether any of
    them survived. A broader sweep over every ${…} cannot tell a ternary
    over markup from a value, and a test that cries wolf gets deleted.
    """
    js = _dash_js()
    carries_text = (".title", ".name", ".description", ".board_name",
                    ".note", ".unit", ".field", ".empty_handling")
    # A reference that is only a ternary's condition, or the left side of an
    # && / ||, is never printed — "r.field ? … esc(r.field) … : ''" prints the
    # escaped one and tests the bare one.
    condition = re.compile(r"[\w.\[\]]+\s*(?:\?|&&|\|\|)")
    bad = []
    for m in re.finditer(r"\$\{([^{}]*)\}", js):
        x = m.group(1)
        if not any(p in x for p in carries_text):
            continue
        left = _strip_esc(condition.sub("", x))
        if any(p in left for p in carries_text):
            bad.append(x[:70])
    # Two deliberate exceptions, and both are safe because the value never
    # reaches markup as markup:
    #   w.title       — the screen-reader announcement, set through
    #                   textContent (asserted below);
    #   im.board_name — the argument to askConfirm, which escapes its own
    #                   message. Escaping here as well would double it, and
    #                   a board called "תקציב & תפעול" would read "&amp;".
    safe = {"w.title", "im.board_name"}
    bad = [b for b in bad if b.strip() not in safe]
    assert not bad, f"user text printed without esc(): {bad}"


def test_the_confirmation_that_names_a_board_does_not_double_escape_it():
    """askConfirm escapes its own message. Escaping at the call site as well
    would turn a board called "תקציב & תפעול" into "תקציב &amp; תפעול" in
    front of the person deciding whether to remove it."""
    i = SRC.index("function askConfirm(")
    assert "esc(message)" in SRC[i:i + 900]
    js = _dash_js()
    j = js.index("DASH-06.3")
    assert "esc(im.board_name)" not in js[j:j + 700]


def test_the_live_region_writes_text_and_not_markup():
    """The one place a name reaches the page without esc() is the screen
    reader announcement — and it goes through textContent, where markup is
    not markup. Pinned so it stays that way."""
    js = _dash_js()
    i = js.index("live.textContent")
    assert "innerHTML" not in js[i:i + 160]


def _mobile_block():
    """The ONE canonical narrow-screen block.

    There is exactly one, and the codebase enforces it (see
    tests/frontend/admin_tabs_sort_search_export.mjs): "a second @media at
    the same breakpoint is indistinguishable from the first to anything
    reading the stylesheet and the mobile tests duly read the wrong one."
    The dashboard's phone rules therefore live there and not beside the rest
    of its styling.
    """
    q = "@media (max-width:820px){"
    i = SRC.index(q)
    depth, j = 1, i + len(q)
    while depth:
        if SRC[j] == "{":
            depth += 1
        elif SRC[j] == "}":
            depth -= 1
        j += 1
    return SRC[i:j]


def test_the_grid_collapses_to_one_column_on_a_phone():
    """R08 — "הווידג׳טים מוצגים בטור ברוחב מלא לפי סדר הקריאה השמור, בלי
    לשנות גדלי דסקטופ"."""
    block = _mobile_block()
    assert ".dash-grid{grid-template-columns:1fr" in block.replace(" ", "")
    assert ".dash-edit-only{display:none" in block.replace(" ", "")


def test_the_dashboard_adds_no_second_media_query_at_a_used_breakpoint():
    """The rule the stylesheet already lives by, asserted from this side too
    — adding one is exactly the mistake this feature made once."""
    for q in ("@media (max-width:820px){", "@media (prefers-reduced-motion"):
        assert SRC.count(q) == 1, f"{q} appears {SRC.count(q)} times"


def test_the_editing_controls_are_desktop_only_in_the_code_too():
    """Hiding a control with CSS still ships it to the phone. R08 says mobile
    "אינו תומך ביצירה, עריכת ווידג׳טים, סדר, גודל או הגדרות דשבורד", so the
    card asks before it draws."""
    js = _dash_js()
    assert "isWide()" in js
    assert "this.isEditor()&&this.isWide()" in js


def test_touch_targets_are_not_below_the_systems_own_floor():
    """R08 — "יעדי מגע לפי רכיבי המערכת". The system's floor is 44px and the
    rows and buttons a reader taps are held to it."""
    css = _dash_css()
    assert "min-height:44px" in css.replace(" ", "")      # the drill-down rows


def test_the_card_never_shows_a_previous_figure_without_marking_it():
    """R09 — "תוצאה קודמת מותרת רק אם מסומנת לא עדכנית עם זמן"."""
    js = _dash_js()
    assert "_stale:true" in js.replace(" ", "")
    assert "לא עדכני" in js


def test_a_blocked_source_drops_what_was_already_on_screen():
    """R09 — "מקור חסום אינו משאיר תוצאה קודמת", and R01 extends it to an
    open drill-down: "שלילת הרשאה תסיר מיד מידע לא מורשה גם מפירוט שכבר
    פתוח"."""
    js = _dash_js()
    assert "had.state!=='blocked'" in js.replace(" ", "")
    assert "out.state==='blocked'&&this.drill" in js.replace(" ", "")


def test_an_old_response_cannot_land_on_top_of_a_new_one():
    """DASH-21.2 — "תגובה לבקשה ישנה לא תדרוס תגובה לבקשה חדשה"."""
    js = _dash_js()
    assert "this.seq[wid]!==my" in js.replace(" ", "")


def test_a_save_conflict_is_shown_and_never_forced():
    """R09 — "התנגשות מציגה 'התצוגה עודכנה על ידי משתמש אחר' ללא דריסה
    שקטה"."""
    js = _dash_js()
    assert "e.status===409" in js.replace(" ", "")
    assert "עודכן על ידי משתמש אחר" in js


# ── שתי צורות הדשבורד, כפי שמגיעים אליהן ───────────────────────────────────

def _views_js():
    i = SRC.index("const Views = {")
    return SRC[i:SRC.index("function renderTabs()", i)]


def test_a_dashboard_tab_is_drawn_in_the_boards_strip():
    """A board dashboard is reached from the board's own tab strip, like a
    form — the same strip, the same name, the same bin."""
    js = _views_js()
    assert "v.kind==='dash'" in js.replace(" ", "")
    assert "fa-chart-simple tab-view-ic" in js
    assert "Dash.openOnBoard" in js


def test_a_dashboard_tab_offers_only_what_the_server_accepts():
    """Lock, pin and duplicate are written through the view endpoint, which
    refuses a dashboard outright. An action that would be refused is not
    drawn — the same rule the form tab follows."""
    js = _views_js()
    i = js.index("actionsFor(v){")
    block = js[i:i + 1200]
    # the early return a form and a dashboard share, and what is in it
    assert "v.kind==='form'||v.kind==='dash'" in block.replace(" ", "")
    early = block[block.index("v.kind==='form'||v.kind==='dash'"):]
    early = early[:early.index("\n", early.index("return v.can_edit"))]
    assert "rename" in early and "delete" in early
    for refused in ("duplicate", "lock", "pin"):
        assert refused not in early, f"{refused} is offered on a dashboard tab"


def test_a_board_dashboard_is_drawn_over_the_board_and_not_as_a_view():
    """`renderTabs` resets st.view to the table for anything the board does
    not itself offer, so a view id of our own would be thrown away on the
    next render. A form short-circuits in renderView for the same reason."""
    m = re.search(r"function renderView\(\)\{(.{0,4000})", SRC, re.S)
    head = m.group(1)
    assert "Dash.onBoard()" in head and "Dash.paint(el)" in head
    assert head.index("Dash.paint(el)") < head.index("el.innerHTML=''")


def test_leaving_the_tab_leaves_the_board_where_it_was():
    """The board was never unloaded, so choosing one of its own views only
    has to let the dashboard go."""
    js = _dash_js()
    assert "leave(){" in js.replace(" ", "")
    assert "Dash.onBoard()) Dash.leave()" in SRC


def test_both_creation_paths_exist_and_ask_for_the_right_thing():
    """DASH-05.1 — a board dashboard is added through "הוספת תצוגה", and a
    standalone one through the workspace's own "+", beside a board."""
    assert "Dash.createOnBoard()" in SRC          # the + on the view strip
    assert "Dash.createStandalone()" in SRC       # the + in the sidebar
    i = SRC.index("createStandalone(){")
    block = SRC[i:i + 1400]
    # "עם שם ובחירה בין ראשי לפרטי"
    assert "nd-name" in block and "nd-vis" in block
    assert 'value="main"' in block and 'value="private"' in block


def test_the_standalone_plus_sits_beside_the_board_and_needs_the_same_right():
    """R01 — "יצירה למי שמורשה ליצור לוחות". It appears and disappears with
    the board entry, because it is the same permission."""
    i = SRC.index("function newThingMenu(")
    block = SRC[i:i + 1800]
    assert "const dash=canBoard?" in block
    assert "${board}${dash}${folder}" in block


# ── חלון הוספת התצוגה ──────────────────────────────────────────────────────

def _add_view_js():
    i = SRC.index("function renderAddViewPop(){")
    return SRC[i:SRC.index("function closeAddView()", i)]


def _add_view_css():
    i = SRC.index("/* ── הוספת תצוגה ──")
    return SRC[i:SRC.index("/* ── תרשימים ──", i)]


def test_the_add_view_panel_says_what_each_kind_is_for():
    """Three words nobody has met before are three words. The panel is the
    one place a board grows a tab, and the three are not even the same kind
    of thing — one reads the board, one writes to it, one measures it."""
    js = _add_view_js()
    for kind in ("טבלה", "טופס", "דשבורד"):
        assert f"he:'{kind}'" in js.replace(" ", "")
    # and each carries a sentence, not only a name
    assert js.count("desc:'") == 3
    assert "av-ds" in js


def test_every_card_is_a_real_control():
    """R08 — keyboard, visible focus, and a touch target the system's own
    size. A div with an onclick is none of those."""
    js, css = _add_view_js(), _add_view_css()
    assert "<button class=\"av-card\"" in js
    assert ".av-card:focus-visible" in css
    assert "min-height:44px" in css.replace(" ", "")


def test_the_panel_invents_no_colour():
    """Invariant 7 — the icon tiles are tinted from the variables that
    already exist, and the colour repeats nothing the words do not say."""
    js, css = _add_view_js(), _add_view_css()
    assert not re.findall(r"#[0-9a-fA-F]{3,6}", css.replace("#fff", "")), \
        "a colour was hardcoded in the panel"
    for v in ("var(--primary)", "var(--green)", "var(--orange)"):
        assert v in js


def test_the_panel_is_written_in_logical_properties():
    """Invariant 9 — RTL-first."""
    css = _add_view_css()
    bad = re.findall(r"(?<![-\w])(margin|padding|border|inset)-(left|right)\s*:", css)
    assert not bad, f"physical direction properties: {bad}"


def test_the_panel_becomes_a_sheet_on_a_phone():
    """A 380px dropdown hanging off a 30px button has nowhere to go on a
    phone, and the cards need the width."""
    block = _mobile_block()
    assert ".av-pop{position:fixed" in block.replace(" ", "")
    assert ".av-chip{min-height:44px}" in block.replace(" ", "")


def test_a_viewer_is_offered_nothing_and_told_why():
    """An action that would be refused is not drawn — and a menu that is
    simply empty reads as broken."""
    js = _add_view_js()
    assert "mayAdd" in js
    assert "רק עורך או מנהל לוח" in js


def test_creating_a_dashboard_view_does_not_stop_to_ask(client=None):
    """The complaint that produced this: a box asking for a name before
    anything exists. Every sibling creates first — Views.createTable,
    FormEditor.create and newBoardQuick all post, open, and let the name be
    changed from where it then is."""
    js = _dash_js()
    i = js.index("async createOnBoard(")
    block = js[i:i + 1400]
    assert "prompt(" not in block, "the dashboard still asks for a name up front"
    assert "JSON.stringify({})" in block, "a name is being sent instead of the server's"
    assert "_making" in block, "a double click would make two dashboards"


# ── בחירת לוחות המקור ──────────────────────────────────────────────────────

def test_a_dashboard_with_no_boards_offers_the_way_to_pick_them():
    """The bug this closes: a standalone dashboard is created with no boards
    on purpose, and until the picker existed there was no way to add one —
    so the widget editor opened on a column list with no rows in it, which
    is what "לא מופיעות העמודות" looks like from the outside."""
    js = _dash_js()
    assert "sourcesPanel()" in js
    # the empty dashboard names the first step, rather than offering the second
    i = js.index("כדי למדוד משהו")
    assert "Dash.sourcesPanel()" in js[i:i + 700]


def test_the_widget_editor_says_when_there_is_nothing_to_map():
    """An empty column picker reads as broken. Two different emptinesses, two
    different sentences: no board at all, and a board with no numeric column
    (R03 names the three kinds that can be summed)."""
    i = SRC.index("Dash.Editor = {")
    js = SRC[i:SRC.index("/* ============ תרשימים", i)] if "/* ============ תרשימים" in SRC[i:] else SRC[i:i + 20000]
    assert "לדשבורד הזה עדיין לא נבחרו לוחות מקור" in js
    assert "אין בלוח עמודה מספרית" in js


def test_only_boards_the_person_can_open_are_offered_as_sources():
    """The server refuses any other (_dash_check_sources), and offering one
    that will be refused is the mistake the rest of this file avoids."""
    js = _dash_js()
    i = js.index("sourcesPanel(){")
    block = js[i:i + 1800]
    assert "st.boards" in block, "the list is not built from the boards this person has"
    assert "/api/boards" not in block, "it should not fetch a wider list than the sidebar's"


def test_removing_a_source_asks_before_it_breaks_a_widget():
    """DASH-06.3 — "לפני הסרת לוח, להציג אילו ווידג׳טים יושפעו ולבקש אישור"."""
    js = _dash_js()
    i = js.index("async srcSave()")
    block = js[i:i + 1400]
    assert "/impact" in block
    assert "askConfirm" in block
    assert "orphaned" in block


def test_the_board_limit_is_said_before_the_save_not_by_it():
    """R02 — up to ten. A refusal that only arrives on save is one the person
    could have been spared."""
    js = _dash_js()
    assert "המגבלה היא 10" in js
    assert "picked.length>10" in js.replace(" ", "")


# ── ווידג׳ט רשימה ──────────────────────────────────────────────────────────

def test_a_list_row_opens_the_item_rather_than_being_a_dead_end():
    """A list that could only be looked at would be the one place on the
    dashboard where a record goes nowhere. It opens through the same path
    the drill-down uses — the existing item card, the item's own
    permissions, and the way back."""
    js = _dash_js()
    i = js.index("listBody(w,out){")
    block = js[i:i + 2600]
    assert "Dash.openItem(" in block
    assert "aria-label=" in block


def test_a_list_says_how_many_it_is_showing_of_how_many():
    """R10 — "אין חיתוך, סכום חלקי… ללא הודעה". Ten rows out of four hundred
    are honest only when the four hundred is beside them."""
    js = _dash_js()
    i = js.index("listBody(w,out){")
    block = js[i:i + 2600]
    assert "out.shown" in block and "out.records" in block
    assert "הצגה מוגבלת" in block


def test_a_list_has_the_same_four_failure_states_as_a_figure():
    """Blocked, error, needs-fix and nothing-to-show. A third widget kind
    with three of them would be a third set of answers."""
    js = _dash_js()
    i = js.index("listBody(w,out){")
    block = js[i:i + 2600]
    for state in ("'blocked'", "'error'", "'needs_fix'"):
        assert state in block, state
    assert "אין רשומות שעונות להגדרות" in block


def test_a_list_cannot_be_asked_to_show_a_link_column():
    """Connect and mirror hold ids filtered per viewer (_visible_link_ids),
    and a row of text has no way to tell that story. The editor does not
    offer them and the server refuses them."""
    i = SRC.index("async cols(){")
    block = SRC[i:i + 1400]
    assert "all:(b.columns||[])" in block
    assert "'connect'" not in block.split("all:(b.columns||[])")[1][:400]
    assert "'mirror'" not in block.split("all:(b.columns||[])")[1][:400]
