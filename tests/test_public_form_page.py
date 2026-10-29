"""עמוד מילוי הטופס — מה שמגיע למי שאינו משתמש.

The only page in this product served to somebody with no account, and the
only API surface they can reach. Both are deliberately small, and what is
tested here is mostly the shape of what does NOT come back: no board, no
column ids, no member names, no other people's records, no permissions.

The page is served to any token at all. What a token IS gets decided by the
API call it then makes, which is the one place that decides anything — so a
guessed address gets the same page and a different answer, and the page
itself gives nothing away.
"""
import json
import pathlib
import re

import pytest
from sqlalchemy.orm import Session

import main as cityos_main
import models as M

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "public-form.html").read_text(encoding="utf-8")
PAPER = (ROOT / "frontend" / "form-paper.js").read_text(encoding="utf-8")

AS = lambda uid: {"X-CityOS-User": str(uid)}
ANON = {"X-CityOS-User": ""}

TEN = [("Text", "text", None), ("Long Text", "long_text", None),
       ("Number", "number", None), ("Single Select", "status", ["א", "ב"]),
       ("Multi Select", "dropdown", ["ג", "ד"]), ("Boolean", "checkbox", None),
       ("Date", "date", None), ("Phone", "phone", None),
       ("Email", "email", None), ("File", "files", None)]


def _board(client, admin_id, name):
    return client.post("/api/boards",
                       json={"name": name, "user_id": admin_id}).json()["id"]


def _col(client, bid, admin_id, title, ctype, options=None):
    cols = [dict(c) for c in client.get(f"/api/boards/{bid}").json()["columns"]]
    col = {"type": ctype, "title": title}
    if options is not None:
        col["options"] = options
    cols.append(col)
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "columns": cols}).status_code == 200
    return [c["id"] for c in client.get(f"/api/boards/{bid}").json()["columns"]
            if c["title"] == title][0]


def _live(client, admin_id, name="טופס ציבורי", access="PUBLIC_LINK", ten=False):
    """A published form, with one text question or with all ten."""
    bid = _board(client, admin_id, name)
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id)).json()
    if ten:
        for label, ctype, options in TEN:
            cid = _col(client, bid, admin_id, label, ctype, options)
            client.post(f"/api/forms/{f['id']}/components",
                        json={"kind": "question", "field_key": cid, "label": label},
                        headers=AS(admin_id))
    else:
        client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": "title", "label": "נושא"},
                    headers=AS(admin_id))
    client.patch(f"/api/forms/{f['id']}", json={"access": access}, headers=AS(admin_id))
    client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"}, headers=AS(admin_id))
    tok = client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).json()["public_token"]
    return bid, f, tok


# ── העמוד עצמו ───────────────────────────────────────────────────────

