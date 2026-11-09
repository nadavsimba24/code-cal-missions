"""אורח לא מוציא נתונים מהמערכת — לא לוח לאקסל ולא קבצים.

An אורח is somebody from outside the organisation, invited in to work on a
board (backend/entra_guests.py brings them in through Entra). Being able to READ
a board and being able to take a copy of it away are two different permissions,
and until now the second came free with the first: the board menu offered
"ייצוא לאקסל" to everybody, and every attachment was one click from being saved.

Both are now capabilities in the role matrix — `export_excel` and
`download_files` — off for אורח and on for every other role. Two things make
that safe to ship:

* CAP_DEFAULT_ON. Every other capability in that table is born False, because it
  describes a power somebody has to be granted. These two describe something
  every role could already do, so born False they would have taken Excel and
  every attachment away from every member of every board on the first restart.
* `_file_is_interface_picture`. One route serves both the files people attach to
  items and the pictures the interface is made of — an avatar, an environment's
  icon, a form's logo and cover. A guest who may not download files must still
  be able to see the app, so those are let through and nothing else is. The
  form's logo as a stranger sees it never comes through here at all; it has a
  route of its own (`public_form_logo`), for the reason written there.

The screen's half — no link offered, no download arrow, no broken thumbnail
where a picture cannot be fetched — is tests/frontend/guest_cannot_take_data_out.mjs.
"""
import io
import pathlib
import shutil
import subprocess

import pytest

from conftest import ADMIN_ID, PRIMARY_ENV_ID, _ensure_user

GUEST_EMAIL = "test.guest@cityos.test"


@pytest.fixture(scope="module")
def guest_id(client):
    """An אורח who is a full member of a board — so a refusal below is about the
    capability and never about board access."""
    uid = _ensure_user("בודק אורח", GUEST_EMAIL)
    client.patch(f"/api/users/{uid}", json={"actor_id": ADMIN_ID, "role": "guest"})
    if PRIMARY_ENV_ID:
        client.post(f"/api/environments/{PRIMARY_ENV_ID}/members",
                    json={"actor_id": ADMIN_ID, "user_id": uid, "role": "member"})
    client.post("/api/boards/1/members",
                json={"actor_id": ADMIN_ID, "user_id": uid, "role": "editor"})
    return uid


def _upload(client, actor, name="סודי.xlsx", ctype="application/vnd.ms-excel"):
    r = client.post("/api/upload", files={"file": (name, io.BytesIO(b"bytes"), ctype)},
                    headers={"X-CityOS-User": str(actor)})
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/", 1)[-1]


def _export(client, actor, board_id=1):
    return client.post(f"/api/boards/{board_id}/export/xlsx",
                       json={"actor_id": actor, "columns": ["פריט"], "rows": [{"cells": ["א"]}]})


def _matrix(client):
    return client.get("/api/role-permissions").json()["matrix"]


# ── the matrix the two live in ─────────────────────────────────────────────
def test_the_two_capabilities_exist_and_are_named_in_hebrew(client):
    d = client.get("/api/role-permissions").json()
    keys = {c["key"]: c["he"] for c in d["capabilities"]}
    assert "export_excel" in keys and "download_files" in keys
    assert keys["export_excel"] and keys["download_files"]      # a row with no label is unusable


def test_they_are_off_for_a_guest_and_on_for_everybody_else(client):
    """The whole point of CAP_DEFAULT_ON: this is one role losing something, not
    every role being asked to be granted it."""
    m = _matrix(client)
    for cap in ("export_excel", "download_files"):
        assert m["guest"][cap] is False, cap
        for role in ("manager", "member", "viewer"):
            assert m[role][cap] is True, (role, cap)
        assert m["admin"][cap] is True, cap


# ── אקסל ───────────────────────────────────────────────────────────────────
def test_a_guest_cannot_export_a_board_to_excel(client, guest_id):
    r = _export(client, guest_id)
    assert r.status_code == 403, r.text
    assert "אקסל" in (r.json().get("detail") or ""), r.text


def test_a_member_of_the_same_board_still_can(client, member_id):
    """The refusal above has to be about the role and not about the export."""
    r = _export(client, member_id)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument")


def test_board_access_is_still_checked_first(client, guinea_id):
    """A capability is not a way INTO a board — somebody with the capability and
    no membership is still refused, and with the board's own message."""
    bid = client.post("/api/boards", json={"name": "לוח סגור לייצוא",
                                           "user_id": ADMIN_ID}).json()["id"]
    r = _export(client, guinea_id, bid)
    assert r.status_code == 403
    assert "גישה" in (r.json().get("detail") or ""), r.text


# ── קבצים ──────────────────────────────────────────────────────────────────
def test_a_guest_cannot_download_an_attachment(client, guest_id):
    token = _upload(client, ADMIN_ID)
    r = client.get(f"/api/files/{token}?user_id={guest_id}")
    assert r.status_code == 403, r.text
    assert "קבצים" in (r.json().get("detail") or ""), r.text


def test_not_even_one_they_uploaded_themselves(client, guest_id):
    """"הורדה מרוכזת" and "קובץ בודד" are the same act of taking the bytes, and
    owning the upload does not make it a different one."""
    token = _upload(client, guest_id, "שלי.docx")
    assert client.get(f"/api/files/{token}?user_id={guest_id}").status_code == 403


