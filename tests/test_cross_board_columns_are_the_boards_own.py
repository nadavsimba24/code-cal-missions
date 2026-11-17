"""העמודות שמוצעות בכלל בין־לוחי הן של שני הלוחות, לא קטלוג קבוע.

Two things were wrong with the fullest cross-board rule the builder could
write, and they look like one thing to the person writing it.

  · "השדות להעתקה" offered five built-ins — סטטוס, עדיפות, תאריך יעד, אחראים,
    תיאור — whichever two boards the rule joined. For a row of checkboxes that
    is the honest list (COPY_FIELDS says so about itself): a column lives on
    one board under one id and on the next under another, so "העתק את «מספר
    הפנייה»" is a PAIR of columns and not a field to tick. The engine has been
    able to carry such a pair since create_mapped_and_link was written — no
    trigger named that action, so it could not be reached from the screen at
    all, and the only cross-board rule that could offered the generic five.

  · the name of the item it creates took a token off «ערך מהפריט» and stored
    it exactly as it was shown — «{{שם הפריט}}» — while the engine's TOKEN_RE
    matches ASCII and nothing else. Nothing resolved, and the rule created an
    item literally named "{{שם הפריט}}". The translation existed; only the
    notice's textarea was doing it.

What is pinned here is that a status change can now reach the mapped action,
that a pair of columns with different ids on the two boards actually carries a
value across, that an incompatible pair is refused in words, and that a token
in the new item's name resolves to the source item rather than to itself.
"""
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Task

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "frontend" / "index.html"

RECIPE = "status_create_mapped_and_link"


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_col(client, bid, admin_id, col):
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id, "columns": _cols(client, bid) + [col]})
    return col["id"]


def _setup(client, admin_id, tag):
    """Two boards joined by a connect column, each with a column of its own.

    The two column ids are deliberately different. That difference IS the
    reason a mapping exists — a shared catalog of five built-ins cannot say
    "«מספר הפנייה» כאן נכנס ל«מספר אסמכתא» שם".
    """
    a = _board(client, admin_id, f"מקור {tag}")
    b = _board(client, admin_id, f"יעד {tag}")
    src_col = _add_col(client, a, admin_id,
                       {"id": f"col_src_{tag}", "type": "text", "title": "מספר הפנייה"})
    dst_col = _add_col(client, b, admin_id,
                       {"id": f"col_dst_{tag}", "type": "text", "title": "מספר אסמכתא"})
    _add_col(client, b, admin_id,
             {"id": f"col_num_{tag}", "type": "number", "title": "עלות"})
    client.patch(f"/api/boards/{a}",
                 json={"actor_id": admin_id,
                       "columns": _cols(client, a) + [
                           {"type": "connect", "title": "קישור",
                            "connect": {"board_ids": [b], "multiple": True,
                                        "two_way": True}}]})
    link = next(x for x in _cols(client, a) if x["type"] == "connect")
    grp = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    return a, b, link, grp, src_col, dst_col, f"col_num_{tag}"


def _rule(client, admin_id, a, b, link, grp, mapping, text="פריט יעד"):
    return client.post(f"/api/boards/{a}/automations",
                       json={"actor_id": admin_id, "recipe_id": RECIPE,
                             "config": {"t_status": "done", "a_connect": link["id"],
                                        "a_board": b, "a_target_group": grp,
                                        "a_text": text, "a_map": mapping}})


def _made(bid, title):
    """What the rule put on the target board — by name, because a new board
    comes seeded with three items of its own and they are not the answer."""
    with Session(cityos_main.engine) as db:
        return db.query(Task).filter(Task.board_id == bid, Task.title == title).all()


# ── שהפעולה בכלל נגישה ─────────────────────────────────────────────────────

def test_a_status_change_can_reach_the_mapped_action():
    """The action existed and nothing led to it — which looks like a product
    decision rather than a pairing nobody wrote down."""
    r = recipes.recipe(RECIPE)
    assert r, "the mapped cross-board rule is not in the catalog"
    assert r["trigger"] == "status_changes_to"
    assert r["action"] == "create_mapped_and_link"
    kinds = {f["key"]: f["type"] for f in r["fields"]}
    assert kinds.get("a_map") == "map", kinds
    assert "a_fields" not in kinds, "the mapped rule must not also offer the fixed five"


def test_the_older_rule_is_left_exactly_as_it_was():
    """A rule somebody already built is not re-asked a question it was never
    asked — which is why this is a new recipe and not a wider old one."""
    old = recipes.recipe("status_create_in_group_and_link")
    kinds = {f["key"]: f["type"] for f in old["fields"]}
    assert kinds.get("a_fields") == "fields", kinds
    assert "a_map" not in kinds, "an existing rule was handed a blank it never had"


def test_the_library_lists_it_under_a_name_of_its_own():
    """Its sentence and its neighbour's read almost alike, and the difference
    between them is the whole point."""
    title = recipes.MVP_TITLES.get(RECIPE, "")
    assert title, "the template would be listed as its bare sentence"
    assert "מפה" in title or "עמודה לעמודה" in title, title


