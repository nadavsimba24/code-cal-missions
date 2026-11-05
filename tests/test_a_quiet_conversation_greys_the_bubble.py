"""A conversation nobody has written in goes grey, and the board says when.

Two rules are pinned here.

  · The item carries WHEN its thread was last written in (`last_comment_at`),
    and the board carries after how many silent days it draws that thread's
    bubble grey (`chat_stale_days`). Seven until somebody says otherwise.

  · That number is not a second setting living beside the automations: it IS
    the "ללא עדכון בשיחה" rule the board has switched on. A board that greys
    at ten and chases at seven would hold two definitions of "ללא מענה", and
    the icon is the one people read without being told.

The rule itself is the third thing: a silence that reaches the threshold is an
event, it fires once per silence, and a reply starts a new one.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
import automations as recipes
import main as cityos_main
from models import Automation, Comment, Task


def _board(client, admin_id, name="לוח שיחות"):
    return client.post("/api/boards", json={"name": name, "user_id": admin_id}).json()["id"]


def _item(client, bid, admin_id, title="פריט"):
    return client.post("/api/tasks", json={"board_id": bid, "title": title,
                                           "user_id": admin_id}).json()["id"]


def _say(client, tid, admin_id, text="שלום"):
    r = client.post(f"/api/tasks/{tid}/comments",
                    json={"content": text, "user_id": admin_id})
    assert r.status_code == 200, r.text
    return r.json()


def _age_thread(tid, days):
    """Put the newest message on this item `days` days in the past.

    The older ones go further back, a minute apart, rather than all landing on
    the same instant: the rule remembers the silence it fired for by WHEN it
    started, so a reply that was back-dated onto the same moment as the message
    before it would not read as a new silence at all — which is a fact about
    this helper, not about the product.
    """
    base = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with Session(cityos_main.engine) as db:
        rows = (db.query(Comment).filter(Comment.task_id == tid)
                  .order_by(Comment.id.desc()).all())
        for i, c in enumerate(rows):
            c.created_at = base - timedelta(minutes=i)
        db.commit()


def _age_item(tid, days):
    """And the item itself, for the case where nobody ever wrote anything."""
    when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    with Session(cityos_main.engine) as db:
        db.query(Task).filter(Task.id == tid).update({Task.created_at: when})
        db.commit()


def _add(client, bid, admin_id, recipe_id, config):
    r = client.post(f"/api/boards/{bid}/automations?user_id={admin_id}",
                    json={"recipe_id": recipe_id, "config": config})
    assert r.status_code == 200, r.text
    return r.json()


def _runs(client, bid, admin_id):
    return client.get(f"/api/boards/{bid}/automations/runs?user_id={admin_id}").json()["runs"]


def _read(client, bid, admin_id):
    r = client.get(f"/api/boards/{bid}?user_id={admin_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _row(board, tid):
    return next(t for t in board["tasks"] if t["id"] == tid)


# ── מה הפריט אומר ───────────────────────────────────────────────────────────

def test_an_item_says_when_its_conversation_was_last_written_in(client, admin_id):
    bid = _board(client, admin_id, "לוח מועד עדכון")
    quiet = _item(client, bid, admin_id, "בלי שיחה")
    talked = _item(client, bid, admin_id, "עם שיחה")
    _say(client, talked, admin_id, "הראשונה")
    _say(client, talked, admin_id, "והאחרונה")
    board = _read(client, bid, admin_id)
    # nobody ever wrote on it, so there is no silence to measure — not a date
    # far in the past, which would read as a thread that has gone stale
    assert _row(board, quiet)["last_comment_at"] is None
    assert _row(board, talked)["last_comment_at"] is not None
    assert _row(board, talked)["comment_count"] == 2


def test_the_thread_itself_answers_with_the_same_moment(client, admin_id):
    """The panel that just read the thread holds the fresher answer, so the
    badge can turn blue again without the whole board being reloaded."""
    bid = _board(client, admin_id, "לוח תשובת שיחה")
    tid = _item(client, bid, admin_id)
    _say(client, tid, admin_id)
    d = client.get(f"/api/tasks/{tid}/comments?user_id={admin_id}").json()
    assert d["count"] == 1
    assert d["last_comment_at"] is not None


# ── הפרמטר ברמת לוח ─────────────────────────────────────────────────────────

def test_a_board_with_no_rule_greys_after_a_week(client, admin_id):
    bid = _board(client, admin_id, "לוח ברירת מחדל")
    assert _read(client, bid, admin_id)["chat_stale_days"] == 7
    assert recipes.CHAT_STALE_DAYS_DEFAULT == 7


def test_the_automation_is_where_the_board_says_how_long(client, admin_id):
    bid = _board(client, admin_id, "לוח סף")
    _add(client, bid, admin_id, "chat_idle_notify_assignees", {"t_days": 14})
    assert _read(client, bid, admin_id)["chat_stale_days"] == 14


def test_two_rules_grey_at_the_earlier_of_them(client, admin_id):
    """The bubble has one colour, and the earliest alarm is still true later."""
    bid = _board(client, admin_id, "לוח שני ספים")
    _add(client, bid, admin_id, "chat_idle_notify_assignees", {"t_days": 14})
    _add(client, bid, admin_id, "chat_idle_set_status",
         {"t_days": 3, "a_status": "on_hold"})
    assert _read(client, bid, admin_id)["chat_stale_days"] == 3


def test_switching_the_rule_off_puts_the_board_back_to_a_week(client, admin_id):
    bid = _board(client, admin_id, "לוח כיבוי")
    a = _add(client, bid, admin_id, "chat_idle_notify_assignees", {"t_days": 21})
    assert _read(client, bid, admin_id)["chat_stale_days"] == 21
    r = client.patch(f"/api/automations/{a['id']}?user_id={admin_id}",
                     json={"is_active": False})
    assert r.status_code == 200, r.text
    assert _read(client, bid, admin_id)["chat_stale_days"] == 7


# ── הכלל עצמו ───────────────────────────────────────────────────────────────

def test_a_silence_that_reached_the_threshold_is_an_event(client, admin_id):
    bid = _board(client, admin_id, "לוח שתיקה")
    _add(client, bid, admin_id, "chat_idle_set_status",
         {"t_days": 7, "a_status": "on_hold"})
    stale = _item(client, bid, admin_id, "שקט מזמן")
    fresh = _item(client, bid, admin_id, "נענה היום")
    _say(client, stale, admin_id)
    _say(client, fresh, admin_id)
    _age_thread(stale, 10)
    _read(client, bid, admin_id)                 # the sweep runs on a read
    hit = {x["task_id"] for x in _runs(client, bid, admin_id)
           if x["event_type"] == "chat_idle_days"}
    assert stale in hit and fresh not in hit, hit


def test_an_item_nobody_ever_wrote_on_is_measured_from_its_creation(client, admin_id):
    """An item opened three weeks ago with not a word on it is the clearest
    case of what the rule is looking for, not one it has no opinion about."""
    bid = _board(client, admin_id, "לוח בלי מילה")
    _add(client, bid, admin_id, "chat_idle_set_status",
         {"t_days": 7, "a_status": "on_hold"})
    old = _item(client, bid, admin_id, "נפתח ונשכח")
    new = _item(client, bid, admin_id, "נפתח עכשיו")
    _age_item(old, 21)
    _read(client, bid, admin_id)
    hit = {x["task_id"] for x in _runs(client, bid, admin_id)
           if x["event_type"] == "chat_idle_days"}
    assert old in hit and new not in hit, hit


def test_a_finished_item_is_not_waiting_for_an_answer(client, admin_id):
    bid = _board(client, admin_id, "לוח הושלם")
    _add(client, bid, admin_id, "chat_idle_notify_assignees", {"t_days": 7})
    tid = _item(client, bid, admin_id, "נסגר")
    _say(client, tid, admin_id)
    _age_thread(tid, 30)
    r = client.patch(f"/api/tasks/{tid}", json={"status": "done", "user_id": admin_id})
    assert r.status_code == 200, r.text
    _read(client, bid, admin_id)
    assert not [x for x in _runs(client, bid, admin_id)
                if x["event_type"] == "chat_idle_days"]


def test_one_silence_fires_once_however_often_the_board_is_opened(client, admin_id):
    bid = _board(client, admin_id, "לוח פעם אחת")
    _add(client, bid, admin_id, "chat_idle_notify_assignees", {"t_days": 7})
    tid = _item(client, bid, admin_id, "שקט")
    _say(client, tid, admin_id)
    _age_thread(tid, 10)
    for _ in range(3):
        _read(client, bid, admin_id)
    fired = [x for x in _runs(client, bid, admin_id)
             if x["event_type"] == "chat_idle_days" and x["task_id"] == tid]
    assert len(fired) == 1, fired


def test_an_answer_then_silence_again_is_a_new_event(client, admin_id):
    """Somebody replying and then abandoning the thread for another month is
    exactly the case the rule is for — so the marker is the silence, not the
    item."""
    bid = _board(client, admin_id, "לוח שתיקה שנייה")
    _add(client, bid, admin_id, "chat_idle_notify_assignees", {"t_days": 7})
    tid = _item(client, bid, admin_id, "שקט וחוזר חלילה")
    _say(client, tid, admin_id, "הראשונה")
    _age_thread(tid, 10)
    _read(client, bid, admin_id)
    _say(client, tid, admin_id, "התשובה")
    # eight rather than ten, so the reply sits at a different moment from the
    # message it answered — the same reason the helper above fans the older
    # ones out, said again for the one that matters most here
    _age_thread(tid, 8)                           # and then quiet again
    _read(client, bid, admin_id)
    fired = [x for x in _runs(client, bid, admin_id)
             if x["event_type"] == "chat_idle_days" and x["task_id"] == tid]
    assert len(fired) == 2, fired


def test_the_rule_cannot_be_set_to_no_days_at_all(client, admin_id):
    """There is no scheduler here — the rule is swept when the board is read,
    and "0 ימים ללא עדכון" would be every item on every read."""
    bid = _board(client, admin_id, "לוח אפס")
    a = _add(client, bid, admin_id, "chat_idle_notify_assignees", {"t_days": 0})
    assert a["config"]["t_days"] == recipes.MIN_IDLE_DAYS
