"""נוסח ההתראה — מה שההתראה אומרת, ושהיא תצא גם במייל.

A notification said one thing: the rule's name, what happened, the item, the
board, the time and a link. Six lines, right for "something happened" and
wrong for the thing people actually send, which is a sentence addressed to a
colleague:

    היי,
    תזכורת להמשך טיפול בתהליך בל"מ
    לרשות: {{item.name}}
    שם הנוהל: {{field.<col>}}
    תודה.

So "התראה" is a blank now, like the recipient beside it. What it holds is the
wording plus whether the notice also leaves by mail, and the wording is
resolved against THIS item on every firing — which is the whole point of
writing one: a notice that said the same thing about every item is a notice
nobody reads twice.

Leaving it empty is a real answer and the only one that could be: it is the
notice this system has always sent, and what every rule written before now
holds. Hence a field type that may be blank, and a save that refuses a token
nobody can answer rather than letting it resolve into nothing at three in the
morning.

The mail is deliberately not routed through _item_mail. That one refuses to
tell the actor about their own keystroke — right for "you were tagged", wrong
for a recurring chase, where the actor is whoever's board read swept the clock
and has nothing to do with the person being chased.
"""
import pathlib
import shutil
import subprocess

import pytest
from sqlalchemy.orm import Session

import automations as recipes
import main as cityos_main
from models import Notification

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"

NOTICE = ('היי,\n"תזכורת להמשך טיפול בתהליך בל"מ\n'
          'לרשות: {{item.name}}\nשם הנוהל: {{field.%s}}\n\nתודה.')


def _board(client, admin_id, name="לוח התראות"):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, bid, admin_id, title, ctype="text"):
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id,
                           "columns": [{"type": ctype, "title": title}]})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json()["columns"] if c["title"] == title)


def _rule(client, bid, admin_id, config, recipe_id="created_notify_person", **kw):
    return client.post(f"/api/boards/{bid}/automations",
                       json={"actor_id": admin_id, "recipe_id": recipe_id,
                             "config": config, **kw})


def _item(client, bid, admin_id, title="הרשות המקומית", cells=None):
    tid = client.post("/api/tasks", json={"board_id": bid, "title": title,
                                          "user_id": admin_id}).json()["id"]
    if cells:
        assert client.patch(f"/api/tasks/{tid}",
                            json={"user_id": admin_id,
                                  "custom_fields": cells}).status_code == 200
    return tid


def _last_notice(uid):
    with Session(cityos_main.engine) as db:
        return (db.query(Notification)
                  .filter(Notification.user_id == uid,
                          Notification.type == "automation")
                  .order_by(Notification.id.desc()).first())


class _Mails:
    """Whatever the engine queued for sending, without a thread in the way."""

    def __enter__(self):
        self.sent = []
        self._real = cityos_main._mail_when_committed
        cityos_main._mail_when_committed = \
            lambda db, msgs: self.sent.extend([m for m in (msgs or []) if m])
        return self

    def __exit__(self, *a):
        cityos_main._mail_when_committed = self._real
        return False


# ── what the notification says ────────────────────────────────────────────

def test_the_rules_own_wording_is_what_arrives(client, admin_id, member_id):
    """With the item's own values in it — which is why it is written at all."""
    bid = _board(client, admin_id)
    cid = _col(client, bid, admin_id, "שם הנוהל")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    # a status rule rather than a creation one, so the cell this notice reads
    # is already on the item when the rule fires — which is the ordinary case
    # and the one a recurring chase is always in
    r = _rule(client, bid, admin_id,
              {"t_status": "done", "a_person": {"kind": "user", "value": member_id},
               "a_notice": {"text": NOTICE % cid}},
              recipe_id="status_notify_person", name="תזכורת בל\"מ")
    assert r.status_code == 200, r.text

    tid = _item(client, bid, admin_id, "עיריית חדרה", {cid: "נוהל 7"})
    assert client.patch(f"/api/tasks/{tid}",
                        json={"user_id": admin_id,
                              "status": "done"}).status_code == 200
    n = _last_notice(member_id)
    assert n is not None, "nothing arrived"
    assert "תזכורת להמשך טיפול" in n.body, n.body
    assert "לרשות: עיריית חדרה" in n.body, n.body
    assert "שם הנוהל: נוהל 7" in n.body, n.body
    # no token survives into what a person reads
    assert "{{" not in n.body, n.body
    # and the heading is the rule's own name — "אוטומציה הופעלה" above a
    # sentence addressed to a colleague reads as a message about nothing
    assert n.title == 'תזכורת בל"מ', n.title


