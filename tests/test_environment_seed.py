"""סביבת ברירת המחדל — נשארת אחת גם אחרי שינוי שם.

The primary workspace is an ordinary, renameable environment. The startup
seeder must recognise it by its `is_primary` flag, not by its name — otherwise
renaming it mints a second primary under the old name on the next boot, and
unassigned boards get attached to the wrong one.
"""
import main as cityos_main
from models import Board, Environment
from sqlalchemy.orm import Session


def _primaries(db):
    return db.query(Environment).filter(Environment.is_primary == True).all()


def test_exactly_one_primary_environment(client):
    with Session(cityos_main.engine) as db:
        assert len(_primaries(db)) == 1


def test_renaming_the_primary_does_not_spawn_a_second_one(client, admin_id):
    """Rename the default workspace, re-run the seeder, and it stays alone."""
    with Session(cityos_main.engine) as db:
        primary = _primaries(db)[0]
        pid, original = primary.id, primary.name

    r = client.patch(f"/api/environments/{pid}",
                     json={"actor_id": admin_id, "name": "סביבה ששונתה"})
    assert r.status_code == 200, r.text

    try:
        cityos_main._seed_environments()          # what every server boot does
        with Session(cityos_main.engine) as db:
            prims = _primaries(db)
            assert len(prims) == 1, [p.name for p in prims]
            assert prims[0].id == pid
            assert prims[0].name == "סביבה ששונתה"
            # the old name must not reappear as a new workspace
            assert db.query(Environment).filter(Environment.name == original).count() == 0
    finally:
        client.patch(f"/api/environments/{pid}", json={"actor_id": admin_id, "name": original})


def test_unassigned_boards_land_on_the_renamed_primary(client, admin_id):
    with Session(cityos_main.engine) as db:
        pid = _primaries(db)[0].id
    bid = client.post("/api/boards", json={"name": "לוח יתום", "user_id": admin_id}).json()["id"]
    with Session(cityos_main.engine) as db:
        db.query(Board).filter(Board.id == bid).update({Board.environment_id: None})
        db.commit()

    cityos_main._seed_environments()
    with Session(cityos_main.engine) as db:
        assert db.query(Board).filter(Board.id == bid).first().environment_id == pid


def test_extra_default_workspaces_are_demoted_on_boot(client, admin_id):
    """Residue of the old name-matching seeder: several workspaces flagged
    primary, none of which the admin could rename away from or delete."""
    with Session(cityos_main.engine) as db:
        real = _primaries(db)[0]
        real_id = real.id
        extra1 = Environment(name="עודף א", is_primary=True, position=90)
        extra2 = Environment(name="עודף ב", is_primary=True, position=91)
        db.add_all([extra1, extra2]); db.commit()
        ids = (extra1.id, extra2.id)
        assert len(_primaries(db)) == 3

    cityos_main._seed_environments()          # what every server boot does

    with Session(cityos_main.engine) as db:
        prims = _primaries(db)
        assert len(prims) == 1, [p.name for p in prims]
        assert prims[0].id == real_id          # the one holding the boards is kept
        # the extras survive as ordinary workspaces — deletable, not deleted
        left = db.query(Environment).filter(Environment.id.in_(ids)).all()
        assert len(left) == 2 and not any(e.is_primary for e in left)

    for eid in ids:                            # and the admin can now remove them
        assert client.delete(f"/api/environments/{eid}?actor_id={admin_id}").status_code == 200


def test_the_default_workspace_can_never_be_deleted(client, admin_id):
    with Session(cityos_main.engine) as db:
        pid = _primaries(db)[0].id
    r = client.delete(f"/api/environments/{pid}?actor_id={admin_id}")
    assert r.status_code == 400
    with Session(cityos_main.engine) as db:
        assert db.query(Environment).filter(Environment.id == pid).count() == 1


def test_a_default_workspace_named_after_a_department_is_renamed_back(client, admin_id):
    """The workspace every user is in must read as everybody's.

    It had been renamed to "מערכות מידע" — a department's name — so a new user,
    who gets this workspace and no other, opened the app inside what looked like
    one department. On boot the default workspace answering to that name is
    named back; the department's own workspace is a different row and is left
    exactly as it is.
    """
    with Session(cityos_main.engine) as db:
        primary = _primaries(db)[0]
        pid, original = primary.id, primary.name
        # the real department, which must survive the boot untouched
        dept = Environment(name="חדשנות טכנולוגיה ומערכות מידע", position=95)
        db.add(dept); db.commit()
        dept_id = dept.id

    r = client.patch(f"/api/environments/{pid}",
                     json={"actor_id": admin_id, "name": "מערכות מידע"})
    assert r.status_code == 200, r.text
    try:
        cityos_main._seed_environments()          # what every server boot does
        with Session(cityos_main.engine) as db:
            prims = _primaries(db)
            assert len(prims) == 1, [p.name for p in prims]
            assert prims[0].id == pid
            assert prims[0].name == cityos_main.PRIMARY_ENV_NAME
            # and the department of that name is still itself
            assert db.query(Environment).filter(Environment.id == dept_id).first().name \
                == "חדשנות טכנולוגיה ומערכות מידע"
    finally:
        with Session(cityos_main.engine) as db:
            db.query(Environment).filter(Environment.id == dept_id).delete()
            db.query(Environment).filter(Environment.id == pid).update({Environment.name: original})
            db.commit()


