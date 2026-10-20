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
    m = re.search(r"\n  async createTable\(\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "createTable moved"
    body = m.group(1)
    assert "kind==='main'" in body.replace(" ", ""), body
    assert "delete base.q" in body, "a new view could carry a search"
    assert "this.current()" not in body, "it starts from the screen, not the main table"


def test_adding_a_table_asks_nothing(client=None):
    """"אני לא רוצה שם לטבלה, רק שתיפתח התצוגה" — there is no type to choose
    in this version, so there is nothing to answer. A form with one field in
    it is a question standing between somebody and the thing they already
    asked for by pressing the button."""
    m = re.search(r"\n  async createTable\(\)\{(.*?)\n  \},", SRC, re.S)
    body = m.group(1)
    assert "_dialog" not in body, "the + still opens a form"
    assert "name:" not in body, "the browser is still naming the view"
    assert "this.apply(" in body, "created but not opened"


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


# ── the server names it, and numbers it when the name is taken ─────────────
def test_an_unnamed_view_is_called_tavla(client, admin_id):
    """Pressing + is not a question, so the answer cannot be a form. The name
    is the server's because the uniqueness rule is the server's."""
    from test_saved_views import _board          # noqa: E402
    bid = _board(client, admin_id)
    r = client.post(f"/api/boards/{bid}/views",
                    json={"user_id": admin_id, "filters": {"view": "table"}},
                    headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "טבלה"


def test_and_numbered_when_that_is_taken(client, admin_id):
    from test_saved_views import _board          # noqa: E402
    bid = _board(client, admin_id)
    names = []
    for _ in range(3):
        r = client.post(f"/api/boards/{bid}/views",
                        json={"user_id": admin_id, "filters": {"view": "table"}},
                        headers={"X-CityOS-User": str(admin_id)})
        assert r.status_code == 200, r.text
        names.append(r.json()["name"])
    assert names == ["טבלה", "טבלה 2", "טבלה 3"], names


def test_a_name_that_is_given_is_still_honoured(client, admin_id):
    """The dialog is gone from the + but renaming still goes through the same
    endpoint, and so does anything else that names a view."""
    from test_saved_views import _board, _mk     # noqa: E402
    bid = _board(client, admin_id)
    assert _mk(client, bid, admin_id, "שם משלי").json()["name"] == "שם משלי"


def test_the_default_name_is_configurable():
    import main as cityos_main                   # noqa: E402
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("NEW_VIEW_NAME"' in src
    assert cityos_main.NEW_VIEW_NAME == "טבלה"
