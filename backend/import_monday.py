"""Turn a monday.com API response into the shape the board importer already speaks.

Pure translation: no database, no HTTP, no side effects. Everything this module
decides to leave out is reported back, because the failure mode of an importer
is not crashing — it is quietly dropping a column and letting someone find out
weeks later.

The response monday returns is nested and repetitive. Column titles and types
arrive again inside every single item, so a 320-item board with 64 columns
spends most of its bytes restating the same 64 titles. What matters is small:
the item names, and the cells that actually have something in them.

The type table below is the migration's mapping sheet, column for column. Where
monday has a type we have no counterpart for, the cell comes in as text rather
than being dropped — a phone number in a text column is still the phone number,
and losing it silently is the one outcome a migration cannot afford.
"""
import html as _html
import json
import re

# monday column type -> our column type, per the migration mapping sheet.
TYPE_MAP = {
    # things we hold as the same kind of thing
    "status":         "status",
    "color":          "status",     # monday's older name for the same thing
    "button":         "status",     # no button here; a status drives the action
    "date":           "date",
    "timeline":       "timeline",
    "people":         "people",
    "person":         "people",
    "item_assignees": "people",
    "numbers":        "number",
    "numeric":        "number",
    "auto_number":    "number",
    "rating":         "rating",
    "dropdown":       "dropdown",
    "tags":           "dropdown",
    "checkbox":       "checkbox",
    "boolean":        "checkbox",
    "file":           "files",
    "doc":            "files",
    "email":          "email",
    # things that arrive as text, because that keeps the value readable and we
    # have nowhere better to put it
    "text":           "text",
    "long_text":      "text",
    "long-text":      "text",
    "phone":          "text",
    "link":           "text",
    "location":       "text",
    "country":        "text",
    "color_picker":   "text",
    "hour":           "text",
    "week":           "text",
    "world_clock":    "text",
    "creation_log":   "text",
    "last_updated":   "text",
    "item_id":        "text",       # monday's id, kept; ours is issued separately
    "formula":        "text",       # the computed value, not the formula
    "mirror":         "text",       # the shown value; the source board isn't here
    "board_relation": "text",       # names of the linked items; the board isn't here
    "name":           "text",
}

# Types with no value to carry over, and why — shown to the user.
UNSUPPORTED = {
    "dependency":     "תלות בין פריטים — לא נתמך",
    "progress":       "מעקב התקדמות — לא נתמך",
    "team":           "צוות — לא נתמך",
    "time_tracking":  "מעקב זמן — לא נתמך",
    "vote":           "הצבעה — לא נתמך",
    "direct_doc":     "מסמך מאנדיי — נשאר במאנדיי, אין לו מקבילה כאן",
}

# monday's sub-items column is not a column here at all: its content arrives as
# the items' own sub-items. Reported on its own, because listing it among the
# columns that did not come in says the exact opposite of what happened.
SUBITEMS_TYPE = "subtasks"

# The types monday does not answer in `text`. Their values live in
# `display_value` (and, for a connect column, in `linked_items`), and a query
# that does not ask for it gets nothing for them on any item.
DISPLAY_VALUE_TYPES = ("formula", "mirror", "board_relation", "dependency")

# What monday puts in display_value when a formula worked out to nothing. It is
# the JavaScript leaking through, not a value anyone typed: a formula over a date
# that is not filled in yet answers the four characters "null", and on her board
# 315 of one column's 320 cells were exactly that — a column that read as full
# and said nothing. Treated as empty, which is what it means.
#
# "#ERROR!" is deliberately not here: that is monday stating something true
# about the formula, and a cell saying so is more use than a blank one.
FORMULA_NOTHING = {"null", "nan", "undefined", "none"}

# Where a monday type lands somewhere other than the obvious place, the report
# says so — an import that quietly retypes a column is an import you cannot
# check.
RETYPED = {
    "formula":        "הערך המחושב יובא כטקסט; הנוסחה עצמה אינה בקובץ",
    "mirror":         "הערך המוצג יובא כטקסט; הלוח שממנו הוא נשאב לא יובא",
    "board_relation": "שמות הפריטים המקושרים יובאו כטקסט; הלוח המקושר לא יובא",
    "item_id":        "מזהה מאנדיי נשמר כטקסט; הפריט מקבל מזהה MISSIONS משלו",
    "button":         "כפתור — יובא כעמודת סטטוס",
    "link":           "קישור יובא כטקסט (תווית + כתובת)",
    "location":       "מיקום יובא כטקסט",
    "phone":          "טלפון יובא כטקסט",
}


# ── the colours monday states ───────────────────────────────────────────────
# A group's header colour and a status label's colour are both how a board is
# read at a glance, and monday states both the same way: `color` as a hex
# string, which is the whole of the usual case, and the names below, which are
# that same palette by the other spelling — what older responses, a status
# column's `labels_colors` (`var_name`) and hand-made files use. A colour that
# is neither is left out rather than guessed at: the importer then gives a
# colour of its own, which is a visible default instead of a wrong claim about
# the source board.
MONDAY_COLORS = {
    "grass_green":    "#037f4c",
    "done_green":     "#00c875",
    "bright_green":   "#9cd326",
    "saladish":       "#cab641",
    "egg_yolk":       "#ffcb00",
    "working_orange": "#fdab3d",
    "dark_orange":    "#ff642e",
    "peach":          "#ffadad",
    "sunset":         "#ff7575",
    "stuck_red":      "#e2445c",
    "dark_red":       "#bb3354",
    "sofia_pink":     "#ff5ac4",
    "lipstick":       "#ff158a",
    "bubble":         "#faa1f1",
    "purple":         "#a25ddc",
    "dark_purple":    "#784bd1",
    "dark_indigo":    "#401694",
    "indigo":         "#5559df",
    "navy":           "#225091",
    "bright_blue":    "#579bfc",
    "dark_blue":      "#0086c0",
    "aquamarine":     "#4eccc6",
    "chili_blue":     "#66ccff",
    "river":          "#68a1bd",
    "winter":         "#9aadbd",
    "explosive":      "#c4c4c4",
    "american_gray":  "#808080",
    "blackish":       "#333333",
    "brown":          "#7f5347",
}


def group_color(raw):
    """A colour monday states — a group's, a status label's — as #rrggbb.

    Takes the hex monday answers, the three-digit shorthand, and the colour's
    name. Anything else — an empty field, a name this table does not hold — is
    None, which the importer reads as "the file did not say".
    """
    c = str(raw or "").strip().lower()
    if not c:
        return None
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3 and all(ch in "0123456789abcdef" for ch in h):
            return "#" + "".join(ch * 2 for ch in h)
        if len(h) == 6 and all(ch in "0123456789abcdef" for ch in h):
            return "#" + h
        return None
    return MONDAY_COLORS.get(re.sub(r"[\s-]+", "_", c))


