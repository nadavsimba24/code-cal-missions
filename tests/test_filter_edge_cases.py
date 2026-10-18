"""מקרי קצה — עמודה שנמחקה, ומשתמש שעזב.

Both are the same shape of problem: a saved filter outlives the thing it
names. They are handled in opposite ways, and the opposition is the point.

**A deleted column** takes its rule out of the tree. Letting it answer true
instead is the obvious shortcut and it is wrong: inside an "וגם" group the two
are identical, and inside an "או" group they are opposites — one deleted
column would make the group true and quietly show the whole board, filter
still lit, badge still counting, nothing filtered. Whoever opens the view is
told what was dropped, because a filter that silently means less than it says
is worse than one that is missing.

**A departed person** keeps their rule. The column still exists, and somebody
leaving does not unassign them from what they were working on — "what was
אורית doing before she left" is a question asked precisely because she left.
Only the label changes.
"""
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import filter_ast as F  # noqa: E402
import main as cityos_main  # noqa: E402
from models import User  # noqa: E402

SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
FIELDS = {"status": "status", "assignees": "people", "due": "date"}


# ── 1. a column that was deleted ──────────────────────────────────────────
def test_the_rule_is_removed_and_named():
    tree, dropped = F.prune(F.parse({"operator": "and", "rules": [
        {"field": "status", "operator": "eq", "value": "done"},
        {"field": "c_gone", "operator": "eq", "value": "x"}]}), FIELDS)
    assert len(tree["rules"]) == 1 and tree["rules"][0]["field"] == "status"
    assert dropped == ["c_gone"]
    assert F.count(tree) == 1


def test_removing_is_not_the_same_as_answering_true():
    """Inside "or" they are opposites, and this is the whole reason prune
    exists: one deleted column answering true shows the entire board."""
    raw = F.parse({"operator": "or", "rules": [
        {"field": "status", "operator": "eq", "value": "done"},
        {"field": "c_gone", "operator": "eq", "value": "x"}]})
    open_item = {"id": 1, "title": "x", "status": "todo", "custom_fields": {}}
    assert F.match(open_item, raw, FIELDS, "2026-10-18") is True, \
        "the unpruned tree matches everything — the bug being prevented"
    pruned, _ = F.prune(raw, FIELDS)
    assert F.match(open_item, pruned, FIELDS, "2026-10-18") is False


def test_a_group_left_empty_goes_too():
    tree, dropped = F.prune(F.parse({"operator": "and", "rules": [
        {"field": "status", "operator": "eq", "value": "done"},
        {"operator": "or", "rules": [
            {"field": "a_gone", "operator": "eq", "value": "1"},
            {"field": "b_gone", "operator": "eq", "value": "2"}]}]}), FIELDS)
    assert len(tree["rules"]) == 1 and tree["rules"][0]["field"] == "status"
    assert sorted(dropped) == ["a_gone", "b_gone"]


def test_a_view_whose_every_rule_is_gone_shows_the_whole_board():
    tree, dropped = F.prune(F.parse({"operator": "and", "rules": [
        {"field": "c_gone", "operator": "eq", "value": "1"}]}), FIELDS)
    assert F.count(tree) == 0 and dropped == ["c_gone"]
    assert F.match({"id": 1, "custom_fields": {}}, tree, FIELDS, "2026-10-18") is True


def test_the_endpoint_says_which_rules_it_could_not_run(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוח קצה",
                                           "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/items/query", json={
        "user_id": admin_id, "today": "2026-10-18",
        "filter": {"operator": "and", "rules": [
            {"field": "c_deleted", "operator": "eq", "value": "x"}]}})
    assert r.status_code == 200, r.text
    assert r.json()["dropped_fields"] == ["c_deleted"]
    assert r.json()["conditions"] == 0, "a rule that cannot run is still counted"


