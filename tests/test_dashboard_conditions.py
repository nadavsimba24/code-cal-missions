"""ספירה עם תנאי — "מספר פגישות של משתמש מסוים", "פגישה אחרי תאריך".

The mechanism was always there: the widget filter is a `filter_ast` tree and
the server has run it since DASH-10. What was missing was a way to build one
without writing JSON, so a count was a count of everything.

This file is the two halves of that meeting. The first is the contract: the
operator table the browser offers has to be the one `filter_ast` accepts, or
the screen builds conditions the server refuses — the same arrangement
`test_formula_parity.py` has, for the same reason.

The second is the two questions that were actually asked, posted exactly as
the builder would post them, against a population whose answer is counted by
hand.
"""
import re
import pathlib

import filter_ast
from conftest import join_primary_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

AS = lambda uid: {"X-CityOS-User": str(uid)}


# ── the two tables must agree ───────────────────────────────────────────────

def _editor_table(name):
    i = SRC.index(f"  {name}:{{")
    depth, j = 0, SRC.index("{", i)
    for k in range(j, len(SRC)):
        if SRC[k] == "{":
            depth += 1
        elif SRC[k] == "}":
            depth -= 1
            if depth == 0:
                return SRC[i:k + 1]
    raise AssertionError(name + " not found")


def test_the_kinds_the_editor_offers_are_the_kinds_the_server_knows():
    """`filter_ast.KINDS` decides what a column may be asked about. A screen
    that offered a kind the server does not have would build a condition it
    refuses."""
    block = _editor_table("KIND")
    pairs = dict(re.findall(r"(\w+):'(\w+)'", block))
    assert pairs, "the editor's kind table could not be read"
    for col_type, kind in pairs.items():
        assert filter_ast.KINDS.get(col_type) == kind, \
            f"{col_type}: editor says {kind}, filter_ast says {filter_ast.KINDS.get(col_type)}"


def test_every_operator_the_editor_offers_is_one_the_server_accepts():
    """`filter_ast.OPS` is the authority on which operators belong to which
    kind — "אופרטורים לפי סוג" (R05)."""
    block = _editor_table("OPS")
    for kind, body in re.findall(r"(\w+):\[(.*?)\],\n", block, re.S):
        offered = set(re.findall(r"\['(\w+)'", body))
        allowed = set(filter_ast.OPS.get(kind, ()))
        assert offered <= allowed, \
            f"{kind}: the editor offers {sorted(offered - allowed)}, which filter_ast refuses"
        assert offered, f"{kind}: no operator offered"


def test_the_relative_periods_are_the_ones_the_server_resolves():
    """R05 — "בתאריך גם טווח ותקופות יחסיות", resolved against the
    organisation's day (see _dash_clock)."""
    block = SRC[SRC.index("  DATE_TOKENS:["):]
    block = block[:block.index("],\n") + 2]
    offered = set(re.findall(r"\['(\w+)'", block))
    assert offered, "no relative periods offered"
    assert offered <= set(filter_ast.DATE_TOKENS), \
        f"unknown periods: {sorted(offered - set(filter_ast.DATE_TOKENS))}"


# ── and the two questions that were asked ───────────────────────────────────

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


def _meeting(client, bid, admin_id, title, when, who=None, col=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id,
                                            "custom_fields": {col["id"]: when}})
    if who:
        client.post(f"/api/tasks/{tid}/assignees",
                    json={"actor_id": admin_id, "user_id": who})
    return tid


def _count_with(client, admin_id, bid, rules, mapping):
    """A counting widget carrying exactly what the builder would have sent."""
    d = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                    json={}).json()
    w = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": d["config_version"], "type": "numbers",
                          "title": "ספירה עם תנאי", "mapping": mapping,
                          "metrics": [{"key": "m", "calc": "count"}],
                          "filters": {"adv": {"type": "group", "operator": "and",
                                              "rules": rules}}})
    assert w.status_code == 200, w.text
    out = client.post(
        f"/api/dashboards/{d['id']}/widgets/{w.json()['widget']['id']}/compute",
        headers=AS(admin_id), json={}).json()
    assert out["state"] == "ok", out
    return out["metrics"][0]["result"]


def test_counting_the_meetings_of_one_person(client, admin_id, member_id):
    """"מספר פגישות של משתמש מסוים" — four meetings, two of them hers."""
    join_primary_env(client, member_id)
    bid = _board(client, admin_id, "פגישות · אדם")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    when = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד פגישה"})
    _meeting(client, bid, admin_id, "שלה 1", "2026-03-02", member_id, when)
    _meeting(client, bid, admin_id, "שלה 2", "2026-03-20", member_id, when)
    _meeting(client, bid, admin_id, "שלו", "2026-03-05", admin_id, when)
    _meeting(client, bid, admin_id, "ללא אחראי", "2026-03-06", None, when)
    got = _count_with(client, admin_id, bid,
                      [{"type": "rule", "field": "assignees",
                        "operator": "has", "value": str(member_id)}], {})
    assert got == 2


