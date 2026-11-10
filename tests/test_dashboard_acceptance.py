"""בדיקות קבלה — DASH-29. The gate the version is delivered through.

DASH-29.4 names what blocks delivery, and it is not timing: "המסירה תתאפשר
רק לאחר סגירת תקלות שחושפות מידע או מציגות מדד שגוי ללא חיווי." So this file
is about those two failures and nothing else, asked against a population
whose every answer is worked out by hand in the comments.

What it covers, in the order DASH-29 lists it:

  1. both kinds of dashboard, end to end;
  2. a known population compared against numbers and every chart type, with
     several measures, units, formulas, a multi-valued mirror, blanks,
     missing periods, negatives, parents and children, and multi-person;
  3. direct API requests, permissions on indirect sources, access revoked
     while somebody is looking, data past the first page, refresh, request
     order and a concurrent save;
  4. the failure states — that nothing wrong is ever shown without saying so.

The per-story suites test each rule where it lives. This one is here to
catch what only shows up when they are put together.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import join_primary_env

AS = lambda uid: {"X-CityOS-User": str(uid)}

# The population of R04, which every numeric answer below is derived from.
R04 = [10, 0, None, 20, 30]


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


def _dash(client, admin_id, env, sources, **kw):
    return client.post("/api/dashboards", headers=AS(admin_id),
                       json={"environment_id": env, "name": kw.pop("name", "קבלה"),
                             "sources": [{"board_id": b, "groups": None} for b in sources],
                             **kw}).json()


def _add(client, admin_id, dash, **kw):
    r = client.post(f"/api/dashboards/{dash['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": dash["config_version"],
                          "type": "numbers", "title": "מדד", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _fresh(client, uid, did):
    return client.get(f"/api/dashboards/{did}", headers=AS(uid)).json()


def _compute(client, uid, did, wid, **body):
    r = client.post(f"/api/dashboards/{did}/widgets/{wid}/compute",
                    headers=AS(uid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _chart(client, uid, did, wid, **body):
    r = client.post(f"/api/dashboards/{did}/widgets/{wid}/chart",
                    headers=AS(uid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── 29.2 · אוכלוסייה ידועה, מול כל סוגי התצוגה ────────────────────────────

def test_the_known_population_gives_the_same_answers_everywhere(client, admin_id):
    """One population, five answers, each one worked out by hand.

    Five records carrying 10, 0, blank, 20 and 30 in a ₪ column, three of
    them "בוצע" and two "בטיפול":

      ספירה            5      — the blank is a record
      סכום             60     — and the stored 0 is a value
      ממוצע (התעלמות)  15     — 60 over the four that had one
      ממוצע (ריק כאפס) 12     — 60 over all five
      עמודות לפי סטטוס בוצע=30 (10+0+20 … no: 10+0 = 10), בטיפול=50

    The chart must agree with the figure: the bars of a status-grouped sum
    add up to the total, which is the property that catches a grouping bug
    that a single number cannot.
    """
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קבלה · אוכלוסייה")
    col = _add_col(client, bid, admin_id,
                   {"type": "number", "title": "ערך", "number": {"unit": "₪"}})
    # 10 and 0 are "בוצע"; blank, 20 and 30 are "בטיפול"
    for v, st in zip(R04, ["done", "done", "in_progress", "in_progress", "in_progress"]):
        _item(client, bid, admin_id, f"רשומה {v}", status=st,
              cf=({} if v is None else {col["id"]: v}))
    d = _dash(client, admin_id, env, [bid], name="קבלה")
    mapping = {str(bid): {"amount": col["id"]}}

    def num(calc, policy="ignore"):
        nonlocal d
        out = _add(client, admin_id, d, mapping=mapping,
                   metrics=[{"key": "m", "field": "amount", "calc": calc,
                             "empty_policy": policy, "format": "currency"}])
        d = _fresh(client, admin_id, d["id"])
        return _compute(client, admin_id, d["id"], out["widget"]["id"])["metrics"][0]

    cnt = _add(client, admin_id, d, metrics=[{"key": "m", "calc": "count"}])
    d = _fresh(client, admin_id, d["id"])
    assert _compute(client, admin_id, d["id"],
                    cnt["widget"]["id"])["metrics"][0]["result"] == 5
    assert num("sum")["result"] == 60
    assert num("avg", "ignore")["result"] == 15
    assert num("avg", "zero")["result"] == 12
    assert num("sum")["unit"] == "₪"

    # the same sum, grouped — and the bars add up to it
    ch = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                     json={"config_version": d["config_version"], "type": "chart",
                           "title": "לפי סטטוס", "mapping": mapping,
                           "metrics": [{"key": "m", "field": "amount", "calc": "sum"}],
                           "chart": {"type": "vbar", "dimension": "status"}}).json()
    bars = _chart(client, admin_id, d["id"], ch["widget"]["id"])
    by = dict(zip([c["label"] for c in bars["categories"]], bars["series"][0]["points"]))
    assert by["בוצע"] == 10          # 10 + 0
    assert by["בטיפול"] == 50        # blank + 20 + 30
    assert sum(bars["series"][0]["points"]) == 60


def test_a_parent_and_its_child_are_two_independent_records(client, admin_id):
    """R02 — "אב וילדים הם רשומות עצמאיות, ללא ירושת ערכים". 7 on the parent
    and 3 on the child is 10 across both and 7 across items alone — nothing
    is inherited in either direction."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קבלה · אב וילד")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    parent = _item(client, bid, admin_id, "אב", cf={col["id"]: 7})
    _item(client, bid, admin_id, "ילד", parent_id=parent, cf={col["id"]: 3})
    d = _dash(client, admin_id, env, [bid], name="אב וילד")
    mapping = {str(bid): {"amount": col["id"]}}
    got = {}
    for scope in ("items", "subitems", "both"):
        w = _add(client, admin_id, d, record_scope=scope, mapping=mapping,
                 metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
        d = _fresh(client, admin_id, d["id"])
        got[scope] = _compute(client, admin_id, d["id"],
                              w["widget"]["id"])["metrics"][0]
    assert got["items"]["result"] == 7 and got["items"]["records"] == 1
    assert got["subitems"]["result"] == 3 and got["subitems"]["records"] == 1
    assert got["both"]["result"] == 10 and got["both"]["records"] == 2


def test_negatives_are_summed_and_refused_by_a_pie(client, admin_id):
    """A negative is a value — "אין להחריג שליליים אוטומטית" — so a sum
    includes it, and a pie refuses to draw rather than dropping it."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קבלה · שליליים")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    for v, st in ((10, "done"), (-4, "in_progress")):
        _item(client, bid, admin_id, f"v{v}", status=st, cf={col["id"]: v})
    d = _dash(client, admin_id, env, [bid], name="שליליים")
    mapping = {str(bid): {"amount": col["id"]}}
    w = _add(client, admin_id, d, mapping=mapping,
             metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    d = _fresh(client, admin_id, d["id"])
    assert _compute(client, admin_id, d["id"],
                    w["widget"]["id"])["metrics"][0]["result"] == 6
    ch = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                     json={"config_version": d["config_version"], "type": "chart",
                           "title": "עוגה", "mapping": mapping,
                           "metrics": [{"key": "m", "field": "amount", "calc": "sum"}],
                           "chart": {"type": "pie", "dimension": "status"}}).json()
    out = _chart(client, admin_id, d["id"], ch["widget"]["id"])
    # the server computes it; the refusal to draw a share of a non-total is
    # the renderer's, and it is asserted in tests/test_dashboard_charts_ui.py
    assert out["state"] == "ok"
    assert sorted(out["series"][0]["points"]) == [-4, 10]


def test_a_formula_and_a_multi_valued_mirror_both_reach_the_total(client, admin_id):
    """DASH-29.2 names both as sources that must be exercised together. The
    formula doubles; the mirror is summed per item before the widget adds
    the items up (R03)."""
    env = _env(client, admin_id)
    far = _board(client, admin_id, "קבלה · רחוק")
    near = _board(client, admin_id, "קבלה · קרוב")
    fc = _add_col(client, far, admin_id, {"type": "number", "title": "ערך רחוק"})
    linked = [_item(client, far, admin_id, f"ר{v}", cf={fc["id"]: v}) for v in (10, 20, 30)]
    base = _add_col(client, near, admin_id, {"type": "number", "title": "בסיס"})
    calc = _add_col(client, near, admin_id,
                    {"type": "formula", "title": "כפול", "formula": "{בסיס}*2"})
    conn = _add_col(client, near, admin_id,
                    {"type": "connect", "title": "קישור",
                     "connect": {"board_ids": [far], "multiple": True, "two_way": False}})
    mir = _add_col(client, near, admin_id,
                   {"type": "mirror", "title": "מראה",
                    "mirror_of": {"connect": conn["id"], "field": fc["id"]}})
    _item(client, near, admin_id, "מקושר", cf={base["id"]: 5, conn["id"]: linked})
    _item(client, near, admin_id, "בודד", cf={base["id"]: 1})
    d = _dash(client, admin_id, env, [near], name="נוסחה ומראה")
    mapping = {str(near): {"calcd": calc["id"], "mir": mir["id"]}}
    f = _add(client, admin_id, d, mapping=mapping,
             metrics=[{"key": "m", "field": "calcd", "calc": "sum"}])
    d = _fresh(client, admin_id, d["id"])
    m = _add(client, admin_id, d, mapping=mapping,
             metrics=[{"key": "m", "field": "mir", "calc": "sum", "mirror_agg": "sum"}])
    d = _fresh(client, admin_id, d["id"])
    assert _compute(client, admin_id, d["id"],
                    f["widget"]["id"])["metrics"][0]["result"] == 12      # 5*2 + 1*2
    mm = _compute(client, admin_id, d["id"], m["widget"]["id"])["metrics"][0]
    assert mm["result"] == 60                                             # 10+20+30
    assert mm["values"] == 1                                              # one item
    assert mm["records"] == 2                                             # the other is blank


# ── 29.1 · שני סוגי הדשבורד ────────────────────────────────────────────────

def test_a_board_dashboard_goes_through_the_whole_process_too(client, admin_id):
    """DASH-29.1 — "לבדוק בשני סוגי הדשבורד תהליך מלא". The board kind holds
    its host board as its only source and answers through the same engine."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קבלה · תצוגת לוח")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    for v in (10, 20):
        _item(client, bid, admin_id, f"פ{v}", cf={col["id"]: v})
    d = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                    json={"name": "תצוגת דשבורד"}).json()
    assert d["kind"] == "board" and [s["board_id"] for s in d["sources"]] == [bid]
    w = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": d["config_version"], "type": "numbers",
                          "title": "סכום", "mapping": {str(bid): {"amount": col["id"]}},
                          "metrics": [{"key": "m", "field": "amount",
                                       "calc": "sum"}]}).json()
    assert _compute(client, admin_id, d["id"],
                    w["widget"]["id"])["metrics"][0]["result"] == 30
    rows = client.post(f"/api/dashboards/{d['id']}/widgets/{w['widget']['id']}/records",
                       headers=AS(admin_id), json={}).json()
    assert rows["records"] == 2
    again = _fresh(client, admin_id, d["id"])
    assert again["name"] == "תצוגת דשבורד" and again["board_id"] == bid


