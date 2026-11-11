#!/usr/bin/env python3
"""העתקת לוח מסביבה אחת לאחרת — המבנה, הקבוצות והפריטים.

Copy one board out of one deployment's database and into another's: the board
row with its column definitions, its groups, and its items with their cell
values. Nothing else — not the saved views, not the forms, not the automations,
not the conversations, not the attachments, and not the board's membership.

The two databases are separate Postgres servers that happen to run the same
schema, so every id in the copy is a NEW id: the board, the groups and the items
are all re-keyed, and every reference between them is rewritten as it is written
out. References that point at things OUTSIDE the board — a person, a linked item
on another board, an uploaded file — cannot be re-keyed that way, and each is
handled explicitly below rather than carried across to mean something else:

  people / accounts   matched by email address; an unmatched person is dropped
  connect / mirror    the column and its cells are left behind entirely, because
                      a board id from the source database names a DIFFERENT
                      board in the target, and a link that silently repoints is
                      worse than a link that is missing
  files               left behind by THIS pass, and brought over by --attach-to
  formula, item_id,   derived — the target recomputes them, and a copied value
  created_at/by       would be a stale answer that never refreshes again

The conversations and the attachments are a second pass, --attach-to, run
against a board this one has already copied. They are separable because nothing
else refers to them, and separate because they are the expensive half: the
uploads are real bytes, and they live in the database — `uploaded_files.data` is
a LargeBinary, not a path — which is the only reason an attachment can cross
between two deployments at all.

Run it twice: once to see the plan, once to carry it out.

    ./venv/bin/python scripts/copy_board_env.py \
        --source qa --target prod --board 11 \
        --environment "מערכות מידע" --folder "רעות אורן" \
        --owner someone@example.com

    ... --apply        # the same command again, once the plan reads right

Without --apply nothing is written: the script opens the target read-only, so a
dry run cannot write even by mistake.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid

try:
    import psycopg2
    import psycopg2.extras
except ImportError:                                           # pragma: no cover
    sys.exit("psycopg2 is missing — ./venv/bin/pip install psycopg2-binary")

# A JSON column comes back from the source as a decoded dict and goes to the
# target as that same dict. Without this psycopg2 has no idea what to do with
# one and raises "can't adapt type 'dict'" — on whichever JSON column somebody
# adds next, long after this script was last looked at.
#
# Deliberately NOT done for `list`. psycopg2 already adapts a list to a Postgres
# ARRAY, which is what `where token = any(%s)` needs; overriding it to Json made
# every such lookup compare a json literal against a text[] and fail. A JSON
# column whose value is a list is wrapped in Json() explicitly at the point of
# use instead, which is the narrower and more obvious thing anyway.
psycopg2.extensions.register_adapter(dict, psycopg2.extras.Json)


# ── where the two databases are ──────────────────────────────────────────
# The connection string is never typed on a command line or left in a file: it
# is read from the deployment that owns it, which is also the one place it is
# guaranteed to be current. The production app setting is a Key Vault reference
# rather than the URL itself, so that one is resolved a second time.
DEPLOYMENTS = {
    "qa":   {"app": "Missions-Qa-Webapp",  "rg": "rg-missions-qa",
             "subscription": "Misssions"},
    "prod": {"app": "Missions-Prd-Webapp", "rg": "RG-Missions-PRD",
             "subscription": "Misssions"},
}
KEYVAULT_PREFIX = "@Microsoft.KeyVault("


def _az(*args):
    return subprocess.check_output(["az", *args], text=True).strip()


def database_url(which):
    """The DATABASE_URL of a deployment, resolved through Key Vault if need be.

    An environment variable wins, so the script can be pointed at a scratch
    database for a rehearsal without touching the real ones.
    """
    override = os.environ.get(f"COPY_{which.upper()}_DATABASE_URL")
    if override:
        return override
    d = DEPLOYMENTS[which]
    url = _az("webapp", "config", "appsettings", "list",
              "--subscription", d["subscription"], "-n", d["app"], "-g", d["rg"],
              "--query", "[?name=='DATABASE_URL'].value", "-o", "tsv")
    if url.startswith(KEYVAULT_PREFIX):
        # "@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/<name>/)"
        inner = url[len(KEYVAULT_PREFIX):].rstrip(")")
        uri = dict(p.split("=", 1) for p in inner.split(";") if "=" in p)["SecretUri"]
        parts = uri.rstrip("/").split("/")
        vault = parts[2].split(".")[0]
        name = parts[-1] if parts[-2] == "secrets" else parts[-2]
        url = _az("keyvault", "secret", "show", "--vault-name", vault,
                  "--name", name, "--query", "value", "-o", "tsv")
    if not url:
        sys.exit(f"no DATABASE_URL on {d['app']}")
    return url


def connect(url):
    """Open a connection from a DATABASE_URL, taken apart rather than parsed.

    psycopg2 reads a URL as a DSN, and a DSN is percent-decoded: a password
    holding a literal '%' — which one of these does — comes back as
    `invalid percent-encoded token` long before anything reaches the server,
    and the error names the password in the clear while it does it. Splitting
    the URL by hand and handing the pieces over as keywords means no part of it
    is ever decoded, so the password may hold whatever it holds.
    """
    rest = url.split("://", 1)[1]
    creds, hostpart = rest.rsplit("@", 1)
    user, _, password = creds.partition(":")
    hostport, _, tail = hostpart.partition("/")
    host, _, port = hostport.partition(":")
    dbname, _, query = tail.partition("?")
    kw = {"host": host, "user": user, "password": password, "dbname": dbname}
    if port:
        kw["port"] = int(port)
    for pair in query.split("&"):
        key, _, val = pair.partition("=")
        if key in ("sslmode", "sslrootcert", "connect_timeout", "application_name"):
            kw[key] = val
    kw.setdefault("sslmode", "require")
    kw.setdefault("application_name", "copy_board_env")
    return psycopg2.connect(**kw)


# ── reading the schema rather than assuming it ───────────────────────────
# The two databases are deployed from the same code, but not always from the
# same commit: QA is a push ahead of production for as long as a release takes.
# A hard-coded INSERT column list would fail on that gap in the one way that is
# hardest to read — "column X does not exist" halfway through a 589-row write.
# Every write below is built from the columns the two actually share.

def table_columns(cx, table):
    cur = cx.cursor()
    cur.execute("""
        select column_name from information_schema.columns
        where table_schema = 'public' and table_name = %s""", (table,))
    cols = {r[0] for r in cur.fetchall()}
    cur.close()
    return cols


def rows(cx, sql, args=()):
    cur = cx.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, args)
    out = cur.fetchall()
    cur.close()
    return [dict(r) for r in out]


def one(cx, sql, args=()):
    got = rows(cx, sql, args)
    return got[0] if got else None


def scalar(cx, sql, args=()):
    cur = cx.cursor()
    cur.execute(sql, args)
    got = cur.fetchone()
    cur.close()
    return got[0] if got else None


# ── what a cell is allowed to carry across ───────────────────────────────
PEOPLE_TYPES = ("people", "accounts")
# Left behind with the column itself — see the module docstring.
UNPORTABLE_TYPES = ("connect", "mirror")
# Carried as columns, but their cells are recomputed by the target.
DERIVED_TYPES = ("formula", "item_id", "created_at", "created_by")
# Carried as a column; the cell names an upload that lives on the source host.
HOSTED_TYPES = ("files",)

# Not columns at all. A board-defined status or priority is not a TaskStatus or
# a Priority, so it rides in custom_fields as the chosen key, label and colour
# with the enum kept underneath as its base — see _task_status_key in main.py —
# and the "_unset" flags are how "nobody has chosen yet" is told apart from the
# enum's own default. They are keyed like cells and belong to no column, so the
# first version of this script read them as the residue of deleted columns and
# dropped all three hundred of them: every item would have arrived showing the
# base status underneath instead of the one somebody actually picked, and the
# 111 items with nothing chosen would have arrived reading "לביצוע".
RESERVED_CELL_KEYS = frozenset((
    "status_key", "status_label", "status_color", "status_unset",
    "priority_key", "priority_label", "priority_color", "priority_unset",
))


def sanitize_columns(cols, report):
    """The board's column definitions, as the target can hold them."""
    out = []
    for c in cols or []:
        c = dict(c)
        ctype = c.get("type")
        if ctype in UNPORTABLE_TYPES:
            report.setdefault("columns_dropped", []).append(
                f"{c.get('title') or c.get('id')} ({ctype})")
            continue
        # A per-column permission is a map of source user ids to a visibility,
        # and a user id means a different person in the target database. Cleared
        # rather than remapped: the board arrives with its columns open, which is
        # something an admin can see and narrow, where a column silently hidden
        # from the wrong person is something nobody finds.
        if c.get("perms"):
            report.setdefault("column_perms_cleared", []).append(
                c.get("title") or c.get("id"))
            c["perms"] = {}
        c["connect"] = None
        c["mirror_of"] = None
        out.append(c)
    return out


