"""בורר המשתמשים — רק על המכונה המקומית.

Dev mode hands identity to whoever asks for it: that is what the user picker
is. It exists for a developer on their own machine, so it is honoured only
when the app is served locally. On any other host the request falls back to
easyauth — identity comes from the platform, and a request without one is
refused. Without this, a .env carrying CITYOS_AUTH_MODE=dev turns the picker
into a public door on any deployment that uploads the working directory.
"""
import auth as cityos_auth


REMOTE = {"host": "code-cal-missions.vercel.app"}
LOCAL = {"host": "localhost:8000"}


def test_dev_identity_works_when_served_locally(client, admin_id):
    r = client.get("/api/auth/me", headers={**LOCAL, "X-CityOS-User": str(admin_id)})
    assert r.status_code == 200 and r.json()["id"] == admin_id


def test_the_same_request_from_a_remote_host_is_refused(client, admin_id):
    """The picker's identity carries no weight once the app is reachable."""
    r = client.get("/api/auth/me", headers={**REMOTE, "X-CityOS-User": str(admin_id)})
    assert r.status_code == 401


def test_the_dev_cookie_is_refused_from_a_remote_host(client, admin_id):
    r = client.get("/api/boards", headers={**REMOTE, "X-CityOS-User": ""},
                   cookies={"cityos_user": str(admin_id)})
    assert r.status_code == 401


def test_the_spa_is_told_not_to_show_a_picker_remotely(client):
    """The picker renders only when the server reports dev for this request."""
    assert client.get("/api/status", headers=LOCAL).json()["auth_mode"] == "dev"
    assert client.get("/api/status", headers=REMOTE).json()["auth_mode"] == "easyauth"


def test_every_local_alias_counts_as_local(client, admin_id):
    for host in ("localhost", "127.0.0.1:8000", "0.0.0.0:8000"):
        r = client.get("/api/status", headers={"host": host})
        assert r.json()["auth_mode"] == "dev", host


def test_a_lookalike_host_does_not_count_as_local(client, admin_id):
    for host in ("localhost.attacker.com", "notlocalhost", "127.0.0.1.example.com"):
        r = client.get("/api/auth/me", headers={"host": host, "X-CityOS-User": str(admin_id)})
        assert r.status_code == 401, host


def test_an_entra_identity_still_works_from_a_remote_host(client, admin_id):
    """Closing the picker must not close the real front door."""
    import base64, json
    from models import User
    from sqlalchemy.orm import Session
    import main as cityos_main
    with Session(cityos_main.engine) as db:
        email = db.query(User).filter(User.id == admin_id).first().email
    blob = base64.b64encode(json.dumps(
        {"claims": [{"typ": "preferred_username", "val": email}]}).encode()).decode()
    r = client.get("/api/auth/me", headers={**REMOTE, "X-CityOS-User": "",
                                            "X-MS-CLIENT-PRINCIPAL": blob})
    assert r.status_code == 200 and r.json()["id"] == admin_id
