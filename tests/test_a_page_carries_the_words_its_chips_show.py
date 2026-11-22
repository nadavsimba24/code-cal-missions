"""A connect column told to show a FIELD goes on showing it when the board pages.

`link_display` is the override map — `{col_id: {item_id: text}}` — that a
connect column needs when it was configured to show a field of the linked
record instead of the record's title. Without an entry for a record the browser
falls back to what /api/tasks/lookup gives it, which is the title.

That fallback is why this file exists. Past FILTER_CLIENT_MAX the board payload
answers with `tasks: []`, so `_board_link_display` runs over an empty list and
correctly returns `{}` — and until today POST /api/boards/{id}/items/query sent
no map at all. Every connect column on every large board therefore showed
titles where it had been told to show "שם לקוח מלא" or a status: the wrong
words, in the right place, with no error, no blank cell and nothing on screen
to say anything had gone wrong. A person reading that board has no way to know
they are looking at the wrong text, which makes it the worst class of bug this
change could have left behind — so the pin is not "the key is present", it is
"the words are the same words the small board shows".

Three rules are pinned here.

**The pages, merged, say exactly what the whole board says.** The same board is
read twice — once below the threshold where every row travels, once above it
where the rows arrive fifty at a time — and the two maps are compared to each
other rather than to a literal this file made up. And the text is asserted to
be the display FIELD and not the record's title, because the bug being caught
is precisely "it quietly showed titles": a test that accepted titles would pass
on the broken server.

**The map is still per reader.** `_link_display_text` re-asks `_col_perm` on
the FAR board for the person actually reading, and falls back to the title when
they may not see the column there. The admin who chose the display field is not
who is reading the page. Two readers ask for the same page here and get
different text.

**The two id-shaped answers carry none of it.** `ids_only` and `only=[ids]` are
answers about which rows survive a filter, asked by a browser that already
holds the rows; a display map in them would be payload nobody reads, built per
request, on the one path that exists to be cheap.

The browser half — merging each page's map into the one the board arrived with,
per column and never by replacing the outer object — is in
tests/frontend/a_page_folds_its_link_display_into_the_board.mjs, driven at the
bottom of this file.
"""
import pathlib
import shutil
import subprocess

import pytest

import main as cityos_main
from conftest import join_primary_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "a_page_folds_its_link_display_into_the_board.mjs"


def AS(uid):
    return {"X-CityOS-User": str(uid)}


@pytest.fixture
def boards(client, admin_id):
    """Boards a test makes, taken away again when it ends — the suite runs
    repeatedly against one seeded temp DB, so a board left behind is left
    behind for every later run of the same process."""
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


