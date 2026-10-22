"""הסינון המתקדם כ-AST שהשרת מריץ — אזורי זמן, ערכים ריקים, ומבנה העץ.

The browser answers instantly because a filter has to; this answers for the
whole board, and it is the authority. Which means the two have to agree, and
the three technical requirements are each a way they could silently disagree:

  * **Timezones.** "היום" is not a fact about the server. A board read from
    Israel at 01:30 is on a different day from the UTC clock, and an item
    created at 22:30 UTC is already tomorrow's to the person reading it. The
    client sends its own date and its offset; the server resolves every token
    against those and never against its own clock.
  * **Nulls.** ריק has to catch a NULL and an empty string alike — the same
    nothing to whoever is looking at the cell. It must NOT catch 0 or False:
    a budget of zero is a budget, and a truthiness test would hide every zero
    on the board from anyone filtering for a value.
  * **The payload.** A recursive tree: groups carrying an operator and rules,
    rules carrying a field, an operator and a value. Arriving from outside, so
    it is parsed before it is run — unknown operators refused by name, depth
    and size capped.
"""
import datetime as dt
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import filter_ast as F  # noqa: E402

SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

FIELDS = {"title": "text", "status": "status", "priority": "status",
          "assignees": "people", "due": "date",
          "c_num": "number", "c_txt": "text", "c_date": "date", "c_ppl": "people"}
TODAY = "2026-10-18"          # a Sunday, so the week boundaries are legible


def item(**kw):
    return {"id": kw.get("id", 1), "title": kw.get("title", "פריט"),
            "status": kw.get("status"), "priority": kw.get("priority"),
            "due_date": kw.get("due"),
            "assignees": [{"id": i} for i in kw.get("people", [])],
            "custom_fields": kw.get("cf", {})}


def m(it, field, op, v=None, v2=None, today=TODAY, off=0, me=None):
    rule = F.parse({"field": field, "operator": op, "value": v, "value2": v2})
    return F.match(it, rule, FIELDS, today, off, me)


# ── 1. אזורי זמן ───────────────────────────────────────────────────────────
def test_today_is_the_clients_day_not_the_servers():
    """The server's own date is never consulted when the client sent one."""
    assert F.span("today", "2026-01-01") == ("2026-01-01", "2026-01-01")
    assert F.span("today", "2030-07-04") == ("2030-07-04", "2030-07-04")


def test_the_week_starts_on_sunday():
    # 2026-10-18 is a Sunday; 2026-10-21 a Wednesday inside the same week
    assert F.span("this_week", "2026-10-18") == ("2026-10-18", "2026-10-24")
    assert F.span("this_week", "2026-10-21") == ("2026-10-18", "2026-10-24")
    assert F.span("last_week", "2026-10-21") == ("2026-10-11", "2026-10-17")
    assert F.span("next_week", "2026-10-21") == ("2026-10-25", "2026-10-31")


def test_the_months_know_their_own_length():
    assert F.span("this_month", "2026-02-10") == ("2026-02-01", "2026-02-28")
    assert F.span("next_month", "2026-12-31") == ("2027-01-01", "2027-01-31")
    assert F.span("last_month", "2027-01-05") == ("2026-12-01", "2026-12-31")


def test_an_instant_becomes_the_day_the_viewer_is_having():
    """The requirement, in one line: 22:30 UTC is already tomorrow in Israel,
    and an item created then has to answer to "נוצר היום" for the person who
    created it — not for a server reading a UTC clock."""
    late = "2026-10-18T22:30:00Z"
    assert F.day_in_zone(late, 180) == "2026-10-19"      # Israel, summer
    assert F.day_in_zone(late, 120) == "2026-10-19"      # Israel, winter
    assert F.day_in_zone(late, 0) == "2026-10-18"        # UTC
    assert F.day_in_zone(late, -480) == "2026-10-18"     # the other way


def test_a_bare_date_is_never_moved_by_a_timezone():
    """A date column names a day, not a moment. Put through a timezone it
    would shift back one day for everybody west of Greenwich — which is how a
    due date lands on the wrong day for half the world."""
    for off in (-720, -300, 0, 180, 840):
        assert F.day_in_zone("2026-10-18", off) == "2026-10-18"


def test_a_due_date_near_midnight_filters_by_the_viewers_day():
    late = item(due="2026-10-18T22:30:00Z")
    assert m(late, "due", "on", "today", today="2026-10-19", off=180), \
        "an item due late on the 18th UTC is not found on the 19th in Israel"
    assert not m(late, "due", "on", "today", today="2026-10-19", off=0)


