"""ה-× על הקישור האחרון בתא — הביטול שלא בוטל.

The × on a link chip wrote the removal, the server obeyed it, and the chip
stayed on screen. Two separate halves of the same mistake, and each of them
only bites on the LAST link in a cell — which, for most cells, is the only one
there ever is.

The browser's half is in the answer, not in the request. A PATCH replies with
the item's whole custom_fields, so a column the server no longer holds is
simply absent from it; the cell merged that answer over itself with
Object.assign, which can add a key and overwrite a key and can never remove
one. The array that had just been emptied went straight back, and the redraw
put the chip back with it. Removing one of several always worked, because then
the answer carried the shorter list. A two-way column hid it again by taking
the whole board fresh — and a new "קישור בין לוחות" column is one-way unless
somebody ticks the box, so one-way is what almost every board has.

The server's half is that emptying a cell is said with a null, and a null
never reached the block that handles a connect column. So the rule written as
"כאשר מוסר קישור" did not hear the one removal that empties a cell, and the
links in it that the actor cannot see — which a submitted list is careful to
keep, because a cell rendered without them must not read as "delete the rest"
— were dropped along with the visible ones.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _cell(client, tid, col_id, uid):
    t = client.get(f"/api/tasks/{tid}", headers=AS(uid)).json()
    return (t.get("custom_fields") or {}).get(col_id) or []


def _setup(client, admin_id, tag, two_way=False, multiple=True, targets=None):
    a = _board(client, admin_id, f"מקור {tag}")
    bs = targets if targets is not None else [_board(client, admin_id, f"יעד {tag}")]
    cols = _cols(client, a) + [{"type": "connect", "title": "קישור",
                                "connect": {"board_ids": bs, "multiple": multiple,
                                            "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return a, bs, next(c for c in _cols(client, a) if c["type"] == "connect")


def _clear(client, tid, col_id, uid):
    """What the × sends when it takes the last link off: a null, not a [].

    Every cleared cell in the grid is said this way — it is setCell's own
    spelling — so the connect column has to mean by it what the rest of the
    table means by it.
    """
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: None}}, headers=AS(uid))


# ── the cell actually empties ───────────────────────────────────────────────

def test_a_null_empties_a_one_way_cell(client, admin_id):
    a, (b,), c = _setup(client, admin_id, "x1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                 json={"custom_fields": {c["id"]: [x]}})
    assert _cell(client, src, c["id"], admin_id) == [x]
    assert _clear(client, src, c["id"], admin_id).status_code == 200
    assert _cell(client, src, c["id"], admin_id) == []


def test_a_null_empties_a_single_link_cell(client, admin_id):
    """A column holding one item is the shape the × is most often used on."""
    a, (b,), c = _setup(client, admin_id, "x2", multiple=False)
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                 json={"custom_fields": {c["id"]: [x]}})
    assert _cell(client, src, c["id"], admin_id) == [x]
    _clear(client, src, c["id"], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []


def test_a_null_empties_a_two_way_cell_on_both_sides(client, admin_id):
    """The two-way path never had the bug — it is pinned so it keeps not
    having it, because the fix moved the code both paths lead into."""
    a, (b,), c = _setup(client, admin_id, "x3", two_way=True)
    mirror = c["connect"]["mirror"][str(b)]
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                 json={"custom_fields": {c["id"]: [x]}})
    _clear(client, src, c["id"], admin_id)
    assert _cell(client, src, c["id"], admin_id) == []
    assert _cell(client, x, mirror, admin_id) == []


# ── the rule hears it ───────────────────────────────────────────────────────

def test_clearing_the_last_link_fires_the_removal_rule(client, admin_id):
    """"כאשר מוסר קישור" heard a replacement and heard an emptied list, and
    did not hear the × — which is the way a link is most often removed."""
    a, (b,), c = _setup(client, admin_id, "r1")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                 json={"custom_fields": {c["id"]: [x]}})
    client.post(f"/api/boards/{a}/automations",
                json={"actor_id": admin_id, "recipe_id": "link_removed_set_status",
                      "config": {"a_status": "done"}})
    _clear(client, src, c["id"], admin_id)
    assert client.get(f"/api/tasks/{src}", headers=AS(admin_id)).json()["status"] == "done"


def test_the_removal_rule_is_told_which_link_went(client, admin_id):
    """The event carries the ids, not just the fact — an action that names the
    removed item has nothing to work from otherwise."""
    a, (b,), c = _setup(client, admin_id, "r2")
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                 json={"custom_fields": {c["id"]: [x]}})
    r = _clear(client, src, c["id"], admin_id).json()
    assert r["event_ids"], "clearing the cell raised no event at all"


# ── a link you cannot see is not yours to delete ────────────────────────────

def test_clearing_a_cell_keeps_the_links_it_never_showed_you(client, admin_id, guinea_id):
    """The same rule a submitted list already obeys. A cell is rendered without
    the items its reader may not open, so "take everything out of it" can only
    mean the part they were shown — otherwise the × quietly severs somebody
    else's relationship, and the cell they were looking at never mentioned it.
    """
    seen = _board(client, admin_id, "יעד גלוי p1")
    unseen = _board(client, admin_id, "יעד חסוי p1")
    a, _bs, c = _setup(client, admin_id, "p1", targets=[seen, unseen])
    for bid in (a, seen):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    src = _item(client, a, admin_id, "מקור")
    vis, hid = _item(client, seen, admin_id, "גלוי"), _item(client, unseen, admin_id, "חסוי")
    client.patch(f"/api/tasks/{src}?user_id={admin_id}",
                 json={"custom_fields": {c["id"]: [vis, hid]}})
    assert _cell(client, src, c["id"], guinea_id) == [vis], "the hidden id leaked"

    _clear(client, src, c["id"], guinea_id)
    assert _cell(client, src, c["id"], guinea_id) == []
    assert _cell(client, src, c["id"], admin_id) == [hid], \
        "clearing the cell deleted a link its clearer was never shown"


# ── the browser's half ──────────────────────────────────────────────────────

def test_both_link_write_paths_reconcile_the_answer(client):
    """The × and the picker's שמור are the two places a link cell is written,
    and they were both merging the answer with Object.assign — which cannot
    remove the key the server dropped."""
    src = INDEX.read_text(encoding="utf-8")
    assert "function applyCellResponse(" in src
    body = src[src.index("async function unlinkFromCell("):]
    body = body[: body.index("\nfunction fitLinkChips")]
    assert "applyCellResponse(t,res,[colId])" in body, body
    save = src[src.index("async function connectSave("):]
    save = save[: save.index("\n/* Somebody else got there first")]
    assert "applyCellResponse(t,res,[colId])" in save, save
    assert "Object.assign({},t.custom_fields,res" not in src, \
        "a link cell is still merging an answer it cannot remove a column with"


def test_the_x_empties_the_cell_on_screen(client):
    """Driven harness: tests/frontend/the_x_on_a_link_chip_empties_the_cell.mjs.

    Verified to fail: put the Object.assign merge back in unlinkFromCell and
    two cases go red — the cell keeps the id, and connectDisp draws the chip
    again instead of going back to "קשר פריט".
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "the_x_on_a_link_chip_empties_the_cell.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
