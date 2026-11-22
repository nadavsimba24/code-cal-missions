"""A dropdown column's options can be renamed, put to rest, and deleted — and
deleting one the items still wear is refused.

A dropdown column is `{id, type:'dropdown', title, options:[str]}` and its
cells are LISTS of those strings. Until now the only thing the column editor
could do to an option was drop it, and dropping it left every cell already
holding the word pointing at nothing: the grid drew a chip the column no longer
offered, a filter on it matched nothing, a form could not be answered with it.
That is exactly the disagreement that made dropping a status-in-use a 409, so
the same rule now holds one column type over, and this file is what says so.

What is pinned, and why each one is here:

**`inactive_options` round-trips.** An option somebody wants to stop offering
without rewriting a year of history is marked inactive rather than deleted. The
list lives on the column, is saved by the same PATCH as the column, and keeps
only words the column actually offers — a stale entry naming a word that is
gone would come back to life the moment somebody re-added the word. A column
that is not a dropdown has no business carrying it at all.

**Deleting a used option is a 409, and nothing is written.** The refusal is
the same shape the status gate raises (`message` plus one entry per option,
with the count), so the editor reads one "no" for both. The column is read back
after the refusal to prove it is total. Sub-items count — they are items on the
same board. Archived items do NOT, matching the status rule (_status_usage_rows
reads live items only). Removing the whole column is a different act with its
own warning and its own bin, and is not refused here.

**GET …/dropdown-usage** counts, per word, how many items wear it — what the
editor needs to say "used by 12 items" before anybody presses delete. Reading
is open to any board member; a stranger to the board is refused.

**POST …/dropdown-rename** rewrites the word in the column (in place, so the
order the admin chose survives) and in every cell carrying it — archived items
and the recycle bin included, because both come back, and an item restored
months later must not return wearing a word the column stopped offering. A cell
that already held the new word keeps it once. It is a board-admin act, the same
gate PATCH /api/boards/{id} puts in front of `columns`.

**Forms.** An inactive option is not offered to a respondent and an answer
choosing it is refused — otherwise "stop offering it" would stop at the grid
and a public link would go on writing it into new items.

Everything here is built on boards this file makes and deletes. Nothing is ever
run against a board that was already there.
"""
import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from conftest import join_primary_env

OPTS = ["אדום", "ירוק", "כחול"]
ANON = {"X-CityOS-User": ""}


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


def _col(client, bid, uid, cid):
    return next(c for c in _cols(client, bid, uid) if c["id"] == cid)


def _save_cols(client, bid, admin_id, cols, **extra):
    return client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols, **extra})


def _dropdown_board(client, admin_id, made, name="לוח רשימה", **col_extra):
    """A board with a dropdown column of three options and a text column, and
    both their ids."""
    bid = _board(client, admin_id, made, name)
    cols = _cols(client, bid, admin_id) + [
        {"type": "dropdown", "title": "צבעים", "options": list(OPTS), **col_extra},
        {"type": "text", "title": "הערה"}]
    r = _save_cols(client, bid, admin_id, cols)
    assert r.status_code == 200, r.text
    got = _cols(client, bid, admin_id)
    dd = next(c for c in got if c.get("title") == "צבעים")
    tx = next(c for c in got if c.get("title") == "הערה")
    return bid, dd["id"], tx["id"]


def _item(client, admin_id, bid, title, **extra):
    r = client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                        "title": title, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _write_cell(tid, cid, value):
    """A cell written straight into the row. Archived and binned items have no
    REST door that writes a cell, and the board is the test's own, so nothing
    shared is touched — the status-rename tests reach for the session the same
    way, for the same reason."""
    with Session(cityos_main.engine) as db:
        t = (db.query(cityos_main.Task).filter(cityos_main.Task.id == tid)
             .execution_options(include_deleted=True).first())
        cf = dict(t.custom_fields or {})
        cf[cid] = value
        t.custom_fields = cf
        db.commit()


def _cell(tid, cid):
    with Session(cityos_main.engine) as db:
        t = (db.query(cityos_main.Task).filter(cityos_main.Task.id == tid)
             .execution_options(include_deleted=True).first())
        return (t.custom_fields or {}).get(cid)


def _archive(tid):
    # Archiving has no REST endpoint of its own — see the status-rename tests.
    with Session(cityos_main.engine) as db:
        db.query(cityos_main.Task).filter(cityos_main.Task.id == tid)\
          .update({"is_archived": True})
        db.commit()


def _with_options(cols, cid, options, **extra):
    out = []
    for c in cols:
        c = dict(c)
        if c["id"] == cid:
            c["options"] = list(options)
            c.update(extra)
        out.append(c)
    return out


def _rename(client, uid, bid, cid, body, expect=200):
    r = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown-rename",
                    headers=AS(uid), json=body)
    assert r.status_code == expect, f"{r.status_code}: {r.text}"
    return r.json()


def _usage(client, uid, bid, cid):
    return client.get(f"/api/boards/{bid}/columns/{cid}/dropdown-usage",
                      headers=AS(uid))


