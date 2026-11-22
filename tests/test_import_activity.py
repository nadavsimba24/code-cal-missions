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


def _val(v):
    """A log row's value as the reader shows it. The audit stores values as
    JSON — that is how "ריק" stays empty rather than arriving as the word null
    — and Chat.transVal decodes them on the way to the screen, so a test that
    compared the raw text would be asserting about the encoding instead of
    about what anybody reads."""
    if isinstance(v, str) and v[:1] in '"[{':
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


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
    """…and asks for ALL of the users, which is not the same request.

    `users` asked bare answers with monday's default page of 200 and says
    nothing about the rest; this account has 318. The 118 it left out are
    ordinary named people, and they came back from an import as "could not be
    matched" — which reads like they are not in the system rather than like the
    export never asked about them. Both files that ask for users ask with a
    limit, because the half that is missing is the half nobody can see."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    for rel in ("backend/monday_export.graphql", "scripts/monday_history.py"):
        q = (root / rel).read_text(encoding="utf-8")
        asks = re.findall(r"users\(limit:\s*(\d+)\)", q)
        assert asks, f"{rel} asks for users without a limit — 200 of them"
        assert all(int(n) > 200 for n in asks), (rel, asks)
    q = (root / "backend" / "monday_export.graphql").read_text(encoding="utf-8")
    assert "activity_logs(" in q
    assert "users(limit:" in q, "without it every row reads מערכת"


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


# ── the twenty-seven kinds that used to go unmapped ─────────────────────────
# LOG_EVENTS mapped nine of the thirty-six kinds monday sends. It now also
# carries both halves of a group move, a batch move, a move between boards, an
# owner added or removed, and a sub-item that changed parents — measured on the
# two real exports, board 1495412381 went from 15,916 rows carried to 17,460
# (unmapped 3,020 → 1,407) and board 5738954426 from 151,797 to 154,752
# (unmapped 13,027 → 1,542).
#
# Two of the three rules below are about what is NOT carried, which is the half
# that gets lost: the second record of a move that only happened once, and an
# owner row whose entire content is a person the file cannot name. Both are
# counted and reported rather than dropped in silence — the standing rule of
# this importer.
def _move(pulse, uuid, when, into=True, src=("g1", "פתוח"), dst=("g2", "סגור")):
    """One half of a group move, as monday writes it: the two groups by name
    and `action_record_uuid` tying the halves together."""
    extra = {"action_record_uuid": uuid} if uuid else {}   # the 2021 rows carry none
    return _log("move_pulse_into_group" if into else "move_pulse_from_group",
                pulse, when=when,
                source_group={"id": src[0], "title": src[1]},
                dest_group={"id": dst[0], "title": dst[1]}, **extra)


def test_a_move_between_groups_comes_in_once_and_only_once(client, admin_id):
    """monday records a move twice — once from the group the item left and once
    from the group it joined, milliseconds apart, sharing an
    `action_record_uuid`. On her visits board 479 of the 565
    `move_pulse_from_group` entries are the second half of a move already
    carried.

    Both halves have to be read, because 432 older entries carry only one of
    them; and only one row may come out, because two rows say the item was
    moved and then moved back. So the count alone is not the assertion: a
    parser that dropped both halves and one that carried both would each be
    wrong in a way `activity == 1` cannot see. `activity_paired` is what tells
    the three apart — one row carried, one half recognised as its twin."""
    logs = [_move(111, "a-1", WHEN), _move(111, "a-1", WHEN + 30_000, into=False)]
    d, board = _imported_board(client, logs)
    rep = d["report"]
    assert rep["activity"] == 1, "one move, and the log says it happened twice"
    assert rep["activity_paired"] == 1, (
        "nothing was recognised as the other half of a move — either both "
        "halves came in, or both were dropped")
    assert dict(rep["activity_unmapped"]) == {}, rep["activity_unmapped"]

    # and the row that did come in is the move, with both groups named
    task = next(t for t in board["tasks"] if t["title"] == "פריט א")
    rows = client.get(f"/api/tasks/{task['id']}/activity", headers=H).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "monday"]
    assert len(mine) == 1 and mine[0]["field"] == "group"
    assert "פתוח" in json.dumps(mine[0], ensure_ascii=False)
    assert "סגור" in json.dumps(mine[0], ensure_ascii=False)


def test_two_different_moves_of_one_item_are_two_rows(client, admin_id):
    """The other side of the pairing, and the one that would be silently wrong:
    an item moved twice really was moved twice. Keyed on monday's own id for
    the action — plus the two groups — so two moves are never folded into one
    however close together they happened."""
    logs = [_move(111, "a-1", WHEN), _move(111, "a-1", WHEN + 30_000, into=False),
            _move(111, "b-2", WHEN + 10_000_000, src=("g2", "סגור"),
                  dst=("g1", "פתוח")),
            _move(111, "b-2", WHEN + 10_030_000, into=False, src=("g2", "סגור"),
                  dst=("g1", "פתוח"))]
    d, _ = _imported_board(client, logs)
    assert d["report"]["activity"] == 2, "two moves became one"
    assert d["report"]["activity_paired"] == 2


def test_an_old_move_that_carries_no_action_id_is_paired_by_what_it_says(
        client, admin_id):
    """monday only started writing `action_record_uuid` partway through; the
    older entries have nothing tying the two halves together but the moment and
    the two groups. Both are needed. Paired on the moment alone, two different
    moves made in the same tenth of a second — a drag through three groups, a
    rule moving an item on twice — would fold into one row and the board would
    be shown as having stopped somewhere it only passed through."""
    # a few milliseconds into a second, the way a real entry falls: the two
    # halves of one move land in the same tenth of it
    logs = [_move(111, None, WHEN + 1_000),
            _move(111, None, WHEN + 31_000, into=False),
            _move(111, None, WHEN + 11_000, src=("g2", "סגור"), dst=("g3", "ארכיון")),
            _move(111, None, WHEN + 41_000, into=False, src=("g2", "סגור"),
                  dst=("g3", "ארכיון"))]
    d, _ = _imported_board(client, logs)
    rep = d["report"]
    assert rep["activity"] == 2, "two moves in one instant became one"
    assert rep["activity_paired"] == 2, "the halves stopped pairing without an id"


def test_a_batch_move_pairs_the_same_way_and_lands_on_every_item(client, admin_id):
    """A batch move states its items and not the groups — `pulse_ids` and
    nothing else — and monday writes it in both halves exactly as it writes a
    single move. One row per item, and the second half paired away for each of
    them."""
    both = [_log("batch_move_pulses_into_group", None, action_record_uuid="c-3",
                 pulse_ids=[111, 222]),
            _log("batch_move_pulses_from_group", None, when=WHEN + 30_000,
                 action_record_uuid="c-3", pulse_ids=[111, 222])]
    d, _ = _imported_board(client, both)
    rep = d["report"]
    assert rep["activity"] == 2, "one move of two items, one row each"
    assert rep["activity_paired"] == 2, "the second half was carried as well"
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "monday"]
    assert {r["task_title"] for r in mine} == {"פריט א", "פריט ב"}


def test_an_owner_the_file_can_name_comes_in_on_the_item(client, admin_id):
    """Who was put on an item, and who was taken off it. The payload is the
    subscription shape — `pulse_id` is the item, `subscribed_id` is the person
    — and the account's user list is the only thing that turns that id into a
    name. The direction is the whole meaning of the row, so it is read off the
    event: added reads "— ← דנה", removed reads "דנה ← —"."""
    users = [{"id": "777", "name": "רעות אורן", "email": "r@example.com"},
             {"id": "42", "name": "דנה כהן", "email": "d@example.com"}]
    logs = [_log("add_owner", 111, subscribed_id="42"),
            _log("remove_owner", 222, when=WHEN + 60_000_000, subscribed_id="42")]
    d, board = _imported_board(client, logs, users)
    assert d["report"]["activity"] == 2, d["report"]
    assert d["report"]["activity_owner_nameless"] == 0

    rows = {r["task_title"]: r for r in
            client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
            if r.get("origin") == "monday"}
    added, removed = rows["פריט א"], rows["פריט ב"]
    assert _val(added["new"]) == "דנה כהן" and not added["old"], added
    assert _val(removed["old"]) == "דנה כהן" and not removed["new"], removed


def test_an_owner_the_file_cannot_name_is_counted_instead_of_carried(
        client, admin_id):
    """Not hypothetical: 8,505 of her meetings board's 8,585 `add_owner` rows
    name monday user 71490011, which the account's user list does not contain —
    a deleted integration account that returns nothing even asked for by id.
    The entire content of the row is who was put on the item, so one that
    cannot name them says "אחראי: — ← —" under a label promising a person.
    Carried, that is 8,505 identical empty lines across the board; counted, it
    is one number in the report that says exactly which history did not come
    and why.

    It is counted on its own and NOT named in activity_unmapped: the event is
    mapped and understood, and the gap has one identifiable fix — the export's
    `users` list did not carry that person."""
    users = [{"id": "777", "name": "רעות אורן", "email": "r@example.com"}]
    logs = [_log("add_owner", 111, subscribed_id="71490011"),
            _log("add_owner", 222, subscribed_id="71490011"),
            _log("update_name", 111, when=WHEN + 60_000_000, name="ב",
                 previous_value="א")]
    d, _ = _imported_board(client, logs, users)
    rep = d["report"]
    assert rep["activity"] == 1, "a nameless owner row was carried anyway"
    assert rep["activity_owner_nameless"] == 2, rep
    assert "add_owner" not in dict(rep["activity_unmapped"]), \
        "a mapped event was reported as one nobody understood"
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    assert not [r for r in rows if r.get("field") == "אחראי"], \
        "an empty אחראי row reached the log"


def test_the_rows_that_have_no_field_of_their_own_are_named_in_hebrew(
        client, admin_id):
    """Three of the things monday records have no field in this system: who was
    put on the item, which board it came from, and a sub-item that changed
    parents. A log row's field name is also what the log PRINTS when it has no
    translation for it — Chat.fieldHe knows title, status, priority, due_date,
    group and col:<id>, and returns the name itself for anything else — so a
    machine key would have put the English word "owner" into a Hebrew log 8,585
    times on rows nobody can correct from here. They are written as the Hebrew
    word they mean, and that is behaviour, not decoration."""
    users = [{"id": "777", "name": "רעות אורן", "email": "r@example.com"},
             {"id": "42", "name": "דנה כהן", "email": "d@example.com"}]
    logs = [_log("add_owner", 111, subscribed_id="42"),
            _log("move_pulse_into_board", 111, when=WHEN + 1_000_000,
                 source_board={"id": "9", "name": "פגישות 2024"},
                 dest_board={"id": "1", "name": "לוח"}),
            _log("move_subitem", None, when=WHEN + 2_000_000,
                 source_pulse_id=222, dest_pulse_id=111)]
    d, board = _imported_board(client, logs, users)
    assert d["report"]["activity"] == 3, d["report"]

    task = next(t for t in board["tasks"] if t["title"] == "פריט א")
    rows = client.get(f"/api/tasks/{task['id']}/activity", headers=H).json()["activity"]
    by_field = {r["field"]: r for r in rows if r.get("origin") == "monday"}
    assert set(by_field) == {"אחראי", "לוח", "תת-פריט"}, sorted(by_field)
    assert _val(by_field["אחראי"]["new"]) == "דנה כהן"
    # the other board, by name — the one thing no column on this board can say
    assert _val(by_field["לוח"]["old"]) == "פגישות 2024"
    # and the sub-item that moved, by the names of the two items, not their ids
    assert _val(by_field["תת-פריט"]["old"]) == "פריט ב"
    assert _val(by_field["תת-פריט"]["new"]) == "פריט א"


def test_the_log_reader_prints_a_field_name_it_does_not_know(client, admin_id):
    """The reason the three above are Hebrew, read off the reader itself. If
    fieldHe ever stopped falling through to the name, those rows would print as
    nothing at all — and nobody would go looking for the cause in a dictionary
    they never had to edit."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "frontend" / "index.html").read_text(encoding="utf-8")
    i = src.index("fieldHe(f){")
    body = src[i:src.index("\n", i)]
    assert body.rstrip().endswith("return f; },"), body
    assert "owner" not in body, "the field now has a translation and a key would do"


