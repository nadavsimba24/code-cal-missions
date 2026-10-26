"""שאלות בטופס — שני מסלולי הוספה, עשרת הסוגים, ומה שנשאר שייך ללוח.

A question is the form's wording of a board field. Two things follow from that
one sentence and are tested here rather than assumed:

  the TYPE is the column's, because the type is the data contract — a question
  that carried a type of its own could write a value the cell cannot read;

  everything else is the form's — the label, the help, the placeholder, whether
  it is required, whether it is shown, and where it sits in the list. None of
  those is visible from the board, and changing one on this form says nothing
  about the next form on the same board.

The second route in — making the field from the editor — is one request and
one transaction on purpose. A browser that made the column and then failed to
make the question would leave a column nobody asked for; one that tried the
other order would be refused for naming a field that does not exist yet.
"""
from sqlalchemy.orm import Session

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}

# The ten the specification names, and the board column each one is.
TEN = [("Text", "text", None), ("Long Text", "long_text", None),
       ("Number", "number", None), ("Single Select", "status", ["אדום", "ירוק"]),
       ("Multi Select", "dropdown", ["א", "ב"]), ("Boolean", "checkbox", None),
       ("Date", "date", None), ("Phone", "phone", None),
       ("Email", "email", None), ("File", "files", None)]


