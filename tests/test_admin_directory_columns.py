"""The two columns the system-admin directory grew, and what they must mean.

Two fields were added to feed the ניהול מערכת screen, and each of them has a
way of being quietly wrong:

* `created_at` on /api/users — "מועד הזמנה למערכת". It is a naive DateTime
  holding UTC, and ECMAScript reads a date-time with NO offset as LOCAL time.
  That exact bug already shipped here once, on `last_login`: every login
  displayed three hours early in Israel — not a different zone, a wrong time.
  So the column is pinned to carry an explicit offset, not merely to exist.

* `active_user_count` on /api/departments — how many of a unit's people actually
  signed in during the last 30 days. `user_count` answers a different question
  ("how many were assigned here") and stays true long after a unit stops being
  used, so neither figure may replace the other. The counting is one grouped
  join over login_events, and the two things easiest to get wrong in that are
  the boundary and the DISTINCT: somebody who signs in daily is one active user,
  not thirty.

Every test here builds its own unit and its own people and removes them in a
`finally`. conftest points the DB at a temp file, but a suite that is run over
and over against the same seeded temp DB only stays meaningful if each test puts
things back.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import main as cityos_main
from models import LoginEvent

# SQLite drops the offset when it writes a plain DateTime, so what the table
# holds is a UTC wall clock — which is exactly what the route's cutoff compares
# against. A test that wrote aware values would be comparing two different
# things, the same way the route would if its cutoff were aware.
NOW = datetime.now(timezone.utc).replace(tzinfo=None)

OFFSET = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def _users(client):
    return client.get("/api/users").json()


def _dept(client, admin_id):
    """A unit of our own, so no seeded row's history can colour the counts."""
    r = client.post("/api/departments",
                    json={"actor_id": admin_id, "name": f"יחידת מדידה {uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    return r.json()


def _member(client, admin_id, dept_id):
    r = client.post("/api/users", json={"actor_id": admin_id, "name": "נבדק פעילות",
                                       "email": f"act_{uuid.uuid4().hex[:8]}@example.com",
                                       "role": "member", "department_id": dept_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _row(client, did):
    return next(d for d in client.get("/api/departments").json() if d["id"] == did)


def _log_in_at(uid, when):
    """Write a login at a chosen instant — the API can only record 'now'."""
    with Session(cityos_main.engine) as db:
        db.add(LoginEvent(user_id=uid, logged_in_at=when, ip="127.0.0.1", user_agent="pytest"))
        db.commit()


def _forget(client, admin_id, uids):
    """Put the directory back.

    Through DELETE /api/users, not through the table: creating a user also
    enrolls them in the workspace, and tearing only the users row out left a
    workspace_members row behind — SQLite then handed the next test the same id
    and the insert failed on a unique constraint.
    """
    for uid in uids:
        with Session(cityos_main.engine) as db:
            db.query(LoginEvent).filter(LoginEvent.user_id == uid).delete()
            db.commit()
        r = client.delete(f"/api/users/{uid}?actor_id={admin_id}")
        assert r.status_code == 200, r.text


# ── created_at ───────────────────────────────────────────────────────

def test_every_user_carries_the_date_their_account_was_opened(client):
    """The directory's "מועד הזמנה למערכת" column has something to show."""
    users = _users(client)
    assert users, "expected a seeded directory"
    missing = [u["id"] for u in users if not u.get("created_at")]
    assert "created_at" in users[0], "user row has no created_at at all"
    assert not missing, f"accounts with no creation date: {missing}"


def test_the_creation_date_says_which_zone_it_is_in(client):
    """A naive timestamp is read by the browser as LOCAL time, and that shipped.

    `last_login` was serialised as "2026-10-15T08:22:02" with nothing to say it
    was UTC, so every login read three hours early in Israel. created_at goes
    through the same serialiser for the same reason, and this is the assertion
    that keeps it there: an offset, explicitly, on every row.
    """
    for u in _users(client):
        assert OFFSET.search(u["created_at"]), \
            f"user {u['id']} created_at has no UTC offset: {u['created_at']!r}"
    # and it is parseable as the aware instant it claims to be
    sample = _users(client)[0]["created_at"]
    assert datetime.fromisoformat(sample).tzinfo is not None, sample


def test_the_creation_date_is_shaped_exactly_like_the_last_login(client, admin_id):
    """One serialiser, so the two date columns of the same table cannot drift.

    They are rendered by the same frontend formatter, which decides how to read
    a bare timestamp. If one route started emitting a different shape the column
    beside it would quietly show a different hour.
    """
    uid = _member(client, admin_id, None)
    try:
        assert client.post("/api/auth/login", json={"actor_id": uid}).status_code == 200
        u = next(x for x in _users(client) if x["id"] == uid)
        assert OFFSET.search(u["last_login"]) and OFFSET.search(u["created_at"])
        assert OFFSET.search(u["last_login"]).group(1) == OFFSET.search(u["created_at"]).group(1), u
    finally:
        _forget(client, admin_id, [uid])


def test_a_brand_new_account_was_created_now_and_not_in_another_zone(client, admin_id):
    """The instant is right, not merely marked.

    An offset bolted onto a timestamp that was never UTC would pass the shape
    check above and still be three hours out, so this one compares the value to
    the clock: an account opened a moment ago reads as a moment ago.
    """
    uid = _member(client, admin_id, None)
    try:
        created = datetime.fromisoformat(next(x for x in _users(client) if x["id"] == uid)["created_at"])
        drift = abs((datetime.now(timezone.utc) - created).total_seconds())
        assert drift < 300, f"created_at is {drift / 3600:.1f}h away from now: {created.isoformat()}"
    finally:
        _forget(client, admin_id, [uid])


# ── active_user_count ────────────────────────────────────────────────

def test_every_unit_reports_how_many_of_its_people_are_active(client):
    """/api/departments exposes active_user_count, an int, never above the total."""
    depts = client.get("/api/departments").json()
    assert depts, "expected at least one seeded unit"
    for d in depts:
        assert "active_user_count" in d, f"unit {d['id']} has no active_user_count"
        assert isinstance(d["active_user_count"], int) and not isinstance(d["active_user_count"], bool), \
            f"unit {d['id']} active_user_count is {type(d['active_user_count'])}"
        assert isinstance(d["user_count"], int)
        assert d["active_user_count"] <= d["user_count"], \
            f"unit {d['id']} reports {d['active_user_count']} active of {d['user_count']} assigned"


def test_a_unit_nobody_signed_into_reports_nobody_active(client, admin_id):
    """Assigned is not active — a unit full of people who never came reads zero."""
    d = _dept(client, admin_id)
    uids = []
    try:
        uids = [_member(client, admin_id, d["id"]) for _ in range(2)]
        row = _row(client, d["id"])
        assert row["user_count"] == 2, row
        assert row["active_user_count"] == 0, row
    finally:
        _forget(client, admin_id, uids)
        client.delete(f"/api/departments/{d['id']}?actor_id={admin_id}")


def test_the_window_is_thirty_days_and_the_boundary_holds(client, admin_id):
    """One login inside the window counts; one well outside it does not.

    The two are written at known instants — the API can only record "now" — so
    the test is about the cutoff itself rather than about whatever the seed
    happens to contain.
    """
    d = _dept(client, admin_id)
    uids = []
    try:
        recent, ancient = _member(client, admin_id, d["id"]), _member(client, admin_id, d["id"])
        uids = [recent, ancient]
        _log_in_at(recent, NOW - timedelta(days=3))
        _log_in_at(ancient, NOW - timedelta(days=90))
        row = _row(client, d["id"])
        assert row["user_count"] == 2, row
        assert row["active_user_count"] == 1, \
            f"expected only the recent login to count, got {row['active_user_count']}"
    finally:
        _forget(client, admin_id, uids)
        client.delete(f"/api/departments/{d['id']}?actor_id={admin_id}")


def test_a_login_just_inside_thirty_days_still_counts(client, admin_id):
    """The edge, from both sides: 29 days ago is active, 31 days ago is not."""
    d = _dept(client, admin_id)
    uids = []
    try:
        inside, outside = _member(client, admin_id, d["id"]), _member(client, admin_id, d["id"])
        uids = [inside, outside]
        _log_in_at(inside, NOW - timedelta(days=29))
        _log_in_at(outside, NOW - timedelta(days=31))
        assert _row(client, d["id"])["active_user_count"] == 1, _row(client, d["id"])
    finally:
        _forget(client, admin_id, uids)
        client.delete(f"/api/departments/{d['id']}?actor_id={admin_id}")


def test_somebody_who_signs_in_every_day_is_one_active_user(client, admin_id):
    """The DISTINCT. Counting login rows instead of people reported 30 active
    users in a unit of one, which is the number an admin would have believed."""
    d = _dept(client, admin_id)
    uids = []
    try:
        uid = _member(client, admin_id, d["id"])
        uids = [uid]
        for day in range(1, 11):
            _log_in_at(uid, NOW - timedelta(days=day))
        row = _row(client, d["id"])
        assert row["user_count"] == 1, row
        assert row["active_user_count"] == 1, \
            f"ten logins by one person counted as {row['active_user_count']} active users"
    finally:
        _forget(client, admin_id, uids)
        client.delete(f"/api/departments/{d['id']}?actor_id={admin_id}")


def test_the_assigned_count_still_includes_a_deactivated_member(client, admin_id):
    """user_count is unchanged by this feature, and that is on purpose.

    It counts everybody assigned to the unit, deactivated accounts included —
    the directory shows them, so the unit has to account for them. The activity
    figure is the one that answers who is actually using the place, and it
    follows the login rather than the status flag.
    """
    d = _dept(client, admin_id)
    uids = []
    try:
        gone, here = _member(client, admin_id, d["id"]), _member(client, admin_id, d["id"])
        uids = [gone, here]
        _log_in_at(here, NOW - timedelta(days=2))
        assert client.patch(f"/api/users/{gone}",
                            json={"actor_id": admin_id, "is_active": False}).status_code == 200
        row = _row(client, d["id"])
        assert row["user_count"] == 2, f"a deactivated member dropped out of user_count: {row}"
        assert row["active_user_count"] == 1, row
    finally:
        _forget(client, admin_id, uids)
        client.delete(f"/api/departments/{d['id']}?actor_id={admin_id}")


def test_a_login_belongs_to_the_unit_the_person_is_in_now(client, admin_id):
    """Moving somebody moves their activity with them.

    The count is a join from the unit through its users to their logins, so a
    person reassigned yesterday is counted where they are today. Pinned because
    the alternative — remembering which unit each login was made from — is a
    different product, and nobody should implement it by accident.
    """
    a, b = _dept(client, admin_id), _dept(client, admin_id)
    uids = []
    try:
        uid = _member(client, admin_id, a["id"])
        uids = [uid]
        _log_in_at(uid, NOW - timedelta(days=1))
        assert _row(client, a["id"])["active_user_count"] == 1
        assert _row(client, b["id"])["active_user_count"] == 0
        assert client.patch(f"/api/users/{uid}",
                            json={"actor_id": admin_id, "department_id": b["id"]}).status_code == 200
        assert _row(client, a["id"])["active_user_count"] == 0, _row(client, a["id"])
        assert _row(client, b["id"])["active_user_count"] == 1, _row(client, b["id"])
    finally:
        _forget(client, admin_id, uids)
        for d in (a, b):
            client.delete(f"/api/departments/{d['id']}?actor_id={admin_id}")


def test_an_unassigned_persons_login_is_counted_by_no_unit(client, admin_id):
    """Somebody with no unit must not be added to any of them, nor to all."""
    before = {d["id"]: d["active_user_count"] for d in client.get("/api/departments").json()}
    uids = []
    try:
        uid = _member(client, admin_id, None)
        uids = [uid]
        _log_in_at(uid, NOW - timedelta(hours=1))
        after = {d["id"]: d["active_user_count"] for d in client.get("/api/departments").json()}
        assert after == before, f"an unassigned login moved a unit's figure: {before} → {after}"
    finally:
        _forget(client, admin_id, uids)


# ── the two shapes must be one shape ─────────────────────────────────

def test_creating_a_unit_answers_with_the_same_keys_as_listing_one(client, admin_id):
    """POST /api/departments returns a row, not a stub.

    The screen renders what it gets back rather than refetching, so a response
    missing active_user_count would draw `undefined` in the new column. Keys, not
    just the one field: the shapes have to stay one shape.
    """
    created = None
    try:
        r = client.post("/api/departments",
                        json={"actor_id": admin_id, "name": f"יחידת צורה {uuid.uuid4().hex[:6]}",
                              "code": "QA", "color": "#0073ea"})
        assert r.status_code == 200, r.text
        created = r.json()
        listed = _row(client, created["id"])
        assert set(created) == set(listed), \
            f"POST returns {sorted(set(created) ^ set(listed))} differently from GET"
        # a brand-new unit is empty, and says so in numbers rather than in nulls
        for key in ("user_count", "board_count", "active_user_count"):
            assert created[key] == 0, f"{key} on a new unit is {created[key]!r}"
    finally:
        if created:
            client.delete(f"/api/departments/{created['id']}?actor_id={admin_id}")


def test_the_activity_figure_is_not_a_way_in(client, member_id):
    """The counts ride on routes a member may already read; nothing new opened.

    /api/departments has always been readable — the panel that writes to it is
    the guarded one. This pins that adding the column did not change either half.
    """
    assert client.get("/api/departments", headers={"X-CityOS-User": str(member_id)}).status_code == 200
    r = client.post("/api/departments", json={"actor_id": member_id, "name": "יחידה אסורה"})
    assert r.status_code == 403, r.text
