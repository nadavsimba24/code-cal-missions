"""Group — the export query and the collection that runs it say the same thing.

Every "the column is empty" report on a migrated board has had the same cause:
the file was produced by a query that never asked for that column. monday
answers a formula, a mirror and a connect column only in `display_value`, names
the board's group division only under `groups`/`group`, and keeps a formula's
expression only in the column's `settings_str` — a query missing any of them
gets a well-formed response with nothing in it.

`backend/monday_export.graphql` is the query; the Postman collection beside it is
how it actually gets run. A collection that drifts from the file is exactly the
failure this is meant to make impossible: her export was produced by a saved
collection two revisions behind, and six formula columns and two connect columns
arrived empty on all 320 items.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
GRAPHQL = ROOT / "backend" / "monday_export.graphql"
COLLECTION = ROOT / "backend" / "monday_export.postman_collection.json"

SRC = GRAPHQL.read_text(encoding="utf-8")


# The file holds three operations now. The board's history is one of them and
# not a field of the first, because asking for it beside 500 items does not fit
# inside monday's complexity ceiling: her 320-item board came back
# REQUEST_MAX_COMPLEXITY_EXCEEDED at cost 5,125,801 against 5,000,000. Splitting
# it costs nothing — the import reads a file of several responses as the one
# board they describe.
_BANNERS = r"page one|the history, as a request of its own|every page after it"


def _operations():
    """The queries in the .graphql file, verbatim and comment-free."""
    parts = re.split(r"^# ── (?:" + _BANNERS + r") ─+\n", SRC, flags=re.M)
    assert len(parts) == 4, "the file no longer has its three banner-separated queries"
    out = []
    for block in parts[1:]:
        lines = block.splitlines()
        while lines and (lines[0].startswith("#") or not lines[0].strip()):
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        out.append("\n".join(lines))
    return out


def _collection():
    return json.loads(COLLECTION.read_text(encoding="utf-8"))


def _queries_in_collection():
    return [i["request"]["body"]["graphql"]["query"] for i in _collection()["item"]]


def test_the_collection_runs_exactly_the_query_the_importer_reads():
    """Not "contains the same fragments" — identical. Anything looser lets the
    two drift in the one direction that matters."""
    assert _queries_in_collection() == _operations()


def test_the_query_asks_for_everything_a_board_is():
    page1, history, pageN = _operations()
    # the division into groups: the board's own list, and each item's group
    assert "groups { id title color }" in page1
    assert page1.count("group { id title color }") >= 1
    assert "group { id title color }" in pageN, "the pages after the first lose the groups"
    # the three types monday answers only in display_value
    for frag in ("FormulaValue", "MirrorValue", "BoardRelationValue"):
        assert frag in page1 and frag in pageN, frag
    assert page1.count("display_value") >= 3
    # a formula's expression, which lives only in the column's own settings
    assert "settings_str" in page1
    # the conversation, on items and on their sub-items alike
    assert page1.count("text_body") >= 3
    # the attachments, by the link that can actually be fetched
    assert "public_url" in page1 and "public_url" in pageN
    # how many items the board holds, which is the only way to know that 500
    # back out of 687 is half an export rather than a whole one
    assert "items_count" in page1
    # the history: the log itself, and the one thing that turns a monday user id
    # into a person — without it every imported row would read "מערכת"
    assert "activity_logs(" in history and "users {" in history
    assert "items_page(" not in history, "it is split off precisely to stay cheap"
    assert "activity_logs(" not in page1, \
        "asking for the log beside 500 items exceeds monday's complexity ceiling"


def test_the_collection_carries_no_token():
    """A collection is a file people mail each other. A token pasted into one is
    a live key to the whole account, and it travels with every copy."""
    raw = COLLECTION.read_text(encoding="utf-8")
    assert "{{MONDAY_TOKEN}}" in raw
    # a monday token is a JWT: three dot-separated base64 segments starting "eyJ"
    assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", raw), \
        "there is a token in the collection"


def test_the_collection_says_how_to_run_it():
    c = _collection()
    keys = {v["key"] for v in c["variable"]}
    assert {"MONDAY_TOKEN", "boardId", "cursor"} <= keys
    desc = c["info"]["description"]
    for marker in ("cursor", "JSON array", "monday_export.graphql"):
        assert marker in desc, f"the collection does not explain {marker}"
    assert len(c["item"]) == 3
    assert "{{boardId}}" in c["item"][0]["request"]["body"]["graphql"]["variables"]
    assert "{{boardId}}" in c["item"][1]["request"]["body"]["graphql"]["variables"]
    assert "{{logPage}}" in c["item"][1]["request"]["body"]["graphql"]["variables"]
    assert "{{cursor}}" in c["item"][2]["request"]["body"]["graphql"]["variables"]


def test_both_files_say_that_one_request_carries_one_query():
    """The file holds two operations, and a request holding both comes back HTTP
    200 with `operation name is required when multiple operations are defined` —
    no data, and an error that reads like a dead token rather than like a query
    with one query too many. It cost an afternoon: an export that had worked for
    weeks was re-copied after a field was added to the query, and that time the
    whole file went into the box. Both files a person opens have to say so."""
    collection = COLLECTION.read_text(encoding="utf-8")
    for path, raw in ((GRAPHQL, SRC), (COLLECTION, collection)):
        assert "operation name is required" in raw, \
            f"{path.name} does not name the error two operations in one request gives"
        assert "one operation" in raw, \
            f"{path.name} does not say that a request carries one operation"
        assert "collection" in raw.lower(), \
            f"{path.name} does not point at the collection, whose requests hold one each"


def test_the_collection_refuses_to_send_an_empty_boardId():
    """The one failure monday does not report. `boards(ids: [])` — which is what
    an empty collection variable makes of `{"boardId": [{{boardId}}]}` — answers
    HTTP 200 with the first 25 boards in the account. Her history export came
    back that way: 20,064 log entries belonging to twenty-five boards, none of
    them the board she was exporting, and nothing anywhere saying so.

    Postman is the only place this can be caught while it is still cheap, so
    every request that takes a board id checks the variable before it goes and
    checks the answer when it returns."""
    for item in _collection()["item"]:
        if "{{boardId}}" not in item["request"]["body"]["graphql"]["variables"]:
            continue
        scripts = {e["listen"]: "\n".join(e["script"]["exec"]) for e in item.get("event") or []}
        assert "boardId" in scripts.get("prerequest", ""), \
            f"{item['name']} sends whatever is in the variable, empty or not"
        assert "boards.length" in scripts.get("test", ""), \
            f"{item['name']} accepts an answer holding the whole account"
def test_every_request_says_how_much_came_back():
    """A page of 500 looks exactly like a board of 500. The count belongs in
    Postman, where it is still cheap to act on: by the time the file is imported
    the answer is already saved, and a report saying 500 of 687 came is a report
    about an export that has to be run again."""
    items, history, nxt = [
        "\n".join(next(e["script"]["exec"] for e in item["event"] if e["listen"] == "test"))
        for item in _collection()["item"]]
    assert "items_count" in items and "items_page" in items
    assert "activity_logs" in history
    assert "next_items_page" in nxt
    for name, script in (("1", items), ("3", nxt)):
        assert "cursor" in script, f"request {name} says nothing about there being more"


def test_the_query_and_the_collection_both_ask_what_colour_a_group_is():
    """A group's header colour is how a board is read before a word of it is,
    and `color` is the one missing field a response does not look wrong without:
    the groups still arrive, named and in order, wearing colours this app picked
    — so a board whose "דחוף" was red comes across green and it reads as
    somebody's decision rather than as a field nobody asked for. Postman is
    where that is still cheap to catch, so the run says how many groups came
    back with a colour."""
    page1, _history, pageN = _operations()
    assert "groups { id title color }" in page1
    assert "group { id title color }" in page1 and "group { id title color }" in pageN
    script = "\n".join(next(e["script"]["exec"] for e in _collection()["item"][0]["event"]
                            if e["listen"] == "test"))
    assert "g.color" in script and "קבוצות" in script, \
        "the run does not say whether the groups came back with their colours"


def test_the_collection_carries_the_cursor_so_nobody_retypes_it():
    """70 characters of base64 copied by hand, and monday refuses the whole
    request if one of them is wrong. Requests 1 and 3 store what they got, which
    also means request 3 can simply be run again for the next page."""
    items, _history, nxt = _collection()["item"]
    for item in (items, nxt):
        script = "\n".join(next(e["script"]["exec"] for e in item["event"]
                                if e["listen"] == "test"))
        assert "pm.collectionVariables.set('cursor'" in script, \
            f"{item['name']} leaves the cursor to be copied by hand"


def test_the_history_script_counts_against_the_limit_its_own_query_asks_for():
    """The script says "that is the ceiling, ask for page 2" by comparing the
    count to a number. If the query's limit changes and the number does not, it
    says it about the wrong total — and the page that is missing is one nobody
    goes looking for."""
    _page1, history, _nxt = _operations()
    limit = re.search(r"activity_logs\(limit: (\d+)", history).group(1)
    script = "\n".join(next(e["script"]["exec"]
                            for e in _collection()["item"][1]["event"]
                            if e["listen"] == "test"))
    assert limit in script, \
        f"the history script does not count against the limit the query asks for ({limit})"
def test_the_history_walks_its_own_pages_and_adds_them_up():
    """monday has no count for the log — no `activity_logs_count` beside the
    board's `items_count` — so "how many entries are there" has no answer until
    the pages have been walked and summed. Which means the walking is the
    feature: the request asks for the page after the last one on every Send and
    carries the running total, because a person doing that by hand edits the
    query between runs and loses count at page three."""
    history = _operations()[1]
    assert "$page: Int!" in history and "page: $page" in history, \
        "the page is hard-coded, so every page after the first is a manual edit"

    item = _collection()["item"][1]
    keys = {v["key"] for v in _collection()["variable"]}
    assert {"logPage", "logTotal"} <= keys, "the walk has nowhere to keep its place"
    scripts = {e["listen"]: "\n".join(e["script"]["exec"]) for e in item["event"]}
    # it advances, it tallies, and it stops when a page comes back short
    assert "pm.collectionVariables.set('logPage'" in scripts["test"]
    assert "pm.collectionVariables.set('logTotal'" in scripts["test"]
    assert "logPage" in scripts["prerequest"], "a fresh collection starts nowhere"
