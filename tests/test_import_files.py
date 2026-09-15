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


# ── the other half of the trip: out of here, and back ───────────────────────
# A file cell shows the file's NAME, and that is all a grid can hold. Exported
# as a grid and imported back, a board's attachments were names with nothing
# behind them — while the bytes had never left the database. The addresses now
# ride on a sheet of their own, the way the conversation already does.

def _board_with_a_file(client, admin_id, content=b"%PDF-1.4 spec", name="spec.pdf"):
    """A board, an item, a file column, and a real uploaded file in it."""
    b = client.post("/api/boards", json={"name": "לוח עם קובץ", "actor_id": admin_id}).json()
    cols = [{"id": "col_doc", "type": "files", "title": "מסמך"}]
    r = client.patch(f"/api/boards/{b['id']}", json={"columns": cols, "actor_id": admin_id})
    assert r.status_code == 200, r.text
    up = client.post(f"/api/upload?actor_id={admin_id}",
                     files={"file": (name, content, "application/pdf")}).json()
    t = client.post("/api/tasks", json={"board_id": b["id"], "title": "פריט עם מסמך",
                                        "actor_id": admin_id}).json()
    client.patch(f"/api/tasks/{t['id']}", json={
        "custom_fields": {"col_doc": [{"name": up["name"], "url": up["url"]}]},
        "actor_id": admin_id})
    return b, t, up


def _xlsx_of(client, admin_id, board_id, columns, rows):
    r = client.post(f"/api/boards/{board_id}/export/xlsx",
                    json={"columns": columns, "rows": rows, "actor_id": admin_id})
    assert r.status_code == 200, r.text
    return r.content


def _sheet(raw, title):
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(raw), data_only=True)
    try:
        if title not in wb.sheetnames:
            return None
        return [list(r) for r in wb[title].iter_rows(values_only=True)]
    finally:
        wb.close()


def test_the_export_carries_each_files_address_on_a_sheet_of_its_own(client, admin_id):
    b, t, up = _board_with_a_file(client, admin_id)
    raw = _xlsx_of(client, admin_id, b["id"],
                   ["פריט", "מסמך"], [{"level": 1, "cells": ["פריט עם מסמך", "spec.pdf"]}])
    rows = _sheet(raw, "קבצים")
    assert rows, "the workbook has no file sheet"
    assert [str(c or "") for c in rows[0]] == ["מספר מזהה", "פריט", "עמודה", "שם הקובץ", "כתובת"]
    body = [r for r in rows[1:] if r and r[1]]
    assert len(body) == 1
    assert body[0][1] == "פריט עם מסמך" and body[0][2] == "מסמך"
    assert body[0][3] == "spec.pdf" and body[0][4] == up["url"]


def test_a_board_exported_from_here_comes_back_with_its_files_openable(client, admin_id):
    """The whole question: after the import, is the file a file — the way it is
    when someone uploads one — or a name?"""
    b, t, up = _board_with_a_file(client, admin_id, content=b"%PDF-1.4 the real spec")
    raw = _xlsx_of(client, admin_id, b["id"],
                   ["פריט", "מסמך"], [{"level": 1, "cells": ["פריט עם מסמך", "spec.pdf"]}])
    d = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": ("board.xlsx", raw,
                                    "application/vnd.openxmlformats-officedocument."
                                    "spreadsheetml.sheet")},
                    data={"actor_id": admin_id})
    assert d.status_code == 200, d.text
    d = d.json()
    assert d["report"]["files_reused"] == 1, d["report"]
    assert d["report"]["files_imported"] == 0, "the bytes never left — nothing to fetch"

    # the column is a file column again, not a column of names
    with Session(cityos_main.engine) as db:
        board = db.query(cityos_main.Board).filter(cityos_main.Board.id == d["id"]).first()
        col = next(c for c in (board.settings or {})["columns"] if c.get("title") == "מסמך")
        assert col["type"] == "files", col
        task = db.query(Task).filter(Task.board_id == d["id"],
                                     Task.title == "פריט עם מסמך").first()
        cell = (task.custom_fields or {})[col["id"]]
    assert cell == [{"name": "spec.pdf", "url": up["url"]}], cell
    # and it opens
    got = client.get(f"{up['url']}?user_id={admin_id}")
    assert got.status_code == 200 and got.content == b"%PDF-1.4 the real spec"


