"""שאלת File — מאיפה הקובץ בא, ולמי מותר להצביע עליו.

A respondent uploads before they send, so between those two moments a file
exists and belongs to nothing. That window is where the whole of this lives.

Two columns on `uploaded_files` are what it is made of. `form_view_id` says
which form the upload was made FOR — NULL on every ordinary board attachment,
which is what makes those unclaimable by a form. `claimed_at` says a
submission has taken it, which is what stops one upload becoming a cell on
two records.

So changing an id in the request buys nothing: a token off somebody's board
carries no form id, a token from another form carries a different one, and a
token already used carries a claim. None of the three is a file a submission
may point at, and all three are refused out loud rather than dropped — a form
sent with a file on it must not produce a record without one.
"""
import datetime as dt

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}
ANON = {"X-CityOS-User": ""}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


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


def _col(client, bid, admin_id, title, ctype):
    cols = [dict(c) for c in client.get(f"/api/boards/{bid}").json()["columns"]]
    cols.append({"type": ctype, "title": title})
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    return [c["id"] for c in client.get(f"/api/boards/{bid}").json()["columns"]
            if c["title"] == title][0]


def _form_with_file(client, admin_id, name, access="PUBLIC_LINK"):
    """A published form: a title question and a file question."""
    bid = _board(client, admin_id, name)
    cid = _col(client, bid, admin_id, "צרופה", "files")
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id)).json()
    t = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": "title", "label": "נושא"},
                    headers=AS(admin_id)).json()
    q = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": cid, "label": "צרופה"},
                    headers=AS(admin_id)).json()
    client.patch(f"/api/forms/{f['id']}", json={"access": access}, headers=AS(admin_id))
    client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"}, headers=AS(admin_id))
    tok = client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).json()["public_token"]
    return bid, f, cid, t, q, tok


def _up(client, tok, headers=ANON, name="note.txt", body=b"hello", ctype="text/plain"):
    return client.post(f"/api/public/forms/{tok}/upload", headers=headers,
                       files={"file": (name, body, ctype)})


def _send(client, tok, t, q, files, headers=ANON, title="עם קובץ"):
    return client.post(f"/api/public/forms/{tok}/submit", headers=headers,
                       json={"answers": {str(t["id"]): title, str(q["id"]): files}})


def _task(client, bid, title):
    return [x for x in client.get(f"/api/boards/{bid}").json()["tasks"]
            if x["title"] == title][0]


# ── הדרך התקינה ──────────────────────────────────────────────────────

def test_a_file_lands_in_the_field_it_was_asked_for(client, admin_id):
    bid, _f, cid, t, q, tok = _form_with_file(client, admin_id, "קובץ תקין")
    up = _up(client, tok).json()
    assert _send(client, tok, t, q, [up["token"]]).status_code == 200

    cell = _task(client, bid, "עם קובץ")["custom_fields"][cid]
    assert len(cell) == 1
    assert cell[0]["name"] == "note.txt" and cell[0]["type"] == "text/plain"
    assert cell[0]["url"] == f"/api/files/{up['token']}"
    # …and only in that field
    other = _task(client, bid, "עם קובץ")["custom_fields"]
    assert [k for k, v in other.items() if isinstance(v, list) and v
            and isinstance(v[0], dict) and "url" in v[0]] == [cid]


def test_uploading_works_on_both_kinds_of_form(client, admin_id, member_id):
    for access, who in (("PUBLIC_LINK", ANON), ("AUTHENTICATED", AS(member_id))):
        bid, _f, cid, t, q, tok = _form_with_file(client, admin_id, "גישה " + access, access)
        up = _up(client, tok, headers=who)
        assert up.status_code == 200, (access, up.text)
        assert _send(client, tok, t, q, [up.json()["token"]],
                     headers=who).status_code == 200, access
        assert len(_task(client, bid, "עם קובץ")["custom_fields"][cid]) == 1
    # …and an AUTHENTICATED form refuses an upload from nobody, like everything else
    _b, _f, _c, _t, _q, tok = _form_with_file(client, admin_id, "סגור", "AUTHENTICATED")
    assert _up(client, tok, headers=ANON).status_code == 401


# ── שינוי מזהה בבקשה ─────────────────────────────────────────────────

