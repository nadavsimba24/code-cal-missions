"""Every change in the status and priority columns reaches the log.

The log was written from the TaskStatus / Priority enum, and the board does not
speak in those. A board's vocabulary maps onto them, several entries to one — the
default statuses put both "תקוע" and "הקפאה" on `on_hold` — so writing the log
from the enum had two consequences, and between them they could make a change
vanish:

  · moving an item between two statuses that share an enum value wrote NO row
    at all, because the enum had not moved;
  · and whenever a board-defined status was picked, the row named its base
    ("תקוע") rather than the status somebody actually chose ("הקפאה") — a log
    that reads as though only the original status ever existed.

On top of that, /api/tasks/{id}/move — the kanban drag, the sub-item status cell
and the console `move` command — wrote the status straight onto the column and
audited nothing whatsoever.

The log is now written from the vocabulary key the cell shows, once per column,
after the whole edit has landed. A rule's own change is written too, with no user
behind it, which the log renders as "מערכת".
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Task, AuditLog

FROZEN = {"status_key": "x_frozen", "status_label": "הקפאה", "status_color": "#FD5AC3"}


def _board(client, admin_id, name="לוח יומן"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _rows(tid, field="status"):
    with Session(cityos_main.engine) as db:
        return [(r.old_value, r.new_value, r.changed_by)
                for r in (db.query(AuditLog)
                            .filter(AuditLog.entity_type == "task", AuditLog.entity_id == tid,
                                    AuditLog.field_name == field)
                            .order_by(AuditLog.id).all())]


def _cf(tid):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        v = t.status
        return ((v.value if hasattr(v, "value") else v), dict(t.custom_fields or {}))


def _set(client, tid, admin_id, **body):
    return client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json=body)


# ── the change that used to disappear ───────────────────────────────────────

def test_moving_between_two_statuses_that_share_an_engine_value_is_logged(client, admin_id):
    """"תקוע" and "הקפאה" are both `on_hold`. The enum does not move; the board
    plainly shows something different, so the log has to say so."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, status="on_hold")                      # תקוע
    before = len(_rows(tid))
    r = _set(client, tid, admin_id, status="on_hold", custom_fields=dict(FROZEN))   # הקפאה
    assert r.status_code == 200, r.text
    rows = _rows(tid)
    assert len(rows) == before + 1, "the change wrote no log row at all"
    assert rows[-1][0] == "on_hold" and rows[-1][1] == "x_frozen"


def test_a_board_defined_status_is_logged_by_its_own_name(client, admin_id):
    """Not by the engine value it rides on, which is a different status."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, status="done")
    _set(client, tid, admin_id, status="on_hold", custom_fields=dict(FROZEN))
    rows = _rows(tid)
    assert rows[-1][:2] == ("done", "x_frozen"), \
        f"logged the base instead of the chosen status: {rows[-1]}"


def test_one_row_per_change_not_one_per_bookkeeping_field(client, admin_id):
    """Choosing a board status writes key+label+colour into custom_fields. Those
    rows are implementation detail and stay hidden; the status row is the one."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, status="on_hold", custom_fields=dict(FROZEN))
    assert len(_rows(tid)) == 1
    acts = client.get(f"/api/tasks/{tid}/activity?user_id={admin_id}").json()["activity"]
    shown = [a for a in acts if (a.get("field") or "").startswith("col:status")]
    assert shown == [], f"the bookkeeping leaked into the log: {shown}"


def test_the_same_holds_for_a_board_defined_priority(client, admin_id):
    """The priority column has the identical machinery, so it has the identical
    hole: a board priority sharing `high` logged nothing."""
    bid = _board(client, admin_id)
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "priorities": [
        {"key": "high", "label": "גבוהה", "color": "#fdab3d"},
        {"key": "x_blocker", "label": "חוסם", "color": "#FD5AC3", "base": "high"},
    ]})
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, priority="high")
    before = len(_rows(tid, "priority"))
    _set(client, tid, admin_id, priority="high",
         custom_fields={"priority_key": "x_blocker", "priority_label": "חוסם",
                        "priority_color": "#FD5AC3"})
    rows = _rows(tid, "priority")
    assert len(rows) == before + 1, "a priority change on the same base wrote no row"
    assert rows[-1][:2] == ("high", "x_blocker")


# ── the endpoint that audited nothing ───────────────────────────────────────

