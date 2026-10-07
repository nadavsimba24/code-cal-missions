"""Importing a monday.com API response as a board.

The interesting cases are not "does it parse". They are: the column budget is
not raised to make the file fit, nothing is dropped without saying so, and the
types monday tells us about survive — which is the whole reason for reading the
JSON instead of a CSV export of the same board.
"""
import json

import pytest

import import_monday
import main as cityos_main

H = {"X-CityOS-User": "1", "host": "localhost"}


def _resp(items, board_name=None):
    b = {"items_page": {"cursor": None, "items": items}}
    if board_name:
        b["name"] = board_name
    return json.dumps({"data": {"boards": [b]}}, ensure_ascii=False).encode()


def _cv(cid, title, ctype, text="", value=None):
    c = {"id": cid, "type": ctype, "column": {"title": title}, "text": text}
    if value is not None:
        c["value"] = value if isinstance(value, str) else json.dumps(value)
    return c


def _item(name, cols, subitems=None):
    it = {"id": "1", "name": name, "column_values": cols}
    if subitems:
        it["subitems"] = subitems
    return it


def _upload(client, raw, name=None, filename="response.json"):
    data = {"name": name} if name else {}
    return client.post("/api/boards/import",
                       files={"file": (filename, raw, "application/json")},
                       data=data, headers=H)


# ── the column budget ───────────────────────────────────────────────────
def test_a_file_with_more_columns_than_allowed_does_not_raise_the_cap(client):
    cap = cityos_main.IMPORT_MAX_COLS
    cols = [_cv(f"c{i}", f"עמודה {i}", "text", text=f"ערך {i}") for i in range(cap + 15)]
    r = _upload(client, _resp([_item("פריט", cols)]), name="גדוש")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["columns"] == cap - 1, \
        f"the board got {d['columns']} custom columns; the budget is {cap - 1}"


def test_the_fullest_columns_are_the_ones_that_survive(client):
    """A column two items use carries less of the board than one every item fills."""
    cap = cityos_main.IMPORT_MAX_COLS
    items = []
    for n in range(6):
        cols = [_cv(f"busy{i}", f"מלאה {i}", "text", text="כן") for i in range(cap + 5)]
        # one sparse column, filled on a single item only
        cols.append(_cv("rare", "נדירה", "text", text="פעם" if n == 0 else ""))
        items.append(_item(f"פריט {n}", cols))
    r = _upload(client, _resp(items), name="דירוג")
    titles = _column_titles(client, r.json()["id"])
    assert "נדירה" not in titles, "a one-item column displaced a column every item fills"
    reasons = {s["title"]: s["reason"] for s in r.json()["report"]["skipped"]}
    assert "נדירה" in reasons and "תקרה" in reasons["נדירה"]


def test_every_dropped_column_is_named_with_a_reason(client):
    cap = cityos_main.IMPORT_MAX_COLS
    cols = ([_cv(f"c{i}", f"עמודה {i}", "text", text="ערך") for i in range(cap + 4)]
            + [_cv("empty", "תמיד ריקה", "text", text=""),
               _cv("f1", "נוסחה", "formula", text=""),
               _cv("b1", "כפתור", "button", text="Click me")])
    rep = _upload(client, _resp([_item("פריט", cols)]), name="דוח").json()["report"]
    named = {s["title"] for s in rep["skipped"]}
    assert "כפתור" in named
    assert all(s["reason"] for s in rep["skipped"]), "a column was dropped with no reason given"
    # A column with no value on any item is not created, and is named in its own
    # part of the report rather than among the columns that were dropped: an
    # empty text column is empty in monday too, while an empty formula column is
    # one the export never asked for the result of. Either way it is NAMED —
    # nothing leaves the file without appearing somewhere in the report.
    assert rep["columns_empty"] == ["תמיד ריקה"]
    assert [c["title"] for c in rep["columns_need_reexport"]] == ["נוסחה"]
    assert rep["columns_found"] == len(cols)


def _column_titles(client, bid):
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    return {c["title"] for c in board["columns"] if c["id"].startswith("col_")}


