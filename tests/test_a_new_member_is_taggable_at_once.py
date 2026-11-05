"""מנהל לוח מוסיף משתתף — ואפשר לתייג אותו מיד, בלי רענון יזום.

Every picker on a board draws from boardPeople(), which reads
st.board.members — the list that came down with the board when it was loaded.
The members dialog fetched its own list and redrew its own rows and touched
nothing else. So an admin invited somebody, watched the name appear in the
dialog, closed it, and then could not tag them: not in a people column, not
in the assignee menu, not in the filter's people chips, not in a form's
אנשים question, not with @ in the chat. Only F5 fixed it.

The fix is in two halves and neither is redundant:

  · the admin's own browser rebuilds st.board.members out of the answer the
    dialog already fetched. The live stream cannot cover this one —
    Live.onEvent drops an event whose actor is me, on the grounds that I can
    already see what I did, which is true of a row I edited and not of a
    picker I am not looking at;
  · the server announces board.changed, so everybody ELSE with the board
    open reconciles the way they already do for a column or a group.

A membership change is a change to the board, because who may be tagged in
it is part of what the board is.

The avatar joins the members payload here for the same reason: that answer is
no longer drawn only in the dialog, and the board payload's own "members" key
carries exactly {id, name, avatar_url}.
"""
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import main as cityos_main  # noqa: E402

SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def _route(name):
    """One route's source, from its def to the next top-level one."""
    i = SRC.index(f"def {name}(")
    j = SRC.index("\n@app.", i)
    return SRC[i:j]


# ── the server announces it ───────────────────────────────────────────────
@pytest.mark.parametrize("route", ["add_board_member", "update_board_member",
                                   "remove_board_member"])
def test_every_membership_change_is_announced(route):
    """Who may be tagged in a board is part of what the board is, so a
    membership change is a board change and travels as one. board.changed is
    what the browser already reconciles a whole board on — see Live.apply,
    where it is one of the three events that force a full refresh."""
    body = _route(route)
    assert 'bus.publish("board.changed"' in body, body[-700:]
    # the actor rides along, because that is how the browser knows not to
    # redraw over somebody's own open editor
    assert "actor_id=actor_id" in body


def test_the_event_goes_out_after_the_write_and_not_before(client, admin_id):
    """An announcement before the commit describes something that may yet be
    rolled back. Checked by position rather than by eye: the publish sits
    below the commit in every one of the three."""
    for route in ("add_board_member", "update_board_member", "remove_board_member"):
        body = _route(route)
        assert body.index("db.commit()") < body.index('bus.publish("board.changed"'), route


# ── the payload carries what the picker needs ─────────────────────────────
def test_the_members_payload_carries_the_face(client, admin_id):
    """st.board.members is rebuilt from this answer, and that list is
    {id, name, avatar_url} in the board payload. Without the avatar here,
    everyone just invited loses their photo until the next full board load."""
    bid = client.post("/api/boards",
                      json={"actor_id": admin_id, "name": "לוח חברים"}).json()["id"]
    try:
        r = client.get(f"/api/boards/{bid}/members?user_id={admin_id}")
        assert r.status_code == 200, r.text
        ms = r.json()["members"]
        assert ms, "a board always has at least one member — the person on it"
        for m in ms:
            assert "avatar_url" in m, m
            assert "user_id" in m and "name" in m and "is_active" in m, m
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_an_invited_member_is_in_the_list_the_pickers_are_built_from(client, admin_id):
    """End to end on the server's side of it: invite, then ask the two
    answers the browser builds its pickers from. Both have to name them —
    the dialog's list, and the board payload's own."""
    import models
    from sqlalchemy.orm import Session
    bid = client.post("/api/boards",
                      json={"actor_id": admin_id, "name": "לוח הזמנה"}).json()["id"]
    try:
        with Session(cityos_main.engine) as db:
            other = (db.query(models.User)
                       .filter(models.User.id != admin_id,
                               models.User.is_active.isnot(False))
                       .first())
        if other is None:
            pytest.skip("no second user to invite")
        oid, oname = other.id, other.name
        r = client.post(f"/api/boards/{bid}/members",
                        json={"actor_id": admin_id, "user_id": oid, "role": "editor"})
        assert r.status_code == 200, r.text
        dialog = client.get(f"/api/boards/{bid}/members?user_id={admin_id}").json()
        assert oid in [m["user_id"] for m in dialog["members"]]
        board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
        assert oid in [m["id"] for m in board["members"]], board["members"]
        assert oname in [m["name"] for m in board["members"]]
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


# ── and the browser repairs its own list ──────────────────────────────────
def test_the_admins_own_browser_updates_without_a_reload():
    """Driven harness: tests/frontend/a_new_member_is_taggable_at_once.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "a_new_member_is_taggable_at_once.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_dialog_does_not_empty_the_board_when_its_fetch_fails():
    """The hazard the change brings with it. Both callers swallow a failed
    request, and the empty default they fall back to is indistinguishable,
    inside the sync, from an answer. A board you can see always has at least
    one member — you — so an empty list is a failed fetch, and writing it
    through would take every person off every picker over one timeout."""
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    i = html.index("  _syncBoardPeople(){")
    body = html[i:html.index("\n  },", i)]
    assert "if(!got.length)return;" in body, body
    # …and the callers decline before it, rather than relying on that alone
    j = html.index("  async refresh(){ let d=null;")
    assert "if(!d) return;" in html[j:j + 400]