# ── 1. inactive_options round-trips ───────────────────────────────────────
def test_inactive_options_are_saved_and_read_back_with_the_column(
        client, admin_id, boards):
    """Putting an option to rest is a property of the column, saved by the same
    PATCH that saves the column — so it is read back the same way."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    cols = _with_options(_cols(client, bid, admin_id), cid, OPTS,
                         inactive_options=["ירוק"])
    r = _save_cols(client, bid, admin_id, cols)
    assert r.status_code == 200, r.text
    col = _col(client, bid, admin_id, cid)
    assert col.get("inactive_options") == ["ירוק"], col
    assert col["options"] == OPTS, "putting an option to rest removed it"


def test_an_inactive_entry_the_column_does_not_offer_is_dropped(
        client, admin_id, boards):
    """A word that is not an option is not something that can be at rest. Kept,
    it would silently re-deactivate the word the day somebody added it back."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    cols = _with_options(_cols(client, bid, admin_id), cid, OPTS,
                         inactive_options=["ירוק", "סגול שלא קיים"])
    assert _save_cols(client, bid, admin_id, cols).status_code == 200
    assert _col(client, bid, admin_id, cid).get("inactive_options") == ["ירוק"]


def test_a_column_that_is_not_a_dropdown_does_not_keep_inactive_options(
        client, admin_id, boards):
    """Only a dropdown has string options to put to rest."""
    bid, _cid, tx = _dropdown_board(client, admin_id, boards)
    cols = [dict(c, inactive_options=["משהו"]) if c["id"] == tx else c
            for c in _cols(client, bid, admin_id)]
    assert _save_cols(client, bid, admin_id, cols).status_code == 200
    assert not _col(client, bid, admin_id, tx).get("inactive_options")


# ── 2. deleting an option the items wear ──────────────────────────────────
def test_deleting_an_option_an_item_wears_is_refused_and_nothing_is_written(
        client, admin_id, boards):
    """The status rule one column type over. The refusal names the option and
    how many items hold it, and the column is read back afterwards to prove the
    refusal wrote nothing."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    a = _item(client, admin_id, bid, "פריט א")
    b = _item(client, admin_id, bid, "פריט ב")
    _write_cell(a, cid, ["ירוק"])
    _write_cell(b, cid, ["אדום", "ירוק"])

    cols = _with_options(_cols(client, bid, admin_id), cid, ["אדום", "כחול"])
    r = _save_cols(client, bid, admin_id, cols)
    assert r.status_code == 409, f"{r.status_code}: {r.text}"
    d = r.json()["detail"]
    assert isinstance(d, dict) and d.get("message"), r.text
    assert d["options"] == [{"col_id": cid, "column": "צבעים",
                             "label": "ירוק", "items": 2}], d
    assert _col(client, bid, admin_id, cid)["options"] == OPTS, \
        "a refused deletion removed the option anyway"


def test_deleting_an_option_nobody_wears_is_allowed(client, admin_id, boards):
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, ["אדום"])
    cols = _with_options(_cols(client, bid, admin_id), cid, ["אדום", "ירוק"])
    r = _save_cols(client, bid, admin_id, cols)
    assert r.status_code == 200, r.text
    assert _col(client, bid, admin_id, cid)["options"] == ["אדום", "ירוק"]


def test_a_sub_item_wearing_the_option_also_blocks_its_deletion(
        client, admin_id, boards):
    """A sub-item is an item of the same board; its cell reads the same column."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    parent = _item(client, admin_id, bid, "הורה")
    sub = _item(client, admin_id, bid, "תת פריט", parent_id=parent)
    _write_cell(sub, cid, ["כחול"])
    cols = _with_options(_cols(client, bid, admin_id), cid, ["אדום", "ירוק"])
    r = _save_cols(client, bid, admin_id, cols)
    assert r.status_code == 409, f"{r.status_code}: {r.text}"
    assert r.json()["detail"]["options"][0]["items"] == 1, r.text
    assert _col(client, bid, admin_id, cid)["options"] == OPTS


def test_an_archived_item_does_not_block_the_deletion(client, admin_id, boards):
    """Matching the status rule: only live items are asked."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט בארכיון")
    _write_cell(tid, cid, ["כחול"])
    _archive(tid)
    cols = _with_options(_cols(client, bid, admin_id), cid, ["אדום", "ירוק"])
    r = _save_cols(client, bid, admin_id, cols)
    assert r.status_code == 200, f"{r.status_code}: {r.text}"


def test_removing_the_whole_column_is_not_refused_by_this_rule(
        client, admin_id, boards):
    """Deleting the column is its own act, with its own warning and its own
    recycle bin. The option gate only asks columns that survive the save."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, ["ירוק"])
    cols = [c for c in _cols(client, bid, admin_id) if c["id"] != cid]
    r = _save_cols(client, bid, admin_id, cols)
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    assert cid not in {c["id"] for c in _cols(client, bid, admin_id)}


