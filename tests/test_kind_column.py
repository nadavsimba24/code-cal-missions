"""עמודת "סוג" — משימה / באג / שיפור.

A status-shaped column type that ships with its own three values, so it goes
through the same {label,color} validation as a status column and can be
renamed or recoloured per board from the same editor.
"""


def _board(client, admin_id, name="לוח סוגים"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid, admin_id, cols):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": cols})
    assert r.status_code == 200, r.text
    return r.json()["columns"]


KIND = [{"label": "משימה", "color": "#0073ea"},
        {"label": "באג", "color": "#e2445c"},
        {"label": "שיפור", "color": "#a25ddc"}]


def test_the_column_type_is_accepted_with_its_three_values(client, admin_id):
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, [{"type": "item_kind", "title": "סוג", "options": KIND}])[0]
    assert col["type"] == "item_kind" and col["title"] == "סוג"
    assert [o["label"] for o in col["options"]] == ["משימה", "באג", "שיפור"]
    assert [o["color"] for o in col["options"]] == ["#0073ea", "#e2445c", "#a25ddc"]


def test_values_go_through_the_same_validation_as_a_status_column(client, admin_id):
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, [{"type": "item_kind", "title": "סוג", "options": [
        {"label": "  משימה  ", "color": "#0073ea"},     # trimmed
        {"label": "משימה", "color": "#e2445c"},          # duplicate, dropped
        {"label": "", "color": "#00c875"},               # blank, dropped
        {"label": "באג", "color": "not-a-colour"},       # falls back
    ]}])[0]
    assert [o["label"] for o in col["options"]] == ["משימה", "באג"]
    assert col["options"][1]["color"] == "#c4c4c4"


def test_the_values_can_be_renamed_per_board(client, admin_id):
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, [{"type": "item_kind", "title": "סוג", "options": KIND}])[0]
    renamed = _cols(client, bid, admin_id, [{**col, "options": [
        {"label": "פיצ'ר", "color": "#00c875"}, {"label": "תקלה", "color": "#e2445c"}]}])[0]
    assert [o["label"] for o in renamed["options"]] == ["פיצ'ר", "תקלה"]


def test_a_cell_stores_the_chosen_value(client, admin_id):
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, [{"type": "item_kind", "title": "סוג", "options": KIND}])[0]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט",
                                          "user_id": admin_id}).json()["id"]
    val = {"label": "באג", "color": "#e2445c"}
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": {col["id"]: val}})
    task = [t for t in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"]
            if t["id"] == tid][0]
    assert task["custom_fields"][col["id"]] == val


def test_two_kind_columns_keep_separate_vocabularies(client, admin_id):
    bid = _board(client, admin_id)
    cols = _cols(client, bid, admin_id, [
        {"type": "item_kind", "title": "סוג", "options": KIND},
        {"type": "item_kind", "title": "סוג משני", "options": [{"label": "אחר", "color": "#9699a6"}]}])
    assert [o["label"] for o in cols[0]["options"]] == ["משימה", "באג", "שיפור"]
    assert [o["label"] for o in cols[1]["options"]] == ["אחר"]


def test_non_admin_cannot_add_the_column(client, admin_id, member_id):
    bid = _board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": member_id,
                           "columns": [{"type": "item_kind", "title": "סוג"}]})
    assert r.status_code == 403