def test_a_name_the_admin_chose_is_still_left_alone(client, admin_id):
    """The rename is a correction of one specific name, not a policy of naming
    the default workspace on every boot."""
    with Session(cityos_main.engine) as db:
        pid, original = (lambda p: (p.id, p.name))(_primaries(db)[0])

    r = client.patch(f"/api/environments/{pid}",
                     json={"actor_id": admin_id, "name": "המטה שלנו"})
    assert r.status_code == 200, r.text
    try:
        cityos_main._seed_environments()
        with Session(cityos_main.engine) as db:
            assert _primaries(db)[0].name == "המטה שלנו"
    finally:
        with Session(cityos_main.engine) as db:
            db.query(Environment).filter(Environment.id == pid).update({Environment.name: original})
            db.commit()


# ── a workspace an admin removed, and one they renamed ──────────────────────
# The seeder used to create the municipality's 17 workspaces BY NAME on every
# boot, so either act was undone by the next restart. Both happened in QA:
# "חדשנות טכנולוגיה ומערכות מידע" was deleted on the 18th and was back on the
# 19th. These are about the 17, not about the primary workspace above.

def test_a_seeded_workspace_that_was_deleted_stays_deleted(client, admin_id):
    """A restart must not reverse an administrative decision. And what came
    back was not even the thing that was deleted: its boards had been moved to
    the default workspace on the way out, and nothing moves them back, so the
    workspace returned empty, wearing the name of something finished with."""
    name = "חדשנות טכנולוגיה ומערכות מידע"
    with Session(cityos_main.engine) as db:
        env = db.query(Environment).filter(Environment.name == name).first()
        assert env is not None, "this test is about one of the seeded workspaces"
        eid = env.id

    assert client.delete(f"/api/environments/{eid}?actor_id={admin_id}").status_code == 200

    cityos_main._seed_environments()          # what every server boot does
    cityos_main._seed_environments()          # and the boot after that
    with Session(cityos_main.engine) as db:
        assert db.query(Environment).filter(Environment.name == name).count() == 0, \
            "a deleted workspace came back on the next boot"


def test_renaming_a_seeded_workspace_does_not_mint_a_second_one(client, admin_id):
    """Renamed, the old name is missing from the table — which is exactly what
    the name-matching seeder read as "create it"."""
    with Session(cityos_main.engine) as db:
        env = db.query(Environment).filter(Environment.name == "שיווק").first()
        assert env is not None
        eid = env.id

    r = client.patch(f"/api/environments/{eid}",
                     json={"actor_id": admin_id, "name": "שיווק ודוברות"})
    assert r.status_code == 200, r.text
    try:
        cityos_main._seed_environments()
        with Session(cityos_main.engine) as db:
            assert db.query(Environment).filter(Environment.name == "שיווק").count() == 0, \
                "the old name came back as a second workspace"
            assert db.query(Environment).filter(Environment.id == eid).first().name \
                == "שיווק ודוברות"
    finally:
        client.patch(f"/api/environments/{eid}", json={"actor_id": admin_id, "name": "שיווק"})


def test_a_new_database_still_starts_with_every_workspace(tmp_path, monkeypatch):
    """The other half of the rule: the list is still what a fresh installation
    is set up with, in its own order, behind the default workspace."""
    from models import Organization, init_db
    eng = init_db("sqlite:///" + str(tmp_path / "fresh.db"))
    with Session(eng) as db:
        db.add(Organization(name="עיריית בדיקה", slug="fresh-test"))
        db.commit()
    monkeypatch.setattr(cityos_main, "engine", eng)
    cityos_main._seed_environments()
    with Session(eng) as db:
        rows = db.query(Environment).order_by(Environment.position, Environment.id).all()
        names = [e.name for e in rows]
        assert names[0] == cityos_main.PRIMARY_ENV_NAME
        assert rows[0].is_primary is True
        assert names[1:] == [n for n, _ in cityos_main.ENVIRONMENTS_SEED]
        # and a second boot of that same database adds nothing
        cityos_main._seed_environments()
        assert db.query(Environment).count() == len(names)
