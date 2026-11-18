"""אוטומציה — "כשמוסיפים או מסירים אחראי, הודע לאחראי עצמו".

Both triggers were already there: "כאשר משויך אדם לפריט" and "כאשר מוסר
שיוך של אדם מהפריט". What could not be said was WHO to tell, because the
recipient list had five answers and none of them was the person the event is
about:

· "המשתמש שביצע את השינוי" is whoever did the assigning — the manager who
  handed the job out, not the one who got it;
· "למשויכים לפריט" is everybody currently on it, which is the wrong list on
  an addition and an empty promise on a REMOVAL: by the time the rule runs
  the person is no longer among them, so the one person the news is about is
  the one person that action cannot reach;
· "משתמש קבוע" is a name chosen when the rule was written, which is the
  opposite of "whoever it turns out to be".

So the missing piece is a recipient and not a trigger — and because it is a
recipient, both triggers gain it at once and every other action in the
catalog goes on working exactly as it did.

What is pinned here:

· the added person is told, and nobody else is;
· the removed person is told — the case the whole thing exists for — and
  being taken off the item does not take the notification away, because
  seeing an item is a board role and a per-item override and never
  assignment;
· a rule whose trigger carries no such person is REFUSED when it is written,
  not left to resolve into nobody at three in the morning;
· and the test screen, which has no event behind it, says the person will be
  known at run time rather than reporting that there is nobody.
"""
import pathlib
import shutil
import subprocess
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import automations as recipes  # noqa: E402
import main as cityos_main  # noqa: E402
from models import Notification  # noqa: E402

HARNESS = ROOT / "tests" / "frontend" / \
    "automation_notifies_the_person_whose_assignment_changed.mjs"


def _board(client, admin_id, who):
    bid = client.post("/api/boards",
                      json={"name": "לוח שיוכים", "user_id": admin_id}).json()["id"]
    for uid in who:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    return bid


def _rule(client, bid, admin_id, recipe_id, config):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config})


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                           "title": title}).json()["id"]


def _assign(client, tid, admin_id, who):
    return client.post(f"/api/tasks/{tid}/assignees",
                       json={"actor_id": admin_id, "user_id": who})


def _unassign(client, tid, admin_id, who):
    return client.post(f"/api/tasks/{tid}/assignees",
                       json={"actor_id": admin_id, "user_id": who, "action": "remove"})


def _bells(uid, task_id):
    """The automation's own notifications for this person on this item.

    `type == "automation"` and not merely "anything that arrived": assigning
    somebody also sends the product's own built-in "שויכת למשימה", and a test
    that counted every row would pass on the wrong one.
    """
    with Session(cityos_main.engine) as db:
        return db.query(Notification).filter(
            Notification.user_id == uid,
            Notification.task_id == task_id,
            Notification.type == "automation").all()


EVENT_PERSON = {"kind": "event_person"}


# ── the catalog says it exists, and says where it belongs ──────────────────

def test_the_recipient_is_offered_with_the_triggers_it_belongs_to():
    cat = {r["key"]: r for r in recipes.recipients_catalog()}
    assert "event_person" in cat, "the recipient is not in the catalog at all"
    one = cat["event_person"]
    assert one["takes_value"] is False, "it is read off the event, not chosen"
    assert sorted(one["triggers"]) == ["person_assigned", "person_unassigned"]
    # and the five that were always there are unrestricted, or every rule
    # written before this would stop being saveable
    for key in ("user", "field", "actor", "owner", "board_admin"):
        assert cat[key]["triggers"] == [], key


# ── an addition ────────────────────────────────────────────────────────────

def test_the_person_who_was_added_is_the_person_who_is_told(client, admin_id,
                                                            member_id, guinea_id):
    bid = _board(client, admin_id, [member_id, guinea_id])
    assert _rule(client, bid, admin_id, "assigned_notify_person",
                 {"a_person": EVENT_PERSON}).status_code == 200
    tid = _item(client, bid, admin_id)
    assert _assign(client, tid, admin_id, member_id).status_code == 200

    assert len(_bells(member_id, tid)) == 1, "the person put on the job was not told"
    assert _bells(admin_id, tid) == [], \
        "it told the manager who did the assigning — that is the actor, not this"
    assert _bells(guinea_id, tid) == [], "it told somebody the event was not about"


def test_a_second_person_added_later_gets_their_own_and_only_their_own(
        client, admin_id, member_id, guinea_id):
    """One rule, two events, two different recipients — which is the whole
    reason this is read off the event rather than chosen when the rule is
    written."""
    bid = _board(client, admin_id, [member_id, guinea_id])
    assert _rule(client, bid, admin_id, "assigned_notify_person",
                 {"a_person": EVENT_PERSON}).status_code == 200
    tid = _item(client, bid, admin_id)
    _assign(client, tid, admin_id, member_id)
    _assign(client, tid, admin_id, guinea_id)

    assert len(_bells(member_id, tid)) == 1, \
        "the first person was told again when the second was added"
    assert len(_bells(guinea_id, tid)) == 1


