"""Group 7 & 8 — frontend sanity + file upload roundtrip."""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


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


def test_file_upload_and_serve_roundtrip(client):
    """Uploaded files are stored in the DB and served back (persist across instances)."""
    r = client.post("/api/upload", files={"file": ("note.txt", b"hello-cityos", "text/plain")})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("/api/files/")
    g = client.get(url)
    assert g.status_code == 200 and g.content == b"hello-cityos"
    assert client.get("/api/files/nope").status_code == 404


def test_chat_file_delete_and_permissions(client):
    """A chat attachment appears in the item's files, can be deleted by its
    uploader (removing it from the comment + files list + the stored blob), and a
    different non-privileged user is refused."""
    # upload a file, attach it via a comment authored by user 1 (board-1 admin)
    up = client.post("/api/upload", files={"file": ("doc.txt", b"bye-cityos", "text/plain")}).json()
    url = up["url"]
    r = client.post("/api/tasks/1/comments", json={"content": "here", "user_id": 1,
                                                   "attachments": [{"name": "doc.txt", "url": url}]})
    cid = r.json()["id"]
    try:
        files = client.get("/api/tasks/1/files").json()["files"]
        assert any(f["url"] == url for f in files)
        # a non-privileged, non-uploader user cannot delete it
        r = client.post("/api/tasks/1/files/delete", json={"user_id": 5, "url": url})
        assert r.status_code == 403
        # the uploader deletes it → gone from the list and the blob is removed
        r = client.post("/api/tasks/1/files/delete", json={"user_id": 1, "url": url})
        assert r.status_code == 200, r.text
        files = client.get("/api/tasks/1/files").json()["files"]
        assert not any(f["url"] == url for f in files)
        assert client.get(url).status_code == 404
    finally:
        client.delete(f"/api/comments/{cid}?user_id=1")
