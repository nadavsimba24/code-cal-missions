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
