"""תצוגות שמורות — חיתוך של לוח, שמור כטאב, אישי או ציבורי.

"באגים דחופים פתוחים" is three filters somebody sets every morning. A view is
that cut, named and kept.

The permission model is two words, and the asymmetry in it is the thing worth
testing, because getting it wrong is not a cosmetic failure:

  private — only its owner sees it. Somebody's own way of reading a board is
            not a statement about the board. A private view leaking into
            somebody else's tab strip is a stranger's bookmark appearing on
            your screen; a private view that another person can EDIT is worse.
  public  — everyone who may open the board sees it. It is a tab on the board,
            so creating one is an edit to the board and takes the rights of
            one — while making a private one takes only the right to look.

And a view is only as good as what it restores: the cut is stored whole, so a
tab opens the board the way it was left rather than approximately.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import SavedView  # noqa: E402

SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

CUT = {"view": "table", "q": "באג", "people": [], "status": "", "priority": "high",
       "sort": "", "links": {"col": "", "mode": "", "item": 0},
       "adv": {"op": "and", "rules": [
           {"field": "status", "op": "ne", "v": "done"},
           {"field": "priority", "op": "eq", "v": "high"}]}}


def _board(client, admin_id, invite=(), role="editor", name="לוח תצוגות"):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    for uid in invite:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    return bid


def _mk(client, bid, uid, name, vis="private", filters=None):
    return client.post(f"/api/boards/{bid}/views",
                       json={"user_id": uid, "name": name, "visibility": vis,
                             "filters": filters if filters is not None else CUT},
                       headers={"X-CityOS-User": str(uid)})


def _cfg(client, vid, uid, filters, **extra):
    """Save a view's configuration, carrying the version it is based on.

    A config save must name the version it is overwriting — that is what lets
    the server refuse a stale one instead of silently accepting it. Read here
    rather than passed in, because every caller of this helper means "save
    over what is there now"; a case that is ABOUT the stale version sends its
    own (see tests/test_view_concurrency.py).
    """
    with Session(cityos_main.engine) as db:
        have = db.query(SavedView).filter(SavedView.id == vid).one().config_version or 1
    return client.patch(f"/api/views/{vid}",
                        json=dict({"user_id": uid, "filters": filters,
                                   "config_version": have}, **extra),
                        headers={"X-CityOS-User": str(uid)})


def _list(client, bid, uid, main=False):
    """The board's SAVED views.

    The main table is a row like any other now, and it is on the strip — so
    it comes back from this endpoint too. Every case that was written before
    that means "the saved cuts", so it is filtered out here and asked for
    explicitly by the cases that are about it (tests/test_view_records.py).
    """
    r = client.get(f"/api/boards/{bid}/views?user_id={uid}",
                   headers={"X-CityOS-User": str(uid)})
    assert r.status_code == 200, r.text
    rows = r.json()["views"]
    return rows if main else [v for v in rows if v.get("kind") != "main"]


# ── saving a cut, and getting it back whole ───────────────────────────────
def test_a_view_keeps_the_whole_cut_not_an_approximation_of_it(client, admin_id):
    bid = _board(client, admin_id)
    r = _mk(client, bid, admin_id, "באגים דחופים פתוחים")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["name"] == "באגים דחופים פתוחים"
    assert v["visibility"] == "public", "every saved view is shared in this version"
    # everything except the search box — see test_a_saved_view_never_holds_a_search
    assert v["filters"] == {k: val for k, val in CUT.items() if k != "q"}, \
        "the cut came back changed"
    assert v["filters"]["adv"]["rules"][1]["v"] == "high"


def test_a_saved_view_never_holds_a_search(client, admin_id):
    """A search is a שינוי זמני — "מתאפסת ביציאה מהתצוגה". Stored, it would be
    the opposite of temporary: a tab that silently narrows the board for
    everybody who opens it, above a search box that looks empty.

    Dropped wherever a configuration is WRITTEN, not only where one is
    created: saving over a view would otherwise store what creating one is
    forbidden to."""
    bid = _board(client, admin_id)
    v = _mk(client, bid, admin_id, "בלי חיפוש").json()
    assert CUT["q"], "the fixture cut has to carry a search for this to mean anything"
    assert "q" not in v["filters"]
    assert v["filters"]["priority"] == CUT["priority"], "the rest of the cut went with it"

    r = _cfg(client, v["id"], admin_id, dict(CUT, q="שוב"))
    assert r.status_code == 200, r.text
    assert "q" not in _list(client, bid, admin_id)[0]["filters"], "a save stored one"


def test_a_view_with_no_name_is_named_by_the_server(client, admin_id):
    """Creating a table view is one click — there is no type to choose and no
    question to answer — so the name cannot be a question either. Sending no
    name means "call it something free", and the server does, because the
    uniqueness rule is the server's.

    A name that IS given is still checked; and renaming to nothing is still
    refused, because there "" means "take its name away"."""
    bid = _board(client, admin_id)
    v = _mk(client, bid, admin_id, "   ").json()
    assert v["name"] == cityos_main.NEW_VIEW_NAME

    r = client.patch(f"/api/views/{v['id']}", json={"user_id": admin_id, "name": "   "},
                     headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 400, "a view was left with no name at all"


def test_a_cut_the_server_would_refuse_is_not_saved(client, admin_id):
    """A view holding a filter the query endpoint rejects is a tab that cannot
    open — caught when it is saved, not when somebody clicks it."""
    bid = _board(client, admin_id)
    bad = dict(CUT, adv={"op": "and", "rules": [{"field": "status", "op": "DROP"}]})
    r = _mk(client, bid, admin_id, "שבור", filters=bad)
    assert r.status_code == 400 and "אופרטור" in r.json()["detail"]


# ── shared, and only shared ───────────────────────────────────────────────
def test_every_saved_view_is_a_tab_everybody_sees(client, admin_id, guinea_id):
    """There are no private views in this version. A saved table view IS a tab
    on the board, so it appears for everyone who may open the board — and a
    client that asks for a private one gets a shared one, because that is the
    only kind there is."""
    bid = _board(client, admin_id, invite=[guinea_id])
    v = _mk(client, bid, admin_id, "שלי בלבד").json()
    assert v["visibility"] == "public"
    assert [x["name"] for x in _list(client, bid, guinea_id)] == ["שלי בלבד"]


def test_keeping_a_view_takes_the_rights_of_an_edit_to_the_board(client, admin_id, guinea_id):
    """It used to take only the right to look, because a private view changed
    nothing for anybody else. Now every view is a tab on everybody's board, so
    making one is a change to the board and a viewer may not make it."""
    bid = _board(client, admin_id, invite=[guinea_id], role="viewer")
    r = _mk(client, bid, guinea_id, "הקריאה שלי")
    assert r.status_code == 403, r.text
    assert "עורך" in r.json()["detail"]
    assert _list(client, bid, guinea_id) == []


# ── public ────────────────────────────────────────────────────────────────
def test_a_public_view_is_everybodys(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    _mk(client, bid, admin_id, "לכולם", vis="public")
    assert [v["name"] for v in _list(client, bid, guinea_id)] == ["לכולם"]


def test_a_viewer_cannot_put_a_tab_on_the_board_by_any_door(client, admin_id, guinea_id):
    """Asking for public is refused, and so is asking for private — because
    private is written as public. Neither spelling is a way round the rights."""
    bid = _board(client, admin_id, invite=[guinea_id], role="viewer")
    assert _mk(client, bid, guinea_id, "ציבורית", vis="public").status_code == 403
    assert _mk(client, bid, guinea_id, "פרטית", vis="private").status_code == 403
    assert _list(client, bid, guinea_id) == []


# ── who may change one ────────────────────────────────────────────────────
def test_a_view_is_edited_by_its_owner(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, guinea_id, "של דנה", vis="public").json()["id"]
    r = client.patch(f"/api/views/{vid}", json={"user_id": admin_id, "name": "חטוף"},
                     headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 200, "a board admin must be able to tidy a public tab"
    other = client.patch(f"/api/views/{vid}", json={"user_id": guinea_id, "name": "חזרה"},
                         headers={"X-CityOS-User": str(guinea_id)})
    assert other.status_code == 200, "its own author lost it"


def test_an_editor_may_change_any_unlocked_view_on_the_board(client, admin_id, guinea_id, member_id):
    """Authorship is not the boundary; the board's roles are.

    A saved view is a tab on the board — part of how the board is set up — so
    the question is what somebody may do to THIS BOARD, not who happened to
    press save first. An editor edits the board, so an editor edits its tabs.
    What protects a cut people rely on is the lock, not its author's name."""
    bid = _board(client, admin_id, invite=[guinea_id, member_id])     # both editors
    vid = _mk(client, bid, guinea_id, "של דנה", vis="public").json()["id"]
    r = client.patch(f"/api/views/{vid}", json={"user_id": member_id, "name": "בשם אחר"},
                     headers={"X-CityOS-User": str(member_id)})
    assert r.status_code == 200, r.text
    assert client.delete(f"/api/views/{vid}",
                         headers={"X-CityOS-User": str(member_id)}).status_code == 200


