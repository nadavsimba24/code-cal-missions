"""Cross-board reporting off the links.

Built from the relationships rather than from copied data, and filtered per
reader by the same rule the cells use — a total that includes items the reader
may not see is a leak, because a count is information too.
"""

AS = lambda uid: {"X-CityOS-User": str(uid)}


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _set(client, tid, col_id, ids, uid):
    return client.patch(f"/api/tasks/{tid}?user_id={uid}",
                        json={"custom_fields": {col_id: ids}}, headers=AS(uid))


def _connect(client, admin_id, a, targets, title="קישור", two_way=True):
    cols = _cols(client, a) + [{"type": "connect", "title": title,
                                "connect": {"board_ids": targets, "multiple": True,
                                            "two_way": two_way}}]
    client.patch(f"/api/boards/{a}", json={"actor_id": admin_id, "columns": cols})
    return next(x for x in _cols(client, a) if x["type"] == "connect" and x["title"] == title)


def _report(client, bid, uid):
    return client.get(f"/api/boards/{bid}/links/report", headers=AS(uid)).json()


# ── the report itself ───────────────────────────────────────────────────────

def test_a_board_with_no_connect_column_reports_nothing_to_report(client, admin_id):
    a = _board(client, admin_id, "בלי קישור r0")
    r = _report(client, a, admin_id)
    assert r["connect_columns"] == [] and r["totals"]["links"] == 0


def test_it_counts_the_links_and_the_items_that_have_them(client, admin_id):
    a, b = _board(client, admin_id, "מקור r1"), _board(client, admin_id, "יעד r1")
    c = _connect(client, admin_id, a, [b])
    before = _report(client, a, admin_id)["totals"]         # a new board is not empty
    linked, bare = _item(client, a, admin_id, "מקושר"), _item(client, a, admin_id, "בודד")
    xs = [_item(client, b, admin_id, f"יעד {i}") for i in range(3)]
    _set(client, linked, c["id"], xs, admin_id)
    t = _report(client, a, admin_id)["totals"]
    assert t["links"] == 3 and t["linked_items"] == 1 and t["far_items"] == 3
    assert t["items"] == before["items"] + 2
    assert t["unlinked_items"] == before["unlinked_items"] + 1


def test_it_says_where_the_work_reaches(client, admin_id):
    a = _board(client, admin_id, "מקור r2")
    b1, b2 = _board(client, admin_id, "יעד א r2"), _board(client, admin_id, "יעד ב r2")
    c = _connect(client, admin_id, a, [b1, b2])
    src = _item(client, a, admin_id, "מקור")
    _set(client, src, c["id"],
         [_item(client, b1, admin_id, "א1"), _item(client, b1, admin_id, "א2"),
          _item(client, b2, admin_id, "ב1")], admin_id)
    by = {x["board_name"]: x for x in _report(client, a, admin_id)["by_board"]}
    assert by["יעד א r2"]["links"] == 2 and by["יעד ב r2"]["links"] == 1
    assert [x["board_name"] for x in _report(client, a, admin_id)["by_board"]][0] == "יעד א r2", \
        "the busiest board is not first"


def test_it_breaks_the_far_side_down_by_status(client, admin_id):
    a, b = _board(client, admin_id, "מקור r3"), _board(client, admin_id, "יעד r3")
    c = _connect(client, admin_id, a, [b])
    src = _item(client, a, admin_id, "מקור")
    done1, done2 = _item(client, b, admin_id, "הושלם 1"), _item(client, b, admin_id, "הושלם 2")
    other = _item(client, b, admin_id, "בתהליך")
    for tid, stv in ((done1, "done"), (done2, "done"), (other, "in_progress")):
        client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={"status": stv})
    _set(client, src, c["id"], [done1, done2, other], admin_id)
    by = {x["label"]: x for x in _report(client, a, admin_id)["by_status"]}
    assert by["הושלם"]["items"] == 2 and by["בתהליך"]["items"] == 1
    assert by["הושלם"]["color"], "a status arrived without its colour"


