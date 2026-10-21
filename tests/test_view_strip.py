"""ממשק הרצועה — לשוניות התצוגה, הסימונים והתפריט.

Driven harness: tests/frontend/view_strip.mjs, which lifts the real Views
object out of index.html and exercises it.

Verified to fail: drop the aria-label from either icon and two cases go red;
derive the menu from a role instead of the server's flags and the viewer case
goes red; make the picker's search case-sensitive and one goes red.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_strip_asks_the_server_what_may_be_done():
    """The flags, not a role. A menu built from st.board.my_role would be a
    second copy of the permission matrix living in the browser, and the two
    would disagree the first time either moved — with the browser's copy
    being the one somebody sees."""
    m = re.search(r"\n  actionsFor\(v\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "actionsFor moved"
    body = m.group(1)
    for flag in ("v.can_edit", "v.can_duplicate", "v.can_lock"):
        assert flag in body, flag
    assert "my_role" not in body, "the menu re-derives the permission matrix"
    assert "isBoardAdmin" not in body


def test_the_delete_dialog_says_the_board_is_not_being_deleted():
    """"מסך מחיקה יציג את שם התצוגה ואת ההבהרה שנתוני הלוח נשמרים." The word
    "מחיקה" beside a board full of work is frightening in a way the action
    does not deserve."""
    m = re.search(r"\n  del\(id\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "Views.del moved"
    body = m.group(1)
    assert "v?v.name:''" in body or "v.name" in body, "the dialog does not name the view"

    # The note STRING, not the method body. The first version of this case
    # searched the whole block, and the block holds a comment quoting the
    # requirement — so deleting the sentence from the message somebody
    # actually reads left the case green.
    note = re.search(r"note:\s*'([^']*)'\s*(?:\+\s*'([^']*)')?", body)
    assert note, "the dialog has no note"
    text = (note.group(1) or "") + (note.group(2) or "")
    assert "פריטי הלוח לא יימחקו" in text, text
    assert "לשחזר" in text, "nobody is told it can be brought back"


def test_the_picker_is_reachable_before_the_strip_overflows():
    """A strip that only reveals its escape hatch once it has overflowed is
    one nobody finds: by then the thing they are looking for is off-screen and
    so is the button."""
    m = re.search(r"const picker=Views\.items\.length(.*?);\n", SRC, re.S)
    assert m, "the picker button moved"
    assert "openPicker" in m.group(1)
    # the accessible name now carries WHERE YOU ARE as well as what the button
    # does — see test_the_button_says_which_view_you_are_on
    assert 'aria-label="התצוגה הנוכחית' in m.group(1), "the button has no accessible name"


def test_choosing_a_blocked_view_goes_to_the_main_table_without_explaining():
    m = re.search(r"\n  pick\(id\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "Views.pick moved"
    body = m.group(1)
    assert "v.blocked" in body and "this.leave()" in body, body
    assert "עמודה" not in body, "the message names the column the block exists to hide"


def test_the_tabs_share_one_underline():
    """The open tab is marked by a border along its bottom edge, so every tab
    has to end at the same height. Centring them let a taller tab — one
    carrying a menu button — ride its underline lower than its neighbours,
    which reads as the row being out of line rather than as one tab being
    bigger."""
    m = re.search(r"\n\.tabs\{([^}]*)\}", SRC)
    assert m, ".tabs moved"
    assert "align-items:stretch" in m.group(1), m.group(1)


def test_the_things_beside_the_tabs_keep_their_own_height():
    """Stretch is for tabs. The + , the save buttons and the all-views picker
    are controls next to them, and a stretched button is a tall pill."""
    # Every declaration of each selector, not the first one: a coarse-pointer
    # block redeclares some of them, and these rules are defined after it in
    # the file — so slicing at the block cut the real rule out and slicing
    # before it matched the override. At least one declaration has to carry
    # the opt-out, which is what the browser resolves to.
    for sel in (".tab-add-wrap", ".tab-save", ".tab-all", ".save-failed"):
        decls = re.findall(r"(?:^|\n|,)" + re.escape(sel) + r"\{([^}]*)\}", SRC)
        assert decls, sel
        assert any("align-self:center" in d for d in decls), (sel, decls)


def test_the_menu_button_does_not_make_its_tab_taller():
    """A 44px target inside a 42px row is the whole of the bug. The target is
    made of padding that reaches into the tab's own, so the row keeps the
    height it had."""
    m = re.search(r"\.tab-view-menu\{([^}]*)\}", SRC)
    assert m and "height:22px" in m.group(1), m and m.group(1)

    coarse = re.search(r"@media \(hover:none\),\(pointer:coarse\)\{(.*?)\n\}", SRC, re.S)
    # the menu button's own declaration inside that block — "height:44px"
    # anywhere in it also matches .tab-all's min-height, which is a different
    # control and is allowed to be 44 tall
    btn = re.search(r"\.tab-view-menu\{([^}]*)\}", coarse.group(1))
    assert btn, coarse.group(1)
    assert "height:44px" not in btn.group(1), "the touch size grows the row again"
    assert "padding:11px" in btn.group(1) and "margin:-11px" in btn.group(1), btn.group(1)


def test_the_plus_offers_tavla_by_that_name():
    """It is what the thing is called everywhere else — the first one added is
    "טבלה". A menu item named "תצוגת טבלה חדשה" names a category instead."""
    i = SRC.index("function renderAddViewPop()")
    body = SRC[i:SRC.index("\n}", SRC.index("join('')", i))]
    assert "<span>טבלה</span>" in body, body[:400]
    assert "תצוגת טבלה חדשה" not in body


def test_only_one_tab_is_lit_at_a_time():
    """A saved view is a cut OF the table, so opening one leaves st.view on
    'table' — which lit "טבלה ראשית" at the same time as the view itself. Two
    active tabs is the same as none: there was no telling which one you were
    looking at."""
    i = SRC.index("function renderTabs()")
    body = SRC[i:SRC.index("const formTab", i)]
    assert "onSaved" in body, "the board's own tabs stay lit under a saved view"
    flat = body.replace(" ", "")
    assert "(!onSaved&&st.view===id)?'active':''" in flat, flat[-300:]


def test_the_button_says_which_view_you_are_on():
    """A count answers a question nobody asked. The one actually being asked,
    by somebody who has scrolled the strip or is on a narrow screen, is "which
    of these am I looking at"."""
    i = SRC.index("const openNow=Views.openView")
    body = SRC[i:SRC.index("    : '';", i)]
    # the span's CONTENT, not merely that the variable exists above it: the
    # first version of this passed with the name swapped back for the count,
    # because `hereName` was still declared a line earlier
    flat = body.replace(" ", "")
    assert '<spanclass="tab-all-nm">${esc(hereName)}</span>' in flat, body[:400]
    assert "tab-all-n{" not in SRC, "the count is still what the button shows"
    assert 'aria-label="התצוגה הנוכחית' in body, "the name is not announced"


def test_the_button_is_there_as_soon_as_there_is_a_view():
    """It used to appear only past two views, which is the moment it stops
    being needed as an indicator and starts being needed as a list."""
    m = re.search(r"const picker=Views\.items\.length(\S*)", SRC)
    assert m, "the picker button moved"
    assert not m.group(1).startswith(">"), \
        "the indicator hides until there is more than one view"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_strip_harness():
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" / "view_strip.mjs")],
                       capture_output=True, text=True)
    print(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
