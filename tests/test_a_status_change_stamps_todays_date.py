"""אוטומציה — "כשהסטטוס זז, רשום את תאריך העדכון".

This is the first rule anybody writes on a board that tracks handling, and
until now neither half of it could be said.

The VALUE could not be written. A date column stores the ISO day; the
{{תאריך ההפעלה}} token resolves to 11/11/2026, because that is the date a
Hebrew reader expects to find in the middle of a notification and it is the
same token both halves of the catalog offer. The two were never introduced, so
"עדכן את «תאריך עדכון» ל{{תאריך ההפעלה}}" was refused by its own token: the
history said "אינו תאריך — לא נכתב לעמודה" on every single firing and the cell
stayed empty. The rule looked active, ran, and did nothing.

The TRIGGER could not be said. A status trigger named one value — "כאשר
הסטטוס משתנה ל«אושר»" — and the nearest thing to "whenever it moves" was
"כאשר ערך העמודה משתנה", which hears a status column and is deaf to the
board's own status. The blank takes a wildcard now, on the trigger half only:
as an action, "שנה את הסטטוס לכל ערך שהוא" is not an instruction.
"""
import pathlib
import shutil
import subprocess
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Task


ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "automation_any_status.mjs"


def _board(client, admin_id, name="לוח תאריכים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, bid, admin_id, **spec):
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    col = {"id": "col_" + spec["type"][:5] + str(len(cols)), **spec}
    cols.append(col)
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return col


def _add(client, bid, admin_id, recipe_id, config):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _cell(tid, col_id):
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        return (t.custom_fields or {}).get(col_id)


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


def test_the_rule_she_asked_for_runs_end_to_end(client, admin_id):
    """כאשר הסטטוס משתנה (לכל ערך שהוא) — עדכן את «תאריך עדכון» ל«היום»."""
    bid = _board(client, admin_id)
    date_col = _col(client, bid, admin_id, type="date", title="תאריך עדכון")
    _add(client, bid, admin_id, "status_set_column",
         {"t_status": recipes.ANY_STATUS, "a_column": date_col["id"],
          "a_text": "{{now.date}}"})
    tid = _item(client, bid, admin_id)
    assert _cell(tid, date_col["id"]) is None

    client.patch(f"/api/tasks/{tid}", json={"status": "in_progress", "user_id": admin_id})
    today = datetime.now().date().isoformat()
    assert _cell(tid, date_col["id"]) == today, \
        f"the cell holds {_cell(tid, date_col['id'])!r}; runs: {_runs(client, bid, admin_id)}"

    # …and again on the NEXT change, whatever the value is: that is the whole
    # of what "לכל ערך שהוא" means, and a rule that fired once would be the
    # one-value rule wearing a different label.
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        cf = dict(t.custom_fields or {})
        cf[date_col["id"]] = "2020-01-01"
        t.custom_fields = cf
        db.commit()
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert _cell(tid, date_col["id"]) == today


def test_the_rule_already_on_the_board_writes_its_date_now(client, admin_id):
    """The one that was there before, which is where this was found.

    "כאשר ערך העמודה «תקנה 15 אחרונה» משתנה, עדכן את «תאריך עדכון תקנה 15»
    ל{{תאריך ההפעלה}}" — a rule somebody built, switched on, and watched do
    nothing. It is the same token and the same refusal as the one above; what
    makes it worth its own test is that nothing about it had to change. The
    rule in the database is untouched and it writes its date from the next
    firing on.
    """
    bid = _board(client, admin_id)
    watched = _col(client, bid, admin_id, type="date", title="תקנה 15 אחרונה")
    stamp = _col(client, bid, admin_id, type="date", title="תאריך עדכון תקנה 15")
    _add(client, bid, admin_id, "column_changed_set_column",
         {"t_column": watched["id"], "a_column": stamp["id"],
          "a_text": "{{now.date}}"})
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}",
                 json={"custom_fields": {watched["id"]: "2026-02-01"},
                       "user_id": admin_id})
    assert _cell(tid, stamp["id"]) == datetime.now().date().isoformat(), \
        f"runs: {_runs(client, bid, admin_id)}"


