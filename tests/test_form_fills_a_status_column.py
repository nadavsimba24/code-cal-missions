"""עמודת סטטוס נענית מתוך טופס — גם כשאין לה אוצר מילים משלה.

Reported on a board whose "עדיפות" is a column of type status: the question
could not be answered from the form.

A status column born from the board's "+" is handed the default vocabulary
outright and stores it, so most columns carry their own list. A column that
arrives WITHOUT one — imported from a monday export whose status column was
empty and whose file carried no column definitions, or made before columns
had a vocabulary at all — has `options` of None, and the two halves of the
product then disagreed about what that column offers:

  · the grid falls back to STATUS_OPTS in statusColOpts, draws the five
    words, and lets anybody pick one;
  · the form editor's canvas falls back the same way — optionsFor reads
    statusColOpts — so the question PREVIEWED correctly, with all five;
  · the published form's options come from the server, which had no such
    list anywhere. It served `options: null`, so the page drew a select
    holding only "—", and the validator — reading the same empty list —
    refused every answer with "הערך אינו אחת האפשרויות".

A question nobody could answer, in a form that looked right while being
designed. The vocabulary now lives on the server too, in STATUS_COL_FALLBACK,
and _status_col_vocab is the one function both the offer and the check read,
so they cannot drift apart again.

An option of the default list has no id — it is not IN the column, so there
is nothing for a cell to point at — and the cell written against it carries
the label and the colour. That is not a special case invented for forms: it
is exactly what pickStatusCell writes in the browser for the same pick.
"""
import pathlib
import re
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import main as cityos_main  # noqa: E402
from models import Task  # noqa: E402

SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _board(client, admin_id, name="לוח פניות"):
    return client.post("/api/boards",
                       json={"actor_id": admin_id, "name": name}).json()["id"]


def _col(client, bid, admin_id, spec):
    cur = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    r = client.patch(f"/api/boards/{bid}",
                     json={"actor_id": admin_id, "columns": cur + [spec]})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json()["columns"] if c.get("title") == spec["title"])


def _question(client, fid, admin_id, key, label):
    r = client.post(f"/api/forms/{fid}/components?user_id={admin_id}",
                    json={"kind": "question", "field_key": str(key), "label": label})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def form_on_a_bare_status_column(client, admin_id):
    """The board from the report: "עדיפות" is a status column that never got
    a vocabulary of its own."""
    bid = _board(client, admin_id)
    col = _col(client, bid, admin_id, {"type": "status", "title": "עדיפות"})
    fid = client.post(f"/api/boards/{bid}/forms?user_id={admin_id}",
                      json={"title": "טופס פנייה"}).json()["id"]
    title_q = _question(client, fid, admin_id, "title", "נושא")
    col_q = _question(client, fid, admin_id, col, "עדיפות")
    try:
        yield bid, col, fid, title_q, col_q
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


def _offered(client, fid, admin_id, label="עדיפות"):
    p = client.get(f"/api/forms/{fid}/preview?user_id={admin_id}").json()
    q = next(c for c in p["components"] if c.get("label") == label)
    return q["type"], (q.get("options") or [])


# ── the column has nothing of its own ─────────────────────────────────────
def test_the_board_stores_no_vocabulary_for_it(client, admin_id,
                                               form_on_a_bare_status_column):
    """The premise of everything below, stated rather than assumed: this is a
    real state a column can be in, and it is the state the report came from."""
    bid, col, _fid, _t, _q = form_on_a_bare_status_column
    cols = client.get(f"/api/boards/{bid}?user_id={admin_id}").json()["columns"]
    assert next(c for c in cols if c["id"] == col).get("options") is None


def test_the_form_offers_the_words_the_board_offers(client, admin_id,
                                                    form_on_a_bare_status_column):
    """It used to offer nothing at all — a select holding only "—"."""
    _bid, _col, fid, _t, _q = form_on_a_bare_status_column
    kind, opts = _offered(client, fid, admin_id)
    assert kind == "status"
    assert [o["label"] for o in opts] == [o["label"]
                                          for o in cityos_main.STATUS_COL_FALLBACK]


def test_an_answer_from_that_list_is_accepted(client, admin_id,
                                              form_on_a_bare_status_column):
    """The whole of the report: the question can be answered. A preview
    submit validates without making an item, which is what makes it the right
    place to ask whether the ANSWER is acceptable."""
    _bid, _col, fid, title_q, col_q = form_on_a_bare_status_column
    _kind, opts = _offered(client, fid, admin_id)
    r = client.post(f"/api/forms/{fid}/preview/submit?user_id={admin_id}",
                    json={"answers": {str(title_q): "נזילה",
                                      str(col_q): opts[0]["value"]}})
    assert r.status_code == 200, r.text


