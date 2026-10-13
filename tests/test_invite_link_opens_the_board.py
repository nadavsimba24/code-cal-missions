"""The link in an invitation mail has to be a link the invitee can follow.

It was not. `APP_BASE_URL` is set in neither pipeline, so the base fell back to
a hardcoded `code-cal-missions.vercel.app` — a different deployment from either
QA or production, and one whose database is re-seeded per cold start. The mail
named a board, and the button landed on a demo where that board does not exist.

These pin the three things that make the link work: the host is one the invitee
can actually sign in on, the board invitation points at the board itself, and
the path the button opens is served by the SPA that reads the deep link.
"""
import re
import main as cityos_main


def _captured(monkeypatch):
    out = []
    monkeypatch.setattr(cityos_main, "_send_email",
                        lambda to, subject, html: out.append((to, subject, html)) or True)
    return out


def _href(html):
    m = re.search(r'<a href="([^"]+)"', html)
    assert m, "the mail has no link at all"
    return m.group(1)


def test_the_board_link_points_at_the_board_on_this_host(client, admin_id, guinea_id, monkeypatch):
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.delenv("ENTRA_REDIRECT_URI", raising=False)
    sent = _captured(monkeypatch)
    boards = client.get(f"/api/boards?user_id={admin_id}").json()
    bid = (boards["boards"] if isinstance(boards, dict) else boards)[0]["id"]
    client.delete(f"/api/boards/{bid}/members/{guinea_id}?actor_id={admin_id}")
    sent.clear()

    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    href = _href(sent[0][2])
    # the host the invitation was issued on (conftest signs requests as
    # host: localhost), never a hardcoded other deployment
    assert href.startswith("http://localhost/"), href
    assert "vercel.app" not in href
    assert href.endswith(f"/#/board/{bid}")

    # and that URL is served: the fragment never reaches the server, so what the
    # browser requests is the site root — which must hand back the SPA.
    page = client.get(href.split("#")[0])
    assert page.status_code == 200
    assert "board\\/(\\d+)" in page.text or "#/board/" in page.text


def test_the_workspace_link_uses_the_sso_host_when_one_is_configured(client, admin_id, guinea_id, monkeypatch):
    """Where sign-in works is where the mail must send people. The production
    pipeline writes ENTRA_REDIRECT_URI from the Web App's own hostnames, so its
    origin is the one host the invitee is certain to have an account on."""
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setenv("ENTRA_REDIRECT_URI",
                       "https://missions.example.gov.il/auth/callback,"
                       "https://missions-prd.azurewebsites.net/auth/callback")
    sent = _captured(monkeypatch)
    env = client.post("/api/environments",
                      json={"actor_id": admin_id, "name": "סביבת קישור"}).json()
    client.post(f"/api/environments/{env['id']}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"})
    assert _href(sent[0][2]) == "https://missions.example.gov.il"


def test_an_explicit_base_url_still_wins(client, admin_id, guinea_id, monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://missions.example.gov.il/")
    monkeypatch.setenv("ENTRA_REDIRECT_URI", "https://other.example/auth/callback")
    sent = _captured(monkeypatch)
    env = client.post("/api/environments",
                      json={"actor_id": admin_id, "name": "סביבת מפורשת"}).json()
    client.post(f"/api/environments/{env['id']}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"})
    # no double slash where the setting ended with one
    assert _href(sent[0][2]) == "https://missions.example.gov.il"


def test_the_link_follows_the_host_the_browser_used(client, admin_id, guinea_id, monkeypatch):
    """Both Azure front ends terminate TLS and speak plain http to the
    container, so the host and scheme that matter are the forwarded ones. A
    link built from the inner request would name an unroutable host over http."""
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.delenv("ENTRA_REDIRECT_URI", raising=False)
    sent = _captured(monkeypatch)
    env = client.post("/api/environments",
                      json={"actor_id": admin_id, "name": "סביבת פרוקסי"}).json()
    client.post(f"/api/environments/{env['id']}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "member"},
                headers={"x-forwarded-host": "missions.example.gov.il",
                         "x-forwarded-proto": "https"})
    assert _href(sent[0][2]) == "https://missions.example.gov.il"
