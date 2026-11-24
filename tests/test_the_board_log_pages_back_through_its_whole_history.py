"""The board activity log reaches its whole history, a page at a time.

Pinned: GET /api/boards/{id}/activity pages with a keyset cursor
(`next_cursor` / `has_more`) over (created_at, id), and its `date` filter is a
range in SQL rather than a string match after the fact.

Why it matters: the endpoint used to fetch the newest limit*3 rows, filter
them in Python and stop — so only the newest 400 lines were ever reachable
(on a busy production board, the last two days of months of history), and
picking an older day in the date filter returned an empty log while the rows
sat in the table. Ties in created_at are real (a bulk edit writes many rows in
one instant), so the pages must neither skip nor repeat across a tie, and
rows the reader never sees (internal status-vocabulary fields) must not leave
a gap or end the paging early.

The modal's "טען עוד" button is pinned by tests/frontend/board_log_load_more.mjs.
"""
import pathlib
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

from sqlalchemy.orm import Session

from conftest import join_primary_env
import main as cityos_main
from models import AuditLog


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _board_with_history(client, admin_id, name):
    """A board whose one item has 30 dated lines and 6 hidden internal ones.

    Every stamp is in the past, so all of them sort after the board's own
    creation rows, and three pairs share a timestamp exactly to exercise ties.
    Returns (board_id, item_id, inserted row ids, the old day's date string).
    """
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט עם היסטוריה",
                                          "user_id": admin_id}).json()["id"]
    base = datetime.utcnow().replace(microsecond=0) - timedelta(days=2)
    old_day = base - timedelta(days=40)
    ids = []
    with Session(cityos_main.engine) as db:
        rows = []
        for i in range(30):
            when = base - timedelta(hours=i // 2 if i < 6 else i)   # 0,0,1,1,2,2 tie
            rows.append(AuditLog(entity_type="task", entity_id=tid, field_name="title",
                                 old_value=f"v{i + 1}", new_value=f"v{i}",
                                 changed_by=admin_id, action="update", created_at=when))
            if i % 5 == 0:
                # never shown to anyone — a page must reach past these
                rows.append(AuditLog(entity_type="task", entity_id=tid,
                                     field_name="col:status_key", old_value="a",
                                     new_value="b", changed_by=admin_id,
                                     action="update", created_at=when))
        for j in range(3):
            rows.append(AuditLog(entity_type="task", entity_id=tid, field_name="title",
                                 old_value=f"old{j}", new_value=f"old{j + 1}",
                                 changed_by=admin_id, action="update",
                                 created_at=old_day + timedelta(hours=j)))
        db.add_all(rows)
        db.commit()
        ids = [r.id for r in rows]
    return bid, tid, ids, old_day.strftime("%Y-%m-%d")


def _cleanup(ids):
    with Session(cityos_main.engine) as db:
        db.query(AuditLog).filter(AuditLog.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def _all_pages(client, bid, admin_id, limit, extra=""):
    seen, cursor, pages = [], None, 0
    while True:
        url = f"/api/boards/{bid}/activity?limit={limit}{extra}"
        if cursor:
            url += "&cursor=" + cursor
        r = client.get(url, headers=_h(admin_id))
        assert r.status_code == 200, r.text
        d = r.json()
        assert "activity" in d and "people" in d, "the existing keys must stay"
        seen += d["activity"]
        pages += 1
        assert pages < 100, "paging never ended"
        if not d["has_more"]:
            assert d["next_cursor"] is None
            return seen, pages
        assert d["next_cursor"], "has_more without a cursor to continue from"
        cursor = d["next_cursor"]


def test_paging_returns_every_line_once_and_in_order(client, admin_id):
    bid, _tid, ids, _day = _board_with_history(client, admin_id, "לוג מדופדף")
    try:
        whole = client.get(f"/api/boards/{bid}/activity?limit=1000",
                           headers=_h(admin_id)).json()
        assert whole["has_more"] is False
        paged, pages = _all_pages(client, bid, admin_id, limit=4)
        assert pages > 1, "the history should not fit in one page of 4"
        got = [x["id"] for x in paged]
        assert len(got) == len(set(got)), "a line came back on two pages"
        assert got == [x["id"] for x in whole["activity"]], \
            "paging lost, added or reordered lines compared with one big page"
        assert all(x["field"] != "col:status_key" for x in paged)
        # 30 recent + 3 old visible inserted lines, plus the board's own
        assert len(got) >= 33
    finally:
        _cleanup(ids)


def test_a_page_is_full_even_when_hidden_rows_fill_the_scan(client, admin_id):
    """A page only comes back short when the history has run out."""
    bid, _tid, ids, _day = _board_with_history(client, admin_id, "לוג עם שורות נסתרות")
    try:
        d = client.get(f"/api/boards/{bid}/activity?limit=10",
                       headers=_h(admin_id)).json()
        assert len(d["activity"]) == 10 and d["has_more"] is True
    finally:
        _cleanup(ids)


def test_the_date_filter_finds_a_day_older_than_the_first_page(client, admin_id):
    bid, _tid, ids, day = _board_with_history(client, admin_id, "לוג לפי תאריך")
    try:
        first = client.get(f"/api/boards/{bid}/activity?limit=5",
                           headers=_h(admin_id)).json()["activity"]
        assert all(not str(x["created_at"]).startswith(day) for x in first)
        d = client.get(f"/api/boards/{bid}/activity?limit=5&date={day}",
                       headers=_h(admin_id)).json()
        assert [x["new"] for x in d["activity"]] == ["old3", "old2", "old1"], \
            "the older day's lines were not found"
        assert all(str(x["created_at"]).startswith(day) for x in d["activity"])
        assert d["has_more"] is False and d["next_cursor"] is None
    finally:
        _cleanup(ids)


def test_paging_keeps_the_date_filter(client, admin_id):
    bid, _tid, ids, day = _board_with_history(client, admin_id, "לוג תאריך מדופדף")
    try:
        paged, pages = _all_pages(client, bid, admin_id, limit=1, extra=f"&date={day}")
        assert pages == 3
        assert [x["new"] for x in paged] == ["old3", "old2", "old1"]
    finally:
        _cleanup(ids)


def test_the_last_page_says_there_is_nothing_more(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוג קצר", "user_id": admin_id}).json()["id"]
    d = client.get(f"/api/boards/{bid}/activity", headers=_h(admin_id)).json()
    assert d["has_more"] is False and d["next_cursor"] is None


def test_a_malformed_date_or_cursor_is_a_400_not_a_500(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוג שגוי", "user_id": admin_id}).json()["id"]
    assert client.get(f"/api/boards/{bid}/activity?date=yesterday",
                      headers=_h(admin_id)).status_code == 400
    assert client.get(f"/api/boards/{bid}/activity?cursor=nonsense",
                      headers=_h(admin_id)).status_code == 400
    assert client.get(f"/api/boards/{bid}/activity/export?date=31-12-2026",
                      headers=_h(admin_id)).status_code == 400


def test_a_non_member_still_cannot_read_any_page(client, admin_id):
    bid, _tid, ids, _day = _board_with_history(client, admin_id, "לוג סגור")
    try:
        email = "log.pager.outsider@cityos.test"
        for u in client.get("/api/users").json():
            if u.get("email") == email:
                out = u["id"]; break
        else:
            out = client.post("/api/users", json={"actor_id": admin_id, "name": "זר לדפדוף",
                                                  "email": email, "role": "member"}).json()["id"]
        join_primary_env(client, out)
        cursor = client.get(f"/api/boards/{bid}/activity?limit=3",
                            headers=_h(admin_id)).json()["next_cursor"]
        assert cursor
        assert client.get(f"/api/boards/{bid}/activity",
                          headers=_h(out)).status_code == 403
        assert client.get(f"/api/boards/{bid}/activity?cursor={cursor}",
                          headers=_h(out)).status_code == 403
    finally:
        _cleanup(ids)


def test_the_modal_offers_load_more_with_the_same_filters():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    harness = (pathlib.Path(__file__).resolve().parent / "frontend"
               / "board_log_load_more.mjs")
    r = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
