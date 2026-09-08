"""Moving an item between groups by its status is an automation, not a rule of
the software.

Setting a status used to file the item into the group that stood for that
status. Nobody wrote that rule, it was on every board that had ever existed and
every board created since, it was absent from the board's own list of
automations, and there was no switch for it. It also had to guess: a board with
two in_progress groups has no single right answer, and the code carried a
growing list of exceptions — skip groups left at the default status, no fallback
by status family — every one of them a report about an item that moved somewhere
nobody asked for.

The catalog already had the rule as a recipe: status_changes_to → move_to_group,
with the group named by whoever set it up. That is now the only way an item
moves by itself, which makes it visible in the automations list, switchable, and
answerable to the person who wrote it.
"""
import pytest

from conftest import ADMIN_ID


@pytest.fixture
def board(client):
    """A fresh board — three groups, one per stage, exactly as one is created."""
    bid = client.post("/api/boards", json={"name": "אוטומציות קבוצה",
                                           "user_id": ADMIN_ID}).json()["id"]
    b = client.get(f"/api/boards/{bid}?user_id={ADMIN_ID}").json()
    groups = {g["task_status"]: g["id"] for g in b["groups"]}
    return {"id": bid, "groups": groups, "first": b["groups"][0]["id"]}


def _item(client, board, **kw):
    body = {"board_id": board["id"], "title": "פריט", "group_id": board["first"],
            "user_id": ADMIN_ID}
    body.update(kw)
    return client.post("/api/tasks", json=body).json()


def _where(client, board, tid):
    b = client.get(f"/api/boards/{board['id']}?user_id={ADMIN_ID}").json()
    return next(t for t in b["tasks"] if t["id"] == tid)["group_id"]


def _rule(client, board, status, group_id, **kw):
    r = client.post(f"/api/boards/{board['id']}/automations",
                    json={"user_id": ADMIN_ID, "recipe_id": "status_move_group",
                          "config": {"t_status": status, "a_group": group_id}, **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()


# ── nothing moves on its own ───────────────────────────────────────────────
def test_a_new_board_has_no_automations_at_all(client, board):
    """Every rule on a board is one somebody put there."""
    d = client.get(f"/api/boards/{board['id']}/automations?user_id={ADMIN_ID}").json()
    assert d["automations"] == []


def test_a_status_change_leaves_the_item_where_it_is(client, board):
    """Including a status this board has a group for — that group is not a magnet."""
    t = _item(client, board)
    for status in ("in_progress", "done", "backlog", "review", "todo"):
        assert client.patch(f"/api/tasks/{t['id']}",
                            json={"user_id": ADMIN_ID, "status": status}).status_code == 200
        assert _where(client, board, t["id"]) == board["first"], \
            f"{status} moved the item with no automation asking for it"


def test_an_item_created_with_a_status_is_not_filed_by_it(client, board):
    t = _item(client, board, status="done")
    assert t["group_id"] == board["first"]


def test_a_parent_completing_by_itself_still_does_not_move(client, board):
    """The roll-up marks the parent done; where a done item belongs is a rule."""
    p = _item(client, board)
    subs = [_item(client, board, parent_id=p["id"], title=f"s{i}") for i in (1, 2)]
    for s in subs:
        client.patch(f"/api/tasks/{s['id']}", json={"user_id": ADMIN_ID, "status": "done"})
    b = client.get(f"/api/boards/{board['id']}?user_id={ADMIN_ID}").json()
    parent = next(t for t in b["tasks"] if t["id"] == p["id"])
    assert parent["status"] == "done"                 # the roll-up still happens
    assert parent["group_id"] == board["first"]       # and it happens in place


# ── and with a rule, it does ───────────────────────────────────────────────
def test_the_automation_is_what_moves_it(client, board):
    """The behaviour is not gone — it is written down."""
    done = board["groups"]["done"]
    _rule(client, board, "done", done)
    t = _item(client, board)
    client.patch(f"/api/tasks/{t['id']}", json={"user_id": ADMIN_ID, "status": "done"})
    assert _where(client, board, t["id"]) == done


def test_it_moves_only_for_the_status_the_rule_names(client, board):
    _rule(client, board, "done", board["groups"]["done"])
    t = _item(client, board)
    client.patch(f"/api/tasks/{t['id']}", json={"user_id": ADMIN_ID, "status": "in_progress"})
    assert _where(client, board, t["id"]) == board["first"]


def test_the_group_is_named_by_the_rule_not_guessed_from_the_status(client, board):
    """The whole reason the built-in rule could not be right: which group a status
    means is the board's decision, not the status's."""
    _rule(client, board, "done", board["groups"]["backlog"])   # deliberately not the done group
    t = _item(client, board)
    client.patch(f"/api/tasks/{t['id']}", json={"user_id": ADMIN_ID, "status": "done"})
    assert _where(client, board, t["id"]) == board["groups"]["backlog"]


# ── and it is there to be seen and switched off ────────────────────────────
def test_the_rule_is_listed_with_the_board_s_automations(client, board):
    a = _rule(client, board, "done", board["groups"]["done"])
    d = client.get(f"/api/boards/{board['id']}/automations?user_id={ADMIN_ID}").json()
    listed = [x for x in d["automations"] if x["id"] == a["id"]]
    assert listed, "the rule that moves items is not in the list of automations"
    assert listed[0]["is_active"] is True
    assert listed[0].get("sentence"), "a listed rule says what it does"


def test_switching_it_off_stops_the_moving(client, board):
    a = _rule(client, board, "done", board["groups"]["done"])
    assert client.patch(f"/api/automations/{a['id']}",
                        json={"user_id": ADMIN_ID, "is_active": False}).status_code == 200
    t = _item(client, board)
    client.patch(f"/api/tasks/{t['id']}", json={"user_id": ADMIN_ID, "status": "done"})
    assert _where(client, board, t["id"]) == board["first"]


def test_deleting_it_stops_the_moving_too(client, board):
    a = _rule(client, board, "done", board["groups"]["done"])
    assert client.delete(f"/api/automations/{a['id']}?user_id={ADMIN_ID}").status_code == 200
    t = _item(client, board)
    client.patch(f"/api/tasks/{t['id']}", json={"user_id": ADMIN_ID, "status": "done"})
    assert _where(client, board, t["id"]) == board["first"]


def test_the_write_says_where_the_item_ended_up(client, board):
    """The one client the live stream never tells is the one who made the change
    — it would be echoing their own edit back at them. So a move made by a rule
    has to come back with the write, or the person who set the status watches
    the row sit still until something else redraws the board."""
    done = board["groups"]["done"]
    _rule(client, board, "done", done)
    t = _item(client, board)
    r = client.patch(f"/api/tasks/{t['id']}", json={"user_id": ADMIN_ID, "status": "done"})
    assert r.status_code == 200, r.text
    assert r.json().get("group_id") == done

    unmoved = _item(client, board)
    r2 = client.patch(f"/api/tasks/{unmoved['id']}",
                      json={"user_id": ADMIN_ID, "status": "in_progress"})
    assert r2.json().get("group_id") == board["first"]


# ── the grid does not have its own copy of the rule ────────────────────────
def test_the_board_screen_does_not_move_the_row_by_itself(client):
    """The grid mirrored the server's move so the row did not wait for a refresh.
    A mirror of a rule that no longer exists is the rule, still running, in the
    one place nobody would look for it."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "x.task_status===value" not in src, \
        "the grid still files a row into a group by its status"
    assert "_group_for_status" not in src
    # ...and it does not have to: it follows what came back from the write
    assert "res.group_id!==t.group_id" in src, \
        "the grid ignores the group the server put the item in"
