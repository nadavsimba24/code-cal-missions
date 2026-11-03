"""קובץ מגיע לשיחה פעם אחת בדיוק — לא פעמיים.

Three roads lead to one upload, and each of them has produced a double:

  * a drop on the composer. Chat.onDrop sits on the composer, where it can turn
    an Outlook drag carrying no file bytes into an .eml; bindDnd also listens on
    #chat-panel so a file can be dropped anywhere on the conversation and not
    only on the composer strip. The composer is INSIDE the panel, so a drop on
    it fired the inner handler and then bubbled to the outer one — every file
    uploaded twice, and for a mail under two different names, since the panel
    uploaded the raw file while the composer named it first.
  * a drop on the panel away from the composer. One handler, and it has to
    stay one.
  * a paste. It lived on the textarea, then on the panel — where a paste with
    focus on <body> never travels — and now on document, the only node every
    paste passes. A document listener is global and PERMANENT: Chat.open calls
    bindDnd on every open, so without its guard the tenth conversation of the
    day would attach every pasted file ten times, for the rest of the session.

The same stopPropagation then froze the panel. #chat-panel carries .dnd-over
while a drag is over it, and that class draws a blue sheet across the whole
conversation reading "שחרר כאן כדי לצרף לשיחה". The panel's own drop handler was
the only thing taking it off — and a drop on the composer is kept from reaching
it, on purpose. So dropping onto the composer attached the file and left the
sheet up for good: no drag is in flight any more to raise a dragleave, and
nothing else was coming to clear it. Dropping on the big area was fine and
dropping on the strip at the bottom "froze the screen", which is one bug
wearing the shape of two. Both markers come down in one place now (Chat._dndMark),
ahead of every way out of onDrop — including the two that attach nothing.

The harness does not call the handlers. It builds the listener graph the page
really builds — composer inside panel inside document, with bubbling and
stopPropagation — dispatches one event and counts. Verified to fail: remove the
stopPropagation and two cases go red; remove the bind guard and the paste
uploads six times after six opens; let the panel upload on its own again and
the routing check goes red.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "drop_attaches_once.mjs"


def test_a_dropped_file_is_attached_once():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_one_upload_call_stores_one_file(client, admin_id):
    """And the same at the other end of the wire: the client counting its own
    calls proves nothing if the server duplicates. One POST, one stored row —
    checked by the token, since the suite shares a database and counting rows
    by name would count every other test's."""
    from sqlalchemy.orm import Session

    import main as cityos_main
    from models import UploadedFile

    r = client.post("/api/upload",
                    files={"file": ("דוח.pdf", b"%PDF-1.4 content", "application/pdf")},
                    headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 200, r.text
    token = r.json()["url"].rsplit("/", 1)[-1]
    with Session(cityos_main.engine) as db:
        rows = db.query(UploadedFile).filter(UploadedFile.token == token).all()
    assert len(rows) == 1, f"one upload produced {len(rows)} rows"
    assert rows[0].size == len(b"%PDF-1.4 content")


def test_a_comment_keeps_the_attachment_once(client, admin_id):
    """The last place a double could appear: the message itself. Two uploads of
    the same file are two attachments — that is a person attaching it twice —
    but one upload must never become two entries on the comment."""
    from sqlalchemy.orm import Session

    import main as cityos_main
    from models import Comment

    bid = client.post("/api/boards", json={"name": "לוח צירופים",
                                           "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    up = client.post("/api/upload",
                     files={"file": ("קובץ.pdf", b"x", "application/pdf")},
                     headers={"X-CityOS-User": str(admin_id)}).json()

    r = client.post(f"/api/tasks/{tid}/comments",
                    json={"actor_id": admin_id, "content": "מצורף", "attachments": [up]})
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        c = db.query(Comment).filter(Comment.id == r.json()["id"]).first()
        assert len(c.attachments) == 1, c.attachments
        assert c.attachments[0]["url"] == up["url"]
