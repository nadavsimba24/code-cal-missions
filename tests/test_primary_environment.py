"""הסביבה הראשית — a workspace like any other, by invitation.

One environment is flagged primary: it is where new boards land, it is the one
the app opens in, and it cannot be deleted. What it is NOT any more is a
workspace everybody is in by definition.

That rule used to be the opposite, and it was not a row in the table — being a
user WAS being a member. The price was paid one screen away: a board can only
invite people who are already in its environment, so on the workspace almost
every board lives in, that list was the entire user directory. Membership is
now a row somebody wrote, here as everywhere else.

Nobody lost access when it changed: _seed_environments backfills a row for
everyone already sitting on a board in the primary workspace, which is what
their access was resting on.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Board, Environment, EnvironmentMember, User

H = {"X-CityOS-User": "1", "host": "localhost"}


def _primary(db):
    return db.query(Environment).filter(Environment.is_primary == True).first()  # noqa: E712


def _mk_user(client, admin_id, email, name="משתמש חדש"):
    for u in client.get("/api/users").json():
        if u.get("email") == email:
            return u["id"]
    return client.post("/api/users", json={"actor_id": admin_id, "name": name,
                                           "email": email, "role": "member"}).json()["id"]


def _env_ids_for(client, uid):
    return {e["id"] for e in client.get(f"/api/environments?user_id={uid}").json()["environments"]}


def _members(client, env_id, admin_id):
    return client.get(f"/api/environments/{env_id}/members?actor_id={admin_id}").json()


def test_the_default_workspace_is_called_the_primary_one(client):
    with Session(cityos_main.engine) as db:
        assert _primary(db).name == "סביבה ראשית"


def test_a_user_created_today_is_in_no_workspace_until_somebody_adds_them(client, admin_id):
    """The whole point of the change: an account is not an invitation."""
    uid = _mk_user(client, admin_id, "primary.newcomer@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    assert pid not in _env_ids_for(client, uid)
    assert _env_ids_for(client, uid) == set(), "a new account belongs to nothing"


def test_adding_them_puts_them_in_it(client, admin_id):
    uid = _mk_user(client, admin_id, "primary.added@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    r = client.post(f"/api/environments/{pid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": "member"})
    assert r.status_code == 200, r.text
    assert pid in _env_ids_for(client, uid)
    assert uid in {m["user_id"] for m in _members(client, pid, admin_id)["members"]}


def test_and_they_can_be_taken_out_of_it_again(client, admin_id):
    """It used to answer 400: nobody could be removed from a workspace that was
    everybody's. Now removal is refused for one reason only — the same one as
    in every other workspace — that a board inside it still names them."""
    uid = _mk_user(client, admin_id, "primary.removable@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    client.post(f"/api/environments/{pid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "member"})
    r = client.delete(f"/api/environments/{pid}/members/{uid}?actor_id={admin_id}")
    assert r.status_code == 200, r.text
    assert pid not in _env_ids_for(client, uid)


def test_somebody_on_a_board_in_it_still_cannot_be_removed(client, admin_id):
    """The guard that keeps the backfill honest: taking the row away would take
    a board they are on with it."""
    uid = _mk_user(client, admin_id, "primary.onaboard@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    client.post(f"/api/environments/{pid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "member"})
    bid = client.post("/api/boards",
                      json={"name": "לוח שמחזיק אותם", "user_id": admin_id}).json()["id"]
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    try:
        r = client.delete(f"/api/environments/{pid}/members/{uid}?actor_id={admin_id}")
        assert r.status_code == 400, r.text
        assert "לוחות הבאים" in r.json()["detail"], r.json()
        assert pid in _env_ids_for(client, uid)
    finally:
        client.delete(f"/api/boards/{bid}/members/{uid}?actor_id={admin_id}")


def test_a_manager_of_it_can_be_appointed_and_stood_down(client, admin_id):
    """Appointing is a role change on a member, as in every other workspace —
    it used to be the one place a PATCH wrote a member's first row."""
    uid = _mk_user(client, admin_id, "primary.manager@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    client.post(f"/api/environments/{pid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "member"})
    r = client.patch(f"/api/environments/{pid}/members/{uid}",
                     json={"actor_id": admin_id, "role": "manager"})
    assert r.status_code == 200, r.text
    got = _members(client, pid, admin_id)
    assert [m for m in got["members"] if m["user_id"] == uid][0]["role"] == "manager"

    r = client.patch(f"/api/environments/{pid}/members/{uid}",
                     json={"actor_id": admin_id, "role": "member"})
    assert r.status_code == 200, r.text
    got = _members(client, pid, admin_id)
    assert [m for m in got["members"] if m["user_id"] == uid][0]["role"] == "member"
    assert pid in _env_ids_for(client, uid), "standing a manager down leaves a member"


