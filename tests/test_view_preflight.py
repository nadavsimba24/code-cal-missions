"""בדיקות מקדימות לפיתוח — חמשת המיפויים, ועל מה העבודה באמת חלה.

The chapter asks for five things to be verified against the existing
implementation before building on them, and for performance to be MEASURED
rather than guessed at: "אין להמציא יעד זמן בלי מדידת בסיס."

So there is no timing assertion in this file. A test that failed at 120ms and
passed at 119ms would be a number somebody invented, and it would fail on a
busy laptop while the thing it claims to protect was fine. The measurement
lives in scripts/bench_views.py, which prints and asserts nothing; the
baseline it produced is recorded at the bottom of this docstring.

What IS asserted here is the property those timings depend on being true:
that filtering, the counts and paging all work over the whole permitted board
and not over the page that happens to be loaded. That is a correctness rule
with a performance consequence, and it is the one that silently breaks.

Baseline, 2026-10-20, SQLite on the developer's machine, median of seven:

    board   items  cols   open   filter  +search  +sort   page 2   ids-only  one row
    23          9     5   30ms     29ms     28ms   30ms     16ms       15ms     12ms
    61        320    54   85ms     83ms     87ms   85ms     86ms       68ms     19ms
    strip (list views): 2.5ms on both

Read it as a shape, not as a target: the work tracks the board, the strip does
not track anything, and asking about one named row is the one question whose
cost does not grow with the board.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import BoardViewPrefs, SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list, _cfg  # noqa: E402
from test_view_hierarchy import _item, _query, _on, _h  # noqa: E402


# ── 1. the board roles map onto the permission model ───────────────────────
def test_the_three_board_roles_map_to_capabilities():
    """The views layer asks `role in (admin, editor)` and `role == admin`, so
    the three roles have to be exactly these three and mean what they mean."""
    caps = {r: cityos_main._board_caps(r) for r in ("admin", "editor", "viewer")}
    assert caps["admin"] >= {"view", "edit", "delete", "manage"}
    assert caps["editor"] == {"view", "edit"}
    assert caps["viewer"] == {"view"}
    assert cityos_main._board_caps("nonsense") == set()


# ── 2. filters and sort are represented the way a view stores them ─────────
def test_a_saved_filter_is_the_same_tree_the_query_endpoint_runs(client, admin_id):
    """The view stores the tree under `adv`; the endpoint reads it under
    `filter`. Same shape, so a saved cut can be handed straight over."""
    bid = _board(client, admin_id)
    _item(client, bid, admin_id, "פריט סימן")
    tree = _on("סימן")
    vid = _mk(client, bid, admin_id, "חיתוך", filters=dict(CUT, adv=tree)).json()["id"]

    stored = [v for v in _list(client, bid, admin_id) if v["id"] == vid][0]["filters"]["adv"]
    got = _query(client, bid, admin_id, filter=stored)
    assert any(i["title"] == "פריט סימן" for i in got["items"]), got["matched"]


def test_the_sorts_a_view_can_store_are_the_sorts_the_server_runs(client, admin_id):
    """A view that stored a sort the server does not know would open in an
    order it did not promise, silently."""
    bid = _board(client, admin_id)
    for key in ("due", "priority", "title"):
        vid = _mk(client, bid, admin_id, f"ממוין {key}",
                  filters=dict(CUT, sort=key)).json()["id"]
        v = [x for x in _list(client, bid, admin_id) if x["id"] == vid][0]
        assert v["needs_fix"] == [], (key, v["needs_fix"])
        assert _query(client, bid, admin_id, sort=key)["sort"] == key


# ── 3. sub-item columns are addressed by id ────────────────────────────────
def test_sub_item_values_are_read_by_column_id(client, admin_id):
    """A sub-item carries its values in the same custom_fields map, under the
    same ids. If it did not, a condition about a column would mean two
    different things depending on which row answered it."""
    bid = _board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id, "columns": [{"type": "text", "title": "הערה"}]},
                     headers=_h(admin_id))
    col = r.json()["columns"][-1]["id"]

    parent = _item(client, bid, admin_id, "הורה")
    kid = _item(client, bid, admin_id, "ילד", parent=parent)
    client.patch(f"/api/tasks/{kid}", json={"user_id": admin_id,
                                            "custom_fields": {col: "סימן"}},
                 headers=_h(admin_id))

    got = _query(client, bid, admin_id,
                 filter={"op": "and", "rules": [{"field": col, "op": "has", "v": "סימן"}]})
    row = next((i for i in got["items"] if i["id"] == parent), None)
    assert row is not None, "the sub-item's own column value did not answer"
    assert [s["title"] for s in row["subtasks"]] == ["ילד"]
    assert row["context_only"] is True


# ── 4. restore and refresh ─────────────────────────────────────────────────
def test_the_restore_path_exists_and_is_reversible(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    assert client.delete(f"/api/views/{vid}", headers=_h(admin_id)).status_code == 200
    assert [v["id"] for v in _list(client, bid, admin_id)] == []
    assert client.post(f"/api/views/{vid}/restore", json={"user_id": admin_id},
                       headers=_h(admin_id)).status_code == 200
    assert [v["id"] for v in _list(client, bid, admin_id)] == [vid]


def test_a_refresh_sees_what_somebody_else_saved(client, admin_id, guinea_id):
    """The refresh mechanism is the strip being re-read, so the strip has to
    be the live answer rather than what it was when the board opened."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    before = [v for v in _list(client, bid, guinea_id) if v["id"] == vid][0]

    _cfg(client, vid, admin_id, dict(CUT, sort="due"))
    after = [v for v in _list(client, bid, guinea_id) if v["id"] == vid][0]
    assert after["config_version"] == before["config_version"] + 1
    assert after["filters"]["sort"] == "due"


