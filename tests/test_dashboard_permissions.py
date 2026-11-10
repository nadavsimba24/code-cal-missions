"""Dashboards: what is stored, who may open one, and when a widget goes dark.

Three rules are pinned here, and the third is the one that costs people data.

R09 — a save is checked against the version it was based on. Two people with
the same dashboard open must not be able to overwrite each other in silence.

R01 (ניהול) — "ראשי נגיש למורשי סביבת העבודה; פרטי למוזמנים בלבד", and a
board dashboard answers to the board's own roles because DASH-03.2 forbids
inventing new ones.

R01 (נתונים) — "אם לצופה חסרה הרשאה למקור נדרש, לרבות מקור מאחורי מראה או
נוסחה, כל הווידג׳ט ייחסם. אין להציג חישוב חלקי … שמות מקורות חסומים או מידע
שניתן להסיק ממנו כמויות וסכומים."

That last one is why half of this file is about what a blocked widget does
NOT say. A sum over four boards with one of them refused is not three
quarters of an answer — it is a wrong number wearing the clothes of a right
one, and the reader has no way to tell. The mirror and formula cases are
here because those are the two doors that do not look like doors: neither
column holds data of its own, so a check that only looked at what the widget
names directly would wave both of them through.
"""
from conftest import join_primary_env

AS = lambda uid: {"X-CityOS-User": str(uid)}


# ── setup ───────────────────────────────────────────────────────────────────

def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_col(client, bid, admin_id, col):
    cols = _cols(client, bid) + [col]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    return _cols(client, bid)[-1]


def _env(client, admin_id):
    for e in client.get("/api/environments", headers=AS(admin_id)).json()["environments"]:
        if e.get("is_primary"):
            return e["id"]
    return None


def _dash(client, admin_id, env_id, sources=(), visibility="main", name="דשבורד בדיקה"):
    r = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env_id, "name": name,
                          "visibility": visibility,
                          "sources": [{"board_id": b, "groups": None} for b in sources]})
    assert r.status_code == 200, r.text
    return r.json()


def _widget(client, admin_id, dash, **kw):
    body = {"config_version": dash["config_version"], "type": "numbers",
            "title": "מדד בדיקה", **kw}
    r = client.post(f"/api/dashboards/{dash['id']}/widgets", headers=AS(admin_id), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _read(client, uid, dash_id):
    return client.get(f"/api/dashboards/{dash_id}", headers=AS(uid))


def _state(client, uid, dash_id, widget_id):
    body = _read(client, uid, dash_id).json()
    return next(w for w in body["widgets"] if w["id"] == widget_id)


# ── DASH-02 · מה נשמר, ושמירה מוגנת בגרסה ──────────────────────────────────

def test_a_dashboard_comes_back_with_the_settings_it_was_saved_with(client, admin_id):
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח דשבורד 1")
    d = _dash(client, admin_id, env, [a])
    got = _read(client, admin_id, d["id"]).json()
    assert got["name"] == "דשבורד בדיקה"
    assert got["kind"] == "standalone"
    assert [s["board_id"] for s in got["sources"]] == [a]
    assert got["config_version"] == 1


def test_a_save_that_does_not_name_a_version_is_refused(client, admin_id):
    """"אין שמירה אוטומטית של גרסה מיושנת" — nor of an unstated one. A save
    with no version is a save that cannot be checked, which is the silent
    overwrite the rule exists to stop."""
    env = _env(client, admin_id)
    d = _dash(client, admin_id, env, [])
    r = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                     json={"name": "שם חדש"})
    assert r.status_code == 400


def test_a_save_on_a_stale_version_is_refused_and_names_the_current_one(client, admin_id):
    env = _env(client, admin_id)
    d = _dash(client, admin_id, env, [])
    ok = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                      json={"config_version": 1, "name": "ראשון"})
    assert ok.status_code == 200 and ok.json()["config_version"] == 2
    stale = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                         json={"config_version": 1, "name": "שני"})
    assert stale.status_code == 409
    # the current version travels back, so the client can reload and retry
    assert stale.json()["detail"]["config_version"] == 2
    assert _read(client, admin_id, d["id"]).json()["name"] == "ראשון"


