"""Group — importing an item's conversation (ייבוא שיחה על פריט).

A board's conversation is most of what happened on it, and until now an import
brought the items and left every message behind. Both importers now carry it:
a monday response brings each item's updates and their replies, and a workbook
exported from here brings its "שיחות" sheet home.

The author is the delicate part. A message is a record of who said what, so a
writer with no account here keeps their name through `origin` instead of being
signed over to whoever happened to run the import.
"""
import io
import json

from sqlalchemy.orm import Session
import main as cityos_main
from models import Comment, Task, User


def _monday(items, board_name="לוח מיובא"):
    return json.dumps({"data": {"boards": [{"id": "1", "name": board_name,
                                            "items_page": {"items": items}}]}}).encode()


def _item(name, updates=None, subitems=None):
    return {"id": "9" + name, "name": name,
            "column_values": [{"id": "text", "type": "text", "text": "ערך",
                               "column": {"title": "טקסט"}}],
            "updates": updates or [], "subitems": subitems or []}


def _upd(uid, body, who, when, email="", replies=None, assets=None, html=False):
    out = {"id": uid, "created_at": when, "creator": {"name": who, "email": email},
           "replies": replies or []}
    out["body" if html else "text_body"] = body
    if assets:
        out["assets"] = assets
    return out


def _import(client, admin_id, raw, filename="board.json"):
    return client.post(f"/api/boards/import?actor_id={admin_id}",
                       files={"file": (filename, raw, "application/json")},
                       data={"actor_id": admin_id})


def _comments(board_id):
    with Session(cityos_main.engine) as db:
        ids = [t.id for t in db.query(Task).filter(Task.board_id == board_id).all()]
        return db.query(Comment).filter(Comment.task_id.in_(ids)).order_by(Comment.id).all()


def test_an_items_conversation_comes_with_it(client, admin_id):
    raw = _monday([_item("תיקון מדרכה", [
        _upd("u1", "פתחתי קריאה מול הקבלן", "דנה כהן", "2026-01-01T09:00:00Z"),
        _upd("u2", "הקבלן מגיע ביום ראשון", "יואב לוי", "2026-01-02T09:00:00Z"),
    ])])
    r = _import(client, admin_id, raw)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["messages"] == 2 and d["report"]["messages_imported"] == 2
    cs = _comments(d["id"])
    assert [c.content for c in cs] == ["פתחתי קריאה מול הקבלן", "הקבלן מגיע ביום ראשון"]
    assert all(c.parent_id is None for c in cs)


def test_a_reply_stays_under_the_message_it_answers(client, admin_id):
    raw = _monday([_item("החלפת תמרור", [
        _upd("u1", "מי אחראי?", "דנה כהן", "2026-01-01T09:00:00Z",
             replies=[_upd("r1", "אני", "יואב לוי", "2026-01-01T10:00:00Z")]),
    ])])
    d = _import(client, admin_id, raw).json()
    cs = _comments(d["id"])
    assert len(cs) == 2
    root = next(c for c in cs if c.parent_id is None)
    reply = next(c for c in cs if c.parent_id is not None)
    assert reply.parent_id == root.id and reply.content == "אני"


def test_the_conversation_reads_oldest_first(client, admin_id):
    """monday hands back the newest update first; a conversation reads the other
    way, and the dates have to survive the trip or it cannot be reordered."""
    raw = _monday([_item("גינון", [
        _upd("u2", "שני", "דנה כהן", "2026-03-01T09:00:00Z"),
        _upd("u1", "ראשון", "דנה כהן", "2026-01-01T09:00:00Z"),
    ])])
    d = _import(client, admin_id, raw).json()
    cs = _comments(d["id"])
    assert [c.content for c in cs] == ["ראשון", "שני"]
    assert cs[0].created_at.year == 2026 and cs[0].created_at.month == 1


def test_a_writer_with_an_account_gets_the_message(client, admin_id):
    with Session(cityos_main.engine) as db:
        me = db.query(User).filter(User.id == admin_id).first()
        name, email = me.name, me.email
    raw = _monday([_item("פריט", [_upd("u1", "לפי השם", name, "2026-01-01T09:00:00Z"),
                                  _upd("u2", "לפי המייל", "שם אחר לגמרי", "2026-01-02T09:00:00Z",
                                       email=email)])])
    d = _import(client, admin_id, raw).json()
    cs = _comments(d["id"])
    assert [c.user_id for c in cs] == [admin_id, admin_id]
    assert all((c.origin or {}).get("matched") for c in cs)