# ── 5. user preferences can be stored ──────────────────────────────────────
def test_both_preferences_round_trip(client, admin_id):
    bid = _board(client, admin_id)
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    assert client.put(f"/api/boards/{bid}/views/order",
                      json={"user_id": admin_id, "order": [b, a]},
                      headers=_h(admin_id)).status_code == 200
    assert client.put(f"/api/boards/{bid}/views/last",
                      json={"user_id": admin_id, "view_id": b},
                      headers=_h(admin_id)).status_code == 200
    with Session(cityos_main.engine) as db:
        row = (db.query(BoardViewPrefs)
                 .filter(BoardViewPrefs.board_id == bid,
                         BoardViewPrefs.user_id == admin_id).one())
    assert row.order == [b, a] and row.last_view_id == b


# ── the property the timings rest on ───────────────────────────────────────
@pytest.fixture
def wide(client, admin_id):
    """More rows than one page holds, so "the page" and "the board" differ.

    Created in the REVERSE of the order they sort in. The first version made
    them in ascending order, which meant the board's own position order and
    the sorted order were the same list — so the sort case passed with the
    sort removed entirely. A fixture that agrees with the thing it is testing
    proves nothing."""
    bid = _board(client, admin_id)
    for i in reversed(range(60)):
        _item(client, bid, admin_id, f"פריט סימן {i:02d}")
    _item(client, bid, admin_id, "אחר")
    return bid


def test_the_filter_runs_over_the_board_and_not_over_the_page(client, wide, admin_id):
    got = _query(client, wide, admin_id, filter=_on("סימן"), limit=10)
    assert len(got["items"]) == 10, "the page is a page"
    assert got["matched"] == 60, got["matched"]


def test_the_counts_are_of_the_board_and_not_of_the_page(client, wide, admin_id):
    got = _query(client, wide, admin_id, filter=_on("סימן"), limit=10)
    assert got["matched_own"] == 60
    assert got["total"] >= 61


def test_the_sort_spans_the_pages(client, wide, admin_id):
    """Page two continues page one rather than being ordered against itself."""
    one = _query(client, wide, admin_id, filter=_on("סימן"), sort="title", limit=10)
    two = _query(client, wide, admin_id, filter=_on("סימן"), sort="title",
                 limit=10, offset=10)
    a = [i["title"] for i in one["items"]]
    b = [i["title"] for i in two["items"]]
    assert a == sorted(a) and b == sorted(b), (a, b)
    assert max(a) <= min(b), (a[-1], b[0])
    assert not set(a) & set(b), "a row landed on two pages"
    # and it really is the SORT doing this, not the board's own order
    unsorted = [i["title"] for i in
                _query(client, wide, admin_id, filter=_on("סימן"), limit=10)["items"]]
    assert unsorted != a, "the board's order already matched — the case proves nothing"


def test_paging_covers_the_whole_answer_exactly_once(client, wide, admin_id):
    seen, offset = [], 0
    while True:
        got = _query(client, wide, admin_id, filter=_on("סימן"), sort="title",
                     limit=25, offset=offset)
        seen += [i["id"] for i in got["items"]]
        if not got.get("has_more"):
            break
        offset = got["next_offset"]
    assert len(seen) == 60 and len(set(seen)) == 60


def test_the_measurement_script_states_no_target():
    """"אין להמציא יעד זמן בלי מדידת בסיס." The script prints; it does not
    judge. A threshold in it would be a number somebody invented."""
    src = (ROOT / "scripts" / "bench_views.py").read_text(encoding="utf-8")
    assert "assert" in src, "it should still check the calls succeeded"
    for sign in ("< 100", "<100", "assert med", "assert lo", "threshold", "TARGET"):
        assert sign not in src, f"the benchmark invented a target: {sign}"
