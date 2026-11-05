"""סינון על עמודת "רשימה נפתחת" — עמודה שמחזיקה כמה ערכים בתא אחד.

Reported on a real board, on a column called "מי ביקש": picking a value in
the filter panel returned nothing at all, and "ריק" returned the whole board.

A dropdown is asked about as a status — ADV_KINDS and filter_ast.KINDS both
map `dropdown` and `status` to the kind "status", so both offer שווה ל /
לא שווה ל / ריק / אינו ריק — and it is not SHAPED like one. A status cell
holds the one option chosen, as `{"label": …}` or as a bare string. A dropdown
cell holds the LIST of options ticked in it, which is the entire reason the
type exists.

Both engines read that list through the single-value branch and neither of
them said so:

  · the browser's advCell asked `typeof v === 'object'`, which an array
    answers yes to, read `.label` off it and found nothing — so EVERY cell of
    every dropdown column read as empty;
  · the server's filter_ast._cell fell through to `str(v)` and compared
    against the repr — "['ראש העיר']" is not "ראש העיר".

Different wrong answers, one cause, and the same thing on screen: a column
whose chips are offered, whose values are drawn in the cells, and whose filter
matches nothing.

What is pinned here: a value matches when it is ONE OF the things ticked —
anything stricter is unanswerable on a column built to take several — that
"לא שווה ל" is the exact negation over the same board, that emptiness is about
the list and not about its repr, and that a single-value status column still
behaves exactly as it did.
"""
import datetime
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import filter_ast  # noqa: E402

TODAY = datetime.date(2026, 11, 5)
FIELDS = {"c_who": "status"}


def _match(cells, op, value=None):
    rule = {"type": "rule", "field": "c_who", "operator": op,
            "value": value, "value2": None}
    return filter_ast.match_rule({"title": "x", "custom_fields": cells},
                                 rule, FIELDS, TODAY, 0, None)


# ── the cell reads as the list it is ──────────────────────────────────────
def test_a_multi_select_cell_reads_as_its_values_and_not_as_its_repr():
    """str(["ראש העיר"]) is "['ראש העיר']", and that string is what every
    comparison was being made against."""
    got = filter_ast._cell({"custom_fields": {"c_who": ["ראש העיר", "מהנדס"]}},
                           "c_who", "status", 0)
    assert got == ["ראש העיר", "מהנדס"]


def test_a_single_value_status_cell_still_reads_as_one_label():
    """The branch is shared, so the fix has to leave the other half alone."""
    assert filter_ast._cell({"custom_fields": {"c_who": {"label": "בוצע"}}},
                            "c_who", "status", 0) == "בוצע"
    assert filter_ast._cell({"custom_fields": {"c_who": "בוצע"}},
                            "c_who", "status", 0) == "בוצע"


# ── שווה ל means "it is one of the things ticked" ─────────────────────────
def test_a_value_matches_when_it_is_one_of_the_ones_ticked():
    assert _match({"c_who": ["ראש העיר"]}, "eq", "ראש העיר") is True
    assert _match({"c_who": ["מהנדס", "ראש העיר"]}, "eq", "ראש העיר") is True
    assert _match({"c_who": ["מהנדס"]}, "eq", "ראש העיר") is False


def test_not_equal_is_the_exact_negation_of_equal():
    """The two have to divide the board between them. They did not: "שווה ל"
    answered with nothing and "לא שווה ל" with everything, so a row that
    plainly said ראש העיר was in the "לא" half."""
    for cells in ({"c_who": ["ראש העיר"]}, {"c_who": ["מהנדס", "ראש העיר"]},
                  {"c_who": ["מהנדס"]}, {"c_who": None}, {"c_who": []}):
        assert _match(cells, "eq", "ראש העיר") is not _match(cells, "ne", "ראש העיר")


def test_the_case_of_the_typed_value_does_not_decide_the_answer():
    """Every other text comparison in this module is case-folded; a value
    picked from a chip is exact, but one typed in the advanced builder is
    whatever somebody typed."""
    assert _match({"c_who": ["Mayor"]}, "eq", "mayor") is True


# ── ריק / אינו ריק are about the list ─────────────────────────────────────
def test_a_cell_cleared_back_to_an_empty_list_is_empty():
    """Unticking the last option writes [] rather than null — see
    toggleDropdown in index.html, which sends `arr.length?arr:null` only from
    the grid. A cell emptied by a form, an import or an automation keeps the
    empty list, and "[]" read as a string is not empty to anybody."""
    assert _match({"c_who": []}, "empty") is True
    assert _match({"c_who": None}, "empty") is True
    assert _match({"c_who": ["ראש העיר"]}, "empty") is False


