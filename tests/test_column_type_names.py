"""The column type formerly called "חשבונות" is called "קישור".

The word was already in use — the cross-board type's default title was
"קישור" — so the rename had to move that one along with it, or two different
column types would have been created under the same name. These read the real
COLUMN_TYPES, COL_DEFAULTS and FIELD_TYPE_HE out of index.html and check that
no two types share a name or a default title, this one included.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "column_type_names.mjs"


def test_the_column_types_are_named_and_none_of_them_collide():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
