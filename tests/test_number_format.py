"""A number column that says what the number is.

A budget column, a square-metre column and a count of complaints are all
"number" today, and the board cannot tell you which is which. The unit and the
thousands separator are what make the figure readable — and they are
presentation, not data: the cell goes on storing a number, so the board still
sorts on it, formulas still add it up, and the export still hands Excel a
figure rather than the string "₪1,234".

What is asserted here is that the server keeps the setting, that it keeps only
the setting (not an arbitrary blob), and that no cell value changed because of
it. How the figure is drawn and edited lives in
tests/frontend/number_format.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "number_format.mjs"


def _board(client, admin_id, name="תקציב"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _num_col(client, bid, uid, cid="col_sum"):
    return next(c for c in client.get(f"/api/boards/{bid}?user_id={uid}").json()["columns"]
                if c["id"] == cid)


def _save(client, bid, admin_id, cfg, cid="col_sum"):
    col = {"id": cid, "type": "number", "title": "תקציב"}
    if cfg is not None:
        col["number"] = cfg
    r = client.patch(f"/api/boards/{bid}", json={"columns": [col], "user_id": admin_id})
    assert r.status_code == 200, r.text
    return _num_col(client, bid, admin_id, cid)


def test_a_unit_and_a_separator_survive_the_round_trip(client, admin_id):
    bid = _board(client, admin_id)
    got = _save(client, bid, admin_id, {"unit": "₪", "thousands": True})
    assert got["number"] == {"unit": "₪", "thousands": True}


def test_a_unit_of_your_own_is_kept_as_typed(client, admin_id):
    bid = _board(client, admin_id)
    assert _save(client, bid, admin_id, {"unit": 'מ"ר', "thousands": False})["number"] == \
        {"unit": 'מ"ר', "thousands": False}


def test_a_plain_number_column_carries_no_setting_at_all(client, admin_id):
    """The default is stored as nothing. A board nobody configured should not
    end up with {unit:"",thousands:false} on every number column it has."""
    bid = _board(client, admin_id)
    assert _save(client, bid, admin_id, None)["number"] is None
    assert _save(client, bid, admin_id, {"unit": "", "thousands": False})["number"] is None


def test_the_setting_can_be_taken_back_off(client, admin_id):
    bid = _board(client, admin_id)
    _save(client, bid, admin_id, {"unit": "₪", "thousands": True})
    assert _save(client, bid, admin_id, {"unit": "", "thousands": False})["number"] is None


def test_a_unit_is_not_a_place_to_put_a_paragraph(client, admin_id):
    bid = _board(client, admin_id)
    got = _save(client, bid, admin_id, {"unit": "א" * 200, "thousands": True})
    assert got["number"]["unit"] == "א" * 6


def test_the_setting_is_refused_as_anything_but_a_setting(client, admin_id):
    """Whatever arrives, what is stored is a unit and a flag — nothing else
    rides along into the board's settings."""
    bid = _board(client, admin_id)
    for junk in ("₪", ["₪"], 42, True):
        assert _save(client, bid, admin_id, junk)["number"] is None
    got = _save(client, bid, admin_id, {"unit": "₪", "thousands": True, "onclick": "alert(1)"})
    assert got["number"] == {"unit": "₪", "thousands": True}


def test_only_a_number_column_gets_one(client, admin_id):
    bid = _board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}", json={
        "columns": [{"id": "col_t", "type": "text", "title": "טקסט",
                     "number": {"unit": "₪", "thousands": True}}],
        "user_id": admin_id})
    assert r.status_code == 200, r.text
    assert _num_col(client, bid, admin_id, "col_t")["number"] is None


def test_changing_the_unit_does_not_touch_a_single_cell(client, admin_id):
    """The whole point of keeping presentation out of the value: the currency
    can be changed at any time, and no item data is rewritten to do it."""
    bid = _board(client, admin_id)
    _save(client, bid, admin_id, {"unit": "₪", "thousands": True})
    t = client.post("/api/tasks", json={"title": "סלילה", "board_id": bid,
                                        "user_id": admin_id}).json()
    client.patch(f"/api/tasks/{t['id']}",
                 json={"custom_fields": {"col_sum": 1234567.5}, "user_id": admin_id})
    _save(client, bid, admin_id, {"unit": "$", "thousands": False})
    board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    got = next(x for x in board["tasks"] if x["id"] == t["id"])
    assert got["custom_fields"]["col_sum"] == 1234567.5, \
        "the stored figure changed when only its presentation should have"


def test_the_grid_draws_and_edits_the_figure_the_way_it_was_configured():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