def test_filled_is_the_rows_with_something_ticked():
    assert _match({"c_who": ["ראש העיר"]}, "filled") is True
    assert _match({"c_who": []}, "filled") is False


# ── through the API, on a board ───────────────────────────────────────────
def _board(client, admin_id):
    return client.post("/api/boards",
                       json={"actor_id": admin_id, "name": "פניות"}).json()["id"]


def _col(client, bid, admin_id, spec):
    cur = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id, "columns": cur + [spec]})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json()["columns"] if c.get("title") == spec["title"])


def _item(client, bid, admin_id, title, cells):
    tid = client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                          "title": title}).json()["id"]
    r = client.patch(f"/api/tasks/{tid}",
                     json={"actor_id": admin_id, "custom_fields": cells})
    assert r.status_code == 200, r.text
    return tid


def _ask(client, bid, admin_id, col, op, value=None):
    """The titles the board answers with, for one condition on one column."""
    r = client.post(f"/api/boards/{bid}/items/query",
                    json={"user_id": admin_id, "limit": 50,
                          "today": TODAY.isoformat(), "tz_offset": 0,
                          "filter": {"type": "group", "operator": "and",
                                     "rules": [{"type": "rule", "field": col,
                                                "operator": op, "value": value}]}})
    assert r.status_code == 200, r.text
    return sorted(i.get("title") for i in r.json()["items"])


def _empty_the_board(client, bid, admin_id):
    """A new board is created with starter rows in it. They are real items
    with nothing in the column under test, so they are three more correct
    answers to "ריק" — and they would make every count below read as noise
    rather than as the five rows the test is about."""
    for t in client.get(f"/api/boards/{bid}?user_id={admin_id}").json().get("tasks") or []:
        client.delete(f"/api/tasks/{t['id']}?user_id={admin_id}")


@pytest.fixture
def asked_board(client, admin_id):
    """The board from the report: a "מי ביקש" dropdown and five rows."""
    bid = _board(client, admin_id)
    _empty_the_board(client, bid, admin_id)
    col = _col(client, bid, admin_id,
               {"type": "dropdown", "title": "מי ביקש",
                "options": ["ראש העיר", "מהנדס העיר", "תושב"]})
    _item(client, bid, admin_id, "נזילה", {col: ["ראש העיר"]})
    _item(client, bid, admin_id, "מדרכה", {col: ["מהנדס העיר", "ראש העיר"]})
    _item(client, bid, admin_id, "תאורה", {col: ["מהנדס העיר"]})
    _item(client, bid, admin_id, "לא נשאל", {col: None})
    _item(client, bid, admin_id, "נוקה", {col: []})
    try:
        yield bid, col
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_board_answers_the_question_the_panel_asks(client, admin_id, asked_board):
    """The whole of the report, end to end."""
    bid, col = asked_board
    assert _ask(client, bid, admin_id, col, "eq", "ראש העיר") == ["מדרכה", "נזילה"]
    assert _ask(client, bid, admin_id, col, "eq", "מהנדס העיר") == ["מדרכה", "תאורה"]
    assert _ask(client, bid, admin_id, col, "eq", "תושב") == []


def test_the_board_answers_the_empty_question_too(client, admin_id, asked_board):
    bid, col = asked_board
    assert _ask(client, bid, admin_id, col, "empty") == ["לא נשאל", "נוקה"]
    assert _ask(client, bid, admin_id, col, "filled") == ["מדרכה", "נזילה", "תאורה"]


def test_the_two_halves_of_the_board_are_still_the_whole_board(client, admin_id, asked_board):
    bid, col = asked_board
    yes = _ask(client, bid, admin_id, col, "eq", "ראש העיר")
    no = _ask(client, bid, admin_id, col, "ne", "ראש העיר")
    assert sorted(yes + no) == ["לא נשאל", "מדרכה", "נוקה", "נזילה", "תאורה"]


# ── and the engine in the browser, which answers first ────────────────────
def test_the_browser_answers_the_same_question_the_same_way():
    """Driven harness: tests/frontend/filter_a_dropdown_column.mjs.

    The local engine is what narrows the board on the keystroke, before the
    server's answer arrives and on every board small enough never to ask it.
    Both had to be fixed, so both are pinned — a fix to one alone would leave
    the board changing its mind a moment after it was filtered."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "filter_a_dropdown_column.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
