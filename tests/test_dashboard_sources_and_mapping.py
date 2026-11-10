"""Making a dashboard: duplicating it, choosing its boards, groups and columns.

What is pinned here is mostly R02 — the rules for which records a measure is
made of — and the two places the spec insists a person decides rather than
the system:

DASH-07.1 — "הצעת התאמת עמודות לפי שם וסוג **מחייבת אישור או תיקון לפני
שימוש**". So the proposal endpoint stores nothing, and the test says so by
asking twice and finding the widget unchanged.

DASH-06.3 — removing a board shows what it would break and asks. The impact
is counted on the server, because the configuration a reader holds has
already been filtered to what they may see.

The parent/child rules (R02) are the subtle ones and they are the reason
_dash_population is tested directly rather than through a screen: "אב וילדים
הם רשומות עצמאיות, ללא ירושת ערכים", "מזהה רשומה נספר פעם אחת", "שני פריטים
בשם זהה נספרים בנפרד", and archived and deleted records are out. Each of
those is a different way to get a total wrong by one.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from conftest import join_primary_env

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_col(client, bid, admin_id, col):
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id, "columns": _cols(client, bid) + [col]})
    return _cols(client, bid)[-1]


def _env(client, admin_id):
    for e in client.get("/api/environments", headers=AS(admin_id)).json()["environments"]:
        if e.get("is_primary"):
            return e["id"]


def _dash(client, admin_id, env_id, sources=(), **kw):
    r = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env_id, "name": kw.pop("name", "דש"),
                          "sources": [{"board_id": b, "groups": None} for b in sources],
                          **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _widget(client, admin_id, dash, **kw):
    r = client.post(f"/api/dashboards/{dash['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": dash["config_version"],
                          "type": "numbers", "title": "מדד", **kw})
    return r


def _item(client, bid, admin_id, title, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()["id"]


def _population(dash_id, widget_id, uid):
    """The records a widget measures, as the server works them out."""
    with Session(cityos_main.engine) as db:
        d = db.query(cityos_main.Dashboard).filter(
            cityos_main.Dashboard.id == dash_id).first()
        w = db.query(cityos_main.DashboardWidget).filter(
            cityos_main.DashboardWidget.id == widget_id).first() if widget_id else None
        return [t.id for t in cityos_main._dash_population(db, d, w, uid)]


# ── DASH-05 · שכפול ──────────────────────────────────────────────────────────

def test_a_duplicate_gets_new_ids_and_keeps_the_settings(client, admin_id):
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח לשכפול")
    d = _dash(client, admin_id, env, [a], name="מקור")
    w = _widget(client, admin_id, d).json()["widget"]
    r = client.post(f"/api/dashboards/{d['id']}/duplicate", headers=AS(admin_id))
    assert r.status_code == 200, r.text
    copy = r.json()
    assert copy["id"] != d["id"]
    assert copy["name"] == "מקור (עותק)"
    assert [s["board_id"] for s in copy["sources"]] == [a]
    assert len(copy["widgets"]) == 1
    assert copy["widgets"][0]["id"] != w["id"]        # new ids, not shared rows


def test_a_change_to_the_copy_leaves_the_original_alone(client, admin_id):
    """DASH-12.1 for the dashboard: "שינוי בעותק לא ישנה את המקור"."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח עצמאות העותק")
    d = _dash(client, admin_id, env, [a], name="לא ישתנה")
    copy = client.post(f"/api/dashboards/{d['id']}/duplicate",
                       headers=AS(admin_id)).json()
    client.patch(f"/api/dashboards/{copy['id']}", headers=AS(admin_id),
                 json={"config_version": copy["config_version"], "name": "שונה"})
    back = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    assert back["name"] == "לא ישתנה"


def test_a_duplicate_does_not_carry_the_audience_across(client, admin_id, guinea_id):
    """Sharing is a deliberate act. A copy that arrived pre-shared would hand
    a private dashboard's readership to whoever pressed copy."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    d = _dash(client, admin_id, env, [], name="פרטי למקור", visibility="private")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "viewer"})
    copy = client.post(f"/api/dashboards/{d['id']}/duplicate",
                       headers=AS(admin_id)).json()
    assert copy["visibility"] == "private"
    assert client.get(f"/api/dashboards/{d['id']}", headers=AS(guinea_id)).status_code == 200
    assert client.get(f"/api/dashboards/{copy['id']}", headers=AS(guinea_id)).status_code == 404


def test_a_duplicate_may_not_carry_a_board_the_copier_cannot_open(
        client, admin_id, member_id):
    """"שכפול ייצור מזהים חדשים בלי להקנות הרשאות למקורות" — refused rather
    than quietly shrunk, because a copy missing a board computes different
    numbers from the original while looking exactly like it."""
    env = _env(client, admin_id)
    closed = _board(client, admin_id, "סגור לשכפול")
    d = _dash(client, admin_id, env, [closed], name="עם לוח סגור")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": member_id, "role": "owner"})
    r = client.post(f"/api/dashboards/{d['id']}/duplicate", headers=AS(member_id))
    assert r.status_code == 403


def test_the_copys_layout_points_at_the_copys_own_widgets(client, admin_id):
    """The grid is keyed by widget id, so copying it as it stands would leave
    every key pointing at a widget belonging to the original."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח פריסה")
    d = _dash(client, admin_id, env, [a], name="פריסה")
    w = _widget(client, admin_id, d).json()
    client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                 json={"config_version": w["config_version"],
                       "layout": {str(w["widget"]["id"]): {"col": 0, "span": 2}}})
    copy = client.post(f"/api/dashboards/{d['id']}/duplicate",
                       headers=AS(admin_id)).json()
    new_id = str(copy["widgets"][0]["id"])
    assert list(copy["layout"].keys()) == [new_id]
    assert copy["layout"][new_id] == {"col": 0, "span": 2}


