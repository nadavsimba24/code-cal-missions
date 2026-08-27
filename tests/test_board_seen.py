"""נצפה לאחרונה — who has opened the board, and when.

A different question from the activity log beside it: someone can read a board
every morning and never change a thing on it.
"""
import time

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _seen(client, bid, uid):
    return client.get(f"/api/boards/{bid}/seen", headers=AS(uid)).json()


def _mark(client, bid, uid):
    return client.post(f"/api/boards/{bid}/seen", json={"user_id": uid}, headers=AS(uid))


def test_opening_a_board_records_who_and_when(client, admin_id):
    bid = _board(client, admin_id, "נצפה s1")
    assert _seen(client, bid, admin_id)["seen"] == []
    assert _mark(client, bid, admin_id).status_code == 200
    d = _seen(client, bid, admin_id)
    assert len(d["seen"]) == 1
    e = d["seen"][0]
    assert e["user_id"] == admin_id and e["name"] and e["seen_at"]
    assert "avatar_url" in e, "the row cannot render an avatar without this"


def test_a_second_visit_updates_the_time_it_does_not_add_a_row(client, admin_id):
    """One row per person: the question is who has seen it lately, not how many
    times each of them looked."""
    bid = _board(client, admin_id, "נצפה s2")
    _mark(client, bid, admin_id)
    first = _seen(client, bid, admin_id)["seen"][0]["seen_at"]
    time.sleep(1.05)
    _mark(client, bid, admin_id)
    d = _seen(client, bid, admin_id)
    assert len(d["seen"]) == 1
    assert d["seen"][0]["seen_at"] > first, "the visit did not refresh the time"


def test_the_most_recent_viewer_is_first(client, admin_id, member_id, guinea_id):
    bid = _board(client, admin_id, "נצפה s3")
    for uid in (member_id, guinea_id):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    _mark(client, bid, member_id); time.sleep(1.05)
    _mark(client, bid, guinea_id); time.sleep(1.05)
    _mark(client, bid, admin_id)
    assert [e["user_id"] for e in _seen(client, bid, admin_id)["seen"]] == \
        [admin_id, guinea_id, member_id]


def test_it_also_says_who_has_never_opened_it(client, admin_id, member_id):
    bid = _board(client, admin_id, "נצפה s4")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _mark(client, bid, admin_id)
    d = _seen(client, bid, admin_id)
    assert [e["user_id"] for e in d["seen"]] == [admin_id]
    assert member_id in [u["user_id"] for u in d["never"]]
    assert d["total_members"] >= 2


def test_someone_who_left_the_board_stays_in_the_history(client, admin_id, guinea_id):
    """They did look. A history that quietly drops them is not a history — but
    it says they are no longer on the board, so the row is not misleading."""
    bid = _board(client, admin_id, "נצפה s5")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    _mark(client, bid, guinea_id)
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    e = next(x for x in _seen(client, bid, admin_id)["seen"] if x["user_id"] == guinea_id)
    assert e["is_member"] is False
    assert e["user_id"] not in [u["user_id"] for u in _seen(client, bid, admin_id)["never"]]


# ── permissions ─────────────────────────────────────────────────────────────

def test_a_non_member_cannot_read_the_list(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "נצפה p1")
    assert client.get(f"/api/boards/{bid}/seen", headers=AS(guinea_id)).status_code == 403


def test_a_non_member_cannot_record_a_visit(client, admin_id, guinea_id):
    """Otherwise anyone could put their name on any board's list."""
    bid = _board(client, admin_id, "נצפה p2")
    assert _mark(client, bid, guinea_id).status_code == 403
    assert _seen(client, bid, admin_id)["seen"] == []


def test_a_plain_member_may_read_it(client, admin_id, member_id):
    """The same gate as the activity log next to it — it answers a question of
    the same kind, so it is not a manager-only view."""
    bid = _board(client, admin_id, "נצפה p3")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "viewer"})
    assert client.get(f"/api/boards/{bid}/seen", headers=AS(member_id)).status_code == 200


def test_a_deleted_board_has_no_list(client, admin_id):
    bid = _board(client, admin_id, "נצפה p4")
    _mark(client, bid, admin_id)
    client.delete(f"/api/boards/{bid}?user_id={admin_id}")
    assert client.get(f"/api/boards/{bid}/seen", headers=AS(admin_id)).status_code == 404
    assert client.post(f"/api/boards/{bid}/seen", json={"user_id": admin_id},
                       headers=AS(admin_id)).status_code == 404


def test_each_board_keeps_its_own_list(client, admin_id):
    a, b = _board(client, admin_id, "נצפה x1"), _board(client, admin_id, "נצפה x2")
    _mark(client, a, admin_id)
    assert len(_seen(client, a, admin_id)["seen"]) == 1
    assert _seen(client, b, admin_id)["seen"] == []
