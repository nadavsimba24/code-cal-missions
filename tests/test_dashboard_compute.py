"""The measure itself: counting, summing, averaging and filtering.

The spine of this file is the worked example the spec puts in R04, because
it is the one place the document commits to numbers:

    נתוני בדיקה 10, 0, ריק, 20, 30:
    ספירה 5, סכום 60, ממוצע 15 בהתעלמות מריקים וממוצע 12 בריק כאפס.
    מסנן אינו ריק מפיק ספירה 4.

Five records and six answers, and every one of them is a different way to
get it wrong: counting the blank as absent, treating the zero as empty,
averaging over the wrong denominator, letting the empty policy move the sum,
or letting a filter leak into the count. The example is run here against a
number column, a formula column and a multi-valued mirror, because R03 names
all three as numeric sources and a reduction that only works for the first
is not the one the dashboard needs.

The rest pins the things R03 and R04 say must NOT happen: an error is not a
blank, a blank is not a zero, a zero is not an absence, and no total is ever
an average of averages.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from conftest import join_primary_env

AS = lambda uid: {"X-CityOS-User": str(uid)}

# The worked example of R04, in the order the spec writes it.
R04 = [10, 0, None, 20, 30]


def _board(client, admin_id, name):
    """A board with nothing on it.

    Creating one seeds three example items ("פריט 1/2/3"). They are fine on a
    real board and ruinous in a test about counting, so they go — every
    number asserted below is then a number this file put there."""
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


def _dash(client, admin_id, env_id, sources, name="חישוב"):
    r = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env_id, "name": name,
                          "sources": [{"board_id": b, "groups": None} for b in sources]})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title, cf=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id}).json()["id"]
    if cf:
        client.patch(f"/api/tasks/{tid}",
                     json={"user_id": admin_id, "custom_fields": cf})
    return tid


def _widget(client, admin_id, dash, **kw):
    r = client.post(f"/api/dashboards/{dash['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": dash["config_version"],
                          "type": "numbers", "title": "מדד", **kw})
    assert r.status_code == 200, r.text
    return r.json()["widget"]


def _compute(client, uid, dash_id, widget_id, **body):
    r = client.post(f"/api/dashboards/{dash_id}/widgets/{widget_id}/compute",
                    headers=AS(uid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _one(res):
    assert len(res["metrics"]) == 1, res
    return res["metrics"][0]


def _number_board(client, admin_id, name, values=R04):
    """A board whose items carry the R04 values in a number column."""
    bid = _board(client, admin_id, name)
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "סכום"})
    for i, v in enumerate(values):
        _item(client, bid, admin_id, f"רשומה {i}",
              cf=({} if v is None else {col["id"]: v}))
    return bid, col


def _metric(calc, field="amount", **kw):
    return dict({"key": "m", "field": field, "calc": calc}, **kw)


# ── R04, against a number column ────────────────────────────────────────────

def test_the_worked_example_counts_five(client, admin_id):
    """"ספירה 5" — a record with a blank cell is still a record. "ספירת
    רשומות אינה מושפעת מריק בעמודה אלא אם קיים מסנן שמחריג אותו"."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "R04 ספירה")
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("count")])
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["state"] == "ok" and m["result"] == 5
    assert m["records"] == 5


def test_the_worked_example_sums_sixty(client, admin_id):
    """"סכום 60" — and the same 60 under either empty policy, because adding
    zeros does not move a sum. The policy changes the AVERAGE, not this."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "R04 סכום")
    d = _dash(client, admin_id, env, [bid])
    # four of the five records carried a number — the stored 0 is one of
    # them — and under "ריק כאפס" the blank joins them as a fifth. The SUM is
    # 60 either way, which is the point: the policy moves the denominator of
    # an average, never the total of a sum.
    for policy, participating in (("ignore", 4), ("zero", 5)):
        w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                    metrics=[_metric("sum", empty_policy=policy)])
        m = _one(_compute(client, admin_id, d["id"], w["id"]))
        assert m["state"] == "ok", m
        assert m["result"] == 60, f"{policy}: {m}"
        assert m["values"] == participating and m["records"] == 5
        d = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()


def test_the_worked_example_averages_fifteen_ignoring_blanks(client, admin_id):
    """"ממוצע 15 בהתעלמות מריקים" — 60 over the four records that had a
    value. The zero is one of them: "אפס תקין תמיד משתתף"."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "R04 ממוצע 15")
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("avg", empty_policy="ignore")])
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["state"] == "ok" and m["result"] == 15
    assert m["values"] == 4


