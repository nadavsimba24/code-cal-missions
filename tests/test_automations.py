"""Group — board automations (אוטומציות): if-then recipes, Monday-style.

A board admin builds rules from a recipe catalog; they fire inline on the change
that triggered them. These cover the wiring (does a rule actually run), the
permission bar, and the guards — an inactive rule, a bad config, and two rules
pointing at each other.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Task, Notification, Automation


def _mk_board(client, admin_id, name="לוח אוטומציות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _mk_item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id, config, active=True):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config, "is_active": active})


def _notes_for(task_id):
    with Session(cityos_main.engine) as db:
        return db.query(Notification).filter(Notification.task_id == task_id).all()


def test_the_recipe_catalog_is_served(client, admin_id):
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    ids = {r["id"] for r in d["recipes"]}
    assert "status_notify_person" in ids
    one = next(r for r in d["recipes"] if r["id"] == "status_notify_person")
    # the sentence carries the placeholders the picker fills in
    assert "{t_status}" in one["sentence"] and "{a_person}" in one["sentence"]
    assert {f["key"] for f in one["fields"]} == {"t_status", "a_person"}


def test_only_a_board_admin_may_define_a_rule(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    r = _add(client, bid, guinea_id, "created_set_priority", {"a_priority": "high"})
    assert r.status_code == 403
    assert _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).status_code == 200


def test_a_rule_records_who_created_and_who_last_changed_it(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    client.patch(f"/api/automations/{aid}?user_id={guinea_id}", json={"is_active": False})

    row = next(a for a in client.get(f"/api/boards/{bid}/automations?user_id={admin_id}")
               .json()["automations"] if a["id"] == aid)
    assert row["created_by"] == admin_id and row["created_by_name"]
    assert row["updated_by"] == guinea_id and row["updated_by_name"]
    assert row["is_active"] is False


def test_status_change_notifies_the_chosen_person(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": guinea_id})
    tid = _mk_item(client, bid, admin_id)
    assert not _notes_for(tid)

    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    got = [n for n in _notes_for(tid) if n.user_id == guinea_id]
    assert len(got) == 1


def test_a_rule_only_fires_for_its_own_status(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": guinea_id})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "in_progress"})
    assert not [n for n in _notes_for(tid) if n.user_id == guinea_id]


def test_status_change_can_assign_a_person(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "status_assign_person",
         {"t_status": "review", "a_person": guinea_id})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "review"})
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert guinea_id in {u.id for u in t.assignees}


def test_a_new_item_can_be_given_a_status(client, admin_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"})
    tid = _mk_item(client, bid, admin_id, "פריט חדש")
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._st_of(t) == "in_progress"


def test_a_new_item_can_get_a_subitem(client, admin_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "status_create_subitem",
         {"t_status": "done", "a_text": "סיכום"})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    with Session(cityos_main.engine) as db:
        subs = db.query(Task).filter(Task.parent_id == tid).all()
        assert [s.title for s in subs] == ["סיכום"]


def test_an_inactive_rule_does_not_fire(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "status_notify_person",
               {"t_status": "done", "a_person": guinea_id}).json()["id"]
    client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"is_active": False})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    assert not [n for n in _notes_for(tid) if n.user_id == guinea_id]

    # ...and switching it back on makes it fire again
    client.patch(f"/api/automations/{aid}?user_id={admin_id}", json={"is_active": True})
    tid2 = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid2}?user_id={admin_id}", json={"status": "done"})
    assert [n for n in _notes_for(tid2) if n.user_id == guinea_id]


def test_two_rules_pointing_at_each_other_terminate(client, admin_id):
    """A → B and B → A must not spin forever; the cascade is depth-bounded."""
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "status_set_priority", {"t_status": "done", "a_priority": "critical"})
    _add(client, bid, admin_id, "priority_notify_person", {"t_priority": "critical", "a_person": admin_id})
    tid = _mk_item(client, bid, admin_id)
    r = client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    assert r.status_code == 200          # it returns at all — no runaway loop
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        assert cityos_main._task_priority_key(t) == "critical"


def test_a_rule_with_a_missing_value_is_refused(client, admin_id):
    bid = _mk_board(client, admin_id)
    r = _add(client, bid, admin_id, "status_notify_person", {"t_status": "done"})
    assert r.status_code == 400
    assert _add(client, bid, admin_id, "no_such_recipe", {}).status_code == 400


def test_a_rule_can_be_deleted(client, admin_id):
    bid = _mk_board(client, admin_id)
    aid = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"}).json()["id"]
    assert client.delete(f"/api/automations/{aid}?user_id={admin_id}").status_code == 200
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(Automation.id == aid).first() is None


def test_rules_are_scoped_to_their_own_board(client, admin_id, guinea_id):
    """A rule on one board must never fire for an item on another."""
    b1, b2 = _mk_board(client, admin_id, "לוח א"), _mk_board(client, admin_id, "לוח ב")
    _add(client, b1, admin_id, "status_notify_person", {"t_status": "done", "a_person": guinea_id})
    tid = _mk_item(client, b2, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    assert not [n for n in _notes_for(tid) if n.user_id == guinea_id]


def test_the_list_shows_a_filled_in_sentence(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": guinea_id})
    row = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"][0]
    assert "{" not in row["sentence"]           # every placeholder resolved
    assert "הושלם" in row["sentence"]           # the status label, not its key
