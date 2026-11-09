"""מסך של אורח נושא את שמו, ומסרב להדפיס את עצמו.

The request was "do not let a guest take a screenshot". That cannot be done.
A page cannot see Cmd+Shift+4, cannot see the operating system's capture tool,
cannot see a screen recording, and cannot see a phone pointed at the monitor —
and a script that claims to block screenshots catches the PrintScreen key on
Windows and nothing else, which on a Mac is nothing at all. Shipping one would
have been a lock on a door that is not there.

What is built instead is the pair that answers the same worry:

* `clean_screen` — off for אורח, so their screen carries their name, their
  address and the date across everything. The screenshot still happens; it is
  no longer anonymous, which is what makes an onward leak traceable.
* `print_board` — off for אורח. Printing is "save as PDF" in every browser,
  which is the whole board as a file, and it is the one copy the page is asked
  about before it is made.

Neither has a server leg, and this file pins that they do not pretend to: the
browser owns the print dialogue and the operating system owns the pixels. The
screen's half is tests/frontend/guest_screen_is_marked.mjs.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SCREEN_ONLY = ("print_board", "clean_screen")


def _matrix(client):
    return client.get("/api/role-permissions").json()


def test_the_two_are_in_the_matrix_with_a_name_to_show(client):
    d = _matrix(client)
    keys = {c["key"]: c["he"] for c in d["capabilities"]}
    for cap in SCREEN_ONLY:
        assert cap in keys, cap
        assert keys[cap], f"{cap} has no label, and an unlabelled row is unusable"


def test_a_guest_starts_with_a_marked_screen_and_no_printing(client):
    m = _matrix(client)["matrix"]
    for cap in SCREEN_ONLY:
        assert m["guest"][cap] is False, cap
        for role in ("manager", "member", "viewer", "admin"):
            assert m[role][cap] is True, (role, cap)


def test_an_administrator_can_hand_them_back(client, admin_id):
    """Which is the reason they are capabilities and not a rule in the code: an
    organisation whose guests print legitimately says so in the matrix."""
    try:
        for cap in SCREEN_ONLY:
            r = client.put("/api/role-permissions", json={
                "actor_id": admin_id, "role": "guest", "capability": cap, "allowed": True})
            assert r.status_code == 200, r.text
        m = _matrix(client)["matrix"]
        assert all(m["guest"][cap] is True for cap in SCREEN_ONLY)
    finally:
        for cap in SCREEN_ONLY:
            client.put("/api/role-permissions", json={
                "actor_id": admin_id, "role": "guest", "capability": cap, "allowed": False})


def test_the_server_does_not_pretend_to_enforce_either_of_them(client):
    """The honest half. Both live entirely in the browser, and a `_cap` check on
    some route would read as a guarantee the server cannot make — somebody would
    later rely on it. CAP_HE says so in words; this says so in code."""
    for cap in SCREEN_ONLY:
        assert not re.search(rf'_cap\([^)]*["\']{cap}["\']', MAIN), \
            f"{cap} is being checked on the server, where it cannot be enforced"
    assert "no web page has ever been able to stop" in MAIN, \
        "the note explaining why these two are screen-only is gone"


def test_the_screen_carries_the_mark_and_refuses_the_print():
    """Driven harness: tests/frontend/guest_screen_is_marked.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "guest_screen_is_marked.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
