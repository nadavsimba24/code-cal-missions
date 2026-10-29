"""יצירת פריט בלוח אחר — בלי קישור.

Every cross-board action in this catalog has been a LINK action: it creates the
item and ties it to the one that set the rule off, and the connect column is
both the route and the permission at once. That left a hand-off unsayable —
"כאשר פריט מועבר ל«הועברו לפרסום», צור פריט ב«מעקב התקשרויות»" is two boards
with no relationship between the items, and nothing to connect them by.

The specification allows it as the second of two routes: "אוטומציה בין לוחות
תתבסס על עמודת קישור או על יצירת פריט בלוח יעד שהוגדר מראש".

What this group is really about is the PERMISSION. With no connect column there
is no column to read the allowed boards off, so the two things that were always
underneath it have to carry the weight on their own: the author must hold
writing rights on the target board for the rule to be saved at all, and the
grant recording that is re-read before every firing. A cross-board write that
rested on a check made once, months ago, is the failure worth testing for.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Automation, Board, Task


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _group(client, bid, admin_id, name="קבוצה"):
    r = client.post("/api/groups",
                    json={"board_id": bid, "name": name, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _groups(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["groups"]


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks",
                       json={"board_id": bid, "title": title,
                             "user_id": admin_id}).json()["id"]


def _move(client, bid, admin_id, tid, gid):
    """Moving an item between groups goes through the board's own move
    endpoint — a PATCH carrying group_id does not move it."""
    r = client.post(f"/api/boards/{bid}/items/move",
                    json={"actor_id": admin_id, "group_id": gid, "ids": [tid]})
    assert r.status_code == 200, r.text


def _add(client, bid, actor, recipe_id, config, active=True):
    return client.post(f"/api/boards/{bid}/automations?user_id={actor}",
                       json={"recipe_id": recipe_id, "config": config, "is_active": active})


def _items_on(bid):
    with Session(cityos_main.engine) as db:
        return [t.title for t in db.query(Task).filter(
            Task.board_id == bid, Task.deleted_at == None).all()]      # noqa: E711


# ── the rule from the screenshot ───────────────────────────────────────────

def test_moving_an_item_opens_one_on_another_board(client, admin_id):
    """"When an item is moved to «הועברו לפרסום (ארכיון)» create an item in
    «B3 מחשוב - מעקב התקשרויות»"."""
    src = _board(client, admin_id, "לוח מקור")
    dst = _board(client, admin_id, "B3 מחשוב - מעקב התקשרויות")
    archive = _group(client, src, admin_id, "הועברו לפרסום (ארכיון)")
    target = _groups(client, dst, admin_id)[0]["id"]
    r = _add(client, src, admin_id, "moved_group_create_in_board",
             {"t_group": archive, "a_board": dst, "a_target_group": target,
              "a_text": "מעקב התקשרות"})
    assert r.status_code == 200, r.text
    tid = _item(client, src, admin_id, "מכרז 12/26")
    assert "מעקב התקשרות" not in _items_on(dst)
    _move(client, src, admin_id, tid, archive)
    assert "מעקב התקשרות" in _items_on(dst)


def test_the_new_item_lands_in_the_group_the_rule_names(client, admin_id):
    src = _board(client, admin_id, "מקור")
    dst = _board(client, admin_id, "יעד")
    archive = _group(client, src, admin_id, "ארכיון")
    second = _group(client, dst, admin_id, "נכנסות")
    _add(client, src, admin_id, "moved_group_create_in_board",
         {"t_group": archive, "a_board": dst, "a_target_group": second,
          "a_text": "חדש"})
    tid = _item(client, src, admin_id)
    _move(client, src, admin_id, tid, archive)
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == dst, Task.title == "חדש").first()
        assert made is not None and made.group_id == second


def test_it_does_not_open_a_second_one_for_the_same_item(client, admin_id):
    """The guard every creating action keeps: one target item per source item
    per rule, so an item moved out of the group and back does not pile up."""
    src = _board(client, admin_id, "מקור")
    dst = _board(client, admin_id, "יעד")
    archive = _group(client, src, admin_id, "ארכיון")
    other = _group(client, src, admin_id, "בעבודה")
    target = _groups(client, dst, admin_id)[0]["id"]
    _add(client, src, admin_id, "moved_group_create_in_board",
         {"t_group": archive, "a_board": dst, "a_target_group": target,
          "a_text": "חדש"})
    tid = _item(client, src, admin_id)
    for g in (archive, other, archive):
        _move(client, src, admin_id, tid, g)
    assert _items_on(dst).count("חדש") == 1


# ── the permission the connect column used to carry ────────────────────────

