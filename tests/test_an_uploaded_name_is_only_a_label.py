"""A file's name is a label: no path, no control characters, on the way in or out.

Files are stored under a random token, so a name never reached a path on the
server. But the name a client sent was stored and handed back verbatim — in
the upload's JSON and in the download's Content-Disposition. The penetration
test of 2026-11 uploaded "../../../etc/shadow" and got exactly that back.
Pinned here: traversal with either separator, control and bidi-override
characters, and leading dots are cleaned when the name is stored, and the
download header carries only the clean name.
"""
from urllib.parse import unquote

import pytest

import main

H = lambda uid: {"X-CityOS-User": str(uid)}


@pytest.mark.parametrize("raw,clean", [
    ("../../../etc/shadow", "shadow"),
    ("..\\..\\windows\\system32\\boot.ini", "boot.ini"),
    ("a/b\\c/../d.txt", "d.txt"),
    ("report\x00.pdf", "report.pdf"),
    ("line\r\nbreak.txt", "linebreak.txt"),
    ("photo\u202egpj.exe", "photogpj.exe"),      # RLO: would display as photoexe.jpg
    ("..", "file"),
    (".env", "env"),
    ("name. . .", "name"),
    ("דו\"ח רבעוני.xlsx", "דו\"ח רבעוני.xlsx"),  # Hebrew and quotes are a name, not an attack
    ("", "file"),
])
def test_a_name_is_cut_down_to_a_label(raw, clean):
    assert main._safe_filename(raw) == clean


def test_an_upload_stores_and_serves_only_the_clean_name(client, admin_id):
    r = client.post("/api/upload",
                    files={"file": ("../../../etc/shadow", b"test", "text/plain")},
                    headers=H(admin_id))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "shadow"
    tok = r.json()["url"].rsplit("/", 1)[-1]
    d = client.get(f"/api/files/{tok}?dl=1", headers=H(admin_id)).headers["content-disposition"]
    assert "/" not in unquote(d.split("''", 1)[1]) and d.endswith("shadow"), d


def test_a_name_stored_before_the_fix_is_cleaned_on_the_way_out(client, admin_id):
    """Old rows keep the name they arrived with; the header must not."""
    from sqlalchemy.orm import Session
    r = client.post("/api/upload", files={"file": ("x.txt", b"old", "text/plain")},
                    headers=H(admin_id))
    tok = r.json()["url"].rsplit("/", 1)[-1]
    with Session(main.engine) as db:
        db.query(main.UploadedFile).filter(main.UploadedFile.token == tok) \
          .update({"name": "../../etc/passwd"})
        db.commit()
    d = client.get(f"/api/files/{tok}?dl=1", headers=H(admin_id)).headers["content-disposition"]
    assert unquote(d.split("''", 1)[1]) == "passwd", d
