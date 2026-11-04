"""תיבת כתיבת ההודעה גדלה עם מה שנכתב בה.

The composer was 44px and stayed there however long the message got, so
writing anything substantial meant composing through a three-line window —
scrolling back and forth to re-read your own sentence before sending it. The
only way out was the drag handle, which is a thing you have to know is there.

It follows the text now, up to a share of the window, and scrolls past that:
a composer that eats the conversation it belongs to has stopped being a
composer.

The behaviour itself is exercised in tests/frontend/chat_composer_grows.mjs,
where the functions can actually be run against a textarea whose scrollHeight
moves. What is pinned HERE is the wiring that decides whether any of it ever
happens — which is the half that broke before: a feature hooked onto four of
the five places that change the text reads as "it works, usually".
"""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def test_the_behaviour_in_the_browser():
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" /
                                    "chat_composer_grows.mjs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_it_is_hooked_where_every_change_already_goes():
    """Typing, the bullet and emoji buttons, a restored draft, opening a
    comment for editing — all five already call syncHL, so hooking the growth
    there is what keeps the list complete when a sixth is added."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("  syncHL(){")
    body = src[i:src.index("\n  },", i)]
    assert "this.grow();" in body, body
    # the five callers, still calling it
    assert src.count("this.syncHL()") + src.count("Chat.syncHL()") >= 5


def test_the_scroll_handler_does_not_resize():
    """Resizing from inside a scroll handler is how a textarea ends up
    fighting itself: the resize moves the scroll, which resizes again."""
    src = INDEX.read_text(encoding="utf-8")
    assert 'onscroll="Chat.syncHLScroll()"' in src
    i = src.index("  syncHLScroll(){")
    body = src[i:src.index("\n  },", i)]
    assert "grow()" not in body, body


def test_the_box_still_has_a_floor_and_a_handle():
    """The CSS minimum is what an empty composer is, and the drag handle is
    not taken away — somebody who wants it bigger than the text still may."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.index(".composer textarea{")
    rule = src[i:src.index("}", i)]
    assert "min-height:44px" in rule, rule
    assert "resize:vertical" in rule, rule