def test_a_file_whose_bytes_are_no_longer_here_keeps_its_name(client, admin_id):
    """An address pointing at a blob this database does not hold is not a file;
    filed as one it would be a chip that 404s."""
    rows = [["מספר מזהה", "פריט", "עמודה", "שם הקובץ", "כתובת"],
            ["", "פריט", "מסמך", "old.pdf", "/api/files/" + "f" * 32]]
    d = _import_xlsx(client, admin_id, [["פריט", "הערה"], ["פריט", "משהו"]], rows)
    assert d["report"]["files_gone"] == 1
    assert d["report"]["files_reused"] == 0
    with Session(cityos_main.engine) as db:
        task = db.query(Task).filter(Task.board_id == d["id"]).first()
        cell = [v for k, v in (task.custom_fields or {}).items() if isinstance(v, list)][0]
    assert cell == [{"name": "old.pdf", "url": ""}], cell


def _import_xlsx(client, admin_id, board_rows, file_rows=None, talk_rows=None):
    """A workbook built by hand: the board sheet, and the sheets beside it."""
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "לוח"
    for r in board_rows:
        ws.append(list(r))
    if file_rows:
        fs = wb.create_sheet("קבצים")
        for r in file_rows:
            fs.append(list(r))
    if talk_rows:
        tsheet = wb.create_sheet("שיחות")
        for r in talk_rows:
            tsheet.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/boards/import?actor_id={admin_id}",
                    files={"file": ("board.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument."
                                    "spreadsheetml.sheet")},
                    data={"actor_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_monday_asset_link_in_a_cell_becomes_a_named_file_not_a_wall_of_text(client, admin_id):
    """monday's Excel export writes the addresses, several to a cell. As text
    that is an unreadable cell; as a file column it is what it is."""
    a = "https://mashcal.monday.com/protected_static/1/resources/2/%D7%AA%D7%9B%D7%A0%D7%95%D7%9F.docx"
    b = "https://mashcal.monday.com/protected_static/1/resources/3/map.jpg"
    d = _import_xlsx(client, admin_id, [["פריט", "קובץ תוכן"], ["פריט א", f"{a}, {b}"]])
    with Session(cityos_main.engine) as db:
        board = db.query(cityos_main.Board).filter(cityos_main.Board.id == d["id"]).first()
        col = next(c for c in (board.settings or {})["columns"] if c.get("title") == "קובץ תוכן")
        assert col["type"] == "files", col
        task = db.query(Task).filter(Task.board_id == d["id"]).first()
        cell = (task.custom_fields or {})[col["id"]]
    assert [f["name"] for f in cell] == ["תכנון.docx", "map.jpg"]
    assert [f["url"] for f in cell] == [a, b]
    # the bytes are behind monday's login, so they are not fetched and not faked
    assert d["report"]["files_linked"] == 2
    assert d["report"]["files_imported"] == 0


def test_an_ordinary_link_column_is_not_turned_into_an_attachment(client, admin_id):
    d = _import_xlsx(client, admin_id,
                     [["פריט", "קישור לדף"], ["פריט א", "https://www.hod-hasharon.muni.il/"]])
    with Session(cityos_main.engine) as db:
        board = db.query(cityos_main.Board).filter(cityos_main.Board.id == d["id"]).first()
        col = next(c for c in (board.settings or {})["columns"] if c.get("title") == "קישור לדף")
    assert col["type"] == "text", col


def test_a_file_sheet_naming_an_item_that_is_not_here_is_reported(client, admin_id):
    rows = [["מספר מזהה", "פריט", "עמודה", "שם הקובץ", "כתובת"],
            ["", "פריט שאינו בקובץ", "מסמך", "x.pdf", "/api/files/" + "a" * 32]]
    d = _import_xlsx(client, admin_id, [["פריט", "הערה"], ["פריט א", "משהו"]], rows)
    assert d["report"]["files_items_unmatched"] == ["פריט שאינו בקובץ"]


def test_the_login_page_monday_answers_with_is_not_stored_as_the_file(client, admin_id,
                                                                     monkeypatch):
    """An asset link that needs a session answers 200 with monday's HTML login
    page. Stored, that is a .docx that opens and is not the file."""
    import urllib.request

    class _Resp:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self, n=None):
            return b"<!DOCTYPE html><html>login</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cityos_main._IMPORT_OPENER, "open", lambda *a, **k: _Resp())
    assert cityos_main._fetch_import_file(MONDAY_HOST + "/spec.docx") is None


