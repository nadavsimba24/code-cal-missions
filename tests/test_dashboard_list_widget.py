"""ווידג׳ט רשימה — הרשומות עצמן, לא חישוב עליהן.

A third widget kind, asked for after the spec was written and not excluded
by it: the dashboard could say how MUCH and how it is DISTRIBUTED, and could
not show what it was counting.

What matters about it is that it is not a second way of reading a board. It
runs on the same population as the numbers and the charts — the same
sources, the same two filter layers, the same visitor's filter, the same
per-item permission — so a list beside a figure cannot disagree with it.

And the rule that costs the most to get wrong: a column the viewer may not
see blocks the WHOLE widget. R01 makes no exception for a column somebody is
only looking at — a list missing one is a partial answer wearing the clothes
of a complete one, which is the thing the rule exists to prevent.
"""
from conftest import join_primary_env

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    bid = client.post("/api/boards",
                      json={"name": name, "user_id": admin_id}).json()["id"]
    for t in client.get(f"/api/boards/{bid}").json()["tasks"]:
        client.delete(f"/api/tasks/{t['id']}", headers=AS(admin_id))
    return bid


def _add_col(client, bid, admin_id, col):
    cols = client.get(f"/api/boards/{bid}").json()["columns"] + [col]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    return client.get(f"/api/boards/{bid}").json()["columns"][-1]


def _item(client, bid, admin_id, title, cf=None, **kw):
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id, **kw}).json()["id"]
    if cf:
        client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": cf})
    return tid


def _env(client, admin_id):
    return next(e["id"] for e in client.get("/api/environments",
                                            headers=AS(admin_id)).json()["environments"]
                if e.get("is_primary"))


def _dash(client, admin_id, env, sources, name="רשימה"):
    return client.post("/api/dashboards", headers=AS(admin_id),
                       json={"environment_id": env, "name": name,
                             "sources": [{"board_id": b, "groups": None}
                                         for b in sources]}).json()


def _list_widget(client, admin_id, d, **kw):
    return client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                       json={"config_version": d["config_version"], "type": "list",
                             "title": "רשומות", **kw})


