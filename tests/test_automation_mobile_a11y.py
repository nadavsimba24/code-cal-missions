"""סעיף 15 — שימוש בנייד ונגישות, driven harness.

On a phone the module is readable and not writable, except for the one write
somebody picks up a phone to make: stopping a rule that is misbehaving, which
asks first. Everything else — the keyboard, the names a screen reader reads,
a state that is never only a colour, the sentence as one continuous line, and
Hebrew with Latin values inside it — is checked in
tests/frontend/automations_mobile_a11y.mjs.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_module_is_usable_on_a_phone_and_with_a_keyboard():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automations_mobile_a11y.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_page_declares_its_direction_and_language():
    """RTL is the page's, not a stylesheet's guess — and a document that does
    not say which language it is in is read aloud in the wrong one."""
    head = SRC[:4000]
    assert 'dir="rtl"' in head, head[:200]
    assert 'lang="he"' in head, head[:200]


def test_escape_is_bound_once_and_globally():
    """A second global handler would close the dialog twice — and the second
    close lands on whatever opened underneath it."""
    assert SRC.count("document.addEventListener('keydown',e=>{") == 1
