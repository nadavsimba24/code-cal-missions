"""פעולות השרת לניהול תצוגת טופס — מי רשאי, מה חוזר, ומה לא.

The management side of a form: making one, loading it, renaming it, building
its list of components, and taking it away. All of it goes through the
board's own permissions, which is the point — there is no second permission
model here, only the board's read at the two levels it already has:

    editor  builds the form      (the right that puts a tab on the board)
    admin   publishes it         (the right that changes the board's exposure)
    viewer  neither, and cannot read the management side either

And the other separation, which is not about roles at all: what a manager is
shown and what a respondent will be shown are two different payloads, built
by two different functions, so the column ids, the board id and the hidden
questions cannot travel by being forgotten about.
"""
from sqlalchemy.orm import Session

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}
ANON = {"X-CityOS-User": ""}


def _board(client, admin_id, name):
    r = client.post("/api/boards", json={"name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _member(client, bid, admin_id, uid, role):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _col(client, bid, admin_id, title, ctype="text"):
    cols = [dict(c) for c in client.get(f"/api/boards/{bid}").json()["columns"]]
    cols.append({"type": ctype, "title": title})
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    after = client.get(f"/api/boards/{bid}").json()["columns"]
    return [c["id"] for c in after if c.get("title") == title][0]


def _form(client, bid, uid, name=None):
    r = client.post(f"/api/boards/{bid}/forms",
                    json={"name": name} if name else {}, headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _comps(client, fid, uid):
    return client.get(f"/api/forms/{fid}", headers=AS(uid)).json()["components"]


# ── יצירה ────────────────────────────────────────────────────────────

def test_a_new_form_is_a_draft_called_the_default_name(client, admin_id):
    bid = _board(client, admin_id, "יצירה")
    f = _form(client, bid, admin_id)
    assert f["name"] == "טופס חדש"
    assert f["status"] == "DRAFT"
    assert f["access"] == "AUTHENTICATED"
    assert f["published_at"] is None and f["published_by"] is None
    # no public address until it is published — see _public_form_or_refuse
    assert f["public_token"] is None and f["public_url"] is None
    assert f["components"] == []


def test_the_second_default_name_is_numbered_rather_than_refused(client, admin_id):
    bid = _board(client, admin_id, "שם תפוס")
    assert _form(client, bid, admin_id)["name"] == "טופס חדש"
    second = _form(client, bid, admin_id)["name"]
    assert second != "טופס חדש" and second.startswith("טופס חדש")


# ── טעינה ועדכון ─────────────────────────────────────────────────────

def test_a_form_loads_for_management_with_everything_on_it(client, admin_id):
    bid = _board(client, admin_id, "טעינה")
    f = _form(client, bid, admin_id, "פנייה")
    got = client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).json()
    for key in ("id", "view_id", "board_id", "name", "status", "access",
                "public_token", "target_group_id", "design", "success",
                "record_submitter", "config_version", "components"):
        assert key in got, key
    assert got["name"] == "פנייה" and got["board_id"] == bid


def test_name_and_settings_update_together(client, admin_id):
    bid = _board(client, admin_id, "עדכון")
    f = _form(client, bid, admin_id)
    r = client.patch(f"/api/forms/{f['id']}",
                     json={"name": "פניות תושבים", "display_title": "דברו איתנו",
                           "theme_color": "#00c875", "success_title": "תודה"},
                     headers=AS(admin_id))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["name"] == "פניות תושבים"
    assert got["design"]["display_title"] == "דברו איתנו"
    assert got["design"]["theme_color"] == "#00c875"
    assert got["success"]["title"] == "תודה"
    # and the untouched settings stood still
    assert got["design"]["text_align"] == "right"


# ── רכיבים: הוספה, עדכון, הסרה, סדר ─────────────────────────────────

def test_components_are_added_updated_removed_and_reordered(client, admin_id):
    bid = _board(client, admin_id, "רכיבים")
    addr = _col(client, bid, admin_id, "כתובת")
    f = _form(client, bid, admin_id)
    fid = f["id"]

    head = client.post(f"/api/forms/{fid}/components",
                       json={"kind": "heading", "content": "פרטים"},
                       headers=AS(admin_id))
    assert head.status_code == 200, head.text
    q1 = client.post(f"/api/forms/{fid}/components",
                     json={"kind": "question", "field_key": "title",
                           "label": "נושא", "required": True},
                     headers=AS(admin_id)).json()
    q2 = client.post(f"/api/forms/{fid}/components",
                     json={"kind": "question", "field_key": addr,
                           "label": "כתובת"}, headers=AS(admin_id)).json()
    head = head.json()
    assert [c["position"] for c in _comps(client, fid, admin_id)] == [0, 1, 2]

    # insert at a position, and everything after it moves down
    note = client.post(f"/api/forms/{fid}/components",
                       json={"kind": "text", "content": "שדה חובה מסומן בכוכבית",
                             "position": 1}, headers=AS(admin_id)).json()
    assert [c["id"] for c in _comps(client, fid, admin_id)] == \
        [head["id"], note["id"], q1["id"], q2["id"]]

    # update one, and only it
    r = client.patch(f"/api/forms/{fid}/components/{q2['id']}",
                     json={"label": "היכן?", "placeholder": "הרצל 1"},
                     headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "היכן?" and r.json()["placeholder"] == "הרצל 1"
    assert r.json()["field_key"] == addr        # not named, not changed
    assert [c for c in _comps(client, fid, admin_id)
            if c["id"] == q1["id"]][0]["label"] == "נושא"

    # reorder by id
    r = client.put(f"/api/forms/{fid}/components/order",
                   json={"order": [q2["id"], q1["id"]]}, headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert [c["id"] for c in _comps(client, fid, admin_id)] == \
        [q2["id"], q1["id"], head["id"], note["id"]]

    # remove one, and the positions close up behind it
    assert client.delete(f"/api/forms/{fid}/components/{note['id']}",
                         headers=AS(admin_id)).status_code == 200
    after = _comps(client, fid, admin_id)
    assert [c["id"] for c in after] == [q2["id"], q1["id"], head["id"]]
    assert [c["position"] for c in after] == [0, 1, 2]


def test_a_component_operation_is_held_to_the_same_rules_as_a_bulk_save(client, admin_id):
    bid = _board(client, admin_id, "חוקי רכיב")
    other = _board(client, admin_id, "לוח זר")
    theirs = _col(client, other, admin_id, "שלהם")
    f = _form(client, bid, admin_id)
    fid = f["id"]

    # a field of another board
    assert client.post(f"/api/forms/{fid}/components",
                       json={"kind": "question", "field_key": theirs, "label": "x"},
                       headers=AS(admin_id)).status_code == 400
    # the same field twice
    q = client.post(f"/api/forms/{fid}/components",
                    json={"kind": "question", "field_key": "title", "label": "א"},
                    headers=AS(admin_id)).json()
    assert client.post(f"/api/forms/{fid}/components",
                       json={"kind": "question", "field_key": "title", "label": "ב"},
                       headers=AS(admin_id)).status_code == 400
    # hidden and required at once
    assert client.patch(f"/api/forms/{fid}/components/{q['id']}",
                        json={"required": True, "visible": False},
                        headers=AS(admin_id)).status_code == 400
    # …and a PATCH onto its own field is not a duplicate of itself
    assert client.patch(f"/api/forms/{fid}/components/{q['id']}",
                        json={"field_key": "title", "label": "ג"},
                        headers=AS(admin_id)).status_code == 200
    # a component of another form is not this form's to touch
    g = _form(client, bid, admin_id)
    assert client.patch(f"/api/forms/{g['id']}/components/{q['id']}",
                        json={"label": "גנוב"}, headers=AS(admin_id)).status_code == 404
    assert client.delete(f"/api/forms/{g['id']}/components/{q['id']}",
                         headers=AS(admin_id)).status_code == 404


def test_turning_a_question_into_a_heading_releases_its_field(client, admin_id):
    bid = _board(client, admin_id, "המרה")
    f = _form(client, bid, admin_id)
    q = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": "title", "label": "נושא"},
                    headers=AS(admin_id)).json()
    r = client.patch(f"/api/forms/{f['id']}/components/{q['id']}",
                     json={"kind": "heading", "content": "כותרת"}, headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert "field_key" not in r.json()
    # the field is free again
    assert client.post(f"/api/forms/{f['id']}/components",
                       json={"kind": "question", "field_key": "title", "label": "נושא"},
                       headers=AS(admin_id)).status_code == 200


# ── תנאי קבלה: שינוי בטופס אחד אינו משנה טופס אחר ───────────────────

def test_every_component_operation_leaves_the_other_form_alone(client, admin_id):
    bid = _board(client, admin_id, "שני טפסים")
    addr = _col(client, bid, admin_id, "כתובת")
    a = _form(client, bid, admin_id, "א")
    b = _form(client, bid, admin_id, "ב")
    for fid in (a["id"], b["id"]):
        client.patch(f"/api/forms/{fid}",
                     json={"components": [
                         {"kind": "question", "field_key": "title", "label": "נושא"},
                         {"kind": "question", "field_key": addr, "label": "כתובת"}]},
                     headers=AS(admin_id))
    before = _comps(client, b["id"], admin_id)

    qa = _comps(client, a["id"], admin_id)
    client.patch(f"/api/forms/{a['id']}/components/{qa[0]['id']}",
                 json={"label": "שונה"}, headers=AS(admin_id))
    client.delete(f"/api/forms/{a['id']}/components/{qa[1]['id']}", headers=AS(admin_id))
    client.post(f"/api/forms/{a['id']}/components",
                json={"kind": "text", "content": "חדש"}, headers=AS(admin_id))
    client.patch(f"/api/forms/{a['id']}", json={"name": "א׳", "theme_color": "#e2445c"},
                 headers=AS(admin_id))

    assert _comps(client, b["id"], admin_id) == before
    jb = client.get(f"/api/forms/{b['id']}", headers=AS(admin_id)).json()
    assert jb["name"] == "ב" and jb["design"]["theme_color"] == "#0073ea"


# ── הרשאות ───────────────────────────────────────────────────────────

def test_an_editor_may_manage_a_form_and_a_viewer_may_not(client, admin_id,
                                                          member_id, guinea_id):
    bid = _board(client, admin_id, "הרשאות")
    _member(client, bid, admin_id, member_id, "editor")
    _member(client, bid, admin_id, guinea_id, "viewer")

    f = _form(client, bid, member_id)              # an editor creates one
    fid = f["id"]
    assert client.get(f"/api/forms/{fid}", headers=AS(member_id)).status_code == 200
    assert client.patch(f"/api/forms/{fid}", json={"name": "של העורך"},
                        headers=AS(member_id)).status_code == 200
    assert client.post(f"/api/forms/{fid}/components",
                       json={"kind": "question", "field_key": "title", "label": "נושא"},
                       headers=AS(member_id)).status_code == 200

    # a viewer cannot read the management side, let alone change it
    assert client.post(f"/api/boards/{bid}/forms", json={},
                       headers=AS(guinea_id)).status_code == 403
    assert client.get(f"/api/boards/{bid}/forms", headers=AS(guinea_id)).status_code == 403
    assert client.get(f"/api/forms/{fid}", headers=AS(guinea_id)).status_code == 403
    assert client.get(f"/api/forms/{fid}/preview", headers=AS(guinea_id)).status_code == 403
    assert client.patch(f"/api/forms/{fid}", json={"name": "לא"},
                        headers=AS(guinea_id)).status_code == 403
    assert client.post(f"/api/forms/{fid}/components", json={"kind": "text"},
                       headers=AS(guinea_id)).status_code == 403
    assert client.put(f"/api/forms/{fid}/components/order", json={"order": []},
                      headers=AS(guinea_id)).status_code == 403
    assert client.delete(f"/api/forms/{fid}", headers=AS(guinea_id)).status_code == 403
    assert client.get(f"/api/forms/{fid}", headers=AS(admin_id)).json()["name"] == "של העורך"


def test_somebody_who_is_not_on_the_board_reaches_none_of_it(client, admin_id, guinea_id):
    """A direct request, with no screen that drew it and nothing filtered out."""
    bid = _board(client, admin_id, "לא חבר")
    f = _form(client, bid, admin_id)
    fid, cid = f["id"], None
    cid = client.post(f"/api/forms/{fid}/components",
                      json={"kind": "question", "field_key": "title", "label": "נושא"},
                      headers=AS(admin_id)).json()["id"]
    for call in (
        lambda: client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(guinea_id)),
        lambda: client.get(f"/api/boards/{bid}/forms", headers=AS(guinea_id)),
        lambda: client.get(f"/api/forms/{fid}", headers=AS(guinea_id)),
        lambda: client.get(f"/api/forms/{fid}/preview", headers=AS(guinea_id)),
        lambda: client.patch(f"/api/forms/{fid}", json={"name": "x"}, headers=AS(guinea_id)),
        lambda: client.post(f"/api/forms/{fid}/components",
                            json={"kind": "text"}, headers=AS(guinea_id)),
        lambda: client.patch(f"/api/forms/{fid}/components/{cid}",
                             json={"label": "x"}, headers=AS(guinea_id)),
        lambda: client.delete(f"/api/forms/{fid}/components/{cid}", headers=AS(guinea_id)),
        lambda: client.put(f"/api/forms/{fid}/components/order",
                           json={"order": []}, headers=AS(guinea_id)),
        lambda: client.delete(f"/api/forms/{fid}", headers=AS(guinea_id)),
    ):
        assert call().status_code == 403
    # and with no identity at all, the middleware answers first
    assert client.get(f"/api/forms/{fid}", headers=ANON).status_code == 401


def test_publishing_and_access_are_the_admins(client, admin_id, member_id):
    """An editor builds the form; exposing the board is not theirs to do."""
    bid = _board(client, admin_id, "פרסום")
    _member(client, bid, admin_id, member_id, "editor")
    f = _form(client, bid, member_id)
    fid = f["id"]
    r = client.patch(f"/api/forms/{fid}", json={"status": "PUBLISHED"},
                     headers=AS(member_id))
    assert r.status_code == 403 and "מנהל הלוח" in r.json()["detail"]
    assert client.patch(f"/api/forms/{fid}", json={"access": "PUBLIC_LINK"},
                        headers=AS(member_id)).status_code == 403
    # the editor's own edits still go through in the same request shape
    assert client.patch(f"/api/forms/{fid}", json={"display_title": "שלום"},
                        headers=AS(member_id)).status_code == 200
    # and an admin may do all of it
    r = client.patch(f"/api/forms/{fid}",
                     json={"status": "PUBLISHED", "access": "PUBLIC_LINK"},
                     headers=AS(admin_id))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PUBLISHED" and r.json()["access"] == "PUBLIC_LINK"
    assert r.json()["published_by"] == admin_id
    # a status that does not change is not an exposure change
    assert client.patch(f"/api/forms/{fid}", json={"status": "PUBLISHED"},
                        headers=AS(member_id)).status_code == 200


# ── תצוגות הטופס כחלק מתצוגות הלוח ──────────────────────────────────

def test_forms_come_back_with_the_board_views(client, admin_id, member_id, guinea_id):
    bid = _board(client, admin_id, "רצועה")
    _member(client, bid, admin_id, member_id, "editor")
    _member(client, bid, admin_id, guinea_id, "viewer")
    cut = client.post(f"/api/boards/{bid}/views",
                      json={"name": "חיתוך", "actor_id": admin_id}).json()
    f = _form(client, bid, admin_id, "טופס")

    rows = client.get(f"/api/boards/{bid}/views", headers=AS(admin_id)).json()["views"]
    by_kind = {v["kind"]: v for v in rows}
    assert set(by_kind) == {"saved", "form"}
    assert by_kind["saved"]["id"] == cut["id"]
    assert by_kind["form"]["form_id"] == f["id"]
    assert by_kind["form"]["form_status"] == "DRAFT"
    assert by_kind["form"]["form_access"] == "AUTHENTICATED"
    # a form is not a cut: nothing to duplicate, nothing to fix, no filters
    assert by_kind["form"]["can_duplicate"] is False
    assert by_kind["form"]["filters"] == {}
    assert "public_token" not in by_kind["form"]

    # can_edit on a form follows the BOARD, not who happened to make it
    def mine(uid):
        return {v["kind"]: v for v in client.get(f"/api/boards/{bid}/views",
                                                 headers=AS(uid)).json()["views"]}
    assert mine(member_id)["form"]["can_edit"] is True
    assert mine(guinea_id)["form"]["can_edit"] is False
    # the same answer the board already gives for a cut — an editor edits the
    # board's tabs, whoever made them, and a viewer edits none of them
    assert mine(member_id)["saved"]["can_edit"] is True
    assert mine(guinea_id)["saved"]["can_edit"] is False


def test_the_cut_endpoints_still_refuse_a_form(client, admin_id):
    bid = _board(client, admin_id, "לא חיתוך")
    f = _form(client, bid, admin_id)
    vid = f["view_id"]
    assert client.patch(f"/api/views/{vid}", json={"name": "x"},
                        headers=AS(admin_id)).status_code == 400
    assert client.post(f"/api/views/{vid}/duplicate", json={},
                       headers=AS(admin_id)).status_code == 400
    # and it is not somewhere a reader lands
    assert client.put(f"/api/boards/{bid}/views/last", json={"view_id": vid},
                      headers=AS(admin_id)).json()["last_view_id"] is None


# ── מנהל מול משיב ────────────────────────────────────────────────────

def test_the_respondent_payload_is_not_the_manager_payload(client, admin_id):
    bid = _board(client, admin_id, "הפרדה")
    addr = _col(client, bid, admin_id, "כתובת")
    pick = _col(client, bid, admin_id, "סוג פנייה", "dropdown")
    cols = [dict(c) for c in client.get(f"/api/boards/{bid}").json()["columns"]]
    for c in cols:
        if c["id"] == pick:
            c["options"] = ["תאורה", "ניקיון"]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})

    f = _form(client, bid, admin_id, "פנייה")
    fid = f["id"]
    client.patch(f"/api/forms/{fid}", json={
        "display_title": "דברו איתנו", "success_title": "תודה",
        "components": [
            {"kind": "heading", "content": "פרטים"},
            {"kind": "question", "field_key": "title", "label": "נושא", "required": True},
            {"kind": "question", "field_key": addr, "label": "כתובת",
             "placeholder": "הרצל 1"},
            {"kind": "question", "field_key": pick, "label": "סוג"},
            {"kind": "question", "field_key": "assignees", "label": "אחראי"},
            {"kind": "question", "field_key": "status", "label": "סטטוס",
             "visible": False},
        ]}, headers=AS(admin_id))

    pub = client.get(f"/api/forms/{fid}/preview", headers=AS(admin_id)).json()
    blob = __import__("json").dumps(pub, ensure_ascii=False)

    # nothing that says what is behind the form
    for leaked in ("board_id", "view_id", "field_key", "target_group_id",
                   "published_by", "config_version", "record_submitter"):
        assert leaked not in blob, leaked
    assert addr not in blob and pick not in blob      # the real column ids
    assert "כתובת" in blob                            # the question's own words

    # the hidden question is not sent — hiding wins, and it wins here
    assert len(pub["components"]) == 5
    assert all(c.get("label") != "סטטוס" for c in pub["components"])

    # what a browser needs to draw it, and that is all
    q = {c["label"]: c for c in pub["components"] if c["kind"] == "question"}
    assert q["נושא"]["type"] == "text" and q["נושא"]["required"] is True
    assert q["כתובת"]["placeholder"] == "הרצל 1"
    assert [o["label"] for o in q["סוג"]["options"]] == ["תאורה", "ניקיון"]
    # An אחראים question is answerable, so it arrives with people in it —
    # but only because this reader is the board's own admin. The list is cut
    # to a name and an id and carries nothing else about anybody: no address,
    # no role, no avatar. Who is refused it entirely is pinned next door, in
    # test_public_form_page.test_the_member_list_still_does_not_reach_anybody_
    # the_board_does_not_know.
    assert q["אחראי"]["type"] == "people"
    who = q["אחראי"]["options"]
    assert admin_id in [o["value"] for o in who]
    assert all(set(o) == {"value", "label"} for o in who), who
    for u in client.get("/api/users", headers=AS(admin_id)).json():
        assert (u.get("email") or "@@") not in blob

    assert pub["design"]["display_title"] == "דברו איתנו"
    assert pub["success"]["title"] == "תודה"
    assert pub["token"] == f["public_token"]

    # the manager, by contrast, is shown all six and the plumbing
    mgr = client.get(f"/api/forms/{fid}", headers=AS(admin_id)).json()
    assert len(mgr["components"]) == 6
    assert mgr["board_id"] == bid and mgr["target_group_id"] is not None


def test_a_question_whose_column_was_deleted_drops_out_of_the_respondent_view(
        client, admin_id):
    bid = _board(client, admin_id, "עמודה שנמחקה")
    addr = _col(client, bid, admin_id, "כתובת")
    f = _form(client, bid, admin_id)
    client.patch(f"/api/forms/{f['id']}", json={"components": [
        {"kind": "question", "field_key": "title", "label": "נושא"},
        {"kind": "question", "field_key": addr, "label": "כתובת"}]},
        headers=AS(admin_id))
    cols = [c for c in client.get(f"/api/boards/{bid}").json()["columns"]
            if c["id"] != addr]
    # a column a form asks about is not deleted without saying so — see
    # tests/test_form_field_lifecycle.py for the rule itself
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}
                        ).status_code == 409
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols,
                              "confirm_columns": [addr]}).status_code == 200

    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    assert [c["label"] for c in pub["components"]] == ["נושא"]
    # the question is still on the manager's side, waiting to be dealt with
    mgr = client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).json()
    assert len(mgr["components"]) == 2


# ── מחיקה ────────────────────────────────────────────────────────────

def test_deleting_a_form_takes_the_tab_and_nothing_else(client, admin_id, member_id):
    bid = _board(client, admin_id, "מחיקה")
    _member(client, bid, admin_id, member_id, "editor")
    addr = _col(client, bid, admin_id, "כתובת")
    item = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                           "user_id": admin_id}).json()["id"]
    f = _form(client, bid, admin_id)
    assert client.delete(f"/api/forms/{f['id']}", headers=AS(member_id)).status_code == 200

    rows = client.get(f"/api/boards/{bid}/views", headers=AS(admin_id)).json()["views"]
    assert rows == []
    assert client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).status_code == 404
    board = client.get(f"/api/boards/{bid}").json()
    assert addr in [c["id"] for c in board["columns"]]
    assert item in [t["id"] for t in board["tasks"]]
    with Session(cityos_main.engine) as db:
        assert db.query(M.FormView).filter(M.FormView.id == f["id"]).first() is not None
