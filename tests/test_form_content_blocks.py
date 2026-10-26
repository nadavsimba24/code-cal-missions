"""רכיבי תוכן — כותרת וטקסט, וסדר אחד לכל רכיבי הטופס.

A form is a list of two kinds of thing. A question is bound to a board field
and asks for a value. A heading and a text are bound to nothing and ask for
nothing: they are the form's own words, there so the person filling it in
knows what this section is and what is expected of them.

The distinction is held by the table, not by the code that writes to it — a
CHECK that a question names a field and that a content block does not — so
there is no path, through any endpoint or any future one, that produces a
heading pointing at a column or a question pointing at nothing.

And the order is ONE order. Questions and content blocks share a single
`position` sequence, because a heading that cannot sit between two questions
is not a heading, it is a title.
"""
from sqlalchemy.orm import Session
import pytest

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    r = client.post("/api/boards", json={"name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _col(client, bid, admin_id, title, ctype="text"):
    cols = [dict(c) for c in _cols(client, bid)]
    cols.append({"type": ctype, "title": title})
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    return [c["id"] for c in _cols(client, bid) if c["title"] == title][0]


def _form(client, bid, uid):
    r = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _add(client, fid, uid, **body):
    return client.post(f"/api/forms/{fid}/components", json=body, headers=AS(uid))


def _comps(client, fid, uid):
    return client.get(f"/api/forms/{fid}", headers=AS(uid)).json()["components"]


# ── הוספה, עריכה, מחיקה ──────────────────────────────────────────────

def test_a_heading_and_a_text_are_added_edited_and_removed(client, admin_id):
    bid = _board(client, admin_id, "רכיבי תוכן")
    f = _form(client, bid, admin_id)
    h = _add(client, f["id"], admin_id, kind="heading", content="פרטי הפונה")
    t = _add(client, f["id"], admin_id, kind="text", content="נחזור אליך תוך 5 ימים.")
    assert h.status_code == 200 and t.status_code == 200, (h.text, t.text)
    h, t = h.json(), t.json()
    assert h["kind"] == "heading" and h["content"] == "פרטי הפונה"
    assert t["kind"] == "text" and t["content"] == "נחזור אליך תוך 5 ימים."
    # a content block carries no question settings at all
    for c in (h, t):
        for k in ("field_key", "label", "required", "visible", "placeholder"):
            assert k not in c, f"{c['kind']} carries {k}"

    r = client.patch(f"/api/forms/{f['id']}/components/{h['id']}",
                     json={"content": "פרטי הפונה (חובה)"}, headers=AS(admin_id))
    assert r.status_code == 200 and r.json()["content"] == "פרטי הפונה (חובה)"

    assert client.delete(f"/api/forms/{f['id']}/components/{t['id']}",
                         headers=AS(admin_id)).status_code == 200
    left = _comps(client, f["id"], admin_id)
    assert [c["id"] for c in left] == [h["id"]]
    assert left[0]["position"] == 0, "the positions did not close up"


def test_an_empty_heading_is_allowed_because_it_is_about_to_be_typed_into(client, admin_id):
    bid = _board(client, admin_id, "ריק")
    f = _form(client, bid, admin_id)
    r = _add(client, f["id"], admin_id, kind="heading")
    assert r.status_code == 200 and r.json()["content"] == ""


# ── אין קישור לשדה, לא בשום דרך ──────────────────────────────────────

def test_a_content_block_cannot_be_bound_to_a_field(client, admin_id):
    bid = _board(client, admin_id, "בלי שדה")
    cid = _col(client, bid, admin_id, "כתובת")
    f = _form(client, bid, admin_id)
    # asking for one is not an error — it is ignored, the way the shape says
    h = _add(client, f["id"], admin_id, kind="heading", content="כותרת",
             field_key=cid, required=True).json()
    assert "field_key" not in h
    with Session(cityos_main.engine) as db:
        row = db.query(M.FormComponent).filter(M.FormComponent.id == h["id"]).first()
        assert row.field_key is None
        assert row.required is False
    # …and the field is still free for a question to ask about
    assert _add(client, f["id"], admin_id, kind="question",
                field_key=cid, label="כתובת").status_code == 200


def test_the_table_itself_refuses_a_bound_content_block(client, admin_id):
    """Not a rule the writers remember — a CHECK the database enforces."""
    bid = _board(client, admin_id, "אילוץ")
    f = _form(client, bid, admin_id)
    h = _add(client, f["id"], admin_id, kind="heading", content="כותרת").json()
    with Session(cityos_main.engine) as db:
        row = db.query(M.FormComponent).filter(M.FormComponent.id == h["id"]).first()
        row.field_key = "col_anything"
        with pytest.raises(Exception):
            db.commit()
        db.rollback()


def test_content_blocks_create_no_columns_on_the_board(client, admin_id):
    bid = _board(client, admin_id, "בלי עמודות")
    before = [c["id"] for c in _cols(client, bid)]
    f = _form(client, bid, admin_id)
    for i in range(3):
        _add(client, f["id"], admin_id, kind="heading", content=f"כותרת {i}")
        _add(client, f["id"], admin_id, kind="text", content=f"טקסט {i}")
    assert [c["id"] for c in _cols(client, bid)] == before
    assert len(_comps(client, f["id"], admin_id)) == 6


# ── לא תשובה, ולא ערך ברשומה ─────────────────────────────────────────

def test_a_content_block_is_not_something_to_answer(client, admin_id):
    """What the respondent is sent says which blocks are questions and which
    are words. A content block carries no type, no field and no options —
    there is nothing on it for an answer to attach to."""
    bid = _board(client, admin_id, "לא תשובה")
    cid = _col(client, bid, admin_id, "כתובת")
    f = _form(client, bid, admin_id)
    client.patch(f"/api/forms/{f['id']}", json={"components": [
        {"kind": "heading", "content": "פרטים"},
        {"kind": "question", "field_key": cid, "label": "כתובת"},
        {"kind": "text", "content": "לא נשתמש בכתובת לשום דבר אחר."},
    ]}, headers=AS(admin_id))
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    kinds = [c["kind"] for c in pub["components"]]
    assert kinds == ["heading", "question", "text"]
    for c in pub["components"]:
        if c["kind"] == "question":
            continue
        # its words and how they are set — never a field, a type or options,
        # which is what an answer would attach to
        assert set(c) == {"id", "kind", "content", "settings"}, c
        assert not {"field_key", "type", "options", "required"} & set(c)
    # the one answerable block is the only one naming a type
    assert [c for c in pub["components"] if "type" in c][0]["label"] == "כתובת"


# ── סדר אחד לשניהם ───────────────────────────────────────────────────

def test_questions_and_content_share_one_order(client, admin_id):
    bid = _board(client, admin_id, "סדר מעורב")
    a = _col(client, bid, admin_id, "שם")
    b = _col(client, bid, admin_id, "טלפון", "phone")
    f = _form(client, bid, admin_id)
    r = client.patch(f"/api/forms/{f['id']}", json={"components": [
        {"kind": "heading", "content": "מי את"},
        {"kind": "question", "field_key": a, "label": "שם מלא"},
        {"kind": "text", "content": "נשתמש בטלפון רק אם נצטרך פרטים."},
        {"kind": "question", "field_key": b, "label": "טלפון"},
    ]}, headers=AS(admin_id))
    assert r.status_code == 200, r.text
    got = _comps(client, f["id"], admin_id)
    assert [c["kind"] for c in got] == ["heading", "question", "text", "question"]
    assert [c["position"] for c in got] == [0, 1, 2, 3]

    # a drag that moves the trailing question to the top — one list, one order
    ids = [c["id"] for c in got]
    r = client.put(f"/api/forms/{f['id']}/components/order",
                   json={"order": [ids[3], ids[0], ids[1], ids[2]]}, headers=AS(admin_id))
    assert r.status_code == 200, r.text
    after = _comps(client, f["id"], admin_id)
    assert [c["id"] for c in after] == [ids[3], ids[0], ids[1], ids[2]]
    assert [c["kind"] for c in after] == ["question", "heading", "question", "text"]
    assert [c["position"] for c in after] == [0, 1, 2, 3]

    # …and it is the order a reload gives back
    again = _comps(client, f["id"], admin_id)
    assert [c["id"] for c in again] == [ids[3], ids[0], ids[1], ids[2]]
    # …and the respondent reads it in that order too
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    assert [c["kind"] for c in pub["components"]] == ["question", "heading", "question", "text"]
    # the board's own columns never moved
    assert [c["id"] for c in _cols(client, bid)][-2:] == [a, b]


def test_a_content_block_can_be_inserted_between_two_questions(client, admin_id):
    bid = _board(client, admin_id, "הכנסה באמצע")
    a = _col(client, bid, admin_id, "א")
    b = _col(client, bid, admin_id, "ב")
    f = _form(client, bid, admin_id)
    q1 = _add(client, f["id"], admin_id, kind="question", field_key=a, label="א").json()
    q2 = _add(client, f["id"], admin_id, kind="question", field_key=b, label="ב").json()
    mid = _add(client, f["id"], admin_id, kind="heading", content="בין לבין",
               position=1).json()
    got = _comps(client, f["id"], admin_id)
    assert [c["id"] for c in got] == [q1["id"], mid["id"], q2["id"]]
    assert [c["position"] for c in got] == [0, 1, 2]


def test_a_question_turned_into_a_heading_gives_its_field_back(client, admin_id):
    bid = _board(client, admin_id, "המרה")
    cid = _col(client, bid, admin_id, "כתובת")
    f = _form(client, bid, admin_id)
    q = _add(client, f["id"], admin_id, kind="question", field_key=cid,
             label="כתובת", required=True).json()
    r = client.patch(f"/api/forms/{f['id']}/components/{q['id']}",
                     json={"kind": "heading", "content": "כותרת"}, headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert "field_key" not in r.json() and r.json()["content"] == "כותרת"
    with Session(cityos_main.engine) as db:
        row = db.query(M.FormComponent).filter(M.FormComponent.id == q["id"]).first()
        assert row.field_key is None and row.required is False
    # the field is free, and the board never noticed any of it
    assert _add(client, f["id"], admin_id, kind="question", field_key=cid,
                label="כתובת שוב").status_code == 200
    assert cid in [c["id"] for c in _cols(client, bid)]
