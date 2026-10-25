"""Group — תלויות ומחזור חיי לוח: what a deletion costs, said before it happens.

An automation is configuration that points at other configuration: a column, a
status value, a group, a link column, a board. Every one of those can be
deleted by somebody who has never opened the automations screen, and until now
the rule found out at its next firing — which on a quiet board is next week.

So the order is reversed. Before the deletion: who depends on this, who owns
them, how they use it and what will happen. After it: suspended, written down,
and the owner and the board's admins told. And never, ever, a replacement
guessed from a name — a new column called "אזור" is not the old one.

The other half is the board's own life. A deleted board takes its rules with
it and suspends the rules elsewhere that pointed at it; a deleted item takes
its waiting runs, and its sub-items'; an item moved to another board is not
the item the wait was promised about.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import (Automation, AutomationQueue, AutomationRun, AuditLog,
                    Board, Notification, Task)

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _col(client, bid, admin_id, **spec):
    cols = _cols(client, bid)
    col = {"id": spec.pop("id", "col_" + spec["type"][:4] + str(len(cols))), **spec}
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols + [col]})
    assert r.status_code == 200, r.text
    return col


def _drop_col(client, bid, admin_id, col_id):
    return client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id,
                              "columns": [c for c in _cols(client, bid) if c["id"] != col_id]})


def _statuses(client, bid):
    return client.get(f"/api/boards/{bid}").json()["statuses"]


def _add(client, bid, admin_id, recipe_id, config, **extra):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": recipe_id,
                          "config": config, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _status_of(rid):
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == rid).first()
        return a.status if a else None


def _dependents(client, bid, admin_id, kind, ref):
    return client.get(f"/api/boards/{bid}/automations/dependents"
                      f"?kind={kind}&ref={ref}&user_id={admin_id}")


def _notes(client, uid):
    return client.get(f"/api/notifications?user_id={uid}", headers=AS(uid)).json()["notifications"]


def _col_rule(client, bid, admin_id, col):
    """A rule that listens to one column — the simplest dependency there is."""
    return _add(client, bid, admin_id, "column_changed_notify_assignees",
                {"t_column": col["id"]})


# ── מה ההשפעה, לפני המחיקה ─────────────────────────────────────────────────

def test_the_preview_names_the_rules_that_depend_on_a_column(client, admin_id):
    bid = _board(client, admin_id, "לוח תלויות עמודה")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _col_rule(client, bid, admin_id, col)
    r = _dependents(client, bid, admin_id, "column", col["id"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert [x["id"] for x in d["dependents"]] == [rule["id"]], d
    one = d["dependents"][0]
    assert one["owner_id"], "the preview does not say who answers for it"
    assert one["uses"], "the preview does not say HOW it is used"
    assert one["impact"], "the preview does not say what will happen"


def test_a_rule_that_does_not_use_it_is_not_listed(client, admin_id):
    bid = _board(client, admin_id, "לוח לא תלוי")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    assert _dependents(client, bid, admin_id, "column", col["id"]).json()["dependents"] == []


def test_the_preview_covers_a_status_value(client, admin_id):
    bid = _board(client, admin_id, "לוח תלויות סטטוס")
    rule = _add(client, bid, admin_id, "status_set_priority",
                {"t_status": "done", "a_priority": "critical"})
    d = _dependents(client, bid, admin_id, "status", "done").json()
    assert [x["id"] for x in d["dependents"]] == [rule["id"]], d


def test_the_preview_covers_a_group(client, admin_id):
    bid = _board(client, admin_id, "לוח תלויות קבוצה")
    gid = client.get(f"/api/boards/{bid}").json()["groups"][0]["id"]
    rule = _add(client, bid, admin_id, "moved_group_set_status",
                {"t_group": gid, "a_status": "done"})
    d = _dependents(client, bid, admin_id, "group", gid).json()
    assert [x["id"] for x in d["dependents"]] == [rule["id"]], d


def test_the_preview_covers_a_target_board_from_the_other_side(client, admin_id):
    """«השהיית אוטומציות תלויות בלוחות אחרים» — so somebody deleting a board
    has to be shown the rules that are not on it."""
    a, b = _board(client, admin_id, "מקור יעד"), _board(client, admin_id, "יעד נמחק")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True,
                                            "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    rule = _add(client, a, admin_id, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    d = _dependents(client, b, admin_id, "board", b).json()
    assert rule["id"] in [x["id"] for x in d["dependents"]], d
    assert any(x["board_id"] == a for x in d["dependents"]), \
        "the rule was not shown as living on another board"


def test_the_preview_is_not_open_to_everyone(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח סגור תלויות")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    r = _dependents(client, bid, guinea_id, "column", col["id"])
    assert r.status_code == 403, r.text


def test_an_unknown_kind_is_refused_rather_than_answered_emptily(client, admin_id):
    """An empty answer to a question nobody understood reads as "nothing
    depends on this", which is the one wrong answer here."""
    bid = _board(client, admin_id, "לוח שאלה לא מוכרת")
    assert _dependents(client, bid, admin_id, "nonesuch", "x").status_code == 400


