"""ניהול מערכת — the six tabs sort, filter and export as one shared table.

The six tabs of the system-administration window had grown six half-tables, and
the first one that learned to sort made the other five look broken. The
behaviour now lives once — a COLS table per tab, sortOf/sortBy/sortRows, a live
search box, a count, and a client-side CSV — and every tab declares its columns
instead. Shared machinery means one mistake breaks all six at once, which is
what the harness run here is for.

Four of its checks are regression guards rather than feature tests:

* `autoRowsHTML` must EXIST. `bodyHTML` routes the automations tab to it and the
  reference was written before the method was; the first admin to click a column
  header on that tab would have got a TypeError and an empty table.
* `repaint()` must not assign to `#sa-body`. The search input lives inside that
  element, so rebuilding it between two keystrokes takes the input out of the DOM
  and the caret with it — the trap the comment on `setAutoQ` has been warning
  about since the automations filter.
* the empty-state `colspan` must equal the real column count. It was a hardcoded
  7 on the users tab, and the moment "מועד הזמנה למערכת" was added the "no
  results" cell stopped spanning the table.
* a blank must sort LAST in both directions. A plain comparator puts the empty
  rows first the moment the arrow flips, and an admin reversing a column wants
  the other end of the data, not a screenful of rows with nothing to say.

A fifth, found in review after the first version of this file was written: the
sort control was the `<th>` itself, wearing `role="button"`. An explicit ARIA
role REPLACES the implicit one, so the cell stopped being a `columnheader` — and
`aria-sort` is honoured only on a columnheader, which meant the sort state
`syncHeads()` so carefully maintains was announced to nobody, and every cell
underneath lost its header association as well. The control is now a native
`<button class="sa-th-btn">` inside a th that is still a th, and the hand-rolled
`thKey` handler went away with the role that made it necessary. The harness
fails if either comes back.

And the invariants the project will not give up on: no purple in the new CSS,
logical properties rather than left/right, a CSV that Excel opens in Hebrew
(BOM, CRLF, every field quoted and every embedded quote doubled) and that it
cannot be made to *execute* — a field opening with = + - or @ is a formula to
Excel, and these are names typed by users.

The backend half of the same feature is pinned by
tests/test_admin_directory_columns.py.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "admin_tabs_sort_search_export.mjs"
INDEX = ROOT / "frontend" / "index.html"


def test_the_admin_tabs_sort_search_and_export_as_one_table():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_toolbar_is_wired_into_every_tab_that_renders_a_table():
    """Every tab paints barHTML — the count, the search box and the export.

    The harness proves the toolbar is right; this proves it is actually there.
    A tab that renders its own header row and forgets the bar looks finished and
    silently has no search, which is how five of the six used to be. The
    automations tab is the one exception and says so in its own comment: its list
    is narrowed server-side, so it carries the richer am-bar instead.
    """
    src = INDEX.read_text(encoding="utf-8")
    for tab, renderer in (("users", "usersHTML(){"),
                          ("guests", "async renderGuests(){"),
                          ("depts", "async renderDepts(){"),
                          ("envs", "async renderEnvs(){"),
                          ("history", "async renderHistory(){")):
        i = src.index(renderer)
        block = src[i:src.index("\n  }", i)]
        assert f"barHTML('{tab}'" in block, f"the {tab} tab paints no toolbar"
        assert f"headHTML('{tab}')" in block, f"the {tab} tab paints no sortable header"
        assert 'id="sa-rows"' in block, f"the {tab} tab has no tbody for repaint() to fill"
    # the automations tab gets its own bar, with the server-side filter and the
    # emergency stop, but still the shared header and the shared tbody
    i = src.index("  paintAutos(){")
    autos = src[i:src.index("\n  }", i)]
    assert "headHTML('autos')" in autos and 'id="sa-rows"' in autos and 'id="sa-count"' in autos


def test_the_whole_window_is_reached_only_by_a_system_admin():
    """Sorting and exporting a directory is still a system-admin screen.

    The feature added an export button to six tabs; none of it may become a way
    in. The one door, SysAdmin.open, still asks for manage_system before it
    renders anything, and the exports read lists this window already fetched.
    """
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("  async open(tab){")
    opener = src[i:src.index("\n  }", i)]
    assert "hasCap('manage_system')" in opener, opener
    assert "רק מנהל מערכת" in opener, opener
