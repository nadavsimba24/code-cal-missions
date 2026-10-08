"""Two things a number column was missing: which side its sign sits on, and
what a column of them comes to.

₪ used to trail the figure, the way Hebrew prose writes it. A column of figures
is not prose: trailing, the sign moved left and right with every change of
magnitude, so nothing in the column lined up. It leads now, like every other
currency sign the formatter knows, and a negative is -₪50 rather than ₪-50.

And each group now draws its totals under its own rows, in the columns they
belong to — summed over the rows the group is drawing, so a filtered board
totals what is on the screen rather than what is behind it.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "number_column.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_sign_leads_and_the_group_totals_its_rows():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_total_is_drawn_and_not_stored():
    """The same line the column's own settings are on: the cell keeps a number,
    everything else is presentation. A total that was written anywhere would
    have to be kept right through every edit, filter and import."""
    assert "function groupSums(tasks)" in SRC
    body = SRC[SRC.index("function groupSums(tasks)"):]
    body = body[:body.index("\n}\n") + 2]
    for forbidden in ("api(", "setCell", "custom_fields[", "st.board.tasks"):
        assert forbidden not in body, f"groupSums reaches for {forbidden}"


def test_the_totals_sit_outside_the_rows_that_can_be_dragged():
    """Item rows are a Sortable list keyed on the group's tbody. A total row
    inside it would be a row the drag could aim at, reorder, or drop onto."""
    assert "<tfoot><tr class=\"group-sum\">" in SRC
    assert "${groupSumRowHTML(g.tasks)}" in SRC
    tbody = SRC[SRC.index("<tbody data-gid="):SRC.index("${groupSumRowHTML(g.tasks)}")]
    assert "group-sum" not in tbody, "the totals row ended up inside the drag container"