# ── 3. dropdown-usage ─────────────────────────────────────────────────────
def test_usage_counts_how_many_items_wear_each_word(
        client, admin_id, member_id, boards):
    """What the editor shows beside each option before anybody presses delete.
    Any board member may read it — an editor sees the board's cells anyway."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    a = _item(client, admin_id, bid, "א")
    b = _item(client, admin_id, bid, "ב")
    _write_cell(a, cid, ["אדום", "ירוק"])
    _write_cell(b, cid, ["ירוק"])

    r = _usage(client, admin_id, bid, cid)
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    out = r.json()
    assert out["col_id"] == cid
    usage = out["usage"]
    assert usage.get("ירוק") == 2 and usage.get("אדום") == 1, out
    assert not usage.get("כחול"), out

    join_primary_env(client, member_id)
    r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                    json={"actor_id": admin_id, "user_id": member_id,
                          "role": "viewer"})
    assert r.status_code == 200, r.text
    r = _usage(client, member_id, bid, cid)
    assert r.status_code == 200, f"a board member could not read usage: {r.text}"
    assert r.json()["usage"].get("ירוק") == 2


def test_usage_is_refused_to_someone_outside_the_board(
        client, admin_id, guinea_id, boards):
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    r = _usage(client, guinea_id, bid, cid)
    assert r.status_code == 403, f"{r.status_code}: {r.text}"


def test_usage_of_an_unknown_column_is_not_found(client, admin_id, boards):
    bid, _cid, _tx = _dropdown_board(client, admin_id, boards)
    r = _usage(client, admin_id, bid, "col_nope")
    assert r.status_code == 404, f"{r.status_code}: {r.text}"


def test_usage_of_a_column_that_is_not_a_dropdown_is_a_bad_request(
        client, admin_id, boards):
    """400 and not 404: the column exists, it simply has no words to count."""
    bid, _cid, tx = _dropdown_board(client, admin_id, boards)
    r = _usage(client, admin_id, bid, tx)
    assert r.status_code == 400, f"{r.status_code}: {r.text}"


# ── 4. dropdown-rename ────────────────────────────────────────────────────
def test_a_rename_rewrites_the_option_in_place_and_every_cell_carrying_it(
        client, admin_id, boards):
    """The whole job in one call: the column's word, in the position the admin
    put it, and every cell — archived and binned ones too, because both come
    back. A cell that already held the new word holds it once, and the item's
    other columns are left alone."""
    bid, cid, tx = _dropdown_board(client, admin_id, boards)
    live = _item(client, admin_id, bid, "חי")
    both = _item(client, admin_id, bid, "כבר יש את החדש")
    archived = _item(client, admin_id, bid, "בארכיון")
    binned = _item(client, admin_id, bid, "בסל")
    other = _item(client, admin_id, bid, "אחר")
    _write_cell(live, cid, ["ירוק", "כחול"])
    _write_cell(live, tx, "ירוק")             # same word, different column
    _write_cell(both, cid, ["ירוק", "ירוק כהה"])
    _write_cell(archived, cid, ["ירוק"])
    _write_cell(binned, cid, ["ירוק"])
    _write_cell(other, cid, ["אדום"])
    _archive(archived)
    assert client.delete(f"/api/tasks/{binned}",
                         headers=AS(admin_id)).status_code == 200

    out = _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק כהה"})
    assert out["col_id"] == cid and out["column"]["title"] == "צבעים", out
    assert out["from"] == "ירוק" and out["to"] == "ירוק כהה", out
    assert out["items"] == 4, out

    assert _col(client, bid, admin_id, cid)["options"] == ["אדום", "ירוק כהה", "כחול"], \
        "the option moved, or was not renamed"
    assert _cell(live, cid) == ["ירוק כהה", "כחול"]
    assert _cell(live, tx) == "ירוק", "a rename reached a different column"
    assert _cell(both, cid) == ["ירוק כהה"], "a cell ended up holding the word twice"
    assert _cell(archived, cid) == ["ירוק כהה"], "an archived item kept the old word"
    assert _cell(binned, cid) == ["ירוק כהה"], "an item in the bin kept the old word"
    assert _cell(other, cid) == ["אדום"]


def test_an_inactive_option_stays_inactive_under_its_new_name(
        client, admin_id, boards):
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    cols = _with_options(_cols(client, bid, admin_id), cid, OPTS,
                         inactive_options=["ירוק"])
    assert _save_cols(client, bid, admin_id, cols).status_code == 200
    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק בהיר"})
    col = _col(client, bid, admin_id, cid)
    assert col.get("inactive_options") == ["ירוק בהיר"], col


def test_only_a_board_admin_may_rename_an_option(
        client, admin_id, guinea_id, boards):
    """The same gate PATCH /api/boards/{id} puts in front of `columns`. And the
    actor is who signs the request: naming the admin in the body changes
    nothing."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, ["ירוק"])
    join_primary_env(client, guinea_id)
    r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert r.status_code == 200, r.text

    _rename(client, guinea_id, bid, cid, {"from": "ירוק", "to": "זית"}, expect=403)
    _rename(client, guinea_id, bid, cid,
            {"actor_id": admin_id, "from": "ירוק", "to": "זית"}, expect=403)
    assert _cell(tid, cid) == ["ירוק"], "an editor rewrote cells on the whole board"
    assert _col(client, bid, admin_id, cid)["options"] == OPTS


def test_a_rename_on_an_unknown_board_or_column_is_not_found(
        client, admin_id, boards):
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    body = {"from": "ירוק", "to": "זית"}
    _rename(client, admin_id, 99999999, cid, body, expect=404)
    _rename(client, admin_id, bid, "col_nope", body, expect=404)


