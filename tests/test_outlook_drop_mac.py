"""Dragging a mail attachment into the conversation — on a Mac as on a PC.

It worked on Windows and did nothing on a Mac, and the cause was two handlers
bound to the same panel with different rules. Windows Outlook puts the bytes on
the drag (CF_HDROP → the browser reports "Files"); macOS Outlook hands over a
promise and no bytes. The panel's handler tested for "Files" alone, so on a Mac
it refused the drag at dragover — and a dragover that does not preventDefault
makes the browser cancel the drop before it happens. No drop event, no cursor,
no message. Only the composer strip at the bottom carried the wider rule.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_panel_and_the_composer_cannot_drift_apart_again():
    """The bug was two acceptance rules for one panel. There is one now, and
    one handler behind it."""
    m = re.search(r"  bindDnd\(\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "bindDnd moved"
    body = m.group(1)
    assert "_isImport" in body, "the panel judges drags by a rule of its own again"
    assert "this.onDrop(e)" in body, "the panel handles a drop by itself again"
    assert "types||[]).includes('Files')" not in body, \
        "the Windows-only test is back — this is the macOS bug exactly"


def test_a_drag_is_judged_by_where_it_came_from_not_by_what_it_names():
    """At `dragover` the browser hides the bytes, and for a drag it cannot
    interpret it reports no types at all — which is what macOS Outlook is. A
    rule written against type names answers "no" there, the dragover does not
    preventDefault, and the browser cancels the drop before it happens: no
    drop zone, no cursor, no drop event, nothing on screen. That is the whole
    of "I drag from the mail and nothing changes".

    So the rule is where the drag came from, not what it calls itself."""
    m = re.search(r"  _isImport\(e\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "_isImport moved"
    body = m.group(1)
    assert "sortable" in body, "nothing tells our own row-drag apart from a file"
    assert "return true" in body, "the gate still judges a drag by its type names"
    for named in ("'files'", "filegroupdescriptor", "text/html", "public."):
        assert named not in body.lower(), \
            f"the type list is back ({named}) — that is the macOS bug exactly"


def test_pasting_is_offered_as_the_way_round_it():
    """The promise cannot be made into bytes by any amount of JavaScript. ⌘C in
    Outlook puts the real file on the clipboard, and that path has to be named
    where somebody stuck will read it."""
    assert "⌘C" in SRC and "⌘V" in SRC, "nothing tells a Mac user what does work"
    m = re.search(r"  onPaste\(e\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "onPaste moved"
    body = m.group(1)
    assert "startsWith('image/')" in body, "the screenshot path is gone"
    assert "kind!=='file'" in body, "paste takes images only again"


def test_dragging_a_mail_in_behaves_the_same_on_both_platforms():
    """Driven harness: tests/frontend/outlook_drop_mac.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "outlook_drop_mac.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_an_eml_and_a_msg_can_actually_be_uploaded(client, admin_id):
    """The client turns a macOS drag into a .eml and uploads it. An upload
    endpoint that refuses that extension would make the whole path pointless,
    and the refusal would arrive as "שגיאה בהעלאה" with no reason."""
    for name, ctype in (("הדוח הרבעוני.eml", "message/rfc822"),
                        ("mail.msg", "application/vnd.ms-outlook")):
        r = client.post("/api/upload",
                        files={"file": (name, b"Subject: test\r\n\r\n<p>x</p>", ctype)},
                        headers={"X-CityOS-User": str(admin_id)})
        assert r.status_code == 200, f"{name} → {r.status_code} {r.text}"


def test_a_mac_is_told_the_route_that_works_without_having_to_fail_first():
    """Measured, not assumed: a window-level listener bound before any element
    printed nothing at all for a drag out of Outlook on macOS, while a drag out
    of Finder printed and attached. The browser raises no drag event for a
    promised file, so the composer's "drop here" overlay can never appear and
    the after-the-fact message can never be reached. The one thing left is to
    say it up front, where somebody will read it before trying."""
    assert "_isMac()" in SRC, "nothing distinguishes the platform the drag fails on"
    m = re.search(r"  composerHTML\(mode,cid\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "composerHTML moved"
    body = m.group(1)
    assert "this._isMac()" in body, "the hint is shown to everybody, or to nobody"
    assert "⌘C" in body and "⌘V" in body
    assert "comp-mac-hint" in SRC and ".comp-mac-hint{" in SRC


def test_the_drag_diagnostic_stays():
    """It is what turned three rounds of guessing into one answer. The next
    person with a drag that does nothing should not have to add it again."""
    assert "[drag]" in SRC
    assert "addEventListener('dragenter'" in SRC, \
        "the earliest point a drag can be seen is no longer watched"


def test_paste_is_listened_for_where_a_paste_actually_travels():
    """Two mistakes in a row, and the second is the subtle one.

    Paste was bound on the textarea (onpaste=…), so ⌘V did nothing unless the
    caret was inside it — and after dragging a file around, it is not. Moving
    it to #chat-panel did not fix that: a paste event is dispatched to the
    FOCUSED element and bubbles up from there, and with focus on <body> the
    event never passes the panel at all. document is the one node it always
    passes."""
    assert 'onpaste="' not in SRC, "the text box handles paste again — and only it"
    m = re.search(r"  bindDnd\(\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "bindDnd moved"
    body = m.group(1)
    assert "document.addEventListener('paste'" in body, \
        "a paste with focus outside the panel is lost again"
    assert "panel.addEventListener('paste'" not in body
    assert "classList.contains('open')" in body, \
        "a paste is taken even when no conversation is open"


def test_there_is_a_route_that_depends_on_neither_a_drag_nor_the_caret():
    """A drag can be refused by the browser before any code runs, and ⌘V goes
    to whatever is focused. A click is neither: it is a user gesture, which is
    exactly what reading the clipboard requires."""
    m = re.search(r"  async pasteFromClipboard\(\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "the clipboard button is gone"
    body = m.group(1)
    assert "navigator.clipboard.read" in body
    assert "canComment()" in body, "it attaches for someone who may only read"
    # Every way it can fail has to be said, and said CORRECTLY — a wrong
    # reason is worse than none. navigator.clipboard is undefined outside a
    # secure context, and blaming the browser for the address is exactly the
    # misdiagnosis this whole investigation kept producing.
    assert "isSecureContext" in body, "an http origin is reported as an old browser"
    assert "NotAllowedError" in body, "a blocked permission fails silently"
    assert "⌘V" in body, "the dead end does not point anywhere"
    assert 'onclick="Chat.pasteFromClipboard()"' in SRC, "nothing calls it"


def test_a_paste_that_carried_nothing_at_all_says_so():
    """Text pastes as text and says nothing — that is an ordinary paste. A
    clipboard holding neither a file nor text, right after somebody was told
    "copy it in Outlook and press ⌘V", is the silence this investigation was
    about: it looks exactly like the shortcut not being wired up, which is
    what it twice was."""
    m = re.search(r"  onPaste\(e\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "onPaste moved"
    body = m.group(1)
    assert "hasText" in body, "an empty clipboard is indistinguishable from a text paste"
    assert "אין קובץ בלוח" in body
