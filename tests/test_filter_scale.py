"""ביצועים וקנה מידה — איפה הסינון רץ, וכמה שורות חוזרות בבקשה.

Two decisions, and each has a failure the other cannot catch.

**Where the filter runs.** Below the threshold the browser filters what it
already holds: instant, no request, and on a board of a few hundred rows
simply better. Above it the question goes to the server, which is the only
side that can answer for rows the browser was never handed. The number is
configuration — a board of 1,000 rows on a laptop is not the same board on a
five-year-old phone.

**How much comes back.** Never more than fifty. Not because the server cannot
build a bigger response, but because the browser cannot draw it, and the
request blocks everything behind it while it tries. Scrolling asks for the
next fifty under the filters already active — which is the part that is easy
to get wrong, because a page fetched under the previous filters looks exactly
like a page fetched under these.

And the one that is invisible until it bites: on a large board the server's
answer IS what the browser shows, so a filter the server does not know about
silently stops working at exactly the board size where filtering matters most.
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import main as cityos_main  # noqa: E402

SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
H = {"X-CityOS-User": "1", "host": "localhost"}


def _board(client, admin_id, n=0, name="לוח גדול"):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    for i in range(n):
        client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                        "title": f"פריט {i:04d}",
                                        "priority": "high" if i % 2 else "low"})
    return bid


def _q(client, bid, admin_id, **body):
    r = client.post(f"/api/boards/{bid}/items/query",
                    json={"user_id": admin_id, "today": "2026-10-18", **body})
    assert r.status_code == 200, r.text
    return r.json()


# ── the page ──────────────────────────────────────────────────────────────
def test_never_more_than_fifty_rows_in_one_answer(client, admin_id):
    bid = _board(client, admin_id, n=120)
    d = _q(client, bid, admin_id, filter={"operator": "and", "rules": []})
    assert len(d["items"]) == 50, len(d["items"])
    assert d["limit"] == 50 and d["has_more"] is True
    assert d["matched"] >= 120, d["matched"]


def test_a_caller_cannot_ask_for_the_whole_board_in_one_go(client, admin_id):
    bid = _board(client, admin_id, n=60)
    d = _q(client, bid, admin_id, filter={"operator": "and", "rules": []}, limit=100000)
    assert len(d["items"]) <= cityos_main.QUERY_PAGE_MAX


def test_scrolling_walks_the_pages_and_reaches_the_end(client, admin_id):
    bid = _board(client, admin_id, n=120)
    seen, off, guard = [], 0, 0
    while True:
        guard += 1
        assert guard < 20, "the walk does not end"
        d = _q(client, bid, admin_id, filter={"operator": "and", "rules": []}, offset=off)
        seen += d["item_ids"]
        if not d["has_more"]:
            break
        assert d["next_offset"] > off, "the next page starts where the last one did"
        off = d["next_offset"]
    assert len(seen) == len(set(seen)), "a row arrived on two pages"
    assert len(seen) == d["matched"], f"{len(seen)} rows walked, {d['matched']} matched"


def test_a_page_is_a_page_of_what_matched_not_of_the_board(client, admin_id):
    """The filter runs first and the page is cut out of the result — the
    other way round would answer "the first fifty rows, of which these
    match", which is a different and useless question."""
    bid = _board(client, admin_id, n=120)
    d = _q(client, bid, admin_id, filter={"operator": "and", "rules": [
        {"field": "priority", "operator": "eq", "value": "high"}]})
    assert d["matched"] == 60, d["matched"]
    assert len(d["items"]) == 50 and d["has_more"] is True
    d2 = _q(client, bid, admin_id, offset=50, filter={"operator": "and", "rules": [
        {"field": "priority", "operator": "eq", "value": "high"}]})
    assert len(d2["items"]) == 10 and d2["has_more"] is False