def sanitize_cells(custom_fields, by_id, people_map, report):
    """One item's cells, with every id rewritten or dropped."""
    cf = dict(custom_fields or {})
    out = {}
    for cid, val in cf.items():
        if cid in RESERVED_CELL_KEYS:
            # The item's own status and priority, not a cell. Carried verbatim:
            # the key is a board-defined vocabulary entry and the board's
            # vocabulary travels with it in `settings`.
            out[cid] = val
            report["cells_reserved"] = report.get("cells_reserved", 0) + 1
            continue
        col = by_id.get(cid)
        ctype = (col or {}).get("type")
        if col is None:
            # A value with no column above it: the column was deleted and the
            # cell was left behind. It is invisible on the source board and
            # would be invisible on the copy; it is not carried. Counted PER
            # COLUMN ID and with a sample of what it held, because "382 cells
            # dropped" is only reassuring once you can see that what they hold
            # is the residue of a column somebody removed on purpose.
            report["cells_orphaned"] = report.get("cells_orphaned", 0) + 1
            seen = report.setdefault("orphan_cols", {}).setdefault(cid, {"n": 0, "eg": None})
            seen["n"] += 1
            if seen["eg"] is None and val not in (None, "", [], {}):
                seen["eg"] = str(val)[:60]
            continue
        if ctype in UNPORTABLE_TYPES:
            report["cells_unportable"] = report.get("cells_unportable", 0) + 1
            continue
        if ctype in DERIVED_TYPES:
            report["cells_derived"] = report.get("cells_derived", 0) + 1
            continue
        if ctype in HOSTED_TYPES:
            if val:
                report["cells_files"] = report.get("cells_files", 0) + 1
            continue
        if ctype in PEOPLE_TYPES:
            ids = val if isinstance(val, list) else ([val] if val else [])
            kept, lost = [], []
            for uid in ids:
                try:
                    uid = int(uid)
                except (TypeError, ValueError):
                    continue
                if uid in people_map:
                    kept.append(people_map[uid])
                else:
                    lost.append(uid)
            if lost:
                report["people_unmatched_cells"] = report.get("people_unmatched_cells", 0) + 1
                report.setdefault("people_unmatched_ids", set()).update(lost)
            if kept:
                out[cid] = kept
            continue
        out[cid] = val
    return out


