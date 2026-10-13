"""Two conditions, not one — "אם X וגם Y, אז…".

A rule was one trigger and one action, so the moment the trigger fired the
action ran: "when the status changes to done, notify Dana" fires on every item
that reaches done, whatever else is true of it. The case this covers is the
one a board actually has: when the status changes to done **and only if the
priority is urgent**, notify Dana.

A condition is the other half of the if. It is read off the item at the moment
the trigger fires, it is ANDed with every other condition on the rule, and a
rule held back by one records a skip that names it — because "why did nothing
happen" is the question the run history exists to answer.
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Task, Notification


def _mk_board(client, admin_id, name="לוח תנאים", invite=None):
    bid = client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]
    if invite is not None:
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": invite, "role": "editor"})
    return bid


def _mk_item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id, config):
    return client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                       json={"recipe_id": recipe_id, "config": config})


def _notes_for(task_id, uid):
    with Session(cityos_main.engine) as db:
        return [n for n in db.query(Notification)
                .filter(Notification.task_id == task_id).all() if n.user_id == uid]


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


def test_the_condition_catalog_is_served(client, admin_id):
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    kinds = {c["kind"] for c in d["conditions"]}
    assert {"status_is", "priority_is", "person_is", "group_is", "overdue"} <= kinds
    assert d["max_conditions"] >= 2
    one = next(c for c in d["conditions"] if c["kind"] == "priority_is")
    assert "…" in one["label"] and one["type"] == "priority"      # a blank to fill
    free = next(c for c in d["conditions"] if c["kind"] == "overdue")
    assert free["type"] is None and "…" not in free["label"]      # nothing to fill


def test_the_action_runs_only_when_the_second_condition_holds(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": guinea_id,
          "conditions": [{"kind": "priority_is", "value": "critical"}]})

    # the trigger fires, the condition does not hold → nothing happens
    low = _mk_item(client, bid, admin_id, "לא דחוף")
    client.patch(f"/api/tasks/{low}?user_id={admin_id}", json={"priority": "low"})
    client.patch(f"/api/tasks/{low}?user_id={admin_id}", json={"status": "done"})
    assert not _notes_for(low, guinea_id)

    # the same trigger on an item the condition does hold for → it runs
    hot = _mk_item(client, bid, admin_id, "דחוף")
    client.patch(f"/api/tasks/{hot}?user_id={admin_id}", json={"priority": "critical"})
    client.patch(f"/api/tasks/{hot}?user_id={admin_id}", json={"status": "done"})
    assert len(_notes_for(hot, guinea_id)) == 1


def test_a_held_back_rule_says_which_condition_held_it(client, admin_id, guinea_id):
    """A skip with no reason is the thing the history exists to prevent."""
    bid = _mk_board(client, admin_id, invite=guinea_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": guinea_id,
          "conditions": [{"kind": "priority_is", "value": "critical"}]})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})

    runs = _runs(client, bid, admin_id)
    assert len(runs) == 1, runs
    assert runs[0]["outcome"] == "skipped"
    assert "התנאי אינו מתקיים" in runs[0]["reason"]
    assert "העדיפות" in runs[0]["reason"]      # which one, in the board's words


def test_both_conditions_must_hold(client, admin_id, guinea_id):
    """Two conditions are ANDed: one of them holding is not enough."""
    bid = _mk_board(client, admin_id, invite=guinea_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": guinea_id,
          "conditions": [{"kind": "priority_is", "value": "critical"},
                         {"kind": "has_assignee"}]})

    # urgent, but nobody on it
    alone = _mk_item(client, bid, admin_id, "קריטי בלי אחראי")
    client.patch(f"/api/tasks/{alone}?user_id={admin_id}", json={"priority": "critical"})
    client.patch(f"/api/tasks/{alone}?user_id={admin_id}", json={"status": "done"})
    assert not _notes_for(alone, guinea_id)

    # urgent and assigned
    both = _mk_item(client, bid, admin_id, "קריטי עם אחראי")
    client.patch(f"/api/tasks/{both}?user_id={admin_id}", json={"priority": "critical"})
    client.post(f"/api/tasks/{both}/assignees",
                json={"actor_id": admin_id, "user_id": admin_id})
    client.patch(f"/api/tasks/{both}?user_id={admin_id}", json={"status": "done"})
    assert len(_notes_for(both, guinea_id)) == 1


def test_a_rule_with_no_conditions_behaves_exactly_as_before(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    _add(client, bid, admin_id, "status_notify_person",
         {"t_status": "done", "a_person": guinea_id})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    assert len(_notes_for(tid, guinea_id)) == 1


def test_the_sentence_reads_the_conditions_out(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    r = _add(client, bid, admin_id, "status_notify_person",
             {"t_status": "done", "a_person": guinea_id,
              "conditions": [{"kind": "priority_is", "value": "critical"},
                             {"kind": "no_assignee"}]}).json()
    # what happened, what else had to be true, and only then what is done
    assert "ורק אם" in r["sentence"] and " וגם " in r["sentence"]
    assert r["sentence"].index("ורק אם") < r["sentence"].index("שלח התראה")
    assert r["condition_phrases"] and len(r["condition_phrases"]) == 2
    assert r["conditions"][0] == {"kind": "priority_is", "value": "critical"}
    # the name a nameless rule falls back on is that same sentence
    assert "ורק אם" in r["display_name"]


def test_a_condition_with_no_value_is_refused(client, admin_id, guinea_id):
    """Not a blank to come back to: "only if the status is …" with no status is
    not a narrower rule, it is the rule without the condition."""
    bid = _mk_board(client, admin_id, invite=guinea_id)
    r = _add(client, bid, admin_id, "status_notify_person",
             {"t_status": "done", "a_person": guinea_id,
              "conditions": [{"kind": "status_is"}]})
    assert r.status_code == 400
    # and a draft, which may leave the recipe's own blanks empty, is no softer
    d = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": "status_notify_person", "status": "draft",
                          "config": {"conditions": [{"kind": "status_is"}]}})
    assert d.status_code == 400


def test_conditions_that_cannot_both_hold_are_refused(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    for conds in ([{"kind": "has_assignee"}, {"kind": "no_assignee"}],
                  [{"kind": "status_is", "value": "done"},
                   {"kind": "status_is", "value": "stuck"}],
                  [{"kind": "overdue"}, {"kind": "no_due_date"}],
                  [{"kind": "priority_is", "value": "critical"},
                   {"kind": "priority_is_not", "value": "critical"}]):
        r = _add(client, bid, admin_id, "status_notify_person",
                 {"t_status": "done", "a_person": guinea_id, "conditions": conds})
        assert r.status_code == 400, conds


def test_an_unknown_condition_is_refused_and_never_fires_blind(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    r = _add(client, bid, admin_id, "status_notify_person",
             {"t_status": "done", "a_person": guinea_id,
              "conditions": [{"kind": "the_moon_is_full"}]})
    assert r.status_code == 400
    # and if one is ever stored by an older version, the rule holds its fire
    # rather than treating "cannot evaluate" as "go ahead"
    with Session(cityos_main.engine) as db:
        t = Task(board_id=bid, title="x")
        assert cityos_main._condition_holds(db, t, "the_moon_is_full", None) is False


def test_more_than_the_maximum_is_refused(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    many = [{"kind": "has_assignee"}, {"kind": "has_due_date"},
            {"kind": "priority_is", "value": "critical"},
            {"kind": "status_is", "value": "done"}]
    r = _add(client, bid, admin_id, "status_notify_person",
             {"t_status": "done", "a_person": guinea_id, "conditions": many})
    assert r.status_code == 400


def test_a_condition_may_not_name_a_stranger_to_the_board(client, admin_id, guinea_id):
    """The same bar an action's person gets: a rule that names somebody who was
    never invited is a rule that can never hold."""
    bid = _mk_board(client, admin_id)              # guinea NOT invited
    r = _add(client, bid, admin_id, "created_set_priority",
             {"a_priority": "high", "conditions": [{"kind": "person_is", "value": guinea_id}]})
    assert r.status_code == 400


def test_the_dry_run_answers_each_condition_separately(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "status_notify_person",
               {"t_status": "done", "a_person": guinea_id,
                "conditions": [{"kind": "priority_is", "value": "critical"}]}).json()["id"]
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})

    d = client.post(f"/api/automations/{aid}/test?user_id={admin_id}",
                    json={"task_id": tid}).json()
    # the trigger holds on this item; the extra condition does not, and the test
    # may not answer "would run" over it
    assert d["verdict"] == "would_skip"
    assert "התנאי אינו מתקיים" in d["summary"]
    mine = [c for c in d["conditions"] if "עדיפות" in c["label"]]
    assert mine and mine[0]["ok"] is False
    assert mine[0]["expected"] and mine[0]["actual"]      # both sides, side by side


def test_a_condition_change_shows_up_in_the_version_diff(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id, invite=guinea_id)
    aid = _add(client, bid, admin_id, "status_notify_person",
               {"t_status": "done", "a_person": guinea_id,
                "conditions": [{"kind": "priority_is", "value": "critical"}]}).json()["id"]
    client.patch(f"/api/automations/{aid}?user_id={admin_id}",
                 json={"status": "paused"})
    client.patch(f"/api/automations/{aid}?user_id={admin_id}",
                 json={"config": {"t_status": "done", "a_person": guinea_id,
                                  "conditions": [{"kind": "priority_is", "value": "high"}]}})
    d = client.get(f"/api/automations/{aid}/versions/compare?user_id={admin_id}").json()
    rows = [i for g in d["groups"] for i in g["changes"]]
    mine = [i for i in rows if i["key"] == "conditions"]
    assert mine, rows
    # read as the phrase, never as a list of dicts
    assert "{" not in mine[0]["to"] and "העדיפות" in mine[0]["to"]


def test_the_catalog_ships_templates_that_come_with_conditions(client, admin_id):
    """The two-clause rules a board actually writes, as a pick rather than an
    assembly: the template arrives with its conditions and the person fills in
    the values, exactly as they fill the recipe's own blanks."""
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    withc = [r for r in d["recipes"] if r.get("conditions")]
    assert len(withc) >= 5, [r["id"] for r in withc]
    two = [r for r in withc if len(r["conditions"]) == 2]
    assert two, "no template with two conditions"

    one = next(r for r in withc if r["id"] == "cond_status_prio_open_notify_assignees")
    assert [c["kind"] for c in one["conditions"]] == ["priority_is", "has_assignee"]
    # each condition says what it needs filled, and what it says
    assert one["conditions"][0]["type"] == "priority" and "…" in one["conditions"][0]["label"]
    assert one["conditions"][1]["type"] is None
    # a plain template is unchanged: an empty list, never a missing key
    plain = next(r for r in d["recipes"] if r["id"] == "status_notify_person")
    assert plain["conditions"] == []


