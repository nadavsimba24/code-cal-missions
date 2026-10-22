"""Group — גורם מפעיל מבוסס תאריך: which clock, and which instant.

  · the board's zone, then the organisation's, then Asia/Jerusalem;
  · a date with no time means nine in the morning THERE;
  · a moment that passed while the rule was paused does not run retroactively;
  · moving a date cancels the schedule made for the old one, and deleting it
    cancels the run altogether.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, Board, Organization, Task

UTC = timezone.utc
IL = ZoneInfo("Asia/Jerusalem")


def _board(client, admin_id, name="לוח תאריכים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id, config, **extra):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט", **extra):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **extra}).json()["id"]


def _runs(client, bid, admin_id, kind=None):
    rows = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}"
                      ).json()["runs"]
    return [r for r in rows if kind is None or r["event_type"] == kind]


def _aged(aid, days=60):
    """A rule that has been switched on for a while — see _already_on_for in
    tests/test_automation_triggers.py for why these need it."""
    with Session(cityos_main.engine) as db:
        db.query(Automation).filter(Automation.id == aid).update(
            {Automation.activated_at:
             datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)})
        db.commit()


def _set_due(client, tid, admin_id, value):
    r = client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "due_date": value})
    assert r.status_code == 200, r.text


def _tz(client, bid, admin_id, name):
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"timezone": name})
    assert r.status_code == 200, r.text


# ── which clock ─────────────────────────────────────────────────────────────

def test_a_board_with_no_zone_of_its_own_keeps_the_municipality_s(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי אזור")
    d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    assert d["timezone"] == "Asia/Jerusalem" and d["timezone_own"] is False
    assert d["due_default_hour"] == 9


def test_a_board_can_name_its_own(client, admin_id):
    bid = _board(client, admin_id, "לוח עם אזור")
    _tz(client, bid, admin_id, "Europe/Berlin")
    d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    assert d["timezone"] == "Europe/Berlin" and d["timezone_own"] is True
    # and give it back
    _tz(client, bid, admin_id, "")
    assert client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                      ).json()["timezone"] == "Asia/Jerusalem"


def test_a_zone_that_is_not_one_is_refused(client, admin_id):
    bid = _board(client, admin_id, "לוח אזור שגוי")
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}",
                     json={"timezone": "Mars/Olympus"})
    assert r.status_code == 400 and "IANA" in r.json()["detail"]


def test_only_a_board_admin_may_move_the_clock(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח אזור הרשאות")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    r = client.patch(f"/api/boards/{bid}?actor_id={guinea_id}",
                     json={"timezone": "Europe/Berlin"})
    assert r.status_code == 403


def test_the_board_falls_back_to_the_organisation(client, admin_id):
    bid = _board(client, admin_id, "לוח יורש ארגון")
    r = client.patch("/api/organization/settings",
                     json={"user_id": admin_id, "timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    try:
        d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
        assert d["timezone"] == "Europe/Berlin" and d["timezone_own"] is False
        # the board's own still wins over it
        _tz(client, bid, admin_id, "Asia/Tokyo")
        assert client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                          ).json()["timezone"] == "Asia/Tokyo"
    finally:
        client.patch("/api/organization/settings",
                     json={"user_id": admin_id, "timezone": ""})


def test_only_a_system_admin_sets_the_organisation_s(client, admin_id, guinea_id):
    assert client.patch("/api/organization/settings",
                        json={"user_id": guinea_id, "timezone": "UTC"}).status_code == 403
    assert client.patch("/api/organization/settings",
                        json={"user_id": admin_id, "timezone": "Mars/Olympus"}
                        ).status_code == 400
    assert client.get(f"/api/organization/settings?user_id={admin_id}"
                      ).json()["default_timezone"] == "Asia/Jerusalem"


def test_a_zone_that_was_typed_wrong_does_not_stop_the_board(client, admin_id):
    """A board whose zone is nonsense still runs — on the default. The
    alternative is a board whose automations stop at a typo."""
    bid = _board(client, admin_id, "לוח אזור מקולקל")
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == bid).first()
        b.settings = {**(b.settings or {}), "timezone": "לא אזור"}
        db.commit()
        assert str(cityos_main._board_tz(db, b)) == "Asia/Jerusalem"


# ── which instant ───────────────────────────────────────────────────────────

def test_a_date_with_no_time_means_nine_in_the_morning_there(client, admin_id):
    plain = datetime(2026, 12, 1)
    assert cityos_main._due_moment(plain, IL) == datetime(2026, 12, 1, 9, tzinfo=IL)
    berlin = cityos_main._due_moment(plain, ZoneInfo("Europe/Berlin"))
    assert berlin.hour == 9 and str(berlin.tzinfo) == "Europe/Berlin"
    # and the two are different instants — nine o'clock is a local thing
    assert cityos_main._due_moment(plain, IL).astimezone(UTC) != berlin.astimezone(UTC)


def test_a_date_that_names_a_time_is_the_instant_it_was_stored_as(client, admin_id):
    """The column holds no zone and what is written into it is UTC — the
    picker sends the chosen day at local noon, converted. So a stored time is
    an instant already, and the board's zone does not move it a second time.
    """
    at_four = datetime(2026, 12, 1, 16, 30)
    assert cityos_main._due_moment(at_four, IL) == datetime(2026, 12, 1, 16, 30, tzinfo=UTC)
    # the same stored value means the same instant whatever the board's zone is
    assert cityos_main._due_moment(at_four, ZoneInfo("Asia/Tokyo")) \
        == cityos_main._due_moment(at_four, IL)


def test_the_picker_s_own_convention_lands_on_the_day_it_was_given(client, admin_id):
    """What the date cell really sends: the chosen day at local noon, as UTC.
    It must come back as that day on the board, not the one before it."""
    noon_il = datetime(2026, 12, 1, 12, tzinfo=IL)
    stored = noon_il.astimezone(UTC).replace(tzinfo=None)     # what SQLite keeps
    got = cityos_main._due_moment(stored, IL)
    assert got.astimezone(IL).date() == noon_il.date()
    assert got.astimezone(IL).hour == 12


def test_a_date_that_already_names_an_instant_is_left_alone(client, admin_id):
    exact = datetime(2026, 12, 1, 7, 0, tzinfo=UTC)
    assert cityos_main._due_moment(exact, IL) == exact
    assert cityos_main._due_moment(datetime(2026, 12, 1, 9, tzinfo=IL), IL) == exact


def test_the_same_wall_clock_is_a_different_instant_across_the_clock_change(client,
                                                                            admin_id):
    """Israel is UTC+2 in winter and UTC+3 in summer. Nine in the morning is
    nine in the morning on both sides of that, which is the point."""
    winter = cityos_main._due_moment(datetime(2026, 1, 15), IL)
    summer = cityos_main._due_moment(datetime(2026, 7, 15), IL)
    assert winter.hour == summer.hour == 9
    assert winter.utcoffset() != summer.utcoffset()
    assert winter.astimezone(UTC).hour == 7 and summer.astimezone(UTC).hour == 6


def test_an_hour_the_clocks_skipped_still_resolves(client, admin_id):
    """On the night the clocks go forward 02:30 does not exist. A due date on
    it must still name some instant rather than blowing up the sweep."""
    for day in (datetime(2026, 3, 27, 2, 30), datetime(2026, 10, 25, 2, 30)):
        got = cityos_main._due_moment(day, IL)
        assert got is not None and got.astimezone(UTC) is not None


def test_nothing_at_all_is_not_a_moment(client, admin_id):
    assert cityos_main._due_moment(None, IL) is None


# ── the zone decides when it fires ──────────────────────────────────────────

def test_a_date_does_not_fire_before_nine_in_the_board_s_morning(client, admin_id):
    """Today's date, with no time. At midnight UTC it is already "today" — and
    it is not nine o'clock yet anywhere, so nothing runs."""
    bid = _board(client, admin_id, "לוח תשע בבוקר")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    _aged(a["id"])
    today = datetime.now(IL).date()
    tid = _item(client, bid, admin_id, due_date=today.isoformat())
    before_nine = datetime.combine(today, datetime.min.time(), tzinfo=IL).replace(hour=7)
    fired = cityos_main._due_window_reached(
        "due_date_arrives", 0, cityos_main._due_moment(datetime.combine(
            today, datetime.min.time()), IL), before_nine)
    assert fired is False
    after_nine = before_nine.replace(hour=10)
    assert cityos_main._due_window_reached(
        "due_date_arrives", 0, cityos_main._due_moment(datetime.combine(
            today, datetime.min.time()), IL), after_nine) is True


