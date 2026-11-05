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
    assert "contain-intrinsic-height" in rule, (
        "without a fallback size an unrendered group measures zero and the "
        "scrollbar is wrong before anything scrolls")
    # the BLOCK axis by name, never the `contain-intrinsic-size` shorthand: that
    # one sets both, and a group sized by its contents in the inline axis then
    # claims its height estimate as a width too — measured at 9000px of empty
    # horizontal scroll. See tests/test_board_scrolls_sideways.py.
    assert "contain-intrinsic-size" not in rule, (
        "the shorthand is back, and it leaks the height estimate into the width")


def test_every_group_states_the_height_it_will_turn_out_to_be():
    """A shared default cannot be right for a group of 2 and a group of 223.

    The BLOCK axis only, and spelled as the longhand on purpose: as the
    `contain-intrinsic-size` shorthand the same number also claimed that many
    pixels of WIDTH for a skipped group, which stretched the horizontal
    scrollbar to a width nothing was drawn at. See
    tests/test_board_scrolls_sideways.py.
    """
    assert "contain-intrinsic-height:auto ${est}px" in SRC, (
        "vTable stopped writing a per-group estimate")
    # ...and it is the one the reserve spacer uses, asked of the same function.
    # Two copies of this sum drift apart, and a wrong estimate does not fail —
    # it jumps.
    assert "const est=groupEst(g);" in SRC, (
        "groupHTML works the estimate out for itself again instead of asking "
        "groupEst, so the group and the spacer that reserves its room can "
        "disagree")
    body = _fn_body("groupEst")
    # the estimate has to follow the row count, not be a constant
    assert re.search(r"tasks\.length\*(\w+)\(\)", body), (
        "the estimate no longer scales with the number of rows")
    fn = re.search(r"tasks\.length\*(\w+)\(\)", body).group(1)
    assert f"function {fn}(" in SRC, f"{fn} is not defined"
    assert re.search(r"\bGROUP_CHROME_EST\s*=\s*\d+", SRC), "GROUP_CHROME_EST is not defined"


def _fn_body(name):
    """The source of one top-level function, by brace counting."""
    i = SRC.index(f"function {name}(")
    j = SRC.index("{", i)
    depth, k = 0, j
    while k < len(SRC):
        if SRC[k] == "{":
            depth += 1
        elif SRC[k] == "}":
            depth -= 1
            if depth == 0:
                return SRC[j:k + 1]
        k += 1
    raise AssertionError(f"{name} does not close")


def test_a_group_says_what_its_own_furniture_costs():
    """The jump that was left, and why it was only on SOME boards.

    One constant stood in for furniture that is not the same on every board.
    A group whose number column has values in it draws a סה"כ row under the
    rows — on the boards that have a number column and on no others — and it
    was counted nowhere: a dozen such groups are some six hundred pixels the
    board does not know it owns, and it spends them one group at a time as
    each comes into view. An open sub-item panel is a nested table, and it was
    counted as nothing at all.
    """
    body = _fn_body("groupEst")
    assert "groupHasSum(g)" in body and "sumRowEst()" in body, (
        "a group that totals a number column draws a סה\"כ row the estimate "
        "does not know about, and the board jumps by one row per group")
    assert "subPanelEst(t)" in body, (
        "an open sub-item panel is a whole nested table and the estimate "
        "counts it as nothing")
    # groupHasSum has to answer the same question groupSumRowHTML answers by
    # building one — the number columns, and whether any of them is filled in
    ask = _fn_body("groupHasSum")
    assert "customColumns()" in ask and "'number'" in ask, (
        "groupHasSum no longer asks about the number columns")


def test_the_spacer_reserves_the_gaps_between_the_groups_too():
    """A margin is outside the box the estimate describes.

    The spacer stands in for a dozen groups, so it stands in for the gaps
    under them as well — without them the board is a dozen gaps shorter than
    it will be, and spends the difference the moment the groups arrive.
    """
    assert "n+groupSlot(g)" in SRC, "the reserve no longer goes through groupSlot"
    slot = _fn_body("groupSlot")
    assert "groupEst(g)" in slot and "GROUP_GAP" in slot, (
        "the slot is no longer the group plus the gap under it")
    gap = re.search(r"GROUP_GAP=(\d+)", SRC)
    assert gap, "GROUP_GAP is gone"
    css = re.search(r"\n\.group\{([^}]*)\}", SRC).group(1)
    real = re.search(r"margin-bottom:(\d+)px", css)
    assert real and int(real.group(1)) == int(gap.group(1)), (
        f"the gap under a group is {real and real.group(1)}px on screen but "
        f"the spacer reserves {gap.group(1)}px")


