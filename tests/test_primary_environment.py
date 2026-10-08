"""הסביבה הראשית — the workspace every user is in.

One environment is flagged primary. It is where the organisation meets: every
user belongs to it without being invited, it is the one the app opens in, and
nobody can be taken out of it.

What it is NOT is a way into boards. Inside it a board is seen exactly as a
board anywhere else is — public to the workspace, or by invitation — which is
the whole reason it can be given to everybody safely.
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


def test_the_default_workspace_is_called_the_primary_one(client):
    with Session(cityos_main.engine) as db:
        assert _primary(db).name == "סביבה ראשית"


def test_a_user_created_today_is_in_it_without_being_invited(client, admin_id):
    """The old seeder granted a row per user, once, on first boot — so everyone
    created afterwards was outside the one workspace everybody shares."""
    uid = _mk_user(client, admin_id, "primary.newcomer@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
        assert not db.query(EnvironmentMember).filter(
            EnvironmentMember.environment_id == pid,
            EnvironmentMember.user_id == uid).first(), "the test is about the case with no row"
    assert pid in _env_ids_for(client, uid)


def test_nobody_can_be_removed_from_it(client, admin_id):
    uid = _mk_user(client, admin_id, "primary.stays@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    r = client.delete(f"/api/environments/{pid}/members/{uid}?actor_id={admin_id}")
    assert r.status_code == 400, r.text
    assert "כל משתמשי המערכת" in r.json()["detail"]
    assert pid in _env_ids_for(client, uid), "and they are still in it"


def test_a_manager_of_it_can_be_appointed_and_stood_down(client, admin_id):
    """A row on this workspace says one thing only: who manages it. Appointing
    someone writes the first row they have had; standing them down removes it
    and leaves them an ordinary member, which is what everyone is."""
    uid = _mk_user(client, admin_id, "primary.manager@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
    r = client.patch(f"/api/environments/{pid}/members/{uid}",
                     json={"actor_id": admin_id, "role": "manager"})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/environments/{pid}/members?actor_id={admin_id}").json()
    assert [m for m in got["members"] if m["user_id"] == uid][0]["role"] == "manager"

    r = client.delete(f"/api/environments/{pid}/members/{uid}?actor_id={admin_id}")
    assert r.status_code == 200 and r.json()["status"] == "demoted", r.text
    assert pid in _env_ids_for(client, uid)
    got = client.get(f"/api/environments/{pid}/members?actor_id={admin_id}").json()
    assert [m for m in got["members"] if m["user_id"] == uid][0]["role"] == "member"


def test_its_member_list_is_everyone_and_offers_nobody_to_add(client, admin_id):
    uid = _mk_user(client, admin_id, "primary.listed@cityos.test")
    with Session(cityos_main.engine) as db:
        pid = _primary(db).id
        total = db.query(User).count()
    got = client.get(f"/api/environments/{pid}/members?actor_id={admin_id}").json()
    assert got["everyone"] is True
    assert len(got["members"]) == total, [m["name"] for m in got["members"]]
    assert uid in {m["user_id"] for m in got["members"]}
    assert got["available"] == [], "there is nobody left to add to a workspace everyone is in"


def test_another_environment_is_still_by_invitation(client, admin_id):
    uid = _mk_user(client, admin_id, "primary.outsider@cityos.test")
    eid = client.post("/api/environments",
                      json={"actor_id": admin_id, "name": "סביבה מוזמנת"}).json()["id"]
    assert eid not in _env_ids_for(client, uid)
    got = client.get(f"/api/environments/{eid}/members?actor_id={admin_id}").json()
    assert got["everyone"] is False
    assert uid in {u["id"] for u in got["available"]}


def test_being_in_it_is_not_a_way_into_its_boards(client, admin_id):
    """The requirement that makes the rest of it safe: inside the primary
    workspace a board is still seen by its own permissions."""
    uid = _mk_user(client, admin_id, "primary.noboards@cityos.test")
    bid = client.post("/api/boards", json={"name": "לוח פרטי בראשית", "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        assert db.query(Board).filter(Board.id == bid).first().environment_id == _primary(db).id
    seen = {b["id"] for b in client.get(f"/api/boards?user_id={uid}").json()}
    assert bid not in seen
    assert client.get(f"/api/boards/{bid}?user_id={uid}").status_code == 403