def test_the_events_that_are_not_an_item_s_history_stay_out(client, admin_id):
    """Her board's log is half board housekeeping — subscriptions, column
    settings, view changes — and a quarter of the subscribes sit a second away
    from an add_owner that already says the same thing better. None of it is a
    change to an item, so none of it belongs in an item's log.

    What is pinned is that they are counted and NAMED. Nothing is dropped in
    silence here: a kind nobody mapped has to be visible in the report, because
    that report is the only place anyone would ever learn the history was
    incomplete."""
    logs = [_log("subscribe", 111), _log("unsubscribe", 111),
            _log("change_column_settings", 111), _log("board_view_changed", 111),
            _log("delete_pulse", 111),
            _log("update_name", 111, when=WHEN + 60_000_000, name="ב",
                 previous_value="א")]
    d, _ = _imported_board(client, logs)
    rep = d["report"]
    assert rep["activity"] == 1
    assert dict(rep["activity_unmapped"]) == {
        "subscribe": 1, "unsubscribe": 1, "change_column_settings": 1,
        "board_view_changed": 1, "delete_pulse": 1}
    assert rep["activity_paired"] == 0 and rep["activity_owner_nameless"] == 0


# ── a history request that came back with the whole account ─────────────────
def test_the_history_of_the_other_boards_in_the_file_is_not_imported(client, admin_id):
    """`boards(ids: $boardId)` run with the variable unset is `boards(ids: null)`,
    which answers with every board in the account. It is easy to do to the
    history request in particular: it is the second one run, and the first one's
    variable does not carry over. Her merged file arrived that way — one board's
    items beside twenty-six boards' logs — and was refused as twenty-seven
    boards.

    The items say which board the file is about. The rest brought no items, and
    the first of them would otherwise have settled `activity_logs` for the whole
    import: the history of a board nobody is importing, hung on items that are
    not there."""
    items = [_item(111, "פריט א")]
    main = {"data": {"boards": [{"id": "1", "name": "לוח",
                                 "groups": [{"id": "g1", "title": "פתוח"}],
                                 "items_page": {"cursor": None, "items": items}}]}}
    hist = {"data": {"users": [{"id": "777", "name": "רעות אורן", "email": "r@example.com"}],
                     "boards": [
                         # listed before the one being imported, which is the
                         # order that used to decide whose log was read
                         {"id": "999", "activity_logs": [
                             _log("update_name", 555, name="ד", previous_value="ג")]},
                         {"id": "1", "activity_logs": [
                             _log("update_name", 111, name="ב", previous_value="א")]},
                         {"id": "888", "activity_logs": []},
                     ]}}
    d = _upload(client, json.dumps([main, hist], ensure_ascii=False).encode())
    rep = d["report"]
    assert rep["items"] == 1, rep
    assert rep["activity"] == 1, "this board's history, and only it"
    assert rep["other_boards"] == ["888", "999"], \
        "the boards that brought no items are named in the report, not dropped quietly"
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "monday"]
    assert len(mine) == 1 and mine[0]["user_name"] == "רעות אורן"


