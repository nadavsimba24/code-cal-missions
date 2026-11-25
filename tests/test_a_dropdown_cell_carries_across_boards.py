"""A dropdown («רשימה») cell carries across boards through a column mapping.

A dropdown cell is a LIST of words. A mapped value is read straight off the
source cell, so it reached _coerce_cell as ['גבעת שמואל - עיריה'], was str()ed
into "['גבעת שמואל - עיריה']" and looked up among the target column's options,
where no such word is or ever could be. The rule was refused on every firing,
and the refusal took the item it had just created back with it — prod rule 70
(status_create_in_group_and_link), run 1528:

    השדה 'col_f4f40ce7' בלוח היעד אינו יכול לקבל את הערך —
    '['גבעת שמואל - עיריה']' אינו ערך מוכר בעמודה — לא נכתב

People lists and {label,color} status cells were each fixed the same way
before; this pins the third shape. Each word is held to the target's own
vocabulary, a dropdown target keeps the list, and a single-value status
target takes it only when there is exactly one word to take.
"""
from sqlalchemy.orm import Session

import main as cityos_main
from models import Task

OLD = "status_create_in_group_and_link"
PLACE = "גבעת שמואל - עיריה"


def _board(client, admin_id, name):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _cols(client, bid):
    return client.get(f"/api/boards/{bid}").json()["columns"]


def _add_col(client, bid, admin_id, col):
    client.patch(f"/api/boards/{bid}",
                 json={"actor_id": admin_id, "columns": _cols(client, bid) + [col]})
    return col["id"]


def _setup(client, admin_id, tag, dst_options):
    a = _board(client, admin_id, f"מקור רשימה {tag}")
    b = _board(client, admin_id, f"יעד רשימה {tag}")
    src = _add_col(client, a, admin_id,
                   {"id": f"col_dds_{tag}", "type": "dropdown", "title": "רשות",
                    "options": [PLACE, "רמת גן - עיריה"]})
    dst = _add_col(client, b, admin_id,
                   {"id": f"col_ddd_{tag}", "type": "dropdown", "title": "רשות מקומית",
                    "options": dst_options})
    client.patch(f"/api/boards/{a}",
                 json={"actor_id": admin_id,
                       "columns": _cols(client, a) + [
                           {"type": "connect", "title": "קישור",
                            "connect": {"board_ids": [b], "multiple": True,
                                        "two_way": True}}]})
    link = next(x for x in _cols(client, a) if x["type"] == "connect")
    grp = client.get(f"/api/boards/{b}").json()["groups"][0]["id"]
    r = client.post(f"/api/boards/{a}/automations",
                    json={"actor_id": admin_id, "recipe_id": OLD,
                          "config": {"t_status": "done", "a_connect": link["id"],
                                     "a_board": b, "a_target_group": grp,
                                     "a_text": f"יעד {tag}", "a_fields": ["priority"],
                                     "a_map": [{"from": src, "to": dst}]}})
    assert r.status_code == 200, r.text
    return a, b, src, dst


def _fire(client, admin_id, a, src):
    tid = client.post("/api/tasks", json={"board_id": a, "title": "פריט מקור",
                                          "user_id": admin_id,
                                          "custom_fields": {src: [PLACE]}}).json()["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})


def _made(bid, title):
    with Session(cityos_main.engine) as db:
        return db.query(Task).filter(Task.board_id == bid, Task.title == title).all()


def test_a_dropdown_word_the_target_offers_lands_in_the_new_item(client, admin_id):
    a, b, src, dst = _setup(client, admin_id, "dd1", [PLACE, "אחר"])
    _fire(client, admin_id, a, src)
    made = _made(b, "יעד dd1")
    assert len(made) == 1, "the rule took its own item back — the list was refused"
    assert (made[0].custom_fields or {}).get(dst) == [PLACE]


def test_a_word_the_target_does_not_offer_is_named_as_the_word(client, admin_id):
    """Still refused — the target's vocabulary decides — but the history says
    which word, not the Python spelling of a list."""
    a, b, src, _ = _setup(client, admin_id, "dd2", ["אחר"])
    _fire(client, admin_id, a, src)
    assert _made(b, "יעד dd2") == []
    runs = client.get(f"/api/boards/{a}/automations/runs?user_id={admin_id}").json()
    rows = runs.get("runs", runs) if isinstance(runs, dict) else runs
    reasons = " ".join(str(r.get("reason") or "") for r in rows)
    assert f"'{PLACE}' אינו ערך מוכר" in reasons, reasons
    assert "['" not in reasons, reasons


def test_coerce_cell_reads_a_list_word_by_word(client, admin_id):
    bid = _board(client, admin_id, "לוח המרה")
    dd = {"id": "c_dd", "type": "dropdown", "options": [PLACE, "ב"]}
    st = {"id": "c_st", "type": "status",
          "options": [{"label": PLACE, "color": "#00c875"}, {"label": "ב", "color": "#e2445c"}]}
    with Session(cityos_main.engine) as db:
        assert cityos_main._coerce_cell(db, bid, dd, [PLACE, "ב"]) == ([PLACE, "ב"], None)
        assert cityos_main._coerce_cell(db, bid, dd, [{"label": PLACE}]) == ([PLACE], None)
        assert cityos_main._coerce_cell(db, bid, st, [PLACE]) == (PLACE, None)
        got, err = cityos_main._coerce_cell(db, bid, st, [PLACE, "ב"])
        assert got is None and err, "two words cannot become one status"
        got, err = cityos_main._coerce_cell(db, bid, dd, [])
        assert got is None and err
        # a lone word into a dropdown is what set_column has always written
        assert cityos_main._coerce_cell(db, bid, dd, PLACE) == (PLACE, None)