# ── 2. ערכים ריקים ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,empty", [
    (None, True), ("", True), ("   ", True), ("\t\n", True), ([], True), ({}, True),
    (0, False), (0.0, False), (False, False), ("0", False), ("x", False), ([1], False),
])
def test_what_counts_as_empty(v, empty):
    assert F.is_empty(v) is empty


def test_a_null_and_an_empty_string_are_the_same_nothing():
    for v in (None, "", "   "):
        assert m(item(cf={"c_txt": v}), "c_txt", "empty"), repr(v)
        assert not m(item(cf={"c_txt": v}), "c_txt", "filled"), repr(v)
    assert m(item(cf={}), "c_txt", "empty"), "a key that was never written"


def test_zero_is_a_value_and_not_an_empty_cell():
    """The one a truthiness test gets wrong, and it hides every zero on the
    board from anybody filtering for a number."""
    z = item(cf={"c_num": 0})
    assert not m(z, "c_num", "empty")
    assert m(z, "c_num", "filled")
    assert m(z, "c_num", "lt", 1)
    assert m(z, "c_num", "eq", 0)


def test_an_empty_cell_is_outside_every_comparison():
    blank = item(cf={})
    for op, v, v2 in (("gt", 1, None), ("lt", 1, None), ("between", 0, 99)):
        assert not m(blank, "c_num", op, v, v2), op
    for op in ("on", "before", "after"):
        assert not m(blank, "c_date", op, "today"), op


# ── 3. מבנה הנתונים ────────────────────────────────────────────────────────
def test_the_tree_is_recursive_and_each_group_carries_its_own_operator():
    tree = F.parse({"type": "group", "operator": "or", "rules": [
        {"type": "group", "operator": "and", "rules": [
            {"type": "rule", "field": "status", "operator": "eq", "value": "done"},
            {"type": "rule", "field": "due", "operator": "on", "value": "this_week"}]},
        {"type": "group", "operator": "and", "rules": [
            {"type": "rule", "field": "priority", "operator": "eq", "value": "high"}]},
    ]})
    assert tree["operator"] == "or"
    assert [g["operator"] for g in tree["rules"]] == ["and", "and"]
    assert F.count(tree) == 3


def test_the_specs_example_answers_the_way_the_spec_reads():
    """(Group A: Status=Done AND Date=This Week) OR (Group B: Priority=High)"""
    tree = F.parse({"operator": "or", "rules": [
        {"operator": "and", "rules": [
            {"field": "status", "operator": "eq", "value": "done"},
            {"field": "due", "operator": "on", "value": "this_week"}]},
        {"operator": "and", "rules": [
            {"field": "priority", "operator": "eq", "value": "high"}]}]})
    run = lambda it: F.match(it, tree, FIELDS, TODAY)
    assert run(item(status="done", due="2026-10-20", priority="low"))      # A
    assert not run(item(status="done", due="2026-10-01", priority="low"))  # A, wrong week
    assert run(item(status="todo", due="2026-10-01", priority="high"))     # B
    assert not run(item(status="todo", due="2026-10-01", priority="low"))  # neither


def test_the_short_spelling_the_browser_holds_is_accepted_too():
    """The in-memory shape uses `op`/`v`; the wire shape uses
    `operator`/`value`. One parser reads both, so a payload built by hand in a
    script is not a second format to support."""
    a = F.parse({"op": "and", "rules": [{"field": "title", "op": "has", "v": "גשר"}]})
    b = F.parse({"operator": "and", "rules": [
        {"field": "title", "operator": "has", "value": "גשר"}]})
    assert a == b


def test_a_tree_that_arrived_from_outside_is_refused_by_name():
    with pytest.raises(F.BadFilter, match="אופרטור"):
        F.parse({"operator": "and", "rules": [{"field": "title", "operator": "drop"}]})
    with pytest.raises(F.BadFilter, match="קשר לוגי"):
        F.parse({"operator": "xor", "rules": []})
    with pytest.raises(F.BadFilter, match="בלי עמודה"):
        F.parse({"operator": "and", "rules": [{"operator": "eq", "value": 1}]})
    with pytest.raises(F.BadFilter, match="עמוק"):
        deep = {"operator": "and", "rules": []}
        for _ in range(F.MAX_DEPTH + 3):
            deep = {"operator": "and", "rules": [deep]}
        F.parse(deep)
    with pytest.raises(F.BadFilter, match="יותר מדי"):
        F.parse({"operator": "and", "rules": [
            {"field": "title", "operator": "eq", "value": i}
            for i in range(F.MAX_RULES + 1)]})


def test_an_unfinished_tree_never_empties_the_board():
    for tree in (None, {"operator": "and", "rules": []},
                 {"operator": "and", "rules": [{"operator": "or", "rules": []}]}):
        assert F.match(item(), F.parse(tree), FIELDS, TODAY)
    assert m(item(), "c_gone", "eq", "x"), "a column deleted since hides the board"


