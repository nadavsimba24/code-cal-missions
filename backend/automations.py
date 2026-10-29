"""Board automations — the recipe catalog ("אם–אז", Monday-style).

Pure data plus validation: no database and no app imports, so it can be read by
the API, the engine and the tests without a circular import. The engine that
actually fires these lives in main.py, next to the task endpoints it hooks.

A recipe pairs one trigger with one action and declares the placeholders a board
admin fills in. A stored Automation keeps only `recipe_id` + the filled values,
so a recipe's wording can be improved later without rewriting saved rules.
"""

import re

import filter_ast          # pure, like this module: no app imports, no database

# ── field types the UI knows how to render ──────────────────────────
# status/priority → the board's own vocabulary; person → a board member;
# group → a group on the board; text → free text.
# connect → a connect column on this board; item → a specific item to link to;
# board → one of the boards that connect column points at.
FIELD_TYPES = ("status", "priority", "person", "recipient", "group", "text",
               "connect", "item", "board")

# ── conditions ("רק אם") ────────────────────────────────────────────
# A recipe pairs one trigger with one action, and for a long time that pair was
# the whole "if": the moment the trigger fired, the action ran. A condition is
# the other half of the if. The trigger says what happened; a condition says
# what must ALSO be true of the item for the action to run. They are ANDed, and
# read at the moment the trigger fires — against the item as it is then, not as
# it was when the rule was written.
#
# Stored inside the rule's own `config`, under this reserved key, rather than in
# a column of its own: drafts, versions, publishing, comparing and the export
# all carry `config` already, so a condition travels through every one of them
# without any of them learning a new field.
CONDITION_KEY = "conditions"
MAX_CONDITIONS = 3

# ── a condition about one of the board's own columns ────────────────────────
# The conditions below ask about the handful of things every board has: the
# status, the priority, the people on the item, its group, its due date. Most
# of what a board actually MEANS lives in its own columns — "רק אם התקציב מעל
# X", "רק אם סוג הפנייה הוא Y" — and none of that could be asked about at all.
#
# A column condition is three answers, because asking about a column takes
# three: which column, what kind of column it is, and the value. So the stored
# value is {"col": <column id>, "type": <the column's own type>, "value": …}
# rather than a scalar like every other condition's.
#
# The column's TYPE is kept with it rather than looked up when the rule runs,
# for the case where it cannot be looked up: a column that was deleted, or
# changed type. A rule that cannot run has to stay legible enough to fix, and
# "העמודה «תקציב» היא «1000»" over a missing column says what to do where a
# bare column id does not.
#
# filter_ast owns the table of which column types can be asked about and how —
# the advanced filter asks the same question of the same columns, and a second
# copy of that table here is how the two would come to disagree.
COLUMN_CONDITIONS = ("column_is", "column_is_not")

# ── the field matrix ────────────────────────────────────────────────────────
# What each kind of column may be in a rule: something that sets it off,
# something it asks about, something it writes — and the rule that governs it.
#
# This is the list the capabilities service answers with, and it is the whole
# of "סוג שדה שלא הוגדר במטריצה לא יהיה זמין": a type absent from here is not
# offered anywhere, which is a decision somebody has to make deliberately
# rather than a gap that quietly lets a half-supported column through.
#
# `kind` is how its value is compared (see filter_ast.KINDS and the operators
# below). None means it has no value anything can be asked about.
FIELD_MATRIX = {
    # טקסט, מספר, סטטוס, תאריך — the four that do everything
    "text":       {"trigger": True,  "condition": True,  "action": False, "kind": "text",
                   "rule": "אימות סוג"},
    "long_text":  {"trigger": True,  "condition": True,  "action": False, "kind": "text",
                   "rule": "אימות סוג"},
    "email":      {"trigger": True,  "condition": True,  "action": False, "kind": "text",
                   "rule": "אימות סוג"},
    "phone":      {"trigger": True,  "condition": True,  "action": False, "kind": "text",
                   "rule": "אימות סוג"},
    "number":     {"trigger": True,  "condition": True,  "action": False, "kind": "number",
                   "rule": "אימות סוג"},
    "rating":     {"trigger": True,  "condition": True,  "action": False, "kind": "number",
                   "rule": "אימות סוג"},
    "status":     {"trigger": True,  "condition": True,  "action": True,  "kind": "status",
                   "rule": "סטטוס לפי מזהה ערך קבוע"},
    "priority":   {"trigger": True,  "condition": True,  "action": True,  "kind": "status",
                   "rule": "סטטוס לפי מזהה ערך קבוע"},
    "date":       {"trigger": True,  "condition": True,  "action": False, "kind": "date",
                   "rule": "אימות סוג"},
    "timeline":   {"trigger": True,  "condition": True,  "action": False, "kind": "date",
                   "rule": "אימות סוג"},
    "due":        {"trigger": True,  "condition": True,  "action": True,  "kind": "date",
                   "rule": "אימות סוג"},
    # אנשים, תיבה, בחירה יחידה או מרובה
    "people":     {"trigger": True,  "condition": True,  "action": True,  "kind": "people",
                   "rule": "משתמש פעיל; הוספה, הסרה או החלפה לפי הסוג"},
    "assignees":  {"trigger": True,  "condition": True,  "action": True,  "kind": "people",
                   "rule": "משתמש פעיל; הוספה, הסרה או החלפה לפי הסוג"},
    "checkbox":   {"trigger": True,  "condition": True,  "action": False, "kind": "check",
                   "rule": "הוספה, הסרה או החלפה לפי הסוג"},
    "dropdown":   {"trigger": True,  "condition": True,  "action": False, "kind": "status",
                   "rule": "בחירה יחידה או מרובה — לפי הסוג"},
    # קישור בין לוחות
    "connect":    {"trigger": True,  "condition": True,  "action": True,  "kind": "link",
                   "rule": "לפי פריטים מקושרים והרשאות היעד"},
    # מראה — read only, and never a trigger
    "mirror":     {"trigger": False, "condition": True,  "action": False, "kind": "text",
                   "rule": "לקריאה בלבד ובכפוף להרשאת מקור"},
    # קובץ — a trigger only on being added or removed, and only ever asked
    # whether it is there
    "files":      {"trigger": True,  "condition": True,  "action": False, "kind": "check",
                   "rule": "אין העתקה או מחיקה אוטומטית ב־MVP",
                   "ops": ("empty", "filled")},
    # שדות מערכת — read only
    "item_id":    {"trigger": False, "condition": True,  "action": False, "kind": "text",
                   "rule": "שדה מערכת לקריאה בלבד"},
    "created_at": {"trigger": False, "condition": True,  "action": False, "kind": "date",
                   "rule": "שדה מערכת לקריאה בלבד"},
    "created_by": {"trigger": False, "condition": True,  "action": False, "kind": "people",
                   "rule": "שדה מערכת לקריאה בלבד"},
    # נוסחה — asked after it has been worked out, and never a trigger
    "formula":    {"trigger": False, "condition": True,  "action": False, "kind": "number",
                   "rule": "לאחר חישוב סופי; שינוי החישוב אינו Trigger עצמאי"},
}

# The operators each kind offers. filter_ast holds the board filter's own table
# and is the implementation these are evaluated by, so the two are the same
# list — with the one kind the filter has no answer for added here.
COLUMN_OPS = {**{k: tuple(v) for k, v in filter_ast.OPS.items()},
              "link": ("linked", "not_linked")}
OPS_HE = {
    "eq": "שווה", "ne": "אינו שווה", "has": "מכיל", "nhas": "אינו מכיל",
    "empty": "ריק", "filled": "אינו ריק", "gt": "גדול מ", "lt": "קטן מ",
    "between": "בטווח", "on": "בתאריך", "before": "לפני", "after": "אחרי",
    "yes": "מסומן", "no": "אינו מסומן",
    "linked": "מקושר", "not_linked": "אינו מקושר",
}
# An operator that needs no value at all — the null questions and the two
# checkbox ones. Asked of a missing value they are the only ones that answer:
# everything else holds its fire, because a value nobody filled in is not zero
# and not an empty string.
OPS_NO_VALUE = ("empty", "filled", "yes", "no", "linked", "not_linked")
OPS_TWO_VALUES = ("between",)

# The one group a rule's conditions form: all of them, or any of them. One
# group is the whole of "אין לשלב AND ו-OR באותה קבוצה" — there is nowhere to
# mix them.
CONDITION_GROUP_OPS = ("and", "or")
CONDITION_GROUP_KEY = "conditions_op"


def field_matrix():
    """The matrix, as the capabilities service answers it."""
    out = []
    for t, m in FIELD_MATRIX.items():
        kind = m.get("kind")
        out.append({"type": t, "kind": kind,
                    "trigger": m["trigger"], "condition": m["condition"],
                    "action": m["action"], "rule": m["rule"],
                    "operators": list(m.get("ops") or COLUMN_OPS.get(kind) or ())})
    return out


def field_ops(col_type):
    """The operators a column of this type may be asked with — () when it may
    not be asked about at all."""
    m = FIELD_MATRIX.get(str(col_type or ""))
    if not m or not m["condition"]:
        return ()
    return tuple(m.get("ops") or COLUMN_OPS.get(m.get("kind")) or ())


def capabilities():
    """automation-capabilities — what this engine can actually do today.

    Served rather than written down, because "what is supported" is a question
    whose answer moves: a screen that guessed would offer a column type the
    engine refuses, and a type nobody has decided about yet must be absent
    rather than half-present.
    """
    return {
        "fields": field_matrix(),
        "operators": {k: list(v) for k, v in COLUMN_OPS.items()},
        "operator_labels": dict(OPS_HE),
        "operators_without_value": list(OPS_NO_VALUE),
        "operators_with_two_values": list(OPS_TWO_VALUES),
        "group_operators": list(CONDITION_GROUP_OPS),
        "max_conditions": MAX_CONDITIONS,
        "mirror_match": list(MIRROR_MATCH),
        "mirror_match_default": MIRROR_MATCH_DEFAULT,
        # the three things the engine promises about a value nobody filled in
        "null_semantics": {
            "no_coercion": True,
            "missing_is_not_zero": True,
            "missing_is_not_empty_string": True,
            "unmet_condition_is": "skipped",
        },
    }


# ── ערכים דינמיים ───────────────────────────────────────────────────────────
# A value an action writes can be taken from the item it is acting on instead
# of typed into the rule. Written as {{…}} inside a text, which is the one
# place a person can put several of them in a row and read the result:
#
#     "המשך טיפול ב-{{item.name}} — {{field.col_area}}"
#
# Every token is named here. An unknown one is refused when the rule is SAVED
# rather than left to resolve into nothing at three in the morning, and a token
# whose value is missing resolves to an empty string rather than to the word
# "None" — a name is not improved by the word None in the middle of it.
TOKENS = {
    "item.id":     "מזהה הפריט",
    "item.name":   "שם הפריט",
    "item.url":    "קישור ישיר לפריט",
    "board.id":    "מזהה הלוח",
    "board.name":  "שם הלוח",
    "actor.name":  "מי ביצע את השינוי",
    "actor.email": "הדוא\"ל של מי שביצע",
    "now":         "זמן ההפעלה",
    "now.date":    "תאריך ההפעלה",
    "now.time":    "שעת ההפעלה",
    "event.old":   "הערך הקודם",
    "event.new":   "הערך החדש",
    "owner.name":  "בעל האוטומציה",
}
# Two that take a column after them: a field of this item, and a field of the
# item at the other end of a connect column — the latter only where there is
# exactly one linked item, because "the value from the linked item" is not a
# value at all when there are three of them.
TOKEN_PREFIXES = {
    "field.":  "ערך של עמודה בפריט",
    "linked.": "ערך חד־משמעי מפריט מקושר",
}
TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


