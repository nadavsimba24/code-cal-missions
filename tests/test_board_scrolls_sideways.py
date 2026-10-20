"""A board wider than the window still scrolls sideways.

`content-visibility: auto` on `.group` turns on PAINT containment as well, and
it does so permanently — not only while a group is off screen and skipped. Paint
containment clips whatever leaves the element's box. The table is
`width:max-content` and a board with its columns out is wider than any window,
so a plain full-width `.group` clipped every column past the edge; layout
containment then hid that overflow from `#view`, the element that actually
scrolls, so the horizontal scrollbar disappeared too. Half the board became
unreachable — not hidden behind a scrollbar, gone.

That the sideways scroll is the design and not an accident is written all over
the sheet: `.grp-stick` and `.tbl` are both `width:max-content`, `.gh-in` is
`position:sticky; inset-inline-start:0` so a group's name stays pinned while the
columns slide past it, and `#view.scrolled-x` exists to fade in the shadow on
the frozen first column.

So the group's box grows to its contents, and the per-group height estimate is
confined to the block axis — as the shorthand it would otherwise claim `est`
pixels of *width* for a group nobody has scrolled to yet, and a 223-row group
asks for some nine thousand of them.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _group_rule():
    m = re.search(r"\n\.group\{([^}]*)\}", SRC)
    assert m, "the .group rule is gone"
    return m.group(1)


def test_the_containment_boundary_is_as_wide_as_what_it_holds():
    """Nothing to clip means nothing clipped, and #view sees the overflow."""
    rule = _group_rule()
    if "content-visibility:auto" not in rule:
        return   # no containment, no clipping — the scroll needs no help
    assert "min-width:max-content" in rule or "width:max-content" in rule, (
        "`.group` paints with containment but is sized by its container, so a "
        "table wider than the window is clipped and the board cannot be "
        "scrolled sideways")


def test_the_scrolling_element_still_scrolls_both_ways():
    m = re.search(r"\n#view\{([^}]*)\}", SRC)
    assert m, "#view is gone"
    assert re.search(r"overflow:\s*auto", m.group(1)), (
        "#view is the board's scrollport in both axes")


def test_the_height_estimate_does_not_claim_a_width_as_well():
    """The shorthand sets both axes. A skipped group must measure empty across,
    or the scrollbar stretches to a width nothing is painted at."""
    rule = _group_rule()
    if "content-visibility:auto" not in rule:
        return
    assert "contain-intrinsic-height" in rule, (
        "the per-group estimate has to name the block axis")
    assert "contain-intrinsic-width:none" in rule, (
        "the inline axis has to stay unset, or a skipped group claims its "
        "height estimate as a width too")
    # and the per-group inline style has to agree with the rule
    assert "contain-intrinsic-size:auto ${est}px" not in SRC, (
        "vTable writes the shorthand inline, and an inline style beats the "
        "sheet — so the width axis is set after all")


def test_the_group_name_stays_pinned_while_the_columns_slide():
    """What the sideways scroll is for: the frozen name and first column.

    Both come to rest against the edge the board is CLIPPED at rather than the
    one its content box ends at — they are pulled out by #view's own inline
    padding, which is the strip the columns behind them used to peek through.
    See tests/test_pinned_column.py."""
    assert re.search(r"\n\.gh-in\{[^}]*position:sticky[^}]*"
                     r"inset-inline-start:calc\(-1 \* var\(--view-pad", SRC), (
        "the group name no longer sticks")
    assert "#view.scrolled-x" in SRC, (
        "the frozen-column shadow is driven by horizontal scroll on #view")