def test_a_file_of_one_board_says_nothing_about_other_boards(client, admin_id):
    d = _upload(client, _resp([_item(111, "פריט א")],
                              logs=[_log("update_name", 111, name="ב", previous_value="א")]))
    assert d["report"]["other_boards"] == []


def test_a_history_that_came_in_pages_is_imported_whole(client, admin_id):
    """`activity_logs` paginates by `page`, not by cursor: a board with more
    history than one request can carry is several responses in the same file.
    The merge used to take the log from the first response carrying one and drop
    every page after it — and nothing says so, because a log that stops partway
    reads like a board that went quiet."""
    items = [_item(111, "פריט א"), _item(222, "פריט ב")]
    main = {"data": {"boards": [{"id": "1", "name": "לוח",
                                 "groups": [{"id": "g1", "title": "פתוח"}],
                                 "items_page": {"cursor": None, "items": items}}]}}
    page = lambda *logs: {"data": {"boards": [{"id": "1", "activity_logs": list(logs)}]}}
    d = _upload(client, json.dumps([
        main,
        page(_log("update_name", 111, when=WHEN, name="ב", previous_value="א")),
        page(_log("update_name", 222, when=WHEN - 1, name="ד", previous_value="ג"),
             _log("update_name", 111, when=WHEN - 2, name="ו", previous_value="ה")),
    ], ensure_ascii=False).encode())
    assert d["report"]["activity"] == 3, "a page of history after the first was dropped"
    assert d["report"]["activity_asked"] is True