# ── a status column's own colours ───────────────────────────────────────────
# A status cell does not hold a word, it points at one of the column's options
# — and an option is a word AND a colour. The colour is most of what a status
# column is: "הושלם" is read as green before it is read as a word, and a board
# whose statuses arrive in a palette cycled by position says things it never
# said.
#
# monday keeps that vocabulary in the column's own settings, and writes it two
# ways. The older, and still the usual one, is two maps side by side keyed by
# the label's index:
#
#     {"labels": {"0": "בעבודה", "1": "הושלם"},
#      "labels_colors": {"0": {"color": "#fdab3d", "var_name": "working-orange"},
#                        "1": {"color": "#00c875", "var_name": "done-green"}}}
#
# the newer one a single list, each entry carrying its own colour:
#
#     {"labels": [{"id": 1, "name": "בעבודה", "color": "#fdab3d"}, …]}
#
# Both are read. A label the file gives no colour for is simply absent here,
# which the importer reads as "the file did not say" and answers with a default
# — the same rule a group's colour follows.
def status_colors(settings):
    """{label: #rrggbb} for one status column, from monday's own definition."""
    if not isinstance(settings, dict):
        return {}
    labels = settings.get("labels")
    colors = settings.get("labels_colors")
    out = {}
    if isinstance(labels, dict):
        # the two maps, joined on the index they are both keyed by. The colour
        # is an object — `color` is the chip, `border` the darker edge of the
        # same chip and not a second colour to choose from — and `var_name` is
        # that colour by name, which is the half older responses carry.
        for idx, label in labels.items():
            name = str(label or "").strip()
            if not name:
                continue
            spec = (colors or {}).get(idx) if isinstance(colors, dict) else None
            if isinstance(spec, str):
                hexed = group_color(spec)
            elif isinstance(spec, dict):
                hexed = group_color(spec.get("color")) or group_color(spec.get("var_name"))
            else:
                hexed = None
            if hexed:
                out.setdefault(name, hexed)
    elif isinstance(labels, list):
        for it in labels:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or it.get("label") or "").strip()
            hexed = group_color(it.get("color")) or group_color(it.get("var_name"))
            if name and hexed:
                out.setdefault(name, hexed)
    return out


def cell_label_color(cv):
    """The colour a single status CELL states, when the query asked for it.

    `... on StatusValue { label_style { color } }` answers the colour of the
    option that cell points at. It is the same colour the column's settings
    hold, said per cell — so it stands in for a file whose query asked for the
    items and not for the column definitions, which is most hand-written ones.
    """
    style = (cv or {}).get("label_style")
    if isinstance(style, str):
        try:
            style = json.loads(style)
        except Exception:                           # noqa: BLE001
            return None
    if isinstance(style, dict):
        return group_color(style.get("color"))
    return None


# ── sub-items a file names and does not describe ────────────────────────────
# monday's sub-items column holds no value of its own: it is the sub-items, and
# a query that asked for `subitems` brings them whole — their own columns, their
# own conversation. A query that did not still renders that column, as the
# sub-items' NAMES joined by commas, and monday's own CSV/Excel export of a
# board writes exactly the same thing.
#
# That text is the file saying these sub-items exist. Read as nothing it is a
# board that arrives without them, which is what somebody notices a week later
# when half their work is missing from a migrated board.
#
# A name is not a sub-item the way the real thing is — there are no columns
# behind it and no history — and what is built from one is reported as that. It
# is still the difference between a board that has its sub-items and a board
# that does not.
#
# The names cannot be split better than on the comma: monday joins them with
# ", " and escapes nothing, so a sub-item whose own name holds a comma arrives
# as two. That is the file's limit, not a choice here — a re-export that asks
# for `subitems` carries them properly, and the report says so.
SUBITEM_NAMES_MAX = 100


def _subitem_names(it, sub_col_ids):
    """The sub-item names an item's sub-items column holds, in file order."""
    out = []
    for cv in it.get("column_values") or []:
        if not isinstance(cv, dict):
            continue
        if cv.get("id") not in sub_col_ids and cv.get("type") != SUBITEMS_TYPE:
            continue
        for part in str(cv.get("text") or "").split(","):
            name = part.strip()
            if name:
                out.append(name[:500])
        if len(out) >= SUBITEM_NAMES_MAX:
            break
    return out[:SUBITEM_NAMES_MAX]


# ── the board's activity log ────────────────────────────────────────────────
# monday's `activity_logs` is the board's history: who changed what, when. The
# events worth carrying across are the ones that describe an item this import is
# also bringing; everything else is counted and named in the report rather than
# dropped in silence.
#
# An entry's details live in `data`, which is a JSON *string* — monday does not
# nest it — and `created_at` is microseconds since the epoch, as a string of 17
# digits. Both are the kind of thing that looks like a bug the first time.
LOG_EVENTS = {
    "create_pulse":          ("create", None),
    "pulse_create":          ("create", None),
    "update_name":           ("update", "title"),
    "pulse_name_updated":    ("update", "title"),
    "update_column_value":   ("update", "column"),
    "change_column_value":   ("update", "column"),
    # one entry, many items, and no values: monday records that a column was
    # set across them, which is who-and-when even without the what
    "batch_change_pulses_column_value": ("update", "column"),
    "move_pulse_into_group": ("update", "group"),
}

# How many log entries one import will carry. monday itself pages them, and a
# board of a few hundred items with sixty columns has tens of thousands: past
# some point this stops being history and becomes a table nobody reads.
MAX_LOG_ENTRIES = 20000


def _log_when(raw):
    """monday's log timestamps are microseconds since the epoch, as a string."""
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.isdigit():
        n = int(s)
        from datetime import datetime, timezone
        # monday documents microseconds. Its activity log sends SEVENTEEN
        # digits — tenths of a microsecond, 10,000,000 to the second:
        # 17913700065986844 is 2026-10-07, and read as microseconds it is the
        # year 2537. Unlisted, the whole range check fell through and every
        # imported row was stamped with the moment of the import instead, which
        # is a log that says everything happened at once.
        #
        # Which unit it is settles itself: only one divisor puts the number
        # inside the range a real date can occupy, so the list is tried rather
        # than the digits counted.
        for div in (10_000_000, 1_000_000, 1_000, 1, 1_000_000_000):
            secs = n / div
            if not 1_000_000_000 <= secs < 4_000_000_000:      # 2001 … 2096
                continue
            try:
                return datetime.fromtimestamp(secs, timezone.utc).replace(tzinfo=None).isoformat()
            except (OverflowError, OSError, ValueError):
                return ""
        return ""
    return s


def _log_value(v):
    """One side of a logged change, as the words a person would read.

    monday states a changed cell as the column type's own object — a status as
    {"label":{"text":"Done"}}, a date as {"date":"2025-01-01"} — and the shape
    differs per type. What the log needs is the text, so the known places are
    tried in order and anything else is left as it came.
    """
    if v is None or v == "" or v == {}:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return ", ".join(x for x in (_log_value(i) for i in v) if x)
    if isinstance(v, dict):
        for k in ("text", "name", "title", "date", "value", "label"):
            if k in v:
                got = _log_value(v[k])
                if got:
                    return got
        for k in ("personsAndTeams", "chosenValues", "linkedPulseIds"):
            if v.get(k):
                return _log_value(v[k])
        return ""
    return str(v)