def test_counting_the_meetings_after_a_date(client, admin_id):
    """"פגישה אחרי תאריך מסוים" — the board column, mapped the way the
    builder maps it: the field key IS the column id."""
    bid = _board(client, admin_id, "פגישות · תאריך")
    when = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד פגישה"})
    for t, day in (("ינואר", "2026-01-10"), ("מרץ", "2026-03-10"),
                   ("אפריל", "2026-04-10")):
        _meeting(client, bid, admin_id, t, day, None, when)
    cid = when["id"]
    got = _count_with(client, admin_id, bid,
                      [{"type": "rule", "field": cid, "operator": "after",
                        "value": "2026-02-01"}],
                      {str(bid): {cid: cid}})
    assert got == 2


def test_two_conditions_must_both_hold(client, admin_id, member_id):
    """R05 — "בין תנאים AND". Her meetings, and only the ones after March."""
    join_primary_env(client, member_id)
    bid = _board(client, admin_id, "פגישות · שניים")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    when = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד פגישה"})
    _meeting(client, bid, admin_id, "שלה, מוקדם", "2026-01-05", member_id, when)
    _meeting(client, bid, admin_id, "שלה, מאוחר", "2026-04-05", member_id, when)
    _meeting(client, bid, admin_id, "שלו, מאוחר", "2026-04-06", admin_id, when)
    cid = when["id"]
    got = _count_with(client, admin_id, bid, [
        {"type": "rule", "field": "assignees", "operator": "has",
         "value": str(member_id)},
        {"type": "rule", "field": cid, "operator": "after", "value": "2026-02-01"},
    ], {str(bid): {cid: cid}})
    assert got == 1


def test_a_condition_on_a_status_counts_only_that_status(client, admin_id):
    bid = _board(client, admin_id, "פגישות · סטטוס")
    when = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד"})
    for t, st in (("א", "done"), ("ב", "done"), ("ג", "in_progress")):
        tid = _meeting(client, bid, admin_id, t, "2026-03-01", None, when)
        client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "status": st})
    got = _count_with(client, admin_id, bid,
                      [{"type": "rule", "field": "status", "operator": "eq",
                        "value": "done"}], {})
    assert got == 2


# ── כמות בכל ערך של עמודה ──────────────────────────────────────────────────

def _chart(client, admin_id, bid, dimension, mapping=None):
    d = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                    json={}).json()
    w = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": d["config_version"], "type": "chart",
                          "title": "חלוקה", "mapping": mapping or {},
                          "metrics": [{"key": "m", "calc": "count"}],
                          "chart": {"type": "vbar", "dimension": dimension}})
    assert w.status_code == 200, w.text
    out = client.post(
        f"/api/dashboards/{d['id']}/widgets/{w.json()['widget']['id']}/chart",
        headers=AS(admin_id), json={}).json()
    assert out["state"] == "ok", out
    return dict(zip([c["label"] for c in out["categories"]],
                    out["series"][0]["points"]))


def test_a_status_column_can_be_broken_down_by_its_own_values(client, admin_id):
    """"הצגת כמות בכל ערך מבין עמודה מסוימת, למשל חלוקה לפי סטטוסים."

    A board can have several status columns, and the built-in one is not
    necessarily the one somebody means. Grouping by a COLUMN gives the count
    per value of that column.
    """
    bid = _board(client, admin_id, "חלוקה · סטטוס עמודה")
    col = _add_col(client, bid, admin_id,
                   {"type": "status", "title": "שלב הטיפול",
                    "options": [{"label": "ממתין"}, {"label": "בבדיקה"},
                                {"label": "אושר"}]})
    for label, n in (("ממתין", 3), ("בבדיקה", 1), ("אושר", 2)):
        for i in range(n):
            tid = client.post("/api/tasks",
                              json={"board_id": bid, "title": f"{label} {i}",
                                    "user_id": admin_id}).json()["id"]
            client.patch(f"/api/tasks/{tid}",
                         json={"user_id": admin_id,
                               "custom_fields": {col["id"]: {"label": label}}})
    # one record with nothing in the column — "ללא ערך" (R06)
    client.post("/api/tasks", json={"board_id": bid, "title": "ריק",
                                    "user_id": admin_id})
    got = _chart(client, admin_id, bid, col["id"],
                 {str(bid): {col["id"]: col["id"]}})
    assert got["ממתין"] == 3
    assert got["בבדיקה"] == 1
    assert got["אושר"] == 2
    assert got["ללא ערך"] == 1
    assert sum(got.values()) == 7


