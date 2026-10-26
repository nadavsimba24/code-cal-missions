"""הגשת טופס מקצה לקצה — מה נבדק, ומה נכתב.

Everything the request says about itself is checked against what the SERVER
holds. The board is the form's board; the field is the component's field; the
type is the column's type; the options are the column's options; the person is
the authenticated session. A request that names a board id, a field id or a
user id is naming something it does not get to choose, and none of those is
read from it.

Two things that look like nothing and are not:

  `false` is an answer and `0` is an answer. `if not val` calls both of them
  missing, and that is how a "no" on a checkbox and a zero in a number field
  quietly become blanks. Emptiness is spelled out, on both sides.

  A send that already happened is the same send. The system has a once-only
  guard — a unique key column — and a replay collides with it and gets the
  answer the first attempt got, rather than a second record.
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
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, bid, admin_id, title, ctype, options=None):
    cols = [dict(c) for c in client.get(f"/api/boards/{bid}").json()["columns"]]
    col = {"type": ctype, "title": title}
    if options is not None:
        col["options"] = options
    cols.append(col)
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    return [c["id"] for c in client.get(f"/api/boards/{bid}").json()["columns"]
            if c["title"] == title][0]


class Form:
    """A published form, and the question ids by label."""

    def __init__(self, client, admin_id, name, fields, access="PUBLIC_LINK"):
        self.client, self.admin = client, admin_id
        self.bid = _board(client, admin_id, name)
        f = client.post(f"/api/boards/{self.bid}/forms", json={},
                        headers=AS(admin_id)).json()
        self.fid, self.q, self.col = f["id"], {}, {}
        for label, key, extra in fields:
            # "@title" is the board's own field; anything else is a COLUMN
            # TYPE to make. Spelled with a marker because "status" is both a
            # built-in field and a column type, and guessing from the word
            # alone made a status COLUMN into the board's status field.
            if key.startswith("@"):
                cid = key[1:]
            else:
                cid = _col(client, self.bid, admin_id, label, key,
                           (extra or {}).pop("options", None))
            self.col[label] = cid
            r = client.post(f"/api/forms/{self.fid}/components",
                            json={"kind": "question", "field_key": cid,
                                  "label": label, **(extra or {})},
                            headers=AS(admin_id))
            assert r.status_code == 200, (label, r.text)
            self.q[label] = r.json()["id"]
        client.patch(f"/api/forms/{self.fid}", json={"access": access},
                     headers=AS(admin_id))
        client.patch(f"/api/forms/{self.fid}", json={"status": "PUBLISHED"},
                     headers=AS(admin_id))
        self.tok = client.get(f"/api/forms/{self.fid}",
                              headers=AS(admin_id)).json()["public_token"]

    def send(self, answers, headers=ANON, **extra):
        body = {"answers": {str(self.q[k]): v for k, v in answers.items()}, **extra}
        return self.client.post(f"/api/public/forms/{self.tok}/submit",
                                json=body, headers=headers)

    def tasks(self):
        return self.client.get(f"/api/boards/{self.bid}").json()["tasks"]

    def task(self, title):
        return [t for t in self.tasks() if t["title"] == title][0]


# ── הגשה תקינה: רשומה אחת, מיפוי נכון ────────────────────────────────

def test_a_valid_submission_writes_every_answer_to_its_own_field(client, admin_id):
    f = Form(client, admin_id, "מיפוי", [
        ("נושא", "@title", None), ("כתובת", "text", None),
        ("סיפור", "long_text", None), ("כמה", "number", None),
        ("מתי", "date", None), ("טלפון", "phone", None),
        ("מייל", "email", None), ("מסכים", "checkbox", None),
        ("חומרה", "status", {"options": ["נמוכה", "גבוהה"]}),
        ("נושאים", "dropdown", {"options": ["תאורה", "ניקיון"]}),
    ])
    before = len(f.tasks())
    r = f.send({"נושא": "פנייה מלאה", "כתובת": "הרצל 1", "סיפור": "טקסט ארוך",
                "כמה": 7, "מתי": "2026-11-01", "טלפון": "050-1234567",
                "מייל": "a@b.co.il", "מסכים": True,
                "חומרה": "גבוהה", "נושאים": ["תאורה"]})
    assert r.status_code == 200, r.text
    assert len(f.tasks()) == before + 1, "one submission, one record"

    t = f.task("פנייה מלאה")
    cf = t["custom_fields"]
    assert cf[f.col["כתובת"]] == "הרצל 1"
    assert cf[f.col["סיפור"]] == "טקסט ארוך"
    assert cf[f.col["כמה"]] == 7
    assert cf[f.col["מתי"]] == "2026-11-01"
    assert cf[f.col["טלפון"]] == "050-1234567"
    assert cf[f.col["מייל"]] == "a@b.co.il"
    assert cf[f.col["מסכים"]] is True
    assert cf[f.col["נושאים"]] == ["תאורה"]
    # a status cell points at the option rather than holding the word
    assert cf[f.col["חומרה"]]["label"] == "גבוהה"
    assert cf[f.col["חומרה"]]["id"]
    # and the time it was sent is the record's own
    assert t["created_at"]


def test_the_submission_time_is_kept(client, admin_id):
    f = Form(client, admin_id, "זמן", [("נושא", "@title", None)])
    assert f.send({"נושא": "מתי"}).status_code == 200
    with Session(cityos_main.engine) as db:
        t = db.query(M.Task).filter(M.Task.title == "מתי").first()
        assert t.created_at is not None
        assert t.form_view_id == f.fid


def test_an_authenticated_form_keeps_the_identity_from_the_session(client, admin_id,
                                                                   member_id, guinea_id):
    f = Form(client, admin_id, "מי הגיש", [("נושא", "@title", None)],
             access="AUTHENTICATED")
    # the request even claims to be somebody else — and is not believed
    r = f.send({"נושא": "מהסשן"}, headers=AS(member_id),
               user_id=guinea_id, created_by=guinea_id, board_id=1)
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        t = db.query(M.Task).filter(M.Task.title == "מהסשן").first()
        assert t.created_by == member_id, "the body chose the creator"
        assert t.board_id == f.bid, "the body chose the board"


# ── false ו‎-0 אינם ערכים חסרים ──────────────────────────────────────

def test_a_false_checkbox_is_stored_as_false(client, admin_id):
    f = Form(client, admin_id, "לא מסומן", [
        ("נושא", "@title", None), ("מסכים", "checkbox", None)])
    assert f.send({"נושא": "עם לא", "מסכים": False}).status_code == 200
    cf = f.task("עם לא")["custom_fields"]
    assert f.col["מסכים"] in cf, "false was dropped as if it were missing"
    assert cf[f.col["מסכים"]] is False


def test_a_zero_is_stored_as_zero(client, admin_id):
    f = Form(client, admin_id, "אפס", [
        ("נושא", "@title", None), ("כמה", "number", None)])
    assert f.send({"נושא": "עם אפס", "כמה": 0}).status_code == 200
    cf = f.task("עם אפס")["custom_fields"]
    assert f.col["כמה"] in cf, "0 was dropped as if it were missing"
    assert cf[f.col["כמה"]] == 0
    # …and "0" as a string is the same zero
    assert f.send({"נושא": "אפס כמחרוזת", "כמה": "0"}).status_code == 200
    assert f.task("אפס כמחרוזת")["custom_fields"][f.col["כמה"]] == 0


def test_a_required_checkbox_means_a_box_that_has_to_be_ticked(client, admin_id):
    f = Form(client, admin_id, "חובה לסמן", [
        ("נושא", "@title", None), ("מסכים", "checkbox", {"required": True})])
    r = f.send({"נושא": "בלי הסכמה", "מסכים": False})
    assert r.status_code == 400 and "מסכים" in _problem(r)
    assert all(t["title"] != "בלי הסכמה" for t in f.tasks())
    assert f.send({"נושא": "עם הסכמה", "מסכים": True}).status_code == 200


# ── הערכים תואמים לסוג ───────────────────────────────────────────────

@pytest.mark.parametrize("label,ctype,value", [
    ("מייל", "email", "לא-מייל"),
    ("מייל", "email", "a@b"),
    ("טלפון", "phone", "abc"),
    ("כמה", "number", "הרבה"),
    ("מתי", "date", "מחר"),
])
def test_a_value_that_does_not_fit_the_field_is_refused(client, admin_id,
                                                        label, ctype, value):
    f = Form(client, admin_id, f"סוג {label} {value}", [
        ("נושא", "@title", None), (label, ctype, None)])
    r = f.send({"נושא": "לא תקין", label: value})
    assert r.status_code == 400, r.text
    assert label in _problem(r), r.text
    assert all(t["title"] != "לא תקין" for t in f.tasks())


def test_a_choice_has_to_be_one_of_the_choices(client, admin_id):
    f = Form(client, admin_id, "אפשרויות", [
        ("נושא", "@title", None),
        ("חומרה", "status", {"options": ["נמוכה", "גבוהה"]}),
        ("נושאים", "dropdown", {"options": ["תאורה", "ניקיון"]})])
    assert f.send({"נושא": "המצאה", "חומרה": "קריטית"}).status_code == 400
    assert f.send({"נושא": "המצאה", "נושאים": ["תאורה", "משהו אחר"]}).status_code == 400
    assert all(t["title"] != "המצאה" for t in f.tasks())
    assert f.send({"נושא": "תקין", "חומרה": "נמוכה",
                   "נושאים": ["תאורה", "ניקיון"]}).status_code == 200
    assert f.task("תקין")["custom_fields"][f.col["נושאים"]] == ["תאורה", "ניקיון"]


def test_a_date_outside_the_questions_range_is_refused(client, admin_id):
    f = Form(client, admin_id, "טווח", [
        ("נושא", "@title", None),
        ("מתי", "date", {"settings": {"min": "2026-01-01", "max": "2026-12-31"}})])
    assert f.send({"נושא": "מוקדם", "מתי": "2025-06-01"}).status_code == 400
    assert f.send({"נושא": "מאוחר", "מתי": "2027-06-01"}).status_code == 400
    assert f.send({"נושא": "בטווח", "מתי": "2026-06-01"}).status_code == 200


def test_only_board_members_can_be_named_on_it(client, admin_id, member_id, guinea_id):
    f = Form(client, admin_id, "אנשים", [
        ("נושא", "@title", None), ("אחראי", "@assignees", None)])
    client.post(f"/api/boards/{f.bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    r = f.send({"נושא": "זר", "אחראי": [guinea_id]})
    assert r.status_code == 400 and "אחראי" in _problem(r)
    assert all(t["title"] != "זר" for t in f.tasks())
    assert f.send({"נושא": "חבר", "אחראי": [member_id]}).status_code == 200
    assert [a["id"] for a in f.task("חבר")["assignees"]] == [member_id]


# ── מה שהבקשה אומרת על עצמה ──────────────────────────────────────────

def test_a_question_id_that_is_not_this_forms_is_refused(client, admin_id):
    a = Form(client, admin_id, "טופס אחד", [("נושא", "@title", None)])
    b = Form(client, admin_id, "טופס שני", [("נושא", "@title", None)])
    r = client.post(f"/api/public/forms/{a.tok}/submit", headers=ANON,
                    json={"answers": {str(a.q["נושא"]): "שלי",
                                      str(b.q["נושא"]): "של מישהו אחר"}})
    assert r.status_code == 400, r.text
    assert "רעננו" in r.json()["detail"]
    assert all(t["title"] != "שלי" for t in a.tasks())
    # an id that is not a question at all, the same
    assert client.post(f"/api/public/forms/{a.tok}/submit", headers=ANON,
                       json={"answers": {"999999": "x"}}).status_code == 400


def test_a_hidden_question_is_not_read_and_does_not_block(client, admin_id):
    """Hiding wins over requiring — the decision taken when the model was
    built, and the reason the pair cannot be saved in the first place."""
    f = Form(client, admin_id, "מוסתר", [
        ("נושא", "@title", None), ("פנימי", "text", {"visible": False})])
    r = f.send({"נושא": "עם מוסתר", "פנימי": "ערך שנשלח בכל זאת"})
    assert r.status_code == 200, r.text
    assert f.col["פנימי"] not in f.task("עם מוסתר")["custom_fields"]
    # …and the form cannot be saved in the state that would make this a trap
    assert client.patch(f"/api/forms/{f.fid}/components/{f.q['פנימי']}",
                        json={"required": True}, headers=AS(admin_id)).status_code == 400


def test_the_board_has_no_required_fields_to_satisfy(client, admin_id):
    """A board column has no `required` — a form that does not ask for a
    field simply leaves its cell empty, and nothing is blocked by it."""
    f = Form(client, admin_id, "בלי חובה בלוח", [("נושא", "@title", None)])
    other = _col(client, f.bid, admin_id, "לא נשאל", "text")
    assert "required" not in [c for c in
                              client.get(f"/api/boards/{f.bid}").json()["columns"]
                              if c["id"] == other][0]
    assert f.send({"נושא": "בלי השדה"}).status_code == 200
    assert other not in f.task("בלי השדה")["custom_fields"]


# ── אטומיות ומניעת כפילות ───────────────────────────────────────────

def test_an_invalid_submission_writes_nothing_at_all(client, admin_id):
    f = Form(client, admin_id, "לא תקין", [
        ("נושא", "@title", None), ("כתובת", "text", None), ("מייל", "email", None)])
    before = len(f.tasks())
    r = f.send({"נושא": "חלקי", "כתובת": "הרצל 1", "מייל": "לא מייל"})
    assert r.status_code == 400
    assert len(f.tasks()) == before, "a refused submission created a record"
    with Session(cityos_main.engine) as db:
        assert db.query(M.Task).filter(M.Task.title == "חלקי").first() is None


def test_a_failure_part_way_through_leaves_no_half_record(client, admin_id,
                                                          monkeypatch):
    """The record, its cells, its file claims and its dedup key are one
    transaction. Something raising after the row is built takes all of it."""
    f = Form(client, admin_id, "נפילה באמצע", [("נושא", "@title", None)])
    before = len(f.tasks())

    def boom(*a, **kw):
        raise RuntimeError("the automation engine fell over")
    monkeypatch.setattr(cityos_main, "_run_automations", boom)
    with pytest.raises(RuntimeError):
        f.send({"נושא": "חצי"})
    monkeypatch.undo()
    assert len(f.tasks()) == before
    with Session(cityos_main.engine) as db:
        assert db.query(M.Task).filter(M.Task.title == "חצי").first() is None


def test_the_same_send_twice_is_one_record(client, admin_id):
    f = Form(client, admin_id, "כפילות", [("נושא", "@title", None)])
    before = len(f.tasks())
    sid = "abc-123-def"
    a = f.send({"נושא": "פעם אחת"}, submission_id=sid)
    b = f.send({"נושא": "פעם אחת"}, submission_id=sid)
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert a.json()["duplicate"] is False and b.json()["duplicate"] is True
    assert len(f.tasks()) == before + 1, "the replay made a second record"
    # a different id is a different send
    c = f.send({"נושא": "פעם אחת"}, submission_id="other")
    assert c.json()["duplicate"] is False
    assert len(f.tasks()) == before + 2


def test_the_guard_is_the_systems_own(client, admin_id):
    f = Form(client, admin_id, "מפתח", [("נושא", "@title", None)])
    f.send({"נושא": "עם מפתח"}, submission_id="key-1")
    with Session(cityos_main.engine) as db:
        row = db.query(M.AutomationActionKey).filter(
            M.AutomationActionKey.key == f"form:{f.fid}:key-1").first()
        assert row is not None, "the existing idempotency table was not used"
        assert row.board_id == f.bid


def test_an_id_reused_across_two_forms_is_two_sends(client, admin_id):
    a = Form(client, admin_id, "מפתח א", [("נושא", "@title", None)])
    b = Form(client, admin_id, "מפתח ב", [("נושא", "@title", None)])
    assert a.send({"נושא": "א"}, submission_id="same").json()["duplicate"] is False
    assert b.send({"נושא": "ב"}, submission_id="same").json()["duplicate"] is False
    assert any(t["title"] == "א" for t in a.tasks())
    assert any(t["title"] == "ב" for t in b.tasks())


def test_a_send_with_no_id_is_not_deduplicated(client, admin_id):
    """Honest about what it is: no id, no protection — and the page always
    sends one."""
    f = Form(client, admin_id, "בלי מפתח", [("נושא", "@title", None)])
    before = len(f.tasks())
    f.send({"נושא": "שוב"})
    f.send({"נושא": "שוב"})
    assert len(f.tasks()) == before + 2
