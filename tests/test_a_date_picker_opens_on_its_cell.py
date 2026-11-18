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

What is pinned is the ordering, which is all the first fix was: the widget is
measured before it is opened. A browser cannot show this any more clearly than
the harness does — the fault is between two calls, and the harness watches the
order they are made in.

Two holes were left in that, and both read to a person as "sometimes" too:

* the widget is taken out of the row 200ms after it loses focus, so a picker
  somebody dismissed does not leave a control behind in every cell it was ever
  opened from. Pressing the button again is itself what blurs it — so press,
  press again, and the second calendar is opened against an element the armed
  removal then takes out of the document underneath it. Every press now disarms
  it: the removal is for a DISMISSED widget, and a cell being pressed is not a
  dismissal;

* forcing layout is a request, not a guarantee. A group off screen is skipped
  whole by content-visibility (see .group in the stylesheet), and a cell in one
  can be pressed in the frame it is scrolled into. If the rect still comes back
  empty the picker is not opened at all — the cell's own fallback control is
  drawn where the cell is, and a calendar in the corner is not.
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


def _pick():
    """The body of dateCellPick, which is the whole of what this file is about."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    fn = src[src.index("function dateCellPick(e){"):]
    return fn[: fn.index("\n/* one built-in")]


def test_the_anchor_is_measured_before_the_picker_is_opened():
    """The order is the fix. Measuring after the call measures nothing."""
    body = _pick()
    assert body.index("getBoundingClientRect()") < body.index("showPicker()"), body


def test_an_unmeasurable_cell_opens_no_picker_at_all():
    """A calendar in the corner of the screen is not a smaller problem than no
    calendar — it is the problem being reported, and the cell has a control of
    its own that is drawn in the right place."""
    body = _pick()
    assert "if(!box.width||!box.height)" in body, body
    guard = body[body.index("if(!box.width"):]
    guard = guard[: guard.index("\n")]
    assert "cc-fallback" in guard and "return" in guard, guard


def test_a_press_disarms_the_removal_it_armed():
    """Pressing the button blurs the widget, which arms the removal. Without
    the disarm the removal fires 200ms later, while the calendar that press
    opened is still on screen, and takes its anchor out of the document."""
    body = _pick()
    assert "clearTimeout(nat._rm)" in body, body
    assert "nat._rm=setTimeout(" in body, body
    assert body.index("clearTimeout(nat._rm)") < body.index("showPicker()"), body


def test_the_widget_is_still_built_on_the_press():
    """Not a regression test for the bug — a guard on the reason the bug is
    possible at all. The day a date cell holds a live `<input type="date">`
    this whole file is about nothing, and a board of fifteen date columns is
    slow again."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "nat=document.createElement('input')" in src
    head = src[src.index("function dateCellHTML("): src.index("function dateTyped(")]
    assert 'type="hidden"' in head, head