# ── נמען ההתראה ─────────────────────────────────────────────────────────────
# Who a notification goes to. A fixed person is one answer of five, and the
# other four are read off the thing that happened — which is what makes one
# rule serve a board where the right recipient is a different person each time.
#
# An empty one is NOT an error and NOT everybody: the notification is skipped
# and the log says so, because "nobody was named" is a thing to see in the
# history rather than a reason to stop the rule.
RECIPIENTS = {
    "user":      "משתמש קבוע",
    "field":     "אחראי משדה אנשים",
    "actor":     "המשתמש שביצע את השינוי",
    "owner":     "בעל האוטומציה",
    "board_admin": "מנהל הלוח",
}
RECIPIENT_NEEDS_VALUE = ("user", "field")


def recipients_catalog():
    return [{"key": k, "label": he, "takes_value": k in RECIPIENT_NEEDS_VALUE}
            for k, he in RECIPIENTS.items()]


def recipient_value(raw):
    """(clean, error) for a notification's recipient.

    Stored as {kind, value} — a user id for "משתמש קבוע", a column id for
    "אחראי משדה אנשים", nothing for the three that are read off the event.
    A bare number is the old shape: one fixed person, which is what every rule
    written before this meant.
    """
    if isinstance(raw, (int, str)) and str(raw).lstrip("-").isdigit():
        return {"kind": "user", "value": int(raw)}, None
    if not isinstance(raw, dict):
        return None, "נמען לא תקין"
    kind = str(raw.get("kind") or "user")
    if kind not in RECIPIENTS:
        return None, "סוג נמען לא מוכר"
    if kind == "user":
        try:
            return {"kind": kind, "value": int(raw.get("value"))}, None
        except (TypeError, ValueError):
            return None, "חסר נמען"
    if kind == "field":
        col = str(raw.get("value") or "").strip()
        if not col:
            return None, "חסרה עמודת אנשים בנמען"
        return {"kind": kind, "value": col}, None
    return {"kind": kind}, None


def tokens_catalog():
    return ([{"token": k, "label": he, "takes_column": False} for k, he in TOKENS.items()]
            + [{"token": k, "label": he, "takes_column": True}
               for k, he in TOKEN_PREFIXES.items()])


def token_names(text):
    """Every {{…}} in a text, in the order they appear."""
    return TOKEN_RE.findall(str(text or ""))


def unknown_tokens(text):
    """The ones this engine has no answer for — refused when the rule is saved.

    A typo in a token is a value that silently never appears, which is the
    hardest kind of mistake to see in a rule that otherwise works.
    """
    bad = []
    for name in token_names(text):
        if name in TOKENS:
            continue
        if any(name.startswith(p) and len(name) > len(p) for p in TOKEN_PREFIXES):
            continue
        bad.append(name)
    return bad


# A mirror can reflect several linked items. Whoever writes the rule says
# whether all of them have to match or any one of them — and the default is
# any, which is the reading of "רק אם הסטטוס אצלם הוא בוצע" on a cell showing
# three items: one of them being done is a thing worth acting on.
MIRROR_MATCH = ("any", "all")
MIRROR_MATCH_DEFAULT = "any"
# Columns whose cell holds several values at once. "is" on one of these means
# "is among them", so two of them on one column are not a contradiction.
MULTI_COLUMN_TYPES = ("dropdown", "people", "files")


# A mirror shows a field of a LINKED item. It is read as text — whatever the
# source field is, what the mirror holds is what it displays — and it is asked
# about HERE rather than in filter_ast.KINDS, which is the board filter's own
# vocabulary: a mirror stores nothing, so it is answered by resolving the link
# each time (see _column_cond_holds), which the automations engine does and the
# filter does not.
#
# This is the whole of "שינוי בעמודת מראה אינו גורם מפעיל עצמאי ב־MVP; ניתן
# להשתמש בערכה כתנאי בלבד": askable, never listenable.
MIRROR_KIND = "text"


def column_kind(col_type):
    """How a column of this type can be asked about — None if it cannot be.

    The matrix answers first: it is the list of what this engine supports, and
    a type outside it has no kind here however the board filter reads it.
    """
    t = str(col_type or "")
    m = FIELD_MATRIX.get(t)
    if m:
        return m["kind"] if m["condition"] else None
    return filter_ast.KINDS.get(t)


def column_types():
    """Every column type a condition can be written against, grouped by the
    kind that decides what its value looks like."""
    out = {}
    for t, m in FIELD_MATRIX.items():
        if m["condition"] and m["kind"]:
            out.setdefault(m["kind"], []).append(t)
    return out

# `type` is the value the condition takes — None for one that asks about the
# item itself and needs nothing filled in.
CONDITIONS = {
    "status_is":       {"text": "הסטטוס הוא {status}", "type": "status", "label": "סטטוס"},
    "status_is_not":   {"text": "הסטטוס אינו {status}", "type": "status", "label": "סטטוס"},
    "priority_is":     {"text": "העדיפות היא {priority}", "type": "priority", "label": "עדיפות"},
    "priority_is_not": {"text": "העדיפות אינה {priority}", "type": "priority", "label": "עדיפות"},
    "person_is":       {"text": "{person} משויך לפריט", "type": "person", "label": "אדם"},
    "person_is_not":   {"text": "{person} אינו משויך לפריט", "type": "person", "label": "אדם"},
    "group_is":        {"text": "הפריט בקבוצה {group}", "type": "group", "label": "קבוצה"},
    "group_is_not":    {"text": "הפריט אינו בקבוצה {group}", "type": "group", "label": "קבוצה"},
    "has_assignee":    {"text": "יש אחראי לפריט", "type": None},
    "no_assignee":     {"text": "אין אחראי לפריט", "type": None},
    "has_due_date":    {"text": "לפריט יש תאריך יעד", "type": None},
    "no_due_date":     {"text": "לפריט אין תאריך יעד", "type": None},
    "overdue":         {"text": "תאריך היעד עבר", "type": None},
    "not_overdue":     {"text": "תאריך היעד לא עבר", "type": None},
    # the board's own columns — "type": "column" is the one condition whose
    # value is three answers and not one (see COLUMN_CONDITIONS above)
    "column_is":       {"text": "העמודה {column} היא {value}", "type": "column",
                        "label": "ערך"},
    "column_is_not":   {"text": "העמודה {column} אינה {value}", "type": "column",
                        "label": "ערך"},
}

# Pairs that cannot both hold, and kinds that take one value at a time — two of
# those with different values is the same impossibility. Refused when the rule
# is written: a rule that can never fire is not a narrow rule, it is a rule
# somebody will wait on forever.
_EXCLUSIVE = [("has_assignee", "no_assignee"), ("has_due_date", "no_due_date"),
              ("overdue", "not_overdue"), ("overdue", "no_due_date")]
_ONE_VALUE = ("status_is", "priority_is", "group_is")
# "the status is X" and "the status is not X" are the same contradiction
_NEGATES = {"status_is": "status_is_not", "priority_is": "priority_is_not",
            "person_is": "person_is_not", "group_is": "group_is_not"}


def condition(kind):
    return CONDITIONS.get(kind)


def condition_text(kind, shown=None):
    """One condition as a phrase. `shown` is the value already rendered the way
    the board shows it; without one the blank stays a blank.

    A column condition reads with two blanks — which column, and what value —
    so for one of those `shown` is a {"column": …, "value": …} dict. Either
    blank may be missing, which is what a half-built condition looks like while
    somebody is still choosing.
    """
    spec = CONDITIONS.get(kind)
    if not spec:
        return ""
    if spec["type"] is None:
        return spec["text"]
    if spec["type"] == "column":
        parts = shown if isinstance(shown, dict) else {}
        text = spec["text"]
        for slot in ("column", "value"):
            text = text.replace("{" + slot + "}", parts.get(slot) or "…")
        return text
    return spec["text"].replace("{" + spec["type"] + "}",
                                shown if shown is not None else "…")


def conditions_clause(phrases, group_op="and"):
    """The whole "רק אם" clause from already-rendered condition phrases.

    The group's operator is in the joining word, because that is where a reader
    looks for it: "וגם" or "או", once, over the whole clause.
    """
    parts = [p for p in (phrases or []) if p]
    if not parts:
        return ""
    joiner = " או " if str(group_op) == "or" else " וגם "
    return "ורק אם " + joiner.join(parts)


def conditions_catalog():
    """What the "רק אם" picker offers, in the order a person reads them."""
    return [{"kind": k, "label": condition_text(k), "type": c["type"],
             "value_label": c.get("label", "")} for k, c in CONDITIONS.items()]


def column_condition_value(raw):
    """(clean, error) for the value of a column condition.

    Held to the same line as every other condition's value: a column condition
    with nothing chosen is refused even in a draft, because "רק אם העמודה …
    היא …" with no column and no value is not a narrower rule — it is the rule
    without the condition.
    """
    if not isinstance(raw, dict):
        return None, "תנאי על עמודה אינו תקין"
    col = str(raw.get("col") or "").strip()
    col_type = str(raw.get("type") or "").strip()
    if not col:
        return None, "חסרה עמודה בתנאי"
    kind = column_kind(col_type)
    if not kind:
        return None, "לא ניתן להתנות בעמודה מסוג הזה"
    # the matrix decides what may be asked and how. A type nobody has put in it
    # is not available — which is the point of having one.
    allowed = field_ops(col_type)
    if not allowed:
        return None, "סוג העמודה אינו נתמך בתנאים — נדרשת בדיקת תאימות"
    # A condition written before the operators existed carries a value and no
    # operator. For every kind but the checkbox the default IS what it meant;
    # for a checkbox the value WAS the question, so it is read back as one —
    # otherwise "רק אם התיבה אינה מסומנת" would quietly become its opposite.
    default = _DEFAULT_OP.get(kind, "eq")
    if kind == "check" and not (raw.get("op") or raw.get("operator")):
        default = "yes" if bool(raw.get("value")) else "no"
    op = str(raw.get("op") or raw.get("operator") or default).strip()
    if op not in allowed:
        return None, f"האופרטור אינו נתמך לעמודה מסוג '{col_type}'"
    out = {"col": col, "type": col_type, "op": op}
    # a mirror of several linked items: all of them, or any one of them
    if col_type == "mirror":
        m = str(raw.get("match") or MIRROR_MATCH_DEFAULT)
        out["match"] = m if m in MIRROR_MATCH else MIRROR_MATCH_DEFAULT
    # the questions that take no value at all. Asked of a cell nobody filled
    # in they are the only ones that answer — see the null semantics.
    if op in OPS_NO_VALUE:
        if op in ("linked", "not_linked"):
            # naming an item is optional: "מקושר" on its own asks whether the
            # cell holds anything
            try:
                out["value"] = int(raw.get("value"))
            except (TypeError, ValueError):
                out["value"] = None
        return out, None
    if op in OPS_TWO_VALUES:
        a, aerr = _cond_one_value(kind, raw.get("value"))
        if aerr:
            return None, aerr
        b, berr = _cond_one_value(kind, raw.get("value2"))
        if berr:
            return None, berr
        out["value"], out["value2"] = a, b
        return out, None
    v, err = _cond_one_value(kind, raw.get("value"))
    if err:
        return None, err
    out["value"] = v
    return out, None


# What a kind is asked with when nothing says — the question people mean by
# default for that sort of column.
_DEFAULT_OP = {"text": "eq", "status": "eq", "number": "eq", "people": "has",
               "date": "on", "check": "yes", "link": "linked"}