def test_the_answer_reaches_the_cell_in_the_shape_the_grid_writes(
        client, admin_id, form_on_a_bare_status_column):
    """{label, color} and an id of None — the same thing pickStatusCell
    writes for a pick off the default list, so the cell the form makes is
    indistinguishable from one somebody typed into the board."""
    bid, col, fid, title_q, col_q = form_on_a_bare_status_column
    tok = client.patch(f"/api/forms/{fid}?user_id={admin_id}",
                       json={"status": "PUBLISHED", "access": "PUBLIC_LINK"})
    assert tok.status_code == 200, tok.text
    token = client.get(f"/api/forms/{fid}?user_id={admin_id}").json()["public_token"]
    _kind, opts = _offered(client, fid, admin_id)
    want = next(o for o in opts if o["label"] == "תקוע")
    r = client.post(f"/api/public/forms/{token}/submit",
                    json={"answers": {str(title_q): "מדרכה שבורה",
                                      str(col_q): want["value"]}})
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        made = db.query(Task).filter(Task.board_id == bid,
                                     Task.title == "מדרכה שבורה").first()
        assert made is not None, "the form made no item"
        cell = (made.custom_fields or {}).get(col)
    assert cell is not None, "the answer did not reach the cell"
    assert cell["label"] == "תקוע"
    assert cell["id"] is None
    assert cell["color"] == "#DB2D4C"


def test_a_word_that_is_not_in_the_list_is_still_refused(
        client, admin_id, form_on_a_bare_status_column):
    """Falling back is not the same as accepting anything."""
    _bid, _col, fid, title_q, col_q = form_on_a_bare_status_column
    r = client.post(f"/api/forms/{fid}/preview/submit?user_id={admin_id}",
                    json={"answers": {str(title_q): "x", str(col_q): "משהו אחר"}})
    assert r.status_code == 400, r.text
    assert "אינו אחת האפשרויות" in r.text


# ── a column that does have its own list is untouched ─────────────────────
def test_a_column_with_its_own_vocabulary_still_answers_by_option_id(client, admin_id):
    """The fallback must not stand in front of a column that has a list. A
    cell on such a column POINTS at the option, which is what carries a later
    rename into every cell already on it."""
    bid = _board(client, admin_id, "לוח עם אוצר מילים")
    col = _col(client, bid, admin_id,
               {"type": "status", "title": "עדיפות",
                "options": [{"id": "o_high", "label": "גבוהה", "color": "#e2445c"}]})
    fid = client.post(f"/api/boards/{bid}/forms?user_id={admin_id}",
                      json={"title": "ט"}).json()["id"]
    t = _question(client, fid, admin_id, "title", "נושא")
    q = _question(client, fid, admin_id, col, "עדיפות")
    try:
        kind, opts = _offered(client, fid, admin_id)
        assert kind == "status"
        assert opts == [{"value": "o_high", "label": "גבוהה"}]
        client.patch(f"/api/forms/{fid}?user_id={admin_id}",
                     json={"status": "PUBLISHED", "access": "PUBLIC_LINK"})
        token = client.get(f"/api/forms/{fid}?user_id={admin_id}").json()["public_token"]
        r = client.post(f"/api/public/forms/{token}/submit",
                        json={"answers": {str(t): "עם מזהה", str(q): "o_high"}})
        assert r.status_code == 200, r.text
        with Session(cityos_main.engine) as db:
            made = db.query(Task).filter(Task.board_id == bid,
                                         Task.title == "עם מזהה").first()
            cell = (made.custom_fields or {}).get(col)
        assert cell == {"id": "o_high", "label": "גבוהה", "color": "#e2445c"}
    finally:
        client.delete(f"/api/boards/{bid}?user_id={admin_id}")


# ── the two lists are the same list ───────────────────────────────────────
def test_the_server_falls_back_to_the_words_the_browser_falls_back_to():
    """STATUS_OPTS in index.html and STATUS_COL_FALLBACK here are one
    vocabulary written twice — once for the grid and the form editor, once
    for the form the respondent sees. Written twice they can disagree, and a
    disagreement here is a form that offers a word the board does not have.
    Compared rather than trusted, the way test_filter_ast compares the two
    operator tables."""
    i = SRC.index("const STATUS_OPTS=[")
    block = SRC[i:SRC.index("];", i)]
    pairs = re.findall(r"\{label:'([^']+)',\s*color:'(#[0-9A-Fa-f]{6})'\}", block)
    assert pairs, block[:200]
    assert pairs == [(o["label"], o["color"]) for o in cityos_main.STATUS_COL_FALLBACK]


def test_one_function_answers_both_what_is_offered_and_what_is_accepted():
    """They were two copies of `_status_col_options(col.get("options")) or []`
    and that is how they came to differ from the browser in the first place."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert src.count("_status_col_vocab(") >= 3    # the def, the offer, the check
