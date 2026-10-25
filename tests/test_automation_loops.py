"""Group — מניעת לולאות והפעלה כפולה: a cascade that cannot eat itself.

An automation's action can be another automation's trigger. That is the whole
point of the feature and it is also the whole danger of it: two rules pointing
at each other will go round forever, and "forever" on a board means every item
rewritten a hundred times before anybody notices.

Four separate guards, because they catch different things:

  מזהה שרשרת    · one change and everything it set off share an id, so "what did
                  this edit actually do" is one question with one answer
  אותו אירוע    · never fires the same rule twice — a replay is not a second
                  reason to act
  אותו פריט     · a rule runs at most once per item per chain, which is what
                  stops the ordinary two-rule ping-pong dead
  תקרת שרשרת    · ten firings and five minutes, after which the chain is cut and
                  the cut is written down as a suspected loop

And one that is not a guard at all: the save-time cycle check, which is a
warning. It cannot prove two rules will feed each other, so it does not refuse —
and it does not have to, because the runtime guard binds whatever was saved.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import main as cityos_main
from models import Automation, AutomationQueue, AutomationRun, Task


def _board(client, admin_id, name="לוח לולאות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id, config, **extra):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט"):
    r = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                        "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, bid, admin_id, **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    r = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}{qs}")
    assert r.status_code == 200, r.text
    return r.json()["runs"]


def _ping_pong(client, bid, admin_id, member_id):
    """Two rules that feed each other through the person column.

    «הוקצה אדם ⇐ קבע סטטוס» and «סטטוס נקבע ⇐ הקצה אדם» is the shape every
    real runaway has had: neither rule is wrong, and together they never stop.
    """
    a1 = _add(client, bid, admin_id, "status_assign_person",
              {"t_status": "done", "a_person": admin_id})
    a2 = _add(client, bid, admin_id, "assigned_set_status", {"a_status": "in_progress"})
    a3 = _add(client, bid, admin_id, "status_assign_person",
              {"t_status": "in_progress", "a_person": member_id})
    return a1, a2, a3


# ── מזהה שרשרת ─────────────────────────────────────────────────────────────

def test_every_run_carries_a_chain_id(client, admin_id):
    bid = _board(client, admin_id)
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    runs = _runs(client, bid, admin_id)
    assert runs, "nothing ran"
    assert all(r.get("chain_id") for r in runs), \
        "a run with no chain id cannot be tied to the change that caused it"


def test_one_change_is_one_chain_of_many_events(client, admin_id):
    """The cascade shares the chain. The events inside it are still separate
    events — the two ids answer two different questions."""
    bid = _board(client, admin_id, "לוח שרשרת אחת")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    _add(client, bid, admin_id, "priority_assign_person",
         {"t_priority": "critical", "a_person": admin_id})
    tid = _item(client, bid, admin_id)["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    runs = [r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"]
    assert len(runs) >= 2, runs
    assert len({r["chain_id"] for r in runs}) == 1, "the cascade split into two chains"
    assert len({r["event_id"] for r in runs}) == len(runs), \
        "two different firings were given the same event id"


def test_two_changes_are_two_chains(client, admin_id):
    bid = _board(client, admin_id, "לוח שתי שרשראות")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id, "ראשון")
    _item(client, bid, admin_id, "שני")
    chains = {r["chain_id"] for r in _runs(client, bid, admin_id)}
    assert len(chains) == 2, f"two separate changes shared a chain: {chains}"


def test_a_bulk_action_is_one_batch_and_many_chains(client, admin_id):
    """The two ids are not the same id. "Was this one of a hundred" and "what
    did this one item's change set off" are different questions, and a log that
    answered both with one field could answer neither."""
    bid = _board(client, admin_id, "לוח קבוצתי")
    board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    gid = board["groups"][-1]["id"]
    _add(client, bid, admin_id, "moved_group_set_status",
         {"t_group": gid, "a_status": "done"})
    ids = [_item(client, bid, admin_id, f"פריט {i}")["id"] for i in range(3)]
    r = client.post(f"/api/boards/{bid}/items/move",
                    json={"actor_id": admin_id, "group_id": gid, "ids": ids})
    assert r.status_code == 200, r.text
    runs = [x for x in _runs(client, bid, admin_id) if x["outcome"] == "ran"
            and x["trigger"] == "moved_to_group"]
    assert len(runs) == 3, runs
    assert len({x["batch_id"] for x in runs}) == 1, "one action was logged as three"
    assert len({x["chain_id"] for x in runs}) == 3, "three items shared one chain"


def test_the_chain_id_is_filterable(client, admin_id):
    bid = _board(client, admin_id, "לוח סינון")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id, "ראשון")
    _item(client, bid, admin_id, "שני")
    cid = _runs(client, bid, admin_id)[0]["chain_id"]
    got = _runs(client, bid, admin_id, chain_id=cid)
    assert got and all(r["chain_id"] == cid for r in got)
    assert len(got) < len(_runs(client, bid, admin_id))


# ── אותו אירוע לא יפעיל פעמיים ─────────────────────────────────────────────

def test_the_same_event_does_not_fire_the_same_rule_twice(client, admin_id):
    """A replayed event is not a second reason to act. Fed through twice, the
    rule acts once and the second pass is written down as a non-event."""
    bid = _board(client, admin_id, "לוח אירוע כפול")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)["id"]
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        ev = cityos_main._event("status_changes_to", "item", status="done")
        cityos_main._run_automations(db, t, ev, admin_id)
        cityos_main._run_automations(db, t, ev, admin_id)
        db.commit()
    runs = _runs(client, bid, admin_id)
    ran = [r for r in runs if r["outcome"] == "ran"]
    assert len(ran) == 1, f"the same event fired the rule {len(ran)} times"
    dup = [r for r in runs if r["outcome"] == "skipped" and "כבר" in (r["reason"] or "")]
    assert dup, "the suppressed second firing left no trace in the log"


# ── אותה אוטומציה לא תפעל שוב על אותו פריט באותה שרשרת ────────────────────

def test_a_rule_runs_once_per_item_per_chain(client, admin_id):
    """Two different events, one chain, one item. The rule answers the first
    and is refused the second — which is the guard that stops the ordinary
    two-rule runaway, since every step of one is a new event in the same chain.

    A rule that notifies, deliberately: one that writes a value would be stopped
    the second time by no-op prevention anyway, and then the test would be
    proving the wrong thing.
    """
    bid = _board(client, admin_id, "לוח שרשרת אחת לפריט")
    a = _add(client, bid, admin_id, "status_notify_person",
             {"t_status": "done", "a_person": {"kind": "actor"}})
    tid = _item(client, bid, admin_id)["id"]
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        one = cityos_main._event("status_changes_to", "item", status="done")
        two = dict(one, id="second-event-same-chain")
        cityos_main._run_automations(db, t, one, admin_id)
        cityos_main._run_automations(db, t, two, admin_id)
        db.commit()
    mine = [r for r in _runs(client, bid, admin_id) if r["automation_id"] == a["id"]]
    ran = [r for r in mine if r["outcome"] == "ran"]
    assert len(ran) == 1, f"the rule ran {len(ran)} times on one item in one chain"
    stopped = [r for r in mine if r["outcome"] == "skipped"
               and "בשרשרת" in (r["reason"] or "")]
    assert stopped, f"the second firing was not refused with a reason: {mine}"


def test_the_real_two_rule_runaway_stops(client, admin_id, member_id):
    """End to end, through the API, with the shape every real one has had:
    «סטטוס ⇐ הקצה אדם» and «הוקצה אדם ⇐ קבע סטטוס» feeding each other."""
    bid = _board(client, admin_id, "לוח פינג-פונג")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _a1, a2, _a3 = _ping_pong(client, bid, admin_id, member_id)
    tid = _item(client, bid, admin_id)["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    mine = [r for r in _runs(client, bid, admin_id) if r["automation_id"] == a2["id"]]
    ran = [r for r in mine if r["outcome"] == "ran"]
    assert len(ran) == 1, f"«הוקצה אדם» ran {len(ran)} times in one chain: {mine}"
    assert [r for r in mine if "בשרשרת" in (r["reason"] or "")], mine


def test_the_same_rule_still_reaches_a_different_item(client, admin_id, member_id):
    """The guard is per item. A rule that fans out over five items is doing its
    job, not looping, and a guard that counted only the rule would stop it."""
    bid = _board(client, admin_id, "לוח פריטים")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    a, b = _item(client, bid, admin_id, "א")["id"], _item(client, bid, admin_id, "ב")["id"]
    with Session(cityos_main.engine) as db:
        ev = cityos_main._event("status_changes_to", "item", status="done")
        for tid in (a, b):
            t = db.query(Task).filter(Task.id == tid).first()
            cityos_main._run_automations(db, t, dict(ev, id=f"e{tid}"), admin_id)
        db.commit()
    ran = [r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"]
    assert len(ran) == 2, f"the second item was refused as a repeat: {ran}"


def test_a_fresh_change_is_a_fresh_chain(client, admin_id):
    """Yesterday's chain does not hold against today's edit. A rule refused once
    as a repeat has to be free to run when the item changes again."""
    bid = _board(client, admin_id, "לוח שרשרת חדשה")
    a = _add(client, bid, admin_id, "status_notify_person",
             {"t_status": "done", "a_person": {"kind": "actor"}})
    tid = _item(client, bid, admin_id)["id"]
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        for _ in range(2):
            cityos_main._run_automations(
                db, t, cityos_main._event("status_changes_to", "item", status="done"),
                admin_id)
        db.commit()
    ran = [r for r in _runs(client, bid, admin_id)
           if r["automation_id"] == a["id"] and r["outcome"] == "ran"]
    assert len(ran) == 2, f"the second change was swallowed by the first chain: {ran}"


# ── תקרת שרשרת: עשר הפעלות וחמש דקות ──────────────────────────────────────

def _fire_with(db, tid, admin_id, **chain):
    t = db.query(Task).filter(Task.id == tid).first()
    ev = cityos_main._event("status_changes_to", "item", status="done", **chain)
    cityos_main._run_automations(db, t, ev, admin_id)
    db.commit()


def test_ten_firings_stop_the_chain(client, admin_id):
    bid = _board(client, admin_id, "לוח תקרה")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)["id"]
    with Session(cityos_main.engine) as db:
        _fire_with(db, tid, admin_id, chain_runs=cityos_main.AUTOMATION_CHAIN_MAX_RUNS)
    runs = _runs(client, bid, admin_id)
    assert not [r for r in runs if r["outcome"] == "ran"], \
        "a chain that had spent its ten firings ran an eleventh"
    assert [r for r in runs if "לולאה" in (r["reason"] or "")], \
        f"the cut was not written down as a suspected loop: {runs}"


def test_five_minutes_stop_the_chain(client, admin_id):
    """The second ceiling, and it is not the same as the first: a chain can be
    cheap in firings and still be going round."""
    bid = _board(client, admin_id, "לוח שעון")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)["id"]
    old = (datetime.now(timezone.utc)
           - timedelta(seconds=cityos_main.AUTOMATION_CHAIN_MAX_SECONDS + 5))
    with Session(cityos_main.engine) as db:
        _fire_with(db, tid, admin_id, chain_started=old.isoformat())
    runs = _runs(client, bid, admin_id)
    assert not [r for r in runs if r["outcome"] == "ran"], \
        "a chain older than five minutes was still running"
    assert [r for r in runs if "לולאה" in (r["reason"] or "")], runs


def test_the_limits_are_the_ones_the_spec_names(client, admin_id):
    assert cityos_main.AUTOMATION_CHAIN_MAX_RUNS == 10
    assert cityos_main.AUTOMATION_CHAIN_MAX_SECONDS == 300


def test_a_rule_cut_again_and_again_is_taken_out_of_service(client, admin_id):
    """«מושהית עקב שגיאה» names a loop as one of its four causes. A rule that
    keeps being cut off is in one, and leaving it active means the board reads
    as automated while this never completes."""
    bid = _board(client, admin_id, "לוח השהיה")
    a = _add(client, bid, admin_id, "status_set_priority",
             {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)["id"]
    for _ in range(cityos_main.AUTOMATION_FAIL_CUTOFF):
        with Session(cityos_main.engine) as db:
            _fire_with(db, tid, admin_id,
                       chain_runs=cityos_main.AUTOMATION_CHAIN_MAX_RUNS)
    with Session(cityos_main.engine) as db:
        row = db.query(Automation).filter(Automation.id == a["id"]).first()
        assert row.status == "paused_error", row.status
        assert row.is_active is False


def test_a_cut_chain_is_cut_once_and_not_logged_forever(client, admin_id):
    """A chain already stopped does not go on writing a row for every rule it
    meets on the way down. One record of the cut is the record."""
    bid = _board(client, admin_id, "לוח רישום")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)["id"]
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        ev = cityos_main._event("status_changes_to", "item", status="done",
                                chain_runs=cityos_main.AUTOMATION_CHAIN_MAX_RUNS)
        cityos_main._run_automations(db, t, ev, admin_id)
        cityos_main._run_automations(db, t, dict(ev, id="e2"), admin_id)
        db.commit()
    cut = [r for r in _runs(client, bid, admin_id) if "לולאה" in (r["reason"] or "")]
    assert len(cut) == 1, f"the same cut was written down {len(cut)} times"


# ── זיהוי בשמירה ───────────────────────────────────────────────────────────

def test_a_circular_dependency_is_warned_about_on_activation(client, admin_id, member_id):
    """Warned about, not refused: the engine cannot tell from two rules' shapes
    that they will really feed each other, and the runtime guard binds anyway."""
    bid = _board(client, admin_id, "לוח מעגל")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    a1 = _add(client, bid, admin_id, "status_assign_person",
              {"t_status": "done", "a_person": admin_id}, status="draft")
    a2 = _add(client, bid, admin_id, "assigned_set_status", {"a_status": "done"})
    r = client.patch(f"/api/automations/{a1['id']}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.status_code == 200, r.text
    warn = r.json().get("warnings") or []
    assert any(w.get("cycle") for w in warn), f"no circular-dependency warning: {warn}"
    assert any("מעגלית" in (w.get("text") or "") for w in warn), warn
    with Session(cityos_main.engine) as db:
        assert db.query(Automation).filter(
            Automation.id == a1["id"]).first().status == "active", \
            "the warning refused the activation instead of warning about it"
    assert a2["id"]


def test_a_cycle_through_a_third_rule_is_found_too(client, admin_id):
    """A → B → C → A. A check that only looked at pairs saw nothing wrong with
    any of the three."""
    bid = _board(client, admin_id, "לוח מעגל ארוך")
    a1 = _add(client, bid, admin_id, "status_set_priority",
              {"t_status": "done", "a_priority": "critical"}, status="draft")
    _add(client, bid, admin_id, "priority_assign_person",
         {"t_priority": "critical", "a_person": admin_id})
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "done"})
    r = client.patch(f"/api/automations/{a1['id']}?user_id={admin_id}",
                     json={"status": "active"})
    assert r.status_code == 200, r.text
    assert any(w.get("cycle") for w in (r.json().get("warnings") or [])), \
        f"a three-rule cycle was not seen: {r.json().get('warnings')}"


def test_the_impact_screen_names_the_cycle(client, admin_id):
    bid = _board(client, admin_id, "לוח השפעה")
    a1 = _add(client, bid, admin_id, "status_set_priority",
              {"t_status": "done", "a_priority": "critical"}, status="draft")
    _add(client, bid, admin_id, "priority_assign_person",
         {"t_priority": "critical", "a_person": admin_id})
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "done"})
    d = client.get(f"/api/automations/{a1['id']}/impact?user_id={admin_id}").json()
    assert any(x.get("cycle") for x in (d.get("loop_risk") or [])), d.get("loop_risk")


def test_runtime_beats_the_configuration(client, admin_id, member_id):
    """«זיהוי בזמן ריצה גובר על כל הגדרה». Somebody read the save-time warning,
    decided they knew better and switched it on anyway. The chain still stops,
    and it stops well inside the ceiling rather than at it."""
    bid = _board(client, admin_id, "לוח למרות הכל")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    _ping_pong(client, bid, admin_id, member_id)
    tid = _item(client, bid, admin_id)["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        ran = db.query(AutomationRun).filter(AutomationRun.task_id == tid,
                                             AutomationRun.outcome == "ran").all()
        assert len(ran) <= cityos_main.AUTOMATION_CHAIN_MAX_RUNS, \
            f"the chain ran away: {len(ran)} firings"


# ── נתונים חסרים, הרשאות, המתנה ───────────────────────────────────────────

def test_an_event_with_no_chain_is_given_one(client, admin_id):
    """Every call site that hands the engine a bare dictionary still gets a
    chain — the guard cannot depend on each of them remembering."""
    bid = _board(client, admin_id, "לוח בלי שרשרת")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical"})
    tid = _item(client, bid, admin_id)["id"]
    with Session(cityos_main.engine) as db:
        t = db.query(Task).filter(Task.id == tid).first()
        cityos_main._run_automations(
            db, t, {"type": "status_changes_to", "status": "done"}, admin_id)
        db.commit()
    runs = [r for r in _runs(client, bid, admin_id) if r["outcome"] == "ran"]
    assert runs and all(r["chain_id"] for r in runs), runs


def test_the_chain_is_not_shown_to_somebody_who_may_not_read_the_log(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח סגור")
    _add(client, bid, admin_id, "created_set_priority", {"a_priority": "high"})
    _item(client, bid, admin_id)
    r = client.get(f"/api/boards/{bid}/automations/runs?user_id={member_id}")
    assert r.status_code == 403, r.text


def test_the_limits_are_published_to_the_screen(client, admin_id):
    d = client.get(f"/api/automation-capabilities?user_id={admin_id}").json()
    assert d["chain"]["max_runs"] == cityos_main.AUTOMATION_CHAIN_MAX_RUNS
    assert d["chain"]["max_seconds"] == cityos_main.AUTOMATION_CHAIN_MAX_SECONDS


def test_a_wait_carries_its_chain_across(client, admin_id):
    """A delayed action is the one piece of a chain that outlives the request.
    What it carries is the chain it belongs to and how much of the allowance
    that chain had already spent — or a wait would be a way of resetting the
    guard, which is exactly what a loop would use it for."""
    bid = _board(client, admin_id, "לוח המתנה")
    _add(client, bid, admin_id, "status_set_priority",
         {"t_status": "done", "a_priority": "critical",
          "actions": [{"key": "wait", "values": {"days": 60}},
                      {"key": "set_status", "values": {"status": "in_progress"}}]})
    tid = _item(client, bid, admin_id)["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    with Session(cityos_main.engine) as db:
        row = (db.query(AutomationQueue)
                 .filter(AutomationQueue.task_id == tid).first())
        assert row is not None, "the wait was never stored"
        assert (row.event or {}).get("chain"), "the stored wait lost its chain"
        assert (row.event or {}).get("chain_runs") is not None, \
            "the stored wait forgot how much of the allowance was spent"