# ── the types, which are the point of reading JSON ──────────────────────
def test_the_column_types_survive_the_trip(client):
    cols = [
        _cv("s", "סטטוס", "status", text="בטיפול"),
        _cv("d", "תאריך", "date", text="2025-09-03", value={"date": "2025-09-03"}),
        _cv("n", "מספר", "numbers", text="72", value="72"),
        _cv("dd", "רשימה", "dropdown", text="אלפא, ביתא", value={"ids": [1, 2]}),
        _cv("cb", "סימון", "checkbox", text="v", value={"checked": True}),
        _cv("lt", "תיאור", "long_text", text="טקסט ארוך"),
    ]
    bid = _upload(client, _resp([_item("פריט", cols)]), name="סוגים").json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    got = {c["title"]: c["type"] for c in board["columns"] if c["id"].startswith("col_")}
    assert got == {"סטטוס": "status", "תאריך": "date", "מספר": "number",
                   "רשימה": "dropdown", "סימון": "checkbox", "תיאור": "text"}

    by_title = {c["title"]: c["id"] for c in board["columns"] if c["id"].startswith("col_")}
    cf = board["tasks"][0]["custom_fields"]
    assert cf[by_title["תאריך"]] == "2025-09-03"
    assert cf[by_title["מספר"]] == 72
    assert cf[by_title["רשימה"]] == ["אלפא", "ביתא"]
    assert cf[by_title["סימון"]] is True
    # a status cell points at one of the column's options; it does not hold the
    # word. The bare label matches nothing and the board shows "טרם הוגדר" over
    # a value that is in fact there.
    st = cf[by_title["סטטוס"]]
    opts = next(c for c in board["columns"] if c["title"] == "סטטוס")["options"]
    assert st["label"] == "בטיפול"
    assert st["id"] == next(o["id"] for o in opts if o["label"] == "בטיפול"), \
        "the cell does not reference the option it was imported as"
    assert st["color"] == next(o["color"] for o in opts if o["label"] == "בטיפול")


def test_every_status_cell_arrives_showing_its_status(client):
    """The column came over, the vocabulary came over, and every cell was blank.

    A status cell references an option by id; written as the bare label monday
    rendered it matches nothing, and the board shows "טרם הוגדר" over data that
    is sitting right there. The whole column reads as never filled in — which is
    the worst way for a migration to fail, because it looks like a small board
    rather than a broken one."""
    labels = ["מעוניינים", "בטיפול", "נחתם", "מעוניינים"]
    items = [dict(_item(f"לקוח {i}", [_cv("s", "סטטוס לקוח", "status", text=v)]), id=str(i))
             for i, v in enumerate(labels)]
    bid = _upload(client, _resp(items), name="לקוחות").json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "סטטוס לקוח")
    by_label = {o["label"]: o for o in col["options"]}

    shown = [t["custom_fields"][col["id"]] for t in board["tasks"]]
    assert len(shown) == 4, "an item lost its status cell entirely"
    assert [v["label"] for v in shown] == labels, [v.get("label") for v in shown]
    for v in shown:
        assert v["id"] == by_label[v["label"]]["id"], \
            "the cell does not point at the option the column offers"
        assert v["color"] == by_label[v["label"]]["color"]
    # two items on the same status are the same option, not two that look alike
    assert shown[0]["id"] == shown[3]["id"]


def test_a_status_option_carries_an_id_a_cell_can_point_at(client):
    items = [_item("פריט", [_cv("s", "שלב", "status", text="בחינה")])]
    bid = _upload(client, _resp(items), name="מזהים").json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "שלב")
    assert all(o.get("id") for o in col["options"]), \
        "an option with no id can only ever be matched by its own name"


def test_a_status_column_keeps_the_labels_the_board_actually_used(client):
    items = [_item(f"פריט {i}", [_cv("s", "שלב", "status", text=v)])
             for i, v in enumerate(["בחינה", "דרישות", "בחינה", "בדיקות"])]
    bid = _upload(client, _resp(items), name="סטטוסים").json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "שלב")
    labels = [o["label"] for o in col["options"]]
    assert labels == ["בחינה", "דרישות", "בדיקות"], "the vocabulary is wrong or duplicated"
    assert all(o.get("color") for o in col["options"]), "an imported status option has no colour"


def test_a_file_column_arrives_as_a_files_column_holding_the_names(client):
    """A files column is where a file belongs, so that is where it lands.

    The bytes stay behind monday's auth and the signed links in an export expire
    within the hour, so what actually crosses over is the name — which is the
    half that tells you which items have a document attached."""
    cols = [_cv("f", "מסמך", "file", text="https://monday.com/protected/x",
                value={"files": [{"name": "אפיון.docx", "assetId": 1}]})]
    bid = _upload(client, _resp([_item("פריט", cols)]), name="קבצים").json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "מסמך")
    assert col["type"] == "files"
    assert board["tasks"][0]["custom_fields"][col["id"]] == [{"name": "אפיון.docx", "url": ""}]


