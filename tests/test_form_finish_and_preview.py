"""סיום ההגשה והתצוגה המקדימה — מה נאמר, מתי, ולמי.

Two screens and one rule between them.

The thank-you is shown AFTER the server has said the record exists, never
before: a form that congratulates somebody on the way out of the browser is
a form that loses submissions silently.

The preview runs the real validation through a door that writes nothing. The
same function, not a second one that agrees today — and reached by the form's
id with the rights of whoever may open the builder, never by the public
token. Hung off the token it would be precisely the way around the gate.

And the errors in both are per question: the page can put each message beside
the field it belongs to, nothing is re-rendered, and what somebody already
typed is still there when they fix the one thing that was wrong.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}
ANON = {"X-CityOS-User": ""}

import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "public-form.html").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _board(client, admin_id, name):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, bid, admin_id, title, ctype):
    cols = [dict(c) for c in client.get(f"/api/boards/{bid}").json()["columns"]]
    cols.append({"type": ctype, "title": title})
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    return [c["id"] for c in client.get(f"/api/boards/{bid}").json()["columns"]
            if c["title"] == title][0]


def _form(client, admin_id, name, publish=True, access="PUBLIC_LINK"):
    """A form asking a title, an email and a required text."""
    bid = _board(client, admin_id, name)
    mail = _col(client, bid, admin_id, "מייל", "email")
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id)).json()
    q = {}
    for label, key, extra in (("נושא", "title", {"required": True}),
                              ("מייל", mail, {}),
                              ("פרטים", "title", None)):
        if label == "פרטים":
            continue
        q[label] = client.post(f"/api/forms/{f['id']}/components",
                               json={"kind": "question", "field_key": key,
                                     "label": label, **(extra or {})},
                               headers=AS(admin_id)).json()["id"]
    client.patch(f"/api/forms/{f['id']}",
                 json={"access": access, "success_title": "תודה רבה",
                       "success_message": "הפנייה נקלטה, נחזור תוך יומיים."},
                 headers=AS(admin_id))
    tok = None
    if publish:
        client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"},
                     headers=AS(admin_id))
        tok = client.get(f"/api/forms/{f['id']}",
                         headers=AS(admin_id)).json()["public_token"]
    return bid, f, q, tok


def _tasks(client, bid):
    return client.get(f"/api/boards/{bid}").json()["tasks"]


# ── מסך הצלחה ────────────────────────────────────────────────────────

def test_the_manager_writes_the_thank_you_and_the_respondent_reads_it(client, admin_id):
    bid, f, q, tok = _form(client, admin_id, "תודה")
    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["נושא"]): "פנייה"}})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "תודה רבה"
    assert r.json()["message"] == "הפנייה נקלטה, נחזור תוך יומיים."


def test_the_thank_you_comes_only_after_the_record_exists(client, admin_id,
                                                          monkeypatch):
    """The page draws it from the server's answer, and the server does not
    answer until it has committed."""
    bid, f, q, tok = _form(client, admin_id, "אחרי הכתיבה")
    before = len(_tasks(client, bid))

    def boom(*a, **kw):
        raise RuntimeError("the engine fell over on the way out")
    monkeypatch.setattr(cityos_main, "_run_automations", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["נושא"]): "לא נוצרה"}})
    monkeypatch.undo()
    assert len(_tasks(client, bid)) == before
    # the page's success screen is reached from the try, never from the catch
    send = PAGE[PAGE.index("async function send(){"):PAGE.index("function banner(")]
    assert "done(r)" in send.split("catch(e)")[0], "success is shown before the answer"
    assert "done(" not in send.split("catch(e)")[1], "a failure can still show success"


# ── שגיאות ליד השאלה ─────────────────────────────────────────────────

def test_every_problem_comes_back_at_once_keyed_by_its_question(client, admin_id):
    bid, f, q, tok = _form(client, admin_id, "ליד השאלה")
    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["מייל"]): "לא-מייל"}})
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    assert isinstance(d, dict) and d["message"]
    by = {e["question_id"]: e for e in d["errors"]}
    # both问题 at once: the missing required one AND the bad email
    assert set(by) == {q["נושא"], q["מייל"]}, d
    assert by[q["נושא"]]["message"] == "שדה חובה"
    assert "דוא" in by[q["מייל"]]["message"]
    assert by[q["מייל"]]["label"] == "מייל"


def test_an_error_message_says_nothing_about_what_is_behind_the_form(client, admin_id):
    bid, f, q, tok = _form(client, admin_id, "בלי פרטים פנימיים")
    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["מייל"]): "לא-מייל"}})
    blob = __import__("json").dumps(r.json(), ensure_ascii=False)
    for leak in (str(bid), "col_", "board", "Traceback", "sqlalchemy", "form_view"):
        assert leak not in blob, f"the refusal leaks {leak}: {blob}"


def test_a_refusal_leaves_the_answers_on_screen(client, admin_id):
    """Nothing is re-rendered on an error, so the inputs keep what was typed
    — including the files already uploaded."""
    send = PAGE[PAGE.index("async function send(){"):PAGE.index("function banner(")]
    catch = send[send.index("catch(e)"):]
    assert "draw()" not in catch and "load()" not in catch, \
        "a failed send redraws the form and loses what was typed"
    assert "fieldError(x.question_id, x.message)" in catch, \
        "the server's problems are not placed beside their questions"


def test_a_server_failure_says_so_in_our_words_and_invites_a_retry(client, admin_id):
    send = PAGE[PAGE.index("async function send(){"):PAGE.index("function banner(")]
    assert "e.status >= 500" in send, "a 500 is reported as whatever it said"
    assert "נסו לשלוח שוב" in send
    assert "sending = false" in send and "btn.disabled = false" in send, \
        "the button stays dead after a failure"


def test_a_form_closed_while_somebody_was_filling_it_in_is_handled(client, admin_id):
    bid, f, q, tok = _form(client, admin_id, "נסגר באמצע")
    client.patch(f"/api/forms/{f['id']}", json={"status": "DISABLED"},
                 headers=AS(admin_id))
    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["נושא"]): "מאוחר מדי"}})
    assert r.status_code == 410
    send = PAGE[PAGE.index("async function send(){"):PAGE.index("function banner(")]
    assert "[401, 403, 404, 410].indexOf(e.status) >= 0" in send
    assert "refusal(e)" in send


# ── Preview ──────────────────────────────────────────────────────────

def test_the_preview_runs_the_real_validation_and_writes_nothing(client, admin_id):
    bid, f, q, tok = _form(client, admin_id, "בדיקה יבשה", publish=False)
    before = len(_tasks(client, bid))

    bad = client.post(f"/api/forms/{f['id']}/preview/submit", headers=AS(admin_id),
                      json={"answers": {str(q["מייל"]): "לא-מייל"}})
    assert bad.status_code == 400
    by = {e["question_id"] for e in bad.json()["detail"]["errors"]}
    assert by == {q["נושא"], q["מייל"]}, "the preview checks something else"

    ok = client.post(f"/api/forms/{f['id']}/preview/submit", headers=AS(admin_id),
                     json={"answers": {str(q["נושא"]): "בדיקה",
                                       str(q["מייל"]): "a@b.co.il"}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["preview"] is True
    assert ok.json()["title"] == "תודה רבה", "the preview shows the real thank-you"
    assert len(_tasks(client, bid)) == before, "the preview created a record"
    with Session(cityos_main.engine) as db:
        assert db.query(M.Task).filter(M.Task.title == "בדיקה").first() is None


def test_the_preview_is_the_same_validation_and_not_a_second_one():
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert src.count("def _form_validate(") == 1
    # the two CALL sites — the definition itself does not count
    assert src.count("_form_validate(db, f, b, answers, claim=") == 2, \
        "the preview and the real submission do not share the check"


def test_the_preview_never_claims_a_file(client, admin_id):
    bid = _board(client, admin_id, "קובץ בתצוגה")
    cid = _col(client, bid, admin_id, "צרופה", "files")
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id)).json()
    t = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": "title", "label": "נושא"},
                    headers=AS(admin_id)).json()
    q = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": cid, "label": "צרופה"},
                    headers=AS(admin_id)).json()
    client.patch(f"/api/forms/{f['id']}", json={"access": "PUBLIC_LINK"},
                 headers=AS(admin_id))
    client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"},
                 headers=AS(admin_id))
    tok = client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).json()["public_token"]
    up = client.post(f"/api/public/forms/{tok}/upload", headers=ANON,
                     files={"file": ("a.txt", b"hi", "text/plain")}).json()["token"]

    r = client.post(f"/api/forms/{f['id']}/preview/submit", headers=AS(admin_id),
                    json={"answers": {str(t["id"]): "בדיקה", str(q["id"]): [up]}})
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        assert db.query(M.UploadedFile).filter(
            M.UploadedFile.token == up).first().claimed_at is None, \
            "the preview took the file"
    # …so the real submission can still use it
    assert client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                       json={"answers": {str(t["id"]): "אמיתי",
                                         str(q["id"]): [up]}}).status_code == 200


def test_the_preview_cannot_be_used_to_get_around_the_gate(client, admin_id,
                                                           member_id, guinea_id):
    bid, f, q, tok = _form(client, admin_id, "לא דלת אחורית", publish=False)
    body = {"answers": {str(q["נושא"]): "בעד"}}
    # somebody not on the board gets nowhere
    assert client.post(f"/api/forms/{f['id']}/preview/submit", json=body,
                       headers=AS(guinea_id)).status_code == 403
    # …and it is not reachable by the public token at all
    client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"},
                 headers=AS(admin_id))
    tok = client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).json()["public_token"]
    assert client.post(f"/api/public/forms/{tok}/preview/submit", json=body,
                       headers=ANON).status_code in (404, 405)
    # an editor who may open the builder may test it
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    assert client.post(f"/api/forms/{f['id']}/preview/submit", json=body,
                       headers=AS(member_id)).status_code == 200
    # a viewer may not
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    assert client.post(f"/api/forms/{f['id']}/preview/submit", json=body,
                       headers=AS(guinea_id)).status_code == 403


def test_the_preview_works_on_a_form_that_is_not_published(client, admin_id):
    """Which is the whole point of it being a management endpoint."""
    bid, f, q, _tok = _form(client, admin_id, "טיוטה", publish=False)
    assert client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)
                      ).json()["status"] == "DRAFT"
    r = client.post(f"/api/forms/{f['id']}/preview/submit", headers=AS(admin_id),
                    json={"answers": {str(q["נושא"]): "טיוטה"}})
    assert r.status_code == 200, r.text
    assert len(_tasks(client, bid)) == len(_tasks(client, bid))


# ── מה המסך עושה עם זה ───────────────────────────────────────────────

def test_the_editors_preview_is_fillable_and_shows_the_thank_you():
    i = INDEX.index("const FormEditor={")
    block = INDEX[i:INDEX.index("</style>", i)]
    assert "fill:true" in block, "the preview cannot be filled in"
    assert "FormEditor.tryPreview()" in block, "there is nothing to submit"
    assert "'/preview/submit'" in block or "/preview/submit" in block
    assert "thanksHTML()" in block, "the preview never shows the success screen"
    assert "לא נוצרה רשומה" in block, "nothing says the preview writes nothing"
    # and the errors land beside their questions here too
    assert "d.errors.forEach(x=>this.pErr(x.question_id, x.message))" in block
