"""The advanced filter, as a tree the server can be asked to evaluate.

The board's toolbar filters one question at a time. An advanced filter asks
several at once — "mine, overdue, and not done" — and the shape that holds
that is a tree, because "A and (B or C)" is a different question from
"(A and B) or C" and a flat list cannot tell the two apart.

    group = {"type": "group", "operator": "and" | "or", "rules": [ node, … ]}
    rule  = {"type": "rule", "field": "<id>", "operator": "<op>",
             "value": …, "value2": …}

Nothing here touches the database or the request. It takes the tree and a dict
describing one item, and answers yes or no — which is what makes it testable
against the browser's copy of the same rules, one case at a time.

── Two things this module is careful about ─────────────────────────────────

**Dates belong to the person looking.** "היום" is not a fact about the server.
A board viewed from Israel at 01:30 is on a different day from the UTC clock,
and an item created at 22:30 UTC is already tomorrow's to the person reading
it. So the tokens are never resolved against the server's clock: the request
carries `today` — the client's own local date — and every span is worked out
from that. A value that carries a TIME is converted to the viewer's day using
the offset the client sends, for the same reason.

**Empty means empty.** A NULL in the database and an empty string are the same
nothing to the person looking at the cell, and so is a cell holding a space.
What is NOT empty is 0 and False: a budget of zero is a budget, and an
unticked box is an answer. A truthiness test would file both under "empty" and
hide every zero on the board from anybody filtering for a value.

── And one it is careful about because the tree arrives from outside ───────

It is untrusted input shaped like a program. A tree can be deep, wide, or
self-referential by accident, and evaluating it blindly is an invitation. So
it is parsed before it is run: unknown operators are refused by name, the
depth and the number of rules are capped, and anything that is not one of the
two shapes above is rejected rather than ignored.
"""
import datetime as _dt
import re

MAX_DEPTH = 8          # a tree deeper than this is not a question anybody asked
MAX_RULES = 200        # across the whole tree
GROUP_OPS = ("and", "or")

# The operators each kind of column offers. The same table the browser holds,
# and tests/test_filter_ast.py compares the two rather than trusting that they
# were kept in step by hand.
OPS = {
    "text":   ("eq", "ne", "has", "nhas", "empty", "filled"),
    "status": ("eq", "ne", "empty", "filled"),
    "number": ("eq", "ne", "gt", "lt", "between", "empty", "filled"),
    "people": ("has", "nhas", "empty", "filled"),
    "date":   ("on", "before", "after", "between", "empty", "filled"),
    "check":  ("yes", "no"),
}
ALL_OPS = {o for ops in OPS.values() for o in ops}

# What a column type can be asked about. Mirrors ADV_KINDS in the frontend.
KINDS = {
    "text": "text", "email": "text", "long_text": "text", "phone": "text",
    "status": "status", "dropdown": "status", "priority": "status",
    "number": "number", "rating": "number", "formula": "number",
    "people": "people", "created_by": "people", "assignees": "people",
    "date": "date", "created_at": "date", "timeline": "date", "due": "date",
    "checkbox": "check", "files": "check",
}

DATE_TOKENS = ("today", "yesterday", "tomorrow", "this_week", "next_week",
               "last_week", "this_month", "next_month", "last_month",
               "last_7", "last_30")

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BadFilter(ValueError):
    """The tree is not one this module will run, and the reason is in the text."""


# ── parsing ────────────────────────────────────────────────────────────────
def parse(node, _depth=0, _count=None):
    """Validate the tree and return it normalised. Raises BadFilter.

    Normalised means: a group always has `operator` and `rules`, a rule always
    has `field`, `operator`, `value`, `value2`. Everything downstream can then
    read fields without asking whether they are there.
    """
    if _count is None:
        _count = [0]
    if node is None:
        return None
    if not isinstance(node, dict):
        raise BadFilter("כל צומת בעץ הסינון חייב להיות אובייקט")
    if _depth > MAX_DEPTH:
        raise BadFilter(f"עץ הסינון עמוק מדי (מעל {MAX_DEPTH} רמות)")

    # A group is anything carrying `rules`; the explicit type is accepted and
    # not required, because the browser's own in-memory shape omits it.
    if "rules" in node or node.get("type") == "group":
        op = str(node.get("operator") or node.get("op") or "and").lower()
        if op not in GROUP_OPS:
            raise BadFilter(f"קשר לוגי לא מוכר: {op}")
        raw = node.get("rules")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise BadFilter("rules חייב להיות רשימה")
        kids = [parse(k, _depth + 1, _count) for k in raw]
        return {"type": "group", "operator": op,
                "rules": [k for k in kids if k is not None]}

    _count[0] += 1
    if _count[0] > MAX_RULES:
        raise BadFilter(f"יותר מדי תנאים בסינון (מעל {MAX_RULES})")
    field = node.get("field")
    if not isinstance(field, str) or not field.strip():
        raise BadFilter("תנאי בלי עמודה")
    op = str(node.get("operator") or node.get("op") or "").lower()
    if op not in ALL_OPS:
        raise BadFilter(f"אופרטור לא מוכר: {op or '—'}")
    return {"type": "rule", "field": field.strip(), "operator": op,
            "value": node.get("value", node.get("v")),
            "value2": node.get("value2", node.get("v2"))}


