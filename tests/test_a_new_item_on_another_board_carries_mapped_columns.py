"""An item a rule creates on another board arrives with the columns it was told to carry.

"צור פריט בלוח אחר" made an item with a name and nothing else. A hand-off from
«H2 נהלים» to «H3 חוזים» therefore arrived with «מספר נוהל» and «מכרז» empty,
and somebody copied them across by hand — the work the rule was there to take
away. monday asks the same question as "Set how columns in the target board
will populate from the current board".

The engine has paired two boards' columns since create_mapped_and_link, but
only on a rule that also LINKS the items, and a hand-off has no link column.
The pairing is now an optional blank on create_in_board itself.

Pinned here:
  · a rule with a pairing creates the item with the mapped values in it, and
    still moves the item that set it off;
  · a pairing the engine cannot carry (text into a number) is refused at the
    save, in words;
  · a rule with no pairing — every rule written before this — runs and READS
    exactly as before: no "· «—»" tail in the list;
  · the templates built on the action went up a version, not to a new id.
"""
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Task

RID = "status_create_in_board_and_move"


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_col(client, bid, admin_id, col):
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id, "columns": _cols(client, bid) + [col]})
    assert r.status_code == 200, r.text
    return col["id"]


def _setup(client, admin_id, tag):
    src = _board(client, admin_id, f"H2 נהלים {tag}")
    dst = _board(client, admin_id, f"H3 חוזים {tag}")
    status = {"id": f"col_noh_{tag}", "type": "status", "title": "סטטוס נוהל",
              "options": [{"id": "o_open", "label": "בטיפול"},
                          {"id": "o_signed", "label": "ועדת שלושה חתומה"}]}
    _add_col(client, src, admin_id, status)
    num_src = _add_col(client, src, admin_id,
                       {"id": f"col_nm_{tag}", "type": "text", "title": "מספר נוהל"})
    num_dst = _add_col(client, dst, admin_id,
                       {"id": f"col_nf_{tag}", "type": "text", "title": "מספר נוהל (מלא)"})
    cost_dst = _add_col(client, dst, admin_id,
                        {"id": f"col_cs_{tag}", "type": "number", "title": "עלות"})
    signed = client.post("/api/groups", json={"board_id": src, "name": "נחתמה ועדת שלושה",
                                              "user_id": admin_id}).json()["id"]
    target = client.get(f"/api/boards/{dst}").json()["groups"][0]["id"]
    return src, dst, status, num_src, num_dst, cost_dst, signed, target


def _rule(client, admin_id, src, dst, status, signed, target, mapping=None,
          text="{{item.name}}"):
    cfg = {"t_status": "o_signed", "t_status_col": status["id"],
           "a_board": dst, "a_target_group": target, "a_text": text,
           "actions": [{"key": "move_to_group", "values": {"group": signed}}]}
    if mapping is not None:
        cfg["a_map"] = mapping
    return client.post(f"/api/boards/{src}/automations?user_id={admin_id}",
                       json={"recipe_id": RID, "is_active": True, "config": cfg})


def _fire(client, admin_id, src, status, title, cells=None):
    tid = client.post("/api/tasks", json={"board_id": src, "title": title,
                                          "user_id": admin_id,
                                          "custom_fields": cells or {}}).json()["id"]
    r = client.patch(f"/api/tasks/{tid}",
                     json={"custom_fields": {status["id"]: {"id": "o_signed",
                                                            "label": "ועדת שלושה חתומה"}},
                           "user_id": admin_id})
    assert r.status_code == 200, r.text
    return tid


def _made(bid, title):
    with Session(cityos_main.engine) as db:
        return db.query(Task).filter(Task.board_id == bid, Task.title == title,
                                     Task.deleted_at == None).all()   # noqa: E711


def test_the_new_item_arrives_with_the_mapped_columns(client, admin_id):
    src, dst, status, num_src, num_dst, _c, signed, target = _setup(client, admin_id, "m1")
    r = _rule(client, admin_id, src, dst, status, signed, target,
              mapping=[{"from": num_src, "to": num_dst}])
    assert r.status_code == 200, r.text

    tid = _fire(client, admin_id, src, status, "נוהל 41", {num_src: "N-2026-41"})

    made = _made(dst, "נוהל 41")
    assert len(made) == 1, "the item was not created on the target board"
    assert (made[0].custom_fields or {}).get(num_dst) == "N-2026-41", made[0].custom_fields
    assert made[0].group_id == target
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.id == tid).first().group_id == signed, \
            "the pairing must not cost the rule its second action"