def test_the_furniture_is_corrected_from_the_screen_as_well():
    """A constant drifts; a measurement does not — and not only for the row."""
    body = _fn_body("learnRowHeight")
    for part in ("m.chrome=chrome", "m.sum=Math.round(sh)"):
        assert part in body, f"learnRowHeight stopped measuring: {part}"
    assert "function learnSubPanel(" in SRC and "learnSubPanel(el,m)" in SRC, (
        "nothing measures a real sub-item panel")
    assert "function learnFoldedGroup(" in SRC and "learnFoldedGroup(el,m)" in SRC, (
        "nothing measures a folded group — the written-down 64 went on being "
        "claimed after the gap under a group moved from 22px to 16px")
    # ...and a measurement must not land between the two halves of one render:
    # the spacer and the groups it reserves room for are drawn a frame apart,
    # and sizing them from different numbers is the jump itself.
    assert "_estNext=m" in body, (
        "learnRowHeight applies its measurement at once instead of holding it "
        "for the next render")
    assert "useLatestMeasurements();" in SRC and "function useLatestMeasurements(" in SRC, (
        "nothing promotes the measurement at the start of a render")
    assert "auto " in SRC[SRC.index("contain-intrinsic-height:auto ${est}px"):][:42], (
        "the estimate must be `auto <length>`, so the browser replaces it with "
        "the real size once the group has been rendered once")


def test_the_estimate_matches_the_height_a_row_really_is():
    """The bug this catches, by example.

    The estimate said 37px while `.tbl td` was 46px tall, so every group
    claimed a fifth less room than it needed, grew as it was rendered, and the
    content below it jumped. Note which declaration wins: there are two
    `.tbl td{height:...}` rules and the LAST one in the sheet is the one the
    browser uses.
    """
    heights = [int(h) for h in re.findall(r"\.tbl td\{[^}]*height:(\d+)px", SRC)]
    assert heights, "the row height is no longer declared on .tbl td"
    real = heights[-1] + 1          # + the bottom border
    est = re.search(r"const ROW_H_EST=(\d+)", SRC)
    assert est, "ROW_H_EST is gone"
    got = int(est.group(1))
    assert abs(got - real) <= 2, (
        f"a row is {real}px on screen but the estimate says {got}px — every "
        "group will claim the wrong amount of room and the board will jump as "
        "it renders")


def test_the_estimate_is_corrected_from_the_screen():
    """A constant drifts; a measurement does not."""
    assert "function learnRowHeight(" in SRC, "nothing measures a real row"
    assert "learnRowHeight(el)" in SRC, "the measurement is never taken"
    assert "function rowHeightEst(" in SRC and "rowHeightEst()" in SRC, (
        "the estimate does not consult the measured height")


def test_a_board_switch_says_where_its_time_went():
    """"Still slow" has to be answerable with numbers, from her machine.

    And it has to say WHICH kind of open it was: a board fetched from the
    server and one shown from memory are different numbers, and reading them
    as the same would hide either win.
    """
    for part in ("request ${Math.round(fetchMs)}ms", "render ${Math.round(renderMs)}ms",
                 "on screen after"):
        assert part in SRC, f"the board-open timing no longer reports: {part}"
    for how in ("from the server", "from memory, unchanged", "from memory, then updated"):
        assert f"'{how}'" in SRC, f"the timing line no longer distinguishes: {how}"


@pytest.mark.parametrize("name,least", [("sp", 1.2)])
def test_the_loader_is_not_frantic(name, least):
    m = re.search(r"\.spin\{[^}]*animation:" + name + r"\s+([\d.]+)s", SRC)
    assert m, "the spinner's animation is gone"
    secs = float(m.group(1))
    assert secs >= least, (
        f"the loader turns once every {secs}s — fast enough to read as a fault "
        "rather than as progress")
