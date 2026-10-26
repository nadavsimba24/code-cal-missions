"""מחזור החיים של הטופס, והשער שאי אפשר לעקוף.

DRAFT → PUBLISHED → DISABLED, and back. Three states and one address: the
public token is minted at the FIRST publish and kept, so a link somebody sent
out last month is the link that works when the form is switched on again.

The gate is one function — _public_form_or_refuse — and every public door
goes through it. That is not tidiness: it is the whole of "בדיקת סטטוס וגישה
מתבצעת גם בזמן ההגשה, ולא רק בפתיחת העמוד". Between opening a form and
pressing send there is a person typing, and in that gap the form can be
disabled, unpublished, deleted or switched to AUTHENTICATED. A respondent who
had it on screen is refused at the send, by the same check that let them in.

And nothing in the link says what is behind it: no board id, no view id, no
column ids. Holding the token is permission to fill in a form, and that is
all it is permission for.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}
ANON = {"X-CityOS-User": ""}


def _problem(r, label=None):
    """The validation problems a 400 carries, flattened for assertion.

    The detail is a dict now — a message and a list of problems keyed by the
    question each one belongs to, so a page can put the words beside the
    field rather than in a paragraph at the top.
    """
    d = r.json()["detail"]
    if isinstance(d, str):
        return d
    out = " | ".join(f"{e.get('label')}: {e.get('message')}" for e in d.get("errors", []))
    return (d.get("message", "") + " | " + out) if out else d.get("message", "")


def _board(client, admin_id, name):
    r = client.post("/api/boards", json={"name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _form(client, bid, uid):
    r = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _set(client, fid, uid, **body):
    return client.patch(f"/api/forms/{fid}", json=body, headers=AS(uid))


def _get(client, fid, uid):
    return client.get(f"/api/forms/{fid}", headers=AS(uid)).json()


def _ask(client, fid, uid, field="title", label="נושא", **extra):
    r = client.post(f"/api/forms/{fid}/components",
                    json={"kind": "question", "field_key": field, "label": label, **extra},
                    headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _titles(client, bid):
    """A new board ships with three demo items, so every count here is a delta."""
    return [t["title"] for t in client.get(f"/api/boards/{bid}").json()["tasks"]]


def _publish(client, fid, uid):
    assert _set(client, fid, uid, status="PUBLISHED").status_code == 200
    return _get(client, fid, uid)["public_token"]


# ── המזהה הציבורי ────────────────────────────────────────────────────

def test_the_address_is_minted_at_the_first_publish_and_then_kept(client, admin_id):
    bid = _board(client, admin_id, "כתובת")
    f = _form(client, bid, admin_id)
    assert f["public_token"] is None and f["public_url"] is None

    tok = _publish(client, f["id"], admin_id)
    assert tok and len(tok) == 32
    assert _get(client, f["id"], admin_id)["public_url"] == "/forms/" + tok

    # off and on again is the same form coming back, at the same address
    assert _set(client, f["id"], admin_id, status="DISABLED").status_code == 200
    assert _get(client, f["id"], admin_id)["public_token"] == tok
    assert _set(client, f["id"], admin_id, status="PUBLISHED").status_code == 200
    assert _get(client, f["id"], admin_id)["public_token"] == tok


def test_the_link_says_nothing_about_what_is_behind_it(client, admin_id):
    bid = _board(client, admin_id, "לא חושף")
    f = _form(client, bid, admin_id)
    _ask(client, f["id"], admin_id)
    tok = _publish(client, f["id"], admin_id)
    url = _get(client, f["id"], admin_id)["public_url"]
    for leak in (str(bid), str(f["id"]), str(f["view_id"])):
        assert leak not in url.replace(tok, ""), f"the address carries {leak}"
    # …and neither does what the address answers with
    pub = client.get(f"/api/public/forms/{tok}", headers=ANON).json()
    blob = __import__("json").dumps(pub, ensure_ascii=False)
    for leak in ("board_id", "view_id", "field_key", "target_group_id"):
        assert leak not in blob, leak


# ── השער: מצב ──────────────────────────────────────────────────────

def test_only_a_published_form_answers_at_all(client, admin_id):
    bid = _board(client, admin_id, "מצבים")
    f = _form(client, bid, admin_id)
    _ask(client, f["id"], admin_id)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)
    body = {"answers": {}}

    # published: open and sending
    assert client.get(f"/api/public/forms/{tok}", headers=ANON).status_code == 200
    assert client.post(f"/api/public/forms/{tok}/submit",
                       json=body, headers=ANON).status_code == 200

    # disabled: gone, and said to be gone
    assert _set(client, f["id"], admin_id, status="DISABLED").status_code == 200
    assert client.get(f"/api/public/forms/{tok}", headers=ANON).status_code == 410
    assert client.post(f"/api/public/forms/{tok}/submit",
                       json=body, headers=ANON).status_code == 410

    # back to a draft: it has an address and nothing at it
    assert _set(client, f["id"], admin_id, status="DRAFT").status_code == 200
    assert client.get(f"/api/public/forms/{tok}", headers=ANON).status_code == 404
    assert client.post(f"/api/public/forms/{tok}/submit",
                       json=body, headers=ANON).status_code == 404

    # a token nobody minted is not a form
    assert client.get("/api/public/forms/" + "f" * 32, headers=ANON).status_code == 404


def test_a_respondent_holding_the_page_cannot_send_after_it_is_disabled(client, admin_id):
    """תנאי קבלה: the page was open; the send is still refused."""
    bid = _board(client, admin_id, "נסגר באמצע")
    f = _form(client, bid, admin_id)
    _ask(client, f["id"], admin_id)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)

    # the respondent opens it and starts typing
    opened = client.get(f"/api/public/forms/{tok}", headers=ANON)
    assert opened.status_code == 200
    qid = opened.json()["components"][0]["id"]

    # …and the form is closed while they are
    assert _set(client, f["id"], admin_id, status="DISABLED").status_code == 200

    r = client.post(f"/api/public/forms/{tok}/submit",
                    json={"answers": {str(qid): "פנייה"}}, headers=ANON)
    assert r.status_code == 410, r.text
    assert "נסגר" in r.json()["detail"]
    # and nothing landed on the board
    assert "פנייה" not in _titles(client, bid)


def test_a_deleted_form_stops_answering_too(client, admin_id):
    bid = _board(client, admin_id, "נמחק")
    f = _form(client, bid, admin_id)
    _ask(client, f["id"], admin_id)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)
    assert client.delete(f"/api/forms/{f['id']}", headers=AS(admin_id)).status_code == 200
    assert client.get(f"/api/public/forms/{tok}", headers=ANON).status_code == 410
    assert client.post(f"/api/public/forms/{tok}/submit",
                       json={"answers": {}}, headers=ANON).status_code == 410


# ── השער: גישה ─────────────────────────────────────────────────────

def test_an_authenticated_form_refuses_somebody_with_no_identity(client, admin_id):
    bid = _board(client, admin_id, "מחוברים בלבד")
    f = _form(client, bid, admin_id)
    _ask(client, f["id"], admin_id)
    tok = _publish(client, f["id"], admin_id)
    assert _get(client, f["id"], admin_id)["access"] == "AUTHENTICATED"

    assert client.get(f"/api/public/forms/{tok}", headers=ANON).status_code == 401
    assert client.post(f"/api/public/forms/{tok}/submit",
                       json={"answers": {}}, headers=ANON).status_code == 401
    # an account the system knows gets in, whatever board it is on
    assert client.get(f"/api/public/forms/{tok}", headers=AS(admin_id)).status_code == 200


def test_switching_to_authenticated_locks_out_a_page_already_open(client, admin_id):
    bid = _board(client, admin_id, "השתנה באמצע")
    f = _form(client, bid, admin_id)
    _ask(client, f["id"], admin_id)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)
    opened = client.get(f"/api/public/forms/{tok}", headers=ANON)
    assert opened.status_code == 200
    qid = opened.json()["components"][0]["id"]

    assert _set(client, f["id"], admin_id, access="AUTHENTICATED").status_code == 200
    r = client.post(f"/api/public/forms/{tok}/submit",
                    json={"answers": {str(qid): "פנייה"}}, headers=ANON)
    assert r.status_code == 401, r.text


def test_a_public_link_form_takes_anybody_and_records_who_it_can(client, admin_id,
                                                                 member_id):
    bid = _board(client, admin_id, "קישור ציבורי")
    f = _form(client, bid, admin_id)
    q = _ask(client, f["id"], admin_id)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)

    assert client.post(f"/api/public/forms/{tok}/submit",
                       json={"answers": {str(q["id"]): "מאלמוני"}},
                       headers=ANON).status_code == 200
    assert client.post(f"/api/public/forms/{tok}/submit",
                       json={"answers": {str(q["id"]): "ממזוהה"}},
                       headers=AS(member_id)).status_code == 200

    assert {"מאלמוני", "ממזוהה"} <= set(_titles(client, bid))
    with Session(cityos_main.engine) as db:
        rows = {t.title: t for t in db.query(M.Task)
                .filter(M.Task.board_id == bid, M.Task.form_view_id == f["id"]).all()}
        assert set(rows) == {"מאלמוני", "ממזוהה"}
        assert rows["מאלמוני"].created_by is None
        assert rows["ממזוהה"].created_by == member_id
        # both say which form they came through
        assert all(t.form_view_id == f["id"] for t in rows.values())


def test_filling_a_form_in_grants_nothing_on_the_board(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לא מעניק גישה")
    f = _form(client, bid, admin_id)
    q = _ask(client, f["id"], admin_id)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)
    assert client.post(f"/api/public/forms/{tok}/submit",
                       json={"answers": {str(q["id"]): "פנייה"}},
                       headers=AS(guinea_id)).status_code == 200
    # still not on the board, and still cannot see it
    with Session(cityos_main.engine) as db:
        assert db.query(M.BoardMember).filter(
            M.BoardMember.board_id == bid, M.BoardMember.user_id == guinea_id).first() is None
        assert cityos_main._board_role(db, bid, guinea_id) is None
    assert client.get(f"/api/boards/{bid}", headers=AS(guinea_id)).status_code == 403


# ── מי רשאי לשנות מצב וגישה ─────────────────────────────────────────

def test_status_and_access_take_board_admin(client, admin_id, member_id):
    bid = _board(client, admin_id, "הרשאת ניהול")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    f = _form(client, bid, admin_id)
    for body in ({"status": "PUBLISHED"}, {"access": "PUBLIC_LINK"}):
        r = _set(client, f["id"], member_id, **body)
        assert r.status_code == 403, body
        assert "מנהל הלוח" in r.json()["detail"]
    assert _get(client, f["id"], admin_id)["status"] == "DRAFT"
    assert _get(client, f["id"], admin_id)["public_token"] is None
    # an editor's own edits are unaffected
    assert _set(client, f["id"], member_id, display_title="שלום").status_code == 200


def test_the_checks_cannot_be_walked_around_through_the_api(client, admin_id, guinea_id):
    """No second door: the management route still needs the board, the public
    route still needs the gate, and neither accepts the other's argument."""
    bid = _board(client, admin_id, "אין דלת אחורית")
    f = _form(client, bid, admin_id)
    q = _ask(client, f["id"], admin_id)
    tok = _publish(client, f["id"], admin_id)

    # the management endpoints are not reachable by a stranger holding the token
    assert client.get(f"/api/forms/{f['id']}", headers=AS(guinea_id)).status_code == 403
    assert _set(client, f["id"], guinea_id, status="DISABLED").status_code == 403
    # the token is not a form id and the form id is not a token
    assert client.get(f"/api/public/forms/{f['id']}", headers=ANON).status_code == 404
    assert client.get(f"/api/forms/{tok}", headers=AS(admin_id)).status_code in (404, 422)
    # posting the item straight at the board is the IDOR create_task closed
    assert client.post("/api/tasks", json={"board_id": bid, "title": "עוקף"},
                       headers=AS(guinea_id)).status_code == 403
    # and the public submit does not take a board id of its own
    r = client.post(f"/api/public/forms/{tok}/submit",
                    json={"answers": {str(q["id"]): "x"}, "board_id": 1,
                          "created_by": admin_id}, headers=AS(admin_id))
    assert r.status_code == 200
    with Session(cityos_main.engine) as db:
        t = db.query(M.Task).filter(M.Task.title == "x").first()
        assert t.board_id == bid, "the submission chose its own board"


