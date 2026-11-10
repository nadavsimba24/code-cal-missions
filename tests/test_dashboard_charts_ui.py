"""The five chart types, drawn headless out of index.html.

The harness runs the REAL `Charts` object, so what is asserted is the code
that ships. What it is for is the geometry that goes wrong in a way that
still looks like a chart: an axis that does not reach zero turns a 4%
difference into a doubling, a line interpolated over a missing period draws a
trend through months that have no answer, and a pie over mixed signs draws a
share of a total that is not a total.

R08 runs through all of it — every element a focusable control with a name,
a data table carrying the same numbers, and no series told apart by colour
alone.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "dashboard_charts.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _charts_js():
    i = SRC.index("const Charts = {")
    return SRC[i:SRC.index("/* ---- עורך הווידג׳ט (DASH-11) ----", i)]


def test_every_chart_type_draws_what_the_spec_requires():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_charts_invent_no_colour_of_their_own():
    """Invariant 7 — the palette comes from the server (the board's status
    colours, then the shared list), so the renderer holds no colour of its
    own.

    One exception, and it is the file's own convention in seventy-odd other
    places: white for text drawn ON a saturated fill — the percentage inside
    a pie slice. It is not a palette choice, it is the only legible contrast
    against every colour the palette contains.
    """
    import re
    js = _charts_js()
    found = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,6}", js)}
    assert found <= {"#fff"}, f"a colour was hardcoded in the renderer: {sorted(found - {'#fff'})}"


def test_a_chart_element_is_a_control_and_not_a_shape():
    """R08 — "כל פעולה תומכת במקלדת ובמיקוד נראה; לפקדים שמות נגישים", and
    DASH-22.3 — "פתיחת פירוט במקלדת ובמגע"."""
    js = _charts_js()
    assert 'role="button" tabindex="0"' in js
    assert "aria-label=" in js
    assert "event.key==='Enter'" in js


def test_information_is_not_left_to_hover_alone():
    """R08 — "מידע מלא במגע ובמיקוד ולא ב־hover בלבד". The <title> is the
    tooltip; the aria-label is what focus and touch reach."""
    js = _charts_js()
    assert "<title>" in js and "aria-label=" in js
