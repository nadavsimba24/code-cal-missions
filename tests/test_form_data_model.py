"""מודל הנתונים של תצוגת טופס — הלוח, הרכיבים, והגבולות ביניהם.

A form is a view of a board, so the identity is a `SavedView` whose `kind` is
"form"; `FormView` holds what only a form has, and `FormComponent` holds the
rows in the form's own order. Three things that have to be true of that shape,
and are tested here rather than assumed:

  a board can carry two forms that disagree about everything except the board
  a question cannot name a field of a different board
  deleting a form leaves the board exactly as it was

And the rule underneath: a form names columns, it never owns them. Nothing in
the form tables is something a column or an item hangs off, which is why the
third one is true by construction rather than by cleanup.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}
ADMIN = 1


def _board(client, name):
    r = client.post("/api/boards", json={"name": name, "user_id": ADMIN})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _col(client, bid, title, ctype="text"):
    """Add a custom column and return its generated id."""
    cols = [dict(c) for c in client.get(f"/api/boards/{bid}").json()["columns"]]
    cols.append({"type": ctype, "title": title})
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": ADMIN, "columns": cols})
    assert r.status_code == 200, r.text
    after = client.get(f"/api/boards/{bid}").json()["columns"]
    return [c["id"] for c in after if c.get("title") == title][0]


def _form(client, bid, name=None):
    r = client.post(f"/api/boards/{bid}/forms",
                    json={"name": name} if name else {}, headers=AS(ADMIN))
    assert r.status_code == 200, r.text
    return r.json()


def _save(client, fid, **body):
    return client.patch(f"/api/forms/{fid}", json=body, headers=AS(ADMIN))


# ── תנאי קבלה 1: שני טפסים באותו לוח, עם שאלות וסדר שונים ────────────

def test_two_forms_on_one_board_keep_separate_questions_and_order(client):
    bid = _board(client, "שני טפסים")
    addr = _col(client, bid, "כתובת")

    short = _form(client, bid, "פנייה קצרה")
    long_ = _form(client, bid, "פנייה מלאה")
    assert short["id"] != long_["id"]
    assert short["board_id"] == long_["board_id"] == bid
    # neither has an address yet — one is minted at the first publish, and
    # then it is that form's alone
    assert short["public_token"] is None and long_["public_token"] is None
    for f in (short, long_):
        assert _save(client, f["id"], status="PUBLISHED").status_code == 200
    tok = {f["id"]: client.get(f"/api/forms/{f['id']}", headers=AS(ADMIN)).json()
           for f in (short, long_)}
    a, b = tok[short["id"]], tok[long_["id"]]
    assert a["public_token"] and b["public_token"]
    assert a["public_token"] != b["public_token"]
    assert a["public_url"] == "/forms/" + a["public_token"]

    # the same two fields, in opposite orders, with different wording
    r = _save(client, short["id"], components=[
        {"kind": "question", "field_key": "title", "label": "נושא"},
        {"kind": "question", "field_key": addr, "label": "כתובת"},
    ])
    assert r.status_code == 200, r.text

    r = _save(client, long_["id"], components=[
        {"kind": "heading", "content": "פרטי הפנייה"},
        {"kind": "question", "field_key": addr, "label": "היכן זה קרה?",
         "description": "רחוב ומספר בית", "placeholder": "הרצל 1", "required": True},
        {"kind": "text", "content": "נחזור אליך תוך 5 ימי עבודה."},
        {"kind": "question", "field_key": "title", "label": "כותרת הפנייה"},
    ])
    assert r.status_code == 200, r.text

    a = client.get(f"/api/forms/{short['id']}", headers=AS(ADMIN)).json()
    b = client.get(f"/api/forms/{long_['id']}", headers=AS(ADMIN)).json()

    assert [c["field_key"] for c in a["components"]] == ["title", addr]
    assert [c.get("field_key") for c in b["components"]] == [None, addr, None, "title"]
    assert [c["position"] for c in b["components"]] == [0, 1, 2, 3]

    # the same field, two forms, two different questions about it
    qa = [c for c in a["components"] if c.get("field_key") == addr][0]
    qb = [c for c in b["components"] if c.get("field_key") == addr][0]
    assert qa["label"] == "כתובת" and qb["label"] == "היכן זה קרה?"
    assert qa["required"] is False and qb["required"] is True
    assert qb["description"] == "רחוב ומספר בית" and qb["placeholder"] == "הרצל 1"
    # …and editing one says nothing about the other
    assert _save(client, short["id"], components=[
        {"kind": "question", "field_key": "title", "label": "שונה"}]).status_code == 200
    again = client.get(f"/api/forms/{long_['id']}", headers=AS(ADMIN)).json()
    assert [c.get("field_key") for c in again["components"]] == [None, addr, None, "title"]


def test_form_order_is_not_the_board_column_order(client):
    """The form's order is its own — the board's columns do not dictate it."""
    bid = _board(client, "סדר עצמאי")
    first = _col(client, bid, "ראשונה")
    second = _col(client, bid, "שנייה")
    f = _form(client, bid)
    assert _save(client, f["id"], components=[
        {"kind": "question", "field_key": second, "label": "ב"},
        {"kind": "question", "field_key": first, "label": "א"},
    ]).status_code == 200
    got = client.get(f"/api/forms/{f['id']}", headers=AS(ADMIN)).json()
    assert [c["field_key"] for c in got["components"]] == [second, first]
    # the board's own column order is untouched by that
    cols = client.get(f"/api/boards/{bid}").json()["columns"]
    ids = [c["id"] for c in cols]
    assert ids.index(first) < ids.index(second)


# ── תנאי קבלה 2: שדה מלוח אחר נכשל ───────────────────────────────────

def test_question_cannot_name_a_field_of_another_board(client):
    bid = _board(client, "לוח הטופס")
    other = _board(client, "לוח אחר")
    mine = _col(client, bid, "שלי")
    theirs = _col(client, other, "שלהם")
    f = _form(client, bid)

    r = _save(client, f["id"], components=[
        {"kind": "question", "field_key": theirs, "label": "שדה של מישהו אחר"}])
    assert r.status_code == 400, r.text
    assert "הלוח הזה" in r.json()["detail"]

    # a field that exists nowhere is refused the same way
    assert _save(client, f["id"], components=[
        {"kind": "question", "field_key": "col_nope", "label": "אין כזה"}
    ]).status_code == 400

    # and the valid one next to it still works
    assert _save(client, f["id"], components=[
        {"kind": "question", "field_key": mine, "label": "שלי"}]).status_code == 200

    # the refusal is whole: a list with one bad field writes none of it
    r = _save(client, f["id"], components=[
        {"kind": "question", "field_key": "title", "label": "טוב"},
        {"kind": "question", "field_key": theirs, "label": "רע"},
    ])
    assert r.status_code == 400
    got = client.get(f"/api/forms/{f['id']}", headers=AS(ADMIN)).json()
    assert [c["field_key"] for c in got["components"]] == [mine]


def test_derived_columns_are_not_fields_a_form_may_ask_for(client):
    """A column the system computes has nothing to ask about."""
    bid = _board(client, "עמודות נגזרות")
    f = _form(client, bid)
    # every new board ships with these three
    for key in ("sys_item_id", "sys_created_at", "sys_created_by"):
        r = _save(client, f["id"],
                  components=[{"kind": "question", "field_key": key, "label": key}])
        assert r.status_code == 400, key


# ── תנאי קבלה 3: מחיקת טופס משאירה את נתוני הלוח ─────────────────────

def test_deleting_a_form_leaves_the_board_alone(client):
    bid = _board(client, "מחיקה")
    addr = _col(client, bid, "כתובת")
    item = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "custom_fields": {addr: "הרצל 1"},
                                           "user_id": ADMIN}).json()["id"]
    f = _form(client, bid)
    assert _save(client, f["id"], components=[
        {"kind": "question", "field_key": addr, "label": "כתובת"},
        {"kind": "question", "field_key": "title", "label": "נושא"},
    ]).status_code == 200

    r = client.delete(f"/api/forms/{f['id']}", headers=AS(ADMIN))
    assert r.status_code == 200, r.text

    board = client.get(f"/api/boards/{bid}").json()
    assert addr in [c["id"] for c in board["columns"]]
    t = [t for t in board["tasks"] if t["id"] == item][0]
    assert t["custom_fields"][addr] == "הרצל 1"
    # gone from the list, and gone through the door
    assert client.get(f"/api/boards/{bid}/forms", headers=AS(ADMIN)).json()["forms"] == []
    assert client.get(f"/api/forms/{f['id']}", headers=AS(ADMIN)).status_code == 404


def test_deleting_a_form_does_not_touch_the_other_form(client):
    bid = _board(client, "מחיקה אחת")
    a, b = _form(client, bid, "א"), _form(client, bid, "ב")
    assert _save(client, b["id"], components=[
        {"kind": "question", "field_key": "title", "label": "נושא"}]).status_code == 200
    assert client.delete(f"/api/forms/{a['id']}", headers=AS(ADMIN)).status_code == 200
    got = client.get(f"/api/forms/{b['id']}", headers=AS(ADMIN)).json()
    assert [c["field_key"] for c in got["components"]] == ["title"]


# ── המבנה עצמו ───────────────────────────────────────────────────────

def test_a_form_cannot_exist_without_a_board(client):
    """NOT NULL on both halves, and no door that makes one without the other."""
    for col in (M.FormView.__table__.c.board_id, M.FormView.__table__.c.view_id,
                M.FormComponent.__table__.c.form_id,
                M.FormComponent.__table__.c.board_id):
        assert col.nullable is False, col
    assert client.post("/api/boards/999999/forms", json={}, headers=AS(ADMIN)).status_code == 404


def test_the_component_board_is_the_form_board(client):
    """Structural, not remembered: the pair is a composite foreign key."""
    fks = {fk.name for fk in M.FormComponent.__table__.constraints
           if fk.__class__.__name__ == "ForeignKeyConstraint"}
    assert "fk_form_component_board" in fks
    bid = _board(client, "זוג")
    f = _form(client, bid)
    _save(client, f["id"], components=[{"kind": "question", "field_key": "title", "label": "x"}])
    with Session(cityos_main.engine) as db:
        rows = db.query(M.FormComponent).filter(M.FormComponent.form_id == f["id"]).all()
        assert rows and all(c.board_id == bid for c in rows)


def test_the_database_refuses_a_status_or_access_it_does_not_know(client):
    """CHECK constraints, which SQLite enforces even though it ignores FKs."""
    bid = _board(client, "ערכים סגורים")
    f = _form(client, bid)
    assert _save(client, f["id"], status="LIVE").status_code == 400
    assert _save(client, f["id"], access="EVERYONE").status_code == 400
    with Session(cityos_main.engine) as db:
        row = db.query(M.FormView).filter(M.FormView.id == f["id"]).first()
        row.status = "LIVE"
        with pytest.raises(Exception):
            db.commit()
        db.rollback()


def test_a_content_component_binds_to_nothing(client):
    bid = _board(client, "תוכן")
    f = _form(client, bid)
    assert _save(client, f["id"], components=[
        {"kind": "heading", "content": "כותרת", "field_key": "title"}]).status_code == 200
    got = client.get(f"/api/forms/{f['id']}", headers=AS(ADMIN)).json()
    assert got["components"][0]["kind"] == "heading"
    assert "field_key" not in got["components"][0]
    with Session(cityos_main.engine) as db:
        assert db.query(M.FormComponent).filter(
            M.FormComponent.form_id == f["id"]).first().field_key is None


def test_the_same_field_cannot_be_asked_twice_in_one_form(client):
    bid = _board(client, "כפילות")
    f = _form(client, bid)
    r = _save(client, f["id"], components=[
        {"kind": "question", "field_key": "title", "label": "פעם"},
        {"kind": "question", "field_key": "title", "label": "פעמיים"},
    ])
    assert r.status_code == 400
    assert "יותר מפעם אחת" in r.json()["detail"]


def test_a_hidden_question_cannot_be_required(client):
    """A state nothing can satisfy is not a state worth saving."""
    bid = _board(client, "מוסתר וחובה")
    f = _form(client, bid)
    r = _save(client, f["id"], components=[
        {"kind": "question", "field_key": "title", "label": "סמוי",
         "required": True, "visible": False}])
    assert r.status_code == 400
    assert "מוסתרת" in r.json()["detail"]


# ── עיצוב, מסך הצלחה, הגשה ───────────────────────────────────────────

def test_design_and_success_settings_round_trip_and_stay_apart(client):
    bid = _board(client, "עיצוב")
    a, b = _form(client, bid, "כחול"), _form(client, bid, "ירוק")
    assert _save(client, a["id"], theme_color="#0073ea", font_family="Rubik",
                 font_size="large", text_align="right", show_logo=True,
                 success_title="תודה", success_message="נחזור אליך",
                 success_allow_another=True).status_code == 200
    assert _save(client, b["id"], theme_color="#00c875", font_size="small",
                 text_align="center", success_title="נקלט").status_code == 200

    ja = client.get(f"/api/forms/{a['id']}", headers=AS(ADMIN)).json()
    jb = client.get(f"/api/forms/{b['id']}", headers=AS(ADMIN)).json()
    assert ja["design"]["theme_color"] == "#0073ea"
    assert ja["design"]["font_size"] == "large" and ja["design"]["text_align"] == "right"
    assert ja["success"] == {"title": "תודה", "message": "נחזור אליך",
                             "allow_another": True, "redirect_url": None}
    assert jb["design"]["theme_color"] == "#00c875"
    assert jb["design"]["font_size"] == "small" and jb["design"]["text_align"] == "center"
    assert jb["success"]["allow_another"] is False


def test_design_values_are_validated(client):
    bid = _board(client, "ולידציה")
    f = _form(client, bid)
    assert _save(client, f["id"], theme_color="red").status_code == 400
    assert _save(client, f["id"], font_size="huge").status_code == 400
    assert _save(client, f["id"], text_align="justify").status_code == 400
    # a redirect is a link a stranger follows — only http(s)
    assert _save(client, f["id"],
                 success_redirect_url="javascript:alert(1)").status_code == 400
    assert _save(client, f["id"],
                 success_redirect_url="https://hod-hasharon.muni.il").status_code == 200


def test_submission_time_and_submitter_have_a_place(client):
    """No submissions table: the record IS the submission.

    `created_at` is when it was sent, `created_by` is who sent it, and
    `form_view_id` — the fact the item did not already carry — is which form
    it came through. `record_submitter` is the "כאשר נדרש".
    """
    assert M.Task.__table__.c.form_view_id.nullable is True
    bid = _board(client, "הגשה")
    f = _form(client, bid)
    assert client.get(f"/api/forms/{f['id']}",
                      headers=AS(ADMIN)).json()["record_submitter"] is True
    assert _save(client, f["id"], record_submitter=False).status_code == 200
    assert client.get(f"/api/forms/{f['id']}",
                      headers=AS(ADMIN)).json()["record_submitter"] is False

    item = client.post("/api/tasks", json={"board_id": bid, "title": "ידני",
                                           "user_id": ADMIN}).json()["id"]
    with Session(cityos_main.engine) as db:
        t = db.query(M.Task).filter(M.Task.id == item).first()
        assert t.form_view_id is None           # nothing made the ordinary way
        t.form_view_id = f["id"]
        db.commit()
        t = db.query(M.Task).filter(M.Task.id == item).first()
        assert t.form_view_id == f["id"]
        assert t.created_at is not None and t.created_by == ADMIN


# ── הטופס כתצוגה, ומה שהוא עדיין לא ─────────────────────────────────

def test_a_form_is_a_view_row_of_its_board(client):
    bid = _board(client, "תצוגה")
    f = _form(client, bid, "הטופס")
    with Session(cityos_main.engine) as db:
        v = db.query(M.SavedView).filter(M.SavedView.id == f["view_id"]).first()
        assert v.kind == "form" and v.board_id == bid and v.name == "הטופס"
        assert v.filters == {}


def test_a_form_travels_with_the_board_views(client):
    """It is a view of the board — and it is not a CUT of it."""
    bid = _board(client, "רצועה")
    f = _form(client, bid, "טופס")
    strip = client.get(f"/api/boards/{bid}/views", headers=AS(ADMIN)).json()["views"]
    assert [v["name"] for v in strip] == ["טופס"]
    row = strip[0]
    assert row["kind"] == "form" and row["form_id"] == f["id"]
    assert row["form_status"] == "DRAFT"
    assert row["filters"] == {} and row["needs_fix"] == []
    # the token is a capability; a tab is not where one is handed out
    assert "public_token" not in row


def test_the_cut_endpoints_refuse_a_form(client):
    bid = _board(client, "לא חיתוך")
    f = _form(client, bid)
    vid = f["view_id"]
    assert client.patch(f"/api/views/{vid}", json={"name": "x"},
                        headers=AS(ADMIN)).status_code == 400
    assert client.post(f"/api/views/{vid}/duplicate", json={},
                       headers=AS(ADMIN)).status_code == 400


def test_a_form_name_is_unique_on_its_board_like_any_tab(client):
    bid = _board(client, "שמות")
    _form(client, bid, "פנייה")
    r = client.post(f"/api/boards/{bid}/forms", json={"name": "פנייה"}, headers=AS(ADMIN))
    assert r.status_code == 400
    # …and renaming onto a taken name is refused too
    other = _form(client, bid, "אחר")
    assert _save(client, other["id"], name="פנייה").status_code == 400
    assert _save(client, other["id"], name="חדש").status_code == 200


def test_publishing_stamps_who_and_when_and_picks_a_landing_group(client):
    bid = _board(client, "פרסום")
    f = _form(client, bid)
    assert f["status"] == "DRAFT" and f["published_at"] is None
    r = _save(client, f["id"], status="PUBLISHED")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "PUBLISHED"
    assert got["published_at"] and got["published_by"] == ADMIN
    assert got["target_group_id"] is not None
    assert _save(client, f["id"], status="DISABLED").json()["status"] == "DISABLED"
    # the board log records the move, and records what it moved FROM
    import models as _M
    from sqlalchemy.orm import Session as _S
    with _S(cityos_main.engine) as db:
        rows = (db.query(_M.AuditLog)
                  .filter(_M.AuditLog.entity_type == "saved_view",
                          _M.AuditLog.entity_id == f["view_id"],
                          _M.AuditLog.action == "form_status").all())
        assert [(r.old_value, r.new_value) for r in rows] == [
            ("DRAFT", "PUBLISHED"), ("PUBLISHED", "DISABLED")]


def test_a_save_moves_the_configuration_version(client):
    bid = _board(client, "גרסה")
    f = _form(client, bid)
    before = f["config_version"]
    after = _save(client, f["id"], display_title="שלום").json()["config_version"]
    assert after > before


# ── הגירה מהמנגנון הישן ──────────────────────────────────────────────

def test_the_old_board_setting_becomes_a_form_view(client):
    """`board.settings["form"]` was one form per board and four flags a field.

    The label is copied from the column as the rows are written — the one
    irreversible step, and the point of the whole exercise: from here on,
    renaming the column renames the column and not the question.
    """
    bid = _board(client, "הגירה")
    addr = _col(client, bid, "כתובת")
    gone = _col(client, bid, "עמודה שתימחק")
    with Session(cityos_main.engine) as db:
        b = db.query(M.Board).filter(M.Board.id == bid).first()
        s = dict(b.settings or {})
        s["form"] = {"fields": [
            {"key": "title", "required": True, "visible": True},
            {"key": addr, "required": False, "visible": True, "min": "2026-01-01"},
            {"key": "status", "required": True, "visible": False},   # unsendable
            {"key": "col_not_here", "required": False, "visible": True},
            {"key": addr, "required": True, "visible": True},        # a repeat
        ]}
        b.settings = s
        db.commit()
    # the column one of the questions names goes away before the migration runs
    cols = [c for c in client.get(f"/api/boards/{bid}").json()["columns"] if c["id"] != gone]
    client.patch(f"/api/boards/{bid}", json={"actor_id": ADMIN, "columns": cols})

    cityos_main._migrate_board_forms()

    forms = client.get(f"/api/boards/{bid}/forms", headers=AS(ADMIN)).json()["forms"]
    assert len(forms) == 1
    f = client.get(f"/api/forms/{forms[0]['id']}", headers=AS(ADMIN)).json()
    # it was reachable before, so it is reachable after
    assert f["status"] == "PUBLISHED" and f["access"] == "AUTHENTICATED"
    assert f["target_group_id"] is not None

    comps = f["components"]
    assert [c["field_key"] for c in comps] == ["title", addr, "status"]
    assert [c["position"] for c in comps] == [0, 1, 2]
    # the wording is stored now, taken from the column at this moment
    assert comps[0]["label"] == "שם הפריט" and comps[1]["label"] == "כתובת"
    assert comps[1]["settings"] == {"min": "2026-01-01"}
    # hidden and required together was unsendable; the visible half wins
    assert comps[2]["visible"] is False and comps[2]["required"] is False
    # a field the board no longer has is dropped, not carried across
    assert all(c["field_key"] != "col_not_here" for c in comps)

    with Session(cityos_main.engine) as db:
        b = db.query(M.Board).filter(M.Board.id == bid).first()
        assert "form" not in (b.settings or {}), "the old key survived the migration"

    # running again finds nothing to do
    cityos_main._migrate_board_forms()
    assert len(client.get(f"/api/boards/{bid}/forms", headers=AS(ADMIN)).json()["forms"]) == 1


def test_the_board_no_longer_carries_a_form_in_its_payload(client):
    bid = _board(client, "בלי מפתח")
    assert "form" not in client.get(f"/api/boards/{bid}").json()
    # and the old write door is closed
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": ADMIN, "form": {"fields": []}})
    assert r.status_code == 200          # ignored, not an error
    with Session(cityos_main.engine) as db:
        b = db.query(M.Board).filter(M.Board.id == bid).first()
        assert "form" not in (b.settings or {})