def test_an_author_without_rights_on_the_target_board_is_refused(
        client, admin_id, guinea_id):
    """With no connect column there is nothing declaring which boards the rule
    may reach, so the author's own rights are what stands in its place. A rule
    saved by somebody with rights only here would be a way to write onto a
    board they were never given — with the rule, not their hands, writing."""
    src = _board(client, admin_id, "מקור")
    dst = _board(client, admin_id, "יעד סגור")
    archive = _group(client, src, admin_id, "ארכיון")
    target = _groups(client, dst, admin_id)[0]["id"]
    # a board admin HERE, a stranger THERE
    client.post(f"/api/boards/{src}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "admin"})
    r = _add(client, src, guinea_id, "moved_group_create_in_board",
             {"t_group": archive, "a_board": dst, "a_target_group": target,
              "a_text": "חדש"})
    assert r.status_code == 403, r.text
    assert "הרשאה" in r.json()["detail"]


def test_the_grant_is_recorded_so_it_can_be_taken_away(client, admin_id):
    """A cross-board write that rested on a check made once, months ago, is the
    failure this is written against. The grant is a row, it names the board and
    the action, and revoking it stops the rule."""
    src = _board(client, admin_id, "מקור")
    dst = _board(client, admin_id, "יעד")
    archive = _group(client, src, admin_id, "ארכיון")
    target = _groups(client, dst, admin_id)[0]["id"]
    aid = _add(client, src, admin_id, "moved_group_create_in_board",
               {"t_group": archive, "a_board": dst, "a_target_group": target,
                "a_text": "חדש"}).json()["id"]
    with Session(cityos_main.engine) as db:
        grants = db.query(cityos_main.AutomationAuthorizationGrant).filter_by(
            automation_id=aid).all()
        assert [(g.target_board_id, g.action_key) for g in grants] \
            == [(dst, "create_in_board")], grants
        for g in grants:                       # an admin takes it away
            g.revoked_at = cityos_main._now_naive()
        db.commit()
    d = client.post(f"/api/boards/{src}/automations/validate?user_id={admin_id}",
                    json={"automation_id": aid}).json()
    assert any("מענק ההרשאה" in b for b in d["blockers"]), d["blockers"]


def test_a_deleted_target_board_stops_it_rather_than_failing_quietly(client, admin_id):
    src = _board(client, admin_id, "מקור")
    dst = _board(client, admin_id, "יעד שימחק")
    archive = _group(client, src, admin_id, "ארכיון")
    target = _groups(client, dst, admin_id)[0]["id"]
    aid = _add(client, src, admin_id, "moved_group_create_in_board",
               {"t_group": archive, "a_board": dst, "a_target_group": target,
                "a_text": "חדש"}).json()["id"]
    gone = client.delete(f"/api/boards/{dst}?user_id={admin_id}").json()
    # the deletion suspends the rules on OTHER boards that were writing into it
    assert gone["automations_suspended_elsewhere"] == 1, gone
    d = client.post(f"/api/boards/{src}/automations/validate?user_id={admin_id}",
                    json={"automation_id": aid}).json()
    assert d["valid"] is False
    assert any("לוח היעד נמחק" in e for e in d["errors"]), d


def test_another_organisations_board_is_never_a_target(client, admin_id):
    """Checked when it fires and not only when it was saved: a board moved
    between tenants afterwards is still one this rule must not write into."""
    src = _board(client, admin_id, "מקור")
    dst = _board(client, admin_id, "יעד")
    archive = _group(client, src, admin_id, "ארכיון")
    target = _groups(client, dst, admin_id)[0]["id"]
    _add(client, src, admin_id, "moved_group_create_in_board",
         {"t_group": archive, "a_board": dst, "a_target_group": target,
          "a_text": "חדש"})
    with Session(cityos_main.engine) as db:
        b = db.query(Board).filter(Board.id == dst).first()
        b.organization_id = (b.organization_id or 0) + 9999
        db.commit()
    tid = _item(client, src, admin_id)
    _move(client, src, admin_id, tid, archive)
    assert "חדש" not in _items_on(dst)
    runs = client.get(f"/api/boards/{src}/automations/runs?user_id={admin_id}").json()["runs"]
    assert runs and runs[0]["outcome"] == "skipped", runs
    assert "ארגון אחר" in runs[0]["reason"], runs[0]["reason"]


# ── it is a hand-off, not a relationship ───────────────────────────────────

def test_nothing_links_the_two_items(client, admin_id):
    """The difference from create_and_link, and the reason this exists: the
    source board need not have a connect column at all."""
    src = _board(client, admin_id, "מקור")
    dst = _board(client, admin_id, "יעד")
    archive = _group(client, src, admin_id, "ארכיון")
    target = _groups(client, dst, admin_id)[0]["id"]
    _add(client, src, admin_id, "moved_group_create_in_board",
         {"t_group": archive, "a_board": dst, "a_target_group": target,
          "a_text": "חדש"})
    tid = _item(client, src, admin_id)
    _move(client, src, admin_id, tid, archive)
    with Session(cityos_main.engine) as db:
        # no relationship was made, and none could have been: the source board
        # has no connect column at all, which is the whole point of this action.
        # Counted over THIS item only — the table is shared with every other
        # test in the run.
        assert db.query(cityos_main.ItemLink).filter(
            (cityos_main.ItemLink.a_task_id == tid)
            | (cityos_main.ItemLink.b_task_id == tid)).count() == 0
        cols = (db.query(Board).filter(Board.id == src).first().settings or {}
                ).get("columns") or []
        assert not [c for c in cols if c.get("type") == "connect"]
