"""Building a widget: the draft, the copy, the format, and the three filters.

Two separations carry this file.

**A preview is not a save.** R09 opens with it — "תצוגה מקדימה אינה שמירה" —
and DASH-11.2 asks for one before anything is stored. So the preview endpoint
computes a configuration that does not exist, moves no version, and leaves
nothing behind. What it must NOT be is more permissive than the save: a draft
that could read a board the saved widget could not would be a way to compute
over a source through a widget that can never exist.

**A visitor's filter is not the dashboard's.** R05 — "צופה מסנן זמנית לאורך
הביקור בלבד, ללא השפעה על אחרים" — so the temporary filter travels in the
request, is applied to the same population the saved filters are, is never
written, and resetting is just the next request without it. The test that
matters is the one asserting a second reader is unaffected.

The rest is the arithmetic of presentation (DASH-15: rounding and units are
display and must never move a stored value) and the save-time rules that stop
a filter being stored over a field some source cannot answer (DASH-16.1,
DASH-17.1).
"""
from conftest import join_primary_env

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    bid = client.post("/api/boards",
                      json={"name": name, "user_id": admin_id}).json()["id"]
    for t in client.get(f"/api/boards/{bid}").json()["tasks"]:
        client.delete(f"/api/tasks/{t['id']}", headers=AS(admin_id))
    return bid


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


def _dash(client, admin_id, env_id, sources, name="עריכה"):
    r = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env_id, "name": name,
                          "sources": [{"board_id": b, "groups": None} for b in sources]})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title, cf=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id}).json()["id"]
    if cf:
        client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": cf})
    return tid


def _numbers(client, admin_id, name, values):
    bid = _board(client, admin_id, name)
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "סכום"})
    for i, v in enumerate(values):
        _item(client, bid, admin_id, f"ר{i}", cf=({} if v is None else {col["id"]: v}))
    return bid, col


def _widget(client, admin_id, dash, **kw):
    r = client.post(f"/api/dashboards/{dash['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": dash["config_version"],
                          "type": "numbers", "title": "מדד", **kw})
    return r


def _fresh(client, uid, dash_id):
    return client.get(f"/api/dashboards/{dash_id}", headers=AS(uid)).json()


def _compute(client, uid, dash_id, widget_id, **body):
    r = client.post(f"/api/dashboards/{dash_id}/widgets/{widget_id}/compute",
                    headers=AS(uid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _metric(calc, **kw):
    return dict({"key": "m", "field": "amount", "calc": calc}, **kw)


# ── DASH-11 · הטיוטה ────────────────────────────────────────────────────────

def test_a_preview_computes_without_creating_anything(client, admin_id):
    """"תצוגה מקדימה אינה שמירה" — no row, no version movement, no id."""
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "טיוטה", [10, 20, 30])
    d = _dash(client, admin_id, env, [bid])
    r = client.post(f"/api/dashboards/{d['id']}/widgets/preview", headers=AS(admin_id),
                    json={"type": "numbers", "title": "טיוטה",
                          "mapping": {str(bid): {"amount": col["id"]}},
                          "metrics": [_metric("sum")]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["preview"] is True and out["widget_id"] is None
    assert out["metrics"][0]["result"] == 60
    after = _fresh(client, admin_id, d["id"])
    assert after["widgets"] == []
    assert after["config_version"] == d["config_version"]


def test_a_preview_needs_no_version_because_it_conflicts_with_nothing(client, admin_id):
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "טיוטה ללא גרסה", [1])
    d = _dash(client, admin_id, env, [bid])
    r = client.post(f"/api/dashboards/{d['id']}/widgets/preview", headers=AS(admin_id),
                    json={"type": "numbers", "title": "ללא גרסה",
                          "metrics": [{"key": "m", "calc": "count"}]})
    assert r.status_code == 200, r.text


def test_a_preview_refuses_exactly_what_the_save_refuses(client, admin_id):
    """A draft that validated more loosely would be a configuration somebody
    could see working and then not be allowed to keep."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "טיוטה פסולה")
    txt = _add_col(client, bid, admin_id, {"type": "text", "title": "הערה"})
    d = _dash(client, admin_id, env, [bid])
    body = {"type": "numbers", "title": "סכום טקסט",
            "mapping": {str(bid): {"amount": txt["id"]}},
            "metrics": [_metric("sum")]}
    prev = client.post(f"/api/dashboards/{d['id']}/widgets/preview",
                       headers=AS(admin_id), json=body)
    save = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                       json={**body, "config_version": d["config_version"]})
    assert prev.status_code == 400 and save.status_code == 400
    assert prev.json()["detail"] == save.json()["detail"]


def test_a_preview_is_blocked_by_the_same_sources_a_save_would_be(
        client, admin_id, guinea_id):
    """R01 reaches the draft too. Otherwise previewing is a way to read a
    board through a widget that could never be stored."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    closed, col = _numbers(client, admin_id, "סגור לטיוטה", [10])
    d = _dash(client, admin_id, env, [closed], name="טיוטה חסומה")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "owner"})
    r = client.post(f"/api/dashboards/{d['id']}/widgets/preview", headers=AS(guinea_id),
                    json={"type": "numbers", "title": "נסיון",
                          "mapping": {str(closed): {"amount": col["id"]}},
                          "metrics": [_metric("sum")]})
    assert r.status_code == 200
    assert r.json()["state"] == "blocked" and r.json()["metrics"] == []


