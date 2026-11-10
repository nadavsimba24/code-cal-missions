"""סטטוס שיש בו שימוש אינו נמחק — לא בלוח, ולא בעמודת סטטוס.

A status is a word a board agreed on, and an item wearing it points at that
word. Removing it from the vocabulary while items still wear it leaves cells
holding a value the board no longer offers: the grid draws the label it
cached, the picker does not list it, the filter cannot ask for it, and nothing
on screen explains why the three disagree.

What is pinned here is that the removal is REFUSED — 409, naming the status
and how many items wear it — and that the refusal is exact:

  * a rename keeps the key, so it is not a deletion and is not refused;
  * תקוע and הקפאה both store on_hold, so the guard counts the vocabulary key
    an item SHOWS and not the enum underneath it, or one of the two would be
    protected by the other's items;
  * an item in the recycle bin wears nothing — the number in the refusal has
    to be a number the admin can go and look at;
  * a refused save writes NOTHING: not the statuses, and not the suspension of
    the automations that a real deletion would carry out.
"""
import pathlib
import shutil
import subprocess

import pytest

import main as cityos_main

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "status_in_use_is_not_deletable.mjs"


def _board(client, admin_id, name="לוח מחיקת סטטוס"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _set(client, bid, admin_id, statuses):
    return client.patch(f"/api/boards/{bid}",
                        json={"user_id": admin_id, "statuses": statuses})


def _cols(client, bid, admin_id, title, labels):
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [
        {"type": "status", "title": title,
         "options": [{"label": x, "color": "#0073ea"} for x in labels]}]})
    assert r.status_code == 200, r.text
    return r.json()["columns"][0]


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _wear(client, tid, admin_id, entry):
    """Put a board status on an item the way the board's own picker does."""
    r = client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={
        "status": entry["base"],
        "custom_fields": {"status_key": entry["key"], "status_label": entry["label"],
                          "status_color": entry["color"], "status_unset": None}})
    assert r.status_code == 200, r.text


BASE = [{"key": "todo", "label": "לביצוע", "color": "#c4c4c4"},
        {"key": "in_progress", "label": "בתהליך", "color": "#fdab3d"},
        {"key": "done", "label": "הושלם", "color": "#00c875"}]


def _by_key(statuses, key):
    return next(s for s in statuses if s["key"] == key)


# ── הסטטוסים של הלוח ──────────────────────────────────────────────────────

def test_a_status_nobody_wears_is_removed_without_argument(client, admin_id):
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE).json()["statuses"]
    tid = _item(client, bid, admin_id)
    _wear(client, tid, admin_id, _by_key(out, "done"))
    r = _set(client, bid, admin_id, [s for s in BASE if s["key"] != "in_progress"])
    assert r.status_code == 200, r.text
    assert [s["key"] for s in r.json()["statuses"]] == ["todo", "done"]


def test_a_status_an_item_wears_cannot_be_removed(client, admin_id):
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE).json()["statuses"]
    for i in range(2):
        _wear(client, _item(client, bid, admin_id, f"פריט {i}"), admin_id,
              _by_key(out, "done"))
    r = _set(client, bid, admin_id, [s for s in BASE if s["key"] != "done"])
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert "שימוש" in d["message"]
    assert d["statuses"] == [{"key": "done", "label": "הושלם", "items": 2}]
    # and the board still offers it
    got = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["statuses"]
    assert [s["key"] for s in got] == ["todo", "in_progress", "done"]


def test_moving_the_items_away_opens_the_deletion(client, admin_id):
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE).json()["statuses"]
    tid = _item(client, bid, admin_id)
    _wear(client, tid, admin_id, _by_key(out, "done"))
    assert _set(client, bid, admin_id,
                [s for s in BASE if s["key"] != "done"]).status_code == 409
    _wear(client, tid, admin_id, _by_key(out, "in_progress"))
    r = _set(client, bid, admin_id, [s for s in BASE if s["key"] != "done"])
    assert r.status_code == 200, r.text


def test_a_rename_is_not_a_deletion(client, admin_id):
    """"שינוי שם רכיב — המשך לפי מזהה קבוע". The key survives, so nothing was
    removed and there is nothing to refuse — even for a status every item on
    the board is wearing."""
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE).json()["statuses"]
    _wear(client, _item(client, bid, admin_id), admin_id, _by_key(out, "done"))
    renamed = [dict(s, label="סגור" if s["key"] == "done" else s["label"]) for s in BASE]
    r = _set(client, bid, admin_id, renamed)
    assert r.status_code == 200, r.text
    assert _by_key(r.json()["statuses"], "done")["label"] == "סגור"


