"""The wait an import makes you sit through.

The report was that the machine seems to hang while a file is being uploaded.
It is not the upload and it is not the server: a 259-item monday export takes
0.10s to import and 0.18s to read back. What holds the screen is the browser
laying out every row of the new board in one go — and a main thread building a
grid cannot repaint or answer a click while it does it, so the tab looks dead.

That render is not made faster here; it is made visible. The timings below are
the measurement that says which part to cover, and they double as a guard: if
the server side ever becomes the slow part, this is where it shows up.

The cover itself lives in tests/frontend/import_busy.mjs.
"""
import json
import pathlib
import shutil
import subprocess
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "import_busy.mjs"
H = {"X-CityOS-User": "1", "host": "localhost"}


def _big_export(n=259):
    """A board the size of the one being migrated, in monday's own shape."""
    labels = ["מעוניינים", "בטיפול", "נחתם"]
    items = [{"id": str(i), "name": f"לקוח {i}",
              "group": {"id": "topics", "title": "בעבודה"},
              "column_values": [
                  {"id": "s", "type": "status", "column": {"title": "סטטוס"},
                   "text": labels[i % len(labels)]},
                  {"id": "t", "type": "text", "column": {"title": "איש קשר"},
                   "text": f"איש קשר {i}"},
                  {"id": "e", "type": "email", "column": {"title": "דוא\"ל"},
                   "text": f"c{i}@muni.il"},
                  {"id": "d", "type": "date", "column": {"title": "עודכן"},
                   "text": "2026-09-14", "value": json.dumps({"date": "2026-09-14"})},
              ]} for i in range(n)]
    return json.dumps({"data": {"boards": [{
        "id": "6204255781", "name": "לקוחות",
        "groups": [{"id": "topics", "title": "בעבודה"}],
        "items_page": {"cursor": None, "items": items}}]}}, ensure_ascii=False).encode()


def test_the_server_is_not_the_part_that_is_slow(client):
    """If this ever fails, the cover is hiding a real problem rather than an
    unavoidable one, and the fix moves to the server."""
    raw = _big_export()
    t0 = time.monotonic()
    r = client.post("/api/boards/import",
                    files={"file": ("response.json", raw, "application/json")}, headers=H)
    took = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert r.json()["items"] == 259
    assert took < 5.0, f"importing 259 items took {took:.1f}s on the server"


def test_reading_the_imported_board_back_is_not_slow_either(client):
    raw = _big_export()
    bid = client.post("/api/boards/import",
                      files={"file": ("response.json", raw, "application/json")},
                      headers=H).json()["id"]
    t0 = time.monotonic()
    board = client.get(f"/api/boards/{bid}?user_id=1", headers=H).json()
    took = time.monotonic() - t0
    assert len(board["tasks"]) == 259
    assert took < 5.0, f"reading 259 items back took {took:.1f}s"


def test_the_wait_is_stated_while_it_happens_and_never_left_on_screen():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