def test_a_widget_save_moves_the_dashboards_own_version(client, admin_id):
    """One counter for the dashboard AND its widgets. Two would let a widget
    rewrite land on top of a settings rewrite with both claiming to be
    current."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח דשבורד 2")
    d = _dash(client, admin_id, env, [a])
    out = _widget(client, admin_id, d)
    assert out["config_version"] == 2
    assert _read(client, admin_id, d["id"]).json()["config_version"] == 2


def test_a_widget_never_carries_a_computed_result(client, admin_id):
    """"תוצאות מחושבות אינן מקור אמת." The settings are the record; a figure
    is worked out from live boards every time and is not stored beside them."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח דשבורד 3")
    d = _dash(client, admin_id, env, [a])
    w = _widget(client, admin_id, d)["widget"]
    for forbidden in ("value", "result", "rows", "computed_at", "series"):
        assert forbidden not in w


# ── DASH-03 · מי פותח ומי מנהל ─────────────────────────────────────────────

def test_a_main_dashboard_opens_to_the_workspace_and_a_private_one_does_not(
        client, admin_id, guinea_id):
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    openly = _dash(client, admin_id, env, [], visibility="main", name="ראשי")
    closed = _dash(client, admin_id, env, [], visibility="private", name="פרטי")
    assert _read(client, guinea_id, openly["id"]).status_code == 200
    # 404 and not 403: "there is one and it is not yours" is a disclosure of
    # its own to somebody guessing ids.
    assert _read(client, guinea_id, closed["id"]).status_code == 404


def test_an_invitee_may_open_a_private_dashboard_and_may_not_save_it(
        client, admin_id, guinea_id):
    env = _env(client, admin_id)
    d = _dash(client, admin_id, env, [], visibility="private", name="פרטי מוזמן")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "viewer"})
    got = _read(client, guinea_id, d["id"])
    assert got.status_code == 200 and got.json()["can_edit"] is False
    r = client.patch(f"/api/dashboards/{d['id']}", headers=AS(guinea_id),
                     json={"config_version": got.json()["config_version"], "name": "לא"})
    assert r.status_code == 403


def test_a_named_owner_may_save_it(client, admin_id, guinea_id):
    env = _env(client, admin_id)
    d = _dash(client, admin_id, env, [], visibility="private", name="פרטי בעלים")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "owner"})
    got = _read(client, guinea_id, d["id"]).json()
    assert got["can_edit"] is True
    r = client.patch(f"/api/dashboards/{d['id']}", headers=AS(guinea_id),
                     json={"config_version": got["config_version"], "name": "כן"})
    assert r.status_code == 200


def test_the_creator_cannot_be_removed_from_their_own_dashboard(client, admin_id, guinea_id):
    """A dashboard that can end up belonging to nobody is a dashboard nobody
    can fix."""
    env = _env(client, admin_id)
    d = _dash(client, admin_id, env, [], name="בעלות")
    r = client.delete(f"/api/dashboards/{d['id']}/members/{admin_id}", headers=AS(admin_id))
    assert r.status_code == 400