def main():
    ap = argparse.ArgumentParser(
        description="העתקת לוח — מבנה, קבוצות ופריטים — מסביבה אחת לאחרת",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=sorted(DEPLOYMENTS), required=True,
                    help="מאיפה להעתיק")
    ap.add_argument("--target", choices=sorted(DEPLOYMENTS), required=True,
                    help="לאן להעתיק")
    ap.add_argument("--board", type=int, required=True, help="מספר הלוח במקור")
    ap.add_argument("--environment", required=True,
                    help="שם הסביבה ביעד — חייבת להיות קיימת")
    ap.add_argument("--folder", default=None,
                    help="שם התיקייה ביעד; תיווצר אם אינה קיימת")
    ap.add_argument("--name", default=None,
                    help="שם ללוח החדש (ברירת מחדל: שם הלוח במקור)")
    ap.add_argument("--owner", default=None,
                    help="כתובת המייל של מי שיהיה מנהל הלוח ביעד — בלעדיו הלוח "
                         "לא ייראה לאיש, כי גישה כאן היא לפי חברות בלוח")
    ap.add_argument("--compare", type=int, metavar="BOARD_ID", default=None,
                    help="להשוות את לוח המקור ללוח ביעד, טבלה מול טבלה")
    ap.add_argument("--attach-to", type=int, metavar="BOARD_ID", default=None,
                    help="לוח שכבר הועתק — להביא אליו את השיחות והקבצים מהמקור")
    ap.add_argument("--verify", type=int, metavar="BOARD_ID", default=None,
                    help="לא להעתיק — רק לקרוא לוח ביעד ולדווח מה יש בו בפועל")
    ap.add_argument("--allow-duplicate", action="store_true",
                    help="להמשיך גם אם כבר קיים ביעד לוח באותו שם באותו מקום")
    ap.add_argument("--apply", action="store_true",
                    help="לכתוב בפועל (בלעדיו: רק תוכנית, היעד נפתח לקריאה בלבד)")
    args = ap.parse_args()

    if args.verify:
        # Counting what is actually in the target, rather than trusting that a
        # run which printed four lines wrote everything in the other six. A
        # write that stops halfway looks, in the terminal, exactly like a write
        # whose output was pasted halfway.
        dst = connect(database_url(args.target))
        dst.set_session(readonly=True)
        try:
            return verify(dst, args)
        finally:
            dst.close()

    if args.compare:
        src = connect(database_url(args.source))
        src.set_session(readonly=True)
        dst = connect(database_url(args.target))
        dst.set_session(readonly=True)
        try:
            return compare(src, dst, args)
        finally:
            src.close()
            dst.close()

    if args.attach_to:
        src = connect(database_url(args.source))
        src.set_session(readonly=True)
        dst = connect(database_url(args.target))
        if not args.apply:
            dst.set_session(readonly=True)
        try:
            rc = attach_content(src, dst, args)
            if args.apply:
                dst.commit()
            return rc
        except Exception:
            dst.rollback()
            raise
        finally:
            src.close()
            dst.close()

    if args.source == args.target:
        sys.exit("source and target are the same deployment")
    if args.apply and not args.owner:
        sys.exit("--owner is required with --apply: a board nobody is a member "
                 "of is a board nobody can open")

    print(f"source: {args.source}  →  target: {args.target}")
    src = connect(database_url(args.source))
    src.set_session(readonly=True)
    dst = connect(database_url(args.target))
    if not args.apply:
        # A dry run cannot write even if the code below were wrong about what
        # it is doing: the server refuses the statement, not the script.
        dst.set_session(readonly=True)

    report = {}
    try:
        plan = build(src, dst, args, report)
        describe(plan, report, args)
        if not args.apply:
            print("\n— תוכנית בלבד. להרצה בפועל: הוסיפי --apply —")
            return 0
        apply_plan(dst, plan, report, args)
        dst.commit()
        print(f"\n✓ נכתב. הלוח החדש ביעד: id={plan['new_board_id']}")
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()
    return 0


FILE_URL = re.compile(r"^(?:https?://[^/]+)?/api/files/([0-9a-fA-F]{8,64})$")


def pair_items(src, dst, args):
    """Which item in the target is which item in the source.

    The copy knew this while it ran and did not write it down anywhere — the
    ids were a dictionary in memory and the process has long since exited. It
    is recoverable because the copy inserted the items in one deterministic
    order and Postgres handed out ids from a sequence, so the target's items in
    id order ARE the source's items in copy order.

    That is a derivation, though, not a fact, and hanging 400 conversations on
    it unchecked is how a comment ends up on the wrong item — which nobody
    would ever spot, because every item still has comments and they all still
    read plausibly. So it is checked: the two lists must be the same length and
    agree on every title and on the parent/sub-item shape of every row. Any
    disagreement and this refuses to write rather than write something subtly
    wrong.
    """
    s_items = rows(src, """
        select id, title, parent_id from tasks
        where board_id = %s and deleted_at is null
        order by coalesce(parent_id, id), parent_id nulls first, position, id""",
        (args.board,))
    d_items = rows(dst, """
        select id, title, parent_id from tasks
        where board_id = %s and deleted_at is null order by id""", (args.attach_to,))

    print(f"  מקור {len(s_items)} פריטים · יעד {len(d_items)} פריטים")
    d_by_id = {d["id"]: d for d in d_items}

    if len(s_items) == len(d_items):
        tmap, ok = {}, True
        for s, d in zip(s_items, d_items):
            if (s["title"] or "") != (d["title"] or "") \
                    or bool(s["parent_id"]) != bool(d["parent_id"]):
                ok = False
                break
            tmap[s["id"]] = d["id"]
        if ok and all(not s["parent_id"] or
                      tmap.get(s["parent_id"]) == d_by_id[tmap[s["id"]]]["parent_id"]
                      for s in s_items):
            print("  הותאמו לפי סדר ההעתקה, ואומתו לפי כותרת ומבנה")
            return tmap

    # The positional derivation has stopped holding — which happens the moment
    # anybody adds or removes an item on either side, and somebody has. Falling
    # back to matching by title, which survives that, but only where a title
    # picks out exactly ONE item on each side: a repeated title gives no way to
    # tell which of them a conversation belongs to, and guessing would hang real
    # messages on the wrong row.
    print("  ! סדר ההעתקה כבר לא תקף — הלוחות השתנו מאז. מתאים לפי כותרת.")
    s_count, d_count = {}, {}
    for s in s_items:
        s_count[s["title"] or ""] = s_count.get(s["title"] or "", 0) + 1
    for d in d_items:
        d_count[d["title"] or ""] = d_count.get(d["title"] or "", 0) + 1
    d_by_title = {}
    for d in d_items:
        d_by_title.setdefault(d["title"] or "", []).append(d)

    tmap, ambiguous, unmatched = {}, [], []
    for s in s_items:
        title = s["title"] or ""
        if s_count[title] > 1 or d_count.get(title, 0) > 1:
            ambiguous.append(title)
            continue
        if title not in d_by_title:
            unmatched.append(title)
            continue
        tmap[s["id"]] = d_by_title[title][0]["id"]

    extra = [d["title"] for d in d_items if (d["title"] or "") not in s_count]
    print(f"  הותאמו {len(tmap)} פריטים לפי כותרת")
    if unmatched:
        print(f"  {len(unmatched)} פריטים במקור ללא מקביל ביעד — "
              "שיחות עליהם לא יעברו: " + ", ".join(repr(t) for t in unmatched[:5])
              + (" …" if len(unmatched) > 5 else ""))
    if extra:
        print(f"  {len(extra)} פריטים חדשים ביעד שלא קיימים במקור — לא נוגע בהם: "
              + ", ".join(repr(t) for t in extra[:5]) + (" …" if len(extra) > 5 else ""))
    if ambiguous:
        uniq = sorted(set(ambiguous))
        print(f"  ! {len(ambiguous)} פריטים עם כותרת שחוזרת יותר מפעם אחת — "
              "אי אפשר לדעת לאיזה מהם השיחה שייכת, ולכן הם מדולגים: "
              + ", ".join(repr(t) for t in uniq[:5]) + (" …" if len(uniq) > 5 else ""))
    if not tmap:
        sys.exit("אין ולו פריט אחד שניתן להתאים בוודאות. לא כותב כלום.")
    return tmap