# ── המחיקה משהה, מתעדת ומודיעה ────────────────────────────────────────────

def test_deleting_a_column_suspends_the_rules_that_use_it(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקת עמודה")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _col_rule(client, bid, admin_id, col)
    assert _status_of(rule["id"]) == "active"
    _drop_col(client, bid, admin_id, col["id"])
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_the_owner_and_the_board_admins_are_told(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח הודעה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "admin"})
    col = _col(client, bid, admin_id, type="text", title="אזור")
    _col_rule(client, bid, admin_id, col)
    before = len(_notes(client, member_id))
    _drop_col(client, bid, admin_id, col["id"])
    after = _notes(client, member_id)
    assert len(after) > before, "a board admin was not told"
    assert any("אזור" in (n.get("body") or "") or "הושהתה" in (n.get("title") or "")
               for n in after[:3]), after[:2]


def test_the_suspension_is_written_down(client, admin_id):
    bid = _board(client, admin_id, "לוח תיעוד")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _col_rule(client, bid, admin_id, col)
    _drop_col(client, bid, admin_id, col["id"])
    with Session(cityos_main.engine) as db:
        rows = db.query(AuditLog).filter(AuditLog.entity_type == "automation",
                                         AuditLog.entity_id == rule["id"]).all()
    assert [r for r in rows if "תלות" in (r.field_name or "") + (r.new_value or "")], \
        [(r.action, r.field_name, r.new_value) for r in rows]


def test_deleting_a_status_value_suspends_the_rule(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקת סטטוס")
    rule = _add(client, bid, admin_id, "status_set_priority",
                {"t_status": "done", "a_priority": "critical"})
    keep = [s for s in _statuses(client, bid) if s["key"] != "done"]
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "statuses": keep})
    assert r.status_code == 200, r.text
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_deleting_a_group_suspends_the_rule(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקת קבוצה")
    groups = client.get(f"/api/boards/{bid}").json()["groups"]
    gid = groups[0]["id"]
    rule = _add(client, bid, admin_id, "moved_group_set_status",
                {"t_group": gid, "a_status": "done"})
    client.post("/api/groups", json={"board_id": bid, "name": "אחרת", "actor_id": admin_id})
    r = client.delete(f"/api/groups/{gid}?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_an_unrelated_rule_keeps_running(client, admin_id):
    bid = _board(client, admin_id, "לוח לא נוגע")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    other = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _drop_col(client, bid, admin_id, col["id"])
    assert _status_of(other["id"]) == "active"


# ── שינוי שם ממשיך לפי מזהה ───────────────────────────────────────────────

def test_renaming_a_column_changes_nothing_but_the_name(client, admin_id):
    """«המשך לפי מזהה קבוע והצגת השם החדש»."""
    bid = _board(client, admin_id, "לוח שינוי שם")
    col = _col(client, bid, admin_id, type="text", title="אזור")
    rule = _col_rule(client, bid, admin_id, col)
    cols = [dict(c, title="מחוז") if c["id"] == col["id"] else c for c in _cols(client, bid)]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    assert _status_of(rule["id"]) == "active"
    shown = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    one = next(x for x in shown["automations"] if x["id"] == rule["id"])
    assert "מחוז" in one["sentence"], one["sentence"]


def test_renaming_a_status_keeps_its_key(client, admin_id):
    bid = _board(client, admin_id, "לוח שם סטטוס")
    rule = _add(client, bid, admin_id, "status_set_priority",
                {"t_status": "done", "a_priority": "critical"})
    st = [dict(s, label="הסתיים") if s["key"] == "done" else s
          for s in _statuses(client, bid)]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "statuses": st})
    assert _status_of(rule["id"]) == "active"
    tid = _item(client, bid, admin_id, "פריט")
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert (t.priority.value if hasattr(t.priority, "value") else t.priority) == "critical"