def test_a_viewer_may_not_preview(client, admin_id, guinea_id):
    """Previewing is an authoring action and asks for an author's rights."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    bid = _board(client, admin_id, "טיוטה לצופה")
    d = _dash(client, admin_id, env, [bid], name="טיוטה לצופה")
    r = client.post(f"/api/dashboards/{d['id']}/widgets/preview", headers=AS(guinea_id),
                    json={"type": "numbers", "title": "לא שלי",
                          "metrics": [{"key": "m", "calc": "count"}]})
    assert r.status_code == 403


def test_moving_from_a_count_to_a_sum_needs_the_columns_said_out_loud(
        client, admin_id):
    """DASH-11.2 — "מעבר מספירה לחישוב יחייב בחירת עמודות מפורשת". A counting
    widget may be carrying a mapping from some earlier shape of itself;
    inheriting it would pick the column for somebody."""
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "ספירה לסכום", [10, 20])
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[{"key": "m", "calc": "count"}]).json()["widget"]
    ver = _fresh(client, admin_id, d["id"])["config_version"]
    silent = client.patch(f"/api/dashboards/{d['id']}/widgets/{w['id']}",
                          headers=AS(admin_id),
                          json={"config_version": ver, "metrics": [_metric("sum")]})
    assert silent.status_code == 400
    assert "מפורשת" in silent.json()["detail"]
    spoken = client.patch(f"/api/dashboards/{d['id']}/widgets/{w['id']}",
                          headers=AS(admin_id),
                          json={"config_version": ver, "metrics": [_metric("sum")],
                                "mapping": {str(bid): {"amount": col["id"]}}})
    assert spoken.status_code == 200, spoken.text


# ── DASH-12 · השכפול ────────────────────────────────────────────────────────

def test_a_duplicated_widget_is_its_own_row(client, admin_id):
    """"שינוי בעותק לא ישנה את המקור" — which is a fact about the JSON being
    copied by value, not assigned across."""
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "שכפול ווידג׳ט", [5])
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, title="מקורי",
                mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("sum")]).json()["widget"]
    ver = _fresh(client, admin_id, d["id"])["config_version"]
    r = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/duplicate",
                    headers=AS(admin_id), json={"config_version": ver})
    assert r.status_code == 200, r.text
    copy = r.json()["widget"]
    assert copy["id"] != w["id"] and copy["title"] == "מקורי (עותק)"
    assert copy["metrics"] == w["metrics"] and copy["mapping"] == w["mapping"]
    client.patch(f"/api/dashboards/{d['id']}/widgets/{copy['id']}", headers=AS(admin_id),
                 json={"config_version": r.json()["config_version"],
                       "title": "שונה בעותק"})
    titles = {x["id"]: x["title"] for x in _fresh(client, admin_id, d["id"])["widgets"]}
    assert titles[w["id"]] == "מקורי"
    assert titles[copy["id"]] == "שונה בעותק"


def test_duplicating_cannot_step_over_the_widget_ceiling(client, admin_id):
    """DASH-12.3 — a limit a duplicate could step over is not a limit."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "תקרת שכפול")
    d = _dash(client, admin_id, env, [bid])
    ver = d["config_version"]
    first = None
    for i in range(20):
        out = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                          json={"config_version": ver, "type": "numbers",
                                "title": f"מדד {i}",
                                "metrics": [{"key": "m", "calc": "count"}]}).json()
        ver = out["config_version"]
        first = first or out["widget"]["id"]
    r = client.post(f"/api/dashboards/{d['id']}/widgets/{first}/duplicate",
                    headers=AS(admin_id), json={"config_version": ver})
    assert r.status_code == 400 and "20" in r.json()["detail"]


# ── DASH-15 · פורמט ויחידה ──────────────────────────────────────────────────

