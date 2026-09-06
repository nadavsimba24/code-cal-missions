"""An environment's face: the creator's avatar by default, editable afterwards.

Every environment used to be created with the same 🏢. It now starts with no
icon at all, which the client draws as the creator's own avatar — the colour
and initials that already identify that person everywhere else — and the
system-admin screen is where it gets a face of its own: a colour, a glyph on
that colour, or an uploaded picture.

The frontend half (the badge and the picker) runs under node from
tests/frontend/env_appearance.mjs; the rest is the API that stores it.
"""
import pathlib
import shutil
import subprocess

import pytest

from conftest import ADMIN_ID

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "env_appearance.mjs"


def test_the_badge_and_the_picker():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


@pytest.fixture
def env(client):
    e = client.post("/api/environments", json={"actor_id": ADMIN_ID, "name": "סביבת מראה"})
    assert e.status_code == 200, e.text
    e = e.json()
    yield e
    client.delete(f"/api/environments/{e['id']}?actor_id={ADMIN_ID}")


def test_a_new_environment_has_no_icon_of_its_own(client, env):
    """Which is what makes the creator's avatar the default, rather than one
    building emoji standing in for every environment in the system."""
    assert not env["icon"]
    assert env["created_by"] == ADMIN_ID


def test_the_creator_travels_with_the_environment(client, env):
    """The client cannot draw whose avatar it is without being told."""
    listed = next(e for e in client.get(f"/api/environments?user_id={ADMIN_ID}").json()["environments"]
                  if e["id"] == env["id"])
    assert listed["created_by"] == ADMIN_ID


def test_a_glyph_and_a_colour_can_be_set(client, env):
    r = client.patch(f"/api/environments/{env['id']}",
                     json={"actor_id": ADMIN_ID, "icon": "fa:crown", "color": "#ef4444"})
    assert r.status_code == 200, r.text
    assert r.json()["icon"] == "fa:crown"
    assert r.json()["color"] == "#ef4444"


def test_an_uploaded_url_fits_the_column(client, env):
    """The icon column is 50 characters; an upload URL is /api/files/<32 hex>."""
    url = "/api/files/" + "a" * 32
    assert len(url) <= 50
    r = client.patch(f"/api/environments/{env['id']}", json={"actor_id": ADMIN_ID, "icon": url})
    assert r.status_code == 200, r.text
    assert r.json()["icon"] == url


def test_the_icon_can_be_cleared_back_to_the_avatar(client, env):
    """An empty icon is a choice, not a missing field — so it must be storable
    and must survive the round trip, or "reset" would silently do nothing."""
    client.patch(f"/api/environments/{env['id']}", json={"actor_id": ADMIN_ID, "icon": "fa:bolt"})
    r = client.patch(f"/api/environments/{env['id']}", json={"actor_id": ADMIN_ID, "icon": ""})
    assert r.status_code == 200, r.text
    assert not r.json()["icon"]
    listed = next(e for e in client.get(f"/api/environments?user_id={ADMIN_ID}").json()["environments"]
                  if e["id"] == env["id"])
    assert not listed["icon"]


def test_a_patch_that_names_no_icon_leaves_it_alone(client, env):
    """Renaming must not wipe the face — the two travel in the same endpoint."""
    client.patch(f"/api/environments/{env['id']}", json={"actor_id": ADMIN_ID, "icon": "fa:gem"})
    r = client.patch(f"/api/environments/{env['id']}", json={"actor_id": ADMIN_ID, "name": "שם אחר"})
    assert r.status_code == 200, r.text
    assert r.json()["icon"] == "fa:gem"
    assert r.json()["name"] == "שם אחר"