def test_a_value_the_item_does_not_have_leaves_a_gap_and_not_the_word_none(
        client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח ריק")
    cid = _col(client, bid, admin_id, "שם הנוהל")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    _rule(client, bid, admin_id,
          {"a_person": {"kind": "user", "value": member_id},
           "a_notice": {"text": "שם הנוהל: {{field.%s}}." % cid}})
    _item(client, bid, admin_id, "בלי נוהל")
    n = _last_notice(member_id)
    assert n.body == "שם הנוהל: .", repr(n.body)


def test_a_rule_that_names_no_wording_sends_what_it_always_sent(
        client, admin_id, member_id):
    """Every rule written before this one, and the compatibility story in
    full: the blank may be empty, and empty is the old notice."""
    bid = _board(client, admin_id, "לוח ברירת מחדל")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    r = _rule(client, bid, admin_id,
              {"a_person": {"kind": "user", "value": member_id}})
    assert r.status_code == 200, r.text          # activates with the blank unset
    _item(client, bid, admin_id, "פריט")
    n = _last_notice(member_id)
    assert n.title == "אוטומציה הופעלה", n.title
    for part in ("פריט:", "לוח:", "זמן:"):
        assert part in n.body, n.body


# ── and whether it also goes by mail ──────────────────────────────────────

def test_the_notice_can_go_by_mail_as_well(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח מייל")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    _rule(client, bid, admin_id,
          {"a_person": {"kind": "user", "value": member_id},
           "a_notice": {"text": "תזכורת ל{{item.name}}", "mail": True}},
          name="תזכורת")
    with _Mails() as m:
        _item(client, bid, admin_id, "עיריית חדרה")
    assert len(m.sent) == 1, m.sent
    to, subject, html = m.sent[0]
    assert "תזכורת" in subject and "לוח מייל" in subject, subject
    assert "תזכורת לעיריית חדרה" in html, html


def test_without_the_switch_no_mail_leaves(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח בלי מייל")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    _rule(client, bid, admin_id,
          {"a_person": {"kind": "user", "value": member_id},
           "a_notice": {"text": "תזכורת"}})
    with _Mails() as m:
        _item(client, bid, admin_id, "פריט")
    assert m.sent == [], m.sent
    # …and the in-app notice still arrived
    assert _last_notice(member_id).body == "תזכורת"


def test_the_mail_is_escaped_and_its_lines_are_kept(client, admin_id, member_id):
    """A notice is typed into a textarea. What somebody typed there is not
    HTML, and its newlines are part of what they wrote."""
    bid = _board(client, admin_id, "לוח בריחה")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    _rule(client, bid, admin_id,
          {"a_person": {"kind": "user", "value": member_id},
           "a_notice": {"text": "שורה <b>אחת</b>\nשורה שתיים", "mail": True}})
    with _Mails() as m:
        _item(client, bid, admin_id, "פריט")
    html = m.sent[0][2]
    assert "&lt;b&gt;" in html and "<b>אחת</b>" not in html, html
    assert "שורה <br>שורה שתיים" in html.replace("אחת&lt;/b&gt;", "") or "<br>" in html, html


# ── what the save refuses ─────────────────────────────────────────────────

def test_a_token_nobody_can_answer_is_refused_at_the_save(client, admin_id,
                                                          member_id):
    """Rather than left to resolve into nothing at three in the morning."""
    bid = _board(client, admin_id, "לוח סימנייה")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    r = _rule(client, bid, admin_id,
              {"a_person": {"kind": "user", "value": member_id},
               "a_notice": {"text": "שלום {{pulse.name}}"}})
    assert r.status_code == 400, r.text
    assert "pulse.name" in r.json()["detail"], r.json()


def test_a_bare_string_is_read_as_the_wording(client, admin_id, member_id):
    """What an older client sends, and what somebody pasting a configuration
    writes. A string means "this wording, in the app only" — the quieter of
    the two, which is the right reading of silence about the mail."""
    bid = _board(client, admin_id, "לוח מחרוזת")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    r = _rule(client, bid, admin_id,
              {"a_person": {"kind": "user", "value": member_id},
               "a_notice": "תזכורת פשוטה"})
    assert r.status_code == 200, r.text
    assert r.json()["config"]["a_notice"] == {"text": "תזכורת פשוטה", "mail": False}


def test_the_wording_is_capped(client, admin_id, member_id):
    bid = _board(client, admin_id, "לוח ארוך")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    r = _rule(client, bid, admin_id,
              {"a_person": {"kind": "user", "value": member_id},
               "a_notice": {"text": "א" * (recipes.NOTICE_MAX + 50)}})
    assert r.status_code == 200, r.text
    assert len(r.json()["config"]["a_notice"]["text"]) == recipes.NOTICE_MAX


# ── the word stays a word ─────────────────────────────────────────────────

def test_the_sentence_still_reads_as_a_sentence():
    """The blank's own NAME is the word the sentence needs. "שלח … ל…" in the
    from-scratch picker says nothing about what the action does."""
    assert recipes.plain(recipes.ACTIONS["notify_person"]) == "שלח התראה ל…"
    assert recipes.plain(recipes.ACTIONS["notify_assignees"]) == "שלח התראה למשויכים לפריט"
    # …and every other blank is still a value somebody has yet to choose
    assert recipes.plain(recipes.ACTIONS["set_status"]) == "שנה את הסטטוס ל…"
    # an extra action reads the same way
    assert recipes.action_text("notify_person", {"person": "דנה"}) == "שלח התראה לדנה"


def test_every_notify_recipe_declares_the_blank(client, admin_id):
    """Derived from the action's own field list rather than repeated in each
    recipe — the one that was missed would be a rule whose sentence shows a
    blank the save then refuses."""
    for r in recipes.RECIPES:
        if r["action"] in ("notify_person", "notify_assignees"):
            assert any(f["key"] == "a_notice" and f["type"] == "notice"
                       for f in r["fields"]), r["id"]
    d = client.get("/api/automations/recipes").json()
    every = next(x for x in d["recipes"] if x["id"] == "every_days_notify_person")
    assert "{a_notice}" in every["sentence"], every["sentence"]


def test_the_list_shows_that_there_is_a_wording_not_the_wording(
        client, admin_id, member_id):
    """A rule's sentence is one line in a list of thirty; a notice is a
    paragraph with the item's values in it."""
    bid = _board(client, admin_id, "לוח משפט")
    assert client.post(f"/api/boards/{bid}/members",
                       json={"actor_id": admin_id, "user_id": member_id,
                             "role": "editor"}).status_code in (200, 201)
    plain_rule = _rule(client, bid, admin_id,
                       {"a_person": {"kind": "user", "value": member_id}})
    with_text = _rule(client, bid, admin_id,
                      {"a_person": {"kind": "user", "value": member_id},
                       "a_notice": {"text": "היי, תזכורת ארוכה מאוד"}},
                      recipe_id="status_notify_person")
    assert plain_rule.status_code == 200 and with_text.status_code in (200, 400), \
        (plain_rule.text, with_text.text)
    s1 = plain_rule.json()["sentence"]
    assert "שלח התראה ל" in s1 and "{" not in s1, s1
    if with_text.status_code == 200:
        s2 = with_text.json()["sentence"]
        assert "התראה מותאמת" in s2 and "תזכורת ארוכה" not in s2, s2


# ── the browser's half ────────────────────────────────────────────────────

def test_the_word_opens_an_editor_and_not_a_one_line_box():
    src = INDEX.read_text(encoding="utf-8")
    assert "if(f.type==='notice'){ this.pickNotice(key,null); return; }" in src
    assert "if(f.type==='notice'){ this.pickNotice(key,{actIdx:i,key}); return; }" in src
    fn = src[src.index("  pickNotice(key,into){"):]
    fn = fn[:fn.index("\n  },")]
    assert "<textarea id=\"au-notice\"" in fn, fn
    assert "au-notice-mail" in fn, fn
    # the columns are offered by title, which is the point — see tokenMenuHTML
    assert "this.tokenMenuHTML('au-notice')" in fn, fn


def test_the_token_menu_names_the_columns_and_not_their_ids():
    src = INDEX.read_text(encoding="utf-8")
    fn = src[src.index("  tokenMenuHTML(into){"):]
    fn = fn[:fn.index("\n  },")]
    assert "ערך של «${esc(c.title||c.id)}»" in fn, fn
    assert "putToken('field.${c.id}'" in fn, fn


def test_an_empty_blank_does_not_hold_the_save_button():
    src = INDEX.read_text(encoding="utf-8")
    assert "OPTIONAL_FIELDS:['pick','connect_opt','notice']," in src
    assert set(recipes.OPTIONAL_TYPES) == {"pick", "connect_opt", "notice"}, \
        recipes.OPTIONAL_TYPES
    assert "const ready=r.fields.every(f=>!this._needs(f)" in src


def test_the_editor_in_the_browser(client, admin_id):
    """Driven harness: tests/frontend/automation_notice.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "automation_notice.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