def test_a_status_set_through_move_is_logged(client, admin_id):
    """The kanban drag goes through /move, which used to audit nothing."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, status="in_progress")
    before = len(_rows(tid))
    r = client.post(f"/api/tasks/{tid}/move", json={"status": "done", "actor_id": admin_id})
    assert r.status_code == 200, r.text
    rows = _rows(tid)
    assert len(rows) == before + 1, "dragging a card on the kanban logged nothing"
    assert rows[-1][:2] == ("in_progress", "done")


def test_move_to_a_board_defined_status_carries_its_label_and_is_logged(client, admin_id):
    """It also used to write the raw string onto the column and leave the old
    board label in custom_fields, so the cell painted a status it did not have."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/move", json={"status": "x_frozen", "actor_id": admin_id})
    status, cf = _cf(tid)
    assert status == "on_hold" and cf.get("status_key") == "x_frozen"
    assert _rows(tid)[-1][:2] == ("", "x_frozen")

    # ...and moving off it clears the label rather than leaving it behind
    client.post(f"/api/tasks/{tid}/move", json={"status": "done", "actor_id": admin_id})
    status, cf = _cf(tid)
    assert status == "done" and "status_key" not in cf and "status_label" not in cf
    assert _rows(tid)[-1][:2] == ("x_frozen", "done")


def test_move_accepts_an_engine_value_the_board_does_not_offer(client, admin_id):
    """The sub-item status cell cycles through todo/in_progress/review/done, and
    the default vocabulary offers neither `todo` nor `review`."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, status="done")
    r = client.post(f"/api/tasks/{tid}/move", json={"status": "review", "actor_id": admin_id})
    assert r.status_code == 200, r.text
    assert _cf(tid)[0] == "review"
    assert _rows(tid)[-1][:2] == ("done", "review")


def test_move_leaves_an_unknown_status_alone(client, admin_id):
    """Same tolerance the PATCH endpoint has — and nothing to log."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, status="done")
    before = _rows(tid)
    client.post(f"/api/tasks/{tid}/move", json={"status": "לא סטטוס", "actor_id": admin_id})
    assert _cf(tid)[0] == "done"
    assert _rows(tid) == before


# ── a rule's own change ─────────────────────────────────────────────────────

def test_a_rule_that_sets_a_status_is_logged_as_the_system(client, admin_id):
    """It belongs in the log like anybody's change — but not under the name of
    whoever's edit tripped the rule, which would be a lie about who decided."""
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                json={"recipe_id": "created_set_status",
                      "config": {"a_status": "done"}, "is_active": True})
    tid = _item(client, bid, admin_id, "פריט שהכלל נוגע בו")
    assert _cf(tid)[0] == "done", "the rule did not run"
    rows = _rows(tid)
    assert rows, "the rule's own status change never reached the log"
    assert rows[-1][:2] == ("", "done")
    assert rows[-1][2] is None, "the rule's change was attributed to a person"


# ── undo still understands the row ──────────────────────────────────────────

def test_undoing_a_board_defined_status_change_works(client, admin_id):
    """The row holds a vocabulary key now, which is not a TaskStatus value, so
    undo cannot go straight at the enum any more."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, status="done")
    _set(client, tid, admin_id, status="on_hold", custom_fields=dict(FROZEN))
    log_id = [a for a in client.get(f"/api/tasks/{tid}/activity?user_id={admin_id}").json()["activity"]
              if a.get("field") == "status"][0]["id"]
    r = client.post(f"/api/activity/{log_id}/undo", json={"actor_id": admin_id})
    assert r.status_code == 200, r.text
    status, cf = _cf(tid)
    assert status == "done", "undo did not put the status back"
    assert "status_key" not in cf, "undo left the board label behind"


def test_undoing_back_to_undecided_restores_the_grey_default(client, admin_id):
    """An empty old value means nobody had chosen, and that is restorable too."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _set(client, tid, admin_id, status="done")        # "" → done
    log_id = [a for a in client.get(f"/api/tasks/{tid}/activity?user_id={admin_id}").json()["activity"]
              if a.get("field") == "status"][0]["id"]
    r = client.post(f"/api/activity/{log_id}/undo", json={"actor_id": admin_id})
    assert r.status_code == 200, r.text
    status, cf = _cf(tid)
    assert cf.get("status_unset") is True and status == "todo"