# ── people ──────────────────────────────────────────────────────────────
def test_a_known_person_is_assigned_and_a_stranger_is_kept_by_name(client, admin_id):
    """A name with no account here is kept as the name, not thrown away.

    A monday people cell carries monday's own person id and an export carries no
    e-mail to resolve it against, so a display name is often the only key there
    is — and on a real board it matches almost nobody. Dropping those cells left
    two columns of 306 and 135 items empty over data plainly present in monday.
    The name is a string, which is not an id and cannot become an assignment by
    accident; the report still names everyone who did not match.
    """
    me = client.get("/api/users", headers=H).json()[0]
    cols = [_cv("p", "אחראי", "people", text=me["name"]),
            _cv("p2", "גורם", "people", text="מישהו שלא קיים")]
    r = _upload(client, _resp([_item("פריט", cols)]), name="אנשים").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    by_title = {c["title"]: c["id"] for c in board["columns"] if c["id"].startswith("col_")}
    cf = board["tasks"][0]["custom_fields"]
    assert cf[by_title["אחראי"]] == [me["id"]], "a matched person was not assigned"
    assert cf[by_title["גורם"]] == ["מישהו שלא קיים"], "the name was thrown away"
    assert "מישהו שלא קיים" in r["report"]["people_unmatched"]


def test_a_cell_holding_both_keeps_the_account_and_the_name(client):
    me = client.get("/api/users", headers=H).json()[0]
    cols = [_cv("p", "אחראי", "people", text=f'{me["name"]}, Deleted member')]
    r = _upload(client, _resp([_item("פריט", cols)]), name="מעורב").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "אחראי")
    assert board["tasks"][0]["custom_fields"][col["id"]] == [me["id"], "Deleted member"]


def test_a_kept_name_survives_an_edit_of_the_cell(client, admin_id):
    """The membership rule has nothing to say about a name that is not an
    assignment — and asking it would compare text to an integer column, which
    Postgres refuses outright."""
    me = client.get("/api/users", headers=H).json()[0]
    cols = [_cv("p", "אחראי", "people", text="רעות אורן")]
    r = _upload(client, _resp([_item("פריט", cols)]), name="עריכה").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "אחראי")
    task = board["tasks"][0]
    # the owner of the board adds themselves beside the imported name
    up = client.patch(f"/api/tasks/{task['id']}", headers=H, json={
        "actor_id": admin_id, "custom_fields": {col["id"]: ["רעות אורן", me["id"]]}})
    assert up.status_code == 200, up.text
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    kept = next(t for t in board["tasks"] if t["id"] == task["id"])["custom_fields"][col["id"]]
    assert "רעות אורן" in kept and me["id"] in kept


