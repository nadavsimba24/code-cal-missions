"""Charts: what they are grouped by, how their series are formed, and when
a configuration is refused.

This is DASH-22 — the half every chart type shares — and the rules it is made
of are R06 (grouping and series) and R07 (periods). Both are easy to
implement in a way that looks right and is wrong, which is why so much of
this file is about numbers rather than shapes:

· a record assigned to three people belongs to three categories, **with its
  full value in each** (R06). The bars then add up to more than the total,
  and that is a fact about the data, flagged rather than smoothed away;
· a week starts on Sunday, not Monday — one day out and every weekly bar is
  wrong while the chart still looks plausible;
· a month with no records is a month in which nothing happened, not a row to
  skip; and in an average it is a GAP, not a zero (R07, DASH-27.3);
· two categories with the same total must not swap places between refreshes.

The type-specific rules are asserted as refusals at save time, because that
is where the spec puts them: a chart accepted and then uncomputable is a
problem in front of somebody who did not configure it.
"""
import datetime

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


def _group(client, bid, admin_id, name):
    return client.post("/api/groups", json={"board_id": bid, "name": name,
                                            "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title, **kw):
    cf = kw.pop("cf", None)
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id, **kw}).json()["id"]
    if cf:
        client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": cf})
    return tid


def _env(client, admin_id):
    for e in client.get("/api/environments", headers=AS(admin_id)).json()["environments"]:
        if e.get("is_primary"):
            return e["id"]


def _dash(client, admin_id, env_id, sources, name="תרשים"):
    return client.post("/api/dashboards", headers=AS(admin_id),
                       json={"environment_id": env_id, "name": name,
                             "sources": [{"board_id": b, "groups": None}
                                         for b in sources]}).json()


def _widget(client, admin_id, dash, **kw):
    return client.post(f"/api/dashboards/{dash['id']}/widgets", headers=AS(admin_id),
                       json={"config_version": dash["config_version"],
                             "type": "chart", "title": "תרשים", **kw})