def test_a_date_that_has_passed_fires_on_the_next_read(client, admin_id):
    bid = _board(client, admin_id, "לוח עבר")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    _aged(a["id"])
    when = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
    _item(client, bid, admin_id, due_date=when.isoformat())
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert len(_runs(client, bid, admin_id, "due_date_arrives")) == 1


# ── a date that moves, and a date that goes ────────────────────────────────

def test_moving_a_date_cancels_the_schedule_made_for_the_old_one(client, admin_id):
    """"שינוי תאריך יבטל את התזמון הקודם" — and the new date is a new schedule,
    which must be free to fire when it comes."""
    bid = _board(client, admin_id, "לוח הזזת תאריך")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    _aged(a["id"])
    tid = _item(client, bid, admin_id,
                due_date=(datetime.now(UTC).replace(tzinfo=None)
                          - timedelta(days=3)).isoformat())
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert len(_runs(client, bid, admin_id, "due_date_arrives")) == 1

    # forward, out of reach: the old schedule is spent and the new one has not come
    _set_due(client, tid, admin_id,
             (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30)).isoformat())
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert len(_runs(client, bid, admin_id, "due_date_arrives")) == 1

    # and back to a moment that HAS come — a different schedule, so it fires
    _set_due(client, tid, admin_id,
             (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).isoformat())
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    runs = _runs(client, bid, admin_id, "due_date_arrives")
    assert len(runs) == 2, [r["created_at"] for r in runs]


