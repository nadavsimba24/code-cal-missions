"""Group — bringing the files with the board (תמיכה בקבצים בייבוא).

monday's export carries a pre-signed link per attachment. Those links work for
about an hour and then the file is behind monday's auth for good, so the import
is the only moment the bytes can cross. Until now what arrived was a list of
names: enough to see that an item had a spec attached, and useless for opening
it.

Nothing here touches the network — the fetcher is replaced, because a test that
depends on someone's expiring S3 link is a test that fails next week.
"""
import json

from sqlalchemy.orm import Session
import main as cityos_main
from models import Comment, Task, UploadedFile

MONDAY_HOST = "https://files-monday-com.s3.amazonaws.com/1/resources/9"


def _resp(items):
    return json.dumps({"data": {"boards": [{"id": "1", "name": "לוח", "items_page":
                                            {"items": items}}]}}).encode()


def _item(name, cols=(), assets=(), updates=()):
    return {"id": "9" + name, "name": name, "column_values": list(cols),
            "assets": list(assets), "updates": list(updates)}


def _filecol(title, filename):
    """A monday file cell as the export writes one: the name is in the text and
    the link comes off the item's assets."""
    return {"id": "f1", "type": "file", "column": {"title": title}, "text": filename}


def _import(client, admin_id, raw):
    return client.post(f"/api/boards/import?actor_id={admin_id}",
                       files={"file": ("board.json", raw, "application/json")},
                       data={"actor_id": admin_id})


def _serve(monkeypatch, payloads):
    """Stand in for the network: url → (bytes, content_type), or None."""
    calls = []

    def fake(url):
        calls.append(url)
        return payloads.get(url)
    monkeypatch.setattr(cityos_main, "_fetch_import_file", fake)
    return calls


def _cells(board_id):
    with Session(cityos_main.engine) as db:
        return [t.custom_fields or {} for t in
                db.query(Task).filter(Task.board_id == board_id).all()]


def test_a_file_on_an_item_arrives_with_its_bytes(client, admin_id, monkeypatch):
    url = f"{MONDAY_HOST}/spec.docx"
    _serve(monkeypatch, {url: (b"PK\x03\x04 a real docx would be here", "application/pdf")})
    raw = _resp([_item("תיקון מדרכה",
                       cols=[_filecol("מסמך דרישות", "spec.docx")],
                       assets=[{"id": "1", "name": "spec.docx", "public_url": url}])])
    d = _import(client, admin_id, raw).json()
    assert d["files"] == 1 and d["report"]["files_imported"] == 1
    assert d["report"]["files_bytes"] > 0

    cell = next(v for cf in _cells(d["id"]) for k, v in cf.items() if isinstance(v, list) and v)
    assert cell[0]["name"] == "spec.docx"
    assert cell[0]["url"].startswith("/api/files/"), cell
    # and the bytes are really here, served by this app
    token = cell[0]["url"].rsplit("/", 1)[-1]
    with Session(cityos_main.engine) as db:
        row = db.query(UploadedFile).filter(UploadedFile.token == token).first()
    assert row and row.data.startswith(b"PK") and row.size == len(row.data)
    got = client.get(f"/api/files/{token}?user_id={admin_id}")
    assert got.status_code == 200 and got.content == row.data


def test_an_attachment_on_a_message_comes_too(client, admin_id, monkeypatch):
    url = f"{MONDAY_HOST}/photo.jpg"
    _serve(monkeypatch, {url: (b"\xff\xd8\xff a jpeg", "image/jpeg")})
    upd = {"id": "u1", "text_body": "מצורפת תמונה", "created_at": "2026-01-01T09:00:00",
           "creator": {"name": "דנה"},
           "assets": [{"id": "2", "name": "photo.jpg", "public_url": url}]}
    d = _import(client, admin_id, _resp([_item("פריט", updates=[upd])])).json()
    assert d["report"]["files_imported"] == 1
    with Session(cityos_main.engine) as db:
        c = db.query(Comment).join(Task, Task.id == Comment.task_id).filter(
            Task.board_id == d["id"]).first()
    assert c.attachments[0]["url"].startswith("/api/files/")
    assert c.attachments[0]["name"] == "photo.jpg"


