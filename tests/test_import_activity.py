"""The board's history, brought across with it.

monday's `activity_logs` is the board's own record of who changed what and when.
It lands here as the very rows the log already reads — AuditLog on the task — so
it shows up in the item's own לוגים tab and in the board-level log at once.
There is one log in this system, not two.

The part that matters most is the part that does nothing: an imported row offers
no undo. The change happened in monday, possibly a year ago, and reverting it
would write that value onto the item as it stands now — from a button that looks
exactly like every other undo on the page.
"""
import json

import main as cityos_main

H = {"X-CityOS-User": "1", "host": "localhost"}
WHEN = 1727259000000000          # µs since the epoch — 2024-09-25, monday's unit


def _log(event, pulse, when=WHEN, user="777", **data):
    data.setdefault("pulse_id", pulse)
    return {"id": str(when), "event": event, "user_id": user,
            "created_at": str(when), "data": json.dumps(data)}


def _resp(items, logs=None, users=None):
    board = {"id": "1", "name": "לוח", "groups": [{"id": "g1", "title": "פתוח"}],
             "items_page": {"cursor": None, "items": items}}
    if logs is not None:
        board["activity_logs"] = logs
    doc = {"data": {"boards": [board]}}
    if users is not None:
        doc["data"]["users"] = users
    return json.dumps(doc, ensure_ascii=False).encode()


def _item(iid, name, cols=None):
    return {"id": str(iid), "name": name, "group": {"id": "g1", "title": "פתוח"},
            "column_values": cols or []}


def _cv(cid, title, ctype, text=""):
    return {"id": cid, "type": ctype, "column": {"title": title}, "text": text}


def _upload(client, raw, name="היסטוריה"):
    r = client.post("/api/boards/import?actor_id=1", headers=H,
                    files={"file": ("response.json", raw, "application/json")},
                    data={"actor_id": 1, "name": name})
    assert r.status_code == 200, r.text
    return r.json()


def _imported_board(client, logs, users=None, cols=None):
    items = [_item(111, "פריט א", cols), _item(222, "פריט ב")]
    d = _upload(client, _resp(items, logs, users))
    board = client.get(f"/api/boards/{d['id']}?user_id=1", headers=H).json()
    return d, board


# ── it lands on the item, in the tab that already exists ────────────────────
def test_the_history_shows_in_the_item_s_own_log_tab(client, admin_id):
    me = client.get("/api/users", headers=H).json()[0]
    logs = [_log("update_column_value", 111, column_id="status", column_title="סטטוס",
                 previous_value={"label": {"text": "לביצוע"}},
                 value={"label": {"text": "בוצע"}}),
            _log("create_pulse", 111, when=WHEN - 60_000_000)]
    users = [{"id": "777", "name": me["name"], "email": me["email"]}]
    d, board = _imported_board(client, logs, users,
                               cols=[_cv("status", "סטטוס", "status", text="בוצע")])
    task = next(t for t in board["tasks"] if t["title"] == "פריט א")
    rows = client.get(f"/api/tasks/{task['id']}/activity", headers=H).json()["activity"]
    kinds = {r["action"] for r in rows}
    assert {"create", "update"} <= kinds, rows
    upd = next(r for r in rows if r["action"] == "update")
    assert upd["user_name"] == me["name"], "the author was matched to the account"
    assert "בוצע" in json.dumps(upd, ensure_ascii=False)
    assert d["report"]["activity"] == 2
    assert d["report"]["activity_from"] == "2024-09-25"


def test_the_same_rows_are_the_board_level_log(client, admin_id):
    logs = [_log("update_name", 222, name="שם חדש", previous_value="שם ישן")]
    d, board = _imported_board(client, logs)
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "monday"]
    assert len(mine) == 1 and mine[0]["task_title"] == "פריט ב"