def test_the_person_opening_the_view_is_told():
    i = SRC.index("  apply(v){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "advPrune(" in body, "a saved view is applied without pruning it"
    assert "חלק מחוקי הסינון הוסרו כיוון שהעמודות שלהם נמחקו" in body


def test_the_repaired_view_is_not_written_back_over_the_saved_one():
    """Rewriting somebody's saved filter because they opened it is exactly
    the overwrite the locking rules exist to prevent. Repairing it is theirs
    to decide."""
    i = SRC.index("  apply(v){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "/api/views/" not in body, "opening a view saves over it"


# ── 2. a person who left ──────────────────────────────────────────────────
def test_a_rule_naming_somebody_who_left_is_kept_and_keeps_answering():
    tree = F.parse({"operator": "and", "rules": [
        {"field": "assignees", "operator": "has", "value": 9}]})
    pruned, dropped = F.prune(tree, FIELDS)
    assert dropped == [], "the column still exists; only the person is gone"
    hers = {"id": 1, "title": "x", "assignees": [{"id": 9}], "custom_fields": {}}
    mine = {"id": 2, "title": "y", "assignees": [{"id": 7}], "custom_fields": {}}
    assert F.match(hers, pruned, FIELDS, "2026-10-18") is True
    assert F.match(mine, pruned, FIELDS, "2026-10-18") is False


def test_the_filter_still_returns_rows_assigned_to_a_deactivated_user(client, admin_id, guinea_id):
    """End to end, with the account actually switched off. "What was she
    working on" is a question asked precisely because she left."""
    bid = client.post("/api/boards", json={"name": "לוח עזיבה",
                                           "user_id": admin_id}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    tid = client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                          "title": "שלה", "assignee_ids": [guinea_id]}).json()["id"]
    client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id, "title": "לא שלה"})

    with Session(cityos_main.engine) as db:
        u = db.query(User).filter(User.id == guinea_id).first()
        was, u.is_active = u.is_active, False
        db.commit()
    try:
        r = client.post(f"/api/boards/{bid}/items/query", json={
            "user_id": admin_id, "today": "2026-10-18",
            "filter": {"operator": "and", "rules": [
                {"field": "assignees", "operator": "has", "value": guinea_id}]}})
        assert r.status_code == 200, r.text
        assert r.json()["item_ids"] == [tid], r.json()
        assert r.json()["dropped_fields"] == []
    finally:
        with Session(cityos_main.engine) as db:
            db.query(User).filter(User.id == guinea_id).first().is_active = was
            db.commit()


def test_the_label_says_they_are_no_longer_active():
    i = SRC.index("function advPersonLabel(id)")
    body = SRC[i:SRC.index("\n}", i)]
    assert "משתמש לא פעיל" in body
    assert "is_active===false" in body and "boardPeople()" in body, \
        "somebody merely taken off the board reads as still on it"


def test_a_value_the_list_no_longer_offers_survives_being_redrawn():
    """A <select> drawn without an option for its own value shows the
    placeholder, and the next redraw writes that placeholder back. Nobody
    decides to drop her from the filter; the filter forgets her."""
    i = SRC.index("function advChoices(f,cur)")
    body = SRC[i:SRC.index("\nconst advField", i) if "\nconst advField" in SRC[i:i + 4000]
               else i + 1600]
    assert "!out.some(o=>o.v===String(cur))" in body, \
        "a value not in the list is not kept as an option"
    assert "gone:true" in body
    # and the builder asks for the choices per input, with the value in hand
    assert "advChoices(f,v)" in SRC, "the builder builds the list without the value"


