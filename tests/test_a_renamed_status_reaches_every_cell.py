"""Renaming a status option carries the new word into the cells already wearing it.

The column editor rewrites the VOCABULARY. The cells go on holding whatever
they were written with — the grid stores the label, a form answer and a monday
import store the whole option — so an option renamed from "אושר" to "אושר
סופית" leaves every item already marked with it reading the old word. The
browser used to fix that itself, one PATCH per cell over the rows it happened
to hold, which is a fiftieth of the job on a board the server is paging:
fifty rows renamed and twenty-one thousand left behind, a migration that looks
like it ran. POST /api/boards/{id}/columns/{col}/status-rename does the whole
board in one pass, and this file is what says it really does.

What is pinned, and why each one is here:

**All three cell shapes.** A bare label string, `{label,color}` with no id, and
a full `{id,label,color}` are all genuinely in the data — the grid wrote the
first two over the years, forms and the monday import write the third. The old
browser loop only ever handled the dict-with-a-label ones, so the other two are
new ground and the only place they are checked is here. Resolution is by option
id first and by the old label only then, because the id is the option's stable
name and the label is the very thing being changed.

**An old word that is now some OTHER option's name is refused, not guessed.**
A cell holding only a label cannot be resolved in that case: it is unknowable
whether it means the option renamed away from the word or the one that now
answers to it. Guessing moves items between statuses, silently, with nothing on
any screen to say it happened. The refusal is the whole point of the endpoint
being careful, so it gets its own test — and the cells are read back after it
to prove the refusal is total rather than a half-written board plus a 400.

**A cell still reads back as the same option id.** An automation stores the
option's id and `_status_cell_key` reads a cell back to one, so rules were
never what broke in a rename — but they are what a careless rewrite (writing
just the new label, dropping the id) would break, and it would break them
without any error.

**Archived items and the recycle bin are included.** They come back. An
unarchive or a restored board must not bring back a word the column stopped
offering months ago, which is the same unreadable disagreement that makes
dropping a status-in-use a 409.

The browser's half — the editor no longer refusing on a large board, the call
going out without a colour and only after the column itself saved, and the rows
on screen being brought into line without a re-fetch — is pinned at the bottom
of this file and in tests/frontend/status_rename_adopts_the_rows_on_screen.mjs.

Everything here is built on boards this file makes and deletes. Nothing is ever
run against a board that was already there.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import join_primary_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "status_rename_adopts_the_rows_on_screen.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

OLD, NEW = "אושר", "אושר סופית"


def AS(uid):
    return {"X-CityOS-User": str(uid)}


@pytest.fixture
def boards(client, admin_id):
    """Boards a test makes, taken away again when it ends — the suite runs
    repeatedly against one seeded temp DB."""
    made = []
    try:
        yield made
    finally:
        for bid in reversed(made):
            client.delete(f"/api/boards/{bid}", headers=AS(admin_id))


def _board(client, admin_id, made, name):
    r = client.post("/api/boards", json={"actor_id": admin_id, "name": name})
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    made.append(bid)
    return bid


def _cols(client, bid, uid):
    r = client.get(f"/api/boards/{bid}", headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()["columns"]


def _status_col(client, admin_id, made, name="לוח סטטוס"):
    """A board with a status column of three options, and the options by label."""
    bid = _board(client, admin_id, made, name)
    cols = _cols(client, bid, admin_id) + [
        {"type": "status", "title": "סטטוס עבודה",
         "options": [{"label": OLD, "color": "#00c875"},
                     {"label": "ממתין", "color": "#fdab3d"},
                     {"label": "נדחה", "color": "#e2445c"}]}]
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    col = next(c for c in _cols(client, bid, admin_id) if c["type"] == "status")
    return bid, col["id"], {o["label"]: o for o in col["options"]}


def _item(client, admin_id, bid, title, **extra):
    r = client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                        "title": title, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _write_cell(tid, cid, value):
    """A status cell written exactly as one of the three shapes, straight into
    the row. The API normalises what it is given — which is the point: the old
    shapes are what is ALREADY in the data, and there is no endpoint that will
    write them any more. The board belongs to the test and is deleted with it,
    so nothing shared is touched; test_a_big_board_sends_its_count_not_its_rows
    reaches for the session the same way, for the same reason."""
    with Session(cityos_main.engine) as db:
        t = db.query(cityos_main.Task).filter(cityos_main.Task.id == tid).first()
        cf = dict(t.custom_fields or {})
        cf[cid] = value
        t.custom_fields = cf
        db.commit()


def _cell(tid, cid):
    with Session(cityos_main.engine) as db:
        t = (db.query(cityos_main.Task).filter(cityos_main.Task.id == tid)
             .execution_options(include_deleted=True).first())
        return (t.custom_fields or {}).get(cid)


def _rename_the_column(client, admin_id, bid, cid, opts, frm=OLD, to=NEW):
    """Save the column under its NEW vocabulary — what the editor does first.
    The endpoint resolves each rename by the option's new label, so it can only
    be called after this."""
    cols = _cols(client, bid, admin_id)
    for c in cols:
        if c["id"] == cid:
            c["options"] = [dict(o, label=to if o["label"] == frm else o["label"])
                            for o in opts.values()]
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text


def _carry(client, uid, bid, cid, renames, expect=200):
    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(uid), json={"renames": renames})
    assert r.status_code == expect, f"{r.status_code}: {r.text}"
    return r.json()


# ── the cells, in every shape they are written in ─────────────────────────
def test_every_shape_a_status_cell_is_written_in_follows_the_rename(
        client, admin_id, boards):
    """Three shapes, one rename. The bare string and the id-less dict are what
    the grid has been writing for a year; the full option is what a form answer
    and the monday import write. All three mean the same option and all three
    have to end up saying the new word — in the shape the server stores, so
    the NEXT rename matches them by id and never by text."""
    bid, cid, opts = _status_col(client, admin_id, boards)
    o, other = opts[OLD], opts["ממתין"]
    shapes = {
        "a bare label": _item(client, admin_id, bid, "תא מחרוזת"),
        "label and colour": _item(client, admin_id, bid, "תא בלי מזהה"),
        "the whole option": _item(client, admin_id, bid, "תא מלא"),
        "an id under a word nobody uses any more": _item(client, admin_id, bid,
                                                         "תא עם מזהה ומילה ישנה"),
    }
    _write_cell(shapes["a bare label"], cid, OLD)
    _write_cell(shapes["label and colour"], cid, {"label": OLD, "color": o["color"]})
    _write_cell(shapes["the whole option"], cid,
                {"id": o["id"], "label": OLD, "color": o["color"]})
    # By id FIRST and by the old label only then. This cell is what an earlier
    # rename that the cells never followed leaves behind: the right option id
    # under a word that is nobody's label now. Resolved by text it is invisible;
    # resolved by id it is the same option and follows like the rest.
    _write_cell(shapes["an id under a word nobody uses any more"], cid,
                {"id": o["id"], "label": "מילה ישנה אחרת", "color": o["color"]})
    elsewhere = _item(client, admin_id, bid, "תא בסטטוס אחר")
    _write_cell(elsewhere, cid, {"id": other["id"], "label": "ממתין",
                                 "color": other["color"]})
    empty = _item(client, admin_id, bid, "תא ריק")

    _rename_the_column(client, admin_id, bid, cid, opts)
    out = _carry(client, admin_id, bid, cid, [{"from": OLD, "to": NEW}])

    assert out["items"] == 4, out
    assert out["renamed"] == [{"from": OLD, "to": NEW, "id": o["id"], "items": 4}]
    assert out["col_id"] == cid and out["title"] == "סטטוס עבודה"
    assert out["scanned"] >= 6, out

    want = {"id": o["id"], "label": NEW, "color": o["color"]}
    for what, tid in shapes.items():
        assert _cell(tid, cid) == want, f"{what} did not follow the rename"
    # a cell on a different option is not a cell this rename is about
    assert _cell(elsewhere, cid) == {"id": other["id"], "label": "ממתין",
                                     "color": other["color"]}
    assert _cell(empty, cid) is None


def test_a_cell_is_resolved_by_its_option_id_before_its_word(client, admin_id, boards):
    """The one case where the two rules disagree, written down so the order
    cannot be flipped by accident.

    Two options renamed in one sitting, and a cell carrying the SECOND one's id
    under the FIRST one's old word — the sort of thing a form answer or an
    import leaves behind after an earlier rename the cells never followed. By
    id it is the second option and stays there; by text it is the first, and
    the rename quietly moves an item from one status to another. The id is the
    option's stable name; the label is the thing being changed, so it cannot be
    what identifies the option being changed."""
    bid, cid, opts = _status_col(client, admin_id, boards)
    approved, waiting = opts[OLD], opts["ממתין"]
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, {"id": waiting["id"], "label": OLD,
                           "color": waiting["color"]})

    cols = _cols(client, bid, admin_id)
    for c in cols:
        if c["id"] == cid:
            c["options"] = [dict(approved, label=NEW),
                            dict(waiting, label="בהמתנה"), opts["נדחה"]]
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    out = _carry(client, admin_id, bid, cid, [{"from": OLD, "to": NEW},
                                              {"from": "ממתין", "to": "בהמתנה"}])
    assert out["items"] == 1, out
    assert _cell(tid, cid) == {"id": waiting["id"], "label": "בהמתנה",
                               "color": waiting["color"]}, (
        "the cell was resolved by its word and changed status")


def test_a_renamed_cell_still_reads_back_as_the_same_option(client, admin_id, boards):
    """The quiet one. An automation stores the option's id and every rule reads
    a cell through _status_cell_key, so a rewrite that wrote only the new label
    would leave the words right and the rules dead — a board whose automations
    stop firing with nothing anywhere saying why."""
    bid, cid, opts = _status_col(client, admin_id, boards)
    o = opts[OLD]
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, OLD)                      # the shape with no id at all
    _rename_the_column(client, admin_id, bid, cid, opts)
    _carry(client, admin_id, bid, cid, [{"from": OLD, "to": NEW}])

    with Session(cityos_main.engine) as db:
        col = cityos_main._find_col(db, bid, cid)
        key = cityos_main._status_cell_key(col, _cell(tid, cid))
    assert key == o["id"], (
        f"the cell reads back as {key!r} and the option is {o['id']!r} — "
        "every rule written against this status just stopped matching")


def test_a_second_identical_rename_writes_nothing(client, admin_id, boards):
    """Idempotent, because this is called from a save button and a save button
    gets pressed twice. The second call still succeeds — the column offers the
    word, the cells already carry it — and says it touched nothing, which is
    also what the toast on screen reads off."""
    bid, cid, opts = _status_col(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, OLD)
    _rename_the_column(client, admin_id, bid, cid, opts)

    first = _carry(client, admin_id, bid, cid, [{"from": OLD, "to": NEW}])
    assert first["items"] == 1
    before = _cell(tid, cid)
    again = _carry(client, admin_id, bid, cid, [{"from": OLD, "to": NEW}])
    assert again["items"] == 0, again
    assert again["renamed"][0]["items"] == 0
    assert _cell(tid, cid) == before


def test_an_archived_item_and_one_in_the_bin_are_rewritten_too(
        client, admin_id, boards):
    """Both come back. An item unarchived or a board restored from the bin
    after a rename would otherwise return wearing a word the column has not
    offered for months — unreadable on screen and unmatched by every rule, and
    discovered long after anybody remembers the rename."""
    bid, cid, opts = _status_col(client, admin_id, boards)
    o = opts[OLD]
    live = _item(client, admin_id, bid, "פריט חי")
    archived = _item(client, admin_id, bid, "פריט בארכיון")
    binned = _item(client, admin_id, bid, "פריט בסל")
    for tid in (live, archived, binned):
        _write_cell(tid, cid, {"id": o["id"], "label": OLD, "color": o["color"]})

    # Archiving has no REST endpoint of its own — the flag is set by the AI
    # tool path and nowhere else — so the state is made here directly.
    with Session(cityos_main.engine) as db:
        db.query(cityos_main.Task).filter(cityos_main.Task.id == archived)\
          .update({"is_archived": True})
        db.commit()
    assert client.delete(f"/api/tasks/{binned}",
                         headers=AS(admin_id)).status_code == 200

    _rename_the_column(client, admin_id, bid, cid, opts)
    out = _carry(client, admin_id, bid, cid, [{"from": OLD, "to": NEW}])
    assert out["items"] == 3, out

    want = {"id": o["id"], "label": NEW, "color": o["color"]}
    assert _cell(live, cid) == want
    assert _cell(archived, cid) == want, "an archived item kept the old word"
    assert _cell(binned, cid) == want, "an item in the bin kept the old word"
    # …and it is still the same word once it is back on the board
    assert client.post(f"/api/tasks/{binned}/restore",
                       headers=AS(admin_id)).status_code == 200
    assert _cell(binned, cid) == want


# ── the refusal that is the whole point ───────────────────────────────────
def test_an_old_word_that_is_now_another_options_name_is_refused(
        client, admin_id, boards):
    """The case: somebody renames "אושר" to "ממתין" and "ממתין" to "בהמתנה" in
    one sitting — a word moves from one option to another. A cell holding only
    the string "ממתין" is then unresolvable: it might mean the option that just
    left the word behind, or the one that now answers to it, and they are
    different statuses. Guessing moves items between statuses with nothing on
    any screen to say it happened, so the endpoint says no — and says no before
    writing anything, because half a rename leaves a board holding two
    spellings of one option with nothing able to tell them apart."""
    bid, cid, opts = _status_col(client, admin_id, boards)
    waiting, approved = opts["ממתין"], opts[OLD]
    on_waiting = _item(client, admin_id, bid, "פריט ממתין")
    on_approved = _item(client, admin_id, bid, "פריט מאושר")
    _write_cell(on_waiting, cid, "ממתין")            # a label, and only a label
    _write_cell(on_approved, cid, {"id": approved["id"], "label": OLD,
                                   "color": approved["color"]})

    # the column is saved with the words swapped: the approved option is now
    # called "ממתין", which is the word the other option's cells still carry
    cols = _cols(client, bid, admin_id)
    for c in cols:
        if c["id"] == cid:
            c["options"] = [dict(approved, label="ממתין"),
                            dict(waiting, label="בהמתנה"), opts["נדחה"]]
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200

    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(admin_id),
                    json={"renames": [{"from": OLD, "to": "ממתין"},
                                      {"from": "ממתין", "to": "בהמתנה"}]})
    assert r.status_code == 400, f"{r.status_code}: {r.text}"
    assert "ממתין" in r.json()["detail"], r.text
    # nothing moved: both cells are exactly as they were written, including the
    # rename that WAS resolvable — the list is one act
    assert _cell(on_waiting, cid) == "ממתין"
    assert _cell(on_approved, cid) == {"id": approved["id"], "label": OLD,
                                       "color": approved["color"]}


def test_a_refusal_in_a_list_of_renames_takes_the_whole_list_with_it(
        client, admin_id, boards):
    """Checked whole before a single cell is written. A list where one rename
    is impossible is refused entirely rather than applied in part — a board
    holding half a rename is the state this endpoint exists to prevent."""
    bid, cid, opts = _status_col(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, OLD)
    _rename_the_column(client, admin_id, bid, cid, opts)

    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(admin_id),
                    json={"renames": [{"from": OLD, "to": NEW},
                                      {"from": "נדחה", "to": "אין מילה כזאת"}]})
    assert r.status_code == 400, r.text
    assert _cell(tid, cid) == OLD, "the good half of a refused list was written anyway"


# ── the refusals, as status codes ─────────────────────────────────────────
def test_a_rename_with_no_body_is_refused(client, admin_id, boards):
    """422 and not 500: the body is the request."""
    bid, cid, _opts = _status_col(client, admin_id, boards)
    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(admin_id))
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("renames", [
    [],                                        # nothing asked
    [{"from": "", "to": NEW}],                 # no old word
    [{"from": OLD, "to": ""}],                 # no new word
    [{"from": OLD, "to": OLD}],                # the same word on both sides
    ["אושר"],                                  # not even a rename
    [{"from": "  ", "to": "  "}],
])
def test_a_list_with_no_usable_rename_in_it_is_refused(
        client, admin_id, boards, renames):
    """400 rather than a cheerful 200 saying nothing happened. The caller is a
    save button that has just rewritten a column's vocabulary — being told
    "nothing to do" when something plainly was asked for is how a column and
    its cells come apart."""
    bid, cid, _opts = _status_col(client, admin_id, boards)
    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(admin_id), json={"renames": renames})
    assert r.status_code == 400, f"{r.status_code}: {r.text}"


def test_a_word_the_column_does_not_offer_is_refused(client, admin_id, boards):
    """Each rename names its option by the NEW label, resolved against the live
    column — so a label no option carries almost always means the save of the
    column itself did not land. Renaming the cells to it anyway would put the
    board in exactly the state this endpoint exists to prevent."""
    bid, cid, _opts = _status_col(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, OLD)
    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(admin_id),
                    json={"renames": [{"from": OLD, "to": NEW}]})
    assert r.status_code == 400, r.text          # the column was never saved
    assert NEW in r.json()["detail"], r.text
    assert _cell(tid, cid) == OLD


def test_a_column_that_is_not_a_status_column_is_refused(client, admin_id, boards):
    """400 and not 404: the column is there, it is simply not one with a
    vocabulary to rename."""
    bid = _board(client, admin_id, boards, "לוח טקסט")
    cols = _cols(client, bid, admin_id) + [{"type": "text", "title": "הערה"}]
    cid = client.patch(f"/api/boards/{bid}",
                       json={"actor_id": admin_id,
                             "columns": cols}).json()["columns"][-1]["id"]
    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(admin_id), json={"renames": [{"from": "א", "to": "ב"}]})
    assert r.status_code == 400, r.text


def test_an_unknown_board_an_unknown_column_and_a_binned_board_are_not_found(
        client, admin_id, boards):
    """Three 404s, because all three are the same answer: there is nothing here
    to rename. A board in the recycle bin is deliberately among them — it is
    restorable, not editable."""
    bid, cid, _opts = _status_col(client, admin_id, boards)
    body = {"renames": [{"from": OLD, "to": NEW}]}
    assert client.post(f"/api/boards/99999999/columns/{cid}/status-rename",
                       headers=AS(admin_id), json=body).status_code == 404
    assert client.post(f"/api/boards/{bid}/columns/col_nope/status-rename",
                       headers=AS(admin_id), json=body).status_code == 404

    assert client.delete(f"/api/boards/{bid}", headers=AS(admin_id)).status_code == 200
    try:
        r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                        headers=AS(admin_id), json=body)
        assert r.status_code == 404, r.text
    finally:
        client.post(f"/api/trash/boards/{bid}/restore", headers=AS(admin_id))


def test_only_a_board_admin_may_carry_a_rename_into_the_cells(
        client, admin_id, guinea_id, boards):
    """The same gate PATCH /api/boards/{id} puts in front of `columns`.
    Editing the words and carrying them into the cells are one act and must not
    be able to come apart because one half asked for less — an editor who could
    run this could rewrite a status on every item of the board without being
    allowed to change the column at all."""
    bid, cid, opts = _status_col(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, OLD)
    _rename_the_column(client, admin_id, bid, cid, opts)

    join_primary_env(client, guinea_id)
    r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert r.status_code == 200, r.text

    body = {"renames": [{"from": OLD, "to": NEW}]}
    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(guinea_id), json=body)
    assert r.status_code == 403, r.text
    assert _cell(tid, cid) == OLD, "an editor rewrote a status on the whole board"

    # …and the actor is the person signing the request, never a parameter in
    # the body: naming the admin in the body changes nothing
    r = client.post(f"/api/boards/{bid}/columns/{cid}/status-rename",
                    headers=AS(guinea_id),
                    json={"actor_id": admin_id, "renames": [{"from": OLD, "to": NEW}]})
    assert r.status_code == 403, r.text
    assert _cell(tid, cid) == OLD

    # the admin, with the same body, is allowed — so what was refused above is
    # the person and not the request
    assert _carry(client, admin_id, bid, cid, [{"from": OLD, "to": NEW}])["items"] == 1


# ── the browser's half ────────────────────────────────────────────────────
def _fn(name):
    """A top-level function of the SPA, by name."""
    m = SRC.index(f"function {name}(")
    i = SRC.index("{", m)
    depth = 0
    for j in range(i, len(SRC)):
        if SRC[j] == "{":
            depth += 1
        elif SRC[j] == "}":
            depth -= 1
            if not depth:
                return SRC[m:j + 1]
    raise AssertionError("unbalanced " + name)


def test_the_editor_no_longer_refuses_to_rename_on_a_large_board():
    """The cheapest pin that the refusal is gone. The old _csSave asked
    filterMode() and, on a board the server was paging, saved the words and
    told the person in a toast that the items had not followed — because the
    loop it was about to run only reached the fifty rows on screen. One server
    call does the whole board, so neither the question nor the apology has any
    business being there."""
    body = _fn("_csSave")
    assert "filterMode()==='server'" not in body.replace(" ", ""), \
        "the editor still asks how big the board is before renaming"
    assert "בלוח גדול כזה" not in body, "the old refusal toast is still there"
    assert "_csMigrate(" in body, "nothing carries the rename into the cells"


def test_the_rename_is_carried_only_after_the_column_itself_is_saved():
    """Each rename names its option by its NEW label and the server resolves it
    against the live column, so a call that went out first would be refused
    with a 400 every time. The ordering is the contract."""
    body = _fn("_csSave")
    assert "if(!await saveColumns(cols))return;" in body, \
        "the save is no longer the thing the rename waits for"
    assert body.index("saveColumns(cols)") < body.index("_csMigrate("), \
        "the rename goes out before the column that defines it"


def test_the_call_sends_no_colour_and_asks_the_right_endpoint():
    """The server reads the colour off the column's own option, deliberately —
    a colour in the body is one more thing that can disagree with the column."""
    body = _fn("_csMigrate")
    assert "/columns/" in body and "/status-rename" in body
    assert "renames.push({from,to:o.label})" in body.replace(" ", ""), \
        "the body carries something other than from/to"
    assert "color" not in body, "a colour is travelling with the rename"


def test_the_toast_says_what_the_server_says():
    """Two sentences, both the server's: how many items it really rewrote, and
    — when it refuses — its own reason, which is written for the person
    ("הסטטוס X אינו קיים בעמודה", "X הוא כעת שמו של סטטוס אחר"). A generic
    "something went wrong" over either of those would throw away the only
    sentence that says what to do next."""
    save, migrate = _fn("_csSave"), _fn("_csMigrate")
    assert "r.items" in migrate, "the count on screen is not the server's count"
    assert "פריטים עודכנו" in save and "${moved}" in save, \
        "the toast does not say how many items followed"
    assert "(e&&e.detail)" in migrate, "a refusal is shown as something generic"
    # a refusal returns null, and null is NOT 0 — the cheerful line must not be
    # printed over a refusal that has already said why
    assert "moved!==null" in save, "the success toast fires over a refusal too"


def test_the_rows_on_screen_follow_the_rename():
    """Driven harness: the real _csAdoptRenames over rows in every shape.
    One server call comes back with no rows and a 21,000-item board cannot be
    re-fetched, so the grid is brought into line locally — which is only safe
    because the rewrite is a pure relabelling whose result is known exactly."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