def test_a_rename_on_a_column_that_is_not_a_dropdown_is_a_bad_request(
        client, admin_id, boards):
    bid, _cid, tx = _dropdown_board(client, admin_id, boards)
    _rename(client, admin_id, bid, tx, {"from": "א", "to": "ב"}, expect=400)


def test_renaming_a_word_the_column_does_not_offer_is_refused(
        client, admin_id, boards):
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, ["סגול"])            # a stray word in a cell
    _rename(client, admin_id, bid, cid, {"from": "סגול", "to": "זית"}, expect=400)
    assert _cell(tid, cid) == ["סגול"]
    assert _col(client, bid, admin_id, cid)["options"] == OPTS


@pytest.mark.parametrize("to", ["כחול", "Blue"])
def test_renaming_onto_another_options_word_is_refused(
        client, admin_id, boards, to):
    """Two options with one name cannot be told apart in a cell holding just the
    word — renaming onto an existing option would merge them silently. The
    comparison ignores case, so "blue" and "Blue" are the same word."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    if to == "Blue":
        cols = _with_options(_cols(client, bid, admin_id), cid,
                             ["אדום", "ירוק", "blue"])
        assert _save_cols(client, bid, admin_id, cols).status_code == 200
    tid = _item(client, admin_id, bid, "פריט")
    _write_cell(tid, cid, ["ירוק"])
    before = _col(client, bid, admin_id, cid)["options"]
    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": to}, expect=400)
    assert _cell(tid, cid) == ["ירוק"]
    assert _col(client, bid, admin_id, cid)["options"] == before


@pytest.mark.parametrize("body", [
    {"from": "", "to": "זית"},
    {"from": "ירוק", "to": ""},
    {"from": "  ", "to": "  "},
])
def test_a_rename_with_an_empty_word_is_refused(client, admin_id, boards, body):
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    _rename(client, admin_id, bid, cid, body, expect=400)
    assert _col(client, bid, admin_id, cid)["options"] == OPTS


def test_a_rename_with_no_body_is_refused(client, admin_id, boards):
    """422 and not 500: the body is the request."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    r = client.post(f"/api/boards/{bid}/columns/{cid}/dropdown-rename",
                    headers=AS(admin_id))
    assert r.status_code == 422, f"{r.status_code}: {r.text}"


# ── 5. forms ──────────────────────────────────────────────────────────────
def _form_on(client, admin_id, bid, cid):
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id))
    assert f.status_code == 200, f.text
    fid = f.json()["id"]
    q = {}
    for label, key in (("נושא", "title"), ("צבע", cid)):
        r = client.post(f"/api/forms/{fid}/components", headers=AS(admin_id),
                        json={"kind": "question", "field_key": key, "label": label})
        assert r.status_code == 200, (label, r.text)
        q[label] = r.json()["id"]
    client.patch(f"/api/forms/{fid}", json={"access": "PUBLIC_LINK"},
                 headers=AS(admin_id))
    r = client.patch(f"/api/forms/{fid}", json={"status": "PUBLISHED"},
                     headers=AS(admin_id))
    assert r.status_code == 200, r.text
    tok = client.get(f"/api/forms/{fid}", headers=AS(admin_id)).json()["public_token"]
    return fid, q, tok


def test_a_form_does_not_offer_an_inactive_option_nor_accept_it(
        client, admin_id, boards):
    """Putting an option to rest has to reach the public link too, or a form
    goes on writing a word the board stopped offering into every new item."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    fid, q, tok = _form_on(client, admin_id, bid, cid)
    cols = _with_options(_cols(client, bid, admin_id), cid, OPTS,
                         inactive_options=["ירוק"])
    assert _save_cols(client, bid, admin_id, cols).status_code == 200

    pub = client.get(f"/api/public/forms/{tok}", headers=ANON)
    assert pub.status_code == 200, pub.text
    qq = next(c for c in pub.json()["components"] if c.get("label") == "צבע")
    offered = [o["value"] for o in (qq.get("options") or [])]
    assert offered == ["אדום", "כחול"], f"the form offers {offered}"

    # the owner's preview is the same projection
    prev = client.get(f"/api/forms/{fid}/preview", headers=AS(admin_id)).json()
    pq = next(c for c in prev["components"] if c.get("label") == "צבע")
    assert [o["value"] for o in pq.get("options") or []] == ["אדום", "כחול"]

    # an old page that still offers it cannot write through it
    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["נושא"]): "עם צבע מושבת",
                                      str(q["צבע"]): ["ירוק"]}})
    assert r.status_code == 400, f"{r.status_code}: {r.text}"
    titles = [t["title"] for t in client.get(f"/api/boards/{bid}",
                                             headers=AS(admin_id)).json()["tasks"]]
    assert "עם צבע מושבת" not in titles, "a refused answer still made an item"

    # an active option still goes through
    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(q["נושא"]): "עם צבע פעיל",
                                      str(q["צבע"]): ["כחול"]}})
    assert r.status_code == 200, r.text


# ── 6. a rename reaches the rules and the views that remember the word ────
# A rule "רק אם «צבעים» היא «ירוק»" and a saved tab filtering on «ירוק» both
# name the option by its word. Renamed in the column and the cells only, the
# rule would go quietly false for ever and the tab quietly empty — nothing on
# screen would say why. So the rename carries the word into both. And because
# the SAME word may well be an option of another dropdown on the board, or of a
# column on another board that happens to share the id, the rewrite is pinned
# to this column of this board and nothing else.
#
# Rules and views are made through the API where it has a door (it does for
# both); they are read back through the session because the version history
# and `config_version` are what is being asserted, and those are row facts.
from models import Automation, AutomationVersion, SavedView  # noqa: E402


def _cond(cid, value, kind="column_is"):
    return {"kind": kind, "value": {"col": cid, "type": "dropdown", "value": value}}


def _rule(client, admin_id, bid, conds, **cfg):
    config = {"a_priority": "high", **cfg, "conditions": conds}
    r = client.post(f"/api/boards/{bid}/automations", headers=AS(admin_id),
                    json={"recipe_id": "created_set_priority", "config": config})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _add_list_cond(aid, cid, words, kind="column_is"):
    """A condition holding a LIST of words, written into the rule's live config.

    The automation API takes one word per condition (it stores the value as a
    scalar), but the rename's helper explicitly carries a list too — a rule
    imported or saved before that rule held one — so the list form is put in
    place through the session, on this test's own board."""
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == aid).one()
        cfg = dict(a.config or {})
        cfg["conditions"] = list(cfg.get("conditions") or []) + [
            {"kind": kind, "value": {"col": cid, "type": "dropdown",
                                     "op": "eq", "value": list(words)}}]
        a.config = cfg
        db.commit()