def prune(node, fields):
    """Drop every rule naming a column that is no longer on the board.

    Returns (tree, removed) — the tree without them, and the field ids that
    went. A saved view outlives the board it was saved on, and somebody
    deleting a column turns every view that mentioned it into a question
    about something that does not exist.

    Removing the rule is not the same as letting it answer true, and the
    difference is the whole reason this function exists. Inside an "and"
    group the two are identical. Inside an "or" group they are opposites: a
    rule that answers true makes the group true, so ONE deleted column would
    quietly show the whole board — the filter still on, the badge still
    counting, nothing filtered. Removing it leaves the remaining
    alternatives to decide, which is what whoever wrote them meant.

    A group left empty is dropped for the same reason, one level up.

    A rule naming a PERSON is never pruned here: the column still exists, and
    somebody having left the organisation does not unassign them from what
    they were working on. See the people branch of match_rule.
    """
    removed = []

    def walk(n):
        if not n:
            return None
        if n.get("type") == "group" or "rules" in n:
            kids = [k for k in (walk(x) for x in (n.get("rules") or [])) if k]
            if not kids:
                return None
            return {"type": "group", "operator": n.get("operator", "and"), "rules": kids}
        if n.get("field") in fields:
            return n
        removed.append(n.get("field"))
        return None

    out = walk(node)
    if out is None and node:
        out = {"type": "group", "operator": node.get("operator", "and"), "rules": []}
    return out, removed


def count(node):
    """How many conditions the tree holds — the number on the toolbar badge."""
    if not node:
        return 0
    if node.get("type") == "group" or "rules" in node:
        return sum(count(k) for k in (node.get("rules") or []))
    return 1


# ── dates, in the viewer's day ─────────────────────────────────────────────
def _day(v):
    """A YYYY-MM-DD out of whatever the cell holds, or None.

    A bare date is returned as it is: it names a day, not a moment, and
    putting it through a timezone would move it. Anything carrying a time is
    the caller's business — see `day_in_zone`.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if _ISO_DAY.match(s):
        return s
    return s[:10] if len(s) >= 10 else None


def day_in_zone(v, offset_min):
    """The calendar day a stored value falls on for a viewer at `offset_min`.

    `offset_min` is minutes EAST of UTC — Israel in winter is +120. It is the
    client's own offset, sent with the request, because the only clock that
    can answer "is this today?" is the one the person is reading.

    A value with no time in it is a day already and is returned untouched.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if _ISO_DAY.match(s):
        return s
    try:
        iso = s.replace(" ", "T").replace("Z", "+00:00")
        d = _dt.datetime.fromisoformat(iso)
    except ValueError:
        return _day(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)      # the database writes UTC
    local = d.astimezone(_dt.timezone(_dt.timedelta(minutes=offset_min or 0)))
    return local.date().isoformat()


