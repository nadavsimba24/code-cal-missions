"""להשתמש ב"עדיפות" באוטומציות כעמודת סטטוס.

A priority is a labelled, coloured, board-defined vocabulary — the same shape
as a status, which is why FIELD_MATRIX has called its kind "status" all along
and why the advanced filter has always offered it as one.

Automations had not. A rule could be about "הסטטוס של הלוח" or about a column
of type status, and priority was neither. Naming it anyway was the worst of
the three outcomes: the rule SAVED, and then sat there reporting that a
column had been deleted which had never existed.

It is a source of its own now, under the built-in's own name, and the two
spellings of the same rule are deliberately both kept:

    כאשר העדיפות משתנה ל«גבוהה»        — the dedicated trigger
    כאשר «עדיפות» משתנה ל«גבוהה»       — the status blank, pointed at it

They are one moment, so a change announces itself as both. Dropping either
would retire rules somebody already wrote; keeping only one would leave the
other spelling silently dead, which is what this is fixing.
"""
import pathlib
import sys

from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import main as cityos_main  # noqa: E402
from models import Task  # noqa: E402

INDEX = ROOT / "frontend" / "index.html"
PRIO = cityos_main.PRIORITY_AS_STATUS


def _board(client, admin_id, name="לוח עדיפות כסטטוס"):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    return bid, client.get(f"/api/boards/{bid}?user_id={admin_id}").json()


def _rule(client, bid, admin_id, recipe_id, config):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config})


def _task(tid):
    with Session(cityos_main.engine) as db:
        return db.query(Task).filter(Task.id == tid).first()


# ── it is a vocabulary like any other ─────────────────────────────────────
def test_the_priority_answers_as_a_status_vocabulary(client, admin_id):
    bid, _ = _board(client, admin_id)
    with Session(cityos_main.engine) as db:
        b = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        opts, col = cityos_main._status_vocab(b, PRIO)
    assert col, "a column that is not there is what this used to answer"
    assert col["title"] == "עדיפות"
    keys = {o["key"] for o in opts}
    assert "high" in keys and "critical" in keys, keys
    # keyed the way every other status vocabulary comes back from here
    assert all(set(o) >= {"key", "label"} for o in opts), opts


def test_a_rule_naming_it_is_not_reported_as_broken(client, admin_id):
    """The whole of the report: it saved, and then said a column had been
    deleted which had never existed."""
    bid, b = _board(client, admin_id)
    v = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "status_move_group",
                          "config": {"t_status": "high", "t_status_col": PRIO,
                                     "a_group": b["groups"][1]["id"]}})
    assert v.status_code == 200, v.text
    assert v.json()["blockers"] == [], v.json()["blockers"]


def test_a_value_outside_the_vocabulary_is_still_refused(client, admin_id):
    """It is a vocabulary, so it refuses what is not in it — exactly as a
    status column does."""
    bid, b = _board(client, admin_id)
    v = client.post(f"/api/boards/{bid}/automations/validate?user_id={admin_id}",
                    json={"recipe_id": "status_move_group",
                          "config": {"t_status": "nonsense", "t_status_col": PRIO,
                                     "a_group": b["groups"][1]["id"]}})
    assert any("אינו קיים" in x or "אינה קיימת" in x
               for x in v.json()["blockers"]), v.json()


def test_the_sentence_calls_it_by_its_name(client, admin_id):
    """Not «priority» — the id is what is stored, never what is read."""
    bid, b = _board(client, admin_id)
    r = _rule(client, bid, admin_id, "status_move_group",
              {"t_status": "high", "t_status_col": PRIO,
               "a_group": b["groups"][1]["id"]})
    assert "«עדיפות»" in r.json()["sentence"], r.json()["sentence"]
    assert "priority" not in r.json()["sentence"], r.json()["sentence"]


# ── and it runs, both ways round ──────────────────────────────────────────
def test_a_priority_change_sets_off_a_rule_written_as_a_status(client, admin_id):
    bid, b = _board(client, admin_id)
    first, second = b["groups"][0]["id"], b["groups"][1]["id"]
    assert _rule(client, bid, admin_id, "status_move_group",
                 {"t_status": "high", "t_status_col": PRIO,
                  "a_group": second}).status_code == 200
    tid = client.post("/api/tasks",
                      json={"board_id": bid, "user_id": admin_id, "title": "פ",
                            "group_id": first}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "priority": "high"})
    assert _task(tid).group_id == second


