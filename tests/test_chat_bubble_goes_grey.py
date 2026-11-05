"""בועית שיחה שהשתתקה מאפירה, והלוח קובע מתי.

The visible half of "אם לא בוצע עדכון בבועית השיחה — האייקון הופך מכחול
לאפור": a row's conversation badge is blue while the thread is live and grey
once it has been quiet for as long as the board says. Seven days until the
board says otherwise, and the board says otherwise by having a "ללא עדכון
בשיחה" automation switched on — see
tests/test_a_quiet_conversation_greys_the_bubble.py for that half.

The browser's share of it is in tests/frontend/chat_bubble_goes_grey.mjs: only
a blue badge can go grey, the threshold comes off the board, and the greyed
badge says in its title how long it has been. What is checked HERE is the one
thing the browser cannot promise — that the default it falls back to when the
board has not answered is the same number the server grades silence by.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import automations as recipes  # noqa: E402


def test_the_browser_half(capsys):
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" /
                                    "chat_bubble_goes_grey.mjs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
    with capsys.disabled():
        print(r.stdout)


def test_the_browsers_fallback_is_the_servers_default():
    """The number hard-coded in chatStaleDays() is the one the server would
    have sent. They are two places on purpose — the browser draws the first row
    before any board has answered — and a drift between them would be a board
    that greys at one number and chases at another."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    i = src.index("function chatStaleDays(")
    body = src[i:src.index("}", i)]
    assert f"d>0)?d:{recipes.CHAT_STALE_DAYS_DEFAULT}" in body.replace(" ", ""), body
