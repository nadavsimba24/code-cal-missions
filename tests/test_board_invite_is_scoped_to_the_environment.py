"""מזמינים ללוח רק מי שכבר בסביבה.

A board lives in an environment, and the environment is who was let into this
part of the product at all. The board's invite picker offered every active
account in the system — so a board inside "אגף ההנדסה" listed people who had
never been given that environment, and inviting one of them handed out access
nobody upstream had granted.

The rule is not the board's own: _env_role already knows what belonging to an
environment means, including the case that is not a row in the table — a system
admin belongs to every environment.

The primary workspace was a second such case, and it swallowed the rule whole:
everybody was a member of it without a row, so on the workspace almost every
board lives in, the picker went on offering the entire directory. It is an
ordinary workspace now (see test_primary_environment.py) and this scopes its
boards like any other.

And the picker is not the rule. The POST is held to the same line, because an
invitation is a grant of access whatever screen it was made from.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Board, Environment, EnvironmentMember, User


def _env(db, name="אגף ההנדסה"):
    e = Environment(name=name, organization_id=None)
    db.add(e); db.flush()
    return e.id


def _setup(client, admin_id, guinea_id, put_guinea_in_env):
    """A board in an environment of its own, and guinea either in it or not."""
    with Session(cityos_main.engine) as db:
        env_id = _env(db)
        db.add(EnvironmentMember(environment_id=env_id, user_id=admin_id,
                                 role="manager"))
        if put_guinea_in_env:
            db.add(EnvironmentMember(environment_id=env_id, user_id=guinea_id,
                                     role="member"))
        db.commit()
    bid = client.post("/api/boards",
                      json={"name": "לוח סביבה", "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        b.environment_id = env_id
        db.commit()
    return bid, env_id


def _available(client, bid):
    return {u["id"] for u in client.get(f"/api/boards/{bid}/members").json()["available"]}


def test_somebody_outside_the_environment_is_not_offered(client, admin_id, guinea_id):
    bid, _ = _setup(client, admin_id, guinea_id, put_guinea_in_env=False)
    assert guinea_id not in _available(client, bid)


def test_and_somebody_inside_it_is(client, admin_id, guinea_id):
    bid, _ = _setup(client, admin_id, guinea_id, put_guinea_in_env=True)
    assert guinea_id in _available(client, bid)


def test_the_invitation_itself_is_refused_not_just_hidden(client, admin_id, guinea_id):
    """The picker is not the rule — the same line the deactivated check draws
    one statement above it."""
    bid, _ = _setup(client, admin_id, guinea_id, put_guinea_in_env=False)
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert r.status_code == 400, r.text
    assert "סביבה" in r.json()["detail"], r.json()
    # and nothing was written
    assert client.get(f"/api/boards/{bid}/members").json()["members"] \
        == [m for m in client.get(f"/api/boards/{bid}/members").json()["members"]
            if m["user_id"] != guinea_id]


def test_adding_them_to_the_environment_makes_the_invitation_work(
        client, admin_id, guinea_id):
    bid, env_id = _setup(client, admin_id, guinea_id, put_guinea_in_env=False)
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": guinea_id,
                             "role": "editor"}).status_code == 400
    with Session(cityos_main.engine) as db:
        db.add(EnvironmentMember(environment_id=env_id, user_id=guinea_id,
                                 role="member"))
        db.commit()
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert r.status_code == 200, r.text
    assert guinea_id in {m["user_id"] for m in
                         client.get(f"/api/boards/{bid}/members").json()["members"]}


# ── the workspace this rule used to leave alone ────────────────────────────

def test_the_primary_environment_is_narrowed_too(client, admin_id, guinea_id):
    """The boards most people work on are in the primary workspace, and it is
    where this rule was doing nothing at all: everybody was a member of it
    without a row. Its boards offer its members, like anywhere else."""
    bid = client.post("/api/boards",
                      json={"name": "לוח ראשי", "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        pid = cityos_main._primary_env_id(db)
        b = db.query(Board).filter(Board.id == bid).first()
        assert b.environment_id == pid, b.environment_id
    # guinea is in it (tests/conftest.py enrolls them, as an admin would)
    assert guinea_id in _available(client, bid)
    stranger = client.post("/api/users",
                           json={"actor_id": admin_id, "name": "לא בסביבה הראשית",
                                 "email": "scope.primary.stranger@cityos.test",
                                 "role": "member"}).json()["id"]
    assert stranger not in _available(client, bid)
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": stranger, "role": "editor"})
    assert r.status_code == 400, r.text


# ── and the one case that is still not a row in the table ─────────────────

def test_a_board_with_no_environment_is_not_scoped(client, admin_id, guinea_id):
    """Refusing every invitation because a legacy board has no environment
    would be inventing a rule out of a missing column."""
    bid = client.post("/api/boards",
                      json={"name": "לוח ישן", "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        b.environment_id = None
        db.commit()
    assert guinea_id in _available(client, bid)


def test_a_deactivated_account_is_still_never_offered(client, admin_id, guinea_id):
    """The older rule still stands beside the new one."""
    bid, _ = _setup(client, admin_id, guinea_id, put_guinea_in_env=True)
    with Session(cityos_main.engine) as db:
        db.query(User).filter(User.id == guinea_id).first().is_active = False
        db.commit()
    try:
        assert guinea_id not in _available(client, bid)
    finally:
        with Session(cityos_main.engine) as db:
            db.query(User).filter(User.id == guinea_id).first().is_active = True
            db.commit()


def test_a_member_already_on_the_board_is_left_alone(client, admin_id, guinea_id):
    """Scoping decides who may be ADDED. Somebody already on the board stays
    listed whatever the environment says now — otherwise nobody could see them
    to take them off."""
    bid, env_id = _setup(client, admin_id, guinea_id, put_guinea_in_env=True)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    with Session(cityos_main.engine) as db:
        db.query(EnvironmentMember).filter(
            EnvironmentMember.environment_id == env_id,
            EnvironmentMember.user_id == guinea_id).delete()
        db.commit()
    members = client.get(f"/api/boards/{bid}/members").json()["members"]
    assert guinea_id in {m["user_id"] for m in members}
