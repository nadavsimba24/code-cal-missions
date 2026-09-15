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


def _operations():
    """The two queries in the .graphql file, verbatim and comment-free."""
    parts = re.split(r"^# ── (?:page one|every page after it) ─+\n", SRC, flags=re.M)
    assert len(parts) == 3, "the file no longer has its two banner-separated queries"
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
    page1, pageN = _operations()
    # the division into groups: the board's own list, and each item's group
    assert "groups { id title }" in page1
    assert page1.count("group { id title }") >= 1
    assert "group { id title }" in pageN, "the pages after the first lose the groups"
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
    assert len(c["item"]) == 2
    assert "{{boardId}}" in c["item"][0]["request"]["body"]["graphql"]["variables"]
    assert "{{cursor}}" in c["item"][1]["request"]["body"]["graphql"]["variables"]