def test_a_board_attachment_cannot_be_claimed_by_a_form(client, admin_id):
    """The attack this exists to stop: a token seen on a board, posted as an
    answer, copied onto a new record."""
    bid, _f, cid, t, q, tok = _form_with_file(client, admin_id, "לא מהלוח")
    board_file = client.post("/api/upload", headers=AS(admin_id),
                             files={"file": ("secret.pdf", b"%PDF-", "application/pdf")})
    stolen = board_file.json()["url"].rsplit("/", 1)[-1]

    r = _send(client, tok, t, q, [stolen])
    assert r.status_code == 400, r.text
    assert "צרופה" in _problem(r), r.text
    assert all(x["title"] != "עם קובץ"
               for x in client.get(f"/api/boards/{bid}").json()["tasks"]), \
        "a refused file still produced a record"
    with Session(cityos_main.engine) as db:
        row = db.query(M.UploadedFile).filter(M.UploadedFile.token == stolen).first()
        assert row is not None, "somebody else's attachment was touched"
        assert row.form_view_id is None and row.claimed_at is None


def test_a_file_uploaded_for_another_form_is_refused(client, admin_id):
    _b1, _f1, _c1, _t1, _q1, tok1 = _form_with_file(client, admin_id, "טופס א")
    bid2, _f2, _c2, t2, q2, tok2 = _form_with_file(client, admin_id, "טופס ב")
    theirs = _up(client, tok1).json()["token"]

    r = _send(client, tok2, t2, q2, [theirs])
    assert r.status_code == 400, r.text
    assert all(x["title"] != "עם קובץ"
               for x in client.get(f"/api/boards/{bid2}").json()["tasks"])
    # …and the other form can still use its own
    assert _send(client, tok1, _t1, _q1, [theirs]).status_code == 200


def test_one_upload_cannot_become_two_records(client, admin_id):
    bid, _f, cid, t, q, tok = _form_with_file(client, admin_id, "פעם אחת")
    up = _up(client, tok).json()["token"]
    assert _send(client, tok, t, q, [up], title="ראשון").status_code == 200
    r = _send(client, tok, t, q, [up], title="שני")
    assert r.status_code == 400, r.text
    assert all(x["title"] != "שני" for x in client.get(f"/api/boards/{bid}").json()["tasks"])
    with Session(cityos_main.engine) as db:
        assert db.query(M.UploadedFile).filter(
            M.UploadedFile.token == up).first().claimed_at is not None


def test_a_token_that_names_nothing_is_refused(client, admin_id):
    bid, _f, _cid, t, q, tok = _form_with_file(client, admin_id, "לא קיים")
    assert _send(client, tok, t, q, ["f" * 32]).status_code == 400
    assert all(x["title"] != "עם קובץ"
               for x in client.get(f"/api/boards/{bid}").json()["tasks"])


# ── המדיניות ─────────────────────────────────────────────────────────

def test_the_policy_is_enforced_where_it_cannot_be_argued_with(client, admin_id):
    _bid, _f, _cid, t, q, tok = _form_with_file(client, admin_id, "מדיניות")
    # type: an allowlist
    assert _up(client, tok, name="x.svg", body=b"<svg/>", ctype="image/svg+xml").status_code == 400
    assert _up(client, tok, name="x.exe", body=b"MZ",
               ctype="application/x-msdownload").status_code == 400
    assert _up(client, tok, name="x.png", body=PNG, ctype="image/png").status_code == 200
    # size
    big = b"0" * (cityos_main.FORM_UPLOAD_MAX_BYTES + 1)
    assert _up(client, tok, name="big.txt", body=big, ctype="text/plain").status_code == 413
    # count, per question, at the submission
    toks = [_up(client, tok, name=f"{i}.txt").json()["token"]
            for i in range(cityos_main.FORM_UPLOAD_PER_QUESTION + 1)]
    r = _send(client, tok, t, q, toks)
    assert r.status_code == 400 and "עד" in _problem(r), r.text
    # …and the ones inside the limit still work
    assert _send(client, tok, t, q, toks[:cityos_main.FORM_UPLOAD_PER_QUESTION]
                 ).status_code == 200


def test_the_whole_submission_has_a_budget_not_only_each_file(client, admin_id,
                                                              monkeypatch):
    _bid, _f, _cid, t, q, tok = _form_with_file(client, admin_id, "תקציב")
    monkeypatch.setattr(cityos_main, "FORM_UPLOAD_TOTAL_BYTES", 2048)
    toks = [_up(client, tok, name=f"{i}.txt", body=b"0" * 1200).json()["token"]
            for i in range(2)]
    r = _send(client, tok, t, q, toks)
    assert r.status_code == 413, r.text
    # under the budget it goes through, and the files are still unclaimed
    assert _send(client, tok, t, q, toks[:1]).status_code == 200