def copy_files(src, dst, tokens, apply, report):
    """The uploads themselves, bytes and all.

    These live in the database — `uploaded_files.data` is a LargeBinary — and
    not on the web app's disk, which is why an attachment can cross between two
    deployments at all. A token is unique, so one that happens to exist in the
    target already is re-minted and the reference rewritten to match.
    """
    if not tokens:
        return {}
    got = rows(src, """
        select token, name, content_type, data, size, created_at
        from uploaded_files where token = any(%s)""", (list(tokens),))
    report["files_missing"] = sorted(tokens - {f["token"] for f in got})
    taken = {r["token"] for r in rows(
        dst, "select token from uploaded_files where token = any(%s)", (list(tokens),))}
    remap, nbytes = {}, 0
    for f in got:
        token = f["token"]
        if token in taken:
            token = uuid.uuid4().hex
            remap[f["token"]] = token
        nbytes += f["size"] or 0
        if apply:
            cur = dst.cursor()
            cur.execute("""
                insert into uploaded_files (token, name, content_type, data, size, created_at)
                values (%s, %s, %s, %s, %s, %s)""",
                (token, f["name"], f["content_type"],
                 psycopg2.Binary(f["data"]) if f["data"] is not None else None,
                 f["size"], f["created_at"]))
            cur.close()
    report["files_copied"] = len(got)
    report["files_bytes"] = nbytes
    report["files_retokened"] = len(remap)
    return remap


def _rewrite_urls(attachments, remap):
    """An attachment list with any re-minted token swapped in."""
    out = []
    for a in attachments or []:
        if isinstance(a, dict) and a.get("url"):
            m = FILE_URL.match(a["url"].strip())
            if m and m.group(1) in remap:
                a = dict(a, url=f"/api/files/{remap[m.group(1)]}")
        out.append(a)
    return out


def _tokens_in(attachments):
    found = set()
    for a in attachments or []:
        if isinstance(a, dict) and a.get("url"):
            m = FILE_URL.match(a["url"].strip())
            if m:
                found.add(m.group(1))
    return found


def attach_content(src, dst, args):
    """Bring the conversations and the attachments onto a board already copied."""
    board = one(src, "select * from boards where id = %s", (args.board,))
    if not board:
        sys.exit(f"board {args.board} does not exist in {args.source}")
    target = one(dst, "select id, name from boards where id = %s", (args.attach_to,))
    if not target:
        sys.exit(f"board {args.attach_to} does not exist in {args.target}")
    print(f"source: {args.source} לוח {args.board} → {args.target} לוח {args.attach_to} "
          f"({target['name']!r})")

    # Only messages THIS pass put there. Counting every comment on the board
    # would refuse to run because colleagues had started talking on it, which
    # is the normal state of a board somebody is already working in — and the
    # thing actually worth refusing is running the copy twice.
    have = scalar(dst, """
        select count(*) from comments c join tasks t on t.id = c.task_id
        where t.board_id = %s and c.origin ->> 'source' = %s""",
        (args.attach_to, f"{args.source} board {args.board}"))
    if have and not args.allow_duplicate:
        sys.exit(f"ביעד כבר יש {have} הודעות שהועתקו מ{args.source} לוח {args.board} — "
                 "הרצה נוספת תכפיל אותן.\nאם זו בכל זאת הכוונה: --allow-duplicate")

    tmap = pair_items(src, dst, args)
    report = {}

    # ── who wrote what ───────────────────────────────────────────────────
    src_people = rows(src, "select id, name, email from users where email is not null and email <> ''")
    dst_people = rows(dst, "select id, lower(email) as email from users where email is not null and email <> ''")
    by_email = {p["email"]: p["id"] for p in dst_people}
    people_map = {p["id"]: by_email[(p["email"] or "").lower()]
                  for p in src_people if (p["email"] or "").lower() in by_email}
    src_names = {p["id"]: (p["name"] or p["email"]) for p in src_people}

    comments = rows(src, """
        select * from comments where task_id = any(%s) order by id""",
        (list(tmap),))

    # What the pairing could not place. Said as a number of MESSAGES rather
    # than of items, because "4 items skipped" sounds like nothing and "4 items
    # skipped, carrying 31 messages" is a gap somebody has to decide about.
    skipped = [t["id"] for t in rows(src, """
        select id from tasks where board_id = %s and deleted_at is null""",
        (args.board,)) if t["id"] not in tmap]
    if skipped:
        n = scalar(src, "select count(*) from comments where task_id = any(%s)",
                   (skipped,)) or 0
        print(f"  ({len(skipped)} פריטים שלא הותאמו מחזיקים {n} הודעות שלא יעברו)")

    # ── the files: cells first, then the ones hanging off messages ───────
    settings = dict(board.get("settings") or {})
    file_cols = [c.get("id") for c in (settings.get("columns") or [])
                 if c.get("type") in HOSTED_TYPES]
    cells = rows(src, """
        select id, custom_fields from tasks
        where board_id = %s and deleted_at is null""", (args.board,)) if file_cols else []
    tokens = set()
    cell_writes = []
    for t in cells:
        cf = t.get("custom_fields") or {}
        mine = {cid: cf[cid] for cid in file_cols if cf.get(cid)}
        if mine:
            cell_writes.append((t["id"], mine))
            for val in mine.values():
                tokens |= _tokens_in(val if isinstance(val, list) else [val])
    for c in comments:
        tokens |= _tokens_in(c.get("attachments"))

    print("\n── מה ייכתב ─────────────────────────────────────────────")
    print(f"  הודעות          {len(comments)}"
          f"  (מתוכן {sum(1 for c in comments if c.get('parent_id'))} תגובות בשרשור)")
    print(f"  פריטים עם תאי קבצים  {len(cell_writes)}")
    print(f"  קבצים מצורפים   {len(tokens)}")

    remap = copy_files(src, dst, tokens, args.apply, report)
    if report.get("files_copied") is not None:
        print(f"  מתוכם נמצאו במקור {report['files_copied']}"
              f"  ({report['files_bytes'] / 1048576:.1f}MB)")
    if report.get("files_missing"):
        print(f"  ! {len(report['files_missing'])} טוקנים ללא קובץ במקור — "
              "ההפניה אליהם תרד")
    if report.get("files_retokened"):
        print(f"  {report['files_retokened']} טוקנים חודשו (התנגשו עם קיימים ביעד)")

    if not args.apply:
        _authors_note(comments, people_map, src_names)
        print("\n— תוכנית בלבד. להרצה בפועל: הוסיפי --apply —")
        return 0

    # ── the file cells ───────────────────────────────────────────────────
    # Tokens the source could not produce a file for. A reference to one of
    # them would render as a broken attachment on the target, so the
    # reference goes too rather than the name hanging there unopenable.
    missing = set(report.get("files_missing") or [])
    for sid, mine in cell_writes:
        clean = {}
        for cid, val in mine.items():
            lst = val if isinstance(val, list) else [val]
            kept = [a for a in _rewrite_urls(lst, remap)
                    if not (_tokens_in([a]) & missing)]
            if kept:
                clean[cid] = kept
        if not clean:
            continue
        cur = dst.cursor()
        cur.execute("""
            update tasks set custom_fields = (coalesce(custom_fields::jsonb, '{}'::jsonb)
                                              || %s::jsonb)::json
            where id = %s""",
            (json.dumps(clean, ensure_ascii=False), tmap[sid]))
        cur.close()
    print(f"\n  תאי קבצים עודכנו: {len(cell_writes)}")

    # ── the conversations ────────────────────────────────────────────────
    shared = table_columns(dst, "comments")
    cmap, orphaned = {}, 0
    for c in comments:
        row = {k: v for k, v in c.items() if k in shared}
        row.pop("id", None)
        row["task_id"] = tmap[c["task_id"]]
        parent = c.get("parent_id")
        if parent and parent not in cmap:
            # A reply whose parent is not on this board — it cannot be threaded
            # under anything here, so it is written as a message of its own
            # rather than silently dropped or re-parented onto a stranger.
            orphaned += 1
            parent = None
        row["parent_id"] = cmap.get(parent) if parent else None
        row["attachments"] = psycopg2.extras.Json(
            [a for a in _rewrite_urls(c.get("attachments"), remap)
             if not (_tokens_in([a]) & missing)])
        row["mentions"] = psycopg2.extras.Json(
            [people_map[u] for u in (c.get("mentions") or []) if u in people_map])
        row["likes"] = psycopg2.extras.Json(
            [people_map[u] for u in (c.get("likes") or []) if u in people_map])
        row["seen_by"] = psycopg2.extras.Json([])
        author = c.get("user_id")
        # `origin` is stamped on EVERY copied message, not only the ones that
        # arrive unattributed. It is what makes a copied message tellable from
        # one somebody wrote here — which is what the re-run guard counts, and
        # the only way this pass could ever be undone without taking the
        # board's real conversations with it. The UI ignores it whenever the
        # message has an author (see index.html, `c.origin && !c.user_id`), so
        # recording it costs nothing in what anybody sees.
        row["origin"] = psycopg2.extras.Json({
            "source": f"{args.source} board {args.board}",
            "author": src_names.get(author, ""),
            "external_id": str(c["id"])})
        if author in people_map:
            row["user_id"] = people_map[author]
        else:
            # A message whose author has no account here is left unattributed
            # and named off `origin` instead, rather than being put in the
            # mouth of whoever ran the copy.
            row["user_id"] = None
        cmap[c["id"]] = _insert(dst, "comments", row, shared)
    print(f"  הודעות נכתבו: {len(cmap)}")
    if orphaned:
        print(f"  {orphaned} תגובות שההודעה שהן עונות לה אינה על הלוח — נכתבו כהודעות עצמאיות")
    _authors_note(comments, people_map, src_names)
    return 0


