"""כאשר סטטוס משתנה — צור פריט בלוח אחר, והעבר את הפריט לקבוצה.

The rule as monday writes it: "When «סטטוס נוהל» changes to «ועדת שלושה
חתומה», create an item in «H3 חוזים», and then move item to «נחתמה ועדת
שלושה»". Both halves were already actions here; what was missing was a
template that STARTS with both, so nobody had to find "+ הוסף פעולה" to say
the second — and the question asked was whether such a rule exists at all.

What is pinned: the template is in the library under its own name and says
it starts with the move; a rule built from it creates the item on the other
board AND moves the item that set it off (not the new one) in its own board;
and it is the ordinary rule underneath — no hand-built twin offered beside the
general one in the from-scratch flow.
"""
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Task

RID = "status_create_in_board_and_move"


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _group(client, bid, admin_id, name):
    r = client.post("/api/groups", json={"board_id": bid, "name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _status_col(client, bid, admin_id):
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    col = {"id": "col_noh" + str(len(cols)), "type": "status", "title": "סטטוס נוהל",
           "options": [{"id": "o_open", "label": "בטיפול"},
                       {"id": "o_signed", "label": "ועדת שלושה חתומה"}]}
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols + [col]})
    assert r.status_code == 200, r.text
    return col


def test_the_library_offers_it_by_name_starting_with_the_move():
    t = next(x for x in recipes.catalog() if x["id"] == RID)
    assert t["title"] == "כאשר סטטוס משתנה, צור פריט בלוח אחר והעבר את הפריט לקבוצה"
    assert t["action"] == "create_in_board"
    assert t["then"] == ["move_to_group"]
    # the move needs a group on THIS board, so the library says so up front
    assert "group" in t["needs"]
    # every other template starts with its own action alone
    assert all(x["then"] == [] for x in recipes.catalog() if x["id"] != RID)


def test_it_is_not_a_second_entry_in_the_from_scratch_flow():
    picked = [a["recipe_id"] for b in recipes.blueprint()
              if b["trigger"] == "status_changes_to" for a in b["actions"]]
    assert RID not in picked
    assert "status_create_in_board" in picked


def test_the_rule_creates_on_the_other_board_and_moves_this_item(client, admin_id):
    src = _board(client, admin_id, "לוח נהלים")
    dst = _board(client, admin_id, "H3 חוזים")
    col = _status_col(client, src, admin_id)
    signed = _group(client, src, admin_id, "נחתמה ועדת שלושה")
    target = client.get(f"/api/boards/{dst}?user_id={admin_id}").json()["groups"][0]["id"]
    r = client.post(f"/api/boards/{src}/automations?user_id={admin_id}",
                    json={"recipe_id": RID, "is_active": True, "config": {
                        "t_status": "o_signed", "t_status_col": col["id"],
                        "a_board": dst, "a_target_group": target, "a_text": "חוזה חדש",
                        "actions": [{"key": "move_to_group", "values": {"group": signed}}]}})
    assert r.status_code == 200, r.text

    tid = client.post("/api/tasks", json={"board_id": src, "title": "נוהל 7",
                                          "user_id": admin_id}).json()["id"]
    r = client.patch(f"/api/tasks/{tid}",
                     json={"custom_fields": {col["id"]: {"id": "o_signed",
                                                         "label": "ועדת שלושה חתומה"}},
                           "user_id": admin_id})
    assert r.status_code == 200, r.text

    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == dst, Task.title == "חוזה חדש",
                                     Task.deleted_at == None).all()     # noqa: E711
        assert len(made) == 1 and made[0].group_id == target
        moved = db.query(Task).filter(Task.id == tid).first()
        assert moved.board_id == src and moved.group_id == signed, \
            "the move is of the item that set the rule off, in its own board"
