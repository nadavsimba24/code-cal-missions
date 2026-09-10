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
import json

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
    "subtasks":       "תתי־פריטים מיובאים בנפרד, לא כעמודה",
    "team":           "צוות — לא נתמך",
    "time_tracking":  "מעקב זמן — לא נתמך",
    "vote":           "הצבעה — לא נתמך",
}

# Where a monday type lands somewhere other than the obvious place, the report
# says so — an import that quietly retypes a column is an import you cannot
# check.
RETYPED = {
    "formula":        "הערך המחושב יובא כטקסט; הנוסחה עצמה לא הועברה",
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
        # the board's name and groups ride on every page; the first page that
        # carries them settles it, so a later page without them takes nothing
        for k in ("id", "name", "groups"):
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
        out = [p.strip() for p in text.split(",") if p.strip()]
        for p in ((val or {}).get("personsAndTeams") or []) if isinstance(val, dict) else []:
            e = (p or {}).get("email")
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

    # text, and everything that lands in text
    if isinstance(val, dict):
        if val.get("url"):
            label = (val.get("text") or "").strip()
            return f"{label} — {val['url']}" if label else val["url"]
        if val.get("email"):
            return val["email"]
    return text or None


def parse(raw, max_cols):
    """Read a monday response and return what to build, and what was left out.

    max_cols is the number of custom columns the board may have — the item name
    is not one of them.
    """
    doc = json.loads(raw)
    board, items, cursor = _items_of(doc)

    # ── survey the columns: title, type, and how many items actually use them ──
    meta, fill, order = {}, {}, []

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
            if (cv.get("text") or "").strip():
                fill[cid] += 1

    for it in items:
        survey(it)

    skipped, keep = [], []
    for cid in order:
        m = meta[cid]
        title = m["title"] or cid
        if not fill[cid]:
            skipped.append({"title": title, "type": m["type"], "reason": "ריקה בכל הפריטים"})
        elif m["type"] in UNSUPPORTED:
            skipped.append({"title": title, "type": m["type"], "reason": UNSUPPORTED[m["type"]]})
        elif m["type"] not in TYPE_MAP:
            skipped.append({"title": title, "type": m["type"], "reason": "סוג עמודה שאינו נתמך"})
        else:
            keep.append(cid)

    # Over the limit, the fullest columns win — a column two items use carries
    # less of the board than one that every item fills. Ties keep the original
    # order so the same file always imports the same way.
    keep.sort(key=lambda c: (-fill[c], order.index(c)))
    over = keep[max_cols:]
    keep = keep[:max_cols]
    for cid in over:
        skipped.append({"title": meta[cid]["title"] or cid, "type": meta[cid]["type"],
                        "reason": f"מעבר לתקרה של {max_cols} עמודות (מלאה ב-{fill[cid]} פריטים)"})

    columns = [{"key": cid, "title": meta[cid]["title"] or cid,
                "type": TYPE_MAP[meta[cid]["type"]], "monday_type": meta[cid]["type"],
                "fill": fill[cid]} for cid in keep]
    for c in columns:
        if c["monday_type"] in RETYPED:
            c["note"] = RETYPED[c["monday_type"]]
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

    rows, sub_total = [], 0
    for it in items:
        g = it.get("group") or {}
        gid = g.get("id")
        if gid and gid not in seen_g:
            seen_g[gid] = (g.get("title") or "").strip() or "קבוצה"
            groups.append({"id": gid, "title": seen_g[gid]})
        subs = []
        for s in it.get("subitems") or []:
            subs.append({"name": (s.get("name") or "").strip() or "תת-פריט",
                         "values": read(s, lookup_by_title=True)})
        sub_total += len(subs)
        rows.append({"name": (it.get("name") or "").strip() or "פריט",
                     "group": gid, "values": read(it), "subitems": subs})

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
            "groups": len(groups),
            "truncated": bool(cursor),
            "columns_found": len(meta),
            "columns_imported": len(columns),
            "mapping": [{"title": c["title"], "from": c["monday_type"],
                         "to": c["type"], "note": c.get("note")} for c in columns],
            "skipped": skipped,
        },
    }