def test_it_counts_per_connect_column(client, admin_id):
    a, b = _board(client, admin_id, "מקור r4"), _board(client, admin_id, "יעד r4")
    c1 = _connect(client, admin_id, a, [b], title="ראשי")
    c2 = _connect(client, admin_id, a, [b], title="משני")
    src = _item(client, a, admin_id, "מקור")
    _set(client, src, c1["id"], [_item(client, b, admin_id, "x1"),
                                 _item(client, b, admin_id, "x2")], admin_id)
    _set(client, src, c2["id"], [_item(client, b, admin_id, "y1")], admin_id)
    by = {x["title"]: x["links"] for x in _report(client, a, admin_id)["connect_columns"]}
    assert by["ראשי"] == 2 and by["משני"] == 1


def test_a_one_way_column_is_reported_too(client, admin_id):
    a, b = _board(client, admin_id, "מקור r5"), _board(client, admin_id, "יעד r5")
    c = _connect(client, admin_id, a, [b], two_way=False)
    src = _item(client, a, admin_id, "מקור")
    _set(client, src, c["id"], [_item(client, b, admin_id, "יעד")], admin_id)
    assert _report(client, a, admin_id)["totals"]["links"] == 1


# ── the totals are the reader's, not the board's ────────────────────────────

def test_the_totals_never_count_what_the_reader_may_not_see(client, admin_id, guinea_id):
    a = _board(client, admin_id, "מקור r6")
    seen_b, closed_b = _board(client, admin_id, "גלוי r6"), _board(client, admin_id, "סגור r6")
    for bid in (a, seen_b):
        client.post(f"/api/boards/{bid}/members",
                    json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    c = _connect(client, admin_id, a, [seen_b, closed_b])
    src = _item(client, a, admin_id, "מקור")
    _set(client, src, c["id"], [_item(client, seen_b, admin_id, "גלוי"),
                                _item(client, closed_b, admin_id, "סוד")], admin_id)
    assert _report(client, a, admin_id)["totals"]["links"] == 2
    mine = _report(client, a, guinea_id)
    assert mine["totals"]["links"] == 1, "the report totalled up a link the reader cannot see"
    assert [x["board_name"] for x in mine["by_board"]] == ["גלוי r6"]


def test_a_non_member_cannot_read_the_report(client, admin_id, guinea_id):
    a, b = _board(client, admin_id, "מקור r7"), _board(client, admin_id, "יעד r7")
    _connect(client, admin_id, a, [b])
    assert client.get(f"/api/boards/{a}/links/report", headers=AS(guinea_id)).status_code == 403


# ── related items, per item ─────────────────────────────────────────────────

def test_related_lists_everything_the_item_connects_to(client, admin_id):
    a, b = _board(client, admin_id, "מקור r8"), _board(client, admin_id, "יעד r8")
    c1 = _connect(client, admin_id, a, [b], title="ראשי")
    c2 = _connect(client, admin_id, a, [b], title="משני")
    src = _item(client, a, admin_id, "מקור")
    _set(client, src, c1["id"], [_item(client, b, admin_id, "x1")], admin_id)
    _set(client, src, c2["id"], [_item(client, b, admin_id, "y1")], admin_id)
    d = client.get(f"/api/tasks/{src}/related", headers=AS(admin_id)).json()
    assert d["total"] == 2
    assert {g["column_title"] for g in d["groups"]} == {"ראשי", "משני"}
    assert all(i["board_name"] == "יעד r8" for g in d["groups"] for i in g["items"])


def test_related_shows_the_reverse_side_as_well(client, admin_id):
    """What points back at it, which is what makes a dependency visible from
    the side that did not create the link."""
    a, b = _board(client, admin_id, "מקור r9"), _board(client, admin_id, "יעד r9")
    c = _connect(client, admin_id, a, [b])
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    d = client.get(f"/api/tasks/{x}/related", headers=AS(admin_id)).json()
    assert d["total"] == 1 and d["groups"][0]["items"][0]["id"] == src


def test_related_marks_a_binned_item(client, admin_id):
    a, b = _board(client, admin_id, "מקור r10"), _board(client, admin_id, "יעד r10")
    c = _connect(client, admin_id, a, [b])
    src, x = _item(client, a, admin_id, "מקור"), _item(client, b, admin_id, "יעד")
    _set(client, src, c["id"], [x], admin_id)
    client.delete(f"/api/tasks/{x}?user_id={admin_id}")
    d = client.get(f"/api/tasks/{src}/related", headers=AS(admin_id)).json()
    assert d["groups"][0]["items"][0]["deleted"] is True


def test_related_hides_what_the_reader_may_not_see(client, admin_id, guinea_id):
    a = _board(client, admin_id, "מקור r11")
    closed_b = _board(client, admin_id, "סגור r11")
    client.post(f"/api/boards/{a}/members",
                json={"actor_id": admin_id, "user_id": guinea_id, "role": "editor"})
    c = _connect(client, admin_id, a, [closed_b])
    src = _item(client, a, admin_id, "מקור")
    _set(client, src, c["id"], [_item(client, closed_b, admin_id, "סוד")], admin_id)
    assert client.get(f"/api/tasks/{src}/related", headers=AS(admin_id)).json()["total"] == 1
    d = client.get(f"/api/tasks/{src}/related", headers=AS(guinea_id)).json()
    assert d["total"] == 0
    assert "סוד" not in client.get(f"/api/tasks/{src}/related", headers=AS(guinea_id)).text


def test_related_refuses_an_item_you_cannot_open(client, admin_id, guinea_id):
    a, b = _board(client, admin_id, "מקור r12"), _board(client, admin_id, "סגור r12")
    x = _item(client, b, admin_id, "סוד")
    assert client.get(f"/api/tasks/{x}/related", headers=AS(guinea_id)).status_code in (403, 404)


def test_setting_a_status_through_the_api_clears_the_not_yet_chosen_flag(client, admin_id):
    """Only the board UI used to clear it, by sending it in custom_fields — so a
    status set through the API, an import or a script left the cell reading
    "טרם הוגדר" while task.status said otherwise. Found by the report, which
    reads the flag to decide what to count."""
    b = _board(client, admin_id, "דגל r13")
    t = _item(client, b, admin_id, "פריט")
    assert (client.get(f"/api/tasks/{t}", headers=AS(admin_id)).json()
            .get("custom_fields") or {}).get("status_unset") is True
    client.patch(f"/api/tasks/{t}?user_id={admin_id}", json={"status": "done"})
    got = client.get(f"/api/tasks/{t}", headers=AS(admin_id)).json()
    assert got["status"] == "done"
    assert (got.get("custom_fields") or {}).get("status_unset") in (None, False)


def test_the_same_for_priority(client, admin_id):
    b = _board(client, admin_id, "דגל r14")
    t = _item(client, b, admin_id, "פריט")
    client.patch(f"/api/tasks/{t}?user_id={admin_id}", json={"priority": "high"})
    got = client.get(f"/api/tasks/{t}", headers=AS(admin_id)).json()
    assert got["priority"] == "high"
    assert (got.get("custom_fields") or {}).get("priority_unset") in (None, False)


def test_a_status_the_board_does_not_know_leaves_the_flag_alone(client, admin_id):
    """The flag must follow the status actually taking, not the attempt."""
    b = _board(client, admin_id, "דגל r15")
    t = _item(client, b, admin_id, "פריט")
    client.patch(f"/api/tasks/{t}?user_id={admin_id}", json={"status": "not_a_status"})
    got = client.get(f"/api/tasks/{t}", headers=AS(admin_id)).json()
    assert (got.get("custom_fields") or {}).get("status_unset") is True


def test_an_unknown_priority_leaves_its_flag_alone_too(client, admin_id):
    b = _board(client, admin_id, "דגל r16")
    t = _item(client, b, admin_id, "פריט")
    client.patch(f"/api/tasks/{t}?user_id={admin_id}", json={"priority": "not_a_priority"})
    got = client.get(f"/api/tasks/{t}", headers=AS(admin_id)).json()
    assert (got.get("custom_fields") or {}).get("priority_unset") is True