def test_a_view_is_not_a_way_into_a_board_you_cannot_open(client, admin_id, guinea_id):
    bid = _board(client, admin_id, name="לוח סגור")
    _mk(client, bid, admin_id, "ציבורית", vis="public")
    r = client.get(f"/api/boards/{bid}/views?user_id={guinea_id}",
                   headers={"X-CityOS-User": str(guinea_id)})
    assert r.status_code == 403, r.text
    r = _mk(client, bid, guinea_id, "שלי")
    assert r.status_code == 403


def test_deleting_takes_it_off_everybodys_board_and_keeps_it(client, admin_id, guinea_id):
    """Off the strip for everyone, and still there to put back.

    A view is a tab other people work off; deleting one by mistake is noticed
    the next morning, by which time a hard delete has left nothing to restore.
    Same shape as a deleted board or item — deleted_at, and a bin beside it."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "זמנית", vis="public").json()["id"]
    assert len(_list(client, bid, guinea_id)) == 1
    r = client.delete(f"/api/views/{vid}", headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 200
    assert _list(client, bid, guinea_id) == []
    with Session(cityos_main.engine) as db:
        row = db.query(SavedView).filter(SavedView.id == vid).first()
        assert row is not None and row.deleted_at is not None, "the cut was destroyed"
        assert row.deleted_by == admin_id


def test_the_tabs_come_back_in_the_order_they_were_made(client, admin_id):
    bid = _board(client, admin_id)
    for n in ("ראשונה", "שנייה", "שלישית"):
        _mk(client, bid, admin_id, n)
    assert [v["name"] for v in _list(client, bid, admin_id)] == ["ראשונה", "שנייה", "שלישית"]


def test_a_tab_strip_is_not_a_list(client, admin_id):
    """The ceiling counts the ACTIVE views on the board. Per board and not per
    person: the strip is shared, so one person filling it fills everybody's."""
    bid = _board(client, admin_id)
    for i in range(cityos_main.VIEW_MAX):
        assert _mk(client, bid, admin_id, f"תצוגה {i}").status_code == 200
    r = _mk(client, bid, admin_id, "אחת יותר מדי")
    assert r.status_code == 400 and "יותר מדי" in r.json()["detail"]


