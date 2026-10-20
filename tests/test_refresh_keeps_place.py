"""רענון הדפדפן משאיר אותך באותו לוח ובאותה סביבה.

Where you are is two things, and only one of them was being kept. The open
board has been written to localStorage for a long time; the workspace never
was — it lived in st.env and nowhere else, so a reload started from nothing and
Env.load defaulted to the primary one.

With a board open that was invisible: the URL carries #/board/N, and opening
the board pulls its workspace along behind it. The moment there is no board in
the URL — the home screen, a cleared hash, a workspace switched into but not
yet opened into — the reload landed in the primary workspace, and the
remembered board was then measured against THAT workspace and thrown away for
not belonging to it. A board in another department reopened as some board in
the shared one.

One thing is deliberately unchanged: with no remembered workspace at all the
entry behaves exactly as before, which is what keeps a new user — invited to a
single board in somebody else's department — opening in the workspace everybody
shares. Remembering is the record of a choice; its absence is not a choice, and
tests/test_primary_env_entry.py still pins that.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_workspace_is_written_down_wherever_it_changes():
    """Two places change it: picking one in the switcher, and opening a board
    that belongs to another. A reload is only as good as the less careful of
    the two."""
    assert "localStorage.setItem('cc_env'" in SRC, "the workspace is still not kept"
    m = re.search(r"  select\(id\)\{(.*?)\},", SRC, re.S)
    assert m and "rememberEnv()" in m.group(1), \
        "switching workspace is forgotten on reload"
    m = re.search(r"function followBoardEnv\(boardId\)\{(.*?)\n\}", SRC, re.S)
    assert m and "rememberEnv()" in m.group(1), \
        "opening a board elsewhere does not record where it took you"


def test_the_workspace_is_restored_before_the_board_is_chosen():
    """Order matters and is the whole bug: the board is chosen out of the
    active workspace, so reading cc_board while the primary one is active is
    what dropped a board belonging anywhere else."""
    m = re.search(r"async function enterApp\(\)\{(.*?)\n\}", SRC, re.S)
    assert m, "enterApp moved"
    body = m.group(1)
    assert "rememberedEnvId()" in body
    # the CODE, not the comment that explains it — the prose names cc_board
    # first on purpose
    assert body.index("rememberedEnvId()") < body.index("localStorage.getItem('cc_board')"), \
        "the board is chosen before the workspace is restored"


def test_the_restore_is_not_performed_in_front_of_her():
    """Coming back to the same place is not enough — it must not be watchable.

    The restore was correct and visible: loadBoards painted the sidebar first,
    while no workspace was known yet (Env.active() null, so the board list read
    "אין לוחות שהוזמנת אליהם" over a full account), then Env.load drew the
    primary workspace's name into the switcher, and only then did the
    remembered workspace — or the one the board in the URL belongs to — replace
    it and the boards appear. Three paints on every refresh, two of them of
    somewhere she is not, and on a cold server slow enough to read.

    So the entry settles where it is first and draws once. The counting is in
    tests/frontend/refresh_keeps_place.mjs; what is pinned here is the shape
    that makes it possible."""
    m = re.search(r"async function enterApp\(\)\{(.*?)\n\}", SRC, re.S)
    assert m, "enterApp moved"
    body = m.group(1)
    assert "loadBoards({render:false})" in body, \
        "the boards paint the sidebar themselves again, before there is a workspace"
    assert body.count("renderSidebar()") == 1, \
        "the entry paints the sidebar more than once"
    # Env.ensure, not Env.load: a render asks for the workspaces too, and the
    # two callers share one request rather than issuing one each.
    assert "Env.load()" not in body, \
        "the entry loads the workspaces itself, past the one-request guarantee"
    assert body.index("Env.ensure()") < body.index("renderSidebar()"), \
        "the sidebar is painted before the workspaces are known"
    # the workspace a link leads to is resolved before that paint, not by
    # openDeepLink afterwards
    assert body.index("followBoardEnv(r.boardId)") < body.index("renderSidebar()"), \
        "a link to a board elsewhere draws the remembered workspace first"
    # and the two requests still travel together — this cost no round trip
    assert "await Promise.all([" in body


def test_a_refresh_comes_back_to_the_same_place():
    """Driven harness: tests/frontend/refresh_keeps_place.mjs.

    Verified to fail: drop rememberEnv() from Env.select and three cases go
    red; drop it from followBoardEnv and two do; remove the restore from
    enterApp and four do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "refresh_keeps_place.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