def test_the_format_travels_with_the_figure_and_never_changes_it(client, admin_id):
    """"העיגול ישפיע על התצוגה בלבד" — so the response carries the full value
    AND how to show it, and never a figure that has already been rounded."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "פורמט")
    base = _add_col(client, bid, admin_id, {"type": "number", "title": "בסיס"})
    third = _add_col(client, bid, admin_id,
                     {"type": "formula", "title": "שליש", "formula": "{בסיס}/3"})
    _item(client, bid, admin_id, "אחד", cf={base["id"]: 1})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": third["id"]}},
                metrics=[_metric("sum", format="number", precision=2)]).json()["widget"]
    m = _compute(client, admin_id, d["id"], w["id"])["metrics"][0]
    assert m["precision"] == 2 and m["format"] == "number"
    assert abs(m["result"] - 1 / 3) < 1e-9        # the full value, not 0.33


def test_a_percent_must_say_which_scale_its_column_is_in(client, admin_id):
    """"באחוזים יש להגדיר סולם מקור 0–1 או 0–100" — 0.5 and 50 are the same
    half and a column holds one of them."""
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "אחוזים", [0.5])
    d = _dash(client, admin_id, env, [bid])
    bad = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                  metrics=[_metric("sum", format="percent")])
    assert bad.status_code == 400 and "סולם" in bad.json()["detail"]
    ok = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                 metrics=[_metric("sum", format="percent", scale="0-1")])
    assert ok.status_code == 200, ok.text
    m = _compute(client, admin_id, d["id"], ok.json()["widget"]["id"])["metrics"][0]
    assert m["scale"] == "0-1"
    assert m["result"] == 0.5          # the label did not touch the value


def test_a_precision_outside_zero_to_four_is_refused(client, admin_id):
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "דיוק", [1])
    d = _dash(client, admin_id, env, [bid])
    r = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("sum", precision=7)])
    assert r.status_code == 400 and "דיוק" in r.json()["detail"]


def test_the_unit_comes_from_the_column_that_was_added_up(client, admin_id):
    """The figure's unit is a property of what it was made of, not of the
    request that asked for it."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "יחידה")
    col = _add_col(client, bid, admin_id,
                   {"type": "number", "title": "תקציב", "number": {"unit": "₪"}})
    _item(client, bid, admin_id, "אחד", cf={col["id"]: 100})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("sum", format="currency")]).json()["widget"]
    m = _compute(client, admin_id, d["id"], w["id"])["metrics"][0]
    assert m["unit"] == "₪" and m["format"] == "currency"
    assert m["calc"] == "sum"          # DASH-15.3 — the operation is shown too


# ── DASH-16 · המסנן המקומי ──────────────────────────────────────────────────

def test_a_local_filter_over_an_unmapped_field_cannot_be_saved(client, admin_id):
    """DASH-16.1 — "מיפוי חסר יחסום את הפעולה"."""
    env = _env(client, admin_id)
    a, ca = _numbers(client, admin_id, "מקומי א", [1])
    b, _cb = _numbers(client, admin_id, "מקומי ב", [2])
    d = _dash(client, admin_id, env, [a, b], name="מסנן מקומי")
    r = _widget(client, admin_id, d,
                mapping={str(a): {"amount": ca["id"]}},
                metrics=[{"key": "m", "calc": "count"}],
                filters={"adv": {"type": "group", "operator": "and", "rules": [
                    {"type": "rule", "field": "amount", "operator": "filled"}]}})
    assert r.status_code == 400
    assert "אינו ממופה" in r.json()["detail"]


def test_a_local_filter_does_not_reach_the_other_widgets(client, admin_id):
    """DASH-16.2 — "ולא ישנה ווידג׳טים אחרים"."""
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "מקומי בלבד", [1, 5, 10])
    d = _dash(client, admin_id, env, [bid])
    plain = _widget(client, admin_id, d, title="ללא מסנן",
                    mapping={str(bid): {"amount": col["id"]}},
                    metrics=[{"key": "m", "calc": "count"}]).json()
    d = _fresh(client, admin_id, d["id"])
    filtered = _widget(client, admin_id, d, title="עם מסנן",
                       mapping={str(bid): {"amount": col["id"]}},
                       metrics=[{"key": "m", "calc": "count"}],
                       filters={"adv": {"type": "group", "operator": "and", "rules": [
                           {"type": "rule", "field": "amount",
                            "operator": "gt", "value": 3}]}}).json()
    assert _compute(client, admin_id, d["id"],
                    plain["widget"]["id"])["metrics"][0]["result"] == 3
    assert _compute(client, admin_id, d["id"],
                    filtered["widget"]["id"])["metrics"][0]["result"] == 2


# ── DASH-17 · מסנן הדשבורד והסינון הזמני ────────────────────────────────────

