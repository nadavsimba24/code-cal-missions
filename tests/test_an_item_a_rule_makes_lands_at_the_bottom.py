"""An item an automation makes lands at the bottom of its group.

The two ways a person adds an item each land it at a fixed place: the
"+ הוסף פריט" line at the foot of a group puts it last, and the "פריט חדש"
button at the top of the board puts it first in the first group. An item a
rule makes is the third way, and it never said where. It took the column
default, 0, which tied it with the group's first row. The tie went by id, so
the new item showed up second: neither the top nor the bottom. After that, the
group's numbers no longer matched what the board showed, so the next item a
person added could also land somewhere unexpected.

This pins that a rule-made item gets the same "last" a person's "+ הוסף פריט"
gets.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Task


def _order(bid, gid):
    with Session(cityos_main.engine) as db:
        rows = (db.query(Task).filter(Task.board_id == bid, Task.group_id == gid,
                                      Task.parent_id == None)          # noqa: E711
                .order_by(Task.position, Task.id).all())
        return [t.title for t in rows]


def test_an_item_a_rule_makes_is_the_last_row_of_its_group(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוח פריט מכלל בתחתית",
                                           "user_id": admin_id}).json()["id"]
    gid = client.post("/api/groups", json={"board_id": bid, "name": "יעד",
                                           "actor_id": admin_id}).json()["id"]
    try:
        for name in ("ראשון", "שני", "שלישי"):
            r = client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                                "title": name, "user_id": admin_id})
            assert r.status_code == 200, r.text
        r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                        json={"recipe_id": "status_set_priority",
                              "config": {"t_status": "done", "a_priority": "high",
                                         "actions": [{"key": "create_item",
                                                      "values": {"text": "מהכלל",
                                                                 "group": gid}}]}})
        assert r.status_code == 200, r.text
        trigger = client.post("/api/tasks", json={"board_id": bid, "title": "מפעיל",
                                                  "user_id": admin_id}).json()["id"]
        client.patch(f"/api/tasks/{trigger}", json={"status": "done", "user_id": admin_id})

        assert _order(bid, gid) == ["ראשון", "שני", "שלישי", "מהכלל"]

        # and the group still counts properly afterwards: a person's next
        # "+ הוסף פריט" goes under the rule's item, not beside an old row
        client.post("/api/tasks", json={"board_id": bid, "group_id": gid,
                                        "title": "רביעי", "user_id": admin_id})
        assert _order(bid, gid) == ["ראשון", "שני", "שלישי", "מהכלל", "רביעי"]
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")
