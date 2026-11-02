"""בוחרים עמודה באותה דרך בכל מקום שכלל מצביע על עמודה.

A rule names a column in three places: a condition ("רק אם «תחום» הוא …"), a
blank in its own sentence ("כאשר הערך ב«תחום» משתנה"), and a blank in an
extra action ("עדכן את «תחום» ל…"). Only the first asked the two questions
anybody actually has in mind — what KIND of column, and then which one. The
other two handed over every column on the board at once, which on a board
carrying thirty of them is not a question somebody wants to read, and which
meant a person met whichever version the rule they happened to be writing
used.

There is one picker now. Sharing it exposed the thing that is easy to get
wrong: WHICH columns each caller may offer is not the same question.
Listening to a column is wider than writing to one — מזהה פריט, מועד יצירה
and יוצר הרשומה are derived from the item and store nothing, so a rule
pointed at one would write a cell the board never reads. That was decided by
sniffing the field key for an `a_` prefix, and an extra action's field is
keyed plainly "column" with no prefix — so those three WERE offered there as
somewhere to write to. The caller says so now instead of the key implying it.

Nothing moved on the server: what a blank stores is still the column's id.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _src():
    return INDEX.read_text(encoding="utf-8")


def test_there_is_exactly_one_column_picker():
    """Two would be two behaviours a month from now — which is how the
    condition and the blanks came to disagree in the first place."""
    src = _src()
    assert src.count("colPickOpen(anchor,cols,onPick,empty){") == 1
    # and all three callers go through it
    assert src.count("this.colPickOpen(") == 4, \
        "a caller was added or removed without this test being looked at"


def test_the_blanks_no_longer_build_a_flat_column_menu():
    """The regression this guards: a column blank falling through to the
    generic value menu again, which lists every column at once."""
    src = _src()
    for fn, after in (("async pickField(e,key){", "\n  /* ---- איזו עמודת סטטוס"),
                      ("async pickActValue(e,i,key){", "\n  setActValue(")):
        body = src[src.index(fn):]
        body = body[:body.index(after)]
        assert "if(f.type==='column'){" in body, fn
        i = body.index("if(f.type==='column'){")
        j = body.index("this._optionsFor(")
        assert i < j, f"{fn}: the column branch must come before the generic menu"


def test_writing_to_a_column_is_a_narrower_list_than_listening():
    """Said by the caller, not read off the key — an extra action's field is
    keyed "column" with no a_ prefix, and that is exactly how the three
    derived columns used to be offered as somewhere to write."""
    src = _src()
    fn = src[src.index("  _blankCols(fkey,write){"):]
    fn = fn[:fn.index("\n  },")]
    assert "'item_id','created_at','created_by'" in fn, fn
    assert "(write===undefined)?/^a_/" in fn, fn
    assert "'mirror','connect','formula'" in fn, fn
    # the extra action is the caller that has to say it
    assert "this._blankCols(f.key,true)" in src


def test_the_picker_offers_a_way_back():
    """Picking the wrong kind is a thing somebody does, and without this the
    only way out is to dismiss the menu and find the blank again."""
    src = _src()
    fn = src[src.index("  colPickType(e,type){"):]
    fn = fn[:fn.index("\n  },")]
    assert "colPickBack" in fn, fn
    assert "colTypeHe(type)" in fn, fn


def test_the_two_questions_are_asked_everywhere(client, admin_id):
    """Driven harness: tests/frontend/automation_column_blank.mjs.

    Verified to fail: take the f.type==='column' branch out of pickField and
    seven cases go red.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_column_blank.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