def test_a_board_dashboard_follows_the_boards_own_roles(client, admin_id, guinea_id):
    """DASH-03.2 — "צופה לא יוכל לשמור הגדרות, ולא ייווצרו תפקידי מערכת חדשים"."""
    a = _board(client, admin_id, "לוח עם תצוגת דשבורד")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    r = client.post(f"/api/boards/{a}/dashboards", headers=AS(admin_id),
                    json={"name": "תצוגת דשבורד"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["kind"] == "board" and d["board_id"] == a and d["view_id"]
    seen = _read(client, guinea_id, d["id"])
    assert seen.status_code == 200 and seen.json()["can_edit"] is False
    # a board viewer may not create one either
    denied = client.post(f"/api/boards/{a}/dashboards", headers=AS(guinea_id),
                         json={"name": "לא שלי"})
    assert denied.status_code == 403


def test_a_board_dashboard_shows_its_host_board_and_cannot_be_pointed_elsewhere(
        client, admin_id):
    """DASH-06.1 — "הלוח המארח יהיה המקור היחיד והקבוע"."""
    a = _board(client, admin_id, "מארח")
    other = _board(client, admin_id, "אחר")
    d = client.post(f"/api/boards/{a}/dashboards", headers=AS(admin_id),
                    json={"name": "מוצמד ללוח"}).json()
    assert [s["board_id"] for s in d["sources"]] == [a]
    r = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                     json={"config_version": d["config_version"],
                           "sources": [{"board_id": other, "groups": None}]})
    assert r.status_code == 400


def test_a_stranger_cannot_reach_a_dashboard_through_the_api(client, admin_id, guinea_id):
    """"לאכוף את ההרשאות גם בבקשות API ישירות" — DASH-03.3. There is no screen
    in this test at all; the endpoint is the whole of the defence."""
    env = _env(client, admin_id)
    d = _dash(client, admin_id, env, [], visibility="private", name="לא לך")
    assert _read(client, guinea_id, d["id"]).status_code == 404
    assert client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(guinea_id),
                       json={"config_version": 1, "title": "פריצה"}).status_code == 404
    assert client.delete(f"/api/dashboards/{d['id']}",
                         headers=AS(guinea_id)).status_code == 404


# ── DASH-04 · הרשאות נתוני מקור, וחסימת ווידג׳ט ─────────────────────────────