def test_two_statuses_on_one_enum_are_guarded_apart(client, admin_id):
    """תקוע and הקפאה both store on_hold. An item wearing הקפאה must not keep
    תקוע alive, and must not be counted twice."""
    bid = _board(client, admin_id)
    vocab = BASE + [{"label": "הקפאה", "color": "#fd5ac3", "base": "on_hold"},
                    {"key": "on_hold", "label": "תקוע", "color": "#e2445c"}]
    out = _set(client, bid, admin_id, vocab).json()["statuses"]
    frozen = next(s for s in out if s["label"] == "הקפאה")
    assert frozen["key"].startswith("x_") and frozen["base"] == "on_hold"
    _wear(client, _item(client, bid, admin_id), admin_id, frozen)
    # תקוע is worn by nobody, even though the item underneath it says on_hold
    keep = [s for s in out if s["key"] != "on_hold"]
    assert _set(client, bid, admin_id, keep).status_code == 200
    # הקפאה is worn, and is refused
    r = _set(client, bid, admin_id, [s for s in keep if s["key"] != frozen["key"]])
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["statuses"][0]["items"] == 1


def test_an_item_with_no_status_chosen_holds_nothing(client, admin_id):
    """"טרם הוגדר" is the absence of a choice, not one of the words — an item
    nobody has set must not keep whichever status it defaulted to alive."""
    bid = _board(client, admin_id)
    _set(client, bid, admin_id, BASE)
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                 json={"status": "done", "custom_fields": {"status_unset": True}})
    r = _set(client, bid, admin_id, [s for s in BASE if s["key"] != "done"])
    assert r.status_code == 200, r.text


def test_an_item_in_the_recycle_bin_wears_nothing(client, admin_id):
    """The number in the refusal has to be one the admin can go and look at.
    A deleted item is on no screen, so it holds no status open."""
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE).json()["statuses"]
    tid = _item(client, bid, admin_id)
    _wear(client, tid, admin_id, _by_key(out, "done"))
    assert client.delete(f"/api/tasks/{tid}?user_id={admin_id}").status_code in (200, 204)
    r = _set(client, bid, admin_id, [s for s in BASE if s["key"] != "done"])
    assert r.status_code == 200, r.text


def test_a_refused_save_changes_nothing_at_all(client, admin_id):
    """The gate stands in front of the write AND in front of the suspension of
    the dependents: a save that did not happen must not leave a stopped
    automation or a renamed status behind it."""
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE).json()["statuses"]
    _wear(client, _item(client, bid, admin_id), admin_id, _by_key(out, "done"))
    # one request that renames a status, recolours another and drops a third
    attempt = [dict(BASE[0], label="חדש"), dict(BASE[1], color="#00c2b8")]
    assert _set(client, bid, admin_id, attempt).status_code == 409
    got = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["statuses"]
    assert got == out


# ── הסטטוסים של עמודת סטטוס ───────────────────────────────────────────────

def test_an_option_an_item_wears_cannot_be_removed(client, admin_id):
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, "שלב", ["תכנון", "ביצוע", "מסירה"])
    opt = next(o for o in col["options"] if o["label"] == "ביצוע")
    tid = _item(client, bid, admin_id)
    assert client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={
        "custom_fields": {col["id"]: {"id": opt["id"], "label": opt["label"],
                                      "color": opt["color"]}}}).status_code == 200
    short = dict(col, options=[o for o in col["options"] if o["id"] != opt["id"]])
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [short]})
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["statuses"] == [{"col_id": col["id"], "column": "שלב",
                              "key": opt["id"], "label": "ביצוע", "items": 1}]
    got = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"][0]
    assert [o["label"] for o in got["options"]] == ["תכנון", "ביצוע", "מסירה"]


def test_a_cell_written_as_a_bare_label_counts_too(client, admin_id):
    """The grid writes the label into the cell and a form answer writes the
    whole option. Both are in the data, so both have to hold the option open —
    counting only one shape is a deletion that looks guarded and is not."""
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, "שלב", ["תכנון", "ביצוע"])
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                 json={"custom_fields": {col["id"]: "ביצוע"}})
    short = dict(col, options=[o for o in col["options"] if o["label"] != "ביצוע"])
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [short]})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["statuses"][0]["label"] == "ביצוע"


