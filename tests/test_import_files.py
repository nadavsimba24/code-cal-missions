"""Group — bringing the files with the board (תמיכה בקבצים בייבוא).

monday's export carries a pre-signed link per attachment. Those links work for
about an hour and then the file is behind monday's auth for good, so the import
is the only moment the bytes can cross. Until now what arrived was a list of
names: enough to see that an item had a spec attached, and useless for opening
it.

Nothing here touches the network — the fetcher is replaced, because a test that
depends on someone's expiring S3 link is a test that fails next week.

Three tests were retired from this file when the attachment fetch moved to a
pooled urllib3 client. They stood in for the network one level lower, by
replacing the opener's own `open` (`_IMPORT_OPENER`) or by calling the redirect
handler (`_NoRedirects`) directly — objects the fetch no longer has, and a test
written against the client's insides breaks again on the next change of client
while proving nothing about what the fetch actually does with the answer. What
they pinned — a body over the per-file ceiling, a redirect that must not be
followed, and monday's login page served as a 200 — is pinned in
tests/test_import_attachment_fetching.py instead, against a real HTTP server on
a real socket and without knowing which client library answers it. Please do
not reintroduce a stub opener here: replacing `_fetch_import_file`, as the rest
of this file does, is the right level for testing what the import does with the
bytes, and that other file is the right level for testing how they are got.
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


def _serve_with_reasons(monkeypatch, answer, why):
    """The same stand-in, saying WHY a fetch came back empty.

    The real fetch leaves its verdict on `_IMPORT_FETCH`, a thread-local, and
    the run-of-failures guard reads it there: "dead" is a 401/403/404/410 or
    monday's sign-in page, and "transient" is a timeout, a reset, a 5xx or a
    file over the ceiling. A stand-in that says nothing counts as dead, which is
    deliberate — see the guard — so a test about a TIMEOUT has to say so, and
    this is the documented seam for saying it. Nothing else about the fetch is
    imitated: it still answers bytes-or-None and still never raises.
    """
    calls = []

    def fake(url):
        calls.append(url)
        cityos_main._IMPORT_FETCH.why = why
        got = answer(url)
        if got:
            # A fetch that succeeded leaves the transient verdict it started
            # with; only the return value says it worked.
            cityos_main._IMPORT_FETCH.why = "transient"
        return got
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
    assert r["files_over_budget"] == 3, "the ones past the budget were not accounted for"
    # Counted as its own thing, because the report is read as a diagnosis: a
    # ceiling is a number here that someone can raise, and "did not answer" is
    # a file nobody here can do anything about.
    assert r["files_unreachable"] == 0, "the ceiling was reported as a failure to fetch"


# The per-file ceiling — that a body over it is refused, that a body of exactly
# it is not, and that the rest of a runaway one is never read — is now
# tests/test_import_attachment_fetching.py, over a socket. See the note at the
# top of this file.


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


# That a redirect is refused rather than followed — to another host and to
# another path on monday alike — is now tested where a real 302 can be served:
# tests/test_import_attachment_fetching.py. See the note at the top.


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
                   "files_expired", "הקישורים בקובץ פגו", "stat(r.files_imported,'קבצים')",
                   # Abandoned reads as the opposite advice from unreachable —
                   # run the import again, rather than export again — so it has
                   # a line of its own and never shares one.
                   "files_abandoned", "מעולם לא נתבקשו"):
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
    """A run of answers that condemn the export stops the fetching, and every
    file is still accounted for — as two different things.

    A stand-in fetch says only None, so every failure here counts as a dead
    link: with nothing recorded on `_IMPORT_FETCH` the guard reads "dead", on
    purpose, so that replacing `_fetch_import_file` wholesale — which is what
    `_serve` does and what most of this file is built on — cannot quietly
    switch the guard off. That makes this the dead case, and the transient one
    is below.

    What changed when the run learned to tell the two apart is the accounting,
    not the giving up. It used to call all twenty "לא נענו" — monday would not
    serve these — when seventeen of them had never been asked for. H3 חוזים is
    what that sentence was printed over: 367 live attachments reported as
    unreachable by an import that never dialled one of them. So the twenty are
    split into the three that were really refused and the seventeen the import
    abandoned, and the point of the original assertion — that none of them
    falls between the cracks — is now that the two numbers add up to the whole.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    calls = _serve(monkeypatch, {})                     # everything fails
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"f{i}.txt")],
                   assets=[{"id": str(i), "name": f"f{i}.txt",
                            "public_url": f"{MONDAY_HOST}/f{i}.txt"}])
             for i in range(20)]
    r = _import(client, admin_id, _resp(items)).json()["report"]
    # The files are fetched by a pool now, so up to one pool's worth are already
    # in flight when the run trips — in flight together, which is the whole point:
    # the rule exists to stop spending a timeout per file, and a handful at once
    # costs one timeout, not a handful of them.
    assert len(calls) <= 3 + cityos_main.IMPORT_FILE_WORKERS, \
        f"tried {len(calls)} times before giving up"
    assert len(calls) < 20, "it has to stop trying, not work through all of them"
    assert r["files_unreachable"] == len(calls), \
        "a file is unreachable only if monday was actually asked about it"
    assert r["files_abandoned"] == 20 - len(calls), \
        "the ones it stopped trying are still accounted for — as abandoned"
    assert r["files_unreachable"] + r["files_abandoned"] == 20, \
        "a file fell between the two counts"


