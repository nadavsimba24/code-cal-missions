"""העברת כמה פריטים לקבוצה — בקשה אחת, טרנזקציה אחת, סדר שנשמר.

Moving a selection used to be one round trip per item, each renumbering the
group the item left and the group it joined, followed by a refetch of the whole
board. That is why it was slow — and why the calls could not simply be fired in
parallel: two of them renumbering one group at the same time leave two items
claiming one position, and the board reads back ordered by position alone, so a
row springs back to where it was.

This pins the endpoint that replaced it: what it moves, what it refuses, the
order it leaves behind, and that it answers with enough for the caller to place
its rows without asking for the board again.
"""
import main as cityos_main
from models import Task
from sqlalchemy.orm import Session


def _group(client, board_id, name, admin_id):
    r = client.post("/api/groups", json={"board_id": board_id, "name": name, "actor_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item(client, board_id, gid, title, admin_id):
    r = client.post("/api/tasks", json={"board_id": board_id, "group_id": gid,
                                        "title": title, "actor_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _order(board_id, gid):
    with Session(cityos_main.engine) as db:
        return [t.id for t in cityos_main._group_items(db, board_id, gid)]


def _positions(board_id, gid):
    with Session(cityos_main.engine) as db:
        return [t.position for t in cityos_main._group_items(db, board_id, gid)]


def test_a_selection_moves_in_one_call_and_keeps_its_order(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוח העברות", "user_id": admin_id}).json()["id"]
    src1, src2, dst = (_group(client, bid, n, admin_id) for n in ("מקור א", "מקור ב", "יעד"))
    a = _item(client, bid, src1, "א", admin_id)
    b = _item(client, bid, src1, "ב", admin_id)
    c = _item(client, bid, src2, "ג", admin_id)
    sitting = _item(client, bid, dst, "יושב", admin_id)

    r = client.post(f"/api/boards/{bid}/items/move",
                    json={"actor_id": admin_id, "ids": [c, a, b], "group_id": dst})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [m["id"] for m in body["moved"]] == [c, a, b]
    assert body["missing"] == [] and body["unchanged"] == []

    # the item already there keeps its place; the moved ones follow in the order asked for
    assert _order(bid, dst) == [sitting, c, a, b]
    # dense, so nothing can tie and spring back
    assert _positions(bid, dst) == [0, 1, 2, 3]
    # and the groups they left closed their gaps
    assert _positions(bid, src1) == [] and _order(bid, src2) == []

    # the answer is enough to place the rows without refetching the board
    by_group = {g["group_id"]: g["ids"] for g in body["order"]}
    assert by_group[dst] == [sitting, c, a, b]
    assert by_group[src1] == [] and by_group[src2] == []


def test_it_refuses_what_is_not_this_board_s_to_move(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוח א", "user_id": admin_id}).json()["id"]
    other = client.post("/api/boards", json={"name": "לוח ב", "user_id": admin_id}).json()["id"]
    g = _group(client, bid, "קבוצה", admin_id)
    mine = _item(client, bid, None, "שלי", admin_id)
    theirs = _item(client, other, None, "של לוח אחר", admin_id)
    parent = _item(client, bid, None, "אב", admin_id)
    sub = client.post("/api/tasks", json={"board_id": bid, "parent_id": parent,
                                          "title": "תת", "actor_id": admin_id}).json()["id"]

    r = client.post(f"/api/boards/{bid}/items/move",
                    json={"actor_id": admin_id, "ids": [mine, theirs, sub, 99999], "group_id": g})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [m["id"] for m in body["moved"]] == [mine]
    # a board's own id space: another board's item, a sub-item and a stranger are named, not moved
    assert set(body["missing"]) == {theirs, sub, 99999}
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.id == sub).first().parent_id == parent
        assert db.query(Task).filter(Task.id == theirs).first().board_id == other


def test_an_item_already_in_the_target_group_is_left_alone(client, admin_id):
    """Re-appending it would reorder a group nobody asked to reorder."""
    bid = client.post("/api/boards", json={"name": "לוח שקט", "user_id": admin_id}).json()["id"]
    g = _group(client, bid, "קבוצה", admin_id)
    first = _item(client, bid, g, "ראשון", admin_id)
    second = _item(client, bid, g, "שני", admin_id)

    r = client.post(f"/api/boards/{bid}/items/move",
                    json={"actor_id": admin_id, "ids": [first], "group_id": g})
    assert r.status_code == 200, r.text
    assert r.json()["moved"] == [] and r.json()["unchanged"] == [first]
    assert _order(bid, g) == [first, second]


def test_a_viewer_cannot_move_anything(client, admin_id, guinea_id):
    bid = client.post("/api/boards", json={"name": "לוח הרשאות", "user_id": admin_id}).json()["id"]
    g = _group(client, bid, "קבוצה", admin_id)
    t = _item(client, bid, None, "פריט", admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})

    r = client.post(f"/api/boards/{bid}/items/move?user_id={guinea_id}",
                    json={"ids": [t], "group_id": g})
    assert r.status_code == 403, r.text


def test_nothing_selected_is_an_error_not_a_silent_success(client, admin_id):
    bid = client.post("/api/boards", json={"name": "לוח ריק", "user_id": admin_id}).json()["id"]
    g = _group(client, bid, "קבוצה", admin_id)
    assert client.post(f"/api/boards/{bid}/items/move",
                       json={"actor_id": admin_id, "ids": [], "group_id": g}).status_code == 400
    assert client.post(f"/api/boards/{bid}/items/move",
                       json={"actor_id": admin_id, "ids": [1], "group_id": 999999}).status_code == 404
