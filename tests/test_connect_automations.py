"""Connect columns inside the automation engine.

Five behaviours from the spec: link on creation, react to a linked item's
status, notify when a link is made, act when one is removed, and create an item
on another board already linked back.
"""

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _tasks(client, bid):
    return client.get(f"/api/boards/{bid}").json()["tasks"]


def _cell(client, tid, col_id, uid):
    t = client.get(f"/api/tasks/{tid}", headers=AS(uid)).json()
    return (t.get("custom_fields") or {}).get(col_id) or []


def _set(client, tid, col_id, ids, uid):
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: ids}}, headers=AS(uid))


def _rule(client, admin_id, bid, recipe_id, config):
    return client.post(f"/api/boards/{bid}/automations",
                       json={"actor_id": admin_id, "recipe_id": recipe_id, "config": config})


def _setup(client, admin_id, tag, two_way=True):
    a, b = _board(client, admin_id, f"מקור {tag}"), _board(client, admin_id, f"יעד {tag}")
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": [b], "multiple": True, "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, b, next(x for x in _cols(client, a) if x["type"] == "connect")


def _notes(client, uid):
    return client.get(f"/api/notifications?user_id={uid}", headers=AS(uid)).json()["notifications"]


# ── the recipes exist and validate ──────────────────────────────────────────

def test_the_catalog_offers_the_link_recipes(client, admin_id):
    cat = client.get("/api/automations/recipes", headers=AS(admin_id)).json()["recipes"]
    ids = {r["id"] for r in cat}
    for want in ("created_link_item", "created_create_and_link", "link_added_notify_person",
                 "link_removed_set_status", "linked_status_set_status"):
        assert want in ids, want
    triggers = {r["trigger"] for r in cat}
    assert {"link_added", "link_removed", "linked_status_changes_to"} <= triggers


def test_a_rule_without_its_column_is_refused(client, admin_id):
    a, b, c = _setup(client, admin_id, "v1")
    r = _rule(client, admin_id, a, "created_link_item", {"a_item": 1})
    assert r.status_code >= 400, "a link rule saved with no column named"


# ── 1. link on creation ─────────────────────────────────────────────────────

def test_creating_an_item_links_it_to_an_item_on_another_board(client, admin_id):
    a, b, c = _setup(client, admin_id, "c1")
    target = _item(client, b, admin_id, "היעד הקבוע")
    _rule(client, admin_id, a, "created_link_item",
          {"a_connect": c["id"], "a_item": target})
    made = _item(client, a, admin_id, "פריט חדש")
    assert _cell(client, made, c["id"], admin_id) == [target]


def test_the_reverse_shows_on_the_target_board(client, admin_id):
    a, b, c = _setup(client, admin_id, "c2")
    mirror = c["connect"]["mirror"][str(b)]
    target = _item(client, b, admin_id, "היעד הקבוע")
    _rule(client, admin_id, a, "created_link_item",
          {"a_connect": c["id"], "a_item": target})
    made = _item(client, a, admin_id, "פריט חדש")
    assert _cell(client, target, mirror, admin_id) == [made]


def test_it_will_not_link_to_an_item_the_column_does_not_reach(client, admin_id):
    """The rule names an item; the column decides whether it can hold it."""
    a, b, c = _setup(client, admin_id, "c3")
    elsewhere = _board(client, admin_id, "לוח אחר c3")
    stray = _item(client, elsewhere, admin_id, "זר")
    _rule(client, admin_id, a, "created_link_item", {"a_connect": c["id"], "a_item": stray})
    made = _item(client, a, admin_id, "פריט חדש")
    assert _cell(client, made, c["id"], admin_id) == []


# ── 5. create an item on another board and link it ──────────────────────────

def test_creating_an_item_creates_and_links_one_on_the_target_board(client, admin_id):
    a, b, c = _setup(client, admin_id, "k1")
    _rule(client, admin_id, a, "created_create_and_link",
          {"a_connect": c["id"], "a_board": b, "a_text": "משימת ליווי"})
    made = _item(client, a, admin_id, "פריט חדש")
    linked = _cell(client, made, c["id"], admin_id)
    assert len(linked) == 1
    other = client.get(f"/api/tasks/{linked[0]}", headers=AS(admin_id)).json()
    assert other["title"] == "משימת ליווי" and other["board_id"] == b


def test_it_refuses_a_board_the_column_does_not_point_at(client, admin_id):
    a, b, c = _setup(client, admin_id, "k2")
    elsewhere = _board(client, admin_id, "לוח אחר k2")
    before = len(_tasks(client, elsewhere))
    _rule(client, admin_id, a, "created_create_and_link",
          {"a_connect": c["id"], "a_board": elsewhere, "a_text": "לא אמור להיווצר"})
    made = _item(client, a, admin_id, "פריט חדש")
    assert _cell(client, made, c["id"], admin_id) == []
    assert len(_tasks(client, elsewhere)) == before, "an orphan item was created on a board it cannot link to"


def test_the_created_item_lands_in_the_first_group(client, admin_id):
    a, b, c = _setup(client, admin_id, "k3")
    _rule(client, admin_id, a, "created_create_and_link",
          {"a_connect": c["id"], "a_board": b, "a_text": "נוצר"})
    made = _item(client, a, admin_id, "פריט חדש")
    other = client.get(f"/api/tasks/{_cell(client, made, c['id'], admin_id)[0]}",
                       headers=AS(admin_id)).json()
    groups = client.get(f"/api/boards/{b}").json()["groups"]
    assert other["group_id"] == groups[0]["id"]


