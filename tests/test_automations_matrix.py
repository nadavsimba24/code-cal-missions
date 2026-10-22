"""Group — the automations permission matrix, row by row.

              פעולה                          מנהל מערכת  מנהל לוח  חבר לוח  צופה
  צפייה ברשימה ובלוג                              כן        כן    הרשאה     לא
  יצירה, עריכה, הפעלה, השהיה, מחיקה               כן        כן      לא      לא
  העברת בעלות, סדר וחשיבות                        כן        כן      לא      לא
  Dry Run, הפעלה ידנית, Retry                     כן        כן      לא      לא
  שחזור גרסה, ייצוא לוג                           כן   הרשאת נתונים  לא     לא
  ניהול ארגוני והשבתת חירום                       כן        לא      לא      לא
  אוטומציה בין לוחות                              כן   רק אם מורשה   לא     לא
                                                       בכל הלוחות

"חבר לוח" is a board editor and "צופה" a board viewer — BROLE_HE's own words.
The two "הרשאה" cells are capabilities, because a role alone cannot express
"invited to the board, and allowed to read its machinery".
"""
from sqlalchemy.orm import Session
import main as cityos_main
from models import Board, BoardMember, RolePermission, User


def _role(client, admin_id, bid, uid, role):
    r = client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": uid, "role": role})
    assert r.status_code == 200, r.text


def _grant(cap, allowed=True, role="member"):
    """Turn a capability on for the workspace role the test users carry."""
    with Session(cityos_main.engine) as db:
        row = (db.query(RolePermission)
                 .filter(RolePermission.role == role, RolePermission.capability == cap).first())
        if not row:
            row = RolePermission(role=role, capability=cap, allowed=allowed)
            db.add(row)
        row.allowed = allowed
        db.commit()


def _ws_role_of(uid):
    with Session(cityos_main.engine) as db:
        return (db.query(User.role).filter(User.id == uid).scalar() or "guest")