def _activity_of(board, people):
    """The board's log, as rows the importer can write, plus what was left out.

    Each row names the monday item it belongs to; matching that to a task is the
    importer's job, and the only moment it can be done — the mapping exists
    while the import runs and nowhere after it.
    """
    raw = board.get("activity_logs")
    if not isinstance(raw, list):
        return [], {}
    rows, dropped, unmapped = [], 0, {}
    # Rows whose author the file cannot name. monday's own actors have negative
    # ids (-4 is its automations), and "מערכת" is the truth about those. A
    # positive id with no name is a person: on her board 1,311 rows by someone
    # who is neither in the account's user list nor in a people cell, and a log
    # that quietly calls them the system is a log that lost them.
    nameless = {}
    for e in raw:
        if not isinstance(e, dict):
            continue
        ev = (e.get("event") or "").strip()
        known = LOG_EVENTS.get(ev)
        if not known:
            unmapped[ev or "—"] = unmapped.get(ev or "—", 0) + 1
            continue
        action, field = known
        data = e.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {}
        if not isinstance(data, dict):
            data = {}
        # A batch column change names its items in the plural and carries no
        # value at all: what it records is that someone set this column across
        # these items, which is history even without the values.
        ids = data.get("pulse_ids") if isinstance(data.get("pulse_ids"), list) else None
        items_here = [str(i) for i in ids] if ids else None
        if items_here is None:
            one = data.get("pulse_id") or data.get("item_id")
            items_here = [str(one)] if one is not None else []
        if not items_here:
            dropped += 1
            continue
        if len(rows) + len(items_here) > MAX_LOG_ENTRIES:
            dropped += len(items_here)
            continue
        uid = str(e.get("user_id") or "")
        who = people.get(uid) or {}
        if not who and uid and not uid.startswith("-"):
            nameless[uid] = nameless.get(uid, 0) + len(items_here)
        # A move does not state a value; it states the two groups, by name. Read
        # as a value the row came out "changed group: — ← —", which is the
        # shape of a row that knows something happened and nothing else.
        if field == "group":
            old = _log_value((data.get("source_group") or {}).get("title"))
            new = _log_value((data.get("dest_group") or {}).get("title"))
        else:
            old = _log_value(data.get("previous_value"))
            new = _log_value(data.get("value") if "value" in data else data.get("name"))
        for item in items_here:
            rows.append({
                "item": item,
                "action": action,
                "field": field,
                # the column this touched, as monday names it; the importer turns
                # it into the column it became here
                "column": str(data.get("column_id") or "") if field == "column" else "",
                "column_title": (data.get("column_title") or "").strip() if field == "column" else "",
                "old": old,
                "new": new,
                "author": (who.get("name") or "").strip(),
                "email": (who.get("email") or "").strip(),
                "at": _log_when(e.get("created_at")),
                "event": ev,
            })
    rows.sort(key=lambda r: r.get("at") or "")
    return rows, {"dropped": dropped, "unmapped": unmapped, "nameless": nameless}


class NotMondayJson(Exception):
    pass


def _boards_in(doc):
    """Every board object in the document, however many responses it holds."""
    if isinstance(doc, list):
        out = []
        for one in doc:
            out.extend(_boards_in(one))
        return out
    if not isinstance(doc, dict):
        return []
    data = doc.get("data") or {}
    boards = data.get("boards") or doc.get("boards")
    if isinstance(boards, list):
        return [b for b in boards if isinstance(b, dict)]
    # page two onwards is fetched at the root, by cursor, and comes back without
    # the board around it — it is still a page of the same board
    nxt = data.get("next_items_page") or doc.get("next_items_page")
    return [{"items_page": nxt}] if isinstance(nxt, dict) else []


def _users_in(doc):
    """The account's users, by monday id — {"11397425": {"name", "email"}}.

    monday names a person in two places and neither is the one you need: a
    people CELL carries their monday id, and the activity log carries only a
    user id. Both are useless on their own, which is why the query asks for
    `users { id name email }` at the root: it is the only thing that turns an id
    into a person, and the e-mail is the half that survives a rename.
    """
    if isinstance(doc, list):
        out = {}
        for one in doc:
            out.update(_users_in(one))
        return out
    if not isinstance(doc, dict):
        return {}
    users = (doc.get("data") or {}).get("users") or doc.get("users")
    out = {}
    for u in users if isinstance(users, list) else []:
        if isinstance(u, dict) and u.get("id") is not None:
            out[str(u["id"])] = {"name": (u.get("name") or "").strip(),
                                 "email": (u.get("email") or "").strip()}
    return out


def _people_in_cells(items):
    """Names for monday user ids, read off the board's own people cells.

    `users` at the root of the query is the proper answer, and it is not a
    complete one: monday's user list leaves out whoever is no longer an active
    member of the account, and the activity log does not care — it names the
    person who made the change years ago. Her export came back with 200 users and
    a log written by 21 people; fifteen of them were not on the list, and 4,672
    rows would have read "מערכת".

    A people CELL carries both halves: the ids in `value.personsAndTeams` and the
    display names in `text`, in the same order. It only names people who still
    sit in a cell on this board, which is most of the ones the list dropped —
    anyone who was assigned work here and has since left.

    The pairing is positional, so it is taken only when the two sides are the
    same length; a name with a comma in it would otherwise shift every name
    after it onto the wrong person, which is worse than no name at all. No
    e-mail comes from here, and the account's own list wins wherever it has an
    answer.
    """
    out = {}
    def scan(it):
        for cv in (it or {}).get("column_values") or []:
            if cv.get("type") != "people":
                continue
            try:
                v = json.loads(cv.get("value") or "null") or {}
            except ValueError:
                continue
            ids = [str(p.get("id")) for p in (v.get("personsAndTeams") or [])
                   if isinstance(p, dict) and p.get("kind") == "person" and p.get("id") is not None]
            names = [n.strip() for n in (cv.get("text") or "").split(",") if n.strip()]
            if len(ids) != len(names):
                continue
            for uid, name in zip(ids, names):
                if uid not in out and name:
                    out[uid] = {"name": name, "email": ""}
    for it in items or []:
        scan(it)
        for sub in (it or {}).get("subitems") or []:
            scan(sub)
    return out