# ── and it cannot be undone ─────────────────────────────────────────────────
def test_an_imported_row_offers_no_undo_and_refuses_one(client, admin_id):
    """The whole reason this needed building rather than mapping."""
    logs = [_log("update_column_value", 111, column_id="status", column_title="סטטוס",
                 previous_value={"label": {"text": "לביצוע"}},
                 value={"label": {"text": "בוצע"}})]
    d, board = _imported_board(client, logs,
                               cols=[_cv("status", "סטטוס", "status", text="בוצע")])
    task = next(t for t in board["tasks"] if t["title"] == "פריט א")
    row = next(r for r in client.get(f"/api/tasks/{task['id']}/activity",
                                     headers=H).json()["activity"]
               if r["action"] == "update")
    assert row["origin"] == "monday"
    assert row["can_undo"] is False, "an imported change must not offer an undo"
    # and the endpoint refuses one that arrives anyway — an old page, a script
    r = client.post(f"/api/activity/{row['id']}/undo", headers=H, json={"actor_id": admin_id})
    assert r.status_code == 400
    assert "מיובאת" in r.json()["detail"]


def test_a_change_made_here_still_undoes(client, admin_id):
    """The gate is about where the row came from, not about the board."""
    d, board = _imported_board(client, [])
    task = board["tasks"][0]
    client.patch(f"/api/tasks/{task['id']}", headers=H,
                 json={"actor_id": admin_id, "title": "שם אחר"})
    row = next(r for r in client.get(f"/api/tasks/{task['id']}/activity",
                                     headers=H).json()["activity"]
               if r["action"] == "update")
    assert row["can_undo"] is True and not row["origin"]
    assert client.post(f"/api/activity/{row['id']}/undo", headers=H,
                       json={"actor_id": admin_id}).status_code == 200


# ── who did it ──────────────────────────────────────────────────────────────
def test_an_author_with_no_account_keeps_their_name(client, admin_id):
    """The audit has nowhere else to put a person, and "מערכת" over a change a
    named colleague made is worse than no history at all."""
    logs = [_log("update_name", 111, name="ב", previous_value="א")]
    users = [{"id": "777", "name": "רעות אורן", "email": "reuto@example.com"}]
    d, board = _imported_board(client, logs, users)
    task = next(t for t in board["tasks"] if t["title"] == "פריט א")
    row = client.get(f"/api/tasks/{task['id']}/activity", headers=H).json()["activity"][0]
    assert row["user_name"] == "רעות אורן"
    assert row["user_id"] is None, "a name is not an account"


# ── what did not come, and why ──────────────────────────────────────────────
def test_history_of_an_item_outside_the_import_is_counted_not_guessed(client, admin_id):
    logs = [_log("update_name", 999, name="ב", previous_value="א"),   # no such item here
            _log("update_name", 111, name="ב", previous_value="א")]
    d, _ = _imported_board(client, logs)
    assert d["report"]["activity"] == 2, "the parser read both"
    assert d["report"]["activity_dropped"] == 0
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    assert len([r for r in rows if r.get("origin") == "monday"]) == 1, \
        "only the one whose item is here was written"


def test_events_with_no_counterpart_are_named(client, admin_id):
    logs = [_log("delete_pulse", 111), _log("create_update", 111),
            _log("update_name", 111, name="ב", previous_value="א")]
    d, _ = _imported_board(client, logs)
    rep = d["report"]
    assert rep["activity"] == 1
    assert dict(rep["activity_unmapped"]) == {"delete_pulse": 1, "create_update": 1}


def test_a_query_that_never_asked_says_so(client, admin_id):
    d, _ = _imported_board(client, None)      # no activity_logs key at all
    assert d["report"]["activity"] == 0
    assert d["report"]["activity_asked"] is False


def test_the_report_and_the_log_say_where_a_row_came_from():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "activity_asked" in src and "רשומות היסטוריה" in src
    assert "log-src" in src and "אין מה לבטל כאן" in src
    assert src.count("a.origin==='monday'") == 2, "the item tab and the board log"


def test_the_query_asks_for_the_history_and_for_who_did_it():
    import pathlib
    q = (pathlib.Path(__file__).resolve().parent.parent
         / "backend" / "monday_export.graphql").read_text(encoding="utf-8")
    assert "activity_logs(" in q
    assert "users {" in q, "without it every row reads מערכת"


