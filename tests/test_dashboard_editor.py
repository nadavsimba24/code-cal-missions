"""The widget editor, drawn headless.

It exists because of one report — "אני לא רואה את האופציה לבחור עמודה" — and
the cause was not a missing picker. The default calculation is a count, a
count needs no column (R03: "ספירת רשומות אינה מושפעת מריק בעמודה"), so the
picker is genuinely absent until somebody chooses a sum or an average.

Absent and unexplained reads as broken. That is the rule this pins: where a
control is missing on purpose, the editor says why — and it says it in all
three places the editor can be empty, because all three looked identical
from the outside.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "dashboard_editor.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _editor_js():
    i = SRC.index("Dash.Editor = {")
    return SRC[i:SRC.index("\n};", i) + 3]


def test_the_editor_explains_every_control_it_leaves_out():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_three_emptinesses_are_three_different_sentences():
    """They looked identical from the outside — nothing at all — and they
    have three different fixes: choose another calculation, choose a source
    board, or add a numeric column to the board."""
    js = _editor_js()
    assert "ספירה סופרת רשומות ואינה זקוקה לעמודה" in js
    assert "לא נבחרו לוחות מקור" in js
    assert "אין בלוח עמודה מספרית" in js


def test_a_count_is_not_asked_to_map_a_column():
    """R03 — a count counts records, and a record is not a value in a
    column. The server refuses to validate one (see _dash_validate_mapping),
    so asking for it here would be asking for something that cannot be
    saved."""
    js = _editor_js()
    assert "const needsCol=['sum','avg'].includes(m.calc)" in js.replace('"', "'")