def _board(client, admin_id, name):
    r = client.post("/api/boards", json={"name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_col(client, bid, admin_id, title, ctype, options=None):
    cols = [dict(c) for c in _cols(client, bid)]
    col = {"type": ctype, "title": title}
    if options is not None:
        col["options"] = options
    cols.append(col)
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    return [c["id"] for c in _cols(client, bid) if c["title"] == title][0]


def _form(client, bid, uid, name=None):
    r = client.post(f"/api/boards/{bid}/forms",
                    json={"name": name} if name else {}, headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _comps(client, fid, uid):
    return client.get(f"/api/forms/{fid}", headers=AS(uid)).json()["components"]


# ── מסלול 1: שדה קיים בלוח ────────────────────────────────────────────

def test_all_ten_types_can_be_asked_about(client, admin_id):
    """Every type on the list, as a column, as a question, and back out."""
    bid = _board(client, admin_id, "עשרה סוגים")
    f = _form(client, bid, admin_id)
    made = {}
    for label, ctype, options in TEN:
        cid = _add_col(client, bid, admin_id, label, ctype, options)
        r = client.post(f"/api/forms/{f['id']}/components",
                        json={"kind": "question", "field_key": cid, "label": label},
                        headers=AS(admin_id))
        assert r.status_code == 200, f"{label} ({ctype}): {r.text}"
        made[ctype] = r.json()["id"]
    assert len(made) == 10
    assert len(_comps(client, f["id"], admin_id)) == 10

    # and the respondent is told the type, so a browser can draw the right input
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    types = {c["type"] for c in pub["components"]}
    assert types == {t for _l, t, _o in TEN}, types


def test_the_question_type_is_the_columns_and_not_its_own(client, admin_id):
    bid = _board(client, admin_id, "סוג נגזר")
    cid = _add_col(client, admin_id and bid, admin_id, "מתי", "date")
    f = _form(client, bid, admin_id)
    client.post(f"/api/forms/{f['id']}/components",
                json={"kind": "question", "field_key": cid, "label": "תאריך האירוע",
                      "type": "text"},            # ignored: not a question's to say
                headers=AS(admin_id))
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    assert pub["components"][0]["type"] == "date"


def test_choices_come_from_the_board_field(client, admin_id):
    bid = _board(client, admin_id, "אפשרויות")
    single = _add_col(client, bid, admin_id, "חומרה", "status", ["נמוכה", "גבוהה"])
    multi = _add_col(client, bid, admin_id, "נושאים", "dropdown", ["תאורה", "ניקיון"])
    f = _form(client, bid, admin_id)
    for cid, label in ((single, "חומרה"), (multi, "נושאים")):
        client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": cid, "label": label},
                    headers=AS(admin_id))
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    by = {c["label"]: c for c in pub["components"]}
    assert [o["label"] for o in by["חומרה"]["options"]] == ["נמוכה", "גבוהה"]
    assert [o["label"] for o in by["נושאים"]["options"]] == ["תאורה", "ניקיון"]

    # renaming an option on the BOARD moves the form's answer with it
    cols = [dict(c) for c in _cols(client, bid)]
    for c in cols:
        if c["id"] == multi:
            c["options"] = ["תאורת רחוב", "ניקיון"]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    by = {c["label"]: c for c in pub["components"]}
    assert [o["label"] for o in by["נושאים"]["options"]] == ["תאורת רחוב", "ניקיון"]


# ── מסלול 2: שדה חדש מתוך העורך ──────────────────────────────────────

def test_a_field_made_in_the_editor_appears_on_the_board(client, admin_id):
    bid = _board(client, admin_id, "שדה מהעורך")
    f = _form(client, bid, admin_id)
    before = {c["id"] for c in _cols(client, bid)}
    r = client.post(f"/api/forms/{f['id']}/fields",
                    json={"type": "phone", "title": "טלפון ליצירת קשר",
                          "label": "באיזה מספר נחזור אליך?", "required": True},
                    headers=AS(admin_id))
    assert r.status_code == 200, r.text
    col, comp = r.json()["column"], r.json()["component"]

    after = {c["id"]: c for c in _cols(client, bid)}
    assert col["id"] in after and col["id"] not in before, "the column is not on the board"
    assert after[col["id"]]["type"] == "phone"
    assert after[col["id"]]["title"] == "טלפון ליצירת קשר"
    # the question is bound to it, with the form's own wording
    assert comp["field_key"] == col["id"]
    assert comp["label"] == "באיזה מספר נחזור אליך?"
    assert comp["required"] is True
    assert [c["field_key"] for c in _comps(client, f["id"], admin_id)] == [col["id"]]


def test_a_select_field_made_in_the_editor_carries_its_options(client, admin_id):
    bid = _board(client, admin_id, "בחירה מהעורך")
    f = _form(client, bid, admin_id)
    r = client.post(f"/api/forms/{f['id']}/fields",
                    json={"type": "status", "title": "סוג פנייה",
                          "options": ["תאורה", "ניקיון", "תאורה"]},   # the repeat drops
                    headers=AS(admin_id))
    assert r.status_code == 200, r.text
    col = [c for c in _cols(client, bid) if c["id"] == r.json()["column"]["id"]][0]
    assert [o["label"] for o in col["options"]] == ["תאורה", "ניקיון"]
    assert all(o.get("id") for o in col["options"]), "an option with no stable id"
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    assert [o["label"] for o in pub["components"][0]["options"]] == ["תאורה", "ניקיון"]


def test_every_one_of_the_ten_can_be_made_from_the_editor(client, admin_id):
    bid = _board(client, admin_id, "עשרה מהעורך")
    f = _form(client, bid, admin_id)
    for label, ctype, options in TEN:
        body = {"type": ctype, "title": "שדה " + label}
        if options:
            body["options"] = options
        r = client.post(f"/api/forms/{f['id']}/fields", json=body, headers=AS(admin_id))
        assert r.status_code == 200, f"{label} ({ctype}): {r.text}"
    assert len(_comps(client, f["id"], admin_id)) == 10
    assert len([c for c in _cols(client, bid) if c["id"].startswith("col_")]) == 10


def test_a_refused_question_leaves_no_column_behind(client, admin_id):
    """The whole point of doing both in one transaction."""
    bid = _board(client, admin_id, "עקביות")
    f = _form(client, bid, admin_id)
    before = {c["id"] for c in _cols(client, bid)}
    # hidden and required at once — refused by the same rule an ordinary
    # question is refused by, after the column has already been built
    r = client.post(f"/api/forms/{f['id']}/fields",
                    json={"type": "text", "title": "לא ייווצר",
                          "required": True, "visible": False},
                    headers=AS(admin_id))
    assert r.status_code == 400, r.text
    assert {c["id"] for c in _cols(client, bid)} == before, "a column survived a refusal"
    assert _comps(client, f["id"], admin_id) == []
    assert all(c["title"] != "לא ייווצר" for c in _cols(client, bid))


def test_the_field_route_refuses_what_it_should(client, admin_id, member_id):
    bid = _board(client, admin_id, "סירובים")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    f = _form(client, bid, admin_id)
    bad = [
        ({"type": "connect", "title": "לא"}, "a type a form cannot ask about"),
        ({"type": "text", "title": "   "}, "a field with no name"),
        ({"type": "dropdown", "title": "ריק", "options": []}, "a choice with no choices"),
        ({"type": "status", "title": "ריק2"}, "a vocabulary that was never given"),
    ]
    for body, why in bad:
        assert client.post(f"/api/forms/{f['id']}/fields", json=body,
                           headers=AS(admin_id)).status_code == 400, why
    # a name the board already uses
    client.post(f"/api/forms/{f['id']}/fields", json={"type": "text", "title": "כתובת"},
                headers=AS(admin_id))
    assert client.post(f"/api/forms/{f['id']}/fields",
                       json={"type": "text", "title": "כתובת"},
                       headers=AS(admin_id)).status_code == 400
    # adding a COLUMN is the admin's; adding a question about one is not
    r = client.post(f"/api/forms/{f['id']}/fields",
                    json={"type": "text", "title": "של עורך"}, headers=AS(member_id))
    assert r.status_code == 403 and "מנהל הלוח" in r.json()["detail"]
    existing = [c["id"] for c in _cols(client, bid) if c["title"] == "כתובת"][0]
    assert client.delete(f"/api/forms/{f['id']}/components/"
                         f"{_comps(client, f['id'], admin_id)[0]['id']}",
                         headers=AS(admin_id)).status_code == 200
    assert client.post(f"/api/forms/{f['id']}/components",
                       json={"kind": "question", "field_key": existing, "label": "כתובת"},
                       headers=AS(member_id)).status_code == 200


# ── מה שייך לטופס ומה שייך ללוח ──────────────────────────────────────

def test_editing_the_question_does_not_touch_the_board(client, admin_id):
    bid = _board(client, admin_id, "גבול")
    cid = _add_col(client, bid, admin_id, "כתובת הנכס", "text")
    f = _form(client, bid, admin_id)
    c = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": cid, "label": "כתובת הנכס"},
                    headers=AS(admin_id)).json()
    r = client.patch(f"/api/forms/{f['id']}/components/{c['id']}",
                     json={"label": "איפה זה?", "description": "רחוב ומספר",
                           "placeholder": "הרצל 1", "required": True},
                     headers=AS(admin_id))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["label"] == "איפה זה?" and got["description"] == "רחוב ומספר"
    assert got["placeholder"] == "הרצל 1" and got["required"] is True
    # the column kept its own name, and its own everything
    col = [x for x in _cols(client, bid) if x["id"] == cid][0]
    assert col["title"] == "כתובת הנכס", "renaming the question renamed the column"
    assert col["type"] == "text"
    # required is the FORM's setting — a board column has no such thing
    assert "required" not in col


def test_removing_a_question_keeps_the_field_and_its_values(client, admin_id):
    bid = _board(client, admin_id, "הסרה")
    cid = _add_col(client, bid, admin_id, "כתובת", "text")
    item = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "custom_fields": {cid: "הרצל 1"},
                                           "user_id": admin_id}).json()["id"]
    f = _form(client, bid, admin_id)
    c = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": cid, "label": "כתובת"},
                    headers=AS(admin_id)).json()
    assert client.delete(f"/api/forms/{f['id']}/components/{c['id']}",
                         headers=AS(admin_id)).status_code == 200
    board = client.get(f"/api/boards/{bid}").json()
    assert cid in [x["id"] for x in board["columns"]], "the column went with the question"
    t = [x for x in board["tasks"] if x["id"] == item][0]
    assert t["custom_fields"][cid] == "הרצל 1"
    # …and the field is free to be asked about again
    assert client.post(f"/api/forms/{f['id']}/components",
                       json={"kind": "question", "field_key": cid, "label": "שוב"},
                       headers=AS(admin_id)).status_code == 200


