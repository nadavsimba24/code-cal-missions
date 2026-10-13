"""Board automations — the recipe catalog ("אם–אז", Monday-style).

Pure data plus validation: no database and no app imports, so it can be read by
the API, the engine and the tests without a circular import. The engine that
actually fires these lives in main.py, next to the task endpoints it hooks.

A recipe pairs one trigger with one action and declares the placeholders a board
admin fills in. A stored Automation keeps only `recipe_id` + the filled values,
so a recipe's wording can be improved later without rewriting saved rules.
"""

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
    the board shows it; without one the blank stays a blank."""
    spec = CONDITIONS.get(kind)
    if not spec:
        return ""
    if spec["type"] is None:
        return spec["text"]
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
        elif t in ("person", "group"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return None, f"חסר ערך בתנאי '{condition_text(kind)}'"
        else:
            v = str(v or "").strip()
            if not v:
                return None, f"חסר ערך בתנאי '{condition_text(kind)}'"
        sig = (kind, v)
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
}


def _f(key, type_, label):
    return {"key": key, "type": type_, "label": label}


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
]

RECIPES_BY_ID = {r["id"]: r for r in RECIPES}


def recipe(recipe_id):
    return RECIPES_BY_ID.get(recipe_id)


def sentence(recipe_id, cond_phrases=None):
    """The recipe as one '{placeholder}'-carrying sentence, for the UI to fill.

    `cond_phrases` are a stored rule's extra conditions, already rendered — they
    go between the trigger and the action, which is where they belong in the
    reading: what happened, what else had to be true, and only then what is
    done about it.
    """
    r = recipe(recipe_id)
    if not r:
        return ""
    trig = TRIGGERS[r["trigger"]].replace("{status}", "{t_status}").replace("{priority}", "{t_priority}")
    act = ACTIONS[r["action"]]
    for k in ("person", "status", "priority", "group", "text", "connect", "item", "board"):
        act = act.replace("{" + k + "}", "{a_" + k + "}")
    clause = conditions_clause(cond_phrases)
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
             "conditions": recipe_conditions(r["id"])} for r in RECIPES]


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
        if v is None or v == "":
            continue                              # not filled in yet, and that is allowed
        if f["type"] == "text":
            v = (str(v)).strip()[:200]
        elif f["type"] == "connect":
            v = (str(v)).strip()
        elif f["type"] in ("person", "group", "item", "board"):
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
    return clean, None


def missing_fields(recipe_id, config):
    """The placeholders a draft still has to fill before it can be switched on."""
    r = recipe(recipe_id)
    if not r:
        return ["מתכון לא מוכר"]
    cfg = config or {}
    return [f["label"] for f in r["fields"]
            if cfg.get(f["key"]) in (None, "", [])]


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
        elif f["type"] in ("person", "group", "item", "board"):
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
    return clean, None