def test_a_link_that_has_already_expired_keeps_the_name(client, admin_id, monkeypatch):
    """An hour later that is every link in the file, and a name is still worth
    more than a blank cell."""
    url = f"{MONDAY_HOST}/gone.docx"
    _serve(monkeypatch, {})                     # the fetch returns None for everything
    raw = _resp([_item("פריט", cols=[_filecol("מסמך", "gone.docx")],
                       assets=[{"id": "1", "name": "gone.docx", "public_url": url}])])
    d = _import(client, admin_id, raw).json()
    assert d["report"]["files_imported"] == 0
    assert d["report"]["files_unreachable"] == 1
    cell = next(v for cf in _cells(d["id"]) for k, v in cf.items() if isinstance(v, list) and v)
    assert cell[0]["name"] == "gone.docx" and cell[0]["url"] == url


def test_the_import_stops_fetching_at_its_budget_and_says_so(client, admin_id, monkeypatch):
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_FILES", 2)
    urls = {f"{MONDAY_HOST}/f{i}.txt": (b"x" * 10, "text/plain") for i in range(5)}
    _serve(monkeypatch, urls)
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"f{i}.txt")],
                   assets=[{"id": str(i), "name": f"f{i}.txt",
                            "public_url": f"{MONDAY_HOST}/f{i}.txt"}])
             for i in range(5)]
    d = _import(client, admin_id, _resp(items)).json()
    r = d["report"]
    assert r["files_imported"] == 2, r
    assert r["files_unreachable"] == 3, "the ones past the budget were not accounted for"


def test_a_file_over_the_per_file_ceiling_is_not_stored(client, admin_id, monkeypatch):
    """The real fetcher stops reading past MAX_UPLOAD_BYTES and reports nothing."""
    big = b"x" * (cityos_main.MAX_UPLOAD_BYTES + 1)

    class FakeResp:
        headers = {"Content-Type": "application/zip"}

        def read(self, n=None):
            return big[:n] if n else big

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cityos_main._IMPORT_OPENER, "open", lambda *a, **k: FakeResp())
    assert cityos_main._fetch_import_file(f"{MONDAY_HOST}/huge.zip") is None


# ── the guard on what may be fetched at all ─────────────────────────────────

def test_only_mondays_own_asset_hosts_are_fetched():
    """The URLs come out of a file someone uploaded. Fetching whatever it names
    would let an import point this server at an address inside its own network."""
    ok = ["https://files-monday-com.s3.amazonaws.com/1/x.docx",
          "https://files-monday-com.s3.eu-west-1.amazonaws.com/1/x.docx",
          "https://mashcal.monday.com/protected_static/1/x.docx"]
    bad = ["http://files-monday-com.s3.amazonaws.com/1/x.docx",     # not https
           "https://169.254.169.254/latest/meta-data/",             # cloud metadata
           "https://localhost/secret", "https://10.0.0.5/x",
           "https://evil.example.com/x", "https://monday.com.evil.example.com/x",
           "file:///etc/passwd", ""]
    for u in ok:
        assert cityos_main._fetch_import_file.__doc__      # the real function, not a stub
        parts = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(u)
        assert cityos_main._import_host_allowed(parts.hostname), u
    for u in bad:
        parts = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(u)
        allowed = parts.scheme == "https" and cityos_main._import_host_allowed(parts.hostname)
        assert not allowed, f"{u} would be fetched"


def test_a_redirect_is_refused_rather_than_followed(monkeypatch):
    """An allowed host that bounces the fetch elsewhere is the same hole."""
    h = cityos_main._NoRedirects()
    assert h.redirect_request(None, None, 302, "Found", {}, "https://evil.example.com/x") is None


