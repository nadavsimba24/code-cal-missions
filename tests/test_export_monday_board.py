"""The export run, end to end, against a monday that answers like monday does.

Doing this by hand in Postman is five kinds of place to lose a page: a cursor
copied with a character missing, a response saved half-downloaded, the history
walked until somebody loses count, a board exported with an empty variable so
monday answers with the whole account. The script exists to take those away,
which only helps if it walks the pages correctly — so a fake monday is stood
up here and made to behave the way the real one does on the boards that caused
each of those failures: more items than one page holds, a log with no count to
walk against, and a log page refused for complexity.
"""
import http.server
import importlib.util
import json
import pathlib
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "export_monday_board", ROOT / "scripts" / "export_monday_board.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


exporter = _load()


# ── a monday that answers like monday ──────────────────────────────────────
class FakeMonday:
    """Serves the three queries. `script` decides how it behaves."""

    def __init__(self, items_pages=1, log_pages=1, log_size=None,
                 refuse_complexity=0, items_count=None):
        self.items_pages = items_pages
        self.log_pages = log_pages
        self.log_size = log_size
        self.refuse_complexity = refuse_complexity
        self.items_count = items_count
        self.seen = []                 # (operation, variables) in order
        self.limits = []               # the activity_logs limit of each log call

    def answer(self, query, variables):
        self.seen.append((self._op(query), variables))
        if "next_items_page" in query:
            n = len(
                [1 for op, _ in self.seen if op == "next"])
            last = n + 1 >= self.items_pages
            return {"data": {"next_items_page": {
                "cursor": None if last else f"cursor-{n + 1}",
                "items": [{"id": str(100 + n), "name": f"פריט עמוד {n + 1}",
                           "group": {"id": "g1", "title": "קבוצה", "color": "#e2445c"}}]}}}
        if "activity_logs" in query:
            limit = int(query.split("activity_logs(limit: ", 1)[1].split(",", 1)[0])
            self.limits.append(limit)
            if self.refuse_complexity > 0:
                self.refuse_complexity -= 1
                return {"errors": [{"message": "REQUEST_MAX_COMPLEXITY_EXCEEDED, cost 5125801"}]}
            page = int(variables.get("page") or 1)
            size = self.log_size if self.log_size is not None else limit
            n = size if page < self.log_pages else 1      # a short page is the end
            return {"data": {"boards": [{"id": variables["boardId"][0],
                                         "activity_logs": [{"id": f"l{page}-{i}"}
                                                           for i in range(n)]}]},
                    "account": {}}
        return {"data": {"boards": [{
            "id": variables["boardId"][0], "name": "לוח הבדיקה",
            "items_count": self.items_count,
            "groups": [{"id": "g1", "title": "קבוצה", "color": "#e2445c"}],
            "columns": [{"id": "c1", "title": "טקסט", "type": "text"}],
            "items_page": {"cursor": None if self.items_pages == 1 else "cursor-1",
                           "items": [{"id": "1", "name": "פריט",
                                      "group": {"id": "g1", "title": "קבוצה",
                                                "color": "#e2445c"}}]},
        }], "users": [{"id": "1", "name": "רינה", "email": "r@x.co.il"}]}}

    @staticmethod
    def _op(q):
        return ("next" if "next_items_page" in q
                else "log" if "activity_logs" in q else "page1")


