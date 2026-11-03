"""קבוצה שנערכה — שם או צבע — מתעדכנת מיד, בלי רענון.

"הוספתי קבוצה חדשה, אבל כשערכתי את השם ואת הצבע זה התעדכן רק ברענון."

Two things had to be true at once for the old name to survive that long.

`openBoard` paints a board it has already seen from memory before it asks the
server anything — that is what makes returning to a board instant — so
`saveGroup`, which sent the change and then called `openBoard`, repainted from
a copy that still held the old name. It never applied its own change anywhere
locally, although the PATCH had already succeeded and there was nothing left
to guess about.

The recheck that follows should then have caught it, and did not: `boardStamp`
counted the groups and the columns rather than looking at them. A rename, a
recolour, a move, a column retyped, a status option added — none of those
touches an item's `updated_at` and none changes a count, so the stamp said
"nothing changed", `revalidateBoard` returned without redrawing, and only a
hand reload of the page showed the new name. That half is pinned in
tests/test_board_cache.py, together with the companion rule it exposed: where
the stamp says the two copies agree, the one kept in the cache is the one ON
SCREEN, because that is the one carrying what was just applied to it.

This file pins the first half — the change is on the board the moment the
server accepts it — and the two cases that come with it: a refused creation
must add nothing, and a group left where it is must not ask the server to
reorder anything.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "group_edit_shows_at_once.mjs"
INDEX = ROOT / "frontend" / "index.html"


def test_an_edited_group_is_on_the_board_before_the_repaint():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_create_route_still_answers_with_the_group_it_made():
    """addGroup puts the server's own answer on the board, so the answer has to
    carry the group — id, name, position and colour, the shape the board holds.
    A route changed to answer {"ok": true} would leave the board without it."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    i = src.index('@app.post("/api/groups")')
    body = src[i:src.index("@app.", i + 10)]
    assert "return _group_dict(g)" in body, body
    d = src[src.index("def _group_dict(g):"):]
    d = d[:d.index("\n@app.")]
    for field in ('"id"', '"name"', '"position"', '"color"'):
        assert field in d, f"_group_dict no longer carries {field}"


def test_the_edit_is_applied_where_the_board_is_held():
    """Not a style point: openBoard paints from memory first, so a saveGroup
    that only talks to the server repaints the old name."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("async function saveGroup(")
    body = src[i:src.index("\n}", i)]
    assert "st.board.groups" in body, body
    assert "mine.name=name" in body and "mine.color=color" in body, body