def test_an_abandoned_file_keeps_its_name_and_says_it_was_abandoned(client, admin_id,
                                                                    monkeypatch):
    """Per cell, an abandoned attachment is shaped like an over-budget one.

    It is not an unreachable file and must not read as one: the name is worth
    keeping, the link is worth keeping — it very probably still works — and the
    chip has to know not to offer monday's expired-looking address as something
    to click.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 2)
    _serve(monkeypatch, {})                             # everything fails, as dead
    # Comfortably more files than a pool's worth: the run trips at two, but the
    # sixteen already in flight are real answers and are not abandoned, so a
    # board of a dozen could in principle be dialled end to end.
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"f{i}.txt")],
                   assets=[{"id": str(i), "name": f"f{i}.txt",
                            "public_url": f"{MONDAY_HOST}/f{i}.txt"}])
             for i in range(40)]
    d = _import(client, admin_id, _resp(items)).json()
    assert d["report"]["files_abandoned"] >= 1, d["report"]
    cells = [v for cf in _cells(d["id"]) for v in cf.values()
             if isinstance(v, list) and v]
    given_up = [c[0] for c in cells if c[0].get("why") == "abandoned"]
    assert len(given_up) == d["report"]["files_abandoned"], \
        "the report counts abandoned files the cells do not say are abandoned"
    one = given_up[0]
    assert one["name"].endswith(".txt") and one["url"].startswith(MONDAY_HOST)
    assert one["dead"] is True
    assert set(one) == {"name", "url", "why", "dead"}, one


def test_a_run_of_timeouts_does_not_abandon_the_rest_of_the_board(client, admin_id,
                                                                  monkeypatch):
    """The H3 regression, at the level the report is read.

    "H3 חוזים" carried 884 attachments. The import brought 509 and called the
    other 375 "לא נגישים", and the same links fetched 400-for-400 from this
    machine twice within the hour. What had happened is that five fetches in a
    row timed out — a loaded machine, big files, sixteen workers and a long
    write transaction holding SQLite — and the run-of-failures guard read that
    as an export whose links had all expired. 367 live files were never
    requested.

    A timeout says nothing about the export. It leaves the run where it was,
    every file after the bad patch is still asked for, and nothing is abandoned.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    bad = {f"{MONDAY_HOST}/f{i}.txt" for i in range(6)}
    calls = _serve_with_reasons(monkeypatch, lambda u: (
        None if u in bad else (b"the bytes", "text/plain")), why="transient")
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"f{i}.txt")],
                   assets=[{"id": str(i), "name": f"f{i}.txt",
                            "public_url": f"{MONDAY_HOST}/f{i}.txt"}])
             for i in range(20)]
    r = _import(client, admin_id, _resp(items)).json()["report"]
    assert len(calls) == 20, f"only {len(calls)} of 20 files were ever asked for"
    assert r["files_abandoned"] == 0, "a run of timeouts condemned the rest of the board"
    assert r["files_imported"] == 14, r
    assert r["files_unreachable"] == 6, r


