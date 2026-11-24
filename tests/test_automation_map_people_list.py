"""A people column mapped onto another board carries its people, not a refusal.

On QA board 174 the rule "כאשר «סטטוס ההליך» משתנה ל«אושר לפרסום», צור פריט
בלוח B91…" failed on every firing: its mapping carried «מנה"פ מקומי» (a people
column) into «מנהל פרויקט» on the target board, and a people cell is a LIST.
The write str()'d the list and looked for a user named "[9]", so even a member
of the target board was refused — and the refusal took the created item back
with it. Nothing ever appeared on the other board.

Pinned here: a list of ids reaches the target cell; an imported email is
matched to the target board's member who has it; a name matching nobody is
carried as the text it was; and the rule's sentence names the copied fields
and the target columns in words, not as ['description'] and col_… ids.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import BoardMember, Task, User


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_col(client, bid, admin_id, col):
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id, "columns": _cols(client, bid) + [col]})
    assert r.status_code == 200, r.text
    return col


def _setup(client, admin_id, tag):
    a, b = _board(client, admin_id, f"הכנה {tag}"), _board(client, admin_id, f"חוזים {tag}")
    _add_col(client, a, admin_id, {"type": "connect", "title": "קישור",
                                   "connect": {"board_ids": [b], "multiple": True,
                                               "two_way": True}})
    conn = next(x for x in _cols(client, a) if x["type"] == "connect")
    src = _add_col(client, a, admin_id, {"id": f"col_pm_{tag}", "type": "people",
                                         "title": 'מנה"פ מקומי'})
    dst = _add_col(client, b, admin_id, {"id": f"col_mgr_{tag}", "type": "people",
                                         "title": "מנהל פרויקט"})
    grp = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id,
                          "recipe_id": "status_create_in_group_and_link",
                          "config": {"t_status": "done", "a_connect": conn["id"],
                                     "a_board": b, "a_target_group": grp,
                                     "a_text": "{{item.name}}",
                                     "a_fields": ["description"],
                                     "a_map": [{"from": src["id"], "to": dst["id"]}]}})
    assert r.status_code == 200, r.text
    return a, b, src, dst, r.json()


def _fire(client, a, admin_id, title, cell):
    tid = client.post("/api/tasks", json={"board_id": a, "title": title,
                                          "user_id": admin_id,
                                          "custom_fields": cell}).json()["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert r.status_code == 200, r.text


def _made(b, title):
    with Session(cityos_main.engine) as db:
        return [dict(t.custom_fields or {}) for t in
                db.query(Task).filter(Task.board_id == b, Task.title == title,
                                      Task.deleted_at == None).all()]   # noqa: E711


def test_a_list_of_member_ids_reaches_the_target_people_column(client, admin_id):
    a, b, src, dst, _ = _setup(client, admin_id, "ids")
    _fire(client, a, admin_id, "גבעת שמואל", {src["id"]: [admin_id]})
    made = _made(b, "גבעת שמואל")
    assert len(made) == 1, "the rule was refused and the item taken back"
    assert made[0].get(dst["id"]) == [admin_id]


def test_an_imported_email_is_matched_to_the_target_boards_member(client, admin_id):
    a, b, src, dst, _ = _setup(client, admin_id, "mail")
    with Session(cityos_main.engine) as db:
        email = db.query(User.email).filter(User.id == admin_id).scalar()
    _fire(client, a, admin_id, "אלעד", {src["id"]: [email.upper()]})
    made = _made(b, "אלעד")
    assert len(made) == 1, "an email the board can resolve must not refuse the rule"
    assert made[0].get(dst["id"]) == [admin_id]


def test_a_name_matching_nobody_is_carried_as_text_not_refused(client, admin_id):
    a, b, src, dst, _ = _setup(client, admin_id, "name")
    _fire(client, a, admin_id, "מטה יהודה", {src["id"]: ["אדם שאין לו חשבון"]})
    made = _made(b, "מטה יהודה")
    assert len(made) == 1, "an unknown imported name took the whole item back"
    assert made[0].get(dst["id"]) == ["אדם שאין לו חשבון"]


def test_the_sentence_names_the_fields_and_the_target_columns(client, admin_id):
    *_, rule = _setup(client, admin_id, "said")
    said = rule.get("sentence") or rule.get("label") or ""
    if not said:
        bid = rule["board_id"]
        said = next(x for x in client.get(f"/api/boards/{bid}/automations").json()
                    ["automations"] if x["id"] == rule["id"])["sentence"]
    assert "['description']" not in said and "תיאור" in said, said
    assert "col_mgr_said" not in said and "מנהל פרויקט" in said, said


def test_a_deactivated_member_named_in_the_source_is_not_put_on_the_item(client, admin_id):
    """A name resolves to an account only through the same gate an id does:
    a deactivated member still answers to their name, and must not be
    written onto the new item by it."""
    a, b, src, dst, _ = _setup(client, admin_id, "off")
    with Session(cityos_main.engine) as db:
        u = User(name="חבר מושבת", email="off-member@example.test",
                 is_active=False)
        db.add(u)
        db.flush()
        db.add(BoardMember(board_id=b, user_id=u.id, role="editor"))
        db.commit()
        uid = u.id
    try:
        _fire(client, a, admin_id, "רשות מושבתת", {src["id"]: ["חבר מושבת", admin_id]})
        made = _made(b, "רשות מושבתת")
        assert len(made) == 1
        assert uid not in (made[0].get(dst["id"]) or []), made[0]
        assert made[0].get(dst["id"]) == [admin_id], made[0]
    finally:
        with Session(cityos_main.engine) as db:
            db.query(BoardMember).filter(BoardMember.user_id == uid).delete()
            db.query(User).filter(User.id == uid).delete()
            db.commit()


def test_an_id_the_target_board_cannot_name_is_dropped_and_the_item_still_made(client, admin_id):
    a, b, src, dst, _ = _setup(client, admin_id, "gone")
    _fire(client, a, admin_id, "רשות חסרה", {src["id"]: [987654321]})
    made = _made(b, "רשות חסרה")
    assert len(made) == 1, "one unknown person took the whole item back"
    assert not made[0].get(dst["id"]), made[0]


def test_a_rule_that_copies_only_board_columns_needs_no_built_in_ticked(client, admin_id):
    """Ticking «שם נוהל» in "השדות להעתקה" writes a pair into the mapping and
    nothing into `fields`, so the rule must save with `fields` empty."""
    a, b = _board(client, admin_id, "רק עמודות א"), _board(client, admin_id, "רק עמודות ב")
    _add_col(client, a, admin_id, {"type": "connect", "title": "קישור",
                                   "connect": {"board_ids": [b], "multiple": True,
                                               "two_way": True}})
    conn = next(x for x in _cols(client, a) if x["type"] == "connect")
    s = _add_col(client, a, admin_id, {"id": "col_nm_src", "type": "text", "title": "שם נוהל"})
    t = _add_col(client, b, admin_id, {"id": "col_nm_dst", "type": "text", "title": "שם נוהל"})
    grp = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id, "is_active": True,
                          "recipe_id": "status_create_in_group_and_link",
                          "config": {"t_status": "done", "a_connect": conn["id"],
                                     "a_board": b, "a_target_group": grp,
                                     "a_text": "{{item.name}}",
                                     "a_map": [{"from": s["id"], "to": t["id"]}]}})
    assert r.status_code == 200, r.text
    _fire(client, a, admin_id, "נוהל עמודות", {s["id"]: "נוהל 12"})
    made = _made(b, "נוהל עמודות")
    runs = client.get(f"/api/boards/{a}/automations/runs?user_id={admin_id}").json()["runs"]
    assert len(made) == 1 and made[0].get(t["id"]) == "נוהל 12", [(x.get("outcome"), x.get("reason")) for x in runs]


def test_without_a_mapping_the_copy_fields_blank_is_still_required(client, admin_id):
    a, b = _board(client, admin_id, "בלי מיפוי א"), _board(client, admin_id, "בלי מיפוי ב")
    _add_col(client, a, admin_id, {"type": "connect", "title": "קישור",
                                   "connect": {"board_ids": [b], "multiple": True}})
    conn = next(x for x in _cols(client, a) if x["type"] == "connect")
    grp = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id, "is_active": True,
                          "recipe_id": "status_create_in_group_and_link",
                          "config": {"t_status": "done", "a_connect": conn["id"],
                                     "a_board": b, "a_target_group": grp,
                                     "a_text": "x"}})
    assert r.status_code == 400, r.text
    assert "השדות להעתקה" in r.text
