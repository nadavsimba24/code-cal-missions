"""כל עמודת סטטוס של הלוח מוצעת בטופס — ועמודה שאינה על הלוח, לא.

The ask was "לאפשר לכל עמודה מסוג סטטוס להופיע בטופס, לדוגמה עמודת עדיפות",
and what stood in the way was not the status columns — those were always
offered — but the five built-in fields being offered beside them whether the
board shows them or not.

On an imported board that is four questions about columns that are not there.
The monday import hides אחראים, סטטוס, עדיפות and תאריך יעד outright: the
file fills none of them, and left showing they would be four columns of
"טרם הוגדר" standing in front of the board that was actually imported.

So a board whose own "עדיפות" is a status column offered TWO fields called
עדיפות — the hidden built-in first, the real column beneath it, nothing on
either row to tell them apart. Choosing the top one bound the question to a
column the board does not draw: the answer went somewhere invisible and the
question looked broken.

The rule is the one the filter panel already applies, for the same reason and
in the same words — see advFields, "a column taken off the board is not a
column to filter by". שם הפריט is exempt in both places: it is the item
itself and the board cannot hide it.

Only what is OFFERED changes. A question already bound to a built-in that was
hidden afterwards keeps working — hiding is reversible, the form outlives the
board's layout, and the server still accepts the key.
"""
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import main as cityos_main  # noqa: E402

SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_builder_offers_what_the_board_actually_has():
    """Driven harness: tests/frontend/form_offers_the_boards_status_columns.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "form_offers_the_boards_status_columns.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_import_really_does_hide_those_four():
    """The premise, read off the import rather than assumed. If this list ever
    stops hiding them, the duplicate "עדיפות" above stops being possible and
    the rule above stops being about anything — and the test that says so
    should be this one, not a puzzled reader a year from now."""
    i = cityos_main.__file__
    src = pathlib.Path(i).read_text(encoding="utf-8")
    j = src.index('"col_hidden": ["assignees", "status", "priority", "due"]')
    assert j > 0


def test_the_two_names_for_the_due_date_are_mapped_and_not_assumed():
    """col_hidden speaks the board's column keys, where the due date is
    `due`; a form field calls the same thing `due_date`. That is the only
    place the two vocabularies differ, and a lookup that silently misses
    just stops hiding the one column it was asked about."""
    i = SRC.index("const FORM_BUILTIN_COL_KEY=")
    block = SRC[i:SRC.index(";", i)]
    assert "due_date:'due'" in block, block


def test_a_status_column_is_never_what_this_drops():
    """The point of the change is more columns reachable from a form, not
    fewer. DERIVED_COLS is the only list that takes a column out, and a
    status column is not in it — nor is it in the server's own copy."""
    i = SRC.index("const DERIVED_COLS=")
    block = SRC[i:SRC.index(";", i)]
    assert "status" not in block, block
    assert "status" not in cityos_main.FORM_DERIVED_TYPES


def test_the_server_still_accepts_a_built_in_the_board_has_hidden(client, admin_id):
    """Hiding is reversible and a form outlives a board's layout, so this is
    a change to what is OFFERED and not to what is allowed. A form that
    already asks for a built-in since hidden must keep saving."""
    bid = client.post("/api/boards",
                      json={"actor_id": admin_id, "name": "לוח מיובא"}).json()["id"]
    try:
        fid = client.post(f"/api/boards/{bid}/forms?user_id={admin_id}",
                          json={"title": "ט"}).json()["id"]
        r = client.post(f"/api/forms/{fid}/components?user_id={admin_id}",
                        json={"kind": "question", "field_key": "priority",
                              "label": "עדיפות"})
        assert r.status_code == 200, r.text
        # …and now the board hides it
        cur = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
        u = client.patch(f"/api/boards/{bid}",
                         json={"actor_id": admin_id,
                               "col_hidden": ["priority"],
                               "columns": cur["columns"]})
        assert u.status_code == 200, u.text
        cid = r.json()["id"]
        e = client.patch(f"/api/forms/{fid}/components/{cid}?user_id={admin_id}",
                         json={"label": "דחיפות"})
        assert e.status_code == 200, e.text
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")