def _authors_note(comments, people_map, src_names):
    lost = sorted({src_names.get(c["user_id"], str(c["user_id"])) for c in comments
                   if c.get("user_id") and c["user_id"] not in people_map})
    if lost:
        print("  כותבים ללא חשבון ביעד — ההודעה נרשמת על שמם בלי לשייך משתמש: "
              + ", ".join(lost))


# Everything that belongs to a board, and how to count it. The point of the
# list is that it is EXHAUSTIVE: a comparison that only counts what the copy
# knows how to carry would report a clean bill of health while leaving the
# saved views and the forms behind, which is exactly the question "did the
# whole board come across" is asking about.
BOARD_SCOPED = [
    ("קבוצות", "select count(*) from groups where board_id = %(b)s"),
    ("פריטים (חיים)", "select count(*) from tasks where board_id = %(b)s and deleted_at is null"),
    ("פריטים בסל המיחזור", "select count(*) from tasks where board_id = %(b)s and deleted_at is not null"),
    ("שיוכי אחראים", "select count(*) from task_assignees ta join tasks t on t.id = ta.task_id"
                     " where t.board_id = %(b)s"),
    ("הודעות בשיחות", "select count(*) from comments c join tasks t on t.id = c.task_id"
                      " where t.board_id = %(b)s"),
    # Split out, because a conversation hanging off an item somebody deleted is
    # not a conversation the copy lost — it is one that went to the recycle bin
    # with its item, and the items in the bin were never in scope.
    ("  מהן על פריטים חיים", "select count(*) from comments c join tasks t on t.id = c.task_id"
                            " where t.board_id = %(b)s and t.deleted_at is null"),
    ("  מהן על פריטים מחוקים", "select count(*) from comments c join tasks t on t.id = c.task_id"
                              " where t.board_id = %(b)s and t.deleted_at is not null"),
    ("חברי לוח", "select count(*) from board_members where board_id = %(b)s"),
    ("תצוגות שמורות", "select count(*) from saved_views where board_id = %(b)s"),
    ("תצוגות לוח", "select count(*) from board_views where board_id = %(b)s"),
    ("טפסים", "select count(*) from form_views where board_id = %(b)s"),
    ("רכיבי טפסים", "select count(*) from form_components where board_id = %(b)s"),
    ("אוטומציות", "select count(*) from automations where board_id = %(b)s"),
    ("דשבורדים", "select count(*) from dashboards where board_id = %(b)s"),
    ("התראות", "select count(*) from notifications where board_id = %(b)s"),
]


