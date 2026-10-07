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


def _items_of(doc):
    """monday nests the items differently depending on how the query was written.

    A board longer than one page comes back as several responses, each holding
    the cursor that fetched the next. Handed all of them in one file — a JSON
    array of the responses — the pages are read as the one board they are. Two
    *different* boards in a file are not: one import builds one board, and
    quietly taking the first would import half a migration and say nothing.

    The cursor of the last page comes back too. A cursor that is still set means
    the export stopped before the board ended, which is the one thing a
    migration must not discover later.
    """
    boards = _boards_in(doc)
    if not boards:
        raise NotMondayJson("no boards in the response")
    ids = {str(b["id"]) for b in boards if b.get("id")}
    if len(ids) > 1:
        raise NotMondayJson("the file holds more than one board: " + ", ".join(sorted(ids)))

    board, items, cursor, seen = {}, [], None, set()
    for b in boards:
        # the board's name, groups and column definitions ride on the page that
        # asked for them; the first page carrying each settles it, so a later
        # page without them takes nothing away
        for k in ("id", "name", "groups", "columns"):
            if b.get(k) and not board.get(k):
                board[k] = b[k]
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
    if not items:
        raise NotMondayJson("no items in the response")
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


def _cell_value(cv, ctype, assets_by_name, assets_by_id=None):
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
        mails = [(p or {}).get("email") for p in persons]
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

    def survey(it):
        for cv in it.get("column_values") or []:
            cid = cv.get("id")
            if not cid:
                continue
            if cid not in meta:
                meta[cid] = {"title": ((cv.get("column") or {}).get("title") or "").strip(),
                             "type": cv.get("type") or ""}
                fill[cid] = 0
                order.append(cid)
            if "display_value" in cv:
                asked.add(cid)
            if str(cv.get("display_value") or "").strip().lower() in FORMULA_NOTHING:
                nothing[cid] = nothing.get(cid, 0) + 1
            if _has_content(cv):
                fill[cid] += 1

    for it in items:
        survey(it)

    skipped, keep, as_subitems = [], [], []
    for cid in order:
        m = meta[cid]
        title = m["title"] or cid
        if m["type"] == SUBITEMS_TYPE:
            as_subitems.append(title)
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

    by_key = {c["key"]: c["type"] for c in columns}
    # sub-items are their own monday board with their own column ids, so they are
    # matched to the parent's columns by title — that is what shares a column on
    # a board here. A sub-item column with no counterpart is not imported.
    by_title = {}
    for c in columns:
        by_title.setdefault((c["title"], c["type"]), c["key"])

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
                t = ((cv.get("column") or {}).get("title") or "").strip()
                key = by_title.get((t, TYPE_MAP.get(cv.get("type") or "")))
            else:
                key = cv.get("id") if cv.get("id") in by_key else None
            if not key:
                continue
            v = _cell_value(cv, by_key[key], assets, by_id)
            if v is not None and v != "" and v != []:
                vals[key] = v
        return vals

    # ── groups, in the order the board puts them ─────────────────────────────
    # Only present when the query asked for them. Without it every item lands in
    # one group, which is a true reading of the file rather than an invention.
    groups, seen_g = [], {}
    for g in board.get("groups") or []:
        gid = (g or {}).get("id")
        if gid and gid not in seen_g:
            seen_g[gid] = (g.get("title") or "").strip() or "קבוצה"
            groups.append({"id": gid, "title": seen_g[gid]})

    rows, sub_total, talk_dropped = [], 0, [0]
    for it in items:
        g = it.get("group") or {}
        gid = g.get("id")
        if gid and gid not in seen_g:
            seen_g[gid] = (g.get("title") or "").strip() or "קבוצה"
            groups.append({"id": gid, "title": seen_g[gid]})
        subs = []
        for s in it.get("subitems") or []:
            sups, sdrop = _updates_of(s)
            talk_dropped[0] += sdrop
            subs.append({"name": (s.get("name") or "").strip() or "תת-פריט",
                         "values": read(s, lookup_by_title=True), "updates": sups})
        sub_total += len(subs)
        ups, dropped = _updates_of(it)
        talk_dropped[0] += dropped
        rows.append({"name": (it.get("name") or "").strip() or "פריט",
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

    return {
        "board_name": (board.get("name") or "").strip() or None,
        "groups": groups,
        "columns": columns,
        "items": rows,
        "report": {
            "items": len(rows),
            "subitems": sub_total,
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
            # how many of them, and the group they all ended up in
            "items_ungrouped": ungrouped,
            "ungrouped_into": groups[0]["title"] if (ungrouped and groups) else "",
            "truncated": bool(cursor),
            "columns_found": len(meta),
            "columns_imported": len(columns),
            "columns_empty": empty,
            # every formula column: the expression that came with it, and
            # whether this app could compute it if asked to
            "formulas": formulas,
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