# ── DASH-06 · לוחות וקבוצות ──────────────────────────────────────────────────

def test_a_group_from_another_board_is_refused(client, admin_id):
    """A group id from elsewhere names records that are never in the
    population, so the widget answers 0 and looks correct."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח קבוצות א")
    b = _board(client, admin_id, "לוח קבוצות ב")
    b_group = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    r = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env, "name": "קבוצה זרה",
                          "sources": [{"board_id": a, "groups": [b_group]}]})
    assert r.status_code == 400


def test_an_empty_group_choice_is_refused_rather_than_stored(client, admin_id):
    """"no groups" can only ever produce an empty population."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח קבוצה ריקה")
    r = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env, "name": "ריק",
                          "sources": [{"board_id": a, "groups": []}]})
    assert r.status_code == 400


def test_all_groups_stays_all_groups_when_a_new_one_is_added(client, admin_id):
    """R02 — "כל הקבוצות כברירת מחדל, **כולל קבוצות עתידיות**". Stored as a
    null and not as the ids that happened to exist at save time, which would
    stop including them the moment somebody added one."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח קבוצות עתידיות")
    d = _dash(client, admin_id, env, [a], name="כל הקבוצות")
    w = _widget(client, admin_id, d).json()["widget"]
    before = _population(d["id"], w["id"], admin_id)
    g = client.post("/api/groups", json={"board_id": a, "name": "קבוצה חדשה",
                                         "user_id": admin_id}).json()["id"]
    fresh = _item(client, a, admin_id, "בקבוצה החדשה", group_id=g)
    assert fresh in _population(d["id"], w["id"], admin_id)
    assert fresh not in before


def test_removing_a_board_says_which_widgets_it_would_break(client, admin_id):
    """DASH-06.3 — shown before the removal, counted on the server."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "מקור א")
    b = _board(client, admin_id, "מקור ב")
    d = _dash(client, admin_id, env, [a, b], name="שני מקורות")
    only_a = _widget(client, admin_id, d, title="רק א",
                     sources=[{"board_id": a, "groups": None}]).json()
    both = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                       json={"config_version": only_a["config_version"],
                             "type": "numbers", "title": "שניהם",
                             "sources": [{"board_id": a, "groups": None},
                                         {"board_id": b, "groups": None}]}).json()
    r = client.get(f"/api/dashboards/{d['id']}/sources/{a}/impact", headers=AS(admin_id))
    assert r.status_code == 200, r.text
    body = r.json()
    verdicts = {x["title"]: x["verdict"] for x in body["widgets"]}
    assert verdicts["רק א"] == "needs_fix"     # nothing left to measure
    assert verdicts["שניהם"] == "ok"           # carries on with board ב
    assert body["orphaned"] == 1
    assert body["sources_left"] == 1
    # and it only reported — nothing was removed
    assert len(client.get(f"/api/dashboards/{d['id']}",
                          headers=AS(admin_id)).json()["sources"]) == 2


# ── DASH-07 · מיפוי עמודות ───────────────────────────────────────────────────

