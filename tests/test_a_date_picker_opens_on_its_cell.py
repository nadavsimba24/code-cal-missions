"""התאריכון נפתח על התא שנלחץ, לא בפינה השמאלית העליונה של המסך.

"לפעמים כשלוחצים בעמודת תאריך על התאריכון — הוא נפתח מצד שמאל העליון."

A date cell holds no `<input type="date">` of its own. One per cell is three
and a half thousand browser widgets in a single group of board 114, each with
its own shadow tree and each laid out whether or not anybody intends to open
it, so the value lives in a hidden input and dateCellPick builds the control
for the press that needs it.

It then called showPicker() on that control in the very next statement. An
element appended one statement earlier has no box: style and layout have not
run for it, it has no layout object, and the anchor rect the picker asks for
comes back empty — so Chrome placed the calendar at the top-left corner of the
screen, which on an RTL board is the far side from the cell that was pressed.

The press after it landed correctly, because that one found the widget still
in the cell and already measured. That is what made it "sometimes" rather than
always, and what kept it from being found.

What is pinned is the ordering, which is all the fix is: the widget is
measured before it is opened. A browser cannot show this any more clearly than
the harness does — the fault is between two calls, and the harness watches the
order they are made in.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "date_picker_opens_on_the_cell.mjs"


def test_the_picker_is_measured_before_it_is_opened():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