def compare(src, dst, args):
    """Source board against target board, line by line, so "did it all come
    across" is answered by the two databases rather than by anybody's memory."""
    s = one(src, "select name from boards where id = %s", (args.board,))
    d = one(dst, "select name from boards where id = %s", (args.compare,))
    if not s or not d:
        sys.exit("אחד הלוחות לא קיים")
    print(f"  {args.source} לוח {args.board} {s['name']!r}")
    print(f"  {args.target} לוח {args.compare} {d['name']!r}\n")
    print(f"  {'':28s}{args.source:>8s}{args.target:>8s}")
    for label, sql in BOARD_SCOPED:
        try:
            a = scalar(src, sql, {"b": args.board}) or 0
            b = scalar(dst, sql, {"b": args.compare}) or 0
        except Exception as exc:
            src.rollback(); dst.rollback()
            print(f"  {label:28s}  — {str(exc).splitlines()[0][:40]}")
            continue
        mark = "" if a == b else ("  ✓ ביעד יותר" if b > a else "  ← לא עבר")
        print(f"  {label:28s}{a:>8d}{b:>8d}{mark}")

    scol = (one(src, "select settings from boards where id = %s", (args.board,))
            or {}).get("settings") or {}
    dcol = (one(dst, "select settings from boards where id = %s", (args.compare,))
            or {}).get("settings") or {}
    print(f"  {'עמודות':28s}{len(scol.get('columns') or []):>8d}"
          f"{len(dcol.get('columns') or []):>8d}")
    return 0


def verify(dst, args):
    """What the target actually holds for one board, counted there."""
    bid = args.verify
    b = one(dst, """
        select b.id, b.name, b.icon, b.board_type, b.deleted_at,
               e.name as env, f.name as folder,
               jsonb_array_length(coalesce(b.settings::jsonb -> 'columns', '[]'::jsonb)) as ncols
        from boards b
        left join environments e on e.id = b.environment_id
        left join folders f on f.id = b.folder_id
        where b.id = %s""", (bid,))
    if not b:
        sys.exit(f"no board {bid} in {args.target}")
    print(f"── לוח {bid} ב־{args.target} ─────────────────────────────")
    print(f"  שם            {b['name']!r}  ({b['board_type']}, {b['icon']})")
    print(f"  סביבה/תיקייה  {b['env']!r} / {b['folder']!r}")
    print(f"  עמודות        {b['ncols']}")
    if b["deleted_at"]:
        print("  ! הלוח בסל המיחזור")

    counts = one(dst, """
        select (select count(*) from groups where board_id = %(b)s) as groups,
               (select count(*) from tasks where board_id = %(b)s and deleted_at is null) as items,
               (select count(*) from tasks where board_id = %(b)s and parent_id is not null
                  and deleted_at is null) as subitems,
               (select count(*) from task_assignees ta join tasks t on t.id = ta.task_id
                  where t.board_id = %(b)s) as assignees,
               (select count(*) from board_members where board_id = %(b)s) as members,
               (select count(*) from tasks where board_id = %(b)s
                  and custom_fields::jsonb ? 'status_key') as with_status,
               (select count(*) from tasks where board_id = %(b)s
                  and coalesce(custom_fields::text, '{}') <> '{}') as with_cells
        """, {"b": bid})
    for key, label in (("groups", "קבוצות"), ("items", "פריטים"),
                       ("subitems", "  מתוכם תת־פריטים"), ("assignees", "שיוכי אחראים"),
                       ("members", "חברי לוח"), ("with_cells", "פריטים עם תוכן בתאים"),
                       ("with_status", "פריטים עם סטטוס מוגדר־לוח")):
        print(f"  {label:22s} {counts[key]}")

    for m in rows(dst, """
            select u.name, u.email, bm.role from board_members bm
            join users u on u.id = bm.user_id where bm.board_id = %s""", (bid,)):
        print(f"    · {m['name']} <{m['email']}> — {m['role']}")

    # The conversations and the attachments, so "did that pass run, and did it
    # finish" is a question the target answers rather than one anybody recalls.
    talk = rows(dst, """
        select c.id, c.created_at, c.origin, c.parent_id,
               coalesce(u.name, '') as author, t.title as item,
               coalesce(jsonb_array_length(c.attachments::jsonb), 0) as nfiles
        from comments c join tasks t on t.id = c.task_id
        left join users u on u.id = c.user_id
        where t.board_id = %s order by c.id""", (bid,))
    print(f"\n  הודעות                 {len(talk)}")
    print(f"    מתוכן מהעתקה         {sum(1 for c in talk if c['origin'])}")
    print(f"    עם קבצים מצורפים     {sum(1 for c in talk if c['nfiles'])}")
    cells = scalar(dst, """
        select count(*) from tasks
        where board_id = %s and custom_fields::text ~ '/api/files/'""", (bid,))
    print(f"  פריטים עם תאי קבצים    {cells}")
    # The question a count of attachments cannot answer: does each one actually
    # open. A reference is just a token in a URL, and a token with no row behind
    # it renders as an attachment that 404s when somebody clicks it.
    refs = set()
    for src_json in (
            [c["attachments"] for c in rows(dst, """
                select c.attachments from comments c join tasks t on t.id = c.task_id
                where t.board_id = %s""", (bid,))]
            + [t["custom_fields"] for t in rows(dst, """
                select custom_fields from tasks where board_id = %s""", (bid,))]):
        refs |= set(re.findall(r"/api/files/([0-9a-fA-F]{8,64})",
                               json.dumps(src_json, ensure_ascii=False)))
    if refs:
        live = {r["token"] for r in rows(
            dst, "select token from uploaded_files where token = any(%s)", (list(refs),))}
        dead = refs - live
        print(f"  קבצים שמופנים אליהם    {len(refs)}")
        print(f"    נפתחים בפועל         {len(live)}"
              + (f"   ! {len(dead)} שבורים" if dead else ""))

    for c in talk[:12]:
        who = c["author"] or ((c["origin"] or {}).get("author") or "—")
        when = c["created_at"].strftime("%Y-%m-%d %H:%M") if c["created_at"] else ""
        mark = "העתקה" if c["origin"] else "נכתב כאן"
        print(f"    · [{mark}] {when}  {who}  על {c['item']!r}"
              + (f"  ({c['nfiles']} קבצים)" if c["nfiles"] else ""))
    if len(talk) > 12:
        print(f"    … ועוד {len(talk) - 12}")
    return 0