def test_a_success_clears_the_run_of_dead_answers(client, admin_id, monkeypatch):
    """The guard is about a wholly stale export, not about a board missing a
    few files — a live one in between proves the export is not stale."""
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
    assert r["files_abandoned"] == 0, "the file after the success was never asked for"


def test_a_run_that_fails_transiently_is_still_bounded(client, admin_id, monkeypatch):
    """The backstop. A failure that proves nothing still costs a round trip,
    and an export of 900 attachments at twenty seconds apiece is eighteen
    minutes of a request somebody is sitting in front of — so a long enough run
    of failures of any kind is taken as the network being gone.

    It is deliberately an order of magnitude above anything a bad minute
    produces, which is why it is turned down here: at its shipped value this
    test would be a thousand round trips.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_GIVE_UP_STREAK", 6)
    calls = _serve_with_reasons(monkeypatch, lambda u: None, why="transient")
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"f{i}.txt")],
                   assets=[{"id": str(i), "name": f"f{i}.txt",
                            "public_url": f"{MONDAY_HOST}/f{i}.txt"}])
             for i in range(40)]
    r = _import(client, admin_id, _resp(items)).json()["report"]
    assert len(calls) < 40, "nothing bounded a board whose every file timed out"
    assert len(calls) <= 6 + cityos_main.IMPORT_FILE_WORKERS, \
        f"tried {len(calls)} times before the backstop stopped it"
    assert r["files_abandoned"] >= 40 - (6 + cityos_main.IMPORT_FILE_WORKERS)
    assert r["files_unreachable"] + r["files_abandoned"] == 40, \
        "a file fell between the two counts"


def test_every_attachment_the_file_named_is_accounted_for(client, admin_id, monkeypatch):
    """Whatever became of them, the numbers add up to the attachments in hand.

    This is the one assertion that cannot be satisfied by relabelling: a file
    that stops being "unreachable" and does not become something else has gone
    missing from the report, and a report that does not add up is how two
    thirds of a board were quietly lost twice already — once to the memory
    ceiling and once to this guard.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_FAIL_STREAK", 3)
    # Everything that is dialled at all answers dead, so the guard trips partway
    # down and the twenty live-looking links split into dialled and abandoned.
    _serve_with_reasons(monkeypatch, lambda u: None, why="dead")
    expired = (f"{MONDAY_HOST}/old.txt?X-Amz-Algorithm=AWS4-HMAC-SHA256"
               "&X-Amz-Date=20200101T000000Z&X-Amz-Expires=3600&X-Amz-Signature=dead")
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"f{i}.txt")],
                   assets=[{"id": str(i), "name": f"f{i}.txt",
                            "public_url": f"{MONDAY_HOST}/f{i}.txt"}])
             for i in range(20)]
    items.append(_item("ישן", cols=[_filecol("מסמך", "old.txt")],
                       assets=[{"id": "90", "name": "old.txt", "public_url": expired}]))
    d = _import(client, admin_id, _resp(items)).json()
    r = d["report"]
    named = 21
    became = (r["files_imported"] + r["files_unreachable"] + r["files_abandoned"]
              + r["files_expired"] + r["files_over_budget"])
    assert r["files_expired"] == 1, "a link whose signature says it lapsed is its own count"
    assert r["files_abandoned"] > 0, "nothing was abandoned, so this proves nothing"
    assert became == named, \
        f"{named - became} of the attachments this file named are in no count: {r}"
    # and nothing was invented either: every attachment is one entry on the
    # board, with its name, whatever became of its bytes
    cells = [v for cf in _cells(d["id"]) for v in cf.values()
             if isinstance(v, list) and v]
    assert sum(len(c) for c in cells) == named, f"{cells} for {named} attachments"
    assert all(e.get("name") for c in cells for e in c), "an attachment lost its name"


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
    # the name is kept and the address is not a link; the entry says why, so the
    # chip can show it as a name rather than as something to click
    assert cell == [{"name": "old.pdf", "url": "", "why": "gone", "dead": True}], cell


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


