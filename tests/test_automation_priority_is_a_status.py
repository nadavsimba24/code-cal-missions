"""עדיפות היא עמודה מסוג סטטוס — וגם הקטלוג צריך לנהוג בה ככזו.

FIELD_MATRIX has said so all along: priority's `kind` is "status", and the
filter engine, the conditions, the operator matrix and the blockers have all
treated it that way. The CATALOG had not.

    "כאשר הסטטוס משתנה"  could be paired with twelve actions
    "כאשר העדיפות משתנה" could be paired with two

    "שנה את הסטטוס"      was reachable from thirteen triggers
    "שנה את העדיפות"     was reachable from five

Nothing in the engine was missing — a recipe is a trigger, an action and the
blanks between them, and every one of these pairings would have run. They had
simply never been written down. The failure was invisible from the outside:
the builder offers what the catalog holds, so "כאשר העדיפות משתנה ל«דחוף»,
העבר את הפריט לקבוצה" looked like a product decision rather than a list
nobody had finished.

Two pairings stay out, and both on purpose — see _derive_priority_recipes.
"""
import pathlib
import sys

from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import automations as recipes  # noqa: E402
import main as cityos_main  # noqa: E402
from models import Task  # noqa: E402


def _pairs():
    by_trigger, by_action = {}, {}
    for r in recipes.RECIPES:
        by_trigger.setdefault(r["trigger"], set()).add(r["action"])
        by_action.setdefault(r["action"], set()).add(r["trigger"])
    return by_trigger, by_action


def test_the_matrix_has_always_called_it_a_status():
    assert recipes.FIELD_MATRIX["priority"]["kind"] == "status"
    assert recipes.FIELD_MATRIX["priority"]["kind"] == \
        recipes.FIELD_MATRIX["status"]["kind"]


def test_a_priority_change_sets_off_what_a_status_change_does():
    """Everything but one, and the one is a rule that answers itself."""
    by_trigger, _ = _pairs()
    on_status = by_trigger["status_changes_to"]
    on_priority = by_trigger["priority_changes_to"]
    missing = on_status - on_priority
    assert missing == {"set_priority"}, missing


def test_and_a_priority_can_be_set_by_everything_that_sets_a_status():
    """Everything but the priority change itself, which is the same self-loop
    said from the other side."""
    _, by_action = _pairs()
    missing = by_action["set_status"] - by_action["set_priority"]
    assert missing == {"priority_changes_to"}, missing


def test_priority_never_answers_itself():
    """The status twin of this exists only because a board may carry several
    status COLUMNS — "שנה את «שלב» כאשר «סטטוס אישור» משתנה" is two different
    columns. There is one priority, so the same shape is a self-loop."""
    assert not [r for r in recipes.RECIPES
                if r["trigger"] == "priority_changes_to"
                and r["action"] == "set_priority"]


def test_a_derived_recipe_is_a_recipe_like_any_other():
    """It has to be, or the half of the product that reads the catalog —
    the library, the tags, the versions, the sentence — would answer "" for
    exactly the rules nobody wrote by hand."""
    for rid in ("priority_move_group", "every_days_set_priority",
                "priority_set_status", "column_changed_set_priority"):
        r = recipes.recipe(rid)
        assert r, rid
        assert recipes.sentence(rid).count("{") == len(
            [f for f in r["fields"] if "{" + f["key"] + "}" in recipes.sentence(rid)]), rid
        assert recipes.tags_of(rid) is not None
        assert recipes.needs_of(rid) == sorted(set(recipes.needs_of(rid)))
        assert recipes.template_version(rid) >= 1
        # the priority blank is a priority, not a status left behind by the twin
        keys = {f["key"]: f["type"] for f in r["fields"]}
        if r["action"] == "set_priority":
            assert keys.get("a_priority") == "priority", keys
            assert "a_status" not in keys, keys
        if r["trigger"] == "priority_changes_to":
            assert keys.get("t_priority") == "priority", keys
            assert "t_status" not in keys, keys


def test_every_derived_id_is_its_own(client, admin_id):
    ids = [r["id"] for r in recipes.RECIPES]
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
    served = client.get("/api/automations/recipes").json()["recipes"]
    assert len(served) == len(ids)


# ── and they run ──────────────────────────────────────────────────────────
def test_a_priority_change_moves_the_item(client, admin_id):
    """The rule from the report, end to end: it could not be built at all."""
    bid = client.post("/api/boards",
                      json={"name": "לוח עדיפות", "user_id": admin_id}).json()["id"]
    b = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    first, second = b["groups"][0]["id"], b["groups"][1]["id"]
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "priority_move_group",
                          "config": {"t_priority": "high", "a_group": second}})
    assert r.status_code == 200, r.text
    assert "כאשר העדיפות משתנה" in r.json()["sentence"], r.json()["sentence"]
    tid = client.post("/api/tasks",
                      json={"board_id": bid, "user_id": admin_id, "title": "פ",
                            "group_id": first}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "priority": "high"})
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.id == tid).first().group_id == second


def test_a_recurring_rule_can_raise_a_priority(client, admin_id):
    bid = client.post("/api/boards",
                      json={"name": "לוח הסלמה", "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "every_days_set_priority",
                          "config": {"t_days": 7, "a_priority": "high"}})
    assert r.status_code == 200, r.text
    assert "כל «7» ימים" in r.json()["sentence"], r.json()["sentence"]


def test_a_wrong_value_is_reported_the_way_a_wrong_status_is(client, admin_id):
    """The half that was already right, pinned so it stays that way: a
    priority outside the board's vocabulary is a blocker, exactly as a status
    outside its column's vocabulary is."""
    bid = client.post("/api/boards",
                      json={"name": "לוח ערכים", "user_id": admin_id}).json()["id"]
    v = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "urgent"}})
    assert v.status_code == 200, v.text
    assert any("העדיפות" in b for b in v.json()["blockers"]), v.json()