def test_the_board_shows_a_kept_name_as_a_name_and_not_as_a_person():
    """It is who was on the item in monday — not someone this system can notify
    or assign, and the cell has to say which."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "function peopleGhost" in src
    assert "av-ghost" in src and "אין לו חשבון כאן" in src
    i = src.index("function peopleDisp")
    body = src[i:i + 700]
    assert "typeof v!=='number'" in body and "peopleGhost(v)" in body
    # and it reads as a name wherever a people cell is turned into text
    assert "? ((st.users||[]).find(u=>u.id===x)||{}).name : x" in src


# ── sub-items ───────────────────────────────────────────────────────────
def test_subitems_become_children_and_show_only_their_own_columns(client):
    parent_cols = [_cv("s", "סטטוס", "status", text="בטיפול"),
                   _cv("only", "רק באב", "text", text="ערך")]
    sub_cols = [_cv("xx", "סטטוס", "status", text="בוצע")]
    raw = _resp([_item("אב", parent_cols,
                       subitems=[{"id": "9", "name": "בן", "column_values": sub_cols}])])
    d = _upload(client, raw, name="תת").json()
    assert d["subitems"] == 1
    board = client.get(f"/api/boards/{d['id']}?user_id=1", headers=H).json()
    top = board["tasks"][0]
    assert len(top["subtasks"]) == 1 and top["subtasks"][0]["title"] == "בן"
    by_title = {c["title"]: c["id"] for c in board["columns"] if c["id"].startswith("col_")}
    # matched to the parent's column by title, not by monday's own id — and a
    # sub-item's status references the same vocabulary the parent column has
    sub_st = top["subtasks"][0]["custom_fields"][by_title["סטטוס"]]
    opts = next(c for c in board["columns"] if c["title"] == "סטטוס")["options"]
    assert sub_st["label"] == "בוצע"
    assert sub_st["id"] == next(o["id"] for o in opts if o["label"] == "בוצע")
    assert by_title["רק באב"] not in (board.get("sub_cols") or []), \
        "sub-items show a column none of them carries"


# ── the shape of the file ───────────────────────────────────────────────
def test_a_json_file_that_is_not_a_monday_response_is_refused(client):
    r = _upload(client, json.dumps({"hello": "world"}).encode())
    assert r.status_code == 400
    assert "מאנדיי" in r.json()["detail"]


def test_a_csv_still_imports_as_a_table(client):
    """The new branch must not have swallowed the path that already worked."""
    csv = "שם,סטטוס\nפריט א,בוצע\nפריט ב,בטיפול\n".encode()
    r = client.post("/api/boards/import",
                    files={"file": ("board.csv", csv, "text/csv")},
                    data={"name": "טבלה"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["items"] == 2


def test_it_does_not_care_which_way_the_query_nested_the_items():
    """monday returns items under items_page or directly, depending on the query."""
    flat = json.dumps({"data": {"boards": [{"items": [
        {"id": "1", "name": "פריט", "column_values": []}]}]}}).encode()
    assert import_monday.looks_like_monday(flat)
    assert import_monday.parse(flat, 39)["items"][0]["name"] == "פריט"


def test_an_item_with_no_name_still_becomes_a_row(client):
    raw = _resp([_item("", [_cv("t", "עמודה", "text", text="ערך")])])
    d = _upload(client, raw, name="ללא שם").json()
    assert d["items"] == 1


# ── the mapping sheet ───────────────────────────────────────────────────
# The migration was specified as a table: this monday type becomes that column
# here. These are that table, asserted — because a column that lands as the
# wrong type is a board that looks imported and isn't.
def test_every_type_on_the_mapping_sheet_lands_where_the_sheet_says(client):
    sheet = {
        "auto_number": "number", "button": "status", "checkbox": "checkbox",
        "color_picker": "text", "country": "text", "creation_log": "text",
        "date": "date", "doc": "files", "dropdown": "dropdown", "email": "email",
        "file": "files", "formula": "text", "hour": "text",
        "item_assignees": "people", "item_id": "text", "last_updated": "text",
        "link": "text", "location": "text", "long_text": "text", "mirror": "text",
        "numbers": "number", "people": "people", "phone": "text",
        "rating": "rating", "status": "status", "tags": "dropdown", "text": "text",
        "timeline": "timeline", "week": "text", "world_clock": "text",
        "board_relation": "text",
    }
    for monday_type, ours in sheet.items():
        assert import_monday.TYPE_MAP.get(monday_type) == ours, \
            f"{monday_type} should import as {ours}, not {import_monday.TYPE_MAP.get(monday_type)}"


def test_the_types_the_sheet_calls_unsupported_are_reported_not_guessed_at(client):
    for monday_type in ("dependency", "progress", "team", "time_tracking", "vote"):
        assert monday_type in import_monday.UNSUPPORTED, \
            f"{monday_type} is neither imported nor explained"
        assert monday_type not in import_monday.TYPE_MAP


def test_the_sub_items_column_is_neither_imported_nor_a_loss(client):
    """It is the one type on the sheet whose content does come in — as the
    items' sub-items. Called "unsupported" it reads as "the sub-items did not
    come in", which is the opposite of what happens."""
    assert import_monday.SUBITEMS_TYPE == "subtasks"
    assert "subtasks" not in import_monday.TYPE_MAP
    assert "subtasks" not in import_monday.UNSUPPORTED


def test_a_column_that_lands_somewhere_other_than_the_obvious_place_says_so(client):
    """An import that quietly retypes a column is an import you cannot check."""
    cols = [_cv("f", "חישוב", "formula", text="42"),
            _cv("t", "טקסט", "text", text="ערך")]
    r = _upload(client, _resp([_item("פריט", cols)]), name="הסבה").json()
    notes = {m["title"]: m["note"] for m in r["report"]["mapping"]}
    assert notes["חישוב"], "the formula column was retyped in silence"
    assert notes["טקסט"] is None, "a column that landed where you'd expect claims otherwise"


def test_an_e_mail_column_arrives_as_an_e_mail_column(client):
    """monday states the type; there is now somewhere of our own for it to land,
    so it is no longer flattened into text — and nothing is reported, because
    nothing was decided on the user's behalf."""
    cols = [_cv("e", "דוא\"ל איש קשר", "email", text="bhaa@abugosh.muni.il",
                value={"text": "bhaa@abugosh.muni.il", "email": "bhaa@abugosh.muni.il"})]
    r = _upload(client, _resp([_item("פריט", cols)]), name="מיילים").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "דוא\"ל איש קשר")
    assert col["type"] == "email"
    assert board["tasks"][0]["custom_fields"][col["id"]] == "bhaa@abugosh.muni.il"
    assert [m["note"] for m in r["report"]["mapping"]] == [None]


# ── values that are not strings ─────────────────────────────────────────
def test_a_timeline_keeps_both_of_its_ends(client):
    cols = [_cv("tl", "טווח", "timeline", text="2025-03-01 - 2025-04-15",
                value={"from": "2025-03-01", "to": "2025-04-15"})]
    bid = _upload(client, _resp([_item("פריט", cols)]), name="ציר").json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "טווח")
    assert col["type"] == "timeline"
    assert board["tasks"][0]["custom_fields"][col["id"]] == {"from": "2025-03-01",
                                                             "to": "2025-04-15"}


