"""Group — the local login screen can still find the users.

Dev mode's picker has to list the users while nobody is signed in, and the way
it did that was to sign in as user 1, then 2, then 3, and try reading /api/users
as each. Those are the ids the demo seed happens to create. On a database whose
demo users have been removed — which is what a local database looks like after a
few months, and what hers looks like now (ids 8, 9, 10) — all three are refused,
the list comes back empty, and the login screen offers "אין משתמשים" with no way
past it. The server was fine; there was no way to tell it who you were.
"""
import pathlib

import pytest
from sqlalchemy.orm import Session

import auth as cityos_auth
import main as cityos_main
from models import User

SRC = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_picker_can_read_the_directory_with_no_identity(client):
    r = client.get("/api/auth/dev-users", headers={"X-CityOS-User": ""})
    assert r.status_code == 200, r.text
    assert r.json(), "the picker has nobody to offer"
    assert {"id", "name", "role"} <= set(r.json()[0])


def test_it_does_not_depend_on_the_seeded_ids(client, admin_id):
    """The whole failure: a database whose users start at 8."""
    with Session(cityos_main.engine) as db:
        ids = {u.id for u in db.query(User).filter(User.is_active.isnot(False))}
    got = {u["id"] for u in client.get("/api/auth/dev-users").json()}
    assert got == ids, "the picker offers a different set than the database holds"
    assert 1 not in got or 1 in ids


def test_an_inactive_account_is_not_offered(client, admin_id):
    """The automation engine's identity is a user row and is not a person."""
    with Session(cityos_main.engine) as db:
        u = User(email="gone@example.com", name="מושבת", role="member", is_active=False)
        db.add(u)
        db.commit()
        uid = u.id
    try:
        assert uid not in {x["id"] for x in client.get("/api/auth/dev-users").json()}
    finally:
        with Session(cityos_main.engine) as db:
            db.delete(db.query(User).filter(User.id == uid).first())
            db.commit()


def test_outside_dev_mode_the_route_does_not_exist(client, monkeypatch):
    """Not 403 — 404. In production the picker is not a thing that is refused,
    it is a thing that is not there."""
    monkeypatch.setattr(cityos_main, "auth_mode", lambda: "entra")
    assert client.get("/api/auth/dev-users").status_code == 404
    monkeypatch.setattr(cityos_main, "auth_mode", lambda: "easyauth")
    assert client.get("/api/auth/dev-users").status_code == 404


def test_the_picker_asks_for_that_directory_and_not_for_user_1(client):
    assert "/api/auth/dev-users" in SRC
    assert "for(const probe of [1,2,3])" not in SRC, "the hardcoded probe is back"


def test_reaching_the_picker_clears_the_identity_it_could_not_use(client):
    """A cookie naming a user who is no longer in the database 403s every plain
    browser request — an <img src>, a download — for as long as it is there."""
    block = SRC[SRC.index("async loadPickerUsers()"):]
    block = block[:block.index("showLogin()")]
    assert "setDevUser(null)" in block


def test_an_empty_picker_says_what_is_wrong(client):
    """"אין משתמשים" under a working server sent two people looking for a bug in
    the database."""
    for marker in ("לא ניתן לקרוא את רשימת המשתמשים",
                   "אין משתמשים פעילים במסד הנתונים",
                   "למחוק את cityos.db"):
        assert marker in SRC, f"the empty login screen does not say {marker}"


def test_a_stale_identity_is_refused_rather_than_guessed(client):
    """The other half of the bug is not a bug: a cookie naming a user who is not
    in the database gets 403, and must not fall back to somebody."""
    r = client.get("/api/users", headers={"X-CityOS-User": "999999"})
    assert r.status_code == 403


def test_the_public_route_list_is_exactly_those_two(client):
    """Every path on it is reachable with no identity at all, so the list is the
    app's entire unauthenticated surface."""
    assert cityos_main.PUBLIC_API_PATHS == {"/api/status", "/api/auth/dev-users"}


def test_nothing_else_answers_without_an_identity(client):
    """The directory being public must not have made anything else public."""
    for path in ("/api/users", "/api/boards", "/api/dashboard", "/api/auth/me"):
        r = client.get(path, headers={"X-CityOS-User": ""})
        assert r.status_code in (401, 403), f"{path} answered {r.status_code}"
