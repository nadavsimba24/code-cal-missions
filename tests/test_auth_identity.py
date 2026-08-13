"""Group 23 — identity is taken from the transport, never from the request.

These lock in the fix for the finding that every endpoint trusted an `actor_id`
parameter, so `?actor_id=1` was system admin.
"""
import main as cityos_main

ANON = {"X-CityOS-User": ""}


def _as(uid):
    return {"X-CityOS-User": str(uid)}


# ── the parameters themselves are no longer believed ─────────────────

def test_actor_id_parameter_cannot_elevate(client, member_id, admin_id):
    """A signed-in member claiming actor_id=<admin> stays a member."""
    r = client.get(f"/api/login-history?actor_id={admin_id}", headers=_as(member_id))
    assert r.status_code == 403


def test_actor_id_in_body_cannot_elevate(client, member_id, admin_id):
    """Same for a body-supplied actor_id on a mutating endpoint."""
    r = client.post("/api/boards", json={"name": "אסור", "user_id": admin_id},
                    headers=_as(member_id))
    assert r.status_code == 403


def test_anonymous_cannot_read_resident_data(client):
    """Citizen requests carry PII and used to be readable with no identity."""
    for path in ("/api/citizen-requests", "/api/permits", "/api/users", "/api/audit-log"):
        assert client.get(path, headers=ANON).status_code == 401, path


def test_status_stays_public(client):
    """The health endpoint must remain reachable for the platform probe."""
    assert client.get("/api/status", headers=ANON).status_code == 200


def test_unknown_identity_is_refused(client):
    assert client.get("/api/boards", headers={"X-CityOS-User": "nobody@example.test"}).status_code == 403


# ── aggregate views no longer fall back to "every board" ─────────────

def test_visible_boards_is_empty_without_identity():
    from sqlalchemy.orm import Session
    with Session(cityos_main.engine) as db:
        assert cityos_main._visible_board_ids(db, None) == set()


def test_require_board_edit_refuses_missing_actor():
    import pytest
    from fastapi import HTTPException
    from sqlalchemy.orm import Session
    with Session(cityos_main.engine) as db:
        with pytest.raises(HTTPException) as e:
            cityos_main._require_board_edit(db, 1, None)
        assert e.value.status_code == 401


# ── AI tools run with the caller's permissions ───────────────────────

def test_ai_tools_require_an_actor():
    assert "התחברות" in cityos_main.execute_ai_tool("list_users", {}, None)


def test_ai_cannot_delete_a_task_on_a_board_it_cannot_see(client, admin_id, guinea_id):
    """The tool path used to ignore permissions entirely."""
    b = client.post("/api/boards", json={"name": "לוח סגור", "user_id": admin_id}).json()
    bid = b["id"]
    try:
        g = client.post("/api/groups", json={"board_id": bid, "name": "ג", "actor_id": admin_id}).json()
        t = client.post("/api/tasks", json={"title": "סודי", "board_id": bid,
                                           "group_id": g["id"], "user_id": admin_id}).json()
        out = cityos_main.execute_ai_tool("delete_task", {"task_id": t["id"]}, guinea_id)
        assert "אין לך" in out
        # and the item really was left alone (the tool archives rather than deletes)
        from sqlalchemy.orm import Session
        with Session(cityos_main.engine) as db:
            row = db.query(cityos_main.Task).filter(cityos_main.Task.id == t["id"]).first()
            assert row is not None and row.is_archived is False
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def test_ai_board_listing_is_scoped_to_the_caller(client, admin_id, guinea_id):
    b = client.post("/api/boards", json={"name": "לוח פרטי מאוד", "user_id": admin_id}).json()
    try:
        assert "לוח פרטי מאוד" not in cityos_main.execute_ai_tool("list_boards", {}, guinea_id)
    finally:
        client.delete(f"/api/boards/{b['id']}?user_id={admin_id}")


# ── uploads cannot execute on our origin ─────────────────────────────

def test_html_upload_is_served_as_an_inert_attachment(client, admin_id):
    up = client.post("/api/upload",
                     files={"file": ("evil.html", b"<script>alert(1)</script>", "text/html")},
                     headers=_as(admin_id))
    assert up.status_code == 200, up.text
    r = client.get(up.json()["url"], headers=_as(admin_id))
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_svg_upload_is_not_served_inline(client, admin_id):
    """SVG executes script when rendered same-origin, so it is never inline."""
    up = client.post("/api/upload",
                     files={"file": ("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")},
                     headers=_as(admin_id))
    r = client.get(up.json()["url"], headers=_as(admin_id))
    assert r.headers["content-disposition"].startswith("attachment")


def test_png_upload_still_renders_inline(client, admin_id):
    png = bytes.fromhex("89504e470d0a1a0a")
    up = client.post("/api/upload", files={"file": ("ok.png", png, "image/png")},
                     headers=_as(admin_id))
    r = client.get(up.json()["url"], headers=_as(admin_id))
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers["content-disposition"].startswith("inline")


def test_files_require_authentication(client, admin_id):
    up = client.post("/api/upload", files={"file": ("a.txt", b"hi", "text/plain")},
                     headers=_as(admin_id))
    assert client.get(up.json()["url"], headers=ANON).status_code == 401


# ── the LLM proxy is not an open relay ───────────────────────────────

def test_llm_proxy_requires_authentication(client):
    r = client.post("/api/llm/v1/chat/completions", json={"messages": []}, headers=ANON)
    assert r.status_code == 401