def test_a_mapping_is_proposed_by_name_and_type_and_stored_by_nobody(client, admin_id):
    """DASH-07.1 — the proposal needs approval. Asking for one must not be a
    way of applying one."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח ייחוס")
    b = _board(client, admin_id, "לוח מטרה")
    ca = _add_col(client, a, admin_id, {"type": "number", "title": "תקציב"})
    cb = _add_col(client, b, admin_id, {"type": "number", "title": "תקציב"})
    _add_col(client, b, admin_id, {"type": "number", "title": "משהו אחר"})
    d = _dash(client, admin_id, env, [a, b], name="מיפוי")
    w = _widget(client, admin_id, d).json()["widget"]
    r = client.post(f"/api/dashboards/{d['id']}/mapping-proposal", headers=AS(admin_id),
                    json={"reference_board_id": a, "fields": {"amount": ca["id"]}})
    assert r.status_code == 200, r.text
    prop = r.json()["proposals"][str(b)]["amount"]
    assert prop["column_id"] == cb["id"]
    assert prop["match"] == "name_and_type"
    assert len(prop["candidates"]) == 2          # both number columns offered
    # nothing was written: not the mapping, and not the version either —
    # a proposal that moved the version would be a save wearing a question's
    # clothes, and the next real save would conflict against it.
    before = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    client.post(f"/api/dashboards/{d['id']}/mapping-proposal", headers=AS(admin_id),
                json={"reference_board_id": a, "fields": {"amount": ca["id"]}})
    back = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    assert back["widgets"][0]["mapping"] == {}
    assert back["config_version"] == before["config_version"]


def test_a_name_that_matches_nothing_is_proposed_as_nothing(client, admin_id):
    """Same name and same type is the only match offered with confidence."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "ייחוס ללא תאום")
    b = _board(client, admin_id, "מטרה ללא תאום")
    ca = _add_col(client, a, admin_id, {"type": "number", "title": "ייחודי"})
    _add_col(client, b, admin_id, {"type": "number", "title": "שונה לגמרי"})
    d = _dash(client, admin_id, env, [a, b], name="ללא תאום")
    r = client.post(f"/api/dashboards/{d['id']}/mapping-proposal", headers=AS(admin_id),
                    json={"reference_board_id": a, "fields": {"amount": ca["id"]}})
    prop = r.json()["proposals"][str(b)]["amount"]
    assert prop["column_id"] is None and prop["match"] == "none"
    assert len(prop["candidates"]) == 1          # offered, not chosen