def test_a_writer_with_no_account_keeps_their_name(client, admin_id):
    """Signing their words over to whoever ran the import would put words in a
    colleague's mouth."""
    raw = _monday([_item("פריט", [_upd("u1", "כתבתי את זה", "מישהי מהעירייה",
                                       "2026-01-01T09:00:00Z")])])
    d = _import(client, admin_id, raw).json()
    c = _comments(d["id"])[0]
    assert c.user_id is None
    assert c.origin["author"] == "מישהי מהעירייה" and c.origin["matched"] is False
    assert c.origin["source"] == "monday"
    # and the reader is told who wrote it, not "—"
    shown = client.get(f"/api/tasks/{c.task_id}/comments?user_id={admin_id}").json()
    msg = shown["comments"][0] if isinstance(shown, dict) and "comments" in shown else shown[0]
    assert msg["user_name"] == "מישהי מהעירייה"
    assert msg["origin"]["source"] == "monday"


def test_html_bodies_arrive_as_text(client, admin_id):
    raw = _monday([_item("פריט", [_upd("u1", "<p>שורה ראשונה</p><p>שורה שנייה</p>",
                                       "דנה", "2026-01-01T09:00:00Z", html=True)])])
    d = _import(client, admin_id, raw).json()
    c = _comments(d["id"])[0]
    assert "<p>" not in c.content and "שורה ראשונה" in c.content and "שורה שנייה" in c.content


def test_an_attachment_keeps_its_name(client, admin_id):
    raw = _monday([_item("פריט", [_upd("u1", "מצורף המפרט", "דנה", "2026-01-01T09:00:00Z",
                                       assets=[{"name": "מפרט.pdf", "public_url": "http://x/1"}])])])
    d = _import(client, admin_id, raw).json()
    c = _comments(d["id"])[0]
    assert c.attachments and c.attachments[0]["name"] == "מפרט.pdf"


def test_a_subitems_conversation_is_not_lost(client, admin_id):
    sub = {"id": "s1", "name": "תת-פריט", "column_values": [],
           "updates": [_upd("s-u1", "הודעה על תת-פריט", "דנה", "2026-01-01T09:00:00Z")]}
    raw = _monday([_item("פריט אב", [], subitems=[sub])])
    d = _import(client, admin_id, raw).json()
    assert d["messages"] == 1
    with Session(cityos_main.engine) as db:
        c = db.query(Comment).join(Task, Task.id == Comment.task_id).filter(
            Task.board_id == d["id"]).first()
        t = db.query(Task).filter(Task.id == c.task_id).first()
        assert t.parent_id is not None


def test_an_empty_update_is_not_an_empty_message(client, admin_id):
    raw = _monday([_item("פריט", [_upd("u1", "   ", "דנה", "2026-01-01T09:00:00Z"),
                                  _upd("u2", "אמיתי", "דנה", "2026-01-02T09:00:00Z")])])
    d = _import(client, admin_id, raw).json()
    assert d["messages"] == 1


def test_a_board_with_no_conversation_still_imports(client, admin_id):
    d = _import(client, admin_id, _monday([_item("פריט")])).json()
    assert d["items"] == 1 and d["messages"] == 0
    assert d["report"]["updates"] == 0


def test_the_import_caps_the_conversation_and_says_so(client, admin_id, monkeypatch):
    monkeypatch.setattr(cityos_main, "IMPORT_MAX_MESSAGES", 3)
    ups = [_upd(f"u{i}", f"הודעה {i}", "דנה", f"2026-01-{i+1:02d}T09:00:00Z") for i in range(6)]
    d = _import(client, admin_id, _monday([_item("פריט", ups)])).json()
    assert d["messages"] == 3
    assert d["report"]["messages_dropped"] == 3
    assert len(_comments(d["id"])) == 3


def test_the_conversations_people_are_matched_like_the_columns_people(client, admin_id):
    """Someone who only ever appears in the conversation is still a person to
    look for, or every imported message would come in unattributed."""
    with Session(cityos_main.engine) as db:
        email = db.query(User).filter(User.id == admin_id).first().email
    raw = _monday([_item("פריט", [_upd("u1", "שלי", "לא משנה", "2026-01-01T09:00:00Z",
                                       email=email)])])
    d = _import(client, admin_id, raw).json()
    assert d["report"]["people_matched"] >= 1
    assert _comments(d["id"])[0].user_id == admin_id


# ── the workbook route: what this app exports, it can now read back ──────────

