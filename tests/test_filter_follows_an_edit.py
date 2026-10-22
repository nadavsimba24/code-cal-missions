"""הסינון עוקב אחרי עריכה — a row edited out of the filter leaves the board.

A filter can be answered by the server, and that answer is a LIST OF ITEM IDS.
A list of ids is a photograph: it cannot know that one of the items in it has
since been edited. Filtering a board by סטטוס "בדיקה" and setting a row to
"נבדק ותקין" left the row sitting on screen, because its id was still in the
answer — and the opposite was the same bug the other way round, a row edited
INTO the filter staying hidden until something forced a reload.

The fix is not a new rule about statuses. A write to an item retires the
server's answer: the board falls back to the local engine, which is reading the
values that were just typed, and a fresh answer is asked for once the writing
stops. The behaviour is checked in tests/frontend/filter_follows_an_edit.mjs;
what is checked here is that the retirement is wired to the one place every
write actually leaves through, because a dozen call sites each remembering to
do it is a dozen chances for the next one to forget.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_board_follows_an_edit_out_of_the_filter():
    """Driven harness: tests/frontend/filter_follows_an_edit.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "filter_follows_an_edit.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_every_write_leaves_through_the_one_door():
    """api() is that door. The status picker, a people cell, a drag between
    groups, the item panel, a bulk edit — a dozen places change a cell and all
    of them go out through here, so this is where the answer is retired."""
    i = SRC.index("const api = async (p,o)=>{")
    body = SRC[i:SRC.index("return r.json();};", i)]
    assert "advWrote(p,o)" in body, \
        "a write no longer retires the server's filter answer"


def test_somebody_elses_edit_retires_it_too():
    """A change arriving over the event stream is fetched with a GET, so
    nothing retires the answer on the way in. Without this, the row another
    person moved out of the filter stayed on this screen."""
    i = SRC.index("  async apply(){")
    body = SRC[i:SRC.index("\n  find(id){", i)]
    assert "advAnswerStale()" in body, \
        "a live change no longer retires the server's filter answer"


def test_the_filters_own_question_is_not_a_write():
    """It is a POST, and a rule written as "any POST" would have had the
    filter retiring its own answer and asking again, forever."""
    i = SRC.index("function advWrote(")
    body = SRC[i:SRC.index("\n}", i)]
    assert r"\/api\/tasks" in body, "the test for a write no longer names the item endpoint"
    assert "'GET'" in body, "a read now counts as a write"


def test_an_answer_overtaken_by_a_write_is_refused():
    """An answer asked for before a write describes the board before it.
    Storing it would put the stale list back a moment after it was dropped."""
    i = SRC.index("async function advAskServer(")
    body = SRC[i:SRC.index("\n}", i)]
    assert "_advWrites" in body, "a reply can no longer tell that it was overtaken"


def test_the_two_halves_disagreeing_never_shows_an_empty_board():
    """The server's list can only REMOVE rows in the browser's own mode —
    those are the rows this browser already holds. Removing every one of them
    while the engine here matched some is not an answer: it is a server that
    has not been restarted onto this version, or a column one of them knows
    about and the other does not. An empty board is the one outcome that looks
    like a correct answer and is not, and on screen it is unarguable — the
    filter panel goes on counting the items the board holds while the board
    shows none. That is exactly how a stale backend reached a user."""
    i = SRC.index("function applyFilters(")
    body = SRC[i:SRC.index("\nfunction ", i + 10)]
    assert "advDisagreed()" in body, \
        "an empty answer from the server can silently empty the board again"
    assert "theirs.length || !mine.length" in body, \
        "a cut that genuinely matches nothing no longer shows nothing"
    i = SRC.index("function advDisagreed(")
    note = SRC[i:SRC.index("\n}", i)]
    assert "_advSplit" in note, "the warning fires on every render again"
    assert "toast(" in note, "the disagreement is back to being silent"