def test_reordering_questions_leaves_the_board_columns_alone(client, admin_id):
    bid = _board(client, admin_id, "סדר")
    a = _add_col(client, bid, admin_id, "ראשונה", "text")
    b = _add_col(client, bid, admin_id, "שנייה", "text")
    before = [c["id"] for c in _cols(client, bid)]
    f = _form(client, bid, admin_id)
    ids = [client.post(f"/api/forms/{f['id']}/components",
                       json={"kind": "question", "field_key": k, "label": k},
                       headers=AS(admin_id)).json()["id"] for k in (a, b)]
    r = client.put(f"/api/forms/{f['id']}/components/order",
                   json={"order": [ids[1], ids[0]]}, headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert [c["field_key"] for c in _comps(client, f["id"], admin_id)] == [b, a]
    assert [c["id"] for c in _cols(client, bid)] == before, "the board's columns moved"


def test_one_forms_wording_order_and_rules_say_nothing_about_another(client, admin_id):
    bid = _board(client, admin_id, "שני טפסים")
    a = _add_col(client, bid, admin_id, "כתובת", "text")
    b = _add_col(client, bid, admin_id, "טלפון", "phone")
    f1, f2 = _form(client, bid, admin_id, "א"), _form(client, bid, admin_id, "ב")
    ids = {}
    for f in (f1, f2):
        ids[f["id"]] = [client.post(f"/api/forms/{f['id']}/components",
                                    json={"kind": "question", "field_key": k, "label": t},
                                    headers=AS(admin_id)).json()["id"]
                        for k, t in ((a, "כתובת"), (b, "טלפון"))]
    # everything the form owns, changed on the first one only
    first = ids[f1["id"]]
    client.patch(f"/api/forms/{f1['id']}/components/{first[0]}",
                 json={"label": "איפה?", "required": True, "placeholder": "הרצל 1"},
                 headers=AS(admin_id))
    client.patch(f"/api/forms/{f1['id']}/components/{first[1]}",
                 json={"visible": False}, headers=AS(admin_id))
    client.put(f"/api/forms/{f1['id']}/components/order",
               json={"order": [first[1], first[0]]}, headers=AS(admin_id))

    second = _comps(client, f2["id"], admin_id)
    assert [c["field_key"] for c in second] == [a, b], "the other form's order moved"
    assert second[0]["label"] == "כתובת" and second[0]["required"] is False
    assert second[0]["placeholder"] == "" and second[1]["visible"] is True
    # and the board is untouched by any of it
    cols = {c["id"]: c for c in _cols(client, bid)}
    assert cols[a]["title"] == "כתובת" and cols[b]["title"] == "טלפון"