def _items_of(doc):
    """monday nests the items differently depending on how the query was written.

    A board longer than one page comes back as several responses, each holding
    the cursor that fetched the next. Handed all of them in one file — a JSON
    array of the responses — the pages are read as the one board they are. Two
    *different* boards in a file are not: one import builds one board, and
    quietly taking the first would import half a migration and say nothing.
    "Two boards" means two boards that each brought items; a board named by a
    response that brought none of its own is one of the account's others, and it
    is dropped and reported rather than treated as a second migration.

    The cursor of the last page comes back too. A cursor that is still set means
    the export stopped before the board ended, which is the one thing a
    migration must not discover later.
    """
    boards = _boards_in(doc)
    if not boards:
        raise NotMondayJson("no boards in the response")
    ids = {str(b["id"]) for b in boards if b.get("id")}
    # Which board the file is about is settled by the ITEMS. A request run with
    # the boardId variable unset asks `boards(ids: null)` and comes back with
    # every board in the account — the history query especially, since it is run
    # second and the variable is easy to lose: her merged file held one board's
    # items beside twenty-six boards' logs, and was refused as twenty-seven
    # boards. Those others carry no items and are not a migration; they are the
    # same board's file with a log nobody asked for, so they are dropped and
    # counted. Two boards that each brought ITEMS are a different thing, and
    # still refused — one import builds one board, and quietly taking the first
    # would import half a migration and say nothing.
    with_items = {str(b["id"]) for b in boards
                  if b.get("id") and ("items_page" in b or "items" in b)}
    extra = []
    if len(with_items) == 1:
        keep = next(iter(with_items))
        extra = sorted(ids - {keep})
        # a page fetched by cursor has no board around it: it is this board's
        boards = [b for b in boards if str(b.get("id") or keep) == keep]
    elif len(ids) > 1:
        raise NotMondayJson(
            "the file holds more than one board: " + ", ".join(sorted(ids))
            + " — a request run without the boardId variable answers with every "
              "board in the account; re-run it with the board's id and merge again")

    board, items, cursor, seen = {}, [], None, set()
    # The history is the one thing that arrives in SEVERAL pieces and still has
    # to end up whole. `activity_logs` paginates by `page`, not by cursor, so a
    # long log is several responses in the same file — and taking it from the
    # first response carrying one dropped every page after it. Silently: a log
    # that stops in March reads exactly like a board nobody touched since.
    logs, logs_seen, logs_asked = [], set(), False
    for b in boards:
        # the board's name, groups and column definitions ride on the page that
        # asked for them; the first page carrying each settles it, so a later
        # page without them takes nothing away
        for k in ("id", "name", "groups", "columns"):
            if b.get(k) and not board.get(k):
                board[k] = b[k]
        got_logs = b.get("activity_logs")
        if isinstance(got_logs, list):
            logs_asked = True
            # a page is taken as monday sent it, repeated ids and all — only an
            # entry already read from an EARLIER page is the same page handed
            # over twice
            seen_logs_before = logs_seen
            logs_seen = set(seen_logs_before)
            for e in got_logs:
                eid = (e or {}).get("id") if isinstance(e, dict) else None
                if eid is not None:
                    logs_seen.add(eid)
                    if eid in seen_logs_before:
                        continue
                logs.append(e)
        page = b.get("items_page")
        got = (page or {}).get("items") if isinstance(page, dict) else b.get("items")
        if not isinstance(got, list):
            continue
        cursor = (page or {}).get("cursor") if isinstance(page, dict) else None
        # a page is taken as monday sent it; only an item already read from an
        # *earlier* page is a repeat — the same page handed over twice
        before = seen
        seen = set(before)
        for it in got:
            iid = (it or {}).get("id")
            if iid is not None:
                seen.add(iid)
                if iid in before:
                    continue
            items.append(it)
    if logs_asked:
        # asked for and empty is not the same as never asked, and the report
        # tells them apart by whether the key is here at all
        board["activity_logs"] = logs
    if not items:
        raise NotMondayJson("no items in the response")
    if extra:
        board["_other_boards"] = extra
    return board, items, cursor


def looks_like_monday(raw):
    try:
        _items_of(json.loads(raw))
        return True
    except Exception:
        return False


# ── formulas ────────────────────────────────────────────────────────
# monday keeps a formula column's definition in the column's own settings, as an
# expression over column IDs: {"formula": "{numeric_mkl3sp} + 5"}. This app's
# formula column reads the same shape over column TITLES.
#
# An imported formula column arrives as TEXT, holding the value monday worked
# out. That is the migration's own rule, and it is the conservative one: a live
# formula recomputes from the columns that came across, so any column the export
# left behind, any cell the import retyped, any function monday has and this app
# spells differently, and the board shows a number that is not the number it
# showed in monday — without saying so. The migrated board is meant to be the
# board, and a value is a fact where a formula is a promise about twenty other
# columns.
#
# The expression is still translated and kept on the column, and the column menu
# offers turning it into a live formula column — per column, once someone has
# looked at the numbers. What cannot be computed here is said in the report
# rather than discovered as a blank column.
_FORMULA_REF = re.compile(r"\{([^{}]+)\}")
_FORMULA_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_FORMULA_STRING = re.compile(r"'[^']*'|\"[^\"]*\"")
# The functions this app's own formula engine implements. It is the same list as
# FORMULA_FUNCS in frontend/index.html, and a test compares the two — a name
# here that the engine does not have would import a formula that shows nothing,
# and a name the engine has but this list does not would freeze a formula that
# would have worked.
FORMULA_FUNCS = (
    # numbers
    "ROUND", "ROUNDUP", "ROUNDDOWN", "ABS", "SQRT", "POWER", "SUM", "AVERAGE",
    "MIN", "MAX", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
    # logic
    "IF", "AND", "OR", "NOT", "TRUE", "FALSE",
    # text
    "CONCATENATE", "TEXT", "LEN", "LEFT", "RIGHT", "UPPER", "LOWER", "TRIM", "SEARCH",
    # dates
    "TODAY", "DAYS", "ADD_DAYS", "YEAR", "MONTH", "DAY", "FORMAT_DATE",
)
# what is left once references, strings, functions and numbers are taken out
_FORMULA_REST = re.compile(r"^[0-9+\-*/().,\s<>=!]*$")


def _column_defs(board):
    """The board's own column definitions, when the query asked for them.

    Only this is where a formula lives — the copy of a column that rides inside
    every item carries its title and type and nothing else.
    """
    out = {}
    for c in board.get("columns") or []:
        cid = (c or {}).get("id")
        if not cid:
            continue
        raw = c.get("settings")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:                       # noqa: BLE001
                raw = None
        if not isinstance(raw, dict):
            raw = None
            for key in ("settings_str", "settings"):
                v = c.get(key)
                if isinstance(v, str) and v.strip():
                    try:
                        raw = json.loads(v)
                        break
                    except Exception:               # noqa: BLE001
                        continue
        out[str(cid)] = {"title": (c.get("title") or "").strip(),
                         "type": c.get("type") or "",
                         "settings": raw if isinstance(raw, dict) else {}}
    return out


def translate_formula(expr, titles_by_id):
    """(expression over titles, ids it could not name). Pure text work."""
    missing = []

    def one(m):
        key = m.group(1).strip()
        title = titles_by_id.get(key)
        if not title:
            missing.append(key)
            return m.group(0)
        return "{" + title + "}"

    return _FORMULA_REF.sub(one, expr or "").strip(), missing


def formula_unsupported(expr):
    """The function names in `expr` this app's engine does not implement.

    Everything else in a formula — references, numbers, strings, arithmetic and
    comparisons — the engine handles. So the question is only ever "does it know
    these functions?", and the answer names them rather than being a yes/no: a
    report that says "uses SWITCH" is actionable, "not supported" is not.
    """
    if not (expr or "").strip():
        return ["—"]
    stripped = _FORMULA_STRING.sub("''", _FORMULA_REF.sub("1", expr))
    names = {m.group(0).upper() for m in _FORMULA_NAME.finditer(stripped)}
    unknown = sorted(n for n in names if n not in FORMULA_FUNCS)
    if unknown:
        return unknown
    # nothing unknown by name, but the leftovers still have to be syntax the
    # engine reads — a stray character is a formula that will not run
    rest = _FORMULA_NAME.sub("", stripped).replace("''", "")
    return [] if _FORMULA_REST.match(rest) else ["תחביר לא מוכר"]


def formula_is_computable(expr):
    """Can this app's engine work it out? See formula_unsupported."""
    return not formula_unsupported(expr)