# That monday's login page — HTML, served as 200, where the file should have
# been — is not stored as the file is now tested against a server that really
# answers that way: tests/test_import_attachment_fetching.py. See the note at
# the top.


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

# ── a file attached to a reply ──────────────────────────────────────────────
def test_a_file_attached_to_a_reply_comes_across(client, admin_id, monkeypatch):
    """A reply is a message like any other and can carry the attachment the whole
    thread was about. The parser always read `assets` off it — the export simply
    never asked, and a reply holding nothing but a file was dropped whole, since
    a message with no text and no file carries nothing."""
    url = f"{MONDAY_HOST}/spec.docx"
    _serve(monkeypatch, {url: (b"DOCX BYTES", "application/octet-stream")})
    items = [_item("פריט", updates=[{
        "id": "1", "body": "<p>ראו קובץ</p>", "text_body": "ראו קובץ",
        "created_at": "2026-01-01T10:00:00Z", "creator": {"name": "משה", "email": "m@x.co"},
        "assets": [],
        "replies": [{"id": "2", "body": "", "text_body": "",
                     "created_at": "2026-01-01T11:00:00Z",
                     "creator": {"name": "דנה", "email": "d@x.co"},
                     "assets": [{"id": "9", "name": "spec.docx", "public_url": url}]}],
    }])]
    r = _import(client, admin_id, _resp(items)).json()
    assert r["report"]["files_imported"] == 1, "the reply's file is a file"
    assert r["messages"] >= 2, "and the reply itself survives, having carried it"


def test_the_shipped_query_asks_for_a_reply_s_attachments():
    import pathlib, re
    q = (pathlib.Path(__file__).resolve().parent.parent
         / "backend" / "monday_export.graphql").read_text(encoding="utf-8")
    for m in re.finditer(r"replies \{[^}]*\{[^}]*\}[^}]*\}", q):
        assert "assets" in m.group(0), "a replies block that does not ask for assets"
    assert q.count("replies {") == 4


def test_an_expired_attachment_is_marked_rather_than_handed_over_as_a_link(client, admin_id, monkeypatch):
    """What she hit: the chips were there, and opening one answered with S3's
    "Request has expired" instead of the file. The name is worth keeping — the
    item did have a spec attached — but not as something to click."""
    monkeypatch.setattr(cityos_main, "_signed_url_expired", lambda u: True)
    url = f"{MONDAY_HOST}/spec.docx?X-Amz-Expires=3600"
    calls = _serve(monkeypatch, {url: (b"x", "application/octet-stream")})
    items = [_item("פריט", cols=[_filecol("מסמך", "spec.docx")],
                   assets=[{"id": "1", "name": "spec.docx", "public_url": url}])]
    d = _import(client, admin_id, _resp(items)).json()
    assert d["report"]["files_expired"] == 1
    assert not calls, "a signature that says it lapsed is not worth a round trip"
    with Session(cityos_main.engine) as db:
        task = db.query(Task).filter(Task.board_id == d["id"]).first()
        cell = [v for k, v in (task.custom_fields or {}).items() if isinstance(v, list)][0]
    assert cell[0]["name"] == "spec.docx", "the name survives"
    assert cell[0]["dead"] is True and cell[0]["why"] == "expired"