def _wb(items_rows, talk_rows, talk_sheet="שיחות"):
    """A workbook shaped like the board export: the items, then the conversation."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "לוח"
    for r in items_rows:
        ws.append(r)
    ts = wb.create_sheet(talk_sheet)
    for r in talk_rows:
        ts.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _import_xlsx(client, admin_id, raw, filename="board.xlsx"):
    return client.post(f"/api/boards/import?actor_id={admin_id}",
                       files={"file": (filename, raw,
                                       "application/vnd.openxmlformats-officedocument."
                                       "spreadsheetml.sheet")},
                       data={"actor_id": admin_id})


TALK_HEAD = cityos_main.TALK_HEADERS


def test_a_workbook_brings_its_conversation_sheet_home(client, admin_id):
    raw = _wb([["פריט", "הערה"], ["תיקון מדרכה", "דחוף"], ["החלפת תמרור", ""]],
              [TALK_HEAD,
               ["A1", "תיקון מדרכה", "עדכון", "דנה כהן", "2026-01-01 09:00:00",
                "פתחתי קריאה", 2, "", 101, ""],
               ["A1", "תיקון מדרכה", "תגובה", "יואב לוי", "2026-01-01 10:00:00",
                "בטיפול", 0, "מפרט.pdf", 102, 101],
               ["A2", "החלפת תמרור", "עדכון", "דנה כהן", "2026-01-02 09:00:00",
                "הוזמן תמרור", 0, "", 103, ""]])
    r = _import_xlsx(client, admin_id, raw)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["items"] == 2 and d["messages"] == 3
    assert d["report"]["replies_imported"] == 1
    cs = _comments(d["id"])
    assert {c.content for c in cs} == {"פתחתי קריאה", "בטיפול", "הוזמן תמרור"}
    reply = next(c for c in cs if c.content == "בטיפול")
    root = next(c for c in cs if c.content == "פתחתי קריאה")
    assert reply.parent_id == root.id, "the thread came apart"
    assert reply.attachments[0]["name"] == "מפרט.pdf"
    assert reply.created_at.hour == 10


def test_a_message_for_an_item_that_is_not_here_is_reported_not_guessed(client, admin_id):
    raw = _wb([["פריט"], ["תיקון מדרכה"]],
              [TALK_HEAD,
               ["A1", "פריט אחר לגמרי", "עדכון", "דנה", "2026-01-01 09:00:00", "שלום", 0, "", 1, ""]])
    d = _import_xlsx(client, admin_id, raw).json()
    assert d["messages"] == 0
    assert d["report"]["conversation_items_unmatched"] == ["פריט אחר לגמרי"]
    assert _comments(d["id"]) == []


def test_a_workbook_with_no_conversation_sheet_imports_as_before(client, admin_id):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["פריט"])
    wb.active.append(["תיקון מדרכה"])
    buf = io.BytesIO()
    wb.save(buf)
    d = _import_xlsx(client, admin_id, buf.getvalue()).json()
    assert d["items"] == 1 and d["messages"] == 0


def test_the_sheet_is_found_by_its_headers_too(client, admin_id):
    """A file someone rebuilt by hand should not have to guess our sheet name."""
    raw = _wb([["פריט"], ["תיקון מדרכה"]],
              [TALK_HEAD, ["", "תיקון מדרכה", "עדכון", "דנה", "2026-01-01 09:00:00",
                           "הודעה", 0, "", 1, ""]],
              talk_sheet="Conversation")
    d = _import_xlsx(client, admin_id, raw).json()
    assert d["messages"] == 1


def test_an_unknown_writer_in_a_workbook_keeps_their_name(client, admin_id):
    raw = _wb([["פריט"], ["תיקון מדרכה"]],
              [TALK_HEAD, ["", "תיקון מדרכה", "עדכון", "רינה מהעירייה", "2026-01-01 09:00:00",
                           "הודעה", 0, "", 1, ""]])
    d = _import_xlsx(client, admin_id, raw).json()
    c = _comments(d["id"])[0]
    assert c.user_id is None and c.origin["author"] == "רינה מהעירייה"
    assert c.origin["source"] == "xlsx"
    assert d["report"]["people_unmatched"] == ["רינה מהעירייה"]


def test_a_reply_whose_parent_is_missing_is_not_hung_on_nothing(client, admin_id):
    raw = _wb([["פריט"], ["תיקון מדרכה"]],
              [TALK_HEAD, ["", "תיקון מדרכה", "תגובה", "דנה", "2026-01-01 09:00:00",
                           "תשובה ליתום", 0, "", 2, 999]])
    d = _import_xlsx(client, admin_id, raw).json()
    assert d["messages"] == 0 and _comments(d["id"]) == []


def test_a_board_exported_from_here_comes_back_with_its_conversation(client, admin_id):
    """The round trip the feature exists for."""
    bid = client.post("/api/boards", json={"name": "לוח מקור", "user_id": admin_id}).json()["id"]
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "תיקון מדרכה",
                                          "user_id": admin_id}).json()["id"]
    client.post(f"/api/tasks/{tid}/comments",
                json={"content": "פתחתי קריאה מול הקבלן", "user_id": admin_id})
    exported = client.post(f"/api/boards/{bid}/export/xlsx?actor_id={admin_id}",
                           json={"columns": ["פריט"],
                                 "rows": [{"cells": ["תיקון מדרכה"]}]})
    assert exported.status_code == 200, exported.text

    d = _import_xlsx(client, admin_id, exported.content, "לוח מקור_1.xlsx").json()
    assert d["items"] == 1 and d["messages"] == 1
    c = _comments(d["id"])[0]
    assert c.content == "פתחתי קריאה מול הקבלן"
    assert c.user_id == admin_id, "the author came home as somebody else"