def build(src, dst, args, report):
    """Everything the write needs, worked out before a single row is written."""
    board = one(src, "select * from boards where id = %s", (args.board,))
    if not board:
        sys.exit(f"board {args.board} does not exist in {args.source}")
    if board.get("deleted_at"):
        sys.exit(f"board {args.board} is in the recycle bin in {args.source}")
    print(f"  board: {board['name']!r}")

    # ── where it lands ───────────────────────────────────────────────────
    env = one(dst, "select id, name from environments where name = %s", (args.environment,))
    if not env:
        have = rows(dst, "select name from environments order by name")
        sys.exit(f"no environment named {args.environment!r} in {args.target}.\n"
                 "what is there: " + ", ".join(repr(e["name"]) for e in have))
    folder = None
    if args.folder:
        folder = one(dst, "select id, name from folders where environment_id = %s and name = %s",
                     (env["id"], args.folder))

    # Running the same command twice is the likeliest way this goes wrong, and
    # the second run looks exactly like the first until somebody opens the
    # workspace and finds the board there in duplicate, 471 items each.
    wanted_name = args.name or board["name"]
    dupe = one(dst, """
        select id from boards
        where name = %s and environment_id = %s and deleted_at is null
          and folder_id is not distinct from %s""",
        (wanted_name, env["id"], folder["id"] if folder else None))
    if dupe and not args.allow_duplicate:
        sys.exit(f"{args.target} already holds a board named {wanted_name!r} in "
                 f"{args.environment!r}" + (f"/{args.folder!r}" if args.folder else "")
                 + f" (id={dupe['id']}).\n"
                 "if the copy is meant to sit beside it, pass --allow-duplicate.")

    owner = None
    if args.owner:
        owner = one(dst, "select id, name, email from users where lower(email) = lower(%s)",
                    (args.owner,))
        if not owner:
            sys.exit(f"no user {args.owner!r} in {args.target} — "
                     "the board would be created with no member who can open it")

    # ── who is who across the two databases ──────────────────────────────
    # An email address is the only thing that means the same person in both: the
    # user ids are each database's own, and the same number is two colleagues.
    src_people = rows(src, "select id, name, email from users where email is not null and email <> ''")
    dst_people = rows(dst, "select id, lower(email) as email from users where email is not null and email <> ''")
    by_email = {p["email"]: p["id"] for p in dst_people}
    people_map = {p["id"]: by_email[(p["email"] or "").lower()]
                  for p in src_people if (p["email"] or "").lower() in by_email}
    report["people_total"] = len(src_people)
    report["people_matched"] = len(people_map)
    src_names = {p["id"]: (p["name"] or p["email"]) for p in src_people}

    # ── the board's own shape ────────────────────────────────────────────
    settings = dict(board.get("settings") or {})
    settings["columns"] = sanitize_columns(settings.get("columns"), report)
    by_id = {c.get("id"): c for c in settings["columns"]}

    groups = rows(src, "select * from groups where board_id = %s order by position, id", (args.board,))
    items = rows(src, """
        select * from tasks
        where board_id = %s and deleted_at is null
        order by coalesce(parent_id, id), parent_id nulls first, position, id""",
        (args.board,))
    report["items_deleted_skipped"] = scalar(
        src, "select count(*) from tasks where board_id = %s and deleted_at is not null",
        (args.board,)) or 0

    assignees = rows(src, """
        select ta.task_id, ta.user_id from task_assignees ta
        join tasks t on t.id = ta.task_id
        where t.board_id = %s and t.deleted_at is null""", (args.board,))

    for it in items:
        it["_cells"] = sanitize_cells(it.get("custom_fields"), by_id, people_map, report)
        if it.get("permissions"):
            report["item_perms_cleared"] = report.get("item_perms_cleared", 0) + 1

    report["people_unmatched_names"] = sorted(
        src_names.get(u, str(u)) for u in report.get("people_unmatched_ids", set()))
    # Said before the write rather than after it: an "אחראי" that quietly fails
    # to come across is the one loss on this board nobody would notice by
    # looking, because the item is there and only the name beside it is gone.
    report["assignees_kept"] = sum(1 for a in assignees if a["user_id"] in people_map)
    report["assignees_lost_people"] = sorted(
        {src_names.get(a["user_id"], str(a["user_id"])) for a in assignees
         if a["user_id"] not in people_map})

    return {"board": board, "settings": settings, "groups": groups, "items": items,
            "assignees": assignees, "env": env, "folder": folder, "owner": owner,
            "people_map": people_map, "new_board_id": None}


def describe(plan, report, args):
    b, settings = plan["board"], plan["settings"]
    print("\n── מה ייכתב ─────────────────────────────────────────────")
    print(f"  לוח            {args.name or b['name']!r}  ({b['board_type']}, {b['icon']})")
    print(f"  סביבה          {plan['env']['name']!r} (id={plan['env']['id']})")
    if args.folder:
        print(f"  תיקייה         {args.folder!r} " +
              (f"(קיימת, id={plan['folder']['id']})" if plan["folder"] else "(תיווצר)"))
    print(f"  עמודות         {len(settings['columns'])}")
    print(f"  קבוצות         {len(plan['groups'])}")
    print(f"  פריטים         {len(plan['items'])}"
          f"  (מתוכם {sum(1 for i in plan['items'] if i.get('parent_id'))} תת־פריטים)")
    print(f"  שיוכי אחראים   {report['assignees_kept']}/{len(plan['assignees'])}")
    if plan["owner"]:
        print(f"  מנהל הלוח      {plan['owner']['name']} <{plan['owner']['email']}>")

    print("\n── מה לא עובר ───────────────────────────────────────────")
    print(f"  אנשים מזוהים לפי מייל: {report['people_matched']}/{report['people_total']}")
    if report.get("people_unmatched_names"):
        print("  אין להם חשבון ביעד, והשיוך אליהם יירד: "
              + ", ".join(report["people_unmatched_names"][:20])
              + (" …" if len(report["people_unmatched_names"]) > 20 else ""))
    for key, label in (
            ("columns_dropped", "עמודות שנשארות מאחור (קשר/מראה)"),
            ("column_perms_cleared", "עמודות שהרשאותיהן נוקו"),
    ):
        if report.get(key):
            print(f"  {label}: " + ", ".join(report[key]))
    for key, label in (
            ("cells_unportable", "תאי קשר/מראה שלא נכתבים"),
            ("cells_derived", "תאים מחושבים שהיעד יחשב מחדש"),
            ("cells_files", "תאי קבצים שלא נכתבים"),
            ("cells_orphaned", "תאים ללא עמודה"),
            ("item_perms_cleared", "פריטים שהרשאותיהם הפרטניות נוקו"),
            ("items_deleted_skipped", "פריטים בסל המיחזור שלא מועתקים"),
    ):
        if report.get(key):
            print(f"  {label}: {report[key]}")
    if report.get("assignees_lost_people"):
        print("  אחראים שיירדו (אין להם חשבון ביעד): "
              + ", ".join(report["assignees_lost_people"]))
    if report.get("orphan_cols"):
        print("\n  התאים ללא עמודה, לפי מזהה העמודה שנמחקה:")
        for cid, d in sorted(report["orphan_cols"].items(), key=lambda kv: -kv[1]["n"]):
            print(f"    {cid:24s} {d['n']:4d} תאים   דוגמה: "
                  + (d["eg"] if d["eg"] else "(ריקים)"))
    print("  לא מועתקים בכלל: תצוגות שמורות, טפסים, אוטומציות, שיחות, "
          "קבצים, חברי לוח, התראות והיסטוריה")