def test_an_action_written_as_a_status_writes_the_priority(client, admin_id):
    bid, _ = _board(client, admin_id)
    assert _rule(client, bid, admin_id, "created_set_status",
                 {"a_status": "critical", "a_status_col": PRIO}).status_code == 200
    tid = client.post("/api/tasks", json={"board_id": bid, "user_id": admin_id,
                                          "title": "ב"}).json()["id"]
    assert cityos_main._task_priority_key(_task(tid)) == "critical"


def test_both_spellings_hear_the_same_change(client, admin_id):
    """One moment, two ways of having written the rule about it. A board
    carrying both must fire both, or whichever spelling somebody did not use
    is a rule that silently never runs."""
    bid, b = _board(client, admin_id)
    second = b["groups"][1]["id"]
    assert _rule(client, bid, admin_id, "status_move_group",
                 {"t_status": "high", "t_status_col": PRIO,
                  "a_group": second}).status_code == 200
    assert _rule(client, bid, admin_id, "priority_set_status",
                 {"t_priority": "high", "a_status": "done"}).status_code == 200
    tid = client.post("/api/tasks",
                      json={"board_id": bid, "user_id": admin_id, "title": "ג",
                            "group_id": b["groups"][0]["id"]}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "priority": "high"})
    t = _task(tid)
    assert t.group_id == second, "the status spelling did not fire"
    assert cityos_main._task_status_key(t) == "done", "the priority spelling did not fire"


def test_a_rules_own_write_wakes_the_other_spelling_too(client, admin_id):
    """A priority set BY a rule is as much a priority change as one somebody
    typed, and the status spelling has to hear it."""
    bid, b = _board(client, admin_id)
    second = b["groups"][1]["id"]
    assert _rule(client, bid, admin_id, "created_set_priority",
                 {"a_priority": "high"}).status_code == 200
    assert _rule(client, bid, admin_id, "status_move_group",
                 {"t_status": "high", "t_status_col": PRIO,
                  "a_group": second}).status_code == 200
    tid = client.post("/api/tasks",
                      json={"board_id": bid, "user_id": admin_id, "title": "ד",
                            "group_id": b["groups"][0]["id"]}).json()["id"]
    assert _task(tid).group_id == second


def test_a_rule_about_the_boards_own_status_is_untouched(client, admin_id):
    """The one that would be a silent regression: naming no column still
    means the board's own statuses, not the priority."""
    bid, b = _board(client, admin_id)
    second = b["groups"][1]["id"]
    assert _rule(client, bid, admin_id, "status_move_group",
                 {"t_status": "done", "a_group": second}).status_code == 200
    tid = client.post("/api/tasks",
                      json={"board_id": bid, "user_id": admin_id, "title": "ה",
                            "group_id": b["groups"][0]["id"]}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "priority": "high"})
    assert _task(tid).group_id != second, "a priority change moved a status rule"
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "status": "done"})
    assert _task(tid).group_id == second


# ── the browser offers it ─────────────────────────────────────────────────
def test_the_picker_offers_it_on_every_board():
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("  _statusSources(){")
    body = src[i:src.index("\n  },", i)]
    assert "'עדיפות'" in body and "PRIORITY_AS_STATUS" in body, body
    # the browser and the server agree on the id
    assert f"PRIORITY_AS_STATUS:'{PRIO}'" in src
    # …and the values offered under it are the board's priorities
    i = src.index("  _optionsFor(")
    body = src[i:src.index("\n    if(type==='group')", i)]
    assert "boardPriorityList()" in body and "PRIORITY_AS_STATUS" in body, body


def test_a_plain_board_can_reach_it_without_an_extra_click_everywhere():
    """The step BEFORE the values stays gated on the board actually having a
    status column — making everybody confirm the only obvious answer would be
    a click bought with nothing. The way in on a plain board is the line at
    the top of the values instead."""
    src = INDEX.read_text(encoding="utf-8")
    i = src.index("  _statusSourceLine(key,into){")
    body = src[i:src.index("\n  },", i)]
    assert "this._statusSources().length<2" in body, body
    assert "_statusCols().length" not in body, "it is still gated on columns"
    # and the chip reads as a name, not as the id
    i = src.index("  _colCell(id){")
    body = src[i:src.index("\n  },", i)]
    assert "'עדיפות'" in body, body