def test_the_public_address_serves_the_fill_page(client, admin_id):
    _bid, _f, tok = _live(client, admin_id, "דף")
    r = client.get(f"/forms/{tok}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "form-paper.js" in r.text, "the page does not load the shared renderer"


def test_the_page_is_served_before_the_static_mount_catches_everything(client):
    """The mount at "/" matches any path; the first route registered wins."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert src.index("def public_form_page") < src.index('app.mount("/"'), (
        "the page route is behind the catch-all and will never be reached")


def test_the_page_is_told_nothing_and_asks_for_everything(client, admin_id):
    """It is served to any token, valid or not — so it cannot be carrying the
    answer, and a guessed address gives nothing away by the page it returns."""
    same = client.get("/forms/" + "f" * 32).text
    _bid, _f, tok = _live(client, admin_id, "אותו דף")
    assert client.get(f"/forms/{tok}").text == same
    # and nothing of the app's own world is in it
    for leak in ("board_id", "st.board", "/api/boards", "assignee", "BoardMember"):
        assert leak not in PAGE, f"the public page knows about {leak}"
    assert "noindex" in PAGE, "a form's address is indexable"


def test_the_page_is_hebrew_rtl_and_fits_a_phone():
    assert '<html lang="he" dir="rtl">' in PAGE
    assert "@media(max-width:480px)" in PAGE, "there is no phone layout"
    assert "env(safe-area-inset-bottom)" in PAGE, "the page runs under the home bar"
    # thumb-sized targets, which is the whole of a form on a phone
    assert re.search(r"\.fv-in\{[^}]*min-height:44px", PAGE)
    assert re.search(r"\.fv-opt\{[^}]*min-height:44px", PAGE)
    assert re.search(r"\.fv-submit\{[^}]*min-height:46px", PAGE)


def test_one_renderer_serves_the_editor_and_this_page():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'src="form-paper.js"' in index and 'src="/form-paper.js"' in PAGE
    assert "const FormPaper" not in index, "a second copy of the renderer"


def test_this_page_asks_for_the_renderer_by_its_real_address():
    """A relative src on THIS page fetches the page itself.

    index.html is served at "/", so a bare "form-paper.js" resolves to the
    root and is correct there. This page is served at /forms/{token}, where a
    bare one resolves to /forms/form-paper.js — and the route above matches
    ANY token, so the browser was handed 20KB of this very page under a
    text/html content type. nosniff then refused to execute it, FormPaper was
    never defined, and the form sat on its spinner for good: the link "did not
    open". Every asset this page asks for is therefore root-relative.
    """
    for src in re.findall(r'<script src="([^"]+)"', PAGE):
        assert src.startswith(("/", "http")), (
            f"{src} resolves against /forms/ and will fetch the page itself")


def test_the_renderer_is_served_as_javascript_not_as_the_page(client, admin_id):
    """The same thing again from the outside: what the browser actually gets."""
    r = client.get("/form-paper.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"], r.headers["content-type"]
    assert "const FormPaper" in r.text
    # and the shadow it used to fall into, so the trap itself is on record
    shadow = client.get("/forms/form-paper.js")
    assert "text/html" in shadow.headers["content-type"], (
        "a path under /forms/ is the fill page, whatever it is named")
    for t in ("text", "long_text", "number", "status", "dropdown",
              "checkbox", "date", "phone", "email", "files"):
        assert f"'{t}'" in PAPER, f"the renderer cannot draw {t}"


# ── מה שהשרת מחזיר, ומה שלא ──────────────────────────────────────────

def test_the_answer_carries_only_what_is_needed_to_fill_the_form(client, admin_id,
                                                                 member_id):
    bid, f, tok = _live(client, admin_id, "רק הדרוש", ten=True)
    # a board with members, items and a hidden question — none of it may travel
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    client.post("/api/tasks", json={"board_id": bid, "title": "רשומה קיימת",
                                    "user_id": admin_id})
    hidden = _col(client, bid, admin_id, "פנימי", "text")
    client.post(f"/api/forms/{f['id']}/components",
                json={"kind": "question", "field_key": hidden, "label": "סודי",
                      "visible": False}, headers=AS(admin_id))

    pub = client.get(f"/api/public/forms/{tok}", headers=ANON)
    assert pub.status_code == 200
    blob = json.dumps(pub.json(), ensure_ascii=False)

    assert set(pub.json()) == {"token", "status", "access", "design",
                               "success", "components", "uploads"}, sorted(pub.json())
    for leak in ("board_id", "view_id", "field_key", "target_group_id",
                 "published_by", "record_submitter", "config_version",
                 "can_hide_branding", "owner_id", "my_role", "permissions"):
        assert leak not in blob, leak
    # no column ids, no member names, no existing records
    assert hidden not in blob and "רשומה קיימת" not in blob
    assert "סודי" not in blob, "a hidden question was sent"
    for u in client.get("/api/users", headers=AS(admin_id)).json():
        assert (u.get("email") or "@@") not in blob
        assert (u.get("name") or "@@") not in blob


def test_every_one_of_the_ten_arrives_with_what_it_needs_to_be_drawn(client, admin_id):
    _bid, _f, tok = _live(client, admin_id, "עשרה ציבורי", ten=True)
    pub = client.get(f"/api/public/forms/{tok}", headers=ANON).json()
    by = {c["label"]: c for c in pub["components"]}
    assert len(by) == 10
    assert {c["type"] for c in pub["components"]} == {t for _l, t, _o in TEN}
    # a choice arrives with its choices, and only a choice does
    assert [o["label"] for o in by["Single Select"]["options"]] == ["א", "ב"]
    assert [o["label"] for o in by["Multi Select"]["options"]] == ["ג", "ד"]
    assert "options" not in by["Text"] and "options" not in by["File"]


def _with_assignees(client, admin_id, name, access="PUBLIC_LINK"):
    """A published form carrying an אחראים question. Returns (bid, fid, token)."""
    bid = _board(client, admin_id, name)
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id)).json()
    q = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": "assignees",
                          "label": "אחראים"}, headers=AS(admin_id)).json()
    client.patch(f"/api/forms/{f['id']}", json={"access": access}, headers=AS(admin_id))
    client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"}, headers=AS(admin_id))
    tok = client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).json()["public_token"]
    assert q["id"]
    return bid, f["id"], tok


def _people_q(doc):
    return next(c for c in doc["components"] if c["type"] == "people")


def test_an_assignees_question_offers_the_people_it_may_be_answered_with(
        client, admin_id, member_id):
    """It used to offer nobody, which made it a field that did nothing.

    The options are what the control is built from, so an empty list is a
    question with no answer available — clicking it did nothing in the
    editor, in the preview and on the published page alike.
    """
    bid, _fid, tok = _with_assignees(client, admin_id, "אחראים נפתח")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    q = _people_q(client.get(f"/api/public/forms/{tok}", headers=AS(member_id)).json())
    assert member_id in [o["value"] for o in q["options"]]
    assert all(o["label"] for o in q["options"]), "a person with no name to show"
    assert all(isinstance(o["value"], int) for o in q["options"]), (
        "an id is what _can_be_assigned compares, and it compares to a number")


def test_the_member_list_still_does_not_reach_anybody_the_board_does_not_know(
        client, admin_id, member_id, guinea_id):
    """The line the form has always held, now that there is a list to hold back.

    A member may name a member — they can see that list in the app anyway.
    A stranger on a public link, and a signed-in account that is not on this
    board, get an empty question and no names at all: "מילוי טופס אינו מעניק
    גישה ללוח" is the same rule it was.
    """
    bid, _fid, tok = _with_assignees(client, admin_id, "אחראים נסגר")
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "editor"})
    assert _people_q(client.get(f"/api/public/forms/{tok}",
                                headers=AS(member_id)).json()).get("options")
    for who, headers in (("a stranger", ANON),
                         ("a signed-in outsider", AS(guinea_id))):
        doc = client.get(f"/api/public/forms/{tok}", headers=headers).json()
        assert not _people_q(doc).get("options"), who
        blob = json.dumps(doc, ensure_ascii=False)
        for u in client.get("/api/users", headers=AS(admin_id)).json():
            assert (u.get("name") or "@@") not in blob, f"{who} was told a name"


def test_the_builder_sees_the_picker_in_their_own_preview(client, admin_id):
    """The preview is the published page, so it is the published page's list —
    and the person building the board's form is on the board by definition."""
    _bid, fid, _tok = _with_assignees(client, admin_id, "אחראים בתצוגה")
    doc = client.get(f"/api/forms/{fid}/preview", headers=AS(admin_id)).json()
    assert admin_id in [o["value"] for o in _people_q(doc)["options"]]


# What the renderer draws only for the person BUILDING the form: the drag
# grip, the marks on a hidden or orphaned question, the greying that says a
# tick-list on the canvas is a drawing rather than a control, and the
# stand-ins for the column types a form cannot collect at all — in fill mode
# those are refused outright (see FILLABLE), so a respondent never meets one.
# A respondent is never in that mode, so the public page rightly has no rule
# for these.
#
# One of them, fv-opt-off, is drawn only when `live` is false — and all three
# of the product's call sites pass live (editor canvas, preview, public page),
# so nothing a user can open emits it today. It is kept on this list, and the
# non-live branch is kept under test, as the RENDERER's contract rather than
# as a look somebody can reach: `live` exists precisely so that a surface can
# ask for a drawing, and the day one does, the drawing has to still be styled.
# Nobody should read this set as a list of things on screen.
_EDITOR_ONLY = {"fv-bgrip", "fv-hid-t", "fv-gone-t", "fv-opt-off", "fv-stars"}

# …and these are not a look at all. A marker class carries a FACT about the
# block that code reads back off the element — fv-files-off is how blockedWhy
# finds the question a form cannot take a file for — and the element's
# appearance comes from the classes beside it. A stylesheet rule for one would
# be the odd thing, so the rule below exempts them and the test demands the
# thing that makes them legitimate instead: somebody has to be reading it.
_MARKERS = {"fv-files-off"}


def test_the_pages_both_style_every_class_the_one_renderer_emits():
    """Two stylesheets, one renderer — a class only one of them knows about
    is how the editor's form and the published one quietly drift apart. The
    exceptions are listed above rather than inferred, so adding one is a
    decision somebody makes and not a rule that quietly stops holding."""
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    # Read out of the class attributes and not off the whole file, and
    # through the interpolation rather than around it: a name that only
    # appears inside a `${...}` — which is where every conditional class
    # lives, fv-opt-off included — is exactly the one nobody styles.
    seen = set()
    for attr in re.findall(r'class="([^"]*)"', PAPER):
        for name in re.findall(r"fv-[a-z0-9-]+", attr):
            seen.add(name)
            if name in _MARKERS:
                continue
            assert f".{name}" in index, f"index.html has no rule for {name}"
            if name not in _EDITOR_ONLY:
                assert f".{name}" in PAGE, f"public-form.html has no rule for {name}"
    assert _EDITOR_ONLY <= seen, (
        f"listed as editor-only but no longer drawn: {_EDITOR_ONLY - seen}")
    # A marker nobody reads is a class that does nothing, which is how this
    # exemption would turn into a hole: it would excuse any unstyled name.
    for name in _MARKERS:
        assert name in seen, f"listed as a marker but no longer drawn: {name}"
        assert re.search(rf"contains\(['\"]{re.escape(name)}['\"]\)", PAPER + index), (
            f"{name} is styled by nobody and read by nobody — it marks nothing")


# The names the test above cannot see. `fv-blk-${c.kind}` reads out of the
# attribute as the bare stem "fv-blk-", which is a substring of .fv-blk-heading
# and so passes however many kinds go unstyled; and the state a block is in —
# selected, hidden, orphaned — is not fv- prefixed at all, so the scan skips
# it entirely.
#
# Neither list is written down here. The kinds are the server's own list of
# what a component may be, and the states are read off the renderer's class
# attribute, so a fourth of either arrives in this test on the day it arrives
# in the product rather than on the day somebody remembers this file.
_CONTENT_KINDS = tuple(k for k in M.FORM_COMPONENT_KINDS if k != "question")


def _block_states(paper):
    """The state classes blockHTML can put on a block, read off blockHTML.

    Every one of them is a `${cond?' name':''}` inside the block's class
    attribute, and none is fv- prefixed — which is exactly why the scan above
    cannot see them. The fv- prefixed ones that are written the same way
    (fv-blk-empty) belong to that scan and are left to it.
    """
    out = set()
    for attr in re.findall(r'class="(fv-blk[^"]*)"', paper):
        for name in re.findall(r"\?\s*'\s+([a-z][\w-]*)'\s*:\s*''", attr):
            if not name.startswith("fv-"):
                out.add(name)
    return out


def _rule_bodies(css, selector, *, exactly):
    """The declarations of every flat rule that reaches this selector.

    `exactly` is the difference between "this element is styled" and "there
    is a rule somewhere with this name in it". With it on, the selector has
    to END the one it is matched against — optional ancestors and an optional
    pseudo, nothing after — so `.fv-blk.sel .fv-bgrip`, which styles the drag
    grip INSIDE a selected block, does not answer for the block itself. With
    it off, a descendant rule counts: a heading block is styled by
    `.fv-blk-heading h3`, which is the whole of what styling a heading means.
    """
    tail = r"(::?[\w-]+)?$" if exactly else r"(?![\w-])"
    pat = re.compile(r"(^|[\s>+~])" + re.escape(selector) + tail)
    out = []
    for sels, body in re.findall(r"([^{}@;]+)\{([^{}]*)\}", css):
        for one in sels.split(","):
            if pat.search(one.strip()):
                out.append(body)
    return out


def _declares(css, selector, *, exactly=False):
    """…and that at least one of those rules actually sets something."""
    return any(re.search(r"[a-z-]+\s*:[^;{}]", b)
               for b in _rule_bodies(css, selector, exactly=exactly))


def test_the_editor_styles_every_state_and_every_kind_of_block_it_draws():
    """The two halves of the class scan that a substring check cannot make.

    A kind with no rule draws as an unstyled paragraph, and a state with no
    rule means the selected question looks exactly like the other nine — on
    the one screen whose whole job is to show you which one you are editing.

    The state is matched against the selector a browser would match, and the
    rule has to land ON the block. An earlier version of this test accepted
    `.fv-blk.sel` OR the bare word `sel` anywhere in 19,600 lines of mixed
    CSS and JS — where `this.sel=`, `.vis-opt.sel` and `.tl-day.sel` all
    answer for it — so deleting `.fv-blk.sel{…}` from the stylesheet left it
    green. It could not fail, which is worse than not existing.
    """
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert re.search(r"fv-blk-\$\{c\.kind\}", PAPER), (
        "the block no longer carries its kind as a class, so none of the rules "
        "below can reach it whatever the stylesheet says")
    for kind in _CONTENT_KINDS:
        assert _declares(index, f".fv-blk-{kind}"), \
            f"index.html has no rule for a {kind} block"
    states = _block_states(PAPER)
    assert states, "blockHTML marks no state on a block at all — has it been rewritten?"
    for state in sorted(states):
        assert _declares(index, f".fv-blk.{state}", exactly=True), (
            f"index.html has no rule for a block in the {state} state: it is "
            f"drawn exactly like every other block on the canvas")


def test_a_people_question_is_one_a_respondent_is_allowed_to_answer():
    """FILLABLE is the renderer's own list of what a form may collect, and a
    type missing from it is refused in words on the fill surfaces however
    well the server sends it. אחראים was refused there for exactly that
    reason, which is a question nobody could answer.

    What the control then LOOKS like — a tick box per person, carrying the id
    as a number — is not asserted by reading the source for it. The renderer
    is run instead, in tests/frontend/form_controls_live.mjs, where the
    markup it really produces and what collect() really returns can both be
    looked at; a regex over a window of the file pins the shape of today's
    code and says nothing about either.
    """
    fillable = re.search(r"FILLABLE:\s*\[(.*?)\]", PAPER, re.S).group(1)
    assert "'people'" in fillable, "a people question is still refused at fill time"


# ── מי נכנס ──────────────────────────────────────────────────────────

def test_an_anonymous_respondent_opens_a_public_form(client, admin_id):
    _bid, _f, tok = _live(client, admin_id, "אנונימי")
    assert client.get(f"/forms/{tok}").status_code == 200
    assert client.get(f"/api/public/forms/{tok}", headers=ANON).status_code == 200


def test_a_members_only_form_sends_somebody_to_sign_in_and_back(client, admin_id):
    _bid, _f, tok = _live(client, admin_id, "מחוברים", access="AUTHENTICATED")
    r = client.get(f"/api/public/forms/{tok}", headers=ANON)
    assert r.status_code == 401
    d = r.json()["detail"]
    assert isinstance(d, dict), d
    assert d["message"]
    # the path travels url-encoded inside the query, whichever door it is
    import urllib.parse as _u
    back = f"/forms/{tok}"
    assert back in _u.unquote(d["login_url"]), d["login_url"]
    # whatever the deployment's door is, it comes back HERE
    assert d["login_url"].startswith(("/auth/login", "/.auth/login", "/")), d["login_url"]
    # the page follows it rather than drawing a button nobody needs
    assert "location.replace(url)" in PAGE


def test_the_login_url_cannot_be_turned_into_an_open_redirect():
    assert cityos_main._login_url("//evil.example") == cityos_main._login_url("/")
    assert "evil" not in cityos_main._login_url("https://evil.example")


def test_filling_a_form_in_still_grants_nothing(client, admin_id, guinea_id):
    bid, f, tok = _live(client, admin_id, "בלי גישה")
    q = client.get(f"/api/public/forms/{tok}", headers=ANON).json()["components"][0]
    assert client.post(f"/api/public/forms/{tok}/submit",
                       json={"answers": {str(q["id"]): "פנייה"}},
                       headers=AS(guinea_id)).status_code == 200
    assert client.get(f"/api/boards/{bid}", headers=AS(guinea_id)).status_code == 403
    with Session(cityos_main.engine) as db:
        assert cityos_main._board_role(db, bid, guinea_id) is None


# ── קבצים ────────────────────────────────────────────────────────────

def test_a_respondent_can_attach_a_file_and_it_lands_on_the_record(client, admin_id):
    bid = _board(client, admin_id, "קבצים")
    cid = _col(client, bid, admin_id, "צרופה", "files")
    f = client.post(f"/api/boards/{bid}/forms", json={}, headers=AS(admin_id)).json()
    q = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": cid, "label": "צרופה"},
                    headers=AS(admin_id)).json()
    t = client.post(f"/api/forms/{f['id']}/components",
                    json={"kind": "question", "field_key": "title", "label": "נושא"},
                    headers=AS(admin_id)).json()
    client.patch(f"/api/forms/{f['id']}", json={"access": "PUBLIC_LINK"}, headers=AS(admin_id))
    client.patch(f"/api/forms/{f['id']}", json={"status": "PUBLISHED"}, headers=AS(admin_id))
    tok = client.get(f"/api/forms/{f['id']}", headers=AS(admin_id)).json()["public_token"]

    up = client.post(f"/api/public/forms/{tok}/upload", headers=ANON,
                     files={"file": ("note.txt", b"hello", "text/plain")})
    assert up.status_code == 200, up.text
    # the token, and the file's own facts back — nothing about the board,
    # the form's internals or where the bytes went
    assert set(up.json()) == {"token", "name", "size", "type"}, up.json()
    assert "url" not in up.json(), "the respondent is handed a way to read it back"

    r = client.post(f"/api/public/forms/{tok}/submit", headers=ANON,
                    json={"answers": {str(t["id"]): "עם קובץ",
                                      str(q["id"]): [up.json()["token"]]}})
    assert r.status_code == 200, r.text
    task = [x for x in client.get(f"/api/boards/{bid}").json()["tasks"]
            if x["title"] == "עם קובץ"][0]
    files = task["custom_fields"][cid]
    assert len(files) == 1 and files[0]["name"] == "note.txt"
    assert files[0]["url"].startswith("/api/files/")