def test_a_new_column_with_the_old_name_does_not_revive_the_rule(client, admin_id):
    """«אין להתאים שדה חלופי אוטומטית לפי שם». A column called "אזור" is not
    the column called "אזור" that somebody deleted last week."""
    bid = _board(client, admin_id, "לוח שם חוזר")
    col = _col(client, bid, admin_id, id="col_old", type="text", title="אזור")
    rule = _col_rule(client, bid, admin_id, col)
    _drop_col(client, bid, admin_id, col["id"])
    assert _status_of(rule["id"]) == "paused_error"
    _col(client, bid, admin_id, id="col_new", type="text", title="אזור")
    assert _status_of(rule["id"]) == "paused_error", "a rule was re-pointed by name"
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == rule["id"]).first()
        assert (a.config or {}).get("t_column") == "col_old", a.config


# ── שינוי סוג שדה ─────────────────────────────────────────────────────────

def test_an_incompatible_type_change_suspends_the_rule(client, admin_id):
    bid = _board(client, admin_id, "לוח סוג שדה")
    col = _col(client, bid, admin_id, id="col_t", type="text", title="אזור")
    rule = _add(client, bid, admin_id, "column_changed_set_status",
                {"t_column": col["id"], "a_status": "done"})
    cols = [dict(c, type="mirror") if c["id"] == col["id"] else c for c in _cols(client, bid)]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_a_compatible_type_change_leaves_it_running(client, admin_id):
    bid = _board(client, admin_id, "לוח סוג תואם")
    col = _col(client, bid, admin_id, id="col_t2", type="text", title="אזור")
    rule = _col_rule(client, bid, admin_id, col)
    cols = [dict(c, type="email") if c["id"] == col["id"] else c for c in _cols(client, bid)]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    assert _status_of(rule["id"]) == "active", _status_of(rule["id"])


# ── פריטים ────────────────────────────────────────────────────────────────

def _waiting_rule(client, bid, admin_id):
    return _add(client, bid, admin_id, "created_set_priority",
                {"a_priority": "high",
                 "actions": [{"key": "wait", "values": {"days": 60}},
                             {"key": "post_update", "values": {"text": "אחרי"}}]})


def _pending(tid):
    with Session(cityos_main.engine) as db:
        return [r for r in db.query(AutomationQueue)
                .filter(AutomationQueue.task_id == tid,
                        AutomationQueue.done_at == None).all()          # noqa: E711
                if (r.state or "pending") == "pending"]


def test_deleting_an_item_cancels_its_waiting_runs(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקת פריט")
    _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id, "פריט")
    assert _pending(tid), "nothing was waiting to begin with"
    client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
    assert not _pending(tid), "a deleted item still had a run coming"


