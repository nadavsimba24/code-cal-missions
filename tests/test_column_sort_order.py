"""מיון עמודות סטטוס ועדיפות — לפי הסדר של הלוח.

Sorting the status column used to read the underlying enum value, which got
three things wrong at once, all of them visible inside a group:

  * a board-defined status tied with the status it behaves as — both are
    "in_progress" underneath, so their order came out arbitrary;
  * an item with nothing chosen sorted as its group's status instead of last;
  * the order was the enum's, not the one the admin set in "ניהול סטטוסים",
    so "בהמתנה" landed after "הושלם".

These run the real functions out of frontend/index.html in node, with a stub
board — no browser, no jsdom, so the gate needs nothing beyond node itself.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

# the ordering rules and everything they lean on
WANTED = ["boardStatusList", "boardStatusMap", "statusKeyOf", "statusOrder",
          "boardPriorityList", "boardPriorityMap", "priorityKeyOf", "prioOrder"]


def _extract(name):
    """The source of one top-level `function name(...)` declaration."""
    m = re.search(r"^function %s\(" % re.escape(name), APP_JS, re.M)
    assert m, f"{name}() is gone from index.html — did it get renamed?"
    i, depth, started = m.start(), 0, False
    while i < len(APP_JS):
        if APP_JS[i] == "{":
            depth += 1
            started = True
        elif APP_JS[i] == "}":
            depth -= 1
            if started and depth == 0:
                return APP_JS[m.start():i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces in {name}()")


def _run(board, tasks, key):
    """Sort values for `tasks` on column `key`, as the browser would compute them."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    consts = "\n".join(m.group(0) for m in
                       re.finditer(r"^const (?:STATUS|PRIORITY) = \{.*?^\};", APP_JS, re.M | re.S))
    src = (consts + "\n" + "\n".join(_extract(n) for n in WANTED) + "\n"
           + "const st=" + json.dumps({"board": board}, ensure_ascii=False) + ";\n"
           + "const fn=" + ("statusOrder" if key == "status" else "prioOrder") + ";\n"
           + "console.log(JSON.stringify("
           + json.dumps(tasks, ensure_ascii=False) + ".map(t=>fn(t))));")
    res = subprocess.run([node, "-e", src], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


BOARD = {
    "statuses": [
        {"key": "in_progress", "label": "בתהליך", "color": "#fdab3d", "base": "in_progress"},
        {"key": "review", "label": "בבדיקה", "color": "#579bfc", "base": "review"},
        {"key": "on_hold", "label": "בהמתנה", "color": "#808080", "base": "on_hold"},
        {"key": "x_supplier", "label": "ממתין לספק", "color": "#a25ddc", "base": "in_progress"},
    ],
    "priorities": [
        {"key": "high", "label": "גבוהה", "color": "#fdab3d", "base": "high"},
        {"key": "low", "label": "נמוכה", "color": "#579bfc", "base": "low"},
        {"key": "x_burning", "label": "בוער", "color": "#bb3354", "base": "high"},
    ],
}

# what a "בביצוע" group actually holds: the active statuses, a board-defined
# one that behaves as in_progress, and an item nobody has chosen for
IN_PROGRESS_GROUP = [
    {"status": "in_progress", "custom_fields": {}},
    {"status": "review", "custom_fields": {}},
    {"status": "on_hold", "custom_fields": {}},
    {"status": "in_progress", "custom_fields": {"status_key": "x_supplier"}},
    {"status": "in_progress", "custom_fields": {"status_unset": True}},
]


def test_statuses_sort_in_the_order_the_board_lists_them():
    vals = _run(BOARD, IN_PROGRESS_GROUP[:3], "status")
    assert vals == [0, 1, 2]        # בתהליך, בבדיקה, בהמתנה — the board's order


def test_a_board_defined_status_does_not_tie_with_its_base():
    vals = _run(BOARD, [IN_PROGRESS_GROUP[0], IN_PROGRESS_GROUP[3]], "status")
    assert vals[0] != vals[1]
    assert vals == [0, 3]           # "ממתין לספק" sits where the board put it


def test_an_item_with_nothing_chosen_sorts_last():
    vals = _run(BOARD, IN_PROGRESS_GROUP, "status")
    assert vals[-1] == max(vals)
    assert vals[-1] > len(BOARD["statuses"])


def test_the_whole_group_comes_out_in_the_boards_order():
    vals = _run(BOARD, IN_PROGRESS_GROUP, "status")
    order = [x for _, x in sorted(zip(vals, ["בתהליך", "בבדיקה", "בהמתנה",
                                             "ממתין לספק", "טרם הוגדר"]))]
    assert order == ["בתהליך", "בבדיקה", "בהמתנה", "ממתין לספק", "טרם הוגדר"]


def test_a_status_the_board_dropped_sorts_before_the_unset_ones():
    """An item still holding a status the admin removed is not "unchosen"."""
    vals = _run(BOARD, [{"status": "done", "custom_fields": {}},
                        {"status": "in_progress", "custom_fields": {"status_unset": True}}],
                "status")
    assert vals[0] < vals[1]


def test_priorities_follow_the_same_rule():
    vals = _run(BOARD, [{"priority": "high", "custom_fields": {}},
                        {"priority": "low", "custom_fields": {}},
                        {"priority": "high", "custom_fields": {"priority_key": "x_burning"}},
                        {"priority": "medium", "custom_fields": {"priority_unset": True}}],
                "priority")
    assert vals == [0, 1, 2, 999]