def _board(client, admin_id, name="לוח מטריצה"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _add(client, bid, admin_id, recipe_id="created_set_priority", config=None, **extra):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config or {"a_priority": "high"},
                          **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


# ── row 1 — צפייה ברשימה ובלוג ───────────────────────────────────────────────

def test_row1_viewing(client, admin_id, guinea_id, member_id):
    bid = _board(client, admin_id)
    _add(client, bid, admin_id)
    _role(client, admin_id, bid, guinea_id, "editor")
    _role(client, admin_id, bid, member_id, "viewer")
    see = lambda uid: client.get(f"/api/boards/{bid}/automations?user_id={uid}").status_code
    log = lambda uid: client.get(f"/api/boards/{bid}/automations/runs?user_id={uid}").status_code

    # מנהל מערכת · מנהל לוח → כן
    assert see(admin_id) == 200 and log(admin_id) == 200

    # חבר לוח → only with the dedicated capability
    _grant("view_automations", False, _ws_role_of(guinea_id))
    assert see(guinea_id) == 403 and log(guinea_id) == 403
    _grant("view_automations", True, _ws_role_of(guinea_id))
    assert see(guinea_id) == 200 and log(guinea_id) == 200

    # צופה → never, capability or not
    _grant("view_automations", True, _ws_role_of(member_id))
    assert see(member_id) == 403, "a board viewer got in through the capability"
    assert log(member_id) == 403
    _grant("view_automations", False, _ws_role_of(guinea_id))


def test_row1_someone_off_the_board_sees_nothing(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _grant("view_automations", True, _ws_role_of(guinea_id))
    assert client.get(f"/api/boards/{bid}/automations?user_id={guinea_id}").status_code == 403
    _grant("view_automations", False, _ws_role_of(guinea_id))


# ── rows 2-4 — everything that changes a rule, and running one ───────────────

def test_rows2to4_changing_and_running(client, admin_id, guinea_id, member_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id)
    tid = _item(client, bid, admin_id)
    _role(client, admin_id, bid, guinea_id, "editor")
    _role(client, admin_id, bid, member_id, "viewer")
    _grant("view_automations", True, _ws_role_of(guinea_id))     # seeing is not doing

    def attempts(uid):
        return [
            client.post(f"/api/boards/{bid}/automations?user_id={uid}",
                        json={"recipe_id": "created_set_priority",
                              "config": {"a_priority": "low"}}).status_code,          # יצירה
            client.patch(f"/api/automations/{a['id']}?user_id={uid}",
                         json={"name": "שונה"}).status_code,                           # עריכה
            client.patch(f"/api/automations/{a['id']}?user_id={uid}",
                         json={"status": "paused"}).status_code,                        # השהיה
            client.patch(f"/api/automations/{a['id']}?user_id={uid}",
                         json={"owner_id": uid}).status_code,                          # בעלות
            client.patch(f"/api/automations/{a['id']}?user_id={uid}",
                         json={"importance": "critical", "run_order": 3}).status_code,  # סדר/חשיבות
            client.post(f"/api/automations/{a['id']}/test?user_id={uid}",
                        json={"task_id": tid}).status_code,                            # Dry Run
            client.post(f"/api/automations/{a['id']}/run?user_id={uid}",
                        json={"task_id": tid}).status_code,                            # הפעלה ידנית
            client.post(f"/api/boards/{bid}/automations/bulk?user_id={uid}",
                        json={"ids": [a["id"]], "action": "pause"}).status_code,        # מרובה
            client.delete(f"/api/automations/{a['id']}?user_id={uid}").status_code,     # מחיקה
        ]

    assert all(c == 403 for c in attempts(guinea_id)), attempts(guinea_id)
    assert all(c == 403 for c in attempts(member_id)), attempts(member_id)
    # and the board admin — the same list, all the way to the delete
    assert all(c == 200 for c in attempts(admin_id)), attempts(admin_id)
    _grant("view_automations", False, _ws_role_of(guinea_id))


def test_row4_retry_is_admin_only(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "todo"})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": admin_id})
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]
    skipped = next(r for r in runs if r["can_retry"])
    _role(client, admin_id, bid, guinea_id, "editor")
    assert client.post(f"/api/automation-runs/{skipped['id']}/retry?user_id={guinea_id}"
                       ).status_code == 403
    assert client.post(f"/api/automation-runs/{skipped['id']}/retry?user_id={admin_id}"
                       ).status_code == 200


