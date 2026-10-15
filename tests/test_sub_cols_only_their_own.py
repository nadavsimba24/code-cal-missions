"""Sub-items that share no column with the item show their own, not the item's.

board.sub_cols is the shared subset and board.sub_only is what lives on sub-item
rows alone. An empty shared subset read as "never configured — inherit every
item column" is right for a stale list and wrong for a sub-item board whose
columns are its own by design, which is what a monday import now produces: the
sub-items showed a dozen empty item columns in front of the ones with values in
them.

The server's half — deriving sub_only from the file — is in
tests/test_import_monday_subitem_columns.py and tests/test_import_subitems.py.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "sub_cols_only_their_own.mjs"


def test_the_sub_item_header_is_the_sub_items_own():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
