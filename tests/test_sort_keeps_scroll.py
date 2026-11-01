"""מיון לפי עמודה שהגעת אליה בגלילה משאיר אותך באותו מקום.

"ביצוע מיון בעמודה שמופיע לאחר גלילה אופקית מקפיצה חזרה לצד הימני ביותר."

renderView always remembered the offset and put it back. The flaw was not
that it forgot — it was that an offset can only be applied as far as the
content allows. Assigning scrollLeft past the end is clamped silently, and a
board reaches its full width in stages: the rows are built, syncItemColWidth
sets the column widths, and fitLinkChipsSoon re-measures the connect cells
60ms after that. One frame of grace was not enough, and what was lost was
the DIFFERENCE — so the failure scaled with distance. A column near the
right-hand edge needs a small offset and always came back; a column you had
to scroll to find did not, and the board snapped to the right-hand edge.

Measured against the previous code under the same conditions: asking for
-1800 while the table was still 300px wide landed at -300 and stayed there,
while -80 landed exactly. That asymmetry is the whole of the reported bug.

The restore is re-applied until it takes now, bounded so a board that
genuinely cannot scroll that far settles instead of spinning. The harness
runs the real loop out of index.html against a stand-in element that clamps
the way a browser does and widens late — the clamp being the one part no
amount of reading the source can show you.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "sort_keeps_scroll.mjs"
INDEX = ROOT / "frontend" / "index.html"


def test_the_offset_survives_a_table_that_widens_late():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_sorting_goes_through_the_render_that_restores_it():
    """columnSort must not grow a path of its own that skips renderView —
    the restore lives there, and a second copy would be the one that drifts."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("function columnSort(e,key){")
    body = src[i:src.index("\n}", i)]
    assert "renderView()" in body, body