def test_the_same_page_of_history_handed_over_twice_is_not_twice_the_history(client, admin_id):
    """Pasting the same response in twice is a mistake made while assembling the
    array by hand, and it must not double the board's past."""
    items = [_item(111, "פריט א")]
    main = {"data": {"boards": [{"id": "1", "name": "לוח",
                                 "groups": [{"id": "g1", "title": "פתוח"}],
                                 "items_page": {"cursor": None, "items": items}}]}}
    hist = {"data": {"boards": [{"id": "1", "activity_logs": [
        _log("update_name", 111, when=WHEN, name="ב", previous_value="א")]}]}}
    d = _upload(client, json.dumps([main, hist, hist], ensure_ascii=False).encode())
    assert d["report"]["activity"] == 1


def test_a_file_whose_history_is_other_boards_says_so_instead_of_blaming_the_query(client, admin_id):
    """Her file, exactly: the history request ran without boardId, monday
    answered with the first 25 boards in the account — ordered newest first, and
    her board was older than all of them. So the file HAS history and none of it
    is hers, which the report must not report as "the query never asked".
    """
    main = {"data": {"boards": [{"id": "6257071922", "name": "לוח",
                                 "groups": [{"id": "g1", "title": "פתוח"}],
                                 "items_page": {"cursor": None,
                                                "items": [_item(111, "פריט א")]}}]}}
    hist = {"data": {"boards": [{"id": "999", "activity_logs": [
        _log("update_name", 555, name="ד", previous_value="ג")]}]}}
    d = _upload(client, json.dumps([main, hist], ensure_ascii=False).encode())
    rep = d["report"]
    assert rep["activity"] == 0 and rep["activity_asked"] is False
    assert rep["other_boards"] == ["999"], "the log that did come is named as another board's"
    assert rep["board_id"] == "6257071922", \
        "the report hands back the id the re-run needs as its variable"