def test_a_measure_with_no_column_on_one_board_blocks_the_save(client, admin_id):
    """DASH-07.3 — refused at the save, where the person who can fix it is."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "ממופה")
    b = _board(client, admin_id, "לא ממופה")
    ca = _add_col(client, a, admin_id, {"type": "number", "title": "סכום"})
    d = _dash(client, admin_id, env, [a, b], name="מיפוי חסר")
    r = _widget(client, admin_id, d,
                mapping={str(a): {"amount": ca["id"]}},
                metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    assert r.status_code == 400
    assert "מיפוי" in r.json()["detail"] or "לוח" in r.json()["detail"]


def test_a_sum_over_a_text_column_blocks_the_save(client, admin_id):
    """DASH-07.2 — "המקורות המספריים המותרים הם מספר, נוסחה מספרית ומראה
    מספרית"."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח טקסט")
    txt = _add_col(client, a, admin_id, {"type": "text", "title": "הערה"})
    d = _dash(client, admin_id, env, [a], name="סכום טקסט")
    r = _widget(client, admin_id, d,
                mapping={str(a): {"amount": txt["id"]}},
                metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    assert r.status_code == 400
    assert "מספרית" in r.json()["detail"]


def test_two_boards_answering_one_measure_in_different_units_block_the_save(
        client, admin_id):
    """R05 — "אין המרת מטבע אוטומטית". A sum of shekels and hours is not a
    number with a problem; it is not a number."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "שקלים")
    b = _board(client, admin_id, "שעות")
    ca = _add_col(client, a, admin_id,
                  {"type": "number", "title": "כמות", "number": {"unit": "₪"}})
    cb = _add_col(client, b, admin_id,
                  {"type": "number", "title": "כמות", "number": {"unit": "שעות"}})
    d = _dash(client, admin_id, env, [a, b], name="יחידות")
    r = _widget(client, admin_id, d,
                mapping={str(a): {"amount": ca["id"]}, str(b): {"amount": cb["id"]}},
                metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    assert r.status_code == 400
    assert "יחידות" in r.json()["detail"]


def test_a_count_needs_no_column_at_all(client, admin_id):
    """A count counts records, and a record is not a value in a column."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "ספירה בלבד")
    d = _dash(client, admin_id, env, [a], name="ספירה")
    r = _widget(client, admin_id, d, metrics=[{"key": "m", "calc": "count"}])
    assert r.status_code == 200, r.text


# ── DASH-08 · פריטים, תתי־פריטים, וכפילויות ─────────────────────────────────

def _scoped(client, admin_id, env, board, scope):
    d = _dash(client, admin_id, env, [board], name=f"היקף {scope}")
    w = _widget(client, admin_id, d, record_scope=scope).json()["widget"]
    return d, w


def test_items_subitems_and_both_are_three_different_populations(client, admin_id):
    env = _env(client, admin_id)
    a = _board(client, admin_id, "לוח היררכיה")
    parent = _item(client, a, admin_id, "אב")
    kid = _item(client, a, admin_id, "ילד", parent_id=parent)
    d_i, w_i = _scoped(client, admin_id, env, a, "items")
    d_s, w_s = _scoped(client, admin_id, env, a, "subitems")
    d_b, w_b = _scoped(client, admin_id, env, a, "both")
    items = _population(d_i["id"], w_i["id"], admin_id)
    subs = _population(d_s["id"], w_s["id"], admin_id)
    both = _population(d_b["id"], w_b["id"], admin_id)
    assert parent in items and kid not in items
    assert kid in subs and parent not in subs
    assert parent in both and kid in both
    # "אב וילדים הם רשומות עצמאיות" — both is the union, counted once each
    assert len(both) == len(set(both)) == len(items) + len(subs)


def test_the_default_population_is_items(client, admin_id):
    """R02 — "ברירת מחדל פריטים"."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "ברירת מחדל")
    parent = _item(client, a, admin_id, "אב ברירת מחדל")
    kid = _item(client, a, admin_id, "ילד ברירת מחדל", parent_id=parent)
    d = _dash(client, admin_id, env, [a], name="ברירת מחדל")
    w = _widget(client, admin_id, d).json()["widget"]
    assert w["record_scope"] == "items"
    pop = _population(d["id"], w["id"], admin_id)
    assert parent in pop and kid not in pop


def test_two_records_with_the_same_name_are_counted_separately(client, admin_id):
    """R02 — "שני פריטים בשם זהה נספרים בנפרד". De-duplicating by name would
    quietly delete one of them from every total."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "שמות זהים")
    one = _item(client, a, admin_id, "אותו שם בדיוק")
    two = _item(client, a, admin_id, "אותו שם בדיוק")
    d = _dash(client, admin_id, env, [a], name="שמות")
    w = _widget(client, admin_id, d).json()["widget"]
    pop = _population(d["id"], w["id"], admin_id)
    assert one in pop and two in pop


def test_archived_and_deleted_records_are_out_of_the_population(client, admin_id):
    """R02 — "מחוקים ובארכיון מוחרגים"."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "ארכיון ומחיקה")
    live = _item(client, a, admin_id, "חי")
    archived = _item(client, a, admin_id, "בארכיון")
    deleted = _item(client, a, admin_id, "נמחק")
    d = _dash(client, admin_id, env, [a], name="הדרה")
    w = _widget(client, admin_id, d).json()["widget"]
    assert set(_population(d["id"], w["id"], admin_id)) >= {live, archived, deleted}
    # Archiving has no REST endpoint of its own — the flag is set by the AI
    # tool path and nowhere else — so the state is made here directly. The
    # board was created by this test, so nothing shared is being mutated.
    with Session(cityos_main.engine) as db:
        db.query(cityos_main.Task).filter(
            cityos_main.Task.id == archived).update({"is_archived": True})
        db.commit()
    client.delete(f"/api/tasks/{deleted}", headers=AS(admin_id))
    pop = _population(d["id"], w["id"], admin_id)
    assert live in pop
    assert archived not in pop and deleted not in pop


def test_a_record_that_moved_boards_is_counted_where_it_is_now(client, admin_id):
    """R02 — "פריט שהועבר נספר במיקומו הנוכחי בלבד". A move rewrites board_id
    on the item, so there is one row in one place and nothing to de-duplicate
    across boards."""
    env = _env(client, admin_id)
    a = _board(client, admin_id, "מקור מעבר")
    b = _board(client, admin_id, "יעד מעבר")
    t = _item(client, a, admin_id, "נודד")
    d = _dash(client, admin_id, env, [a, b], name="מעבר")
    w = _widget(client, admin_id, d).json()["widget"]
    assert t in _population(d["id"], w["id"], admin_id)
    client.post(f"/api/tasks/{t}/move", headers=AS(admin_id), json={"board_id": b})
    pop = _population(d["id"], w["id"], admin_id)
    assert pop.count(t) == 1          # once, and only once, wherever it is


def test_a_record_the_reader_may_not_open_is_not_in_their_population(
        client, admin_id, guinea_id):
    """DASH-04.3 — "להחיל הרשאות פריט על אוכלוסיית הנתונים". A population
    filtered after it has been counted has already been counted wrong."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    a = _board(client, admin_id, "הרשאת פריט")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    openly = _item(client, a, admin_id, "גלוי")
    hidden = _item(client, a, admin_id, "חסוי")
    client.post(f"/api/tasks/{hidden}/permissions", headers=AS(admin_id),
                json={"user_id": guinea_id, "perm": "none"})
    d = _dash(client, admin_id, env, [a], name="הרשאת פריט")
    w = _widget(client, admin_id, d).json()["widget"]
    mine = _population(d["id"], w["id"], admin_id)
    theirs = _population(d["id"], w["id"], guinea_id)
    assert hidden in mine and openly in mine
    assert openly in theirs and hidden not in theirs
