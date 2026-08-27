"""On a phone, views are chosen from a dropdown rather than a scrolling strip.

The strip is still rendered — the breakpoint decides which of the two is shown,
so rotating the phone switches between them with no re-render and the two can
never disagree about which view is current. Both halves are checked: the markup
renderTabs produces (under node, as tests/test_selection_bar.py does) and the
CSS that swaps them.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "view_dropdown.mjs"
CSS = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _mobile_block():
    q = "@media (max-width:820px){"
    i = CSS.index(q)
    j, depth = i + len(q), 1
    while depth:
        if CSS[j] == "{":
            depth += 1
        elif CSS[j] == "}":
            depth -= 1
        j += 1
    return CSS[i:j]


def test_the_dropdown_is_built_correctly():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_strip_gives_way_to_the_dropdown_on_a_narrow_screen():
    block = _mobile_block()
    assert re.search(r"\.tabs \.tab,\.tab-add-wrap\{display:none\}", block), \
        "the tab strip is still shown on a phone"
    assert re.search(r"\.tab-dd\{[^{}]*display:flex", block), \
        "the view picker is not shown on a phone"


def test_the_picker_is_not_a_native_select():
    """A native <select> draws its option list itself, outside this stylesheet's
    reach — which is how it ended up rendering with no readable text."""
    assert 'class="tab-dd" onclick="openViewPicker' in CSS, \
        "the view picker is not the app's own popover"
    assert '<select class="tab-dd"' not in CSS, \
        "the native select is back"


def test_the_dropdown_does_not_show_on_a_wide_screen():
    """Otherwise both pickers appear at once."""
    m = re.search(r"^\.tab-dd\{([^{}]*)\}", CSS, re.M)
    assert m and "display:none" in m.group(1), \
        "the dropdown has no desktop default — it would show alongside the tabs"


def test_the_dropdown_is_a_thumb_sized_target():
    m = re.search(r"\.tab-dd\{([^{}]*)\}", _mobile_block())
    assert m and "min-height:44px" in m.group(1).replace(" ", ""), \
        "the view picker is smaller than the platform minimum tap target"