def test_a_pairing_the_engine_cannot_carry_is_refused_at_the_save(client, admin_id):
    src, dst, status, num_src, _n, cost_dst, signed, target = _setup(client, admin_id, "m2")
    r = _rule(client, admin_id, src, dst, status, signed, target,
              mapping=[{"from": num_src, "to": cost_dst}])
    assert r.status_code == 400, r.text
    assert "מיפוי שדות אינו תקין" in r.json()["detail"]


def test_a_rule_with_no_pairing_runs_and_reads_as_it_always_did(client, admin_id):
    src, dst, status, _ns, _nd, _c, signed, target = _setup(client, admin_id, "m3")
    r = _rule(client, admin_id, src, dst, status, signed, target, text="חוזה בלי מיפוי")
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    _fire(client, admin_id, src, status, "נוהל 42")
    assert len(_made(dst, "חוזה בלי מיפוי")) == 1

    rules = client.get(f"/api/boards/{src}/automations?user_id={admin_id}").json()["automations"]
    label = next(a for a in rules if a["id"] == rid)["sentence"]
    assert "·" not in label and "—" not in label, label
    assert label.startswith("כאשר"), label


def test_the_templates_on_the_action_went_up_a_version_not_to_a_new_id():
    for rid in ("status_create_in_board", RID, "moved_group_create_in_board"):
        r = recipes.recipe(rid)
        a_map = [f for f in r["fields"] if f["key"] == "a_map"]
        assert a_map and recipes.field_optional(a_map[0]), rid
        assert recipes.template_version(rid) == 2, rid
    # …and the action itself carries the blank for when it is an extra action
    assert any(f["key"] == "map" and recipes.field_optional(f)
               for f in recipes.action_fields("create_in_board"))


def test_each_mapping_is_checked_against_its_own_action_s_board(client, admin_id):
    """The rule's own pairing is about a_board; an extra "צור פריט בלוח אחר"
    has a board of its own, and its pairing is about THAT board. The save
    used to hold every pairing against the last board any action named — so
    this rule, right on both counts, was refused."""
    src, dst, status, num_src, num_dst, _c, signed, target = _setup(client, admin_id, "m4")
    third = _board(client, admin_id, "H4 תיקים m4")
    num_third = _add_col(client, third, admin_id,
                         {"id": "col_n3_m4", "type": "text", "title": "מספר נוהל בתיק"})
    t_grp = client.get(f"/api/boards/{third}").json()["groups"][0]["id"]
    r = client.post(f"/api/boards/{src}/automations?user_id={admin_id}",
                    json={"recipe_id": RID, "is_active": True, "config": {
                        "t_status": "o_signed", "t_status_col": status["id"],
                        "a_board": dst, "a_target_group": target, "a_text": "{{item.name}}",
                        "a_map": [{"from": num_src, "to": num_dst}],
                        "actions": [
                            {"key": "create_in_board",
                             "values": {"board": third, "target_group": t_grp,
                                        "text": "תיק {{item.name}}",
                                        "map": [{"from": num_src, "to": num_third}]}},
                            {"key": "move_to_group", "values": {"group": signed}}]}})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    # Only the rule's own creation is checked at the firing: a rule creates one
    # target item per source item (_creation_guard), so the second creation is
    # skipped by design — what this pins is that it is SAVED, against its own
    # board, rather than refused against the first one's.
    _fire(client, admin_id, src, status, "נוהל 43", {num_src: "N-43"})
    a = _made(dst, "נוהל 43")
    assert len(a) == 1 and (a[0].custom_fields or {}).get(num_dst) == "N-43"

    # …and both pairings are in the rule's sentence, the extra one included
    rules = client.get(f"/api/boards/{src}/automations?user_id={admin_id}").json()["automations"]
    label = next(x for x in rules if x["id"] == rid)["sentence"]
    assert "מספר נוהל → מספר נוהל (מלא)" in label, label
    assert "מספר נוהל → מספר נוהל בתיק" in label, label


