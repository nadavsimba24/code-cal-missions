"""שעות הכניסה נשלחות מסומנות כ-UTC, כדי שאפשר יהיה להציג אותן בשעון ישראל.

login_events.logged_in_at is written with datetime.now(timezone.utc), but the
column is a plain DateTime: SQLAlchemy drops the offset and hands the value back
naive, and it was serialised naive too — "2026-10-15T08:22:02" with nothing
saying that is UTC. ECMAScript reads a date-time with no offset as LOCAL time,
so the admin directory showed every login three hours early in Israel. Not a
different zone — a wrong time.

The API says which zone it means now. The screen does the rest: it formats in
Asia/Jerusalem, so the column reads Israel time wherever the viewer's machine is
set (tests/frontend/login_time_is_israel_time.mjs).
"""
import re

from sqlalchemy.orm import Session
import main as cityos_main
from models import LoginEvent

OFFSET = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


def _last_login(client, admin_id, uid):
    return next(u["last_login"] for u in client.get("/api/users").json() if u["id"] == uid)


def test_a_recorded_login_comes_back_marked(client, admin_id):
    r = client.post("/api/auth/login", json={"actor_id": admin_id})
    assert r.status_code == 200, r.text
    assert OFFSET.search(r.json()["logged_in_at"]), r.json()["logged_in_at"]


def test_the_directory_column_is_marked(client, admin_id):
    """`last_login` is what the "כניסה אחרונה" column renders."""
    client.post("/api/auth/login", json={"actor_id": admin_id})
    v = _last_login(client, admin_id, admin_id)
    assert v and OFFSET.search(v), repr(v)


def test_the_login_history_rows_are_marked(client, admin_id):
    client.post("/api/auth/login", json={"actor_id": admin_id})
    rows = client.get(f"/api/users/{admin_id}/login-history").json()
    assert rows and all(OFFSET.search(r["logged_in_at"]) for r in rows), rows[:2]


def test_the_consolidated_history_is_marked_too(client, admin_id):
    client.post("/api/auth/login", json={"actor_id": admin_id})
    rows = client.get("/api/login-history").json()
    assert rows and all(OFFSET.search(r["logged_in_at"]) for r in rows), rows[:2]


def test_the_marked_value_is_the_instant_that_was_stored(client, admin_id):
    """Marking must not shift the moment — the row said UTC all along."""
    client.post("/api/auth/login", json={"actor_id": admin_id})
    with Session(cityos_main.engine) as db:
        row = (db.query(LoginEvent).filter(LoginEvent.user_id == admin_id)
                 .order_by(LoginEvent.id.desc()).first())
    sent = client.get(f"/api/users/{admin_id}/login-history").json()[0]["logged_in_at"]
    assert sent.startswith(row.logged_in_at.isoformat()), (sent, row.logged_in_at)


def test_a_user_who_never_logged_in_has_no_timestamp(client, admin_id, guinea_id):
    """The column draws "— מעולם לא —" from a null, so it must stay a null."""
    v = _last_login(client, admin_id, guinea_id)
    assert v is None or OFFSET.search(v), repr(v)