def test_a_board_with_no_files_reports_none(client, admin_id, monkeypatch):
    _serve(monkeypatch, {})
    d = _import(client, admin_id, _resp([_item("פריט")])).json()
    assert d["files"] == 0 and d["report"]["files_imported"] == 0
    assert d["report"]["files_unreachable"] == 0


def test_the_report_says_what_became_of_the_files():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    for marker in ("files_imported", "files_unreachable", "files_over_budget",
                   "files_expired", "הקישורים בקובץ פגו", "stat(r.files_imported,'קבצים')"):
        assert marker in src, f"the report says nothing about {marker}"


# ── the link's own expiry, read instead of discovered ───────────────────────

def _signed(minted="20260914T105448Z", expires="3600"):
    return (f"{MONDAY_HOST}/x.docx?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            f"&X-Amz-Date={minted}&X-Amz-Expires={expires}&X-Amz-Signature=deadbeef")


def test_an_expired_link_is_recognised_without_a_round_trip():
    """monday's links are S3 signatures carrying when they were minted and for
    how long. 305 of them cost three minutes of 403s before this was read."""
    from datetime import datetime, timedelta, timezone
    minted = datetime(2026, 9, 14, 10, 54, 48, tzinfo=timezone.utc)
    url = _signed()
    assert cityos_main._signed_url_expired(url, now=minted + timedelta(minutes=30)) is False
    assert cityos_main._signed_url_expired(url, now=minted + timedelta(minutes=61)) is True


def test_a_link_with_no_signature_is_left_to_the_fetch():
    assert cityos_main._signed_url_expired(f"{MONDAY_HOST}/x.docx") is False
    assert cityos_main._signed_url_expired("") is False
    assert cityos_main._signed_url_expired(_signed(minted="nonsense")) is False


def test_an_expired_export_is_not_fetched_at_all(client, admin_id, monkeypatch):
    calls = _serve(monkeypatch, {})
    url = _signed(minted="20200101T000000Z")            # long lapsed
    raw = _resp([_item("פריט", cols=[_filecol("מסמך", "x.docx")],
                       assets=[{"id": "1", "name": "x.docx", "public_url": url}])])
    r = _import(client, admin_id, raw).json()["report"]
    assert calls == [], "an expired link was still fetched"
    assert r["files_expired"] == 1 and r["files_unreachable"] == 0


def test_the_import_gives_up_after_a_run_of_failures(client, admin_id, monkeypatch):
    """Whatever the cause, if the first handful cannot be had the rest cannot
    either — and an import must not spend a minute per hundred files proving it."""
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    calls = _serve(monkeypatch, {})                     # everything fails
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"f{i}.txt")],
                   assets=[{"id": str(i), "name": f"f{i}.txt",
                            "public_url": f"{MONDAY_HOST}/f{i}.txt"}])
             for i in range(20)]
    r = _import(client, admin_id, _resp(items)).json()["report"]
    assert len(calls) == 3, f"tried {len(calls)} times before giving up"
    assert r["files_unreachable"] == 20, "the ones it stopped trying are still accounted for"


def test_one_success_resets_the_run(client, admin_id, monkeypatch):
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 2)
    good = f"{MONDAY_HOST}/good.txt"
    _serve(monkeypatch, {good: (b"hello", "text/plain")})
    items = [_item("א", cols=[_filecol("מסמך", "bad1.txt")],
                   assets=[{"id": "1", "name": "bad1.txt", "public_url": f"{MONDAY_HOST}/bad1.txt"}]),
             _item("ב", cols=[_filecol("מסמך", "good.txt")],
                   assets=[{"id": "2", "name": "good.txt", "public_url": good}]),
             _item("ג", cols=[_filecol("מסמך", "bad2.txt")],
                   assets=[{"id": "3", "name": "bad2.txt", "public_url": f"{MONDAY_HOST}/bad2.txt"}])]
    r = _import(client, admin_id, _resp(items)).json()["report"]
    assert r["files_imported"] == 1 and r["files_unreachable"] == 2