def _cond_one_value(kind, v):
    """(value, error) for one side of a column condition, by the kind of
    column it is about. Type-safe on purpose: a number column asked about the
    word "גבוה" is a rule that can never hold, and it is refused when it is
    written rather than skipped for ever afterwards."""
    if kind == "check":
        return bool(v), None
    if kind == "people":
        try:
            return int(v), None
        except (TypeError, ValueError):
            return None, "חסר ערך בתנאי על העמודה"
    if kind == "number":
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None, "הערך בתנאי על העמודה אינו מספר"
        if v == int(v):
            v = int(v)                 # 1000, not 1000.0, in the sentence
        return v, None
    if kind == "date":
        v = str(v or "").strip()
        if not (filter_ast._ISO_DAY.match(v) or v in filter_ast.DATE_TOKENS):
            return None, "חסר תאריך בתנאי על העמודה"
        return v, None
    if True:
        v = str(v if v is not None else "").strip()[:200]
        if not v:
            return None, "חסר ערך בתנאי על העמודה"
    return v, None


def condition_group_op(raw, conds):
    """(operator, error) for the one group a rule's conditions form.

    "MVP יתמוך בקבוצת תנאים אחת: כל התנאים מסוג AND או לפחות תנאי אחד מסוג OR.
    אין לשלב AND ו-OR באותה קבוצה" — one group, one operator over all of it.
    There is nowhere to mix them, which is the point of there being one group:
    a reader of "רק אם א וגם ב או ג" cannot tell what it means, and neither
    can anyone writing it.
    """
    op = str(raw or "and").strip().lower()
    if op not in CONDITION_GROUP_OPS:
        return None, "אופרטור תנאים לא מוכר — AND או OR"
    if op == "or" and len(conds or []) < 2:
        return None, "OR דורש לפחות שני תנאים"
    return op, None