def test_a_conditioned_template_is_not_offered_in_the_from_scratch_pairing(client, admin_id):
    """Trigger-and-action has to land on exactly one recipe. In that flow the
    conditions are step 2 — chosen, not inherited."""
    d = client.get(f"/api/automations/recipes?user_id={admin_id}").json()
    withc = {r["id"] for r in d["recipes"] if r.get("conditions")}
    offered = {a["recipe_id"] for b in d["blueprint"] for a in b["actions"]}
    assert not (offered & withc), offered & withc
    # and each pair is still offered exactly once
    pairs = [(b["trigger"], a["action"]) for b in d["blueprint"] for a in b["actions"]]
    assert len(pairs) == len(set(pairs))


def test_a_template_rule_fires_on_both_its_conditions(client, admin_id, guinea_id):
    """Saved from a template, it is the same row a hand-built rule is — so it
    runs through the same gate, on both clauses."""
    bid = _mk_board(client, admin_id, invite=guinea_id)
    r = _add(client, bid, admin_id, "cond_status_prio_open_notify_assignees",
             {"t_status": "done",
              "conditions": [{"kind": "priority_is", "value": "critical"},
                             {"kind": "has_assignee"}]})
    assert r.status_code == 200, r.text
    assert "ורק אם" in r.json()["sentence"] and " וגם " in r.json()["sentence"]

    # critical but unassigned → the notification has nobody and the rule holds
    nobody = _mk_item(client, bid, admin_id, "קריטי בלי אחראי")
    client.patch(f"/api/tasks/{nobody}?user_id={admin_id}", json={"priority": "critical"})
    client.patch(f"/api/tasks/{nobody}?user_id={admin_id}", json={"status": "done"})
    assert not _notes_for(nobody, guinea_id)

    # critical and assigned to guinea → guinea hears about it
    hot = _mk_item(client, bid, admin_id, "קריטי עם אחראי")
    client.patch(f"/api/tasks/{hot}?user_id={admin_id}", json={"priority": "critical"})
    client.post(f"/api/tasks/{hot}/assignees",
                json={"actor_id": admin_id, "user_id": guinea_id})
    # being assigned is itself a notification, so it is the DELTA across the
    # status change that says whether the rule spoke
    before = len(_notes_for(hot, guinea_id))
    client.patch(f"/api/tasks/{hot}?user_id={admin_id}", json={"status": "done"})
    assert len(_notes_for(hot, guinea_id)) == before + 1


def test_a_template_rule_still_has_to_have_its_values(client, admin_id, guinea_id):
    """The template brings the conditions, not their values."""
    bid = _mk_board(client, admin_id, invite=guinea_id)
    r = _add(client, bid, admin_id, "cond_status_prio_open_notify_assignees",
             {"t_status": "done",
              "conditions": [{"kind": "priority_is"}, {"kind": "has_assignee"}]})
    assert r.status_code == 400