def test_the_same_date_saved_again_does_not_fire_twice(client, admin_id):
    """The other side of it: re-saving the date it already has is not a new
    schedule, and a reminder somebody already had is not sent again."""
    bid = _board(client, admin_id, "לוח אותו תאריך")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    _aged(a["id"])
    when = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).isoformat()
    tid = _item(client, bid, admin_id, due_date=when)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    for _ in range(3):
        _set_due(client, tid, admin_id, when)
        client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert len(_runs(client, bid, admin_id, "due_date_arrives")) == 1


def test_deleting_the_date_cancels_the_scheduled_run(client, admin_id):
    bid = _board(client, admin_id, "לוח מחיקת תאריך")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    _aged(a["id"])
    tid = _item(client, bid, admin_id,
                due_date=(datetime.now(UTC).replace(tzinfo=None)
                          + timedelta(days=1)).isoformat())
    _set_due(client, tid, admin_id, None)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _runs(client, bid, admin_id, "due_date_arrives") == []
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.id == tid).first().due_date is None


def test_an_item_with_no_date_is_never_scheduled(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי תאריך")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    _aged(a["id"])
    _item(client, bid, admin_id)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _runs(client, bid, admin_id, "due_date_arrives") == []


# ── a moment that passed while the rule was off ────────────────────────────

def test_a_moment_that_passed_while_the_rule_was_paused_does_not_run(client, admin_id):
    """"לא ירוץ רטרואקטיבית כברירת מחדל". Switching a rule back on restamps
    the moment it became answerable, and everything behind that stays behind."""
    bid = _board(client, admin_id, "לוח השהיה")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    _aged(a["id"])
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "paused"})
    # the date comes and goes while nobody is listening
    _item(client, bid, admin_id,
          due_date=(datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).isoformat())
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _runs(client, bid, admin_id, "due_date_arrives") == []

    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert _runs(client, bid, admin_id, "due_date_arrives") == [], \
        "a date that passed while the rule was off ran retroactively"


def test_a_date_that_comes_after_it_is_switched_back_on_does_run(client, admin_id):
    """The rule is not deaf for ever — only to what it missed."""
    bid = _board(client, admin_id, "לוח אחרי חזרה")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "paused"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    # a date in the past as stored, but AFTER the rule came back: a minute ago
    _item(client, bid, admin_id,
          due_date=(datetime.now(UTC).replace(tzinfo=None)
                    + timedelta(seconds=2)).isoformat())
    import time
    time.sleep(2.1)
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert len(_runs(client, bid, admin_id, "due_date_arrives")) == 1


# ── the marker stays bounded ───────────────────────────────────────────────

def test_the_memory_of_what_already_fired_does_not_grow_without_end(client, admin_id):
    bid = _board(client, admin_id, "לוח זיכרון")
    a = _add(client, bid, admin_id, "due_notify_assignees", {})
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        row.state = {"fired": [f"{i}@2026-01-01T07:00" for i in range(cityos_main._DUE_FIRED_MAX + 50)]}
        row.activated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60)
        db.commit()
    _item(client, bid, admin_id,
          due_date=(datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).isoformat())
    client.get(f"/api/boards/{bid}?user_id={admin_id}")
    with Session(cityos_main.engine) as db:
        kept = (db.query(Automation).filter(Automation.id == a["id"]).first().state or {})
        assert len(kept.get("fired") or []) <= cityos_main._DUE_FIRED_MAX
