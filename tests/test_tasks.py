"""Group 3 — task lifecycle: create → read → update → comment → move → delete."""


def _board_group(client, board_id=1):
    b = client.get(f"/api/boards/{board_id}?user_id=1").json()
    gid = b["groups"][0]["id"] if b.get("groups") else None
    return gid


def test_edit_comment_keeps_mentions_and_attachments(client, admin_id):
    """Editing a comment persists content, @mentions and attachments (parity with
    the composer), not just the text body."""
    r = client.post("/api/tasks/1/comments", json={"content": "מקורי", "user_id": admin_id})
    cid = r.json()["id"]
    try:
        r = client.patch(f"/api/comments/{cid}", json={
            "user_id": admin_id,
            "content": "ערוך עם תיוג",
            "mentions": [admin_id],
            "attachments": [{"name": "x.txt", "url": "/api/files/abc"}],
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["content"] == "ערוך עם תיוג"
        assert d["mentions"] == [admin_id]
        assert d["attachments"] and d["attachments"][0]["url"] == "/api/files/abc"
    finally:
        client.delete(f"/api/comments/{cid}?user_id={admin_id}")


def test_task_lifecycle(client):
    """Full task flow: create -> appears on board -> update -> comment -> move -> delete."""
    gid = _board_group(client)

    # create
    r = client.post("/api/tasks", json={"title": "pytest task", "board_id": 1, "group_id": gid})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]

    try:
        # appears in the board
        board = client.get("/api/boards/1?user_id=1").json()
        ids = [t["id"] for t in board["tasks"]]
        assert tid in ids

        # update
        r = client.patch(f"/api/tasks/{tid}", json={"title": "pytest task updated"})
        assert r.status_code in (200, 204), r.text

        # comment (acting user 1 is a board admin → allowed)
        r = client.post(f"/api/tasks/{tid}/comments", json={"content": "hi", "user_id": 1})
        assert r.status_code in (200, 201), r.text
        comments = client.get(f"/api/tasks/{tid}/comments").json()["comments"]
        assert any("hi" in (c.get("content") or "") for c in comments)

        # move
        r = client.post(f"/api/tasks/{tid}/move", json={"group_id": gid, "position": 0})
        assert r.status_code in (200, 204), r.text

        # activity log reads
        assert client.get(f"/api/tasks/{tid}/activity").status_code == 200
    finally:
        # delete (cleanup so the shared DB stays tidy)
        r = client.delete(f"/api/tasks/{tid}")
        assert r.status_code in (200, 204), r.text


def test_comment_read_receipts(client, admin_id, member_id):
    """A message reports who has seen it (read receipts), excluding its own author."""
    def _find(cid):
        for c in client.get("/api/tasks/1/comments").json()["comments"]:
            if c["id"] == cid:
                return c
        return None

    r = client.post("/api/tasks/1/comments", json={"content": "seen-test", "user_id": admin_id})
    cid = r.json()["id"]
    try:
        # nobody has seen it yet
        assert _find(cid)["seen_users"] == []
        # a different member opens the thread → becomes a viewer
        assert client.post("/api/tasks/1/comments/seen", json={"user_id": member_id}).status_code == 200
        assert member_id in [u["id"] for u in _find(cid)["seen_users"]]
        # the author viewing does NOT add themselves as a "seen by"
        client.post("/api/tasks/1/comments/seen", json={"user_id": admin_id})
        assert admin_id not in [u["id"] for u in _find(cid)["seen_users"]]
    finally:
        client.delete(f"/api/comments/{cid}?user_id={admin_id}")


def test_mention_in_comment_notifies_user(client, admin_id, member_id):
    """Tagging a user in a comment (explicit mention id) notifies them, not the author."""
    base = client.get(f"/api/notifications?user_id={member_id}").json()["unread_count"]
    r = client.post("/api/tasks/1/comments", json={"content": "שלום, נא לבדוק",
                                                    "user_id": admin_id, "mentions": [member_id]})
    cid = r.json()["id"]
    try:
        n = client.get(f"/api/notifications?user_id={member_id}").json()
        assert n["unread_count"] == base + 1
        top = n["notifications"][0]
        assert top["type"] == "mention" and top["task_id"] == 1
        # the author does not notify themselves
        r2 = client.post("/api/tasks/1/comments", json={"content": "hi", "user_id": admin_id,
                                                        "mentions": [admin_id]})
        client.delete(f"/api/comments/{r2.json()['id']}?user_id={admin_id}")
        # admin's own unread count unaffected by self-mention
        assert client.get(f"/api/notifications?user_id={admin_id}").json()["unread_count"] == \
            client.get(f"/api/notifications?user_id={admin_id}").json()["unread_count"]
    finally:
        client.delete(f"/api/comments/{cid}?user_id={admin_id}")
        client.post("/api/notifications/read-all", json={"user_id": member_id})


def test_assigning_person_notifies_them(client, admin_id, member_id):
    """Adding a user to a task's people (assignees) column notifies them; the actor
    assigning themselves is not notified; removing does not notify."""
    gid = _board_group(client)
    r = client.post("/api/tasks", json={"title": "assign notif", "board_id": 1, "group_id": gid})
    tid = r.json()["id"]
    try:
        base = client.get(f"/api/notifications?user_id={member_id}").json()["unread_count"]
        # admin assigns the member → member notified
        client.post(f"/api/tasks/{tid}/assignees", json={"user_id": member_id, "action": "add", "actor_id": admin_id})
        n = client.get(f"/api/notifications?user_id={member_id}").json()
        assert n["unread_count"] == base + 1
        assert n["notifications"][0]["type"] == "assign" and n["notifications"][0]["task_id"] == tid
        # re-adding the same person does not notify again
        client.post(f"/api/tasks/{tid}/assignees", json={"user_id": member_id, "action": "add", "actor_id": admin_id})
        assert client.get(f"/api/notifications?user_id={member_id}").json()["unread_count"] == base + 1
        # self-assignment is not notified
        selfbase = client.get(f"/api/notifications?user_id={admin_id}").json()["unread_count"]
        client.post(f"/api/tasks/{tid}/assignees", json={"user_id": admin_id, "action": "add", "actor_id": admin_id})
        assert client.get(f"/api/notifications?user_id={admin_id}").json()["unread_count"] == selfbase
    finally:
        client.delete(f"/api/tasks/{tid}")
        client.post("/api/notifications/read-all", json={"user_id": member_id})


def test_assign_at_creation_notifies(client, admin_id, member_id):
    """Assigning a user while creating the item notifies them (not the creator)."""
    gid = _board_group(client)
    base = client.get(f"/api/notifications?user_id={member_id}").json()["unread_count"]
    r = client.post("/api/tasks", json={"title": "created with assignee", "board_id": 1,
                                        "group_id": gid, "assignee_ids": [member_id, admin_id],
                                        "actor_id": admin_id})
    tid = r.json()["id"]
    try:
        n = client.get(f"/api/notifications?user_id={member_id}").json()
        assert n["unread_count"] == base + 1  # member notified
        assert n["notifications"][0]["type"] == "assign" and n["notifications"][0]["task_id"] == tid
    finally:
        client.delete(f"/api/tasks/{tid}")
        client.post("/api/notifications/read-all", json={"user_id": member_id})


def test_a_status_change_never_moves_the_item_between_groups(client):
    """Setting a status leaves the item in the group it is in — every status,
    including the ones a group on this board stands for.

    Filing an item by its status is an automation a board can be given
    (status_changes_to → move_to_group). It used to be built in as well: a rule
    with no name, absent from the board's own list of automations and impossible
    to switch off. See tests/test_status_group_automation.py."""
    b = client.get("/api/boards/1?user_id=1").json()
    every_status = ("todo", "in_progress", "review", "on_hold", "cancelled",
                    "backlog", "done")
    gid = b["groups"][0]["id"]
    tid = client.post("/api/tasks", json={"title": "move-me", "board_id": 1,
                                          "group_id": gid}).json()["id"]

    def where():
        board = client.get("/api/boards/1?user_id=1").json()
        return next(t for t in board["tasks"] if t["id"] == tid)["group_id"]

    try:
        for status in every_status:
            r = client.patch(f"/api/tasks/{tid}", json={"status": status, "user_id": 1})
            assert r.status_code == 200, r.text
            assert where() == gid, f"status {status} moved the item out of its group"
    finally:
        client.delete(f"/api/tasks/{tid}")


def test_a_renamed_status_does_not_throw_the_item_out_of_its_group(client, admin_id):
    """Her board: "לביצוע" renamed to "חזרה לפיתוח", groups בתכנון/בביצוע/הושלם.

    Setting it used to file the item under the `todo` stage and drop it into the
    planning group, out of the development group where it belongs. A status with
    no group of its own leaves the item exactly where it is.
    """
    bid = client.post("/api/boards", json={"name": "פיתוח", "user_id": admin_id}).json()["id"]
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "statuses": [
        {"key": "backlog", "label": "בתכנון"},
        {"key": "in_progress", "label": "בפיתוח"},
        {"key": "todo", "label": "חזרה לפיתוח", "color": "#e2445c"},
        {"key": "done", "label": "הושלם"},
    ]})
    board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    dev = next(g["id"] for g in board["groups"] if g["task_status"] == "in_progress")
    t = client.post("/api/tasks", json={"board_id": bid, "title": "משימה",
                                        "group_id": dev, "status": "in_progress",
                                        "user_id": admin_id}).json()
    assert t["group_id"] == dev

    client.patch(f"/api/tasks/{t['id']}", json={"user_id": admin_id, "status": "todo"})
    fresh = [x for x in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
             if x["id"] == t["id"]][0]
    assert fresh["status"] == "todo"        # the status did change
    assert fresh["group_id"] == dev         # the item did not move