def _rule_row(aid):
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == aid).one()
        return dict(a.config or {}), a.draft_version


def _versions(aid):
    with Session(cityos_main.engine) as db:
        return [(v.version, v.summary, v.snapshot)
                for v in db.query(AutomationVersion)
                           .filter(AutomationVersion.automation_id == aid)
                           .order_by(AutomationVersion.version).all()]


def _conds_of(cfg):
    return [(c["kind"], c["value"]["col"], c["value"]["value"])
            for c in cfg.get("conditions") or []]


def _view(client, admin_id, bid, name, adv):
    r = client.post(f"/api/boards/{bid}/views", headers=AS(admin_id),
                    json={"name": name, "filters": {"view": "table", "adv": adv}})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _view_row(vid):
    with Session(cityos_main.engine) as db:
        v = db.query(SavedView).filter(SavedView.id == vid).one()
        return dict(v.filters or {}), (v.config_version or 1)


def _ast(*rules):
    """The wire shape filter_ast.parse normalises to."""
    return {"type": "group", "operator": "and", "rules": list(rules)}


def _ast_rule(cid, value, op="eq"):
    return {"type": "rule", "field": cid, "operator": op,
            "value": value, "value2": None}


def _second_dropdown(client, admin_id, bid, title="צבעים נוספים"):
    """Another dropdown on the same board, offering the SAME words."""
    cols = _cols(client, bid, admin_id) + [
        {"type": "dropdown", "title": title, "options": list(OPTS)}]
    assert _save_cols(client, bid, admin_id, cols).status_code == 200
    return next(c for c in _cols(client, bid, admin_id) if c.get("title") == title)["id"]


def test_a_rules_condition_on_the_column_asks_for_the_new_word(
        client, admin_id, boards):
    """Both forms a condition holds the word in — a single word, and a list of
    them — come out naming the new word, and the rest of the rule is untouched.
    A version is recorded, so "who changed this rule" still has an answer."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    aid = _rule(client, admin_id, bid, [_cond(cid, "ירוק")])
    _add_list_cond(aid, cid, ["ירוק", "כחול"], kind="column_is_not")
    before = _versions(aid)

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק כהה"})

    cfg, _draft = _rule_row(aid)
    assert _conds_of(cfg) == [
        ("column_is", cid, "ירוק כהה"),
        ("column_is_not", cid, ["ירוק כהה", "כחול"])], cfg
    assert cfg.get("a_priority") == "high", "the rename touched the rule's action"
    after = _versions(aid)
    assert len(after) == len(before) + 1, \
        f"no version was recorded for the rewrite: {after}"
    _n, summary, snap = after[-1]
    assert "ירוק" in summary and "ירוק כהה" in summary, summary
    assert _conds_of(snap.get("config") or {})[0] == ("column_is", cid, "ירוק כהה"), snap


def test_a_pending_draft_of_the_rule_is_carried_too(client, admin_id, boards):
    """An edit to an active rule waits as a draft. Left holding the old word,
    publishing it later would bring back a condition no cell can meet. Here
    only the DRAFT mentions the word, so the draft is carried on its own."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    aid = _rule(client, admin_id, bid, [_cond(cid, "אדום")])
    r = client.patch(f"/api/automations/{aid}", headers=AS(admin_id),
                     json={"config": {"a_priority": "high", "conditions": [
                         _cond(cid, "אדום"), _cond(cid, "ירוק")]}})
    assert r.status_code == 200, r.text
    live, draft_v = _rule_row(aid)
    assert draft_v, "the edit did not become a draft — the test has no draft to check"
    assert _conds_of(live) == [("column_is", cid, "אדום")], live

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "זית"})

    live_after, draft_after = _rule_row(aid)
    assert draft_after == draft_v, "the rename published or dropped the draft"
    assert _conds_of(live_after) == [("column_is", cid, "אדום")], live_after
    snap = next(s for n, _s, s in _versions(aid) if n == draft_v)
    assert _conds_of(snap.get("config") or {}) == [
        ("column_is", cid, "אדום"), ("column_is", cid, "זית")], \
        f"the draft still asks for the old word: {snap}"


