"""תצוגות טבלה — נעילה, הצמדה, שכפול, פח, סדר אישי ופריסת עמודות.

The saved-view strip already kept a cut: filters, sort, the condition tree.
What a TABLE view has to keep as well is the table — which columns are shown,
in what order, how wide — because that is the difference between a view and a
filter. A board's settings are one arrangement for everybody; two views of one
board are meant to disagree about all four.

Around that sit the things a shared strip needs once people actually rely on
it, and each one exists because the shared-ness creates the problem:

  נעילה   — a shared cut is a stray "שמור" away from being somebody else's
            cut. A locked view is read and copied, never written; not even by
            its owner, which is what makes it a lock and not a permission.
  הצמדה   — the board's statement about which cut matters here. Everyone's
            strip, not the reader's.
  סדר אישי — the opposite: which tab somebody reaches for first is a habit,
            and arranging it changes nothing for anybody else.
  שכפול    — the way to build on a cut you may not overwrite.
  פח       — a tab people work off, deleted by mistake, is noticed the next
            morning. A hard delete leaves nothing to put back.

Driven alongside tests/test_saved_views.py, which owns the cut itself.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import SavedView, BoardViewPrefs  # noqa: E402

# the cut and the helpers that build one; the fixtures come from conftest
from test_saved_views import CUT, _board, _mk, _list  # noqa: E402


def _h(uid):
    return {"X-CityOS-User": str(uid)}


def _patch(client, vid, uid, **data):
    return client.patch(f"/api/views/{vid}", json=dict(data, user_id=uid), headers=_h(uid))


def _one(client, bid, uid, name):
    return next(v for v in _list(client, bid, uid) if v["name"] == name)


# ── פריסת עמודות: what makes it a TABLE view ───────────────────────────────
def test_a_view_keeps_the_table_and_not_only_the_cut(client, admin_id):
    """Visible columns, their order and their widths travel with the view.

    They used to live on the board's settings, where there is one of them for
    everybody — so two views of one board could differ in every way except the
    thing a table view is mostly about."""
    bid = _board(client, admin_id)
    cols = {"order": ["item", "status", "c7"], "hidden": ["due", "priority"],
            "widths": {"item": 320, "status": 110, "c7": 200}}
    v = _mk(client, bid, admin_id, "רק הסטטוס", filters=dict(CUT, cols=cols)).json()
    assert v["filters"]["cols"] == cols, "the layout came back changed"

    back = _one(client, bid, admin_id, "רק הסטטוס")
    assert back["filters"]["cols"]["widths"]["item"] == 320
    assert back["filters"]["cols"]["hidden"] == ["due", "priority"]


def test_two_views_of_one_board_disagree_about_the_table(client, admin_id):
    bid = _board(client, admin_id)
    _mk(client, bid, admin_id, "רחבה", filters=dict(CUT, cols={"widths": {"item": 400}}))
    _mk(client, bid, admin_id, "צרה", filters=dict(CUT, cols={"widths": {"item": 120}}))
    got = {v["name"]: v["filters"]["cols"]["widths"]["item"] for v in _list(client, bid, admin_id)}
    assert got == {"רחבה": 400, "צרה": 120}


# ── נעילה ──────────────────────────────────────────────────────────────────
# "תצוגה שרק בעל הלוח רשאי לשנות את הגדרותיה, לפתוח את נעילתה או למחוק אותה."
# So a lock does not freeze a view — it narrows who may touch it to the board's
# owner. The person who MADE it is on the outside of that narrowing like
# everybody else, unless they happen to run the board.
def test_a_locked_view_is_not_its_makers_to_change_any_more(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])          # guinea is an editor
    vid = _mk(client, bid, guinea_id, "מאושרת").json()["id"]
    assert _patch(client, vid, guinea_id, name="לפני הנעילה").status_code == 200

    assert _patch(client, vid, admin_id, locked=True).status_code == 200
    r = _patch(client, vid, guinea_id, name="אחרי הנעילה")
    assert r.status_code == 403, "the view's own maker wrote through the lock"
    assert "בעל הלוח" in r.json()["detail"]
    assert _patch(client, vid, guinea_id, filters=dict(CUT, q="אחר")).status_code == 403


def test_the_board_owner_writes_through_the_lock(client, admin_id, guinea_id):
    """The whole point of the narrowing: somebody can still fix the tab."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, guinea_id, "מאושרת").json()["id"]
    _patch(client, vid, admin_id, locked=True)
    assert _patch(client, vid, admin_id, name="תוקן").status_code == 200
    assert _one(client, bid, admin_id, "תוקן")["locked"] is True, "the fix unlocked it"