def _bump_sequence(cx, table):
    """Make the table's id sequence sit above the ids already in it.

    A database whose rows arrived by import rather than through the app has a
    sequence that never advanced, and the first ordinary INSERT after that
    collides with an existing id. Checked and corrected here, because the
    failure it causes — a duplicate key on row one of five hundred — reads as a
    bug in this script rather than as the state the table was already in.
    """
    seq = scalar(cx, "select pg_get_serial_sequence(%s, 'id')", (table,))
    if not seq:
        return None
    top = scalar(cx, f"select coalesce(max(id), 0) from {table}") or 0
    cur_val = scalar(cx, "select last_value from " + seq)
    if cur_val is not None and cur_val <= top:
        scalar(cx, "select setval(%s, %s)", (seq, top + 1))
        return f"{table}: {cur_val} → {top + 1}"
    return None


def _insert(cx, table, values, shared):
    cols = [c for c in values if c in shared]
    cur = cx.cursor()
    cur.execute(
        f'insert into {table} ({", ".join(cols)}) values '
        f'({", ".join(["%s"] * len(cols))}) returning id',
        [values[c] for c in cols])
    new_id = cur.fetchone()[0]
    cur.close()
    return new_id


def apply_plan(dst, plan, report, args):
    b, settings = plan["board"], plan["settings"]
    print("\n── כותב ─────────────────────────────────────────────────")

    bumped = [m for m in (_bump_sequence(dst, t)
                          for t in ("boards", "groups", "tasks", "folders", "board_members"))
              if m]
    if bumped:
        print("  רצפי מזהים שעודכנו: " + "; ".join(bumped))

    folder_id = plan["folder"]["id"] if plan["folder"] else None
    if args.folder and folder_id is None:
        folder_id = _insert(dst, "folders",
                            {"environment_id": plan["env"]["id"], "name": args.folder,
                             "position": 0},
                            table_columns(dst, "folders"))
        print(f"  תיקייה חדשה {args.folder!r}: id={folder_id}")

    # ── the board ────────────────────────────────────────────────────────
    shared_boards = table_columns(dst, "boards") & set(b)
    board_row = {k: v for k, v in b.items() if k in shared_boards}
    board_row.update({
        "name": args.name or b["name"],
        "settings": json.dumps(settings, ensure_ascii=False),
        "environment_id": plan["env"]["id"],
        "folder_id": folder_id,
        # Each of these names a row in the SOURCE database and nothing in the
        # target: a department that is some other department here, a person who
        # deleted it there, a position among boards that are not these boards.
        "department_id": None,
        "organization_id": None,
        "deleted_at": None,
        "deleted_by": None,
        "position": 0,
        "is_archived": False,
    })
    board_row.pop("id", None)
    new_board = _insert(dst, "boards", board_row, shared_boards)
    plan["new_board_id"] = new_board
    print(f"  לוח: id={new_board}")

    # ── groups ───────────────────────────────────────────────────────────
    shared_groups = table_columns(dst, "groups")
    gmap = {}
    for g in plan["groups"]:
        row = {k: v for k, v in g.items() if k in shared_groups}
        row.pop("id", None)
        row["board_id"] = new_board
        gmap[g["id"]] = _insert(dst, "groups", row, shared_groups)
    print(f"  קבוצות: {len(gmap)}")

    # ── items ────────────────────────────────────────────────────────────
    # Parents before their sub-items, so a sub-item's parent_id is already a
    # number in this database by the time it is written. The source query orders
    # them that way; this is the guard that says so out loud if it ever does not.
    shared_tasks = table_columns(dst, "tasks")
    tmap = {}
    for it in plan["items"]:
        parent = it.get("parent_id")
        if parent and parent not in tmap:
            raise RuntimeError(
                f"item {it['id']} names parent {parent}, which has not been written yet")
        row = {k: v for k, v in it.items() if k in shared_tasks}
        row.pop("id", None)
        row.update({
            "board_id": new_board,
            "group_id": gmap.get(it.get("group_id")),
            "parent_id": tmap.get(parent) if parent else None,
            "custom_fields": json.dumps(it["_cells"], ensure_ascii=False),
            # Item-level permissions are a map of source user ids; see the note
            # on column perms above — cleared, not remapped.
            "permissions": json.dumps({}),
            # "מספר מזהה" is unique within the board it was minted for, and this
            # is a different board. Cleared so the target mints fresh ones.
            "item_uid": None,
            "item_uid_board": None,
            # These name rows that were not copied: the form the item arrived
            # through, the project step it hung off, who deleted it.
            "form_view_id": None,
            "step_id": None,
            "deleted_at": None,
            "deleted_by": None,
            "created_by": plan["people_map"].get(it.get("created_by")),
        })
        tmap[it["id"]] = _insert(dst, "tasks", row, shared_tasks)
    print(f"  פריטים: {len(tmap)}")

    # ── who is responsible for what ──────────────────────────────────────
    cur = dst.cursor()
    wrote = 0
    for a in plan["assignees"]:
        tid, uid = tmap.get(a["task_id"]), plan["people_map"].get(a["user_id"])
        if tid and uid:
            cur.execute("insert into task_assignees (task_id, user_id) values (%s, %s)",
                        (tid, uid))
            wrote += 1
    print(f"  שיוכי אחראים: {wrote}/{len(plan['assignees'])}")

    # ── one member, so the board can be opened at all ────────────────────
    # The board's own membership is not copied; access here is membership-based,
    # so a board that arrives with none is a board that has arrived nowhere.
    owner = plan["owner"]
    cur.execute("insert into board_members (board_id, user_id, role) values (%s, %s, %s)",
                (new_board, owner["id"], "admin"))
    print(f"  מנהל הלוח: {owner['name']} <{owner['email']}>")

    env_member = scalar(dst, "select count(*) from environment_members "
                             "where environment_id = %s and user_id = %s",
                        (plan["env"]["id"], owner["id"]))
    if not env_member:
        print(f"  ! {owner['email']} אינו חבר בסביבה {plan['env']['name']!r} — "
              "ייתכן שהלוח לא יופיע לו ברשימת הסביבות")
    cur.close()


if __name__ == "__main__":
    sys.exit(main())
