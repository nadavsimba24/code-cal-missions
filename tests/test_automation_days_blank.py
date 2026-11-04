"""«כל כמה ימים» — הסרת ה-placeholder, והשלוש שנשארו אחריו.

The blank was a bare number box carrying its own label as a placeholder:
text that repeated what the sentence behind it already said, and that
disappeared the moment anybody typed into it. Taking it out leaves nothing
saying what the number is for, so the question is asked once, above the box,
where it stays.

Three things are worth more than the placeholder was, and the browser half of
each is pinned in tests/frontend/automation_days_blank.mjs:

  · the floor is the FIELD's. A recurring rule counts days and cannot count
    nought of them — MIN_EVERY_DAYS is one — and the server rounded a nought
    up silently. A value somebody chose being replaced without a word is
    worse than one being refused, because nothing on screen says it happened.
  · a number alone does not say what it means, so a line under the box reads
    the sentence the rule will actually run under.
  · almost every answer is one of four.

What is checked HERE is the half the browser cannot promise: that the floor
it enforces is the one the server declares, and that the server still has the
last word on a value that gets past it.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import automations as recipes  # noqa: E402

INDEX = ROOT / "frontend" / "index.html"


def test_the_browser_half(capsys):
    r = subprocess.run(["node", str(ROOT / "tests" / "frontend" /
                                    "automation_days_blank.mjs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_floor_the_box_enforces_is_the_one_the_recipe_declares():
    """Two numbers that must not drift apart: the `min` the catalog puts on
    the field, and the one the picker refuses below."""
    r = recipes.recipe("every_days_notify_person")
    days = next(f for f in r["fields"] if f["key"] == "t_days")
    assert days["min"] == recipes.MIN_EVERY_DAYS == 1
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("    if(f.type==='days'){")
    body = src[i:src.index("\n    }", i)]
    # read off the field, never written into the markup as a constant
    assert "(typeof f.min==='number')?f.min:0" in body, body
    assert 'min="${lo}"' in body, body
    assert "placeholder" not in body, "the placeholder came back"


def test_the_days_before_and_after_blanks_have_no_floor():
    """Nought days before the due date is the due date — a real answer, and
    the reason the floor is the field's rather than one number for all."""
    for rid in ("due_near_notify_person", "due_passed_notify_assignees"):
        days = next(f for f in recipes.recipe(rid)["fields"] if f["key"] == "t_days")
        assert "min" not in days, (rid, days)


def test_the_server_still_has_the_last_word(client, admin_id):
    """The browser refusing a nought is a courtesy, not the rule. A caller
    that never saw the picker — the API, an import, an older tab — still
    lands on something the engine can run."""
    bid = client.post("/api/boards",
                      json={"name": "לוח ימים", "user_id": admin_id}).json()["id"]
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "every_days_notify_assignees",
                          "config": {"t_days": 0}})
    assert r.status_code == 200, r.text
    assert r.json()["config"]["t_days"] == recipes.MIN_EVERY_DAYS
