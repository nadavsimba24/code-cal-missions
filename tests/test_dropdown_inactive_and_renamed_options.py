"""A list column's inactive options are hidden from a new choice but stay on
the cells that hold them, and a renamed option follows into the rows already
on screen.

Hiding a button must not renumber the others, because toggleDropdown finds the
word by its index in col.options. A rename is rewritten on the server, but the
rows on screen were fetched before it, so the browser brings them into line
itself, sub-items included.

Driven harness: tests/frontend/dropdown_inactive_and_renamed_options.mjs.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "dropdown_inactive_and_renamed_options.mjs"


def test_inactive_options_and_a_rename_as_the_cell_popover_sees_them():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
