"""אפשר לערוך אוטומציה שכבר הוגדרה — את הכלל עצמו, לא רק את שמו.

"ערוך" opened the name, the description, the owner and the running order:
everything ABOUT the rule and nothing the rule DOES. The sentence itself was
fixed at creation, so a trigger pointed at the wrong column, or a status
picked by mistake, meant deleting the rule and building it again — which
throws away its history, its owner, its running order and its id, and every
reference anybody had to it.

The server has taken a changed configuration all along, and takes it
carefully: while the rule is ACTIVE the edit is written as a draft version
and the live rule goes on running until somebody publishes it, which is the
banner that already says "גרסה N ממתינה להפעלה". The one thing missing in
between was a builder opened on a rule that exists.

The screen is the hard half, and it is covered by the driven harness. What
is pinned here is the contract underneath it, because the editor is only
safe if these hold:

  · an active rule's live configuration is NOT touched by a save — it
    becomes a pending version, and the rule goes on running what it ran
  · the pending version's configuration is readable, because that is what a
    second edit has to continue from rather than silently discard
  · a paused or draft rule is changed outright, with no version to publish
  · a save aimed at a version that has moved on is refused, and the refusal
    says what the rule reads now
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
from models import Automation

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"


def _board(client, admin_id, name="לוח עריכה"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _rule(client, bid, admin_id, config=None, status="active"):
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "created_set_priority",
                          "config": config or {"a_priority": "high"},
                          "status": status})
    assert r.status_code == 200, r.text
    return r.json()


def _live(aid):
    with Session(cityos_main.engine) as db:
        a = db.query(Automation).filter(Automation.id == aid).first()
        return dict(a.config or {}), a.draft_version, a.status


# ── an active rule keeps running what it is running ───────────────────────

def test_editing_an_active_rule_leaves_the_live_one_alone(client, admin_id):
    bid = _board(client, admin_id)
    a = _rule(client, bid, admin_id)
    r = client.patch(f"/api/automations/{a['id']}",
                     json={"user_id": admin_id, "config": {"a_priority": "low"}})
    assert r.status_code == 200, r.text
    cfg, draft, status = _live(a["id"])
    assert cfg == {"a_priority": "high"}, cfg      # untouched
    assert draft, "the edit left nothing to publish"
    assert status == "active"


def test_the_pending_version_is_readable_so_a_second_edit_can_continue_it(
        client, admin_id):
    """Without this an editor opened on the live rule would quietly throw the
    waiting version away, and nobody would be told it had happened."""
    bid = _board(client, admin_id, "לוח טיוטה")
    a = _rule(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}",
                 json={"user_id": admin_id, "config": {"a_priority": "low"}})
    _, draft, _ = _live(a["id"])
    v = client.get(f"/api/automations/{a['id']}/versions?user_id={admin_id}")
    assert v.status_code == 200, v.text
    row = next((x for x in v.json()["versions"] if x["version"] == draft), None)
    assert row, [x["version"] for x in v.json()["versions"]]
    assert (row["snapshot"] or {}).get("config") == {"a_priority": "low"}, row


def test_publishing_the_pending_version_is_what_makes_it_live(client, admin_id):
    bid = _board(client, admin_id, "לוח פרסום")
    a = _rule(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}",
                 json={"user_id": admin_id, "config": {"a_priority": "low"}})
    r = client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}",
                    json={"user_id": admin_id})
    assert r.status_code == 200, r.text
    cfg, draft, _ = _live(a["id"])
    assert cfg == {"a_priority": "low"}, cfg
    assert not draft


# ── a rule that is not running is changed outright ────────────────────────

def test_editing_a_paused_rule_applies_at_once(client, admin_id):
    bid = _board(client, admin_id, "לוח מושהה")
    a = _rule(client, bid, admin_id)
    client.patch(f"/api/automations/{a['id']}",
                 json={"user_id": admin_id, "status": "paused"})
    r = client.patch(f"/api/automations/{a['id']}",
                     json={"user_id": admin_id, "config": {"a_priority": "low"}})
    assert r.status_code == 200, r.text
    cfg, draft, _ = _live(a["id"])
    assert cfg == {"a_priority": "low"} and not draft, (cfg, draft)


def test_a_draft_may_be_saved_half_built(client, admin_id):
    """Which is what a draft is for — and why the editor leaves its button
    enabled where it disables it for a rule that runs."""
    bid = _board(client, admin_id, "לוח טיוטה חלקית")
    a = _rule(client, bid, admin_id, config={}, status="draft")
    r = client.patch(f"/api/automations/{a['id']}",
                     json={"user_id": admin_id, "config": {}})
    assert r.status_code == 200, r.text
    assert _live(a["id"])[2] == "draft"


# ── and a save aimed at a version that moved on is refused ────────────────

def test_a_stale_edit_is_refused_rather_than_silently_winning(client, admin_id):
    bid = _board(client, admin_id, "לוח התנגשות")
    a = _rule(client, bid, admin_id)
    stale = a["etag"]
    # somebody else renames it, which moves the version on
    assert client.patch(f"/api/automations/{a['id']}",
                        json={"user_id": admin_id, "name": "שם אחר"}).status_code == 200
    r = client.patch(f"/api/automations/{a['id']}",
                     json={"user_id": admin_id, "etag": stale,
                           "config": {"a_priority": "low"}})
    assert r.status_code == 409, (r.status_code, r.text)


def test_only_somebody_who_may_manage_automations_can_edit_one(
        client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח הרשאה")
    a = _rule(client, bid, admin_id)
    r = client.patch(f"/api/automations/{a['id']}",
                     json={"user_id": guinea_id, "config": {"a_priority": "low"}})
    assert r.status_code == 403, r.text
    assert _live(a["id"])[0] == {"a_priority": "high"}


# ── the browser's half ─────────────────────────────────────────────────────

def test_the_menu_offers_editing_the_rule_and_not_only_its_details():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  menuHTML(a,which){"):]
    fn = fn[:fn.index("\n  },")]
    assert "Automations.editRule(" in fn, fn
    # the old entry is still there, named for what it actually does
    assert "'פרטים — שם, בעלות וסדר'" in fn, fn


def test_an_edit_starts_from_what_was_stored():
    """Rebuilding the configuration from the screen alone would delete every
    key the builder has no blank for — a field mapping is edited through the
    API and nowhere else."""
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  async save(asDraft){"):]
    fn = fn[:fn.index("\n  },")]
    assert "const config=ed?{...(this.building.base||{})}:{};" in fn, fn
    # …and the three the builder DOES own are cleared, or a removal would merge
    assert "delete config.conditions; delete config.conditions_op; delete config.actions;" in fn, fn
    assert "method:'PATCH'" in fn, fn


def test_a_pending_draft_is_what_the_edit_continues():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  async editRule(id){"):]
    fn = fn[:fn.index("\n  },")]
    assert "a.draft_version" in fn and "/versions" in fn, fn
    assert "snapshot.config" in fn, fn


def test_the_round_trip(client, admin_id):
    """Driven harness: tests/frontend/automation_edit_rule.mjs.

    Verified to fail: start save()'s config from {} when editing and the
    carried-through key goes red; merge instead of clearing and the removal
    cases do.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_edit_rule.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