# ── the two engines have to agree ──────────────────────────────────────────
def test_the_two_copies_of_the_operator_table_match():
    """One table in Python, one in JavaScript, and a filter that means
    different things on the two sides of the wire is the worst kind of bug
    here — it hides rows on the server that the browser showed, and nothing
    on screen says which answer you are looking at."""
    js = {}
    i = SRC.index("const ADV_OPS = {")
    depth, j = 0, SRC.index("{", i)
    for k in range(j, len(SRC)):
        if SRC[k] == "{":
            depth += 1
        elif SRC[k] == "}":
            depth -= 1
            if not depth:
                table = SRC[j:k + 1]
                break
    for kind in F.OPS:
        at = table.index(kind + ":")
        d2, start = 0, table.index("[", at)
        for k in range(start, len(table)):
            if table[k] == "[":
                d2 += 1
            elif table[k] == "]":
                d2 -= 1
                if not d2:
                    js[kind] = tuple(re.findall(r"\['(\w+)'", table[start:k + 1]))
                    break
    assert js == {k: tuple(v) for k, v in F.OPS.items()}


def test_the_two_copies_of_the_kind_table_match():
    i = SRC.index("const ADV_KINDS = {")
    j = SRC.index("};", i)
    js = dict(re.findall(r"(\w+):'(\w+)'", SRC[i:j]))
    assert js == F.KINDS


def test_the_dynamic_dates_are_the_same_list_on_both_sides():
    i = SRC.index("const ADV_DATES = [")
    j = SRC.index("];", i)
    js = tuple(re.findall(r"\['(\w+)'", SRC[i:j]))
    assert js == F.DATE_TOKENS


# ── and the endpoint that runs it ──────────────────────────────────────────
H = {"X-CityOS-User": "1", "host": "localhost"}


def _board(client, admin_id, name="לוח סינון"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _task(client, bid, admin_id, title, **kw):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id, **kw}).json()["id"]


def test_the_endpoint_answers_with_the_ids_that_match(client, admin_id):
    bid = _board(client, admin_id)
    a = _task(client, bid, admin_id, "גשר הרצל")
    b = _task(client, bid, admin_id, "מדרכה ביאליק")
    r = client.post(f"/api/boards/{bid}/items/query", json={
        "user_id": admin_id, "today": TODAY, "tz_offset": 180,
        "filter": {"type": "group", "operator": "and", "rules": [
            {"type": "rule", "field": "title", "operator": "has", "value": "הרצל"}]}})
    assert r.status_code == 200, r.text
    d = r.json()
    # a new board comes with sample items of its own, so the assertion is
    # about the two this test made and not about an absolute count
    assert a in d["item_ids"] and b not in d["item_ids"]
    assert d["matched"] == 1 and d["total"] >= 2 and d["conditions"] == 1
    assert d["client_clock"] is True and d["today"] == TODAY and d["tz_offset"] == 180


def test_a_tree_the_server_refuses_is_refused_out_loud(client, admin_id):
    """Not silently ignored. A filter the server drops while the browser keeps
    showing its results is the two disagreeing with nothing on screen to say
    so."""
    bid = _board(client, admin_id)
    r = client.post(f"/api/boards/{bid}/items/query", json={
        "user_id": admin_id,
        "filter": {"operator": "and", "rules": [
            {"field": "title", "operator": "DROP TABLE"}]}})
    assert r.status_code == 400
    assert "אופרטור" in r.json()["detail"]


def test_without_a_client_date_the_server_says_whose_clock_answered(client, admin_id):
    """It still answers — a script has no timezone — but it says that the day
    it used was its own, because "היום" meaning two different days is exactly
    the bug this requirement is about."""
    bid = _board(client, admin_id)
    r = client.post(f"/api/boards/{bid}/items/query", json={
        "user_id": admin_id,
        "filter": {"operator": "and", "rules": [
            {"field": "due", "operator": "on", "value": "today"}]}})
    assert r.status_code == 200, r.text
    assert r.json()["client_clock"] is False
    assert r.json()["today"] == dt.datetime.now(dt.timezone.utc).date().isoformat()


