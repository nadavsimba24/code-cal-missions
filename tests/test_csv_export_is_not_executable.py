"""A name is not a program: nothing a user typed may run when a CSV is opened.

Excel treats a cell whose text begins with ``=``, ``+``, ``-`` or ``@`` as a
FORMULA, quotes and all. Every value in these five exports is written by an
ordinary member — an item title, a cell value, a board name, an automation name,
the old and new value in an activity row — so a person who names an item
``=HYPERLINK("http://evil",…)`` was writing code that ran on the machine of the
colleague who exported the file and double-clicked it.

The .xlsx export has always been safe (``_xlsx_cell`` sets ``data_type="s"`` —
"never a formula, whatever the text is"). The CSV exports were not. They now go
through ``_csv_safe``, which puts Excel's own "this is text" marker — a single
leading apostrophe, consumed when the file is opened — in front of a dangerous
value, and through ``_csv_writer``, which applies it to every field of every row
of every export.

What this file pins, and why each part matters:

* the ``_csv_safe`` table itself, including the numeric exemption — a negative
  figure must still sum in Excel, so ``-5`` is left alone while ``-1+cmd|calc``
  is not;
* that the marker is applied BEFORE csv quoting, so an injected quote cannot
  escape through the guard;
* all five export routes end to end, with a hostile string planted in real data
  — this is the part that matters, because the whole point of wrapping the
  WRITER rather than each call site is that no route can forget;
* that no bare ``csv.writer(buf)`` survives in ``backend/main.py`` outside the
  wrapper, which is what stops a sixth export being added next year with the bug
  quietly back in it;
* that the BOM, the CRLF, embedded commas and quotes and the Hebrew all still
  survive — the file still has to open correctly in Hebrew Excel, which is the
  reason the BOM is written in the first place.

The frontend's client-side ``exportCSV`` implements the same rule, including the
numeric exemption, and is pinned by ``tests/frontend/admin_tabs_sort_search_export.mjs``.
The two must not disagree about what is dangerous.
"""
import csv
import io
import pathlib
import re

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import ADMIN_ID
from models import Board, Task

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_PY = ROOT / "backend" / "main.py"

_csv_safe = cityos_main._csv_safe
_csv_writer = cityos_main._csv_writer

# What an attacker types. Every one of these begins — once Excel has skipped the
# whitespace it ignores — with a character that opens a formula.
EVIL = '=HYPERLINK("http://evil","לחצי כאן")'


# ── _csv_safe, value by value ──────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    '=HYPERLINK("http://evil")',   # the classic: a link to anywhere, auto-rendered
    "@me",                         # @ opens a legacy call in older sheets
    "-1+cmd|calc",                 # DDE: not a number, so the exemption must not catch it
    "\t=cmd",                      # Excel skips the tab before deciding it is a formula
])
def test_a_value_excel_would_execute_comes_back_marked_as_text(value):
    assert _csv_safe(value) == "'" + value


@pytest.mark.parametrize("value", ["+1", "-2", "-5", "-3.5", "0", "1e3"])
def test_a_number_is_left_alone_so_a_negative_figure_still_sums_in_excel(value):
    # A leading minus is far more often a negative number than an attack, and an
    # apostrophe in front of it turns a figure into a string Excel can no longer
    # add up — a budget column of marked-up negatives would quietly stop summing.
    assert _csv_safe(value) == value


@pytest.mark.parametrize("value", [
    "a@b.co.il",     # a mail address: the @ has to be LEADING to mean anything
    "רעות אורן",      # an ordinary Hebrew name
    "2026-10-28",    # a date, which starts with a digit
    "—",             # the em dash this product writes into an empty cell
])
def test_ordinary_text_is_handed_over_exactly_as_it_was_typed(value):
    # The em dash matters on its own: it is what the exports write for an empty
    # cell, it is not one of the four formula characters, and marking it would
    # put a stray apostrophe in front of every blank in the file.
    assert _csv_safe(value) == value


def test_an_absent_value_is_an_empty_cell_and_never_the_word_none():
    assert _csv_safe(None) == ""


def test_a_typed_hyphen_in_front_of_words_is_still_marked():
    # The exemption is "wholly a number", not "starts like one": "-1 מדרגה" is a
    # phrase a person can type into a name and Excel still reads it as a formula.
    assert _csv_safe("-1 מדרגה") == "'-1 מדרגה"


def test_the_guard_only_looks_at_the_front_of_the_value():
    assert _csv_safe("סה״כ = 5") == "סה״כ = 5"


# ── _csv_writer: the ordering, and that nothing slips past it ──────────────

