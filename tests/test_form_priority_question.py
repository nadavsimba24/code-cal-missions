"""«עדיפות» כשאלה בטופס — מוצעת, נענית, ונשמרת.

The plan names five built-in fields a form may ask for — `title`, `assignees`,
`status`, `priority`, `due_date` — and four of them worked. The server offered
priority as one of them, served it with the board's own priority vocabulary,
and checked a submitted answer against that vocabulary. The renderer's two
places that draw a vocabulary and validate against one both named it beside
`status`.

Only the list of what a form can COLLECT did not. So the question reached the
page and drew "שדה מסוג זה אינו נתמך במילוי טופס" over something the whole
rest of the stack was ready to answer — a refusal written for a column a form
genuinely cannot take, shown for one it can.

A priority is a labelled, board-defined vocabulary: the same shape as a
status, which is why FIELD_MATRIX has called its kind "status" all along.
"""
import pathlib
import subprocess

from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
import sys  # noqa: E402
sys.path.insert(0, str(ROOT / "backend"))
import main as cityos_main  # noqa: E402
from models import Task  # noqa: E402

PAPER = ROOT / "frontend" / "form-paper.js"


def _form(client, admin_id, name="טופס עדיפות"):
    bid = client.post("/api/boards",
                      json={"name": name, "user_id": admin_id}).json()["id"]
    fid = client.post(f"/api/boards/{bid}/forms?user_id={admin_id}",
                      json={"title": name}).json()["id"]
    return bid, fid


def _ask(client, fid, admin_id, key, label=None):
    r = client.post(f"/api/forms/{fid}/components?user_id={admin_id}",
                    json={"kind": "question", "field_key": key,
                          "label": label or key})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _publish(client, fid, admin_id):
    r = client.patch(f"/api/forms/{fid}?user_id={admin_id}",
                     json={"status": "PUBLISHED", "access": "PUBLIC_LINK"})
    assert r.status_code == 200, r.text
    return client.get(f"/api/forms/{fid}?user_id={admin_id}").json()["public_token"]


# ── the server has always been ready ──────────────────────────────────────
def test_the_form_offers_it_with_the_boards_own_priorities(client, admin_id):
    bid, fid = _form(client, admin_id)
    _ask(client, fid, admin_id, "priority", "דחיפות")
    p = client.get(f"/api/forms/{fid}/preview?user_id={admin_id}").json()
    q = next(c for c in p["components"] if c.get("label") == "דחיפות")
    assert q["type"] == "priority", q
    labels = {o["label"] for o in q["options"]}
    assert labels, q
    with Session(cityos_main.engine) as db:
        b = db.query(cityos_main.Board).filter(cityos_main.Board.id == bid).first()
        assert labels == {x["label"] for x in cityos_main._board_priorities(b)}


def test_an_answer_outside_the_vocabulary_is_refused(client, admin_id):
    _bid, fid = _form(client, admin_id)
    t = _ask(client, fid, admin_id, "title")
    p = _ask(client, fid, admin_id, "priority")
    r = client.post(f"/api/forms/{fid}/preview/submit?user_id={admin_id}",
                    json={"answers": {str(t): "x", str(p): "nonsense"}})
    assert r.status_code == 400, r.text
    assert "אינו אחת האפשרויות" in r.text, r.text


def test_a_submitted_priority_reaches_the_item(client, admin_id):
    """The whole point: a stranger answers the question and the item is born
    with that priority."""
    bid, fid = _form(client, admin_id)
    t = _ask(client, fid, admin_id, "title")
    p = _ask(client, fid, admin_id, "priority")
    tok = _publish(client, fid, admin_id)
    r = client.post(f"/api/public/forms/{tok}/submit",
                    json={"answers": {str(t): "פנייה דחופה", str(p): "critical"}})
    assert r.status_code == 200, r.text
    with Session(cityos_main.engine) as db:
        made = (db.query(Task).filter(Task.board_id == bid,
                                      Task.title == "פנייה דחופה").first())
    assert made is not None, "the form made no item"
    assert cityos_main._task_priority_key(made) == "critical"


# ── and the page draws it ─────────────────────────────────────────────────
def _render(payload):
    """The real renderer, run rather than read — the same trick the .mjs
    harnesses use."""
    script = ROOT / "tests" / "frontend" / "_fp_tmp.mjs"
    script.write_text(
        "import fs from 'fs';\n"
        f"const FormPaper=new Function(fs.readFileSync({str(PAPER)!r},'utf8')"
        "+';return FormPaper;')();\n"
        f"console.log(FormPaper.inputHTML({payload}, {{fill:true}}));\n",
        encoding="utf-8")
    try:
        r = subprocess.run(["node", str(script)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout
    finally:
        script.unlink(missing_ok=True)


def test_a_priority_question_draws_a_control_and_not_a_refusal():
    one = ("{id:1,kind:'question',label:'x',type:'%s',"
           "options:[{value:'critical',label:'קריטית'}]}")
    for t in ("status", "priority"):
        out = _render(one % t)
        assert "fv-unsupported" not in out, (t, out)
        assert "<select" in out and "קריטית" in out, (t, out)


def test_the_refusal_is_still_there_for_a_column_a_form_cannot_take():
    """The message is not removed — it is written for a column a form
    genuinely cannot collect, and a mirror is one."""
    out = _render("{id:1,kind:'question',label:'x',type:'mirror'}")
    assert "fv-unsupported" in out, out


def test_the_renderer_names_it_everywhere_it_names_a_status():
    """Three places: what can be collected, what draws a vocabulary, and what
    validates against one. It was in two of the three, which is why this
    failed on the page and nowhere else."""
    src = PAPER.read_text(encoding="utf-8")
    i = src.index("  FILLABLE:")
    assert "'priority'" in src[i:src.index("],", i)], src[i:i + 200]
    assert "type==='status'||type==='priority'||type==='dropdown'" in src
    assert "(t === 'status' || t === 'priority')" in src
