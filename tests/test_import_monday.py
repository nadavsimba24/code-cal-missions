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
    assert {"תמיד ריקה", "נוסחה", "כפתור"} <= named
    assert all(s["reason"] for s in rep["skipped"]), "a column was dropped with no reason given"
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
    assert cf[by_title["סטטוס"]] == "בטיפול"


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
def test_a_known_person_is_assigned_and_a_stranger_is_reported(client, admin_id):
    me = client.get("/api/users", headers=H).json()[0]
    cols = [_cv("p", "אחראי", "people", text=me["name"]),
            _cv("p2", "גורם", "people", text="מישהו שלא קיים")]
    r = _upload(client, _resp([_item("פריט", cols)]), name="אנשים").json()
    board = client.get(f"/api/boards/{r['id']}?user_id=1", headers=H).json()
    by_title = {c["title"]: c["id"] for c in board["columns"] if c["id"].startswith("col_")}
    cf = board["tasks"][0]["custom_fields"]
    assert cf[by_title["אחראי"]] == [me["id"]], "a matched person was not assigned"
    assert by_title["גורם"] not in cf, "an unknown name was stored as if it were an account"
    assert "מישהו שלא קיים" in r["report"]["people_unmatched"]


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
    # matched to the parent's column by title, not by monday's own id
    assert top["subtasks"][0]["custom_fields"][by_title["סטטוס"]] == "בוצע"
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
    for monday_type in ("dependency", "progress", "subtasks", "team",
                        "time_tracking", "vote"):
        assert monday_type in import_monday.UNSUPPORTED, \
            f"{monday_type} is neither imported nor explained"
        assert monday_type not in import_monday.TYPE_MAP


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