def test_an_upload_is_refused_where_it_should_be(client, admin_id):
    _bid, f, tok = _live(client, admin_id, "העלאות")
    assert client.post(f"/api/public/forms/{tok}/upload", headers=ANON,
                       files={"file": ("x.exe", b"MZ", "application/x-msdownload")}
                       ).status_code == 400
    assert client.post(f"/api/public/forms/{tok}/upload", headers=ANON,
                       files={"file": ("x.svg", b"<svg/>", "image/svg+xml")}
                       ).status_code == 400
    assert client.post(f"/api/public/forms/{tok}/upload", headers=ANON,
                       files={"file": ("empty.txt", b"", "text/plain")}
                       ).status_code == 400
    # and not at all once the form is closed
    client.patch(f"/api/forms/{f['id']}", json={"status": "DISABLED"}, headers=AS(admin_id))
    assert client.post(f"/api/public/forms/{tok}/upload", headers=ANON,
                       files={"file": ("ok.txt", b"hi", "text/plain")}).status_code == 410


# ── לוגו ─────────────────────────────────────────────────────────────

def test_the_logo_is_reachable_without_an_account_and_only_the_logo_is(client, admin_id):
    _bid, f, tok = _live(client, admin_id, "לוגו ציבורי")
    up = client.post("/api/upload", headers=AS(admin_id),
                     files={"file": ("logo.png", b"\x89PNG\r\n\x1a\n", "image/png")})
    logo = up.json()["url"].rsplit("/", 1)[-1]
    client.patch(f"/api/forms/{f['id']}", json={"logo_token": logo, "show_logo": True},
                 headers=AS(admin_id))

    r = client.get(f"/api/public/forms/{tok}/logo", headers=ANON)
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/")
    assert r.headers["x-content-type-options"] == "nosniff"
    # the ordinary attachment route still needs an account — this one serves
    # exactly the file the form names and nothing a caller can choose
    assert client.get(f"/api/files/{logo}", headers=ANON).status_code == 401
    client.patch(f"/api/forms/{f['id']}", json={"show_logo": False}, headers=AS(admin_id))
    assert client.get(f"/api/public/forms/{tok}/logo", headers=ANON).status_code == 404