def test_the_worked_example_averages_twelve_with_blanks_as_zero(client, admin_id):
    """"ממוצע 12 בריק כאפס" — 60 over five, because "רשומה ריקה קיימת
    משתתפת במכנה כאפס"."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "R04 ממוצע 12")
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("avg", empty_policy="zero")])
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["state"] == "ok" and m["result"] == 12
    assert m["values"] == 5


def test_the_worked_example_counts_four_when_blanks_are_filtered_out(client, admin_id):
    """"מסנן אינו ריק מפיק ספירה 4" — the only thing that removes a record
    from a count is a condition that says to."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "R04 מסנן")
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d,
                mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("count")],
                filters={"adv": {"type": "group", "operator": "and", "rules": [
                    {"type": "rule", "field": "amount", "operator": "filled"}]}})
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["state"] == "ok" and m["result"] == 4


# ── the same example, through the other two numeric sources ─────────────────

def test_a_formula_over_a_blank_cell_is_zero_because_the_browser_says_so(
        client, admin_id):
    """R03 names נוסחה as a numeric source, and the formula here doubles the
    value — so the four stored numbers contribute 120.

    The fifth record is the interesting one. Its base cell is blank, and
    `{בסיס}*2` over a blank is **0, not blank**: a missing reference is zero
    in arithmetic, which is what the browser's engine does (see the
    `("{a}+1", {"a": None})` case in test_formula_parity.py). So the formula
    column genuinely holds a value for that record, and the measure counts
    five participating values rather than four.

    This is worth a test of its own because the obvious expectation is the
    other one. If the dashboard decided a formula over a blank was blank, it
    would disagree with the cell the reader can see in the column — and the
    whole reason there is a second engine is that the two must agree."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "R04 נוסחה")
    base = _add_col(client, bid, admin_id, {"type": "number", "title": "בסיס"})
    calc = _add_col(client, bid, admin_id,
                    {"type": "formula", "title": "כפול", "formula": "{בסיס}*2"})
    for i, v in enumerate(R04):
        _item(client, bid, admin_id, f"נוסחה {i}",
              cf=({} if v is None else {base["id"]: v}))
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": calc["id"]}},
                metrics=[_metric("sum")])
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["state"] == "ok" and m["result"] == 120
    assert m["values"] == 5 and m["records"] == 5


def test_a_multi_valued_mirror_is_reduced_per_item_before_the_widget_sums(
        client, admin_id):
    """R03 — "במראה מרובת ערכים מגדירים סכום או ממוצע לכל פריט, ואז מבצעים
    את חישוב הווידג׳ט בין הפריטים. בממוצע החיצוני כל פריט בעל פלט תקין מקבל
    משקל אחד."

    One item linked to three records of 10, 20 and 30. Summed inside, the
    item is worth 60; averaged inside, it is worth 20. An engine that
    flattened the three into the outer average instead would answer 20 in
    both cases and be wrong in one of them.
    """
    env = _env(client, admin_id)
    near = _board(client, admin_id, "מראה קרוב")
    far = _board(client, admin_id, "מראה רחוק")
    far_col = _add_col(client, far, admin_id, {"type": "number", "title": "ערך"})
    linked = [_item(client, far, admin_id, f"רחוק {v}", cf={far_col["id"]: v})
              for v in (10, 20, 30)]
    conn = _add_col(client, near, admin_id,
                    {"type": "connect", "title": "קישור",
                     "connect": {"board_ids": [far], "multiple": True, "two_way": False}})
    mirror = _add_col(client, near, admin_id,
                      {"type": "mirror", "title": "מראה",
                       "mirror_of": {"connect": conn["id"], "field": far_col["id"]}})
    one = _item(client, near, admin_id, "מקושר לשלושה", cf={conn["id"]: linked})
    _item(client, near, admin_id, "ללא קישור")
    d = _dash(client, admin_id, env, [near])
    got = {}
    for inner in ("sum", "avg"):
        w = _widget(client, admin_id, d,
                    mapping={str(near): {"amount": mirror["id"]}},
                    metrics=[_metric("avg", mirror_agg=inner)])
        got[inner] = _one(_compute(client, admin_id, d["id"], w["id"]))
        d = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    assert got["sum"]["result"] == 60     # one item, worth 10+20+30
    assert got["avg"]["result"] == 20     # the same item, worth (10+20+30)/3
    # and the unlinked item is a blank, not a zero — one value either way
    assert got["sum"]["values"] == 1 and got["sum"]["records"] == 2


# ── union across boards, and what must never happen ─────────────────────────

def test_several_boards_are_one_union_and_not_an_average_of_averages(
        client, admin_id):
    """R03 — "כמה לוחות מחושבים מאיחוד הערכים, ללא ממוצע של ממוצעים".

    Three records of 10 on one board and one record of 100 on another. The
    union averages (10+10+10+100)/4 = 32.5. An average of the two boards'
    averages would be (10+100)/2 = 55 — a number that weights a board of
    three the same as a board of one.
    """
    env = _env(client, admin_id)
    a, ca = _number_board(client, admin_id, "איחוד א", [10, 10, 10])
    b, cb = _number_board(client, admin_id, "איחוד ב", [100])
    d = _dash(client, admin_id, env, [a, b], name="איחוד")
    w = _widget(client, admin_id, d,
                mapping={str(a): {"amount": ca["id"]}, str(b): {"amount": cb["id"]}},
                metrics=[_metric("avg")])
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["result"] == 32.5
    assert m["values"] == 4


def test_no_intermediate_rounding(client, admin_id):
    """R03 — "ללא עיגול ביניים". A third, three times, is one — not 0.99."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "ללא עיגול")
    base = _add_col(client, bid, admin_id, {"type": "number", "title": "בסיס"})
    third = _add_col(client, bid, admin_id,
                     {"type": "formula", "title": "שליש", "formula": "{בסיס}/3"})
    for i in range(3):
        _item(client, bid, admin_id, f"שליש {i}", cf={base["id"]: 1})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": third["id"]}},
                metrics=[_metric("sum")])
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert abs(m["result"] - 1.0) < 1e-9


