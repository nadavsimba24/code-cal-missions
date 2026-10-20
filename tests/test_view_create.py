"""ה-"+" מוסיף תצוגת טבלה.

Driven harness: tests/frontend/view_create.mjs.

The "+" used to toggle the board's view TYPES, and with the other six held
back by VIEWS_WIP that list was one disabled row — the button opened a menu
with nothing in it anybody could press. What this version adds is a saved
table view, and since that is the only kind there is, there is no type to pick
first: "בגרסה זו סוג התצוגה היחיד הוא טבלה שמורה, ולכן אין צורך בקטלוג סוגים."

Verified to fail: have createTable read this.current() instead of the main
table and two harness cases go red; drop the error element from the dialog and
three do; send filters with a rename and one does.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_plus_offers_the_one_thing_this_version_can_add():
    i = SRC.index("function renderAddViewPop()")
    body = SRC[i:SRC.index("\n}", SRC.index("join('')", i))]
    assert "Views.createTable()" in body, "the + still only toggles view types"


def test_the_plus_is_offered_to_whoever_may_put_a_tab_on_the_board():
    """An action that is going to be refused is not drawn — the same rule the
    per-view menu follows."""
    i = SRC.index("function renderAddViewPop()")
    body = SRC[i:SRC.index("\n}", SRC.index("join('')", i))]
    assert "my_role==='admin'||st.board.my_role==='editor'" in body.replace(" ", ""), body[:400]
    assert "mayAdd?" in body, "the action is drawn for everybody"


def test_the_creation_starts_from_the_main_table():
    """"יצירה חדשה תתבסס על הגדרות הטבלה הראשית שנשמרו, ללא חיפוש או התאמות
    זמניות." Somebody who adjusted the board and then pressed + was not asking
    to freeze those adjustments into a new tab."""
    m = re.search(r"\n  createTable\(\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "createTable moved"
    body = m.group(1)
    assert "kind==='main'" in body.replace(" ", ""), body
    assert "delete base.q" in body, "a new view could carry a search"
    assert "this.current()" not in body, "it starts from the screen, not the main table"


def test_save_as_new_still_starts_from_the_screen():
    """The other direction, and the two must not drift into each other: this
    is the button that means "with my adjustments"."""
    m = re.search(r"\n  async save\(id\)\{(.*?)\n  \},", SRC, re.S)
    assert m and "this._pending||this.current()" in m.group(1).replace(" ", "")


def test_the_dialog_has_no_visibility_choice_left():
    """Every saved view is a tab on the board, so the question has one answer
    and asking it was offering a choice that does not exist."""
    m = re.search(r"\n  _dialog\(v, opts\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "_dialog moved"
    body = m.group(1)
    assert "vw-vis" not in body and "visibility" not in body, body[:300]


def test_the_validation_error_sits_beside_the_field():
    """A toast about a name is four seconds of text somewhere else on the
    screen while the thing it is about is under the caret."""
    m = re.search(r"\n  _dialog\(v, opts\)\{(.*?)\n  \},", SRC, re.S)
    body = m.group(1)
    assert 'id="vw-err"' in body and 'aria-describedby="vw-err"' in body
    assert 'role="alert"' in body

    m2 = re.search(r"\n  async save\(id\)\{(.*?)\n  \},", SRC, re.S)
    assert "this._err(" in m2.group(1), "a refused save still toasts"


def test_cancel_creates_nothing():
    """"ביטול אינו יוצר תצוגה." Nothing is written before save is pressed —
    the dialog holds the prepared cut in memory and the only call is in
    save()."""
    m = re.search(r"\n  _dialog\(v, opts\)\{(.*?)\n  \},", SRC, re.S)
    assert "api(" not in m.group(1), "the dialog writes something on the way up"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_create_harness():
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" / "view_create.mjs")],
                       capture_output=True, text=True)
    print(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
