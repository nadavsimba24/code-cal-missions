"""A monday import brings the whole board, or it says so loudly enough to hear.

Both rules here were written by the same migration. A monday board of 2,069
items was imported and arrived with 2,000: the row ceiling cut the last 69 in
file order, all of them in one group, and the loss was written into the import
report as one line among thirty. It was found a day later by counting the group
in monday — 1,819 there, 1,748 here — which is the one way a migration must not
be checked.

So two things are pinned:

  * past the ceiling the import is REFUSED rather than trimmed. A board quietly
    3% short is worse than an import that did not happen, because only one of
    the two gets noticed.
  * the file is measured against `items_count`, monday's own answer to how many
    rows the board has. The cursor already catches an export that stopped at the
    END; a merge that lost a page out of the MIDDLE ends on a null cursor and
    reads as a complete file of a smaller board. Only this number sees it.
"""
import json

import pytest

import import_monday
import main as cityos_main

H = {"X-CityOS-User": "1", "host": "localhost"}


def _item(n):
    return {"id": str(n), "name": f"P-{n:05d}",
            "column_values": [{"id": "t", "type": "text",
                               "column": {"title": "שם הרשות"}, "text": f"רשות {n}"}],
            "group": {"id": "g1", "title": "ערבויות ששוחררו"}}


def _resp(items, items_count=None, cursor=None):
    b = {"id": "4633188480", "name": "ערבויות",
         "groups": [{"id": "g1", "title": "ערבויות ששוחררו"}],
         "items_page": {"cursor": cursor, "items": items}}
    if items_count is not None:
        b["items_count"] = items_count
    return json.dumps({"data": {"boards": [b]}}, ensure_ascii=False).encode()


def _upload(client, raw, name=None):
    return client.post("/api/boards/import",
                       files={"file": ("response.json", raw, "application/json")},
                       data={"name": name} if name else {}, headers=H)


# ── the row ceiling ─────────────────────────────────────────────────────
def test_a_file_past_the_row_ceiling_is_refused_rather_than_cut(client, monkeypatch):
    """This is the exact shape of the board that lost 69 rows: more items than
    the ceiling, and nothing in the result that looks wrong."""
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_ROWS", 20)
    r = _upload(client, _resp([_item(i) for i in range(29)]), name="חורג")
    assert r.status_code == 413, \
        f"a file 9 rows past the ceiling imported anyway: {r.status_code} {r.text[:300]}"
    # the two numbers are the whole point — "too big" is not something to act on
    assert "29" in r.text and "20" in r.text, r.text


def test_a_file_exactly_at_the_ceiling_is_imported_whole(client, monkeypatch):
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_ROWS", 20)
    r = _upload(client, _resp([_item(i) for i in range(20)]), name="בדיוק")
    assert r.status_code == 200, r.text
    assert r.json()["items"] == 20


def test_the_default_ceiling_clears_a_real_monday_board(client):
    """2,069 was a real board and it did not fit. The ceiling is now set where a
    board somebody actually migrates does not reach it."""
    assert cityos_main.IMPORT_MAX_ROWS >= 2069, \
        "the ceiling is back below the size of the board that found it"


# ── the file against monday's own count ─────────────────────────────────
def test_a_file_short_of_the_board_says_how_many_are_missing():
    rep = import_monday.parse(_resp([_item(i) for i in range(1748)],
                                    items_count=1817), 79)["report"]
    assert rep["items"] == 1748
    assert rep["items_expected"] == 1817
    assert rep["items_missing"] == 69


def test_a_whole_file_reports_nothing_missing():
    rep = import_monday.parse(_resp([_item(i) for i in range(12)],
                                    items_count=12), 79)["report"]
    assert rep["items_missing"] == 0


def test_a_merge_that_lost_a_middle_page_is_caught_though_the_cursor_is_clean():
    """The page that went missing is not the last one, so the file ends on a
    null cursor and `truncated` is false. Without items_count this file reads as
    a complete export of a 20-item board."""
    doc = [{"data": {"boards": [{"id": "1", "name": "לוח", "items_count": 30,
                                 "items_page": {"cursor": "c1",
                                                "items": [_item(i) for i in range(10)]}}]}},
           # the middle page (10-19) is the one the merge dropped
           {"data": {"next_items_page": {"cursor": None,
                                         "items": [_item(i) for i in range(20, 30)]}}}]
    rep = import_monday.parse(json.dumps(doc, ensure_ascii=False), 79)["report"]
    assert rep["truncated"] is False, "the cursor cannot see this one — that is the point"
    assert rep["items"] == 20
    assert rep["items_missing"] == 10


def test_a_file_that_never_stated_a_count_says_nothing_rather_than_guessing():
    """`items_count` is only in the file when the query asked for it. Absent, the
    report must not claim the board is whole and must not claim it is short."""
    rep = import_monday.parse(_resp([_item(i) for i in range(5)]), 79)["report"]
    assert rep["items_expected"] is None
    assert rep["items_missing"] == 0


def test_the_count_survives_the_pages_that_do_not_carry_it(client):
    """It rides on the first response only — page two onwards comes back at the
    root, with no board around it. Losing it there is losing the check."""
    doc = [{"data": {"boards": [{"id": "1", "name": "לוח", "items_count": 25,
                                 "items_page": {"cursor": "c1",
                                                "items": [_item(i) for i in range(10)]}}]}},
           {"data": {"next_items_page": {"cursor": None,
                                         "items": [_item(i) for i in range(10, 20)]}}}]
    rep = import_monday.parse(json.dumps(doc, ensure_ascii=False), 79)["report"]
    assert rep["items_expected"] == 25
    assert rep["items_missing"] == 5
