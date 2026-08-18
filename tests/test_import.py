"""Group 15 — import a board from a CSV / Excel file."""


def test_import_board_from_csv(client, admin_id):
    """The header row becomes columns (types inferred), the first column names
    the item, and one item is created per data row."""
    csv = "שם משימה,תאריך,תקציב\nא,2026-09-01,100\nב,02/10/2026,250\n"
    r = client.post(f"/api/boards/import?user_id={admin_id}",
                    files={"file": ("data.csv", csv.encode("utf-8-sig"), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == 2 and body["columns"] == 2
    bid = body["id"]
    try:
        b = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()
        # the first header names the item (name) column
        assert b["col_labels"].get("item") == "שם משימה"
        custom = [c for c in b["columns"] if str(c["id"]).startswith("col_")]
        assert {c["title"]: c["type"] for c in custom} == {"תאריך": "date", "תקציב": "number"}
        assert sorted(t["title"] for t in b["tasks"]) == ["א", "ב"]
        # values are coerced to the column type (DD/MM/YYYY -> ISO)
        date_col = next(c["id"] for c in custom if c["title"] == "תאריך")
        num_col = next(c["id"] for c in custom if c["title"] == "תקציב")
        b_item = next(t for t in b["tasks"] if t["title"] == "ב")
        assert b_item["custom_fields"][date_col] == "2026-10-02"
        assert b_item["custom_fields"][num_col] == 250
    finally:
        client.delete(f"/api/boards/{bid}?actor_id={admin_id}")


def test_import_rejects_an_empty_file(client, admin_id):
    r = client.post(f"/api/boards/import?user_id={admin_id}",
                    files={"file": ("empty.csv", b"", "text/csv")})
    assert r.status_code == 400
