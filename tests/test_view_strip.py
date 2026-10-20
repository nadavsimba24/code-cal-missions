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
    assert 'aria-label="כל התצוגות' in m.group(1), "the button has no accessible name"


def test_choosing_a_blocked_view_goes_to_the_main_table_without_explaining():
    m = re.search(r"\n  pick\(id\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "Views.pick moved"
    body = m.group(1)
    assert "v.blocked" in body and "this.leave()" in body, body
    assert "עמודה" not in body, "the message names the column the block exists to hide"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_strip_harness():
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" / "view_strip.mjs")],
                       capture_output=True, text=True)
    print(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
