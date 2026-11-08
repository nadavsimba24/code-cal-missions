"""עמודת קבצים: משלושה קבצים ומעלה — שלושה אייקונים לפי סוג, ואז +X.

A files cell drew one chip per file, and a chip is a paperclip plus the first
nine letters of the name. Three of them wrap the grid row onto three lines and
still say nothing: three columns of "דוח בטיחו…" tell a person neither what
the files are nor how many there are, which is the whole of what the column is
for at a glance.

From three up the cell collapses — the first three as a type icon apiece (PDF
red, Excel green, an image blue …) and a +X for whatever is left. The names
are not gone: they are all in the hover, which travels in data-tipf so our own
box answers at once and keeps one name per line, rather than in title, where
the browser waits a second and a half and runs them together.

What is easy to lose here is the remove. The chips each carried an ×; the
collapsed strip has no room for one, so the strip opens a list — every name in
full, each a link, each with its own ×, and a "העלה קובץ" at the bottom. Take
that list away and a cell holding three files becomes a cell nothing can be
taken out of.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _src():
    return INDEX.read_text(encoding="utf-8")


def test_three_is_where_the_cell_stops_spelling_names_out():
    """Three, not four: three clipped names is already the state nobody can
    read, so three is where the icons take over."""
    src = _src()
    assert "if(files.length>=3){" in src


def test_the_icon_says_what_the_file_is():
    """A paperclip on everything is the same cell it was before, with fewer
    letters. The point of collapsing is that the TYPE survives it."""
    src = _src()
    table = src[src.index("const FILE_TYPE_ICONS=[") : src.index("function fileTypeIcon")]
    for icon in (
        "fa-file-pdf",
        "fa-file-word",
        "fa-file-excel",
        "fa-file-powerpoint",
        "fa-file-image",
        "fa-file-video",
        "fa-file-audio",
        "fa-file-zipper",
        "fa-file-code",
        "fa-file-lines",
    ):
        assert icon in table, f"no icon for {icon}"
    # the palette variables, not hand-picked hexes — invariant 7, and purple
    # in particular is not ours to use
    assert "#" not in table, table
    assert "var(--red)" in table and "var(--green)" in table


def test_the_type_is_worked_out_the_way_the_chat_works_it_out():
    """A file saved from the clipboard arrives named "קובץ-<ts>" with no
    extension on it, and its type is only in the MIME the server recorded.
    Chat.fileExt already falls back to that — a second, simpler split('.')
    here would show those files as the blank fa-file."""
    src = _src()
    fn = src[src.index("function fileTypeIcon(f){") :]
    fn = fn[: fn.index("\n}")]
    assert "Chat.fileExt(f&&f.name,f&&f.type)" in fn, fn


def test_the_hover_is_ours_and_not_the_browsers():
    """data-tipf, not title: an element carrying both answers twice — ours at
    once and the browser's a second and a half later, on top of it."""
    src = _src()
    strip = src[src.index('<span class="file-icons"') :]
    strip = strip[: strip.index("`+add")]
    assert "data-tipf=" in strip
    assert " title=" not in strip, strip


def test_a_collapsed_cell_can_still_lose_a_file():
    """The per-chip × is not drawn in the collapsed strip, so if the list it
    opens ever goes away, a cell holding three files holds them for good."""
    src = _src()
    assert 'onclick="openFilesList(event,' in src
    pop = src[src.index("function buildFilesPop(pop,taskId,colId){") :]
    pop = pop[: pop.index("\nasync function removeFileFromList")]
    assert "removeFileFromList(event," in pop, pop
    assert "uploadFileCell(" in pop, pop


def test_the_collapsed_files_cell(client):
    """Driven harness: tests/frontend/files_cell_collapses.mjs.

    Verified to fail: move the threshold to `files.length>=4` and five cases
    go red.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "files_cell_collapses.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
