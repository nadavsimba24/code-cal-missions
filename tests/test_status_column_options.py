"""עמודת סטטוס — אוצר מילים נפרד לכל עמודה.

A board admin names and colours the statuses of every status column on its
own (col.options = [{label,color}]), independently of the board-wide status
list that drives the built-in "סטטוס" column.
"""


def _make_board(client, admin_id, name="סטטוסים לעמודה"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _status_col(client, bid, admin_id, title="שלב", options=None):
    col = {"type": "status", "title": title}
    if options is not None:
        col["options"] = options
    r = client.patch(f"/api/boards/{bid}", json={"columns": [col], "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()["columns"][0]


def _cols(client, bid, uid):
    return client.get(f"/api/boards/{bid}?user_id={uid}").json()["columns"]


def test_status_column_keeps_its_own_labels_and_colors(client, admin_id):
    bid = _make_board(client, admin_id)
    opts = [{"label": "טרם החל", "color": "#579bfc"}, {"label": "בביצוע", "color": "#fdab3d"}]
    col = _status_col(client, bid, admin_id, options=opts)
    assert col["options"] == opts
    assert _cols(client, bid, admin_id)[0]["options"] == opts


def test_two_status_columns_are_independent(client, admin_id):
    bid = _make_board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [
        {"type": "status", "title": "שלב תכנון", "options": [{"label": "הוגש", "color": "#00c875"}]},
        {"type": "status", "title": "שלב ביצוע", "options": [{"label": "נדחה", "color": "#e2445c"}]},
    ]})
    a, b = r.json()["columns"]
    assert [o["label"] for o in a["options"]] == ["הוגש"]
    assert [o["label"] for o in b["options"]] == ["נדחה"]


def test_board_statuses_are_untouched_by_a_status_column(client, admin_id):
    """The built-in status column has its own board-wide vocabulary."""
    bid = _make_board(client, admin_id)
    client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "statuses": [
        {"key": "todo", "label": "ממתין", "color": "#c4c4c4"},
        {"key": "done", "label": "אושר", "color": "#00c875"},
    ]})
    _status_col(client, bid, admin_id, options=[{"label": "ממתין", "color": "#000000"}])
    board = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
    assert [s["label"] for s in board["statuses"]] == ["ממתין", "אושר"]
    assert board["statuses"][0]["color"] == "#c4c4c4"


def test_labels_are_trimmed_deduped_and_capped(client, admin_id):
    bid = _make_board(client, admin_id)
    opts = ([{"label": "  כפול  ", "color": "#00c875"}, {"label": "כפול", "color": "#e2445c"},
             {"label": "", "color": "#00c875"}, {"label": "x" * 60, "color": "#00c875"}]
            + [{"label": f"s{i}", "color": "#00c875"} for i in range(30)])
    col = _status_col(client, bid, admin_id, options=opts)
    labels = [o["label"] for o in col["options"]]
    assert labels[0] == "כפול" and labels.count("כפול") == 1
    assert "" not in labels
    assert len(labels[1]) == 40                      # long label truncated
    assert len(labels) == 20                         # STATUS_COL_MAX


def test_bad_color_falls_back_and_empty_options_reset(client, admin_id):
    bid = _make_board(client, admin_id)
    col = _status_col(client, bid, admin_id, options=[{"label": "א", "color": "red"},
                                                      {"label": "ב"}])
    assert [o["color"] for o in col["options"]] == ["#c4c4c4", "#c4c4c4"]
    # no options at all → column falls back to the client defaults
    assert _status_col(client, bid, admin_id, options=[])["options"] is None
    assert _status_col(client, bid, admin_id)["options"] is None


def test_plain_string_options_are_accepted(client, admin_id):
    """A dropdown-shaped options list still yields a usable status vocabulary."""
    bid = _make_board(client, admin_id)
    col = _status_col(client, bid, admin_id, options=["אחד", "שתיים"])
    assert col["options"] == [{"label": "אחד", "color": "#c4c4c4"},
                              {"label": "שתיים", "color": "#c4c4c4"}]


def test_dropdown_options_stay_plain_strings(client, admin_id):
    bid = _make_board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [
        {"type": "dropdown", "title": "רשימה", "options": ["א", "ב"]}]})
    assert r.json()["columns"][0]["options"] == ["א", "ב"]


def test_non_admin_cannot_edit_status_column_options(client, admin_id, member_id):
    col = _status_col(client, 1, admin_id, title="שלב בדיקה",
                      options=[{"label": "פתוח", "color": "#00c875"}])
    r = client.patch("/api/boards/1", json={"user_id": member_id, "columns": [
        {**col, "options": [{"label": "שונה", "color": "#e2445c"}]}]})
    assert r.status_code == 403
    assert _cols(client, 1, admin_id)[0]["options"][0]["label"] == "פתוח"


def test_cell_value_carries_the_chosen_label_and_color(client, admin_id):
    bid = _make_board(client, admin_id)
    col = _status_col(client, bid, admin_id, options=[{"label": "בבדיקה", "color": "#579bfc"}])
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט", "user_id": admin_id}).json()["id"]
    val = {"label": "בבדיקה", "color": "#579bfc"}
    client.patch(f"/api/tasks/{tid}", json={"user_id": admin_id, "custom_fields": {col["id"]: val}})
    task = [t for t in client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["tasks"] if t["id"] == tid][0]
    assert task["custom_fields"][col["id"]] == val