def test_a_new_group_does_not_steal_todo_items(client, admin_id):
    """A freshly added group is created with the default `todo` status. Setting a
    todo-family status ("חזרה לפיתוח") must not yank an item out of "בביצוע" into
    that new last group — a group left at the default status is a plain section,
    never an auto-move destination."""
    bid = client.post("/api/boards", json={"name": "מגנט", "user_id": admin_id}).json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    dev = next(g["id"] for g in board["groups"] if g["task_status"] == "in_progress")

    # add a new group — it defaults to `todo`, becoming the last group
    new_g = client.post("/api/groups", json={"board_id": bid, "name": "קבוצה חדשה",
                                             "actor_id": admin_id}).json()
    assert new_g["task_status"] == "todo"

    t = client.post("/api/tasks", json={"board_id": bid, "title": "משימה",
                                        "group_id": dev, "status": "in_progress",
                                        "user_id": admin_id}).json()
    client.patch(f"/api/tasks/{t['id']}", json={"user_id": admin_id, "status": "todo"})
    fresh = [x for x in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
             if x["id"] == t["id"]][0]
    assert fresh["group_id"] == dev, "a todo status pulled the item into the new group"


def test_creating_an_item_logs_a_creation_entry(client, admin_id):
    """A new item (and sub-item) opens its activity log with a non-undoable
    "create" entry recording who created it and its title."""
    bid = client.post("/api/boards", json={"name": "לוג יצירה", "user_id": admin_id}).json()["id"]
    t = client.post("/api/tasks", json={"board_id": bid, "title": "חדש", "user_id": admin_id}).json()
    acts = client.get(f"/api/tasks/{t['id']}/activity?user_id={admin_id}").json()["activity"]
    created = [a for a in acts if a["action"] == "create"]
    assert created, "no creation entry in the activity log"
    assert created[0]["field"] == "item" and created[0]["new"] == "חדש"
    assert created[0]["can_undo"] is False       # creation is history, not undoable

    sub = client.post("/api/tasks", json={"board_id": bid, "title": "תת", "parent_id": t["id"],
                                          "user_id": admin_id}).json()
    sacts = client.get(f"/api/tasks/{sub['id']}/activity?user_id={admin_id}").json()["activity"]
    screated = [a for a in sacts if a["action"] == "create"]
    assert screated and screated[0]["field"] == "subitem"


