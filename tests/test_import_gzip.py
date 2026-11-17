"""A big export may arrive compressed, and it imports to the same board.

The number that produced this test: a monday board of 21,187 items exports to
78.5MB of JSON and gzips to 4.0MB. Writing that board — every item, every cell
and 9,950 history rows — takes 13 seconds; the minutes people were waiting were
78MB climbing a home upload link to Azure. Twenty times less to send is the
whole of the fix, and it is only a fix if the compressed file produces exactly
the board the plain one does.

The second rule here is the one compression always brings with it: a few
megabytes can name a file no machine can hold, so the ceiling is measured
against what the import READS, not against what arrived on the wire.
"""
import gzip
import json

import main as cityos_main

H = {"X-CityOS-User": "1", "host": "localhost"}


def _board(n_items):
    return json.dumps({"data": {"boards": [{
        "id": "5738954426", "name": "לקוחות",
        "items_count": n_items,
        "groups": [{"id": "g1", "title": "פעילים"}],
        "items_page": {"cursor": None, "items": [
            {"id": str(i), "name": f"לקוח {i}",
             "group": {"id": "g1", "title": "פעילים"},
             "column_values": [{"id": "t", "type": "text",
                                "column": {"title": "איש קשר"},
                                "text": f"דני {i}"}]}
            for i in range(n_items)]}}]}}, ensure_ascii=False).encode()


def _upload(client, raw, filename, name):
    return client.post("/api/boards/import",
                       files={"file": (filename, raw, "application/octet-stream")},
                       data={"name": name}, headers=H)


def test_a_gzipped_export_imports_the_same_board_as_the_plain_one(client):
    raw = _board(12)
    plain = _upload(client, raw, "export.json", "רגיל")
    packed = _upload(client, gzip.compress(raw), "export.json.gz", "דחוס")
    assert plain.status_code == 200, plain.text[:300]
    assert packed.status_code == 200, \
        f"a gzipped export was refused: {packed.status_code} {packed.text[:300]}"
    # Same board, by the only measure that matters to a migration: the rows.
    a, b = plain.json(), packed.json()
    assert a["id"] != b["id"], "two imports, two boards"
    assert a["items"] == b["items"] == 12, (a["items"], b["items"])
    ia = client.get(f"/api/boards/{a['id']}", headers=H).json()
    ib = client.get(f"/api/boards/{b['id']}", headers=H).json()
    def titles(d):
        rows = d.get("tasks") or [t for g in d.get("groups") or [] for t in g["tasks"]]
        return [t["title"] for t in rows]
    assert titles(ia) == titles(ib) != [], \
        "the compressed file produced a different board than the plain one"


def test_the_ceiling_is_measured_against_what_the_import_reads(client, monkeypatch):
    """The whole point of a limit on uploads is what the server ends up holding.
    Checked against the compressed size instead, 4MB of zeros would unpack into
    as much as the sender felt like sending."""
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_UPLOAD_MB", 1)
    bomb = gzip.compress(b"{\"data\":{\"boards\":[]}}" + b" " * (4 * 1024 * 1024))
    assert len(bomb) < 1024 * 1024, "the test's own premise: it arrives small"
    r = _upload(client, bomb, "bomb.json.gz", "פצצה")
    assert r.status_code == 413, \
        f"a file that unpacked past the ceiling was accepted: {r.status_code}"


def test_a_corrupt_archive_is_a_400_and_says_so(client):
    """Half a download is the ordinary way a .gz goes wrong, and it must not
    read as a bad board — the file is fine, it just did not arrive whole."""
    half = gzip.compress(_board(3))[: 40]
    r = _upload(client, half, "export.json.gz", "חצי")
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]}"
    assert "פגום" in r.text, r.text[:200]