def _written(rows, many=False):
    """Rows through the real writer, as the bytes a route would hand back."""
    buf = io.StringIO()
    w = _csv_writer(buf)
    if many:
        w.writerows(rows)
    else:
        for r in rows:
            w.writerow(r)
    return buf.getvalue()


def test_the_text_marker_goes_on_before_the_quoting_so_a_quote_cannot_escape():
    # Order is the whole of the guarantee here. The apostrophe is added to the
    # raw value and csv's own quote-doubling happens afterwards, on the marked
    # string — so a value carrying a quote cannot close the field early and land
    # outside the marker. Marking after quoting would produce "=A1&""x""" with
    # the apostrophe in the wrong place, or outside the quotes entirely.
    out = _written([['=A1&"x"']])
    assert out == '"\'=A1&""x"""\r\n', repr(out)


def test_every_field_of_the_row_is_guarded_and_not_merely_the_first():
    out = _written([["שלום", "=cmd", 7, None, "@me"]])
    assert out == 'שלום,\'=cmd,7,,\'@me\r\n', repr(out)


def test_writerows_is_guarded_exactly_as_writerow_is():
    # writerows is the easy one to forget, because csv.writer provides it for
    # free and a wrapper that only overrides writerow would pass every other
    # test in this file while leaking on whichever export used the plural form.
    assert _written([["=a"], ["=b"]], many=True) == _written([["=a"], ["=b"]])
    assert _written([["=a"], ["=b"]], many=True) == "'=a\r\n'=b\r\n"


def test_the_bom_crlf_commas_quotes_and_hebrew_all_survive_the_guard():
    # The guard was added to a file that already had to open correctly in Hebrew
    # Excel: the UTF-8 BOM is why Hebrew is not mojibake, the CRLF is what Excel
    # expects between rows, and the quoting is what keeps a name containing a
    # comma from splitting the row in two.
    buf = io.StringIO()
    buf.write("﻿")
    w = _csv_writer(buf)
    w.writerow(["שם", "הערה"])
    w.writerow(["דנה, לוי", 'אמרה "שלום", ואז יצאה'])
    out = buf.getvalue()
    assert out.startswith("﻿"), repr(out[:10])
    assert out.endswith("\r\n")
    assert '"דנה, לוי"' in out, repr(out)
    assert '"אמרה ""שלום"", ואז יצאה"' in out, repr(out)
    # and round-trips back to exactly what went in
    rows = list(csv.reader(io.StringIO(out.lstrip("﻿"))))
    assert rows == [["שם", "הערה"], ["דנה, לוי", 'אמרה "שלום", ואז יצאה']]


# ── the five routes, end to end ────────────────────────────────────────────

def assert_nothing_in_it_executes(body, must_contain=EVIL):
    """Parse an exported file the way Excel would and assert no cell is live.

    Parsing rather than searching for the marker: what matters is not that an
    apostrophe appears somewhere, it is that no FIELD of the file — in any
    column, including ones added later — reaches Excel looking like a formula.
    """
    assert body.startswith("﻿"), "the Hebrew BOM is gone from the export"
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    assert len(rows) >= 2, f"nothing was exported, so nothing was proved:\n{body}"
    fields = [f for row in rows for f in row]
    for n, row in enumerate(rows):
        for col, field in enumerate(row):
            if not re.match(r"^[\t\r\n ]*[=+\-@]", field):
                continue
            try:
                float(field)          # a number, which is allowed through on purpose
                continue
            except ValueError:
                pass
            raise AssertionError(
                f"row {n} column {col} is a live formula in Excel: {field!r}")
    # Compared against the PARSED fields, not against the raw text: the raw text
    # carries csv's own quote-doubling, so the planted value is unrecognisable
    # there — and a test that searched the raw body would pass on a file whose
    # quoting had broken.
    if must_contain is not None:
        assert "'" + must_contain in fields, \
            f"the planted value is not in the file at all:\n{body}"