def test_a_saved_views_filter_on_the_word_is_rewritten_and_its_version_moves_once(
        client, admin_id, boards):
    """The shared configuration of the tab moved, so `config_version` goes up —
    by exactly one, a client holding the old version must see one change. A
    rule nested in a sub-group is reached, a binned view is carried (it comes
    back), and a view that never mentioned the word keeps its version."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    hit = _view(client, admin_id, bid, "ירוקים", _ast(
        _ast_rule(cid, "ירוק"),
        {"type": "group", "operator": "or",
         "rules": [_ast_rule(cid, ["ירוק", "כחול"]), _ast_rule("status", "done")]}))
    quiet = _view(client, admin_id, bid, "אדומים", _ast(_ast_rule(cid, "אדום")))
    binned = _view(client, admin_id, bid, "בסל", _ast(_ast_rule(cid, ["ירוק"])))
    assert client.delete(f"/api/views/{binned}", headers=AS(admin_id)).status_code == 200
    _f, v_hit = _view_row(hit)
    _f, v_quiet = _view_row(quiet)
    _f, v_binned = _view_row(binned)

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק כהה"})

    f, v = _view_row(hit)
    rules = f["adv"]["rules"]
    assert rules[0]["value"] == "ירוק כהה", f
    assert rules[1]["rules"][0]["value"] == ["ירוק כהה", "כחול"], f
    assert rules[1]["rules"][1]["value"] == "done", "a rule on another field moved"
    assert f.get("view") == "table", "the rest of the cut was lost"
    assert v == v_hit + 1, f"config_version went {v_hit} → {v}, not up by one"

    f, v = _view_row(quiet)
    assert f["adv"]["rules"][0]["value"] == "אדום"
    assert v == v_quiet, "a view that never named the word was bumped"

    f, v = _view_row(binned)
    assert f["adv"]["rules"][0]["value"] == ["ירוק כהה"], \
        f"a view in the bin kept the old word: {f}"
    assert v == v_binned + 1


def test_a_view_saved_in_the_browsers_own_shape_is_rewritten_too(
        client, admin_id, boards):
    """The board's filter panel holds its rules as {field, op, v} (index.html,
    the filter panel's newRule) and Views.current() saves `st.filters.adv` exactly as
    held — filter_ast.parse accepts that shape on purpose ("the browser's own
    in-memory shape omits it", and reads `v` when `value` is absent). A view
    made from the real tab strip therefore names the word under `v`, and a
    rename that only looks under `value` leaves it asking for a word no cell
    holds any more."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    vid = _view(client, admin_id, bid, "מהדפדפן", {
        "op": "and", "rules": [{"field": cid, "op": "eq", "v": "ירוק", "v2": ""}]})
    _f, before = _view_row(vid)

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק כהה"})

    f, v = _view_row(vid)
    rule = f["adv"]["rules"][0]
    assert rule.get("value", rule.get("v")) == "ירוק כהה", \
        f"a view saved by the browser still filters on the old word: {f}"
    assert v == before + 1, f"config_version went {before} → {v}"