def test_a_rating_arrives_as_a_number_of_stars_and_nonsense_does_not(client):
    cols = [_cv("r", "דירוג", "rating", text="4", value={"rating": 4}),
            _cv("r2", "מחוץ לטווח", "rating", text="9", value={"rating": 9})]
    bid = _upload(client, _resp([_item("פריט", cols)]), name="כוכבים").json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    by_title = {c["title"]: c for c in board["columns"] if c["id"].startswith("col_")}
    cf = board["tasks"][0]["custom_fields"]
    assert by_title["דירוג"]["type"] == "rating"
    assert cf[by_title["דירוג"]["id"]] == 4
    assert by_title["מחוץ לטווח"]["id"] not in cf, "a 9-star rating was stored as if it were real"


# ── people are matched on the half that lasts ───────────────────────────
def test_a_person_is_found_by_e_mail_even_when_the_display_name_has_changed(client):
    me = client.get("/api/users", headers=H).json()[0]
    cols = [_cv("p", "אחראי", "people", text="שם ישן שכבר לא בשימוש",
                value={"personsAndTeams": [{"id": 9, "kind": "person",
                                            "email": me["email"]}]})]
    r = _upload(client, _resp([_item("פריט", cols)]), name="מייל").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "אחראי")
    assert board["tasks"][0]["custom_fields"][col["id"]] == [me["id"]]


def test_a_person_is_found_through_the_account_s_user_list(client):
    """A people cell states a person as monday's own id for them and usually
    without an e-mail beside it — which is why her two people columns, 306 items
    and 135, matched almost nobody: a display name character for character was
    the only key there was. `users { id name email }` at the root of the query
    turns that id into an address, and an address is what can be matched.
    """
    me = client.get("/api/users", headers=H).json()[0]
    cols = [_cv("p", "אחראי", "people", text="שם שאינו שמו של אף חשבון",
                value={"personsAndTeams": [{"id": 11397425, "kind": "person"}]})]
    doc = json.loads(_resp([_item("פריט", cols)]).decode())
    doc["data"]["users"] = [{"id": "11397425", "name": "מי שהוא", "email": me["email"]}]
    r = _upload(client, json.dumps(doc, ensure_ascii=False).encode(), name="מיל").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "אחראי")
    assert board["tasks"][0]["custom_fields"][col["id"]] == [me["id"]], \
        "the id was never resolved to an address"
    assert r["report"]["people_matched"] == 1


def test_without_the_user_list_the_name_is_still_all_there_is(client):
    """And then it is kept as a name rather than dropped — the behaviour the
    board already relies on."""
    cols = [_cv("p", "אחראי", "people", text="רעות אורן",
                value={"personsAndTeams": [{"id": 11397425, "kind": "person"}]})]
    r = _upload(client, _resp([_item("פריט", cols)]), name="בלי").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "אחראי")
    assert board["tasks"][0]["custom_fields"][col["id"]] == ["רעות אורן"]


def test_one_person_named_twice_is_assigned_once(client):
    """monday's cell can carry both the display name and the e-mail of the same
    person; two tokens are not two people."""
    me = client.get("/api/users", headers=H).json()[0]
    cols = [_cv("p", "אחראי", "people", text=me["name"],
                value={"personsAndTeams": [{"id": 9, "kind": "person",
                                            "email": me["email"]}]})]
    r = _upload(client, _resp([_item("פריט", cols)]), name="כפילות").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "אחראי")
    assert board["tasks"][0]["custom_fields"][col["id"]] == [me["id"]]
    assert r["report"]["people_matched"] == 1


# ── groups ──────────────────────────────────────────────────────────────
def test_the_board_keeps_its_own_groups_and_each_item_lands_in_its_own(client):
    items = [
        dict(_item("ראשון", [_cv("t", "טקסט", "text", text="א")]),
             group={"id": "g1", "title": "רבעון ראשון"}),
        dict(_item("שני", [_cv("t", "טקסט", "text", text="ב")]),
             group={"id": "g2", "title": "רבעון שני"}),
        dict(_item("שלישי", [_cv("t", "טקסט", "text", text="ג")]),
             group={"id": "g1", "title": "רבעון ראשון"}),
    ]
    bid = _upload(client, _resp(items), name="קבוצות").json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    names = [g["name"] for g in board["groups"]]
    assert names == ["רבעון ראשון", "רבעון שני"], f"got {names}"
    where = {t["title"]: t["group_id"] for t in board["tasks"]}
    first = {g["name"]: g["id"] for g in board["groups"]}
    assert where["ראשון"] == where["שלישי"] == first["רבעון ראשון"]
    assert where["שני"] == first["רבעון שני"]
    # position is counted inside the group, not across the board
    pos = {t["title"]: t["position"] for t in board["tasks"]}
    assert pos["ראשון"] == 0 and pos["שלישי"] == 1 and pos["שני"] == 0