@pytest.fixture(scope="module")
def hostile(client):
    """A board, an automation, an item and an activity trail, all named EVIL.

    One fixture for all five routes because they overlap: the board name reaches
    two exports, the automation name three, the item title and the audit trail
    the other two. Everything is torn down afterwards — the admin export is
    org-wide, so a stray board called =HYPERLINK(…) would turn up in another
    test's file.
    """
    bid = client.post("/api/boards", json={"name": EVIL, "user_id": ADMIN_ID}).json()["id"]
    try:
        a = client.post(f"/api/boards/{bid}/automations",
                        json={"actor_id": ADMIN_ID, "name": EVIL,
                              "recipe_id": "created_set_priority",
                              "config": {"a_priority": "high"}})
        assert a.status_code == 200, a.text
        # creating the item fires the automation, which is what writes a run row
        tid = client.post("/api/tasks", json={"board_id": bid, "title": EVIL,
                                              "user_id": ADMIN_ID}).json()["id"]
        # a rename, so the hostile title is also the "from" value of an audit row
        client.patch(f"/api/tasks/{tid}", json={"title": "@evil", "user_id": ADMIN_ID})
        yield {"board_id": bid, "task_id": tid, "automation_id": a.json()["id"]}
    finally:
        with Session(cityos_main.engine) as db:
            for t in db.query(Task).filter(Task.board_id == bid).all():
                db.delete(t)
            b = db.query(Board).filter(Board.id == bid).first()
            if b:
                db.delete(b)
            db.commit()


def test_the_automation_run_log_export_carries_no_formula(client, hostile, admin_id):
    r = client.get(f"/api/boards/{hostile['board_id']}/automations/runs/export"
                   f"?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert_nothing_in_it_executes(r.text)


def test_the_organisation_wide_automations_export_carries_no_formula(client, hostile,
                                                                     admin_id):
    r = client.get(f"/api/admin/automations/export?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert_nothing_in_it_executes(r.text)


def test_the_board_automations_export_carries_no_formula(client, hostile, admin_id):
    r = client.get(f"/api/boards/{hostile['board_id']}/automations/export"
                   f"?user_id={admin_id}")
    assert r.status_code == 200, r.text
    assert_nothing_in_it_executes(r.text)


def test_the_board_activity_export_carries_no_formula(client, hostile, admin_id):
    r = client.get(f"/api/boards/{hostile['board_id']}/activity/export"
                   f"?actor_id={admin_id}")
    assert r.status_code == 200, r.text
    assert_nothing_in_it_executes(r.text)
    # the rename put the hostile title in the "from" column and "@evil" in the
    # "to" one — both are user text and both have to be marked
    fields = [f for row in csv.reader(io.StringIO(r.text.lstrip("﻿"))) for f in row]
    assert "'@evil" in fields, r.text


def test_the_item_activity_export_carries_no_formula(client, hostile, admin_id):
    r = client.get(f"/api/tasks/{hostile['task_id']}/activity/export"
                   f"?actor_id={admin_id}")
    assert r.status_code == 200, r.text
    assert_nothing_in_it_executes(r.text)


def test_an_exported_file_still_reads_as_what_the_user_typed(client, hostile, admin_id):
    """The marker is a presentation device, not a mutation of the data.

    Excel consumes the apostrophe on open, so stripping it has to give back the
    original text exactly — including the quotes inside it. A guard that escaped
    or dropped characters would make the export lie about what is in the board.
    """
    body = client.get(f"/api/boards/{hostile['board_id']}/automations/export"
                      f"?user_id={admin_id}").text
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    names = [r[0] for r in rows[1:]]
    assert ["'" + EVIL] == names, names
    assert [n[1:] for n in names] == [EVIL]


# ── and the export nobody has written yet ──────────────────────────────────

def test_no_export_in_the_backend_writes_through_a_bare_csv_writer():
    """The sixth export, the one that does not exist yet.

    Wrapping the writer is what makes the rule impossible to forget, and the way
    it gets forgotten is somebody copying an older export that still said
    csv.writer(buf). The only legitimate mention of csv.writer in the whole file
    is inside _csv_writer itself, where it builds the writer it wraps.
    """
    src = MAIN_PY.read_text(encoding="utf-8")
    offenders = []
    inside_wrapper = False
    for n, line in enumerate(src.splitlines(), 1):
        if line.startswith("class _csv_writer"):
            inside_wrapper = True
            continue
        # the wrapper ends where the next top-level definition starts
        if inside_wrapper and line and not line[0].isspace():
            inside_wrapper = False
        if inside_wrapper or line.lstrip().startswith("#"):
            continue
        if re.search(r"\bcsv\.writer\s*\(", line):
            offenders.append(f"{MAIN_PY.name}:{n}: {line.strip()}")
    assert not offenders, (
        "a CSV is being written without the formula guard — use _csv_writer:\n"
        + "\n".join(offenders))


def test_all_five_csv_exports_are_still_built_with_the_guarded_writer():
    # The counterpart of the test above: that one proves nothing bare is left,
    # this one proves the guarded writer is actually in use, so deleting every
    # export is not a way to make the suite green.
    src = MAIN_PY.read_text(encoding="utf-8")
    uses = re.findall(r"=\s*_csv_writer\(", src)
    assert len(uses) == 5, f"expected the five CSV exports, found {len(uses)}"