def test_only_the_board_owner_turns_the_lock_either_way(client, admin_id, guinea_id):
    """Locking as well as unlocking. A lock an editor could apply and then not
    undo would be a trap, and "רק בעל הלוח" reads the same at both ends."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, guinea_id, "מאושרת").json()["id"]
    assert _patch(client, vid, guinea_id, locked=True).status_code == 403
    _patch(client, vid, admin_id, locked=True)
    assert _patch(client, vid, guinea_id, locked=False).status_code == 403
    assert _patch(client, vid, admin_id, locked=False).status_code == 200
    assert _patch(client, vid, guinea_id, name="עכשיו כן").status_code == 200


def test_deleting_a_locked_view_is_the_board_owners_too(client, admin_id, guinea_id):
    """The definition names deletion beside changing and unlocking, and a lock
    that stopped edits but not deletion would protect nothing."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, guinea_id, "מאושרת").json()["id"]
    _patch(client, vid, admin_id, locked=True)
    r = client.delete(f"/api/views/{vid}", headers=_h(guinea_id))
    assert r.status_code == 403 and "בעל הלוח" in r.json()["detail"]
    assert client.delete(f"/api/views/{vid}", headers=_h(admin_id)).status_code == 200


def test_the_strip_says_who_may_press_save_on_a_locked_view(client, admin_id, guinea_id):
    """can_edit is the question the strip actually asks — may I press שמור —
    which is the rights AND the lock. can_lock is the switch itself."""
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, guinea_id, "מאושרת").json()["id"]
    _patch(client, vid, admin_id, locked=True)

    mine = _one(client, bid, guinea_id, "מאושרת")
    assert mine["can_edit"] is False and mine["can_lock"] is False
    theirs = _one(client, bid, admin_id, "מאושרת")
    assert theirs["can_edit"] is True and theirs["can_lock"] is True


# ── הצמדה ──────────────────────────────────────────────────────────────────
def test_a_pinned_view_comes_first_for_everyone(client, admin_id, guinea_id):
    """Pinning is the board's statement, so it is not somebody's own order."""
    bid = _board(client, admin_id, invite=[guinea_id])
    _mk(client, bid, admin_id, "ראשונה")
    second = _mk(client, bid, admin_id, "שנייה").json()["id"]
    _mk(client, bid, admin_id, "שלישית")
    assert _patch(client, second, admin_id, pinned=True).status_code == 200
    assert [v["name"] for v in _list(client, bid, guinea_id)][0] == "שנייה"
    assert [v["name"] for v in _list(client, bid, admin_id)][0] == "שנייה"


# ── סדר תצוגות אישי ────────────────────────────────────────────────────────
def test_arranging_the_strip_is_personal_and_changes_nobody_elses(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    c = _mk(client, bid, admin_id, "ג").json()["id"]
    assert [v["name"] for v in _list(client, bid, guinea_id)] == ["א", "ב", "ג"]

    r = client.put(f"/api/boards/{bid}/views/order",
                   json={"user_id": guinea_id, "order": [c, a, b]}, headers=_h(guinea_id))
    assert r.status_code == 200, r.text
    assert [v["name"] for v in _list(client, bid, guinea_id)] == ["ג", "א", "ב"]
    assert [v["name"] for v in _list(client, bid, admin_id)] == ["א", "ב", "ג"], \
        "one person's arrangement moved somebody else's tabs"


def test_a_view_made_since_the_strip_was_arranged_lands_at_the_end(client, admin_id):
    """Arranging is not a promise about views that did not exist yet, and a
    new tab must not shove its way into the middle of somebody's order."""
    bid = _board(client, admin_id)
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    client.put(f"/api/boards/{bid}/views/order",
               json={"user_id": admin_id, "order": [b, a]}, headers=_h(admin_id))
    _mk(client, bid, admin_id, "חדשה")
    assert [v["name"] for v in _list(client, bid, admin_id)] == ["ב", "א", "חדשה"]


def test_a_pin_still_wins_over_a_personal_arrangement(client, admin_id):
    bid = _board(client, admin_id)
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    client.put(f"/api/boards/{bid}/views/order",
               json={"user_id": admin_id, "order": [a, b]}, headers=_h(admin_id))
    _patch(client, b, admin_id, pinned=True)
    assert [v["name"] for v in _list(client, bid, admin_id)] == ["ב", "א"]


def test_an_arrangement_naming_views_that_are_gone_settles_rather_than_fails(client, admin_id):
    """A strip arranged, then re-arranged against a stale list, must not
    error — it must simply drop what is not there."""
    bid = _board(client, admin_id)
    a = _mk(client, bid, admin_id, "א").json()["id"]
    r = client.put(f"/api/boards/{bid}/views/order",
                   json={"user_id": admin_id, "order": [99999, a, "לא מספר", a]},
                   headers=_h(admin_id))
    assert r.status_code == 200
    assert r.json()["order"] == [a], "a stale or duplicated id was kept"


def test_arranging_takes_only_the_right_to_look(client, admin_id, guinea_id):
    """It changes nothing about the board, which is why it needs no rights
    beyond opening it — a viewer may arrange their own strip."""
    bid = _board(client, admin_id, invite=[guinea_id], role="viewer")
    a = _mk(client, bid, admin_id, "א").json()["id"]
    b = _mk(client, bid, admin_id, "ב").json()["id"]
    r = client.put(f"/api/boards/{bid}/views/order",
                   json={"user_id": guinea_id, "order": [b, a]}, headers=_h(guinea_id))
    assert r.status_code == 200, r.text
    assert [v["name"] for v in _list(client, bid, guinea_id)] == ["ב", "א"]


# ── שכפול ──────────────────────────────────────────────────────────────────
def test_duplicating_keeps_the_cut_and_the_table(client, admin_id):
    bid = _board(client, admin_id)
    cols = {"order": ["item", "status"], "hidden": ["due"], "widths": {"item": 300}}
    vid = _mk(client, bid, admin_id, "המקור", filters=dict(CUT, cols=cols)).json()["id"]
    r = client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id}, headers=_h(admin_id))
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["id"] != vid
    assert c["name"] == "המקור — עותק"
    assert c["filters"]["cols"] == cols and c["filters"]["q"] == CUT["q"]


