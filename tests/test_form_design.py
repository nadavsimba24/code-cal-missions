"""הגדרות העיצוב של תצוגת טופס — לכל טופס לעצמו, ובמנגנון תצוגה אחד.

Design belongs to the FORM. Two forms on one board are two different-looking
forms and the board has nothing to say about either; the settings live on the
form's own row and are copied nowhere.

What a form may choose is closed. Three sizes, three alignments, three
emphases, three heading levels, and the product's own typeface — "אין להוסיף
בחירת גופן חופשית, גדלים חופשיים, CSS מותאם אישית". A form cannot hold a value
the stylesheet has no rule for, because the server will not store one.

The branding switch is the one setting that is not a preference: taking the
product's name off a page somebody outside the organisation will read is an
entitlement, and it is checked where it is spent.
"""
import pytest

import main as cityos_main
import models as M

AS = lambda uid: {"X-CityOS-User": str(uid)}


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


def _design(client, fid, uid):
    return client.get(f"/api/forms/{fid}", headers=AS(uid)).json()["design"]


# ── תנאי קבלה: שני טפסים באותו לוח נראים שונה ────────────────────────

def test_two_forms_on_one_board_can_look_nothing_alike(client, admin_id):
    bid = _board(client, admin_id, "שני מראות")
    a, b = _form(client, bid, admin_id), _form(client, bid, admin_id)
    assert _set(client, a["id"], admin_id,
                display_title="פנייה דחופה", display_description="נחזור היום",
                theme_color="#e2445c", background_color="#fff5f6",
                font_size="large", text_align="center",
                submit_label="שלחו עכשיו").status_code == 200
    assert _set(client, b["id"], admin_id,
                display_title="בקשה רגילה", theme_color="#00c875",
                font_size="small", text_align="right").status_code == 200

    da, db_ = _design(client, a["id"], admin_id), _design(client, b["id"], admin_id)
    assert da["display_title"] == "פנייה דחופה" and db_["display_title"] == "בקשה רגילה"
    assert da["theme_color"] == "#e2445c" and db_["theme_color"] == "#00c875"
    assert da["background_color"] == "#fff5f6" and db_["background_color"] == "#ffffff"
    assert da["font_size"] == "large" and db_["font_size"] == "small"
    assert da["text_align"] == "center" and db_["text_align"] == "right"
    assert da["submit_label"] == "שלחו עכשיו" and db_["submit_label"] == ""

    # a reload is the same answer — the settings are on the row, not in a session
    assert _design(client, a["id"], admin_id) == da
    assert _design(client, b["id"], admin_id) == db_


def test_the_board_has_no_say_in_how_a_form_looks(client, admin_id):
    bid = _board(client, admin_id, "לא בלוח")
    f = _form(client, bid, admin_id)
    _set(client, f["id"], admin_id, theme_color="#123456", submit_label="קדימה")
    board = client.get(f"/api/boards/{bid}").json()
    assert "form" not in board
    flat = str(board)
    assert "#123456" not in flat and "קדימה" not in flat


# ── מה שאפשר לבחור, ומה שלא ──────────────────────────────────────────

def test_the_choices_are_closed(client, admin_id):
    bid = _board(client, admin_id, "ערכים סגורים")
    f = _form(client, bid, admin_id)
    for body, why in (
        ({"font_size": "24px"}, "a free size"),
        ({"font_size": "huge"}, "a size nothing has a rule for"),
        ({"text_align": "justify"}, "an alignment outside the three"),
        ({"theme_color": "rgb(1,2,3)"}, "a colour that is not a hex"),
        ({"background_color": "transparent"}, "a background that is not a colour"),
    ):
        assert _set(client, f["id"], admin_id, **body).status_code == 400, why
    # and the long way round is closed too: there is no custom-css field
    assert _set(client, f["id"], admin_id, custom_css="body{display:none}").status_code == 200
    assert "custom_css" not in _design(client, f["id"], admin_id)


def test_a_form_does_not_pick_a_typeface(client, admin_id):
    """One font stack for the product — Figtree and Rubik. Not a setting."""
    bid = _board(client, admin_id, "גופן")
    f = _form(client, bid, admin_id)
    assert "font_family" not in _design(client, f["id"], admin_id)
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    assert "font_family" not in pub["design"]


def test_alignment_starts_at_the_direction_the_product_is_written_in(client, admin_id):
    bid = _board(client, admin_id, "כיוון")
    f = _form(client, bid, admin_id)
    assert _design(client, f["id"], admin_id)["text_align"] == "right"


def test_the_submit_label_is_a_button_not_a_paragraph(client, admin_id):
    bid = _board(client, admin_id, "כפתור")
    f = _form(client, bid, admin_id)
    assert _set(client, f["id"], admin_id, submit_label="x" * 41).status_code == 400
    assert _set(client, f["id"], admin_id, submit_label="שלח בקשה").status_code == 200
    assert _design(client, f["id"], admin_id)["submit_label"] == "שלח בקשה"


# ── עיצוב ברמת הרכיב ─────────────────────────────────────────────────