def test_the_ceiling_is_the_boards_and_not_each_persons(client, admin_id, guinea_id):
    """Counted per owner, a second editor could double the strip."""
    bid = _board(client, admin_id, invite=[guinea_id])
    for i in range(cityos_main.VIEW_MAX):
        assert _mk(client, bid, admin_id, f"תצוגה {i}").status_code == 200
    assert _mk(client, bid, guinea_id, "ואחת שלי").status_code == 400


def test_a_view_says_whether_the_person_looking_may_change_it(client, admin_id, guinea_id):
    """The tab strip draws a pencil or it does not, and it must not have to
    work that out from the ownership rules a second time."""
    bid = _board(client, admin_id, invite=[guinea_id])
    _mk(client, bid, guinea_id, "של דנה", vis="public")
    mine = _list(client, bid, guinea_id)[0]
    theirs = _list(client, bid, admin_id)[0]
    assert mine["can_edit"] is True
    assert theirs["can_edit"] is True, "a board admin may tidy a public tab"
    assert theirs["owner_name"], "the strip cannot say whose view it is"


# ── the browser's half ─────────────────────────────────────────────────────
def test_the_cut_a_tab_restores_is_the_cut_it_saved():
    """Driven harness: tests/frontend/saved_views.mjs.

    A view that comes back with the filters but not the base view, or with
    the condition tree flattened, is worse than no view: it opens a board
    that looks right and is answering a different question.
    """
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "saved_views.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_strip_says_what_each_tab_is_before_it_is_opened():
    """"Who can see this" used to be the one question a saved view raised, and
    the strip answered it with a lock or a group of people. Every view is
    shared now, so that question is gone — and two others took its place: is
    this one locked, and is it pinned. Both change how the tab behaves, so
    both are on it.

    The icons live in tabIcons and the menu in actionsFor; this pins that the
    strip actually draws them. tests/frontend/view_strip.mjs runs them."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    # Views' own tabsHTML — BoardLog has one too, and it comes first in the
    # file. Anchoring on the name alone read the wrong method entirely.
    at = src.index("const Views = {")
    i = src.index("  tabsHTML(){", at)
    j = src.index("\n  },", i)
    body = src[i:j]
    assert "this.tabIcons(v)" in body, "a tab no longer says whether it is locked or pinned"
    assert "this.actionsFor(v)" in body, "the menu is drawn without asking the server"
    assert "visibility" not in body, "the strip still draws a permission model that is gone"


# ── the lock, and who overrides it ─────────────────────────────────────────
def test_the_owner_of_a_public_view_is_whoever_made_it(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    v = _mk(client, bid, guinea_id, "של דנה", vis="public").json()
    assert v["owner_id"] == guinea_id
    mine = [x for x in _list(client, bid, guinea_id) if x["id"] == v["id"]][0]
    assert mine["is_owner"] is True and mine["can_edit"] is True


def test_a_viewer_may_look_and_may_not_overwrite(client, admin_id, guinea_id, member_id):
    """A viewer is where the line now sits. Somebody adjusting what they are
    looking at must not be able to rewrite a tab other people rely on, and the
    damage is invisible to everyone it affects until they next open the tab and
    find it answering a different question."""
    bid = _board(client, admin_id, invite=[guinea_id])
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "viewer"})
    vid = _mk(client, bid, guinea_id, "של דנה", vis="public").json()["id"]
    seen = [x for x in _list(client, bid, member_id) if x["id"] == vid][0]
    assert seen["is_owner"] is False
    assert seen["can_edit"] is False, "a viewer is offered the overwrite"
    r = _cfg(client, vid, member_id, {"q": "משהו אחר"})
    assert r.status_code == 403
    assert client.delete(f"/api/views/{vid}",
                         headers={"X-CityOS-User": str(member_id)}).status_code == 403


def test_a_reader_can_always_keep_a_copy_of_their_own(client, admin_id, guinea_id, member_id):
    """"Save as new view" is what is offered instead, and it has to actually
    work — otherwise the rule is just a dead end."""
    bid = _board(client, admin_id, invite=[guinea_id, member_id])
    _mk(client, bid, guinea_id, "של דנה", vis="public")
    r = _mk(client, bid, member_id, "הגרסה שלי")
    assert r.status_code == 200, r.text
    assert r.json()["owner_id"] == member_id


def test_a_system_administrator_may_overwrite_any_view(client, admin_id, guinea_id):
    """Somebody has to be able to fix or remove a tab whose author has left."""
    with Session(cityos_main.engine) as db:
        from models import User
        assert db.query(User).filter(User.id == admin_id).first().role == "admin", \
            "this test needs the fixture admin to be a system admin"
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, guinea_id, "של דנה", vis="public").json()["id"]
    r = client.patch(f"/api/views/{vid}", json={"user_id": admin_id, "name": "מסודר"},
                     headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "מסודר"


# ── the view in the URL ────────────────────────────────────────────────────
def test_the_address_carries_the_open_view():
    """A filtered board is a thing people send each other. Without the view in
    the link, "look at this" opens the board unfiltered and the sentence
    beside it stops making sense."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    i = src.index("const Router={")
    j = src.index("\n};", i)
    router = src[i:j]
    assert "/view/" in router, "the view is not in the address"
    assert "viewId" in router
    # the default is what keeps a shared link intact: every existing caller
    # passes two arguments and none of them is about the view
    assert "if(viewId===undefined)" in router, \
        "opening an item drops the view out of the address"
    # The view is the third argument wherever the link is followed. Matched
    # as a prefix because the call grew a fourth — the parsed address itself,
    # which is how a link to the board's automations is told apart — and what
    # is pinned here is that the VIEW is still handed over, not how many
    # arguments the call happens to take.
    assert "openDeepLink(r.boardId, r.itemId, r.viewId" in src, \
        "a link carrying a view opens the board without it"


def test_a_shared_link_to_a_view_that_is_not_yours_says_so():
    """A private view, or one since deleted. The board opens unfiltered either
    way — but silently, it looks exactly like the link having worked."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    i = src.index("async function openDeepLink(")
    j = src.index("\n}", i)
    body = src[i:j]
    assert "Views.load(boardId)" in body, "the views are not waited for"
    assert "התצוגה אינה זמינה" in body


def test_a_view_keeps_the_order_it_was_saved_in():
    """The spec lists sort among what a view holds, and the column sort — the
    one every column header offers — was not in the kept list. So a view could
    carry a filter and not the order it was read in: sorting by a column
    changed the screen and changed nothing the view could see. "שמור תצוגה"
    never lit, and the sorted board could not be kept."""
    assert "colSort" in cityos_main.VIEW_CONFIG_KEYS, \
        "a view can no longer hold the order the board is in"
    i = SRC.index("  current(){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "colSort" in body, "the sort is back out of the cut a view compares"
    i = SRC.index("  apply(v){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "st.colSort=" in body, "a view no longer restores the order it saved"
    i = SRC.index("function columnSort(")
    body = SRC[i:SRC.index("\n}", i)]
    assert "refreshToolbar()" in body, \
        "sorting no longer reaches the tab strip, so the save button cannot light"


def test_clearing_a_filter_stays_in_the_view():
    """It used to leave: the tab went dark and the board fell back to its own
    table. That answered a question nobody asked — somebody emptying a view's
    filter is adjusting that view, not walking out of it — and leaving took
    the adjustment with it, so there was nothing left to save."""
    i = SRC.index("function clearFilters()")
    body = SRC[i:SRC.index("function togglePop(", i)]
    assert "Views.leave" not in body, "clearing a filter throws you out of the view again"
    assert "renderTabs()" in body, "the strip is not told, so the change cannot be saved"
    assert "function boardIsCut()" in SRC, \
        "nothing knows that a sort alone is a cut worth clearing or keeping"