def test_a_copy_carries_no_lock_and_no_pin(client, admin_id):
    """Both are statements about THAT tab. A copy is a new tab nobody has
    decided anything about yet — a copy that arrived locked could not even be
    edited, which is the whole reason to copy a locked view."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "מאושרת").json()["id"]
    _patch(client, vid, admin_id, locked=True, pinned=True)
    c = client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                    headers=_h(admin_id)).json()
    assert c["locked"] is False and c["pinned"] is False
    assert _patch(client, c["id"], admin_id, name="ועכשיו שלי").status_code == 200


def test_copying_twice_says_so(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "המקור").json()["id"]
    first = client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                        headers=_h(admin_id)).json()["name"]
    second = client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                         headers=_h(admin_id)).json()["name"]
    assert first == "המקור — עותק" and second == "המקור — עותק 2"


def test_a_locked_view_can_still_be_copied(client, admin_id):
    """Read and build on, never write: copying is how you build on it."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "מאושרת").json()["id"]
    _patch(client, vid, admin_id, locked=True)
    assert client.post(f"/api/views/{vid}/duplicate", json={"user_id": admin_id},
                       headers=_h(admin_id)).status_code == 200


def test_a_viewer_cannot_duplicate_a_tab_onto_the_board(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id], role="viewer")
    vid = _mk(client, bid, admin_id, "המקור").json()["id"]
    r = client.post(f"/api/views/{vid}/duplicate", json={"user_id": guinea_id}, headers=_h(guinea_id))
    assert r.status_code == 403


