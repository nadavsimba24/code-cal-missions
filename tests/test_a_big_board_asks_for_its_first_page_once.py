"""The first page of a board too big to arrive whole is asked for once.

Past FILTER_CLIENT_MAX the board comes back with no rows — `tasks: []` and an
`item_count` — and the browser fetches fifty at a time from
POST /api/boards/{id}/items/query. The request for the FIRST fifty is made from
the render, because a board reaches the screen several ways (fetched, restored
from the cache, replaced under an open view by a revalidate, switched to from a
dashboard) and a hook in openBoard would cover one of them and be forgotten by
the next one added.

That is the right place for it and it is also the dangerous one. A render that
asks, an answer that renders and an answer that resets is a loop: the same
fifty rows, over and over, against the server, for as long as the board is
open. Nothing on screen looks wrong while it happens — which is why it is
pinned by counting requests rather than by looking at rows. It is the single
most expensive regression this change could reintroduce.

The other end of the same behaviour is a first page that never arrives. The
board carries no rows of its own up here, so a failed fetch leaves literally
nothing on screen: without a state of its own it reads as an empty board under
a toast that has already faded, and the only honest thing to show is a sentence
and a button. Retrying automatically is deliberately not it — a board the
server keeps refusing would hammer it once per render.

The behaviour itself is exercised in tests/frontend/a_big_board_asks_for_its_
first_page_once.mjs, which runs the real ensurePagedRows and the real Paged
over a stubbed api() and counts what goes out.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "a_big_board_asks_for_its_first_page_once.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_a_big_board_asks_for_its_first_page_once():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_first_page_is_asked_for_from_the_render_not_from_one_way_in():
    """Read off the source because the point is WHERE the call sits: in
    renderView, which every path that puts a board on screen ends in. A call
    moved into openBoard would pass the harness above and leave a board
    restored from the cache with no rows and nothing fetching them."""
    i = SRC.index("function renderView(")
    body = SRC[i:SRC.index("\nfunction ", i + 10)]
    assert "ensurePagedRows()" in body, "nothing asks for the rows when a board is drawn"
    # through a typeof, like every other optional neighbour renderView reaches
    # for — several harnesses run this function on its own
    assert "typeof ensurePagedRows==='function'" in body


def test_the_board_payload_still_says_how_big_it_is(client, admin_id):
    """The browser picks its mode from `item_count`, and up here that number is
    the only thing saying the board is not empty. This is the server half of
    the same sentence — the harness above assumes a board that arrived with no
    rows and a count; this is where that shape comes from."""
    bid = client.post("/api/boards", json={"actor_id": admin_id,
                                           "name": "לוח לעמוד ראשון"}).json()["id"]
    try:
        b = client.get(f"/api/boards/{bid}",
                       headers={"X-CityOS-User": str(admin_id)}).json()
        assert isinstance(b["item_count"], int) and b["item_count"] > 0
        assert "filter_client_max" in b
    finally:
        client.delete(f"/api/boards/{bid}", headers={"X-CityOS-User": str(admin_id)})