# ── the history of an item that is gone ─────────────────────────────────────
# Found while looking for an imported item's log and finding one row that was
# not its own: "created item 'פריט 742'", dated three weeks before the item
# existed, from a board deleted weeks earlier. Destroying a board took its
# items, their comments and their links, and left all of their history behind —
# and ids are reissued, so the next item created into that id inherited it.
def test_destroying_a_board_takes_its_history_with_it(client, admin_id):
    from models import AuditLog
    from sqlalchemy.orm import Session
    d, board = _imported_board(client, [])
    task_ids = [t["id"] for t in board["tasks"]]
    with Session(cityos_main.engine) as db:
        before = db.query(AuditLog).filter(AuditLog.entity_type == "task",
                                           AuditLog.entity_id.in_(task_ids)).count()
    client.patch(f"/api/tasks/{task_ids[0]}", headers=H,
                 json={"actor_id": admin_id, "title": "שינוי כלשהו"})
    with Session(cityos_main.engine) as db:
        assert db.query(AuditLog).filter(AuditLog.entity_type == "task",
                                         AuditLog.entity_id.in_(task_ids)).count() > before
    assert client.delete(f"/api/boards/{d['id']}?user_id={admin_id}").status_code == 200
    r = client.delete(f"/api/trash/boards/{d['id']}?user_id={admin_id}")
    assert r.status_code in (200, 204), r.text
    with Session(cityos_main.engine) as db:
        left = db.query(AuditLog).filter(AuditLog.entity_type == "task",
                                         AuditLog.entity_id.in_(task_ids)).count()
    assert left == 0, f"{left} log rows outlived the board they described"


def test_the_sweep_clears_history_that_points_at_nothing_or_at_a_stranger(client, admin_id):
    """And leaves imported history alone — a monday change from 2024 written
    onto an item created today is the one thing that legitimately predates it."""
    from datetime import datetime, timedelta
    from models import AuditLog
    from sqlalchemy.orm import Session
    d, board = _imported_board(client, [])
    task = board["tasks"][0]
    with Session(cityos_main.engine) as db:
        t = db.query(cityos_main.Task).filter(cityos_main.Task.id == task["id"]).first()
        born = t.created_at
        db.add_all([
            # points at no item at all
            AuditLog(entity_type="task", entity_id=999_999, action="update",
                     field_name="title", created_at=born),
            # older than the item it names — a reissued id
            AuditLog(entity_type="task", entity_id=t.id, action="create",
                     field_name="item", new_value="פריט 742",
                     created_at=born - timedelta(days=21)),
            # imported, and older on purpose
            AuditLog(entity_type="task", entity_id=t.id, action="update",
                     field_name="title", created_at=born - timedelta(days=400),
                     origin={"source": "monday", "author": "רעות אורן"}),
        ])
        db.commit()
        orphans, wrong = cityos_main._sweep_stray_audit(db)
        assert orphans >= 1 and wrong >= 1, (orphans, wrong)
        rows = db.query(AuditLog).filter(AuditLog.entity_type == "task",
                                         AuditLog.entity_id == t.id).all()
    assert not any(r.new_value == "פריט 742" for r in rows), "a stranger's row survived"
    assert any(isinstance(r.origin, dict) and r.origin.get("source") == "monday"
               for r in rows), "imported history was swept away with the debris"


# ── two requests, one file ──────────────────────────────────────────────────
def test_the_history_can_arrive_in_a_response_of_its_own(client, admin_id):
    """Asking for the log beside 500 items does not fit: her 320-item board came
    back REQUEST_MAX_COMPLEXITY_EXCEEDED, cost 5,125,801 against monday's
    ceiling of 5,000,000. So it is fetched separately and both responses go into
    one file as a JSON array — the same mechanism that reads a long board's
    pages, used across fields rather than across pages. The board's name, its
    groups, its columns and its history are each taken from whichever response
    carries them.
    """
    items = [_item(111, "פריט א"), _item(222, "פריט ב")]
    first = {"data": {"boards": [{"id": "1", "name": "לוח",
                                  "groups": [{"id": "g1", "title": "פתוח"}],
                                  "items_page": {"cursor": None, "items": items}}]}}
    second = {"data": {"users": [{"id": "777", "name": "רעות אורן", "email": "r@example.com"}],
                       "boards": [{"id": "1", "activity_logs": [
                           _log("update_name", 111, name="ב", previous_value="א")]}]}}
    d = _upload(client, json.dumps([first, second], ensure_ascii=False).encode())
    rep = d["report"]
    assert rep["items"] == 2 and rep["groups"] == 1, "the items response was read"
    assert rep["activity"] == 1 and rep["activity_asked"] is True, "and so was the history"
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "monday"]
    assert len(mine) == 1
    assert mine[0]["user_name"] == "רעות אורן", "the users list came from the second response"
    assert mine[0]["can_undo"] is False


