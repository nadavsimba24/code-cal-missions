"""«טרם הוגדר» is a value, and a person has to be able to go back to it.

Every item starts on the grey default: nobody has chosen a status yet, and the
cell says so. But the only things sayable afterwards were the board's own
statuses, so the first click was irreversible — a status set by mistake could
be changed to another status and never back to "not decided". The board log
would then read as a decision nobody made.

An explicit null says it: not one of the engine values, but the absence of a
choice. The engine value returns to the neutral `todo`, exactly where a new
item's sits, so the kanban and the charts read such an item as unstarted rather
than as whatever it was before it was cleared.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Task, AuditLog


def _board(client, admin_id, name="לוח סטטוס"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id,
                                           "custom_fields": {"status_unset": True}}).json()["id"]


def _row(tid):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        v = t.status
        return ((v.value if hasattr(v, "value") else v), dict(t.custom_fields or {}))


def test_a_new_item_starts_undecided(client, admin_id):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    _, cf = _row(tid)
    assert cf.get("status_unset") is True


def test_a_status_can_be_put_back_to_undecided(client, admin_id):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    status, cf = _row(tid)
    assert status == "done" and "status_unset" not in cf      # choosing is choosing

    r = client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": None})
    assert r.status_code == 200, r.text
    status, cf = _row(tid)
    assert cf.get("status_unset") is True
    # the neutral engine value, where a new item sits — not the one it had
    assert status == "todo"


def test_an_empty_string_says_the_same_thing(client, admin_id):
    """The board sends null; a script or an import may well send ""."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "in_progress"})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": ""})
    status, cf = _row(tid)
    assert cf.get("status_unset") is True and status == "todo"


def test_clearing_drops_a_board_defined_status_entirely(client, admin_id):
    """A board status beyond the seven rides on the item as a label and colour.
    Clearing has to take those with it, or the cell would keep painting the old
    one while claiming nothing was chosen."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    # x_frozen is a default board status whose engine value is on_hold
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "on_hold",
                 "custom_fields": {"status_key": "x_frozen", "status_label": "הקפאה",
                                   "status_color": "#FD5AC3"}})
    _, cf = _row(tid)
    assert cf.get("status_key") == "x_frozen"

    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": None})
    status, cf = _row(tid)
    assert cf.get("status_unset") is True
    assert "status_key" not in cf and "status_label" not in cf and "status_color" not in cf
    assert status == "todo"


def test_the_log_records_it_as_a_change_to_nothing(client, admin_id):
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": None})
    with Session(cityos_main.engine) as db:
        rows = (db.query(AuditLog)
                  .filter(AuditLog.entity_type == "task", AuditLog.entity_id == tid,
                          AuditLog.field_name == "status")
                  .order_by(AuditLog.id).all())
    assert len(rows) == 2, [(r.old_value, r.new_value) for r in rows]
    # ...→ done, then done → nothing. An empty value is what both logs show as "—"
    assert rows[-1].old_value == "done" and rows[-1].new_value == ""


def test_choosing_again_after_clearing_works(client, admin_id):
    """And the round trip leaves no trace of the clearing behind."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": None})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "review"})
    status, cf = _row(tid)
    assert status == "review" and "status_unset" not in cf


def test_an_unknown_status_still_changes_nothing(client, admin_id):
    """The guard this sits next to: a value that is not a status is ignored, and
    must not be mistaken for a request to clear."""
    bid = _board(client, admin_id)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "לא סטטוס"})
    status, cf = _row(tid)
    assert status == "done" and "status_unset" not in cf
