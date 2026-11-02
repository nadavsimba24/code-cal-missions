"""A status column nobody has filled in yet is still a column of the board.

The importer's standing rule is "no value on any item, no column" — a monday
response carries a cell for every column the board holds, the hidden and the
archived ones included, and creating those leaves empty columns standing in
front of a migrated board that nobody asked for.

A status column is the exception. Its own definition states its vocabulary —
"טרם הוגדר / בעבודה / הושלם" — and that vocabulary is the column, whether or
not any item sits on one of the words yet. A board migrated early in its life
has those columns empty in monday too, and arriving without them is the first
thing anyone notices. So: an empty status column that brought a vocabulary is
imported, with its words and their colours; one that brought none still falls
to the rule, because there is nothing left to build it from.
"""
import json

import pytest

H = {"X-CityOS-User": "1", "host": "localhost"}

LABELS = {"0": "טרם הוגדר", "1": "בעבודה", "2": "הושלם"}
COLORS = {"0": {"color": "#c4c4c4"}, "1": {"color": "#fdab3d"}, "2": {"color": "#00c875"}}


def _cv(cid, title, ctype, text=""):
    return {"id": cid, "type": ctype, "column": {"title": title}, "text": text}


def _status_def(cid, title, labels=LABELS, colors=COLORS):
    """monday answers settings as a JSON *string*, which is where a status
    column's words live — the copy riding inside every cell carries the title
    and the type and nothing more."""
    return {"id": cid, "title": title, "type": "status",
            "settings_str": json.dumps({"labels": labels, "labels_colors": colors},
                                       ensure_ascii=False)}


def _resp(items, columns=None):
    b = {"name": "לוח מאנדיי", "items_page": {"cursor": None, "items": items}}
    if columns is not None:
        b["columns"] = columns
    return json.dumps({"data": {"boards": [b]}}, ensure_ascii=False).encode()


def _upload(client, raw, name="סטטוס ריק"):
    r = client.post("/api/boards/import",
                    files={"file": ("response.json", raw, "application/json")},
                    data={"name": name}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _cols(client, bid):
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    return {c["title"]: c for c in board["columns"] if c["id"].startswith("col_")}


def _one_item(extra=()):
    """One item that fills the text column and leaves every status alone."""
    return [{"id": "1", "name": "פריט", "column_values":
             [_cv("t", "תיאור", "text", text="יש ערך")] + list(extra)}]


@pytest.fixture
def empty_status(client):
    """The case itself: a status column with a vocabulary and no values."""
    items = _one_item([_cv("s", "סטטוס", "status", text="")])
    return _upload(client, _resp(items, columns=[_status_def("s", "סטטוס")]))


def test_a_status_column_no_item_filled_in_is_still_imported(client, empty_status):
    assert "סטטוס" in _cols(client, empty_status["id"]), \
        "the column the file defined is not on the board"


def test_it_arrives_with_the_vocabulary_its_definition_states(client, empty_status):
    col = _cols(client, empty_status["id"])["סטטוס"]
    assert [o["label"] for o in col["options"]] == ["טרם הוגדר", "בעבודה", "הושלם"], \
        "an empty status column has no cells to learn its words from — only its definition"


def test_the_words_keep_the_colours_monday_gave_them(client, empty_status):
    col = _cols(client, empty_status["id"])["סטטוס"]
    paint = {o["label"]: (o.get("color") or "").lower() for o in col["options"]}
    assert paint["הושלם"] == "#00c875" and paint["בעבודה"] == "#fdab3d", \
        "the palette was cycled by position over a vocabulary the file coloured"


def test_the_labels_come_in_the_order_the_board_states_them(client):
    """monday keys the labels by index and writes the key as a string, so "10"
    sorts before "2" for anyone reading them as text."""
    labels = {"0": "ראשון", "2": "שני", "10": "עשירי"}
    items = _one_item([_cv("s", "סטטוס", "status", text="")])
    d = _upload(client, _resp(items, columns=[_status_def("s", "סטטוס", labels, {})]),
                name="סדר")
    col = _cols(client, d["id"])["סטטוס"]
    assert [o["label"] for o in col["options"]] == ["ראשון", "שני", "עשירי"]


def test_it_is_reported_as_imported_and_not_as_missing(client, empty_status):
    rep = empty_status["report"]
    assert "סטטוס" not in rep["columns_empty"], \
        "a column that was created is being named among the ones that were not"
    assert rep["columns_status_empty"] == ["סטטוס"], \
        "empty here and empty in monday still reads as a loss until it is said"


def test_a_status_column_the_file_never_defined_still_falls_to_the_rule(client):
    """No `columns { settings_str }` in the query: the column has no words, and
    an empty status column with no vocabulary is nothing to build."""
    items = _one_item([_cv("s", "סטטוס", "status", text="")])
    d = _upload(client, _resp(items), name="בלי הגדרות")
    assert "סטטוס" not in _cols(client, d["id"])
    assert "סטטוס" in d["report"]["columns_empty"]


def test_an_empty_column_of_any_other_type_is_still_not_a_column(client):
    """The exception is the status column's alone — the rule it stands against
    is what keeps a migrated board free of columns nobody has in monday."""
    items = _one_item([_cv("n", "מספר", "numbers", text=""),
                       _cv("d", "תאריך", "date", text="")])
    d = _upload(client, _resp(items, columns=[_status_def("s", "סטטוס")]), name="ריקות")
    titles = _cols(client, d["id"])
    assert "מספר" not in titles and "תאריך" not in titles
    assert set(d["report"]["columns_empty"]) == {"מספר", "תאריך"}


def test_a_status_column_that_was_used_is_unchanged_by_this(client):
    """The words a board actually uses still come from its items, so a column
    whose vocabulary outgrew what anyone selected does not drag the rest in."""
    items = [{"id": "1", "name": "פריט", "column_values":
              [_cv("s", "סטטוס", "status", text="בעבודה")]}]
    d = _upload(client, _resp(items, columns=[_status_def("s", "סטטוס")]), name="בשימוש")
    col = _cols(client, d["id"])["סטטוס"]
    assert [o["label"] for o in col["options"]] == ["בעבודה"]
    assert d["report"]["columns_status_empty"] == []


def test_a_status_column_only_the_board_definitions_name_still_comes_across(client):
    """monday answers with a cell per column on every item, so a column no item
    echoes is a file whose items cannot speak for it — a board with nothing on
    it yet, or a page that brought no items. The board's own column list is
    then the only statement of what it holds, and for a status column that
    statement is the whole column."""
    items = _one_item()                     # no status cell on the item at all
    d = _upload(client, _resp(items, columns=[_status_def("s", "סטטוס"),
                                              {"id": "n", "title": "מספר", "type": "numbers"}]),
                name="רק בהגדרות")
    cols = _cols(client, d["id"])
    assert "סטטוס" in cols, "the board's own column list named it and it was not created"
    assert [o["label"] for o in cols["סטטוס"]["options"]] == \
        ["טרם הוגדר", "בעבודה", "הושלם"]
    assert "מספר" not in cols, \
        "a column asserted by nothing and filled by nobody is not a column of this board"
