"""A board whose structure is built and whose rows are not.

monday answers such a board `items_page: {items: []}` beside its columns and its
groups — real board `8038892607` is one: thirteen columns, one group, and a log
saying the three default rows were deleted in December 2024 and nothing was ever
created after them.

The import refused it twice over, and the message said "no items in the
response", which reads as a broken export rather than an empty board. It is
worth importing as it stands: the columns, the groups and the log arrive, and
the first row is typed here instead of there.

What must NOT become importable along with it is the history response on its
own — one board, a log, and nothing that was ever asked to carry a row. That
file is a step of the export somebody uploaded by mistake, and it has to keep
saying so.
"""
import json

import pytest

import import_monday

H = {"X-CityOS-User": "1", "host": "localhost"}


def _upload(client, raw, name=None, filename="response.json"):
    data = {"name": name} if name else {}
    return client.post("/api/boards/import",
                       files={"file": (filename, raw, "application/json")},
                       data=data, headers=H)


def _empty_board(**extra):
    b = {"id": "8038892607", "name": "סיור דינמי ממוקד אתגר - צד תושב",
         "items_count": 0,
         "groups": [{"id": "topics", "title": "סיכום הפתרונות והמענים", "color": "#579bfc"}],
         "columns": [{"id": "name", "title": "Name", "type": "name"},
                     {"id": "status_1", "title": "סטטוס מענה", "type": "status",
                      "settings_str": json.dumps({"labels": {"0": "פתוח", "1": "טופל"}})},
                     {"id": "text_1", "title": "שם התושב", "type": "text"},
                     {"id": "long_1", "title": "מה האתגר?", "type": "long_text"}],
         "items_page": {"cursor": None, "items": []}}
    b.update(extra)
    return json.dumps({"data": {"boards": [b]}}, ensure_ascii=False).encode()


def test_a_board_with_no_rows_is_imported_rather_than_refused(client):
    r = _upload(client, _empty_board(), name="צד תושב")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "צד תושב"


def test_it_arrives_with_the_columns_the_file_states(client):
    r = _upload(client, _empty_board())
    bid = r.json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    titles = [c["title"] for c in board["columns"]]
    assert "סטטוס מענה" in titles, titles
    assert board["tasks"] == [], "a board with no rows arrived holding rows"


def test_a_column_no_row_fills_is_still_a_column_of_this_board(client):
    """With items, a column no item shows a value for is read as a column that
    is not really there — hidden, archived, never asked for — and dropped. With
    no items that reasoning has nothing to stand on: every column is empty
    because there is no row. The file's list is the whole of what the board is."""
    r = _upload(client, _empty_board())
    board = client.get(f"/api/boards/{r.json()['id']}?user_id=1", headers=H).json()
    titles = [c["title"] for c in board["columns"]]
    for t in ("סטטוס מענה", "שם התושב", "מה האתגר?"):
        assert t in titles, f"{t} missing from {titles}"
    assert not r.json()["report"].get("blank"), r.json()["report"]


def test_mondays_name_column_does_not_become_a_column(client):
    """monday lists the item's own name among the board's columns. Read as one
    it arrives as a second "Name" standing empty beside every row's title."""
    r = _upload(client, _empty_board())
    board = client.get(f"/api/boards/{r.json()['id']}?user_id=1", headers=H).json()
    assert "Name" not in [c["title"] for c in board["columns"]]


def test_the_group_the_board_keeps_comes_with_it(client):
    r = _upload(client, _empty_board())
    bid = r.json()["id"]
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    assert [g["name"] for g in board["groups"]] == ["סיכום הפתרונות והמענים"]


def test_the_log_still_arrives_for_a_board_with_no_rows(client):
    """The log is most of what an empty board has to say — in the real one it is
    the whole record of a board being built."""
    logs = [{"id": "1", "event": "create_column", "user_id": "11397425",
             "created_at": "17311112220000000",
             "data": json.dumps({"board_id": 8038892607, "column_title": "סטטוס מענה"})}]
    r = _upload(client, _empty_board(activity_logs=logs))
    assert r.status_code == 200, r.text


def test_the_history_response_on_its_own_is_still_refused(client):
    """One board, a log, and no page that was ever asked to carry a row."""
    raw = json.dumps({"data": {"boards": [
        {"id": "8038892607",
         "activity_logs": [{"id": "1", "event": "create_column", "user_id": "1",
                            "created_at": "17311112220000000", "data": "{}"}]}]}},
        ensure_ascii=False).encode()
    r = _upload(client, raw, filename="log.json")
    assert r.status_code == 400
    assert "מאנדיי" in r.json()["detail"]


def test_the_parser_tells_the_two_apart(client):
    """Directly, because the endpoint reports both as a 400 and the difference
    between them is the whole of this change."""
    board, items, cursor = import_monday._items_of(json.loads(_empty_board()))
    assert items == [] and board["id"] == "8038892607"
    with pytest.raises(import_monday.NotMondayJson):
        import_monday._items_of({"data": {"boards": [{"id": "1", "activity_logs": []}]}})