# ── the zero states of R04 ──────────────────────────────────────────────────

def test_an_empty_board_counts_zero_but_averages_no_data(client, admin_id):
    """"אין רשומות: ספירה 0" and "ממוצע ללא ערכים: אין נתונים". A count of
    nothing is a number; an average of nothing is not."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "ריק לגמרי")
    col = _add_col(client, bid, admin_id, {"type": "number", "title": "סכום"})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("count"), _metric("avg", field="amount")])
    res = _compute(client, admin_id, d["id"], w["id"])
    by = {m["calc"]: m for m in res["metrics"]}
    assert by["count"]["state"] == "ok" and by["count"]["result"] == 0
    assert by["avg"]["state"] == "no_data" and by["avg"]["result"] is None


def test_a_sum_with_no_numeric_values_is_a_true_zero_and_says_why(client, admin_id):
    """"סכום ללא ערכים מספריים: 0 עם אין ערכים מספריים לחישוב"."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "סכום ללא ערכים", [None, None])
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("sum")])
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["state"] == "ok" and m["result"] == 0
    assert m["values"] == 0 and m["note"] == "אין ערכים מספריים לחישוב"


def test_a_broken_formula_is_not_shown_as_zero(client, admin_id):
    """DASH-09.1 — "אין להתייחס אליו כאל ריק בלי להתריע", and R04 — a
    calculation error is not a 0. The measure reports what failed instead of
    producing a total that silently omits it."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "נוסחה שבורה")
    base = _add_col(client, bid, admin_id, {"type": "number", "title": "בסיס"})
    bad = _add_col(client, bid, admin_id,
                   {"type": "formula", "title": "שבורה", "formula": "{אין עמודה כזו}+1"})
    _item(client, bid, admin_id, "אחת", cf={base["id"]: 5})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": bad["id"]}},
                metrics=[_metric("sum")])
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["state"] == "needs_fix"
    assert m["result"] is None            # emphatically not 0
    assert m["failed"] == 1 and m["reason"]


def test_a_blocked_source_computes_nothing_at_all(client, admin_id, guinea_id):
    """R01 — a blocked widget carries no result and no record count either;
    a population size is "מידע שניתן להסיק ממנו כמויות"."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    closed, col = _number_board(client, admin_id, "סגור לחישוב")
    d = _dash(client, admin_id, env, [closed], name="חסום")
    w = _widget(client, admin_id, d, mapping={str(closed): {"amount": col["id"]}},
                metrics=[_metric("sum")])
    mine = _compute(client, admin_id, d["id"], w["id"])
    assert _one(mine)["result"] == 60
    theirs = _compute(client, guinea_id, d["id"], w["id"])
    assert theirs["state"] == "blocked"
    assert theirs["metrics"] == []
    assert "records" not in theirs