def _run(client, uid, did, wid, **body):
    r = client.post(f"/api/dashboards/{did}/widgets/{wid}/compute",
                    headers=AS(uid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _fixture(client, admin_id):
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "רשימה · לוח")
    num = _add_col(client, bid, admin_id,
                   {"type": "number", "title": "תקציב", "number": {"unit": "₪"}})
    txt = _add_col(client, bid, admin_id, {"type": "text", "title": "הערה"})
    for i, (t, v) in enumerate((("אלף", 10), ("בית", 20), ("גימל", 30))):
        _item(client, bid, admin_id, t, status="done" if i else "in_progress",
              cf={num["id"]: v, txt["id"]: f"הערה {t}"})
    return env, bid, num, txt


# ── מה הוא מציג ─────────────────────────────────────────────────────────────

def test_a_list_shows_the_records_with_the_columns_it_was_given(client, admin_id):
    env, bid, num, txt = _fixture(client, admin_id)
    d = _dash(client, admin_id, env, [bid])
    w = _list_widget(client, admin_id, d,
                     display={"columns": {str(bid): [num["id"], txt["id"]]}}).json()
    out = _run(client, admin_id, d["id"], w["widget"]["id"])
    assert out["state"] == "ok" and out["type"] == "list"
    assert [c["label"] for c in out["columns"]] == ["תקציב", "הערה"]
    by = {r["title"]: r for r in out["rows"]}
    assert set(by) == {"אלף", "בית", "גימל"}
    assert by["בית"]["cells"][num["id"]] == 20
    assert by["גימל"]["cells"][txt["id"]] == "הערה גימל"
    assert by["אלף"]["board_name"] == "רשימה · לוח"
    assert by["אלף"]["my_perm"] in ("edit", "delete")


def test_a_list_says_how_many_there_are_and_not_only_how_many_it_shows(
        client, admin_id):
    """R10 — "אין חיתוך… ללא הודעה". Ten rows out of four hundred is honest
    only when the four hundred is beside them."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "רשימה · הרבה")
    for i in range(25):
        _item(client, bid, admin_id, f"פריט {i:02d}")
    d = _dash(client, admin_id, env, [bid])
    w = _list_widget(client, admin_id, d, display={"limit": 10}).json()
    out = _run(client, admin_id, d["id"], w["widget"]["id"])
    assert out["records"] == 25
    assert out["shown"] == 10 and len(out["rows"]) == 10
    assert out["limit"] == 10


def test_a_list_runs_on_the_same_population_as_the_figure_beside_it(client, admin_id):
    """A list and a count over one configuration must agree, or the dashboard
    contradicts itself on one screen."""
    env, bid, num, _txt = _fixture(client, admin_id)
    d = _dash(client, admin_id, env, [bid])
    only_done = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "status", "operator": "eq", "value": "done"}]}}
    lst = _list_widget(client, admin_id, d, filters=only_done).json()
    d = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    cnt = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                      json={"config_version": d["config_version"], "type": "numbers",
                            "title": "כמה", "filters": only_done,
                            "metrics": [{"key": "m", "calc": "count"}]}).json()
    rows = _run(client, admin_id, d["id"], lst["widget"]["id"])
    figure = _run(client, admin_id, d["id"],
                  cnt["widget"]["id"])["metrics"][0]["result"]
    assert rows["records"] == figure == 2


def test_a_visitors_filter_narrows_the_list_too(client, admin_id):
    env, bid, num, _txt = _fixture(client, admin_id)
    d = _dash(client, admin_id, env, [bid])
    w = _list_widget(client, admin_id, d,
                     mapping={str(bid): {"amount": num["id"]}},
                     display={"columns": {str(bid): [num["id"]]}}).json()
    temp = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "gt", "value": 15}]}}
    out = _run(client, admin_id, d["id"], w["widget"]["id"], temp_filter=temp)
    assert out["records"] == 2
    assert {r["title"] for r in out["rows"]} == {"בית", "גימל"}


# ── ומה הוא לא מציג ─────────────────────────────────────────────────────────

def test_a_column_the_viewer_may_not_see_blocks_the_whole_list(client, admin_id,
                                                               guinea_id):
    """R01 — "אם לצופה חסרה הרשאה למקור נדרש… כל הווידג׳ט ייחסם."

    A list is where this is easiest to get wrong: blanking the one cell looks
    reasonable and is a partial answer. The rule has no exception for a
    column somebody is only looking at.
    """
    env, bid, num, txt = _fixture(client, admin_id)
    join_primary_env(client, guinea_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    client.post(f"/api/boards/{bid}/columns/{num['id']}/permissions",
                headers=AS(admin_id), json={"user_id": guinea_id, "perm": "none"})
    d = _dash(client, admin_id, env, [bid])
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "viewer"})
    w = _list_widget(client, admin_id, d,
                     display={"columns": {str(bid): [num["id"], txt["id"]]}}).json()
    wid = w["widget"]["id"]
    assert _run(client, admin_id, d["id"], wid)["state"] == "ok"
    theirs = _run(client, guinea_id, d["id"], wid)
    assert theirs["state"] == "blocked"
    assert theirs["rows"] == [] and theirs["columns"] == []
    assert "records" not in theirs
    assert "תקציב" not in str(theirs) and "הערה" not in str(theirs)


def test_a_record_the_viewer_may_not_open_is_not_a_row(client, admin_id, guinea_id):
    """DASH-04.3 — item permissions apply to the population, and a list IS
    the population."""
    env, bid, _num, txt = _fixture(client, admin_id)
    join_primary_env(client, guinea_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    hidden = client.get(f"/api/boards/{bid}").json()["tasks"]
    hid = next(t["id"] for t in hidden if t["title"] == "בית")
    client.post(f"/api/tasks/{hid}/permissions", headers=AS(admin_id),
                json={"user_id": guinea_id, "perm": "none"})
    d = _dash(client, admin_id, env, [bid])
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "viewer"})
    w = _list_widget(client, admin_id, d,
                     display={"columns": {str(bid): [txt["id"]]}}).json()
    mine = _run(client, admin_id, d["id"], w["widget"]["id"])
    theirs = _run(client, guinea_id, d["id"], w["widget"]["id"])
    assert {r["title"] for r in mine["rows"]} == {"אלף", "בית", "גימל"}
    assert {r["title"] for r in theirs["rows"]} == {"אלף", "גימל"}
    assert theirs["records"] == 2


def test_a_connect_or_mirror_column_is_refused_rather_than_flattened(client, admin_id):
    """Both carry a disclosure story a row of text cannot tell — the ids they
    hold are filtered per viewer (see _visible_link_ids). They are one click
    away, on the item itself."""
    env = _env(client, admin_id)
    far = _board(client, admin_id, "רשימה · רחוק")
    near = _board(client, admin_id, "רשימה · קרוב")
    conn = _add_col(client, near, admin_id,
                    {"type": "connect", "title": "קישור",
                     "connect": {"board_ids": [far], "multiple": True, "two_way": False}})
    d = _dash(client, admin_id, env, [near])
    r = _list_widget(client, admin_id, d,
                     display={"columns": {str(near): [conn["id"]]}})
    assert r.status_code == 400
    assert "מתוך הפריט עצמו" in r.json()["detail"]


def test_a_column_from_a_board_the_widget_does_not_read_is_refused(client, admin_id):
    env, bid, num, _txt = _fixture(client, admin_id)
    other = _board(client, admin_id, "רשימה · לא מקור")
    col = _add_col(client, other, admin_id, {"type": "text", "title": "זר"})
    d = _dash(client, admin_id, env, [bid])
    r = _list_widget(client, admin_id, d,
                     display={"columns": {str(other): [col["id"]]}})
    assert r.status_code == 400


def test_a_list_needs_no_measure(client, admin_id):
    """It measures nothing, so demanding a metric — and the column mapping a
    metric needs — would be demanding something it never uses."""
    env, bid, _num, txt = _fixture(client, admin_id)
    d = _dash(client, admin_id, env, [bid])
    r = _list_widget(client, admin_id, d,
                     display={"columns": {str(bid): [txt["id"]]}})
    assert r.status_code == 200, r.text
    out = _run(client, admin_id, d["id"], r.json()["widget"]["id"])
    assert out["state"] == "ok" and "metrics" not in out