# ── 29.3 · API ישיר, הרשאות, עימוד, סדר ושמירה מקבילה ─────────────────────

def test_access_revoked_while_looking_removes_the_data_at_once(client, admin_id,
                                                               guinea_id):
    """R01 — "שלילת הרשאה תסיר מיד מידע לא מורשה גם מפירוט שכבר פתוח". The
    next request is the test: nothing is served from what was true before."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    bid = _board(client, admin_id, "קבלה · שלילת גישה")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    _item(client, bid, admin_id, "פריט", cf={col["id"]: 42})
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    d = _dash(client, admin_id, env, [bid], name="שלילה")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "viewer"})
    w = _add(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
             metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    wid = w["widget"]["id"]
    assert _compute(client, guinea_id, d["id"], wid)["metrics"][0]["result"] == 42
    drill = client.post(f"/api/dashboards/{d['id']}/widgets/{wid}/records",
                        headers=AS(guinea_id), json={}).json()
    assert drill["records"] == 1
    client.delete(f"/api/boards/{bid}/members/{guinea_id}", headers=AS(admin_id))
    after = _compute(client, guinea_id, d["id"], wid)
    assert after["state"] == "blocked" and after["metrics"] == []
    reopened = client.post(f"/api/dashboards/{d['id']}/widgets/{wid}/records",
                           headers=AS(guinea_id), json={}).json()
    assert reopened["state"] == "blocked" and reopened["rows"] == []
    assert reopened["records"] is None


def test_the_measure_counts_past_the_first_page(client, admin_id):
    """DASH-29.3 — "נתונים מעבר לעמוד הראשון". The figure is over the whole
    population; the list is what is paged."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קבלה · עימוד")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    for i in range(120):
        _item(client, bid, admin_id, f"פ{i}", cf={col["id"]: 1})
    d = _dash(client, admin_id, env, [bid], name="עימוד")
    w = _add(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
             metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    wid = w["widget"]["id"]
    assert _compute(client, admin_id, d["id"], wid)["metrics"][0]["result"] == 120
    seen, offset = [], 0
    while True:
        page = client.post(f"/api/dashboards/{d['id']}/widgets/{wid}/records",
                           headers=AS(admin_id),
                           json={"offset": offset, "limit": 50}).json()
        assert page["records"] == 120 and page["result"] == 120
        seen += page["rows"]
        if not page["has_more"]:
            break
        offset += 50
    assert len(seen) == 120 and len({r["id"] for r in seen}) == 120


def test_two_people_saving_at_once_do_not_overwrite_each_other(client, admin_id,
                                                               member_id):
    """DASH-29.3 — "שמירה מקבילה". Both hold the same version; the second one
    through is refused and told what the current version is."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קבלה · שמירה מקבילה")
    d = _dash(client, admin_id, env, [bid], name="מקבילה")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": member_id, "role": "owner"})
    ver = _fresh(client, admin_id, d["id"])["config_version"]
    first = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                         json={"config_version": ver, "name": "של הראשון"})
    second = client.patch(f"/api/dashboards/{d['id']}", headers=AS(member_id),
                          json={"config_version": ver, "name": "של השני"})
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["config_version"] == first.json()["config_version"]
    assert _fresh(client, admin_id, d["id"])["name"] == "של הראשון"


def test_every_dashboard_route_refuses_a_stranger(client, admin_id, guinea_id):
    """DASH-29.3 — "לבדוק בקשות API ישירות". There is no screen in this test;
    the endpoints are the whole of the defence."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    bid = _board(client, admin_id, "קבלה · זרים")
    d = _dash(client, admin_id, env, [bid], name="פרטי", visibility="private")
    w = _add(client, admin_id, d, metrics=[{"key": "m", "calc": "count"}])
    wid = w["widget"]["id"]
    did = d["id"]
    probes = [
        ("GET", f"/api/dashboards/{did}", None),
        ("POST", f"/api/dashboards/{did}/widgets", {"config_version": 1, "title": "x"}),
        ("POST", f"/api/dashboards/{did}/widgets/{wid}/compute", {}),
        ("POST", f"/api/dashboards/{did}/widgets/{wid}/chart", {}),
        ("POST", f"/api/dashboards/{did}/widgets/{wid}/records", {}),
        ("POST", f"/api/dashboards/{did}/widgets/preview", {"title": "x"}),
        ("POST", f"/api/dashboards/{did}/duplicate", {}),
        ("POST", f"/api/dashboards/{did}/mapping-proposal",
         {"reference_board_id": bid, "fields": {"a": "b"}}),
        ("GET", f"/api/dashboards/{did}/members", None),
        ("GET", f"/api/dashboards/{did}/sources/{bid}/impact", None),
        ("DELETE", f"/api/dashboards/{did}", None),
    ]
    for method, path, body in probes:
        r = client.request(method, path, headers=AS(guinea_id),
                           **({"json": body} if body is not None else {}))
        assert r.status_code in (403, 404), f"{method} {path} → {r.status_code}"
        assert "קבלה" not in r.text and str(bid) not in r.text, \
            f"{method} {path} leaked something"


def test_an_indirect_source_is_enforced_on_every_door(client, admin_id, guinea_id):
    """DASH-29.3 — "הרשאות למקורות עקיפים". A mirror reads another board, and
    every way into the widget has to know it."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    near = _board(client, admin_id, "קבלה · עקיף קרוב")
    far = _board(client, admin_id, "קבלה · עקיף רחוק")
    client.post(f"/api/boards/{near}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    fc = _add_col(client, far, admin_id, {"type": "number", "title": "ערך"})
    t = _item(client, far, admin_id, "רחוק", cf={fc["id"]: 99})
    conn = _add_col(client, near, admin_id,
                    {"type": "connect", "title": "קישור",
                     "connect": {"board_ids": [far], "multiple": True, "two_way": False}})
    mir = _add_col(client, near, admin_id,
                   {"type": "mirror", "title": "מראה",
                    "mirror_of": {"connect": conn["id"], "field": fc["id"]}})
    _item(client, near, admin_id, "קרוב", cf={conn["id"]: [t]})
    d = _dash(client, admin_id, env, [near], name="עקיף")
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "viewer"})
    w = _add(client, admin_id, d, mapping={str(near): {"amount": mir["id"]}},
             metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    wid = w["widget"]["id"]
    assert _compute(client, admin_id, d["id"], wid)["metrics"][0]["result"] == 99
    for path in ("compute", "chart", "records"):
        r = client.post(f"/api/dashboards/{d['id']}/widgets/{wid}/{path}",
                        headers=AS(guinea_id), json={}).json()
        assert r["state"] == "blocked", path
        # Checked by NAME and by structure rather than by scanning the text
        # for an id: a board id of 19 turns up inside a timestamp, and a
        # leak test that cries wolf is one that gets deleted.
        assert "קבלה · עקיף רחוק" not in str(r), path
        assert not r.get("metrics") and not r.get("rows"), path
        assert r.get("records") in (None,), path
        assert not r.get("categories") and not r.get("series"), path
    shown = _fresh(client, guinea_id, d["id"])["widgets"][0]
    assert shown["state"] == "blocked" and shown.get("mapping", {}) == {}


# ── 29.4 · שום מדד שגוי ללא חיווי ──────────────────────────────────────────

def test_nothing_wrong_is_ever_shown_as_a_number(client, admin_id):
    """DASH-29.4, and the sentence the whole gate turns on. Four ways a
    measure can fail, and not one of them comes back as a figure."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קבלה · מצבים")
    base = _add_col(client, bid, admin_id, {"type": "number", "title": "בסיס"})
    bad = _add_col(client, bid, admin_id,
                   {"type": "formula", "title": "שבורה", "formula": "{אין כזו}+1"})
    _item(client, bid, admin_id, "פריט", cf={base["id"]: 1})
    d = _dash(client, admin_id, env, [bid], name="מצבים")

    # 1 · a broken formula — reported, never 0
    broken = _add(client, admin_id, d, mapping={str(bid): {"amount": bad["id"]}},
                  metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    d = _fresh(client, admin_id, d["id"])
    m = _compute(client, admin_id, d["id"],
                 broken["widget"]["id"])["metrics"][0]
    assert m["state"] == "needs_fix" and m["result"] is None and m["failed"] == 1

    # 2 · an average with nothing to average — "אין נתונים", never 0
    empty = _board(client, admin_id, "קבלה · ריק")
    ec = _add_col(client, empty, admin_id, {"type": "number", "title": "ערך"})
    d2 = _dash(client, admin_id, env, [empty], name="ריק")
    avg = _add(client, admin_id, d2, mapping={str(empty): {"amount": ec["id"]}},
               metrics=[{"key": "m", "field": "amount", "calc": "avg"}])
    got = _compute(client, admin_id, d2["id"],
                   avg["widget"]["id"])["metrics"][0]
    assert got["state"] == "no_data" and got["result"] is None

    # 3 · a sum with no numeric values — a true 0, and it says why
    d2 = _fresh(client, admin_id, d2["id"])
    s = _add(client, admin_id, d2, mapping={str(empty): {"amount": ec["id"]}},
             metrics=[{"key": "m", "field": "amount", "calc": "sum"}])
    zero = _compute(client, admin_id, d2["id"], s["widget"]["id"])["metrics"][0]
    assert zero["state"] == "ok" and zero["result"] == 0 and zero["records"] == 0

    # 4 · a chart past its limits — blocked with an explanation, nothing cut
    many = _board(client, admin_id, "קבלה · מגבלה")
    for i in range(51):
        g = client.post("/api/groups", json={"board_id": many, "name": f"ק{i:03d}",
                                             "user_id": admin_id}).json()["id"]
        _item(client, many, admin_id, f"פ{i}", group_id=g)
    d3 = _dash(client, admin_id, env, [many], name="מגבלה")
    ch = client.post(f"/api/dashboards/{d3['id']}/widgets", headers=AS(admin_id),
                     json={"config_version": d3["config_version"], "type": "chart",
                           "title": "יותר מדי",
                           "metrics": [{"key": "m", "calc": "count"}],
                           "chart": {"type": "vbar", "dimension": "group"}}).json()
    out = _chart(client, admin_id, d3["id"], ch["widget"]["id"])
    assert out["state"] == "too_many" and out["categories"] == []
    assert out["found"] == 51 and "50" in out["reason"]


# ── שני סוגי הדשבורד, כפי שמגיעים אליהם ───────────────────────────────────

def test_a_board_dashboard_appears_in_the_boards_view_strip(client, admin_id):
    """DASH-05.1 — "יצירה בלוח תתבצע דרך הוספת תצוגה, בחירת דשבורד והזנת שם."

    The strip is where a board dashboard is reached from, so the views
    endpoint has to say two things about the row: that it IS a dashboard,
    and which one — otherwise the tab can be drawn and not opened.
    """
    bid = _board(client, admin_id, "רצועה · דשבורד")
    d = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                    json={"name": "מדדי הלוח"}).json()
    strip = client.get(f"/api/boards/{bid}/views", headers=AS(admin_id)).json()["views"]
    tab = next((v for v in strip if v["id"] == d["view_id"]), None)
    assert tab is not None, "the dashboard is not a tab on its board"
    assert tab["kind"] == "dash"
    assert tab["dashboard_id"] == d["id"]
    assert tab["name"] == "מדדי הלוח"
    assert tab["filters"] == {}          # it holds no cut
    assert tab["can_edit"] is True