def test_the_small_board_answer_is_ids_and_is_capped(client, admin_id):
    """A board under the threshold gets the id list, because the browser
    already holds every row. The cap is the same threshold — past it, it
    should not have been asking this way."""
    bid = _board(client, admin_id, n=20)
    d = _q(client, bid, admin_id, filter={"operator": "and", "rules": []}, ids_only=True)
    assert "items" not in d and len(d["item_ids"]) == d["matched"]
    assert d["truncated"] is False
    assert len(d["item_ids"]) <= cityos_main.FILTER_CLIENT_MAX


# ── the toolbar filters, which the server has to know about ───────────────
def test_the_server_applies_the_toolbar_filters_too(client, admin_id, guinea_id):
    """On a large board the local pass is skipped, so a toolbar filter the
    server does not know about silently stops working at exactly the board
    size where filtering matters most."""
    bid = _board(client, admin_id, n=0)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    a = client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                        "title": "גשר הרצל", "priority": "high",
                                        "assignee_ids": [guinea_id]}).json()["id"]
    client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                    "title": "מדרכה ביאליק", "priority": "low"})
    empty = {"operator": "and", "rules": []}
    assert _q(client, bid, admin_id, filter=empty, q="הרצל")["item_ids"] == [a]
    assert _q(client, bid, admin_id, filter=empty, priority="high")["item_ids"] == [a]
    assert _q(client, bid, admin_id, filter=empty, people=[guinea_id])["item_ids"] == [a]


def test_the_toolbar_and_the_tree_narrow_together(client, admin_id):
    bid = _board(client, admin_id, n=0)
    client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                    "title": "גשר דחוף", "priority": "high"})
    client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                    "title": "גשר רגיל", "priority": "low"})
    d = _q(client, bid, admin_id, q="גשר", filter={"operator": "and", "rules": [
        {"field": "priority", "operator": "eq", "value": "high"}]})
    assert d["matched"] == 1


# ── the threshold ─────────────────────────────────────────────────────────
def test_the_threshold_is_configuration_not_an_opinion():
    assert cityos_main.FILTER_CLIENT_MAX == int(
        __import__("os").environ.get("FILTER_CLIENT_MAX", "1000") or 1000)
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("FILTER_CLIENT_MAX"' in src


def test_the_board_tells_the_browser_where_to_filter(client, admin_id):
    """The browser needs the number BEFORE it asks anything — it is the
    number that decides whether to ask at all."""
    bid = _board(client, admin_id, n=1)
    b = client.get(f"/api/boards/{bid}?user_id={admin_id}", headers=H).json()
    assert b["filter_client_max"] == cityos_main.FILTER_CLIENT_MAX


def test_the_browser_chooses_the_side_by_that_number():
    i = SRC.index("function filterMode()")
    assert "boardRowCount()>filterClientMax()" in SRC[i:i + 200]
    i = SRC.index("function filterClientMax()")
    assert "filter_client_max" in SRC[i:i + 220], "the browser invents its own threshold"


def test_a_large_board_shows_the_servers_answer_and_does_not_re_filter_it():
    """Re-running the local engine over a page would narrow a second time
    against whatever this browser happens to hold — the half the server was
    asked to replace."""
    i = SRC.index("function applyFilters(tasks){")
    body = SRC[i:SRC.index("\n}", i)]
    assert "Paged.on?Paged.rows" in body
    assert "if(Paged.on){" in body and "return out;" in body


def test_an_answer_to_an_old_question_cannot_overwrite_a_new_one():
    """Two requests in flight and the slower one landing last is the classic
    way a filtered board ends up showing the previous filter's rows."""
    i = SRC.index("const Paged = {")
    body = SRC[i:SRC.index("\n};", i)]
    assert "++this.seq" in body and "mine!==this.seq" in body
    assert "clearTimeout(_pagedTimer)" in SRC, "every keystroke fires a request"


def test_scrolling_near_the_bottom_asks_for_the_next_page():
    i = SRC.index("  bind(){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "addEventListener('scroll'" in body
    assert "scrollHeight" in body and "this.load(false)" in body
    assert "this.loading" in body, "scrolling fires a request per scroll event"
