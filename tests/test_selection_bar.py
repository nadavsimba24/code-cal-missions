"""The bulk-selection bar's menus must not outlive the selection.

The behaviour lives entirely in the browser, so it is exercised by running the
real renderSelBar out of index.html under node against a stub DOM — the same
approach test_assets.py already uses for the syntax check. The harness itself
reports which case failed.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "selection_bar.mjs"


def test_the_selection_bar_menus_follow_the_selection():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