def test_a_rename_leaves_the_same_word_on_another_column_or_board_alone(
        client, admin_id, boards):
    """The same word, in a condition and a view, on (a) another dropdown of the
    same board and (b) a column of ANOTHER board that carries the same column
    id. Neither was renamed, and neither may move — nor may its version."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    other_cid = _second_dropdown(client, admin_id, bid)
    mine = _rule(client, admin_id, bid, [_cond(cid, "ירוק")])
    sibling = _rule(client, admin_id, bid, [_cond(other_cid, "ירוק")])
    _add_list_cond(sibling, other_cid, ["ירוק"])
    sib_view = _view(client, admin_id, bid, "עמודה אחרת",
                     _ast(_ast_rule(other_cid, "ירוק")))

    far = _board(client, admin_id, boards, "לוח אחר")
    cols = _cols(client, far, admin_id) + [
        {"id": cid, "type": "dropdown", "title": "צבעים", "options": list(OPTS)}]
    assert _save_cols(client, far, admin_id, cols).status_code == 200
    assert any(c["id"] == cid for c in _cols(client, far, admin_id)), \
        "the other board did not keep the column id — the test cannot pin this"
    far_rule = _rule(client, admin_id, far, [_cond(cid, "ירוק")])
    far_view = _view(client, admin_id, far, "בלוח האחר", _ast(_ast_rule(cid, ["ירוק"])))

    sib_versions = len(_versions(sibling))
    far_versions = len(_versions(far_rule))
    _f, sib_v = _view_row(sib_view)
    _f, far_v = _view_row(far_view)

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק כהה"})

    # the one that should move did — otherwise "left alone" proves nothing
    assert _conds_of(_rule_row(mine)[0]) == [("column_is", cid, "ירוק כהה")]

    assert _conds_of(_rule_row(sibling)[0]) == [
        ("column_is", other_cid, "ירוק"), ("column_is", other_cid, ["ירוק"])], \
        "a condition on another column of the board was rewritten"
    assert len(_versions(sibling)) == sib_versions
    f, v = _view_row(sib_view)
    assert f["adv"]["rules"][0]["value"] == "ירוק" and v == sib_v, \
        f"a view on another column of the board moved: {f} v{v}"

    assert _conds_of(_rule_row(far_rule)[0]) == [("column_is", cid, "ירוק")], \
        "a rule on another board was rewritten"
    assert len(_versions(far_rule)) == far_versions
    f, v = _view_row(far_view)
    assert f["adv"]["rules"][0]["value"] == ["ירוק"] and v == far_v, \
        f"a view on another board moved: {f} v{v}"
    assert _col(client, far, admin_id, cid)["options"] == OPTS


# ── 7. a rename reaches the rules that WRITE the word ─────────────────────
# set_column will write into a dropdown, and it writes a word the column must
# offer — _coerce_cell refuses anything else. A rule "כאשר נוצר פריט, עדכן את
# «צבעים» ל«ירוק»" left holding the old word after a rename is refused on every
# firing from then on: the rule goes quietly dead, which is exactly what the
# conditions half of the rename exists to prevent. Both places a set_column
# lives are pinned — the rule's own action (a_column/a_text) and an added one
# ({"key": "set_column", "values": {column, text}}) — live and in a draft.
# Only a value that IS the word moves; a sentence that contains it is not a
# reference to the option.
def _set_rule(client, admin_id, bid, cid, text, recipe_id="created_set_column", **cfg):
    r = client.post(f"/api/boards/{bid}/automations", headers=AS(admin_id),
                    json={"recipe_id": recipe_id,
                          "config": {"a_column": cid, "a_text": text, **cfg}})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _extra_set(cid, text):
    return {"key": "set_column", "values": {"column": cid, "text": text}}


def _prio_rule_with_extra(client, admin_id, bid, extras):
    r = client.post(f"/api/boards/{bid}/automations", headers=AS(admin_id),
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "high", "actions": extras}})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _extras_of(cfg):
    return [(x["values"].get("column"), x["values"].get("text"))
            for x in cfg.get("actions") or [] if x.get("key") == "set_column"]


def test_a_set_column_rules_own_action_writes_the_new_word(
        client, admin_id, boards):
    """The rule's own action, for each recipe that keeps it — and a version is
    recorded for it, as for a condition."""
    bid, cid, tx = _dropdown_board(client, admin_id, boards)
    made = _set_rule(client, admin_id, bid, cid, "ירוק")
    on_status = _set_rule(client, admin_id, bid, cid, " ירוק ",
                          recipe_id="status_set_column", t_status="done")
    on_column = _set_rule(client, admin_id, bid, cid, "ירוק",
                          recipe_id="column_changed_set_column", t_column=tx)
    before = {a: len(_versions(a)) for a in (made, on_status, on_column)}

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק כהה"})

    for aid in (made, on_status, on_column):
        cfg, _d = _rule_row(aid)
        assert cfg.get("a_text") == "ירוק כהה", f"rule {aid} still writes {cfg}"
        assert cfg.get("a_column") == cid, cfg
        assert len(_versions(aid)) == before[aid] + 1, \
            f"no version was recorded for rule {aid}"
    assert _rule_row(on_status)[0].get("t_status") == "done"
    assert _rule_row(on_column)[0].get("t_column") == tx


def test_an_added_set_column_action_writes_the_new_word(client, admin_id, boards):
    """An extra action on a rule whose own action is something else."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    aid = _prio_rule_with_extra(client, admin_id, bid, [_extra_set(cid, "ירוק")])
    assert _extras_of(_rule_row(aid)[0]) == [(cid, "ירוק")], \
        "the added action was not stored — the test has nothing to check"

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "זית"})

    cfg, _d = _rule_row(aid)
    assert _extras_of(cfg) == [(cid, "זית")], cfg
    assert cfg.get("a_priority") == "high"


