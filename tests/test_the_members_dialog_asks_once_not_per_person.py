"""Opening "משתתפים" costs the same however many accounts the system has.

GET /api/boards/{id}/members built the invitation list by asking about every
user in the system one at a time — _outside_board_env per person, which is
_env_role, which is _can_admin_envs, which is _cap, which is _ws_role: five or
six queries each. On production's 241 accounts that was some 1,400 queries
against a remote database before the dialog could open, and the button looked
dead for seconds in both environments.

Two things are pinned:

- the number of queries does not grow with the number of accounts — ten more
  people in the system cost the request nothing extra;
- the batched answer is the per-person rule's answer: for every active
  non-member, being offered is exactly "_outside_board_env lets them in". The
  invitation itself still asks the per-person rule, so a drift between the two
  would show up here before it showed up as a picker offering the wrong people.
"""
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import join_primary_env


def AS(uid):
    return {"X-CityOS-User": str(uid)}


def _queries(client, admin_id, bid):
    n = [0]

    def count(*_a, **_k):
        n[0] += 1
    event.listen(cityos_main.engine, "before_cursor_execute", count)
    try:
        r = client.get(f"/api/boards/{bid}/members", headers=AS(admin_id))
    finally:
        event.remove(cityos_main.engine, "before_cursor_execute", count)
    assert r.status_code == 200, r.text
    return n[0], r.json()


def _user(client, admin_id, i, in_env):
    email = f"members.count.{i}@cityos.test"
    for u in client.get("/api/users", headers=AS(admin_id)).json():
        if u.get("email") == email:
            uid = u["id"]
            break
    else:
        r = client.post("/api/users", headers=AS(admin_id),
                        json={"name": f"נספר {i}", "email": email, "role": "member"})
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
    if in_env:
        join_primary_env(client, uid)
    return uid


@pytest.fixture
def board(client, admin_id):
    r = client.post("/api/boards", headers=AS(admin_id),
                    json={"name": "דלת המשתתפים", "workspace_id": 1})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    try:
        yield bid
    finally:
        client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


def test_ten_more_accounts_cost_the_dialog_no_extra_queries(client, admin_id, board):
    before, _ = _queries(client, admin_id, board)
    # half of them in the board's environment and half outside it, so both
    # branches of the rule are paid for if they are paid per person
    for i in range(10):
        _user(client, admin_id, i, in_env=(i % 2 == 0))
    after, _ = _queries(client, admin_id, board)
    assert after <= before, (
        f"{before} queries became {after} with ten more accounts — the "
        "invitation list is asking about people one at a time again")


def test_the_batched_answer_is_the_per_person_rule(client, admin_id, board):
    for i in range(10):
        _user(client, admin_id, i, in_env=(i % 2 == 0))
    _, body = _queries(client, admin_id, board)
    offered = {u["id"] for u in body["available"]}
    members = {m["user_id"] for m in body["members"]}
    with Session(cityos_main.engine) as db:
        b = db.query(cityos_main.Board).filter(cityos_main.Board.id == board).first()
        expected = {u.id for u in db.query(cityos_main.User).all()
                    if u.id not in members and u.is_active is not False
                    and not cityos_main._outside_board_env(db, b, u.id)}
    assert offered == expected, (
        f"offered but refused on invite: {sorted(offered - expected)}; "
        f"allowed but not offered: {sorted(expected - offered)}")
    assert offered, "nobody at all is invitable — the test proves nothing"