def test_a_dashboard_tab_is_renamed_and_deleted_like_any_other(client, admin_id):
    """It is a tab on the board, so the board's own machinery runs it — and
    the cut endpoints refuse it, exactly as they refuse a form."""
    bid = _board(client, admin_id, "רצועה · ניהול")
    d = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                    json={"name": "לפני"}).json()
    vid = d["view_id"]
    # Renamed through the dashboard endpoint, which is the one door a
    # dashboard tab has: the view endpoint refuses it outright because a
    # dashboard is not a cut, exactly as it refuses a form (a form renames
    # through /api/forms for the same reason).
    ver = client.get(f"/api/dashboards/{d['id']}",
                     headers=AS(admin_id)).json()["config_version"]
    r = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                     json={"config_version": ver, "name": "אחרי"})
    assert r.status_code == 200, r.text
    strip = client.get(f"/api/boards/{bid}/views", headers=AS(admin_id)).json()["views"]
    assert next(v for v in strip if v["id"] == vid)["name"] == "אחרי"
    # a dashboard is not a cut: saving one over it is refused by name
    bad = client.patch(f"/api/views/{vid}", headers=AS(admin_id),
                       json={"user_id": admin_id, "config_version": 1,
                             "filters": {"q": "x"}})
    assert bad.status_code == 400 and "דשבורד" in bad.json()["detail"]
    dup = client.post(f"/api/views/{vid}/duplicate", headers=AS(admin_id),
                      json={"user_id": admin_id})
    assert dup.status_code == 400
    # deleting the tab takes it off the strip
    assert client.delete(f"/api/views/{vid}?user_id={admin_id}").status_code == 200
    strip = client.get(f"/api/boards/{bid}/views", headers=AS(admin_id)).json()["views"]
    assert not any(v["id"] == vid for v in strip)


