"""Group — כללי ביצוע, התנגשויות והשהיה.

Three things the module half-did:

  · the order rules fire in could be set one rule at a time, which is how two
    of them end up claiming the same number — and then the order between them
    is their ids, which is not an order anybody chose;
  · a conflict between two rules writing one field was reported BEFORE a rule
    was switched on and never again afterwards;
  · a board whose automations are frozen read as an ordinary board with four
    active rules and no explanation of why nothing was happening.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationVersion, Task


def _board(client, admin_id, name="לוח סדר"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _member(client, admin_id, bid, uid, role="editor"):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id,
                          "config": config or {"a_priority": "high"}, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _order(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    r = client.get(f"/api/boards/{bid}/automations/order?user_id={admin_id}{qs}")
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


# ── כללי ביצוע: the order, and who decides it ──────────────────────────────

def test_the_order_is_run_order_and_then_the_id(client, admin_id):
    bid = _board(client, admin_id, "לוח סדר בסיסי")
    a = _add(client, bid, admin_id, name="ראשון")
    b = _add(client, bid, admin_id, name="שני")
    c = _add(client, bid, admin_id, name="שלישי")
    # all three sit on the default, in the middle of the range, so the order
    # between them is when each came into service and then its id
    assert [x["run_order"] for x in _order(client, bid, admin_id)["order"]] \
        == [cityos_main.RUN_ORDER_DEFAULT] * 3
    assert [x["id"] for x in _order(client, bid, admin_id)["order"]] == \
        [a["id"], b["id"], c["id"]]
    # moved by hand, one rule at a time
    client.patch(f"/api/automations/{c['id']}?user_id={admin_id}", json={"run_order": 7})
    got = _order(client, bid, admin_id)["order"]
    assert [x["id"] for x in got] == [c["id"], a["id"], b["id"]], got
    assert [x["position"] for x in got] == [1, 2, 3]


def test_two_rules_on_one_number_are_shown_as_sharing_it(client, admin_id):
    """That is the thing somebody arranging them needs to see: the order
    between those two is their ids, which nobody chose."""
    bid = _board(client, admin_id, "לוח מספר כפול")
    a = _add(client, bid, admin_id, name="א")
    b = _add(client, bid, admin_id, name="ב")
    for x in (a, b):
        client.patch(f"/api/automations/{x['id']}?user_id={admin_id}", json={"run_order": 3})
    got = _order(client, bid, admin_id)["order"]
    assert all(x["shares_number"] for x in got if x["run_order"] == 3)


def test_the_whole_list_can_be_arranged_at_once(client, admin_id):
    bid = _board(client, admin_id, "לוח סידור")
    a = _add(client, bid, admin_id, name="א")
    b = _add(client, bid, admin_id, name="ב")
    c = _add(client, bid, admin_id, name="ג")
    r = client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                    json={"ids": [c["id"], a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["order"] == [c["id"], a["id"], b["id"]]
    got = _order(client, bid, admin_id)["order"]
    assert [x["id"] for x in got] == [c["id"], a["id"], b["id"]]
    # spread across the range rather than packed at the front: somebody putting
    # a rule between two of these later needs a number to put it on
    nums = [x["run_order"] for x in got]
    assert nums == sorted(nums) and len(set(nums)) == 3, nums
    assert nums[0] >= cityos_main.RUN_ORDER_MIN and nums[-1] <= cityos_main.RUN_ORDER_MAX
    assert not any(x["shares_number"] for x in got)


def test_rules_left_out_keep_their_place_behind_the_ones_named(client, admin_id):
    """An admin arranging the three that matter is not asking to shuffle the
    other twenty."""
    bid = _board(client, admin_id, "לוח סידור חלקי")
    ids = [_add(client, bid, admin_id, name=f"כלל {i}")["id"] for i in range(4)]
    client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                json={"ids": [ids[3], ids[2]]})
    got = [x["id"] for x in _order(client, bid, admin_id)["order"]]
    assert got == [ids[3], ids[2], ids[0], ids[1]], got


def test_arranging_is_a_version_like_any_other_change(client, admin_id):
    bid = _board(client, admin_id, "לוח סידור גרסה")
    a = _add(client, bid, admin_id, name="א")
    b = _add(client, bid, admin_id, name="ב")
    client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                json={"ids": [b["id"], a["id"]]})
    # only the rules that actually moved get a version — a renumber that put a
    # rule back where it already was is not a change to record
    v = client.get(f"/api/automations/{a['id']}/versions?user_id={admin_id}"
                   ).json()["versions"]
    assert any("סדר הביצוע" in (x["summary"] or "") for x in v), v


def test_arranging_nothing_is_refused_and_a_stranger_cannot(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח סידור הרשאות")
    _member(client, admin_id, bid, guinea_id, "editor")
    a = _add(client, bid, admin_id)
    assert client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                       json={"ids": []}).status_code == 400
    assert client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                       json={"ids": [10 ** 7]}).status_code == 400
    assert client.post(f"/api/boards/{bid}/automations/order?user_id={guinea_id}",
                       json={"ids": [a["id"]]}).status_code == 403
    assert client.get(f"/api/boards/{10 ** 7}/automations/order?user_id={admin_id}"
                      ).status_code == 404


def test_importance_does_not_decide_who_goes_first_and_says_so(client, admin_id):
    """It is for reading and filtering. A rule marked קריטית does not overtake
    one marked נמוכה, and the answer says that rather than leaving it to be
    assumed."""
    bid = _board(client, admin_id, "לוח חשיבות")
    low = _add(client, bid, admin_id, name="נמוכה", importance="low")
    crit = _add(client, bid, admin_id, name="קריטית", importance="critical")
    d = _order(client, bid, admin_id)
    assert [x["id"] for x in d["order"]] == [low["id"], crit["id"]]
    assert d["importance_affects_order"] is False


def test_the_order_can_be_read_for_one_trigger(client, admin_id):
    bid = _board(client, admin_id, "לוח לפי טריגר")
    made = _add(client, bid, admin_id, name="על יצירה")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "low"}, name="על סטטוס")
    got = _order(client, bid, admin_id, trigger="item_created")["order"]
    assert [x["id"] for x in got] == [made["id"]]


def test_the_order_is_the_order_the_engine_actually_uses(client, admin_id):
    """The list and the firing must not be two different answers."""
    bid = _board(client, admin_id, "לוח סדר אמיתי")
    first = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
                 name="מסמן בוצע")
    second = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
                  name="מסמן בטיפול")
    client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                json={"ids": [second["id"], first["id"]]})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        # the one that runs LAST decides
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) == "done"


# ── התנגשויות: the log says who wrote over whom ────────────────────────────

def test_the_log_says_when_one_rule_wrote_over_another(client, admin_id):
    bid = _board(client, admin_id, "לוח התנגשות")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, name="ראשון")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
         name="שני")
    _item(client, bid, admin_id)
    runs = _runs(client, bid, admin_id)
    clash = [r for r in runs if "נכתב באירוע הזה גם" in (r["reason"] or "")]
    assert clash, [r["reason"] for r in runs]
    assert "ראשון" in clash[0]["reason"], clash[0]["reason"]
    assert "הכתיבה האחרונה קובעת" in clash[0]["reason"]


def test_two_rules_writing_different_fields_are_not_a_conflict(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי התנגשות")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    assert not any("נכתב באירוע הזה גם" in (r["reason"] or "")
                   for r in _runs(client, bid, admin_id))


def test_the_same_rule_firing_on_two_changes_is_not_a_conflict(client, admin_id):
    """A ledger per EVENT, because that is its lifetime: rules firing on two
    different changes are not in conflict, they are two changes."""
    bid = _board(client, admin_id, "לוח שני אירועים")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id, "א")
    _item(client, bid, admin_id, "ב")
    assert not any("נכתב באירוע הזה גם" in (r["reason"] or "")
                   for r in _runs(client, bid, admin_id))


def test_the_ledger_does_not_end_up_in_the_stored_event(client, admin_id):
    bid = _board(client, admin_id, "לוח יומן נקי")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"})
    _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        from models import AutomationRun
        for r in db.query(AutomationRun).filter(AutomationRun.board_id == bid).all():
            assert not any(k.startswith("_") for k in (r.event or {})), r.event


def test_a_retry_of_a_conflicted_run_still_works(client, admin_id):
    """The ledger is working state and must not survive into a replay."""
    bid = _board(client, admin_id, "לוח התנגשות וריטריי")
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"})
    _item(client, bid, admin_id)
    skipped = next((r for r in _runs(client, bid, admin_id) if r["can_retry"]), None)
    if skipped:
        assert client.post(f"/api/automation-runs/{skipped['id']}/retry?user_id={admin_id}"
                           ).status_code == 200


# ── השהיה: a board that is stopped knows it ────────────────────────────────

def test_a_frozen_board_says_so_on_its_own_screen(client, admin_id):
    bid = _board(client, admin_id, "לוח מושהה")
    _add(client, bid, admin_id)
    d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
    assert d["freeze"] is None
    f = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid,
                          "reason": "חקירה של תקלה"}).json()
    try:
        d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
        assert d["freeze"] is not None
        assert d["freeze"]["reason"] == "חקירה של תקלה"
        assert d["freeze"]["scope"] == "board"
        assert d["freeze"]["created_by_name"]
    finally:
        client.post(f"/api/admin/automations/release?user_id={admin_id}",
                    json={"freeze_id": f["freeze"]["id"]})
    assert client.get(f"/api/boards/{bid}/automations?user_id={admin_id}"
                      ).json()["freeze"] is None


def test_an_organisation_wide_stop_shows_on_every_board(client, admin_id):
    bid = _board(client, admin_id, "לוח תחת השהיה ארגונית")
    _add(client, bid, admin_id)
    f = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "org", "reason": "שדרוג מערכת כולל",
                          "confirm": True}).json()
    try:
        d = client.get(f"/api/boards/{bid}/automations?user_id={admin_id}").json()
        assert d["freeze"] and d["freeze"]["scope"] == "org"
        # and nothing fires while it holds
        _item(client, bid, admin_id)
        assert _runs(client, bid, admin_id) == []
    finally:
        client.post(f"/api/admin/automations/release?user_id={admin_id}",
                    json={"freeze_id": f["freeze"]["id"]})


def test_the_screen_carries_the_three(client):
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    assert "freezeHTML()" in src and "האוטומציות בלוח מושהות" in src
    assert "כללים אינם נורים ואינם נרשמים" in src


# ── 9.1, requirement by requirement ────────────────────────────────────────

def test_a_rule_may_carry_up_to_ten_actions_in_the_order_shown(client, admin_id):
    import automations as recipes
    assert recipes.MAX_ACTIONS == 10
    bid = _board(client, admin_id, "לוח עשר פעולות")
    extras = [{"key": "create_subitem", "values": {"text": f"תת {i}"}}
              for i in range(9)]                       # + the recipe's own = ten
    a = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high", "actions": extras})
    assert len(a["actions"]) == 9
    _item(client, bid, admin_id, "אב")
    with Session(cityos_main.engine) as db:
        subs = [t.title for t in db.query(Task).filter(Task.board_id == bid,
                                                       Task.parent_id != None).all()]
    assert subs == [f"תת {i}" for i in range(9)], "the actions did not run in order"


def test_an_eleventh_is_refused(client, admin_id):
    bid = _board(client, admin_id, "לוח אחת עשרה")
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "high",
                                     "actions": [{"key": "create_subitem",
                                                  "values": {"text": f"תת {i}"}}
                                                 for i in range(10)]}})
    assert r.status_code == 400 and "10" in r.json()["detail"]


def test_a_failure_stops_the_actions_after_it_and_says_where(client, admin_id,
                                                              monkeypatch):
    """"כשל עוצר את הפעולות הבאות" — and "the rule failed" over ten actions is
    not an answer anybody can act on."""
    bid = _board(client, admin_id, "לוח כשל")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "create_subitem", "values": {"text": "ראשון"}},
                      {"key": "create_subitem", "values": {"text": "מתפוצץ"}},
                      {"key": "create_subitem", "values": {"text": "אחרון"}}]})
    real = cityos_main._run_one_action

    def boom(db, act, cfg, task, *a, **k):
        if (cfg or {}).get("text") == "מתפוצץ":
            raise RuntimeError("נפל")
        return real(db, act, cfg, task, *a, **k)
    monkeypatch.setattr(cityos_main, "_run_one_action", boom)
    _item(client, bid, admin_id, "אב")
    monkeypatch.undo()

    runs = _runs(client, bid, admin_id)
    assert runs and runs[0]["outcome"] == "failed", runs[:1]
    assert "פעולה 3 מתוך 4" in runs[0]["reason"], runs[0]["reason"]
    assert "הפעולות הבאות לא בוצעו" in runs[0]["reason"]


def test_nothing_the_rule_had_already_done_survives_its_failure(client, admin_id,
                                                                 monkeypatch):
    """The one case the specification allows a completed action to be rolled
    back: the same database transaction. Here they always are — the rule runs
    inside one savepoint — so a rule never half-happens."""
    bid = _board(client, admin_id, "לוח כשל חלקי")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "critical",
          "actions": [{"key": "create_subitem", "values": {"text": "נוצר לפני הכשל"}},
                      {"key": "create_subitem", "values": {"text": "מתפוצץ"}}]})
    real = cityos_main._run_one_action

    def boom(db, act, cfg, task, *a, **k):
        if (cfg or {}).get("text") == "מתפוצץ":
            raise RuntimeError("נפל")
        return real(db, act, cfg, task, *a, **k)
    monkeypatch.setattr(cityos_main, "_run_one_action", boom)
    tid = _item(client, bid, admin_id, "אב")
    monkeypatch.undo()
    with Session(cityos_main.engine) as db:
        assert db.query(Task).filter(Task.board_id == bid,
                                     Task.title == "נוצר לפני הכשל").count() == 0
        # and the item itself is untouched by the action that did run
        assert cityos_main._task_priority_key(
            db.query(Task).filter(Task.id == tid).first()) != "critical"


def test_the_order_is_one_to_nine_hundred_and_ninety_nine(client, admin_id):
    bid = _board(client, admin_id, "לוח טווח סדר")
    a = _add(client, bid, admin_id)
    assert cityos_main.RUN_ORDER_MIN == 1 and cityos_main.RUN_ORDER_MAX == 999
    assert a["run_order"] == cityos_main.RUN_ORDER_DEFAULT == 500
    for asked, got in ((0, 1), (-5, 1), (1000, 999), (250, 250)):
        r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                         json={"run_order": asked})
        assert r.json()["run_order"] == got, (asked, r.json()["run_order"])


def test_a_lower_number_goes_first(client, admin_id):
    bid = _board(client, admin_id, "לוח נמוך קודם")
    late = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
                name="מאוחר")
    early = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
                 name="מוקדם")
    client.patch(f"/api/automations/{early['id']}?user_id={admin_id}",
                 json={"run_order": 10})
    client.patch(f"/api/automations/{late['id']}?user_id={admin_id}",
                 json={"run_order": 900})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        # the one with the HIGHER number runs last, so its value is the one left
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) == "done"
    assert [x["id"] for x in _order(client, bid, admin_id)["order"]] \
        == [early["id"], late["id"]]


def test_a_tie_is_broken_by_when_the_version_came_into_service(client, admin_id):
    """"בשוויון, הקדימות נקבעת לפי מועד הפעלת הגרסה ולאחר מכן לפי מזהה" — two
    rules nobody placed are not in an arbitrary order."""
    from datetime import datetime, timedelta, timezone as tz
    bid = _board(client, admin_id, "לוח שוויון")
    first = _add(client, bid, admin_id, name="א")
    second = _add(client, bid, admin_id, name="ב")
    assert first["run_order"] == second["run_order"]
    # the one with the HIGHER id came into service first
    with Session(cityos_main.engine) as db:
        db.query(Automation).filter(Automation.id == second["id"]).update(
            {Automation.activated_at:
             datetime.now(tz.utc).replace(tzinfo=None) - timedelta(days=5)})
        db.commit()
    assert [x["id"] for x in _order(client, bid, admin_id)["order"]] \
        == [second["id"], first["id"]]


def test_and_then_by_the_id(client, admin_id):
    bid = _board(client, admin_id, "לוח שוויון מלא")
    a = _add(client, bid, admin_id, name="א")
    b = _add(client, bid, admin_id, name="ב")
    with Session(cityos_main.engine) as db:
        when = db.query(Automation).filter(Automation.id == a["id"]).first().activated_at
        db.query(Automation).filter(Automation.id == b["id"]).update(
            {Automation.activated_at: when})
        db.commit()
    assert [x["id"] for x in _order(client, bid, admin_id)["order"]] == [a["id"], b["id"]]


def test_the_later_rule_decides_the_value_of_a_shared_field(client, admin_id):
    """"אם שתי אוטומציות כותבות לאותו שדה, המאוחרת בסדר קובעת את הערך הסופי"."""
    bid = _board(client, admin_id, "לוח ערך סופי")
    one = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
               name="ראשון")
    two = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
               name="שני")
    client.post(f"/api/boards/{bid}/automations/order?user_id={admin_id}",
                json={"ids": [two["id"], one["id"]]})
    tid = _item(client, bid, admin_id)
    with Session(cityos_main.engine) as db:
        assert cityos_main._st_of(db.query(Task).filter(Task.id == tid).first()) == "done"


def test_actions_on_one_item_run_one_after_another(client, admin_id):
    """Serially, and in one order — the same event twice gives the same answer."""
    bid = _board(client, admin_id, "לוח סדרתי")
    _add(client, bid, admin_id, "created_set_priority",
         {"a_priority": "high",
          "actions": [{"key": "create_subitem", "values": {"text": "א"}},
                      {"key": "create_subitem", "values": {"text": "ב"}},
                      {"key": "create_subitem", "values": {"text": "ג"}}]})
    for n in range(2):
        parent = _item(client, bid, admin_id, f"אב {n}")
        with Session(cityos_main.engine) as db:
            subs = [t.title for t in db.query(Task).filter(Task.parent_id == parent)
                    .order_by(Task.id).all()]
        assert subs == ["א", "ב", "ג"], subs


def test_switching_a_rule_on_warns_about_a_field_somebody_else_writes(client, admin_id):
    """"לפני הפעלה תוצג אזהרה על כתיבה אפשרית לאותו שדה" — shown, not refused."""
    bid = _board(client, admin_id, "לוח אזהרת שדה")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"}, name="הוותיק")
    new = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
               name="החדש", status="paused")
    r = client.patch(f"/api/automations/{new['id']}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.status_code == 200, r.text
    warn = r.json()["warnings"]
    assert warn and warn[0]["name"] == "הוותיק", warn
    assert "סטטוס" in warn[0]["text"]
    assert warn[0]["runs_after_this"] in (True, False)
    assert "יקבע" in warn[0]["text"], warn[0]["text"]


def test_the_warning_says_which_of_the_two_decides(client, admin_id):
    bid = _board(client, admin_id, "לוח מי קובע")
    old = _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
               name="רץ אחרי")
    client.patch(f"/api/automations/{old['id']}?user_id={admin_id}",
                 json={"run_order": 900})
    new = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
               name="רץ לפני", status="paused")
    client.patch(f"/api/automations/{new['id']}?user_id={admin_id}",
                 json={"run_order": 10})
    r = client.patch(f"/api/automations/{new['id']}?user_id={admin_id}",
                     json={"status": "active"})
    w = r.json()["warnings"][0]
    assert w["runs_after_this"] is True and "וערכה יקבע" in w["text"], w


def test_a_rule_writing_a_field_nobody_else_writes_is_not_warned_about(client, admin_id):
    bid = _board(client, admin_id, "לוח בלי אזהרה")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"})
    other = _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"},
                 status="paused")
    r = client.patch(f"/api/automations/{other['id']}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.json()["warnings"] == []


def test_a_paused_rule_is_not_warned_about(client, admin_id):
    """The warning is about what is RUNNING — a rule nobody switched on writes
    nothing and is not in anybody's way."""
    bid = _board(client, admin_id, "לוח כלל כבוי")
    _add(client, bid, admin_id, "created_set_status", {"a_status": "done"},
         name="כבוי", status="paused")
    new = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
               name="חדש", status="paused")
    r = client.patch(f"/api/automations/{new['id']}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.json()["warnings"] == []
