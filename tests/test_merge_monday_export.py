"""The merge script is the last gate before a monday file is uploaded — it has
to be able to say the file is short.

It already refused a file whose last page still carried a cursor. What it could
not see was the arithmetic: a chain of pages that ends on a null cursor ran to
the end of SOMETHING, and that is not the same as every page in between being
present. A merge assembled by hand, or by a glob that missed a file, loses a
page out of the middle and still closes cleanly.

monday states the board's row count on page one, as `items_count`. It was in
the file and nothing compared it to anything — which is how a 2,069-item board
went in as 2,000 and came out looking finished. See
tests/test_import_monday_whole_board.py for the same rule on the server's side.

The script is run as a subprocess, because its exit code is the whole contract:
0 = ready to upload, 1 = a problem the import would hit.
"""
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "merge_monday_export.py"


def _page(items, cursor=None, board=None, items_count=None):
    """One response: page one carries the board around it, the rest do not."""
    if board is None:
        return {"data": {"next_items_page": {"cursor": cursor, "items": items}}}
    b = {"id": board, "name": "ערבויות", "items_page": {"cursor": cursor, "items": items}}
    if items_count is not None:
        b["items_count"] = items_count
    return {"data": {"users": [{"id": "1", "name": "רעיה", "email": "r@x.co.il"}],
                     "boards": [b]}}


def _items(lo, hi):
    return [{"id": str(i), "name": f"P-{i:05d}", "column_values": []} for i in range(lo, hi)]


def _run(tmp_path, doc, name="merged.json"):
    f = tmp_path / name
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f), "--check"],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def test_a_whole_file_passes_and_says_so(tmp_path):
    doc = [_page(_items(0, 500), cursor="c1", board="1", items_count=600),
           _page(_items(500, 600), cursor=None)]
    code, out = _run(tmp_path, doc)
    assert code == 0, out
    assert "600 פריטים מתוך 600 בלוח" in out, out


def test_a_merge_that_lost_a_middle_page_is_refused(tmp_path):
    """The gap is not at the end, so the last page's cursor is null and every
    check the script had before this one passes."""
    doc = [_page(_items(0, 500), cursor="c1", board="1", items_count=1500),
           # the page 500-999 is the one the merge dropped
           _page(_items(1000, 1500), cursor=None)]
    code, out = _run(tmp_path, doc)
    assert code == 1, out
    assert "חסרים 500" in out, out
    assert "1500" in out and "1000" in out, out


def test_the_file_that_lost_its_last_page_is_refused_by_both_checks(tmp_path):
    """The shape of the real one: 2,069 in monday, the last page never merged."""
    doc = [_page(_items(0, 500), cursor="c1", board="1", items_count=2069),
           _page(_items(500, 2000), cursor="c4")]
    code, out = _run(tmp_path, doc)
    assert code == 1, out
    assert "נעצר באמצע הלוח" in out, out       # the cursor is still open
    assert "חסרים 69" in out, out              # and the arithmetic agrees


def test_a_file_with_more_items_than_the_board_claims_is_not_refused(tmp_path):
    """items_count is read at export time and rows get added. More than it says
    is a board that grew, not a file that is broken."""
    doc = [_page(_items(0, 20), cursor=None, board="1", items_count=18)]
    code, out = _run(tmp_path, doc)
    assert code == 0, out


def test_a_file_that_never_asked_for_the_count_still_passes(tmp_path):
    """An older query did not ask for items_count. Absent, the script cannot do
    the arithmetic and must not invent a problem out of its absence."""
    doc = [_page(_items(0, 37), cursor=None, board="1")]
    code, out = _run(tmp_path, doc)
    assert code == 0, out


def test_the_multiple_of_500_guess_is_dropped_once_the_real_count_is_known(tmp_path):
    """A total that is an exact multiple of the page size used to earn a "worth
    checking in monday" warning. With items_count in the file that question has
    an answer, and the guess is noise beside it."""
    doc = [_page(_items(0, 500), cursor=None, board="1", items_count=500)]
    code, out = _run(tmp_path, doc)
    assert code == 0, out
    assert "כפולה מדויקת" not in out, out


def test_the_guess_is_still_made_when_there_is_no_count_to_check_against(tmp_path):
    doc = [_page(_items(0, 500), cursor=None, board="1")]
    code, out = _run(tmp_path, doc)
    assert code == 0, out
    assert "כפולה מדויקת" in out, out