def test_row4_a_manual_run_really_runs_and_a_dry_run_does_not(client, admin_id):
    """The two are separate endpoints because one keeps what it did."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"},
             status="draft")
    tid = _item(client, bid, admin_id)
    client.post(f"/api/automations/{a['id']}/test?user_id={admin_id}", json={"task_id": tid})
    assert client.get(f"/api/tasks/{tid}?user_id={admin_id}").json()["status"] != "in_progress"

    r = client.post(f"/api/automations/{a['id']}/run?user_id={admin_id}", json={"task_id": tid})
    assert r.status_code == 200 and r.json()["run"]["outcome"] == "ran"
    assert r.json()["run"]["is_test"] is False
    assert client.get(f"/api/tasks/{tid}?user_id={admin_id}").json()["status"] == "in_progress"


def test_row4_a_manual_run_refuses_while_an_emergency_stop_holds(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"})
    tid = _item(client, bid, admin_id)
    f = client.post(f"/api/admin/automations/freeze?user_id={admin_id}",
                    json={"scope": "board", "board_id": bid, "reason": "חקירה"}).json()
    r = client.post(f"/api/automations/{a['id']}/run?user_id={admin_id}", json={"task_id": tid})
    assert r.status_code == 400 and "מושהות" in r.json()["detail"]
    client.post(f"/api/admin/automations/release?user_id={admin_id}",
                json={"freeze_id": f["freeze"]["id"]})


# ── column 2 on its own — מנהל לוח who is not מנהל מערכת ─────────────────────
# Every check above that says "כן" was made by a system admin, who passes each
# of these by being one. So none of them showed that being admin OF THE BOARD
# is itself enough, which is what the second column of the matrix claims.

def test_rows2to4_a_board_admin_is_enough_on_their_own_board(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח בניהול חבר")
    _role(client, admin_id, bid, guinea_id, "admin")
    assert _ws_role_of(guinea_id) != "admin", "this needs an ordinary member"
    tid = _item(client, bid, admin_id)
    me = f"user_id={guinea_id}"

    r = client.post(f"/api/boards/{bid}/automations?{me}",                      # יצירה
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "high"}})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]

    for body in ({"name": "שם חדש"},                                            # עריכה
                 {"description": "הסבר"},
                 {"importance": "critical", "run_order": 4},                     # חשיבות וסדר
                 {"owner_id": guinea_id},                                        # בעלות
                 {"status": "paused"},                                           # השהיה
                 {"status": "active"},                                           # הפעלה
                 {"config": {"a_priority": "low"}}):                             # תוכן הכלל
        got = client.patch(f"/api/automations/{aid}?{me}", json=body)
        assert got.status_code == 200, (body, got.text)

    assert client.post(f"/api/automations/{aid}/publish?{me}").status_code == 200
    client.patch(f"/api/automations/{aid}?{me}", json={"config": {"a_priority": "high"}})
    assert client.post(f"/api/automations/{aid}/discard-draft?{me}").status_code == 200

    assert client.post(f"/api/automations/{aid}/test?{me}",                      # Dry Run
                       json={"task_id": tid}).status_code == 200
    assert client.post(f"/api/automations/{aid}/run?{me}",                       # הפעלה ידנית
                       json={"task_id": tid}).status_code == 200
    assert client.post(f"/api/boards/{bid}/automations/bulk?{me}",               # פעולה מרובה
                       json={"ids": [aid], "action": "pause"}).status_code == 200
    copy = client.post(f"/api/automations/{aid}/duplicate?{me}")                 # שכפול
    assert copy.status_code == 200, copy.text

    for url in (f"/api/boards/{bid}/automations?{me}",                           # row 1, without
                f"/api/boards/{bid}/automations/runs?{me}",                      # any capability
                f"/api/boards/{bid}/automations/tests?{me}",                     # being granted
                f"/api/automations/{aid}/versions?{me}",
                f"/api/automations/{aid}/versions/compare?{me}",
                f"/api/automations/{aid}/impact?{me}"):
        assert client.get(url).status_code == 200, url

    assert client.delete(f"/api/automations/{copy.json()['id']}?{me}").status_code == 200
    assert client.delete(f"/api/automations/{aid}?{me}").status_code == 200      # מחיקה


def test_row4_a_board_admin_may_retry_a_run(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח הפעלה חוזרת")
    _add(client, bid, admin_id, "assigned_set_status", {"a_status": "todo"})
    tid = _item(client, bid, admin_id)
    client.post(f"/api/tasks/{tid}/assignees", json={"actor_id": admin_id, "user_id": admin_id})
    runs = client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]
    skipped = next(r for r in runs if r["can_retry"])
    _role(client, admin_id, bid, guinea_id, "admin")
    assert client.post(f"/api/automation-runs/{skipped['id']}/retry?user_id={guinea_id}"
                       ).status_code == 200


# ── row 5 — שחזור גרסה וייצוא לוג, לפי הרשאת נתונים ──────────────────────────

def test_row5_restore_and_log_export_need_the_data_capability(client, admin_id, guinea_id):
    bid = _board(client, admin_id, "לוח נתונים")
    a = _add(client, bid, admin_id, name="שם ראשון")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"name": "שם שני"})
    # guinea is made a board ADMIN — the role is right, the data capability is not
    _role(client, admin_id, bid, guinea_id, "admin")
    _grant("export_automation_log", False, _ws_role_of(guinea_id))
    _grant("view_automations", True, _ws_role_of(guinea_id))

    log = f"/api/boards/{bid}/automations/runs/export?user_id={guinea_id}"
    lst = f"/api/boards/{bid}/automations/export?user_id={guinea_id}"
    res = f"/api/automations/{a['id']}/restore/1?user_id={guinea_id}"
    assert client.get(log).status_code == 403
    assert client.get(lst).status_code == 403
    assert client.post(res).status_code == 403

    _grant("export_automation_log", True, _ws_role_of(guinea_id))
    assert client.get(log).status_code == 200
    assert client.get(lst).status_code == 200
    assert client.post(res).status_code == 200
    _grant("export_automation_log", False, _ws_role_of(guinea_id))
    _grant("view_automations", False, _ws_role_of(guinea_id))
    # a system admin needs no grant
    assert client.get(f"/api/boards/{bid}/automations/runs/export?user_id={admin_id}"
                      ).status_code == 200


def test_row5_a_restore_offers_the_old_configuration_as_a_draft(client, admin_id):
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, name="התחלה", importance="low")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                 json={"name": "אחרי", "importance": "critical", "run_order": 7})
    back = client.post(f"/api/automations/{a['id']}/restore/1?user_id={admin_id}")
    assert back.status_code == 200, back.text
    got = back.json()
    # the rule has NOT moved — the restore is waiting to be published
    assert got["name"] == "אחרי" and got["importance"] == "critical"
    assert got["draft_version"], "the restore did not produce a draft"
    v = client.get(f"/api/automations/{a['id']}/versions?user_id={admin_id}").json()["versions"]
    assert v[0]["summary"] == "טיוטה משוחזרת מגרסה 1", v[0]
    assert [x["version"] for x in v] == [3, 2, 1], "the restore rewound the history"

    live = client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}").json()
    assert live["name"] == "התחלה" and live["importance"] == "low"
    assert live["draft_version"] is None


def test_row5_a_restore_never_changes_whether_the_rule_runs(client, admin_id):
    """The state it was in three versions ago is not a decision about now —
    not on the restore, and not on the publish either."""
    bid = _board(client, admin_id)
    a = _add(client, bid, admin_id, name="ראשון")
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "paused"})
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"name": "שני"})
    back = client.post(f"/api/automations/{a['id']}/restore/1?user_id={admin_id}").json()
    assert back["status"] == "paused"
    live = client.post(f"/api/automations/{a['id']}/publish?user_id={admin_id}").json()
    assert live["status"] == "paused" and live["is_active"] is False, \
        "publishing an older wording switched the rule on"
    assert live["name"] == "ראשון"


def test_row5_the_log_export_is_the_log(client, admin_id):
    bid = _board(client, admin_id)
    _add(client, bid, admin_id, "created_set_status", {"a_status": "in_progress"}, name="כלל")
    _item(client, bid, admin_id, "פריט בלוג")
    r = client.get(f"/api/boards/{bid}/automations/runs/export?user_id={admin_id}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert "פריט בלוג" in body and "הופעלה" in body
    assert "תוצאה" in body.splitlines()[0]


# ── row 6 — ניהול ארגוני והשבתת חירום ────────────────────────────────────────

def test_row6_org_management_is_system_admin_only(client, admin_id, guinea_id):
    """A board admin is explicitly NOT enough — it can halt every board at once."""
    bid = _board(client, admin_id)
    _role(client, admin_id, bid, guinea_id, "admin")
    _grant("view_automations", True, _ws_role_of(guinea_id))
    _grant("export_automation_log", True, _ws_role_of(guinea_id))
    assert client.get(f"/api/admin/automations?user_id={guinea_id}").status_code == 403
    assert client.get(f"/api/admin/automations/export?user_id={guinea_id}").status_code == 403
    assert client.post(f"/api/admin/automations/freeze?user_id={guinea_id}",
                       json={"scope": "board", "board_id": bid, "reason": "לא מורשה"}
                       ).status_code == 403
    assert client.post(f"/api/admin/automations/release?user_id={guinea_id}",
                       json={"freeze_id": 1}).status_code == 403
    assert client.get(f"/api/admin/automations?user_id={admin_id}").status_code == 200
    _grant("view_automations", False, _ws_role_of(guinea_id))
    _grant("export_automation_log", False, _ws_role_of(guinea_id))


# ── row 7 — אוטומציה בין לוחות ───────────────────────────────────────────────

def _connect_board(client, admin_id, name, targets):
    """A board with a connect column pointing at `targets`."""
    bid = _board(client, admin_id, name)
    cols = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    cols = [c for c in cols if str(c.get("id", "")).startswith("col_")]
    cols.append({"id": "col_link", "type": "connect", "title": "קישור",
                 "connect": {"board_ids": targets, "multi": True}})
    r = client.patch(f"/api/boards/{bid}?actor_id={admin_id}", json={"columns": cols})
    assert r.status_code == 200, r.text
    return bid


def test_row7_a_cross_board_rule_needs_rights_on_the_far_board(client, admin_id, guinea_id):
    far = _board(client, admin_id, "לוח היעד")
    near = _connect_board(client, admin_id, "לוח המקור", [far])
    # guinea runs the near board but has nothing on the far one
    _role(client, admin_id, near, guinea_id, "admin")
    body = {"recipe_id": "created_create_and_link",
            "config": {"a_connect": "col_link", "a_board": far, "a_text": "פריט חדש"}}
    r = client.post(f"/api/boards/{near}/automations?user_id={guinea_id}", json=body)
    assert r.status_code == 403, r.text
    assert "בכל הלוחות" in r.json()["detail"]
    assert "לוח היעד" in r.json()["detail"], "the board they lack rights on is not named"

    # given rights there, the same rule saves
    _role(client, admin_id, far, guinea_id, "editor")
    assert client.post(f"/api/boards/{near}/automations?user_id={guinea_id}",
                       json=body).status_code == 200


def test_row7_a_viewer_on_the_far_board_is_not_enough(client, admin_id, guinea_id):
    """A rule that creates items there writes on it; reading is not writing."""
    far = _board(client, admin_id, "יעד לקריאה")
    near = _connect_board(client, admin_id, "מקור", [far])
    _role(client, admin_id, near, guinea_id, "admin")
    _role(client, admin_id, far, guinea_id, "viewer")
    r = client.post(f"/api/boards/{near}/automations?user_id={guinea_id}",
                    json={"recipe_id": "created_create_and_link",
                          "config": {"a_connect": "col_link", "a_board": far,
                                     "a_text": "פריט"}})
    assert r.status_code == 403


def test_row7_a_system_admin_reaches_every_board(client, admin_id):
    far = _board(client, admin_id, "יעד למנהל מערכת")
    near = _connect_board(client, admin_id, "מקור למנהל מערכת", [far])
    assert client.post(f"/api/boards/{near}/automations?user_id={admin_id}",
                       json={"recipe_id": "created_create_and_link",
                             "config": {"a_connect": "col_link", "a_board": far,
                                        "a_text": "פריט"}}).status_code == 200


def test_row7_a_rule_that_stays_on_its_own_board_is_unaffected(client, admin_id, guinea_id):
    bid = _board(client, admin_id)
    _role(client, admin_id, bid, guinea_id, "admin")
    assert client.post(f"/api/boards/{bid}/automations?user_id={guinea_id}",
                       json={"recipe_id": "created_set_priority",
                             "config": {"a_priority": "high"}}).status_code == 200


def test_row7_a_second_action_reaches_just_as_far_as_the_first(client, admin_id, guinea_id):
    """A rule carries up to four actions, and only the first of them is the
    recipe's own. "אז שנה עדיפות — וגם צור פריט בלוח ההוא" writes on the far
    board exactly as a connect recipe does, and the rule reads as harmless.
    """
    far = _board(client, admin_id, "יעד של פעולה נוספת")
    near = _connect_board(client, admin_id, "מקור של פעולה נוספת", [far])
    _role(client, admin_id, near, guinea_id, "admin")
    body = {"recipe_id": "created_set_priority",
            "config": {"a_priority": "high",
                       "actions": [{"key": "create_and_link",
                                    "values": {"connect": "col_link", "board": far,
                                               "text": "פריט מרוחק"}}]}}
    r = client.post(f"/api/boards/{near}/automations?user_id={guinea_id}", json=body)
    assert r.status_code == 403, r.text
    assert "בכל הלוחות" in r.json()["detail"]
    assert "יעד של פעולה נוספת" in r.json()["detail"]

    _role(client, admin_id, far, guinea_id, "editor")
    assert client.post(f"/api/boards/{near}/automations?user_id={guinea_id}",
                       json=body).status_code == 200


def test_row7_a_second_action_is_checked_when_it_is_added_to_a_saved_rule(client, admin_id,
                                                                          guinea_id):
    """The same, arriving the way it really would: an ordinary rule, saved and
    switched on, which someone then gives a second action."""
    far = _board(client, admin_id, "יעד שנוסף אחר כך")
    near = _connect_board(client, admin_id, "מקור שנוסף אחר כך", [far])
    _role(client, admin_id, near, guinea_id, "admin")
    a = client.post(f"/api/boards/{near}/automations?user_id={guinea_id}",
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "high"}}).json()
    r = client.patch(f"/api/automations/{a['id']}?user_id={guinea_id}",
                     json={"config": {"a_priority": "high",
                                      "actions": [{"key": "create_and_link",
                                                   "values": {"connect": "col_link",
                                                              "board": far,
                                                              "text": "פריט"}}]}})
    assert r.status_code == 403, r.text
    assert "בכל הלוחות" in r.json()["detail"]


def test_row7_an_extra_action_linking_to_an_item_elsewhere_is_checked_too(client, admin_id,
                                                                          guinea_id):
    """`קשר את הפריט אל …` names an item, and an item belongs to a board."""
    far = _board(client, admin_id, "יעד לקישור פריט")
    far_item = _item(client, far, admin_id, "פריט בלוח הרחוק")
    near = _connect_board(client, admin_id, "מקור לקישור פריט", [far])
    _role(client, admin_id, near, guinea_id, "admin")
    r = client.post(f"/api/boards/{near}/automations?user_id={guinea_id}",
                    json={"recipe_id": "created_set_priority",
                          "config": {"a_priority": "high",
                                     "actions": [{"key": "link_to_item",
                                                  "values": {"connect": "col_link",
                                                             "item": far_item}}]}})
    assert r.status_code == 403, r.text
    assert "יעד לקישור פריט" in r.json()["detail"]


# ── row 7, the other half — ACTING on a cross-board rule ────────────────────
# Writing the rule was checked. But the rule is an object on the board, and a
# board admin has a whole shelf of verbs for it: switch it on, run it by hand,
# run it again, copy it, activate it with fifty others in one click. Each of
# those makes it write on the far board just as surely as saving it does, and
# the one who typed it there may not be the one who reaches for the switch.


def _far_reaching_rule(client, admin_id, guinea_id, name="מקור בניהול חבר"):
    """A paused rule on `near` that creates items on `far`.

    A system admin wrote it — they may. guinea runs `near` and has nothing at
    all on `far`, which is the whole question: what may they do with it.
    """
    far = _board(client, admin_id, "יעד ללא הרשאה " + name)
    near = _connect_board(client, admin_id, name, [far])
    a = client.post(f"/api/boards/{near}/automations?user_id={admin_id}",
                    json={"recipe_id": "created_create_and_link", "status": "paused",
                          "config": {"a_connect": "col_link", "a_board": far,
                                     "a_text": "פריט מרוחק"}})
    assert a.status_code == 200, a.text
    _role(client, admin_id, near, guinea_id, "admin")
    return far, near, a.json()


def test_row7_switching_a_cross_board_rule_on_needs_rights_there(client, admin_id, guinea_id):
    far, near, a = _far_reaching_rule(client, admin_id, guinea_id, "הפעלה")
    me = f"user_id={guinea_id}"
    r = client.patch(f"/api/automations/{a['id']}?{me}", json={"status": "active"})
    assert r.status_code == 403, r.text
    assert "בכל הלוחות" in r.json()["detail"]
    assert client.get(f"/api/automations/{a['id']}/impact?{me}").json()["status"] != "active", \
        "the rule started anyway"
    _role(client, admin_id, far, guinea_id, "editor")
    assert client.patch(f"/api/automations/{a['id']}?{me}",
                        json={"status": "active"}).status_code == 200


def test_row7_a_bulk_activate_leaves_a_cross_board_rule_off(client, admin_id, guinea_id):
    """The same switch, reached through the action that moves fifty at once —
    and it has to say which rule it would not touch, not fail the whole call."""
    far, near, a = _far_reaching_rule(client, admin_id, guinea_id, "מרובה")
    mine = client.post(f"/api/boards/{near}/automations?user_id={guinea_id}",
                       json={"recipe_id": "created_set_priority", "status": "paused",
                             "config": {"a_priority": "high"}}).json()
    r = client.post(f"/api/boards/{near}/automations/bulk?user_id={guinea_id}",
                    json={"ids": [a["id"], mine["id"]], "action": "activate"})
    assert r.status_code == 200, r.text
    rows = {x["id"]: x for x in r.json()["results"]}
    assert rows[a["id"]]["ok"] is False and "בכל הלוחות" in rows[a["id"]]["message"]
    assert rows[mine["id"]]["ok"] is True, rows[mine["id"]]
    live = client.get(f"/api/boards/{near}/automations?user_id={guinea_id}").json()["automations"]
    assert {x["id"]: x["status"] for x in live}[a["id"]] != "active"


def test_row7_running_a_cross_board_rule_by_hand_needs_rights_there(client, admin_id, guinea_id):
    """Row 4 says a board admin may run a rule by hand. Row 7 says this rule
    is not theirs to set off — and a manual run is the shortest way to make it
    write on a board they were never given."""
    far, near, a = _far_reaching_rule(client, admin_id, guinea_id, "ידנית")
    tid = _item(client, near, admin_id)
    me = f"user_id={guinea_id}"
    r = client.post(f"/api/automations/{a['id']}/run?{me}", json={"task_id": tid})
    assert r.status_code == 403 and "בכל הלוחות" in r.json()["detail"], r.text
    assert client.post(f"/api/automations/{a['id']}/test?{me}",
                       json={"task_id": tid}).status_code == 403, "a dry run too"
    _role(client, admin_id, far, guinea_id, "editor")
    assert client.post(f"/api/automations/{a['id']}/run?{me}",
                       json={"task_id": tid}).status_code == 200


def test_row7_retrying_a_cross_board_run_needs_rights_there(client, admin_id, guinea_id):
    far = _board(client, admin_id, "יעד להפעלה חוזרת")
    near = _connect_board(client, admin_id, "מקור להפעלה חוזרת", [far])
    client.post(f"/api/boards/{near}/automations?user_id={admin_id}",
                json={"recipe_id": "created_create_and_link",
                      "config": {"a_connect": "col_link", "a_board": far,
                                 "a_text": "פריט מרוחק",
                                 "conditions": [{"kind": "priority_is", "value": "critical"}]}})
    _item(client, near, admin_id, "פריט רגיל")          # not critical → the run skips
    runs = client.get(f"/api/boards/{near}/automations/runs?user_id={admin_id}").json()["runs"]
    skipped = next(r for r in runs if r["can_retry"])
    _role(client, admin_id, near, guinea_id, "admin")
    r = client.post(f"/api/automation-runs/{skipped['id']}/retry?user_id={guinea_id}")
    assert r.status_code == 403 and "בכל הלוחות" in r.json()["detail"], r.text
    _role(client, admin_id, far, guinea_id, "editor")
    assert client.post(f"/api/automation-runs/{skipped['id']}/retry?user_id={guinea_id}"
                       ).status_code == 200


def test_row7_a_copy_does_not_carry_a_reference_its_author_may_not_have(client, admin_id,
                                                                         guinea_id):
    """A copy is a new rule, written by whoever asked for it — so it is written
    under their rights, not under the rights of whoever wrote the original.

    The reference is what does not come with it (see _strip_unreachable_refs);
    the copy itself is made, as a draft with a blank where the far board was.
    Row 7 holds either way — what lands on the board is not a cross-board rule —
    and the two places that would make it one are still shut: it cannot be
    switched on with the blank, and filling the blank back in is refused.
    """
    far, near, a = _far_reaching_rule(client, admin_id, guinea_id, "שכפול")
    me = f"user_id={guinea_id}"
    r = client.post(f"/api/automations/{a['id']}/duplicate?{me}")
    assert r.status_code == 200, r.text
    copy = r.json()
    assert copy["status"] == "draft"
    assert copy["config"].get("a_board") is None, copy["config"]
    assert any("יעד ללא הרשאה" in x for x in copy["dropped_references"]), copy
    assert copy["missing_fields"], copy

    # and the blank is a wall, not a formality
    assert client.patch(f"/api/automations/{copy['id']}?{me}",
                        json={"status": "active"}).status_code == 400
    back = client.patch(f"/api/automations/{copy['id']}?{me}",
                        json={"config": {"a_connect": "col_link", "a_board": far,
                                         "a_text": "פריט מרוחק"}})
    assert back.status_code == 403 and "בכל הלוחות" in back.json()["detail"], back.text

    # given rights there, the copy comes out whole
    _role(client, admin_id, far, guinea_id, "editor")
    whole = client.post(f"/api/automations/{a['id']}/duplicate?{me}").json()
    assert whole["config"].get("a_board") == far and whole["dropped_references"] == []


def test_row7_reading_it_and_pausing_it_are_never_blocked(client, admin_id, guinea_id):
    """The check is on making it act. Looking at a rule on your own board, and
    stopping one, are not that — and refusing the stop would be the wrong way
    round: it would leave the admin of a board unable to halt what runs on it."""
    far, near, a = _far_reaching_rule(client, admin_id, guinea_id, "עצירה")
    me = f"user_id={guinea_id}"
    client.patch(f"/api/automations/{a['id']}?user_id={admin_id}", json={"status": "active"})
    assert client.get(f"/api/boards/{near}/automations?{me}").status_code == 200
    assert client.get(f"/api/automations/{a['id']}/versions?{me}").status_code == 200
    assert client.patch(f"/api/automations/{a['id']}?{me}",
                        json={"status": "paused"}).status_code == 200
    assert client.patch(f"/api/automations/{a['id']}?{me}",
                        json={"name": "שם אחר"}).status_code == 200
    assert client.delete(f"/api/automations/{a['id']}?{me}").status_code == 200


# ── the capabilities are offered where permissions are managed ───────────────

def test_the_two_new_capabilities_are_manageable(client, admin_id):
    assert "view_automations" in cityos_main.CAPABILITIES
    assert "export_automation_log" in cityos_main.CAPABILITIES
    for cap in ("view_automations", "export_automation_log"):
        assert cityos_main.CAP_HE.get(cap), f"{cap} has no Hebrew name in the permissions screen"
    d = client.get(f"/api/permissions?user_id={admin_id}")
    if d.status_code == 200:
        assert "view_automations" in str(d.json())


# ── and the screen offers only what the matrix allows ───────────────────────

def test_the_board_payload_says_whether_the_page_is_offered_at_all(client, admin_id,
                                                                   guinea_id, member_id):
    """A viewer must not be shown a ⚡ button that answers 403."""
    bid = _board(client, admin_id)
    _role(client, admin_id, bid, guinea_id, "editor")
    _role(client, admin_id, bid, member_id, "viewer")
    flag = lambda uid: client.get(f"/api/boards/{bid}?user_id={uid}"
                                  ).json()["can_view_automations"]
    assert flag(admin_id) is True
    assert flag(member_id) is False
    _grant("view_automations", False, _ws_role_of(guinea_id))
    assert flag(guinea_id) is False
    _grant("view_automations", True, _ws_role_of(guinea_id))
    assert flag(guinea_id) is True
    _grant("view_automations", False, _ws_role_of(guinea_id))


def test_the_screen_hides_what_the_server_would_refuse():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "index.html"
           ).read_text(encoding="utf-8")
    # the button and the menu entry both read the flag
    assert "st.board.can_view_automations!==false" in src
    assert src.count("can_view_automations") >= 2
    # the export and the restore read the data capability
    assert "this.data.can_export?" in src
    assert "canRestore=this.data.can_manage&&this.data.can_export" in src
    # and the on/off switch says WHICH refusal it got: "you are not the board's
    # admin" and "you are, but not on the board this rule writes on" are two
    # different problems with two different things to do about them
    assert "toast(e.detail||'רק מנהל הלוח יכול לשנות אוטומציות')" in src