def _has_content(cv):
    """Does this cell carry anything? Counted for the column survey.

    `text` is where most types answer, but not all of them: a formula, a mirror
    and a connect-boards column answer in `display_value` (and in `linked_items`),
    and counting only `text` filed every one of them as "empty in every item".
    """
    if (cv.get("text") or "").strip():
        return True
    dv = str(cv.get("display_value") or "").strip()
    if dv and dv.lower() not in FORMULA_NOTHING:
        return True       # a column of 315 "null"s is not a column with content
    if cv.get("linked_items") or cv.get("linked_item_ids"):
        return True
    if cv.get("files"):
        return True
    return False


def _blob(cv):
    """monday's `value` — the structured original — as a dict, when there is one."""
    raw = cv.get("value")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else None
        except Exception:
            return None
    return None


def _iso(d):
    return d[:10] if isinstance(d, str) and len(d) >= 10 and d[4] == "-" and d[7] == "-" else None


def _cell_value(cv, ctype, assets_by_name, assets_by_id=None, people_by_id=None):
    """The value for one cell, in the form our column type stores.

    `text` is monday's own rendering and is right for most types; `value` is the
    structured original and is the only place some things (a checkbox's state, a
    timeline's two ends, a file's real name) actually appear.
    """
    text = (cv.get("text") or "").strip()
    val = _blob(cv)

    if ctype == "checkbox":
        if isinstance(val, dict):
            return True if val.get("checked") in (True, "true") else None
        return True if text else None

    if ctype == "number":
        try:
            n = float(str(text).replace(",", ""))
        except (TypeError, ValueError):
            return None
        return int(n) if n == int(n) else n

    if ctype == "rating":
        r = (val or {}).get("rating") if isinstance(val, dict) else None
        try:
            r = int(r if r is not None else text)
        except (TypeError, ValueError):
            return None
        return r if 1 <= r <= 5 else None

    if ctype == "date":
        # monday renders these as YYYY-MM-DD already; anything else we skip
        # rather than guess at a day/month order.
        d = (val or {}).get("date") if isinstance(val, dict) else None
        return _iso(d or text)

    if ctype == "timeline":
        frm = _iso((val or {}).get("from")) if isinstance(val, dict) else None
        to = _iso((val or {}).get("to")) if isinstance(val, dict) else None
        if not frm and " - " in text:                       # monday's rendering
            a, _, b = text.partition(" - ")
            frm, to = _iso(a.strip()), _iso(b.strip())
        return {"from": frm, "to": to or frm} if frm else None

    if ctype == "dropdown":
        return [p.strip() for p in text.split(",") if p.strip()] or None

    if ctype == "people":
        # Names as monday shows them, and e-mail addresses when the export
        # carries them. The caller resolves both against real accounts — that is
        # the only place the mapping can be done, and e-mail is the half that
        # survives someone changing their display name.
        names = [p.strip() for p in text.split(",") if p.strip()]
        persons = ((val or {}).get("personsAndTeams") or []) if isinstance(val, dict) else []
        # The cell states a person as monday's own id for them, and only
        # sometimes with an e-mail beside it. The account's user list — asked for
        # at the root of the query — is what turns that id into an address, and
        # an address is what can actually be matched to an account here. Without
        # it the only key is a display name, character for character, which on a
        # real board matched almost nobody: two columns of 306 and 135 items
        # came across as names rather than as the colleagues they name.
        mails = []
        for p in persons:
            e = (p or {}).get("email")
            if not e and (people_by_id or {}):
                e = ((people_by_id or {}).get(str((p or {}).get("id") or "")) or {}).get("email")
            mails.append(e)
        # One person is one token. monday states the people of a cell twice —
        # their display names in `text`, their accounts in `value` — and the two
        # line up in order, so a person who arrives with an e-mail IS that
        # e-mail and not also their name. Emitted as two tokens, a person whose
        # display name had since changed came across as themselves plus a ghost
        # of the old name, now that an unmatched name is kept rather than
        # dropped. Where the two lists do not line up, nothing can be paired and
        # the union is still the honest answer.
        if persons and len(persons) == len(names):
            out = [e or n for e, n in zip(mails, names)]
        else:
            out = list(names)
            for e in mails:
                if e and e not in out:
                    out.append(e)
        return out or None

    if ctype == "files":
        # The bytes live behind monday's auth and the signed links in an export
        # expire within the hour, so what survives is the name — which is the
        # half that tells you which item had a spec attached. An asset id, when
        # the query asked for one, names the file from the asset itself, which
        # is the one place the name is still right after someone renames it.
        out, seen = [], set()

        def add(aid, name):
            a = (assets_by_id or {}).get(str(aid or ""))
            name = (a or {}).get("name") or name
            if not name or name in seen:
                return
            seen.add(name)
            out.append({"name": name,
                        "url": (a or {}).get("url") or assets_by_name.get(name, "")})

        for f in cv.get("files") or []:                  # ... on FileValue
            if isinstance(f, dict):
                add(f.get("asset_id"), None)
        for f in ((val or {}).get("files") or []) if isinstance(val, dict) else []:
            if isinstance(f, dict):
                add(f.get("assetId") or f.get("asset_id"), f.get("name"))
        if not out and text:
            for part in text.split(","):
                add(None, part.strip())
        return out or None

    # ── the three types monday answers somewhere other than `text` ──────
    # formula:        "The computed result is returned in display_value. The text
    #                  and value fields are not populated for formula columns."
    # mirror:         display_value is the mirrored content as text.
    # board_relation: "The text and value fields always return null"; the linked
    #                 items come back in display_value / linked_items.
    # Read only from `text`, all three arrive empty on every item — which is what
    # made six formula columns and two connect columns look like columns nobody
    # had ever filled.
    mtype = (cv.get("type") or "").strip()
    if mtype in DISPLAY_VALUE_TYPES:
        dv = str(cv.get("display_value") or "").strip()
        if dv.lower() in FORMULA_NOTHING:
            dv = ""                       # see FORMULA_NOTHING
        if dv:
            return dv
        names = [str((li or {}).get("name") or "").strip()
                 for li in (cv.get("linked_items") or [])]
        names = [n for n in names if n]
        return ", ".join(names) or None

    # text, and everything that lands in text
    if isinstance(val, dict):
        if val.get("url"):
            label = (val.get("text") or "").strip()
            return f"{label} — {val['url']}" if label else val["url"]
        if val.get("email"):
            return val["email"]
    return text or None


# An item's conversation ("updates" in monday). Capped per item so one very
# chatty item cannot fill an import on its own; what is left out is reported.
MAX_UPDATES_PER_ITEM = 100
MAX_UPDATE_CHARS = 20000


def _plain(body, text_body):
    """An update's text. monday sends the body as HTML and, when the query asks
    for it, the same thing as plain text — which is the one to trust. Falling
    back to the HTML, the tags come out rather than being shown to a reader as
    markup they never wrote."""
    if isinstance(text_body, str) and text_body.strip():
        return text_body.strip()[:MAX_UPDATE_CHARS]
    s = body or ""
    if not isinstance(s, str):
        return ""
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()[:MAX_UPDATE_CHARS]


