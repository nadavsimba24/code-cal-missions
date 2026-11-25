"""Under a filter on a big board, each group counts its whole answer and its
missing rows are reached from the group itself.

Past the client threshold a filtered board's rows arrive fifty at a time,
group after group, through `Paged`. The header of each group counted the rows
that had arrived, so a group of 78 matches read "50" — or "20" — where monday
said 78; and the rows below the first page never loaded unless somebody
scrolled to the very bottom of the whole board, past groups drawn as empty
headers or not drawn at all.

The server now sends `group_matched` (pinned on the API side by
test_a_group_header_counts_the_whole_filtered_answer.py). This pins what the
browser does with it, running the real functions out of index.html:
groupCountKnown reads it; groupsOf draws a group whose matches are all still
on the server; groupMoreRowHTML gives the first incomplete group a «טען עוד»
button, later ones a plain waiting line, and nobody anything once there is no
more; the group name is escaped in the button's aria-label; and
Paged.watchMore never asks twice from the same "gid:held" footer — which is
what keeps an automatic load from walking the whole board down by itself.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_matched_footers.mjs"


def test_a_filtered_big_board_counts_each_group_and_offers_its_missing_rows():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
