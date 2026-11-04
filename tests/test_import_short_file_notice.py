"""The import report has to say, in the UI, that the FILE was short of the board.

The rule lives in tests/frontend/import_short_file_notice.mjs — it is a question
about rendered HTML, so it is asked of the real function in index.html. This is
the pytest that runs it with the rest of the suite.

Why it matters: a monday board of 2,069 items arrived as 2,000 and looked
finished. The backend now refuses a file past the row ceiling, which closes that
door — but a file that is short in the FILE, because a merge lost a page, is not
the backend's to refuse: `items_count` is monday's number, and a query narrowed
on purpose is legitimately smaller. So that one is reported, and the report has
to be impossible to read past.
"""
import pathlib
import shutil
import subprocess

import pytest


def test_the_report_says_how_many_items_the_file_is_missing():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = pathlib.Path(__file__).resolve().parent / "frontend" / "import_short_file_notice.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
