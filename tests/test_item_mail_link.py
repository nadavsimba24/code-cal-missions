"""The button in the mail, and where it lands.

The two item mails — "שוייכת לרשומה" and "תוייגת בשיחה" — are written to
somebody who is not looking at the board. The button is therefore the whole of
the feature: it has to open the board AND the conversation on that record, from
a cold browser, through the sign-in round trip.

What is pinned here is the contract between the two halves: the address the
server writes into the mail has to be the one the client's router reads. They
live in different files and nothing but this says they are the same thing.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

import main as cityos_main

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _href(subject_and_html):
    return re.search(r'href="([^"]+)"', subject_and_html[1]).group(1)


def test_both_mails_link_to_the_record_not_to_the_front_door(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://missions.test")
    for build in (cityos_main._item_assigned_mail, cityos_main._item_mention_mail):
        href = _href(build("רינה", "דנה", "פריט", "לוח", 7, 412))
        assert href == "https://missions.test/#/board/7/item/412", href


def test_the_address_in_the_mail_is_the_one_the_router_reads():
    """Server-side string, client-side regex, two files. The mail is useless if
    they drift, and nothing else in the suite would notice."""
    i = SRC.index("const Router={")
    router = SRC[i:SRC.index("\n};", i)]
    board = re.search(r"h\.match\((/board[^;]+?/)\)", router)
    item = re.search(r"h\.match\((/\\/item[^;]+?/)\)", router)
    assert board and item, \
        "the router's deep-link patterns are no longer where this can read it"
    href = _href(cityos_main._item_assigned_mail("רינה", "דנה", "פריט", "לוח", 7, 412))
    frag = href.split("#", 1)[1]
    bm = re.search(board.group(1)[1:-1].replace("\\d", "[0-9]"), frag)
    im = re.search(item.group(1)[1:-1].replace("\\d", "[0-9]"), frag)
    assert bm and im, f"the router does not recognise the link the mail sends: {href}"
    assert (bm.group(1), im.group(1)) == ("7", "412")


def test_the_mail_link_survives_the_sign_in_round_trip():
    """Sign-in bounces through Entra and back. The record is in the fragment,
    and a loginUrl that forwarded only the path would drop it — landing every
    mailed person on the home screen after they authenticate."""
    m = re.search(r"function loginUrl\(next\)\{(.*?)\n\}", SRC, re.S)
    assert m, "loginUrl moved"
    assert "location.hash" in m.group(1), \
        "the sign-in redirect drops the fragment, which is where the record is"


def test_a_link_that_cannot_be_followed_says_which_way_it_failed():
    """Driven harness: tests/frontend/deep_link.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "deep_link.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_entry_no_longer_swallows_a_deep_link():
    """enterApp used to fall through to the last board when the link named one
    this person cannot see — the mailed link then opened the wrong board in
    silence. One road in now, and it is openDeepLink."""
    m = re.search(r"async function enterApp\(\)\{(.*?)\n\}", SRC, re.S)
    assert m, "enterApp moved"
    body = m.group(1)
    assert "openDeepLink" in body
    assert "Chat.open" not in body, "the deep link is opened in two places again"
