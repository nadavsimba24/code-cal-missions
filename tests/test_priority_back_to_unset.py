"""The priority column gets the way back to «טרם הוגדר» too.

The status column got this first; the priority column beside it has the
identical mechanism and had the identical gap, which is what this closes. Every
item starts on the grey default — nobody has chosen a priority, and the cell
says so — but afterwards the only things sayable were the five engine values and
the board's own priorities, none of which means "nobody has decided". So the
first click was irreversible, and the board log read as a decision somebody made
on purpose.

An explicit null says it. The engine value returns to `medium`, exactly where a
new item's priority sits, so the sort and the charts read a cleared item as
unremarkable rather than as whatever it was before.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Task, AuditLog


def _board(client, admin_id, name="לוח עדיפות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title="פריט"):
    """No priority named, which is how a new item arrives from the board."""
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _row(tid):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        v = t.priority
        return ((v.value if hasattr(v, "value") else v), dict(t.custom_fields or {}))


def test_a_new_item_starts_undecided(client, admin_id):
    bid = _board(client, admin_id)
    prio, cf = _row(_item(client, bid, admin_id))
    assert cf.get("priority_unset") is True
    # the engine value is the neutral one all along — only the flag says "unchosen"
    assert prio == "medium"


def test_a_priority_can_be_put_back_to_undecided(client, admin_id):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": "critical"})
    prio, cf = _row(tid)
    assert prio == "critical" and "priority_unset" not in cf    # choosing is choosing

    r = client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": None})
    assert r.status_code == 200, r.text
    prio, cf = _row(tid)
    assert cf.get("priority_unset") is True
    # the neutral engine value, where a new item sits — not the one it had
    assert prio == "medium"


def test_an_empty_string_says_the_same_thing(client, admin_id):
    """The board sends null; a script or an import may well send ""."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": "low"})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": ""})
    prio, cf = _row(tid)
    assert cf.get("priority_unset") is True and prio == "medium"


def test_clearing_drops_a_board_defined_priority_entirely(client, admin_id):
    """A board priority beyond the five rides on the item as a label and colour.
    Clearing has to take those with it, or the cell would keep painting the old
    one while claiming nothing was chosen."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                 json={"priority": "high",
                       "custom_fields": {"priority_key": "x_blocker", "priority_label": "חוסם",
                                         "priority_color": "#FD5AC3"}})
    _, cf = _row(tid)
    assert cf.get("priority_key") == "x_blocker"

    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": None})
    prio, cf = _row(tid)
    assert cf.get("priority_unset") is True
    assert "priority_key" not in cf and "priority_label" not in cf and "priority_color" not in cf
    assert prio == "medium"


def test_the_log_records_it_as_a_change_to_nothing(client, admin_id):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": "critical"})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": None})
    with Session(cityos_main.engine) as db:
        rows = (db.query(AuditLog)
                  .filter(AuditLog.entity_type == "task", AuditLog.entity_id == tid,
                          AuditLog.field_name == "priority")
                  .order_by(AuditLog.id).all())
    assert len(rows) == 2, [(r.old_value, r.new_value) for r in rows]
    # medium → critical, then critical → nothing. "" is what both logs show as "—"
    assert rows[-1].old_value == "critical" and rows[-1].new_value == ""


def test_clearing_is_logged_even_when_the_engine_value_does_not_move(client, admin_id):
    """`medium` cleared stays `medium`. What changed is that it is no longer
    anybody's choice, and a log that stayed silent would lose that."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": "medium"})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": None})
    with Session(cityos_main.engine) as db:
        rows = (db.query(AuditLog)
                  .filter(AuditLog.entity_type == "task", AuditLog.entity_id == tid,
                          AuditLog.field_name == "priority")
                  .order_by(AuditLog.id).all())
    assert rows and rows[-1].old_value == "medium" and rows[-1].new_value == ""
    assert _row(tid)[1].get("priority_unset") is True


def test_choosing_again_after_clearing_works(client, admin_id):
    """And the round trip leaves no trace of the clearing behind."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": None})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": "emergency"})
    prio, cf = _row(tid)
    assert prio == "emergency" and "priority_unset" not in cf


def test_an_unknown_priority_still_changes_nothing(client, admin_id):
    """The guard this sits next to: a value that is not a priority is ignored,
    and must not be mistaken for a request to clear."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": "critical"})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": "לא עדיפות"})
    prio, cf = _row(tid)
    assert prio == "critical" and "priority_unset" not in cf


def test_the_status_column_is_untouched_by_this(client, admin_id):
    """Clearing one of the two built-in columns must not clear the other."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done",
                                                              "priority": "high"})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"priority": None})
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        status = t.status.value if hasattr(t.status, "value") else t.status
        cf = dict(t.custom_fields or {})
    assert status == "done" and "status_unset" not in cf
    assert cf.get("priority_unset") is True
