"""Board automations — the recipe catalog ("אם–אז", Monday-style).

Pure data plus validation: no database and no app imports, so it can be read by
the API, the engine and the tests without a circular import. The engine that
actually fires these lives in main.py, next to the task endpoints it hooks.

A recipe pairs one trigger with one action and declares the placeholders a board
admin fills in. A stored Automation keeps only `recipe_id` + the filled values,
so a recipe's wording can be improved later without rewriting saved rules.
"""

import filter_ast          # pure, like this module: no app imports, no database

# ── field types the UI knows how to render ──────────────────────────
# status/priority → the board's own vocabulary; person → a board member;
# group → a group on the board; text → free text.
# connect → a connect column on this board; item → a specific item to link to;
# board → one of the boards that connect column points at.
FIELD_TYPES = ("status", "priority", "person", "group", "text",
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
    """How a column of this type can be asked about — None if it cannot be."""
    t = str(col_type or "")
    if t == "mirror":
        return MIRROR_KIND
    return filter_ast.KINDS.get(t)


def column_types():
    """Every column type a condition can be written against, grouped by the
    kind that decides what its value looks like."""
    out = {}
    for t, kind in filter_ast.KINDS.items():
        out.setdefault(kind, []).append(t)
    out.setdefault(MIRROR_KIND, []).append("mirror")
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


def conditions_clause(phrases):
    """The whole "רק אם" clause from already-rendered condition phrases."""
    parts = [p for p in (phrases or []) if p]
    if not parts:
        return ""
    return "ורק אם " + " וגם ".join(parts)


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
    v = raw.get("value")
    if kind == "check":
        v = bool(v)
    elif kind == "people":
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None, "חסר ערך בתנאי על העמודה"
    elif kind == "number":
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None, "הערך בתנאי על העמודה אינו מספר"
        if v == int(v):
            v = int(v)                 # 1000, not 1000.0, in the sentence
    elif kind == "date":
        v = str(v or "").strip()
        if not (filter_ast._ISO_DAY.match(v) or v in filter_ast.DATE_TOKENS):
            return None, "חסר תאריך בתנאי על העמודה"
    else:
        v = str(v if v is not None else "").strip()[:200]
        if not v:
            return None, "חסר ערך בתנאי על העמודה"
    return {"col": col, "type": col_type, "value": v}, None


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
    for col in {c["value"]["col"] for c in conds if c["kind"] in COLUMN_CONDITIONS}:
        vals = {str(c["value"]["value"]) for c in conds
                if c["kind"] == "column_is" and c["value"]["col"] == col}
        multi = any(c["value"]["type"] in MULTI_COLUMN_TYPES
                    for c in conds if c["kind"] in COLUMN_CONDITIONS
                    and c["value"]["col"] == col)
        if len(vals) > 1 and not multi:
            return "לא ניתן להתנות בשני ערכים שונים באותה עמודה"
        refused = {str(c["value"]["value"]) for c in conds
                   if c["kind"] == "column_is_not" and c["value"]["col"] == col}
        if vals & refused:
            return "תנאי על עמודה סותר את ההיפוך שלו באותו ערך"
    return None


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
    "create_and_link":  "צור פריט בשם {text} בלוח {board} וקשר אותו בעמודה {connect}",
    # ── and the three the template library asked for ──
    "post_update":      "הוסף עדכון לשיחת הפריט: {text}",
    "copy_to_linked":   "העתק {fields} לפריט המקושר",
    # the fuller form of create_and_link: it says which group on the target
    # board, and which of the item's own fields travel with it. A separate
    # action rather than three more placeholders on the old one — a rule
    # somebody already built is not re-asked a question it was never asked.
    "create_in_group_and_link":
        "צור פריט בשם {text} בקבוצה {target_group} בלוח {board}, העתק {fields} "
        "וקשר אותו בעמודה {connect}",
}

# What "השדות שהוגדרו" may be. The item's own built-ins, which every board has
# — a custom column exists on one board under one id and on the next board
# under another, so copying those is a mapping between two boards' columns and
# not a list of checkboxes. That is in the Roadmap, not here.
# How far from the due date a "before"/"after" trigger may be set.
MAX_TRIGGER_DAYS = 365

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