def _chart(client, uid, dash_id, wid, **body):
    r = client.post(f"/api/dashboards/{dash_id}/widgets/{wid}/chart",
                    headers=AS(uid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _cell(out, series_key, cat_label):
    cats = [c["label"] for c in out["categories"]]
    s = next(x for x in out["series"] if x["key"] == series_key)
    return s["points"][cats.index(cat_label)]


COUNT = [{"key": "m", "calc": "count"}]


# ── R06 · הקיבוץ ────────────────────────────────────────────────────────────

def test_a_chart_may_only_be_grouped_by_the_four_the_spec_names(client, admin_id):
    """"קיבוץ לפי קבוצה, סטטוס, אדם ותאריך בלבד" — a chart grouped by a
    free-text column is a chart with one bar per item."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "ממדים")
    txt = _add_col(client, bid, admin_id, {"type": "text", "title": "הערה"})
    d = _dash(client, admin_id, env, [bid])
    bad = _widget(client, admin_id, d, metrics=COUNT,
                  chart={"type": "vbar", "dimension": txt["id"]})
    assert bad.status_code == 400
    for dim in ("group", "status", "person", "date"):
        ok = _widget(client, admin_id, d, metrics=COUNT,
                     chart={"type": "vbar", "dimension": dim})
        assert ok.status_code == 200, f"{dim}: {ok.text}"
        d = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()


def test_a_board_that_hides_a_builtin_is_not_grouped_by_it(client, admin_id):
    """A board may take the built-in columns off itself, and a monday import
    switches all four off at once — so an imported board shows no סטטוס, no
    אחראים and no תאריך יעד anywhere.

    Three of the four built-in dimensions ARE those fields, so grouping by
    one of them on such a board groups by a column the board does not have:
    every record carries the default status, nobody is assigned, nothing has
    a due date, and the chart comes out as a single bar or a column of "ללא
    ערך". The report was "העמודות שמופיעות אינן העמודות של הלוח הנבחר".

    The board's own filter has refused a hidden built-in since
    `query_board_items` learned to prune one — a chart is the same question
    asked a different way, so it is refused at save time rather than drawn.
    """
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "לוח מיובא")
    dt = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד"})
    client.patch(f"/api/boards/{bid}", headers=AS(admin_id),
                 json={"actor_id": admin_id,
                       "col_hidden": ["assignees", "status", "priority", "due"]})
    d = _dash(client, admin_id, env, [bid])

    def fresh():
        return client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()

    for dim in ("status", "person"):
        bad = _widget(client, admin_id, d, metrics=COUNT,
                      chart={"type": "vbar", "dimension": dim})
        assert bad.status_code == 400, f"{dim}: {bad.text}"
        assert "אינו מציג" in bad.json()["detail"], bad.text

    # A group belongs to the board itself and cannot be hidden.
    ok = _widget(client, admin_id, d, metrics=COUNT,
                 chart={"type": "vbar", "dimension": "group"})
    assert ok.status_code == 200, ok.text
    d = fresh()

    # The date dimension reads the due date only while nothing better is
    # named, so it is refused bare and accepted the moment a date column of
    # the board is mapped in its place.
    bad = _widget(client, admin_id, d, metrics=COUNT,
                  chart={"type": "vbar", "dimension": "date"})
    assert bad.status_code == 400, bad.text
    d = fresh()
    good = _widget(client, admin_id, d, metrics=COUNT,
                   mapping={str(bid): {"__date__": dt["id"]}},
                   chart={"type": "vbar", "dimension": "date"})
    assert good.status_code == 200, good.text
    d = fresh()

    # …and a SPLIT by a hidden built-in is refused for the same reason.
    split = _widget(client, admin_id, d, metrics=COUNT,
                    chart={"type": "vbar", "dimension": "group", "split": "status"})
    assert split.status_code == 400, split.text


def test_grouping_by_group_counts_each_group_once(client, admin_id):
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "לפי קבוצה")
    a = _group(client, bid, admin_id, "אלפא")
    b = _group(client, bid, admin_id, "ביתא")
    for i in range(3):
        _item(client, bid, admin_id, f"א{i}", group_id=a)
    _item(client, bid, admin_id, "ב0", group_id=b)
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "group"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    assert out["state"] == "ok"
    assert {c["label"] for c in out["categories"]} == {"אלפא", "ביתא"}
    assert _cell(out, "m", "אלפא") == 3
    assert _cell(out, "m", "ביתא") == 1


def test_a_record_on_three_people_is_in_three_categories_with_its_whole_value(
        client, admin_id, member_id, guinea_id):
    """R06 — "ריבוי אנשים משייך את הרשומה ואת מלוא ערכה לכל אדם, עם חיווי
    שרשומה עשויה להופיע ביותר מקטגוריה אחת."

    The full value to each, deliberately: the question a person-grouped chart
    answers is "how much is on each person's plate", and splitting 90 three
    ways answers a different one. The total then exceeds the population, and
    the response says so rather than hiding it.
    """
    env = _env(client, admin_id)
    join_primary_env(client, member_id)
    join_primary_env(client, guinea_id)
    bid = _board(client, admin_id, "ריבוי אנשים")
    for uid in (member_id, guinea_id):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "שעות"})
    t = _item(client, bid, admin_id, "משותף", cf={col["id"]: 90})
    for uid in (admin_id, member_id, guinea_id):
        client.post(f"/api/tasks/{t}/assignees",
                    json={"actor_id": admin_id, "user_id": uid})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d,
                mapping={str(bid): {"amount": col["id"]}},
                metrics=[{"key": "m", "field": "amount", "calc": "sum"}],
                chart={"type": "vbar", "dimension": "person"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    assert len(out["categories"]) == 3
    assert all(s == 90 for s in out["series"][0]["points"])
    assert out["overlap"] is True            # the חיווי R06 asks for
    assert out["records"] == 1               # one record, three categories


def test_an_empty_dimension_becomes_a_category_that_can_be_hidden(client, admin_id):
    """R06 — "ממד ריק מוצג בקטגוריית ללא ערך כברירת מחדל וניתן להסתירו. זו
    הגדרה נפרדת ממדיניות ערך מספרי ריק"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "ללא ערך")
    g = _group(client, bid, admin_id, "יש")
    _item(client, bid, admin_id, "בקבוצה", group_id=g)
    _item(client, bid, admin_id, "ללא אחראי")
    d = _dash(client, admin_id, env, [bid])
    shown = _widget(client, admin_id, d, metrics=COUNT,
                    chart={"type": "vbar", "dimension": "person"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], shown["id"])
    assert "ללא ערך" in {c["label"] for c in out["categories"]}
    d = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    hidden = _widget(client, admin_id, d, metrics=COUNT,
                     chart={"type": "vbar", "dimension": "person",
                            "show_no_value": False}).json()["widget"]
    out2 = _chart(client, admin_id, d["id"], hidden["id"])
    assert "ללא ערך" not in {c["label"] for c in out2["categories"]}


def test_the_source_board_is_a_series_and_never_a_dimension(client, admin_id):
    """R06 — "להציג לוחות מקור כסדרות; לוח מקור אינו ממד קיבוץ נוסף"."""
    env = _env(client, admin_id)
    a, b = _board(client, admin_id, "לוח א"), _board(client, admin_id, "לוח ב")
    _item(client, a, admin_id, "a1", status="done")
    _item(client, a, admin_id, "a2", status="done")
    _item(client, b, admin_id, "b1", status="done")
    d = _dash(client, admin_id, env, [a, b])
    bad = _widget(client, admin_id, d, metrics=COUNT,
                  chart={"type": "vbar", "dimension": "board"})
    assert bad.status_code == 400
    # Status is the dimension here on purpose: its keys are a shared
    # vocabulary, so "בוצע" on two boards is ONE category. A group is
    # board-local — two groups that happen to share a name are two
    # categories, by id, which is the same rule the colours follow.
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "status",
                       "split": "board"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    assert len(out["series"]) == 2
    assert {s["label"] for s in out["series"]} == {"ספירה · לוח א", "ספירה · לוח ב"}
    byname = {s["label"]: s for s in out["series"]}
    i = [c["label"] for c in out["categories"]].index("בוצע")
    assert byname["ספירה · לוח א"]["points"][i] == 2
    assert byname["ספירה · לוח ב"]["points"][i] == 1


def test_splitting_by_the_dimension_itself_is_refused(client, admin_id):
    """It yields one series per category and a chart that says nothing."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "פיצול כפול")
    d = _dash(client, admin_id, env, [bid])
    r = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "status", "split": "status"})
    assert r.status_code == 400


def test_several_measures_must_share_a_unit(client, admin_id):
    """R06 — "כמה מדדים מותרים באותה יחידה ובציר משותף בלבד". Two quantities
    on one axis with two units are drawn as if they were comparable."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "יחידות בתרשים")
    c1 = _add_col(client, bid, admin_id,
                  {"type": "number", "title": "שקלים", "number": {"unit": "₪"}})
    d = _dash(client, admin_id, env, [bid])
    r = _widget(client, admin_id, d,
                mapping={str(bid): {"a": c1["id"], "b": c1["id"]}},
                metrics=[{"key": "a", "field": "a", "calc": "sum", "unit": "₪"},
                         {"key": "b", "field": "b", "calc": "sum", "unit": "שעות"}],
                chart={"type": "vbar", "dimension": "status"})
    assert r.status_code == 400 and "יחידה" in r.json()["detail"]


# ── R06 · המיון ─────────────────────────────────────────────────────────────

def test_categories_sort_by_label_or_by_value_in_either_direction(client, admin_id):
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "מיון")
    for name, n in (("גימל", 1), ("אלף", 3), ("בית", 2)):
        g = _group(client, bid, admin_id, name)
        for i in range(n):
            _item(client, bid, admin_id, f"{name}{i}", group_id=g)
    d = _dash(client, admin_id, env, [bid])

    def labels(**chart):
        nonlocal d
        w = _widget(client, admin_id, d, metrics=COUNT,
                    chart={"type": "vbar", "dimension": "group", **chart}).json()["widget"]
        d = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
        return [c["label"] for c in _chart(client, admin_id, d["id"], w["id"])["categories"]]

    assert labels(sort="label", direction="asc") == ["אלף", "בית", "גימל"]
    assert labels(sort="label", direction="desc") == ["גימל", "בית", "אלף"]
    assert labels(sort="value", direction="desc") == ["אלף", "בית", "גימל"]
    assert labels(sort="value", direction="asc") == ["גימל", "בית", "אלף"]


def test_two_categories_with_one_total_keep_a_stable_order(client, admin_id):
    """"שוויון לפי תווית ומזהה" — a chart that reorders itself on refresh over
    identical data is one nobody trusts."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "שוויון")
    for name in ("זהה ב", "זהה א"):
        g = _group(client, bid, admin_id, name)
        _item(client, bid, admin_id, name, group_id=g)
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "group",
                       "sort": "value", "direction": "desc"}).json()["widget"]
    runs = [[c["label"] for c in _chart(client, admin_id, d["id"], w["id"])["categories"]]
            for _ in range(3)]
    assert runs[0] == runs[1] == runs[2] == ["זהה א", "זהה ב"]


# ── R07 · התקופות ───────────────────────────────────────────────────────────

def test_a_week_starts_on_sunday(client, admin_id):
    """One day out and every weekly bar is wrong while the chart still looks
    plausible. 2026-03-08 is a Sunday; the Saturday before it belongs to the
    previous week."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "שבועות")
    col = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד"})
    for day in ("2026-03-07", "2026-03-08", "2026-03-09"):
        _item(client, bid, admin_id, day, cf={col["id"]: day})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                mapping={str(bid): {"__date__": col["id"]}},
                chart={"type": "vbar", "dimension": "date",
                       "period": "week"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    pts = dict(zip([c["label"] for c in out["categories"]], out["series"][0]["points"]))
    assert pts["שבוע 01/03/2026"] == 1        # the Saturday
    assert pts["שבוע 08/03/2026"] == 2        # Sunday and Monday


def test_a_period_with_no_records_is_a_zero_and_not_a_missing_row(client, admin_id):
    """R07 — "מציגים תקופות ביניים בין הראשונה לאחרונה", and a missing period
    "היא 0 בספירה ובסכום" — a month in which nothing happened, not a row to
    skip."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "פערים")
    col = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד"})
    _item(client, bid, admin_id, "ינואר", cf={col["id"]: "2026-01-15"})
    _item(client, bid, admin_id, "אפריל", cf={col["id"]: "2026-04-15"})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                mapping={str(bid): {"__date__": col["id"]}},
                chart={"type": "vbar", "dimension": "date",
                       "period": "month"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    labels = [c["label"] for c in out["categories"]]
    assert labels == ["ינואר 2026", "פברואר 2026", "מרץ 2026", "אפריל 2026"]
    assert out["series"][0]["points"] == [1, 0, 0, 1]


def test_a_missing_period_is_a_gap_in_an_average_and_not_a_zero(client, admin_id):
    """R07 again, and the half that matters for DASH-27.3: an average over no
    records has no value, and drawing it as 0 invents a month in which the
    average collapsed."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "פער בממוצע")
    col = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד"})
    num = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    _item(client, bid, admin_id, "ינואר", cf={col["id"]: "2026-01-15", num["id"]: 10})
    _item(client, bid, admin_id, "מרץ", cf={col["id"]: "2026-03-15", num["id"]: 30})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d,
                mapping={str(bid): {"__date__": col["id"], "amount": num["id"]}},
                metrics=[{"key": "m", "field": "amount", "calc": "avg"}],
                chart={"type": "line", "dimension": "date",
                       "period": "month"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    assert [c["label"] for c in out["categories"]] == \
        ["ינואר 2026", "פברואר 2026", "מרץ 2026"]
    assert out["series"][0]["points"] == [10, None, 30]     # a hole, not a 0


def test_a_period_label_always_carries_its_year(client, admin_id):
    """R07 — "תווית כוללת שנה או תאריך מלא כשנדרש להבחין בין תקופות". Two
    Marches labelled "מרץ" are two bars nobody can tell apart."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "שנתיים")
    col = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד"})
    _item(client, bid, admin_id, "א", cf={col["id"]: "2025-03-10"})
    _item(client, bid, admin_id, "ב", cf={col["id"]: "2026-03-10"})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                mapping={str(bid): {"__date__": col["id"]}},
                chart={"type": "vbar", "dimension": "date",
                       "period": "month"}).json()["widget"]
    labels = [c["label"] for c in _chart(client, admin_id, d["id"], w["id"])["categories"]]
    assert labels[0] == "מרץ 2025" and labels[-1] == "מרץ 2026"
    assert len(set(labels)) == len(labels)


# ── R10 · המגבלות ───────────────────────────────────────────────────────────

def test_too_many_categories_blocks_with_an_explanation_and_cuts_nothing(
        client, admin_id):
    """R10 — "חריגה חוסמת בהסבר; אין חיתוך, סכום חלקי או קטגוריית אחר
    אוטומטית"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "יותר מדי קטגוריות")
    for i in range(51):
        g = _group(client, bid, admin_id, f"ק{i:03d}")
        _item(client, bid, admin_id, f"פריט {i}", group_id=g)
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "group"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    assert out["state"] == "too_many" and out["limit"] == "categories"
    assert out["found"] == 51 and out["max"] == 50
    assert out["categories"] == []          # nothing truncated and shown anyway
    assert "50" in out["reason"]


def test_the_series_cap_counts_the_combinations_not_the_metrics(client, admin_id):
    """R10 — "10 סדרות לתרשים, כולל סדרות שנוצרו ממדדים מרובים". Three
    measures split four ways is twelve series, not three."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "סדרות")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    for i in range(4):
        g = _group(client, bid, admin_id, f"ג{i}")
        _item(client, bid, admin_id, f"פ{i}", group_id=g, cf={col["id"]: i})
    d = _dash(client, admin_id, env, [bid])
    metrics = [{"key": f"m{i}", "field": f"m{i}", "calc": "sum"} for i in range(3)]
    mapping = {str(bid): {f"m{i}": col["id"] for i in range(3)}}
    w = _widget(client, admin_id, d, mapping=mapping, metrics=metrics,
                chart={"type": "vbar", "dimension": "status",
                       "split": "group"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    assert out["state"] == "too_many" and out["limit"] == "series"
    assert out["found"] == 12 and out["max"] == 10


# ── DASH-22.2 · הצבעים ──────────────────────────────────────────────────────

def test_status_colours_come_from_the_board_and_a_local_change_stays_local(
        client, admin_id):
    """DASH-22.2 — "ברירת המחדל לצבעי סטטוס תילקח מהלוח. שינוי מקומי לא ישנה
    את הלוח, והצבעים יישמרו לפי מזהים"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "צבעי סטטוס")
    _item(client, bid, admin_id, "פריט", status="done")
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "status"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    done = next(c for c in out["categories"] if c["label"] == "בוצע")
    assert done["color"] == "#1AC877"            # the board's own
    ver = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()["config_version"]
    client.patch(f"/api/dashboards/{d['id']}/widgets/{w['id']}", headers=AS(admin_id),
                 json={"config_version": ver,
                       "chart": {"type": "vbar", "dimension": "status",
                                 "colors": {"done": "#0073ea"}}})
    again = _chart(client, admin_id, d["id"], w["id"])
    assert next(c for c in again["categories"] if c["label"] == "בוצע")["color"] == "#0073ea"
    # and the board is untouched
    statuses = client.get(f"/api/boards/{bid}").json().get("statuses") or []
    board_done = next((s for s in statuses if s["key"] == "done"), None)
    assert board_done is None or board_done["color"] == "#1AC877"


# ── DASH-23 → 27 · הכללים של כל סוג, בסדר הפיתוח ──────────────────────────

def test_a_single_category_chart_equals_the_numbers_widget(client, admin_id):
    """DASH-23.3 — "קטגוריה יחידה עם אותן הגדרות תציג ערך זהה לווידג׳ט
    מספרים". True because there is one computation, not two."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קטגוריה יחידה")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    for v in (10, 20, 30):
        _item(client, bid, admin_id, f"פ{v}", status="done", cf={col["id"]: v})
    d = _dash(client, admin_id, env, [bid])
    mapping = {str(bid): {"amount": col["id"]}}
    metrics = [{"key": "m", "field": "amount", "calc": "sum"}]
    num = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                      json={"config_version": d["config_version"], "type": "numbers",
                            "title": "מספר", "mapping": mapping,
                            "metrics": metrics}).json()
    ch = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                     json={"config_version": num["config_version"], "type": "chart",
                           "title": "תרשים", "mapping": mapping, "metrics": metrics,
                           "chart": {"type": "vbar", "dimension": "status"}}).json()
    figure = client.post(
        f"/api/dashboards/{d['id']}/widgets/{num['widget']['id']}/compute",
        headers=AS(admin_id), json={}).json()["metrics"][0]["result"]
    bars = _chart(client, admin_id, d["id"], ch["widget"]["id"])
    assert len(bars["categories"]) == 1
    assert bars["series"][0]["points"][0] == figure == 60


def test_horizontal_and_vertical_carry_the_same_values(client, admin_id):
    """DASH-24.2 — "מעבר בין אנכי לאופקי ישמור על המקורות, החישוב, המסננים,
    הצבעים והמיון ויציג את אותם ערכים"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "אנכי ואופקי")
    for name, n in (("א", 2), ("ב", 3)):
        g = _group(client, bid, admin_id, name)
        for i in range(n):
            _item(client, bid, admin_id, f"{name}{i}", group_id=g)
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "group",
                       "sort": "value", "direction": "desc"}).json()["widget"]
    before = _chart(client, admin_id, d["id"], w["id"])
    ver = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()["config_version"]
    client.patch(f"/api/dashboards/{d['id']}/widgets/{w['id']}", headers=AS(admin_id),
                 json={"config_version": ver,
                       "chart": {"type": "hbar", "dimension": "group",
                                 "sort": "value", "direction": "desc"}})
    after = _chart(client, admin_id, d["id"], w["id"])
    assert after["type"] == "hbar"
    assert [c["label"] for c in after["categories"]] == \
           [c["label"] for c in before["categories"]]
    assert after["series"][0]["points"] == before["series"][0]["points"]
    assert [c["color"] for c in after["categories"]] == \
           [c["color"] for c in before["categories"]]


def test_a_pie_takes_one_measure_and_no_split(client, admin_id):
    """R06 — "עוגה ודונאט משתמשות במדד אחד וללא פיצול נוסף"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "עוגה")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    d = _dash(client, admin_id, env, [bid])
    split = _widget(client, admin_id, d, metrics=COUNT,
                    chart={"type": "pie", "dimension": "status", "split": "group"})
    assert split.status_code == 400 and "פיצול" in split.json()["detail"]
    two = _widget(client, admin_id, d,
                  mapping={str(bid): {"a": col["id"], "b": col["id"]}},
                  metrics=[{"key": "a", "field": "a", "calc": "sum"},
                           {"key": "b", "field": "b", "calc": "sum"}],
                  chart={"type": "pie", "dimension": "status"})
    assert two.status_code == 400 and "מדד יחיד" in two.json()["detail"]


def test_a_stack_refuses_an_average(client, admin_id):
    """DASH-26.1 — "הן יתמכו בספירה ובסכום בלבד, ללא ממוצע". Stacking
    averages adds up numbers whose total means nothing."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "ערימה")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    d = _dash(client, admin_id, env, [bid])
    r = _widget(client, admin_id, d,
                mapping={str(bid): {"amount": col["id"]}},
                metrics=[{"key": "m", "field": "amount", "calc": "avg"}],
                chart={"type": "stacked", "dimension": "status", "split": "group"})
    assert r.status_code == 400 and "ממוצע" in r.json()["detail"]


def test_changing_to_a_stack_with_an_unsupported_calc_blocks_the_save(client, admin_id):
    """DASH-26.3 — "במעבר מסוג תרשים אחר, חישוב שאינו נתמך יחייב תיקון לפני
    שמירה"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "מעבר לערימה")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "ערך"})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d,
                mapping={str(bid): {"amount": col["id"]}},
                metrics=[{"key": "m", "field": "amount", "calc": "avg"}],
                chart={"type": "vbar", "dimension": "status"}).json()["widget"]
    ver = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()["config_version"]
    r = client.patch(f"/api/dashboards/{d['id']}/widgets/{w['id']}", headers=AS(admin_id),
                     json={"config_version": ver,
                           "chart": {"type": "stacked", "dimension": "status"}})
    assert r.status_code == 400 and "ממוצע" in r.json()["detail"]


def test_a_line_demands_a_date_dimension(client, admin_id):
    """DASH-27.1 — "הוא יחייב ממד תאריך; בחירה בממד אחר תחסום שמירה"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "קו")
    d = _dash(client, admin_id, env, [bid])
    r = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "line", "dimension": "status"})
    assert r.status_code == 400 and "תאריך" in r.json()["detail"]
    col = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד"})
    ok = _widget(client, admin_id, d, metrics=COUNT,
                 mapping={str(bid): {"__date__": col["id"]}},
                 chart={"type": "line", "dimension": "date"})
    assert ok.status_code == 200, ok.text


