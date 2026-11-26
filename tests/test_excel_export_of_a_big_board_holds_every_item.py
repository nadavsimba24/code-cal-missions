"""The Excel export of a big board holds every item, not the first page.

Past the client threshold a board's rows arrive fifty at a time through
`Paged`, and the export is built from the rows on screen — so opening a board
and exporting straight away wrote a file of 50 items over a board of hundreds.
The export now pulls every remaining page down (Paged.loadAll) before it
builds the grid, and only falls back to asking about a short file when that
load did not finish.

This drives tests/frontend/excel_export_loads_the_whole_board_first.mjs, which
runs the real Paged out of index.html against a fake /items/query.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "excel_export_loads_the_whole_board_first.mjs"


def test_exporting_a_big_board_loads_the_whole_board_before_the_file_is_built():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