def test_the_board_arrives_under_its_own_name(client):
    """The export names the board. Falling back to the file name was right only
    while the query did not ask for it."""
    raw = _resp([_item("פריט", [_cv("t", "טקסט", "text", text="א")])],
                board_name="ניהול תוכן אתר החברה")
    d = _upload(client, raw, filename="response781 (1).json").json()
    assert d["name"] == "ניהול תוכן אתר החברה", f"got {d['name']!r}"


def test_a_name_typed_in_the_dialog_still_wins_over_the_one_in_the_file(client):
    raw = _resp([_item("פריט", [_cv("t", "טקסט", "text", text="א")])], board_name="שם מהקובץ")
    assert _upload(client, raw, name="שם שנבחר").json()["name"] == "שם שנבחר"


def test_a_group_the_board_declares_is_built_even_with_nothing_in_it(client):
    """An empty stage is part of how the board is laid out. Building only the
    groups that happen to hold an item would quietly redraw the board."""
    raw = json.dumps({"data": {"boards": [{
        "id": "6204255781", "name": "לוח",
        "groups": [{"id": "g1", "title": "לביצוע"},
                   {"id": "g2", "title": "ריקה"},
                   {"id": "g3", "title": "הושלם"}],
        "items_page": {"cursor": None, "items": [
            dict(_item("פריט", [_cv("t", "טקסט", "text", text="א")]),
                 group={"id": "g3", "title": "הושלם"})]}}]}}, ensure_ascii=False).encode()
    bid = _upload(client, raw).json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    assert [g["name"] for g in board["groups"]] == ["לביצוע", "ריקה", "הושלם"], \
        "the groups the board declares, in the board's own order"
    last = board["groups"][2]["id"]
    assert board["tasks"][0]["group_id"] == last


def test_a_group_with_no_title_is_still_a_group_of_its_own(client):
    items = [dict(_item("פריט", [_cv("t", "טקסט", "text", text="א")]),
                  group={"id": "g1", "title": ""})]
    bid = _upload(client, _resp(items)).json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    assert len(board["groups"]) == 1 and board["tasks"][0]["group_id"] == board["groups"][0]["id"]


# ── a board longer than one page ────────────────────────────────────────
def _page(items, cursor=None, board_name=None, groups=None, bid="6204255781"):
    b = {"id": bid, "items_page": {"cursor": cursor, "items": items}}
    if board_name:
        b["name"] = board_name
    if groups:
        b["groups"] = groups
    return {"data": {"boards": [b]}}


def _row(iid, title, gid=None):
    it = dict(_item(title, [_cv("t", "טקסט", "text", text=title)]), id=iid)
    if gid:
        it["group"] = {"id": gid, "title": gid}
    return it


def test_the_pages_of_one_board_are_read_as_the_one_board_they_are(client):
    """A board past the page limit comes back as several responses. Put in one
    file, they are one board — not one board and a lost remainder."""
    raw = json.dumps([
        _page([_row("1", "אחד"), _row("2", "שתיים")], cursor="abc", board_name="לוח ארוך"),
        _page([_row("3", "שלוש")], cursor=None),
    ], ensure_ascii=False).encode()
    d = _upload(client, raw).json()
    assert d["name"] == "לוח ארוך", "the name is on the first page and only there"
    assert d["items"] == 3, f"got {d['items']} items out of two pages"
    assert d["report"]["truncated"] is False, "the last page ended the board"


def test_page_two_fetched_by_cursor_belongs_to_the_same_board(client):
    """next_items_page comes back at the root, with no board around it. It is
    still the same board, and reading it as anything else loses the remainder."""
    raw = json.dumps([
        _page([_row("1", "אחד")], cursor="abc", board_name="לוח"),
        {"data": {"next_items_page": {"cursor": None, "items": [_row("2", "שתיים")]}}},
    ], ensure_ascii=False).encode()
    d = _upload(client, raw).json()
    assert d["name"] == "לוח" and d["items"] == 2, d


def test_a_page_handed_over_twice_does_not_double_the_items(client):
    page = _page([_row("1", "אחד"), _row("2", "שתיים")], cursor="abc")
    raw = json.dumps([page, page, _page([_row("3", "שלוש")])], ensure_ascii=False).encode()
    assert _upload(client, raw).json()["items"] == 3


def test_an_export_that_stopped_before_the_end_of_the_board_says_so(client):
    """A cursor still set means the query had a limit and the board went on. The
    import cannot fetch the rest — but a half-imported board that says nothing
    is the failure this whole reader exists to prevent."""
    raw = json.dumps(_page([_row("1", "אחד")], cursor="MSw2MjA0MjU1NzgxLA"),
                     ensure_ascii=False).encode()
    assert _upload(client, raw).json()["report"]["truncated"] is True