def test_an_option_nobody_wears_is_removed(client, admin_id):
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, "שלב", ["תכנון", "ביצוע", "מסירה"])
    opt = next(o for o in col["options"] if o["label"] == "ביצוע")
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                 json={"custom_fields": {col["id"]: {"id": opt["id"], "label": "ביצוע",
                                                     "color": opt["color"]}}})
    short = dict(col, options=[o for o in col["options"] if o["label"] != "מסירה"])
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [short]})
    assert r.status_code == 200, r.text
    assert [o["label"] for o in r.json()["columns"][0]["options"]] == ["תכנון", "ביצוע"]


def test_renaming_an_option_keeps_its_id_and_is_allowed(client, admin_id):
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, "שלב", ["תכנון", "ביצוע"])
    opt = next(o for o in col["options"] if o["label"] == "ביצוע")
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                 json={"custom_fields": {col["id"]: {"id": opt["id"], "label": "ביצוע",
                                                     "color": opt["color"]}}})
    renamed = dict(col, options=[dict(o, label="בביצוע" if o["id"] == opt["id"] else o["label"])
                                 for o in col["options"]])
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": [renamed]})
    assert r.status_code == 200, r.text


def test_deleting_the_whole_column_is_a_different_act(client, admin_id):
    """The guard is about a word going missing out of a vocabulary the column
    still has. Dropping the column takes the vocabulary with it, and has its
    own warning and its own way back — it must not be blocked here."""
    bid = _board(client, admin_id)
    col = _cols(client, bid, admin_id, "שלב", ["תכנון", "ביצוע"])
    opt = col["options"][0]
    tid = _item(client, bid, admin_id)
    client.patch(f"/api/tasks/{tid}?user_id={admin_id}",
                 json={"custom_fields": {col["id"]: {"id": opt["id"], "label": opt["label"],
                                                     "color": opt["color"]}}})
    r = client.patch(f"/api/boards/{bid}", json={"user_id": admin_id, "columns": []})
    assert r.status_code == 200, r.text


# ── מה שהמסך שואל לפני שהוא מצייר פח אשפה ─────────────────────────────────

def test_the_usage_endpoint_counts_the_board_and_its_columns(client, admin_id):
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE).json()["statuses"]
    col = _cols(client, bid, admin_id, "שלב", ["תכנון", "ביצוע"])
    opt = next(o for o in col["options"] if o["label"] == "תכנון")
    for i in range(3):
        tid = _item(client, bid, admin_id, f"פריט {i}")
        _wear(client, tid, admin_id, _by_key(out, "done"))
        if i < 2:
            client.patch(f"/api/tasks/{tid}?user_id={admin_id}", json={
                "custom_fields": {col["id"]: {"id": opt["id"], "label": opt["label"],
                                              "color": opt["color"]}}})
    u = client.get(f"/api/boards/{bid}/status-usage?user_id={admin_id}")
    assert u.status_code == 200, u.text
    body = u.json()
    assert body["statuses"]["done"] == 3
    assert body["statuses"].get("in_progress", 0) == 0
    assert body["columns"][col["id"]][opt["id"]] == 2


def test_a_sub_item_wears_a_status_as_much_as_an_item_does(client, admin_id):
    bid = _board(client, admin_id)
    out = _set(client, bid, admin_id, BASE).json()["statuses"]
    parent = _item(client, bid, admin_id, "אב")
    sub = client.post("/api/tasks", json={"board_id": bid, "title": "תת־פריט",
                                          "parent_id": parent, "user_id": admin_id}).json()["id"]
    _wear(client, sub, admin_id, _by_key(out, "done"))
    assert client.get(f"/api/boards/{bid}/status-usage?user_id={admin_id}"
                      ).json()["statuses"]["done"] == 1
    r = _set(client, bid, admin_id, [s for s in BASE if s["key"] != "done"])
    assert r.status_code == 409, r.text


def test_the_counts_are_not_open_to_a_stranger(client, admin_id, guinea_id):
    """Membership-based access, like everything else a board answers."""
    bid = _board(client, admin_id)
    assert client.get(f"/api/boards/{bid}/status-usage?user_id={guinea_id}").status_code == 403


def test_the_editor_puts_the_bin_out_of_reach_before_the_refusal():
    """The 409 is the authority and a bad place to learn the rule: by the time
    it arrives, three statuses have been renamed and a fourth recoloured, and
    the refusal throws all of it back. The editor asks the counts first, draws
    them, and disables the bin — see the harness."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