# ── a removal: the case the whole thing exists for ─────────────────────────

def test_the_person_who_was_removed_is_told_although_they_are_no_longer_on_it(
        client, admin_id, member_id):
    """"שלח למשויכים לפריט" cannot do this one. The rule runs after the
    removal, so the person it is about is not among the item's assignees any
    more — and seeing the item is a board role, never assignment, so the
    notification still reaches them."""
    bid = _board(client, admin_id, [member_id])
    tid = _item(client, bid, admin_id)
    _assign(client, tid, admin_id, member_id)
    # the rule is written AFTER the assignment, so the addition cannot be what
    # fires it and the only event in play is the removal
    assert _rule(client, bid, admin_id, "unassigned_notify_person",
                 {"a_person": EVENT_PERSON}).status_code == 200
    assert _unassign(client, tid, admin_id, member_id).status_code == 200

    assert len(_bells(member_id, tid)) == 1, "the person taken off the job was not told"
    assert _bells(admin_id, tid) == []


def test_an_addition_does_not_fire_the_removal_rule(client, admin_id, member_id):
    bid = _board(client, admin_id, [member_id])
    assert _rule(client, bid, admin_id, "unassigned_notify_person",
                 {"a_person": EVENT_PERSON}).status_code == 200
    tid = _item(client, bid, admin_id)
    _assign(client, tid, admin_id, member_id)
    assert _bells(member_id, tid) == [], "a שיוך fired the הסרת-שיוך rule"


# ── refused where the event carries no such person ─────────────────────────

@pytest.mark.parametrize("recipe_id,config", [
    ("created_notify_person", {}),
    ("status_notify_person", {"t_status": "done"}),
    ("due_notify_person", {}),
])
def test_a_trigger_with_no_such_person_refuses_the_rule(client, admin_id,
                                                        member_id, recipe_id, config):
    """Refused where it is written. A rule somebody believes is working and
    which resolves to nobody every time is worse than one that would not
    save."""
    if not recipes.recipe(recipe_id):
        pytest.skip(f"no such recipe: {recipe_id}")
    bid = _board(client, admin_id, [member_id])
    r = _rule(client, bid, admin_id, recipe_id, dict(config, a_person=EVENT_PERSON))
    assert r.status_code >= 400, "it saved a rule whose event has nobody to tell"
    assert "שיוך" in r.text, r.text


def test_an_extra_action_is_held_to_the_same_rule(client, admin_id, member_id):
    """An action added beside the recipe's own is validated by a different
    function, and a pairing enforced in only one of the two is a pairing with
    a way round it."""
    bid = _board(client, admin_id, [member_id])
    r = _rule(client, bid, admin_id, "created_set_status",
              {"a_status": "in_progress",
               recipes.ACTIONS_KEY: [{"key": "notify_person",
                                      "values": {"person": EVENT_PERSON}}]})
    assert r.status_code >= 400, "the extra action smuggled it in"
    assert "שיוך" in r.text, r.text


def test_the_pairing_holds_on_the_trigger_it_belongs_to(client, admin_id, member_id):
    """The same extra action, under a trigger that does carry the person —
    this is the half that must still work."""
    bid = _board(client, admin_id, [member_id])
    r = _rule(client, bid, admin_id, "assigned_set_status",
              {"a_status": "in_progress",
               recipes.ACTIONS_KEY: [{"key": "notify_person",
                                      "values": {"person": EVENT_PERSON}}]})
    assert r.status_code == 200, r.text
    tid = _item(client, bid, admin_id)
    _assign(client, tid, admin_id, member_id)
    assert len(_bells(member_id, tid)) == 1


# ── the test screen, which has no event ────────────────────────────────────

def test_the_dry_run_says_the_person_is_not_known_yet(client, admin_id, member_id):
    """Running a rule against a real item on the test screen has no event
    behind it. "אין נמען" would read as a broken rule; what it says instead is
    when the answer will be known."""
    bid = _board(client, admin_id, [member_id])
    a = _rule(client, bid, admin_id, "assigned_notify_person",
              {"a_person": EVENT_PERSON}).json()
    tid = _item(client, bid, admin_id)
    r = client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}",
                    json={"task_id": tid})
    assert r.status_code == 200, r.text
    assert "בזמן ההפעלה" in r.text, r.text


# ── the builder's own side ─────────────────────────────────────────────────

def test_the_builder_offers_it_only_where_it_means_something():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