@pytest.fixture
def monday(monkeypatch):
    """A fake monday on a real socket, with the script pointed at it."""
    state = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["auth"] = self.headers.get("Authorization")
            out = json.dumps(state["fake"].answer(body["query"], body["variables"])).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(exporter, "API", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setattr(exporter, "PAUSE", 0)

    def run(fake, **kw):
        state["fake"] = fake
        q1, qlog, qnext = exporter.queries()
        return exporter.export_board("123", "tok", q1, qlog, qnext, **kw)

    yield run, state
    srv.shutdown()


# ── the queries it sends ───────────────────────────────────────────────────
def test_the_queries_are_the_ones_the_importer_documents():
    """Read from backend/monday_export.graphql, never copied into the script —
    an export produced by a query one revision behind is how six formula
    columns and two connect columns arrived empty on all 320 items."""
    q1, qlog, qnext = exporter.queries()
    assert "items_page(" in q1 and "groups { id title color }" in q1
    assert "activity_logs(" in qlog and "items_page(" not in qlog
    assert "next_items_page(" in qnext and "group { id title color }" in qnext


def test_the_board_id_is_always_sent(monday):
    """`boards(ids: [])` answers HTTP 200 with the first 25 boards in the
    account. It is the failure monday does not report, and it cost an
    afternoon and 20,064 log rows belonging to other boards."""
    run, _ = monday
    fake = FakeMonday()
    run(fake)
    assert fake.seen, "nothing was sent"
    for op, v in fake.seen:
        if op == "next":
            continue
        assert v.get("boardId") == ["123"], (op, v)


# ── the walks ──────────────────────────────────────────────────────────────
def test_every_page_of_items_is_collected(monday):
    run, _ = monday
    fake = FakeMonday(items_pages=4)
    parts, problems = run(fake, want_history=False)
    assert problems == []
    assert [op for op, _ in fake.seen] == ["page1", "next", "next", "next"]
    assert len(parts) == 4, "a page was left behind the cursor"


def test_the_cursor_is_carried_from_each_answer_to_the_next_request(monday):
    """The character that goes missing when a human copies it."""
    run, _ = monday
    fake = FakeMonday(items_pages=3)
    run(fake, want_history=False)
    cursors = [v.get("cursor") for op, v in fake.seen if op == "next"]
    assert cursors == ["cursor-1", "cursor-2"], cursors


def test_the_history_is_walked_until_a_page_comes_back_short(monday):
    """There is no activity_logs_count. A page short of the limit is the only
    thing that says the log has ended."""
    run, _ = monday
    fake = FakeMonday(log_pages=3, log_size=exporter.LOG_LIMIT)
    parts, problems = run(fake)
    assert problems == []
    pages = [v["page"] for op, v in fake.seen if op == "log"]
    assert pages == [1, 2, 3], pages
    assert len(parts) == 1 + 3


def test_a_log_page_refused_for_complexity_is_halved_not_abandoned(monday):
    """monday answered her 320-item board REQUEST_MAX_COMPLEXITY_EXCEEDED at
    cost 5,125,801 against 5,000,000. A smaller page makes the walk longer and
    nothing else — giving up loses the board's whole history."""
    run, _ = monday
    fake = FakeMonday(refuse_complexity=2)
    parts, problems = run(fake)
    assert problems == []
    assert fake.limits[0] == exporter.LOG_LIMIT
    assert fake.limits[1] == exporter.LOG_LIMIT // 2
    assert fake.limits[2] == exporter.LOG_LIMIT // 4
    assert len(parts) == 2, "the history was dropped instead of retried smaller"


def test_no_history_asks_for_none(monday):
    run, _ = monday
    fake = FakeMonday()
    run(fake, want_history=False)
    assert not [op for op, _ in fake.seen if op == "log"]


# ── what it refuses to call a success ──────────────────────────────────────
def test_a_board_monday_does_not_return_is_a_problem_not_an_empty_file(monday):
    """An id that is wrong, or a board the token cannot see, answers with an
    empty list. Written out, that is a file that imports as a board with
    nothing in it."""
    run, _ = monday

    class Empty(FakeMonday):
        def answer(self, query, variables):
            self.seen.append((self._op(query), variables))
            return {"data": {"boards": []}}

    parts, problems = run(Empty())
    assert parts == []
    assert problems and "123" in problems[0]


def test_a_board_shorter_than_its_own_count_is_said_out_loud(monday, capsys):
    """items_count against what arrived is the arithmetic that turns "did
    everything come?" into a number."""
    run, _ = monday
    run(FakeMonday(items_count=900), want_history=False)
    assert "900" in capsys.readouterr().out


def test_the_token_goes_in_the_header_and_nowhere_else(monday):
    run, state = monday
    fake = FakeMonday()
    run(fake)
    assert state["auth"] == "tok"