def test_a_widget_over_a_board_you_cannot_open_is_blocked(client, admin_id, guinea_id):
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    openly = _board(client, admin_id, "פתוח דש")
    closed = _board(client, admin_id, "סגור דש")
    client.post(f"/api/boards/{openly}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    d = _dash(client, admin_id, env, [openly, closed], name="חוצה לוחות")
    w = _widget(client, admin_id, d, sources=[{"board_id": closed, "groups": None}])["widget"]
    assert _state(client, admin_id, d["id"], w["id"])["state"] == "ok"
    assert _state(client, guinea_id, d["id"], w["id"])["state"] == "blocked"


def test_a_blocked_widget_carries_no_configuration(client, admin_id, guinea_id):
    """The heart of R01. What a blocked widget must not hand over is anything
    a quantity could be inferred from — and the names of the sources it was
    refused are first among them."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    closed = _board(client, admin_id, "סגור חשאי")
    col = _add_col(client, closed, admin_id, {"type": "number", "title": "תקציב"})
    d = _dash(client, admin_id, env, [closed], name="חסוי")
    w = _widget(client, admin_id, d,
                sources=[{"board_id": closed, "groups": None}],
                mapping={str(closed): {"amount": col["id"]}},
                metrics=[{"key": "m1", "field": "amount", "calc": "sum"}])["widget"]
    seen = _state(client, guinea_id, d["id"], w["id"])
    assert seen["state"] == "blocked"
    assert seen.get("sources", []) == []
    assert seen.get("mapping", {}) == {}
    assert seen.get("metrics", []) == []
    assert seen.get("filters", {}) == {}
    assert seen.get("chart", {}) == {}
    # and nothing that would let the board or the column be named
    blob = str(seen)
    assert str(closed) not in blob and col["id"] not in blob and "תקציב" not in blob


def test_a_widget_over_a_column_you_may_not_see_is_blocked(client, admin_id, guinea_id):
    """A board you may open can still hold a column you may not."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    a = _board(client, admin_id, "לוח עם עמודה חסויה")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    col = _add_col(client, a, admin_id, {"type": "number", "title": "שכר"})
    client.post(f"/api/boards/{a}/columns/{col['id']}/permissions", headers=AS(admin_id),
                json={"user_id": guinea_id, "perm": "none"})
    d = _dash(client, admin_id, env, [a], name="עמודה חסויה")
    w = _widget(client, admin_id, d,
                mapping={str(a): {"amount": col["id"]}},
                metrics=[{"key": "m1", "field": "amount", "calc": "sum"}])["widget"]
    assert _state(client, admin_id, d["id"], w["id"])["state"] == "ok"
    assert _state(client, guinea_id, d["id"], w["id"])["state"] == "blocked"


def test_a_mirror_blocks_the_widget_when_the_board_behind_it_is_closed(
        client, admin_id, guinea_id):
    """The first door that does not look like one.

    A mirror holds no value of its own — it reads a field of a linked item on
    ANOTHER board. A check that only looked at the board the widget names
    would compute this happily, and the figure would be drawn from a board
    the reader was refused.
    """
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    near = _board(client, admin_id, "קרוב")
    far = _board(client, admin_id, "רחוק וסגור")
    client.post(f"/api/boards/{near}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    far_col = _add_col(client, far, admin_id, {"type": "number", "title": "סכום רחוק"})
    conn = _add_col(client, near, admin_id,
                    {"type": "connect", "title": "קישור",
                     "connect": {"board_ids": [far], "multiple": True, "two_way": False}})
    mirror = _add_col(client, near, admin_id,
                      {"type": "mirror", "title": "מראה",
                       "mirror_of": {"connect": conn["id"], "field": far_col["id"]}})
    d = _dash(client, admin_id, env, [near], name="דרך מראה")
    w = _widget(client, admin_id, d,
                mapping={str(near): {"amount": mirror["id"]}},
                metrics=[{"key": "m1", "field": "amount", "calc": "sum"}])["widget"]
    assert _state(client, admin_id, d["id"], w["id"])["state"] == "ok"
    # the widget names only `near`, which guinea may open — and it is blocked
    assert _state(client, guinea_id, d["id"], w["id"])["state"] == "blocked"


def test_a_formula_blocks_the_widget_when_a_column_it_reads_is_closed(
        client, admin_id, guinea_id):
    """The second door. A formula names its inputs by title inside its text,
    so a widget can read a forbidden column without ever mentioning it."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    a = _board(client, admin_id, "לוח עם נוסחה")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    secret = _add_col(client, a, admin_id, {"type": "number", "title": "עלות"})
    calc = _add_col(client, a, admin_id,
                    {"type": "formula", "title": "כפול", "formula": "{עלות} * 2"})
    client.post(f"/api/boards/{a}/columns/{secret['id']}/permissions", headers=AS(admin_id),
                json={"user_id": guinea_id, "perm": "none"})
    d = _dash(client, admin_id, env, [a], name="דרך נוסחה")
    w = _widget(client, admin_id, d,
                mapping={str(a): {"amount": calc["id"]}},
                metrics=[{"key": "m1", "field": "amount", "calc": "sum"}])["widget"]
    assert _state(client, admin_id, d["id"], w["id"])["state"] == "ok"
    assert _state(client, guinea_id, d["id"], w["id"])["state"] == "blocked"


def test_being_invited_to_a_dashboard_grants_nothing_about_its_boards(
        client, admin_id, guinea_id):
    """R01 — "בעלות או הזמנה אינן מעניקות הרשאות לנתוני מקור". Being made an
    OWNER is the strongest thing this feature can hand out, and it still does
    not open a board."""
    env = _env(client, admin_id)
    closed = _board(client, admin_id, "סגור למרות הזמנה")
    d = _dash(client, admin_id, env, [closed], visibility="private", name="הזמנה")
    w = _widget(client, admin_id, d)["widget"]
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "owner"})
    got = _read(client, guinea_id, d["id"]).json()
    assert got["can_edit"] is True                     # they manage the dashboard
    assert got["widgets"][0]["state"] == "blocked"     # and read none of its data
    assert got["sources"] == []                        # nor learn which boards


def test_the_header_names_only_the_sources_the_reader_may_open(client, admin_id, guinea_id):
    """DASH-05.2 asks the header for "המקורות המותרים" — the allowed ones. A
    reader whose totals are short is told that the dashboard reaches further
    than they do, without being told where."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    openly = _board(client, admin_id, "גלוי לכותרת")
    closed = _board(client, admin_id, "נסתר מהכותרת")
    client.post(f"/api/boards/{openly}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    d = _dash(client, admin_id, env, [openly, closed], name="כותרת")
    got = _read(client, guinea_id, d["id"]).json()
    assert [s["board_id"] for s in got["sources"]] == [openly]
    assert got["sources_hidden"] == 1


def test_a_dashboard_may_only_connect_boards_its_author_can_open(client, admin_id, guinea_id):
    """"עורך דשבורד רשאי לחבר לוח שיש לו בו הרשאת צפייה" — checked at the
    write, so the server's answer cannot be used to find out whether a board
    id exists.

    The owner here manages the dashboard completely and still cannot reach
    past their own board access, which is the same sentence as
    test_being_invited_to_a_dashboard_grants_nothing_about_its_boards said
    about reading, said now about writing."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    closed = _board(client, admin_id, "לא ניתן לחיבור")
    d = _dash(client, admin_id, env, [], name="בעלות על חיבור")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "owner"})
    ver = _read(client, guinea_id, d["id"]).json()["config_version"]
    r = client.patch(f"/api/dashboards/{d['id']}", headers=AS(guinea_id),
                     json={"config_version": ver,
                           "sources": [{"board_id": closed, "groups": None}]})
    assert r.status_code == 403


def test_creating_a_dashboard_needs_the_right_to_create_boards(client, admin_id, guinea_id):
    """R01 — "יצירה למי שמורשה ליצור לוחות". The same capability, asked the
    same way, rather than a permission of its own."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    r = client.post("/api/dashboards", headers=AS(guinea_id),
                    json={"environment_id": env, "name": "אסור"})
    assert r.status_code == 403


def test_the_widget_ceiling_is_enforced_on_a_direct_request(client, admin_id):
    """R10 — "חריגה חוסמת בהסבר; אין חיתוך". A ceiling only the screen keeps
    is not a ceiling (DASH-12.3)."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח עמוס")
    d = _dash(client, admin_id, env, [a], name="תקרה")
    ver = d["config_version"]
    for i in range(20):
        ver = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                          json={"config_version": ver, "type": "numbers",
                                "title": f"מדד {i}"}).json()["config_version"]
    r = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": ver, "type": "numbers", "title": "אחד יותר מדי"})
    assert r.status_code == 400
    assert "20" in r.json()["detail"]
    # and nothing was trimmed to make room
    assert len(_read(client, admin_id, d["id"]).json()["widgets"]) == 20


def test_a_source_limit_of_ten_boards_is_enforced(client, admin_id):
    """R02 — "דשבורד עצמאי: עד 10 לוחות"."""
    env = _env(client, admin_id)
    boards = [_board(client, admin_id, f"לוח מקור {i}") for i in range(11)]
    r = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env, "name": "יותר מדי",
                          "sources": [{"board_id": b, "groups": None} for b in boards]})
    assert r.status_code == 400 and "10" in r.json()["detail"]


def test_a_board_in_the_recycle_bin_closes_its_dashboard(client, admin_id, member_id):
    """_board_role answers from the membership row and never looks at the
    board, so every caller checks the board separately — get_board does it
    before it asks for the role. A dashboard that forgot would go on opening
    a deleted board's figures to everyone ever invited to it."""
    a = _board(client, admin_id, "לוח שיימחק")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    d = client.post(f"/api/boards/{a}/dashboards", headers=AS(admin_id),
                    json={"name": "תצוגה שתיסגר"}).json()
    assert _read(client, member_id, d["id"]).status_code == 200
    client.delete(f"/api/boards/{a}", headers=AS(admin_id))
    try:
        assert _read(client, member_id, d["id"]).status_code == 404
        assert _read(client, admin_id, d["id"]).status_code == 404
    finally:
        client.post(f"/api/boards/{a}/restore", headers=AS(admin_id))