# ── DASH-10 · the shared filter ─────────────────────────────────────────────

def test_a_condition_with_no_mapping_stops_the_measure(client, admin_id):
    """DASH-10.3 and R05 — "אין סינון חלקי בשקט". Inside an OR group a
    dropped rule and a false one are opposites, and the forgiving reading
    quietly returns the whole board.

    The widget is saved VALID and then broken from the outside, which is the
    way this state really arises: DASH-16.1 refuses to store a filter over an
    unmapped field in the first place, so the only route to one is a
    dashboard that gained a board afterwards. The widget names no sources of
    its own, so it inherits the new one — and now its condition has nothing
    to run against there."""
    env = _env(client, admin_id)
    a, ca = _number_board(client, admin_id, "מסונן א", [1, 2])
    b, _cb = _number_board(client, admin_id, "מסונן ב", [3])
    d = _dash(client, admin_id, env, [a], name="מסנן ללא מיפוי")
    w = _widget(client, admin_id, d,
                mapping={str(a): {"amount": ca["id"]}},
                metrics=[_metric("count")],
                filters={"adv": {"type": "group", "operator": "and", "rules": [
                    {"type": "rule", "field": "amount", "operator": "filled"}]}})
    assert _one(_compute(client, admin_id, d["id"], w["id"]))["result"] == 2
    fresh = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                 json={"config_version": fresh["config_version"],
                       "sources": [{"board_id": a, "groups": None},
                                   {"board_id": b, "groups": None}]})
    res = _compute(client, admin_id, d["id"], w["id"])
    assert res["state"] == "needs_fix"
    assert res["field"] == "amount"
    assert res["metrics"] == []


def test_the_dashboard_filter_and_the_widget_filter_intersect(client, admin_id):
    """DASH-16.2 — "המסנן המקומי יחול יחד עם מסנן הדשבורד, בחיתוך ביניהם"."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "חיתוך", [1, 5, 10, 50])
    d = _dash(client, admin_id, env, [bid], name="חיתוך")
    gt = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "gt", "value": 2}]}}
    client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                 json={"config_version": d["config_version"], "filters": gt})
    d = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    lt = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "lt", "value": 20}]}}
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("count")], filters=lt)
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    assert m["result"] == 2          # 5 and 10 — not 1, and not 50


# ── R10 · the drill-down is the same population ─────────────────────────────

def _records(client, uid, dash_id, widget_id, **body):
    r = client.post(f"/api/dashboards/{dash_id}/widgets/{widget_id}/records",
                    headers=AS(uid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_drilldown_pages_the_list_but_not_the_measure(client, admin_id):
    """R10 — "הרשימה מעומדת אך המדד על כל הרשומות". The totals beside a page
    of two are the totals of all five, or the number the reader clicked on
    would change when they turned the page."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "פירוט מעומד")
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("sum")])
    page = _records(client, admin_id, d["id"], w["id"], limit=2)
    assert len(page["rows"]) == 2
    assert page["has_more"] is True
    assert page["records"] == 5 and page["values"] == 4
    assert page["result"] == 60
    rest = _records(client, admin_id, d["id"], w["id"], limit=2, offset=4)
    assert len(rest["rows"]) == 1 and rest["has_more"] is False
    assert rest["records"] == 5 and rest["result"] == 60


