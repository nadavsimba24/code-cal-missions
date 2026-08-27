"""The tags column type was removed from the product, data included.

It used to be a built-in column on every board, a field type in the form
builder, something the AI tools could read and write, and a JSON column on
tasks. This pins every one of those doors shut — a removal is only done if
nothing quietly keeps writing to what was removed.
"""
import pathlib

import pytest
from sqlalchemy import inspect, text

import main as cityos_main
from models import Task

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


# ── the data ────────────────────────────────────────────────────────────
def test_the_column_is_gone_from_the_database():
    cols = {c["name"] for c in inspect(cityos_main.engine).get_columns("tasks")}
    assert "tags" not in cols, "the tags column still exists on tasks, values and all"


def test_the_model_no_longer_has_the_field():
    assert not hasattr(Task, "tags"), "Task.tags is still mapped"


def test_projects_keep_their_own_tags():
    """A different feature on a different table that was never in scope."""
    cols = {c["name"] for c in inspect(cityos_main.engine).get_columns("projects")}
    assert "tags" in cols, "the projects table lost its tags, which were not part of this"


# ── the API ─────────────────────────────────────────────────────────────
def test_creating_an_item_with_tags_does_not_store_them(client, admin_id):
    bid = client.post("/api/boards", json={"name": "ללא תגיות", "user_id": admin_id}).json()["id"]
    r = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                        "user_id": admin_id, "tags": ["א", "ב"]})
    assert r.status_code == 200, r.text
    assert "tags" not in r.json(), "the API still echoes tags back"


def test_patching_tags_is_ignored(client, admin_id):
    bid = client.post("/api/boards", json={"name": "עדכון", "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    r = client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"tags": ["חדש"]})
    assert r.status_code == 200, r.text
    assert "tags" not in client.get(f"/api/tasks/{tid}").json()


def test_it_cannot_be_hidden_or_renamed_because_it_is_not_a_column(client, admin_id):
    bid = client.post("/api/boards", json={"name": "עמודות", "user_id": admin_id}).json()["id"]
    client.patch(f"/api/boards/{bid}", json={"col_hidden": ["tags"], "user_id": admin_id})
    client.patch(f"/api/boards/{bid}", json={"col_labels": {"tags": "שם אחר"}, "user_id": admin_id})
    board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    assert "tags" not in (board.get("col_hidden") or [])
    assert "tags" not in (board.get("col_labels") or {})


def test_boards_configured_before_the_removal_stop_naming_it(client, admin_id):
    """col_order is a free-form list — it carries custom column ids too, so it
    cannot be validated against a fixed set and a stale key just sits there.
    The startup migration is what clears it out of boards that already had it."""
    from sqlalchemy.orm import Session as _S
    from models import Board

    bid = client.post("/api/boards", json={"name": "לוח ותיק", "user_id": admin_id}).json()["id"]
    with _S(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        b.settings = {**(b.settings or {}), "col_order": ["item", "tags", "status"],
                      "col_hidden": ["tags"], "col_widths": {"tags": 170, "status": 130}}
        db.commit()

    cityos_main._forget_tags_in_board_settings()

    with _S(cityos_main.engine) as db:
        st = db.query(Board).filter(Board.id == bid).first().settings
    assert st["col_order"] == ["item", "status"], "the column order still names tags"
    assert st["col_hidden"] == []
    assert st["col_widths"] == {"status": 130}, "a width is still stored for tags"

    # and running it again changes nothing
    cityos_main._forget_tags_in_board_settings()
    with _S(cityos_main.engine) as db:
        assert db.query(Board).filter(Board.id == bid).first().settings == st


def test_the_board_payload_carries_no_tags(client, admin_id):
    bid = client.post("/api/boards", json={"name": "מטען", "user_id": admin_id}).json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    for t in board.get("tasks", []):
        assert "tags" not in t, "board items still carry a tags key"


# ── the surfaces that fed it ────────────────────────────────────────────
@pytest.mark.parametrize("marker,what", [
    ("tagsEditor", "the tag chip editor"),
    ("boardTags(", "the board tag vocabulary"),
    ("{key:'tags'", "the tags entry in the column list / form builder"),
    ("f.type==='tags'", "the tags field type in form rendering"),
])
def test_the_frontend_surface_is_gone(marker, what):
    assert marker not in INDEX, f"{what} is still in the frontend"


def test_the_ai_tools_cannot_set_tags():
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    tools = src[src.index("def _ai_tools") if "def _ai_tools" in src else 0:]
    assert '"tags": {"type": "array"' not in src, \
        "an AI tool still advertises a tags argument"
    assert 't.tags = args["tags"]' not in src, "an AI tool still writes tags"