def test_both_kinds_hold_the_same_widgets_and_answer_the_same(client, admin_id):
    """The two forms differ in where they are reached from and in nothing
    else: the same widget over the same records gives the same number."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "שני הסוגים")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    for v in (10, 20, 30):
        _item(client, bid, admin_id, f"פ{v}", cf={col["id"]: v})
    metric = [{"key": "m", "field": "amount", "calc": "sum"}]
    mapping = {str(bid): {"amount": col["id"]}}

    on_board = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                           json={"name": "בלוח"}).json()
    standalone = _dash(client, admin_id, env, [bid], name="עצמאי")
    answers = []
    for d in (on_board, standalone):
        w = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                        json={"config_version": d["config_version"], "type": "numbers",
                              "title": "סכום", "mapping": mapping,
                              "metrics": metric}).json()["widget"]
        answers.append(_compute(client, admin_id, d["id"], w["id"])["metrics"][0])
    assert answers[0]["result"] == answers[1]["result"] == 60
    assert answers[0]["records"] == answers[1]["records"] == 3
    # and the charts agree too
    for d in (on_board, standalone):
        fresh = _fresh(client, admin_id, d["id"])
        ch = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                         json={"config_version": fresh["config_version"], "type": "chart",
                               "title": "תרשים", "mapping": mapping, "metrics": metric,
                               "chart": {"type": "vbar", "dimension": "status"}}).json()
        out = _chart(client, admin_id, d["id"], ch["widget"]["id"])
        assert sum(out["series"][0]["points"]) == 60


def test_adding_a_dashboard_view_never_asks_for_a_name(client, admin_id):
    """It is created the way every other thing on a board is — at once, under
    a free default name, renamed from where it then is. A table view, a form
    and a board itself all work that way; the dashboard was the only one that
    stopped to ask.

    The name is the server's, which is also what stops two made in a row from
    colliding — the thing a box asking for a name quietly gets wrong.
    """
    bid = _board(client, admin_id, "ללא שאלת שם")
    first = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                        json={}).json()
    second = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                         json={}).json()
    assert first["name"] == "דשבורד חדש"
    assert second["name"] != first["name"], "two dashboards took the same name"
    assert second["name"].startswith("דשבורד חדש")
    # both are on the strip, and both are openable
    strip = client.get(f"/api/boards/{bid}/views", headers=AS(admin_id)).json()["views"]
    got = {v["id"]: v for v in strip}
    for d in (first, second):
        assert got[d["view_id"]]["dashboard_id"] == d["id"]
    # and renaming afterwards is the ordinary tab rename
    ver = client.get(f"/api/dashboards/{first['id']}",
                     headers=AS(admin_id)).json()["config_version"]
    r = client.patch(f"/api/dashboards/{first['id']}", headers=AS(admin_id),
                     json={"config_version": ver, "name": "מדדי התקציב"})
    assert r.status_code == 200
    strip = client.get(f"/api/boards/{bid}/views", headers=AS(admin_id)).json()["views"]
    assert next(v for v in strip if v["id"] == first["view_id"])["name"] == "מדדי התקציב"