def test_a_date_written_by_a_rule_is_the_day_it_names(client, admin_id):
    """The spellings a rule can carry, and the one it may not.

    %m/%d/%Y is deliberately unreadable here: 03/04/2026 is the third of April
    in this product and the fourth of March in that one, and a rule writing
    into a cell may not guess which. A date silently off by a month is worse
    than one refused in the history.
    """
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, type="date", title="תאריך")
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        board = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        c = next(x for x in (board.settings or {}).get("columns", [])
                 if x["id"] == col["id"])
        for written, stored in (("2026-03-04", "2026-03-04"),
                                ("04/03/2026", "2026-03-04"),
                                ("04.03.2026", "2026-03-04"),
                                # {{זמן ההפעלה}} carries the hour; a date
                                # column holds the day
                                ("04/03/2026 09:30", "2026-03-04"),
                                ("2026-03-04T09:30:00", "2026-03-04")):
            got, err = cityos_main._coerce_cell(db, bid, c, written)
            assert err is None and got == stored, f"{written!r} → {got!r} / {err!r}"
        for refused in ("מחר", "13/13/2026", "", "04/03"):
            got, err = cityos_main._coerce_cell(db, bid, c, refused)
            assert got is None and err, f"{refused!r} was accepted as {got!r}"
    assert _cell(tid, col["id"]) is None


def test_the_wildcard_is_about_the_column_the_rule_names(client, admin_id):
    """"כאשר «שלב» משתנה לכל ערך שהוא" is about that column and no other.

    A board carries one built-in status and any number of status columns. A
    wildcard that heard all of them would be a different rule from the one it
    reads as — and on a board with "שלב" and "סטטוס אישור" it would fire twice
    for one person's single edit.
    """
    bid = _board(client, admin_id)
    stage = _col(client, bid, admin_id, type="status", title="שלב",
                 options=[{"id": "o_a", "label": "פתוח"}, {"id": "o_b", "label": "סגור"}])
    other = _col(client, bid, admin_id, type="status", title="סטטוס אישור",
                 options=[{"id": "o_c", "label": "ממתין"}, {"id": "o_d", "label": "אושר"}])
    mark = _col(client, bid, admin_id, type="date", title="עודכן")
    _add(client, bid, admin_id, "status_set_column",
         {"t_status": recipes.ANY_STATUS, "t_status_col": stage["id"],
          "a_column": mark["id"], "a_text": "{{now.date}}"})
    tid = _item(client, bid, admin_id)

    # the other column moving is not this rule's event
    client.patch(f"/api/tasks/{tid}",
                 json={"custom_fields": {other["id"]: "o_d"}, "user_id": admin_id})
    assert _cell(tid, mark["id"]) is None

    client.patch(f"/api/tasks/{tid}",
                 json={"custom_fields": {stage["id"]: "o_b"}, "user_id": admin_id})
    assert _cell(tid, mark["id"]) == datetime.now().date().isoformat()


def test_a_wildcard_rule_is_readable_and_not_blocked(client, admin_id):
    """It has to read as a sentence and survive the health check.

    The wildcard belongs to no vocabulary — that is the point of it — and the
    check that every status a rule names still exists on the board would
    otherwise report it as a status that was deleted, taking a working rule out
    of service and saying something untrue about why.
    """
    bid = _board(client, admin_id)
    stage = _col(client, bid, admin_id, type="status", title="שלב",
                 options=[{"id": "o_a", "label": "פתוח"}, {"id": "o_b", "label": "סגור"}])
    mark = _col(client, bid, admin_id, type="date", title="עודכן")
    made = _add(client, bid, admin_id, "status_set_column",
                {"t_status": recipes.ANY_STATUS, "t_status_col": stage["id"],
                 "a_column": mark["id"], "a_text": "{{now.date}}"})
    rows = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"]
    row = next(x for x in rows if x["id"] == made["id"])
    assert recipes.ANY_STATUS_LABEL in row["sentence"], row["sentence"]
    assert "«שלב»" in row["sentence"], row["sentence"]
    assert not row.get("blockers"), row.get("blockers")
    assert row["is_active"] is True


def test_the_wildcard_is_offered_on_the_trigger_half_only(client, admin_id):
    """And the engine says so itself, rather than the screen deciding."""
    caps = client.get(f"/api/automation-capabilities?user_id={admin_id}").json()
    assert caps["any_status"] == recipes.ANY_STATUS
    assert caps["any_status_label"] == recipes.ANY_STATUS_LABEL
    assert recipes.is_any_status(recipes.ANY_STATUS)
    assert not recipes.is_any_status("")      # an unfinished blank is not a wildcard
    assert not recipes.is_any_status("done")


def test_the_builder_offers_the_wildcard_where_it_means_something():
    """The screen's half: on the trigger blank, at the head of the list, and
    taken from the engine rather than written down. Runs the real Automations
    object out of index.html under node; the harness names the failing case."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