def test_two_different_boards_in_one_file_are_refused_not_half_imported(client):
    raw = json.dumps([_page([_row("1", "אחד")], bid="111"),
                      _page([_row("2", "שתיים")], bid="222")], ensure_ascii=False).encode()
    r = _upload(client, raw)
    assert r.status_code == 400, r.text
    assert "111" in r.text and "222" in r.text, "the refusal names both boards"


def test_the_groups_of_the_board_survive_being_split_across_pages(client):
    raw = json.dumps([
        _page([_row("1", "אחד", "g1")], cursor="abc", board_name="לוח",
              groups=[{"id": "g1", "title": "לביצוע"}, {"id": "g2", "title": "הושלם"}]),
        _page([_row("2", "שתיים", "g2")]),
    ], ensure_ascii=False).encode()
    bid = _upload(client, raw).json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    assert [g["name"] for g in board["groups"]] == ["לביצוע", "הושלם"]
    where = {t["title"]: t["group_id"] for t in board["tasks"]}
    assert where["אחד"] != where["שתיים"]


def test_a_file_is_named_by_its_asset_even_after_someone_renamed_it(client):
    """The new query asks for asset_id, and the asset carries the name the file
    has now — which the cell's own copy does not."""
    cols = [{"id": "f", "type": "file", "column": {"title": "מסמך"},
             "text": "https://monday.com/protected/x",
             "value": json.dumps({"files": [{"name": "אפיון-ישן.docx", "assetId": 77}]}),
             "files": [{"asset_id": 77}]}]
    it = dict(_item("פריט", cols),
              assets=[{"id": 77, "name": "אפיון סופי.docx",
                       "public_url": "https://files.monday.com/a.docx"}])
    bid = _upload(client, _resp([it])).json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "מסמך")
    # the asset's own name wins over the cell's stale text. The bytes could not
    # be had here, so the entry is marked as the name it is rather than left
    # looking like a working link — see _import_attachments
    assert board["tasks"][0]["custom_fields"][col["id"]] == \
        [{"name": "אפיון סופי.docx", "url": "https://files.monday.com/a.docx",
          "why": "failed", "dead": True}]


def test_the_built_in_columns_the_file_never_had_are_not_shown(client):
    """סטטוס and עדיפות are columns of this system, not of the file.

    Nothing in the import fills them, so on an imported board they are four
    columns of "טרם הוגדר" standing in front of the board that was actually
    migrated — and because the export is built from the same column list, they
    follow it into the file too. They are hidden, not removed: they are still
    the board's columns the moment there is something to put in them."""
    r = _upload(client, _resp([_item("פריט", [_cv("t", "טקסט", "text", text="א")])]),
                name="הסבה").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    assert set(board["col_hidden"]) == {"assignees", "status", "priority", "due"}, \
        board["col_hidden"]
    # the item column is not among them — it is the one that cannot be hidden
    assert "item" not in board["col_hidden"]


def test_a_hidden_built_in_column_is_still_the_board_s_to_bring_back(client, admin_id):
    """Hiding is a display decision, so it is one an admin can undo — if the
    import had removed the columns instead there would be nothing to turn on."""
    r = _upload(client, _resp([_item("פריט", [_cv("t", "טקסט", "text", text="א")])])).json()
    bid = r["id"]
    resp = client.patch(f"/api/boards/{bid}",
                        json={"col_hidden": ["assignees", "due"], "user_id": 1}, headers=H)
    assert resp.status_code == 200, resp.text
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    assert set(board["col_hidden"]) == {"assignees", "due"}, \
        "סטטוס and עדיפות could not be turned back on"


def test_a_file_with_no_groups_gets_one_unnamed_group(client):
    """Without `group { id title }` the export says nothing about how the board
    was divided. Three invented stages would be a claim the file does not make,
    and so would a heading over the one group that holds everything — so it is
    left unnamed, to be renamed once there is something true to call it."""
    r = _upload(client, _resp([_item("פריט", [_cv("t", "טקסט", "text", text="א")])]),
                name="ללא קבוצות").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    assert [g["name"] for g in board["groups"]] == [""]
    assert len(board["tasks"]) == 1, "the item did not land in the group"
    assert board["tasks"][0]["group_id"] == board["groups"][0]["id"]
    assert r["report"]["groups"] == 0, "an invented group was counted as one the file had"


# ── the types monday answers somewhere other than `text` ────────────────────

def _dv(cid, title, mtype, display_value=None, **extra):
    cv = {"id": cid, "type": mtype, "column": {"title": title}, "text": None, "value": None}
    if display_value is not None:
        cv["display_value"] = display_value
    cv.update(extra)
    return cv


