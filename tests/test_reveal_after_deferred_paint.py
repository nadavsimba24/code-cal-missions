"""Group — a link from a mail lands ON the record, not merely near it.

Clicking a notification inside the app takes the board to the record it names:
the row is scrolled to and highlighted behind the conversation. The button in
the "שוייכת לרשומה" / "תוייגת בשיחה" mails opened the conversation and left the
board where it was — the record was somewhere below, unseen, and the two ways in
behaved differently for no reason anybody could see.

The reason was the board's own paint. Only the first group is built when a board
opens; the rest arrive a frame later, behind a spacer. The jump asked for its
row in between, found nothing in the document, and gave up without a word. From
a notification that rarely showed, because a notification usually points at the
board already on screen and already drawn in full. From a mail the board is
always opened by the jump itself, so it showed every time.

The reveal now outlives that half-painted board: it is remembered and finished
by the deferred paint. The behaviour of the two entry points is the same because
it is the same code — see Chat.revealOpenRow / Chat.finishReveal.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_deferred_paint_finishes_the_jump_it_interrupted():
    """Driven harness: tests/frontend/reveal_after_deferred_paint.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "reveal_after_deferred_paint.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_half_painted_board_still_calls_back():
    """The fix is two halves in two places, and the far one is a line inside an
    unrelated-looking render. Deleting it puts the bug back in silence, so it is
    named here: the deferred paint must finish the reveal, not only re-mark the
    row."""
    assert "Chat.markOpenRow(); Chat.finishReveal();" in SRC, \
        "the deferred paint no longer finishes a pending reveal"
    assert "finishReveal(){" in SRC and "this._reveal=id;" in SRC, \
        "the pending-reveal mechanism is gone"


def test_both_ways_in_ask_for_the_same_jump():
    """A notification and a mail link are one behaviour: both open the record
    centred. If one of them stops passing `center`, they drift apart again."""
    assert SRC.count("Chat.open(taskId,{center:true})") >= 1, \
        "the notification no longer centres the record"
    assert SRC.count("Chat.open(itemId,{center:true})") >= 1, \
        "the deep link no longer centres the record"
