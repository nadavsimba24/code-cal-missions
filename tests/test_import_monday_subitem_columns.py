"""Sub-items arrive with the column structure the board gives them.

On monday a sub-item belongs to a board of its own, with its own columns: "שלב",
"שעות", "קבלן" can exist on the sub-items and nowhere on the parent board. The
importer matched sub-item columns to the parent's by title — which is what
sharing a column means here — and dropped every one with no counterpart. That is
most of a sub-item board, and the sub-items landed as a list of names with every
cell empty.

Those columns are board columns here too, marked `sub_only`: shown on the
sub-item rows and never on the parent item, which is the structure the file
describes. Created as ordinary columns instead, they would stand on every item
as well, empty forever.
"""
import json
import pathlib

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


def _sub(name, cols, sid="9"):
    return {"id": sid, "name": name, "column_values": cols}


def _upload(client, raw, name=None):
    data = {"name": name} if name else {}
    return client.post("/api/boards/import",
                       files={"file": ("response.json", raw, "application/json")},
                       data=data, headers=H)


def _board(client, bid):
    return client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()


# the board: items carry אחראי; the sub-items carry אחראי too, plus two columns
# of their own
ITEM_COLS = [_cv("text0", "אחראי", "text", text="דנה"),
             _cv("numbers0", "תקציב", "numbers", text="5000", value="5000")]
SUB_COLS = [_cv("text7", "אחראי", "text", text="יואב"),
            _cv("text9", "שלב", "text", text="פירוק"),
            _cv("numbers4", "שעות", "numbers", text="12", value="12")]


def _one_item_with_subs(client):
    raw = _resp([{"id": "1", "name": "תיקון מדרכה", "column_values": ITEM_COLS,
                  "subitems": [_sub("פירוק האריחים", SUB_COLS)]}])
    r = _upload(client, raw, name="תתי פריטים")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_column_only_the_sub_items_have_is_imported(client):
    d = _one_item_with_subs(client)
    board = _board(client, d["id"])
    titles = {c["title"]: c["id"] for c in board["columns"] if c["id"].startswith("col_")}
    assert "שלב" in titles and "שעות" in titles, \
        f"the sub-item board's own columns were dropped: {sorted(titles)}"
    sub = board["tasks"][0]["subtasks"][0]
    cf = sub["custom_fields"]
    assert cf[titles["שלב"]] == "פירוק"
    assert cf[titles["שעות"]] == 12
    # and the one the parent also has is ONE column, shared
    assert cf[titles["אחראי"]] == "יואב"
    assert board["tasks"][0]["custom_fields"][titles["אחראי"]] == "דנה"


def test_those_columns_belong_to_the_sub_items_and_not_to_the_items(client):
    d = _one_item_with_subs(client)
    board = _board(client, d["id"])
    titles = {c["id"]: c["title"] for c in board["columns"]}
    assert sorted(titles[i] for i in (board.get("sub_only") or [])) == ["שלב", "שעות"]
    # the shared one is the subset the sub-items show; the sub-item-only ones are
    # appended by the board itself, so they are not in this list
    assert [titles[i] for i in (board.get("sub_cols") or [])[1:]] == ["אחראי"]


def test_a_sub_item_column_id_that_repeats_the_parents_is_still_its_own_column(client):
    """The two boards number their columns independently: "text0" on the
    sub-item board is not "text0" on the parent's. Read by id, a sub-item's
    "שלב" was written into the parent's "אחראי"."""
    raw = _resp([{"id": "1", "name": "תיקון מדרכה",
                  "column_values": [_cv("text0", "אחראי", "text", text="דנה")],
                  "subitems": [_sub("פירוק", [_cv("text0", "שלב", "text", text="הכנה")])]}])
    d = _upload(client, raw, name="התנגשות").json()
    board = _board(client, d["id"])
    titles = {c["title"]: c["id"] for c in board["columns"] if c["id"].startswith("col_")}
    assert "שלב" in titles, "a colliding id swallowed the sub-item's own column"
    sub = board["tasks"][0]["subtasks"][0]
    assert sub["custom_fields"].get(titles["שלב"]) == "הכנה"
    assert sub["custom_fields"].get(titles["אחראי"]) is None, \
        "the sub-item's value landed in the parent's column"