def test_a_formula_column_is_read_from_display_value(client):
    """monday: "the computed result is returned in display_value; the text and
    value fields are not populated". Read from text, every formula column on
    every board arrives empty."""
    cols = [_dv("f", "ימים עד לעליה לאוויר", "formula", display_value="14")]
    r = _upload(client, _resp([_item("פריט", cols)]), name="נוסחה").json()
    assert r["report"]["columns_imported"] == 1, r["report"]["skipped"]
    assert not r["report"]["columns_empty"], "a filled formula column counted as empty"


def test_a_connect_boards_column_is_read_from_its_linked_items(client):
    """monday: "the text and value fields always return null" for connect boards."""
    cols = [_dv("b", "תחום מבקש הפיתוח", "board_relation", display_value="חינוך, רווחה")]
    r = _upload(client, _resp([_item("פריט", cols)]), name="קישור").json()
    assert r["report"]["columns_imported"] == 1
    assert not r["report"]["columns_empty"]


def test_a_connect_column_falls_back_to_the_linked_item_names(client):
    cols = [_dv("b", "מוטמע בתחומים", "board_relation",
                linked_items=[{"id": "1", "name": "חינוך"}, {"id": "2", "name": "רווחה"}])]
    r = _upload(client, _resp([_item("פריט", cols)]), name="קישור2").json()
    assert r["report"]["columns_imported"] == 1
    assert not r["report"]["columns_empty"]


def test_a_mirror_column_is_read_from_display_value(client):
    cols = [_dv("m", "מראה", "mirror", display_value="ערך מראה")]
    r = _upload(client, _resp([_item("פריט", cols)]), name="מראה").json()
    assert r["report"]["columns_imported"] == 1
    assert not r["report"]["columns_empty"]


def test_the_export_query_asks_for_those_three(client):
    """The reader cannot find what the query never asked for."""
    import pathlib
    q = (pathlib.Path(__file__).resolve().parent.parent / "backend" / "monday_export.graphql"
         ).read_text(encoding="utf-8")
    for frag in ("... on BoardRelationValue", "... on MirrorValue", "... on FormulaValue"):
        assert q.count(frag) >= 2, f"{frag} is missing from one of the two queries"
    assert "display_value" in q
    # and the limit that will bite a board with six of them is written down
    assert "FIVE formula columns" in q


# ── a formula monday worked out to nothing ──────────────────────────────────
def test_a_formula_that_came_back_null_is_empty_and_not_the_word(client):
    """monday answers the four characters "null" for a formula that worked out to
    nothing — a formula over a date nobody has filled in yet. Stored verbatim it
    filled 315 of one column's 320 cells with the word, which reads as a column
    that is full and says nothing."""
    cols = [_cv("f", "משך", "formula"), _cv("f2", "ימים", "formula")]
    items = [_item("א", [{**cols[0], "display_value": "null"},
                         {**cols[1], "display_value": "47"}]),
             _item("ב", [{**cols[0], "display_value": "NaN"},
                         {**cols[1], "display_value": ""}])]
    r = _upload(client, _resp(items), name="נוסחה").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    by_title = {c["title"]: c["id"] for c in board["columns"] if c["id"].startswith("col_")}
    cells = [t["custom_fields"].get(by_title["ימים"]) for t in board["tasks"]]
    assert "47" in cells, "a value monday did compute still arrives"
    # the column whose every cell was "null" is not a column at all
    assert "משך" not in by_title, "a column of nothing but null was created anyway"
    assert r["report"]["formula_nothing"] == 0, \
        "the count is of cells in columns that were imported"


def test_the_count_of_empty_formula_cells_is_reported(client):
    cols = [_cv("f", "משך", "formula")]
    items = [_item("א", [{**cols[0], "display_value": "null"}]),
             _item("ב", [{**cols[0], "display_value": "199.25"}])]
    r = _upload(client, _resp(items), name="נוסחה2").json()
    rep = r["report"]
    assert rep["formula_nothing"] == 1
    assert rep["formula_nothing_cols"] == [{"title": "משך", "cells": 1}]
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "משך")
    vals = [t["custom_fields"].get(col["id"]) for t in board["tasks"]]
    assert sorted(v for v in vals if v) == ["199.25"], vals
    assert None in vals, "the null cell is empty, not the word"


def test_an_error_monday_states_is_kept(client):
    """"#ERROR!" is monday saying something true about the formula, and a cell
    that says so is more use than a blank one."""
    cols = [_cv("f", "משך", "formula")]
    r = _upload(client, _resp([_item("א", [{**cols[0], "display_value": "#ERROR!"}])]),
                name="שגיאה").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    col = next(c for c in board["columns"] if c.get("title") == "משך")
    assert board["tasks"][0]["custom_fields"][col["id"]] == "#ERROR!"


def test_the_report_explains_an_almost_empty_formula_column():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "formula_nothing" in src and "תאי נוסחה חזרו ממאנדיי" in src
    assert "formula_nothing_cols" in src, "and names the columns it happened in"

