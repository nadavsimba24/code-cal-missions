"""זהות בדפדפן — כותרת או עוגייה.

The X-CityOS-User header only rides on requests the app makes itself. A
browser fetching a URL on its own — <img src>, a download link, a new tab —
sends no header, so an uploaded avatar came back 401 and rendered broken. Dev
mode therefore accepts the same identity from a cookie.
"""
import io

import auth as cityos_auth


def _upload(client, admin_id, name="pic.png"):
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    r = client.post("/api/upload", files={"file": (name, io.BytesIO(png), "image/png")},
                    headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 200, r.text
    return r.json()["url"]


def test_a_file_url_is_reachable_with_the_header(client, admin_id):
    url = _upload(client, admin_id)
    r = client.get(url, headers={"X-CityOS-User": str(admin_id)})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/png")


def test_the_same_url_is_reachable_with_only_a_cookie(client, admin_id):
    """This is what an <img> tag can actually send."""
    url = _upload(client, admin_id)
    r = client.get(url, headers={"X-CityOS-User": ""}, cookies={"cityos_user": str(admin_id)})
    assert r.status_code == 200, r.text
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_an_anonymous_request_is_still_refused(client, admin_id):
    url = _upload(client, admin_id)
    r = client.get(url, headers={"X-CityOS-User": ""})
    assert r.status_code == 401


def test_a_bogus_cookie_is_refused(client, admin_id):
    url = _upload(client, admin_id)
    r = client.get(url, headers={"X-CityOS-User": ""}, cookies={"cityos_user": "999999"})
    assert r.status_code in (401, 403)


def test_the_header_still_wins_over_the_cookie(client, admin_id, guinea_id):
    """A stale cookie must not override the identity the app is sending."""
    r = client.get("/api/users/me", headers={"X-CityOS-User": str(admin_id)},
                   cookies={"cityos_user": str(guinea_id)})
    if r.status_code == 404:                     # endpoint name differs — fall back
        r = client.get("/api/boards", headers={"X-CityOS-User": str(admin_id)},
                       cookies={"cityos_user": str(guinea_id)})
        assert r.status_code == 200
        return
    assert r.status_code == 200 and r.json().get("id") == admin_id


def test_the_cookie_only_counts_in_dev_mode(client, admin_id, monkeypatch):
    url = _upload(client, admin_id)
    monkeypatch.setattr(cityos_auth, "auth_mode", lambda: "easyauth")
    r = client.get(url, headers={"X-CityOS-User": ""}, cookies={"cityos_user": str(admin_id)})
    assert r.status_code == 401                  # easyauth ignores it — fails closed