def test_deleting_a_parent_cancels_the_subitems_waiting_runs(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקת אב")
    _waiting_rule(client, bid, admin_id)
    parent = _item(client, bid, admin_id, "אב")
    sub = _item(client, bid, admin_id, "תת", parent_id=parent)
    assert _pending(sub), "nothing was waiting on the sub-item"
    client.delete(f"/api/tasks/{parent}?user_id={admin_id}")
    assert not _pending(sub), "the sub-item's run survived its parent"


def test_moving_an_item_to_another_board_cancels_its_waiting_runs(client, admin_id):
    """«העברת פריט ללוח אחר — ביטול הפעלות ממתינות ב־MVP». The rule belongs to
    the board the item left, and the item is no longer the one it promised
    something about."""
    a, b = _board(client, admin_id, "לוח יוצא"), _board(client, admin_id, "לוח נכנס")
    _waiting_rule(client, a, admin_id)
    tid = _item(client, a, admin_id, "נודד")
    assert _pending(tid)
    gid = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    r = client.post(f"/api/tasks/{tid}/move",
                    json={"actor_id": admin_id, "board_id": b, "group_id": gid})
    assert r.status_code == 200, r.text
    assert not _pending(tid), "the wait followed the item to another board"


# ── מחזור חיי לוח ─────────────────────────────────────────────────────────

def test_deleting_a_board_stops_its_own_rules(client, admin_id):
    bid = _board(client, admin_id, "לוח נמחק")
    rule = _waiting_rule(client, bid, admin_id)
    tid = _item(client, bid, admin_id, "פריט")
    assert _pending(tid)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert _status_of(rule["id"]) in ("paused", "paused_error"), _status_of(rule["id"])
    assert not _pending(tid), "a deleted board still had runs coming"


def test_deleting_a_board_suspends_the_rules_elsewhere_that_point_at_it(client, admin_id):
    a, b = _board(client, admin_id, "מקור חי"), _board(client, admin_id, "יעד נעלם")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True,
                                            "two_way": True}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    c = next(x for x in _cols(client, a) if x["type"] == "connect")
    rule = _add(client, a, admin_id, "created_create_and_link",
                {"a_connect": c["id"], "a_board": b, "a_text": "חדש"})
    client.delete(f"/api/boards/{b}?user_id={admin_id}")
    assert _status_of(rule["id"]) == "paused_error", _status_of(rule["id"])


def test_restoring_the_board_leaves_the_rules_suspended(client, admin_id):
    """«שחזור — האוטומציות נשארות מושהות עד בדיקה ואישור». Coming back is not
    the same as having been checked."""
    bid = _board(client, admin_id, "לוח חוזר")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    r = client.post(f"/api/trash/boards/{bid}/restore?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert _status_of(rule["id"]) in ("paused", "paused_error"), _status_of(rule["id"])


def test_the_run_log_survives_the_board_going_to_the_bin(client, admin_id):
    bid = _board(client, admin_id, "לוח היסטוריה")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id, "פריט")
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        assert db.query(AutomationRun).filter(AutomationRun.board_id == bid).count() >= 1


# ── מחיקת אוטומציה ────────────────────────────────────────────────────────

def test_a_rule_in_deletion_is_not_in_the_ordinary_list(client, admin_id):
    bid = _board(client, admin_id, "לוח בתהליך מחיקה")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    client.patch(f"/api/automations/{rule['id']}?user_id={admin_id}",
                 json={"status": "deleting"})
    shown = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    assert rule["id"] not in [x["id"] for x in shown["automations"]], shown["automations"]


def test_a_system_admin_can_still_see_it_for_audit(client, admin_id):
    bid = _board(client, admin_id, "לוח ביקורת")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    client.patch(f"/api/automations/{rule['id']}?user_id={admin_id}",
                 json={"status": "deleting"})
    shown = client.get(f"/api/boards/{bid}/automations"
                       f"?user_id={admin_id}&include_deleting=true").json()
    assert rule["id"] in [x["id"] for x in shown["automations"]], shown["automations"]


def test_a_board_admin_who_is_not_a_system_admin_cannot(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח ביקורת סגורה")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    client.patch(f"/api/automations/{rule['id']}?user_id={admin_id}",
                 json={"status": "deleting"})
    shown = client.get(f"/api/boards/{bid}/automations"
                       f"?user_id={guinea_id}&include_deleting=true").json()
    assert rule["id"] not in [x["id"] for x in shown["automations"]]


def test_a_rule_in_deletion_stops_listening(client, admin_id):
    bid = _board(client, admin_id, "לוח לא מאזין")
    rule = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    client.patch(f"/api/automations/{rule['id']}?user_id={admin_id}",
                 json={"status": "deleting"})
    tid = _item(client, bid, admin_id, "פריט")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert (t.priority.value if hasattr(t.priority, "value") else t.priority) != "high"
    assert rule["id"]
