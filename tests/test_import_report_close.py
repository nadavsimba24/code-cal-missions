"""The ✕ of the import report — it asks before discarding the only account of
what the migration did.

The report is built from the response that was imported, and that response is
gone once the modal closes: importing the same file again does not reproduce the
report, it makes a second board. So the ✕ offers the two things people wanted
beside the closing — keep it as a file, or put it in its own window.

The behaviour itself is exercised in tests/frontend/import_report_close.mjs,
under node, against the real functions lifted out of index.html.
"""
import pathlib
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = (HERE.parent / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_report_x_asks_and_a_save_sits_beside_it():
    """The ✕ is re-pointed at the asking, and the saving joins it in the corner.

    "הבנתי" is gone: a footer button that only closes is a second ✕ at the far
    end of a report people scroll, and it was the likelier of the two to be
    clicked — which made losing the report the easiest thing to do here.
    """
    i = SRC.index("function importReport(")
    body = SRC[i:SRC.index("function importReportClose(")]
    assert "st._impReport={title,body}" in body, "the report is kept for the three actions"
    assert "'onclick','importReportClose()'" in body, "the modal's ✕ asks"
    # the word still appears — in the comment saying why the button does not
    assert ">הבנתי<" not in body, "no footer button whose only job is closing"
    assert '<div class="mfoot">' not in body, "and no footer left holding nothing"
    # the save, as an icon in the corner where window actions already live
    assert 'class="modal-act"' in body and "importReportSave()" in body
    assert "fa-file-pdf" in body and 'aria-label="שמירת הדוח כ-PDF"' in body
    assert ".modal-act{position:absolute;top:10px;left:44px" in SRC, \
        "right next to the ✕, same size — it is the same kind of action"


def test_node_drives_the_three_options():
    script = HERE / "frontend" / "import_report_close.mjs"
    r = subprocess.run(["node", str(script)], capture_output=True, text=True)
    if r.returncode and "command not found" in (r.stderr or ""):
        pytest.skip("node is not installed")
    print(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