def test_the_drilldown_sees_exactly_what_the_measure_counted(client, admin_id):
    """The same population, not a second derivation of it."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "אותה אוכלוסייה")
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d,
                mapping={str(bid): {"amount": col["id"]}},
                metrics=[_metric("count")],
                filters={"adv": {"type": "group", "operator": "and", "rules": [
                    {"type": "rule", "field": "amount", "operator": "filled"}]}})
    m = _one(_compute(client, admin_id, d["id"], w["id"]))
    rows = _records(client, admin_id, d["id"], w["id"], limit=200)
    assert m["result"] == 4
    assert len(rows["rows"]) == 4 and rows["records"] == 4


def test_the_drilldown_shows_blanks_and_says_how_they_were_treated(client, admin_id):
    """DASH-14.3 — "בפירוט יופיעו גם רשומות ריקות ששייכות לאוכלוסייה, עם
    הסבר אם וכיצד הן משתתפות בחישוב"."""
    env = _env(client, admin_id)
    bid, col = _number_board(client, admin_id, "ריקים בפירוט")
    d = _dash(client, admin_id, env, [bid])
    for policy, expect in (("ignore", "לא משתתפת בחישוב"), ("zero", "נספרת כאפס")):
        w = _widget(client, admin_id, d, mapping={str(bid): {"amount": col["id"]}},
                    metrics=[_metric("sum", empty_policy=policy)])
        rows = _records(client, admin_id, d["id"], w["id"], limit=200)["rows"]
        blank = [r for r in rows if r.get("value_state") == "empty"]
        assert len(blank) == 1
        assert blank[0]["empty_handling"] == expect
        d = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()


def test_the_drilldown_names_the_board_and_the_kind_of_record(client, admin_id):
    """DASH-18.2 — "ברשימה יוצגו שם הרשומה, לוח המקור וסוג הרשומה"."""
    env = _env(client, admin_id)
    bid = _board(client, admin_id, "שם לוח בפירוט")
    parent = _item(client, bid, admin_id, "אב")
    client.post("/api/tasks", json={"board_id": bid, "title": "ילד",
                                    "parent_id": parent, "user_id": admin_id})
    d = _dash(client, admin_id, env, [bid])
    w = _widget(client, admin_id, d, record_scope="both",
                metrics=[_metric("count", field=None)])
    rows = _records(client, admin_id, d["id"], w["id"], limit=200)["rows"]
    kinds = {r["title"]: r["kind"] for r in rows}
    assert kinds["אב"] == "item" and kinds["ילד"] == "subitem"
    assert all(r["board_name"] == "שם לוח בפירוט" for r in rows)


def test_a_blocked_widget_gives_no_page_and_no_count(client, admin_id, guinea_id):
    """DASH-04.1 — "לפני חישוב **או פתיחת פירוט**". An empty page is itself a
    statement that the population is empty."""
    env = _env(client, admin_id)
    join_primary_env(client, guinea_id)
    closed, col = _number_board(client, admin_id, "סגור לפירוט")
    d = _dash(client, admin_id, env, [closed], name="פירוט חסום")
    w = _widget(client, admin_id, d, mapping={str(closed): {"amount": col["id"]}},
                metrics=[_metric("sum")])
    out = _records(client, guinea_id, d["id"], w["id"])
    assert out["state"] == "blocked"
    assert out["rows"] == [] and out["records"] is None
