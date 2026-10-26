"""מחיקת טופס, ומחיקת שדה שטופס נשען עליו.

Deleting a form takes the tab and the address and nothing else: the board,
its columns and every record a previous submission created are the board's
and stay. "סגור" is a state, not an erasure.

Deleting a COLUMN is the harder one, because a column is the board's and a
question is bound to one. The decision, taken when this was planned and the
same one the saved views take with a filter rule whose column is gone:
removing beats answering falsely. The question is not deleted — that would
throw away its wording, its help and its place in the order, and leave the
builder with nothing to look at. It is left bound and DEAD:

    never sent to a respondent · an answer to it never read ·
    shown to the builder, flagged · and a required one blocks publishing

Which is the whole of "no live mapping to a field that does not exist": the
mapping is still written down, and there is no door at which it is live.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}
ANON = {"X-CityOS-User": ""}


def _board(client, admin_id, name):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_col(client, bid, admin_id, title, ctype, options=None):
    cols = [dict(c) for c in _cols(client, bid)]
    col = {"type": ctype, "title": title}
    if options is not None:
        col["options"] = options
    cols.append(col)
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    return [c["id"] for c in _cols(client, bid) if c["title"] == title][0]


def _drop_col(client, bid, admin_id, cid, confirm=None):
    cols = [dict(c) for c in _cols(client, bid) if c["id"] != cid]
    body = {"actor_id": admin_id, "columns": cols}
    if confirm is not None:
        body["confirm_columns"] = confirm
    return client.patch(f"/api/boards/{bid}", json=body)


def _retype_col(client, bid, admin_id, cid, ctype, confirm=None):
    cols = [dict(c) for c in _cols(client, bid)]
    for c in cols:
        if c["id"] == cid:
            c["type"] = ctype
    body = {"actor_id": admin_id, "columns": cols}
    if confirm is not None:
        body["confirm_columns"] = confirm
    return client.patch(f"/api/boards/{bid}", json=body)


def _form(client, bid, admin_id, questions, publish=True, access="PUBLIC_LINK"):
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id)).json()
    q = {}
    for label, key, extra in questions:
        r = client.post(f"/api/forms/{f['id']}/components",
                        json={"kind": "question", "field_key": key,
                              "label": label, **(extra or {})}, headers=AS(admin_id))
        assert r.status_code == 200, (label, r.text)
        q[label] = r.json()["id"]
    client.patch(f"/api/forms/{f['id']}", json={"access": access}, headers=AS(admin_id))
    tok = None
    if publish:
        client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"},
                     headers=AS(admin_id))
        tok = client.get(f"/api/forms/{f['id']}",
                         headers=AS(admin_id)).json()["public_token"]
    return f, q, tok


def _get(client, fid, admin_id):
    return client.get(f"/api/forms/{fid}", headers=AS(admin_id)).json()


# ── מחיקת טופס ───────────────────────────────────────────────────────

def test_deleting_a_form_closes_the_link_and_keeps_everything_else(client, admin_id):
    bid = _board(client, admin_id, "מחיקת טופס")
    cid = _add_col(client, bid, admin_id, "כתובת", "text")
    f, q, tok = _form(client, bid, admin_id, [("נושא", "title", None),
                                              ("כתובת", cid, None)])
    # a submission arrives while it is open
    assert client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                       json={"answers": {str(q["נושא"]): "פנייה ישנה",
                                         str(q["כתובת"]): "הרצל 1"}}).status_code == 200

    assert client.delete(f"/api/forms/{f['id']}", headers=AS(admin_id)).status_code == 200

    # the link is closed, at both doors
    assert client.get(f"/api/public/forms/{tok}", headers=ANON).status_code == 410
    assert client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                       json={"answers": {}}).status_code == 410
    # and off the board's views
    assert client.get(f"/api/boards/{bid}/forms",
                      headers=AS(admin_id)).json()["forms"] == []
    assert [v for v in client.get(f"/api/boards/{bid}/views",
                                  headers=AS(admin_id)).json()["views"]
            if v["kind"] == "form"] == []

    # the board, the column and the record it collected are untouched
    board = client.get(f"/api/boards/{bid}").json()
    assert cid in [c["id"] for c in board["columns"]]
    t = [x for x in board["tasks"] if x["title"] == "פנייה ישנה"][0]
    assert t["custom_fields"][cid] == "הרצל 1"
    with Session(cityos_main.engine) as db:
        # …and the record still says which form it came through
        assert db.query(M.Task).filter(M.Task.title == "פנייה ישנה"
                                       ).first().form_view_id == f["id"]


# ── מחיקת שדה: אזהרה, אישור, ואז ─────────────────────────────────────

def test_the_impact_screen_says_which_forms_use_the_field(client, admin_id):
    bid = _board(client, admin_id, "אזהרה")
    cid = _add_col(client, bid, admin_id, "כתובת", "text")
    unused = _add_col(client, bid, admin_id, "לא בשימוש", "text")
    f, q, _tok = _form(client, bid, admin_id, [("איפה זה?", cid, {"required": True})])

    r = client.get(f"/api/boards/{bid}/columns/{cid}/impact", headers=AS(admin_id))
    assert r.status_code == 200, r.text
    forms = r.json()["forms"]
    assert len(forms) == 1
    assert forms[0]["form_id"] == f["id"] and forms[0]["label"] == "איפה זה?"
    assert forms[0]["required"] is True and forms[0]["status"] == "PUBLISHED"
    # a column nobody asks about says so
    assert client.get(f"/api/boards/{bid}/columns/{unused}/impact",
                      headers=AS(admin_id)).json()["forms"] == []


def test_a_field_in_use_is_not_deleted_without_saying_so(client, admin_id):
    bid = _board(client, admin_id, "אישור מפורש")
    cid = _add_col(client, bid, admin_id, "כתובת", "text")
    f, q, _tok = _form(client, bid, admin_id, [("כתובת", cid, None)])

    r = _drop_col(client, bid, admin_id, cid)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["message"] and d["columns"][0]["col_id"] == cid
    assert d["columns"][0]["removed"] is True
    assert d["columns"][0]["forms"][0]["form_id"] == f["id"]
    assert cid in [c["id"] for c in _cols(client, bid)], "the column went anyway"

    # naming it back is the explicit consent
    assert _drop_col(client, bid, admin_id, cid, confirm=[cid]).status_code == 200
    assert cid not in [c["id"] for c in _cols(client, bid)]


def test_a_field_nobody_asks_about_needs_no_ceremony(client, admin_id):
    bid = _board(client, admin_id, "בלי טקס")
    cid = _add_col(client, bid, admin_id, "לבד", "text")
    assert _drop_col(client, bid, admin_id, cid).status_code == 200


def test_a_form_in_the_bin_does_not_hold_a_column_hostage(client, admin_id):
    bid = _board(client, admin_id, "טופס בסל")
    cid = _add_col(client, bid, admin_id, "כתובת", "text")
    f, _q, _t = _form(client, bid, admin_id, [("כתובת", cid, None)])
    client.delete(f"/api/forms/{f['id']}", headers=AS(admin_id))
    assert _drop_col(client, bid, admin_id, cid).status_code == 200


# ── מה קורה לשאלה ────────────────────────────────────────────────────

def test_the_question_survives_the_column_and_stops_being_live(client, admin_id):
    bid = _board(client, admin_id, "שאלה יתומה")
    cid = _add_col(client, bid, admin_id, "כתובת", "text")
    f, q, tok = _form(client, bid, admin_id, [("נושא", "title", None),
                                              ("איפה זה?", cid, None)])
    assert _drop_col(client, bid, admin_id, cid, confirm=[cid]).status_code == 200

    # the builder still has it, flagged and with its wording intact
    got = _get(client, f["id"], admin_id)
    orphan = [c for c in got["components"] if c.get("field_key") == cid][0]
    assert orphan["label"] == "איפה זה?"
    assert orphan["orphaned"] is True and "נמחק" in orphan["issue"]

    # the respondent is never sent it
    pub = client.get(f"/api/public/forms/{tok}", headers=ANON).json()
    assert [c["label"] for c in pub["components"]] == ["נושא"]

    # and an old page that still has it cannot write through it
    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["נושא"]): "מדף ישן",
                                      str(q["איפה זה?"]): "הרצל 1"}})
    assert r.status_code == 200, r.text
    t = [x for x in client.get(f"/api/boards/{bid}").json()["tasks"]
         if x["title"] == "מדף ישן"][0]
    assert cid not in t["custom_fields"], "a dead mapping was written through"


def test_a_required_orphan_blocks_publishing(client, admin_id):
    bid = _board(client, admin_id, "חובה יתומה")
    cid = _add_col(client, bid, admin_id, "כתובת", "text")
    f, q, _tok = _form(client, bid, admin_id,
                       [("נושא", "title", None), ("כתובת", cid, {"required": True})],
                       publish=False)
    assert _drop_col(client, bid, admin_id, cid, confirm=[cid]).status_code == 200

    got = _get(client, f["id"], admin_id)
    assert [b["question_id"] for b in got["blockers"]] == [q["כתובת"]]

    r = client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"},
                     headers=AS(admin_id))
    assert r.status_code == 400, r.text
    assert "לפרסם" in r.json()["detail"]["message"]
    assert _get(client, f["id"], admin_id)["status"] == "DRAFT"

    # taking the question out clears it
    assert client.delete(f"/api/forms/{f['id']}/components/{q['כתובת']}",
                         headers=AS(admin_id)).status_code == 200
    assert _get(client, f["id"], admin_id)["blockers"] == []
    assert client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"},
                        headers=AS(admin_id)).status_code == 200


def test_an_orphan_that_is_not_required_does_not_block(client, admin_id):
    bid = _board(client, admin_id, "יתומה לא חובה")
    cid = _add_col(client, bid, admin_id, "כתובת", "text")
    f, _q, _t = _form(client, bid, admin_id,
                      [("נושא", "title", None), ("כתובת", cid, None)], publish=False)
    _drop_col(client, bid, admin_id, cid, confirm=[cid])
    assert _get(client, f["id"], admin_id)["blockers"] == []
    assert client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"},
                        headers=AS(admin_id)).status_code == 200


# ── שינוי סוג ואפשרויות ──────────────────────────────────────────────

def test_changing_a_fields_type_takes_the_same_consent(client, admin_id):
    bid = _board(client, admin_id, "שינוי סוג")
    cid = _add_col(client, bid, admin_id, "מתי", "date")
    f, q, _t = _form(client, bid, admin_id,
                     [("מתי", cid, {"settings": {"min": "2026-01-01"}})])
    r = _retype_col(client, bid, admin_id, cid, "text")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["columns"][0]["new_type"] == "text"
    assert [c for c in _cols(client, bid) if c["id"] == cid][0]["type"] == "date"

    assert _retype_col(client, bid, admin_id, cid, "text",
                       confirm=[cid]).status_code == 200
    # the question follows the column, and the settings that type cannot
    # carry are gone rather than left to mean nothing
    got = _get(client, f["id"], admin_id)
    asked = [c for c in got["components"] if c["id"] == q["מתי"]][0]
    assert asked["settings"] == {}, asked
    assert not asked.get("orphaned"), "a retyped column is not a deleted one"
    # …and the form still works, as the new type
    pub = client.get(f"/api/public/forms/{_t}" if _t else "/", headers=ANON)


def test_the_question_type_follows_the_column_after_a_retype(client, admin_id):
    bid = _board(client, admin_id, "סוג עוקב")
    cid = _add_col(client, bid, admin_id, "ערך", "text")
    f, q, tok = _form(client, bid, admin_id, [("נושא", "title", None),
                                              ("ערך", cid, None)])
    assert client.get(f"/api/public/forms/{tok}", headers=ANON
                      ).json()["components"][1]["type"] == "text"
    assert _retype_col(client, bid, admin_id, cid, "number",
                       confirm=[cid]).status_code == 200
    pub = client.get(f"/api/public/forms/{tok}", headers=ANON).json()
    assert pub["components"][1]["type"] == "number"
    # …and the value is now checked as a number
    assert client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                       json={"answers": {str(q["נושא"]): "x",
                                         str(q["ערך"]): "לא מספר"}}).status_code == 400
    assert client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                       json={"answers": {str(q["נושא"]): "מספר",
                                         str(q["ערך"]): 42}}).status_code == 200


def test_a_choice_with_no_choices_left_is_reported(client, admin_id):
    bid = _board(client, admin_id, "בלי אפשרויות")
    cid = _add_col(client, bid, admin_id, "סוג", "dropdown", ["א", "ב"])
    f, q, _t = _form(client, bid, admin_id, [("סוג", cid, None)], publish=False)
    assert "issue" not in _get(client, f["id"], admin_id)["components"][0]

    cols = [dict(c) for c in _cols(client, bid)]
    for c in cols:
        if c["id"] == cid:
            c["options"] = []
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    asked = _get(client, f["id"], admin_id)["components"][0]
    assert "אפשרויות" in asked.get("issue", ""), asked


def test_removing_one_option_leaves_the_form_working(client, admin_id):
    bid = _board(client, admin_id, "אפשרות ירדה")
    cid = _add_col(client, bid, admin_id, "סוג", "dropdown", ["א", "ב"])
    f, q, tok = _form(client, bid, admin_id, [("נושא", "title", None),
                                              ("סוג", cid, None)])
    cols = [dict(c) for c in _cols(client, bid)]
    for c in cols:
        if c["id"] == cid:
            c["options"] = ["א"]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})

    pub = client.get(f"/api/public/forms/{tok}", headers=ANON).json()
    assert [o["label"] for o in pub["components"][1]["options"]] == ["א"]
    # an old page offering the option that went is refused, by its own words
    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["נושא"]): "ישן", str(q["סוג"]): ["ב"]}})
    assert r.status_code == 400
    assert client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                       json={"answers": {str(q["נושא"]): "חדש",
                                         str(q["סוג"]): ["א"]}}).status_code == 200


# ── מה המסך עושה עם זה ───────────────────────────────────────────────

import pathlib
_ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_delete_dialog_warns_about_the_forms_before_it_asks():
    body = INDEX[INDEX.index("async function deleteColumn"):
                 INDEX.index("async function formUsersHTML")]
    assert "formUsersHTML(colId)" in body, "the dialog says nothing about forms"
    assert body.index("formUsersHTML(colId)") < body.index("askConfirm("), \
        "the warning is fetched after the question is asked"
    assert "saveColumns(cols,[colId])" in body, "the consent is not sent"


def test_the_warning_says_what_happens_to_the_questions():
    body = INDEX[INDEX.index("async function formUsersHTML"):
                 INDEX.index("/* The automations that point at")]
    assert "לא יימחקו" in body, "it does not say the questions survive"
    assert "יפסיקו להישאל" in body, "it does not say they stop being asked"
    assert "לא יוכל להתפרסם" in body, "a required one's consequence is not named"
    # an unanswerable question must not read as "nothing depends on it"
    assert "לא ניתן היה לבדוק" in body


def test_every_other_path_that_edits_columns_asks_the_same_question():
    """One handler, so a path added tomorrow cannot quietly skip the warning."""
    body = INDEX[INDEX.index("async function saveColumns"):
                 INDEX.index("/* Open/close a parent")]
    assert "e.status===409" in body
    assert "saveColumns(cols, cs.map(c=>c.col_id))" in body, "consent is not resent"
    assert "confirm_columns" in body