def test_a_pending_drafts_set_column_actions_are_carried_too(
        client, admin_id, boards):
    """The live rules write other words; only their DRAFTS write the renamed
    one — one in the rule's own action, one in an added action (two rules,
    because an added action identical to the rule's own is dropped as a
    duplicate). Publishing either later must not bring the old word back."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    own = _set_rule(client, admin_id, bid, cid, "אדום")
    extra = _prio_rule_with_extra(client, admin_id, bid, [_extra_set(cid, "כחול")])
    r = client.patch(f"/api/automations/{own}", headers=AS(admin_id),
                     json={"config": {"a_column": cid, "a_text": "ירוק"}})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/automations/{extra}", headers=AS(admin_id),
                     json={"config": {"a_priority": "high",
                                      "actions": [_extra_set(cid, "ירוק ")]}})
    assert r.status_code == 200, r.text
    drafts = {}
    for aid in (own, extra):
        _live, dv = _rule_row(aid)
        assert dv, f"rule {aid}: the edit did not become a draft — nothing to check"
        drafts[aid] = dv

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "זית"})

    live_own, dv_own = _rule_row(own)
    live_extra, dv_extra = _rule_row(extra)
    assert (dv_own, dv_extra) == (drafts[own], drafts[extra]), \
        "the rename published or dropped a draft"
    assert live_own.get("a_text") == "אדום", "a live action on another word moved"
    assert _extras_of(live_extra) == [(cid, "כחול")], live_extra

    snap = next(s for n, _s, s in _versions(own) if n == drafts[own])
    assert (snap.get("config") or {}).get("a_text") == "זית", \
        f"the draft's own action kept the old word: {snap}"
    snap = next(s for n, _s, s in _versions(extra) if n == drafts[extra])
    assert _extras_of(snap.get("config") or {}) == [(cid, "זית")], \
        f"the draft's added action kept the old word: {snap}"


def test_a_set_column_on_another_column_or_inside_a_sentence_is_left_alone(
        client, admin_id, boards):
    """Another dropdown offering the same word was not renamed; and a text that
    merely CONTAINS the word is not the option — rewriting it would change a
    sentence somebody wrote."""
    bid, cid, tx = _dropdown_board(client, admin_id, boards)
    other_cid = _second_dropdown(client, admin_id, bid)
    sibling = _set_rule(client, admin_id, bid, other_cid, "ירוק")
    sib_extra = _prio_rule_with_extra(client, admin_id, bid,
                                      [_extra_set(other_cid, "ירוק")])
    sentence = _set_rule(client, admin_id, bid, tx, "ירוק זה הצבע",
                         recipe_id="status_set_column", t_status="done")
    mine = _set_rule(client, admin_id, bid, cid, "ירוק")
    counts = {a: len(_versions(a)) for a in (sibling, sib_extra, sentence)}

    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק כהה"})

    assert _rule_row(mine)[0].get("a_text") == "ירוק כהה", \
        "the rule that should move did not — 'left alone' would prove nothing"
    assert _rule_row(sibling)[0].get("a_text") == "ירוק", \
        "a rule writing another column was rewritten"
    assert _extras_of(_rule_row(sib_extra)[0]) == [(other_cid, "ירוק")], \
        "an added action writing another column was rewritten"
    assert _rule_row(sentence)[0].get("a_text") == "ירוק זה הצבע"
    for aid, n in counts.items():
        assert len(_versions(aid)) == n, f"rule {aid} got a version for nothing"


def test_a_sentence_containing_the_word_on_this_column_is_left_alone(
        client, admin_id, boards):
    """Same column this time: only a value stripped-equal to the word is it."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    aid = _prio_rule_with_extra(client, admin_id, bid,
                                [_extra_set(cid, "ירוק או כחול")])
    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "זית"})
    assert _extras_of(_rule_row(aid)[0]) == [(cid, "ירוק או כחול")]


def test_after_a_rename_the_rule_writes_the_new_word_into_a_new_item(
        client, admin_id, boards):
    """End to end: the rule fires synchronously on create (as in
    tests/test_automation_recurring_and_columns.py), so the cell of an item made
    after the rename says what the rule now says."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    _set_rule(client, admin_id, bid, cid, "ירוק")
    _rename(client, admin_id, bid, cid, {"from": "ירוק", "to": "ירוק כהה"})
    tid = _item(client, admin_id, bid, "אחרי השינוי")
    got = _cell(tid, cid)
    assert got in ("ירוק כהה", ["ירוק כהה"]), \
        f"the rule did not write the renamed word: {got!r}"


# ── 8. usage of a column hidden from the reader ───────────────────────────
def test_usage_of_a_column_hidden_from_the_reader_is_not_found(
        client, admin_id, guinea_id, boards):
    """A column this reader's override hides is one the grid, filter and export
    never show them. Its words and counts are its content, so the answer is the
    404 of a column that does not exist — a 403 would say it is there."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    join_primary_env(client, guinea_id)
    r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    assert r.status_code == 200, r.text
    assert _usage(client, guinea_id, bid, cid).status_code == 200, \
        "a member could not read usage before the override — nothing to compare"
    r = client.post(f"/api/boards/{bid}/columns/{cid}/permissions",
                    headers=AS(admin_id), json={"user_id": guinea_id, "perm": "none"})
    assert r.status_code == 200, r.text
    r = _usage(client, guinea_id, bid, cid)
    assert r.status_code == 404, f"{r.status_code}: {r.text}"
    assert "ירוק" not in r.text, r.text
    # the admin still reads it
    assert _usage(client, admin_id, bid, cid).status_code == 200


# ── 9. a number can be put to rest ────────────────────────────────────────
@pytest.mark.parametrize("sent", [3, "3"])
def test_a_numeric_option_can_be_made_inactive_and_keeps_its_stored_form(
        client, admin_id, boards, sent):
    """An imported column can hold 3, not "3", as an option, and the browser
    sends back whatever it rendered. Either spelling names the option, and what
    is kept is the option itself — so a comparison against `options` matches."""
    bid, cid, _tx = _dropdown_board(client, admin_id, boards)
    cols = _with_options(_cols(client, bid, admin_id), cid, ["a", 3],
                         inactive_options=[sent])
    r = _save_cols(client, bid, admin_id, cols)
    assert r.status_code == 200, r.text
    col = _col(client, bid, admin_id, cid)
    assert col["options"] == ["a", 3], f"the number option changed form: {col}"
    assert col.get("inactive_options") == [3], \
        f"sent {sent!r}, stored {col.get('inactive_options')!r}"
