"""אוטומציה — "כשתאריך משתנה, עדכן תאריך אחר בעוד מספר הימים שבעמודת מספר".

Neither half could be said before. {{now.date+N}} counts from the firing and
its N is typed into the rule, and {{field.<date>}} copies a date without moving
it. Each item here carries its own number of days, so the count has to be read
off the item: {{date.add.<date col>.<number col>}}.

What is pinned: the target lands on the source date plus the item's own days,
again when the source date moves, backwards for a negative number; an empty
source or an empty count is skipped with the column it is missing from named
(not the coercion's "'' אינו תאריך"); the rule saves, and its sentence reads
the two column names rather than the code.
"""
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Task


def _board(client, admin_id):
    return client.post("/api/boards", json={"name": "לוח ימי טיפול",
                                            "user_id": admin_id}).json()["id"]


def _cols(client, bid, admin_id, *specs):
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    made = []
    for i, spec in enumerate(specs):
        col = {"id": f"col_t{i}{spec['type'][:3]}", **spec}
        cols.append(col)
        made.append(col)
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return made


def _cell(tid, cid):
    with Session(cityos_main.engine) as db:
        return (db.query(Task).filter(Task.id == tid).first().custom_fields or {}).get(cid)


def _set(client, tid, admin_id, **cf):
    r = client.patch(f"/api/tasks/{tid}", json={"custom_fields": cf, "user_id": admin_id})
    assert r.status_code == 200, r.text


def _rule(client, bid, admin_id, src, num, dst):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "column_changed_set_column",
                          "config": {"t_column": src["id"], "a_column": dst["id"],
                                     "a_text": "{{date.add.%s.%s}}" % (src["id"], num["id"])}})
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


def test_the_target_date_is_the_source_date_plus_the_items_own_days(client, admin_id):
    bid = _board(client, admin_id)
    src, num, dst = _cols(client, bid, admin_id,
                          {"type": "date", "title": "תאריך הגשה"},
                          {"type": "number", "title": "ימי טיפול"},
                          {"type": "date", "title": "תאריך יעד"})
    _rule(client, bid, admin_id, src, num, dst)
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "בקשה",
                                          "user_id": admin_id}).json()["id"]
    _set(client, tid, admin_id, **{num["id"]: 10})
    _set(client, tid, admin_id, **{src["id"]: "2026-12-25"})
    assert _cell(tid, dst["id"]) == "2027-01-04", _runs(client, bid, admin_id)

    # the source moving again moves the target again
    _set(client, tid, admin_id, **{src["id"]: "2026-02-20"})
    assert _cell(tid, dst["id"]) == "2026-03-02", _runs(client, bid, admin_id)

    # a negative count is a day before
    _set(client, tid, admin_id, **{num["id"]: -3})
    _set(client, tid, admin_id, **{src["id"]: "2026-03-01"})
    assert _cell(tid, dst["id"]) == "2026-02-26", _runs(client, bid, admin_id)


def test_an_empty_count_is_skipped_and_says_which_column(client, admin_id):
    bid = _board(client, admin_id)
    src, num, dst = _cols(client, bid, admin_id,
                          {"type": "date", "title": "תאריך הגשה"},
                          {"type": "number", "title": "ימי טיפול"},
                          {"type": "date", "title": "תאריך יעד"})
    _rule(client, bid, admin_id, src, num, dst)
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "בלי ימים",
                                          "user_id": admin_id}).json()["id"]
    _set(client, tid, admin_id, **{src["id"]: "2026-12-25"})
    assert _cell(tid, dst["id"]) is None
    said = " ".join(str(r.get("note") or r.get("reason") or r) for r in _runs(client, bid, admin_id))
    assert "ימי טיפול" in said, said


def test_the_rule_saves_and_reads_as_its_column_names(client, admin_id):
    bid = _board(client, admin_id)
    src, num, dst = _cols(client, bid, admin_id,
                          {"type": "date", "title": "תאריך הגשה"},
                          {"type": "number", "title": "ימי טיפול"},
                          {"type": "date", "title": "תאריך יעד"})
    made = _rule(client, bid, admin_id, src, num, dst)
    rows = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"]
    row = next(x for x in rows if x["id"] == made["id"])
    text = str(row)
    assert "«תאריך הגשה» ועוד מספר הימים שב«ימי טיפול»" in text, text
    assert "date.add" not in (row.get("sentence") or row.get("description") or ""), row


def test_the_token_is_known_to_the_engine():
    code = "date.add.col_a1.col_b2"
    assert recipes.token_code(code) == code
    assert recipes.unknown_tokens("{{%s}}" % code) == []
    assert recipes.date_add_cols(code) == ("col_a1", "col_b2")
    # a field. token is still a field. token
    assert recipes.date_add_cols("field.col_a1") is None


# ── the template, by name ─────────────────────────────────────────────────
# The general "כאשר ערך עמודה משתנה" could say this from the first day, and
# that is where it was not found: the value hides at the bottom of the date
# menu behind three blanks that take any column. The library names it.
def test_the_library_offers_it_under_its_own_name():
    t = next(x for x in recipes.catalog() if x["id"] == "date_changed_shift_date")
    assert t["recommended"], t
    assert t["title"] == "כאשר תאריך משתנה, עדכן תאריך אחר לפי מספר הימים שבעמודת מספר"
    by = {f["key"]: f for f in t["fields"]}
    assert by["t_column"].get("col_kinds") == ["date"]
    assert by["a_column"].get("col_kinds") == ["date"]
    assert {"date_column", "number_column"} <= set(t["needs"])
    assert recipes.NEEDS_HE["number_column"]
    # library-only: built from scratch, the pair still lands on the general one
    assert not any(a["recipe_id"] == "date_changed_shift_date"
                   for g in recipes.blueprint() for a in g["actions"])


def test_a_rule_from_the_template_runs(client, admin_id):
    bid = _board(client, admin_id)
    src, num, dst = _cols(client, bid, admin_id,
                          {"type": "date", "title": "תאריך הגשה"},
                          {"type": "number", "title": "ימי טיפול"},
                          {"type": "date", "title": "תאריך יעד"})
    with Session(cityos_main.engine) as db:
        board = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        assert cityos_main._board_template_has(db, board)["number_column"] is True
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "date_changed_shift_date",
                          "config": {"t_column": src["id"], "a_column": dst["id"],
                                     "a_text": "{{date.add.%s.%s}}" % (src["id"], num["id"])}})
    assert r.status_code == 200, r.text
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "מהתבנית",
                                          "user_id": admin_id}).json()["id"]
    _set(client, tid, admin_id, **{num["id"]: 7})
    _set(client, tid, admin_id, **{src["id"]: "2026-12-01"})
    assert _cell(tid, dst["id"]) == "2026-12-08", _runs(client, bid, admin_id)