# ── DASH-18.1 / DASH-26.3 · הפירוט מלחיצה על רכיב ──────────────────────────

def test_clicking_a_bar_opens_exactly_the_records_behind_it(client, admin_id):
    """DASH-18.1 — "לחיצה על רכיב תרשים תפתח את הקטגוריה, הסדרה והמדד
    המתאימים, עם אותם מקורות, מסננים וגרסת הגדרות"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "פירוט מעמודה")
    a = _group(client, bid, admin_id, "אלפא")
    b = _group(client, bid, admin_id, "ביתא")
    for i in range(3):
        _item(client, bid, admin_id, f"א{i}", group_id=a)
    _item(client, bid, admin_id, "ב0", group_id=b)
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "group"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    cat = next(c for c in out["categories"] if c["label"] == "אלפא")
    r = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/records",
                    headers=AS(admin_id),
                    json={"category": cat["key"], "series": out["series"][0]["key"]}).json()
    assert r["records"] == 3
    assert {x["title"] for x in r["rows"]} == {"א0", "א1", "א2"}
    assert r["category"] == cat["key"]


def test_clicking_a_stack_segment_narrows_to_its_series_too(client, admin_id):
    """DASH-26.3 — "לחיצה על מקטע תזהה את הקטגוריה, הסדרה והמדד שלו"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "פירוט ממקטע")
    g = _group(client, bid, admin_id, "אחת")
    _item(client, bid, admin_id, "בוצע 1", group_id=g, status="done")
    _item(client, bid, admin_id, "בוצע 2", group_id=g, status="done")
    _item(client, bid, admin_id, "בטיפול", group_id=g, status="in_progress")
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "stacked", "dimension": "group",
                       "split": "status"}).json()["widget"]
    out = _chart(client, admin_id, d["id"], w["id"])
    done = next(s for s in out["series"] if s["label"].endswith("בוצע"))
    r = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/records",
                    headers=AS(admin_id),
                    json={"category": out["categories"][0]["key"],
                          "series": done["key"]}).json()
    assert r["records"] == 2
    assert {x["title"] for x in r["rows"]} == {"בוצע 1", "בוצע 2"}


def test_a_blocked_chart_says_nothing_about_its_categories(client, admin_id, guinea_id):
    """R01 reaches a chart exactly as it reaches a figure: a category list is
    "מידע שניתן להסיק ממנו כמויות"."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    closed = _board(client, admin_id, "סגור לתרשים")
    _item(client, closed, admin_id, "חסוי", status="done")
    d = _dash(client, admin_id, env, [closed], name="תרשים חסום")
    w = _widget(client, admin_id, d, metrics=COUNT,
                chart={"type": "vbar", "dimension": "status"}).json()["widget"]
    assert _chart(client, admin_id, d["id"], w["id"])["state"] == "ok"
    theirs = _chart(client, guinea_id, d["id"], w["id"])
    assert theirs["state"] == "blocked"
    assert theirs["categories"] == [] and theirs["series"] == []
    assert "records" not in theirs