def test_not_by_dropping_the_download_flag_from_the_address(client, guest_id):
    """The block is on the bytes, not on the Content-Disposition. A picture asked
    for inline is the same file arriving by another name."""
    token = _upload(client, ADMIN_ID, "תמונה.png", "image/png")
    assert client.get(f"/api/files/{token}?user_id={guest_id}&dl=1").status_code == 403
    assert client.get(f"/api/files/{token}?user_id={guest_id}").status_code == 403


def test_a_member_downloads_the_same_file(client, member_id):
    token = _upload(client, ADMIN_ID)
    r = client.get(f"/api/files/{token}?user_id={member_id}")
    assert r.status_code == 200 and r.content == b"bytes"


def test_the_names_are_not_hidden_only_the_bytes(client, guest_id):
    """A guest goes on working on the board: they see that a file is attached and
    what it is called. Blocking the list as well would be a different request."""
    token = _upload(client, ADMIN_ID, "נראה-לי.pdf", "application/pdf")
    tid = client.post("/api/tasks", json={"board_id": 1, "title": "פריט עם קובץ",
                                          "user_id": ADMIN_ID}).json()["id"]
    try:
        client.post(f"/api/tasks/{tid}/comments", json={
            "actor_id": ADMIN_ID, "content": "מצורף",
            "attachments": [{"name": "נראה-לי.pdf", "url": f"/api/files/{token}",
                             "type": "application/pdf"}]})
        r = client.get(f"/api/tasks/{tid}/files?user_id={guest_id}")
        assert r.status_code == 200, r.text
        assert any(f.get("name") == "נראה-לי.pdf" for f in r.json().get("files", [])), r.text
    finally:
        client.delete(f"/api/tasks/{tid}?user_id={ADMIN_ID}")


# ── the pictures the app itself is made of ─────────────────────────────────
def test_a_guest_still_sees_their_own_face(client, guest_id):
    """Their avatar comes down the same route as every attachment. Refusing it
    would leave a guest looking at a broken image where the app's own chrome is."""
    token = _upload(client, guest_id, "פרצוף.png", "image/png")
    try:
        client.patch(f"/api/users/{guest_id}",
                     json={"actor_id": ADMIN_ID, "avatar_url": f"/api/files/{token}"})
        assert client.get(f"/api/files/{token}?user_id={guest_id}").status_code == 200
    finally:
        client.patch(f"/api/users/{guest_id}", json={"actor_id": ADMIN_ID, "avatar_url": None})


def test_and_the_icon_of_the_environment_they_work_in(client, guest_id):
    token = _upload(client, ADMIN_ID, "סמל.png", "image/png")
    env = client.post("/api/environments", json={"actor_id": ADMIN_ID, "name": "סביבת אייקון",
                                                 "icon": f"/api/files/{token}"}).json()
    try:
        assert client.get(f"/api/files/{token}?user_id={guest_id}").status_code == 200
    finally:
        client.delete(f"/api/environments/{env['id']}?actor_id={ADMIN_ID}")


def test_once_the_environment_is_gone_the_picture_is_content_again(client, guest_id):
    """The whitelist is a question asked of the data, not a flag written on the
    file: the same upload stops being chrome the moment nothing wears it."""
    token = _upload(client, ADMIN_ID, "סמל-זמני.png", "image/png")
    env = client.post("/api/environments", json={"actor_id": ADMIN_ID, "name": "סביבה חולפת",
                                                 "icon": f"/api/files/{token}"}).json()
    assert client.get(f"/api/files/{token}?user_id={guest_id}").status_code == 200
    client.delete(f"/api/environments/{env['id']}?actor_id={ADMIN_ID}")
    assert client.get(f"/api/files/{token}?user_id={guest_id}").status_code == 403


# ── and it is a setting, not a law ─────────────────────────────────────────
def test_a_system_admin_can_hand_either_of_them_back(client, guest_id):
    """The matrix is where this lives precisely so that an organisation which
    wants its guests to download files does not need a release to say so."""
    token = _upload(client, ADMIN_ID)
    try:
        r = client.put("/api/role-permissions", json={"actor_id": ADMIN_ID, "role": "guest",
                                                      "capability": "download_files",
                                                      "allowed": True})
        assert r.status_code == 200, r.text
        assert client.get(f"/api/files/{token}?user_id={guest_id}").status_code == 200
        r = client.put("/api/role-permissions", json={"actor_id": ADMIN_ID, "role": "guest",
                                                      "capability": "export_excel",
                                                      "allowed": True})
        assert r.status_code == 200, r.text
        assert _export(client, guest_id).status_code == 200
    finally:
        for cap in ("download_files", "export_excel"):
            client.put("/api/role-permissions", json={"actor_id": ADMIN_ID, "role": "guest",
                                                      "capability": cap, "allowed": False})
    assert client.get(f"/api/files/{token}?user_id={guest_id}").status_code == 403


# ── the screen's half ──────────────────────────────────────────────────────
def test_the_screen_offers_neither_where_it_is_blocked():
    """Driven harness: tests/frontend/guest_cannot_take_data_out.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = pathlib.Path(__file__).resolve().parent / "frontend" / "guest_cannot_take_data_out.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
