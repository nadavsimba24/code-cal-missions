"""Board-level activity: the same audit records the item log reads, gathered
across every item on the board."""
from sqlalchemy.orm import Session
from conftest import join_primary_env
import main as cityos_main
from models import EnvironmentMember, Board


def _mk_board(client, admin_id, name="לוח לוגים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _mk_item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _outsider(client, admin_id, email):
    """A user who exists and is in the workspace, but not on the board."""
    for u in client.get("/api/users").json():
        if u.get("email") == email:
            uid = u["id"]; break
    else:
        uid = client.post("/api/users", json={"actor_id": admin_id, "name": "זר ללוג",
                                              "email": email, "role": "member"}).json()["id"]
    client.delete(f"/api/boards/1/members/{uid}?actor_id={admin_id}")
    # Outside the BOARD is what these tests mean. Being inside the workspace is
    # now a row somebody writes, and without it no board in it could invite
    # them at all — which is a different test than this file's.
    join_primary_env(client, uid)
    return uid


def test_it_gathers_changes_from_every_item(client, admin_id):
    bid = _mk_board(client, admin_id)
    a = _mk_item(client, bid, admin_id, "פריט א")
    b = _mk_item(client, bid, admin_id, "פריט ב")
    client.patch(f"/api/tasks/{a}?user_id={admin_id}", json={"title": "פריט א מעודכן"})
    client.patch(f"/api/tasks/{b}?user_id={admin_id}", json={"status": "done"})

    acts = client.get(f"/api/boards/{bid}/activity").json()["activity"]
    ids = {x["task_id"] for x in acts}
    assert a in ids and b in ids, "the board log missed one of its items"
    assert len(acts) >= 4, "creations and updates should both be recorded"


def test_each_line_names_the_item_it_belongs_to(client, admin_id):
    """At board level 'changed status' is meaningless without saying of what."""
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id, "פריט מזוהה")
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": "done"})
    acts = client.get(f"/api/boards/{bid}/activity").json()["activity"]
    assert all(x.get("task_title") for x in acts)
    assert any(x["task_title"] == "פריט מזוהה" for x in acts)


def test_newest_first(client, admin_id):
    bid = _mk_board(client, admin_id)
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"title": "אחרי"})
    acts = client.get(f"/api/boards/{bid}/activity").json()["activity"]
    stamps = [x["created_at"] for x in acts if x["created_at"]]
    assert stamps == sorted(stamps, reverse=True)


def test_filtering_by_user_actually_filters(client, admin_id, guinea_id):
    """The item endpoint bound this to the caller, so it always showed only your
    own changes. Board level must honour the query parameter."""
    bid = _mk_board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={guinea_id}", json={"title": "שינוי של גינאה"})

    mine = client.get(f"/api/boards/{bid}/activity?user_id={admin_id}").json()["activity"]
    theirs = client.get(f"/api/boards/{bid}/activity?user_id={guinea_id}").json()["activity"]
    assert all(x["user_id"] == admin_id for x in mine)
    assert all(x["user_id"] == guinea_id for x in theirs)
    assert theirs, "the other user's change is missing"
    assert len(theirs) < len(client.get(f"/api/boards/{bid}/activity").json()["activity"])


def test_the_item_log_now_honours_its_filter_too(client, admin_id, guinea_id):
    bid = _mk_board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={guinea_id}", json={"title": "שונה"})
    unfiltered = client.get(f"/api/tasks/{tid}/activity",
                            headers={"X-CityOS-User": str(admin_id)}).json()["activity"]
    assert {x["user_id"] for x in unfiltered} >= {admin_id, guinea_id}, \
        "the unfiltered item log should show everyone's changes"


def test_a_non_member_cannot_read_the_log(client, admin_id):
    bid = _mk_board(client, admin_id)
    _mk_item(client, bid, admin_id)
    out = _outsider(client, admin_id, "log.outsider@cityos.test")
    assert client.get(f"/api/boards/{bid}/activity?user_id={out}",
                      headers={"X-CityOS-User": str(out)}).status_code == 403


