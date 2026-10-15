"""רק "טבלה ראשית" מוצעת, עד שהתצוגות האחרות יושלמו.

Temporary, and shaped so that undoing it is deleting lines rather than
reconstructing anything. VIEWS_WIP is filtered only where the screen OFFERS a
view — the tab strip, the mobile picker, the "+" popover — and never where a
board's own `views` setting is read for writing. A board that has קנבן turned on
still has it turned on in the database, so taking an id out of the set brings
that view back exactly as each board had it.

The one way this could have gone wrong is toggleBoardView, which writes the
setting back: had it started from the filtered list, the first toggle of any
view would have silently deleted every hidden one from the board. It starts from
boardViewsRaw instead, and the harness holds that down.

Forms is left alone deliberately. It renders as a .tab but it is not a view —
it opens a panel over the board rather than replacing it, which is why the
picker separates it with a rule — and no board has it turned on.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "views_in_progress_are_hidden.mjs"


def test_only_the_main_table_is_offered():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