# ── השבתה שומרת הכול ────────────────────────────────────────────────

def test_disabling_keeps_the_form_and_everything_it_collected(client, admin_id):
    bid = _board(client, admin_id, "השבתה")
    f = _form(client, bid, admin_id)
    q = _ask(client, f["id"], admin_id)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK", display_title="דברו איתנו",
         theme_color="#00c875", submit_label="שלחו")
    tok = _publish(client, f["id"], admin_id)
    client.post(f"/api/public/forms/{tok}/submit",
                json={"answers": {str(q["id"]): "פנייה שהגיעה"}}, headers=ANON)

    assert _set(client, f["id"], admin_id, status="DISABLED").status_code == 200
    after = _get(client, f["id"], admin_id)
    assert after["status"] == "DISABLED"
    assert after["access"] == "PUBLIC_LINK"
    assert after["public_token"] == tok
    assert after["design"]["display_title"] == "דברו איתנו"
    assert after["design"]["theme_color"] == "#00c875"
    assert after["design"]["submit_label"] == "שלחו"
    assert [c["id"] for c in after["components"]] == [q["id"]]
    # the record it collected is a record of the board now, and stays
    assert "פנייה שהגיעה" in [t["title"] for t in
                              client.get(f"/api/boards/{bid}").json()["tasks"]]


