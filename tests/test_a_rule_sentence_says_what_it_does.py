"""משפט האוטומציה — מה הכלל עושה, לא מאיזה טוקן הוא בנוי.

The rule somebody writes first on a board that tracks handling is "כאשר ערך
העמודה «האם ניתן לשחרר?» משתנה, רשום את תאריך העדכון", and the only way to say
the value is the {{תאריך ההפעלה}} token. It ran correctly and it READ as
engine code:

    עדכן את העמודה «תאריך אחרון לעדכון / בדיקה» ל«{{תאריך ההפעלה}}»

in a list of thirty rules somebody scans to find the one that is wrong. The
braces are not information to a reader; they are punctuation to parse past.

What is pinned here is the reading and nothing else — the stored config is
untouched, which is what lets a rule written a year ago read better today
without being re-saved. Three rules:

  · a value that is entirely the firing-date token, written into a DATE
    column, reads «היום» — what the cell will hold the moment it fires.
  · the same token anywhere else reads as its own name, without the braces.
  · a token INSIDE a longer text keeps its braces, and so does one the engine
    has no answer for. "שלום {{שם הפריט}}" and the literal "שלום שם הפריט" are
    two different values, and the sentence is where that difference is read.
"""
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main


def _board(client, admin_id, name="לוח משפטים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, bid, admin_id, **spec):
    cols = [c for c in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
            if str(c.get("id", "")).startswith("col_")]
    col = {"id": "col_" + spec["type"][:5] + str(len(cols)), **spec}
    cols.append(col)
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return col


def _sentence(client, bid, admin_id, recipe_id, config):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config})
    assert r.status_code == 200, r.text
    made = r.json()
    rows = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"]
    return next(x for x in rows if x["id"] == made["id"])["sentence"]


def test_a_rule_that_stamps_the_date_says_today(client, admin_id):
    """The rule in the screenshot, read back as the line somebody scans."""
    bid = _board(client, admin_id)
    watched = _col(client, bid, admin_id, type="status", title="האם ניתן לשחרר?",
                   options=[{"id": "o_a", "label": "כן"}, {"id": "o_b", "label": "לא"}])
    stamp = _col(client, bid, admin_id, type="date",
                 title="תאריך אחרון לעדכון / בדיקה")
    s = _sentence(client, bid, admin_id, "column_changed_set_column",
                  {"t_column": watched["id"], "a_column": stamp["id"],
                   "a_text": "{{now.date}}"})
    assert "«היום»" in s, s
    assert "{{" not in s, s
    # and it still says WHICH column it stamps — the word today replaces the
    # value, never the target
    assert "«תאריך אחרון לעדכון / בדיקה»" in s, s


def test_the_same_token_written_in_hebrew_reads_the_same(client, admin_id):
    """A rule built through the screen stores the NAME inside the braces.

    Those are the rules already on people's boards — the builder translated
    the code into the name on the way into the box and back on the way out,
    and for a while it stored back what it showed. They read like every other
    rule here, with nothing re-saved.
    """
    bid = _board(client, admin_id)
    stamp = _col(client, bid, admin_id, type="date", title="עודכן")
    s = _sentence(client, bid, admin_id, "created_set_column",
                  {"a_column": stamp["id"], "a_text": "{{תאריך ההפעלה}}"})
    assert "«היום»" in s, s


def test_the_date_token_in_a_text_column_is_a_date_and_not_the_word(client, admin_id):
    """«היום» is what a DATE cell will hold. A text cell holds "18/11/2026".

    Saying "today" there would be the sentence describing a value the cell
    never receives, which is the failure this whole change exists to stop.
    """
    bid = _board(client, admin_id)
    note = _col(client, bid, admin_id, type="text", title="הערה")
    s = _sentence(client, bid, admin_id, "created_set_column",
                  {"a_column": note["id"], "a_text": "{{now.date}}"})
    assert "«היום»" not in s, s
    assert "«תאריך ההפעלה»" in s, s      # its own name, and still no braces
    assert "{{" not in s, s


def test_a_token_inside_a_longer_text_keeps_its_braces(client, admin_id):
    """Because there the braces are the information.

    "המשך טיפול ב-{{שם הפריט}}" and the literal "המשך טיפול ב-שם הפריט" are two
    different values, and the sentence is where somebody checks which one the
    rule holds.
    """
    bid = _board(client, admin_id)
    note = _col(client, bid, admin_id, type="text", title="הערה")
    s = _sentence(client, bid, admin_id, "created_set_column",
                  {"a_column": note["id"], "a_text": "המשך טיפול ב-{{שם הפריט}}"})
    assert "{{שם הפריט}}" in s, s


def test_a_token_the_engine_cannot_resolve_is_shown_as_it_is(client, admin_id):
    """A column TITLE typed as a token resolves to nothing and is written
    verbatim — deliberately, because two boards may title a column the same.
    The sentence shows the code, so the rule looks as odd as it is instead of
    reading like one that works."""
    assert recipes.token_phrase("{{האם ניתן לשחרר}}") == "{{האם ניתן לשחרר}}"
    assert recipes.token_phrase("{{field.col_x}}") == "{{field.col_x}}"
    assert recipes.token_phrase("{{field.col_x}}", {"col_x": "שם הנוהל"}.get) \
        == "ערך העמודה שם הנוהל"


def test_an_extra_action_reads_the_same_as_the_rules_own(client, admin_id):
    """The second action is rendered by a different function from the first.

    They have drifted before — one of them quoting a label and the other the
    stored key — so the pairing is pinned rather than assumed.
    """
    bid = _board(client, admin_id)
    stamp = _col(client, bid, admin_id, type="date", title="עודכן")
    second = _col(client, bid, admin_id, type="date", title="נבדק")
    s = _sentence(client, bid, admin_id, "created_set_column",
                  {"a_column": stamp["id"], "a_text": "{{now.date}}",
                   recipes.ACTIONS_KEY: [
                       {"key": "set_column",
                        "values": {"column": second["id"], "text": "{{now.date}}"}}]})
    assert s.count("«היום»") == 2, s
    assert "{{" not in s, s


def test_nothing_about_the_stored_rule_changed(client, admin_id):
    """The reading moved; the wire did not. A rule read back through the API
    still holds the token, because that is what the engine resolves and what
    survives the column being renamed."""
    bid = _board(client, admin_id)
    stamp = _col(client, bid, admin_id, type="date", title="עודכן")
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "created_set_column",
                          "config": {"a_column": stamp["id"], "a_text": "{{now.date}}"}})
    assert r.status_code == 200, r.text
    rows = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()["automations"]
    row = next(x for x in rows if x["id"] == r.json()["id"])
    assert row["config"]["a_text"] == "{{now.date}}", row["config"]
    with Session(cityos_main.engine) as db:
        a = db.query(cityos_main.Automation).filter(
            cityos_main.Automation.id == row["id"]).first()
        assert (a.config or {}).get("a_text") == "{{now.date}}"