def test_a_public_board_viewer_may_read_it(client, admin_id):
    """Seeing the board means seeing its history — the same gate as the board."""
    bid = _mk_board(client, admin_id)
    _mk_item(client, bid, admin_id)
    out = _outsider(client, admin_id, "log.viewer@cityos.test")
    with Session(cityos_main.engine) as db:
        env_id = db.query(Board).filter(Board.id == bid).first().environment_id
        if not db.query(EnvironmentMember).filter(
                EnvironmentMember.environment_id == env_id,
                EnvironmentMember.user_id == out).first():
            db.add(EnvironmentMember(environment_id=env_id, user_id=out, role="member"))
            db.commit()
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "visibility": "public"})
    r = client.get(f"/api/boards/{bid}/activity", headers={"X-CityOS-User": str(out)})
    assert r.status_code == 200


def test_export_returns_a_csv_with_the_item_column(client, admin_id):
    bid = _mk_board(client, admin_id)
    _mk_item(client, bid, admin_id, "פריט ליצוא")
    r = client.get(f"/api/boards/{bid}/activity/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    body = r.content.decode("utf-8-sig")
    assert "פריט" in body.splitlines()[0], "the CSV header should name the item column"
    assert "פריט ליצוא" in body


def test_the_filter_offers_board_people_only(client, admin_id, guinea_id):
    """A workspace is bigger than a board. Listing everyone fills the menu with
    names that can only ever return an empty list."""
    bid = _mk_board(client, admin_id, "לוח לסינון")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    stranger = _outsider(client, admin_id, "log.stranger@cityos.test")
    _mk_item(client, bid, admin_id)

    people = client.get(f"/api/boards/{bid}/activity").json()["people"]
    ids = {p["id"] for p in people}
    assert guinea_id in ids, "an invited member must be offered"
    assert stranger not in ids, "someone with no access to the board was offered"
    assert all(p.get("name") for p in people)


def test_someone_removed_from_the_board_is_still_filterable(client, admin_id):
    """Their work is still in the history — dropping them from the filter would
    leave rows nobody can filter to."""
    bid = _mk_board(client, admin_id, "לוח עוזבים")
    uid = _outsider(client, admin_id, "log.left@cityos.test")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": uid, "role": "editor"})
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={uid}", json={"title": "שיניתי לפני שעזבתי"})
    client.delete(f"/api/boards/{bid}/members/{uid}?actor_id={admin_id}")

    d = client.get(f"/api/boards/{bid}/activity",
                   headers={"X-CityOS-User": str(admin_id)}).json()
    assert uid in {p["id"] for p in d["people"]}, "an author of existing rows vanished from the filter"
    assert any(a["user_id"] == uid for a in d["activity"])
    # sign as the admin: the suite promotes ?user_id= into the auth header, and
    # this user no longer has access to the board they are being filtered by
    only = client.get(f"/api/boards/{bid}/activity?user_id={uid}",
                      headers={"X-CityOS-User": str(admin_id)}).json()["activity"]
    assert only and all(a["user_id"] == uid for a in only)


def test_internal_status_bookkeeping_never_reaches_the_log(client, admin_id):
    """A board-defined status stores its key, label, colour and an unset flag in
    custom_fields. Changing one status writes four audit rows of raw JSON; a
    person reading a log wants one line about the status, not four about its
    colour."""
    bid = _mk_board(client, admin_id, "לוח רעש")
    tid = _mk_item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                 json={"custom_fields": {"status_key": "x_1", "status_label": "בדיקה",
                                         "status_color": "#e2445c", "status_unset": None}})
    fields = {a.get("field") for a in client.get(f"/api/boards/{bid}/activity").json()["activity"]}
    for noisy in ("col:status_key", "col:status_label", "col:status_color", "col:status_unset"):
        assert noisy not in fields, f"{noisy} leaked into the board log"
    item_fields = {a.get("field") for a in
                   client.get(f"/api/tasks/{tid}/activity",
                              headers={"X-CityOS-User": str(admin_id)}).json()["activity"]}
    assert "col:status_key" not in item_fields, "the item log still shows bookkeeping"
