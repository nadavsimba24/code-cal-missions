"""מה שדיאלוג המחיקה מבטיח הוא מה שהשרת עושה.

The confirmation used to end "ולא ניתן לשחזר". That was not a wording
problem, it was false: this product's deletion policy is a recycle bin, the
item sits there for RECYCLE_BIN_DAYS, and somebody who believed the warning
had no reason to go looking for it. The dialog now names the window and the
purge, so the promise is only worth what the server actually honours — which
is what these pin.

Three things, and the third is the one that rots quietly:

  * sixty days is the window, and it is a default the environment can move;
  * an item inside the window is still there and still restorable, and one
    past it is purged the moment a bin is read (there is no scheduler — the
    read is what runs the purge);
  * the number in the sentence is read from the server rather than typed
    into it, so changing RECYCLE_BIN_DAYS cannot leave the dialog promising
    a window nobody keeps.
"""
import datetime
import pathlib
import re
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import Task

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def test_the_window_is_sixty_days():
    """The number the dialog says out loud."""
    assert cityos_main.RECYCLE_BIN_DAYS == 60


def _board_and_item(client, admin_id):
    bid = client.post("/api/boards",
                      json={"name": "לוח סל", "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks",
                      json={"board_id": bid, "title": "פריט",
                            "user_id": admin_id}).json()["id"]
    return bid, tid


def _backdate(task_id, days):
    """Put the deletion that far in the past. Computed from the stored value,
    not from today's date, so this does not depend on the hour it runs at."""
    # The global hook hides deleted rows from every ordinary query, so the
    # bin's own accessor is the one that can see them at all.
    with Session(cityos_main.engine) as db:
        t = cityos_main._deleted_tasks_q(db).filter(Task.id == task_id).first()
        t.deleted_at = t.deleted_at - datetime.timedelta(days=days)
        db.commit()


def _bin_ids(client, bid, admin_id):
    r = client.get(f"/api/boards/{bid}/trash?user_id={admin_id}")
    assert r.status_code == 200, r.text
    return r.json(), [i["id"] for i in r.json()["items"]]


def test_an_item_inside_the_window_is_still_there_and_comes_back(client, admin_id):
    bid, tid = _board_and_item(client, admin_id)
    try:
        client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
        _backdate(tid, cityos_main.RECYCLE_BIN_DAYS - 1)

        body, ids = _bin_ids(client, bid, admin_id)
        assert tid in ids, "an item one day short of the window was already gone"
        # the bin states the window it is keeping to, and the dialog reads it
        assert body["retention_days"] == cityos_main.RECYCLE_BIN_DAYS

        r = client.post(f"/api/tasks/{tid}/restore", json={"actor_id": admin_id})
        assert r.status_code == 200, r.text
        with Session(cityos_main.engine) as db:
            back = cityos_main._deleted_tasks_q(db).filter(Task.id == tid).first()
            assert back is not None and back.deleted_at is None
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_an_item_past_the_window_is_purged_for_good(client, admin_id):
    """"ולאחר מכן ימחקו לצמיתות" — and reading the bin is what performs it."""
    bid, tid = _board_and_item(client, admin_id)
    try:
        client.delete(f"/api/tasks/{tid}?user_id={admin_id}")
        _backdate(tid, cityos_main.RECYCLE_BIN_DAYS + 1)

        _, ids = _bin_ids(client, bid, admin_id)
        assert tid not in ids, "an item past the window was still listed"
        with Session(cityos_main.engine) as db:
            assert cityos_main._deleted_tasks_q(db).filter(Task.id == tid).first() is None, \
                "it left the listing but the row is still in the database"
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_the_dialog_reads_the_window_instead_of_spelling_it_out():
    """A literal 60 in the sentence would survive a change to the server's
    window and go on promising a retention nobody keeps."""
    src = INDEX.read_text(encoding="utf-8")
    assert "function recycleDays()" in src
    # the verb is the same on all three dialogs — one action described with two
    # different words on neighbouring screens reads as two different promises
    assert "המחיקה תנתק" not in src, "a delete dialog still says תנתק"
    assert src.count("המחיקה תסיר") >= 3
    for phrase in ("הפריטים ישמרו בסל המחזור של הלוח למשך ${recycleDays()} יום",
                   "הפריט וכל תת-הפריטים שלו ישמרו בסל המחזור של הלוח למשך ${recycleDays()} יום",
                   "תת-הפריט ישמר בסל המחזור של הלוח למשך ${recycleDays()} יום"):
        assert phrase in src, phrase
    # Scoped to what a dialog actually shows: this file's own prose quotes
    # the old sentence, and so may a comment explaining why it went.
    notes = re.findall(r"note:\s*(?:'[^']*'|`[^`]*`)", src)
    bad = [n for n in notes if "ולא ניתן לשחזר" in n]
    assert not bad, bad


def test_the_note_can_show_two_lines():
    """The note is escaped text in a div, so the second sentence only lands as
    a second line because the rule says so."""
    src = INDEX.read_text(encoding="utf-8")
    note = next(l for l in src.splitlines() if l.startswith(".confirm-note{"))
    assert "white-space:pre-line" in note, note


def test_the_dialog_reads_the_window_off_the_board(client, admin_id):
    """The number in the sentence is the SERVER's, on every screen.

    recycleDays() used to read whichever bin the person happened to have
    opened and fall back to a literal sixty when neither had been — so a board
    opened fresh promised sixty days because the browser said so, not because
    the server did. RECYCLE_BIN_DAYS is environment-settable; the moment
    somebody moved it, that dialog would have been promising a window nobody
    keeps, which is the exact failure this group exists to prevent.
    """
    bid = client.post("/api/boards",
                      json={"name": "לוח חלון", "user_id": admin_id}).json()["id"]
    d = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    assert d["retention_days"] == cityos_main.RECYCLE_BIN_DAYS == 60
    # and the browser prefers it over its own fallback
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("function recycleDays()"):]
    fn = fn[:fn.index("}")]
    assert "st.board && st.board.retention_days" in fn, fn
    assert fn.index("st.board") < fn.index("60"), \
        "the literal fallback is consulted before the server's own answer"


def test_the_bulk_dialog_says_what_it_was_asked_to_say():
    """The wording is a product decision, quoted here so a later edit to the
    sentence is a deliberate one rather than a drift."""
    src = INDEX.read_text(encoding="utf-8")
    for line in ("המחיקה תסיר גם את כל הקישורים הקיימים שלה.",
                 "הפריטים ישמרו בסל המחזור של הלוח למשך ${recycleDays()} יום,"
                 " ולאחר מכן ימחקו לצמיתות."):
        assert line in src, line
    assert "title:'מחיקת פריטים'" in src
    assert "askConfirm(`למחוק ${allowed.length} פריטים?`" in src
