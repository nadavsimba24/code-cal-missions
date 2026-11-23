"""A board admin moves a sub-item column by dragging its header, as on items.

Asked for on 2026-11-23. The drag existed — startColDrag was written for the
item header and the sub-item header alike, and saves a sub-item order through
saveSubCols — but it looked for the OLD sub-item header (tr.subhead with
td[data-subcol]). The sub-item header moved into its own <thead> as
tr.sub-h > th[data-subcol] and was drawn with no grip, so there was nothing to
grab. And the grips were bound when the board rendered, while a sub-item panel
is built later, when its parent is opened — so even a grip would have been
dead in exactly the panels people open.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _fn(name):
    at = SRC.index(f"function {name}(")
    depth = 0
    for k in range(SRC.index("{", at), len(SRC)):
        if SRC[k] == "{":
            depth += 1
        elif SRC[k] == "}":
            depth -= 1
            if not depth:
                return SRC[at:k + 1]


def _head(admin):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    js = "\n".join([
        "const esc=s=>String(s==null?'':s);",
        "const subGroupCheckHTML=()=>'',subSortBtn=()=>'',subResizerHTML=()=>'',subColLabel=c=>c.title;",
        _fn("subHeadHTML"),
        "const cols=[{id:'item',title:'תת-פריט'},{id:'c1',kind:'custom',title:'סטטוס'},{id:'c2',kind:'custom',title:'תאריך'}];",
        f"process.stdout.write(subHeadHTML(7,cols,{json.dumps(admin)}));",
    ])
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_an_admin_gets_a_grip_on_every_sub_item_column_but_the_name():
    html = _head(True)
    cells = re.findall(r'<th class="sub-h-cell" data-subcol="([^"]+)">(.*?)</th>', html, re.S)
    assert [c for c, _ in cells] == ["c1", "c2"]
    assert all("col-grip" in body for _, body in cells), html
    name = re.search(r'<th class="sub-h-name".*?</th>', html, re.S).group(0)
    assert "col-grip" not in name, "the name column is fixed first, as on items"


def test_a_member_who_is_not_an_admin_gets_no_grip():
    assert "col-grip" not in _head(False)


def test_the_drag_knows_the_sub_item_header_as_it_is_drawn_now():
    body = _fn("startColDrag")
    assert "row.classList.contains('sub-h')" in body
    assert "closest('th[data-colkey],[data-subcol]')" in body
    assert "isSub?'[data-subcol]'" in body
    assert "saveSubCols(ids," in body


def test_a_panel_opened_after_the_render_is_draggable_too():
    assert re.search(
        r"document\.addEventListener\('pointerdown',ev=>\{\s*const g=ev\.target&&ev\.target\.closest"
        r"&&ev\.target\.closest\('tr\.sub-h \.col-grip'\);\s*if\(g&&isBoardAdmin\(\)\)startColDrag\(ev,g\);",
        SRC)
    # and the render-time binding no longer also takes the sub-item grips,
    # which would start every sub-item drag twice
    assert "root.querySelectorAll('th[data-colkey] .col-grip')" in _fn("initColReorder")