def test_publishing_stamps_who_and_when(client, admin_id):
    bid = _board(client, admin_id, "חותמת")
    f = _form(client, bid, admin_id)
    _publish(client, f["id"], admin_id)
    got = _get(client, f["id"], admin_id)
    assert got["published_at"] and got["published_by"] == admin_id


# ── הגשה: מה שהשער מכניס ────────────────────────────────────────────

def test_a_submission_is_one_record_or_none(client, admin_id):
    bid = _board(client, admin_id, "הגשה")
    f = _form(client, bid, admin_id)
    t = _ask(client, f["id"], admin_id, required=True)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)

    before = len(_titles(client, bid))
    r = client.post(f"/api/public/forms/{tok}/submit", json={"answers": {}}, headers=ANON)
    assert r.status_code == 400 and "חובה" in _problem(r)
    assert len(_titles(client, bid)) == before, "a refused submission wrote something"

    r = client.post(f"/api/public/forms/{tok}/submit",
                    json={"answers": {str(t["id"]): "פנייה"}}, headers=ANON)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "id" not in r.json(), "the respondent is handed a reference to the row"
    assert len(_titles(client, bid)) == before + 1


def test_a_hidden_question_is_not_read_even_if_an_answer_arrives(client, admin_id):
    bid = _board(client, admin_id, "מוסתר")
    f = _form(client, bid, admin_id)
    t = _ask(client, f["id"], admin_id)
    h = _ask(client, f["id"], admin_id, field="status", label="סטטוס", visible=False)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)
    r = client.post(f"/api/public/forms/{tok}/submit",
                    json={"answers": {str(t["id"]): "פנייה", str(h["id"]): "done"}},
                    headers=ANON)
    assert r.status_code == 200
    task = [t for t in client.get(f"/api/boards/{bid}").json()["tasks"]
            if t["title"] == "פנייה"][0]
    assert task["custom_fields"].get("status_unset") is True, "a hidden answer was read"


def test_the_rate_limit_is_the_last_thing_between_a_public_form_and_a_flood(
        client, admin_id, monkeypatch):
    bid = _board(client, admin_id, "קצב")
    f = _form(client, bid, admin_id)
    q = _ask(client, f["id"], admin_id)
    _set(client, f["id"], admin_id, access="PUBLIC_LINK")
    tok = _publish(client, f["id"], admin_id)
    before = len(_titles(client, bid))
    monkeypatch.setattr(cityos_main, "FORM_SUBMIT_MAX", 3)
    cityos_main._form_hits.clear()
    codes = [client.post(f"/api/public/forms/{tok}/submit",
                         json={"answers": {str(q["id"]): f"פנייה {i}"}},
                         headers=ANON).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429], codes
    assert len([t for t in _titles(client, bid) if t.startswith("פנייה ")]) == 3
    cityos_main._form_hits.clear()