def _f(key, type_, label):
    return {"key": key, "type": type_, "label": label}


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
MAX_ACTIONS = 4

# What each action needs filled in. Keyed by the bare field name; the recipe's
# own action declares the same fields prefixed `a_` (see RECIPES), and
# action_list below reads the two into one shape.
ACTION_FIELDS = {
    "notify_person":    [_f("person", "person", "נמען")],
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
    "post_update":      [_f("text", "text", "תוכן העדכון")],
    "copy_to_linked":   [_f("fields", "fields", "השדות להעתקה")],
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


def action_fields(key):
    return ACTION_FIELDS.get(key, [])


def actions_catalog():
    """Every action a rule can be given, for the "פעולה נוספת" picker."""
    # `text` carries the blanks ("{person}") so the builder can put a chip in
    # each one, the way the rule's own sentence does; `label` is the same line
    # with the blanks shown as "…", for the picker that offers it.
    return [{"key": k, "label": plain(text), "text": text,
             "fields": action_fields(k)} for k, text in ACTIONS.items()]


def action_text(key, shown=None):
    """One action as a phrase. `shown` maps a field key to the value already
    rendered the way the board shows it; a blank stays a blank."""
    text = ACTIONS.get(key, "")
    for f in action_fields(key):
        v = (shown or {}).get(f["key"])
        text = text.replace("{" + f["key"] + "}",
                            v if v not in (None, "") else "…")
    return text


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
        out.append({"key": r["action"],
                    "values": {f["key"][2:]: cfg.get(f["key"])
                               for f in r.get("fields", []) if f["key"].startswith("a_")},
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
    elif f["type"] == "connect":
        v = str(v or "").strip()          # a column id, not a number
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
            return max(0, min(int(v), MAX_TRIGGER_DAYS)), None
        except (TypeError, ValueError):
            return None, (f"חסר ערך בשדה '{f['label']}'" if require else None)
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
    singles = {primary} & set(_ONE_PER_RULE)
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
            v, err = _coerce_field(f, (given or {}).get(f["key"]), require_values)
            if err:
                return None, f"{err} בפעולה «{plain(ACTIONS[key])}»"
            if v is not None:
                values[f["key"]] = v
        if key in _ONE_PER_RULE:
            if key in singles:
                return None, (f"«{plain(ACTIONS[key])}» יכולה להופיע פעם אחת "
                              f"בלבד בכלל")
            singles.add(key)
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
    return {f["key"][2:]: cfg.get(f["key"])
            for f in r.get("fields", []) if f["key"].startswith("a_")}


# Placeholder keys are namespaced by side (t_ = trigger, a_ = action) so a recipe
# whose trigger and action both take a status keeps them apart.
RECIPES = [
    # ── status ──
    {"id": "status_notify_person", "trigger": "status_changes_to", "action": "notify_person",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_person", "person", "נמען")]},
    {"id": "status_notify_assignees", "trigger": "status_changes_to", "action": "notify_assignees",
     "fields": [_f("t_status", "status", "סטטוס")]},
    {"id": "status_assign_person", "trigger": "status_changes_to", "action": "assign_person",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_person", "person", "אחראי")]},
    {"id": "status_move_group", "trigger": "status_changes_to", "action": "move_to_group",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_group", "group", "קבוצה")]},
    {"id": "status_set_priority", "trigger": "status_changes_to", "action": "set_priority",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_priority", "priority", "עדיפות")]},
    {"id": "status_create_subitem", "trigger": "status_changes_to", "action": "create_subitem",
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_text", "text", "שם תת־הפריט")]},

    # ── item created ──
    {"id": "created_assign_person", "trigger": "item_created", "action": "assign_person",
     "fields": [_f("a_person", "person", "אחראי")]},
    {"id": "created_set_status", "trigger": "item_created", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},
    {"id": "created_notify_person", "trigger": "item_created", "action": "notify_person",
     "fields": [_f("a_person", "person", "נמען")]},
    {"id": "created_set_priority", "trigger": "item_created", "action": "set_priority",
     "fields": [_f("a_priority", "priority", "עדיפות")]},

    # ── priority ──
    {"id": "priority_notify_person", "trigger": "priority_changes_to", "action": "notify_person",
     "fields": [_f("t_priority", "priority", "עדיפות"), _f("a_person", "person", "נמען")]},
    {"id": "priority_assign_person", "trigger": "priority_changes_to", "action": "assign_person",
     "fields": [_f("t_priority", "priority", "עדיפות"), _f("a_person", "person", "אחראי")]},

    # ── person assigned ──
    {"id": "assigned_set_status", "trigger": "person_assigned", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},
    {"id": "assigned_notify_person", "trigger": "person_assigned", "action": "notify_person",
     "fields": [_f("a_person", "person", "נמען")]},

    # ── due date ──
    {"id": "due_notify_assignees", "trigger": "due_date_arrives", "action": "notify_assignees",
     "fields": []},
    {"id": "due_notify_person", "trigger": "due_date_arrives", "action": "notify_person",
     "fields": [_f("a_person", "person", "נמען")]},
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
     "fields": [_f("a_person", "person", "נמען")]},
    {"id": "link_added_notify_assignees", "trigger": "link_added", "action": "notify_assignees",
     "fields": []},
    {"id": "link_added_set_status", "trigger": "link_added", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},
    {"id": "link_removed_notify_person", "trigger": "link_removed", "action": "notify_person",
     "fields": [_f("a_person", "person", "נמען")]},
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
                                           _f("a_person", "person", "נמען")]},
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
     "fields": [_f("t_status", "status", "סטטוס"), _f("a_person", "person", "נמען")]},
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
     "fields": [_f("a_person", "person", "נמען")]},

    # ── the recommended templates that had no recipe ──
    # A sub-item finishing reaches the rule as an event on the PARENT, so
    # "עדכן שדה בפריט האב" is every action the catalog already has.
    {"id": "subitem_done_set_status", "trigger": "subitem_done", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס בפריט האב")]},
    {"id": "subitem_done_set_priority", "trigger": "subitem_done", "action": "set_priority",
     "fields": [_f("a_priority", "priority", "עדיפות בפריט האב")]},
    {"id": "subitem_done_notify_assignees", "trigger": "subitem_done",
     "action": "notify_assignees", "fields": []},
    {"id": "link_added_copy_to_linked", "trigger": "link_added", "action": "copy_to_linked",
     "fields": [_f("a_fields", "fields", "השדות להעתקה")]},
    {"id": "assigned_post_update", "trigger": "person_assigned", "action": "post_update",
     "fields": [_f("a_text", "text", "תוכן העדכון")]},
    # ── the new sources, each paired with the actions that read naturally ──
    {"id": "moved_group_notify_assignees", "trigger": "moved_to_group",
     "action": "notify_assignees", "fields": [_f("t_group", "group", "קבוצה")]},
    {"id": "moved_group_set_status", "trigger": "moved_to_group", "action": "set_status",
     "fields": [_f("t_group", "group", "קבוצה"), _f("a_status", "status", "סטטוס")]},
    {"id": "moved_group_notify_person", "trigger": "moved_to_group",
     "action": "notify_person",
     "fields": [_f("t_group", "group", "קבוצה"), _f("a_person", "person", "נמען")]},
    {"id": "subitem_created_notify_assignees", "trigger": "subitem_created",
     "action": "notify_assignees", "fields": []},
    {"id": "subitem_created_set_status", "trigger": "subitem_created", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס בפריט האב")]},
    {"id": "column_changed_notify_person", "trigger": "column_changed",
     "action": "notify_person",
     "fields": [_f("t_column", "column", "עמודה"), _f("a_person", "person", "נמען")]},
    {"id": "column_changed_notify_assignees", "trigger": "column_changed",
     "action": "notify_assignees", "fields": [_f("t_column", "column", "עמודה")]},
    {"id": "column_changed_set_status", "trigger": "column_changed", "action": "set_status",
     "fields": [_f("t_column", "column", "עמודה"), _f("a_status", "status", "סטטוס")]},
    {"id": "unassigned_notify_person", "trigger": "person_unassigned",
     "action": "notify_person", "fields": [_f("a_person", "person", "נמען")]},
    {"id": "unassigned_set_status", "trigger": "person_unassigned", "action": "set_status",
     "fields": [_f("a_status", "status", "סטטוס")]},
    {"id": "due_near_notify_assignees", "trigger": "due_date_near",
     "action": "notify_assignees", "conds": ["status_is_not"],
     "fields": [_f("t_days", "days", "ימים לפני")]},
    {"id": "due_near_notify_person", "trigger": "due_date_near", "action": "notify_person",
     "fields": [_f("t_days", "days", "ימים לפני"), _f("a_person", "person", "נמען")]},
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
MVP_TITLES = dict(MVP_TEMPLATES)
MVP_ORDER = {rid: i for i, (rid, _) in enumerate(MVP_TEMPLATES)}

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


def sentence(recipe_id, cond_phrases=None, action_phrases=None):
    """The recipe as one '{placeholder}'-carrying sentence, for the UI to fill.

    `cond_phrases` are a stored rule's extra conditions, already rendered — they
    go between the trigger and the action, which is where they belong in the
    reading: what happened, what else had to be true, and only then what is
    done about it.

    `action_phrases` are the rule's extra actions, already rendered. They read
    on after the first with "וגם", in the order they run — one sentence for the
    whole rule, because a rule that does four things is still one rule and the
    list has to be legible as one line in the history.
    """
    r = recipe(recipe_id)
    if not r:
        return ""
    trig = TRIGGERS[r["trigger"]]
    for k in ("status", "priority", "group", "column", "days"):
        trig = trig.replace("{" + k + "}", "{t_" + k + "}")
    act = ACTIONS[r["action"]]
    for k in ("person", "status", "priority", "group", "text", "connect", "item", "board",
              "fields", "target_group"):
        act = act.replace("{" + k + "}", "{a_" + k + "}")
    clause = conditions_clause(cond_phrases)
    more = [p for p in (action_phrases or []) if p]
    if more:
        act = act + " וגם " + " וגם ".join(more)
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


def catalog():
    """The full catalog the UI renders in the 'automation from a recipe' picker."""
    return [{"id": r["id"], "trigger": r["trigger"], "action": r["action"],
             "sentence": sentence(r["id"]), "fields": r["fields"],
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
        v = config.get(f["key"])
        if v is None or v == "" or v == []:
            continue                              # not filled in yet, and that is allowed
        if f["type"] == "text":
            v = (str(v)).strip()[:200]
        elif f["type"] in ("connect", "column"):
            v = (str(v)).strip()
        elif f["type"] == "days":
            try:
                v = max(0, min(int(v), MAX_TRIGGER_DAYS))
            except (TypeError, ValueError):
                continue
            clean[f["key"]] = v
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
           if cfg.get(f["key"]) in (None, "", [])]
    for i, extra in enumerate((cfg.get(ACTIONS_KEY) or []), start=2):
        key = str((extra or {}).get("key") or "")
        values = (extra or {}).get("values") or {}
        for f in action_fields(key):
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
        v = config.get(f["key"])
        if f["type"] == "text":
            v = (str(v or "")).strip()[:200]
            if not v:
                return None, f"חסר ערך בשדה '{f['label']}'"
        elif f["type"] == "connect":
            v = (str(v or "")).strip()          # a column id, not a number
            if not v:
                return None, f"חסר ערך בשדה '{f['label']}'"
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
                v = max(0, min(int(v), MAX_TRIGGER_DAYS))
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
    acts, aerr = validate_actions(config.get(ACTIONS_KEY), recipe_id,
                                  _primary_values(recipe_id, clean),
                                  require_values=True)
    if aerr:
        return None, aerr
    if acts:
        clean[ACTIONS_KEY] = acts
    return clean, None