# ── העלאה בדף: התקדמות, הצלחה, שגיאה, הסרה ──────────────────────────

def test_the_page_shows_an_upload_going_up():
    """A 9MB file over a phone connection is the case this exists for."""
    assert "XMLHttpRequest" in PAGE, "fetch cannot report upload progress"
    assert "x.upload.onprogress" in PAGE
    assert "fv-bar" in PAGE and "fv-file-pc" in PAGE, "there is no progress to see"


def test_the_page_shows_what_happened_to_each_file():
    assert "fv-file done" in PAGE and "fa-circle-check" in PAGE, "success is not shown"
    assert "fv-file err" in PAGE and "ההעלאה נכשלה" in PAGE, "failure is not shown"
    # a failed file stays on screen with its reason rather than flashing past
    assert "function fail(" in PAGE


def test_a_picked_file_can_be_taken_off_before_sending():
    assert "הסרת הקובץ" in PAGE, "there is no way to remove a file"
    assert "_tokens.splice" in PAGE
    # removed from the form, not deleted from the server — there is no
    # delete-by-id a stranger could call, and the sweeper collects it
    assert "/upload" in PAGE and "method:'DELETE'" not in PAGE


def test_the_page_checks_the_policy_before_sending_bytes():
    for mark in ("p.maxBytes", "p.per", "p.types", "p.totalBytes"):
        assert mark in PAGE, f"the page does not check {mark}"
    assert "DOC.uploads" in PAGE, "the limits are a second copy rather than the server's"