# ── naming the people the account's user list left out ──────────────────────
def test_a_log_author_the_user_list_lost_is_named_by_the_board_s_own_cells(client, admin_id):
    """`users` answers with the account as it is now; the log is the board as it
    was. Her export came back with 200 users and a log written by 21 people,
    fifteen of whom were not on the list — 4,672 rows heading for "מערכת".

    Whoever was assigned work on this board is still named by the people cell
    they sit in, which is where the names come from when the list has none."""
    cell = {"id": "p", "type": "people", "column": {"title": "אחראי"},
            "text": "אביב שמש",
            "value": json.dumps({"personsAndTeams": [{"id": 34108305, "kind": "person"}]})}
    items = [_item(111, "פריט א", [cell])]
    raw = _resp(items, logs=[_log("update_name", 111, user="34108305",
                                  name="ב", previous_value="א")],
                users=[{"id": "777", "name": "מישהו אחר", "email": "x@example.com"}])
    d = _upload(client, raw)
    assert d["report"]["activity"] == 1
    assert d["report"]["activity_nameless"] == 0, "the cell named the author"
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    mine = [r for r in rows if r.get("origin") == "monday"]
    assert mine[0]["user_name"] == "אביב שמש"


def test_the_account_s_list_wins_over_a_cell_when_it_has_an_answer(client, admin_id):
    """The list carries the e-mail, which is the half that survives a rename —
    a cell carries a display name and nothing else."""
    cell = {"id": "p", "type": "people", "column": {"title": "אחראי"}, "text": "שם ישן",
            "value": json.dumps({"personsAndTeams": [{"id": 777, "kind": "person"}]})}
    raw = _resp([_item(111, "פריט א", [cell])],
                logs=[_log("update_name", 111, name="ב", previous_value="א")],
                users=[{"id": "777", "name": "רעות אורן", "email": "r@example.com"}])
    d = _upload(client, raw)
    rows = client.get(f"/api/boards/{d['id']}/activity", headers=H).json()["activity"]
    assert [r["user_name"] for r in rows if r.get("origin") == "monday"] == ["רעות אורן"]


def test_a_cell_whose_names_do_not_line_up_with_its_ids_names_nobody(client, admin_id):
    """The pairing is positional. A name holding a comma would shift every name
    after it onto the wrong person, and a log that names the wrong author is
    worse than one that names none."""
    cell = {"id": "p", "type": "people", "column": {"title": "אחראי"},
            "text": "כהן, יעל, אבי לוי",      # two people, three comma-separated names
            "value": json.dumps({"personsAndTeams": [{"id": 34108305, "kind": "person"},
                                                     {"id": 21615439, "kind": "person"}]})}
    raw = _resp([_item(111, "פריט א", [cell])],
                logs=[_log("update_name", 111, user="34108305", name="ב", previous_value="א")])
    d = _upload(client, raw)
    assert d["report"]["activity_nameless"] == 1, "nobody was guessed at"


def test_mondays_own_actors_are_the_system_and_not_a_missing_person(client, admin_id):
    """monday's automations write to the log under a negative id. "מערכת" is the
    truth about those, so they are not counted as people the file failed to
    name — 1,847 of her rows were this."""
    raw = _resp([_item(111, "פריט א")],
                logs=[_log("update_name", 111, user="-4", name="ב", previous_value="א")])
    d = _upload(client, raw)
    assert d["report"]["activity"] == 1 and d["report"]["activity_nameless"] == 0