def _one_update(up):
    """One message: its text, who wrote it, when, and what was attached.

    The author comes back as a name and, when the query asked for it, an e-mail.
    Both travel: the caller matches them against real accounts, and an author
    with no account here is kept by name rather than being turned into whoever
    happened to run the import.
    """
    if not isinstance(up, dict):
        return None
    text = _plain(up.get("body"), up.get("text_body"))
    who = up.get("creator") or {}
    files = []
    for a in up.get("assets") or []:
        if isinstance(a, dict) and a.get("name"):
            files.append({"name": a["name"], "url": a.get("public_url") or ""})
    if not text and not files:
        return None                       # an empty update carries nothing
    return {"external_id": str(up.get("id") or ""), "body": text,
            "created_at": up.get("created_at") or up.get("updated_at") or "",
            "author": (who.get("name") or "").strip(),
            "email": (who.get("email") or "").strip(),
            "assets": files, "replies": []}


def _updates_of(it):
    """The item's conversation, oldest first, with replies kept under the message
    they answer. Returns (messages, dropped)."""
    ups, dropped = [], 0
    raw = it.get("updates")
    if not isinstance(raw, list):
        return [], 0
    for up in raw:
        one = _one_update(up)
        if one is None:
            continue
        if len(ups) >= MAX_UPDATES_PER_ITEM:
            dropped += 1
            continue
        for rep in (up.get("replies") or []):
            r = _one_update(rep)
            if r is not None:
                r.pop("replies", None)
                one["replies"].append(r)
        ups.append(one)
    # monday returns the newest update first; a conversation reads the other way
    ups.sort(key=lambda u: u.get("created_at") or "")
    for u in ups:
        u["replies"].sort(key=lambda r: r.get("created_at") or "")
    return ups, dropped