def _board_json(client, bid, uid):
    r = client.get(f"/api/boards/{bid}", headers=AS(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _add_col(client, admin_id, bid, col):
    cols = _board_json(client, bid, admin_id)["columns"] + [col]
    r = client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    return r.json()["columns"][-1]["id"]


def _item(client, admin_id, bid, title, **extra):
    r = client.post("/api/tasks", json={"actor_id": admin_id, "board_id": bid,
                                        "title": title, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _linked_pair(client, admin_id, made, rows=6, records=4):
    """A board whose connect column shows a field of the records on another.

    The display text deliberately contains the record's title and is not equal
    to it — "בית דגן" vs "בית דגן · מועצה מקומית" — so a server that fell back
    to titles produces a map that is missing entries rather than one that
    happens to match.
    """
    target = _board(client, admin_id, made, "יעד תצוגה")
    disp = _add_col(client, admin_id, target, {"type": "text", "title": "שם מלא"})
    recs = [_item(client, admin_id, target, f"רשומה {i}",
                  custom_fields={disp: f"רשומה {i} · מועצה מקומית"})
            for i in range(records)]

    src = _board(client, admin_id, made, "מקור תצוגה")
    cid = _add_col(client, admin_id, src, {
        "type": "connect", "title": "קישור",
        "connect": {"board_ids": [target], "multiple": True, "display_field": disp}})
    for i in range(rows):
        _item(client, admin_id, src, f"פריט {i}",
              custom_fields={cid: [recs[i % len(recs)]]})
    return target, disp, recs, src, cid


def _walk_pages(client, bid, uid, limit=2):
    """Every page of /items/query, merged the way Paged.mergeLinkDisplay merges
    them: per column, into the inner map, never by replacing it. Page two's
    inner map knows only page two's items, so an assignment here would be the
    browser bug this mirrors.

    Returns the merged map, the row ids in the order they arrived, and each
    page's own map — the last so a test can say that no single page held the
    whole answer, which is what makes the merge the thing under test.
    """
    merged, rows, pages, off, guard = {}, [], [], 0, 0
    while True:
        guard += 1
        assert guard < 50, "the walk does not end"
        r = client.post(f"/api/boards/{bid}/items/query", headers=AS(uid),
                        json={"filter": {"operator": "and", "rules": []},
                              "limit": limit, "offset": off})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "link_display" in d, "a page of rows carries no link_display at all"
        pages.append(d["link_display"] or {})
        for col_id, page in (d["link_display"] or {}).items():
            merged.setdefault(col_id, {}).update(page)
        rows += [t["id"] for t in d["items"]]
        if not d["has_more"]:
            return merged, rows, pages
        off = d["next_offset"]


# ── the end-to-end guard ──────────────────────────────────────────────────
def test_the_pages_merged_say_exactly_what_the_whole_board_says(
        client, admin_id, boards, monkeypatch):
    """One board, read on both sides of the threshold. Below it the rows and
    the map travel together in the board payload; above it the rows come fifty
    at a time and each page brings the map for its own rows. What the browser
    ends up holding has to be the same thing in both cases — same column, same
    item ids, same strings."""
    _t, _disp, recs, src, cid = _linked_pair(client, admin_id, boards)

    whole = _board_json(client, src, admin_id)["link_display"]
    assert whole.get(cid), "the small board carries no override map to compare against"

    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", 2)
    big = _board_json(client, src, admin_id)
    assert big["tasks"] == [] and big["link_display"] == {}, \
        "this board was supposed to be paging"

    merged, rows, _pages = _walk_pages(client, src, admin_id)
    assert len(rows) == len(set(rows)) == big["item_count"], \
        "the walk did not see the board once through"
    assert merged == whole, (
        "the paged board shows different words from the whole one\n"
        f" paged: {merged}\n whole: {whole}")

    # …and the words are the FIELD. Without this the test passes on exactly the
    # bug it exists to catch: a server sending nothing leaves the browser
    # falling back to titles, and two empty maps compare equal.
    assert set(merged[cid]) == {str(i) for i in recs}, merged[cid]
    titles = {str(i): f"רשומה {n}" for n, i in enumerate(recs)}
    for rid, text in merged[cid].items():
        assert text == titles[rid] + " · מועצה מקומית", (rid, text)
        assert text != titles[rid], "the chip is showing the linked record's title"


def test_a_record_on_the_second_page_is_not_lost_when_the_first_is_merged(
        client, admin_id, boards, monkeypatch):
    """The merge is per column and per item, and the thing it must survive is
    pages that know different records. Asked of the pages themselves: no single
    page carries the whole answer, which is what makes merging the only way to
    get it."""
    _t, _d, recs, src, cid = _linked_pair(client, admin_id, boards, rows=4, records=4)
    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", 2)

    merged, _rows, pages = _walk_pages(client, src, admin_id, limit=2)
    seen = [set((p.get(cid) or {})) for p in pages]
    said = [s for s in seen if s]
    assert len(said) > 1, "one page carried the whole answer — nothing was merged"
    assert any(a != b for a in said for b in said), \
        "every page carries the same records — this board does not prove a merge"
    assert set().union(*said) == {str(i) for i in recs}
    assert set(merged[cid]) == {str(i) for i in recs}, (
        "a record a page knew about did not survive the merge")


def test_a_page_of_a_board_with_no_display_field_carries_an_empty_map(
        client, admin_id, boards, monkeypatch):
    """An override map says only where the column was told to show something
    other than the title, so an ordinary connect column contributes nothing to
    it. Pinned because the opposite — a map listing every chip — would be a
    page-sized copy of data the browser already resolves through
    /api/tasks/lookup."""
    target = _board(client, admin_id, boards, "יעד בלי שדה")
    rec = _item(client, admin_id, target, "רשומה")
    src = _board(client, admin_id, boards, "מקור בלי שדה")
    cid = _add_col(client, admin_id, src, {
        "type": "connect", "title": "קישור",
        "connect": {"board_ids": [target], "multiple": True}})
    for i in range(3):
        _item(client, admin_id, src, f"פריט {i}", custom_fields={cid: [rec]})

    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", 1)
    merged, rows, _pages = _walk_pages(client, src, admin_id, limit=2)
    assert rows, "no rows came back at all"
    assert merged == {}, merged
    # the cells really are linked — the empty map is a decision about what the
    # column was told to show, not a board with nothing on it
    page = client.post(f"/api/boards/{src}/items/query", headers=AS(admin_id),
                       json={"filter": {"operator": "and", "rules": []},
                             "limit": 2, "offset": 0}).json()
    assert any((t.get("custom_fields") or {}).get(cid) for t in page["items"])


# ── the same page, two readers ────────────────────────────────────────────
def test_a_reader_who_may_not_see_the_far_column_is_sent_the_title(
        client, admin_id, guinea_id, boards, monkeypatch):
    """The permission is re-asked on the far board, for the person reading the
    page, at the moment the page is built. The admin chose the display field
    while able to see it; that grants the next reader nothing.

    A refusal falls back to the title rather than blanking the chip — and a
    text equal to the title is simply absent from the override map, which is
    how "this reader sees the title" looks on the wire. Both readers ask for
    the same page of the same board in the same breath here, so what is being
    compared is the reader and nothing else."""
    target, disp, recs, src, cid = _linked_pair(client, admin_id, boards,
                                                rows=4, records=2)
    join_primary_env(client, guinea_id)
    for bid in (target, src):
        r = client.post(f"/api/boards/{bid}/members", headers=AS(admin_id),
                        json={"actor_id": admin_id, "user_id": guinea_id,
                              "role": "editor"})
        assert r.status_code == 200, r.text

    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", 1)
    mine, _r, _p = _walk_pages(client, src, admin_id)
    theirs, _r, _p = _walk_pages(client, src, guinea_id)
    assert mine == theirs and mine.get(cid), \
        "the guinea cannot see the field yet — nothing to compare"

    r = client.post(f"/api/boards/{target}/columns/{disp}/permissions",
                    headers=AS(admin_id), json={"user_id": guinea_id, "perm": "none"})
    assert r.status_code == 200, r.text
    try:
        mine, mine_rows, _p = _walk_pages(client, src, admin_id)
        theirs, their_rows, _p = _walk_pages(client, src, guinea_id)
        assert mine.get(cid), "the admin lost the text they are entitled to"
        assert not theirs.get(cid), (
            "the guinea was handed text off a column they may not read: "
            f"{theirs.get(cid)}")
        # and the rows themselves still arrive — the chip shows the title, it
        # does not disappear
        assert their_rows == mine_rows
    finally:
        client.post(f"/api/boards/{target}/columns/{disp}/permissions",
                    headers=AS(admin_id), json={"user_id": guinea_id, "perm": None})


# ── and not on the answers that are about ids ─────────────────────────────
def test_an_ids_only_answer_carries_no_link_display(
        client, admin_id, boards, monkeypatch):
    """`ids_only` is the small-board answer: the browser holds every row
    already and is asking only which of them survive the filter. It gets its
    display text from the board payload, which still carries it down there, so
    a map here would be built per request and read by nobody."""
    _t, _d, _r, src, cid = _linked_pair(client, admin_id, boards, rows=3, records=2)
    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", 1)
    r = client.post(f"/api/boards/{src}/items/query", headers=AS(admin_id),
                    json={"filter": {"operator": "and", "rules": []}, "ids_only": True})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "item_ids" in d, "an ids_only answer stopped answering with ids"
    assert "link_display" not in d, d.get("link_display")
    # …on a board that has something to say. The same board asked for a PAGE
    # answers with the map, so the absence above is the shape of the answer and
    # not an empty board.
    page = client.post(f"/api/boards/{src}/items/query", headers=AS(admin_id),
                       json={"filter": {"operator": "and", "rules": []}}).json()
    assert (page.get("link_display") or {}).get(cid), (
        "a page of rows says nothing either — this board proves nothing about "
        f"ids_only: {page.get('link_display')}")


def test_an_answer_about_named_ids_carries_no_link_display(
        client, admin_id, boards, monkeypatch):
    """`only=[ids]` is the narrowest question in the API — "do these rows still
    match?" — asked after an edit. It returns ids and nothing else, by the same
    rule: a caller asking about one row must not be handed a page of others,
    nor a map describing them."""
    _t, _d, _r, src, _c = _linked_pair(client, admin_id, boards, rows=3, records=2)
    monkeypatch.setattr(cityos_main, "FILTER_CLIENT_MAX", 1)
    ids = _walk_pages(client, src, admin_id)[1]
    r = client.post(f"/api/boards/{src}/items/query", headers=AS(admin_id),
                    json={"filter": {"operator": "and", "rules": []},
                          "only": ids[:1]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["asked"] == ids[:1] and "item_ids" in d
    assert "link_display" not in d, d.get("link_display")


# ── the browser's half of it ──────────────────────────────────────────────
def test_a_page_folds_its_link_display_into_the_board():
    """Driven harness: the real Paged.mergeLinkDisplay over two pages that know
    different rows, plus the pin that it is reached from Paged.load and from
    nowhere else."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