def span(value, today):
    """A token or a plain date, as the inclusive span [from, to] it covers.

    `today` is the CLIENT's date, never the server's. Weeks start on Sunday,
    as they do in Israel.
    """
    if value is None or value == "":
        return None
    s = str(value).strip()
    if _ISO_DAY.match(s):
        return (s, s)
    try:
        t = _dt.date.fromisoformat(str(today))
    except (TypeError, ValueError):
        return None
    day = lambda n: t + _dt.timedelta(days=n)
    # Monday is 0 in Python; Sunday-first means shifting by one
    sunday = t - _dt.timedelta(days=(t.weekday() + 1) % 7)

    def month(n):
        y, m = t.year, t.month + n
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        first = _dt.date(y, m, 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        return first, _dt.date(ny, nm, 1) - _dt.timedelta(days=1)

    table = {
        "today":      (t, t),
        "yesterday":  (day(-1), day(-1)),
        "tomorrow":   (day(1), day(1)),
        "this_week":  (sunday, sunday + _dt.timedelta(days=6)),
        "next_week":  (sunday + _dt.timedelta(days=7), sunday + _dt.timedelta(days=13)),
        "last_week":  (sunday - _dt.timedelta(days=7), sunday - _dt.timedelta(days=1)),
        "this_month": month(0),
        "next_month": month(1),
        "last_month": month(-1),
        "last_7":     (day(-6), t),
        "last_30":    (day(-29), t),
    }
    got = table.get(s)
    return (got[0].isoformat(), got[1].isoformat()) if got else None


# ── emptiness ──────────────────────────────────────────────────────────────
def is_empty(c):
    """NULL, an empty string and a string of spaces — all the same nothing.

    0 and False are deliberately NOT empty: a budget of zero is a budget, and
    an unticked box is an answer.
    """
    if c is None:
        return True
    if isinstance(c, str):
        return c.strip() == ""
    if isinstance(c, (list, tuple, dict)):
        return len(c) == 0
    return False


# ── one rule against one item ──────────────────────────────────────────────
def _cell(item, field, kind, offset_min):
    """What the field holds on this item, in the shape the operators expect."""
    cf = item.get("custom_fields") or {}
    if field == "title":
        return (item.get("title") or "").strip() or None
    if field == "status":
        return item.get("status_key") or item.get("status") or None
    if field == "priority":
        return item.get("priority_key") or item.get("priority") or None
    if field == "assignees":
        return [a.get("id") if isinstance(a, dict) else a
                for a in (item.get("assignees") or [])]
    if field == "due":
        return day_in_zone(item.get("due_date"), offset_min)
    v = cf.get(field)
    if kind == "people":
        arr = v if isinstance(v, list) else ([] if v in (None, "") else [v])
        out = []
        for x in arr:
            x = x.get("id") if isinstance(x, dict) else x
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                pass
        return out
    if kind == "status":
        if v in (None, ""):
            return None
        return v.get("label") if isinstance(v, dict) else str(v)
    if kind == "number":
        # `v in (None, "", False)` would be a trap here: in Python 0 == False,
        # so a cell holding zero would be read as an empty cell — the exact
        # thing is_empty is written to avoid, undone one function away from it.
        if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()):
            return None
        try:
            return float(v.get("value") if isinstance(v, dict) else v)
        except (TypeError, ValueError):
            return None
    if kind == "date":
        if v in (None, ""):
            return None
        d = (v.get("from") or v.get("date")) if isinstance(v, dict) else v
        return day_in_zone(d, offset_min)
    if kind == "check":
        return bool(len(v)) if isinstance(v, list) else bool(v)
    if v in (None, ""):
        return None
    return v if isinstance(v, str) else str(v)


def match_rule(item, rule, fields, today, offset_min, me_id):
    """One rule. `fields` maps a field id to the kind it is asked about."""
    kind = fields.get(rule["field"])
    if kind is None:
        return True                     # a column deleted since: stop filtering
    c = _cell(item, rule["field"], kind, offset_min)
    op, v, v2 = rule["operator"], rule.get("value"), rule.get("value2")

    if op == "empty":
        return is_empty(c)
    if op == "filled":
        return not is_empty(c)
    if op == "yes":
        return c is True
    if op == "no":
        return c is not True

    if kind == "people":
        want = me_id if v == "me" else v
        try:
            want = int(want)
        except (TypeError, ValueError):
            return True                 # nothing chosen yet
        has = want in (c or [])
        return (not has) if op == "nhas" else has

    if kind == "date":
        if op == "between":
            a, b = span(v, today), span(v2, today)
            if not a or not b:
                return True
            if is_empty(c):
                return False
            return min(a[0], b[0]) <= c <= max(a[1], b[1])
        sp = span(v, today)
        if not sp:
            return True
        if is_empty(c):
            return False
        if op == "on":
            return sp[0] <= c <= sp[1]
        if op == "before":
            return c < sp[0]
        if op == "after":
            return c > sp[1]
        return True

    if kind == "number":
        def num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        if op == "between":
            a, b = num(v), num(v2)
            if a is None or b is None:
                return True
            if is_empty(c) or c is None:
                return False
            return min(a, b) <= c <= max(a, b)
        n = num(v)
        if n is None:
            return True
        if c is None:
            return False
        return {"eq": c == n, "ne": c != n, "gt": c > n, "lt": c < n}.get(op, True)

    want = "" if v is None else str(v)
    if want == "":
        return True
    if rule["field"] in ("status", "priority"):
        # the rule holds the key; compare keys, not the Hebrew beside them
        got = "" if c is None else str(c)
        return got != want if op == "ne" else got == want
    if is_empty(c):
        return op in ("ne", "nhas")
    a, b = str(c).lower(), want.lower()
    return {"eq": a == b, "ne": a != b,
            "has": b in a, "nhas": b not in a}.get(op, True)


def match(item, node, fields, today, offset_min=0, me_id=None):
    """The tree. An empty group matches everything — a filter nobody finished
    building must never hide the board."""
    if not node:
        return True
    if node.get("type") == "group" or "rules" in node:
        kids = [k for k in (node.get("rules") or []) if k]
        if not kids:
            return True
        f = lambda k: match(item, k, fields, today, offset_min, me_id)
        return any(map(f, kids)) if node["operator"] == "or" else all(map(f, kids))
    return match_rule(item, node, fields, today, offset_min, me_id)
