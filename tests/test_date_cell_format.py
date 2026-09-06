"""A date column reads the same to everyone looking at the same board.

`<input type="date">` renders its day/month order from the *browser's* locale.
`<html lang="he" dir="rtl">` does not change it, and neither does anything else
on the page — so the two columns built on that input, and no other date in the
app, said 31/12/2026 to one person and 12/31/2026 to the next. A fix to that
order could only ever appear for the half of the users whose browser already
agreed with it, which is exactly how it was reported.

The cell now carries its own text. Runs the real fdate, dateCellHTML,
builtinCellHTML and customCellHTML out of index.html under node, the same way
tests/test_item_col_shrink.py does; the harness names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "date_cell_format.mjs"


def test_date_cells_do_not_leave_their_format_to_the_browser():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
