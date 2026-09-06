"""Whoever may open ניהול מערכת → סביבות may act in it.

Reported as "QA has the option to delete an environment and production does
not", with identical code deployed to both. It was one permission row: two
different tests answered "is this person a system admin". The screen opens on
the `manage_system` capability; the actions inside it asked instead for a
WorkspaceMember row with role=admin. Someone holding one and not the other was
shown the list of every environment with every action on it hidden — which is
what production looked like beside QA, where the same person also holds the row.

These use a plain member granted `manage_system` through the role matrix and
nothing else: exactly the account the report came from.
"""
import pytest

from conftest import ADMIN_ID, MEMBER_ID


@pytest.fixture
def sys_manager(client):
    """Grant 'member' the manage_system capability, then put it back."""
    before = client.get("/api/role-permissions").json()
    was = bool(((before.get("matrix") or {}).get("member") or {}).get("manage_system"))
    client.put("/api/role-permissions",
               json={"actor_id": ADMIN_ID, "role": "member",
                     "capability": "manage_system", "allowed": True})
    yield MEMBER_ID
    client.put("/api/role-permissions",
               json={"actor_id": ADMIN_ID, "role": "member",
                     "capability": "manage_system", "allowed": was})


@pytest.fixture
def env(client):
    e = client.post("/api/environments", json={"actor_id": ADMIN_ID, "name": "סביבה למחיקה"}).json()
    yield e
    client.delete(f"/api/environments/{e['id']}?actor_id={ADMIN_ID}")


def test_they_can_delete_an_environment(client, sys_manager):
    """The report itself."""
    uid = sys_manager
    e = client.post("/api/environments", json={"actor_id": ADMIN_ID, "name": "נמחקת"}).json()
    r = client.delete(f"/api/environments/{e['id']}?actor_id={uid}")
    assert r.status_code == 200, r.text
    ids = {x["id"] for x in client.get(f"/api/environments?user_id={ADMIN_ID}").json()["environments"]}
    assert e["id"] not in ids


def test_they_see_every_environment_the_screen_lists(client, sys_manager, env):
    """A management screen showing a filtered list is not a management screen."""
    ids = {x["id"] for x in client.get(f"/api/environments?user_id={sys_manager}").json()["environments"]}
    assert env["id"] in ids


def test_they_may_hand_out_the_manager_role(client, sys_manager, env):
    d = client.get(f"/api/environments/{env['id']}/members?actor_id={sys_manager}")
    assert d.status_code == 200, d.text
    assert d.json()["can_set_manager"] is True

    client.post(f"/api/environments/{env['id']}/members",
                json={"actor_id": sys_manager, "user_id": ADMIN_ID, "role": "member"})
    r = client.patch(f"/api/environments/{env['id']}/members/{ADMIN_ID}",
                     json={"actor_id": sys_manager, "role": "manager"})
    assert r.status_code == 200, r.text


def test_without_the_capability_none_of_it_opens(client, env):
    """The capability is the gate — not a formality that everyone passes."""
    r = client.delete(f"/api/environments/{env['id']}?actor_id={MEMBER_ID}")
    assert r.status_code == 403, r.text
    assert env["id"] in {x["id"] for x in
                         client.get(f"/api/environments?user_id={ADMIN_ID}").json()["environments"]}


def test_a_workspace_admin_keeps_everything_they_had(client, env):
    """The rule was widened, never narrowed: nobody loses what they could do."""
    d = client.get(f"/api/environments/{env['id']}/members?actor_id={ADMIN_ID}")
    assert d.status_code == 200 and d.json()["can_set_manager"] is True
    assert env["id"] in {x["id"] for x in
                         client.get(f"/api/environments?user_id={ADMIN_ID}").json()["environments"]}


def test_the_primary_environment_is_still_undeletable(client, sys_manager):
    """Widening who may delete must not widen what may be deleted."""
    envs = client.get(f"/api/environments?user_id={ADMIN_ID}").json()["environments"]
    primary = next((e for e in envs if e["is_primary"]), None)
    if primary is None:
        pytest.skip("no primary environment in this database")
    r = client.delete(f"/api/environments/{primary['id']}?actor_id={sys_manager}")
    assert r.status_code == 400, r.text
    assert primary["id"] in {x["id"] for x in
                             client.get(f"/api/environments?user_id={ADMIN_ID}").json()["environments"]}
