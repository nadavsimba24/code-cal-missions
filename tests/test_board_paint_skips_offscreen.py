"""A board that is three to seven groups should not be painted all at once.

Only the first group is anywhere near the screen when a board opens, and the
expensive part of a row is not its text — it is the input fields inside it. A
board of 670 items in three groups holds some fourteen thousand of them, and
they were all laid out before anything appeared.

`content-visibility: auto` lets the browser skip layout and paint for the
groups that are off screen, and nothing about the DOM changes: every row is
still in the document, so refreshRow, the drag handlers, Chat.markOpenRow and
the browser's own find-in-page all still work. What it needs to behave is an
honest height estimate per group — otherwise the scrollbar lies and then jumps
— and that estimate is written by vTable.

Also pinned here: the loader is not frantic. A 34px circle at one turn a
second reads as panic rather than progress.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_a_group_is_painted_only_when_it_is_needed():
    m = re.search(r"\n\.group\{([^}]*)\}", SRC)
    assert m, "the .group rule is gone"
    rule = m.group(1)
    assert "content-visibility:auto" in rule, (
        "off-screen groups are being laid out and painted again")
    assert "contain-intrinsic-size" in rule, (
        "without a fallback size an unrendered group measures zero and the "
        "scrollbar is wrong before anything scrolls")


def test_every_group_states_the_height_it_will_turn_out_to_be():
    """A shared default cannot be right for a group of 2 and a group of 223."""
    assert "contain-intrinsic-size:auto ${est}px" in SRC, (
        "vTable stopped writing a per-group estimate")
    # the estimate has to follow the row count, not be a constant
    est = re.search(r"const est=shut\?\d+:\(g\.tasks\.length\*(\w+)\+(\w+)\)", SRC)
    assert est, "the estimate no longer scales with the number of rows"
    for name in est.groups():
        assert re.search(r"\b" + name + r"\s*=\s*\d+", SRC), f"{name} is not defined"
    assert "auto " in SRC[SRC.index("contain-intrinsic-size:auto ${est}px"):][:40], (
        "the estimate must be `auto <length>`, so the browser replaces it with "
        "the real size once the group has been rendered once")


@pytest.mark.parametrize("name,least", [("sp", 1.2)])
def test_the_loader_is_not_frantic(name, least):
    m = re.search(r"\.spin\{[^}]*animation:" + name + r"\s+([\d.]+)s", SRC)
    assert m, "the spinner's animation is gone"
    secs = float(m.group(1))
    assert secs >= least, (
        f"the loader turns once every {secs}s — fast enough to read as a fault "
        "rather than as progress")