# ── מחיקה ושחזור ───────────────────────────────────────────────────────────
def test_a_deleted_view_waits_in_the_bin(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    assert _list(client, bid, guinea_id) == []

    r = client.get(f"/api/boards/{bid}/views/trash?user_id={admin_id}", headers=_h(admin_id))
    assert r.status_code == 200, r.text
    rows = r.json()["views"]
    assert [v["name"] for v in rows] == ["זמנית"]
    assert rows[0]["deleted_at"] and rows[0]["deleted_by_name"]


def test_restoring_brings_the_cut_back_whole(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    cols = {"widths": {"item": 333}}
    vid = _mk(client, bid, admin_id, "חזרה", filters=dict(CUT, cols=cols)).json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    r = client.post(f"/api/views/{vid}/restore", json={"user_id": admin_id}, headers=_h(admin_id))
    assert r.status_code == 200, r.text
    back = _one(client, bid, guinea_id, "חזרה")
    assert back["filters"]["cols"] == cols and back["filters"]["q"] == CUT["q"]


def test_a_view_in_the_bin_is_not_on_the_strip_and_not_in_the_count(client, admin_id):
    """The per-board ceiling counts tabs, and a tab in the bin is not one."""
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    with Session(cityos_main.engine) as db:
        live = (db.query(SavedView)
                  .filter(SavedView.board_id == bid, SavedView.deleted_at.is_(None)).count())
    assert live == 0
    assert _mk(client, bid, admin_id, "אחרת").status_code == 200


def test_restoring_twice_is_not_an_error(client, admin_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "חזרה").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    assert client.post(f"/api/views/{vid}/restore", json={"user_id": admin_id},
                       headers=_h(admin_id)).status_code == 200
    assert client.post(f"/api/views/{vid}/restore", json={"user_id": admin_id},
                       headers=_h(admin_id)).status_code == 200


def test_the_bin_is_not_a_way_into_a_board_you_cannot_open(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    vid = _mk(client, bid, admin_id, "זמנית").json()["id"]
    client.delete(f"/api/views/{vid}", headers=_h(admin_id))
    assert client.get(f"/api/boards/{bid}/views/trash?user_id={guinea_id}",
                      headers=_h(guinea_id)).status_code == 403
    assert client.post(f"/api/views/{vid}/restore", json={"user_id": guinea_id},
                       headers=_h(guinea_id)).status_code == 403


# ── the permission matrix, walked row by row ───────────────────────────────
# "כל פעולה נבדקת בשרת." So every row is asked of the server, for all three
# roles, rather than trusted to the flags the strip is drawn from. A table of
# expectations beats fifteen more test functions: when a row changes, the
# change is one word here and the case that moves is named in the failure.
#
# Not here: the three "זמני" rows and the table adjustments, which never reach
# the server by definition (see "שינוי זמני"), and עריכת נתוני פריט, which is
# the board's existing item permissions and is tested where those are.
MATRIX = {
    #  action                         owner  editor viewer
    "see":                            (True,  True,  True),
    "create":                         (True,  True,  False),
    "rename_unlocked":                (True,  True,  False),
    "delete_unlocked":                (True,  True,  False),
    "main_table_config_for_everyone": (True,  False, False),
    "lock":                           (True,  False, False),
    "rename_locked":                  (True,  False, False),
    "delete_locked":                  (True,  False, False),
    "duplicate":                      (True,  True,  False),
    "pin":                            (True,  False, False),
    "order_pinned":                   (True,  False, False),
    "restore":                        (True,  False, False),
    "personal_order":                 (True,  True,  True),
}


@pytest.fixture
def cast(client, admin_id, guinea_id, member_id):
    """One board, and a person in each of the three roles on it."""
    bid = _board(client, admin_id, invite=[guinea_id], role="editor")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "viewer"})
    return {"bid": bid, "owner": admin_id, "editor": guinea_id, "viewer": member_id}


def _attempt(client, cast, action, uid):
    """Perform one row of the matrix as `uid`, and return the status code."""
    bid, owner = cast["bid"], cast["owner"]
    if action == "see":
        return client.get(f"/api/boards/{bid}/views?user_id={uid}", headers=_h(uid)).status_code
    if action == "create":
        return _mk(client, bid, uid, f"חדשה {uid}").status_code
    if action == "main_table_config_for_everyone":
        return client.patch(f"/api/boards/{bid}", json={"actor_id": uid,
                                                        "col_widths": {"item": 321}},
                            headers=_h(uid)).status_code
    if action == "personal_order":
        v = _mk(client, bid, owner, f"לסידור {uid}").json()["id"]
        return client.put(f"/api/boards/{bid}/views/order",
                          json={"user_id": uid, "order": [v]}, headers=_h(uid)).status_code

    # the rest act on a view the OWNER made, so authorship never explains a pass
    vid = _mk(client, bid, owner, f"יעד {action} {uid}").json()["id"]
    if action in ("rename_locked", "delete_locked"):
        _patch(client, vid, owner, locked=True)
    if action == "restore":
        client.delete(f"/api/views/{vid}", headers=_h(owner))

    if action in ("rename_unlocked", "rename_locked"):
        return _patch(client, vid, uid, name=f"שונה {uid}").status_code
    if action in ("delete_unlocked", "delete_locked"):
        return client.delete(f"/api/views/{vid}", headers=_h(uid)).status_code
    if action == "duplicate":
        _patch(client, vid, owner, locked=True)        # "לרבות נעולה"
        return client.post(f"/api/views/{vid}/duplicate",
                           json={"user_id": uid}, headers=_h(uid)).status_code
    if action == "lock":
        return _patch(client, vid, uid, locked=True).status_code
    if action == "pin":
        return _patch(client, vid, uid, pinned=True).status_code
    if action == "order_pinned":
        return _patch(client, vid, uid, position=3).status_code
    if action == "restore":
        return client.post(f"/api/views/{vid}/restore",
                           json={"user_id": uid}, headers=_h(uid)).status_code
    raise AssertionError("unknown row: " + action)


@pytest.mark.parametrize("action", sorted(MATRIX))
@pytest.mark.parametrize("who", ("owner", "editor", "viewer"))
def test_the_permission_matrix_is_what_the_server_answers(client, cast, action, who):
    allowed = MATRIX[action][("owner", "editor", "viewer").index(who)]
    code = _attempt(client, cast, action, cast[who])
    if allowed:
        assert code == 200, f"{action} / {who} was refused ({code})"
    else:
        assert code == 403, f"{action} / {who} was allowed ({code})"
