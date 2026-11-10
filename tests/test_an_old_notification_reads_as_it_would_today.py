"""התראה ישנה נקראת בניסוח של היום — אותו אירוע, אותו טקסט, בכל סביבה.

A notification's body is a sentence frozen at the moment it was sent, and
nothing in the app ever rewrites one. So the release that fixed the wording
(see test_notification_names_the_item_now.py) fixed it only for the
notifications sent after it — and that is the whole of the difference somebody
sees between two installations running the SAME code: a local bell whose list
was written after the change reads cleanly, while QA, where the testers have
weeks of rows behind them, still shows

    שויכת למשימה «פריט חדש».
    לוח: MISSIONS רעות ושלי
    שיוך אוטומטי · כאשר נוצר פריט חדש
    זמן: 10/11/2026 09:09

— a placeholder quoted as if it were a name, and the rule's trigger in the
rule's own words, about a thing the reader cannot open and did not ask about.

So the sentence is brought up to date on the way out, the way the item's name
already is: `_clean_notif_body` turns each of the old lines into exactly what
`_assigned_body` / `_notice_body` write today, which makes the age of the row
stop mattering. Two rules it has to keep:

  * what it produces is today's wording, not a third wording — a body written
    since the change passes through untouched, and cleaning twice changes
    nothing.
  * the stored row is evidence of what was sent and is never written back.
"""
import main as cityos_main
from models import Notification
from sqlalchemy.orm import Session

clean = cityos_main._clean_notif_body

# the body in the report, exactly as the bell showed it on QA
OLD_QA_BODY = ("שויכת למשימה «פריט חדש».\n"
               "לוח: MISSIONS רעות ושלי\n"
               "שיוך אוטומטי · כאשר נוצר פריט חדש\n"
               "זמן: 10/11/2026 09:09")


# ── the reported body, line by line ───────────────────────────────────────

def test_the_reported_body_reads_as_it_would_today():
    out = clean(OLD_QA_BODY)
    assert out == ("שויכת לפריט חדש, שטרם ניתן לו שם.\n"
                   "לוח: MISSIONS רעות ושלי\n"
                   "שיוך אוטומטי\n"
                   "זמן: 10/11/2026 09:09"), out


def test_the_placeholder_is_not_quoted_as_a_name():
    assert clean("שויכת למשימה «פריט חדש».") == "שויכת לפריט חדש, שטרם ניתן לו שם."
    # the hand-assign on a just-created item wrote the same placeholder in ''
    assert clean("שויכת למשימה 'פריט חדש'.") == "שויכת לפריט חדש, שטרם ניתן לו שם."
    # and a caller that sent no title at all got the English one
    assert clean("שויכת למשימה «Untitled».") == "שויכת לפריט חדש, שטרם ניתן לו שם."


def test_the_column_survives_the_rewrite():
    """A people column is the assignment's address — the field the reader opens
    the item looking for their own name in. Only the placeholder goes."""
    out = clean("שויכת למשימה «פריט חדש» בעמודה «אחראי».")
    assert out == "שויכת לפריט חדש בעמודה «אחראי», שטרם ניתן לו שם."


def test_the_trigger_tail_goes_and_the_rule_name_stays():
    assert clean("שיוך אוטומטי · כאשר נוצר פריט חדש") == "שיוך אוטומטי"
    named = "שיוך אוטומטי לפי הכלל «שיוך רעות»"
    assert clean(named) == named


def test_the_item_line_goes_only_where_it_held_the_placeholder():
    assert "פריט:" not in clean("פריט: פריט חדש\nלוח: א")
    assert "פריט:" not in clean("פריט: Untitled\nלוח: א")
    kept = "פריט: שיקום כביש רמתיים\nלוח: א"
    assert clean(kept) == kept


# ── it produces today's wording, and only that ────────────────────────────

def test_a_real_name_is_left_alone():
    """The whole point is a placeholder nobody typed. A name somebody DID type
    is the message, however old the row is."""
    body = "שויכת למשימה «שיקום כביש רמתיים» בעמודה «אחראי».\nלוח: א"
    assert clean(body) == body


def test_cleaning_what_is_already_clean_changes_nothing():
    once = clean(OLD_QA_BODY)
    assert clean(once) == once


def test_nothing_at_all_is_handled():
    assert clean("") == ""
    assert clean(None) is None


# ── end to end, and the row stays as it was written ───────────────────────

def test_the_bell_hands_out_the_cleaned_sentence(client, member_id):
    """The QA case: a row written before the change, read through the bell."""
    with Session(cityos_main.engine) as db:
        n = Notification(user_id=member_id, type="assign", title="שויכת למשימה",
                         body=OLD_QA_BODY)
        db.add(n)
        db.commit()
        nid = n.id
    try:
        rows = client.get(f"/api/notifications?user_id={member_id}").json()["notifications"]
        row = next(r for r in rows if r["id"] == nid)
        assert "«פריט חדש»" not in row["body"], row["body"]
        assert " · " not in row["body"], row["body"]
        assert "שטרם ניתן לו שם" in row["body"], row["body"]
        # the board and the time are the message and are untouched
        assert "לוח: MISSIONS רעות ושלי" in row["body"], row["body"]
        assert "זמן: 10/11/2026 09:09" in row["body"], row["body"]

        with Session(cityos_main.engine) as db:
            stored = db.query(Notification).filter(Notification.id == nid).first()
            assert stored.body == OLD_QA_BODY, "the record of what was sent"
    finally:
        with Session(cityos_main.engine) as db:
            db.query(Notification).filter(Notification.id == nid).delete()
            db.commit()


def test_an_item_still_waiting_for_a_name_hands_out_none(client, admin_id, member_id):
    """The live title replaces the placeholder in the frozen sentence. An item
    nobody has named yet has nothing to replace it with — handing out
    "פריט חדש" would put the template back beside a cleaned sentence."""
    bid = client.post("/api/boards",
                      json={"name": "לוח ללא שם", "user_id": admin_id}).json()["id"]
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    r = client.post(f"/api/boards/{bid}/automations",
                    json={"actor_id": admin_id, "recipe_id": "created_assign_person",
                          "config": {"a_person": member_id}})
    assert r.status_code == 200, r.text
    tid = client.post("/api/tasks", json={"board_id": bid, "title": "פריט חדש",
                                          "user_id": admin_id}).json()["id"]

    rows = client.get(f"/api/notifications?user_id={member_id}").json()["notifications"]
    n = next((x for x in rows if x["task_id"] == tid), None)
    assert n is not None, "the assignment never arrived"
    assert n["item_title"] is None, n
    # and once it is given a real name, that name is what the bell carries
    assert client.patch(f"/api/tasks/{tid}",
                        json={"title": "שיקום כביש רמתיים",
                              "user_id": admin_id}).status_code == 200
    rows = client.get(f"/api/notifications?user_id={member_id}").json()["notifications"]
    n = next(x for x in rows if x["task_id"] == tid)
    assert n["item_title"] == "שיקום כביש רמתיים", n