def test_the_page_is_told_the_policy_rather_than_guessing_it(client, admin_id):
    _bid, _f, _cid, _t, _q, tok = _form_with_file(client, admin_id, "מדיניות לדף")
    u = client.get(f"/api/public/forms/{tok}", headers=ANON).json()["uploads"]
    assert u["max_mb"] == cityos_main.FORM_UPLOAD_MAX_BYTES // (1024 * 1024)
    assert u["per_question"] == cityos_main.FORM_UPLOAD_PER_QUESTION
    assert u["total_mb"] == cityos_main.FORM_UPLOAD_TOTAL_BYTES // (1024 * 1024)
    assert "image/svg+xml" not in u["types"] and "image/png" in u["types"]
    page = (cityos_main.frontend_path and
            __import__("pathlib").Path(cityos_main.frontend_path) / "public-form.html"
            ).read_text(encoding="utf-8")
    assert "DOC.uploads" in page, "the page carries its own copy of the limits"


# ── קבצים של טופס שלא הוגש ───────────────────────────────────────────

def test_an_upload_nobody_sent_is_swept_and_a_claimed_one_is_not(client, admin_id):
    bid, _f, cid, t, q, tok = _form_with_file(client, admin_id, "ניקוי")
    kept = _up(client, tok, name="kept.txt").json()["token"]
    assert _send(client, tok, t, q, [kept]).status_code == 200
    orphan = _up(client, tok, name="orphan.txt").json()["token"]
    board_file = client.post("/api/upload", headers=AS(admin_id),
                             files={"file": ("board.txt", b"x", "text/plain")}
                             ).json()["url"].rsplit("/", 1)[-1]

    with Session(cityos_main.engine) as db:
        old = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
               - dt.timedelta(hours=cityos_main.FORM_UPLOAD_TTL_HOURS + 1))
        for tk in (kept, orphan, board_file):
            db.query(M.UploadedFile).filter(M.UploadedFile.token == tk).first().created_at = old
        db.commit()
        dropped = cityos_main._purge_unclaimed_form_uploads(db)
        assert dropped == 1, dropped
        left = {r.token for r in db.query(M.UploadedFile).filter(
            M.UploadedFile.token.in_([kept, orphan, board_file])).all()}
        assert left == {kept, board_file}, left
    # the record still reads its file
    assert _task(client, bid, "עם קובץ")["custom_fields"][cid][0]["name"] == "kept.txt"


def test_a_fresh_unsent_upload_is_left_alone(client, admin_id):
    _bid, _f, _cid, _t, _q, tok = _form_with_file(client, admin_id, "טרי")
    fresh = _up(client, tok).json()["token"]
    with Session(cityos_main.engine) as db:
        assert cityos_main._purge_unclaimed_form_uploads(db) == 0
        assert db.query(M.UploadedFile).filter(
            M.UploadedFile.token == fresh).first() is not None


# ── כישלון לא יוצר רשומה חלקית ───────────────────────────────────────

def test_a_failed_upload_leaves_no_record_at_all(client, admin_id):
    bid, _f, _cid, _t, _q, tok = _form_with_file(client, admin_id, "כישלון")
    before = len(client.get(f"/api/boards/{bid}").json()["tasks"])
    assert _up(client, tok, name="x.exe", body=b"MZ",
               ctype="application/x-msdownload").status_code == 400
    assert len(client.get(f"/api/boards/{bid}").json()["tasks"]) == before
    with Session(cityos_main.engine) as db:
        assert db.query(M.UploadedFile).filter(
            M.UploadedFile.name == "x.exe").first() is None


def test_a_refused_file_rolls_the_whole_submission_back(client, admin_id):
    """One bad token among good ones: no record, and the good ones stay
    unclaimed so the form can be sent again."""
    bid, _f, cid, t, q, tok = _form_with_file(client, admin_id, "חזרה אחורה")
    good = _up(client, tok, name="good.txt").json()["token"]
    r = _send(client, tok, t, q, [good, "f" * 32])
    assert r.status_code == 400, r.text
    assert all(x["title"] != "עם קובץ"
               for x in client.get(f"/api/boards/{bid}").json()["tasks"])
    with Session(cityos_main.engine) as db:
        assert db.query(M.UploadedFile).filter(
            M.UploadedFile.token == good).first().claimed_at is None
    # …and re-sending with only the good one works
    assert _send(client, tok, t, q, [good]).status_code == 200
    assert _task(client, bid, "עם קובץ")["custom_fields"][cid][0]["name"] == "good.txt"