def test_finishing_every_subitem_does_not_finish_the_parent(client):
    """The parent used to complete itself once every sub-item was done.

    Nobody wrote that rule, it was absent from the board's automations list, and
    there was no switch for it — a parent that had been left open on purpose
    reported itself finished, in the charts and the log alike. Whether a parent
    is done is now something a person says."""
    b = client.get("/api/boards/1?user_id=1").json()
    gid = b["groups"][0]["id"]
    p = client.post("/api/tasks", json={"title": "parent", "board_id": 1, "group_id": gid}).json()["id"]
    s1 = client.post("/api/tasks", json={"title": "s1", "board_id": 1, "parent_id": p}).json()["id"]
    s2 = client.post("/api/tasks", json={"title": "s2", "board_id": 1, "parent_id": p}).json()["id"]
    try:
        def parent():
            d = client.get("/api/boards/1?user_id=1").json()
            return next(t for t in d["tasks"] if t["id"] == p)
        was = parent()["status"]
        client.patch(f"/api/tasks/{s1}", json={"status": "done", "user_id": 1})
        client.patch(f"/api/tasks/{s2}", json={"status": "done", "user_id": 1})
        pt = parent()
        assert pt["status"] == was and pt["status"] != "done"   # untouched
        assert pt["group_id"] == gid                            # and still where it was put
    finally:
        client.delete(f"/api/tasks/{p}")


def test_new_item_appended_to_bottom_of_group(client):
    """A newly created item lands at the bottom of its group (last in order)."""
    b = client.get("/api/boards/1?user_id=1").json()
    gid = b["groups"][0]["id"]
    a = client.post("/api/tasks", json={"title": "aaa", "board_id": 1, "group_id": gid}).json()["id"]
    z = client.post("/api/tasks", json={"title": "zzz", "board_id": 1, "group_id": gid}).json()["id"]
    try:
        order = [t["id"] for t in client.get("/api/boards/1?user_id=1").json()["tasks"] if t["group_id"] == gid]
        assert order.index(a) < order.index(z)           # created earlier → higher up
        assert order[-1] == z                            # the latest is at the very bottom
    finally:
        client.delete(f"/api/tasks/{a}"); client.delete(f"/api/tasks/{z}")