def test_the_chip_does_not_link_a_file_that_never_arrived():
    import pathlib as _p
    src = (_p.Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "FILE_DEAD_HE" in src and "fileDeadWhy" in src
    assert "הקישור של מאנדיי פג" in src, "and says what would bring the file"
    assert "file-dead" in src and "att-dead" in src, "the cell chip and the message one"



# ── the window: a board's files are fetched a stretch at a time ─────────────
# The ceiling on what an import brings used to be a memory ceiling wearing
# another name. Everything was fetched before the first item was written and
# everything written stayed in the session until the commit, so a board's files
# were held twice over and 150MB was as much as that could be allowed to reach.
# On ניהול ביקורים — 592 items, 972 attachments, 982MB — the budget ran out 86
# files in, at item 112, and every registration form and schedule below that
# point arrived as a name with nothing behind it. The board imported, reported
# and looked finished.
#
# What makes the ceiling raisable is that neither half piles up any more: the
# fetch runs a window ahead of the walk and lets go of what it has handed over,
# and the rows behind it go to the database a window at a time. These pin that,
# because the symptom of losing it is not an error — it is a board that looks
# complete and is two thirds files-by-name.

def test_a_board_heavier_than_the_window_still_arrives_whole(client, admin_id, monkeypatch):
    """Every file comes across, however many windows it takes to fetch them."""
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_WINDOW_MB", 1)
    blob = b"x" * (300 * 1024)                 # three to a window, seventy in all
    urls = {f"{MONDAY_HOST}/w{i}.pdf": (blob, "application/pdf") for i in range(70)}
    _serve(monkeypatch, urls)
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"w{i}.pdf")],
                   assets=[{"id": str(i), "name": f"w{i}.pdf",
                            "public_url": f"{MONDAY_HOST}/w{i}.pdf"}])
             for i in range(70)]
    r = _import(client, admin_id, _resp(items)).json()["report"]
    assert r["files_imported"] == 70, r
    assert r["files_over_budget"] == 0 and r["files_unreachable"] == 0, r


def test_the_fetch_does_not_pull_the_whole_board_into_memory(monkeypatch):
    """A window's worth is in hand at once, not the board's worth.

    Asked for the first file, it fetches a stretch and stops; asked for a file
    further along, it fetches up to there. What has been handed over is let go,
    so what the import holds is the window whatever the board weighs.
    """
    blob = b"x" * (256 * 1024)
    urls = [f"{MONDAY_HOST}/m{i}.bin" for i in range(400)]
    asked = []

    def fake(url):
        asked.append(url)
        return blob, "application/octet-stream"
    monkeypatch.setattr(cityos_main, "_fetch_import_file", fake)
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_WINDOW_MB", 1)

    win = cityos_main._prefetch_import_files(urls, [len(urls), 400 * 1024 * 1024])
    assert urls[0] in win
    first = len(asked)
    assert first < len(urls), "the first file pulled the whole board"
    peak = win.held
    for u in urls:                              # the walk, in the file's order
        assert u in win
        win[u]
        peak = max(peak, win.held)
    assert len(asked) == len(urls), "some file was never fetched"
    # Rounded up to whole chunks of the fetch, a window is still a window and
    # not four hundred files' worth of bytes.
    assert peak < 16 * 1024 * 1024, f"held {peak} bytes at once"


def test_the_bytes_go_to_the_database_as_they_arrive(client, admin_id, monkeypatch):
    """The rows written do not wait in the session for the commit.

    Left there they are the other copy of the board — the one the fetch window
    cannot do anything about — and the two together are what kept the ceiling
    where it was.
    """
    monkeypatch.setattr(cityos_main, "IMPORT_FILE_WINDOW_MB", 1)
    blob = b"y" * (400 * 1024)
    urls = {f"{MONDAY_HOST}/d{i}.pdf": (blob, "application/pdf") for i in range(12)}
    _serve(monkeypatch, urls)
    held = []
    real_flush = Session.flush

    def watch(self, *a, **kw):
        held.append(sum(len(o.data or b"") for o in self.new
                        if isinstance(o, UploadedFile)))
        return real_flush(self, *a, **kw)
    monkeypatch.setattr(Session, "flush", watch)
    items = [_item(f"פריט {i}", cols=[_filecol("מסמך", f"d{i}.pdf")],
                   assets=[{"id": str(i), "name": f"d{i}.pdf",
                            "public_url": f"{MONDAY_HOST}/d{i}.pdf"}])
             for i in range(12)]
    r = _import(client, admin_id, _resp(items)).json()["report"]
    assert r["files_imported"] == 12, r
    assert max(held) <= 3 * 1024 * 1024, \
        f"{max(held)} bytes of attachments were waiting in the session at once"