def test_promoting_somebody_who_is_not_in_it_is_a_404(client, admin_id):
    uid = _mk_user(client, admin_id, "primary.notin@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    r = client.patch(f"/api/environments/{pid}/members/{uid}",
                     json={"actor_id": admin_id, "role": "manager"})
    assert r.status_code == 404, r.text


def test_its_member_list_is_the_rows_and_offers_the_rest_to_add(client, admin_id):
    """It used to list every account in the system and offer nobody to add —
    which is exactly what the board invite picker inside it inherited."""
    uid = _mk_user(client, admin_id, "primary.listed@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
        total = db.query(User).count()
    got = _members(client, pid, admin_id)
    assert len(got["members"]) < total, "a workspace is its members, not the directory"
    assert uid not in {m["user_id"] for m in got["members"]}
    assert uid in {u["id"] for u in got["available"]}, "and they can be added"


def test_a_board_in_it_offers_only_its_members(client, admin_id):
    """The screen this was all for."""
    uid = _mk_user(client, admin_id, "primary.notoffered@cityos.test")
    bid = client.post("/api/boards",
                      json={"name": "לוח בסביבה הראשית", "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        assert db.query(Board).filter(Board.id == bid).first().environment_id == _primary(db).id
        pid = _primary(db).id
    assert uid not in {u["id"] for u in
                       client.get(f"/api/boards/{bid}/members").json()["available"]}
    client.post(f"/api/environments/{pid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "member"})
    assert uid in {u["id"] for u in
                   client.get(f"/api/boards/{bid}/members").json()["available"]}


def test_another_environment_is_still_by_invitation(client, admin_id):
    uid = _mk_user(client, admin_id, "primary.outsider@cityos.test")
    eid = client.post("/api/environments",
                      json={"actor_id": admin_id, "name": "סביבה מוזמנת"}).json()["id"]
    assert eid not in _env_ids_for(client, uid)
    got = _members(client, eid, admin_id)
    assert uid in {u["id"] for u in got["available"]}


def test_being_in_it_is_not_a_way_into_its_boards(client, admin_id):
    """Unchanged, and still the requirement that makes the rest safe: inside
    the primary workspace a board is seen by its own permissions."""
    uid = _mk_user(client, admin_id, "primary.noboards@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    client.post(f"/api/environments/{pid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "member"})
    bid = client.post("/api/boards", json={"name": "לוח פרטי בראשית", "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        assert db.query(Board).filter(Board.id == bid).first().environment_id == pid
    seen = {b["id"] for b in client.get(f"/api/boards?user_id={uid}").json()}
    assert bid not in seen
    assert client.get(f"/api/boards/{bid}?user_id={uid}").status_code == 403


def test_the_backfill_wrote_a_row_for_everyone_already_on_a_board_in_it(client, admin_id):
    """What made the change safe to run against real data: access that rested
    on the old rule was written down, not withdrawn."""
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
        on_a_board = {uid for (uid,) in
                      db.query(cityos_main.BoardMember.user_id)
                        .join(Board, Board.id == cityos_main.BoardMember.board_id)
                        .filter(Board.environment_id == pid).all()}
        have = {m.user_id for m in db.query(EnvironmentMember).filter(
            EnvironmentMember.environment_id == pid).all()}
    assert on_a_board, "the seed board should be in the primary workspace"
    assert not (on_a_board - have), sorted(on_a_board - have)