def test_a_dashboard_filter_an_existing_widget_cannot_run_is_refused(client, admin_id):
    """DASH-17.1 — a shared condition that runs on four widgets and quietly
    does nothing on the fifth reads as five answers to one question."""
    env = _env(client, admin_id)
    a, ca = _numbers(client, admin_id, "דש-מסנן א", [1])
    b, _cb = _numbers(client, admin_id, "דש-מסנן ב", [2])
    d = _dash(client, admin_id, env, [a, b], name="מסנן דשבורד")
    _widget(client, admin_id, d, mapping={str(a): {"amount": ca["id"]}},
            metrics=[{"key": "m", "calc": "count"}])
    ver = _fresh(client, admin_id, d["id"])["config_version"]
    r = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                     json={"config_version": ver,
                           "filters": {"adv": {"type": "group", "operator": "and",
                                               "rules": [{"type": "rule",
                                                          "field": "amount",
                                                          "operator": "filled"}]}}})
    assert r.status_code == 400 and "אינו ממופה" in r.json()["detail"]


def test_a_visitors_filter_narrows_their_own_view_and_nobody_elses(
        client, admin_id, member_id):
    """R05 — "צופה מסנן זמנית לאורך הביקור בלבד, ללא השפעה על אחרים". The
    second reader is the assertion that matters."""
    env = _env(client, admin_id)
    join_primary_env(client, member_id)
    bid, col = _numbers(client, admin_id, "סינון זמני", [1, 5, 10])
    d = _dash(client, admin_id, env, [bid], name="זמני")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "viewer"})
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[{"key": "m", "calc": "count"}]).json()["widget"]
    temp = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "gt", "value": 3}]}}
    mine = _compute(client, member_id, d["id"], w["id"], temp_filter=temp)
    assert mine["metrics"][0]["result"] == 2
    assert mine["temporary_filter"] is True and mine["conditions"] == 1
    # the other reader, at the same moment, sees the saved configuration
    theirs = _compute(client, admin_id, d["id"], w["id"])
    assert theirs["metrics"][0]["result"] == 3
    assert theirs["temporary_filter"] is False and theirs["conditions"] == 0


def test_resetting_a_temporary_filter_is_simply_not_sending_it(client, admin_id):
    """"איפוס יחזיר למסננים השמורים" — nothing was stored, so nothing has to
    be undone."""
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "איפוס", [1, 5, 10])
    d = _dash(client, admin_id, env, [bid], name="איפוס")
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[{"key": "m", "calc": "count"}]).json()["widget"]
    temp = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "gt", "value": 3}]}}
    assert _compute(client, admin_id, d["id"], w["id"],
                    temp_filter=temp)["metrics"][0]["result"] == 2
    assert _compute(client, admin_id, d["id"], w["id"])["metrics"][0]["result"] == 3
    # and it never reached the stored configuration
    assert _fresh(client, admin_id, d["id"])["filters"] == {}


def test_a_temporary_filter_narrows_the_drilldown_the_same_way(client, admin_id):
    """R10 — the drill-down is the population the measure counted, and the
    visitor's filter is part of that population."""
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "זמני בפירוט", [1, 5, 10])
    d = _dash(client, admin_id, env, [bid], name="זמני פירוט")
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[{"key": "m", "calc": "count"}]).json()["widget"]
    temp = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "gt", "value": 3}]}}
    r = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/records",
                    headers=AS(admin_id), json={"temp_filter": temp, "limit": 50})
    body = r.json()
    assert body["records"] == 2 and len(body["rows"]) == 2


def test_the_active_condition_count_adds_up_all_three_layers(client, admin_id):
    """DASH-17.3 — "להציג את מספר התנאים הפעילים". Counted on the server
    because three places counting one thing is three places that can
    disagree about it."""
    env = _env(client, admin_id)
    bid, col = _numbers(client, admin_id, "מניין תנאים", [1, 5, 10, 50])
    d = _dash(client, admin_id, env, [bid], name="מניין")
    one = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "filled"}]}}
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[{"key": "m", "calc": "count"}], filters=one).json()["widget"]
    ver = _fresh(client, admin_id, d["id"])["config_version"]
    client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                 json={"config_version": ver,
                       "filters": {"adv": {"type": "group", "operator": "and", "rules": [
                           {"type": "rule", "field": "amount",
                            "operator": "gt", "value": 2}]}}})
    temp = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "lt", "value": 20}]}}
    out = _compute(client, admin_id, d["id"], w["id"], temp_filter=temp)
    assert out["conditions"] == 3            # dashboard + widget + visitor
    assert out["metrics"][0]["result"] == 2  # 5 and 10
