"""One numbers dashboard, from creation to the item it was made of.

DASH-29.1 asks for the whole process tested together — "יצירה, הרשאות,
מקורות, מיפוי, ווידג׳טים, סינון, פירוט, עריכת פריט, פריסה, שמירה ופתיחה
מחדש" — and that is what this is: a single story, in order, with the numbers
checked at every step rather than only at the end.

Two things it is here to catch that the per-story tests cannot. The first is
drift between steps: a measure that is right when it is saved and wrong after
the layout moves, or a drill-down that stops agreeing with the figure once a
filter is added. The second is the state after a reload — "שמירה ופתיחה
מחדש" — because a dashboard is a thing people come back to, and a
configuration that only works in the session that built it has not been
saved at all.
"""
from conftest import join_primary_env

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    bid = client.post("/api/boards",
                      json={"name": name, "user_id": admin_id}).json()["id"]
    for t in client.get(f"/api/boards/{bid}").json()["tasks"]:
        client.delete(f"/api/tasks/{t['id']}", headers=AS(admin_id))
    return bid


def _add_col(client, bid, admin_id, col):
    cols = client.get(f"/api/boards/{bid}").json()["columns"] + [col]
    client.patch(f"/api/boards/{bid}", json={"actor_id": admin_id, "columns": cols})
    return client.get(f"/api/boards/{bid}").json()["columns"][-1]


def _item(client, bid, admin_id, title, cf=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id}).json()["id"]
    if cf:
        client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": cf})
    return tid


def test_a_numbers_dashboard_end_to_end(client, admin_id, guinea_id):
    env = next(e["id"] for e in client.get("/api/environments",
                                           headers=AS(admin_id)).json()["environments"]
               if e.get("is_primary"))
    join_primary_env(client, guinea_id)

    # ── 1. two boards of source data, one of which the second reader may open ──
    north = _board(client, admin_id, "תקציב צפון")
    south = _board(client, admin_id, "תקציב דרום")
    client.post(f"/api/boards/{north}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "viewer"})
    cn = _add_col(client, north, admin_id,
                  {"type": "number", "title": "תקציב", "number": {"unit": "₪"}})
    cs = _add_col(client, south, admin_id,
                  {"type": "number", "title": "תקציב", "number": {"unit": "₪"}})
    for v in (100, 200, None):
        _item(client, north, admin_id, f"צפון {v}", cf=({} if v is None else {cn["id"]: v}))
    for v in (300,):
        _item(client, south, admin_id, f"דרום {v}", cf={cs["id"]: v})

    # ── 2. the dashboard, and the boards it is allowed to read ──
    d = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env, "name": "תקציב עירוני",
                          "visibility": "private",
                          "sources": [{"board_id": north, "groups": None},
                                      {"board_id": south, "groups": None}]}).json()
    assert d["can_edit"] is True and d["widgets"] == []

    # ── 3. the mapping, proposed by name and type, then approved ──
    prop = client.post(f"/api/dashboards/{d['id']}/mapping-proposal", headers=AS(admin_id),
                       json={"reference_board_id": north,
                             "fields": {"amount": cn["id"]}}).json()
    assert prop["proposals"][str(south)]["amount"]["column_id"] == cs["id"]
    mapping = {str(north): {"amount": cn["id"]}, str(south): {"amount": cs["id"]}}

    # ── 4. a preview first — which must not create anything ──
    body = {"type": "numbers", "title": "סך התקציב", "mapping": mapping,
            "metrics": [{"key": "m", "field": "amount", "calc": "sum",
                         "format": "currency", "precision": 0}]}
    prev = client.post(f"/api/dashboards/{d['id']}/widgets/preview",
                       headers=AS(admin_id), json=body).json()
    assert prev["metrics"][0]["result"] == 600 and prev["widget_id"] is None
    assert client.get(f"/api/dashboards/{d['id']}",
                      headers=AS(admin_id)).json()["widgets"] == []

    # ── 5. saved, and now it is a widget ──
    made = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                       json={**body, "config_version": d["config_version"]}).json()
    w = made["widget"]
    ver = made["config_version"]
    got = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/compute",
                      headers=AS(admin_id), json={}).json()
    m = got["metrics"][0]
    assert m["result"] == 600 and m["unit"] == "₪" and m["format"] == "currency"
    assert m["records"] == 4 and m["values"] == 3     # one blank, counted as a record

    # ── 6. a second measure, counting, and the ceiling still some way off ──
    cnt = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                      json={"config_version": ver, "type": "numbers",
                            "title": "כמה סעיפים",
                            "metrics": [{"key": "c", "calc": "count"}]}).json()
    ver = cnt["config_version"]
    assert client.post(f"/api/dashboards/{d['id']}/widgets/{cnt['widget']['id']}/compute",
                       headers=AS(admin_id), json={}).json()["metrics"][0]["result"] == 4

    # ── 7. the drill-down agrees with the figure, and pages ──
    page = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/records",
                       headers=AS(admin_id), json={"limit": 2}).json()
    assert page["records"] == 4 and page["result"] == 600
    assert len(page["rows"]) == 2 and page["has_more"] is True
    rest = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/records",
                       headers=AS(admin_id), json={"limit": 50, "offset": 2}).json()
    rows = page["rows"] + rest["rows"]
    assert len(rows) == 4
    blank = [r for r in rows if r["value_state"] == "empty"]
    assert len(blank) == 1 and blank[0]["empty_handling"] == "לא משתתפת בחישוב"
    assert {r["board_name"] for r in rows} == {"תקציב צפון", "תקציב דרום"}

    # ── 8. the item behind a row opens, by the item's own permission ──
    one = rows[0]
    assert one["my_perm"] in ("edit", "delete")
    item = client.get(f"/api/tasks/{one['id']}", headers=AS(admin_id))
    assert item.status_code == 200 and item.json()["title"] == one["title"]

    # ── 9. a visitor's temporary filter narrows their view and nobody else's ──
    temp = {"adv": {"type": "group", "operator": "and", "rules": [
        {"type": "rule", "field": "amount", "operator": "gt", "value": 150}]}}
    narrowed = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/compute",
                           headers=AS(admin_id), json={"temp_filter": temp}).json()
    assert narrowed["metrics"][0]["result"] == 500      # 200 + 300
    assert client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/compute",
                       headers=AS(admin_id), json={}).json()["metrics"][0]["result"] == 600

    # ── 10. the second reader sees the dashboard only once invited, and then
    #        sees a blocked widget, because south is not theirs ──
    assert client.get(f"/api/dashboards/{d['id']}", headers=AS(guinea_id)).status_code == 404
    client.post(f"/api/dashboards/{d['id']}/members", headers=AS(admin_id),
                json={"user_id": guinea_id, "role": "viewer"})
    theirs = client.get(f"/api/dashboards/{d['id']}", headers=AS(guinea_id)).json()
    assert theirs["can_edit"] is False
    assert [s["board_id"] for s in theirs["sources"]] == [north]
    assert theirs["sources_hidden"] == 1
    blocked = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/compute",
                          headers=AS(guinea_id), json={}).json()
    assert blocked["state"] == "blocked" and blocked["metrics"] == []
    assert "records" not in blocked
    drill = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/records",
                        headers=AS(guinea_id), json={}).json()
    assert drill["state"] == "blocked" and drill["rows"] == [] and drill["records"] is None

    # ── 11. the layout is saved explicitly, and the reading order with it ──
    moved = client.patch(f"/api/dashboards/{d['id']}/widgets/{cnt['widget']['id']}",
                         headers=AS(admin_id),
                         json={"config_version": ver, "position": 0}).json()
    ver = moved["config_version"]
    laid = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                        json={"config_version": ver,
                              "layout": {str(w["id"]): {"span": 2}}}).json()
    ver = laid["config_version"]

    # ── 12. a stale save is refused rather than silently winning ──
    stale = client.patch(f"/api/dashboards/{d['id']}", headers=AS(admin_id),
                         json={"config_version": ver - 1, "name": "לא אמור לעבור"})
    assert stale.status_code == 409
    assert stale.json()["detail"]["config_version"] == ver

    # ── 13. reopened, everything is where it was left ──
    again = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()
    assert again["name"] == "תקציב עירוני"
    assert again["layout"] == {str(w["id"]): {"span": 2}}
    order = [x["id"] for x in sorted(again["widgets"], key=lambda x: x["position"])]
    assert order[0] == cnt["widget"]["id"]
    assert again["watch_boards"] == sorted([north, south])
    still = client.post(f"/api/dashboards/{d['id']}/widgets/{w['id']}/compute",
                        headers=AS(admin_id), json={}).json()
    assert still["metrics"][0]["result"] == 600
    assert still["can_fix"] is True

    # ── 14. and a source removed says what it would break before it breaks it ──
    impact = client.get(f"/api/dashboards/{d['id']}/sources/{south}/impact",
                        headers=AS(admin_id)).json()
    assert impact["sources_left"] == 1
    assert {x["verdict"] for x in impact["widgets"]} == {"ok"}
    assert len(client.get(f"/api/dashboards/{d['id']}",
                          headers=AS(admin_id)).json()["sources"]) == 2