# ── שהערך באמת עובר ────────────────────────────────────────────────────────

def test_a_column_here_lands_in_a_column_of_another_name_there(client, admin_id):
    a, b, link, grp, src_col, dst_col, _ = _setup(client, admin_id, "map1")
    r = _rule(client, admin_id, a, b, link, grp, [{"from": src_col, "to": dst_col}])
    assert r.status_code == 200, r.text
    src = client.post("/api/tasks", json={"board_id": a, "title": "מקור",
                                          "user_id": admin_id,
                                          "custom_fields": {src_col: "פ-2026-11"}}).json()["id"]
    client.patch(f"/api/tasks/{src}", json={"status": "done", "user_id": admin_id})
    made = _made(b, "פריט יעד")
    assert len(made) == 1, [t.title for t in made]
    assert (made[0].custom_fields or {}).get(dst_col) == "פ-2026-11", \
        "the value did not travel into the column the mapping names"


def test_a_pair_the_engine_cannot_carry_is_refused_in_words(client, admin_id):
    """«המערכת תאפשר מיפוי רק בין סוגי שדות תואמים» — and says which two."""
    a, b, link, grp, src_col, _, num_col = _setup(client, admin_id, "map2")
    r = _rule(client, admin_id, a, b, link, grp, [{"from": src_col, "to": num_col}])
    assert r.status_code == 400, r.text
    assert "מספר הפנייה" in r.text and "עלות" in r.text, r.text


def test_the_same_target_twice_is_refused(client, admin_id):
    a, b, link, grp, src_col, dst_col, _ = _setup(client, admin_id, "map3")
    r = _rule(client, admin_id, a, b, link, grp,
              [{"from": src_col, "to": dst_col}, {"from": "title", "to": dst_col}])
    assert r.status_code == 400, r.text


# ── ושהשם החדש מדבר על הפריט שהפעיל את הכלל ───────────────────────────────

def test_a_token_in_the_new_item_s_name_resolves(client, admin_id):
    """The bug as it was reported: «{{שם הפריט}}» came out as itself.

    The engine resolves the CODE, which is what the builder now stores; a rule
    carrying the code has always worked, and this pins that it still does so
    the frontend check below is checking the right half.
    """
    a, b, link, grp, src_col, dst_col, _ = _setup(client, admin_id, "tok1")
    r = _rule(client, admin_id, a, b, link, grp, [{"from": src_col, "to": dst_col}],
              text="בדיקה ל{{item.name}}")
    assert r.status_code == 200, r.text
    src = client.post("/api/tasks", json={"board_id": a, "title": "תיקון מדרכה",
                                          "user_id": admin_id}).json()["id"]
    client.patch(f"/api/tasks/{src}", json={"status": "done", "user_id": admin_id})
    made = _made(b, "בדיקה לתיקון מדרכה")
    assert len(made) == 1, "the token in the name did not resolve"


# ── ומה שרק המסך יכול להבטיח ───────────────────────────────────────────────

def test_the_text_blank_stores_the_code_and_shows_the_name():
    """The notice's textarea has kept this split all along; the one-line value
    box never did, and it is the box «ערך מהפריט» writes into."""
    src = INDEX.read_text(encoding="utf-8")
    cell = src[src.index("  _textCell(raw){"):]
    cell = cell[:cell.index("\n  },")]
    assert "this.namesToTokens(shown)" in cell, "the name went to the engine as a name"
    assert "this.unknownTokens(stored)" in cell, cell
    assert "v:stored,label:shown" in cell, cell
    for fn in ("  setText(key){", "  setActText(i,key){"):
        body = src[src.index(fn):]
        body = body[:body.index("\n  },")]
        assert "this._textCell(" in body, fn
    assert "if(f.type==='text') return mk(this.tokensToNames(v));" in src, \
        "a rule reopened for editing would read its own tokens back as codes"


def test_the_field_mapping_is_no_longer_api_only():
    src = INDEX.read_text(encoding="utf-8")
    assert "toast('מיפוי שדות נערך דרך ה-API" not in src, \
        "the blank still sends the person writing the rule to a terminal"
    assert "async pickMap(key,into){" in src
    # both sides come from the engine's own answer about each board, so the
    # compatibility shown on screen is the one the server will apply
    assert "_mapTargetCols(bid)" in src and "automation-capabilities?board_id=" in src


def test_the_mapping_editor_in_the_browser(client, admin_id):
    """Driven harness: tests/frontend/automation_field_map.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_field_map.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_library_says_what_the_board_must_already_have():
    """«בתנאי שיש עמודת קישור בלוח» — the condition the rule is built under,
    said by the library before it is offered rather than by the save after it.

    The action carried no `needs` while nothing led to it, which cost nothing.
    A template that leads to it on a board with no connect column is a rule
    somebody cannot build and is told nothing about.
    """
    assert set(recipes.needs_of(RECIPE)) == {"connect", "group"}, recipes.needs_of(RECIPE)
    assert "link" in recipes.tags_of(RECIPE), recipes.tags_of(RECIPE)
