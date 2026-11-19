"""כאשר הסטטוס משתנה, עדכן עמודת תאריך להיום — and the days around it.

The rule could already be built from the general "עדכן את העמודה …" template
(see test_a_status_change_stamps_todays_date.py, which pins that it RUNS). What
it could not be is said: the builder showed the value blank as
{{תאריך ההפעלה}}, and the only day it could name was today.

What this file pins:

  · a template of its own, recommended, that starts on «כל ערך שהוא» and
    «היום» and needs a date column on the board;
  · a day counted from the firing — {{now.date+7}}, {{now.date-3}} — is a
    value the engine accepts and writes on the board's calendar;
  · the saved sentence reads it in words: «בעוד 7 ימים», not the token;
  · and a fixed day, written as a person writes one, is written as that day.
"""
import pathlib
import subprocess
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Task


ROOT = pathlib.Path(__file__).resolve().parent.parent


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, bid, admin_id, **spec):
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    col = {"id": "col_" + spec["type"][:5] + str(len(cols)), **spec}
    cols.append(col)
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return col


def _add(client, bid, admin_id, config, recipe_id="status_stamp_date"):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id):
    return client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "user_id": admin_id}).json()["id"]


def _cell(tid, col_id):
    with Session(cityos_main.engine) as db:
        return (db.query(Task).filter(Task.id == tid).first().custom_fields or {}).get(col_id)


def _move(client, tid, admin_id, status):
    client.patch(f"/api/tasks/{tid}", json={"status": status, "user_id": admin_id})


# ── the template ──────────────────────────────────────────────────────────
def test_the_template_is_recommended_and_starts_where_it_is_wanted():
    t = next(x for x in recipes.catalog() if x["id"] == "status_stamp_date")
    assert t["recommended"] and t["title"] == "כאשר הסטטוס משתנה, עדכן עמודת תאריך להיום"
    by = {f["key"]: f for f in t["fields"]}
    assert by["t_status"].get("default") == recipes.ANY_STATUS
    assert by["a_text"].get("default") == "{{now.date}}"
    assert by["a_column"].get("col_kinds") == ["date"]
    assert "date_column" in t["needs"] and recipes.NEEDS_HE["date_column"]


def test_a_board_without_a_date_column_is_told_what_it_is_missing(client, admin_id):
    bid = _board(client, admin_id, "בלי תאריך")
    _col(client, bid, admin_id, type="text", title="הערה")
    with Session(cityos_main.engine) as db:
        board = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        assert cityos_main._board_template_has(db, board)["date_column"] is False
    _col(client, bid, admin_id, type="date", title="תאריך עדכון")
    with Session(cityos_main.engine) as db:
        board = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        assert cityos_main._board_template_has(db, board)["date_column"] is True


# ── it runs, on any status change ─────────────────────────────────────────
def test_any_status_change_stamps_today(client, admin_id):
    bid = _board(client, admin_id, "חותמת היום")
    col = _col(client, bid, admin_id, type="date", title="תאריך עדכון")
    made = _add(client, bid, admin_id, {"t_status": recipes.ANY_STATUS,
                                        "a_column": col["id"], "a_text": "{{now.date}}"})
    assert "ל«היום»" in made["sentence"], made["sentence"]
    tid = _item(client, bid, admin_id)
    _move(client, tid, admin_id, "in_progress")
    assert _cell(tid, col["id"]) == datetime.now().date().isoformat()


def test_a_day_counted_from_today_is_written_and_read_in_words(client, admin_id):
    bid = _board(client, admin_id, "בעוד שבוע")
    col = _col(client, bid, admin_id, type="date", title="תאריך בדיקה")
    made = _add(client, bid, admin_id, {"t_status": recipes.ANY_STATUS,
                                        "a_column": col["id"], "a_text": "{{now.date+7}}"})
    assert "ל«בעוד 7 ימים»" in made["sentence"], made["sentence"]
    assert "now.date" not in made["sentence"]
    tid = _item(client, bid, admin_id)
    _move(client, tid, admin_id, "in_progress")
    assert _cell(tid, col["id"]) == (datetime.now().date() + timedelta(days=7)).isoformat()


def test_a_day_back_is_a_day_back(client, admin_id):
    bid = _board(client, admin_id, "לפני")
    col = _col(client, bid, admin_id, type="date", title="תאריך")
    made = _add(client, bid, admin_id, {"t_status": recipes.ANY_STATUS,
                                        "a_column": col["id"], "a_text": "{{now.date-3}}"})
    assert "ל«לפני 3 ימים»" in made["sentence"], made["sentence"]
    tid = _item(client, bid, admin_id)
    _move(client, tid, admin_id, "done")
    assert _cell(tid, col["id"]) == (datetime.now().date() - timedelta(days=3)).isoformat()


def test_a_fixed_day_is_that_day(client, admin_id):
    bid = _board(client, admin_id, "תאריך קבוע")
    col = _col(client, bid, admin_id, type="date", title="תאריך")
    _add(client, bid, admin_id, {"t_status": recipes.ANY_STATUS,
                                 "a_column": col["id"], "a_text": "04/03/2026"})
    tid = _item(client, bid, admin_id)
    _move(client, tid, admin_id, "in_progress")
    assert _cell(tid, col["id"]) == "2026-03-04"


def test_the_engine_accepts_the_offset_and_refuses_nonsense():
    assert recipes.unknown_tokens("{{now.date+14}}") == []
    assert recipes.unknown_tokens("{{now.date-2}}") == []
    assert recipes.unknown_tokens("{{now.date+}}") == ["now.date+"]
    assert recipes.date_offset("now.date+9999") is None       # four digits is not a day count
    assert recipes.date_phrase("{{now.date+1}}") == "מחר"
    assert recipes.date_phrase("נבדק {{now.date}}") is None    # a sentence, not a day


def test_the_older_column_rule_reads_the_same_words(client, admin_id):
    """The rule in her screenshot — a column trigger stamping a date column —
    reads «בעוד 14 ימים» too: the reading belongs to the value, not to the
    template it was built from."""
    bid = _board(client, admin_id, "תקנה 15")
    watched = _col(client, bid, admin_id, type="date", title="תקנה 15 אחרונה")
    stamp = _col(client, bid, admin_id, type="date", title="תאריך עדכון תקנה 15")
    made = _add(client, bid, admin_id, {"t_column": watched["id"], "a_column": stamp["id"],
                                        "a_text": "{{now.date+14}}"},
                recipe_id="column_changed_set_column")
    assert "ל«בעוד 14 ימים»" in made["sentence"], made["sentence"]


def test_the_browser_half():
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" /
                                    "automation_status_stamps_a_date.mjs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
