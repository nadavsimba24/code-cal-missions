"""The field mapping of a cross-board rule offers the SOURCE board's columns.

Reported on QA, boards 174 → 173: in "כשסטטוס משתנה צור פריט בלוח אחר", the
mapping's "השדה בפריט המקור" listed only a brand-new board's default fields.
The automations panel asked automation-capabilities about a board once per
page load and kept the answer, so after one board's automations had been
opened, every other board's rule-builder offered the first board's columns.

Pinned on both sides: the server names the board its answer is about, and the
panel asks again whenever that is not the board on screen.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _load_body():
    at = SRC.index("const bid=st.board.id, q=meId()?('?user_id='+meId()):'';")
    return SRC[at:at + 4000]


def test_the_panel_asks_again_when_the_board_is_another_one():
    body = _load_body()
    assert re.search(r"if\(!this\.caps\|\|this\.caps\.board_id!==bid\)\{", body), \
        "capabilities are still asked once per page and reused on every board"
    assert "automation-capabilities?board_id='+bid" in body


def test_the_target_boards_columns_are_not_kept_across_openings():
    assert "this._mapCols={};" in _load_body()


def test_each_board_answers_with_its_own_columns_and_names_itself(client, admin_id):
    a = client.post("/api/boards", json={"name": "מקור מיפוי", "user_id": admin_id}).json()["id"]
    b = client.post("/api/boards", json={"name": "יעד מיפוי", "user_id": admin_id}).json()["id"]
    try:
        cols = client.get(f"/api/boards/{a}").json()["settings"].get("columns") or []
        r = client.patch(f"/api/boards/{a}", json={"user_id": admin_id, "columns": cols + [
            {"id": "c_ticket", "title": "מספר פנייה", "type": "number"}]})
        assert r.status_code == 200, r.text
        ca = client.get(f"/api/automation-capabilities?board_id={a}").json()
        cb = client.get(f"/api/automation-capabilities?board_id={b}").json()
        assert ca["board_id"] == a and cb["board_id"] == b
        assert "מספר פנייה" in [c["title"] for c in ca["columns"]]
        assert "מספר פנייה" not in [c["title"] for c in cb["columns"]]
    finally:
        client.delete(f"/api/boards/{a}?actor_id={admin_id}")
        client.delete(f"/api/boards/{b}?actor_id={admin_id}")