def test_the_extra_action_s_pairing_must_fit_its_own_board(client, admin_id):
    """The other half: a pairing that fits the RULE's target but not the
    extra action's own is refused, not saved to fail at every firing."""
    src, dst, status, num_src, num_dst, _c, signed, target = _setup(client, admin_id, "m5")
    third = _board(client, admin_id, "H4 תיקים m5")
    t_grp = client.get(f"/api/boards/{third}").json()["groups"][0]["id"]
    r = client.post(f"/api/boards/{src}/automations?user_id={admin_id}",
                    json={"recipe_id": RID, "config": {
                        "t_status": "o_signed", "t_status_col": status["id"],
                        "a_board": dst, "a_target_group": target, "a_text": "x",
                        "actions": [{"key": "create_in_board",
                                     "values": {"board": third, "target_group": t_grp,
                                                "text": "y",
                                                "map": [{"from": num_src, "to": num_dst}]}}]}})
    assert r.status_code == 400, r.text


def test_the_pairing_has_a_blank_when_the_action_is_a_further_one():
    """The builder draws a chip only where the action's `text` has a
    placeholder. "צור פריט בלוח אחר" says nothing about a pairing in its own
    words, so added with "+ הוסף פעולה" it had no blank to press — the
    pairing was reachable on the rule's first action and nowhere else."""
    c = next(x for x in recipes.actions_catalog() if x["key"] == "create_in_board")
    assert "{map}" in c["text"], c["text"]
    # …while the line the picker offers stays the bare wording
    assert "map" not in c["label"] and "·" not in c["label"], c["label"]
    # and an action with no pairing gains no slot
    c2 = next(x for x in recipes.actions_catalog() if x["key"] == "move_to_group")
    assert "·" not in c2["text"], c2["text"]


# ── every action that makes an item, not only create_in_board ─────────────

def test_create_and_link_carries_its_pairing_too(client, admin_id):
    """"צור פריט וקשר" — the same optional pairing, onto the board its link
    column points at, and still linked back."""
    src, dst, status, num_src, num_dst, _c, _s, _t = _setup(client, admin_id, "m6")
    client.patch(f"/api/boards/{src}",
                 json={"actor_id": admin_id, "columns": _cols(client, src) + [
                     {"type": "connect", "title": "קישור",
                      "connect": {"board_ids": [dst], "multiple": True, "two_way": True}}]})
    link = next(x for x in _cols(client, src) if x["type"] == "connect")
    r = client.post(f"/api/boards/{src}/automations?user_id={admin_id}",
                    json={"recipe_id": "status_create_and_link", "is_active": True, "config": {
                        "t_status": "o_signed", "t_status_col": status["id"],
                        "a_connect": link["id"], "a_board": dst, "a_text": "{{item.name}}",
                        "a_map": [{"from": num_src, "to": num_dst}]}})
    assert r.status_code == 200, r.text
    _fire(client, admin_id, src, status, "נוהל 61", {num_src: "N-61"})
    made = _made(dst, "נוהל 61")
    assert len(made) == 1 and (made[0].custom_fields or {}).get(num_dst) == "N-61", \
        made and made[0].custom_fields


def test_create_item_on_this_board_carries_its_pairing(client, admin_id):
    """"צור פריט" onto THIS board — the pairing is between two columns of the
    same board, and is held against this board's columns at the save."""
    src, _d, status, num_src, _n, _c, signed, _t = _setup(client, admin_id, "m7")
    copy_to = _add_col(client, src, admin_id,
                       {"id": "col_cp_m7", "type": "text", "title": "מספר מקור"})
    r = client.post(f"/api/boards/{src}/automations?user_id={admin_id}",
                    json={"recipe_id": "status_create_subitem", "is_active": True, "config": {
                        "t_status": "o_signed", "t_status_col": status["id"], "a_text": "תת",
                        "actions": [{"key": "create_item",
                                     "values": {"text": "המשך {{item.name}}", "group": signed,
                                                "map": [{"from": num_src, "to": copy_to}]}}]}})
    assert r.status_code == 200, r.text
    _fire(client, admin_id, src, status, "נוהל 71", {num_src: "N-71"})
    made = _made(src, "המשך נוהל 71")
    assert len(made) == 1 and (made[0].custom_fields or {}).get(copy_to) == "N-71", \
        made and made[0].custom_fields

    # a pairing naming a column that is not on THIS board is refused
    r = client.post(f"/api/boards/{src}/automations?user_id={admin_id}",
                    json={"recipe_id": "status_create_subitem", "config": {
                        "t_status": "o_signed", "t_status_col": status["id"], "a_text": "תת",
                        "actions": [{"key": "create_item",
                                     "values": {"text": "x", "group": signed,
                                                "map": [{"from": num_src, "to": "col_nope"}]}}]}})
    assert r.status_code == 400, r.text