def test_the_order_of_the_two_responses_does_not_matter(client, admin_id):
    items = [_item(111, "פריט א")]
    hist = {"data": {"boards": [{"id": "1", "activity_logs": [
        _log("update_name", 111, name="ב", previous_value="א")]}]}}
    main = {"data": {"boards": [{"id": "1", "name": "לוח",
                                 "groups": [{"id": "g1", "title": "פתוח"}],
                                 "items_page": {"cursor": None, "items": items}}]}}
    d = _upload(client, json.dumps([hist, main], ensure_ascii=False).encode(), name="")
    assert d["report"]["items"] == 1 and d["report"]["activity"] == 1
    assert d["name"] == "לוח", "the name was taken from whichever response had it"


# ── what her real export turned up ──────────────────────────────────────────
def test_mondays_seventeen_digit_timestamp_is_read_as_the_date_it_is():
    """Its activity log counts in TENTHS of a microsecond — 10,000,000 to the
    second. 17913700065986844 is 2026-10-07; read as microseconds, which is what
    monday documents, it is the year 2537. Unrecognised, the whole range check
    fell through and every imported row was stamped with the moment of the
    import — a log saying everything happened at once, which is how this was
    noticed: "I am not getting the history"."""
    import import_monday as im
    assert im._log_when("17913700065986844").startswith("2026-10-07")
    assert im._log_when("1727259000000000").startswith("2024-09-25")   # plain µs still
    assert im._log_when("1727259000000").startswith("2024-09-25")      # ms
    assert im._log_when("1727259000").startswith("2024-09-25")         # seconds
    assert im._log_when("banana") == "banana" and im._log_when("") == ""


def test_a_move_between_groups_names_both_groups(client, admin_id):
    """monday states a move as two group objects, not as a value. Read as a
    value the row came out "changed group: — ← —" — a row that knows something
    happened and nothing else."""
    e = _log("move_pulse_into_group", 111,
             source_group={"id": "g1", "title": "פתוח"},
             dest_group={"id": "g2", "title": "סגור"})
    d, board = _imported_board(client, [e])
    task = next(t for t in board["tasks"] if t["title"] == "פריט א")
    row = client.get(f"/api/tasks/{task['id']}/activity", headers=H).json()["activity"][0]
    assert "פתוח" in json.dumps(row, ensure_ascii=False)
    assert "סגור" in json.dumps(row, ensure_ascii=False)


def test_a_batch_column_change_lands_on_every_item_it_names(client, admin_id):
    """One entry, many items, and no values at all: monday records that someone
    set this column across them. Taken as a single row it reached one item and
    the other 485 of hers reached none."""
    e = _log("batch_change_pulses_column_value", None, column_id="status",
             column_title="סטטוס", pulse_ids=[111, 222])
    d, board = _imported_board(client, [e],
                               cols=[_cv("status", "סטטוס", "status", text="בוצע")])
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "monday"]
    assert {r["task_title"] for r in mine} == {"פריט א", "פריט ב"}
    assert d["report"]["activity"] == 2, "one entry, two items, two rows"


def test_the_events_that_are_not_an_item_s_history_stay_out(client, admin_id):
    """Her board's log is half board housekeeping — subscriptions, owners,
    column settings, view changes. None of it is a change to an item, so none of
    it belongs in an item's log; it is counted and named instead."""
    logs = [_log("unsubscribe", 111), _log("change_column_settings", 111),
            _log("add_owner", 111), _log("board_view_changed", 111),
            _log("move_pulse_from_group", 111),          # the other half of a move
            _log("update_name", 111, name="ב", previous_value="א")]
    d, _ = _imported_board(client, logs)
    rep = d["report"]
    assert rep["activity"] == 1
    assert dict(rep["activity_unmapped"]) == {
        "unsubscribe": 1, "change_column_settings": 1, "add_owner": 1,
        "board_view_changed": 1, "move_pulse_from_group": 1}