# ── 3 & 4. a link being made, or unmade ─────────────────────────────────────

def test_making_a_link_notifies(client, admin_id, member_id):
    a, b, c = _setup(client, admin_id, "n1")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _rule(client, admin_id, a, "link_added_notify_person", {"a_person": member_id})
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    before = len(_notes(client, member_id))
    _set(client, src, c["id"], [x], admin_id)
    assert len(_notes(client, member_id)) > before, "no notification when the link was made"


def test_removing_a_link_runs_an_action(client, admin_id):
    a, b, c = _setup(client, admin_id, "n2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _rule(client, admin_id, a, "link_removed_set_status", {"a_status": "done"})
    _set(client, src, c["id"], [], admin_id)
    assert client.get(f"/api/tasks/{src}", headers=AS(admin_id)).json()["status"] == "done"


def test_a_replacement_reports_both_sides_of_it(client, admin_id):
    """One edit can add and remove in the same cell."""
    a, b, c = _setup(client, admin_id, "n3")
    src = _item(client, a, admin_id, "מקור")
    x, y = _item(client, b, admin_id, "ראשון"), _item(client, b, admin_id, "שני")
    _set(client, src, c["id"], [x], admin_id)
    _rule(client, admin_id, a, "link_removed_set_status", {"a_status": "done"})
    _set(client, src, c["id"], [y], admin_id)
    t = client.get(f"/api/tasks/{src}", headers=AS(admin_id)).json()
    assert t["status"] == "done"
    assert (t.get("custom_fields") or {}).get(c["id"]) == [y]


def test_a_one_way_column_fires_the_link_triggers_too(client, admin_id):
    a, b, c = _setup(client, admin_id, "n4", two_way=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _rule(client, admin_id, a, "link_added_set_status", {"a_status": "on_hold"})
    _set(client, src, c["id"], [x], admin_id)
    assert client.get(f"/api/tasks/{src}", headers=AS(admin_id)).json()["status"] == "on_hold"


# ── 2. the linked item's status changes ─────────────────────────────────────

def test_a_linked_items_status_change_updates_this_one(client, admin_id):
    a, b, c = _setup(client, admin_id, "s1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _rule(client, admin_id, a, "linked_status_set_status",
          {"t_status": "done", "a_status": "on_hold"})
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"status": "done"})
    assert client.get(f"/api/tasks/{src}", headers=AS(admin_id)).json()["status"] == "on_hold"


def test_it_only_fires_for_the_status_the_rule_names(client, admin_id):
    a, b, c = _setup(client, admin_id, "s2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _rule(client, admin_id, a, "linked_status_set_status",
          {"t_status": "done", "a_status": "on_hold"})
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"status": "in_progress"})
    assert client.get(f"/api/tasks/{src}", headers=AS(admin_id)).json()["status"] != "on_hold"


def test_an_unlinked_item_is_not_affected(client, admin_id):
    a, b, c = _setup(client, admin_id, "s3")
    src, other = _item(client, a, admin_id, "מקושר"), _item(client, a, admin_id, "לא מקושר")
    x = _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _rule(client, admin_id, a, "linked_status_set_status",
          {"t_status": "done", "a_status": "on_hold"})
    client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"status": "done"})
    assert client.get(f"/api/tasks/{other}", headers=AS(admin_id)).json()["status"] != "on_hold"


def test_two_rules_pointing_at_each_other_terminate(client, admin_id):
    """Bounded by the same depth limit as any other cascade — otherwise a pair
    of boards reacting to one another never stops."""
    a, b, c = _setup(client, admin_id, "s4")
    mirror = c["connect"]["mirror"][str(b)]
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    _rule(client, admin_id, a, "linked_status_set_status",
          {"t_status": "done", "a_status": "in_progress"})
    _rule(client, admin_id, b, "linked_status_set_status",
          {"t_status": "in_progress", "a_status": "done"})
    r = client.patch(f"/api/tasks/{x}?user_id={admin_id}", json={"status": "done"})
    assert r.status_code == 200


def test_the_rule_reads_as_a_sentence_with_real_names(client, admin_id):
    """The label is quoted in every notification the rule sends, so a raw column
    id or task id there is what the person receiving it would have to decode."""
    a, b, c = _setup(client, admin_id, "lbl")
    target = _item(client, b, admin_id, "היעד הקבוע")
    _rule(client, admin_id, a, "created_link_item",
          {"a_connect": c["id"], "a_item": target})
    rules = client.get(f"/api/boards/{a}/automations", headers=AS(admin_id)).json()["automations"]
    sent = rules[0]["sentence"]
    assert "היעד הקבוע" in sent and "קישור" in sent
    assert c["id"] not in sent and str(target) not in sent, f"raw ids leaked into the sentence: {sent}"


def test_the_create_and_link_rule_names_its_board(client, admin_id):
    a, b, c = _setup(client, admin_id, "lbl2")
    _rule(client, admin_id, a, "created_create_and_link",
          {"a_connect": c["id"], "a_board": b, "a_text": "משימת ליווי"})
    rules = client.get(f"/api/boards/{a}/automations", headers=AS(admin_id)).json()["automations"]
    assert "יעד lbl2" in rules[0]["sentence"]
