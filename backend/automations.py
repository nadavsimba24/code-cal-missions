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
]

RECIPES_BY_ID = {r["id"]: r for r in RECIPES}


def recipe(recipe_id):
    return RECIPES_BY_ID.get(recipe_id)


def sentence(recipe_id):
    """The recipe as one '{placeholder}'-carrying sentence, for the UI to fill."""
    r = recipe(recipe_id)
    if not r:
        return ""
    trig = TRIGGERS[r["trigger"]].replace("{status}", "{t_status}").replace("{priority}", "{t_priority}")
    act = ACTIONS[r["action"]]
    for k in ("person", "status", "priority", "group", "text", "connect", "item", "board"):
        act = act.replace("{" + k + "}", "{a_" + k + "}")
    return f"{trig}, {act}"


def catalog():
    """The full catalog the UI renders in the 'automation from a recipe' picker."""
    return [{"id": r["id"], "trigger": r["trigger"], "action": r["action"],
             "sentence": sentence(r["id"]), "fields": r["fields"]} for r in RECIPES]


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
    return clean, None