def test_moving_a_widget_leaves_no_two_claiming_one_place(client, admin_id):
    """The reading order IS the mobile column (R08, DASH-19.3), so a tie is
    not a cosmetic wobble on the desktop grid — it is a phone showing a
    different order from the one somebody saved. Writing one position and
    leaving the rest is how the tie happens; the list is re-packed instead."""
    env = next(e["id"] for e in client.get("/api/environments",
                                           headers=AS(admin_id)).json()["environments"]
               if e.get("is_primary"))
    bid = _board(client, admin_id, "סדר קריאה")
    d = client.post("/api/dashboards", headers=AS(admin_id),
                    json={"environment_id": env, "name": "סדר",
                          "sources": [{"board_id": bid, "groups": None}]}).json()
    ver, ids = d["config_version"], []
    for i in range(4):
        out = client.post(f"/api/dashboards/{d['id']}/widgets", headers=AS(admin_id),
                          json={"config_version": ver, "type": "numbers",
                                "title": f"מדד {i}",
                                "metrics": [{"key": "m", "calc": "count"}]}).json()
        ver = out["config_version"]; ids.append(out["widget"]["id"])
    last = client.patch(f"/api/dashboards/{d['id']}/widgets/{ids[3]}", headers=AS(admin_id),
                        json={"config_version": ver, "position": 0}).json()
    ws = client.get(f"/api/dashboards/{d['id']}", headers=AS(admin_id)).json()["widgets"]
    positions = sorted(x["position"] for x in ws)
    assert positions == [0, 1, 2, 3], f"ties or gaps in the reading order: {positions}"
    order = [x["id"] for x in sorted(ws, key=lambda x: x["position"])]
    assert order == [ids[3], ids[0], ids[1], ids[2]]