def parse(raw, max_cols):
    """Read a monday response and return what to build, and what was left out.

    max_cols is the number of custom columns the board may have — the item name
    is not one of them.
    """
    doc = json.loads(raw)
    board, items, cursor = _items_of(doc)
    # the account's user list first, and the board's own people cells behind it
    # for everyone the list no longer carries — see _people_in_cells
    people_by_id = _people_in_cells(items)
    people_by_id.update(_users_in(doc))
    activity, activity_left = _activity_of(board, people_by_id)

    # ── survey the columns: title, type, and how many items actually use them ──
    meta, fill, order = {}, {}, []
    asked = set()          # columns whose cells came with display_value at all
    # cells whose formula monday worked out to nothing — see FORMULA_NOTHING.
    # Counted per column, because a formula column that arrives almost empty is
    # the next thing someone asks about, and the answer is not "the import lost
    # it": monday computed it and there was nothing to compute from.
    nothing = {}
    # The board's own column order, from the board-level definitions when the
    # query asked for them. It beats the order the cells happen to arrive in,
    # and it is the order the source board actually shows.
    board_order = {str(c.get("id")): i for i, c in enumerate(board.get("columns") or [])
                   if isinstance(c, dict) and c.get("id")}

    def survey(it, into=None, note=True):
        m, f, o = into or (meta, fill, order)
        for cv in it.get("column_values") or []:
            cid = cv.get("id")
            if not cid:
                continue
            if cid not in m:
                m[cid] = {"title": ((cv.get("column") or {}).get("title") or "").strip(),
                          "type": cv.get("type") or ""}
                f[cid] = 0
                o.append(cid)
            # Only the items feed these two. A sub-item board has ids of its own
            # and they can repeat the parent's, so counting its cells here would
            # report a formula column of the items by what the sub-items hold.
            if note:
                if "display_value" in cv:
                    asked.add(cid)
                if str(cv.get("display_value") or "").strip().lower() in FORMULA_NOTHING:
                    nothing[cid] = nothing.get(cid, 0) + 1
            if _has_content(cv):
                f[cid] += 1

    for it in items:
        survey(it)
    # The sub-items are a board of their own on monday, with a column set of
    # their own. Surveyed separately, because which of those columns the parent
    # also has is a question that can only be asked once both sets are known.
    smeta, sfill, sorder = {}, {}, []
    for it in items:
        for s_it in it.get("subitems") or []:
            survey(s_it, (smeta, sfill, sorder), note=False)

    skipped, keep, as_subitems, sub_col_ids = [], [], [], set()
    for cid in order:
        m = meta[cid]
        title = m["title"] or cid
        if m["type"] == SUBITEMS_TYPE:
            as_subitems.append(title)
            sub_col_ids.add(cid)
        elif m["type"] in UNSUPPORTED:
            skipped.append({"title": title, "type": m["type"], "reason": UNSUPPORTED[m["type"]]})
        elif m["type"] not in TYPE_MAP:
            skipped.append({"title": title, "type": m["type"], "reason": "סוג עמודה שאינו נתמך"})
        else:
            keep.append(cid)

    # ── a column with nothing in it is not a column of this board ─────────
    # monday's response carries a cell for every column it holds, including the
    # ones nobody sees: a column hidden in the board's view, an archived one, a
    # formula whose result the query never asked for. Created here they are
    # columns she does not have in monday, standing empty in front of the board
    # that was migrated — "עמודה שלא קיימת במקור".
    #
    # So the rule is the file's own evidence: no value on any of the items, no
    # column. Nothing is lost quietly — every one is named in the report, split
    # into the ones that are empty in monday too and the ones whose values the
    # export simply never asked for. And it is self-correcting: re-export with
    # the query that asks, and the columns that DO have values come in.
    blank = [cid for cid in keep if not fill[cid]]
    keep = [cid for cid in keep if fill[cid]]

    # Over the limit, the fullest columns win — a column two items use carries
    # less of the board than one that every item fills. Ties keep the original
    # order so the same file always imports the same way.
    keep.sort(key=lambda c: (-fill[c], order.index(c)))
    over = keep[max_cols:]
    keep = keep[:max_cols]
    # The fill decided WHICH columns survive the ceiling. It has no business
    # deciding their ORDER: a board whose columns come back sorted by how full
    # they happen to be is not the board that was exported. So the survivors go
    # back into the source board's own order — its column list where the file
    # carries one, and the order the cells arrived in otherwise (monday sends a
    # cell per column, in board order).
    keep.sort(key=lambda c: (board_order.get(c, 10 ** 6), order.index(c)))
    for cid in over:
        skipped.append({"title": meta[cid]["title"] or cid, "type": meta[cid]["type"],
                        "reason": f"מעבר לתקרה של {max_cols} עמודות (מלאה ב-{fill[cid]} פריטים)"})

    # named, so that "it is not here" is answerable without counting columns
    empty = [meta[cid]["title"] or cid for cid in blank]
    # An empty formula / mirror / connect column is usually not an empty column:
    # monday answers those in display_value, and a file exported by a query that
    # never asked for it carries nothing for them on any item. That is a file to
    # re-export, not a column to shrug at — and the two are indistinguishable
    # without saying which one this is.
    reexport = [{"title": meta[cid]["title"] or cid, "type": meta[cid]["type"]}
                for cid in blank
                if meta[cid]["type"] in DISPLAY_VALUE_TYPES and cid not in asked]
    empty = [t for t in empty if t not in {r["title"] for r in reexport}]
    columns = [{"key": cid, "title": meta[cid]["title"] or cid,
                "type": TYPE_MAP[meta[cid]["type"]], "monday_type": meta[cid]["type"],
                "fill": fill[cid]} for cid in keep]
    for c in columns:
        if c["monday_type"] in RETYPED:
            c["note"] = RETYPED[c["monday_type"]]
    # ── the formulas, now that every column has a title here ────────────
    defs = _column_defs(board)
    titles_by_id = {c["key"]: c["title"] for c in columns}
    formulas = []
    for c in columns:
        if c["monday_type"] != "formula":
            continue
        raw = (defs.get(c["key"], {}).get("settings") or {}).get("formula")
        if not isinstance(raw, str) or not raw.strip():
            # the query did not ask for the column definitions, so the expression
            # is simply not in the file — the computed values still come across
            continue
        expr, missing = translate_formula(raw, titles_by_id)
        # The column stays text, holding monday's computed value. The expression
        # rides along so the column can be turned into a live one here, and
        # whether that would actually compute is answered now rather than found
        # out by an empty column later.
        c["formula"] = expr
        unsupported = formula_unsupported(expr)
        computable = not (missing or unsupported)
        if computable:
            c["note"] = ("הערך המחושב יובא כטקסט; הנוסחה נשמרה בעמודה וניתן "
                         "להפוך אותה לעמודת נוסחה מחשבת")
        else:
            why = ("היא מפנה לעמודה שלא יובאה" if missing
                   else "היא משתמשת ב" + ", ".join(unsupported))
            c["note"] = (f"הערך המחושב יובא כטקסט; הנוסחה נשמרה בעמודה, אך {why} — "
                         "ולכן היא לא תחושב כאן")
        formulas.append({"title": c["title"], "formula": expr,
                         "missing": sorted(set(missing)),
                         "unsupported": unsupported, "computable": computable})

    # sub-items are their own monday board with their own column ids, so they are
    # matched to the parent's columns by title — that is what shares a column on
    # a board here.
    by_title = {}
    for c in columns:
        by_title.setdefault((c["title"], c["type"]), c["key"])

    # ── the columns only the sub-items have ──────────────────────────────
    # A sub-item column the parent board has no counterpart for used to be
    # dropped where it stood, and that is most of a monday sub-item board: its
    # whole point is a column set of its own. The sub-items then arrived as a
    # list of names with every cell empty — "לא יובאו עם מבנה הטבלה שמוגדר להם".
    #
    # They are board columns here too, marked `sub_only`: shown on the sub-item
    # rows and never on the parent item, which is the structure monday has. The
    # rules are the ones the item columns are held to — a type with nothing to
    # carry is skipped and named, a column no sub-item filled is not a column of
    # this board, and the board's ceiling covers both sets together.
    sub_key, sub_only_titles = {}, []
    sub_found = 0          # sub-item columns the parent board has no counterpart for
    fresh = []
    for cid in sorder:
        m = smeta[cid]
        title = m["title"] or cid
        hit = by_title.get((title, TYPE_MAP.get(m["type"] or "")))
        if hit:
            sub_key[cid] = hit               # the parent has it; one column, shared
            continue
        sub_found += 1
        if m["type"] == SUBITEMS_TYPE:
            continue
        if m["type"] in UNSUPPORTED:
            skipped.append({"title": title, "type": m["type"], "sub_only": True,
                            "reason": UNSUPPORTED[m["type"]] + " (עמודה של תתי-הפריטים)"})
            continue
        if m["type"] not in TYPE_MAP:
            skipped.append({"title": title, "type": m["type"], "sub_only": True,
                            "reason": "סוג עמודה שאינו נתמך (עמודה של תתי-הפריטים)"})
            continue
        if not sfill[cid]:
            continue                          # empty on every sub-item
        fresh.append(cid)
    # the fullest win the room that is left, and the survivors go back into the
    # sub-item board's own order — the same two steps the item columns take
    room = max(max_cols - len(columns), 0)
    fresh.sort(key=lambda c: (-sfill[c], sorder.index(c)))
    for cid in fresh[room:]:
        skipped.append({"title": smeta[cid]["title"] or cid, "type": smeta[cid]["type"],
                        "sub_only": True,
                        "reason": f"מעבר לתקרה של {max_cols} עמודות "
                                  f"(עמודה של תתי-הפריטים, מלאה ב-{sfill[cid]} מהם)"})
    fresh = sorted(fresh[:room], key=lambda c: sorder.index(c))
    for cid in fresh:
        m = smeta[cid]
        # namespaced: a sub-item board numbers its columns on its own, and
        # "status" there is not the "status" of the parent board
        key = "sub:" + cid
        sub_key[cid] = key
        col = {"key": key, "title": m["title"] or cid, "type": TYPE_MAP[m["type"]],
               "monday_type": m["type"], "fill": sfill[cid], "sub_only": True}
        if m["type"] in RETYPED:
            col["note"] = RETYPED[m["type"]]
        columns.append(col)
        sub_only_titles.append(col["title"])

    by_key = {c["key"]: c["type"] for c in columns}
    # column key → {label: #rrggbb}, filled from the cells themselves. The
    # column's settings are where a status vocabulary properly lives, and a
    # query that asked only for the items carries none — so the colour each
    # cell states for its own label is read too, and the two are merged with
    # the definition winning. See cell_label_color.
    cell_colors = {}

    def read(it, lookup_by_title=False):
        # a file's real name and link, when the item happens to carry them
        assets, by_id = {}, {}
        for a in it.get("assets") or []:
            if not isinstance(a, dict):
                continue
            if a.get("name"):
                assets[a["name"]] = a.get("public_url") or ""
            if a.get("id") is not None:
                by_id[str(a["id"])] = {"name": a.get("name") or "",
                                       "url": a.get("public_url") or ""}
        vals = {}
        for cv in it.get("column_values") or []:
            if lookup_by_title:
                # resolved by the sub-item board's own column id, which is what
                # the title match above was for: a shared column's key, or the
                # sub-item-only column this one became
                key = sub_key.get(cv.get("id"))
            else:
                key = cv.get("id") if cv.get("id") in by_key else None
            if not key:
                continue
            v = _cell_value(cv, by_key[key], assets, by_id, people_by_id)
            if v is not None and v != "" and v != []:
                vals[key] = v
                if by_key[key] == "status":
                    paint = cell_label_color(cv)
                    if paint:
                        cell_colors.setdefault(key, {}).setdefault(str(v), paint)
        return vals

    # ── groups, in the order the board puts them ─────────────────────────────
    # Only present when the query asked for them. Without it every item lands in
    # one group, which is a true reading of the file rather than an invention.
    # Their colour comes with them where the file carries it — see group_color.
    groups, seen_g = [], {}
    for g in board.get("groups") or []:
        gid = (g or {}).get("id")
        if gid and gid not in seen_g:
            seen_g[gid] = (g.get("title") or "").strip() or "קבוצה"
            groups.append({"id": gid, "title": seen_g[gid],
                           "color": group_color(g.get("color"))})

    rows, sub_total, talk_dropped, named_subs = [], 0, [0], 0
    for it in items:
        g = it.get("group") or {}
        gid = g.get("id")
        if gid and gid not in seen_g:
            seen_g[gid] = (g.get("title") or "").strip() or "קבוצה"
            groups.append({"id": gid, "title": seen_g[gid],
                           "color": group_color(g.get("color"))})
        subs = []
        for s in it.get("subitems") or []:
            sups, sdrop = _updates_of(s)
            talk_dropped[0] += sdrop
            subs.append({"name": (s.get("name") or "").strip() or "תת-פריט",
                         "values": read(s, lookup_by_title=True), "updates": sups})
        if not subs:
            # The query never asked for `subitems`, and the sub-items column is
            # then the only place the file says they exist — monday renders it
            # as their names, comma-joined. Dropped, as it was, the board came
            # across with the sub-items missing entirely while the report said
            # that column "became the sub-items", which is the one shape of
            # report nobody can catch: it names the loss as the feature.
            #
            # So they are created from their names. A name is all the file
            # holds about them — no columns, no conversation — and the report
            # says so, together with what to re-export to get the rest.
            for name in _subitem_names(it, sub_col_ids):
                subs.append({"name": name, "values": {}, "updates": []})
                named_subs += 1
        sub_total += len(subs)
        ups, dropped = _updates_of(it)
        talk_dropped[0] += dropped
        rows.append({"name": (it.get("name") or "").strip() or "פריט",
                     # monday's own id for the item. The board's history names
                     # items by this and by nothing else, so it has to travel.
                     "id": str(it.get("id") or ""),
                     "group": gid, "values": read(it), "subitems": subs,
                     "updates": ups})

    # An item with no `group` of its own lands in the first group — there is
    # nowhere else to put it. Counted, because the board's own `groups` can be
    # in the file while `group { id title }` on the items is not: a query
    # trimmed by hand, or an older one. The report then said "2 קבוצות,
    # החלוקה נקראה מהקובץ" over a board where all 320 items sat under "פתוח",
    # which reads as the division having been imported. Only this number tells
    # the two apart.
    ungrouped = sum(1 for r in rows if not r["group"])

    # the options a status/dropdown column offers = what the board actually used
    for c in columns:
        if c["type"] not in ("status", "dropdown"):
            continue
        seen = []
        for r in rows:
            for src in [r] + r["subitems"]:
                v = src["values"].get(c["key"])
                for one in (v if isinstance(v, list) else [v]):
                    if one and one not in seen:
                        seen.append(one)
        c["options"] = seen
        if c["type"] == "status":
            # and the colour each of those words is shown in. The column's own
            # definition first — it is the board's vocabulary, and it holds a
            # colour for every option including the ones no item happens to be
            # on — and the cells themselves after it, which is all a file gets
            # when its query never asked for the column definitions.
            paint = dict(cell_colors.get(c["key"]) or {})
            paint.update(status_colors((defs.get(c["key"]) or {}).get("settings")))
            c["option_colors"] = {lbl: paint[lbl] for lbl in seen if lbl in paint}

    # How much of the statuses' colour actually came across, counted the way the
    # groups' is: a board whose every status arrives in this app's palette looks
    # recoloured by somebody here rather than unasked-for in the file.
    status_cols = [c for c in columns if c["type"] == "status"]
    status_options = sum(len(c.get("options") or []) for c in status_cols)
    status_colored = sum(len(c.get("option_colors") or {}) for c in status_cols)

    return {
        "board_name": (board.get("name") or "").strip() or None,
        "groups": groups,
        # the board's own history, when the query asked for it
        "activity": activity,
        "columns": columns,
        "items": rows,
        "report": {
            "items": len(rows),
            "subitems": sub_total,
            # Of those, the ones built from a name in the sub-items column and
            # nothing else — because the query never asked for `subitems`. They
            # are on the board, and they carry no columns and no conversation:
            # a re-export brings the rest. Said apart from the count, so "87
            # תתי-פריטים" is not read as 87 sub-items that came across whole.
            "subitems_named": named_subs,
            # the conversation on the items, and what a per-item ceiling cut
            "updates": sum(len(r["updates"]) + sum(len(u["replies"]) for u in r["updates"])
                           + sum(len(s["updates"]) + sum(len(u["replies"]) for u in s["updates"])
                                 for s in r["subitems"])
                           for r in rows),
            "updates_dropped": talk_dropped[0],
            "groups": len(groups),
            "group_names": [g["title"] for g in groups][:40],
            # A response that asked for neither `groups` on the board nor
            # `group { id title }` on the items says nothing about how the board
            # is divided, and everything lands in one group. That is not a board
            # with one group — it is a question the file was never asked, and the
            # only place it can be said is in the report.
            "groups_need_reexport": not groups,
            "groups_from": "file" if groups else "",
            # How many of them arrived wearing the colour monday gave them. A
            # query that did not ask for `color` answers none, and the board
            # comes across in this app's palette instead — which looks like a
            # choice somebody made rather than a field nobody requested.
            "group_colors": sum(1 for g in groups if g.get("color")),
            # and the same question for the statuses: how many of the words the
            # status columns offer arrived wearing monday's own colour. A query
            # that asked for neither the column definitions nor `label_style`
            # answers none of them, and the whole vocabulary comes across in
            # this app's palette — see status_colors.
            "status_cols": len(status_cols),
            "status_options": status_options,
            "status_colors": status_colored,
            # how many of them, and the group they all ended up in
            "items_ungrouped": ungrouped,
            "ungrouped_into": groups[0]["title"] if (ungrouped and groups) else "",
            "truncated": bool(cursor),
            "columns_found": len(meta) + sub_found,
            "columns_imported": len(columns),
            "columns_empty": empty,
            # the columns that exist on the sub-items and nowhere on the parent
            # board — named, because they are the ones somebody will look for on
            # the item row and not find
            "columns_sub": sub_only_titles,
            # every formula column: the expression that came with it, and
            # whether this app could compute it if asked to
            "formulas": formulas,
            # the board's history: what came, and what was left behind
            "activity": len(activity),
            "activity_from": (activity[0]["at"][:10] if activity else ""),
            "activity_to": (activity[-1]["at"][:10] if activity else ""),
            "activity_dropped": (activity_left or {}).get("dropped", 0),
            "activity_unmapped": sorted(((activity_left or {}).get("unmapped") or {}).items(),
                                        key=lambda kv: -kv[1])[:12],
            # rows by a person the file never names — see `nameless` above
            "activity_nameless": sum(((activity_left or {}).get("nameless") or {}).values()),
            "activity_nameless_who": len((activity_left or {}).get("nameless") or {}),
            "activity_asked": "activity_logs" in (board or {}),
            # monday's own id for the board, so the report can hand back the
            # variable a re-run needs rather than asking her to go and find it
            "board_id": str((board or {}).get("id") or ""),
            # boards the file carried that brought no items of their own — a
            # request run without the boardId variable answers with the whole
            # account. Their logs were left where they were, and saying so is
            # the difference between a file that was read and a file that was
            # guessed at.
            "other_boards": (board or {}).get("_other_boards") or [],
            # the formula cells monday itself answered with nothing
            "formula_nothing": sum(n for cid, n in nothing.items() if cid in by_key),
            "formula_nothing_cols": [{"title": meta[cid]["title"], "cells": n}
                                     for cid, n in sorted(nothing.items(), key=lambda x: -x[1])
                                     if cid in by_key and meta.get(cid)][:12],
            "columns_need_reexport": reexport,
            "as_subitems": as_subitems,
            "mapping": [{"title": c["title"], "from": c["monday_type"],
                         "to": c["type"], "note": c.get("note")} for c in columns],
            "skipped": skipped,
        },
    }
