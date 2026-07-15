"""Group 7 & 8 — bundled avatar assets + frontend sanity."""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
AVATARS = ROOT / "frontend" / "avatars"


def test_avatar_pool_bundled():
    """The bundled avatar pool has all 30 SVGs on disk."""
    svgs = sorted(AVATARS.glob("*.svg"))
    assert len(svgs) == 30, f"expected 30 avatar SVGs, found {len(svgs)}"


def test_avatars_served(client):
    """Avatar SVGs are served over HTTP with an svg content-type."""
    for name in ("00.svg", "29.svg"):
        r = client.get(f"/avatars/{name}")
        assert r.status_code == 200
        assert "svg" in r.headers.get("content-type", "")


def test_index_served(client):
    """The SPA index is served as HTML and contains its key building blocks."""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    # key building blocks are present
    for marker in ("SysAdmin", "avatarInner", "ownerChipHTML"):
        assert marker in r.text, f"index.html missing '{marker}'"


def test_inline_js_syntax():
    """Run node --check on the app's inline JS. Skips if node is unavailable."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    blocks = [
        m.group(2)
        for m in re.finditer(r"<script([^>]*)>(.*?)</script>", html, re.S)
        if "src=" not in m.group(1) and "importmap" not in m.group(1)
    ]
    assert blocks, "no inline script block found"
    app_js = max(blocks, key=len)
    tmp = ROOT / "tests" / "_inline_check.js"
    tmp.write_text(app_js, encoding="utf-8")
    try:
        res = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
    finally:
        tmp.unlink(missing_ok=True)