def test_a_dropdown_puts_a_record_in_each_value_it_holds(client, admin_id):
    """A dropdown holds the options ticked in it, so one record belongs to
    each — the multi-person rule of R06, applied to a column."""
    bid = _board(client, admin_id, "חלוקה · רשימה נפתחת")
    col = _add_col(client, bid, admin_id,
                   {"type": "dropdown", "title": "תחומים",
                    "options": [{"label": "תכנון"}, {"label": "ביצוע"}]})
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "שניהם",
                                          "user_id": admin_id}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id,
                                            "custom_fields": {col["id"]: ["תכנון", "ביצוע"]}})
    got = _chart(client, admin_id, bid, col["id"], {str(bid): {col["id"]: col["id"]}})
    assert got["תכנון"] == 1 and got["ביצוע"] == 1


def test_a_text_column_is_refused_as_a_dimension(client, admin_id):
    """R06 names four kinds rather than "any column" precisely because a
    chart grouped by free text is one bar per record."""
    bid = _board(client, admin_id, "חלוקה · טקסט")
    col = _add_col(client, bid, admin_id, {"type": "text", "title": "הערה"})
    d = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                    json={}).json()
    r = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": d["config_version"], "type": "chart",
                          "title": "לא", "mapping": {str(bid): {col["id"]: col["id"]}},
                          "metrics": [{"key": "m", "calc": "count"}],
                          "chart": {"type": "vbar", "dimension": col["id"]}})
    assert r.status_code == 400
    assert "קיבוץ אפשרי" in r.json()["detail"]


def test_a_line_chart_accepts_a_date_column_as_its_dimension(client, admin_id):
    """DASH-27.1 asks for a date dimension, and a date COLUMN is one."""
    bid = _board(client, admin_id, "חלוקה · קו")
    col = _add_col(client, bid, admin_id, {"type": "date", "title": "מועד פגישה"})
    d = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                    json={}).json()
    ok = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                     json={"config_version": d["config_version"], "type": "chart",
                           "title": "קו", "mapping": {str(bid): {col["id"]: col["id"]}},
                           "metrics": [{"key": "m", "calc": "count"}],
                           "chart": {"type": "line", "dimension": col["id"],
                                     "period": "month"}})
    assert ok.status_code == 200, ok.text


def test_a_hidden_builtin_is_not_offered_as_a_condition(client, admin_id):
    """The server prunes a condition over a column the board has hidden, so
    offering it would build a rule that is silently dropped."""
    js = SRC[SRC.index("filterFields(){"):]
    js = js[:js.index("\n  srcIds()")]
    assert "hidden" in js, "the editor ignores the board's hidden columns"
    assert "'priority'" in js, "עדיפות is a built-in the server offers"


def test_a_distribution_by_a_person_column_counts_each_person(client, admin_id,
                                                              member_id):
    """The report: a column called "מנהלת תפעול" — a people column — and no
    visible way to break down by it. It works; it lives under the chart
    kind, which the editor now says out loud."""
    join_primary_env(client, member_id)
    bid = _board(client, admin_id, "התפלגות · אנשים")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    col = _add_col(client, bid, admin_id, {"type": "people", "title": "מנהלת תפעול"})
    for title, who in (("א", [member_id]), ("ב", [member_id]),
                       ("ג", [admin_id]), ("ד", [])):
        tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                              "user_id": admin_id}).json()["id"]
        client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id,
                                                "custom_fields": {col["id"]: who}})
    got = _chart(client, admin_id, bid, col["id"], {str(bid): {col["id"]: col["id"]}})
    assert sum(got.values()) == 4
    assert got["ללא ערך"] == 1
    assert sorted(v for k, v in got.items() if k != "ללא ערך") == [1, 2]


def test_a_chart_without_a_distribution_cannot_be_saved(client, admin_id):
    """A chart IS its distribution. Saved without one it could only ever say
    "נדרש תיקון" to somebody who did not configure it — DASH-11.2."""
    bid = _board(client, admin_id, "התפלגות · חסרה")
    d = client.post(f"/api/boards/{bid}/dashboards", headers=AS(admin_id),
                    json={}).json()
    r = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                    json={"config_version": d["config_version"], "type": "chart",
                          "title": "ללא התפלגות",
                          "metrics": [{"key": "m", "calc": "count"}],
                          "chart": {"type": "vbar"}})
    assert r.status_code == 400
    assert "התפלגות" in r.json()["detail"]