# ── שליחה: לחיצה אחת, ערכים נבדקים, false ו‎-0 נשמרים ───────────────

def test_the_page_cannot_send_twice_at_once():
    """Two guards, because they catch different things: the disabled button
    stops a second click, and the flag stops a second Enter in a text field —
    which never touches the button at all."""
    assert "let DOC = null, sending = false" in PAGE
    assert "if (sending || !DOC) return;" in PAGE
    assert "btn.disabled = true" in PAGE


def test_the_page_names_the_attempt_so_a_retry_is_not_a_second_record():
    assert "submission_id: SUBMISSION" in PAGE, "a retry would create a second record"
    assert "newSubmissionId" in PAGE
    # minted when the form is drawn, not per send — a retry of the SAME send
    # has to carry the same id
    draw = PAGE[PAGE.index("function draw(){"):PAGE.index("function wireFiles")]
    assert "SUBMISSION = newSubmissionId();" in draw
    send = PAGE[PAGE.index("async function send(){"):PAGE.index("function banner(")]
    assert "newSubmissionId" not in send, "a retry mints a new id and duplicates"


def test_the_page_checks_the_values_before_the_round_trip():
    assert "badValue" in PAPER, "nothing is checked before sending"
    for t in ("email", "phone", "number", "date", "dropdown"):
        assert t in PAPER
    # …and shows the reason beside the field it belongs to
    assert "bad.forEach(x => fieldError(x.id, x.why))" in PAGE


def test_false_and_zero_are_answers_on_the_way_out_too():
    collect = PAPER[PAPER.index("collect(doc, root){"):PAPER.index("badValue(c, val){")]
    assert "val = !!el.checked" in collect, "an unticked box is sent as nothing"
    assert "const empty =" in collect, "emptiness is inferred from truthiness"
    # the CODE, not the comment that explains why it is written this way
    code = re.sub(r"/\*.*?\*/", "", collect, flags=re.S)
    assert "if(!val)" not in code and "if (!val)" not in code