def test_a_filter_is_not_a_way_into_a_board_you_cannot_open(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח סגור")
    _task(client, bid, admin_id, "סודי")
    r = client.post(f"/api/boards/{bid}/items/query",
                    json={"user_id": guinea_id,
                          "filter": {"operator": "and", "rules": []}},
                    headers={"X-CityOS-User": str(guinea_id)})
    assert r.status_code == 403, r.text


def test_an_empty_filter_returns_the_whole_board(client, admin_id):
    bid = _board(client, admin_id)
    a = _task(client, bid, admin_id, "א")
    b = _task(client, bid, admin_id, "ב")
    r = client.post(f"/api/boards/{bid}/items/query",
                    json={"user_id": admin_id, "filter": {"operator": "and", "rules": []}})
    d = r.json()
    assert d["matched"] == d["total"], "an empty filter hid something"
    assert a in d["item_ids"] and b in d["item_ids"]


def test_the_client_sends_the_tree_the_server_parses():
    """advToAst writes the wire shape out in full — type, operator, rules —
    and advQuery sends the clock beside it. Checked in the page's source
    because the two halves live in different files and nothing else says they
    are the same format."""
    i = SRC.index("function advToAst(node)")
    j = SRC.index("\n}", i)
    body = SRC[i:j]
    for part in ("type:'group'", "operator:", "rules:", "type:'rule'", "field:", "value:"):
        assert part in body, part
    i = SRC.index("function advQuery(node)")
    j = SRC.index("\n}", i)
    q = SRC[i:j]
    assert "today:advIso(now)" in q, "the client does not send its own date"
    assert "tz_offset:-now.getTimezoneOffset()" in q, \
        "the client does not send its offset, so an instant cannot be put in its day"
    assert "/items/query" in SRC, "nothing ever sends the tree"


# ── the columns the system issues on its own ───────────────────────────────
def test_a_created_at_column_is_filtered_by_when_the_item_was_created(client, admin_id):
    """מועד יצירה holds nothing in custom_fields — nobody types it, and the
    board draws it from the item. Read as a custom field it came back None for
    EVERY row, and None is not "this item has no value": "ריק" answered with
    the whole board and every other question with none of it. The first reads
    as a filter that never ran, which is what it was reported as."""
    bid = _board(client, admin_id, "לוח מועדי יצירה")
    cols = client.patch(f"/api/boards/{bid}",
                        json={"user_id": admin_id,
                              "columns": [{"type": "created_at", "title": "מועד יצירה"}]}
                        ).json()["columns"]
    cid = cols[0]["id"]
    mine = _task(client, bid, admin_id, "נוצר עכשיו")

    def ask(op, value=None):
        rule = {"field": cid, "operator": op}
        if value is not None:
            rule["value"] = value
        r = client.post(f"/api/boards/{bid}/items/query", json={
            "user_id": admin_id, "today": dt.date.today().isoformat(),
            "tz_offset": 180,
            "filter": {"operator": "and", "rules": [rule]}})
        assert r.status_code == 200, r.text
        return r.json()

    d = ask("empty")
    assert mine not in d["item_ids"], "an item created a moment ago has no creation date"
    assert d["matched"] == 0, "ריק answered with the whole board"

    d = ask("filled")
    assert mine in d["item_ids"] and d["matched"] == d["total"], \
        "אינו ריק answered with none of the board"

    assert mine in ask("on", "today")["item_ids"], "an item created today is not 'היום'"
    assert mine not in ask("on", "yesterday")["item_ids"]
    assert mine in ask("after", "yesterday")["item_ids"]


def test_a_created_by_column_is_filtered_by_who_made_the_item(client, admin_id, guinea_id):
    """Same column, same defect: the creator is on the item, not in its cells.
    And "אני" still means the person asking."""
    bid = _board(client, admin_id, "לוח יוצרים")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    cols = client.patch(f"/api/boards/{bid}",
                        json={"user_id": admin_id,
                              "columns": [{"type": "created_by", "title": "יוצר הרשומה"}]}
                        ).json()["columns"]
    cid = cols[0]["id"]
    mine = _task(client, bid, admin_id, "שלי")
    theirs = client.post("/api/tasks",
                         json={"board_id": bid, "title": "שלהם", "user_id": guinea_id},
                         headers={"X-CityOS-User": str(guinea_id)}).json()["id"]

    def ask(op, value, uid=admin_id):
        r = client.post(f"/api/boards/{bid}/items/query", json={
            "user_id": uid, "today": TODAY,
            "filter": {"operator": "and", "rules": [
                {"field": cid, "operator": op, "value": value}]}},
            headers={"X-CityOS-User": str(uid)})
        assert r.status_code == 200, r.text
        return r.json()["item_ids"]

    assert mine in ask("has", admin_id) and theirs not in ask("has", admin_id)
    assert theirs in ask("has", guinea_id) and mine not in ask("has", guinea_id)
    assert mine in ask("has", "me"), '"אני" does not find what I created'
    assert theirs in ask("has", "me", uid=guinea_id), '"אני" is not the person asking'
    assert theirs in ask("nhas", admin_id)
