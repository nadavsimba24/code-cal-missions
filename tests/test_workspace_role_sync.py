"""Being made a מנהל מערכת in the users screen actually makes you one.

Two rows carry "is this person an admin": `User.role`, which the users screen
edits, and `WorkspaceMember.role`, which most of the system actually reads.
Creating an account wrote both. Changing a role afterwards wrote only the first
— so someone promoted through the screen was let into ניהול מערכת (`_cap`
accepts `User.role == "admin"`) and refused everything offered there (which
reads the workspace row).

That is the whole of "QA has features production does not": in QA the account
was created as an admin and both rows agree; in production it was promoted
later and they never did.
"""
import itertools

import pytest

from conftest import ADMIN_ID


_seq = itertools.count(1)


@pytest.fixture
def promotable(client):
    """A plain member of our own — a fresh one per test, since an email is unique
    and these tests move the same person's role around."""
    n = next(_seq)
    r = client.post("/api/users", json={"actor_id": ADMIN_ID, "name": f"בודק תפקידים {n}",
                                        "email": f"role.sync{n}@cityos.test", "role": "member"})
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    yield uid
    client.patch(f"/api/users/{uid}", json={"actor_id": ADMIN_ID, "role": "member", "is_active": False})


def _ws_role(uid):
    import main as cityos_main
    from models import WorkspaceMember
    from sqlalchemy.orm import Session
    with Session(cityos_main.engine) as db:
        m = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid).first()
        return m.role if m else None


def test_a_new_account_gets_both_rows(client, promotable):
    assert _ws_role(promotable) == "member"


def test_promoting_to_admin_grants_the_row_the_system_reads(client, promotable):
    """The report, in one line."""
    r = client.patch(f"/api/users/{promotable}", json={"actor_id": ADMIN_ID, "role": "admin"})
    assert r.status_code == 200, r.text
    assert _ws_role(promotable) == "admin"


def test_and_the_promotion_actually_works(client, promotable):
    """Not just the row: the thing the row was blocking."""
    client.patch(f"/api/users/{promotable}", json={"actor_id": ADMIN_ID, "role": "admin"})
    e = client.post("/api/environments", json={"actor_id": ADMIN_ID, "name": "סביבה לבדיקת קידום"}).json()
    r = client.delete(f"/api/environments/{e['id']}?actor_id={promotable}")
    assert r.status_code == 200, r.text


def test_demoting_takes_the_row_back(client, promotable):
    """A demotion that leaves the workspace row behind is not a demotion."""
    client.patch(f"/api/users/{promotable}", json={"actor_id": ADMIN_ID, "role": "admin"})
    r = client.patch(f"/api/users/{promotable}", json={"actor_id": ADMIN_ID, "role": "member"})
    assert r.status_code == 200, r.text
    assert _ws_role(promotable) == "member"
    e = client.post("/api/environments", json={"actor_id": ADMIN_ID, "name": "אחרי הורדה"}).json()
    try:
        assert client.delete(f"/api/environments/{e['id']}?actor_id={promotable}").status_code == 403
    finally:
        client.delete(f"/api/environments/{e['id']}?actor_id={ADMIN_ID}")


def test_a_viewer_is_mapped_to_a_viewer(client, promotable):
    client.patch(f"/api/users/{promotable}", json={"actor_id": ADMIN_ID, "role": "viewer"})
    assert _ws_role(promotable) == "viewer"


def test_a_manager_is_not_a_workspace_admin(client, promotable):
    """The seeder's own rule: a manager gets granted environments, not the system."""
    client.patch(f"/api/users/{promotable}", json={"actor_id": ADMIN_ID, "role": "manager"})
    assert _ws_role(promotable) == "member"


def test_the_repair_restores_a_promotion_written_before_the_fix(client, promotable):
    """Exactly the production state: User.role says admin, the row does not."""
    import main as cityos_main
    from models import User, WorkspaceMember
    from sqlalchemy.orm import Session

    with Session(cityos_main.engine) as db:            # reproduce the old bug by hand
        db.query(User).filter(User.id == promotable).first().role = "admin"
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id == promotable).first().role = "member"
        db.commit()
    assert _ws_role(promotable) == "member"

    cityos_main._repair_promoted_admins()
    assert _ws_role(promotable) == "admin"


def test_the_repair_never_takes_a_row_away(client, promotable):
    """It grants what an administrator already decided; it does not re-decide."""
    import main as cityos_main
    from models import User, WorkspaceMember
    from sqlalchemy.orm import Session

    with Session(cityos_main.engine) as db:
        db.query(User).filter(User.id == promotable).first().role = "member"
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id == promotable).first().role = "admin"
        db.commit()

    cityos_main._repair_promoted_admins()
    assert _ws_role(promotable) == "admin"             # untouched