def test_a_status_column_only_the_sub_items_have_keeps_its_vocabulary(client):
    raw = _resp([{"id": "1", "name": "תיקון מדרכה",
                  "column_values": [_cv("text0", "אחראי", "text", text="דנה")],
                  "subitems": [_sub("פירוק", [_cv("status3", "שלב", "status", text="בוצע")]),
                               _sub("יציקה", [_cv("status3", "שלב", "status", text="ממתין")],
                                    sid="10")]}])
    d = _upload(client, raw, name="סטטוס תת").json()
    board = _board(client, d["id"])
    col = next(c for c in board["columns"] if c["title"] == "שלב")
    labels = {o["label"] for o in (col["options"] or [])}
    assert labels == {"בוצע", "ממתין"}, labels
    kid = board["tasks"][0]["subtasks"][0]
    cell = kid["custom_fields"][col["id"]]
    assert cell["label"] == "בוצע"
    assert cell["id"] == next(o["id"] for o in col["options"] if o["label"] == "בוצע")


def test_an_empty_sub_item_column_is_not_a_column(client):
    """The same rule the item columns are held to: no value on any row, no
    column — otherwise the board gets a column nobody in monday has."""
    raw = _resp([{"id": "1", "name": "תיקון מדרכה",
                  "column_values": [_cv("text0", "אחראי", "text", text="דנה")],
                  "subitems": [_sub("פירוק", [_cv("text9", "ריקה", "text", text=""),
                                              _cv("text8", "שלב", "text", text="הכנה")])]}])
    d = _upload(client, raw, name="ריקה").json()
    titles = [c["title"] for c in _board(client, d["id"])["columns"]]
    assert "שלב" in titles and "ריקה" not in titles, titles


def test_a_sub_item_column_type_with_nothing_to_carry_is_named_not_dropped(client):
    raw = _resp([{"id": "1", "name": "תיקון מדרכה",
                  "column_values": [_cv("text0", "אחראי", "text", text="דנה")],
                  "subitems": [_sub("פירוק", [_cv("vote1", "הצבעה", "vote", text="3")])]}])
    rep = _upload(client, raw, name="לא נתמך").json()["report"]
    named = {s["title"]: s["reason"] for s in rep["skipped"]}
    assert "הצבעה" in named and "תתי-הפריטים" in named["הצבעה"], named


def test_the_report_names_the_columns_that_are_the_sub_items_own(client):
    rep = _one_item_with_subs(client)["report"]
    assert sorted(rep["columns_sub"]) == ["שלב", "שעות"]
    # and they are counted as columns that were found and imported
    assert rep["columns_imported"] >= 4
    assert "שלב" in [m["title"] for m in rep["mapping"]]


def test_the_ceiling_covers_both_sets_together(client):
    """A sub-item board cannot buy the board more columns than it is allowed."""
    cap = cityos_main.IMPORT_MAX_COLS
    item_cols = [_cv(f"i{i}", f"פריט {i}", "text", text="ערך") for i in range(cap - 1)]
    sub_cols = [_cv(f"s{i}", f"תת {i}", "text", text="ערך") for i in range(5)]
    raw = _resp([{"id": "1", "name": "אב", "column_values": item_cols,
                  "subitems": [_sub("בן", sub_cols)]}])
    d = _upload(client, raw, name="תקרה").json()
    assert d["columns"] == cap - 1, d["columns"]
    reasons = {s["title"]: s["reason"] for s in d["report"]["skipped"]}
    assert any(t.startswith("תת ") for t in reasons), reasons


def test_sub_items_with_no_shared_column_do_not_inherit_the_items(client):
    """When the two boards share nothing, the sub-item header is its own.

    sub_cols comes back as just the name, and the frontend reads an empty shared
    subset beside sub_only columns as "the sub-items show their own" — not as
    "inherit every item column", which put a dozen empty cells in front of the
    ones that are filled.
    """
    raw = _resp([{"id": "1", "name": "תיקון מדרכה",
                  "column_values": [_cv("text0", "אחראי", "text", text="דנה"),
                                    _cv("text1", "הערות", "text", text="דחוף")],
                  "subitems": [_sub("פירוק", [_cv("text9", "שלב", "text", text="הכנה")])]}])
    d = _upload(client, raw, name="אין משותף").json()
    board = _board(client, d["id"])
    titles = {c["id"]: c["title"] for c in board["columns"]}
    assert board["sub_cols"] == ["item"], board["sub_cols"]
    assert [titles[i] for i in board["sub_only"]] == ["שלב"]
    # the frontend half of the same answer
    html = (pathlib.Path(__file__).resolve().parent.parent
            / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "(subOnly.length ? [name] : all)" in html, (
        "an empty shared subset falls back to inheriting every item column, so "
        "a sub-item board that shares nothing shows the item's columns instead "
        "of its own")
