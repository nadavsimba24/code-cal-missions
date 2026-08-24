"""A board is private unless its admin publishes it.

private — only people invited to the board see it (the behaviour every board
          had before this setting existed, and the default for a new one)
public  — anyone who belongs to the board's environment can see it, read-only
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Board, EnvironmentMember


def _mk_board(client, admin_id, name="לוח חשיפה"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _env_of(bid):
    with Session(cityos_main.engine) as db:
        return db.query(Board).filter(Board.id == bid).first().environment_id


def _join_env(bid, uid):
    """Put a user in the board's environment without inviting them to the board."""
    with Session(cityos_main.engine) as db:
        env_id = db.query(Board).filter(Board.id == bid).first().environment_id
        if not db.query(EnvironmentMember).filter(
                EnvironmentMember.environment_id == env_id,
                EnvironmentMember.user_id == uid).first():
            db.add(EnvironmentMember(environment_id=env_id, user_id=uid, role="member"))
            db.commit()
    return env_id


def _outsider(client, admin_id, email="vis.outsider@cityos.test"):
    for u in client.get("/api/users").json():
        if u.get("email") == email:
            uid = u["id"]
            break
    else:
        uid = client.post("/api/users", json={"actor_id": admin_id, "name": "צופה סביבה",
                                              "email": email, "role": "member"}).json()["id"]
    client.delete(f"/api/boards/1/members/{uid}?actor_id={admin_id}")
    return uid


def _board_ids_for(client, uid):
    return {b["id"] for b in client.get(f"/api/boards?user_id={uid}").json()}


def test_a_new_board_is_private(client, admin_id):
    bid = _mk_board(client, admin_id)
    assert client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["visibility"] == "private"


def test_a_private_board_is_invisible_to_the_rest_of_the_environment(client, admin_id):
    bid = _mk_board(client, admin_id)
    out = _outsider(client, admin_id)
    _join_env(bid, out)
    assert bid not in _board_ids_for(client, out)
    assert client.get(f"/api/boards/{bid}?user_id={out}").status_code == 403


def test_publishing_shows_it_to_the_environment(client, admin_id):
    bid = _mk_board(client, admin_id)
    out = _outsider(client, admin_id, "vis.reader@cityos.test")
    _join_env(bid, out)
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "visibility": "public"})
    assert r.status_code == 200
    assert bid in _board_ids_for(client, out)
    assert client.get(f"/api/boards/{bid}?user_id={out}").status_code == 200


def test_public_is_read_only_without_an_invite(client, admin_id):
    """Seeing a board is not permission to change it."""
    bid = _mk_board(client, admin_id)
    out = _outsider(client, admin_id, "vis.readonly@cityos.test")
    _join_env(bid, out)
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "visibility": "public"})
    assert client.get(f"/api/boards/{bid}?user_id={out}").json()["my_role"] == "viewer"
    r = client.post("/api/tasks", json={"board_id": bid, "title": "לא אמור להיווצר",
                                        "user_id": out})
    assert r.status_code == 403


def test_public_does_not_reach_someone_outside_the_environment(client, admin_id):
    """'Everyone in the environment' is the limit — not everyone in the system."""
    bid = _mk_board(client, admin_id)
    out = _outsider(client, admin_id, "vis.otherenv@cityos.test")
    env_id = _env_of(bid)
    with Session(cityos_main.engine) as db:   # make sure they are NOT in that env
        db.query(EnvironmentMember).filter(EnvironmentMember.environment_id == env_id,
                                           EnvironmentMember.user_id == out).delete()
        db.commit()
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "visibility": "public"})
    assert bid not in _board_ids_for(client, out)


def test_only_a_board_admin_may_publish(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": guinea_id, "visibility": "public"})
    assert r.status_code == 403
    assert client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["visibility"] == "private"


def test_an_unknown_visibility_value_is_refused(client, admin_id):
    bid = _mk_board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "visibility": "everyone"})
    assert r.status_code == 400


def test_a_board_that_predates_the_setting_stays_private(client, admin_id):
    """No board becomes visible to anyone because of the upgrade."""
    bid = _mk_board(client, admin_id)
    with Session(cityos_main.engine) as db:      # strip the key, as old rows have it
        b = db.query(Board).filter(Board.id == bid).first()
        st = dict(b.settings or {}); st.pop("visibility", None); b.settings = st
        db.commit()
    out = _outsider(client, admin_id, "vis.legacy@cityos.test")
    _join_env(bid, out)
    assert client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["visibility"] == "private"
    assert bid not in _board_ids_for(client, out)


def test_unpublishing_takes_it_back(client, admin_id):
    bid = _mk_board(client, admin_id)
    out = _outsider(client, admin_id, "vis.revoked@cityos.test")
    _join_env(bid, out)
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "visibility": "public"})
    assert bid in _board_ids_for(client, out)
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "visibility": "private"})
    assert bid not in _board_ids_for(client, out)
    assert client.get(f"/api/boards/{bid}?user_id={out}").status_code == 403
