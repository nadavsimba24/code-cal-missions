"""«צור פריט בלוח …» — the item is one blank, and behind it the target board's fields.

"באוטומציה אני רוצה שזה יהיה צור פריט חדש ובלחיצה עליו ייפתח לי חלון שבוחר
את השדות שיהיה לפריט שנוצר ולא מיפוי בנפרד." The action that makes an item on
another board asked about that item in three blanks strung through the
sentence, the last a table of pairs read from the source side. It is said now
as «צור [פריט] בלוח [X]», and «פריט» opens a form of the target board's own
fields — group, name, each column — with what fills each one beside it.

Nothing the server stores changes: the form writes target_group, text and map,
the blanks the rule always had, so the engine, the save-time checks and every
existing rule read them as before. The browser half is the whole of it, and is
pinned by tests/frontend/automation_new_item_form.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_new_item_is_one_blank_with_the_target_board_s_fields_behind_it():
    """Driven harness: tests/frontend/automation_new_item_form.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_new_item_form.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
