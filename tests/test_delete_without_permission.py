"""מחיקה ללא הרשאה נעצרת בלחיצה, ולא אחרי שאושרה.

A board editor may not delete: _board_caps gives "delete" to admin alone. The
menu offered "מחק פריט" to them anyway, the confirmation dialog warned that
the item could not be restored, they confirmed — and the answer was a toast
reading "0 פריטים נמחקו". A count, with no reason in it and no one named to
ask. The refusal is told at the click now.

Two halves, and each is useless without the other:

  * the server still decides. The client check is a courtesy and can be stale
    or skipped entirely, so DELETE must keep answering 403 and the item must
    survive it.
  * the client can only be courteous if the item says what the viewer may do
    with it. That is `my_perm`, and the frontend's deleteBlockReason is built
    on it — so the value this endpoint reports for an editor is part of the
    contract, not an implementation detail.

The drawing half — which words, and that no dialog opens — is pinned by
tests/frontend/delete_without_permission.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "delete_without_permission.mjs"


def _board_with_editor(client, admin_id, editor_id):
    bid = client.post("/api/boards",
                      json={"name": "לוח מחיקות", "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": editor_id, "role": "editor"})
    assert r.status_code in (200, 201), r.text
    return bid


def _item(client, bid, admin_id, title="פריט למחיקה"):
    return client.post("/api/tasks",
                       json={"board_id": bid, "title": title,
                             "user_id": admin_id}).json()["id"]


def test_an_editor_is_refused_and_the_item_is_still_there(client, admin_id, guinea_id):
    """403, and nothing moved — the refusal is real, not cosmetic."""
    bid = _board_with_editor(client, admin_id, guinea_id)
    tid = _item(client, bid, admin_id)
    try:
        r = client.delete(f"/api/tasks/{tid}?user_id={guinea_id}")
        assert r.status_code == 403, r.text

        # still listed for the admin, and not in the bin
        rows = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
        assert any(t["id"] == tid for t in rows), "the refused delete took the item anyway"
    finally:
        client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_item_tells_an_editor_that_deleting_is_not_theirs(client, admin_id, guinea_id):
    """my_perm is what the click-time check reads. An editor must see "edit".

    If this ever reported "delete" for somebody who cannot delete, the dialog
    would open again and the 0-items toast would come back with it.
    """
    bid = _board_with_editor(client, admin_id, guinea_id)
    tid = _item(client, bid, admin_id)
    try:
        rows = client.get(f"/api/boards/{bid}?user_id={guinea_id}").json()["tasks"]
        mine = next(t for t in rows if t["id"] == tid)
        assert mine["my_perm"] == "edit", mine["my_perm"]

        admin_rows = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
        theirs = next(t for t in admin_rows if t["id"] == tid)
        assert theirs["my_perm"] == "delete", theirs["my_perm"]
    finally:
        client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_refusal_is_shown_at_the_click_and_names_the_right_scope():
    """The frontend half — runs the real functions out of index.html."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