def validate_conditions(raw):
    """(clean, error) for a rule's extra conditions.

    A condition missing its value is refused even in a draft, unlike a recipe
    placeholder. A placeholder is a blank somebody comes back to and the rule
    cannot run until they do; a condition with no value would silently WIDEN
    what the rule fires on — "only if the status is …" with no status is not a
    narrower rule, it is the rule without the condition.
    """
    if raw in (None, "", []):
        return [], None
    if not isinstance(raw, list):
        return None, "תנאים לא תקינים"
    if len(raw) > MAX_CONDITIONS:
        return None, f"אפשר להגדיר עד {MAX_CONDITIONS} תנאים"
    clean, seen = [], set()
    for c in raw:
        if not isinstance(c, dict):
            return None, "תנאים לא תקינים"
        kind = str(c.get("kind") or "").strip()
        spec = CONDITIONS.get(kind)
        if not spec:
            return None, "תנאי לא מוכר"
        t, v = spec["type"], c.get("value")
        if t is None:
            v = None
        elif t == "column":
            v, cerr = column_condition_value(v)
            if cerr:
                return None, cerr
        elif t in ("person", "group"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return None, f"חסר ערך בתנאי '{condition_text(kind)}'"
        else:
            v = str(v or "").strip()
            if not v:
                return None, f"חסר ערך בתנאי '{condition_text(kind)}'"
        sig = (kind, _sig(v) if isinstance(v, dict) else v)
        if sig in seen:
            continue                    # the same condition twice narrows nothing
        seen.add(sig)
        clean.append({"kind": kind, "value": v})
    err = _impossible(clean)
    if err:
        return None, err
    return clean, None


def _impossible(conds):
    """The reason these conditions can never all hold, if there is one."""
    kinds = {c["kind"] for c in conds}
    for a, b in _EXCLUSIVE:
        if a in kinds and b in kinds:
            return (f"התנאים '{condition_text(a)}' ו'{condition_text(b)}' "
                    f"אינם יכולים להתקיים יחד")
    for kind in _ONE_VALUE:
        vals = {str(c["value"]) for c in conds if c["kind"] == kind}
        if len(vals) > 1:
            return f"'{condition_text(kind)}' יכול להתקיים על ערך אחד בלבד"
    for pos, neg in _NEGATES.items():
        same = {str(c["value"]) for c in conds if c["kind"] == pos} & \
               {str(c["value"]) for c in conds if c["kind"] == neg}
        if same:
            return f"תנאי '{condition_text(pos)}' סותר את ההיפוך שלו באותו ערך"
    # ── the same column, asked two things that cannot both hold ──
    # Per column, not per condition kind: two columns each with their own value
    # is an ordinary two-condition rule. A multi-select column is deliberately
    # left out of the single-value rule — a dropdown cell holds several options
    # at once, so "is A" and "is B" on one are both true of the same item.
    # Only the plain "is this value" questions can contradict each other this
    # way. An operator that takes no value, or two of them, is a different
    # question about the same column and two of those are an ordinary pair.
    def _plain(c, kind):
        return (c["kind"] == kind and c["value"].get("op", "eq") == "eq"
                and "value" in c["value"] and c["value"].get("value2") is None)

    for col in {c["value"]["col"] for c in conds if c["kind"] in COLUMN_CONDITIONS}:
        vals = {str(c["value"]["value"]) for c in conds
                if _plain(c, "column_is") and c["value"]["col"] == col}
        multi = any(c["value"]["type"] in MULTI_COLUMN_TYPES
                    for c in conds if c["kind"] in COLUMN_CONDITIONS
                    and c["value"]["col"] == col)
        if len(vals) > 1 and not multi:
            return "לא ניתן להתנות בשני ערכים שונים באותה עמודה"
        refused = {str(c["value"]["value"]) for c in conds
                   if _plain(c, "column_is_not") and c["value"]["col"] == col}
        if vals & refused:
            return "תנאי על עמודה סותר את ההיפוך שלו באותו ערך"
    return None


# ── which status a rule is about ────────────────────────────────────────────
# A board has one built-in status, and it may also carry columns of type
# status, each with a vocabulary of its own. Every `status` blank in a rule
# used to mean the built-in one and there was no way to say otherwise, so a
# board that tracks its work in a "שלב" column could not fire a rule on it at
# all — only through "כאשר ערך העמודה משתנה", which goes off on every change
# rather than on the one value somebody cares about.
#
# The column travels BESIDE the value, under a derived key: `t_status` is
# answered by `t_status_col`, `a_status` by `a_status_col`. Not inside the
# value, because a bare vocabulary key is what every stored rule already holds
# and what the engine compares against the event — widening it into a dict
# would have had to be understood by the matcher, the dry run, the labels, the
# export, the version diff and the browser, all in the same breath, and every
# rule written before today would have had to be rewritten to keep working.
#
# Absent or empty means the board's own status, which is exactly what a rule
# written before this says. That is why there is no migration.
STATUS_COL_SUFFIX = "_col"

# How a trigger or an action reads once it is about a named status column.
# Whole alternative sentences rather than a substitution on the original:
# "הסטטוס" sits in the middle of a Hebrew sentence whose grammar moves around
# it, and "כאשר הסטטוס «שלב» משתנה" is not a sentence anybody would write.
STATUS_COL_TEXT = {
    "status_changes_to": "כאשר {col} משתנה ל{status}",
    "set_status":        "שנה את {col} ל{status}",
}


def status_col_key(field_key):
    """The key the column for this status blank is kept under."""
    return str(field_key) + STATUS_COL_SUFFIX


def status_col_of(values, field_key):
    """The column this status blank names, or "" for the board's own status."""
    return str((values or {}).get(status_col_key(field_key)) or "").strip()


TRIGGERS = {
    "item_created":        "כאשר נוצר פריט חדש",
    "status_changes_to":   "כאשר הסטטוס משתנה ל{status}",
    "priority_changes_to": "כאשר העדיפות משתנה ל{priority}",
    "person_assigned":     "כאשר משויך אדם לפריט",
    "due_date_arrives":    "כאשר מגיע תאריך היעד",
    # ── links between boards ──
    "link_added":           "כאשר נוצר קשר לפריט בלוח אחר",
    "link_removed":         "כאשר מוסר קשר לפריט בלוח אחר",
    "linked_status_changes_to": "כאשר הסטטוס של פריט מקושר משתנה ל{status}",
    # ── the rest of the sources a change can come from ──
    # Each of these already happened in the product; what they lacked was a way
    # to be listened to. A mirror column is deliberately NOT among them: it
    # shows a value that lives on another item, so "it changed" is that item's
    # event and not this one's. It stays usable as a condition.
    "moved_to_group":      "כאשר הפריט מועבר לקבוצה {group}",
    "subitem_created":     "כאשר נוצר תת־פריט",
    "column_changed":      "כאשר ערך העמודה {column} משתנה",
    "person_unassigned":   "כאשר מוסר שיוך של אדם מהפריט",
    "due_date_near":       "{days} ימים לפני תאריך היעד",
    "due_date_passed":     "{days} ימים אחרי תאריך היעד",
    # ── a rule on a clock rather than on a change ──
    # Every other trigger here is something that HAPPENED to an item. This one
    # is the passage of time itself: it comes round again, on every item the
    # conditions still hold for, for as long as the rule is on. It is what a
    # chase is — "כל שבוע, כל עוד הסטטוס עדיין X, הזכר לאחראי" — and there was
    # no way to say it, because every reminder this catalog had hung off a due
    # date and fired once.
    #
    # MIN_EVERY_DAYS is a floor and not a formality: there is no scheduler in
    # this product, so a recurring rule is swept when the board is read, and
    # "every 0 days" would be "on every read".
    "every_n_days":        "כל {days} ימים",
    # ── a sub-item finishing, reported to its PARENT ──
    # The item the rule then acts on is the parent, which is what makes
    # "עדכן שדה בפריט האב" every action the catalog already has rather than a
    # new one that writes somewhere else.
    "subitem_done":         "כאשר תת־פריט הושלם",
}

ACTIONS = {
    "notify_person":    "שלח התראה ל{person}",
    "notify_assignees": "שלח התראה למשויכים לפריט",
    "assign_person":    "שייך את {person}",
    "set_status":       "שנה את הסטטוס ל{status}",
    "set_priority":     "שנה את העדיפות ל{priority}",
    "move_to_group":    "העבר את הפריט לקבוצה {group}",
    "create_subitem":   "צור תת־פריט בשם {text}",
    "link_to_item":     "קשר את הפריט אל {item} בעמודה {connect}",
    "create_and_link":  "צור פריט בשם {text} בלוח {board} וקשר אותו לפריט המקור בעמודה {connect}",
    # ── a board the rule writes into, with nothing pointing back ──
    # Every cross-board action here has been a LINK action: it creates the item
    # and ties it to the one that set the rule off, and the connect column is
    # both the route and the permission. That leaves "when an item reaches
    # «הועברו לפרסום», open one on «מעקב התקשרויות»" unsayable — a hand-off, not
    # a relationship, and there is nothing to connect the two items by.
    #
    # The specification allows exactly this as the second of two routes:
    # "אוטומציה בין לוחות תתבסס על עמודת קישור או על יצירת פריט בלוח יעד שהוגדר
    # מראש". What stands in the connect column's place as the permission is the
    # pair that was always underneath it — the author must hold writing rights
    # on the target board for the rule to be saved, and the grant recording it
    # is re-read before every firing.
    "create_in_board":  "צור פריט בשם {text} בקבוצה {target_group} בלוח {board}",
    # ── and the three the template library asked for ──
    "post_update":      "הוסף עדכון לשיחת הפריט: {text}",
    "copy_to_linked":   "העתק {fields} {targets}",
    # the fuller form of create_and_link: it says which group on the target
    # board, and which of the item's own fields travel with it. A separate
    # action rather than three more placeholders on the old one — a rule
    # somebody already built is not re-asked a question it was never asked.
    "create_in_group_and_link":
        "צור פריט בשם {text} בקבוצה {target_group} בלוח {board}, העתק {fields} "
        "וקשר אותו לפריט המקור בעמודה {connect}",
    # ── the rest of the MVP table ──
    "set_column":       "עדכן את העמודה {column} ל{text}",
    "clear_column":     "נקה את העמודה {column}",
    "unassign_person":  "הסר את השיוך של {person}",
    "create_item":      "צור פריט בשם {text} בקבוצה {group}",
    # Waiting is an action like any other: it sits between two of them and the
    # ones after it happen later. A minute is the shortest wait worth having
    # and thirty days the longest the specification asks for.
    "wait":             "המתן {days} לפני הפעולה הבאה",
    # The fullest form of creating an item on another board: which group, what
    # it is called, and a mapping between the columns of the two boards. A
    # separate action rather than more placeholders on the ones before it — a
    # rule somebody already built is not re-asked a question it was never
    # asked, which is the versioning rule in practice.
    "create_mapped_and_link":
        "צור פריט בשם {text} בקבוצה {target_group} בלוח {board}, מפה {map} "
        "וקשר אותו לפריט המקור בעמודה {connect}",
}
MIN_WAIT_MINUTES = 1
MAX_WAIT_DAYS = 30
# How many pairs one mapping may carry. A mapping is read as a table by a
# person before they switch the rule on, and a table nobody reads is not a
# safeguard.
MAX_MAP_PAIRS = 20


def map_value(raw):
    """(clean, error) for a field mapping — the SHAPE of it only.

    Whether the two sides exist, and whether their types can carry each
    other, is a question about two boards and is answered where the boards are
    (see _check_automation_map). Here: a list of pairs, each naming a source
    and a target, with no side empty and no target written twice.
    """
    if raw in (None, "", []):
        return None, "חסר מיפוי שדות"
    if not isinstance(raw, list):
        return None, "מיפוי שדות אינו תקין"
    if len(raw) > MAX_MAP_PAIRS:
        return None, f"אפשר למפות עד {MAX_MAP_PAIRS} שדות"
    out, seen = [], set()
    for pair in raw:
        if not isinstance(pair, dict):
            return None, "מיפוי שדות אינו תקין"
        a = str(pair.get("from") or "").strip()
        b = str(pair.get("to") or "").strip()
        if not a or not b:
            return None, "במיפוי יש שדה בלי צד שני"
        if b in seen:
            return None, "אותו שדה יעד מופיע פעמיים במיפוי"
        seen.add(b)
        out.append({"from": a[:64], "to": b[:64]})
    return out, None

# What "השדות שהוגדרו" may be. The item's own built-ins, which every board has
# — a custom column exists on one board under one id and on the next board
# under another, so copying those is a mapping between two boards' columns and
# not a list of checkboxes. That is in the Roadmap, not here.
# How far from the due date a "before"/"after" trigger may be set.
MAX_TRIGGER_DAYS = 365
# The shortest a recurring rule may come round. A day, because the thing it
# counts is days and because the sweep that runs it happens when somebody opens
# the board — anything finer would be a promise the engine cannot keep.
MIN_EVERY_DAYS = 1

COPY_FIELDS = {
    "status":      "סטטוס",
    "priority":    "עדיפות",
    "due":         "תאריך יעד",
    "assignees":   "אחראים",
    "description": "תיאור",
}


def copy_fields_catalog():
    return [{"key": k, "label": he} for k, he in COPY_FIELDS.items()]


def copy_fields_label(v):
    """The chosen fields as one readable phrase for the rule's sentence."""
    picked = [COPY_FIELDS[k] for k in (v or []) if k in COPY_FIELDS]
    return ", ".join(picked) if picked else "שדות"


def _f(key, type_, label, **extra):
    """One placeholder. `extra` carries whatever that one field needs that the
    three above do not say — today only `min`, the floor a recurring interval
    has and the due-date distances do not."""
    return {"key": key, "type": type_, "label": label, **extra}


# ── בין לוחות: יעד אחד או כולם, ומה קורה כשאין ─────────────────────────────
# A rule that writes to a linked item has to answer two questions a rule on its
# own board never faced: WHICH linked item when there is more than one, and what
# "there is none" means. Both are the author's to answer and both have a default
# that is the safe reading of silence.
#
# "כולם" is not the default. A rule written when one item was linked, running a
# month later when there are nine, should not quietly have become nine writes —
# that is the difference between a rule doing more than it was asked and a rule
# doing less, and only one of those is recoverable.
TARGETS = ("one", "all")
TARGETS_DEFAULT = "one"
TARGETS_HE = {"one": "לפריט מקושר אחד", "all": "לכל הפריטים המקושרים"}

# And a missing link is not obviously either thing. For a rule that copies a
# nice-to-have it is a non-event; for a rule that IS the link it is a failure
# somebody has to see. The engine is not the one to decide which.
ON_MISSING = ("skip", "fail")
ON_MISSING_DEFAULT = "skip"
ON_MISSING_HE = {"skip": "דלג בשקט", "fail": "רשום ככשל"}

# ── תתי־פריטים: על מי הכלל פועל ────────────────────────────────────────────
# A sub-item event reaches the PARENT's rules: that is how the trigger is built,
# and for most rules the parent is the right thing to write on — "כאשר תת־פריט
# הושלם, סמן את האב". But "עדכן את תת־הפריט" is a real intention too, and until
# now there was no way to say it. The default stays the parent, which is what
# every rule written before this choice existed meant.
# It wears the trigger's `t_` prefix rather than the action's `a_`, and that is
# not a cosmetic choice: an `a_` field IS one of the action's own, read straight
# out of the catalog by action_list. This one qualifies which item the EVENT is
# taken to be about, which every action of the rule then inherits.
ON_TARGETS = ("parent", "subitem")
ON_TARGETS_DEFAULT = "parent"
ON_TARGETS_HE = {"parent": "על פריט האב", "subitem": "על תת־הפריט"}

# key → (allowed values, default). A "pick" field is never missing: silence is
# the default, which is what lets a rule written before the choice existed go on
# running with the reading the spec gives it.
PICKS = {"targets": (TARGETS, TARGETS_DEFAULT),
         "on_missing": (ON_MISSING, ON_MISSING_DEFAULT),
         "on": (ON_TARGETS, ON_TARGETS_DEFAULT)}

# The field types that may be blank. Everything else a recipe declares has to be
# filled before the rule can be switched on.
OPTIONAL_TYPES = ("pick", "connect_opt")


def pick_key(f):
    """Which choice a pick field carries — by its key, with the a_ prefix a
    recipe placeholder wears stripped off."""
    k = f["key"]
    return k[2:] if k.startswith(("a_", "t_")) else k


PICK_HE = {"targets": TARGETS_HE, "on_missing": ON_MISSING_HE, "on": ON_TARGETS_HE}


def pick_label(f, v):
    """A choice as the sentence says it. Never quoted like a value somebody
    typed — it is part of the sentence, not a thing filled into it."""
    key = pick_key(f)
    return PICK_HE.get(key, {}).get(pick_value(key, v), "")


def pick_value(key, v):
    """A choice, or the default when nothing — or nothing recognisable — was
    chosen. Never an error: a value the catalog no longer offers reads as the
    default rather than taking the rule out of service."""
    allowed, default = PICKS.get(key, ((), ""))
    s = str(v or "").strip()
    return s if s in allowed else default


# ── more than one action ("אז… וגם…") ───────────────────────────────────────
# A recipe pairs one trigger with one action, and that single action was the
# whole "then". Four things that have to happen together on one event were four
# rules listening to the same trigger: four rows to write, four to keep in step
# when the status they all watch is renamed, four lines in the history for one
# event, and no order between them beyond run_order.
#
# So a rule may carry up to MAX_ACTIONS actions, which run in order under the
# rule's own conditions — the conditions are the rule's, not each action's.
#
# Stored like the conditions are: the recipe's own action stays exactly where it
# was (the `a_*` keys in `config`, action #1, nothing migrated), and the extra
# ones go in `config` under this reserved key as
# `[{"key": <action>, "values": {<field>: <value>}}]`. The values are keyed by
# the bare field name because an action's fields are the action's — two
# `notify_person` actions in one rule each need their own person, and a flat
# `a_person` has room for one. Everything that already carries `config` —
# drafts, versions, publishing, comparing, the export — carries these with it
# and learns nothing new.
ACTIONS_KEY = "actions"
MAX_ACTIONS = 10

# What each action needs filled in. Keyed by the bare field name; the recipe's
# own action declares the same fields prefixed `a_` (see RECIPES), and
# action_list below reads the two into one shape.
ACTION_FIELDS = {
    "notify_person":    [_f("person", "recipient", "נמען")],
    "notify_assignees": [],
    "assign_person":    [_f("person", "person", "אחראי")],
    "set_status":       [_f("status", "status", "סטטוס")],
    "set_priority":     [_f("priority", "priority", "עדיפות")],
    "move_to_group":    [_f("group", "group", "קבוצה")],
    "create_subitem":   [_f("text", "text", "שם תת־הפריט")],
    "link_to_item":     [_f("connect", "connect", "עמודת הקישור"),
                         _f("item", "item", "הפריט לקישור")],
    "create_and_link":  [_f("connect", "connect", "עמודת הקישור"),
                         _f("board", "board", "לוח היעד"),
                         _f("text", "text", "שם הפריט החדש")],
    "create_in_board":  [_f("board", "board", "לוח היעד"),
                         _f("target_group", "target_group", "הקבוצה בלוח היעד"),
                         _f("text", "text", "שם הפריט החדש")],
    "post_update":      [_f("text", "text", "תוכן העדכון")],
    "set_column":       [_f("column", "column", "עמודה"),
                         _f("text", "text", "הערך החדש")],
    "clear_column":     [_f("column", "column", "עמודה")],
    "unassign_person":  [_f("person", "person", "אחראי")],
    "create_item":      [_f("text", "text", "שם הפריט"),
                         _f("group", "group", "קבוצה")],
    "wait":             [_f("days", "wait", "המתנה")],
    "create_mapped_and_link":
                        [_f("connect", "connect", "עמודת הקישור"),
                         _f("board", "board", "לוח היעד"),
                         _f("target_group", "target_group", "הקבוצה בלוח היעד"),
                         _f("text", "text", "שם הפריט החדש"),
                         _f("map", "map", "מיפוי שדות")],
    "copy_to_linked":   [_f("fields", "fields", "השדות להעתקה"),
                         _f("connect", "connect_opt", "עמודת הקישור"),
                         _f("targets", "pick", "יעד"),
                         _f("on_missing", "pick", "כשאין פריט מקושר")],
    "create_in_group_and_link":
                        [_f("connect", "connect", "עמודת הקישור"),
                         _f("board", "board", "לוח היעד"),
                         _f("target_group", "target_group", "הקבוצה בלוח היעד"),
                         _f("text", "text", "שם הפריט החדש"),
                         _f("fields", "fields", "השדות להעתקה")],
}

# Actions that write one field of the item, so two of them in one rule means the
# second overwrites the first and the first was never worth running. Refused
# when the rule is written, for the same reason a contradictory condition is:
# nobody finds out from the history that half their rule was pointless.
_ONE_PER_RULE = ("set_status", "set_priority", "move_to_group")


def _one_per_target(key, values):
    """What an action writes, for the once-per-rule check above.

    Two «שנה את הסטטוס» in one rule are the same write only when they are about
    the same status column. On two different columns the second overwrites
    nothing — "שנה את הסטטוס ל«הושלם» וגם שנה את «שלב» ל«אושר»" is one rule
    doing two things, and refusing it would be refusing the whole point of a
    board having more than one status column.
    """
    return (key, status_col_of(values, "status") if key == "set_status" else "")


def action_fields(key):
    return ACTION_FIELDS.get(key, [])


def actions_catalog():
    """Every action a rule can be given, for the "פעולה נוספת" picker."""
    # `text` carries the blanks ("{person}") so the builder can put a chip in
    # each one, the way the rule's own sentence does; `label` is the same line
    # with the blanks shown as "…", for the picker that offers it.
    return [{"key": k, "label": plain(text), "text": text,
             # how it reads once it names a status column of its own; "" when
             # it cannot name one — see STATUS_COL_TEXT
             "text_col": STATUS_COL_TEXT.get(k, ""),
             "fields": action_fields(k)} for k, text in ACTIONS.items()]


def action_text(key, shown=None):
    """One action as a phrase. `shown` maps a field key to the value already
    rendered the way the board shows it; a blank stays a blank.

    "status_col" is a key of its own in `shown` rather than one of the action's
    fields: the column is an answer about the status blank, not a blank the
    action has — see STATUS_COL_TEXT. When it is there the action is said about
    that column instead of about the board's own status.
    """
    col = (shown or {}).get("status_col")
    text = (STATUS_COL_TEXT[key] if col not in (None, "") and key in STATUS_COL_TEXT
            else ACTIONS.get(key, ""))
    for f in action_fields(key):
        v = (shown or {}).get(f["key"])
        text = text.replace("{" + f["key"] + "}",
                            v if v not in (None, "") else "…")
    return text.replace("{col}", col if col not in (None, "") else "…")


def action_list(recipe_id, config):
    """Every action the rule performs, in the order it performs them.

    One shape for both halves — the recipe's own action first, then the extras
    — so the engine, the blockers, the impact screen and the test all ask the
    same question once instead of each knowing where an action can hide.
    """
    r = recipe(recipe_id) or {}
    cfg = config or {}
    out = []
    if r.get("action"):
        # _primary_values rather than a second copy of the same comprehension:
        # it is the one that also carries the status column, which rides beside
        # the status under a key the field list does not mention, and a copy
        # here is how the two would come to disagree about what an action holds
        out.append({"key": r["action"], "values": _primary_values(recipe_id, cfg),
                    "index": 0})
    for i, extra in enumerate((cfg.get(ACTIONS_KEY) or []), start=1):
        key = str((extra or {}).get("key") or "")
        if key not in ACTIONS:
            continue                      # an action from a version we no longer have
        out.append({"key": key, "values": dict((extra or {}).get("values") or {}),
                    "index": i})
    return out


def _coerce_field(f, v, require):
    """(value, error) for one action field — the same coercion validate() does
    for a recipe placeholder, so an extra action is held to the rule its
    neighbour is held to."""
    if f["type"] == "text":
        v = str(v or "").strip()[:200]
        # a token nobody can answer is refused where it is written — in an
        # extra action exactly as in the recipe's own placeholder
        bad = unknown_tokens(v)
        if bad:
            return None, "ערך דינמי לא מוכר: {{" + bad[0] + "}}"
    elif f["type"] == "connect":
        v = str(v or "").strip()          # a column id, not a number
    elif f["type"] == "connect_opt":
        # blank is a value: "whichever column the link was made in"
        return str(v or "").strip(), None
    elif f["type"] == "pick":
        return pick_value(pick_key(f), v), None
    elif f["type"] == "recipient":
        v, err = recipient_value(v)
        if err:
            return None, (err if require else None)
        return v, None
    elif f["type"] == "map":
        v, err = map_value(v)
        if err:
            return None, (err if require else None)
        return v, None
    elif f["type"] == "wait":
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None, (f"חסר ערך בשדה '{f['label']}'" if require else None)
        if n < MIN_WAIT_MINUTES or n > MAX_WAIT_DAYS * 24 * 60:
            return None, f"המתנה היא בין דקה ל-{MAX_WAIT_DAYS} ימים"
        return n, None
    elif f["type"] == "fields":
        # a set of the item's own built-ins, in the catalog's order so two rules
        # that chose the same fields read the same way
        picked = [k for k in COPY_FIELDS if k in set(v or [])]
        return (picked, None) if picked else (
            None, (f"חסר ערך בשדה '{f['label']}'" if require else None))
    elif f["type"] == "column":
        v = str(v or "").strip()          # a column id, like connect
    elif f["type"] == "days":
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None, (f"חסר ערך בשדה '{f['label']}'" if require else None)
        # a recurring rule counts an interval, and an interval of nothing is
        # not an interval — see MIN_EVERY_DAYS. "ימים לפני תאריך היעד" has no
        # such floor: zero there is the date itself, which is a real answer.
        return max(int(f.get("min") or 0), min(n, MAX_TRIGGER_DAYS)), None
    elif f["type"] in ("person", "group", "item", "board", "target_group"):
        try:
            return int(v), None
        except (TypeError, ValueError):
            v = ""
    else:                                 # status / priority — a vocabulary key
        v = str(v or "").strip()
    if v == "":
        return None, (f"חסר ערך בשדה '{f['label']}'" if require else None)
    return v, None


def validate_actions(raw, recipe_id, primary_values=None, require_values=False):
    """(clean, error) for a rule's EXTRA actions.

    `require_values` is the difference between a draft and a rule being switched
    on, exactly as it is for the recipe's own placeholders: a draft may hold a
    blank somebody comes back to, an active rule may not.
    """
    if raw in (None, "", []):
        return [], None
    if not isinstance(raw, list):
        return None, "פעולות לא תקינות"
    if len(raw) > MAX_ACTIONS - 1:
        return None, f"אפשר להגדיר עד {MAX_ACTIONS} פעולות בכלל אחד"
    primary = (recipe(recipe_id) or {}).get("action")
    singles = ({_one_per_target(primary, primary_values)}
               if primary in _ONE_PER_RULE else set())
    seen = set()
    if primary:
        seen.add((primary, _sig(primary_values or {})))
    clean = []
    for item in raw:
        if not isinstance(item, dict):
            return None, "פעולות לא תקינות"
        key = str(item.get("key") or "").strip()
        if key not in ACTIONS:
            return None, "פעולה לא מוכרת"
        given = item.get("values")
        if given is not None and not isinstance(given, dict):
            return None, "פעולות לא תקינות"
        values = {}
        for f in action_fields(key):
            if f["type"] == "status":
                sc = status_col_of(given, f["key"])
                if sc:
                    values[status_col_key(f["key"])] = sc
            v, err = _coerce_field(f, (given or {}).get(f["key"]), require_values)
            if err:
                return None, f"{err} בפעולה «{plain(ACTIONS[key])}»"
            if v is not None:
                values[f["key"]] = v
        if key in _ONE_PER_RULE:
            target = _one_per_target(key, values)
            if target in singles:
                return None, (f"«{plain(ACTIONS[key])}» יכולה להופיע פעם אחת "
                              f"בלבד בכלל")
            singles.add(target)
        sig = (key, _sig(values))
        if sig in seen:
            continue                      # the same action twice does it once
        seen.add(sig)
        clean.append({"key": key, "values": values})
    return clean, None


def _sig(values):
    return tuple(sorted((str(k), str(v)) for k, v in (values or {}).items()))


def _primary_values(recipe_id, config):
    r = recipe(recipe_id) or {}
    cfg = config or {}
    out = {f["key"][2:]: cfg.get(f["key"])
           for f in r.get("fields", []) if f["key"].startswith("a_")}
    # the status column rides beside the status under a derived key the field
    # list does not carry, and the duplicate-action check below reads it off
    # these values — without it two actions on two different columns would
    # look like the same action twice
    for f in r.get("fields", []):
        if f["type"] == "status" and f["key"].startswith("a_"):
            sc = status_col_of(cfg, f["key"])
            if sc:
                out[status_col_key(f["key"][2:])] = sc
    return out


# Placeholder keys are namespaced by side (t_ = trigger, a_ = action) so a recipe
# whose trigger and action both take a status keeps them apart.
RECIPES = [
    # ── status ──
    {"id": "status_notify_person", "trigger": "status_changes_to", "action": "notify_person",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_person", "recipient", "נמען")]},
    {"id": "status_notify_assignees", "trigger": "status_changes_to", "action": "notify_assignees",
     "fields": [_f("t_status", "status", "סטטוס")]},
    {"id": "status_assign_person", "trigger": "status_changes_to", "action": "assign_person",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_person", "person", "אחראי")]},
    {"id": "status_move_group", "trigger": "status_changes_to", "action": "move_to_group",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_group", "group", "קבוצה")]},
    {"id": "status_set_priority", "trigger": "status_changes_to", "action": "set_priority",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_priority", "priority", "עדיפות")]},
    # One status moving another. Every other trigger has paired with
    # "שנה את הסטטוס" from the start, and this one did not — back when a board
    # had exactly one status, "כאשר הסטטוס משתנה, שנה את הסטטוס" was a rule
    # that could only talk to itself, so it was left out on purpose.
    #
    # A board with status columns of its own is the case it was missing: "כאשר
    # «שלב תכנון» משתנה ל«אושר», שנה את «שלב ביצוע» ל«התחיל»" is two different
    # columns and the commonest thing people actually want from two of them.
    # The old reading stays available and stays harmless — pointed at the same
    # status it fires once, because the value it writes is not the value it
    # waits for, and writing the value that IS there is skipped.
    {"id": "status_set_status", "trigger": "status_changes_to", "action": "set_status",
     "fields": [_f("t_status", "status", "סטטוס"),
                _f("a_status", "status", "הסטטוס החדש")]},
    {"id": "status_create_subitem", "trigger": "status_changes_to", "action": "create_subitem",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_text", "text", "שם תת־הפריט")]},
    {"id": "status_create_in_board", "trigger": "status_changes_to",
     "action": "create_in_board",
     "fields": [_f("t_status", "status", "סטטוס"),
                _f("a_board", "board", "לוח היעד"),
                _f("a_target_group", "target_group", "הקבוצה בלוח היעד"),
                _f("a_text", "text", "שם הפריט החדש")]},
    {"id": "status_set_column", "trigger": "status_changes_to", "action": "set_column",
     "fields": [_f("t_status", "status", "סטטוס"),
                _f("a_column", "column", "העמודה לעדכון"),
                _f("a_text", "text", "הערך החדש")]},

    # ── item created ──
    {"id": "created_assign_person", "trigger": "item_created", "action": "assign_person",
     "fields": [_f("a_person", "person", "אחראי")]},
    {"id": "created_set_column", "trigger": "item_created", "action": "set_column",
     "fields": [_f("a_column", "column", "העמודה לעדכון"),
                _f("a_text", "text", "הערך החדש")]},
    {"id": "created_set_status", "trigger": "item_created", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},
    {"id": "created_notify_person", "trigger": "item_created", "action": "notify_person",
     "fields": [_f("a_person", "recipient", "נמען")]},
    {"id": "created_set_priority", "trigger": "item_created", "action": "set_priority",
     "fields": [_f("a_priority", "priority", "עדיפות")]},

    # ── priority ──
    {"id": "priority_notify_person", "trigger": "priority_changes_to", "action": "notify_person",
     "fields": [_f("t_priority", "priority", "עדיפות"), _f("a_person", "recipient", "נמען")]},
    {"id": "priority_assign_person", "trigger": "priority_changes_to", "action": "assign_person",
     "fields": [_f("t_priority", "priority", "עדיפות"), _f("a_person", "person", "אחראי")]},

    # ── person assigned ──
    {"id": "assigned_set_status", "trigger": "person_assigned", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},
    {"id": "assigned_notify_person", "trigger": "person_assigned", "action": "notify_person",
     "fields": [_f("a_person", "recipient", "נמען")]},

    # ── due date ──
    {"id": "due_notify_assignees", "trigger": "due_date_arrives", "action": "notify_assignees",
     "fields": []},
    {"id": "due_notify_person", "trigger": "due_date_arrives", "action": "notify_person",
     "fields": [_f("a_person", "recipient", "נמען")]},
    {"id": "due_set_status", "trigger": "due_date_arrives", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},

    # ── links between boards ──
    # linking on creation, and creating-then-linking, which is the same recipe
    # with the far item made rather than chosen
    {"id": "created_link_item", "trigger": "item_created", "action": "link_to_item",
     "fields": [_f("a_connect", "connect", "עמודת הקישור"), _f("a_item", "item", "הפריט לקישור")]},
    {"id": "created_create_and_link", "trigger": "item_created", "action": "create_and_link",
     "fields": [_f("a_connect", "connect", "עמודת הקישור"), _f("a_board", "board", "לוח היעד"),
                _f("a_text", "text", "שם הפריט החדש")]},
    {"id": "status_create_and_link", "trigger": "status_changes_to", "action": "create_and_link",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_connect", "connect", "עמודת הקישור"),
                _f("a_board", "board", "לוח היעד"), _f("a_text", "text", "שם הפריט החדש")]},
    {"id": "status_link_item", "trigger": "status_changes_to", "action": "link_to_item",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_connect", "connect", "עמודת הקישור"),
                _f("a_item", "item", "הפריט לקישור")]},

    # a link being made, or unmade, as the thing that starts a rule
    {"id": "link_added_notify_person", "trigger": "link_added", "action": "notify_person",
     "fields": [_f("a_person", "recipient", "נמען")]},
    {"id": "link_added_notify_assignees", "trigger": "link_added", "action": "notify_assignees",
     "fields": []},
    {"id": "link_added_set_status", "trigger": "link_added", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},
    {"id": "link_removed_notify_person", "trigger": "link_removed", "action": "notify_person",
     "fields": [_f("a_person", "recipient", "נמען")]},
    {"id": "link_removed_notify_assignees", "trigger": "link_removed", "action": "notify_assignees",
     "fields": []},
    {"id": "link_removed_set_status", "trigger": "link_removed", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},

    # the linked item changing, and this item reacting
    {"id": "linked_status_set_status", "trigger": "linked_status_changes_to", "action": "set_status",
     "fields": [_f("t_status", "status", "הסטטוס בפריט המקושר"), _f("a_status", "status", "סטטוס")]},
    {"id": "linked_status_notify_assignees", "trigger": "linked_status_changes_to",
     "action": "notify_assignees", "fields": [_f("t_status", "status", "הסטטוס בפריט המקושר")]},
    {"id": "linked_status_notify_person", "trigger": "linked_status_changes_to",
     "action": "notify_person", "fields": [_f("t_status", "status", "הסטטוס בפריט המקושר"),
                                           _f("a_person", "recipient", "נמען")]},
    {"id": "linked_status_set_priority", "trigger": "linked_status_changes_to",
     "action": "set_priority", "fields": [_f("t_status", "status", "הסטטוס בפריט המקושר"),
                                          _f("a_priority", "priority", "עדיפות")]},

    # ── templates that come WITH conditions ("רק אם") ──
    # The same trigger-and-action pairs as above, but shipped with the second
    # half of the if already on them, so the common two-clause rules are a pick
    # and not an assembly. `conds` names the condition kinds the template starts
    # with; their values are blanks the person fills, exactly like the recipe's
    # own placeholders. Nothing new is stored — the conditions land in `config`
    # under CONDITION_KEY like any other, so a template rule and a hand-built
    # one remain the same row.
    {"id": "cond_status_prio_notify_person", "trigger": "status_changes_to",
     "action": "notify_person", "conds": ["priority_is"],
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_person", "recipient", "נמען")]},
    {"id": "cond_status_prio_open_notify_assignees", "trigger": "status_changes_to",
     "action": "notify_assignees", "conds": ["priority_is", "has_assignee"],
     "fields": [_f("t_status", "status", "סטטוס")]},
    {"id": "cond_created_prio_unassigned_assign", "trigger": "item_created",
     "action": "assign_person", "conds": ["priority_is", "no_assignee"],
     "fields": [_f("a_person", "person", "אחראי")]},
    {"id": "cond_due_open_notify_assignees", "trigger": "due_date_arrives",
     "action": "notify_assignees", "conds": ["status_is_not", "has_assignee"],
     "fields": []},
    {"id": "cond_status_group_prio_move", "trigger": "status_changes_to",
     "action": "move_to_group", "conds": ["group_is", "priority_is"],
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_group", "group", "קבוצה")]},
    {"id": "cond_created_no_due_notify_person", "trigger": "item_created",
     "action": "notify_person", "conds": ["no_due_date"],
     "fields": [_f("a_person", "recipient", "נמען")]},

    # ── the recommended templates that had no recipe ──
    # A sub-item finishing reaches the rule as an event on the PARENT, so
    # "עדכן שדה בפריט האב" is every action the catalog already has.
    {"id": "subitem_done_set_status", "trigger": "subitem_done", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס בפריט האב"), _f("t_on", "pick", "על מי לפעול")]},
    {"id": "subitem_done_set_priority", "trigger": "subitem_done", "action": "set_priority",
     "fields": [_f("a_priority", "priority", "עדיפות בפריט האב"), _f("t_on", "pick", "על מי לפעול")]},
    {"id": "subitem_done_notify_assignees", "trigger": "subitem_done",
     "action": "notify_assignees", "fields": [_f("t_on", "pick", "על מי לפעול")]},
    # "לאפשר ... יצירת תת־פריט נוסף" — the third thing a sub-item rule can do,
    # next to updating the sub-item and updating its parent
    {"id": "subitem_done_create_subitem", "trigger": "subitem_done",
     "action": "create_subitem", "fields": [_f("a_text", "text", "שם תת־הפריט")]},
    {"id": "link_added_copy_to_linked", "trigger": "link_added", "action": "copy_to_linked",
     # the column is optional and means "whichever one the link was made in"
     # when it is left blank — the event names it by id either way, so the
     # target is never found by name
     "fields": [_f("a_fields", "fields", "השדות להעתקה"),
                _f("a_connect", "connect_opt", "עמודת הקישור"),
                _f("a_targets", "pick", "יעד"),
                _f("a_on_missing", "pick", "כשאין פריט מקושר")]},
    {"id": "assigned_post_update", "trigger": "person_assigned", "action": "post_update",
     "fields": [_f("a_text", "text", "תוכן העדכון")]},
    # ── the new sources, each paired with the actions that read naturally ──
    {"id": "moved_group_notify_assignees", "trigger": "moved_to_group",
     "action": "notify_assignees", "fields": [_f("t_group", "group", "קבוצה")]},
    {"id": "moved_group_create_in_board", "trigger": "moved_to_group",
     "action": "create_in_board",
     "fields": [_f("t_group", "group", "קבוצה"),
                _f("a_board", "board", "לוח היעד"),
                _f("a_target_group", "target_group", "הקבוצה בלוח היעד"),
                _f("a_text", "text", "שם הפריט החדש")]},
    {"id": "moved_group_set_status", "trigger": "moved_to_group", "action": "set_status",
     "fields": [_f("t_group", "group", "קבוצה"), _f("a_status", "status", "סטטוס")]},
    {"id": "moved_group_notify_person", "trigger": "moved_to_group",
     "action": "notify_person",
     "fields": [_f("t_group", "group", "קבוצה"), _f("a_person", "recipient", "נמען")]},
    {"id": "subitem_created_notify_assignees", "trigger": "subitem_created",
     "action": "notify_assignees", "fields": [_f("t_on", "pick", "על מי לפעול")]},
    {"id": "subitem_created_set_status", "trigger": "subitem_created", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס בפריט האב"), _f("t_on", "pick", "על מי לפעול")]},
    {"id": "column_changed_notify_person", "trigger": "column_changed",
     "action": "notify_person",
     "fields": [_f("t_column", "column", "עמודה"), _f("a_person", "recipient", "נמען")]},
    {"id": "column_changed_notify_assignees", "trigger": "column_changed",
     "action": "notify_assignees", "fields": [_f("t_column", "column", "עמודה")]},
    {"id": "column_changed_set_status", "trigger": "column_changed", "action": "set_status",
     "fields": [_f("t_column", "column", "עמודה"), _f("a_status", "status", "סטטוס")]},
    # ── writing one of the board's own columns ──
    # "עדכן את העמודה" has been an action since columns could be written, and
    # it had no recipe of its own: it could only ever be added as a SECOND
    # action to a rule built around something else, so "כאשר «לקוחות» משתנה,
    # עדכן את «מנהל פרויקט מקומי»" — a rule about nothing but a column — was
    # not a rule this catalog could express at all.
    #
    # The trigger column and the action column may be the same one, and that
    # is safe for the same reason the status pair is: the value it writes is
    # not the value that set it off, and writing the value already there is
    # skipped.
    {"id": "column_changed_set_column", "trigger": "column_changed", "action": "set_column",
     "fields": [_f("t_column", "column", "עמודה"),
                _f("a_column", "column", "העמודה לעדכון"),
                _f("a_text", "text", "הערך החדש")]},
    {"id": "column_changed_clear_column", "trigger": "column_changed", "action": "clear_column",
     "fields": [_f("t_column", "column", "עמודה"),
                _f("a_column", "column", "העמודה לניקוי")]},
    {"id": "unassigned_notify_person", "trigger": "person_unassigned",
     "action": "notify_person", "fields": [_f("a_person", "recipient", "נמען")]},
    {"id": "unassigned_set_status", "trigger": "person_unassigned", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},
    # ── כל כמה ימים ──
    # The chase: it comes round again for as long as the rule is on and the
    # conditions still hold. "כל 7 ימים, רק אם «קבלת מסמכים» לפני היום וגם
    # «סטטוס ההליך» הוא «קבלת טפסים מהרשות», שלח התראה ל«מנהל פרויקט מקומי»"
    # is the whole of it, and every part of that except the clock already
    # existed.
    {"id": "every_days_notify_person", "trigger": "every_n_days",
     "action": "notify_person",
     "fields": [_f("t_days", "days", "כל כמה ימים", min=MIN_EVERY_DAYS),
                _f("a_person", "recipient", "נמען")]},
    {"id": "every_days_notify_assignees", "trigger": "every_n_days",
     "action": "notify_assignees",
     "fields": [_f("t_days", "days", "כל כמה ימים", min=MIN_EVERY_DAYS)]},
    {"id": "every_days_set_status", "trigger": "every_n_days", "action": "set_status",
     "fields": [_f("t_days", "days", "כל כמה ימים", min=MIN_EVERY_DAYS),
                _f("a_status", "status", "סטטוס")]},
    {"id": "every_days_post_update", "trigger": "every_n_days", "action": "post_update",
     "fields": [_f("t_days", "days", "כל כמה ימים", min=MIN_EVERY_DAYS),
                _f("a_text", "text", "תוכן העדכון")]},
    {"id": "due_near_notify_assignees", "trigger": "due_date_near",
     "action": "notify_assignees", "conds": ["status_is_not"],
     "fields": [_f("t_days", "days", "ימים לפני")]},
    {"id": "due_near_notify_person", "trigger": "due_date_near", "action": "notify_person",
     "fields": [_f("t_days", "days", "ימים לפני"), _f("a_person", "recipient", "נמען")]},
    {"id": "due_passed_notify_assignees", "trigger": "due_date_passed",
     "action": "notify_assignees", "conds": ["status_is_not"],
     "fields": [_f("t_days", "days", "ימים אחרי")]},
    {"id": "due_passed_set_priority", "trigger": "due_date_passed", "action": "set_priority",
     "fields": [_f("t_days", "days", "ימים אחרי"), _f("a_priority", "priority", "עדיפות")]},

    {"id": "status_create_in_group_and_link", "trigger": "status_changes_to",
     "action": "create_in_group_and_link",
     "fields": [_f("t_status", "status", "סטטוס"),
                _f("a_connect", "connect", "עמודת הקישור"),
                _f("a_board", "board", "לוח היעד"),
                _f("a_target_group", "target_group", "הקבוצה בלוח היעד"),
                _f("a_text", "text", "שם הפריט החדש"),
                _f("a_fields", "fields", "השדות להעתקה")]},
]

RECIPES_BY_ID = {r["id"]: r for r in RECIPES}


# ── the template library ────────────────────────────────────────────────────
# The catalog above is what a rule can be BUILT from. The library is how it is
# FOUND: the nine the specification recommends, first and under their own
# names, and the rest searchable and filterable by the six things a person
# actually has in mind — a status, a date, who it is assigned to, a sub-item, a
# link, a notification.

LIBRARY_TAGS = {
    "status":  "סטטוס",
    "date":    "תאריך",
    "assign":  "שיוך",
    "subitem": "תת־פריט",
    "link":    "קישור",
    "notify":  "התראה",
}

_TRIGGER_TAGS = {
    "status_changes_to":        ("status",),
    "priority_changes_to":      (),
    "item_created":             (),
    "person_assigned":          ("assign",),
    "due_date_arrives":         ("date",),
    "link_added":               ("link",),
    "link_removed":             ("link",),
    "linked_status_changes_to": ("link", "status"),
    "subitem_done":             ("subitem", "status"),
    "moved_to_group":           (),
    "subitem_created":          ("subitem",),
    "column_changed":           (),
    "person_unassigned":        ("assign",),
    "due_date_near":            ("date",),
    "due_date_passed":          ("date",),
}
_ACTION_TAGS = {
    "notify_person":    ("notify",),
    "notify_assignees": ("notify", "assign"),
    "assign_person":    ("assign",),
    "set_status":       ("status",),
    "set_priority":     (),
    "move_to_group":    (),
    "create_subitem":   ("subitem",),
    "link_to_item":     ("link",),
    "create_and_link":  ("link",),
    "create_in_board":  (),
    "create_in_group_and_link": ("link",),
    "copy_to_linked":   ("link",),
    "post_update":      (),
}
_COND_TAGS = {
    "status_is": ("status",), "status_is_not": ("status",),
    "person_is": ("assign",), "person_is_not": ("assign",),
    "has_assignee": ("assign",), "no_assignee": ("assign",),
    "has_due_date": ("date",), "no_due_date": ("date",),
    "overdue": ("date",), "not_overdue": ("date",),
}

# What a board must already have for a template to be usable on it. Everything
# else a template needs it asks for when it is filled in; these are the things
# a person cannot answer in the form because they are the board's structure.
NEEDS_HE = {
    "column":           "עמודה מותאמת בלוח (לא מראה ולא קישור)",
    "writable_column":  "עמודה בלוח שאפשר לכתוב בה",
    "connect":          "עמודת קישור בלוח",
    "connect_two_way":  "עמודת קישור דו־כיוונית בלוח",
    "group":            "לפחות קבוצה אחת בלוח",
    "people":           "לפחות משתמש אחד מוזמן ללוח",
}
_TRIGGER_NEEDS = {
    "column_changed":           ("column",),
    "moved_to_group":           ("group",),
    "link_added":               ("connect",),
    "link_removed":             ("connect",),
    "linked_status_changes_to": ("connect_two_way",),
}
_ACTION_NEEDS = {
    "set_column":               ("writable_column",),
    "clear_column":             ("writable_column",),
    "link_to_item":             ("connect",),
    "create_and_link":          ("connect",),
    "create_in_group_and_link": ("connect", "group"),
    "copy_to_linked":           ("connect",),
    "move_to_group":            ("group",),
    "assign_person":            ("people",),
    "notify_person":            ("people",),
}

# The nine the specification recommends for the MVP, in its order, under the
# names it gives them — a library that opened on 43 generated sentences would
# be a list nobody reads.
MVP_TEMPLATES = [
    ("status_move_group",
     "כאשר סטטוס משתנה ל״הושלם״, העבר את הפריט לקבוצת ״הושלמו״"),
    ("created_assign_person",
     "כאשר פריט נוצר, שייך אותו למשתמש מוגדר"),
    ("cond_due_open_notify_assignees",
     "כאשר הגיע תאריך היעד והסטטוס אינו ״הושלם״, שלח התראה לאחראי"),
    ("status_create_subitem",
     "כאשר סטטוס משתנה ל״מאושר״, צור תת־פריט המשך"),
    ("subitem_done_set_status",
     "כאשר תת־פריט הושלם, עדכן שדה בפריט האב"),
    ("link_added_copy_to_linked",
     "כאשר פריט מקושר, העתק ערך מוגדר לפריט המקושר"),
    ("created_create_and_link",
     "כאשר נוצר פריט בלוח מקור, צור פריט בלוח יעד וקשר ביניהם"),
    ("status_create_in_group_and_link",
     "כאשר סטטוס בלוח המקור משתנה, צור פריט בקבוצה בלוח היעד, העתק שדות וקשר אותו"),
    ("assigned_post_update",
     "כאשר אחראי משתנה, הוסף עדכון לשיחת הפריט"),
]
# Templates the library lists BY NAME and shows beside the recommended ones,
# beyond the nine above. MVP_TEMPLATES is a record of what that specification
# asked for and stays as it was; this is the list that grows as the engine
# learns to do things the document did not know about.
#
# A template with no name is rendered as its bare sentence, which is how
# "סטטוס מזיז סטטוס" went missing: 52nd of 59, under a sentence that reads
# "כאשר הסטטוס משתנה ל…, שנה את הסטטוס ל…" — the one reading of it that looks
# like a rule talking to itself, and no hint that the status it writes can be
# a different column from the one it watches. The name is where that is said.
EXTRA_TEMPLATES = [
    ("status_set_status",
     "כאשר עמודת סטטוס משתנה, עדכן עמודת סטטוס אחרת"),
    ("every_days_notify_person",
     "כל כמה ימים, שלח תזכורת כל עוד התנאים מתקיימים"),
    ("column_changed_set_column",
     "כאשר ערך עמודה משתנה, עדכן ערך בעמודה אחרת"),
    ("created_set_column",
     "כאשר נוצר פריט, מלא ערך בעמודה"),
    ("moved_group_create_in_board",
     "כאשר פריט מועבר לקבוצה, צור פריט בלוח אחר"),
]

LIBRARY_TEMPLATES = MVP_TEMPLATES + EXTRA_TEMPLATES
MVP_TITLES = dict(LIBRARY_TEMPLATES)
MVP_ORDER = {rid: i for i, (rid, _) in enumerate(LIBRARY_TEMPLATES)}

# ── template versions ──
# A system template is versioned so that a rule built from it goes on meaning
# what it meant when it was built. The rule stores its own configuration, so a
# version is a statement about the TEMPLATE: bump it for an additive or
# cosmetic change, and give a NEW id to anything that would change what an
# existing rule does — which is why the fuller create-and-link is its own
# action rather than three more placeholders on the old one.
TEMPLATE_VERSIONS = {}


def template_version(recipe_id):
    return TEMPLATE_VERSIONS.get(recipe_id, 1)


def tags_of(recipe_id):
    r = recipe(recipe_id) or {}
    out = set(_TRIGGER_TAGS.get(r.get("trigger"), ())) | set(_ACTION_TAGS.get(r.get("action"), ()))
    for c in r.get("conds") or []:
        out |= set(_COND_TAGS.get(c, ()))
    return sorted(out)


def needs_of(recipe_id):
    r = recipe(recipe_id) or {}
    return sorted(set(_TRIGGER_NEEDS.get(r.get("trigger"), ()))
                  | set(_ACTION_NEEDS.get(r.get("action"), ())))


def recipe(recipe_id):
    return RECIPES_BY_ID.get(recipe_id)


def _sentence_halves(r, config=None, on_trigger=None, on_action=None):
    """(trigger half, action half) with their placeholders renamed, before the
    conditions clause goes between them.

    Split out because the two halves are chosen independently. A rule may name
    a status column for its trigger, for its action, for both or for neither,
    and those are four different sentences — "כאשר הסטטוס משתנה ל…, שנה את
    «שלב ביצוע» ל…" is as ordinary a rule as the two that name one column each.
    Four whole strings would be a table that grows with every recipe; two
    halves, each picked on its own, is the same answer without the table.

    `on_trigger` / `on_action` override what `config` says, for the catalog —
    which has no config and has to serve both readings of each half.
    """
    trig = TRIGGERS[r["trigger"]]
    want = status_col_of(config, "t_status") if on_trigger is None else on_trigger
    if r["trigger"] in STATUS_COL_TEXT and want:
        # "{col}" is spelled out rather than run through the loop below: the
        # column's key is derived from the status blank's (t_status_col), not
        # from the blank's own name
        trig = STATUS_COL_TEXT[r["trigger"]].replace("{col}", "{t_status_col}")
    for k in ("status", "priority", "group", "column", "days"):
        trig = trig.replace("{" + k + "}", "{t_" + k + "}")
    act = ACTIONS[r["action"]]
    want = status_col_of(config, "a_status") if on_action is None else on_action
    if r["action"] in STATUS_COL_TEXT and want:
        act = STATUS_COL_TEXT[r["action"]].replace("{col}", "{a_status_col}")
    for k in ("person", "status", "priority", "group", "text", "connect", "item", "board",
              "fields", "target_group", "column", "days", "map", "targets", "on_missing"):
        act = act.replace("{" + k + "}", "{a_" + k + "}")
    return trig, act


def sentence(recipe_id, cond_phrases=None, action_phrases=None, group_op="and",
             config=None):
    """The recipe as one '{placeholder}'-carrying sentence, for the UI to fill.

    `cond_phrases` are a stored rule's extra conditions, already rendered — they
    go between the trigger and the action, which is where they belong in the
    reading: what happened, what else had to be true, and only then what is
    done about it.

    `action_phrases` are the rule's extra actions, already rendered. They read
    on after the first with "וגם", in the order they run — one sentence for the
    whole rule, because a rule that does four things is still one rule and the
    list has to be legible as one line in the history.

    A rule that names a status column of its own says so — "כאשר «שלב» משתנה
    ל«אושר»" and not "כאשר הסטטוס משתנה ל«אושר»", which would be a sentence
    about a different column on the same board. See _sentence_halves.
    """
    r = recipe(recipe_id)
    if not r:
        return ""
    trig, act = _sentence_halves(r, config)
    clause = conditions_clause(cond_phrases, group_op)
    more = [p for p in (action_phrases or []) if p]
    if more:
        act = act + " וגם " + " וגם ".join(more)
    # A field the templates do not mention gets a slot of its own at the end.
    # Otherwise it is invisible on a screen that renders the sentence and fills
    # its blanks — a field nobody can set, and a default nobody was shown.
    # Generic rather than a special case: the next field added to a recipe gets
    # the same treatment without anyone remembering to arrange it.
    tail = [f["key"] for f in r.get("fields", [])
            if "{" + f["key"] + "}" not in trig + act]
    if tail:
        act = act + " · " + " · ".join("{" + k + "}" for k in tail)
    return f"{trig}, {clause + ', ' if clause else ''}{act}"


def plain(text):
    """A trigger's or action's wording with its blanks shown as "…" — what a
    from-scratch picker lists, before any value has been chosen."""
    out, depth = [], 0
    for ch in text:
        if ch == "{":
            depth += 1
            if depth == 1:
                out.append("…")
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def blueprint():
    """Trigger → the actions that may follow it, for building a rule from scratch.

    A rule built from scratch is still one of the recipes: picking a trigger and
    then an action lands on the recipe that pairs them. Nothing else is stored,
    so a hand-built rule and one picked off a template are the same row, checked
    by the same validation — the two paths cannot drift apart.
    """
    out = []
    for trig, text in TRIGGERS.items():
        # a conditioned template is NOT offered here: picking a trigger and an
        # action has to land on exactly one recipe, and the conditions in this
        # flow are step 2, chosen rather than inherited
        acts = [{"action": r["action"], "label": plain(ACTIONS[r["action"]]),
                 "recipe_id": r["id"]}
                for r in RECIPES if r["trigger"] == trig and not r.get("conds")]
        if acts:
            out.append({"trigger": trig, "label": plain(text), "actions": acts})
    return out


def recipe_conditions(recipe_id):
    """The conditions a template arrives with, described for the picker: what
    each one says, and what kind of value it still needs."""
    out = []
    for kind in (recipe(recipe_id) or {}).get("conds", []):
        spec = CONDITIONS.get(kind)
        if not spec:
            continue
        out.append({"kind": kind, "label": condition_text(kind),
                    "type": spec["type"], "value_label": spec.get("label", "")})
    return out


def _takes_status_col(r, field_key):
    """Whether this status blank may name a column of its own.

    The trigger and the action that WRITE or LISTEN to a status can; the rest
    cannot, and the one that matters is "הסטטוס של פריט מקושר" — that status
    lives on another board's item and is the built-in one by definition.
    """
    side = r["trigger"] if field_key.startswith("t_") else r["action"]
    return side in STATUS_COL_TEXT


def _sentence_parts(r):
    """Both readings of each half, for a screen that composes the sentence
    while somebody is still choosing.

    The halves are joined with ", " — exactly what sentence() does when a rule
    carries no conditions and no extra actions, which is every rule being
    built. The "_col" reading is "" for a half whose status cannot name a
    column, and that is how the screen knows not to offer the choice there.
    """
    trig, act = _sentence_halves(r, on_trigger=False, on_action=False)
    tcol, _ = _sentence_halves(r, on_trigger=True, on_action=False)
    _, acol = _sentence_halves(r, on_trigger=False, on_action=True)
    # the slot sentence() gives a field the wording does not mention goes on
    # the action half, and it has to travel with it — a screen composing from
    # these parts would otherwise drop the one blank nothing else shows
    tail = [f["key"] for f in r.get("fields", [])
            if "{" + f["key"] + "}" not in trig + act]
    if tail:
        more = " · " + " · ".join("{" + k + "}" for k in tail)
        act, acol = act + more, acol + more
    can = lambda k: any(f["key"] == k and f["type"] == "status"
                        and _takes_status_col(r, k) for f in r["fields"])
    return {"trigger": trig, "action": act,
            "trigger_col": tcol if can("t_status") else "",
            "action_col": acol if can("a_status") else ""}


def catalog():
    """The full catalog the UI renders in the 'automation from a recipe' picker."""
    return [{"id": r["id"], "trigger": r["trigger"], "action": r["action"],
             "sentence": sentence(r["id"]), "fields": r["fields"],
             # Each half of the sentence in both its readings, so the builder
             # can pick them independently: a rule may name a status column for
             # its trigger, for its action, for both or for neither.
             "sentence_parts": _sentence_parts(r),
             "status_fields": [f["key"] for f in r["fields"]
                               if f["type"] == "status"
                               and _takes_status_col(r, f["key"])],
             # a template that comes with its own conditions says so; one that
             # does not sends an empty list and reads exactly as it always did
             "conditions": recipe_conditions(r["id"]),
             # and what the library needs of it: the name it is listed under,
             # what it is about, what the board must already have, and which
             # version of the template this is
             "title": MVP_TITLES.get(r["id"], ""),
             "recommended": r["id"] in MVP_TITLES,
             "order": MVP_ORDER.get(r["id"], len(MVP_ORDER)),
             "tags": tags_of(r["id"]), "needs": needs_of(r["id"]),
             "version": template_version(r["id"])} for r in RECIPES]


def validate_partial(recipe_id, config):
    """(clean_config, error) for a DRAFT — what is filled in is kept, what is
    missing is allowed to be missing.

    A draft exists so a half-built rule can be put down and picked up later, so
    the only thing refused here is nonsense: an unknown recipe, or a value in a
    field the recipe does not have. Completeness is the activation's problem —
    see validate() and the blockers the engine re-derives before every run.
    """
    r = recipe(recipe_id)
    if not r:
        return None, "מתכון לא מוכר"
    if not isinstance(config, dict):
        return None, "הגדרות לא תקינות"
    clean = {}
    for f in r["fields"]:
        # The status column travels beside the value and not inside it, so it
        # has to be carried here by hand — the loop walks the recipe's own
        # fields and `t_status_col` is not one of them. Empty is not kept:
        # that is the board's own status, which is what silence has always
        # meant and what every rule written before this holds.
        if f["type"] == "status":
            _sc = status_col_of(config, f["key"])
            if _sc:
                clean[status_col_key(f["key"])] = _sc
        v = config.get(f["key"])
        if v is None or v == "" or v == []:
            continue                              # not filled in yet, and that is allowed
        if f["type"] == "text":
            v = (str(v)).strip()[:200]
            if unknown_tokens(v):
                continue              # a half-typed token is simply not kept
        elif f["type"] in ("connect", "column", "connect_opt"):
            v = (str(v)).strip()
        elif f["type"] == "pick":
            clean[f["key"]] = pick_value(pick_key(f), v)
            continue
        elif f["type"] == "days":
            try:
                v = max(int(f.get("min") or 0), min(int(v), MAX_TRIGGER_DAYS))
            except (TypeError, ValueError):
                continue
            clean[f["key"]] = v
            continue
        elif f["type"] == "recipient":
            v, rerr = recipient_value(v)
            if rerr:
                continue                          # half-chosen: simply not kept
            clean[f["key"]] = v
            continue
        elif f["type"] == "map":
            v, merr = map_value(v)
            if merr:
                continue                          # half-built: simply not kept
            clean[f["key"]] = v
            continue
        elif f["type"] == "wait":
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            clean[f["key"]] = max(MIN_WAIT_MINUTES, min(v, MAX_WAIT_DAYS * 24 * 60))
            continue
        elif f["type"] == "fields":
            v = [k for k in COPY_FIELDS if k in set(v or [])]
            if v:
                clean[f["key"]] = v
            continue
        elif f["type"] in ("person", "group", "item", "board", "target_group"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue                          # a half-typed value is simply not kept
        else:
            v = (str(v)).strip()
        if v != "":
            clean[f["key"]] = v
    conds, cerr = validate_conditions(config.get(CONDITION_KEY))
    if cerr:
        return None, cerr
    if conds:
        clean[CONDITION_KEY] = conds
    acts, aerr = validate_actions(config.get(ACTIONS_KEY), recipe_id,
                                  _primary_values(recipe_id, clean))
    if aerr:
        return None, aerr
    if acts:
        clean[ACTIONS_KEY] = acts
    return clean, None


def missing_fields(recipe_id, config):
    """The placeholders a draft still has to fill before it can be switched on.

    An extra action's blank is named with the action it belongs to — four
    actions can want four different people, and "נמען" on its own would not say
    which one is still empty.
    """
    r = recipe(recipe_id)
    if not r:
        return ["מתכון לא מוכר"]
    cfg = config or {}
    out = [f["label"] for f in r["fields"]
           if f["type"] not in OPTIONAL_TYPES and cfg.get(f["key"]) in (None, "", [])]
    for i, extra in enumerate((cfg.get(ACTIONS_KEY) or []), start=2):
        key = str((extra or {}).get("key") or "")
        values = (extra or {}).get("values") or {}
        for f in action_fields(key):
            if f["type"] in OPTIONAL_TYPES:
                continue                      # blank is a value, not a blank
            if values.get(f["key"]) in (None, "", []):
                out.append(f"{f['label']} (פעולה {i})")
    return out


def validate(recipe_id, config):
    """(clean_config, error). Every declared placeholder must be filled, and
    nothing else is stored — a rule can't smuggle in extra keys."""
    r = recipe(recipe_id)
    if not r:
        return None, "מתכון לא מוכר"
    if not isinstance(config, dict):
        return None, "הגדרות לא תקינות"
    clean = {}
    for f in r["fields"]:
        # see clean(): the column a status blank names rides beside it, under a
        # derived key the recipe's own field list does not mention
        if f["type"] == "status":
            _sc = status_col_of(config, f["key"])
            if _sc:
                clean[status_col_key(f["key"])] = _sc
        v = config.get(f["key"])
        if f["type"] == "text":
            v = (str(v or "")).strip()[:200]
            if not v:
                return None, f"חסר ערך בשדה '{f['label']}'"
            # a token nobody can answer is refused where it is written, not
            # left to resolve into nothing at three in the morning
            bad = unknown_tokens(v)
            if bad:
                return None, "ערך דינמי לא מוכר: {{" + bad[0] + "}}"
        elif f["type"] == "connect":
            v = (str(v or "")).strip()          # a column id, not a number
            if not v:
                return None, f"חסר ערך בשדה '{f['label']}'"
        elif f["type"] == "connect_opt":
            v = (str(v or "")).strip()          # blank means "the one in the event"
        elif f["type"] == "pick":
            v = pick_value(pick_key(f), v)
        elif f["type"] == "recipient":
            v, rerr = recipient_value(v)
            if rerr:
                return None, rerr
        elif f["type"] == "map":
            v, merr = map_value(v)
            if merr:
                return None, merr
        elif f["type"] == "wait":
            try:
                v = int(v)
            except (TypeError, ValueError):
                return None, f"חסר ערך בשדה '{f['label']}'"
            if v < MIN_WAIT_MINUTES or v > MAX_WAIT_DAYS * 24 * 60:
                return None, f"המתנה היא בין דקה ל-{MAX_WAIT_DAYS} ימים"
        elif f["type"] == "fields":
            v = [k for k in COPY_FIELDS if k in set(v or [])]
            if not v:
                return None, f"חסר ערך בשדה '{f['label']}'"
        elif f["type"] == "column":
            v = (str(v or "")).strip()
            if not v:
                return None, f"חסר ערך בשדה '{f['label']}'"
        elif f["type"] == "days":
            try:
                v = max(int(f.get("min") or 0), min(int(v), MAX_TRIGGER_DAYS))
            except (TypeError, ValueError):
                return None, f"חסר ערך בשדה '{f['label']}'"
        elif f["type"] in ("person", "group", "item", "board", "target_group"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return None, f"חסר ערך בשדה '{f['label']}'"
        else:                                   # status / priority — a vocabulary key
            v = (str(v or "")).strip()
            if not v:
                return None, f"חסר ערך בשדה '{f['label']}'"
        clean[f["key"]] = v
    conds, cerr = validate_conditions(config.get(CONDITION_KEY))
    if cerr:
        return None, cerr
    if conds:
        clean[CONDITION_KEY] = conds
        gop, gerr = condition_group_op(config.get(CONDITION_GROUP_KEY), conds)
        if gerr:
            return None, gerr
        if gop != "and":
            clean[CONDITION_GROUP_KEY] = gop
        gop, gerr = condition_group_op(config.get(CONDITION_GROUP_KEY), conds)
        if gerr:
            return None, gerr
        if gop != "and":
            clean[CONDITION_GROUP_KEY] = gop
    acts, aerr = validate_actions(config.get(ACTIONS_KEY), recipe_id,
                                  _primary_values(recipe_id, clean),
                                  require_values=True)
    if aerr:
        return None, aerr
    if acts:
        clean[ACTIONS_KEY] = acts
    return clean, None
