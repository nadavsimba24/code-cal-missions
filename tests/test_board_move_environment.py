"""העברת לוח לסביבה אחרת — POST /api/boards/{id}/environment.

Moving a board between workspaces requires managing BOTH ends: you may not
push a board into a workspace you do not run, nor pull one out of a workspace
you do not run. The board keeps everything except its folder, which belonged
to the environment it left.
"""
import main as cityos_main
from models import Board, Environment, EnvironmentMember, Folder
from sqlalchemy.orm import Session


def _env(name):
    with Session(cityos_main.engine) as db:
        e = Environment(name=name, icon="🏢", color="#6366f1", position=99)
        db.add(e); db.commit(); db.refresh(e)
        return e.id


def _board_env(bid):
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        return b.environment_id, b.folder_id


def _make_board(client, admin_id, name="לוח להעברה"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _move(client, bid, env_id, actor):
    return client.post(f"/api/boards/{bid}/environment",
                       json={"actor_id": actor, "environment_id": env_id})


def test_system_admin_moves_a_board_between_environments(client, admin_id):
    bid = _make_board(client, admin_id)
    target = _env("סביבת יעד")
    r = _move(client, bid, target, admin_id)
    assert r.status_code == 200, r.text
    assert r.json()["environment_id"] == target
    assert _board_env(bid)[0] == target


def test_the_board_leaves_its_folder(client, admin_id):
    """Folders belong to the old environment, so the board detaches from it."""
    bid = _make_board(client, admin_id)
    src = _board_env(bid)[0]
    with Session(cityos_main.engine) as db:
        f = Folder(environment_id=src, name="תיקייה", position=0)
        db.add(f); db.commit()
        db.query(Board).filter(Board.id == bid).update({Board.folder_id: f.id})
        db.commit()
    assert _board_env(bid)[1] is not None
    assert _move(client, bid, _env("יעד עם תיקייה"), admin_id).status_code == 200
    assert _board_env(bid)[1] is None


def test_items_and_members_survive_the_move(client, admin_id):
    bid = _make_board(client, admin_id)
    before = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    _move(client, bid, _env("יעד שומר תוכן"), admin_id)
    after = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    assert [t["id"] for t in after["tasks"]] == [t["id"] for t in before["tasks"]]
    assert after["my_role"] == "admin"
    assert after["columns"] == before["columns"]


def test_non_manager_cannot_move_a_board(client, admin_id, guinea_id):
    bid = _make_board(client, admin_id)
    target = _env("סביבה שאינה שלי")
    r = _move(client, bid, target, guinea_id)
    assert r.status_code == 403
    assert _board_env(bid)[0] != target


def test_env_manager_needs_to_manage_the_source_too(client, admin_id, guinea_id):
    """Managing only the target is not enough to pull a board out of a workspace."""
    bid = _make_board(client, admin_id)
    target = _env("סביבה שאני מנהל")
    with Session(cityos_main.engine) as db:      # make guinea a manager of the TARGET only
        db.add(EnvironmentMember(environment_id=target, user_id=guinea_id, role="manager"))
        db.commit()
    r = _move(client, bid, target, guinea_id)
    assert r.status_code == 403
    assert "הנוכחית" in r.json()["detail"]
    assert _board_env(bid)[0] != target


def test_moving_to_the_same_environment_is_rejected(client, admin_id):
    bid = _make_board(client, admin_id)
    same = _board_env(bid)[0]
    r = _move(client, bid, same, admin_id)
    assert r.status_code == 400


def test_unknown_board_or_environment(client, admin_id):
    bid = _make_board(client, admin_id)
    assert _move(client, 999999, _board_env(bid)[0], admin_id).status_code == 404
    assert _move(client, bid, 999999, admin_id).status_code == 404
