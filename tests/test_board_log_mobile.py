"""מסך לוג הלוח במובייל — שורה של שש עמודות הופכת לשתי שורות.

The log row was built for a wide dialog: when, who, which item, which column,
what changed, undo — six things side by side wanting some 750px. A phone has
half that, so everything shrank to its minimum at once and the two value pills,
the reason anyone opens a log, were crushed to an ellipsis first: you could see
that something changed and not what.

The row wraps now, and the wrapping needed something to wrap onto — the field,
the change and the undo share one wrapper. On a wide screen that wrapper is
display:contents, so it is not a box at all and the desktop row is unchanged to
the pixel; on a phone it becomes the second line.

The harness reads the rules out of index.html under node, checking that every
one of them lives inside the max-width:820px block, and names the failing case.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "board_log_mobile.mjs"


def test_the_log_row_becomes_two_lines_on_a_phone():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