def test_content_blocks_carry_emphasis_and_a_heading_a_level(client, admin_id):
    bid = _board(client, admin_id, "סגנון רכיב")
    f = _form(client, bid, admin_id)
    h = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "heading", "content": "כותרת",
                          "settings": {"style": "bold", "level": 1}},
                    headers=AS(admin_id))
    assert h.status_code == 200, h.text
    assert h.json()["settings"] == {"style": "bold", "level": 1}
    t = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "text", "content": "הסבר",
                          "settings": {"style": "italic"}}, headers=AS(admin_id))
    assert t.json()["settings"] == {"style": "italic"}
    # normal is the absence of emphasis, not a value to store
    r = client.patch(f"/api/forms/{f['id']}/components/{t.json()['id']}",
                     json={"settings": {"style": "normal"}}, headers=AS(admin_id))
    assert r.json()["settings"] == {}


def test_a_block_cannot_be_styled_in_a_way_the_stylesheet_has_no_rule_for(client, admin_id):
    bid = _board(client, admin_id, "סגנון סגור")
    f = _form(client, bid, admin_id)
    for settings, why in (({"style": "underline"}, "an emphasis outside the three"),
                          ({"level": 7}, "a heading level with no size"),
                          ({"level": 0}, "a level below the range")):
        r = client.post(f"/api/forms/{f['id']}/components",
                        json={"kind": "heading", "content": "כ", "settings": settings},
                        headers=AS(admin_id))
        assert r.status_code == 400, why
    # a setting that belongs to a question is not a setting a heading keeps
    r = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "heading", "content": "כ",
                          "settings": {"style": "bold", "min": "2026-01-01"}},
                    headers=AS(admin_id))
    assert r.status_code == 200 and r.json()["settings"] == {"style": "bold", "level": 2}


# ── מיתוג ────────────────────────────────────────────────────────────

def test_the_branding_comes_off_only_with_the_entitlement(client, admin_id, member_id):
    bid = _board(client, admin_id, "מיתוג")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "admin"})
    f = _form(client, bid, admin_id)
    assert _design(client, f["id"], admin_id)["show_branding"] is True

    # a board admin who is not entitled is refused, and told why
    r = _set(client, f["id"], member_id, show_branding=False)
    assert r.status_code == 403 and "מיתוג" in r.json()["detail"]
    assert _design(client, f["id"], admin_id)["show_branding"] is True
    # …and the screen is told not to offer it
    assert client.get(f"/api/forms/{f['id']}",
                      headers=AS(member_id)).json()["can_hide_branding"] is False

    # a system admin is entitled, always
    assert _set(client, f["id"], admin_id, show_branding=False).status_code == 200
    assert _design(client, f["id"], admin_id)["show_branding"] is False
    assert client.get(f"/api/forms/{f['id']}",
                      headers=AS(admin_id)).json()["can_hide_branding"] is True
    # putting it back is nobody's to be stopped from
    assert _set(client, f["id"], member_id, show_branding=True).status_code == 200


def test_the_entitlement_is_the_systems_own(client, admin_id):
    """Granted per role in the permissions matrix, like every other one."""
    assert "hide_form_branding" in cityos_main.CAPABILITIES
    assert cityos_main.CAP_HE.get("hide_form_branding")


# ── אותו עיצוב בכל שלושת המקומות ─────────────────────────────────────

def test_the_published_shape_carries_everything_the_editor_shows(client, admin_id):
    """One renderer draws the editor, the preview and the published page, so
    the public answer has to carry every setting that renderer reads."""
    bid = _board(client, admin_id, "שלושה מקומות")
    f = _form(client, bid, admin_id)
    _set(client, f["id"], admin_id, display_title="דברו איתנו",
         display_description="נחזור תוך יומיים", theme_color="#e2445c",
         background_color="#fff5f6", text_color="#1f1f1f",
         font_size="large", text_align="center", submit_label="שלחו")
    client.post(f"/api/forms/{f['id']}/components",
                json={"kind": "heading", "content": "פרטים",
                      "settings": {"style": "bold", "level": 1}}, headers=AS(admin_id))

    mgr = _design(client, f["id"], admin_id)
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    for k in ("display_title", "display_description", "theme_color",
              "background_color", "text_color", "font_size", "text_align",
              "submit_label", "show_branding", "logo_token"):
        assert k in pub["design"], f"the published form is not told {k}"
        assert pub["design"][k] == mgr[k], k
    # a block's own emphasis travels too, or the published page is a near-miss
    assert pub["components"][0]["settings"] == {"style": "bold", "level": 1}


def test_a_hidden_logo_is_not_sent_at_all(client, admin_id):
    bid = _board(client, admin_id, "לוגו")
    f = _form(client, bid, admin_id)
    _set(client, f["id"], admin_id, logo_token="abc123", show_logo=True)
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    assert pub["design"]["logo_token"] == "abc123"
    _set(client, f["id"], admin_id, show_logo=False)
    pub = client.get(f"/api/forms/{f['id']}/preview", headers=AS(admin_id)).json()
    assert pub["design"]["logo_token"] is None
    # the manager keeps it, so turning it back on does not lose the upload
    assert _design(client, f["id"], admin_id)["logo_token"] == "abc123"