def test_the_report_says_what_became_of_the_files_in_a_sheet():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    for marker in ("files_reused", "files_linked", "files_gone"):
        assert marker in src, f"the report says nothing about {marker}"


def test_a_monday_address_carrying_an_unescaped_space_is_still_a_file(client, admin_id):
    """monday writes the file's real name into the address without escaping it:
    ".../resources/1375082189/דף הבית.docx" has a space in it. Requiring an
    address with no whitespace matched none of the seven file columns in her
    board — 634 attachments read as text."""
    u = "https://mashcal.monday.com/protected_static/654106/resources/1375082189/דף הבית.docx"
    assert cityos_main._imp_asset_urls(u) == [u]
    assert cityos_main._imp_infer_type([u]) == "files"
    assert cityos_main._imp_file_name(u) == "דף הבית.docx"


def test_two_addresses_in_one_cell_are_two_files(client, admin_id):
    a = "https://mashcal.monday.com/protected_static/1/resources/2/a b.jpg"
    b = "https://mashcal.monday.com/protected_static/1/resources/3/c.jpg"
    assert cityos_main._imp_asset_urls(f"{a}, {b}") == [a, b]


def test_a_file_on_a_sub_item_arrives_with_its_bytes_too(client, admin_id, monkeypatch):
    """A file cell names an asset; the asset's real name and its fetchable link
    are carried by the ROW the cell sits on. The export asked for `assets` on the
    items and not on their sub-items, so a sub-item's files resolved against
    nothing and came in as bare names."""
    url = f"{MONDAY_HOST}/sub-spec.pdf"
    _serve(monkeypatch, {url: (b"%PDF-1.4 the sub-item's spec", "application/pdf")})
    item = _item("פריט אב", cols=[_filecol("מסמך", "parent.pdf")], assets=[])
    item["subitems"] = [{
        "id": "s1", "name": "תת־פריט",
        "column_values": [{"id": "sf1", "type": "file", "column": {"title": "מסמך"},
                           "text": "sub-spec.pdf"}],
        "assets": [{"id": "7", "name": "sub-spec.pdf", "public_url": url}],
        "updates": []}]
    d = _import(client, admin_id, _resp([item])).json()
    assert d["subitems"] == 1
    assert d["report"]["files_imported"] == 1, d["report"]

    with Session(cityos_main.engine) as db:
        sub = db.query(Task).filter(Task.board_id == d["id"],
                                    Task.parent_id.isnot(None)).first()
        cell = [v for v in (sub.custom_fields or {}).values() if isinstance(v, list) and v][0]
    assert cell[0]["name"] == "sub-spec.pdf"
    assert cell[0]["url"].startswith("/api/files/"), cell
    token = cell[0]["url"].rsplit("/", 1)[-1]
    got = client.get(f"/api/files/{token}?user_id={admin_id}")
    assert got.status_code == 200 and got.content == b"%PDF-1.4 the sub-item's spec"


def test_the_export_query_asks_for_the_sub_items_assets():
    import pathlib
    q = (pathlib.Path(__file__).resolve().parent.parent / "backend"
         / "monday_export.graphql").read_text(encoding="utf-8")
    subs = [b for b in q.split("subitems {")[1:]]
    assert len(subs) == 2, "both queries have a sub-items block"
    for b in subs:
        block = b.split("\n      updates")[0].split("\n        updates")[0]
        assert "assets { id name public_url }" in block, "a sub-item's files have no link"
        assert "FileValue" in block, "a sub-item's file cell names no asset"