def test_the_two_edge_cases_behave():
    """Driven harness: tests/frontend/filter_edge_cases.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "filter_edge_cases.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


# ── 3. a column this reader may not see ───────────────────────────────────
def _closed_board(client, admin_id, guinea_id):
    """A board with a תקציב column the guinea may not see, and two items."""
    bid = client.post("/api/boards", json={"name": "לוח תקציב",
                                           "user_id": admin_id}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    cols = client.patch(f"/api/boards/{bid}",
                        json={"user_id": admin_id,
                              "columns": [{"type": "number", "title": "תקציב"}]}).json()["columns"]
    cid = cols[0]["id"]
    # the endpoint takes one user and one permission — `user_id` is the
    # TARGET here, so the actor travels in the header
    r = client.post(f"/api/boards/{bid}/columns/{cid}/permissions",
                    json={"user_id": guinea_id, "perm": "none"},
                    headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 200, r.text
    assert (r.json()["columns"][0].get("perms") or {}).get(str(guinea_id)) == "none"
    big = client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                          "title": "גדול",
                                          "custom_fields": {cid: 5_000_000}}).json()["id"]
    small = client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                            "title": "קטן",
                                            "custom_fields": {cid: 10}}).json()["id"]
    return bid, cid, big, small


def _ask(client, bid, uid, cid):
    return client.post(f"/api/boards/{bid}/items/query", json={
        "user_id": uid, "today": "2026-10-18",
        "filter": {"operator": "and", "rules": [
            {"field": cid, "operator": "gt", "value": 1_000_000}]}},
        headers={"X-CityOS-User": str(uid)})


def test_the_rule_runs_for_somebody_who_may_see_the_column(client, admin_id, guinea_id):
    bid, cid, big, _small = _closed_board(client, admin_id, guinea_id)
    d = _ask(client, bid, admin_id, cid).json()
    assert d["item_ids"] == [big]
    assert d["denied_fields"] == []


def test_the_rule_does_not_run_for_somebody_who_may_not(client, admin_id, guinea_id):
    """And the direction matters: dropping the rule is the SAFE one. Applying
    it would answer a question about hidden figures with a row set, and a row
    set is an answer — they would read the budgets off which rows survived."""
    bid, cid, big, small = _closed_board(client, admin_id, guinea_id)
    d = _ask(client, bid, guinea_id, cid).json()
    # a new board comes with sample items of its own, so the test is that
    # NOTHING was filtered out rather than that exactly two came back
    assert {big, small} <= set(d["item_ids"]), "the hidden column filtered their board"
    assert d["matched"] == d["total"], "the rule narrowed the board for them"
    assert d["denied_fields"] == [cid]
    assert d["dropped_fields"] == [], "reported as a deletion rather than a permission"
    assert d["conditions"] == 0


def test_the_two_reasons_are_told_apart(client, admin_id, guinea_id):
    """"The column was deleted" and "you may not see it" are different facts
    about the board, and telling somebody the wrong one is its own small
    lie."""
    bid, cid, _big, _small = _closed_board(client, admin_id, guinea_id)
    r = client.post(f"/api/boards/{bid}/items/query", json={
        "user_id": guinea_id, "today": "2026-10-18",
        "filter": {"operator": "and", "rules": [
            {"field": cid, "operator": "gt", "value": 1},
            {"field": "c_never_existed", "operator": "eq", "value": "x"}]}},
        headers={"X-CityOS-User": str(guinea_id)})
    d = r.json()
    assert d["denied_fields"] == [cid]
    assert d["dropped_fields"] == ["c_never_existed"]


def test_the_policy_can_be_set_to_block_instead(client, admin_id, guinea_id, monkeypatch):
    """No inference of any kind, not even from the view's name. The cost is
    that a shared view stops working across permission tiers, which for most
    boards is the worse trade — hence it is the setting and not the default."""
    bid, cid, _big, _small = _closed_board(client, admin_id, guinea_id)
    monkeypatch.setattr(cityos_main, "FILTER_COLUMN_POLICY", "block")
    r = _ask(client, bid, guinea_id, cid)
    assert r.status_code == 403
    assert "אינך מורשה" in r.json()["detail"]
    # and the person who may see it is unaffected
    assert _ask(client, bid, admin_id, cid).status_code == 200


def test_the_policy_is_configuration(client, admin_id):
    assert cityos_main.FILTER_COLUMN_POLICY in ("skip", "block")
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("FILTER_COLUMN_POLICY")' in src
    bid = client.post("/api/boards", json={"name": "ל", "user_id": admin_id}).json()["id"]
    b = client.get(f"/api/boards/{bid}?user_id={admin_id}",
                   headers={"X-CityOS-User": str(admin_id)}).json()
    assert b["filter_column_policy"] == cityos_main.FILTER_COLUMN_POLICY, \
        "the browser cannot know which policy to apply"


def test_a_closed_column_is_not_offered_in_the_builder():
    """Offering it would be a leak on its own: you would learn the column
    exists, and could ask about it."""
    i = SRC.index("function advFields()")
    body = SRC[i:SRC.index("\nconst advField", i)]
    assert "advColHidden(c.id)" in body
    j = SRC.index("function advColHidden(colId)")
    assert "col_perms" in SRC[j:j + 200] and "'none'" in SRC[j:j + 200]
