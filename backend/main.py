"""
CityOS — FastAPI Backend Server
"""
import os, sys, json, uuid, csv, io, re, secrets, threading, urllib.parse, urllib.request
import concurrent.futures
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from enum import Enum
from typing import Optional
from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response, StreamingResponse
import os
from pydantic import BaseModel
from sqlalchemy import and_, create_engine, event, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, with_loader_criteria

sys.path.insert(0, os.path.dirname(__file__))
from auth import (auth_mode, current_user, current_user_id, effective_auth_mode,
                  init_auth, resolve_user)
import entra_guests
import filter_ast
import import_monday
from models import (
    Organization, Department, Environment, EnvironmentMember, Folder, User, Board, Group, Task, Comment, BoardMember, WorkspaceMember, RolePermission, Automation, AutomationRun, AutomationVersion, AutomationUsage,
    AutomationTestRun,
    AutomationFreeze, ItemLink, BoardView, SavedView, BoardViewPrefs,
    Permit, CitizenRequest, PublicTransportStop, InfrastructureAsset,
    TaskStatus, Priority, BoardType, init_db,
    AnnualWorkPlan, Project, ProjectStep, BudgetLineItem,
    Approval, ChangeRequest, KPI, Dependency, Document, AuditLog,
    task_assignees, task_watchers,
    ProjectStatus, ApprovalStatus, ChangeRequestStatus,
    DependencyType, BudgetItemType, DocumentType, LoginEvent, UploadedFile, Notification
)

try:
    from dotenv import load_dotenv
    # Load .env from cityos/ root (parent of backend/)
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except Exception:
    pass

app = FastAPI(title="CODE-CAL MISSIONS", version="0.1.0")
# The SPA is served from the same origin as the API, so it needs no CORS grant at
# all. Extra origins (a staging frontend, a local vite server) go in
# CITYOS_CORS_ORIGINS as a comma-separated list. This was allow_origins=["*"].
_cors_origins = [o.strip() for o in (os.environ.get("CITYOS_CORS_ORIGINS") or "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins,
                       allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
                       allow_headers=["Content-Type", "X-CityOS-User"])

# The SPA shell is 650KB of HTML and is re-fetched on every entry, which on a
# phone is the single biggest cost of opening the app. Gzip takes it to ~177KB
# for ~13ms of CPU. Level 6 rather than the default 9: 9 saves under 1KB more
# and costs a third again as much time.
#
# Server-sent events are excluded. Starlette's GZipMiddleware honours neither
# `no-transform` nor a flush after each chunk, so wrapping the /api/events
# stream in it buffers messages until the stream closes — which, for a live
# feed, is never. EventSource always sends `Accept: text/event-stream`, so the
# request itself says whether it is a stream, before any response exists to
# inspect.
class ConditionalGZip:
    def __init__(self, app, minimum_size=500, compresslevel=6):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size,
                                   compresslevel=compresslevel)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            accept = Headers(scope=scope).get("accept", "")
            if "text/event-stream" not in accept:
                return await self.gzip(scope, receive, send)
        return await self.app(scope, receive, send)


app.add_middleware(ConditionalGZip)

# Endpoints that may be reached without an identity. Everything else under /api/
# requires one — so a route added tomorrow is protected by default instead of
# being protected only if its author remembered the dependency.
# /api/auth/dev-users is the local picker's directory, and the picker is what
# someone uses BEFORE they have an identity — so it cannot be behind the check.
# The route itself answers 404 in every mode but dev (see dev_picker_users), and
# dev mode already accepts any user id from a header or a cookie, so it opens
# nothing that was closed.
PUBLIC_API_PATHS = {"/api/status", "/api/auth/dev-users"}


@app.middleware("http")
async def require_authentication(request, call_next):
    path = request.url.path
    if (path.startswith("/api/")
            and path not in PUBLIC_API_PATHS
            and request.method != "OPTIONS"):
        try:
            with Session(engine) as db:
                resolve_user(db, request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    if "text/html" in resp.headers.get("content-type", ""):
        # `no-cache`, not `no-store`. Both force the browser to check with the
        # server before using the page, so a deploy is still picked up on the
        # very next entry — the difference is that `no-store` also forbids
        # keeping the bytes, so all ~180KB of the shell came down again every
        # single time. With `no-cache` the browser sends If-None-Match and an
        # unchanged shell answers 304 with no body at all. On a phone, where
        # this is paid on every entry, that is the difference between a
        # download and a round trip.
        # Safe because the only text/html this app serves is the SPA shell and
        # 404.html — the same bytes for every user, carrying nobody's data.
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp

# Persistent Postgres (production) via DATABASE_URL; SQLite otherwise (local).
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):  # SQLAlchemy needs postgresql://
        DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
    engine = init_db(DATABASE_URL)
    IS_SQLITE = False
else:
    DB_PATH = os.environ.get("CITYOS_DB_PATH", os.path.join(os.path.dirname(__file__), "cityos.db"))
    engine = init_db(f"sqlite:///{DB_PATH}")
    IS_SQLITE = True

# Identity comes from the transport (Entra ID via Azure Easy Auth), never from a
# request parameter. See backend/auth.py for the two modes and why the default
# fails closed.
init_auth(engine)
if auth_mode() == "dev":
    print("[auth] DEV MODE — identity is taken from the X-CityOS-User header. "
          "Never set CITYOS_AUTH_MODE=dev in production.")
elif auth_mode() == "entra":
    # The SSO routes live at /auth/* — outside /api/, so the middleware above
    # lets them through unauthenticated, which is the whole point of a login
    # page. They are registered here, well before the StaticFiles mount at "/",
    # because the first matching route wins.
    import entra
    app.include_router(entra.router)
    if entra.is_configured():
        print(f"[auth] ENTRA SSO — tenant {entra.tenant_id()}, client {entra.client_id()}")
    else:
        print("[auth] ENTRA SSO selected but not configured — set ENTRA_TENANT_ID, "
              "ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET. Every request will be refused.")

def _migrate():
    """Lightweight additive migrations for SQLite (create_all won't ALTER)."""
    from sqlalchemy import text
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(comments)"))}
        for name, ddl in [("parent_id", "INTEGER"), ("mentions", "JSON"), ("likes", "JSON"),
                          ("seen_by", "JSON"), ("origin", "JSON")]:
            if name not in cols:
                conn.execute(text(f"ALTER TABLE comments ADD COLUMN {name} {ddl}"))
        tcols = {r[1] for r in conn.execute(text("PRAGMA table_info(tasks)"))}
        # The tags column type was removed from the product. Dropping the column
        # deletes the values with it, which is the point — leaving them behind
        # would keep data nobody can see, read or delete through the app.
        if "tags" in tcols:
            conn.execute(text("ALTER TABLE tasks DROP COLUMN tags"))
            tcols.discard("tags")
        if "permissions" not in tcols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN permissions JSON"))
        # "מזהה פריט" — automatic 11-digit item identifier (+ the board it belongs to)
        if "item_uid" not in tcols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN item_uid VARCHAR(11)"))
        if "item_uid_board" not in tcols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN item_uid_board INTEGER"))
        # boards: environment membership (Monday-style environments/workspaces)
        bcols = {r[1] for r in conn.execute(text("PRAGMA table_info(boards)"))}
        if "environment_id" not in bcols:
            conn.execute(text("ALTER TABLE boards ADD COLUMN environment_id INTEGER"))
        if "folder_id" not in bcols:
            conn.execute(text("ALTER TABLE boards ADD COLUMN folder_id INTEGER"))
        if "position" not in bcols:
            conn.execute(text("ALTER TABLE boards ADD COLUMN position INTEGER DEFAULT 0"))
        # saved views: lock, pin, and a recycle bin of their own
        vcols = {r[1] for r in conn.execute(text("PRAGMA table_info(saved_views)"))}
        if vcols:                      # absent on a database being created fresh
            for name, ddl in [("locked", "BOOLEAN DEFAULT 0"),
                              ("pinned", "BOOLEAN DEFAULT 0"),
                              ("deleted_at", "DATETIME"),
                              ("deleted_by", "INTEGER"),
                              ("kind", "VARCHAR(10) DEFAULT 'saved'"),
                              ("config_version", "INTEGER DEFAULT 1"),
                              ("schema_version", "INTEGER DEFAULT 1")]:
                if name not in vcols:
                    conn.execute(text(f"ALTER TABLE saved_views ADD COLUMN {name} {ddl}"))
            # The main table has no author — it is the board — so owner_id has
            # to accept NULL. SQLite cannot relax a NOT NULL in place, and the
            # column predates this, so the table is rebuilt: the documented
            # create-copy-drop-rename, with the rows carried across by name so
            # the order of the columns here cannot matter.
            notnull = {r[1] for r in conn.execute(text("PRAGMA table_info(saved_views)"))
                       if r[3] and r[1] == "owner_id"}
            if notnull:
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info(saved_views)"))]
                names = ", ".join(cols)
                conn.execute(text("""CREATE TABLE saved_views__new (
                    id INTEGER PRIMARY KEY,
                    board_id INTEGER NOT NULL REFERENCES boards(id),
                    owner_id INTEGER REFERENCES users(id),
                    name VARCHAR(80) NOT NULL,
                    kind VARCHAR(10) DEFAULT 'saved',
                    visibility VARCHAR(10) DEFAULT 'private',
                    filters JSON,
                    position INTEGER DEFAULT 0,
                    locked BOOLEAN DEFAULT 0,
                    pinned BOOLEAN DEFAULT 0,
                    deleted_at DATETIME,
                    deleted_by INTEGER REFERENCES users(id),
                    config_version INTEGER DEFAULT 1,
                    schema_version INTEGER DEFAULT 1,
                    created_at DATETIME,
                    updated_at DATETIME)"""))
                conn.execute(text(f"INSERT INTO saved_views__new ({names}) "
                                  f"SELECT {names} FROM saved_views"))
                conn.execute(text("DROP TABLE saved_views"))
                conn.execute(text("ALTER TABLE saved_views__new RENAME TO saved_views"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_saved_views_board_id "
                                  "ON saved_views (board_id)"))
                print("[views] saved_views rebuilt — owner_id now accepts NULL")
            # ── the uniqueness rule, at the only place it can be a RULE ──
            # _check_view_name reads and then the insert writes, and between
            # those two the answer can change: two people naming a view the
            # same thing at the same moment both pass the check and both land.
            # A partial unique index is what makes "one name per board" true
            # rather than usually true. Live rows only — a name in the bin
            # holds nothing, which is the behaviour the restore relies on.
            # lower() here and casefold() in the application: the index is the
            # backstop, the check is the precise answer and the message.
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_saved_views_board_name "
                "ON saved_views (board_id, lower(trim(name))) "
                "WHERE deleted_at IS NULL"))
        pcols = {r[1] for r in conn.execute(text("PRAGMA table_info(board_view_prefs)"))}
        if pcols and "last_view_id" not in pcols:
            conn.execute(text("ALTER TABLE board_view_prefs ADD COLUMN last_view_id INTEGER"))
        # boards: recycle bin (soft delete) — NULL deleted_at means a live board
        if "deleted_at" not in bcols:
            conn.execute(text("ALTER TABLE boards ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in bcols:
            conn.execute(text("ALTER TABLE boards ADD COLUMN deleted_by INTEGER"))
        # tasks: recycle bin per board — NULL deleted_at means a live item
        tcols = {r[1] for r in conn.execute(text("PRAGMA table_info(tasks)"))}
        if "deleted_at" not in tcols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in tcols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN deleted_by INTEGER"))
        # environments: primary-workspace flag (may predate the column)
        ecols = {r[1] for r in conn.execute(text("PRAGMA table_info(environments)"))}
        if ecols and "is_primary" not in ecols:
            conn.execute(text("ALTER TABLE environments ADD COLUMN is_primary BOOLEAN DEFAULT 0"))
        if ecols and "created_by" not in ecols:
            conn.execute(text("ALTER TABLE environments ADD COLUMN created_by INTEGER"))
        # environment members: per-environment role (manager | member)
        emcols = {r[1] for r in conn.execute(text("PRAGMA table_info(environment_members)"))}
        if emcols and "role" not in emcols:
            conn.execute(text("ALTER TABLE environment_members ADD COLUMN role VARCHAR(20) DEFAULT 'member'"))
        # notifications table may predate the task_id column (created before mentions)
        ncols = {r[1] for r in conn.execute(text("PRAGMA table_info(notifications)"))}
        if ncols and "task_id" not in ncols:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN task_id INTEGER"))
        # automations: the management columns (owner, importance, status, counters)
        acols = {r[1] for r in conn.execute(text("PRAGMA table_info(automations)"))}
        for name, ddl in [("name", "VARCHAR(120)"), ("description", "TEXT"),
                          ("status", "VARCHAR(16) DEFAULT 'active'"),
                          ("owner_id", "INTEGER"),
                          ("importance", "VARCHAR(10) DEFAULT 'normal'"),
                          ("run_order", "INTEGER DEFAULT 0"),
                          ("fail_count", "INTEGER DEFAULT 0"),
                          ("skip_count", "INTEGER DEFAULT 0"),
                          ("consecutive_failures", "INTEGER DEFAULT 0"),
                          ("last_success_at", "DATETIME"), ("last_failure_at", "DATETIME"),
                          ("last_outcome", "VARCHAR(12)"),
                          ("activated_at", "DATETIME"), ("draft_version", "INTEGER")]:
            if acols and name not in acols:
                conn.execute(text(f"ALTER TABLE automations ADD COLUMN {name} {ddl}"))
        # a rule stored before status existed is described by the switch it has
        if acols and "status" not in acols:
            conn.execute(text("UPDATE automations SET status = CASE WHEN is_active THEN 'active' ELSE 'paused' END"))
        rcols = {r[1] for r in conn.execute(text("PRAGMA table_info(automation_runs)"))}
        if rcols and "is_test" not in rcols:
            conn.execute(text("ALTER TABLE automation_runs ADD COLUMN is_test BOOLEAN DEFAULT 0"))
        if rcols and "version" not in rcols:
            conn.execute(text("ALTER TABLE automation_runs ADD COLUMN version INTEGER"))
        vcols = {r[1] for r in conn.execute(text("PRAGMA table_info(automation_versions)"))}
        if vcols and "is_draft" not in vcols:
            conn.execute(text("ALTER TABLE automation_versions ADD COLUMN is_draft BOOLEAN DEFAULT 0"))
        if vcols and "published_at" not in vcols:
            conn.execute(text("ALTER TABLE automation_versions ADD COLUMN published_at DATETIME"))
        # the trigger/action columns were renamed: both words are SQL keywords, and
        # a table created under the old names is still out there. The old columns
        # are left in place — dropping them would take their values with them.
        for old_c, new_c in (("trigger", "trigger_key"), ("action", "action_key")):
            if rcols and new_c not in rcols:
                conn.execute(text(f"ALTER TABLE automation_runs ADD COLUMN {new_c} VARCHAR(40)"))
                if old_c in rcols:
                    conn.execute(text(f'UPDATE automation_runs SET {new_c} = "{old_c}"'))
        # users: job title + contact phone (for the profile card)
        alcols = {r[1] for r in conn.execute(text("PRAGMA table_info(audit_logs)"))}
        if "origin" not in alcols:
            conn.execute(text("ALTER TABLE audit_logs ADD COLUMN origin JSON"))
        ucols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)"))}
        if "title" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN title VARCHAR(120)"))
        if "email_notifications" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_notifications BOOLEAN DEFAULT 1"))
        if "notif_prefs" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN notif_prefs JSON"))
        if "is_active" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
        # users: Entra object id for guests invited from the guests screen
        if "entra_object_id" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN entra_object_id VARCHAR(64)"))
        _demo = {
            1: ("מנהל אגף הנדסה ותשתיות", "050-2345678"),
            2: ("מנהלת מחלקת תחבורה",     "052-3456789"),
            3: ("מנהל מחלקת תכנון",       "054-4567890"),
            4: ("רכזת פרויקטים",          "053-5678901"),
            5: ("מהנדס ביצוע",            "050-6789012"),
            6: ("רכזת שירות לתושב",       "052-7890123"),
            7: ("עובד תחזוקה",            "058-8901234"),
        }
        for uid, (title, phone) in _demo.items():
            conn.execute(text("UPDATE users SET title=COALESCE(title,:t), phone=COALESCE(phone,:p) WHERE id=:id"),
                         {"t": title, "p": phone, "id": uid})
# The additive migrations use SQLite PRAGMA/ALTER; on Postgres create_all()
# already builds every table with all current columns, so they're not needed.
if IS_SQLITE:
    _migrate()
else:
    # Postgres: create_all builds new tables fully, but columns added later to
    # already-existing tables must be back-filled. Each ALTER runs in its OWN
    # transaction so one failure can't roll back the others (notably item_uid,
    # which the current model always SELECTs — if it's missing, task loads break).
    from sqlalchemy import text as _text
    _PG_MIGRATIONS = [
        "ALTER TABLE comments ADD COLUMN IF NOT EXISTS seen_by JSON",
        "ALTER TABLE comments ADD COLUMN IF NOT EXISTS origin JSON",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS origin JSON",
        # saved views: lock, pin, their own bin, and the three fields the
        # record chapter adds — kind, and the two versions
        "ALTER TABLE saved_views ADD COLUMN IF NOT EXISTS locked BOOLEAN DEFAULT FALSE",
        "ALTER TABLE saved_views ADD COLUMN IF NOT EXISTS pinned BOOLEAN DEFAULT FALSE",
        "ALTER TABLE saved_views ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
        "ALTER TABLE saved_views ADD COLUMN IF NOT EXISTS deleted_by INTEGER",
        "ALTER TABLE saved_views ADD COLUMN IF NOT EXISTS kind VARCHAR(10) DEFAULT 'saved'",
        "ALTER TABLE saved_views ADD COLUMN IF NOT EXISTS config_version INTEGER DEFAULT 1",
        "ALTER TABLE saved_views ADD COLUMN IF NOT EXISTS schema_version INTEGER DEFAULT 1",
        "ALTER TABLE saved_views ALTER COLUMN owner_id DROP NOT NULL",
        "ALTER TABLE board_view_prefs ADD COLUMN IF NOT EXISTS last_view_id INTEGER",
        # see the SQLite side for why this is an index and not only a check
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_saved_views_board_name "
        "ON saved_views (board_id, lower(trim(name))) WHERE deleted_at IS NULL",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS task_id INTEGER",
        "ALTER TABLE boards ADD COLUMN IF NOT EXISTS environment_id INTEGER",
        "ALTER TABLE boards ADD COLUMN IF NOT EXISTS folder_id INTEGER",
        "ALTER TABLE boards ADD COLUMN IF NOT EXISTS position INTEGER DEFAULT 0",
        "ALTER TABLE boards ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
        "ALTER TABLE boards ADD COLUMN IF NOT EXISTS deleted_by INTEGER",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS deleted_by INTEGER",
        "ALTER TABLE environments ADD COLUMN IF NOT EXISTS is_primary BOOLEAN DEFAULT FALSE",
        "ALTER TABLE environments ADD COLUMN IF NOT EXISTS created_by INTEGER",
        "ALTER TABLE environment_members ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'member'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS item_uid VARCHAR(11)",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS item_uid_board INTEGER",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_object_id VARCHAR(64)",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS name VARCHAR(120)",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'active'",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS owner_id INTEGER",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS importance VARCHAR(10) DEFAULT 'normal'",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS run_order INTEGER DEFAULT 0",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS fail_count INTEGER DEFAULT 0",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS skip_count INTEGER DEFAULT 0",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMP",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS last_failure_at TIMESTAMP",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS last_outcome VARCHAR(12)",
        "UPDATE automations SET status = CASE WHEN is_active THEN 'active' ELSE 'paused' END WHERE status IS NULL",
        "ALTER TABLE automation_runs ADD COLUMN IF NOT EXISTS is_test BOOLEAN DEFAULT FALSE",
        "ALTER TABLE automation_runs ADD COLUMN IF NOT EXISTS version INTEGER",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS activated_at TIMESTAMP",
        "ALTER TABLE automations ADD COLUMN IF NOT EXISTS draft_version INTEGER",
        "ALTER TABLE automation_versions ADD COLUMN IF NOT EXISTS is_draft BOOLEAN DEFAULT FALSE",
        "ALTER TABLE automation_versions ADD COLUMN IF NOT EXISTS published_at TIMESTAMP",
        'ALTER TABLE automation_runs ADD COLUMN IF NOT EXISTS trigger_key VARCHAR(40)',
        'ALTER TABLE automation_runs ADD COLUMN IF NOT EXISTS action_key VARCHAR(40)',
        # carried over only on a database that has the pre-rename columns; a
        # bare UPDATE would fail — and log — on every startup of a fresh one
        """DO $$ BEGIN
             IF EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name='automation_runs' AND column_name='trigger') THEN
               UPDATE automation_runs SET trigger_key = "trigger" WHERE trigger_key IS NULL;
             END IF;
             IF EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name='automation_runs' AND column_name='action') THEN
               UPDATE automation_runs SET action_key = "action" WHERE action_key IS NULL;
             END IF;
           END $$;""",
        # tags was removed from the product; the column goes and takes its values
        "ALTER TABLE tasks DROP COLUMN IF EXISTS tags",
    ]
    for _sql in _PG_MIGRATIONS:
        try:
            with engine.begin() as _conn:
                _conn.execute(_text(_sql))
        except Exception as _e:
            print(f"⚠️  pg migration skipped: {_sql!r} → {_e}", flush=True)


def _forget_tags_in_board_settings():
    """Dropping the column leaves boards still naming it.

    A board's settings remember column order, widths, labels and which columns
    are hidden. Boards configured before the removal carry "tags" in those
    lists. Nothing reads it — the order is applied to the columns that exist —
    but it is leftover data describing a feature that is gone, and the request
    was to remove the feature and its data. Idempotent: after the first pass
    there is nothing left to match, so later starts do no writes.
    """
    keys = ("col_order", "col_hidden", "col_labels", "col_widths")
    with Session(engine) as db:
        touched = 0
        for b in db.query(Board).execution_options(include_deleted=True).all():
            st = b.settings or {}
            if not any("tags" in (st.get(k) or []) for k in keys):
                continue
            new = dict(st)
            for k in keys:
                v = new.get(k)
                if isinstance(v, list):
                    new[k] = [x for x in v if x != "tags"]
                elif isinstance(v, dict):
                    new[k] = {kk: vv for kk, vv in v.items() if kk != "tags"}
            b.settings = new
            touched += 1
        if touched:
            db.commit()
            print(f"[migrate] removed the tags column from {touched} board(s) settings", flush=True)


_forget_tags_in_board_settings()

# Seed on first run only — on a persistent DB (Postgres) skip if data exists,
# so real data isn't duplicated or overwritten on every cold start.
from events import bus, EVENTS_ENABLED, HEARTBEAT_SECONDS
import asyncio
from seed import seed_database, seed_work_plan
with Session(engine) as _seed_db:
    _db_empty = _seed_db.query(Board).count() == 0
if _db_empty:
    seed_database(engine)
    seed_work_plan(engine)

REMOVED_DEMO_USERS = {
    "רחל לוי": "rachel@hodhasharon.gov.il",
    "שרה ברק": "sarah@hodhasharon.gov.il",
    "יוסי אברהם": "yossi@hodhasharon.gov.il",
    "נעה שטרן": "noa@hodhasharon.gov.il",
    "עומר גולן": "omer@hodhasharon.gov.il",
    "משה כהן": "admin@hodhasharon.gov.il",
    "דן מזרחי": "dan@hodhasharon.gov.il",
}

def _purge_removed_demo_users():
    """Keep removed demo users out of existing local/serverless databases."""
    # Imported here, not read off the module: `task_assignees` is also the name
    # of a route handler defined further down, which rebinds the global once the
    # module finishes loading. This function ran at import time, before that
    # happened, so it never noticed — and would have failed on the association
    # table the moment anything called it again.
    from models import task_assignees as assignee_rows, task_watchers as watcher_rows
    names = set(REMOVED_DEMO_USERS)
    emails = set(REMOVED_DEMO_USERS.values())
    with Session(engine) as db:
        users = db.query(User).filter(or_(User.name.in_(names), User.email.in_(emails))).all()
        ids = [u.id for u in users]
        if not ids:
            return

        # Never the last way in. Deleting every administrator leaves a database
        # nobody can administer and no screen that can grant it back — so a demo
        # account that is still the only one is kept, and said so.
        #
        # Both rows count, the same two _cap reads. On a database that has just
        # been seeded this step runs before memberships exist at all, so asking
        # only about WorkspaceMember would find no administrators anywhere and
        # cheerfully delete the only one there was.
        admin_ids = ({m.user_id for m in db.query(WorkspaceMember)
                      .filter(WorkspaceMember.role == "admin").all()}
                     | {u.id for u in db.query(User).filter(User.role == "admin").all()})
        if admin_ids and admin_ids.issubset(set(ids)):
            keep = sorted(admin_ids)[0]
            ids = [i for i in ids if i != keep]
            kept = next((u.email for u in users if u.id == keep), keep)
            print(f"⚠️  keeping {kept}: the only administrator left", flush=True)
            if not ids:
                return

        # Rows that only exist to join a user to something: they go with them.
        db.execute(assignee_rows.delete().where(assignee_rows.c.user_id.in_(ids)))
        db.execute(watcher_rows.delete().where(watcher_rows.c.user_id.in_(ids)))
        db.query(BoardMember).filter(BoardMember.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(EnvironmentMember).filter(EnvironmentMember.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(BoardView).filter(BoardView.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(LoginEvent).filter(LoginEvent.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.user_id.in_(ids)).delete(synchronize_session=False)

        db.query(Task).filter(Task.created_by.in_(ids)).update({Task.created_by: None}, synchronize_session=False)
        db.query(Comment).filter(Comment.user_id.in_(ids)).update({Comment.user_id: None}, synchronize_session=False)
        db.query(Permit).filter(Permit.assigned_to.in_(ids)).update({Permit.assigned_to: None}, synchronize_session=False)
        db.query(CitizenRequest).filter(CitizenRequest.assigned_to.in_(ids)).update({CitizenRequest.assigned_to: None}, synchronize_session=False)
        db.query(Project).filter(Project.manager_id.in_(ids)).update({Project.manager_id: None}, synchronize_session=False)
        db.query(ProjectStep).filter(ProjectStep.owner_id.in_(ids)).update({ProjectStep.owner_id: None}, synchronize_session=False)
        db.query(Approval).filter(Approval.approver_user_id.in_(ids)).update({Approval.approver_user_id: None}, synchronize_session=False)
        db.query(ChangeRequest).filter(ChangeRequest.requested_by.in_(ids)).update({ChangeRequest.requested_by: None}, synchronize_session=False)
        db.query(ChangeRequest).filter(ChangeRequest.approved_by.in_(ids)).update({ChangeRequest.approved_by: None}, synchronize_session=False)
        db.query(Document).filter(Document.uploaded_by.in_(ids)).update({Document.uploaded_by: None}, synchronize_session=False)
        db.query(AuditLog).filter(AuditLog.changed_by.in_(ids)).update({AuditLog.changed_by: None}, synchronize_session=False)
        # These four were never detached. It went unnoticed because SQLite does
        # not enforce foreign keys unless asked and the demo users listed above
        # happened to hold none of them — but on Postgres one dangling
        # reference makes the DELETE fail, _safe_startup logs it and carries on,
        # and the users quietly stay. Environment.created_by is the newest of
        # them and the likeliest to be held.
        db.query(Environment).filter(Environment.created_by.in_(ids)).update({Environment.created_by: None}, synchronize_session=False)
        db.query(Automation).filter(Automation.created_by.in_(ids)).update({Automation.created_by: None}, synchronize_session=False)
        db.query(Automation).filter(Automation.updated_by.in_(ids)).update({Automation.updated_by: None}, synchronize_session=False)
        db.query(AutomationRun).filter(AutomationRun.actor_id.in_(ids)).update({AutomationRun.actor_id: None}, synchronize_session=False)
        db.query(ItemLink).filter(ItemLink.created_by.in_(ids)).update({ItemLink.created_by: None}, synchronize_session=False)
        db.query(Board).filter(Board.deleted_by.in_(ids)).update({Board.deleted_by: None}, synchronize_session=False)
        db.query(Task).filter(Task.deleted_by.in_(ids)).update({Task.deleted_by: None}, synchronize_session=False)

        gone = [u.email for u in users if u.id in ids]
        db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        print(f"[seed] demo users removed: {', '.join(gone)}", flush=True)

def _safe_startup(fn):
    """Run a one-time startup/seed step; never let it crash the whole process.
    On a persistent prod DB these are mostly idempotent no-ops, so a failure
    against existing data must not take the server down — log and carry on."""
    try:
        fn()
    except Exception as _e:
        print(f"⚠️  startup step {getattr(fn,'__name__',fn)} failed: {_e}", flush=True)

_safe_startup(_purge_removed_demo_users)

def _seed_memberships():
    """One-time: give existing boards their members so nothing disappears.
    New boards start private to their creator (see create_board)."""
    with Session(engine) as db:
        users = db.query(User).all()
        # workspace/environment members
        if db.query(WorkspaceMember).count() == 0:
            for u in users:
                # only a true system admin (User.role == "admin") is a workspace/system
                # admin; a "manager" is NOT — they get access only to granted environments
                erole = "admin" if u.role == "admin" else ("viewer" if u.role == "viewer" else "member")
                db.add(WorkspaceMember(user_id=u.id, role=erole))
            db.commit()
        # board members
        if db.query(BoardMember).count() == 0:
            for b in db.query(Board).all():
                for u in users:
                    role = "viewer" if u.role == "viewer" else ("admin" if u.role in ("admin", "manager") else "editor")
                    db.add(BoardMember(board_id=b.id, user_id=u.id, role=role))
            db.commit()
_safe_startup(_seed_memberships)

# The municipality's environments (Monday-style workspaces, like 'עיריית הוד השרון').
# Seeded once; sysadmins manage them afterwards via /api/environments.
ENVIRONMENTS_SEED = [
    ("בינוי", "🏗️"), ("היסעים", "🚌"), ("חדשנות טכנולוגיה ומערכות מידע", "💡"),
    ("כספים", "💰"), ("מגזר ערבי דרוזי וצ'רקסי", "🕌"), ("מטה", "🏛️"),
    ("מינהל ואיכות", "📋"), ("משאבי אנוש", "👥"), ("משפטית", "⚖️"),
    ("סוכנות הביטוח", "🛡️"), ("פיקוח ובקרה", "🔎"), ("פיתוח תשתיות ואחזקה", "🛠️"),
    ('פמ"א', "🏭"), ("קשרי לקוחות", "🤝"), ("רגולציה וקשרי ממשל", "📜"),
    ("שיווק", "📣"), ('תבו"ר', "💵"),
]
_ENV_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]

# The primary workspace is matched BY NAME on every startup — renaming it in the
# UI without changing this would make the seeder create a second primary
# environment under the old name.
PRIMARY_ENV_NAME = "סביבה ראשית"
# What the default workspace used to be called. Renamed once, on the boot that
# first carries this list, and only while it still answers to the old name — it
# is an ordinary renameable workspace, so an admin who has given it a name of
# their own must not find it renamed back under them on the next deploy.
#
# "מערכות מידע" is in the list for a different reason than "בדיקה". It is not a
# name this workspace shipped with; it is a name the default workspace was given
# at some point, which left the one workspace EVERY user is in reading as a
# single department's — and a new user, who gets this workspace and no other,
# opened the app inside "מערכות מידע". The organisation's own department of that
# name has its own workspace and is untouched. The rename is therefore
# deliberate and deliberately overriding: name the default workspace that again
# and the next boot will name it back.
LEGACY_PRIMARY_NAMES = ("בדיקה", "מערכות מידע")

def _seed_environments():
    """Seed environments on first run (idempotent by name):
    - a primary workspace (PRIMARY_ENV_NAME) that holds the existing/legacy boards
    - the municipality's 17 environments
    Also gives every current user access to the primary workspace so nothing
    disappears, and attaches legacy (unassigned) boards to the primary workspace."""
    with Session(engine) as db:
        org = db.query(Organization).first()
        existing = {e.name: e for e in db.query(Environment).all()}
        # 1) primary workspace first. An existing primary wins over the name:
        # renaming it (it is an ordinary editable workspace) must not make this
        # seeder mint a second primary under the old name on the next boot.
        #
        # Repair first: more than one workspace flagged primary is never valid.
        # It is the residue of the older name-matching logic — renaming the
        # default workspace made the next boot mint another one under the old
        # name, each flagged primary. A primary workspace cannot be renamed away
        # from, moved out of or deleted, so every extra one is a workspace the
        # admin can no longer get rid of. Keep the one that actually holds the
        # boards (ties: the oldest) and demote the rest to ordinary workspaces.
        prims = db.query(Environment).filter(Environment.is_primary == True).order_by(Environment.id).all()
        if len(prims) > 1:
            counts = {e.id: db.query(Board).filter(Board.environment_id == e.id).count() for e in prims}
            keep = max(prims, key=lambda e: (counts[e.id], -e.id))
            for e in prims:
                if e.id != keep.id:
                    e.is_primary = False
            db.flush()
            print(f"↻ demoted {len(prims) - 1} extra default workspace(s); kept '{keep.name}'")
            prims = [keep]
        primary = (prims[0] if prims else None) or existing.get(PRIMARY_ENV_NAME)
        if not primary:
            primary = Environment(name=PRIMARY_ENV_NAME, icon="🏛️", color=_ENV_COLORS[0],
                                  position=0, is_primary=True, organization_id=org.id if org else None)
            db.add(primary); db.flush()
        elif not primary.is_primary:
            primary.is_primary = True
        if (primary.name or "").strip() in LEGACY_PRIMARY_NAMES:
            primary.name = PRIMARY_ENV_NAME
            print(f"↻ the default workspace is now '{PRIMARY_ENV_NAME}'")
        # 2) the 17 municipality environments after it
        pos = max([e.position for e in existing.values()], default=0) + 1
        for name, icon in ENVIRONMENTS_SEED:
            if name in existing:
                continue
            db.add(Environment(name=name, icon=icon, color=_ENV_COLORS[pos % len(_ENV_COLORS)],
                               position=pos, organization_id=org.id if org else None))
            pos += 1
        # 3) legacy boards (no environment) belong to the primary workspace
        db.query(Board).filter(Board.environment_id == None).update({Board.environment_id: primary.id})
        # 4) nothing to grant: every user belongs to the primary workspace by
        # definition — see _user_env_ids. It used to be seeded as a row per
        # user, once, which left everyone created afterwards outside the one
        # workspace everybody is supposed to share. Rows that already exist are
        # left alone; on this workspace they now carry only the manager role.
        db.commit()
_safe_startup(_seed_environments)


AUTO_COLS = (("created_at", "מועד יצירה", "sys_created_at"),
             ("created_by", "יוצר הרשומה", "sys_created_by"))

def _backfill_auto_columns():
    """Give every board the two automatic columns — who created an item and when.

    New boards ship with them; boards that predate them did not have them at
    all, and the creator column on the oldest ones is a plain people column
    that only auto-filled for items created while it existed. Both are derived
    from the item itself, so adding them is enough — no values to write, and
    they are right for items that predate the column.

    Runs once per board (`auto_cols_v1`): an admin who then removes a column
    must not have it come back on the next restart.
    """
    with Session(engine) as db:
        added = 0
        for b in db.query(Board).all():
            s = dict(b.settings or {})
            cols = [dict(c) for c in (s.get("columns") or [])]
            changed = False
            # the legacy creator column is a people column that has to be written
            # on creation — the derived type reads the item's own creator instead
            for c in cols:
                if c.get("id") == "sys_created_by" and c.get("type") == "people":
                    c["type"] = "created_by"
                    changed = True
            if not s.get("auto_cols_v1"):
                have = {c.get("type") for c in cols}
                used = {c.get("id") for c in cols}
                for typ, title, sid in AUTO_COLS:
                    if typ in have:
                        continue
                    cid = sid if sid not in used else ("col_" + uuid.uuid4().hex[:8])
                    cols.append({"id": cid, "type": typ, "title": title, "options": None,
                                 "formula": None, "connect": None, "copy_mode": None, "perms": {}})
                    used.add(cid)
                    added += 1
                    changed = True
                s["auto_cols_v1"] = True
                changed = True
            if changed:
                s["columns"] = cols
                b.settings = s
        db.commit()
        if added:
            print(f"↻ added {added} automatic column(s) across boards", flush=True)
_safe_startup(_backfill_auto_columns)

# ── Configurable capability matrix (role → feature) ──────────────────
# 'admin' always has every capability (implicit, never stored). These roles are
# editable by a system admin from the SysAdmin → role-permissions panel.
CAPABILITIES = ["manage_system", "create_environment", "create_board",
                "view_automations", "export_automation_log"]
CAP_HE = {
    "manage_system": "ניהול מערכת",
    "create_environment": "יצירת סביבה חדשה",
    "create_board": "יצירת לוח חדש",
    # Two the automations matrix needs and a role alone cannot express: a board
    # EDITOR sees the rules only where the first is granted, and a board ADMIN
    # takes data out of the system only where the second is.
    "view_automations": "צפייה באוטומציות של לוח (לחבר לוח)",
    "export_automation_log": "ייצוא נתוני אוטומציות ושחזור גרסה",
}
EDITABLE_ROLES = ["manager", "member", "viewer", "guest"]
ROLE_HE_BE = {"admin": "מנהל מערכת", "manager": "מנהל", "member": "חבר צוות",
              "viewer": "צפייה בלבד", "guest": "אורח"}

def _seed_role_permissions():
    """Ensure a row exists for every (editable role × capability). Defaults to
    False — only 'admin' (implicit) starts with access, matching prior behavior."""
    with Session(engine) as db:
        existing = {(r.role, r.capability) for r in db.query(RolePermission).all()}
        added = False
        for role in EDITABLE_ROLES:
            for cap in CAPABILITIES:
                if (role, cap) not in existing:
                    db.add(RolePermission(role=role, capability=cap, allowed=False))
                    added = True
        if added:
            db.commit()
_safe_startup(_seed_role_permissions)


def _repair_promoted_admins():
    """Give the workspace row to anyone the users screen already made an admin.

    Promotions written before _sync_ws_role existed set User.role and left the
    workspace row alone, so the account was let into ניהול מערכת and refused
    every action offered there. This puts the row where it was always meant to
    be. It only ever grants, and only where User.role already says "admin" —
    an administrator's own decision, recorded but not carried through. It never
    demotes: a workspace admin who is something else in the users screen may
    have been granted that row deliberately, and taking it away on a deploy is
    not a repair.
    """
    with Session(engine) as db:
        admins = db.query(User).filter(User.role == "admin").all()
        if not admins:
            return
        rows = {m.user_id: m for m in db.query(WorkspaceMember)
                .filter(WorkspaceMember.user_id.in_([u.id for u in admins])).all()}
        fixed = []
        for u in admins:
            m = rows.get(u.id)
            if m is None:
                db.add(WorkspaceMember(user_id=u.id, role="admin"))
                fixed.append(u.email)
            elif m.role != "admin":
                m.role = "admin"
                fixed.append(u.email)
        if fixed:
            db.commit()
            print(f"[auth] workspace admin row restored for: {', '.join(fixed)}", flush=True)
_safe_startup(_repair_promoted_admins)

def _role_perms(db):
    """Return {role: {capability: bool}} for the editable roles."""
    m = {role: {cap: False for cap in CAPABILITIES} for role in EDITABLE_ROLES}
    for r in db.query(RolePermission).all():
        if r.role in m and r.capability in CAPABILITIES:
            m[r.role][r.capability] = bool(r.allowed)
    return m

def _cap(db, uid, cap):
    """Whether the user (by User.role, with 'admin' always-on) has a capability."""
    if uid is None:
        return False
    if _ws_role(db, uid) == "admin":
        return True
    u = db.query(User).filter(User.id == uid).first()
    role = (u.role if u else None) or "guest"
    if role == "admin":
        return True
    row = (db.query(RolePermission)
           .filter(RolePermission.role == role, RolePermission.capability == cap).first())
    return bool(row and row.allowed)


def _ws_role_for(user_role):
    """The workspace-membership role a User.role implies.

    Two rows carry "is this person an admin": User.role, which the users screen
    edits, and WorkspaceMember.role, which most of the system actually reads.
    They are set together when an account is created — and were not when a role
    was changed afterwards, which is the whole of this.
    """
    return "admin" if user_role == "admin" else ("viewer" if user_role == "viewer" else "member")


def _sync_ws_role(db, user):
    """Make the workspace row say what the user's role says.

    Promoting someone to מנהל מערכת in the users screen wrote User.role and
    stopped there. `_cap` accepts User.role == "admin", so they were let into
    ניהול מערכת; everything reading the workspace row went on treating them as
    whatever they were before. In production that produced an account that
    could open the environments screen and act on nothing in it, while the same
    person in QA — created as an admin, both rows written together — had the
    lot. Both directions: a demotion has to take the workspace row with it, or
    it is not a demotion.
    """
    want = _ws_role_for(user.role)
    m = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).first()
    if m:
        m.role = want
    else:
        db.add(WorkspaceMember(user_id=user.id, role=want))


def _can_admin_envs(db, uid):
    """Who may administer environments: see them all, delete one, hand out the
    manager role in one.

    Two different tests used to answer "is this person a system admin". The
    ניהול מערכת screen opens on the `manage_system` capability; the actions
    offered inside it asked instead for a WorkspaceMember row with role=admin.
    Someone holding one and not the other was let into the screen that lists
    every environment and refused every action on it — which is exactly what
    production looked like next to QA, where the same person also holds the row.

    It is now one question, and it is the capability, because that is what the
    screen itself is gated on: whoever may open it may act in it. `_cap`
    already treats a workspace admin as holding everything, so nobody who could
    do this before loses it.
    """
    return _cap(db, uid, "manage_system")

def get_db():
    with Session(engine) as session:
        yield session

# ── API Models ───────────────────────────────────────────────────────

class TaskOut(BaseModel):
    id: int; board_id: int; group_id: Optional[int]
    title: str; description: Optional[str]
    status: str; priority: str; position: int
    due_date: Optional[datetime]; start_date: Optional[datetime]
    estimated_hours: Optional[float]; actual_hours: Optional[float]
    location_lat: Optional[float]; location_lng: Optional[float]
    address: Optional[str]; gis_layer_id: Optional[str]
    custom_fields: dict; is_archived: bool
    created_by: Optional[int]
    created_at: datetime; updated_at: datetime
    assignees: list = []
    subtask_count: int = 0
    comment_count: int = 0

class BoardOut(BaseModel):
    id: int; name: str; description: Optional[str]
    board_type: str; icon: str; color: str
    is_archived: bool
    department_name: Optional[str] = ""
    groups: list = []
    tasks: list = []
    task_count: int = 0

class DashboardOut(BaseModel):
    total_tasks: int
    tasks_by_status: dict
    tasks_by_priority: dict
    overdue_tasks: int
    citizen_requests_open: int
    permits_pending: int
    recent_activity: list = []

# ── API Routes ───────────────────────────────────────────────────────

# The tag of the container image this process was built from, stamped by the
# release pipeline. A deploy that only checks for HTTP 200 proves that
# *something* is answering, which is exactly what a container that never
# restarted also does — so the release goes green while the old code keeps
# serving. Echoing the tag turns "is it up" into "is it the build I just
# pushed". Unauthenticated on purpose: this is also the App Service health
# check path, and the platform's probe carries no identity. A build number is
# not a secret.
IMAGE_TAG = os.environ.get("MISSIONS_IMAGE_TAG") or "dev"


@app.get("/api/status")
def status(request: Request):
    # The SPA shows the local user picker only in dev mode, so this has to be
    # the mode THIS request is actually authenticated under — dev is honoured
    # only when the app is served locally. It exposes no user data.
    return {"status": "ok", "app": "CODE-CAL MISSIONS", "version": "0.1.0",
            "image_tag": IMAGE_TAG,
            "auth_mode": effective_auth_mode(request)}

@app.get("/api/dashboard")
def dashboard(user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        visible = _visible_board_ids(db, user_id)
        tasks = db.query(Task).filter(
            Task.is_archived == False, Task.board_id.in_(visible)
        ).all() if visible else []
        total = len(tasks)
        by_status = {}
        by_priority = {}
        overdue = 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for t in tasks:
            s = t.status.value if hasattr(t.status, 'value') else t.status
            p = t.priority.value if hasattr(t.priority, 'value') else t.priority
            by_status[s] = by_status.get(s, 0) + 1
            by_priority[p] = by_priority.get(p, 0) + 1
            due = t.due_date
            if due and hasattr(due, 'tzinfo') and due.tzinfo:
                due = due.replace(tzinfo=None)
            if due and due < now and s not in ("done", "cancelled"):
                overdue += 1
        citizen_open = db.query(CitizenRequest).filter(
            CitizenRequest.status.in_(["new", "assigned", "in_progress"])
        ).count()
        permits_pending = db.query(Permit).filter(
            Permit.status.in_(["draft", "submitted", "in_review"])
        ).count()
        return {
            "total_tasks": total,
            "tasks_by_status": by_status,
            "tasks_by_priority": by_priority,
            "overdue_tasks": overdue,
            "citizen_requests_open": citizen_open,
            "permits_pending": permits_pending,
            "recent_activity": [],
        }

# Views a board can expose. "table" is always present and cannot be removed.
ALL_VIEWS = ["table", "kanban", "gantt", "dashboard", "ceo", "calendar", "map", "gis"]

def _board_views(b):
    """Enabled views for a board. New boards start with only the main table;
    older/seeded boards (no explicit setting) keep all views for compatibility."""
    s = b.settings or {}
    v = s.get("views")
    if not v:
        return list(ALL_VIEWS)
    # always keep table first and present
    out = ["table"] + [x for x in v if x in ALL_VIEWS and x != "table"]
    return out

# Per-board status vocabulary. Each entry is {key,label,color} where `key` is one
# of the underlying TaskStatus values. Keeping the enum key under the hood means
# the automations, the parent roll-up, the kanban and the charts keep working
# (they all key off task.status) while a board admin may rename/recolor/reorder the statuses
# and expose only the ones the board actually uses.
# The vocabulary a board starts with. Colours come from the status palette, and
# "טרם הוגדר" is not here: it is the state of an item nobody has set, carried as
# custom_fields.status_unset, so listing it would make "not chosen" a choice.
#
# `base` is the engine value the status behaves as — what the automations, the
# kanban and the charts read. Two entries may share one: תקוע and הקפאה are
# different words for an item that is not moving, and both park it in on_hold.
# An entry whose key is not itself an engine value must use the x_ prefix, or
# _norm_board_status drops it the first time an admin saves the list.
STATUS_DEFAULTS = [
    {"key": "done",        "label": "בוצע",   "color": "#1AC877"},
    {"key": "in_progress", "label": "בטיפול", "color": "#FBAA47"},
    {"key": "on_hold",     "label": "תקוע",   "color": "#DB2D4C"},
    {"key": "x_frozen",    "label": "הקפאה",  "color": "#FD5AC3", "base": "on_hold"},
    {"key": "cancelled",   "label": "בוטל",   "color": "#9BADBC"},
]
# What the ENGINE understands, which is the TaskStatus enum — not whatever the
# default vocabulary happens to offer. These were the same set until the
# defaults stopped covering every enum value; deriving this from the defaults
# would have made backlog, todo and review invalid keys overnight and dropped
# them from every board that had saved one.
_STATUS_KEYS = {s.value for s in TaskStatus}

def _valid_hex(c):
    c = str(c or "")
    if len(c) == 7 and c[0] == "#":
        try:
            int(c[1:], 16); return True
        except ValueError:
            return False
    return False

# A custom "status" column carries its own vocabulary — the board admin names and
# colours the labels of every such column separately (the built-in status column
# has its own, board-wide list above). Stored on the column as
def _number_col_cfg(raw):
    """How a number column is shown: a unit beside the figure, and whether the
    thousands are grouped. Or None, which is a plain number.

    Presentation only — the cell stores a number and goes on storing one, so
    sorting, formulas and the Excel export are untouched by anything set here,
    and the unit can be changed as often as anyone likes without rewriting a
    single cell. Stored as nothing when it says nothing, so a board that never
    opened the screen does not carry the defaults around.
    """
    if not isinstance(raw, dict):
        return None
    unit = str(raw.get("unit") or "").strip()[:6]
    thousands = bool(raw.get("thousands"))
    return {"unit": unit, "thousands": thousands} if (unit or thousands) else None


# options=[{label,color}]; an empty/absent list means "use the client defaults".
STATUS_COL_MAX = 30

def _status_col_options(raw):
    """Normalise a status column's own vocabulary, or None when unset.

    Each option carries a stable id. A cell stores that id, so renaming or
    recolouring the option is a change in one place that every cell already
    referencing it picks up — no rewriting of item data, and nothing to go
    stale if a rewrite were to fail halfway.
    """
    if not isinstance(raw, list):
        return None
    out, seen, ids = [], set(), set()
    for it in raw:
        if isinstance(it, str):
            it = {"label": it}
        if not isinstance(it, dict):
            continue
        label = (str(it.get("label") or "").strip())[:40]
        if not label or label in seen:
            continue
        seen.add(label)
        oid = str(it.get("id") or "").strip()
        if not oid or oid in ids:
            oid = "o_" + uuid.uuid4().hex[:8]
        ids.add(oid)
        out.append({"id": oid, "label": label,
                    "color": it.get("color") if _valid_hex(it.get("color")) else "#c4c4c4"})
        if len(out) >= STATUS_COL_MAX:
            break
    return out or None

# A board may define up to this many statuses. Only seven of them can be a
# TaskStatus value — the ones the engine keys off for automation conditions,
# kanban columns and charts. Any status beyond those seven is a board-defined label
# that *behaves as* one of the seven (its `base`): the item stores the base in
# task.status so all of that keeps working, and carries the chosen label and
# colour in custom_fields, which is what the grid renders.
BOARD_STATUS_MAX = 30

def _norm_board_status(it, seen):
    """One validated {key,label,color,base} entry, or None to skip it."""
    if not isinstance(it, dict):
        return None
    key = str(it.get("key") or "").strip()
    label = (str(it.get("label") or "").strip())[:40]
    if key in _STATUS_KEYS:                       # one of the seven built-ins
        base = key
    elif not key or key.startswith("x_"):          # a board-defined status
        # no key means "newly added" — the server mints it. An arbitrary
        # unknown key is still a client mistake and is dropped, as before.
        base = it.get("base") if it.get("base") in _STATUS_KEYS else "in_progress"
        key = key or ("x_" + uuid.uuid4().hex[:8])
    else:
        return None
    if not label:
        label = key
    if key in seen:
        return None
    seen.add(key)
    color = it.get("color") if _valid_hex(it.get("color")) else "#c4c4c4"
    return {"key": key, "label": label, "color": color, "base": base}

def _board_statuses(b):
    """The board's ordered status list (defaults when the admin hasn't customised)."""
    raw = (b.settings or {}).get("statuses")
    if not raw:
        return [dict(x, base=x.get("base", x["key"])) for x in STATUS_DEFAULTS]
    out, seen = [], set()
    for it in raw:
        e = _norm_board_status(it, seen)
        if e:
            out.append(e)
        if len(out) >= BOARD_STATUS_MAX:
            break
    return out or [dict(x, base=x.get("base", x["key"])) for x in STATUS_DEFAULTS]

# ── Priority is a status column too ──────────────────────────────────────
# "עדיפות" is the same kind of thing as "סטטוס": one value out of a named,
# coloured vocabulary. So it gets the same treatment — a board admin renames,
# recolours, reorders, adds and removes its values, up to BOARD_PRIORITY_MAX,
# exactly as with the statuses above. Five of them can be a Priority enum value
# (what sorting and the charts key off); anything beyond behaves as one of those
# five (its `base`), with the chosen label and colour carried on the item.
PRIORITY_DEFAULTS = [
    {"key": "low", "label": "נמוכה", "color": "#579bfc"},
    {"key": "medium", "label": "בינונית", "color": "#5559df"},
    {"key": "high", "label": "גבוהה", "color": "#fdab3d"},
    {"key": "critical", "label": "קריטית", "color": "#e2445c"},
    {"key": "emergency", "label": "חירום", "color": "#bb3354"},
]
_PRIORITY_KEYS = {p["key"] for p in PRIORITY_DEFAULTS}
BOARD_PRIORITY_MAX = 30

def _norm_board_priority(it, seen):
    """One validated {key,label,color,base} priority, or None to skip it."""
    if not isinstance(it, dict):
        return None
    key = str(it.get("key") or "").strip()
    label = (str(it.get("label") or "").strip())[:40]
    if key in _PRIORITY_KEYS:                      # one of the five built-ins
        base = key
    elif not key or key.startswith("x_"):           # a board-defined priority
        base = it.get("base") if it.get("base") in _PRIORITY_KEYS else "medium"
        key = key or ("x_" + uuid.uuid4().hex[:8])
    else:
        return None
    if not label:
        label = key
    if key in seen:
        return None
    seen.add(key)
    color = it.get("color") if _valid_hex(it.get("color")) else "#c4c4c4"
    return {"key": key, "label": label, "color": color, "base": base}

def _board_priorities(b):
    """The board's ordered priority list (defaults when it hasn't customised)."""
    raw = (b.settings or {}).get("priorities")
    if not raw:
        return [dict(x, base=x["key"]) for x in PRIORITY_DEFAULTS]
    out, seen = [], set()
    for it in raw:
        e = _norm_board_priority(it, seen)
        if e:
            out.append(e)
        if len(out) >= BOARD_PRIORITY_MAX:
            break
    return out or [dict(x, base=x["key"]) for x in PRIORITY_DEFAULTS]

def _resolve_priority(board, value):
    """Map a chosen priority key to (engine value, the fields the item carries).

    A board-defined priority is not a Priority enum value, so it is stored as its
    `base` with the chosen label and colour on the item — the same arrangement as
    a board-defined status. Returns (None, None) for a key this board does not
    know, so the caller can leave the priority alone rather than crash on it.
    """
    key = str(value or "").strip()
    if not key:
        return None, None
    cleared = {"priority_key": None, "priority_label": None,
               "priority_color": None, "priority_unset": None}
    if key in _PRIORITY_KEYS:
        return key, cleared
    e = next((p for p in _board_priorities(board) if p["key"] == key), None) if board else None
    if not e:
        return None, None
    return e["base"], {"priority_key": e["key"], "priority_label": e["label"],
                       "priority_color": e["color"], "priority_unset": None}

BOARD_VISIBILITY = ("private", "public")

def _board_visibility(b):
    """'private' — only people invited to the board — or 'public' — anyone who
    belongs to the board's environment.

    Unset reads as private, which is exactly how every board behaved before this
    setting existed. Boards that predate it therefore keep their audience, and
    nothing becomes visible to anyone because of an upgrade.
    """
    v = ((b.settings or {}).get("visibility") if b else None)
    return v if v in BOARD_VISIBILITY else "private"

# ── the recycle bin's one rule ────────────────────────────────────────
# A deleted item is invisible to every query in the application, including the
# ones that load it through a relationship (board.tasks, task.subtasks).
#
# This is a single event hook rather than a filter added to each query on
# purpose: there are ~50 places that read Task, and the failure mode of missing
# one is a deleted item still showing on a board — silent, and exactly the bug
# the feature exists to prevent. One rule cannot be forgotten.
#
# The bin itself, restore and permanent delete opt out with
# .execution_options(include_deleted=True); they are the only code that should.
@event.listens_for(Session, "do_orm_execute")
def _hide_deleted_tasks(state):
    if state.is_select and not state.execution_options.get("include_deleted", False):
        state.statement = state.statement.options(
            with_loader_criteria(Task, lambda cls: cls.deleted_at.is_(None), include_aliases=True)
        )


def _board_role(db, board_id, user_id):
    """Board-scoped role (admin/editor/viewer) for a user, or None if no access."""
    if user_id is None:
        return None
    m = db.query(BoardMember).filter(BoardMember.board_id == board_id,
                                     BoardMember.user_id == user_id).first()
    if m:
        return m.role
    # system (workspace) admins have admin access to every board, even ones
    # they were never explicitly added to
    if _ws_role(db, user_id) == "admin":
        return "admin"
    # A public board is readable by everyone in its environment, with no invite.
    # Deliberately 'viewer': being able to see a board is not permission to
    # change it, so contributing still requires being invited. An explicit
    # BoardMember row wins, above, so inviting someone to a public board as an
    # editor still upgrades them.
    b = db.query(Board).filter(Board.id == board_id).first()
    if (b is not None and b.deleted_at is None and _board_visibility(b) == "public"
            and _env_role(db, b.environment_id, user_id) is not None):
        return "viewer"
    return None

def _is_board_admin(db, board_id, user_id):
    return _board_role(db, board_id, user_id) == "admin"

def _account_blocked(db, user_id):
    """Is this a deactivated account?

    A blocked user stays in the directory — their name is on everything they
    ever did, and the history has to keep reading correctly — but they are not
    a colleague any more: nobody may invite them, tag them, mention them or
    name them in a rule. "Deactivated" is the end of participation, not a
    cosmetic flag on a user who still turns up in every picker.

    Only an explicit False blocks. The column was added to databases that
    already had users, so NULL means "nobody ever deactivated this one".
    """
    if user_id is None:
        return False
    return bool(db.query(User.id)
                  .filter(User.id == user_id, User.is_active.is_(False)).first())

def _can_be_assigned(db, board_id, user_id):
    """May this user be tagged on this board's items? Only people INVITED to it.

    Deliberately not `_board_role`, which a public board satisfies for everyone
    in the environment. Being able to read a board is not the same as being part
    of the work on it: on a busy public board, "everyone in the environment"
    would turn every people column and every @-menu into a directory of hundreds,
    and would let anyone put a colleague's name on an item they never agreed to
    own. Tagging follows the invitation, not the audience.

    Workspace admins stay taggable — they reach every board without an explicit
    invite, and excluding them would make it impossible to tag the very people
    who administer the system. A *blocked* workspace admin is not an exception
    to that: deactivation outranks every role.

    This is the one gate for naming a person — people columns, the assignee
    circles, @-mentions and the person field of an automation all come through
    here — so a deactivated account answered here is refused everywhere at once.
    """
    if user_id is None:
        return False
    if _account_blocked(db, user_id):
        return False
    m = db.query(BoardMember).filter(BoardMember.board_id == board_id,
                                     BoardMember.user_id == user_id).first()
    if m:
        return True
    return _ws_role(db, user_id) == "admin"

def _not_taggable_reason(db, board_id, user_id):
    """Why this person may not be named on this board, in words — "" if they may.

    Two different refusals used to read as one: a deactivated member was told
    they were "not a member of the board", which they are, which sent whoever
    read it looking at the board's invitations for a problem that is on the
    user's account.
    """
    if _account_blocked(db, user_id):
        return "חשבונו מושבת"
    if not _can_be_assigned(db, board_id, user_id):
        return "אינו חבר בלוח"
    return ""

def _filter_people_values(db, board_id, cf, before):
    """Drop non-members from people-column values in `cf` (in place).
    Only *newly added* ids are rejected: ids already stored on the item survive so
    that items tagged before this rule stay editable and can be cleaned up by
    hand, instead of a legacy value making the whole cell impossible to save."""
    board = db.query(Board).filter(Board.id == board_id).first()
    cols = {c["id"]: c for c in ((board.settings or {}).get("columns", []) if board else [])}
    for key, val in list(cf.items()):
        if not isinstance(val, list):
            continue
        col = cols.get(key)
        if not col or col.get("type") != "people":
            continue
        kept = [c for c in (before or {}).get(key, []) if c in val]   # preserved, order-safe
        # An imported name with no account here is a string, not an id: a record
        # of who was on the item in monday. It is no one's assignment, so the
        # membership rule has nothing to say about it — and handing it to
        # _can_be_assigned would compare text to an integer column, which
        # Postgres refuses outright.
        cf[key] = [uid for uid in val
                   if not isinstance(uid, int) or uid in kept
                   or _can_be_assigned(db, board_id, uid)]

_BROLE_ORDER = {"viewer": 0, "editor": 1, "admin": 2}
def _require_board_edit(db, board_id, actor, need="editor", msg=None):
    """Enforce board-level write permission (closes IDOR on board mutations).
    The actor must be a board member whose role meets `need` (editor|admin).

    This used to return silently when `actor` was None, which meant dropping the
    parameter skipped the check entirely. Identity now comes from the transport,
    so None means unauthenticated and must be refused.

    `msg` names what was refused. The default reads "you may not change this
    board", which is true of a viewer but a lie to an editor asking for
    something only an admin may do — they change the board all day. A caller
    asking for more than editor should say what it is asking for."""
    if actor is None:
        raise HTTPException(401, "נדרשת התחברות")
    role = _board_role(db, board_id, actor)
    if role is None or _BROLE_ORDER.get(role, -1) < _BROLE_ORDER.get(need, 1):
        raise HTTPException(403, msg or "אין לך הרשאה לשנות לוח זה")

def _visible_board_ids(db, user_id):
    """Set of board IDs a user is allowed to see (membership-based).
    Mirrors /api/boards visibility so aggregate views (dashboard, CEO,
    insights) never leak boards the user was not invited to.
    An unauthenticated caller (user_id=None) sees nothing — this used to return
    every board, so omitting the parameter exposed the whole workspace."""
    live = db.query(Board).filter(Board.is_archived == False, Board.deleted_at == None).all()
    all_ids = {b.id for b in live}
    if user_id is None:
        return set()
    if _ws_role(db, user_id) == "admin":   # system admins see every board
        return all_ids
    member_ids = {m.board_id for m in db.query(BoardMember).filter(BoardMember.user_id == user_id).all()}
    # plus every public board in an environment this user belongs to — the
    # primary workspace included, which is why a board kept private there stays
    # private: visibility inside it is the board's own, like anywhere else
    env_ids = _user_env_ids(db, user_id)
    public_ids = {b.id for b in live
                  if b.environment_id in env_ids and _board_visibility(b) == "public"}
    return {i for i in all_ids if i in member_ids or i in public_ids}

def _primary_env_id(db):
    e = db.query(Environment).filter(Environment.is_primary == True).first()   # noqa: E712
    return e.id if e else None

def _user_env_ids(db, user_id):
    """The environments a user is in: the ones granted to them, plus the primary.

    The primary workspace is where everybody meets, so belonging to it is not a
    row anyone has to be given — it is what being a user means. A row-per-user
    grant was the same thing until the first person was created after it ran,
    and then it quietly was not.

    This says nothing about which BOARDS they see inside it. A board in the
    primary workspace is seen exactly as a board anywhere else is: public to the
    workspace, or by invitation — see _visible_board_ids."""
    if user_id is None:
        return set()
    ids = {m.environment_id for m in
           db.query(EnvironmentMember).filter(EnvironmentMember.user_id == user_id).all()}
    pid = _primary_env_id(db)
    if pid is not None:
        ids.add(pid)
    return ids

def _ws_role(db, user_id):
    if user_id is None:
        return None
    m = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).first()
    return m.role if m else None

# ── Multi-level permission model (סביבה → לוח → פריט → עמודה) ────────
def _board_caps(role):
    """Capabilities implied by a board role."""
    return {
        "admin":  {"view", "edit", "delete", "manage"},
        "editor": {"view", "edit"},
        "viewer": {"view"},
    }.get(role, set())

def _item_perm(task, user_id, board_role):
    """Effective permission on a specific item: none|view|edit|delete.
    A per-user item override wins over the board role."""
    ov = (task.permissions or {}).get(str(user_id))
    if ov in ("none", "view", "edit", "delete"):
        return ov
    caps = _board_caps(board_role)
    return "delete" if "delete" in caps else ("edit" if "edit" in caps else ("view" if "view" in caps else "none"))

def _link_states(db, ids, user_id):
    """What each linked id is, from `user_id`'s point of view:

      "live"       — a normal item they may see
      "deleted"    — the item is in the recycle bin, and they may see it
      "deleted_board" — the item is fine, but its whole board is in the bin
      None         — not theirs to know about, or gone for good

    "deleted" is deliberately its own answer rather than folded into None. This
    system's deletion policy is a recycle bin: the item can come back, and the
    relationship row is kept so that it comes back with it. A cell that quietly
    dropped the link would give no hint that anything was pending, and the link
    would then reappear out of nowhere on a restore. It is marked instead.

    Purged items are None: there is nothing to restore and nothing to mark, and
    _drop_links_for_tasks has already removed the rows anyway.

    A board in the bin makes its items unavailable even though the items
    themselves were never deleted — the board comes back with them, so this is
    the same "marked, not dropped" answer, told apart only so the cell can say
    where the thing actually went.

    Cached on the session — one board role and one Task row per id per request,
    however many cells point at the same linked item.
    """
    ids = [i for i in (ids or []) if isinstance(i, int)]
    if not ids:
        return {}
    seen = db.info.setdefault(("_link_state", user_id), {})
    roles = db.info.setdefault(("_brole", user_id), {})
    boards = db.info.setdefault("_board_state", {})     # not user-specific
    unknown = [i for i in set(ids) if i not in seen]
    if unknown:
        # explicitly including binned items: the global soft-delete hook would
        # otherwise make them indistinguishable from ids that never existed
        found = {t.id: t for t in db.query(Task).filter(Task.id.in_(unknown))
                 .execution_options(include_deleted=True).all()}
        for i in unknown:
            t = found.get(i)
            if t is None:
                seen[i] = None
                continue
            if t.board_id not in boards:
                bd = db.query(Board).filter(Board.id == t.board_id).first()
                boards[t.board_id] = ("missing" if bd is None else
                                      "bin" if bd.deleted_at is not None else "live")
            if boards[t.board_id] == "missing":
                seen[i] = None            # nothing to restore, nothing to mark
                continue
            # Deliberately not `is_archived`: archiving is housekeeping, not a
            # permission, and treating it as one would relabel an archived item
            # as something the viewer may not see.
            state = ("deleted" if t.deleted_at is not None else
                     "deleted_board" if boards[t.board_id] == "bin" else "live")
            if user_id is None:            # internal caller, nobody to filter for
                seen[i] = state
                continue
            if t.board_id not in roles:
                roles[t.board_id] = _board_role(db, t.board_id, user_id)
            r = roles[t.board_id]
            seen[i] = state if (r is not None and _item_perm(t, user_id, r) != "none") else None
    return {i: seen.get(i) for i in ids}


def _require_task_view(db, task_id, actor):
    """The task, if `actor` may see it. 403/404 otherwise.

    A connect column hands out item ids by design, and an id was enough to read
    an item's conversation, its files and its whole history — including its
    title — on a board the caller was never invited to. Seeing a link is not
    permission to open what it points at, and that has to be enforced on every
    door into the item, not only on GET /api/tasks/{id}.
    """
    t = db.query(Task).filter(Task.id == task_id).first()
    if not t:
        raise HTTPException(404, "task not found")
    board = db.query(Board).filter(Board.id == t.board_id).first()
    if not board or board.deleted_at:
        raise HTTPException(404, "task not found")
    if actor is not None:
        role = _board_role(db, t.board_id, actor)
        if role is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        if _item_perm(t, actor, role) == "none":
            raise HTTPException(403, "אין לך גישה לפריט זה")
    return t


def _visible_link_ids(db, ids, user_id):
    """Of these item ids, the ones `user_id` may see — live or waiting in the bin.

    A connect cell holds ids of items on OTHER boards, so the viewer's access to
    the board they are reading says nothing about their access to the other end.
    Everything the connect column shows, offers or resolves goes through here.

    `user_id=None` means an internal caller with no viewer to filter for (the
    serializer's own default), and is left alone.
    """
    if user_id is None:
        return list(ids or [])
    state = _link_states(db, ids, user_id)
    return [i for i in (ids or []) if isinstance(i, int) and state.get(i)]


def _hidden_link_ids(db, ids, user_id):
    """The complement of _visible_link_ids, in the original order."""
    vis = set(_visible_link_ids(db, ids, user_id))
    return [i for i in (ids or []) if isinstance(i, int) and i not in vis]


# ── system limits on linking ───────────────────────────────────────────────
# Both are guardrails, not product opinions: a board with dozens of connect
# columns is unreadable, and a cell holding thousands of links is a page that
# never finishes rendering. Env-driven so a deployment can move them.
def _max_connect_cols():
    try:
        return max(1, int(os.getenv("CITYOS_MAX_CONNECT_COLS", "10")))
    except ValueError:
        return 10


def _max_links_per_cell():
    try:
        return max(1, int(os.getenv("CITYOS_MAX_LINKS_PER_CELL", "100")))
    except ValueError:
        return 100


def _is_multi(col):
    """Does this connect column hold more than one item? Default yes, matching
    the picker, which treats anything but an explicit false as multiple."""
    return _connect_cfg(col).get("multiple") is not False


# What to tell someone whose link did not take. The rules do the refusing; this
# only explains it, so it runs on the write path where an extra query is free.
LINK_REJECT_HE = {
    "missing":           "הפריט שנבחר אינו קיים עוד",
    "deleted":           "הפריט שנבחר נמחק במהלך הפעולה",
    "board_unavailable": "לוח היעד אינו זמין — הוא נמצא בסל המחזור",
    "forbidden":         "אין לך עוד הרשאת צפייה בפריט שנבחר",
    "no_mirror":         "אין בלוח היעד עמודה שבה יוצג הקשר ההפוך",
    "limit":             "הגעת למספר הקישורים המרבי בתא זה",
    "rejected":          "לא ניתן היה לשמור את הקישור",
}


def _link_reject_reason(db, tid, user_id):
    """Why this id cannot be linked right now — for the message, not the rule."""
    t = (db.query(Task).filter(Task.id == tid)
         .execution_options(include_deleted=True).first())
    if t is None:
        return "missing"
    b = (db.query(Board).filter(Board.id == t.board_id)
         .execution_options(include_deleted=True).first())
    if b is None:
        return "missing"
    if b.deleted_at is not None:
        return "board_unavailable"
    if t.deleted_at is not None:
        return "deleted"
    if user_id is not None:
        role = _board_role(db, t.board_id, user_id)
        if role is None or _item_perm(t, user_id, role) == "none":
            return "forbidden"
    return "rejected"


def _merge_link_ids(db, submitted, current, user_id, multiple=True, report=None):
    """What a connect cell should hold after `user_id` saved `submitted`.

    Two rules, and they are the same rule from both ends. A user cannot ADD a
    link to an item they cannot see — otherwise the picker's restrictions could
    be walked around by posting an id, and the mirror would plant a row on a
    board they have no access to. And a user cannot REMOVE a link they cannot
    see: their cell was rendered without those ids, so submitting the list they
    can see must not read as "delete the rest".

    `multiple` is the column's own cardinality, and it is enforced here rather
    than only in the picker: the UI cleared the selection before saving, so the
    API never had to, and a single-link column would accept a list of any
    length from anything that was not the picker.
    """
    asked = [int(x) for x in (submitted or []) if isinstance(x, (int, str)) and str(x).lstrip("-").isdigit()]
    asked = list(dict.fromkeys(asked))        # the same item twice in one cell is one link
    # An item in the bin can be kept where the link already existed — that is
    # what makes a restore put the relationship back — but it cannot be linked
    # to for the first time. The picker never offers one; this is the API side
    # of the same rule.
    state = _link_states(db, asked, user_id) if user_id is not None else {}
    was = set(current or [])
    keep = [i for i in _visible_link_ids(db, asked, user_id)
            if user_id is None or state.get(i) == "live" or i in was]
    hidden = _hidden_link_ids(db, current or [], user_id)
    if not multiple:
        # A single-link column is the one place the "never delete what you
        # cannot see" rule has to give way: the cell holds one item, and
        # keeping an unseen one alongside a chosen one would hold two. Choosing
        # a value in a single-value cell IS a replacement, so the pick wins;
        # choosing nothing still leaves whatever was there untouched.
        out = keep[-1:] if keep else hidden[:1]
        if report is not None:
            got = set(out)
            for i in asked:
                if i not in got:
                    report.append({"item_id": i, "reason": _link_reject_reason(db, i, user_id)})
        return out
    # Capped rather than refused: hidden links are carried over regardless of
    # what was submitted, so a hard limit could leave a cell that is already
    # over it impossible to edit at all. The picker stops a person well before
    # this; this is the backstop for everything that is not the picker.
    out = (keep + [i for i in hidden if i not in keep])
    capped = out[:_max_links_per_cell()]
    if report is not None:
        got = set(capped)
        for i in asked:
            if i in got:
                continue
            report.append({"item_id": i,
                           "reason": "limit" if i in out else _link_reject_reason(db, i, user_id)})
    return capped


def _col_perm(col, user_id, board_role):
    """Effective permission on a column for a user: none|view|edit."""
    ov = (col.get("perms") or {}).get(str(user_id))
    if ov in ("none", "view", "edit"):
        return ov
    caps = _board_caps(board_role)
    return "edit" if "edit" in caps else ("view" if "view" in caps else "none")

def _filter_columns(b, user_id, role, known=None, fields=None):
    """(known, fields) — every filterable column on the board, and the subset
    this reader may ask about.

    One place, because two of them disagreeing is a leak rather than a bug: the
    query endpoint decides what a filter is allowed to run, and the view layer
    decides whether a SAVED filter may be opened at all. If the second were
    more generous than the first, a view would open and then answer nothing;
    if it were stricter, a cut somebody can run by hand would be refused as a
    tab. They are the same question and this is the one answer.
    """
    known = {} if known is None else known
    fields = {} if fields is None else fields
    for c in ((b.settings or {}).get("columns") or []):
        kind = filter_ast.KINDS.get(c.get("type"))
        if not kind:
            continue
        cid = str(c.get("id"))
        known[cid] = kind
        if user_id is None or _col_perm(c, user_id, role) != "none":
            fields[cid] = kind
    return known, fields


def _unseen_col_ids(b, user_id, role):
    """Column ids on this board that this reader may not see at all."""
    if user_id is None:
        return set()
    return {str(c.get("id")) for c in ((b.settings or {}).get("columns") or [])
            if _col_perm(c, user_id, role) == "none"}


@app.get("/api/boards")
def list_boards(user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        boards = db.query(Board).filter(Board.is_archived == False, Board.deleted_at == None).order_by(
            Board.position, Board.id).all()
        # system (workspace) admins see every board; everyone else only the boards
        # they were invited to (membership-based visibility)
        if user_id is not None and _ws_role(db, user_id) != "admin":
            visible = _visible_board_ids(db, user_id)   # membership + public boards
            boards = [b for b in boards if b.id in visible]
        result = []
        for b in boards:
            task_count = db.query(Task).filter(Task.board_id == b.id, Task.parent_id == None).count()
            dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
            groups = db.query(Group).filter(Group.board_id == b.id).order_by(Group.position).all()
            result.append({
                "id": b.id, "name": b.name, "description": b.description,
                "board_type": b.board_type.value if hasattr(b.board_type, 'value') else b.board_type,
                "icon": b.icon, "color": b.color,
                "is_archived": b.is_archived,
                "department_name": dept_name,
                "environment_id": b.environment_id,
                "folder_id": b.folder_id,
                "position": b.position or 0,
                "task_count": task_count,
                "visibility": _board_visibility(b),
                "my_role": _board_role(db, b.id, user_id) if user_id is not None else None,
                "can_manage_env": _can_manage_env(db, b.environment_id, user_id) if user_id is not None else False,
                "groups": [{"id": g.id, "name": g.name, "position": g.position, "color": g.color, "task_status": g.task_status.value if hasattr(g.task_status, 'value') else g.task_status} for g in groups],
            })
        return result

# ── "מזהה פריט" (item id column) ─────────────────────────────────────
# A purely technical identifier: 11 digits, generated automatically, unique
# inside its board, with no prefix and no business meaning. It cannot be edited
# by hand. Sub-items are issued one by the same logic. Because the identifier is
# tied to the board it was minted for, an item that lands in another board (and
# later comes back) is issued a new one rather than keeping the old number.
ITEM_UID_MIN = 10_000_000_000     # smallest 11-digit number
ITEM_UID_MAX = 99_999_999_999

def _new_item_uid(db, board_id):
    for _ in range(60):
        cand = str(secrets.randbelow(ITEM_UID_MAX - ITEM_UID_MIN + 1) + ITEM_UID_MIN)
        taken = db.query(Task.id).filter(Task.board_id == board_id, Task.item_uid == cand).first()
        if not taken:
            return cand
    return str(secrets.randbelow(ITEM_UID_MAX - ITEM_UID_MIN + 1) + ITEM_UID_MIN)

def _board_name_from(typed, in_file, base):
    """Where an imported board's name came from.

    A board that arrives called "response1992g" is not named — it is named after
    whatever the browser happened to call the download, because the export did
    not carry the board's own name and the filename was the only thing left. The
    import is right to fall back to it; what it cannot do is leave that looking
    like the board's name. So the report says which of the three it was.
    """
    if (typed or "").strip():
        return "typed"
    if (in_file or "").strip():
        return "file"
    return "filename" if (base or "").strip() else "default"


def _mint_item_uids(n):
    """n identifiers, distinct from each other, minted without asking anything.

    For the rows of a board being created in this same transaction — there is
    nothing on it yet for them to collide with. A board that already holds items
    goes through _new_item_uid, which checks.
    """
    out, seen = [], set()
    while len(out) < n:
        c = str(secrets.randbelow(ITEM_UID_MAX - ITEM_UID_MIN + 1) + ITEM_UID_MIN)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

def _ensure_item_uid(db, task):
    """Give the task an identifier if it has none, or a fresh one if the one it
    carries was minted for a different board. Returns the identifier."""
    if task.item_uid and task.item_uid_board == task.board_id:
        return task.item_uid
    task.item_uid = _new_item_uid(db, task.board_id)
    task.item_uid_board = task.board_id
    return task.item_uid

def _board_has_item_id_col(board):
    return any(c.get("type") == "item_id" for c in ((board.settings or {}).get("columns") or []))

def _backfill_item_uids(db, board_id):
    """Every item and sub-item on the board gets an identifier — used when the
    column is added to a board that already holds items."""
    rows = db.query(Task).filter(Task.board_id == board_id).all()
    changed = False
    for t in rows:
        before = t.item_uid
        _ensure_item_uid(db, t)
        changed = changed or (t.item_uid != before)
    if changed:
        db.commit()

def _backfill_item_id_column():
    """Give every board the "מספר מזהה" column, not only the ones created since
    it became one of the defaults.

    A board created before it shipped simply does not have it, which is why the
    column shows up on QA — where boards are made all the time — and not on a
    production board that has been there for months. The identifier itself is
    not new to those items: it is minted the first time a board carrying the
    column is read (see the fetch below), so the column arrives already filled.

    Its own flag rather than a third entry in AUTO_COLS: every existing board
    already carries `auto_cols_v1`, so adding it there would reach new databases
    and skip every board this is for. Once per board, so an admin who removes
    the column does not find it back after the next restart.
    """
    with Session(engine) as db:
        added = 0
        for b in db.query(Board).all():
            s = dict(b.settings or {})
            if s.get("item_id_col_v1"):
                continue
            cols = [dict(c) for c in (s.get("columns") or [])]
            if not any(c.get("type") == "item_id" for c in cols):
                used = {c.get("id") for c in cols}
                cid = "sys_item_id" if "sys_item_id" not in used else ("col_" + uuid.uuid4().hex[:8])
                cols.append({"id": cid, "type": "item_id", "title": "מספר מזהה",
                             "options": None, "formula": None, "connect": None,
                             "copy_mode": None, "perms": {}})
                s["columns"] = cols
                added += 1
            s["item_id_col_v1"] = True
            b.settings = s
        db.commit()
        if added:
            print(f"↻ added the מספר מזהה column to {added} board(s)", flush=True)
_safe_startup(_backfill_item_id_column)


def _col_plan(db, columns, user_id, board_role):
    """The few columns that need work, worked out once for the whole board.

    Serializing an item walked every column three times: is it two-way, is it a
    connect, is it a mirror — and then again to find the ones this viewer may
    not see. None of those answers depends on the item, so on a board of 639
    items and 61 columns the same 39,000 questions were asked and answered per
    render. Here they are asked once and kept with the other per-request caches.
    """
    key = ("_col_plan", id(columns), user_id, board_role)
    plan = db.info.get(key)
    if plan is not None:
        return plan
    cols = columns or []
    plan = {
        "two_way": [c["id"] for c in cols if _is_two_way(c)],
        # EVERY connect column, two-way included: a two-way cell is filled from
        # the relationship rows above and then filtered here, in that order.
        # Excluding it from this list is how the first version of this leaked
        # links the viewer may not see — see tests/test_connect_revoked_access.py
        "connect": [c["id"] for c in cols if c.get("type") == "connect"],
        "mirror": [c for c in cols if c.get("type") == "mirror"],
        "hidden": ([c["id"] for c in cols if _col_perm(c, user_id, board_role) == "none"]
                   if user_id is not None else []),
    }
    db.info[key] = plan
    return plan


_PREFETCH_CHUNK = 400          # keep the IN (...) list inside every driver's limit


def _prefetch_items(db, tasks):
    """Answer, for a whole board at once, the four questions serializing an
    item used to ask one item at a time.

    _serialize_task needed an item's assignees, how many sub-items it has, how
    many comments, and the sub-items themselves. Each was its own query, so a
    board cost about ten statements per row — a board of four hundred items ran
    four thousand of them. In-process against SQLite that is invisible; against
    QA's Postgres every one is a network round trip, which is how opening a
    board came to take twenty seconds.

    Four grouped queries replace all of it. The answers go in the session's own
    info dict, the same place _prefetch_links keeps its cache, and
    _serialize_task reads them from there when they are present and falls back
    to its own query when they are not — so the write paths that serialize a
    single fresh item keep working untouched.

    Returns the sub-items it loaded, because the caller needs them for
    _prefetch_links and there is no reason to ask twice.
    """
    # `task_assignees` is an endpoint name in this module too, so the table is
    # imported under its own name here — same reason as in _purge_rows' caller
    from models import task_assignees as assignee_rows
    ids = [t.id for t in tasks]
    if not ids:
        return []
    info = db.info
    kids = info.setdefault("_kids_by", {})
    for tid in ids:
        kids.setdefault(tid, [])
    subs = []
    for part in [ids[i:i + _PREFETCH_CHUNK] for i in range(0, len(ids), _PREFETCH_CHUNK)]:
        for sub in (db.query(Task)
                      .filter(Task.parent_id.in_(part), Task.is_archived == False)   # noqa: E712
                      .order_by(Task.position).all()):
            kids.setdefault(sub.parent_id, []).append(sub)
            subs.append(sub)
    # a sub-item is serialized too, so it needs the same three answers
    every = ids + [s.id for s in subs]
    ass = info.setdefault("_assignees_by", {})
    nsub = info.setdefault("_nsub_by", {})
    ncom = info.setdefault("_ncom_by", {})
    for tid in every:
        ass.setdefault(tid, [])
        nsub.setdefault(tid, 0)
        ncom.setdefault(tid, 0)
    for part in [every[i:i + _PREFETCH_CHUNK] for i in range(0, len(every), _PREFETCH_CHUNK)]:
        for tid, uid, uname, uav in (db.query(assignee_rows.c.task_id, User.id,
                                              User.name, User.avatar_url)
                                       .join(User, User.id == assignee_rows.c.user_id)
                                       .filter(assignee_rows.c.task_id.in_(part))
                                       .order_by(assignee_rows.c.task_id,
                                                 assignee_rows.c.user_id).all()):
            ass[tid].append({"id": uid, "name": uname, "avatar_url": uav})
        # counts every child, archived ones included — which is what the badge
        # has always shown
        for pid, n in (db.query(Task.parent_id, func.count(Task.id))
                         .filter(Task.parent_id.in_(part))
                         .group_by(Task.parent_id).all()):
            nsub[pid] = n
        for tid, n in (db.query(Comment.task_id, func.count(Comment.id))
                         .filter(Comment.task_id.in_(part))
                         .group_by(Comment.task_id).all()):
            ncom[tid] = n
    return subs


def _serialize_task(t, db, with_subs=True, user_id=None, board_role=None, columns=None):
    # a board read warms these for every row at once (_prefetch_items); a write
    # path serializing one fresh item has nothing warmed and asks for itself
    _pre = db.info
    _ass = _pre.get("_assignees_by")
    if _ass is not None and t.id in _ass:
        assignees = list(_ass[t.id])
    else:
        assignees = [{"id": u.id, "name": u.name, "avatar_url": u.avatar_url} for u in t.assignees] if t.assignees else []
    _ns = _pre.get("_nsub_by")
    subtask_count = (_ns[t.id] if _ns is not None and t.id in _ns
                     else db.query(Task).filter(Task.parent_id == t.id).count())
    _nc = _pre.get("_ncom_by")
    comment_count = (_nc[t.id] if _nc is not None and t.id in _nc
                     else db.query(Comment).filter(Comment.task_id == t.id).count())
    my_perm = _item_perm(t, user_id, board_role) if user_id is not None else "delete"
    cf = dict(t.custom_fields or {})
    # Which columns need anything doing to them is a property of the board and
    # the viewer, not of the item — so it is worked out once (_col_plan) rather
    # than by walking every column on every row. On a board of 639 items and 61
    # columns that walk ran 39,000 times to find, usually, nothing at all.
    plan = _col_plan(db, columns, user_id, board_role)
    # A two-way connect cell is not stored on the item — it is the shared
    # relationship rows, read from whichever side wrote them. That is what makes
    # a link created on the other board appear here without anything copying it.
    for cid in plan["two_way"]:
        cf[cid] = _linked_ids(db, t.id, cid)
    # A connect cell is the one place a board hands out ids from OTHER
    # boards. Show the viewer only the links they could have opened anyway;
    # the rest are not theirs to know about, and _merge_link_ids puts them
    # back when this same viewer saves the cell.
    for cid in plan["connect"]:
        if isinstance(cf.get(cid), list):
            cf[cid] = _visible_link_ids(db, cf[cid], user_id)
    # A mirror field holds no data of its own — it is read through the
    # connect column each time, so it follows the source item with nothing
    # to keep in step. Anything stored under its id is stale and ignored.
    for c in plan["mirror"]:
        cf[c["id"]] = _mirror_cells(db, t, c, user_id, columns or [])
    # A column's permission depends on the column and on the viewer's role —
    # never on the item. It used to ride on every item anyway, which on a board
    # of 687 items and 29 columns was 20,000 repetitions of the same map and
    # over half the response. The board now states it once (see get_board); what
    # stays per item is the consequence: a value the viewer may not see is not
    # in the item at all. Which columns those are is in the plan.
    for cid in plan["hidden"]:
        cf.pop(cid, None)
    d = {
        "id": t.id, "board_id": t.board_id, "group_id": t.group_id,
        "parent_id": t.parent_id,
        "item_uid": t.item_uid,          # "מזהה פריט" — automatic, read-only
        "title": t.title, "description": t.description,
        "status": t.status.value if hasattr(t.status, 'value') else t.status,
        "priority": t.priority.value if hasattr(t.priority, 'value') else t.priority,
        "position": t.position, "due_date": t.due_date,
        "start_date": t.start_date,
        "estimated_hours": t.estimated_hours, "actual_hours": t.actual_hours,
        "location_lat": t.location_lat, "location_lng": t.location_lng,
        "address": t.address,
        "custom_fields": cf,
        "permissions": t.permissions or {},
        "my_perm": my_perm,
        "is_archived": t.is_archived,
        "created_by": t.created_by,
        "created_at": t.created_at, "updated_at": t.updated_at,
        "assignees": assignees,
        "subtask_count": subtask_count,
        "comment_count": comment_count,
    }
    if with_subs:
        _kids = _pre.get("_kids_by")
        subs = (_kids[t.id] if _kids is not None and t.id in _kids
                else db.query(Task).filter(Task.parent_id == t.id, Task.is_archived == False)
                        .order_by(Task.position).all())
        subs = [s for s in subs if user_id is None or _item_perm(s, user_id, board_role) != "none"]
        d["subtasks"] = [_serialize_task(s, db, with_subs=False, user_id=user_id, board_role=board_role, columns=columns) for s in subs]
    return d

def _context_shell(parent, kids, db, user_id=None, board_role=None, columns=None):
    """A parent this reader may not see, holding sub-items they may.

    Everything readable about the parent is left out on purpose — the title
    above all, which is usually the whole of what a row discloses. What remains
    is an id to hang the children on and the two flags that say what this row
    is, so the screen can draw a neutral wrapper instead of a work item.

    The children are serialised normally: they are theirs to read, and nothing
    about them implies anything about the parent beyond its existence, which
    the sub-item's own parent_id already states.
    """
    return {
        "id": parent.id, "board_id": parent.board_id, "group_id": parent.group_id,
        "parent_id": None,
        "title": "", "description": None,
        "status": None, "priority": None,
        "due_date": None, "start_date": None,
        "assignees": [], "custom_fields": {}, "permissions": {},
        "my_perm": "none", "is_archived": False,
        "created_by": None, "created_at": None, "updated_at": None,
        "item_uid": None, "comment_count": 0,
        "subtask_count": len(kids),
        "subtasks": [_serialize_task(k, db, with_subs=False, user_id=user_id,
                                     board_role=board_role, columns=columns)
                     for k in kids],
        # not a row that failed the filter, and not a row with values withheld:
        # a row that is only here to hold the ones below it
        "context_only": True,
        "restricted": True,
    }


def _json_default(o):
    """What json.dumps cannot do by itself, done the way FastAPI would.

    Returning a plain dict hands it to FastAPI, which walks the whole structure
    with jsonable_encoder and then dumps it. On a board of 639 items and 61
    columns — 39,000 cells — that walk is ten times the cost of dumping the
    same thing directly. It is a fixed multiple of the payload, so it is worst
    exactly on the boards that are already slowest.

    Bypassing it only helps if nothing on the wire changes, which is the one
    thing that matters here: a date written "2026-10-14 09:00:00" instead of
    "2026-10-14T09:00:00" would be a quiet break in every cell that parses one.
    test_board_json_is_byte_identical compares the two, byte for byte.
    """
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, (set, frozenset)):
        return list(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    raise TypeError(f"not JSON-serializable: {type(o).__name__}")


def _json(payload):
    """A response built here rather than by FastAPI — see _json_default."""
    return Response(json.dumps(payload, ensure_ascii=False, default=_json_default),
                    media_type="application/json")


# ── saved views (תצוגות שמורות) ────────────────────────────────────────
# A named cut of a board, shown as a tab at the top of it. "באגים דחופים
# פתוחים" is three filters somebody sets every morning; a view is that cut,
# kept.
#
# The permission model is two words, and the asymmetry in it is deliberate:
#
#   private — only its owner sees it. Somebody's own way of reading a board is
#             not a statement about the board, so it takes only the right to
#             look at the board to make one.
#   public  — everyone who may open the board sees it. It is a tab ON the
#             board, which makes creating one an edit to the board, and it
#             takes the rights of one.
#
# Editing and deleting follow the same line: the owner always, and a board
# admin for a public view — somebody has to be able to take down a tab whose
# author has left.
def _is_sys_admin(db, user_id):
    """A system administrator, as opposed to an administrator of one board."""
    if not user_id:
        return False
    u = db.query(User).filter(User.id == user_id).first()
    return bool(u and u.role == "admin")


# ── where a filter runs, and how much comes back at a time ─────────────
# Below the threshold the browser filters what it already holds: the answer
# is instant, no request is made, and on a board of a few hundred rows that
# is simply better. Above it the question goes to the server, which is the
# only side that can answer for rows the browser was never handed.
#
# The number is configuration, not a constant with an opinion: a board of
# 1,000 rows on a laptop is not the same board on a five-year-old phone, and
# whoever runs the deployment is the one who knows which they have.
FILTER_CLIENT_MAX = max(0, int(os.environ.get("FILTER_CLIENT_MAX", "1000") or 1000))
# What happens when a view filters by a column its reader may not see.
#
#   skip  (default) — the rule is not applied for them. They see MORE rows
#                     than the view's author meant, and learn nothing about
#                     the column. This is the safe direction, and the reason
#                     is the opposite of the intuitive one: APPLYING the rule
#                     is the leak. "Budget > 1,000,000", run for somebody who
#                     cannot see budgets, hands them the answer as a row set —
#                     they read the figures off which rows survived. Dropping
#                     the rule hands them nothing.
#   block           — the view refuses to open for them at all. No inference
#                     of any kind, including from the view's name; the cost
#                     is that a shared view stops working across permission
#                     tiers, which for most boards is the worse trade.
#
# Configuration, because this is a security policy and the people who set it
# are the ones who know what is on their boards.
FILTER_COLUMN_POLICY = (os.environ.get("FILTER_COLUMN_POLICY") or "skip").strip().lower()
if FILTER_COLUMN_POLICY not in ("skip", "block"):
    FILTER_COLUMN_POLICY = "skip"
# One page. A board of tens of thousands of rows must never arrive in one
# response — not because the server cannot build it, but because the browser
# cannot draw it, and the request blocks everything behind it while it tries.
QUERY_PAGE = 50
QUERY_PAGE_MAX = 200

VIEW_VIS = ("private", "public")

# ── names and limits ────────────────────────────────────────────────────
# Technical ceilings, not product rules — hence the environment variables.
# They are here so a board cannot be made unusable, not to express anything
# about how many cuts a department ought to keep.
VIEW_NAME_MAX = max(1, int(os.environ.get("VIEW_NAME_MAX", "80") or 80))
# Active views per BOARD, the main table counted as one of them. Per board and
# not per person: the strip is shared now, so one person filling it fills
# everybody's, and a limit counted per owner would not be a limit on the strip.
VIEW_MAX = max(2, int(os.environ.get("VIEW_MAX_PER_BOARD", "100") or 100))
# The fixed main table. It has no row of its own — it is the board — but it
# occupies a name on the strip, and a saved view answering to the same name
# would make the strip ambiguous in the one place a reader cannot afford it.
MAIN_VIEW_NAME = (os.environ.get("MAIN_VIEW_NAME") or "טבלה ראשית").strip()
# How long a deleted view can still be brought back. After it, the row stays
# where it is — this is a window on RESTORING, not a promise to erase — but the
# board log stops offering it, because an offer that fails is worse than none.
VIEW_RESTORE_DAYS = max(1, int(os.environ.get("VIEW_RESTORE_DAYS", "30") or 30))


def _view_name_key(name):
    """What makes two view names "the same".

    Ends trimmed, then casefolded: "Budget" and "budget " are one name. Hebrew
    has no case, so casefold leaves it exactly as typed and the rule costs it
    nothing — it is there for the English a municipality's boards are full of.
    casefold rather than lower because it folds the pairs lower() misses.
    """
    return (name or "").strip().casefold()


def _check_view_name(db, board_id, name, exclude_id=None):
    """The trimmed name, or an HTTPException saying why there isn't one."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "לתצוגה צריך שם")
    if len(name) > VIEW_NAME_MAX:
        # refused rather than trimmed: a silently shortened name is not the one
        # somebody typed, and it can collide with a view that already exists
        raise HTTPException(400, f"שם תצוגה עד {VIEW_NAME_MAX} תווים")
    key = _view_name_key(name)
    if key == _view_name_key(MAIN_VIEW_NAME):
        raise HTTPException(400, "השם הזה שייך לטבלה הראשית")
    q = (db.query(SavedView)
           .filter(SavedView.board_id == board_id, SavedView.deleted_at.is_(None)))
    if exclude_id is not None:
        q = q.filter(SavedView.id != exclude_id)
    if any(_view_name_key(v.name) == key for v in q.all()):
        raise HTTPException(400, "כבר יש תצוגה בשם הזה בלוח")
    return name


def _log_view(db, v, action, field=None, old=None, new=None, actor=None):
    """One line in the board's log for a change to a view.

    "לוג הלוח יתעד יצירה, עדכון משותף, שינוי שם, מחיקה, שחזור, נעילה והצמדה,
    עם מבצע וזמן ופרטי השינוי המורשים."

    Management events only. A temporary adjustment is explicitly NOT one —
    "התאמות זמניות אינן אירוע ניהול משותף" — and it could not be logged here
    anyway, because it never reaches the server. What distinguishes the two
    is exactly whether anybody else is affected.

    The details are deliberately small: what changed and from what to what,
    never the configuration itself. A cut can name a column somebody reading
    the log may not see, and a log is read by more people than a board.
    """
    db.add(AuditLog(entity_type="saved_view", entity_id=v.id, action=action,
                    field_name=field, old_value=old, new_value=new,
                    changed_by=actor))


def _commit_view(db, board_id, *, adding=True, log=None):
    """Commit a view write, with the two board-wide rules enforced for real.

    Both are read-then-write races on their own. Two people naming a view the
    same thing at the same moment both pass _check_view_name; two people
    creating the hundredth both pass _check_view_room. The checks stay — they
    are what produces a sentence somebody can act on — and this is what makes
    them true rather than usually true.

    The name is a partial unique index, so the database refuses the second
    write and the refusal is translated back into the same 400 the check would
    have given. The ceiling cannot be an index, so it is re-counted INSIDE the
    transaction and rolled back if the row that just landed put the board over.
    """
    try:
        if adding:
            # Inside the try, because this is where a duplicate name is
            # refused — a flush outside it raises past the translation and
            # the caller gets a 500 instead of the sentence.
            db.flush()
            live = (db.query(SavedView)
                      .filter(SavedView.board_id == board_id,
                              SavedView.deleted_at.is_(None)).count())
            if live > VIEW_MAX:
                db.rollback()
                raise HTTPException(400, f"יותר מדי תצוגות פעילות בלוח (מקסימום {VIEW_MAX})")
        # The log line is written only once the row it describes is real, and
        # in the same transaction as it: a log entry for a save that was
        # refused is worse than no entry at all.
        if log:
            log()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "כבר יש תצוגה בשם הזה בלוח")


def _check_view_room(db, board_id):
    """One more active view, main table included — or a refusal."""
    # The main table is one of these rows now, so it counts itself — the +1
    # that used to stand in for it would be counting it twice.
    live = (db.query(SavedView)
              .filter(SavedView.board_id == board_id,
                      SavedView.deleted_at.is_(None)).count())
    if live >= VIEW_MAX:
        raise HTTPException(400, f"יותר מדי תצוגות פעילות בלוח (מקסימום {VIEW_MAX})")


def _view_visible_to(v, user_id, role):
    """Who sees a view in the strip.

    This version has no private views: a saved table view is a tab on the
    board, and everyone who may open the board sees every one of them. What is
    still honoured is the rows written BEFORE that was decided — somebody's
    private cut is not republished to their colleagues by a deploy, so it stays
    theirs until they share it themselves. Nothing new is ever written private
    (see create_saved_view), so this clause empties out on its own.
    """
    return v.visibility == "public" or v.owner_id == user_id


def _may_write_locked(role):
    """נעילה: "רק בעל הלוח רשאי לשנות את הגדרותיה, לפתוח את נעילתה או למחוק אותה."

    So a lock does not freeze a view — it narrows who may touch it to the
    board's owner. Everyone else, the person who MADE the view included, may
    read it and copy it and may not write it: a cut a department works off is
    not a stray "שמור" away from being somebody else's cut, and whoever runs
    the board is the one who answers for what its tabs say.

    Locking is the owner's too, not only unlocking. A lock an editor could
    apply and then not undo would be a trap, and "רק בעל הלוח" reads the same
    at both ends of the switch. "בעל הלוח" is the board role and nothing else —
    see _may_edit_view on why this layer does not re-answer who an
    administrator is.
    """
    return role == "admin"


def _may_edit_view(v, user_id, role):
    """Who may rename or rewrite an UNLOCKED view. The lock is asked separately.

    The board's own roles answer it, not authorship: an editor may change any
    view on a board they edit, and a viewer may change none. A saved view is
    a tab on the board — part of how the board is set up — so the question is
    what somebody may do to this board, not who happened to press save first.

    `role` is the whole of the answer, deliberately. A system administrator
    reaches a board through _board_role like everybody else — it already
    returns "admin" for a workspace admin on every board — so there is nothing
    for this layer to add. An override of its own here would be a SECOND path
    to admin, reading a different row (User.role rather than the workspace
    membership _board_role goes through), and the two have drifted apart
    before: see _ws_role_for. Views are not the place to re-answer who an
    administrator is.

    Authorship counts for nothing here, and that is the rule rather than an
    omission: "היוצר משמש לתיעוד ואינו מכתיב הרשאות ניהול". owner_id says who
    made the view, which is worth recording and worth showing; it is not a
    claim on it. An earlier version let the author of a legacy private row
    keep it, which was the same mistake wearing a kinder face — the right
    answer for those rows is to share them, not to hand their author a
    permission the matrix does not give.
    """
    return role in ("admin", "editor")


def _view_blocked_for(b, v, user_id, role):
    """Does this saved cut ask about a column this reader may not see?

    If it does, the view is not opened for them and not copied by them. Not
    "run without that rule": a rule silently dropped from an "or" group shows
    the whole board, and a tab that answers a different question for different
    people is worse than one that opens for neither.

    Always blocking, whatever FILTER_COLUMN_POLICY says. That setting is about
    a filter somebody is building by hand, where the column picker never
    offered the column in the first place; this is a cut that was SAVED while
    somebody could see the column and is being opened by somebody who cannot.
    """
    if user_id is None:
        return False
    adv = (v.filters or {}).get("adv")
    if not adv:
        return False
    # The same two maps the query endpoint builds, from the same helper and
    # the same built-in base — see _filter_columns.
    base = {"title": "text", "status": "status", "priority": "status",
            "assignees": "people", "due": "date"}
    _known, fields = _filter_columns(b, user_id, role, dict(base), dict(base))
    try:
        _tree, gone = filter_ast.prune(filter_ast.parse(adv), fields)
    except filter_ast.BadFilter:
        return False          # a cut the server already refuses is its own error
    unseen = _unseen_col_ids(b, user_id, role)
    return any(str(f) in unseen for f in gone)


# What a saved configuration is made of, and nothing else.
#
# The spec gives this as a table of components: visible columns and their
# order, column widths, filters, sort. Everything else a person does to a
# board while looking at it — the search box, a collapsed group, the scroll
# position, which sub-items they opened — is theirs for as long as they are
# there and is not part of what anybody else opens.
#
# Written as what is KEPT rather than what is dropped, because the two fail in
# opposite directions. A list of things to strip lets anything new the client
# starts sending ride along into everybody's tab, silently, and the first
# anybody knows of it is a view that behaves differently for its author. A
# list of what is kept makes that a decision somebody has to make on purpose.
VIEW_CONFIG_KEYS = (
    "view",        # which base view the cut was taken of — table, for now
    "cols",        # visible columns, their order, their widths
    "adv",         # the condition tree
    "people", "status", "priority", "links",   # the toolbar's own filters
    "sort",
)


def _view_config(filters):
    """The shared part of what somebody is looking at.

    `q` is the one dropped by name in the spec — "טקסט חיפוש: לעולם אינו
    נשמר" — and it is also the clearest case of the rule above: a stored
    search is a tab that silently narrows the board for everybody who opens
    it, above a search box that looks empty.
    """
    if not isinstance(filters, dict):
        return filters
    return {k: v for k, v in filters.items() if k in VIEW_CONFIG_KEYS}


def _view_cut_allowed(b, filters, user_id, role):
    """Is this cut one the person saving it may ask for?

    The same validation duplicate does — "תנאי גישה והאימות זהים לאלה של
    שכפול" — and for the same reason: a filter naming a column somebody may
    not see is one they must not be able to run, and saving it as their own
    view would be exactly that with an extra step.
    """
    if user_id is None or not (filters or {}).get("adv"):
        return True
    base = {"title": "text", "status": "status", "priority": "status",
            "assignees": "people", "due": "date"}
    _known, fields = _filter_columns(b, user_id, role, dict(base), dict(base))
    try:
        _tree, gone = filter_ast.prune(filter_ast.parse(filters["adv"]), fields)
    except filter_ast.BadFilter:
        return True            # the parse error is reported on its own
    unseen = _unseen_col_ids(b, user_id, role)
    return not any(str(f) in unseen for f in gone)


def _view_needs_fix(b, v):
    """Does this cut ask about a column that no longer exists on the board?

    "אם עמודה נדרשת נמחקה, התצוגה תשוחזר במצב הדורש תיקון ולא תציג תוצאות
    חלקיות מטעות."

    The misleading part is specific, not vague. Dropping the dead rule and
    running the rest is identical to the author's intent inside an "and" group
    and its exact opposite inside an "or": a rule that is gone cannot make the
    group true, so one deleted column shows the WHOLE board — filter on, badge
    counting, nothing filtered. A reader has no way to tell that from a cut
    that genuinely matches everything.

    So the view says it needs fixing, and whoever can edit it decides what the
    rule should have been. Unlike a column somebody may not SEE, this is not a
    secret: the column is gone for everyone, so the state is reported to
    everyone and the name of the missing field may be shown.
    """
    f = v.filters or {}
    base = {"title": "text", "status": "status", "priority": "status",
            "assignees": "people", "due": "date"}
    known, _f = _filter_columns(b, None, None, dict(base), dict(base))
    missing = set()

    adv = f.get("adv")
    if adv:
        try:
            _tree, gone = filter_ast.prune(filter_ast.parse(adv), known)
            missing |= {str(x) for x in gone}
        except filter_ast.BadFilter:
            pass

    # A SORT naming a column that is gone is the same failure wearing different
    # clothes: the view opens, the rows come back in some order, and nothing on
    # the screen says the order it promised is not the order it gave. Falling
    # back to the board's own order silently is the "quietly wider results" of
    # the filter case — a wrong answer that looks like an answer.
    #
    # A plain DISPLAY column that was deleted is NOT here. Removing it from the
    # table is the whole of the right behaviour: nothing was promised about it
    # beyond being shown, and a view does not need fixing because a column it
    # used to show no longer exists.
    sort = str(f.get("sort") or "")
    if sort and sort not in ("due", "priority", "title") and sort not in known:
        missing.add(sort)
    return sorted(missing)


def _redact_view_cols(filters, unseen):
    """The view's table layout, minus the columns this reader may not see.

    "הגדרות שאינן ניתנות לצפייה לא יישלחו לדפדפן" — so a width, a position in
    the order or a place on the hidden list is removed before the view leaves
    the server. Each of those is a fact about a column, and the column itself
    is not this reader's to know about.
    """
    if not unseen or not isinstance(filters, dict):
        return filters
    cols = filters.get("cols")
    if not isinstance(cols, dict):
        return filters
    out = dict(cols)
    if isinstance(cols.get("order"), list):
        out["order"] = [c for c in cols["order"] if str(c) not in unseen]
    if isinstance(cols.get("hidden"), list):
        out["hidden"] = [c for c in cols["hidden"] if str(c) not in unseen]
    if isinstance(cols.get("widths"), dict):
        out["widths"] = {k: w for k, w in cols["widths"].items() if str(k) not in unseen}
    return dict(filters, cols=out)


def _merge_view_cols(incoming, stored, unseen):
    """What to store when somebody who sees only part of the table saves it.

    They were sent a layout with the columns they may not see taken out of it,
    so what comes back has no opinion about those columns — and writing it as
    given would delete their width, their place in the order and their entry on
    the hidden list. The reader did not ask for that and could not have known
    they were doing it.

    So the stored settings for unseen columns are put back: the order keeps
    them where they were relative to the columns around them, and the two maps
    simply keep their entries.
    """
    if not unseen:
        return incoming
    if not isinstance(incoming, dict):
        return incoming
    inc = incoming.get("cols")
    old = (stored or {}).get("cols")
    if not isinstance(inc, dict) or not isinstance(old, dict):
        return incoming
    out = dict(inc)
    if isinstance(inc.get("order"), list) and isinstance(old.get("order"), list):
        # walk the stored order, keeping unseen ids pinned to the neighbour they
        # followed; everything else takes the incoming order
        kept = [c for c in inc["order"] if str(c) not in unseen]
        rebuilt, at = [], 0
        for c in old["order"]:
            if str(c) in unseen:
                rebuilt.append(c)
            elif at < len(kept):
                rebuilt.append(kept[at]); at += 1
        rebuilt += kept[at:]
        for c in kept:
            if c not in rebuilt:
                rebuilt.append(c)
        out["order"] = rebuilt
    if isinstance(inc.get("hidden"), list) and isinstance(old.get("hidden"), list):
        out["hidden"] = list(inc["hidden"]) + [c for c in old["hidden"] if str(c) in unseen]
    if isinstance(inc.get("widths"), dict) and isinstance(old.get("widths"), dict):
        w = dict(inc["widths"])
        for k, val in old["widths"].items():
            if str(k) in unseen:
                w[k] = val
        out["widths"] = w
    return dict(incoming, cols=out)


def _view_json(v, db=None, names=None):
    return {"id": v.id, "board_id": v.board_id, "name": v.name,
            "kind": v.kind or "saved",
            "config_version": v.config_version or 1,
            "schema_version": v.schema_version or 1,
            "visibility": v.visibility, "owner_id": v.owner_id,
            "owner_name": (names or {}).get(v.owner_id, ""),
            "filters": v.filters or {}, "position": v.position or 0,
            "locked": bool(v.locked), "pinned": bool(v.pinned),
            # When the shared configuration last changed. A reader holding
            # temporary adjustments compares this with what they opened and
            # says "התצורה המשותפת השתנתה" rather than silently discarding
            # what they were in the middle of.
            "updated_at": v.updated_at.isoformat() if v.updated_at else None}


def _view_order_for(db, board_id, user_id):
    """One person's arrangement of this board's strip — a list of view ids."""
    if user_id is None:
        return []
    row = (db.query(BoardViewPrefs)
             .filter(BoardViewPrefs.board_id == board_id,
                     BoardViewPrefs.user_id == user_id).first())
    return [int(i) for i in (row.order or [])] if row else []


def _arrange_views(rows, personal):
    """The order the strip is drawn in — two blocks, arranged by two people.

    Pinned views come first, in the order the BOARD puts them in. Both halves
    of that are the board owner's: which views are pinned, and how the pinned
    ones sit relative to each other. A reader's own arrangement does not reach
    into them — "סדר אישי לתצוגות שאינן מוצמדות" is exactly that boundary, and
    a pinned view that could be shuffled personally would make pinning mean
    nothing on the screen it was meant to control.

    Everything else follows, in the reader's own order. Views they have not
    arranged keep the board's order after the ones they have, which is where a
    view created since they last arranged their strip lands: at the end,
    disturbing nothing.
    """
    rank = {vid: i for i, vid in enumerate(personal)}
    def key(v):
        # The board's own table is always first. It is not pinned and cannot
        # be — pinning is a choice among the saved cuts, and this one is the
        # board. Ahead of the pinned block rather than inside it.
        if (v.kind or "saved") == "main":
            return (-1, 0, 0, v.id)
        if v.pinned:
            return (0, 0, v.position or 0, v.id)
        return (1, rank.get(v.id, len(rank)), v.position or 0, v.id)
    return sorted(rows, key=key)


def _board_role_or_403(db, board_id, user_id):
    b = db.query(Board).filter(Board.id == board_id).first()
    if not b or b.deleted_at:
        raise HTTPException(404, "board not found")
    role = _board_role(db, board_id, user_id)
    if user_id is not None and role is None:
        raise HTTPException(403, "אין לך גישה ללוח זה")
    return b, role


@app.get("/api/boards/{board_id}/views")
def list_saved_views(board_id: int, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        _b, role = _board_role_or_403(db, board_id, user_id)
        rows = (db.query(SavedView)
                  .filter(SavedView.board_id == board_id,
                          SavedView.deleted_at.is_(None))      # the bin is its own endpoint
                  .order_by(SavedView.position, SavedView.id).all())
        rows = [v for v in rows if _view_visible_to(v, user_id, role)]
        rows = _arrange_views(rows, _view_order_for(db, board_id, user_id))
        names = {}
        if rows:
            ids = {v.owner_id for v in rows}
            names = {u.id: u.name for u in db.query(User).filter(User.id.in_(ids)).all()}
        unseen = _unseen_col_ids(_b, user_id, role)
        def one(v):
            vj = _view_json(v, db, names)
            # A cut that asks about a column this reader may not see is not
            # opened by them — and its filters do not travel either. The
            # message is deliberately general: naming the column, or showing
            # the condition, is the disclosure the block exists to prevent.
            if _view_blocked_for(_b, v, user_id, role):
                return dict(vj, filters={}, blocked=True, needs_fix=[])
            # A column the cut names and the board no longer has. Reported to
            # everyone, unlike `blocked`: the column is gone for all of them.
            return dict(vj, filters=_redact_view_cols(vj["filters"], unseen),
                        blocked=False, needs_fix=_view_needs_fix(_b, v))
        # Where a normal entry lands. Resolved here and not by the client,
        # because the two reasons it can be wrong are both the server's to
        # know: the view may have been deleted since, and it may hold a filter
        # this reader is not allowed to run. Either way the answer is null,
        # which the client reads as the main table.
        #
        # Pinning is deliberately not consulted. "הצמדה אינה קובעת תצוגת
        # ברירת מחדל" — a pin is about the ORDER of the strip, and a board
        # owner pinning a cut must not silently move everybody's landing place.
        prefs = (db.query(BoardViewPrefs)
                   .filter(BoardViewPrefs.board_id == board_id,
                           BoardViewPrefs.user_id == user_id).first()) if user_id else None
        last = prefs.last_view_id if prefs else None
        if last is not None and not any(
                v.id == last and not _view_blocked_for(_b, v, user_id, role) for v in rows):
            last = None
        return {"last_view_id": last,
                "views": [dict(one(v),
                               # may write to it — the rights, and the lock,
                               # which only the board's owner writes through
                               can_edit=(_may_edit_view(v, user_id, role)
                                         and (not v.locked
                                              or _may_write_locked(role))),
                               # may turn the lock itself: the board's owner
                               can_lock=_may_write_locked(role),
                               # may make a tab on this board — the same right
                               # creating one takes. Sent rather than derived,
                               # so the menu offers exactly what the server
                               # would accept and never draws a dead action.
                               can_duplicate=(role in ("admin", "editor")),
                               # drawn as "yours" or "somebody's" — the strip
                               # offers a different thing to save in each case
                               is_owner=(v.owner_id == user_id))
                          for v in rows]}


@app.post("/api/boards/{board_id}/views")
def create_saved_view(board_id: int, data: dict, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        _b, role = _board_role_or_403(db, board_id, user_id)
        name = _check_view_name(db, board_id, data.get("name"))
        # No private views in this version: a saved table view IS a tab on the
        # board, so making one is an edit to the board and needs the rights of
        # one. The parameter is not read — a client asking for "private" gets a
        # shared view, because that is the only kind there is.
        vis = "public"
        if role not in ("admin", "editor"):
            raise HTTPException(403, "תצוגה שמורה היא טאב על הלוח — רק עורך או מנהל לוח יכול ליצור אחת")
        _check_view_room(db, board_id)
        # the cut is validated the way the query endpoint validates one: a view
        # holding a filter the server would refuse is a tab that cannot open
        filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
        try:
            filter_ast.parse(filters.get("adv"))
        except filter_ast.BadFilter as e:
            raise HTTPException(400, str(e))
        if not _view_cut_allowed(_b, filters, user_id, role):
            raise HTTPException(403, "התצוגה מסננת לפי עמודה שאינך מורשה לראות")
        filters = _view_config(filters)
        maxpos = (db.query(func.max(SavedView.position))
                    .filter(SavedView.board_id == board_id).scalar())
        v = SavedView(board_id=board_id, owner_id=user_id, name=name,
                      visibility=vis, filters=filters,
                      position=(maxpos + 1) if maxpos is not None else 0)
        db.add(v)
        _commit_view(db, board_id,
                     log=lambda: _log_view(db, v, "create", field="name",
                                           new=v.name, actor=user_id))
        db.refresh(v)
        return dict(_view_json(v), can_edit=True)


@app.patch("/api/views/{view_id}")
def update_saved_view(view_id: int, data: dict, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        # Through _view_or_404, which also refuses a view that is in the bin.
        # Reading the row directly let a deleted view be saved over: the menu
        # was drawn while it was still there, and "מחיקה תיבדק שוב בזמן
        # הביצוע" is exactly about the gap between those two moments.
        v, role, may = _view_or_404(db, view_id, user_id)
        if not may:
            raise HTTPException(403, "אפשר לערוך רק תצוגה שיצרת")
        # The lock, at both ends of the switch, is the board owner's alone.
        if data.get("locked") is not None and bool(data["locked"]) != bool(v.locked):
            if not _may_write_locked(role):
                raise HTTPException(403, "רק בעל הלוח יכול לנעול תצוגה או לבטל את נעילתה")
            v.locked = bool(data["locked"])
            _log_view(db, v, "lock" if v.locked else "unlock", field="locked",
                      old=str(not v.locked), new=str(v.locked), actor=user_id)
        # הצמדה — and the order the pinned ones sit in — says which cut matters
        # on this board. That is the board owner's statement to make.
        if data.get("pinned") is not None and bool(data["pinned"]) != bool(v.pinned):
            if not _may_write_locked(role):
                raise HTTPException(403, "רק בעל הלוח יכול להצמיד תצוגה")
            v.pinned = bool(data["pinned"])
            _log_view(db, v, "pin" if v.pinned else "unpin", field="pinned",
                      old=str(not v.pinned), new=str(v.pinned), actor=user_id)
        if data.get("position") is not None and not _may_write_locked(role):
            raise HTTPException(403, "רק בעל הלוח יכול לסדר תצוגות מוצמדות")
        # And while it is locked, so is everything the view says.
        rest = [k for k in ("name", "visibility", "filters", "position") if k in data]
        if rest and v.locked and not _may_write_locked(role):
            raise HTTPException(403, "התצוגה נעולה — רק בעל הלוח יכול לשנות אותה")
        if data.get("name") is not None:
            _was = v.name
            v.name = _check_view_name(db, v.board_id, data.get("name"), exclude_id=v.id)
            if v.name != _was:
                _log_view(db, v, "rename", field="name", old=_was, new=v.name, actor=user_id)
        if data.get("visibility") in VIEW_VIS:
            # publishing is the edit that needs the rights, not editing itself:
            # a private view becoming public puts a tab on everybody's board
            if data["visibility"] == "public" and v.visibility != "public" \
                    and role not in ("admin", "editor"):
                raise HTTPException(403, "רק עורך או מנהל לוח יכול לפרסם תצוגה")
            v.visibility = data["visibility"]
        if isinstance(data.get("filters"), dict):
            # ── the version the caller was looking at ────────────────────
            # "עדכון תצורה יכלול גרסה נוכחית ... אם בוצע בינתיים עדכון משותף,
            # השרת ידחה דריסה."
            #
            # Required, not optional, and that is the whole protection: a save
            # that arrives without a version is a save that cannot be checked,
            # and accepting it is exactly the silent overwrite this is here to
            # stop. "אין שמירה אוטומטית של גרסה מיושנת" — nor of an unstated
            # one, which is a stale version nobody bothered to name.
            #
            # 409, so the client can tell "you may not" from "you are behind":
            # the first is a refusal and the second is an invitation to look
            # again. The current version travels back with it, because the
            # next thing that client does is reload and retry.
            want = data.get("config_version")
            have = v.config_version or 1
            if want is None:
                raise HTTPException(400, "שמירת תצורה חייבת לכלול את גרסת התצורה הנוכחית")
            try:
                want = int(want)
            except (TypeError, ValueError):
                raise HTTPException(400, "גרסת תצורה לא תקינה")
            if want != have:
                raise HTTPException(409, {"error": "stale_config",
                                          "detail": "ההגדרות השתנו על ידי משתמש אחר",
                                          "config_version": have})
            try:
                filter_ast.parse(data["filters"].get("adv"))
            except filter_ast.BadFilter as e:
                raise HTTPException(400, str(e))
            b = db.query(Board).filter(Board.id == v.board_id).first()
            # Saving over a cut you may not open would overwrite the rule you
            # cannot see — the same disclosure from the other side.
            if _view_blocked_for(b, v, user_id, role):
                raise HTTPException(403, "התצוגה מסננת לפי עמודה שאינך מורשה לראות")
            if not _view_cut_allowed(b, data["filters"], user_id, role):
                raise HTTPException(403, "התצוגה מסננת לפי עמודה שאינך מורשה לראות")
            v.filters = _view_config(
                _merge_view_cols(data["filters"], v.filters,
                                 _unseen_col_ids(b, user_id, role)))
            # the configuration moved, so the version does — and only here
            v.config_version = (v.config_version or 1) + 1
            # "עדכון משותף" — the event, and the version it produced. Never
            # the cut itself: it can name a column the reader may not see.
            _log_view(db, v, "config", field="config_version",
                      old=str(v.config_version - 1), new=str(v.config_version),
                      actor=user_id)
        if isinstance(data.get("position"), int):
            v.position = data["position"]
        v.updated_at = datetime.now(timezone.utc)
        _commit_view(db, v.board_id, adding=False)
        db.refresh(v)
        # "משתמש ללא שינויים מקומיים יקבל את התצורה החדשה בלי לטעון מחדש את
        # הלוח." The doorbell, not the configuration: the client fetches the
        # strip and decides what to do with it, which is where it knows
        # whether this reader has temporary adjustments to protect.
        bus.publish("view.changed", board_id=v.board_id, actor_id=user_id, view_id=v.id)
        return dict(_view_json(v), can_edit=True)


def _ensure_main_views(db=None):
    """One main-table row per board — "טבלה ראשית אחת תובטח גם עבור לוחות קיימים".

    The board's fixed table used to be nothing at all: the board itself, with
    its column layout in board.settings and no record to point at. That cost
    three things. It could not be named in a link the way a saved view can; it
    had no configuration version, so a client could not tell whether what it
    was holding was stale; and every place that lists views had to special-case
    it, which is how "the main table's name is taken" came to be a hardcoded
    string rather than a row like every other name on the strip.

    Idempotent, and run at startup so boards made before this have one too. It
    never touches a board that already has its row, and it never creates a
    second: the board's own id is what makes the row unique, not the name.
    """
    own = db is None
    db = db or Session(engine)
    try:
        have = {b for (b,) in db.query(SavedView.board_id)
                                .filter(SavedView.kind == "main").all()}
        made = 0
        for (bid,) in db.query(Board.id).all():
            if bid in have:
                continue
            db.add(SavedView(board_id=bid, owner_id=None, kind="main",
                             name=MAIN_VIEW_NAME, visibility="public",
                             filters={"view": "table"}, position=-1))
            made += 1
        if made:
            db.commit()
            print(f"[views] main table ensured on {made} board(s)")
        return made
    finally:
        if own:
            db.close()


# Run once at import, after the function above exists. Deliberately not up
# beside the seeding: that block runs before this module has finished loading,
# and calling a name defined further down from there silently did nothing.
try:
    _ensure_main_views()
except Exception as _e:                      # never block startup over it
    print(f"⚠️  main-table backfill skipped: {_e}", flush=True)


def _within_restore_window(v):
    """Is this deleted view still inside the window it can be brought back in?

    The row is not erased when the window closes — nothing here deletes data on
    a timer — but the log stops offering the restore, because an offer that
    fails when pressed is worse than no offer at all.
    """
    if v.deleted_at is None:
        return True
    gone = v.deleted_at
    if gone.tzinfo is None:                 # SQLite hands back naive datetimes
        gone = gone.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - gone) <= timedelta(days=VIEW_RESTORE_DAYS)


def _view_or_404(db, view_id, user_id, *, live=True):
    """The view, the board role, and whether this person may manage it."""
    q = db.query(SavedView).filter(SavedView.id == view_id)
    v = q.first()
    if not v or (live and v.deleted_at is not None):
        raise HTTPException(404, "view not found")
    _b, role = _board_role_or_403(db, v.board_id, user_id)
    return v, role, _may_edit_view(v, user_id, role)


@app.delete("/api/views/{view_id}")
def delete_saved_view(view_id: int, user_id: int = Depends(current_user_id)):
    """To the bin, not out of existence.

    A view is a tab other people work off. Deleting one by mistake is the kind
    of thing nobody notices until the morning somebody opens the board and
    their cut is gone — and a hard delete leaves nothing to put back. Same
    shape as a deleted board or item: deleted_at, and a restore beside it.

    Deleting a locked view is the board owner's too — the definition names
    deletion alongside changing and unlocking, and a lock that stopped edits
    but not deletion would protect nothing worth protecting.
    """
    with Session(engine) as db:
        v, role, may = _view_or_404(db, view_id, user_id)
        # "לא ניתן למחוק את הטבלה הראשית." It is the board's own table; there
        # is no board without one, so there is nothing here to delete.
        if (v.kind or "saved") == "main":
            raise HTTPException(400, "לא ניתן למחוק את הטבלה הראשית")
        if not may:
            raise HTTPException(403, "אפשר למחוק רק תצוגה שיצרת")
        if v.locked and not _may_write_locked(role):
            raise HTTPException(403, "התצוגה נעולה — רק בעל הלוח יכול למחוק אותה")
        v.deleted_at = datetime.now(timezone.utc)
        v.deleted_by = user_id
        # Into the board's log, because that is where the restore is offered
        # from — "בעל הלוח יוכל לשחזר דרך לוג הלוח". The view's name is the
        # whole of the record: it is what the person reading the log is looking
        # for, and the cut itself is still on the row if it comes back.
        _log_view(db, v, "delete", field="name", old=v.name, actor=user_id)
        db.commit()
        return {"status": "deleted", "id": v.id}


@app.get("/api/boards/{board_id}/views/trash")
def list_deleted_views(board_id: int, user_id: int = Depends(current_user_id)):
    """What can still be brought back, newest first."""
    with Session(engine) as db:
        _b, role = _board_role_or_403(db, board_id, user_id)
        rows = (db.query(SavedView)
                  .filter(SavedView.board_id == board_id,
                          SavedView.deleted_at.isnot(None))
                  .order_by(SavedView.deleted_at.desc(), SavedView.id.desc()).all())
        rows = [v for v in rows if _view_visible_to(v, user_id, role)
                and _within_restore_window(v)]
        names = {}
        if rows:
            ids = {v.owner_id for v in rows} | {v.deleted_by for v in rows if v.deleted_by}
            names = {u.id: u.name for u in db.query(User).filter(User.id.in_(ids)).all()}
        return {"views": [dict(_view_json(v, db, names),
                               deleted_at=v.deleted_at.isoformat() if v.deleted_at else None,
                               deleted_by_name=names.get(v.deleted_by, ""),
                               can_manage=_may_edit_view(v, user_id, role))
                          for v in rows]}


@app.post("/api/views/{view_id}/restore")
def restore_saved_view(view_id: int, user_id: int = Depends(current_user_id)):
    """Back onto the strip, with its cut and its name intact."""
    with Session(engine) as db:
        v, role, may = _view_or_404(db, view_id, user_id, live=False)
        if v.deleted_at is None:
            return dict(_view_json(v), can_edit=may)
        # Bringing a tab back puts it on everybody's board again, which is the
        # same act as creating one and then some — it may be a tab people had
        # already agreed to be rid of. The board owner's.
        if not _may_write_locked(role):
            raise HTTPException(403, "רק בעל הלוח יכול לשחזר תצוגה שנמחקה")
        if not _within_restore_window(v):
            raise HTTPException(400,
                                f"חלון השחזור הוא {VIEW_RESTORE_DAYS} יום ממועד המחיקה, והוא חלף")
        # Putting a tab back on the strip is subject to what the strip allows
        # NOW, not to what it allowed when the tab left it. The board may have
        # filled up since — that is a refusal, because there is nowhere to put
        # it — while a name taken since is not: "בשחזור עם שם תפוס תתווסף
        # סיומת ייחודית", so the view comes back under a name of its own
        # rather than not at all.
        _check_view_room(db, v.board_id)
        v.name = _free_name(db, v.board_id, v.name, " — משוחזרת", exclude_id=v.id)
        # "ההצמדה לא תשוחזר אוטומטית, כדי לא לשנות את סדר הניווט הקיים."
        # A pin puts the tab first for everybody; people have arranged
        # themselves around the strip as it is since. Coming back is the view's
        # to ask for, the front of the strip is not — the board owner can pin
        # it again in one click if that is still what they want.
        v.pinned = False
        v.deleted_at = None
        v.deleted_by = None
        v.updated_at = datetime.now(timezone.utc)
        _log_view(db, v, "restore", field="name", new=v.name, actor=user_id)
        # a restore puts a live row back, so it faces both rules again
        _commit_view(db, v.board_id)
        db.refresh(v)
        b = db.query(Board).filter(Board.id == v.board_id).first()
        return dict(_view_json(v),
                    can_edit=may and (not v.locked or _may_write_locked(role)),
                    can_manage=may,
                    # restored, and possibly into a board that has changed
                    # under it — see _view_needs_fix
                    needs_fix=_view_needs_fix(b, v))


@app.post("/api/views/{view_id}/duplicate")
def duplicate_saved_view(view_id: int, data: dict = None,
                         user_id: int = Depends(current_user_id)):
    """שכפול — the same cut under a new name, owned by whoever copied it.

    Not locked and not pinned, whatever the original was: a lock and a pin are
    statements about THAT tab, and a copy is a new tab that nobody has decided
    anything about yet.
    """
    with Session(engine) as db:
        v, role, _may = _view_or_404(db, view_id, user_id)
        if role not in ("admin", "editor"):
            raise HTTPException(403, "תצוגה שמורה היא טאב על הלוח — רק עורך או מנהל לוח יכול ליצור אחת")
        b = db.query(Board).filter(Board.id == v.board_id).first()
        # Copying a cut you may not open would hand you the cut: the copy is
        # yours, and the rule naming the column you cannot see comes with it.
        if _view_blocked_for(b, v, user_id, role):
            raise HTTPException(403, "התצוגה מסננת לפי עמודה שאינך מורשה לראות")
        _check_view_room(db, v.board_id)
        # A name may arrive with the copy — the dialog offers the suggestion
        # below and lets it be changed before saving — and whichever one comes
        # is held to the same rule as any other name.
        name = _check_view_name(db, v.board_id,
                                ((data or {}).get("name") or "").strip() or _copy_name(db, v))
        maxpos = (db.query(func.max(SavedView.position))
                    .filter(SavedView.board_id == v.board_id).scalar())
        # The SAVED shared configuration, not whatever the copier is looking
        # at — that is what "שמירה כתצוגה חדשה" is for. Shared, unlocked,
        # unpinned, a new id, and nothing but the configuration: no items, and
        # no permission anybody did not already have.
        c = SavedView(board_id=v.board_id, owner_id=user_id, name=name,
                      visibility="public", filters=_view_config(dict(v.filters or {})),
                      position=(maxpos + 1) if maxpos is not None else 0)
        db.add(c)
        _commit_view(db, v.board_id,
                     log=lambda: _log_view(db, c, "create", field="name",
                                           old=v.name, new=c.name, actor=user_id))
        db.refresh(c)
        return dict(_view_json(c), can_edit=True, can_manage=True, is_owner=True)


def _free_name(db, board_id, name, suffix, exclude_id=None):
    """`name` if it is free, else the same with a distinguishing suffix.

    Used where a name MUST come out usable rather than refused: restoring a
    view, and suggesting one for a copy. Where somebody typed the name, it is
    refused instead — see _check_view_name — because silently renaming what a
    person wrote is its own small lie.
    """
    q = db.query(SavedView.name).filter(SavedView.board_id == board_id,
                                        SavedView.deleted_at.is_(None))
    if exclude_id is not None:
        q = q.filter(SavedView.id != exclude_id)
    taken = {_view_name_key(n) for (n,) in q.all()}
    taken.add(_view_name_key(MAIN_VIEW_NAME))

    def fit(tail):
        room = VIEW_NAME_MAX - len(tail)
        return ((name or "")[:room].strip() + tail) if room > 0 else tail.strip()

    if _view_name_key(name) not in taken and len(name or "") <= VIEW_NAME_MAX:
        return name
    n = 1
    while True:
        cand = fit(suffix if n == 1 else f"{suffix} {n}")
        if _view_name_key(cand) not in taken:
            return cand
        n += 1


def _copy_name(db, v):
    """A free name for a copy: "<שם> — עותק", then "עותק 2", and so on.

    Compared the way every other name on the strip is compared — trimmed and
    casefolded, with the main table's name among the taken ones — so the
    suggestion can never come back refused by the rule that produced it.

    Shortened to fit when the original is already near the ceiling. A
    suggestion is ours to trim; a name somebody typed is not.
    """
    taken = {_view_name_key(n) for (n,) in
             db.query(SavedView.name).filter(SavedView.board_id == v.board_id,
                                             SavedView.deleted_at.is_(None)).all()}
    taken.add(_view_name_key(MAIN_VIEW_NAME))

    def fit(suffix):
        room = VIEW_NAME_MAX - len(suffix)
        return ((v.name or "")[:room].strip() + suffix) if room > 0 else suffix.strip()

    n = 1
    while True:
        cand = fit(" — עותק" if n == 1 else f" — עותק {n}")
        if _view_name_key(cand) not in taken:
            return cand
        n += 1


@app.put("/api/boards/{board_id}/views/last")
def set_last_view(board_id: int, data: dict, user_id: int = Depends(current_user_id)):
    """Remember which view this person is on, so the next entry opens it.

    Anyone who may open the board may record it — it says nothing about the
    board, only about them — which is the same reason their order needs no
    rights either.

    `view_id` null means the main table. A view id that is not a live view of
    this board is stored as null rather than refused: the board changes under
    people, and the honest answer to "open the one I was on" when it is gone
    is the main table, not an error on the way in.
    """
    with Session(engine) as db:
        _b, role = _board_role_or_403(db, board_id, user_id)
        want = data.get("view_id")
        keep = None
        if want is not None:
            try:
                want = int(want)
            except (TypeError, ValueError):
                want = None
            if want is not None:
                v = (db.query(SavedView)
                       .filter(SavedView.id == want, SavedView.board_id == board_id,
                               SavedView.deleted_at.is_(None)).first())
                # not a view they could open is not a view they were on
                if v is not None and not _view_blocked_for(_b, v, user_id, role):
                    keep = v.id
        row = (db.query(BoardViewPrefs)
                 .filter(BoardViewPrefs.board_id == board_id,
                         BoardViewPrefs.user_id == user_id).first())
        if not row:
            row = BoardViewPrefs(board_id=board_id, user_id=user_id)
            db.add(row)
        row.last_view_id = keep
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"last_view_id": keep}


@app.put("/api/boards/{board_id}/views/order")
def set_personal_view_order(board_id: int, data: dict,
                            user_id: int = Depends(current_user_id)):
    """סדר תצוגות אישי — this reader's arrangement, nobody else's.

    Anyone who may open the board may arrange their own strip; it changes
    nothing about the board, which is exactly why it needs no rights beyond
    looking. Ids of views that are not on this board are dropped rather than
    refused: a strip arranged and then re-arranged on a stale list must not
    fail, it must simply settle.
    """
    with Session(engine) as db:
        _b, role = _board_role_or_403(db, board_id, user_id)
        want = data.get("order")
        if not isinstance(want, list):
            raise HTTPException(400, "order must be a list of view ids")
        # Pinned views are not this reader's to order — see _arrange_views.
        # Dropped rather than refused, like a stale id: a strip dragged while
        # somebody else pinned a tab must settle, not fail.
        mine = {v.id for v in db.query(SavedView.id)
                                .filter(SavedView.board_id == board_id,
                                        SavedView.deleted_at.is_(None),
                                        SavedView.pinned.isnot(True)).all()}
        seen, clean = set(), []
        for i in want:
            try:
                i = int(i)
            except (TypeError, ValueError):
                continue
            if i in mine and i not in seen:
                seen.add(i)
                clean.append(i)
        row = (db.query(BoardViewPrefs)
                 .filter(BoardViewPrefs.board_id == board_id,
                         BoardViewPrefs.user_id == user_id).first())
        if not row:
            row = BoardViewPrefs(board_id=board_id, user_id=user_id)
            db.add(row)
        row.order = clean
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"order": clean}


# ── the advanced filter, evaluated here ────────────────────────────────
# The client sends the condition tree as JSON — an AST, groups holding groups —
# and gets back the ids that answer it. It filters locally too, for the
# instant feedback a toolbar needs; this is the authority, and the only place
# that can answer for a board bigger than what the browser was handed.
#
# Two things the client must send, and the reason is the same for both: the
# only clock that can say what "היום" means is the one the person is reading.
#   `today`      — the client's own local date (YYYY-MM-DD)
#   `tz_offset`  — minutes east of UTC, so an instant stored in UTC can be
#                  turned into the day the viewer is having
# Without them the server's own date and UTC are used, which is right for a
# script and wrong for a person — so the report says which was used.
@app.post("/api/boards/{board_id}/items/query")
def query_board_items(board_id: int, data: dict, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        # the same gate the board's own fetch uses — a filter must never be a
        # way to learn what is on a board you cannot open
        my_role = _board_role(db, board_id, user_id)
        if user_id is not None and my_role is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        try:
            tree = filter_ast.parse(data.get("filter"))
        except filter_ast.BadFilter as e:
            # Named, not swallowed: a filter the server refuses and the client
            # keeps showing results for is the two disagreeing in silence.
            raise HTTPException(400, str(e))

        today = str(data.get("today") or "").strip()
        if not filter_ast._ISO_DAY.match(today):
            today = datetime.now(timezone.utc).date().isoformat()
            client_clock = False
        else:
            client_clock = True
        try:
            off = int(data.get("tz_offset") or 0)
        except (TypeError, ValueError):
            off = 0
        off = max(-14 * 60, min(14 * 60, off))

        # What each field can be asked about — built-ins, then the board's own.
        #
        # Two maps, because "the column is gone" and "you may not see it" are
        # different answers and the person deserves the right one. `fields` is
        # what this reader may filter by; `known` is every column the board
        # has, used only to tell the two apart in the report.
        base = {"title": "text", "status": "status", "priority": "status",
                "assignees": "people", "due": "date"}
        fields, known = dict(base), dict(base)
        known, fields = _filter_columns(b, user_id, my_role, known, fields)

        # A rule naming a column that was deleted comes OUT of the tree rather
        # than being made to answer true — inside an "or" group the two are
        # opposites, and the second quietly shows the whole board. The caller
        # is told which, so it can say so.
        #
        # A rule naming a column this reader may not SEE comes out for the
        # same reason and a different one: running it would answer a question
        # about hidden data with a row set, and a row set is an answer. Which
        # of the two happened is reported separately — "the column was
        # deleted" and "you may not see it" are different facts about the
        # board, and telling somebody the wrong one is its own small lie.
        tree, gone = filter_ast.prune(tree, fields)
        denied = [f for f in gone if f in known]
        dropped = [f for f in gone if f not in known]
        if denied and FILTER_COLUMN_POLICY == "block":
            raise HTTPException(403, "התצוגה מסננת לפי עמודה שאינך מורשה לראות")
        # A SAVED view naming a column the board no longer has does not run at
        # all — "לא תציג תוצאות חלקיות מטעות". Dropping the dead rule and
        # answering anyway is the misleading part: inside an "or" group it
        # shows the whole board with the filter apparently on.
        #
        # Only when the request says which view it came from. A filter somebody
        # is building by hand cannot name a column that is not on the board —
        # the picker offers what exists — so this is about a cut that was saved
        # while the column was still there.
        if dropped and data.get("view_id"):
            raise HTTPException(409, "התצוגה מסננת לפי עמודה שנמחקה מהלוח — יש לתקן אותה")

        # Ordered, and not by chance: pages are cut out of this list, and a
        # list whose order is whatever the database felt like means page two
        # can repeat a row from page one and skip another entirely.
        rows = (db.query(Task)
                  .filter(Task.board_id == board_id, Task.parent_id.is_(None),
                          Task.is_archived == False, Task.deleted_at.is_(None))
                  .order_by(Task.position, Task.id)
                  .all())
        # and an item this person may not see is not an item this answers for
        if user_id is not None:
            rows = [t for t in rows if _item_perm(t, user_id, my_role) != "none"]

        # "אם עדכון גורם לפריט להפסיק להתאים למסנן, הוא יוסתר לאחר השמירה
        # ותוצג הודעה עם קישור לפריט."
        #
        # Somebody edits a cell and the row they were working on may no longer
        # belong in the cut. Answering that from a PAGE of ids cannot be done:
        # the page holds the first fifty matches, and an item absent from it
        # has either stopped matching or simply sits further down. `ids_only`
        # is no better past its cap, where the honest answer is "truncated".
        #
        # So the question can be asked about named items instead, and then it
        # is exact whatever the board's size: these ids, which of them still
        # match. Everything else about the request is unchanged — the same
        # filter, the same toolbar, the same permissions — because the point
        # is to ask the SAME question about one row.
        only = data.get("only")
        if isinstance(only, list):
            want = {int(x) for x in only if str(x).lstrip("-").isdigit()}
            rows = [t for t in rows if t.id in want]
        # The toolbar's own filters, applied alongside the tree.
        #
        # They have to be here, and the reason is not completeness. On a
        # large board the server's answer IS what the browser shows — the
        # local pass is skipped, because re-filtering a page against the rows
        # this browser happens to hold is the half the server was asked to
        # replace. So a toolbar filter the server does not know about is a
        # filter that silently stops working at exactly the board size where
        # filtering matters most.
        q = str(data.get("q") or "").strip().lower()
        want_people = {int(x) for x in (data.get("people") or []) if str(x).isdigit()}
        want_status = str(data.get("status") or "")
        want_prio = str(data.get("priority") or "")

        def _passes_toolbar(t):
            if want_status and _task_status_key(t) != want_status:
                return False
            if want_prio and _task_priority_key(t) != want_prio:
                return False
            if want_people and not ({u.id for u in t.assignees} & want_people):
                return False
            if q:
                hay = [(t.title or ""), (t.description or ""), str(t.item_uid or "")]
                hay += [u.name or "" for u in t.assignees]
                if not any(q in h.lower() for h in hay):
                    return False
            return True

        # ── the hierarchy rules ──────────────────────────────────────────
        # A condition is asked of sub-items as well, and the four combinations
        # have four different answers:
        #
        #   parent matches, a sub matches  → the parent and the matching subs
        #   parent matches, none does      → the parent alone, no subs under it
        #   parent does not, a sub does    → the parent AS CONTEXT, matching subs
        #   neither                        → not shown
        #
        # Two things fall out of that and are easy to get wrong. A parent that
        # matches still shows only the sub-items that match — a cut is a cut
        # all the way down, and showing the rest under a matching parent would
        # answer a different question on every row. And a parent present only
        # because of its children is marked, because it is there to say WHERE
        # they are: unmarked, it reads as a row that answered the filter.
        subs_all = (db.query(Task)
                      .filter(Task.board_id == board_id, Task.parent_id.isnot(None),
                              Task.is_archived == False, Task.deleted_at.is_(None))
                      .order_by(Task.position, Task.id)
                      .all())
        if user_id is not None:
            # the same gate the parents went through — a sub-item somebody may
            # not see cannot pull its parent into the answer either
            subs_all = [t for t in subs_all if _item_perm(t, user_id, my_role) != "none"]
        if isinstance(only, list):
            subs_all = []          # a question about named rows is about those rows

        total = len(rows)

        def _asked(t):
            """Does this row answer the cut — the conditions and the search."""
            item = {
                "id": t.id, "title": t.title,
                "status": _task_status_key(t), "priority": _task_priority_key(t),
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "assignees": [{"id": u.id} for u in t.assignees],
                "custom_fields": t.custom_fields or {},
            }
            return (_passes_toolbar(t)
                    and filter_ast.match(item, tree, fields, today, off, user_id))

        own = {t.id for t in rows if _asked(t)}
        # matching sub-items, kept in the board's own order under their parent
        kids_hit = {}
        for sub in subs_all:
            if _asked(sub):
                kids_hit.setdefault(sub.parent_id, []).append(sub)
        # a parent appears if it answered, or if one of its children did
        hits = [t for t in rows if t.id in own or t.id in kids_hit]
        # present only to say where the children are — see the rules above
        context_only = {t.id for t in hits if t.id not in own}

        # ── a matching sub-item whose PARENT is not this person's to see ──
        # The permission model allows it: a sub-item carries its own overrides,
        # so somebody can be let into a line of a work plan without being let
        # into the plan. Dropping the parent used to drop the sub-item with
        # it — the row hangs under its parent — so a match they are entitled
        # to simply vanished.
        #
        # Instead the parent comes back as a neutral wrapper: a place to hang
        # the children, carrying no title, no values, no people, no dates.
        # "ולא לחשוף את פרטי האב" is the whole of its content. It is marked
        # both as context and as restricted, because the two mean different
        # things to the screen — one is "this row did not match", the other is
        # "there is nothing here to show you".
        seen_parents = {t.id for t in rows}
        shell_ids = [pid for pid in kids_hit if pid not in seen_parents]
        shells = []
        if shell_ids:
            shells = (db.query(Task)
                        .filter(Task.id.in_(shell_ids), Task.board_id == board_id)
                        .order_by(Task.position, Task.id).all())
        matched = len(hits) + len(shells)

        # ── then sort, over everything that matched ──────────────────────
        # "סינון ומיון חלים על כלל נתוני הלוח המורשים, גם בטעינה מדורגת."
        #
        # Sorting used to be the browser's alone, over the rows it happened to
        # hold. Below the client threshold that is every row and the two are
        # the same thing; past it the server answers with a PAGE, and sorting
        # a page is not sorting the board — it orders fifty rows that were
        # chosen by position and calls the result sorted. Page two then
        # repeats and skips, because each page is ordered against itself.
        #
        # So the order is applied here, after the filter and before the page
        # is cut, which is also the order the spec gives: permissions, then
        # the conditions and the search, then sort, then the hierarchy.
        #
        # The same three keys the toolbar offers and a view stores. Per-COLUMN
        # sorting (the arrows on a header) is still the browser's own and is
        # still wrong past the threshold — it is not part of a saved view's
        # configuration, and giving it the same treatment is its own change.
        prio_rank = {p["key"]: i for i, p in enumerate(_board_priorities(b))}
        _SORTS = {
            # a missing date sorts last, exactly as the browser does it
            "due": lambda t: (t.due_date is None, t.due_date or date.min),
            "priority": lambda t: prio_rank.get(_task_priority_key(t), 998),
            "title": lambda t: (t.title or ""),
        }
        want_sort = str(data.get("sort") or "")
        if want_sort in _SORTS:
            # ── inside the groups, never across them ─────────────────────
            # "סדר הקבוצות נשאר לפי מבנה הלוח. המיון חל בתוך קבוצות ... ואינו
            # מפרק את ההיררכיה."
            #
            # A flat sort reorders the whole board and the groups dissolve:
            # rows from three of them interleave by due date and the board
            # stops being the thing it was arranged into. Groups are
            # structure, not a result — they keep the order the board gives
            # them, and the sort decides who sits where INSIDE each one.
            gpos = {g.id: (g.position or 0, g.id) for g in
                    db.query(Group).filter(Group.board_id == board_id).all()}
            inner = _SORTS[want_sort]
            # a row with no group sorts after the groups, not before them
            hits.sort(key=lambda t: (gpos.get(t.group_id, (10 ** 9, 0)), inner(t),
                                     t.position or 0, t.id))
            # and the same order under each parent, for the same reason: a
            # sort that reordered items but left their children in position
            # order would be two orders on one screen
            for pid in kids_hit:
                kids_hit[pid] = sorted(kids_hit[pid],
                                       key=lambda t: (inner(t), t.position or 0, t.id))

        out = {"matched": matched, "total": total,
               # how many of the rows answered the cut themselves, and how many
               # sub-items did — "3 items" over a list where one of them is
               # only context would be a lie the screen cannot correct
               # Three different numbers, and conflating any two of them
               # misstates the answer: how many top-level items matched, how
               # many sub-items did, and how many rows are on screen only to
               # say where those sub-items are. A context row is not a result.
               # All three count what MATCHED, not what the page happened to
               # load.
               "matched_own": len(own),
               "matched_subs": sum(len(v) for v in kids_hit.values()),
               "matched_context": len(context_only) + len(shells),
               "sort": want_sort if want_sort in _SORTS else "",
               "conditions": filter_ast.count(tree),
               # the rules that could not be run, so the caller can say why
               # the answer is wider than the view promised — and which of
               # the two reasons it was
               "dropped_fields": dropped,
               "denied_fields": denied,
               "column_policy": FILTER_COLUMN_POLICY,
               "client_max": FILTER_CLIENT_MAX,
               # so a caller can see which clock answered "היום"
               "today": today, "tz_offset": off, "client_clock": client_clock}

        # Two ways to answer, and which one is right depends on the board.
        #
        # `ids_only` is the small-board answer: the browser already holds
        # every row and only needs to know which of them survive. It is
        # capped at the same threshold that decides the mode in the first
        # place — past that the browser should not have been asking this way.
        #
        # Otherwise a PAGE of rows, serialised. A board of tens of thousands
        # must never arrive in one response: not because this cannot build
        # it, but because the browser cannot draw it, and the request blocks
        # everything behind it while it tries. Only the page is serialised —
        # the rows that did not make it onto it cost a comparison each and
        # nothing more.
        if isinstance(only, list):
            # the ids asked about that survive, and nothing else: a caller
            # asking about one row must not be handed a page of others
            out["item_ids"] = [t.id for t in hits]
            out["asked"] = sorted(want)
            return out

        if data.get("ids_only"):
            out["item_ids"] = [t.id for t in hits[:FILTER_CLIENT_MAX]]
            out["truncated"] = matched > FILTER_CLIENT_MAX
            return out

        try:
            limit = int(data.get("limit") or QUERY_PAGE)
        except (TypeError, ValueError):
            limit = QUERY_PAGE
        limit = max(1, min(QUERY_PAGE_MAX, limit))
        try:
            offset = max(0, int(data.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        # The wrappers sit at the end of the board's own order, which is where
        # a row with nothing to read belongs: it is scaffolding, not a result.
        ordered = hits + shells
        page = ordered[offset:offset + limit]
        _subs = _prefetch_items(db, page)
        # _prefetch_items has just filled _kids_by with EVERY child of every
        # row on the page. Narrow it to the ones that matched, which is what
        # _serialize_task reads: a parent that answered the cut still shows
        # only the children that did, and one that answered nothing shows none.
        db.info["_kids_by"] = {t.id: kids_hit.get(t.id, []) for t in page}
        _subs = [s for t in page for s in kids_hit.get(t.id, [])]
        _prefetch_links(db, list(page) + _subs, (b.settings or {}).get("columns", []), user_id)
        cols = (b.settings or {}).get("columns", [])
        shell_set = {t.id for t in shells}

        def _row_json(t):
            if t.id in shell_set:
                return _context_shell(t, kids_hit.get(t.id, []), db,
                                      user_id=user_id, board_role=my_role, columns=cols)
            return dict(_serialize_task(t, db, user_id=user_id, board_role=my_role,
                                        columns=cols),
                        context_only=(t.id in context_only), restricted=False)

        out["items"] = [_row_json(t) for t in page]
        out["item_ids"] = [t.id for t in page]
        out["offset"] = offset
        out["limit"] = limit
        out["has_more"] = (offset + len(page)) < matched
        out["next_offset"] = offset + len(page)
        return out


@app.get("/api/boards/{board_id}")
def get_board(board_id: int, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "Board not found")
        if b.deleted_at:                     # in the recycle bin — restore it first
            raise HTTPException(404, "הלוח נמצא בסל המחזור")
        # date-based automations have no scheduler — opening the board is when
        # "the due date arrived" is noticed (each rule fires once per item)
        _sweep_due_date_automations(db, board_id, user_id)
        my_role = _board_role(db, board_id, user_id)
        if user_id is not None and my_role is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        groups = db.query(Group).filter(Group.board_id == b.id).order_by(Group.position).all()
        # only top-level items as rows; sub-items are nested under their parent
        tasks = db.query(Task).filter(Task.board_id == b.id, Task.is_archived == False,
                                      Task.parent_id == None).order_by(Task.position).all()
        dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
        columns = (b.settings or {}).get("columns", [])
        # a board carrying a "מזהה פריט" column shows an identifier for every
        # item — including ones that predate the column, or arrived from elsewhere
        if _board_has_item_id_col(b):
            _backfill_item_uids(db, b.id)
        # hide items the user has no view permission on
        if user_id is not None:
            tasks = [t for t in tasks if _item_perm(t, user_id, my_role) != "none"]
        # one pass for everything an item is about to be asked — its sub-items,
        # assignees and counts (_prefetch_items), then its links (_prefetch_links)
        _subs = _prefetch_items(db, tasks)
        _prefetch_links(db, list(tasks) + _subs, columns, user_id)
        tasks_out = [_serialize_task(t, db, user_id=user_id, board_role=my_role, columns=columns) for t in tasks]

        # board owners = members with the board-scoped admin role (creator + any
        # promoted admin). Exposed to every member so anyone can see who manages it.
        # one join, not a query per owner
        owners = [{"id": ou.id, "name": ou.name, "avatar_url": ou.avatar_url}
                  for ou in (db.query(User)
                               .join(BoardMember, BoardMember.user_id == User.id)
                               .filter(BoardMember.board_id == b.id,
                                       BoardMember.role == "admin")
                               .order_by(User.id).all())]

        # built here rather than by FastAPI — see _json_default
        return _json({
            "id": b.id, "name": b.name, "description": b.description,
            "board_type": b.board_type.value if hasattr(b.board_type, 'value') else b.board_type,
            "icon": b.icon, "color": b.color,
            "is_archived": b.is_archived,
            "department_name": dept_name,
            "views": _board_views(b),
            "view_only": (b.settings or {}).get("view_only", False),
            "visibility": _board_visibility(b),
            "my_role": my_role,
            # whether the automations page is offered at all — a board viewer
            # never sees it, and an editor only where the capability is granted
            "can_view_automations": _can_view_automations(db, b, user_id),
            "owners": owners,
            # who may be tagged in a people column — the pickers build from this,
            # so it holds exactly who _can_be_assigned would accept: a member
            # whose account was deactivated is not offered. Anyone already
            # tagged is re-added client-side, so an old tag stays removable.
            "members": [{"id": mu.id, "name": mu.name, "avatar_url": mu.avatar_url}
                        for mu in (db.query(User)
                                     .join(BoardMember, BoardMember.user_id == User.id)
                                     .filter(BoardMember.board_id == b.id,
                                             User.is_active.isnot(False))
                                     .order_by(User.name).all())],
            "columns": (b.settings or {}).get("columns", []),
            # which columns sub-items show (ids, name column first). None = never
            # configured → sub-items mirror the item columns.
            "sub_cols": (b.settings or {}).get("sub_cols"),
            # custom columns that live ONLY on sub-items, never on the parent items
            "sub_only": (b.settings or {}).get("sub_only", []),
            # one map for the whole board — a column's permission is the same on
            # every item (see _serialize_task)
            "col_perms": ({c["id"]: _col_perm(c, user_id, my_role) for c in columns}
                          if user_id is not None else {}),
            "col_widths": (b.settings or {}).get("col_widths", {}),
            "col_labels": (b.settings or {}).get("col_labels", {}),
            "col_hidden": (b.settings or {}).get("col_hidden", []),
            "col_order": (b.settings or {}).get("col_order", []),
            "notifications_enabled": bool((b.settings or {}).get("notifications_enabled", True)),
            # Where this board's filtering runs. The browser has to know
            # before it asks anything — it is the number that decides whether
            # to ask at all — so it travels with the board rather than with
            # the first answer.
            "filter_client_max": FILTER_CLIENT_MAX,
            "filter_column_policy": FILTER_COLUMN_POLICY,
            "statuses": _board_statuses(b),
            "priorities": _board_priorities(b),
            "form": (b.settings or {}).get("form"),
            "groups": [{"id": g.id, "name": g.name, "position": g.position, "color": g.color, "task_status": g.task_status.value if hasattr(g.task_status, 'value') else g.task_status} for g in groups],
            "tasks": tasks_out,
        })

@app.post("/api/boards")
def create_board(data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        # only a system (workspace) admin may create boards; the creator becomes
        # the board's first admin, so a board is never created without a manager.
        creator = actor_id
        # a new board belongs to the environment it was created in (default: primary workspace)
        env_id = data.get("environment_id")
        if not env_id:
            primary = db.query(Environment).filter(Environment.is_primary == True).first()
            env_id = primary.id if primary else None
        # allowed if the user has the global create-board capability, or manages the
        # target environment (an environment manager runs their own environment)
        if not (_cap(db, creator, "create_board") or _can_manage_env(db, env_id, creator)):
            raise HTTPException(403, "אין לך הרשאה ליצור לוח חדש")
        dept_id = data.get("department_id")
        if not dept_id:
            dept_id = db.query(Department.id).order_by(Department.id).limit(1).scalar()
        folder_id = data.get("folder_id")
        # append the new board at the bottom of its container (env root or folder)
        maxpos = (db.query(func.max(Board.position))
                  .filter(Board.environment_id == env_id, Board.folder_id == folder_id).scalar())
        b = Board(
            name=data.get("name", "לוח חדש"),
            description=data.get("description", ""),
            department_id=dept_id,
            environment_id=env_id,
            folder_id=folder_id,
            position=(maxpos + 1) if maxpos is not None else 0,
            board_type=BoardType.KANBAN,
            icon=data.get("icon", "📋"),
            color=data.get("color", "#0073ea"),
            settings={
                "views": ["table"],  # new boards start with only the main table
                # A new board is private: only the people invited to it can see
                # it. Publishing is a decision its admin makes deliberately from
                # the board menu, never the state a board is born in.
                "visibility": ("public" if data.get("visibility") == "public" else "private"),
                # every new board ships with these auto columns (read-only, from the item's metadata)
                "columns": [
                    {"id": "sys_item_id", "type": "item_id", "title": "מספר מזהה"},
                    {"id": "sys_created_at", "type": "created_at", "title": "מועד יצירה"},
                    # derived from the item's own creator, like "מועד יצירה" above:
                    # nothing to fill in, so it is right on every item on every
                    # board — including boards and items that predate the column
                    {"id": "sys_created_by", "type": "created_by", "title": "יוצר הרשומה"},
                ],
            },
        )
        db.add(b)
        db.flush()
        # default groups: 3 clean stages (no "review"). More can be added in-board.
        g1 = Group(board_id=b.id, name="בתכנון", position=0, color="#579bfc", task_status=TaskStatus.BACKLOG)
        db.add_all([
            g1,
            Group(board_id=b.id, name="בביצוע", position=1, color="#fdab3d", task_status=TaskStatus.IN_PROGRESS),
            Group(board_id=b.id, name="הושלם", position=2, color="#00c875", task_status=TaskStatus.DONE),
        ])
        db.flush()
        # 3 starter items in the first group so the board isn't blank — the creator
        # is recorded as their author and auto-filled into the "יוצר הרשומה" column.
        # Nobody has chosen a status or a priority for them, so both read
        # "טרם הוגדר" until someone does, exactly like an item added by hand.
        for i in range(1, 4):
            cf = {"status_unset": True, "priority_unset": True}
            if creator:
                cf["sys_created_by"] = [creator]
            db.add(Task(board_id=b.id, group_id=g1.id, title=f"פריט {i}",
                        status=TaskStatus.BACKLOG, priority=Priority.MEDIUM, position=i,
                        created_by=creator, custom_fields=cf))
        # creator becomes the board admin; the board is private until they invite others
        db.add(BoardMember(board_id=b.id, user_id=creator, role="admin"))
        db.commit()
        # and the board's own table, which every board has exactly one of.
        # Created here as well as backfilled at startup: the backfill is for
        # the boards that already existed, and a board made a minute from now
        # must not have to wait for the next restart to have one.
        #
        # After the board's own commit, and never able to fail it. A board
        # that could not be created because its main table collided with
        # something would be a board lost to bookkeeping — and the row is
        # recoverable by the backfill, while the board is not.
        try:
            db.add(SavedView(board_id=b.id, owner_id=None, kind="main",
                             name=MAIN_VIEW_NAME, visibility="public",
                             filters={"view": "table"}, position=-1))
            db.commit()
        except IntegrityError:
            db.rollback()
        db.refresh(b)
        return {"id": b.id, "name": b.name, "icon": b.icon, "views": _board_views(b), "my_role": "admin"}

# ── Import a board from a CSV / Excel file ───────────────────────────────
# First row = column headers. First column = the item name; every other column
# becomes a board column whose type is inferred from its values (number / date /
# text). One item is created per data row. Reuses the same board scaffolding as
# create_board (3 default groups, creator becomes admin).

def _imp_to_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def _imp_to_date_iso(v):
    import datetime as _dt
    if isinstance(v, _dt.datetime):
        return v.date().isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


# A monday Excel export writes a file cell as the file's ADDRESS, several of
# them comma-joined in one cell. As text that is a 2,000-character cell nobody
# can read; as a file column it is what it is — named chips, each opening the
# file in monday. The shape is monday's own asset address, so an ordinary link
# column ("קישור לדף הבית") is not mistaken for an attachment.
# The path is anything but a comma, because monday writes the file's real name
# into the address without escaping it: ".../resources/1476615869/הפרויקטים שלנו .docx"
# has a space in it, and requiring "no whitespace" matched none of her files.
_MONDAY_ASSET = re.compile(
    r"^https://[^/\s]+\.monday\.com/(?:protected_static|resources)/[^,]+$|"
    r"^https://files-monday-com\.s3[^/\s]*\.amazonaws\.com/[^,]+$")


def _imp_asset_urls(v):
    """The monday file addresses in one cell, or None if that is not what it is."""
    parts = [p.strip() for p in str(v or "").split(",")]
    parts = [p for p in parts if p]
    if not parts or not all(_MONDAY_ASSET.match(p) for p in parts):
        return None
    return parts


def _imp_file_name(url):
    """The file's name out of its address — the last segment, un-escaped."""
    path = urllib.parse.urlparse(url).path
    name = urllib.parse.unquote((path.rsplit("/", 1)[-1] or "").strip())
    return name[:255] or "קובץ"


def _imp_infer_type(values):
    non_empty = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_empty:
        return "text"
    if all(_imp_asset_urls(v) for v in non_empty):
        return "files"
    if all(_imp_to_number(v) is not None for v in non_empty):
        return "number"
    if all(_imp_to_date_iso(v) is not None for v in non_empty):
        return "date"
    return "text"


def _imp_coerce(v, ctype):
    if v is None:
        return None
    if ctype == "number":
        return _imp_to_number(v)
    if ctype == "date":
        return _imp_to_date_iso(v)
    if ctype == "files":
        urls = _imp_asset_urls(v) or []
        return [{"name": _imp_file_name(u), "url": u} for u in urls] or None
    s = str(v).strip()
    return s or None


# The grey band this app's export writes over a sub-item block, naming the
# columns those sub-items have. It is a header, not an item.
IMPORT_SUBHEAD_FILL = "FFEDEFF5"


def _imp_cell_paint(cell):
    """The colour a sheet painted a cell with, as #rrggbb — or None.

    A group's row is coloured in every file that has groups at all: monday
    fills it, and this app's own export writes the colour on the text. Either
    is the group's colour, and reading it is what lets a board come back the
    colour it left. Read for the group rows only, so a fill anywhere else is
    nobody's business.

    White and black are not read as colours: they are what a sheet looks like
    when nothing was painted, and a group headed "ללא צבע" white-on-white is
    worse than one wearing a default.
    """
    def hexof(c):
        rgb = getattr(c, "rgb", None)
        # openpyxl answers a theme or indexed colour with no usable rgb at all,
        # and the themed palette is not in the file to resolve it against.
        if not isinstance(rgb, str) or len(rgb) != 8:
            return None
        if rgb[:2] == "00":              # fully transparent: nothing was painted
            return None
        h = "#" + rgb[2:].lower()
        return None if h in ("#ffffff", "#000000") else (h if _valid_hex(h) else None)

    try:
        fill = getattr(cell, "fill", None)
        if fill is not None and getattr(fill, "patternType", None) == "solid":
            c = hexof(fill.fgColor)
            # the grey sub-item band is this app's own furniture, not a colour
            # anybody chose for a group
            if c and c != "#" + IMPORT_SUBHEAD_FILL[2:].lower():
                return c
        font = getattr(cell, "font", None)
        if font is not None and font.color is not None:
            return hexof(font.color)
    except (AttributeError, TypeError, ValueError):
        pass
    return None


def _imp_parse_tabular(raw, filename, with_shape=False):
    """Rows (each a list of cell values) from CSV or XLSX bytes.

    With `with_shape`, each row is paired with what the sheet says it is:
    `(level, is_band, paint, values)`. A board exported from here indents the
    first cell by two per level — a group at 0, an item at 1, a sub-item at 2 —
    and paints the sub-item column band grey. Both survive a read-back (the
    outline levels do not, in the streaming reader), so they are what the
    hierarchy is read from. A file with no indentation reads as level 0
    throughout, which is what a flat CSV is.

    `paint` is the colour the sheet gave the row's first cell, which on a group
    row is the group's own colour — the thing a board is recognised by before
    any of it is read. A CSV carries no colour, and says None.
    """
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        import io as _io
        from openpyxl import load_workbook
        wb = load_workbook(_io.BytesIO(raw), data_only=True, read_only=True)
        ws = wb.active
        if not with_shape:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            wb.close()
            return rows
        shaped = []
        for cells in ws.iter_rows():
            first = cells[0] if cells else None
            indent = 0
            band = False
            try:
                indent = int((first.alignment.indent or 0) if first is not None else 0)
                fill = getattr(first, "fill", None)
                band = bool(fill is not None and getattr(fill, "fgColor", None) is not None
                            and str(fill.fgColor.rgb or "").upper() == IMPORT_SUBHEAD_FILL)
            except (AttributeError, TypeError, ValueError):
                pass
            paint = _imp_cell_paint(first) if first is not None else None
            shaped.append((indent // 2, band, paint, [c.value for c in cells]))
        wb.close()
        return shaped
    # CSV / TSV / plain text
    import csv as _csv, io as _io
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1255", "iso-8859-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    sample = text[:4096]
    delim = ","
    if sample.count(";") > sample.count(","):
        delim = ";"
    elif sample.count("\t") > max(sample.count(","), sample.count(";")):
        delim = "\t"
    rows = [list(r) for r in _csv.reader(_io.StringIO(text), delimiter=delim)]
    # a CSV carries no indentation, so every row is flat — a parent column is the
    # only way such a file can name a hierarchy
    return [(0, False, None, r) for r in rows] if with_shape else rows


def _imp_formula_text(raw, filename, shaped):
    """Fill the cells a spreadsheet left uncalculated with the formula itself.

    Excel stores two things for a formula cell: the formula, and the value it
    last worked out. A file written by a program — or one never opened since the
    formula was typed — carries the formula and no value, and read for values
    those cells come back empty. A whole column of them then arrives as a column
    nobody ever filled, which is the opposite of what the file says.

    So where there is no value, the formula is what the file says about that
    cell, and it comes across as text — "=B2*2", verbatim, in a text column.
    Nothing is computed here: a spreadsheet's formula is over cell addresses
    (B2), and the addresses are gone the moment the rows become items.

    Returns (shaped, how many cells were filled this way).
    """
    if not (filename or "").lower().endswith((".xlsx", ".xlsm")):
        return shaped, 0                     # a CSV holds text, formulas included
    import io as _io
    import zipfile
    try:
        # Reading the workbook a second time is not free, so first ask the file
        # whether it has any formulas at all: the sheet's XML carries an <f>
        # element per formula cell, and the board is the first sheet.
        with zipfile.ZipFile(_io.BytesIO(raw)) as z:
            sheets = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))
            if not sheets or b"<f" not in z.read(sheets[0]):
                return shaped, 0
    except Exception:                        # noqa: BLE001 — not a readable zip; the caller reports
        return shaped, 0
    from openpyxl import load_workbook
    try:
        wb = load_workbook(_io.BytesIO(raw), data_only=False, read_only=True)
    except Exception:                        # noqa: BLE001
        return shaped, 0
    try:
        src = [list(r) for r in wb.active.iter_rows(values_only=True)]
    finally:
        wb.close()
    filled = 0
    for i, (*_shape, vals) in enumerate(shaped):
        if i >= len(src):
            break
        for j, v in enumerate(vals):
            if v is not None and str(v).strip() != "":
                continue
            f = src[i][j] if j < len(src[i]) else None
            if isinstance(f, str) and f.startswith("="):
                vals[j] = f
                filled += 1
    return shaped, filled


def _imp_conversation_sheet(raw, filename):
    """The rows of the workbook's conversation sheet, when it has one.

    A board exported from here writes its items on one sheet and its
    conversation on another; reading only the first sheet back meant every
    exported board lost its conversation on the way home. The sheet is found by
    name and, failing that, by its headers — a file someone rebuilt by hand does
    not have to guess at our sheet name.
    """
    if not (filename or "").lower().endswith((".xlsx", ".xlsm")):
        return []                                # a CSV holds one sheet, the items
    import io as _io
    from openpyxl import load_workbook
    try:
        wb = load_workbook(_io.BytesIO(raw), data_only=True, read_only=True)
    except Exception:                            # noqa: BLE001 — the caller reports it
        return []
    try:
        want = {"פריט", "תוכן"}
        best = None
        for ws in wb.worksheets:
            if ws is wb.worksheets[0]:
                continue                         # the first sheet is the board itself
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if not rows:
                continue
            head = {str(c).strip() for c in rows[0] if c is not None}
            if ws.title.strip() in ("שיחות", "שיחה") or want <= head:
                best = rows
                break
        return best or []
    finally:
        wb.close()


def _imp_files_sheet(raw, filename):
    """The rows of the workbook's file sheet, when it has one.

    A file cell holds the file's name, because that is what a grid can show. The
    address it is served at does not fit in the grid at all, so a board exported
    from here writes it on a sheet of its own — the same answer the conversation
    got. Read back, the files come home as files; ignored, they come home as
    names with nothing behind them.
    """
    if not (filename or "").lower().endswith((".xlsx", ".xlsm")):
        return []
    import io as _io
    from openpyxl import load_workbook
    try:
        wb = load_workbook(_io.BytesIO(raw), data_only=True, read_only=True)
    except Exception:                            # noqa: BLE001 — the caller reports it
        return []
    try:
        want = {"פריט", "שם הקובץ"}
        for ws in wb.worksheets:
            if ws is wb.worksheets[0]:
                continue                         # the first sheet is the board itself
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if not rows:
                continue
            head = {str(c).strip() for c in rows[0] if c is not None}
            if ws.title.strip() == "קבצים" or want <= head:
                return rows
        return []
    finally:
        wb.close()


def _imp_attach_files(db, rows, tasks, board, files, max_cols):
    """Hang an imported file sheet on the items and columns it names.

    Matched by name — the item's title and the column's title — because the ids
    in the file belong to the board it came from. A column the sheet names that
    came in as text IS that file column: the grid could only carry its names, so
    the names are replaced by the files themselves.
    """
    out = {"attached": 0, "unmatched_items": [], "unmatched_cols": []}
    if not rows:
        return out
    head = [str(c).strip() if c is not None else "" for c in rows[0]]
    idx = {h: i for i, h in enumerate(head)}
    if not all(h in idx for h in ("פריט", "שם הקובץ")):
        return out
    cell = lambda r, h: (str(r[idx[h]]).strip()
                         if h in idx and idx[h] < len(r) and r[idx[h]] is not None else "")

    by_title = {}
    for t in tasks:
        by_title.setdefault((t.title or "").strip(), t)
    settings = dict(board.settings or {})
    cols = [dict(c) for c in (settings.get("columns") or [])]
    by_col = {(c.get("title") or "").strip(): c for c in cols if c["id"].startswith("col_")}
    custom = [c for c in cols if c["id"].startswith("col_")]

    # item -> column -> [entries], gathered first so one cell is written once
    wanted, missing_items, missing_cols = {}, set(), set()
    for r in rows[1:]:
        title, cname = cell(r, "פריט"), cell(r, "עמודה")
        name, url = cell(r, "שם הקובץ"), cell(r, "כתובת")
        if not (name or url):
            continue
        t = by_title.get(title)
        if t is None:
            missing_items.add(title or "—")
            continue
        col = by_col.get(cname)
        if col is None:
            if len(custom) >= max_cols - 1:
                missing_cols.add(cname or "—")
                continue
            col = {"id": "col_" + uuid.uuid4().hex[:8], "type": "files", "title": cname or "קבצים",
                   "options": None, "formula": None, "connect": None, "copy_mode": None,
                   "perms": {}}
            cols.append(col)
            custom.append(col)
            by_col[cname] = col
        col["type"] = "files"           # a file column, whatever the grid made of it
        wanted.setdefault(t.id, {}).setdefault(col["id"], []).append({"name": name, "url": url})

    if not wanted and not missing_items and not missing_cols:
        return out
    settings["columns"] = cols
    board.settings = settings
    tasks_by_id = {t.id: t for t in tasks}
    for tid, per_col in wanted.items():
        t = tasks_by_id[tid]
        cf = dict(t.custom_fields or {})
        for cid, entries in per_col.items():
            got = _import_attachments(db, entries, files["budget"], files["stats"])
            cf[cid] = got
            out["attached"] += len(got)
        t.custom_fields = cf
    out["unmatched_items"] = sorted(missing_items)[:20]
    out["unmatched_cols"] = sorted(missing_cols)[:20]
    return out


def _imp_attach_conversation(db, rows, tasks, actor_id, budget):
    """Write an imported conversation onto the items it names.

    Rows are matched to items by name, which is the only handle a file and a
    freshly created board share — the ids in the file belong to the board it
    came from. A row naming an item that is not here is counted and reported
    rather than being attached to something arbitrary.

    Threading survives the trip: the file gives every message an id and names
    the one it answers, so roots are written first and replies are hung off
    whatever those ids became here.
    """
    if not rows:
        return {"messages": 0, "replies": 0, "unmatched_items": [], "unmatched_people": []}
    head = [str(c).strip() if c is not None else "" for c in rows[0]]
    idx = {h: i for i, h in enumerate(head)}
    need = ("פריט", "תוכן")
    if not all(h in idx for h in need):
        return {"messages": 0, "replies": 0, "unmatched_items": [], "unmatched_people": []}
    cell = lambda r, h: (str(r[idx[h]]).strip()
                         if h in idx and idx[h] < len(r) and r[idx[h]] is not None else "")

    by_title = {}
    for t in tasks:
        by_title.setdefault((t.title or "").strip(), t)
    names = {}
    for u in db.query(User).all():
        if u.name:
            names.setdefault(u.name.strip().lower(), u.id)
        if u.email:
            names.setdefault(u.email.strip().lower(), u.id)

    def when_of(r):
        v = r[idx["נכתב"]] if "נכתב" in idx and idx["נכתב"] < len(r) else None
        if isinstance(v, datetime):
            return v.replace(tzinfo=None)
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
            return None

    made = {"messages": 0, "replies": 0}
    missing_items, missing_people, id_map = set(), set(), {}
    # roots first: a reply can only be hung off a message that already exists
    for pas in (0, 1):
        for r in rows[1:]:
            if budget[0] <= 0:
                break
            parent_src = cell(r, "בתגובה להודעה")
            if bool(parent_src) != bool(pas):
                continue
            title = cell(r, "פריט")
            task = by_title.get(title)
            if task is None:
                if title:
                    missing_items.add(title)
                continue
            body = cell(r, "תוכן")
            files = [{"name": n.strip(), "url": ""} for n in cell(r, "קבצים").split(",") if n.strip()]
            if not body and not files:
                continue
            author = cell(r, "מאת")
            uid = names.get(author.lower()) if author else None
            if author and not uid:
                missing_people.add(author)
            parent_id = id_map.get(parent_src) if parent_src else None
            if parent_src and parent_id is None:
                continue                          # its message is not in this file
            c = Comment(task_id=task.id, user_id=uid, parent_id=parent_id,
                        content=body[:20000], attachments=files[:20],
                        mentions=[], likes=[], seen_by=[],
                        created_at=when_of(r) or datetime.now(timezone.utc).replace(tzinfo=None),
                        origin={"source": "xlsx", "author": author[:120],
                                "external_id": cell(r, "מזהה הודעה")[:40],
                                "matched": bool(uid)})
            db.add(c)
            db.flush()
            src_id = cell(r, "מזהה הודעה")
            if src_id:
                id_map[src_id] = c.id
            budget[0] -= 1
            made["replies" if parent_id else "messages"] += 1
    return {**made, "unmatched_items": sorted(missing_items)[:20],
            "unmatched_people": sorted(missing_people)[:20]}


IMPORT_MAX_ROWS = 2000
# How many columns a board may be imported with. 40 was below what a real
# monday board carries — a 64-column board lost five columns that had data in
# them purely to the ceiling, which is the one kind of loss a migration cannot
# afford. 80 is the width this app's own export already writes at
# (XLSX_MAX_COLS), so a board that can be imported can also be exported whole.
IMPORT_MAX_COLS = 80
# Messages one import may bring in, across every item on the board. A board's
# conversation can be far longer than the board itself, so it gets a ceiling of
# its own — and what it cuts is named in the report rather than just missing.
IMPORT_MAX_MESSAGES = 10000
# ── the files an import brings with it ───────────────────────────────
# monday's export carries a pre-signed link per attachment. Those links work for
# about an hour and then the file is behind monday's auth forever, so the only
# moment the bytes can be brought across is the import itself. What arrives
# without them is a list of file NAMES — enough to see that an item had a spec
# attached, and useless for opening it.
#
# Fetched under a budget, because a board's attachments can dwarf the board:
# past either ceiling the rest keep their names and the report says how many.
IMPORT_MAX_FILES = int(os.getenv("IMPORT_MAX_FILES", "600"))
IMPORT_MAX_FILE_MB = int(os.getenv("IMPORT_MAX_FILE_MB", "150"))
IMPORT_FILE_TIMEOUT = 20            # seconds per file
# How many attachments are fetched at once. The files are an import's only
# outbound calls and they do not depend on each other, so the wait is the one
# thing worth overlapping. Eight is modest on purpose: the other side is
# monday's S3, and an import is not the only thing this server is doing.
IMPORT_FILE_WORKERS = int(os.getenv("IMPORT_FILE_WORKERS", "8"))
# The upload ceiling for an import. It was 8MB, and a 320-item board exported
# from monday rejected at 11.7MB — of which 8MB was the indentation Postman adds
# when a response is saved from its pretty view. The content was 3.66MB. A limit
# that turns on how a file was saved rather than on what is in it is a limit that
# rejects the right board for the wrong reason, so there is room for a board
# several times that size, pretty-printed.
IMPORT_MAX_UPLOAD_MB = int(os.getenv("IMPORT_MAX_UPLOAD_MB", "32"))

# Only monday's own asset hosts. The URLs come out of a file the user supplied,
# and fetching whatever it names would let an import point this server at an
# address inside the network it runs in.
def _import_host_allowed(host):
    host = (host or "").lower()
    return (host == "monday.com" or host.endswith(".monday.com")
            or (host.startswith("files-monday-com.s3.") and host.endswith(".amazonaws.com"))
            or host == "files-monday-com.s3.amazonaws.com")


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A pre-signed asset link does not redirect. Refusing to follow one closes
    the hole where an allowed host bounces the fetch somewhere it should not go."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_IMPORT_OPENER = urllib.request.build_opener(_NoRedirects)


# Consecutive failures after which the import stops trying. When a file's links
# have expired, every link in that file has expired — and discovering that 300
# times over cost three minutes of an import that had nothing else to do.
IMPORT_FILE_FAIL_STREAK = 5


def _stored_file_token(url):
    """The token in one of this app's own file addresses, or None.

    `/api/files/<32 hex>` is where an uploaded file is served from, so a file
    cell in a board exported from here names a blob this database already holds.
    """
    m = re.fullmatch(r"(?:https?://[^/]+)?/api/files/([0-9a-f]{8,64})", (url or "").strip())
    return m.group(1) if m else None


def _signed_url_expired(url, now=None):
    """Has this pre-signed link already lapsed, going by the link itself?

    monday's asset URLs are S3 signatures carrying the moment they were minted
    and how long they last (`X-Amz-Date` + `X-Amz-Expires`, an hour). Reading it
    is free and exact, which beats spending a round trip per file to be told 403.
    """
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url or "").query)
        minted = (q.get("X-Amz-Date") or [""])[0]
        window = int((q.get("X-Amz-Expires") or ["0"])[0])
        if not minted or window <= 0:
            return False                       # not a signed link — let the fetch decide
        t = datetime.strptime(minted, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return (now or datetime.now(timezone.utc)) > t + timedelta(seconds=window)
    except (ValueError, TypeError, OverflowError):
        return False


def _fetch_import_file(url):
    """(bytes, content_type) for one attachment, or None if it cannot be had.

    Never raises: an expired link, a redirect, a host we do not fetch from and a
    file over the per-file ceiling all mean the same thing to the caller — this
    one keeps its name only.
    """
    try:
        parts = urllib.parse.urlparse(url or "")
        if parts.scheme != "https" or not _import_host_allowed(parts.hostname):
            return None
        req = urllib.request.Request(url, headers={"User-Agent": "CODE-CAL-MISSIONS/import"})
        with _IMPORT_OPENER.open(req, timeout=IMPORT_FILE_TIMEOUT) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            # A monday link that needs a session does not answer 401 — it answers
            # 200 with the login page. Stored, that is a docx-shaped file holding
            # monday's HTML, which is worse than the name on its own: it opens,
            # and it is not the file.
            if ctype == "text/html":
                return None
            data = resp.read(MAX_UPLOAD_BYTES + 1)
            if not data or len(data) > MAX_UPLOAD_BYTES:
                return None
            return data, ctype
    except Exception:                              # noqa: BLE001 — see the docstring
        return None


def _import_fetchable(url):
    """Whether this address is one the import would spend a round trip on.

    The same questions _import_attachments asks before fetching, in the same
    order — kept here so the prefetch warms exactly the set the import would
    have fetched itself, and nothing besides.
    """
    if not url or _stored_file_token(url):
        return False
    parts = urllib.parse.urlparse(url)
    if parts.path.startswith("/protected_static/") or not _import_host_allowed(parts.hostname):
        return False
    return not _signed_url_expired(url)


def _prefetch_import_files(urls, budget, workers=None):
    """Fetch an import's attachments together rather than one after another.

    They were fetched in the order the items are read, one at a time, inside the
    request: a fresh monday export of 320 items carried 307 live S3 links, and
    307 round trips end to end is minutes of a request that spends them waiting.
    The bytes do not depend on each other. Fetched at once, the import then
    walks the items exactly as before and finds each file already in hand.

    What comes back is {url: (bytes, content_type) or None} — None meaning the
    fetch failed, which is what the caller does with a failed fetch anyway. The
    queue is the file's own order, deduplicated; the pool is bounded; and
    submission stops once the import's byte ceiling is accounted for, because a
    prefetch that pulled more than the import may keep would spend exactly the
    time this exists to save.
    """
    seen, queue = set(), []
    for u in urls:
        if u and u not in seen and _import_fetchable(u):
            seen.add(u)
            queue.append(u)
    queue = queue[:max(0, budget[0])]
    if not queue:
        return {}
    left, lock, out, streak = [budget[1]], threading.Lock(), {}, [0]

    def one(u):
        with lock:
            # the run-of-failures guard, honoured here too: if the first handful
            # cannot be had the rest cannot either, and the point of that rule is
            # not to spend a timeout per file proving it. Up to one pool's worth
            # are already in flight when the run trips — but in flight together,
            # so it costs one timeout rather than one each.
            if left[0] <= 0 or streak[0] >= IMPORT_FILE_FAIL_STREAK:
                return u, None
        got = _fetch_import_file(u)
        with lock:
            if got:
                streak[0] = 0
                left[0] -= len(got[0])
            else:
                streak[0] += 1
        return u, got

    n = max(1, min(workers or IMPORT_FILE_WORKERS, len(queue)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=n,
                                               thread_name_prefix="import-file") as pool:
        for u, got in pool.map(one, queue):
            out[u] = got
    return out


def _attachment_urls(parsed, columns):
    """Every address this import might fetch, in the order the file states them.

    The cells of the file columns and the assets hanging off the conversation —
    on the items and on their sub-items alike, which is where half of them were.
    """
    keys = [c["key"] for c in columns if c["type"] == "files"]
    out = []
    def msgs(src):
        for up in src.get("updates") or []:
            for m in [up] + (up.get("replies") or []):
                out.extend((a or {}).get("url") or "" for a in (m.get("assets") or []))
    for row in parsed["items"]:
        for src in [row] + (row.get("subitems") or []):
            for k in keys:
                for f in src["values"].get(k) or []:
                    out.append((f or {}).get("url") or "")
            msgs(src)
    return out


def _import_attachments(db, files, budget, stats, cache=None):
    """Bring a list of [{name,url}] across, and return it pointing here.

    `budget` is [files_left, bytes_left], shared by the whole import. An entry
    whose bytes could not be fetched keeps its name and its original link, so
    nothing is lost that was there before — it simply is not openable.
    """
    out = []
    for f in files or []:
        name = (f.get("name") or "").strip() or "קובץ"
        url = f.get("url") or ""
        # An attachment that could not be fetched keeps its name and the address
        # it had, and now says why. The two kinds of leftover are not the same
        # thing and must not look the same: a /protected_static/ link opens the
        # file in monday, where the user IS signed in, while an expired signature
        # can never open again, for anyone. Handed over as a plain link, that one
        # opens S3's XML complaint — "Request has expired" — which reads as a
        # broken app rather than as a file that did not come across.
        def keep(why, dead=True):
            one = {"name": name[:255], "url": url, "why": why}
            if dead:
                one["dead"] = True
            out.append(one)
            stats[why] = stats.get(why, 0) + 1
        if not url:
            out.append({"name": name[:255], "url": ""})
            continue
        # ── the file is already stored here ───────────────────────────────
        # A board exported from here and imported back names its files by the
        # address they are served at. The bytes never left, so nothing is
        # fetched and nothing is copied — the cell points at the same blob.
        token = _stored_file_token(url)
        if token:
            if db.query(UploadedFile.id).filter(UploadedFile.token == token).first():
                out.append({"name": name[:255], "url": url})
                stats["reused"] = stats.get("reused", 0) + 1
            else:
                out.append({"name": name[:255], "url": "", "why": "gone", "dead": True})
                stats["gone"] = stats.get("gone", 0) + 1
            continue
        # ── a link this server cannot fetch ───────────────────────────────
        # monday's /protected_static/ address is the file behind a LOGIN, and the
        # login is the user's, not this server's: unauthenticated it answers 200
        # with monday's sign-in page. It is what a monday Excel export writes for
        # every attachment, so the name and the link are kept — a chip that opens
        # the file in monday, where the user is signed in — and no round trip is
        # spent being told so. Anything on a host this server does not fetch from
        # is the same answer.
        parts = urllib.parse.urlparse(url)
        if (parts.path.startswith("/protected_static/")
                or not _import_host_allowed(parts.hostname)):
            keep("linked", dead=False)      # this one still opens, in monday
            continue
        # the two questions that can be answered without a round trip
        if _signed_url_expired(url):
            keep("expired")
            continue
        if stats.get("streak", 0) >= IMPORT_FILE_FAIL_STREAK:
            keep("failed")
            continue
        if budget[0] <= 0 or budget[1] <= 0:
            got = None
        elif cache is not None and url in cache:
            got = cache[url]      # already in hand — see _prefetch_import_files
        else:
            got = _fetch_import_file(url)
        if got is None:
            stats["streak"] = stats.get("streak", 0) + 1
            keep("failed")
            continue
        stats["streak"] = 0
        data, ctype = got
        if len(data) > budget[1]:
            keep("over_budget")
            continue
        token = uuid.uuid4().hex
        media_type, _ = _safe_media_type(ctype)
        db.add(UploadedFile(token=token, name=name[:255], content_type=media_type,
                            data=data, size=len(data)))
        budget[0] -= 1
        budget[1] -= len(data)
        stats["imported"] = stats.get("imported", 0) + 1
        stats["bytes"] = stats.get("bytes", 0) + len(data)
        out.append({"name": name[:255], "url": f"/api/files/{token}"})
    return out


# Column headings that mean "the item this row belongs under". A CSV cannot
# indent, so naming the parent is the only way such a file can say it.
# The three columns the system issues on its own — the item's identifier, when
# it was created and by whom. An imported board gets them like any other board,
# but AFTER the columns that came out of the file: nobody typed them, nobody
# asked for them, and in front of the board they read as data that came from
# somewhere. A function, because each import needs its own dicts to mutate.
def IMPORT_SYSTEM_COLS():
    return [{"id": "sys_item_id", "type": "item_id", "title": "מספר מזהה"},
            {"id": "sys_created_at", "type": "created_at", "title": "מועד יצירה"},
            {"id": "sys_created_by", "type": "created_by", "title": "יוצר הרשומה"}]


IMPORT_PARENT_HEADERS = {"פריט אב", "תת פריט של", "תת־פריט של", "תת-פריט של",
                         "שייך לפריט", "parent", "parent item", "sub-item of",
                         "subitem of", "sub item of"}


# Column headings that mean "the group this row belongs to". A flat sheet — a
# CSV, or one built by hand — cannot indent and has no group rows, so a column
# naming the group is the only way such a file can say how the board is divided.
IMPORT_GROUP_HEADERS = {"קבוצה", "שם הקבוצה", "קבוצת", "קיבוץ", "group",
                        "group name", "group title", "board group"}

# What monday calls the column it writes its sub-items' names into. It is not a
# column of the board — the sub-items come in as themselves, under their items —
# so it is the same names a second time, comma-joined, as text.
IMPORT_SUBITEMS_HEADERS = {"subitems", "sub-items", "sub items", "subtasks",
                           "תתי פריטים", "תתי־פריטים", "תתי-פריטים",
                           "תת פריטים", "תתי משימות"}


def _imp_monday_layout(shaped):
    """monday's own Excel/CSV export, read as the divided board it describes.

    monday does not write one table. It writes the board's name on a line of its
    own and then, for every group, that group's name on a line of its own
    followed by a fresh copy of the header row:

        ניהול תוכן אתר החברה           ← the board
        עליה לאוויר - יוני             ← a group
        Name | Subitems | מטפל | …     ← the header
        דף הבית | … | …                ← an item
        Subitems | Name | מטפל | …     ← the sub-item header (a "band")
             | הפרויקטים שלנו | …      ← a sub-item
        באגים                          ← the next group
        Name | Subitems | מטפל | …     ← the header, again

    Read as one flat table from row 0 — which is what happened until now — the
    board's NAME becomes the header row: every column arrives titled "עמודה 3",
    the real header and each group name arrive as items, the sub-items arrive as
    nameless items, and the whole board lands in one invented group. Nothing
    about the file is unclear; it states its division on every one of those
    lines.

    Returns `(title, header, body, summaries)`, the body in the same `(level,
    is_band, paint, values)` shape a board exported from here is already read in — a
    group at 0, an item at 1, a sub-item at 2 — so everything downstream of here
    is unchanged. A sheet that is not this layout returns None and is read
    exactly as before: the first row its header, every row under it an item.
    """
    def txt(vals):
        return [("" if c is None else str(c).strip()) for c in vals]

    rows = [txt(v) for *_, v in shaped]
    if len(rows) < 3:
        return None
    filled = [sum(1 for c in r if c) for r in rows]
    # a line carrying one cell, and that cell the first: a name, not a row
    lone = [f == 1 and bool(r and r[0]) for r, f in zip(rows, filled)]
    head = next((i for i, f in enumerate(filled) if f >= 3), None)
    # the header sits under the board's name, and under the first group's name
    # when there is one. Anything else — a header on row 0, a preamble longer
    # than that — is not this layout.
    if head is None or head not in (1, 2) or not all(lone[:head]):
        return None
    if head + 1 >= len(rows):
        return None
    header = rows[head]
    labels = [c for c in header if c]
    name_lbl = header[0]
    sub_lbl = header[1] if len(header) > 1 else ""

    def is_header(r):
        return [c for c in r if c] == labels

    def is_band(r):
        # the sub-item header monday writes: its own column's title first, the
        # item-name column's title second, and the sub-item columns after them
        return bool(sub_lbl) and len(r) > 1 and r[0] == sub_lbl and r[1] == name_lbl

    body, in_band, i, summaries = [], False, head + 1, 0
    if head == 2:
        body.append((0, False, shaped[1][2], shaped[1][3]))  # the group this header is for
    while i < len(shaped):
        r, vals, paint = rows[i], shaped[i][3], shaped[i][2]
        # A name on a line of its own, with the header repeated beneath it, is
        # how monday says "a new group starts here". The header-beneath is what
        # tells it apart from an item nobody filled anything in for.
        if lone[i] and i + 1 < len(rows) and is_header(rows[i + 1]):
            body.append((0, False, paint, vals))
            in_band, i = False, i + 2                # the repeat is not a row of the board
            continue
        if is_header(r):
            i += 1
            continue
        if is_band(r):
            body.append((2, True, None, vals))
            in_band, i = True, i + 1
            continue
        if in_band and not r[0]:
            body.append((2, False, None, vals))      # a sub-item: its name is in the second cell
            i += 1
            continue
        if not r[0] and not (len(r) > 1 and r[1]):
            # monday closes each group with a summary line — no name anywhere, and
            # in the date column the group's rolled-up range ("2024-05-05 to
            # 2024-05-30"). Imported, that is a "פריט 38" holding one date that
            # belongs to nobody; it was four of the forty-one items her real file
            # "had". A row with a name in the second cell is a sub-item whose
            # band went unread, and it is kept — counted as one of these, it
            # would be a row of the board dropped without a word.
            summaries += 1
            i += 1
            continue
        in_band = False
        body.append((1, False, None, vals))
        i += 1
    return rows[0][0], shaped[head][3], body, summaries


# Colours handed to imported status/dropdown options. Same list the status
# picker offers, so an imported column looks like one made here by hand.
IMPORT_PALETTE = [
    "#1AC877", "#FBAA47", "#DB2D4C", "#565BDC", "#5A9CF9", "#9C51DB", "#E30073",
    "#53CCC5", "#FD6C42", "#9DD335", "#276FDC", "#FD5AC3", "#117FB3", "#7E5348",
    "#B93255", "#FECA29", "#6ACDFD", "#784DCF", "#0F7F4D", "#9BADBC",
]


def _import_comment(db, task, msg, by_token, parent_id=None, files=None, flush=True):
    """One imported message, written onto the item it belongs to.

    The author is matched to an account by e-mail first and by name second — the
    same order the people columns use, for the same reason. An author with no
    account here keeps their name through `origin` instead of being replaced by
    whoever ran the import: a conversation is a record of who said what, and an
    import that rewrites that is worse than one that drops it.
    """
    uid = (by_token.get((msg.get("email") or "").lower())
           or by_token.get((msg.get("author") or "").lower()))
    when = None
    raw = (msg.get("created_at") or "").strip()
    if raw:
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            when = None
    atts = [{"name": a.get("name", ""), "url": a.get("url", "")}
            for a in (msg.get("assets") or [])][:20]
    if files is not None:
        # the bytes, while monday's links still work — see _import_attachments
        atts = _import_attachments(db, atts, files["budget"], files["stats"],
                                   files.get("cache"))
    c = Comment(task_id=task.id, user_id=uid, parent_id=parent_id,
                content=(msg.get("body") or "")[:20000],
                attachments=atts,
                mentions=[], likes=[], seen_by=[],
                created_at=when or datetime.now(timezone.utc).replace(tzinfo=None),
                origin={"source": "monday", "author": (msg.get("author") or "")[:120],
                        "external_id": (msg.get("external_id") or "")[:40],
                        "matched": bool(uid)})
    db.add(c)
    # Flushed only when the row's own id is about to be needed — a message whose
    # replies hang off it. A reply is nobody's parent, and flushing it on its own
    # made every single imported message a round trip of its own; left pending,
    # they go out together with whatever flush comes next.
    if flush:
        db.flush()
    return c


def _import_conversation(db, task, updates, by_token, budget, files=None):
    """An item's whole conversation, replies kept under the message they answer.

    `budget` is a one-element list — the import's remaining message allowance,
    shared across every item so a single board cannot write an unbounded number
    of rows. Returns how many messages were written.
    """
    made = 0
    for up in updates or []:
        if budget[0] <= 0:
            break
        root = _import_comment(db, task, up, by_token, files=files)
        budget[0] -= 1
        made += 1
        for rep in up.get("replies") or []:
            if budget[0] <= 0:
                break
            _import_comment(db, task, rep, by_token, parent_id=root.id, files=files,
                            flush=False)
            budget[0] -= 1
            made += 1
    return made


def _import_monday_board(raw, filename, name, environment_id, folder_id, actor_id):
    """Build a board out of a monday.com API response.

    The column budget is the one the tabular importer already works to: the item
    name plus IMPORT_MAX_COLS - 1 custom columns. Nothing raises it. When the
    file holds more than fits, the fullest columns win and the rest come back in
    the report, named — so the drop is a decision the user can see rather than a
    silence they discover weeks later.
    """
    try:
        parsed = import_monday.parse(raw, IMPORT_MAX_COLS - 1)
    except import_monday.NotMondayJson as e:
        raise HTTPException(400, f"הקובץ אינו תשובת API של מאנדיי ({e})")
    except (ValueError, TypeError):
        raise HTTPException(400, "לא ניתן לקרוא את הקובץ — ודא שהוא JSON תקין")
    if not parsed["items"]:
        raise HTTPException(400, "לא נמצאו פריטים בקובץ")
    if len(parsed["items"]) > IMPORT_MAX_ROWS:
        # a cut this size is not something to notice by counting rows afterwards
        parsed["report"]["rows_dropped"] = len(parsed["items"]) - IMPORT_MAX_ROWS
        parsed["items"] = parsed["items"][:IMPORT_MAX_ROWS]

    with Session(engine) as db:
        env_id = environment_id
        if not env_id:
            primary = db.query(Environment).filter(Environment.is_primary == True).first()
            env_id = primary.id if primary else None
        if not (_cap(db, actor_id, "create_board") or _can_manage_env(db, env_id, actor_id)):
            raise HTTPException(403, "אין לך הרשאה ליצור לוח חדש")

        # ── people: monday gives a display name, and an e-mail when the export
        # carries one; we need an account. E-mail is tried first — it is the half
        # that survives someone changing their display name, and two people can
        # share a name. Anyone with no account here is named in the report rather
        # than being dropped on the floor in silence.
        people_wanted = set()
        for r in parsed["items"]:
            for src in [r] + r["subitems"]:
                for c in parsed["columns"]:
                    if c["type"] == "people":
                        people_wanted.update(src["values"].get(c["key"]) or [])
                # whoever wrote the item's conversation is a person to look for
                # as much as whoever was assigned to it
                for up in src.get("updates") or []:
                    for msg in [up] + (up.get("replies") or []):
                        people_wanted.update(t for t in (msg.get("email"), msg.get("author")) if t)
        by_token = {}
        if people_wanted:
            low = [t.lower() for t in people_wanted]
            for u in db.query(User).filter(or_(func.lower(User.email).in_(low),
                                               func.lower(User.name).in_(low))).all():
                if u.email:
                    by_token.setdefault(u.email.lower(), u.id)
                if u.name:
                    by_token.setdefault(u.name.lower(), u.id)
        unmatched = sorted(t for t in people_wanted if t.lower() not in by_token)

        # ── the columns ──────────────────────────────────────────────────────
        col_ids, custom_cols, sub_used = {}, [], set()
        status_opts = {}   # column key -> {label: the option its cells point at}
        for c in parsed["columns"]:
            cid = "col_" + uuid.uuid4().hex[:8]
            col_ids[c["key"]] = cid
            col = {"id": cid, "type": c["type"], "title": c["title"][:60], "options": None,
                   "formula": c.get("formula"), "connect": None, "copy_mode": None, "perms": {}}
            if c["type"] == "status":
                # through the same normaliser a column edited by hand goes
                # through, so every label gets the stable id a cell points at —
                # renaming the option later then carries its cells with it
                col["options"] = _status_col_options(
                    [{"label": str(o)[:40],
                      "color": IMPORT_PALETTE[j % len(IMPORT_PALETTE)]}
                     for j, o in enumerate(c.get("options") or [])])
                status_opts[c["key"]] = {o["label"]: o for o in (col["options"] or [])}
            elif c["type"] == "dropdown":
                col["options"] = [str(o)[:40] for o in (c.get("options") or [])]
            custom_cols.append(col)
        # Columns that exist on monday's sub-item board and nowhere on the parent
        # one. They are board columns here, shown on the sub-item rows and never
        # on the item — which is the structure the file describes. Without this
        # they stood on every item as well, empty forever.
        sub_only_ids = [col_ids[c["key"]] for c in parsed["columns"] if c.get("sub_only")]

        settings = {
            "views": ["table"],
            # the board's own columns in the board's own order, and the three the
            # system issues after them — see the note in _import_board_file
            "columns": custom_cols + IMPORT_SYSTEM_COLS(),
            # The board's four built-in columns — אחראים, סטטוס, עדיפות,
            # תאריך יעד — are not in the file and nothing in this import fills
            # them. Left showing, they are four columns of "טרם הוגדר" standing
            # in front of the board that was actually imported, and they follow
            # it into every export of it.
            # Hidden, not removed: a board admin turns any of them back on the
            # moment there is something to put in it.
            "col_hidden": ["assignees", "status", "priority", "due"],
            # and the sub-item board's own columns stay on the sub-items
            "sub_only": sub_only_ids,
        }
        base = os.path.splitext(os.path.basename(filename or ""))[0]
        board_name = (name or "").strip() or parsed["board_name"] or base or "לוח מיובא"
        name_from = _board_name_from(name, parsed["board_name"], base)
        maxpos = (db.query(func.max(Board.position))
                  .filter(Board.environment_id == env_id, Board.folder_id == folder_id).scalar())
        dept_id = db.query(Department.id).order_by(Department.id).limit(1).scalar()
        b = Board(name=board_name[:200], description="", department_id=dept_id,
                  environment_id=env_id, folder_id=folder_id,
                  position=(maxpos + 1) if maxpos is not None else 0,
                  board_type=BoardType.KANBAN, icon="\U0001F4CB", color="#0073ea",
                  settings=settings)
        db.add(b)
        db.flush()
        # ── groups: the board's own, when the export carries them ────────────
        # Without `group { id title }` in the query monday says nothing about how
        # the board was divided, and inventing three named stages would be a
        # claim about the file that the file does not make. Everything goes into
        # one group, and that group is left unnamed — a name would be a heading
        # over a division that does not exist. It is renamed or split the moment
        # there is something true to call it.
        #
        # A group's colour is monday's where the file carries it. The header
        # colour is how a board is read before a single name is: a "דחוף" that
        # was red on monday arriving green here is the board saying something
        # it never said. Only a file that did not state one falls back to this
        # app's palette.
        gmap, groups = {}, []
        for i, g in enumerate(parsed["groups"]):
            grp = Group(board_id=b.id, name=g["title"][:200], position=i,
                        color=g.get("color") or IMPORT_PALETTE[i % len(IMPORT_PALETTE)],
                        task_status=TaskStatus.BACKLOG)
            db.add(grp)
            groups.append(grp)
            gmap[g["id"]] = grp
        if not groups:
            grp = Group(board_id=b.id, name="", position=0, color="#579bfc",
                        task_status=TaskStatus.BACKLOG)
            db.add(grp)
            groups.append(grp)
        db.flush()
        g1 = groups[0]

        def cells(values, track_sub=False):
            cf = {"status_unset": True, "priority_unset": True}
            for c in parsed["columns"]:
                v = values.get(c["key"])
                if v is None or v == "" or v == []:
                    continue
                if c["type"] == "status":
                    # A status cell references an option; it does not hold a
                    # word. Written as the bare label monday rendered, it
                    # matches nothing in the column's vocabulary and the board
                    # shows "טרם הוגדר" over data that is in fact there.
                    # The label and colour ride along as the fallback the rest
                    # of the system already uses for an option since removed —
                    # which is also where a label past the column's own ceiling
                    # lands, shown in grey rather than swallowed.
                    o = status_opts.get(c["key"], {}).get(str(v))
                    v = ({"id": o["id"], "label": o["label"], "color": o["color"]} if o
                         else {"label": str(v)[:40], "color": "#c4c4c4"})
                elif c["type"] == "files":
                    # a name is enough to see that an item had a spec attached,
                    # and useless for opening it — so the bytes come too
                    v = _import_attachments(db, v, files["budget"], files["stats"],
                                            files.get("cache"))
                elif c["type"] == "people":
                    # A name with no account here is kept AS the name.
                    #
                    # A monday people cell carries monday's own person id
                    # ({"personsAndTeams":[{"id":11397425}]}) and the export
                    # carries no e-mail to resolve it against, so a display name
                    # character-for-character is the only key there is. On her
                    # board that matched almost nobody — 31 people, one of them
                    # "Deleted member" on 41 items, whom monday itself can no
                    # longer name — and every cell that failed to match was
                    # dropped whole: two columns, 306 and 135 items, arrived
                    # empty over data that is plainly there in monday.
                    #
                    # So the name rides along beside the real ids, as a string.
                    # It is not an assignment and cannot become one by accident:
                    # nothing is notified, nothing is tagged, and the report
                    # still names everyone who did not match. What it is, is the
                    # board saying who was on the item — which is the whole
                    # reason to migrate one.
                    out, seen = [], set()
                    for tok in v:
                        name = str(tok).strip()
                        if not name:
                            continue
                        key = by_token.get(name.lower()) or name
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(key)
                    if not out:
                        continue
                    v = out
                cf[col_ids[c["key"]]] = v
                if track_sub:
                    sub_used.add(col_ids[c["key"]])
            return cf

        made = subs_made = talked = 0
        # the conversation's own ceiling, shared across the whole import
        budget = [IMPORT_MAX_MESSAGES]
        # and the attachments': [files left, bytes left]
        files = {"budget": [IMPORT_MAX_FILES, IMPORT_MAX_FILE_MB * 1024 * 1024],
                 "stats": {}}
        # The attachments, fetched together before the walk begins. Nothing below
        # changes: _import_attachments asks the same questions in the same order
        # and gets the same answers — it just does not wait for them one by one.
        files["cache"] = _prefetch_import_files(
            _attachment_urls(parsed, parsed["columns"]), files["budget"])
        # Identifiers for every row this import writes, minted in one go. Asked
        # per row, each one cost a SELECT ("is this taken on this board?") and
        # the UPDATE that followed the insert — 782 round trips for a board whose
        # every row is being written in this same transaction, and whose answer
        # to that question could only ever be "no": it was created a moment ago
        # and holds nothing.
        uids = iter(_mint_item_uids(len(parsed["items"])
                                    + sum(len(r["subitems"]) for r in parsed["items"])))
        gpos = {}
        # monday's own item id → the task it became. The board's history names
        # items by that id and by nothing else, so this is the only moment the
        # two can be put together.
        by_monday_id = {}
        for row in parsed["items"]:
            grp = gmap.get(row.get("group")) or g1
            pos = gpos[grp.id] = gpos.get(grp.id, -1) + 1
            t = Task(board_id=b.id, group_id=grp.id, title=row["name"][:500],
                     status=TaskStatus.BACKLOG, priority=Priority.MEDIUM, position=pos,
                     created_by=actor_id, custom_fields=cells(row["values"]),
                     item_uid=next(uids), item_uid_board=b.id)
            db.add(t)
            db.flush()
            if row.get("id"):
                by_monday_id[str(row["id"])] = t
            made += 1
            talked += _import_conversation(db, t, row.get("updates"), by_token, budget, files)
            for spos, sub in enumerate(row["subitems"]):
                stask = Task(board_id=b.id, group_id=grp.id, parent_id=t.id,
                             title=sub["name"][:500], status=TaskStatus.BACKLOG,
                             priority=Priority.MEDIUM, position=spos,
                             created_by=actor_id,
                             custom_fields=cells(sub["values"], track_sub=True),
                             item_uid=next(uids), item_uid_board=b.id)
                db.add(stask)
                db.flush()
                subs_made += 1
                talked += _import_conversation(db, stask, sub.get("updates"), by_token,
                                                   budget, files)

        # ── the board's history ──────────────────────────────────────────────
        # Written as the same AuditLog rows the log already reads, so it shows
        # up in both places at once: the item's own לוגים tab and the board-level
        # log. There is one log here, not two.
        #
        # `origin` marks every row as monday's, which is what stops it offering
        # an undo — reverting a change made in monday a year ago would write
        # that value onto the item now, from a button that looks like every
        # other undo. It also keeps the author's name, for the people the
        # account has no match for; the audit has nowhere else to put a person.
        logged, log_unmatched = 0, 0
        for row in parsed.get("activity") or []:
            t = by_monday_id.get(str(row.get("item") or ""))
            if t is None:
                log_unmatched += 1
                continue
            uid = (by_token.get((row.get("email") or "").lower())
                   or by_token.get((row.get("author") or "").lower()))
            field = row.get("field")
            if field == "column":
                cid = col_ids.get(row.get("column") or "")
                if not cid:
                    # the column did not make the trip (its own budget, or a type
                    # with nothing to carry) — so neither can its history
                    log_unmatched += 1
                    continue
                field = "col:" + cid
            when = None
            if row.get("at"):
                try:
                    when = datetime.fromisoformat(str(row["at"]).replace("Z", "+00:00"))
                    when = when.replace(tzinfo=None)
                except ValueError:
                    when = None
            # values go in the shape the log's own reader expects of a column —
            # JSON — so "ריק" stays empty rather than arriving as the word null
            enc = lambda v: json.dumps(v, ensure_ascii=False) if v not in (None, "") else None
            db.add(AuditLog(
                entity_type="task", entity_id=t.id, action=row.get("action") or "update",
                field_name=field, old_value=enc(row.get("old")), new_value=enc(row.get("new")),
                changed_by=uid,
                created_at=when or datetime.now(timezone.utc).replace(tzinfo=None),
                origin={"source": "monday", "event": (row.get("event") or "")[:40],
                        "author": (row.get("author") or "")[:120], "matched": bool(uid)}))
            logged += 1

        if sub_used or sub_only_ids:
            # Sub-items show only the columns they actually carry, in board
            # order. The sub-item-only ones are left out on purpose: the board
            # appends those on its own (settings["sub_only"]), which is the same
            # shape the column picker saves — see removeSubCol in the frontend.
            s2 = dict(b.settings)
            only = set(sub_only_ids)
            s2["sub_cols"] = ["item"] + [c["id"] for c in custom_cols
                                         if c["id"] in sub_used and c["id"] not in only]
            b.settings = s2
        db.add(BoardMember(board_id=b.id, user_id=actor_id, role="admin"))
        db.commit()
        db.refresh(b)

        wanted = parsed["report"].get("updates") or 0
        return {"id": b.id, "name": b.name, "icon": b.icon,
                "items": made, "subitems": subs_made, "columns": len(custom_cols),
                "messages": talked,
                "files": files["stats"].get("imported", 0),
                "report": {**parsed["report"],
                           # the colour each group actually ended up with, beside
                           # the names in `group_names`. The report shows the
                           # groups as the chips they are on the board, which is
                           # the one way "the colours came across" can be checked
                           # at a glance instead of taken on trust.
                           "group_hex": [g.color for g in groups][:40],
                           # the board's name, and which of the three places it
                           # came from — see _board_name_from
                           "board_name": board_name[:200],
                           "board_name_from": name_from,
                           "messages_imported": talked,
                           "files_imported": files["stats"].get("imported", 0),
                           "files_bytes": files["stats"].get("bytes", 0),
                           # a link that had already expired, or a host we do not
                           # fetch from: the name is kept, the file is not here
                           "files_unreachable": files["stats"].get("failed", 0),
                           # a link whose own signature says it lapsed before the
                           # import ran — the one failure worth naming separately,
                           # because the fix is "export and import in one go"
                           "files_expired": files["stats"].get("expired", 0),
                           "files_over_budget": files["stats"].get("over_budget", 0),
                           # a conversation cut by the import's own ceiling, as
                           # opposed to one the file never carried
                           "messages_dropped": max(0, wanted - talked),
                           "people_matched": len(set(by_token.values())),
                           "people_unmatched": unmatched}}


@app.post("/api/boards/import")
async def import_board(file: UploadFile = File(...), name: Optional[str] = Form(None),
                       environment_id: Optional[int] = Form(None),
                       folder_id: Optional[int] = Form(None),
                       actor_id: int = Depends(current_user_id)):
    raw = await file.read()
    if len(raw) > IMPORT_MAX_UPLOAD_MB * 1024 * 1024:
        # The size is said, because "too big" over a file the user believes is
        # small is not something they can act on — and so is the reason it is
        # usually bigger than it looks: a monday response saved from Postman's
        # pretty view is about three times the JSON it holds, all of it
        # indentation, and saving the raw body is the whole fix.
        raise HTTPException(413,
            f"הקובץ גדול מדי — {len(raw) / 1048576:.1f}MB, והמקסימום הוא "
            f"{IMPORT_MAX_UPLOAD_MB}MB. אם שמרת את התשובה מהתצוגה המיופה של פוסטמן, "
            "ההזחה היא כ-70% מהקובץ: שמור את ה-body הגולמי (Raw) ונסה שוב")
    # Reading a workbook and writing a few hundred rows is seconds of CPU and of
    # blocking database calls. Run on the event loop, that is not just this one
    # request being slow: every other request in the app waits behind it — the
    # board someone else is opening, the avatars, the live event stream — which
    # is what makes an import feel like the whole system froze. Off the loop, the
    # import takes exactly as long and nothing else notices.
    return await run_in_threadpool(_import_board_file, raw, file.filename, name,
                                   environment_id, folder_id, actor_id)


def _import_board_file(raw, filename, name, environment_id, folder_id, actor_id):
    # A monday.com API response is JSON, not a table, and carries the column
    # types a CSV export would have flattened to text. It gets its own reader.
    if (filename or "").lower().endswith(".json") or import_monday.looks_like_monday(raw):
        return _import_monday_board(raw, filename, name, environment_id, folder_id, actor_id)
    try:
        shaped = _imp_parse_tabular(raw, filename, with_shape=True)
    except Exception:
        raise HTTPException(400, "לא ניתן לקרוא את הקובץ — ודא שהוא CSV או Excel תקין")
    # Before anything is dropped, so the rows still line up with the sheet's own.
    shaped, formula_cells = _imp_formula_text(raw, filename, shaped)
    # drop fully-empty rows
    shaped = [row for row in shaped
              if any(c is not None and str(c).strip() != "" for c in row[3])]
    if not shaped:
        raise HTTPException(400, "הקובץ ריק")
    rows = [r for *_, r in shaped]
    ncols = min(max(len(r) for r in rows), IMPORT_MAX_COLS)
    if ncols < 1:
        raise HTTPException(400, "לא נמצאו עמודות בקובץ")
    # A board exported from monday states its name and its group division on
    # lines of their own above the header; read from row 0 those lines become the
    # header and two items. Read that layout as what it is, and fall back to
    # "row 0 is the header" for every other sheet.
    md = _imp_monday_layout(shaped)
    if md:
        sheet_title, header, all_body, summary_rows = md[0], md[1], md[2], md[3]
    else:
        sheet_title, header, all_body, summary_rows = None, rows[0], shaped[1:], 0
    body = all_body[:IMPORT_MAX_ROWS]
    # A sheet past the ceiling was cut here without a word, which is the one
    # thing an import must not do: a board short by its last 400 rows looks
    # exactly like a board that has 2,000.
    rows_dropped = len(all_body) - len(body)

    def _cell(r, i):
        return (str(r[i]).strip() if i < len(r) and r[i] is not None else "")

    labels = [(_cell(header, i) or f"עמודה {i + 1}") for i in range(ncols)]

    # ── what the file says about sub-items ───────────────────────────────
    # Two ways a sheet can say "this belongs under that", read in this order:
    # the indentation a board exported from here writes — where the structure IS
    # the sheet — and failing that a column naming the parent by its title, which
    # is how a CSV or a hand-made sheet says the same thing.
    hier = any(lvl >= 1 for lvl, *_ in body)
    parent_at = next((i for i in range(1, ncols)
                      if labels[i].strip().lower() in IMPORT_PARENT_HEADERS), None)
    # and the same for the group: a sheet with a "קבוצה" column is dividing its
    # board by it, the way an exported one divides by its group rows.
    group_at = next((i for i in range(1, ncols)
                     if labels[i].strip().lower() in IMPORT_GROUP_HEADERS), None)

    # ── read the sheet into groups, items and sub-items ──────────────────
    # `band` is the grey header this app writes over a sub-item block, naming the
    # columns those sub-items have. It is a header, not an item, and its labels
    # are what a sub-item's cells are read against.
    #
    # `group_paint` is the colour each group row was painted — monday fills that
    # row with the group's colour and this app's own export writes it on the
    # text, so it is the source board saying what colour the group is. Kept by
    # name, which is how every step after this one refers to a group.
    plan, band_vals, sub_labels, group_paint = [], None, [], {}
    for lvl, is_band, paint, r in body:
        vals = [_cell(r, i) for i in range(ncols)]
        if hier and lvl == 0:
            plan.append(("group", vals))
            if paint and vals[0]:
                group_paint.setdefault(vals[0], paint)
            continue
        if hier and lvl >= 2:
            if is_band or (band_vals is not None and vals[1:] == band_vals[1:]):
                band_vals = vals
                sub_labels = [v or f"עמודה {i + 1}" for i, v in enumerate(vals)]
                continue
            plan.append(("sub", vals))
            continue
        plan.append(("item", vals))
    item_rows = [v for kind, v in plan if kind == "item"]
    sub_rows = [v for kind, v in plan if kind == "sub"]
    # monday writes its sub-items twice: once as their own rows under the band,
    # and once comma-joined into a column of the item ("Subitems"). Kept, that
    # column is the same names a second time as text, standing beside the
    # sub-items it names. The band says which column it is — its own title is
    # the band's first cell.
    # The band names it — its own title is the band's first cell — and for a board
    # whose sub-items were not exported there is no band, so monday's own name
    # for the column stands in. Only ever inside monday's layout: a column
    # someone here called "תתי משימות" by hand is a column of their board.
    sub_col_at = None
    if md:
        _st = _cell(band_vals or [], 0)
        def _is_sub_col(i):
            return (labels[i] == _st if _st
                    else labels[i].strip().lower() in IMPORT_SUBITEMS_HEADERS)
        sub_col_at = next((i for i in range(1, ncols) if _is_sub_col(i)), None)
    if not item_rows:
        raise HTTPException(400, "לא נמצאו פריטים בקובץ")

    # ── the columns ──────────────────────────────────────────────────────
    # An item column is typed from what the items put in it. A column only the
    # sub-items have is typed from the sub-items, and one they share with the
    # items keeps the item column — sub-items on a board show a subset of its
    # columns, never a parallel set of their own.
    # A column with nothing under it on any row is not a column of this board —
    # the same rule the monday import follows. It is created neither when the
    # sheet gives it no heading (a column that is not there at all) nor when it
    # has a heading and no values: an empty column standing in front of the
    # board that was actually imported is a column nobody asked for. Named in
    # the report either way, so "where is it?" has an answer.
    def _has_values(i):
        return any((str(r[i]).strip() if i < len(r) and r[i] is not None else "")
                   for r in item_rows)

    def _blank_col(i):
        return not _cell(header, i) and not _has_values(i)

    empty_cols = [labels[i] for i in range(1, ncols)
                  if i not in (parent_at, group_at, sub_col_at)
                  and _cell(header, i) and not _has_values(i)]
    data_at = [i for i in range(1, ncols)
               if i not in (parent_at, group_at, sub_col_at) and _has_values(i)]
    col_types = [_imp_infer_type([(r[i] if i < len(r) else None) for r in item_rows])
                 for i in data_at]
    col_ids = ["col_" + uuid.uuid4().hex[:8] for _ in data_at]
    by_label = {labels[i]: (cid, i) for i, cid in zip(data_at, col_ids)}
    custom_cols = [{"id": cid, "type": ctype, "title": labels[i], "options": None,
                    "formula": None, "connect": None, "copy_mode": None, "perms": {}}
                   for cid, ctype, i in zip(col_ids, col_types, data_at)]
    # a sub-item column maps to the board column of the same name, or becomes one
    sub_map = []          # (index in the sub row, column id)
    sub_col_ids = []
    # A band column the items have no column for exists only on the sub-items —
    # which is exactly what the export says by naming it in the band and not in
    # the item header. Created as an ordinary board column it stood on every
    # item as well, empty forever, and the structure the board gave its
    # sub-items did not survive the trip.
    sub_only_ids = []
    for i in range(2, len(sub_labels)):
        # a band cell with nothing written in it names no column; invented, it
        # arrives as an "עמודה 21" the sub-items show and nobody can fill
        if not _cell(band_vals or [], i):
            continue
        if len(custom_cols) >= IMPORT_MAX_COLS - 1 and sub_labels[i] not in by_label:
            continue
        hit = by_label.get(sub_labels[i])
        if hit:
            cid = hit[0]
        else:
            cid = "col_" + uuid.uuid4().hex[:8]
            ctype = _imp_infer_type([(r[i] if i < len(r) else None) for r in sub_rows])
            custom_cols.append({"id": cid, "type": ctype, "title": sub_labels[i], "options": None,
                                "formula": None, "connect": None, "copy_mode": None, "perms": {}})
            by_label[sub_labels[i]] = (cid, None)
            sub_only_ids.append(cid)
        sub_map.append((i, cid))
        # the sub-item-only ones are appended by the board itself (sub_only), so
        # they are deliberately not part of the shared subset
        if cid not in sub_col_ids and cid not in sub_only_ids:
            sub_col_ids.append(cid)
    # A column named in the header, empty on every item and filled by the
    # sub-items is now a column of this board — so it is no longer one of the
    # ones the report says were left out for being empty.
    _made = {c["title"] for c in custom_cols}
    empty_cols = [t for t in empty_cols if t not in _made]

    with Session(engine) as db:
        creator = actor_id
        env_id = environment_id
        if not env_id:
            primary = db.query(Environment).filter(Environment.is_primary == True).first()
            env_id = primary.id if primary else None
        if not (_cap(db, creator, "create_board") or _can_manage_env(db, env_id, creator)):
            raise HTTPException(403, "אין לך הרשאה ליצור לוח חדש")
        dept_id = db.query(Department.id).order_by(Department.id).limit(1).scalar()
        maxpos = (db.query(func.max(Board.position))
                  .filter(Board.environment_id == env_id, Board.folder_id == folder_id).scalar())
        base = os.path.splitext(os.path.basename(filename or ""))[0]
        # An exported board names itself on its first line; the file it was saved
        # as carries whatever the browser called it ("Spotical_1786443119").
        board_name = (name or "").strip() or (sheet_title or "").strip() or base or "לוח מיובא"
        name_from = _board_name_from(name, sheet_title, base)
        settings = {
            "views": ["table"],
            # The file's columns first, in the file's own order, and the three
            # the system issues on its own after them. Put first — which is
            # where a board created by hand starts with them — they sit between
            # the item's name and the first column of the board that was
            # actually imported, so the migrated board reads three columns of
            # metadata before it reads anything anybody wrote. It is the same
            # judgement the export already makes (see EXPORT_AUTO_COLS).
            "columns": custom_cols + IMPORT_SYSTEM_COLS(),
            "col_labels": {"item": labels[0]},   # name the item column after the first header
            # The board's four built-in columns — אחראים, סטטוס, עדיפות,
            # תאריך יעד — are not in the file and nothing in this import fills
            # them. Left showing, they are four columns of "טרם הוגדר" standing
            # in front of the board that was actually imported, and they follow
            # it into every export of it.
            # Hidden, not removed: a board admin turns any of them back on the
            # moment there is something to put in it.
            "col_hidden": ["assignees", "status", "priority", "due"],
        }
        if sub_col_ids or sub_only_ids:
            # sub-items show the columns the file gave them, in board order
            settings["sub_cols"] = ["item"] + sub_col_ids
            settings["sub_only"] = sub_only_ids
        b = Board(name=board_name, description="", department_id=dept_id, environment_id=env_id,
                  folder_id=folder_id, position=(maxpos + 1) if maxpos is not None else 0,
                  board_type=BoardType.KANBAN, icon="\U0001F4CB", color="#0073ea", settings=settings)
        db.add(b)
        db.flush()

        # ── groups: the file's own where it has them ─────────────────────
        # A sheet that names its groups is describing a board someone already
        # divided; inventing בתכנון/בביצוע/הושלם over it would file every item
        # under a heading the file never claimed. A flat sheet has no such
        # division, and the three stages are the board it is being turned into.
        #
        # Three ways a file names the division, in the order they are trusted:
        # the group rows an exported board writes between its items, a column
        # naming each row's group — the only way a CSV can say it — and, failing
        # both, nothing, which is the one case that gets the default stages.
        named = [_cell(v, 0) for kind, v in plan if kind == "group" and _cell(v, 0)]
        col_groups = []
        if not named and group_at is not None:
            for kind, vals in plan:
                if kind != "item":
                    continue
                g = _cell(vals, group_at)
                if g and g not in col_groups:
                    col_groups.append(g)
        # an item whose group cell is empty belongs to no group the file named,
        # and filing it under the first one would be a quiet misplacement
        col_blank = bool(col_groups) and any(
            not _cell(v, group_at) for kind, v in plan if kind == "item")
        from_file = named or col_groups
        groups = []
        if from_file:
            # The colour the sheet gave the group, where it gave one. A board
            # exported with its groups coloured comes back coloured; a sheet
            # that says nothing about colour gets this app's palette, which is a
            # default rather than a claim about the file.
            for i, gname in enumerate(list(from_file) + (["ללא קבוצה"] if col_blank else [])):
                groups.append(Group(board_id=b.id, name=gname[:200], position=i,
                                    color=(group_paint.get(gname)
                                           or IMPORT_PALETTE[i % len(IMPORT_PALETTE)]),
                                    task_status=TaskStatus.BACKLOG))
        else:
            groups = [Group(board_id=b.id, name="בתכנון", position=0, color="#579bfc",
                            task_status=TaskStatus.BACKLOG),
                      Group(board_id=b.id, name="בביצוע", position=1, color="#fdab3d",
                            task_status=TaskStatus.IN_PROGRESS),
                      Group(board_id=b.id, name="הושלם", position=2, color="#00c875",
                            task_status=TaskStatus.DONE)]
        db.add_all(groups)
        db.flush()
        by_group = {g.name: g for g in groups} if col_groups else {}

        # The same budget the monday import runs under, shared by every file in
        # this one: the cells that hold addresses, and the file sheet.
        files = {"budget": [IMPORT_MAX_FILES, IMPORT_MAX_FILE_MB * 1024 * 1024],
                 "stats": {}}

        def cells_of(vals, pairs):
            cf = {"status_unset": True, "priority_unset": True}
            for i, cid in pairs:
                col = next((c for c in custom_cols if c["id"] == cid), None)
                val = _imp_coerce(vals[i] if i < len(vals) else None, col["type"] if col else "text")
                if col and col["type"] == "files" and val:
                    # a name is enough to see that an item had a spec attached,
                    # and useless for opening it — so the bytes come too, where
                    # they can be had at all
                    val = _import_attachments(db, val, files["budget"], files["stats"])
                if val is not None and val != "":
                    cf[cid] = val
            return cf

        item_pairs = list(zip(data_at, col_ids))
        pos, subs_made, made_tasks = 0, 0, []
        by_title, parent_of = {}, {}
        grp = groups[0]
        gi, gpos, last_item = -1, {}, None
        for kind, vals in plan:
            if kind == "group":
                gi += 1
                if gi < len(groups):
                    grp = groups[gi]
                last_item = None
                continue
            if kind == "sub":
                # the band's first column is the sub-item's own name
                title = _cell(vals, 1) or f"תת־פריט {subs_made + 1}"
                if last_item is None:
                    continue                      # a sub-item with nothing above it
                t = Task(board_id=b.id, group_id=last_item.group_id, parent_id=last_item.id,
                         title=title[:500], status=TaskStatus.BACKLOG, priority=Priority.MEDIUM,
                         position=subs_made, created_by=creator,
                         custom_fields=cells_of(vals, sub_map))
                db.add(t)
                db.flush()
                _ensure_item_uid(db, t)
                _audit(db, t.id, "create", field="subitem", old=None, new=t.title, user_id=creator)
                made_tasks.append(t)
                subs_made += 1
                continue
            title = _cell(vals, 0) or f"פריט {pos + 1}"
            if by_group:
                # the row names its own group, so the row decides — not its place
                # in the file, which for a flat sheet says nothing
                grp = by_group.get(_cell(vals, group_at)) or groups[-1]
            p = gpos[grp.id] = gpos.get(grp.id, -1) + 1
            t = Task(board_id=b.id, group_id=grp.id, title=title[:500], status=TaskStatus.BACKLOG,
                     priority=Priority.MEDIUM, position=p, created_by=creator,
                     custom_fields=cells_of(vals, item_pairs))
            db.add(t)
            db.flush()
            _ensure_item_uid(db, t)
            _audit(db, t.id, "create", field="item", old=None, new=t.title, user_id=creator)
            made_tasks.append(t)
            by_title.setdefault(t.title, t)
            if parent_at is not None:
                pname = _cell(vals, parent_at)
                if pname:
                    parent_of[t.id] = pname
            last_item = t
            pos += 1

        # ── a parent named by column ─────────────────────────────────────
        # Resolved after every row is in, because a file may name a parent that
        # appears below the row pointing at it. A name that matches nothing is
        # left as a top-level item and reported — guessing at the nearest title
        # would file someone's item under the wrong parent silently.
        orphans = []
        for t in made_tasks:
            pname = parent_of.get(t.id)
            if not pname:
                continue
            parent = by_title.get(pname)
            if parent is None or parent.id == t.id:
                orphans.append(pname)
                continue
            t.parent_id = parent.id
            t.group_id = parent.group_id
            pos -= 1
            subs_made += 1
        db.flush()

        # the conversation sheet, when the workbook carries one
        talk = _imp_attach_conversation(db, _imp_conversation_sheet(raw, filename),
                                        made_tasks, creator, [IMPORT_MAX_MESSAGES])
        # and the file sheet, which is where the addresses of the attachments are
        attached = _imp_attach_files(db, _imp_files_sheet(raw, filename), made_tasks, b,
                                     files, IMPORT_MAX_COLS)
        db.add(BoardMember(board_id=b.id, user_id=creator, role="admin"))
        db.commit()
        db.refresh(b)
        st_files = files["stats"]
        return {"id": b.id, "name": b.name, "icon": b.icon, "items": pos,
                "subitems": subs_made, "columns": len(custom_cols),
                "messages": talk["messages"] + talk["replies"],
                "files": st_files.get("imported", 0) + st_files.get("reused", 0),
                "report": {"messages_imported": talk["messages"] + talk["replies"],
                           # the files: brought across, already here, or a named
                           # link to somewhere this server cannot fetch from
                           "files_imported": st_files.get("imported", 0),
                           "files_bytes": st_files.get("bytes", 0),
                           "files_reused": st_files.get("reused", 0),
                           "files_linked": st_files.get("linked", 0),
                           "files_unreachable": st_files.get("failed", 0),
                           "files_expired": st_files.get("expired", 0),
                           "files_over_budget": st_files.get("over_budget", 0),
                           "files_gone": st_files.get("gone", 0),
                           "files_items_unmatched": attached["unmatched_items"],
                           "replies_imported": talk["replies"],
                           "conversation_items_unmatched": talk["unmatched_items"],
                           "people_unmatched": talk["unmatched_people"],
                           # the division that came out of the FILE — a board
                           # that got the three default stages instead says so
                           # with a 0 here and "default" below, rather than
                           # reporting three groups nobody asked for
                           "groups": len(from_file),
                           "group_names": [g.name for g in groups][:40],
                           # the colour each one ended up with, and how many of
                           # those the sheet itself painted — see group_paint
                           "group_hex": [g.color for g in groups][:40],
                           "group_colors": sum(1 for g in groups if g.name in group_paint),
                           # and where it came from, because "3 קבוצות" over an
                           # undivided board reads exactly like a division
                           "board_name": board_name[:200],
                           "board_name_from": name_from,
                           "groups_from": ("sheet" if named else
                                           "column" if col_groups else "default"),
                           "groups_column": labels[group_at] if (col_groups and group_at is not None) else "",
                           # the line monday writes under each group, holding
                           # that group's rolled-up dates and no name
                           "summary_rows": summary_rows,
                           # cells the spreadsheet never worked out, which came
                           # across as the formula itself rather than as empty
                           "formula_cells_as_text": formula_cells,
                           # a heading in the file with nothing under it: named,
                           # not created — see _has_values above
                           "columns_empty": empty_cols,
                           "rows_dropped": rows_dropped,
                           # how the file said what belongs under what
                           "hierarchy": ("band" if (md and sub_rows)
                                         else "indent" if (hier and sub_rows)
                                         else "parent_column" if (parent_at is not None and subs_made)
                                         else ""),
                           # the columns that were the sub-items themselves
                           "as_subitems": ([labels[sub_col_at]] if sub_col_at is not None else []),
                           # and the ones the sub-items have and the items do
                           # not — named, because that is where somebody will
                           # look for them on the item row and not find them
                           "columns_sub": [c["title"] for c in custom_cols
                                           if c["id"] in set(sub_only_ids)],
                           "parents_unmatched": sorted(set(orphans))[:20]}}


@app.patch("/api/boards/{board_id}")
def update_board(board_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "board not found")
        if data.get("name") is not None:
            b.name = data["name"]
        if data.get("icon") is not None:
            b.icon = data["icon"]
        if data.get("color") is not None:
            b.color = data["color"]
        if data.get("views") is not None:
            views = ["table"] + [v for v in data["views"] if v in ALL_VIEWS and v != "table"]
            s = dict(b.settings or {})
            s["views"] = views
            b.settings = s
        if "view_only" in data:
            s = dict(b.settings or {})
            s["view_only"] = bool(data["view_only"])
            b.settings = s
        if "visibility" in data:
            # Board admins only. Publishing a board hands it to everyone in the
            # environment at once, which is not something an editor should be
            # able to do on their own.
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לשנות את חשיפת הלוח")
            v = data["visibility"]
            if v not in BOARD_VISIBILITY:
                raise HTTPException(400, "ערך חשיפה לא תקין")
            s = dict(b.settings or {})
            s["visibility"] = v
            b.settings = s
        if "form" in data:
            # only a board admin can add/update the form
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לערוך את הטופס")
            s = dict(b.settings or {})
            s["form"] = data["form"]
            b.settings = s
        if data.get("col_widths") is not None:
            # only a board admin may set column widths (drag-to-resize)
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לשנות רוחב עמודות")
            widths = {}
            for k, v in (data["col_widths"] or {}).items():
                try:
                    widths[str(k)] = max(60, min(600, int(v)))
                except (TypeError, ValueError):
                    continue
            s = dict(b.settings or {})
            s["col_widths"] = widths
            b.settings = s
        if data.get("col_labels") is not None:
            # rename a built-in column header (e.g. "פריט") — board admin
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לשנות שם עמודה")
            builtin = {"item", "assignees", "status", "priority", "due"}
            labels = {}
            for k, v in (data["col_labels"] or {}).items():
                if k in builtin:
                    lv = str(v or "").strip()[:40]
                    if lv:
                        labels[str(k)] = lv
            s = dict(b.settings or {})
            s["col_labels"] = labels
            b.settings = s
        if data.get("col_hidden") is not None:
            # hide built-in columns (the "פריט" name column can never be hidden) — board admin
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול להסתיר עמודות")
            hideable = {"assignees", "status", "priority", "due"}
            hidden = [str(k) for k in (data["col_hidden"] or []) if str(k) in hideable]
            s = dict(b.settings or {})
            s["col_hidden"] = list(dict.fromkeys(hidden))  # de-dup, preserve order
            b.settings = s
        if data.get("col_order") is not None:
            # persisted display order of columns (built-in keys + custom ids) — board admin
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לשנות סדר עמודות")
            order = [str(k) for k in (data["col_order"] or []) if isinstance(k, (str, int))]
            s = dict(b.settings or {})
            s["col_order"] = list(dict.fromkeys(order))  # de-dup, preserve first occurrence
            b.settings = s
        if "notifications_enabled" in data:
            # board admin toggles all notifications for this board on/off
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לשנות התראות ללוח")
            s = dict(b.settings or {})
            s["notifications_enabled"] = bool(data["notifications_enabled"])
            b.settings = s
        if data.get("statuses") is not None:
            # only a board admin may rename/recolor/reorder/add statuses
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לערוך סטטוסים")
            out, seen = [], set()
            for it in data["statuses"]:
                e = _norm_board_status(it, seen)
                if e:
                    out.append(e)
                if len(out) >= BOARD_STATUS_MAX:
                    break
            if not out:
                raise HTTPException(400, "חובה סטטוס אחד לפחות")
            s = dict(b.settings or {})
            s["statuses"] = out
            b.settings = s
        if data.get("priorities") is not None:
            # the priority column is a status column, so it is edited under the
            # same rule: only a board admin may rename/recolor/reorder/add
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לערוך עדיפויות")
            out, seen = [], set()
            for it in data["priorities"]:
                e = _norm_board_priority(it, seen)
                if e:
                    out.append(e)
                if len(out) >= BOARD_PRIORITY_MAX:
                    break
            if not out:
                raise HTTPException(400, "חובה עדיפות אחת לפחות")
            s = dict(b.settings or {})
            s["priorities"] = out
            b.settings = s
        if data.get("columns") is not None:
            # only a board admin may add/edit/remove columns and their options
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לערוך עמודות")
            # full replacement of the custom-column definitions
            allowed = {"timeline", "text", "email", "number", "date", "rating", "status",
                       "people", "dropdown", "files", "accounts", "checkbox", "formula",
                       "connect", "created_at", "created_by", "item_id", "mirror"}
            old_cols = {c.get("id"): c for c in (b.settings or {}).get("columns", [])}
            is_ws_admin = _ws_role(db, actor_id) == "admin"
            cols = []
            for c in data["columns"]:
                if not isinstance(c, dict) or c.get("type") not in allowed:
                    continue
                cid = c.get("id") or ("col_" + uuid.uuid4().hex[:8])
                if c["type"] == "connect":
                    # A board admin owns their own board's columns, this one
                    # included. What used to be a blanket workspace-admin gate
                    # is now two narrower rules, because the thing that actually
                    # needs guarding is not the column — it is where the column
                    # REACHES.
                    prev = old_cols.get(cid)
                    changed = (not prev) or prev.get("type") != "connect" or prev.get("connect") != c.get("connect")
                    if changed and not is_ws_admin:
                        _cfg = c.get("connect") or {}
                        _targets = [int(x) for x in (_cfg.get("board_ids") or [])
                                    if str(x).lstrip("-").isdigit()]
                        # Naming a target is not a way to reach a board you were
                        # never given: the picker, the report and the mirror all
                        # read through this list.
                        _seen = _visible_board_ids(db, actor_id)
                        _unseen = [t for t in _targets if t not in _seen]
                        if _unseen:
                            raise HTTPException(
                                403, "אפשר לבחור רק לוחות יעד שיש לך גישה אליהם")
                        # A two-way column CREATES a column on the target board.
                        # Writing into someone else's board takes rights on that
                        # board — said plainly rather than downgrading the column
                        # to one-way behind the admin's back.
                        if _cfg.get("two_way"):
                            _no_admin = [t for t in _targets
                                         if _board_role(db, t, actor_id) != "admin"]
                            if _no_admin:
                                _names = ", ".join(
                                    (db.query(Board.name).filter(Board.id == t).scalar() or str(t))
                                    for t in _no_admin)
                                raise HTTPException(
                                    403, f"קשר דו־כיווני יוצר עמודה בלוח היעד — נדרשת הרשאת "
                                         f"מנהל לוח גם ב: {_names}")
                # a status column carries its own {label,color} vocabulary;
                # every other type keeps its options untouched
                opts = (_status_col_options(c.get("options"))
                        if c["type"] == "status" else c.get("options"))
                cols.append({
                    "id": cid,
                    "type": c["type"],
                    "title": c.get("title") or c["type"],
                    "options": opts,
                    "formula": c.get("formula"),
                    "connect": c.get("connect") if c["type"] == "connect" else None,
                    # which connect column to read through, and which field of
                    # the linked item to show
                    "mirror_of": c.get("mirror_of") if c["type"] == "mirror" else None,
                    # "מזהה פריט": what a click on the cell copies — the number
                    # itself ("id", the default) or a link to the item ("url")
                    "copy_mode": (c.get("copy_mode") if c.get("copy_mode") in ("id", "url") else "id")
                                 if c["type"] == "item_id" else None,
                    # "מספר": the unit shown beside the figure and whether the
                    # thousands are grouped — how it is read, not what is stored
                    "number": _number_col_cfg(c.get("number")) if c["type"] == "number" else None,
                    "perms": c.get("perms") or {},
                })
            _conn_n = sum(1 for c in cols if c.get("type") == "connect")
            _conn_was = sum(1 for c in old_cols.values() if c.get("type") == "connect")
            # An over-budget board that already exists stays editable — the
            # limit blocks growth, it does not freeze the column list.
            if _conn_n > _max_connect_cols() and _conn_n > _conn_was:
                raise HTTPException(
                    400, f"מותרות עד {_max_connect_cols()} עמודות קישור בלוח אחד")
            # A two-way column needs its counterpart to exist before it is saved:
            # the map of WHERE the reverse link shows lives on the column itself,
            # and the configuration screen reads it back to tell the admin.
            for c in cols:
                if _is_two_way(c):
                    c["connect"] = {**_connect_cfg(c),
                                    "mirror": _ensure_mirrors(db, board_id, c)}
            # A connect column that is going away takes its relationships with
            # it: the rows are keyed by (item, column), so leaving them would
            # keep the link readable from the mirror on the other board after
            # this side has no column to show it in.
            _drop_links_for_columns(db, [cid for cid, c in old_cols.items()
                                         if c.get("type") == "connect"
                                         and cid not in {x["id"] for x in cols}])
            s = dict(b.settings or {})
            s["columns"] = cols
            # a deleted column can't linger in the sub-item-only set
            if s.get("sub_only"):
                live = {str(c.get("id")) for c in cols if c.get("id")}
                s["sub_only"] = [i for i in s["sub_only"] if str(i) in live]
            b.settings = s
            # adding the column issues an identifier to every item already on the
            # board (and to its sub-items)
            if any(c.get("type") == "item_id" for c in cols):
                for t in db.query(Task).filter(Task.board_id == board_id).all():
                    _ensure_item_uid(db, t)
        if data.get("sub_cols") is not None:
            # Sub-items have their own column structure: identical for every
            # sub-item on the board, but not necessarily the item's columns.
            # Stored as ids picked from the board's column pool (built-in keys +
            # custom column ids); the name column is always present and first.
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול להגדיר את עמודות תת-הפריט")
            s = dict(b.settings or {})
            pool = {"assignees", "status", "priority", "due"}
            pool |= {str(c.get("id")) for c in s.get("columns", []) if c.get("id")}
            picked = [str(k) for k in (data["sub_cols"] or []) if str(k) in pool]
            s["sub_cols"] = ["item"] + list(dict.fromkeys(picked))
            b.settings = s
        if data.get("sub_only") is not None:
            # Sub-item-only columns: custom columns that exist on sub-item rows
            # but never on the parent items. Stored as a list of custom column
            # ids; only ids that are real columns on this board are kept.
            if _board_role(db, board_id, actor_id) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול להגדיר עמודות תת-פריט")
            s = dict(b.settings or {})
            live = {str(c.get("id")) for c in s.get("columns", []) if c.get("id")}
            s["sub_only"] = [str(k) for k in (data["sub_only"] or []) if str(k) in live]
            b.settings = s
        db.commit()
        # columns, statuses, the board's own settings — everyone on it is looking
        # at a board that just changed shape
        bus.publish("board.changed", board_id=board_id, actor_id=actor_id)
        db.refresh(b)
        # statuses and priorities come back because the server mints the key for
        # a newly added one — the client cannot know it otherwise
        return {"id": b.id, "name": b.name, "icon": b.icon, "color": b.color,
                "views": _board_views(b), "columns": (b.settings or {}).get("columns", []),
                "statuses": _board_statuses(b), "priorities": _board_priorities(b)}

# ── Recycle bin (סל מחזור) ──────────────────────────────────────────
# A deleted board is not destroyed: it keeps its groups, items, comments and
# memberships and only stops being listed. After RECYCLE_BIN_DAYS it is purged
# for good. Restoring simply clears the deletion stamp.
RECYCLE_BIN_DAYS = int(os.getenv("RECYCLE_BIN_DAYS", "60"))   # "חודשיים"


def _hard_delete_board(db, board_id: int):
    """Destroy a board and everything under it. Irreversible — only ever called
    for a board already in the recycle bin (expired, or purged on request)."""
    b = db.query(Board).filter(Board.id == board_id).first()
    if not b:
        return False
    tasks = db.query(Task).filter(Task.board_id == board_id).all()
    task_ids = [t.id for t in tasks]
    if task_ids:
        db.query(Comment).filter(Comment.task_id.in_(task_ids)).delete(synchronize_session=False)
        # The history goes with the items, the way _hard_delete_task has always
        # taken it. Left behind it does not merely sit there: ids are reissued,
        # so a destroyed board's log reattaches to whatever item is created into
        # that id next — and an imported board showed one row of a stranger's
        # history, dated three weeks before the item existed, under "יצר/ה את
        # הפריט" with another board's item name in it.
        db.query(AuditLog).filter(AuditLog.entity_type == "task",
                                  AuditLog.entity_id.in_(task_ids)).delete(synchronize_session=False)
        # links reach across boards, so the far end is on a board that survives
        _drop_links_for_tasks(db, task_ids)
    for t in tasks:          # clear assignee links via the ORM relationship
        t.assignees = []
    db.flush()
    db.query(Task).filter(Task.board_id == board_id).delete(synchronize_session=False)
    db.query(Group).filter(Group.board_id == board_id).delete(synchronize_session=False)
    db.query(BoardMember).filter(BoardMember.board_id == board_id).delete(synchronize_session=False)
    db.delete(b)
    return True


def _sweep_stray_audit(db):
    """Log rows that describe an item that is not there, or is not theirs.

    Two kinds, and the second is why this exists rather than being left as
    harmless clutter:

      · rows pointing at an item that no longer exists — every board destroyed
        before the delete above took the history with it left all of them;
      · rows DATED BEFORE the item they point at was created. An id is reissued
        once the row that held it is gone, so those are a deleted item's history
        wearing a living item's id. A freshly imported board showed one such row
        on an item — "created item 'פריט 742'", three weeks before that item
        existed, from a board deleted weeks earlier.

    Imported history is the one thing that legitimately predates its item: a
    monday change from 2024 is written onto an item created today, and it is
    skipped here by the `origin` that marks it.

    Returns (orphans, misattributed).
    """
    stray = db.query(AuditLog.id).filter(
        AuditLog.entity_type == "task",
        ~db.query(Task.id).filter(Task.id == AuditLog.entity_id).exists()).all()
    orphan_ids = [i for (i,) in stray]
    wrong = db.query(AuditLog.id).join(Task, Task.id == AuditLog.entity_id).filter(
        AuditLog.entity_type == "task", AuditLog.origin.is_(None),
        Task.created_at != None, AuditLog.created_at != None,          # noqa: E711
        AuditLog.created_at < Task.created_at).all()
    wrong_ids = [i for (i,) in wrong]
    for ids in (orphan_ids, wrong_ids):
        for i in range(0, len(ids), 500):                 # SQLite caps the IN list
            db.query(AuditLog).filter(AuditLog.id.in_(ids[i:i + 500])).delete(
                synchronize_session=False)
    if orphan_ids or wrong_ids:
        db.commit()
    return len(orphan_ids), len(wrong_ids)


def _purge_expired_boards(db):
    """Hard-delete boards whose retention window has passed. Cheap enough to run
    whenever the bin is read, so no scheduler is needed."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=RECYCLE_BIN_DAYS)
    expired = [b.id for b in db.query(Board).filter(
        Board.deleted_at != None, Board.deleted_at < cutoff).all()]   # noqa: E711
    for bid in expired:
        _hard_delete_board(db, bid)
    if expired:
        db.commit()
    return expired


# One sweep at boot, so expired boards are cleared even if nobody opens the bin.
with Session(engine) as _bin_db:
    try:
        _expired = _purge_expired_boards(_bin_db)
        if _expired:
            print(f"🗑️  purged {len(_expired)} board(s) past the {RECYCLE_BIN_DAYS}-day window", flush=True)
    except Exception as _e:
        print(f"⚠️  recycle-bin purge skipped: {_e}", flush=True)


def _can_delete_board(db, b, user_id):
    """A board admin, a manager of the board's environment, or a system admin."""
    if user_id is None:
        return True                        # auth disabled → no per-user gate
    return (_board_role(db, b.id, user_id) == "admin"
            or _can_manage_env(db, b.environment_id, user_id))


def _trash_board_json(db, b):
    days_left = RECYCLE_BIN_DAYS - (datetime.now(timezone.utc).replace(tzinfo=None) - b.deleted_at).days
    return {
        "id": b.id, "name": b.name, "icon": b.icon, "color": b.color,
        "description": b.description,
        "environment_id": b.environment_id,
        "environment_name": db.query(Environment.name).filter(
            Environment.id == b.environment_id).scalar() or "",
        "deleted_at": b.deleted_at.isoformat() if b.deleted_at else None,
        "deleted_by": b.deleted_by,
        "deleted_by_name": (db.query(User.name).filter(User.id == b.deleted_by).scalar() or "")
                           if b.deleted_by else "",
        "task_count": db.query(Task).filter(
            Task.board_id == b.id, Task.parent_id == None).count(),   # noqa: E711
        "days_left": max(0, days_left),
        "retention_days": RECYCLE_BIN_DAYS,
    }


@app.delete("/api/boards/{board_id}")
def delete_board(board_id: int, user_id: int = Depends(current_user_id)):
    """Move a board to the recycle bin. Nothing under it is destroyed — groups,
    items, comments and memberships are kept so a restore is lossless. Only a
    board admin or an environment manager may delete it."""
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "board not found")
        if not _can_delete_board(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח או מנהל הסביבה יכול למחוק אותו")
        if b.deleted_at:
            return {"status": "deleted", "id": board_id, "days_left": RECYCLE_BIN_DAYS}
        b.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        b.deleted_by = user_id
        db.commit()
        return {"status": "deleted", "id": board_id,
                "restorable_until_days": RECYCLE_BIN_DAYS}


# ── the board's own recycle bin: items ───────────────────────────────
def _deleted_tasks_q(db):
    """Tasks the bin cares about. The global hook hides deleted rows from every
    query, so the bin has to say explicitly that it wants them."""
    return db.query(Task).execution_options(include_deleted=True)


def _purge_expired_tasks(db, board_id=None):
    """Hard-delete items whose retention window has passed. Run when a bin is
    read, so no scheduler is needed — the same approach the board bin uses."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=RECYCLE_BIN_DAYS)
    q = _deleted_tasks_q(db).filter(Task.deleted_at != None, Task.deleted_at < cutoff)  # noqa: E711
    if board_id is not None:
        q = q.filter(Task.board_id == board_id)
    gone = [t.id for t in q.all()]
    for tid in gone:
        _hard_delete_task(db, tid)
    if gone:
        db.commit()
    return gone


def _hard_delete_task(db, task_id):
    """Remove an item for good, with everything hanging off it."""
    for sub in _deleted_tasks_q(db).filter(Task.parent_id == task_id).all():
        _hard_delete_task(db, sub.id)
    db.query(Comment).filter(Comment.task_id == task_id).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.entity_type == "task",
                              AuditLog.entity_id == task_id).delete(synchronize_session=False)
    _drop_links_for_tasks(db, [task_id])
    t = _deleted_tasks_q(db).filter(Task.id == task_id).first()
    if t:
        t.assignees = []
        db.delete(t)


def _trash_task_json(db, t, users):
    days_left = RECYCLE_BIN_DAYS - (datetime.now(timezone.utc).replace(tzinfo=None) - t.deleted_at).days
    subs = _deleted_tasks_q(db).filter(Task.parent_id == t.id).count()
    return {"id": t.id, "title": t.title, "group_id": t.group_id,
            "deleted_at": t.deleted_at, "deleted_by": t.deleted_by,
            "deleted_by_name": users.get(t.deleted_by, "—"),
            "sub_count": subs,
            "days_left": max(0, days_left), "retention_days": RECYCLE_BIN_DAYS}


@app.get("/api/boards/{board_id}/trash")
def board_trash(board_id: int, actor_id: int = Depends(current_user_id)):
    """Items deleted from this board, newest first.

    Only top-level items are listed: a sub-item is deleted with its parent and
    restored with it, so listing both would offer a restore that does nothing.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        _purge_expired_tasks(db, board_id)
        users = {u.id: u.name for u in db.query(User).all()}
        rows = (_deleted_tasks_q(db)
                .filter(Task.board_id == board_id, Task.deleted_at != None,  # noqa: E711
                        Task.parent_id == None)                              # noqa: E711
                .order_by(Task.deleted_at.desc()).all())
        return {"items": [_trash_task_json(db, t, users) for t in rows],
                "retention_days": RECYCLE_BIN_DAYS}


@app.post("/api/tasks/{task_id}/restore")
def restore_task(task_id: int, data: dict = None, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        t = _deleted_tasks_q(db).filter(Task.id == task_id).first()
        if not t or not t.deleted_at:
            raise HTTPException(404, "item not in the recycle bin")
        _require_board_edit(db, t.board_id, actor_id)
        # the group it lived in may itself be gone; put it back where it can be seen
        g = db.query(Group).filter(Group.id == t.group_id, Group.board_id == t.board_id).first()
        if not g:
            g = db.query(Group).filter(Group.board_id == t.board_id).order_by(Group.position).first()
            t.group_id = g.id if g else None
        for sub in _deleted_tasks_q(db).filter(Task.parent_id == task_id).all():
            sub.deleted_at = None
            sub.deleted_by = None
        t.deleted_at = None
        t.deleted_by = None
        _audit(db, task_id, "restore", field="item", old=None, new=t.title, user_id=actor_id)
        _bid = t.board_id
        db.commit()
        bus.publish("task.created", board_id=_bid, task_id=task_id, actor_id=actor_id)
        return {"status": "restored", "id": task_id}


@app.delete("/api/boards/{board_id}/trash/{task_id}")
def purge_task(board_id: int, task_id: int, actor_id: int = Depends(current_user_id)):
    """Permanent. Board admins only — nothing brings this back."""
    with Session(engine) as db:
        t = _deleted_tasks_q(db).filter(Task.id == task_id, Task.board_id == board_id).first()
        if not t or not t.deleted_at:
            raise HTTPException(404, "item not in the recycle bin")
        if not _is_board_admin(db, board_id, actor_id):
            raise HTTPException(403, "רק מנהל הלוח יכול למחוק לצמיתות")
        _hard_delete_task(db, task_id)
        db.commit()
        return {"status": "purged", "id": task_id}


@app.get("/api/boards/{board_id}/trash/{task_id}")
def view_trashed_task(board_id: int, task_id: int, actor_id: int = Depends(current_user_id)):
    """Read a deleted item without restoring it — the bin's "צפייה"."""
    with Session(engine) as db:
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        t = _deleted_tasks_q(db).filter(Task.id == task_id, Task.board_id == board_id).first()
        if not t or not t.deleted_at:
            raise HTTPException(404, "item not in the recycle bin")
        users = {u.id: u.name for u in db.query(User).all()}
        subs = _deleted_tasks_q(db).filter(Task.parent_id == task_id).order_by(Task.position).all()
        comments = db.query(Comment).filter(Comment.task_id == task_id).count()
        return {"id": t.id, "title": t.title, "description": t.description,
                "status": t.status.value if hasattr(t.status, "value") else t.status,
                "priority": t.priority.value if hasattr(t.priority, "value") else t.priority,
                "due_date": t.due_date,
                "custom_fields": t.custom_fields or {},
                "assignees": [{"id": u.id, "name": u.name, "avatar_url": u.avatar_url}
                              for u in (t.assignees or [])],
                "deleted_at": t.deleted_at, "deleted_by_name": users.get(t.deleted_by, "—"),
                "comment_count": comments,
                "subs": [{"id": x.id, "title": x.title} for x in subs]}


@app.get("/api/trash/boards")
def list_trash_boards(user_id: int = Depends(current_user_id)):
    """Boards currently in the recycle bin that this user may act on."""
    with Session(engine) as db:
        _purge_expired_boards(db)
        rows = db.query(Board).filter(Board.deleted_at != None).order_by(   # noqa: E711
            Board.deleted_at.desc()).all()
        rows = [b for b in rows if _can_delete_board(db, b, user_id)]
        return {"boards": [_trash_board_json(db, b) for b in rows],
                "retention_days": RECYCLE_BIN_DAYS}


@app.post("/api/trash/boards/{board_id}/restore")
def restore_board(board_id: int, user_id: int = Depends(current_user_id)):
    """Bring a board back out of the recycle bin, with all of its content."""
    with Session(engine) as db:
        _purge_expired_boards(db)
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "הלוח לא נמצא — ייתכן שנמחק לצמיתות")
        if not b.deleted_at:
            raise HTTPException(400, "הלוח אינו בסל המחזור")
        if not _can_delete_board(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח או מנהל הסביבה יכול לשחזר אותו")
        # the board's environment may itself have been removed meanwhile — fall
        # back to the primary workspace so a restored board is never orphaned
        if b.environment_id and not db.query(Environment).filter(
                Environment.id == b.environment_id).first():
            primary = db.query(Environment).filter(Environment.is_primary == True).first()  # noqa: E712
            b.environment_id = primary.id if primary else None
            b.folder_id = None
        elif b.folder_id and not db.query(Folder).filter(Folder.id == b.folder_id).first():
            b.folder_id = None
        b.deleted_at = None
        b.deleted_by = None
        db.commit()
        return {"status": "restored", "id": b.id, "name": b.name,
                "environment_id": b.environment_id}


@app.delete("/api/trash/boards/{board_id}")
def purge_board(board_id: int, user_id: int = Depends(current_user_id)):
    """Empty a single board out of the recycle bin — destroys it for good."""
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "board not found")
        if not b.deleted_at:
            raise HTTPException(400, "הלוח אינו בסל המחזור")
        if not _can_delete_board(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח או מנהל הסביבה יכול למחוק אותו")
        _hard_delete_board(db, board_id)
        db.commit()
        return {"status": "purged", "id": board_id}

# ── Board membership & per-board permissions ────────────────────────
BOARD_ROLES = ("admin", "editor", "viewer")
BROLE_HE = {"admin": "מנהל לוח", "editor": "עורך", "viewer": "צופה"}


def _notify(db, user_id, type, title, body="", board_id=None, task_id=None):
    """Create an in-app notification for a recipient (best-effort, no-op on bad input)."""
    if not user_id:
        return
    db.add(Notification(user_id=user_id, type=type, title=title, body=body,
                        board_id=board_id, task_id=task_id))

def _board_notify_on(board):
    """Whether the board emits notifications (board admin can switch it off wholesale)."""
    return bool((board.settings or {}).get("notifications_enabled", True)) if board else True


# ── Outgoing mail ───────────────────────────────────────────────────
# One way out of the app (_send_email) and two providers behind it. Which one
# sends is configuration, never a call site's business: MAIL_PROVIDER names it
# outright, and with nothing named the choice is simply whichever key is set —
# SendGrid first, since an environment holding a SendGrid key was given one on
# purpose. Neither key set is not an error: the message is logged and dropped,
# so an invite still goes through on a machine where mail was never configured.
MAIL_ENDPOINTS = {"sendgrid": "https://api.sendgrid.com/v3/mail/send",
                  "resend": "https://api.resend.com/emails"}


def _mail_provider():
    """Which provider sends, and with what key. ('', None) when mail is off."""
    named = (os.environ.get("MAIL_PROVIDER") or "").strip().lower()
    keys = {"sendgrid": os.environ.get("SENDGRID_API_KEY"),
            "resend": os.environ.get("RESEND_API_KEY")}
    if named in keys:
        # an explicitly named provider is never silently swapped for the other:
        # a missing key is a misconfiguration to see in the log, not to route
        # around, or a test send goes out through a provider nobody chose
        return (named, keys[named]) if keys[named] else ("", None)
    for name in ("sendgrid", "resend"):
        if keys[name]:
            return name, keys[name]
    return "", None


def _mail_from():
    """The From address, as (name, email).

    INVITE_FROM_EMAIL takes either form — "CityOS <no-reply@x.gov.il>" or the
    bare address. The default belongs to Resend's shared sandbox domain, which
    only Resend will accept; SendGrid refuses any sender it has not verified,
    so there it is better to send nothing and say why than to let every message
    come back 403 from a default nobody chose.
    """
    import email.utils
    name, addr = email.utils.parseaddr(
        os.environ.get("INVITE_FROM_EMAIL", "CityOS <onboarding@resend.dev>"))
    return name, addr


def _send_email(to_email, subject, html):
    """Send one transactional email. Returns True only if a provider took it.

    Every caller stays out of the provider question — see _mail_provider.
    """
    provider, api_key = _mail_provider()
    if not provider or not to_email:
        print(f"[email] skipped (no mail provider configured) → {to_email}: {subject}")
        return False
    from_name, from_addr = _mail_from()
    if provider == "sendgrid" and from_addr.endswith("@resend.dev"):
        print("[email] skipped (SENDGRID_API_KEY is set but INVITE_FROM_EMAIL is "
              "still Resend's sandbox sender — set a verified SendGrid sender) "
              f"→ {to_email}: {subject}")
        return False
    # development mode: until a domain is verified with the provider, real
    # recipients are blocked. Redirect every message to a single verified inbox
    # so invites can be tested end-to-end, keeping the original recipient
    # visible in the email.
    redirect = os.environ.get("EMAIL_DEV_REDIRECT")
    actual_to = to_email
    if redirect:
        actual_to = redirect
        subject = f"[פיתוח · נועד ל-{to_email}] {subject}"
        html = (f"<div dir='rtl' style='background:#fff3cd;border:1px solid #ffe08a;"
                f"border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:12.5px;"
                f"font-family:Arial'>⚙️ מצב פיתוח — הנמען המקורי של ההזמנה הוא "
                f"<b>{to_email}</b>. מייל זה הופנה אליך לצורכי בדיקה.</div>") + html
    if provider == "sendgrid":
        body = {"personalizations": [{"to": [{"email": actual_to}]}],
                "from": ({"email": from_addr, "name": from_name} if from_name
                         else {"email": from_addr}),
                "subject": subject,
                "content": [{"type": "text/html", "value": html}]}
        # sandbox_mode validates the whole request — sender identity included —
        # and delivers nothing. It is how a deploy can prove mail is wired up
        # without a message reaching anybody.
        if (os.environ.get("SENDGRID_SANDBOX") or "").strip() not in ("", "0", "false"):
            body["mail_settings"] = {"sandbox_mode": {"enable": True}}
    else:
        from_hdr = f"{from_name} <{from_addr}>" if from_name else from_addr
        body = {"from": from_hdr, "to": [actual_to], "subject": subject, "html": html}
    return _post_mail(provider, api_key, body, actual_to, subject)


def _post_mail(provider, api_key, body, actual_to, subject):
    """The one HTTP call. Split out so a test can exercise the payload alone."""
    import urllib.request, urllib.error, json as _json
    req = urllib.request.Request(MAIL_ENDPOINTS[provider],
                                 data=_json.dumps(body).encode("utf-8"),
                                 headers={"Authorization": f"Bearer {api_key}",
                                          "Content-Type": "application/json",
                                          "User-Agent": "CityOS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        # "sent" must mean a message somebody can receive. A sandbox send is
        # accepted by the provider and then thrown away, so logging it the same
        # way reads as a delivery that never happened — and the log is the only
        # place anyone can see which of the two it was.
        if ((body.get("mail_settings") or {}).get("sandbox_mode") or {}).get("enable"):
            print(f"[email] validated by {provider}, NOT delivered "
                  f"(SENDGRID_SANDBOX is on) → {actual_to}: {subject}")
        else:
            print(f"[email] sent via {provider} → {actual_to}: {subject}")
        return True
    except urllib.error.HTTPError as e:
        # The refusal itself is the useful part — "does not match a verified
        # Sender Identity" is the answer to nearly every mail that never
        # arrives — so the body is logged, not just the status. It carries no
        # credential; the key only ever goes out in the request header.
        detail = ""
        try:
            detail = (e.read() or b"")[:400].decode("utf-8", "replace")
        except Exception:
            pass
        print(f"[email] {provider} refused ({e.code}) → {actual_to}: {detail}")
        return False
    except Exception as e:
        print(f"[email] send failed via {provider} → {actual_to}: {e}")
        return False


def _app_base_url(request: Request = None):
    """The origin the links in outgoing mail must point at.

    Mail hardcoded the Vercel demo host, and nothing in either pipeline sets
    APP_BASE_URL — so an invitation sent from QA or from production linked to a
    different deployment altogether, one whose database is re-seeded per cold
    start. The board named in the mail does not exist there, so "כניסה ללוח"
    could only ever land somebody on an empty demo of somebody else's city.

    In order: the explicit setting; the origin SSO is already configured with
    (the production pipeline writes it from the Web App's own hostnames, so it
    is by definition a host the invitee can sign in on); the host this very
    request arrived on; and only then the old constant.
    """
    explicit = os.environ.get("APP_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    first = os.environ.get("ENTRA_REDIRECT_URI", "").split(",")[0].strip()
    if first:
        origin = first.rsplit("/auth/callback", 1)[0] if "/auth/callback" in first else first
        if origin.strip():
            return origin.rstrip("/")
    if request is not None:
        host = (request.headers.get("x-forwarded-host")
                or request.headers.get("host")
                or request.url.netloc or "")
        host = host.split(",")[0].strip()
        if host:
            proto = (request.headers.get("x-forwarded-proto")
                     or request.url.scheme or "https")
            return f"{proto.split(',')[0].strip() or 'https'}://{host}"
    return "https://code-cal-missions.vercel.app"


def _board_invite_html(invitee_name, board_name, inviter_name, board_id=None, base=None):
    """A board invitation in the wording the product asked for: who added you
    and to which board, nothing else. The button lands on the board itself —
    "כניסה ללוח" promises the board, so it links to the board's deep link and
    not to the home screen."""
    base = (base or _app_base_url()).rstrip("/")
    href = f"{base}/#/board/{board_id}" if board_id else base
    return f"""<div dir="rtl" style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#1a1a2e">
      <div style="background:#0073ea;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0">
        <h2 style="margin:0;font-size:19px">צורפת ללוח "{board_name}" במערכת missions</h2>
      </div>
      <div style="border:1px solid #e6e9ef;border-top:none;border-radius:0 0 12px 12px;padding:22px">
        <p style="font-size:15px">שלום {invitee_name},</p>
        <p style="font-size:15px;margin-bottom:22px"><b>{inviter_name}</b> צירפ/ה אותך ללוח <b>"{board_name}"</b> במערכת missions.</p>
        <a href="{href}" style="display:inline-block;background:#0073ea;color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;font-size:15px">כניסה ללוח</a>
        <p style="color:#9699a6;font-size:12px;margin-top:22px">מייל זה נשלח באופן אוטומטי ממערכת missions.</p>
      </div>
    </div>"""

def _env_invite_html(invitee_name, env_name, inviter_name, base=None):
    """Being added to a workspace, in the wording the product asked for: who
    added you, which workspace, and the one thing a workspace does not come
    with — the boards inside it. No role line: the workspace role is not what
    the invitee needs to read, and board access is granted a board at a time."""
    base = (base or _app_base_url()).rstrip("/")
    return f"""<div dir="rtl" style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#1a1a2e">
      <div style="background:#0073ea;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0">
        <h2 style="margin:0;font-size:19px">צורפת לסביבת העבודה "{env_name}" במערכת missions</h2>
      </div>
      <div style="border:1px solid #e6e9ef;border-top:none;border-radius:0 0 12px 12px;padding:22px">
        <p style="font-size:15px">שלום {invitee_name},</p>
        <p style="font-size:15px"><b>{inviter_name}</b> צירפ/ה אותך לסביבת העבודה <b>"{env_name}"</b> במערכת missions.</p>
        <p style="font-size:13.5px;color:#676879;background:#f5f6f8;border-radius:8px;padding:12px 14px;margin:18px 0">
          שימו לב: ההרשאות ללוחות בסביבת העבודה מוגדרות בנפרד – לוח ציבורי יופיע באופן מיידי, ולכל לוח אחר תידרש הזמנה נפרדת.
        </p>
        <a href="{base}" style="display:inline-block;background:#0073ea;color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;font-size:15px">כניסה למערכת</a>
        <p style="color:#9699a6;font-size:12px;margin-top:22px">מייל זה נשלח באופן אוטומטי ממערכת missions.</p>
      </div>
    </div>"""

# ── mail about one item ─────────────────────────────────────────────────
# Two things that happen TO a person on somebody else's keystroke: being put on
# a record, and being tagged in its conversation. Both already left an in-app
# notification, which only reaches somebody who is already in the app — and the
# whole point of these two events is that they are addressed to someone who is
# not looking.
#
# Every message is built BEFORE the commit, while the item, the board and the
# people are loaded, and sent AFTER it. Nothing is mailed about a change that
# rolled back, and the send — an HTTPS call to the provider — happens outside
# the transaction rather than holding it open.


def _mail_esc(v):
    """Text going into an email's HTML. An item called "קרקע <הרצל 12> & חניה"
    is an ordinary title and must not be able to close a tag."""
    import html as _h
    return _h.escape("" if v is None else str(v), quote=True)


def _item_link(board_id, task_id, base=None):
    """The deep link both mails point at: the item, opened on its conversation.
    #/board/{b}/item/{t} is the route the app already reads — see Router."""
    base = (base or _app_base_url()).rstrip("/")
    return f"{base}/#/board/{board_id}/item/{task_id}"


def _item_mail_html(heading, to_name, sentence, cta, href):
    """The shell both item mails share, in the house style of the invitations:
    a coloured heading, who you are, what happened, one button to the place it
    happened. `sentence` arrives as HTML — its <b> marks the names."""
    return f"""<div dir="rtl" style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#1a1a2e">
      <div style="background:#0073ea;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0">
        <h2 style="margin:0;font-size:19px">{heading}</h2>
      </div>
      <div style="border:1px solid #e6e9ef;border-top:none;border-radius:0 0 12px 12px;padding:22px">
        <p style="font-size:15px">שלום {_mail_esc(to_name)},</p>
        <p style="font-size:15px;margin-bottom:22px">{sentence}</p>
        <a href="{href}" style="display:inline-block;background:#0073ea;color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;font-size:15px">{cta}</a>
        <p style="color:#9699a6;font-size:12px;margin-top:22px">מייל זה נשלח באופן אוטומטי ממערכת missions ואין להגיב לו.</p>
      </div>
    </div>"""


def _item_assigned_mail(to_name, actor_name, item_title, board_name, board_id, task_id, base=None):
    """"שוייכת לרשומה" — the wording the product asked for, word for word.

    The subject quotes the board's name and spells MISSIONS in capitals; the
    sentence below spells it in lower case. That is not an inconsistency to be
    tidied away — it is how the wording was given, and the heading repeats the
    subject rather than the sentence, so the two stay in step."""
    return (f'שוייכת לרשומה בלוח "{board_name}" במערכת MISSIONS',
            _item_mail_html(
                f'שוייכת לרשומה בלוח "{_mail_esc(board_name)}" במערכת MISSIONS',
                to_name,
                f'שויכת ע"י <b>{_mail_esc(actor_name)}</b> לרשומה '
                f'<b>"{_mail_esc(item_title)}"</b> בלוח <b>{_mail_esc(board_name)}</b> '
                f'במערכת missions.',
                "כניסה לרשומה", _item_link(board_id, task_id, base)))


def _item_mention_mail(to_name, actor_name, item_title, board_name, board_id, task_id, base=None):
    """"תוייגת בשיחה". The button says כניסה לשיחה and lands on the item's
    conversation, which is the same deep link — the item opens on its chat.

    The subject says בשיחה, not ברשומה: what happened is that somebody was
    named in the conversation, and the record is where that conversation is.
    Same capitalisation rule as the mail above."""
    return (f'תוייגת בשיחה בלוח "{board_name}" במערכת MISSIONS',
            _item_mail_html(
                f'תוייגת בשיחה בלוח "{_mail_esc(board_name)}" במערכת MISSIONS',
                to_name,
                f'תוייגת ע"י <b>{_mail_esc(actor_name)}</b> בשיחה ברשומה '
                f'<b>"{_mail_esc(item_title)}"</b> בלוח <b>{_mail_esc(board_name)}</b> '
                f'במערכת missions.',
                "כניסה לשיחה", _item_link(board_id, task_id, base)))


# What each kind of event is called, and which builder writes it.
ITEM_MAILS = {"assign": _item_assigned_mail, "mention": _item_mention_mail}


def _item_mail(db, uid, task, board, actor_id, kind, base=None):
    """One person, one event → (to, subject, html), or None if it must not go.

    Every reason not to send lives here rather than at the five call sites: the
    board's notification switch, a recipient who is not a real reachable user,
    a deactivated account, and the person who did it — nobody is told by mail
    about their own keystroke.
    """
    if not uid or task is None or kind not in ITEM_MAILS:
        return None
    if uid == actor_id or not _board_notify_on(board):
        return None
    to = db.query(User).filter(User.id == uid).first()
    if not to or not to.email or to.is_active is False:
        return None
    actor = db.query(User).filter(User.id == actor_id).first()
    subject, html = ITEM_MAILS[kind](
        to.name, actor.name if actor else "משתמש במערכת", task.title,
        board.name if board else "", task.board_id, task.id, base)
    return (to.email, subject, html)


def _send_item_mails(msgs):
    """Send what was built, after the commit. A message that could not be built
    is a None in the list — the call sites stay one line that way."""
    for m in msgs:
        if m:
            _send_email(*m)


@app.get("/api/boards/{board_id}/members")
def list_board_members(board_id: int):
    with Session(engine) as db:
        ms = db.query(BoardMember).filter(BoardMember.board_id == board_id).all()
        member_ids = {m.user_id for m in ms}
        out = []
        for m in ms:
            u = db.query(User).filter(User.id == m.user_id).first()
            out.append({"user_id": m.user_id, "name": u.name if u else "—",
                        "email": u.email if u else "", "role": m.role,
                        # a member who was deactivated stays listed: somebody
                        # has to be able to see them and take them off the board
                        "is_active": (u.is_active is not False) if u else True})
        # who could still be invited — never a deactivated account
        available = [{"id": u.id, "name": u.name} for u in db.query(User).all()
                     if u.id not in member_ids and u.is_active is not False]
        return {"members": out, "available": available}

@app.post("/api/boards/{board_id}/members")
def add_board_member(board_id: int, data: dict, request: Request = None,
                     actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if not _is_board_admin(db, board_id, actor_id):
            raise HTTPException(403, "רק מנהל הלוח יכול לנהל הרשאות")
        uid = data.get("user_id")
        # The picker no longer offers them, but the picker is not the rule: an
        # invitation is a grant of access, and a deactivated account must not
        # receive one however the request was made.
        if _account_blocked(db, uid):
            raise HTTPException(400, "לא ניתן להזמין ללוח משתמש מושבת")
        role = data.get("role", "editor")
        if role not in BOARD_ROLES:
            role = "editor"
        m = db.query(BoardMember).filter(BoardMember.board_id == board_id, BoardMember.user_id == uid).first()
        is_new = m is None
        if m:
            m.role = role
        else:
            db.add(BoardMember(board_id=board_id, user_id=uid, role=role))
        board = db.query(Board).filter(Board.id == board_id).first()
        inviter = db.query(User).filter(User.id == actor_id).first()
        # in-app notification to the added user — every role, only on a real add,
        # and only if the board hasn't switched notifications off
        if is_new and _board_notify_on(board):
            _notify(db, uid, "board_add", f"נוספת ללוח '{board.name if board else ''}'",
                    f"{(inviter.name + ' ') if inviter else ''}הוסיף/ה אותך ללוח בתפקיד {BROLE_HE.get(role, role)}.",
                    board_id=board_id)
        db.commit()
        # email the invitee — only on a genuine new invitation, any role
        if is_new:
            invitee = db.query(User).filter(User.id == uid).first()
            if invitee and invitee.email and board:
                _send_email(invitee.email,
                            f'צורפת ללוח "{board.name}" במערכת missions',
                            _board_invite_html(invitee.name, board.name,
                                               inviter.name if inviter else "מנהל הלוח",
                                               board.id, _app_base_url(request)))
        return {"status": "ok", "invited": is_new}

@app.patch("/api/boards/{board_id}/members/{uid}")
def update_board_member(board_id: int, uid: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if not _is_board_admin(db, board_id, actor_id):
            raise HTTPException(403, "רק מנהל הלוח יכול לנהל הרשאות")
        m = db.query(BoardMember).filter(BoardMember.board_id == board_id, BoardMember.user_id == uid).first()
        if not m:
            raise HTTPException(404, "member not found")
        role = data.get("role")
        if role in BOARD_ROLES:
            # don't allow demoting the last admin
            if m.role == "admin" and role != "admin":
                admins = db.query(BoardMember).filter(BoardMember.board_id == board_id, BoardMember.role == "admin").count()
                if admins <= 1:
                    raise HTTPException(400, "חייב להישאר לפחות מנהל אחד ללוח")
            m.role = role
        db.commit()
        return {"status": "ok"}

@app.delete("/api/boards/{board_id}/members/{uid}")
def remove_board_member(board_id: int, uid: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if not _is_board_admin(db, board_id, actor_id):
            raise HTTPException(403, "רק מנהל הלוח יכול לנהל הרשאות")
        m = db.query(BoardMember).filter(BoardMember.board_id == board_id, BoardMember.user_id == uid).first()
        if not m:
            return {"status": "removed"}
        if m.role == "admin":
            admins = db.query(BoardMember).filter(BoardMember.board_id == board_id, BoardMember.role == "admin").count()
            if admins <= 1:
                raise HTTPException(400, "לא ניתן להסיר את מנהל הלוח האחרון")
        db.delete(m)
        board = db.query(Board).filter(Board.id == board_id).first()
        actor = db.query(User).filter(User.id == actor_id).first()
        # notify the removed user (any role) — no board deep-link (no longer a member)
        if _board_notify_on(board):
            _notify(db, uid, "board_remove", f"הוסרת מהלוח '{board.name if board else ''}'",
                    f"{(actor.name + ' ') if actor else ''}הסיר/ה אותך מהלוח.")
        db.commit()
        return {"status": "removed"}

# ── In-app notifications (התראות) ───────────────────────────────────
def _serialize_notif(n):
    return {"id": n.id, "type": n.type, "title": n.title, "body": n.body,
            "board_id": n.board_id, "task_id": n.task_id,
            "is_read": bool(n.is_read), "created_at": n.created_at}

@app.get("/api/notifications")
def list_notifications(user_id: int = Depends(current_user_id), limit: int = 30):
    if user_id is None:
        raise HTTPException(400, "user_id required")
    with Session(engine) as db:
        q = db.query(Notification).filter(Notification.user_id == user_id)
        unread = q.filter(Notification.is_read == False).count()
        items = q.order_by(Notification.created_at.desc()).limit(max(1, min(100, limit))).all()
        return {"notifications": [_serialize_notif(n) for n in items], "unread_count": unread}

@app.post("/api/notifications/{nid}/read")
def read_notification(nid: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        n = db.query(Notification).filter(Notification.id == nid,
                                          Notification.user_id == actor_id).first()
        if n and not n.is_read:
            n.is_read = True
            db.commit()
        return {"status": "ok"}

@app.post("/api/notifications/read-all")
def read_all_notifications(data: dict, actor_id: int = Depends(current_user_id)):
    uid = actor_id  # you may only clear your own notifications
    with Session(engine) as db:
        db.query(Notification).filter(Notification.user_id == uid,
                                      Notification.is_read == False).update({Notification.is_read: True})
        db.commit()
        return {"status": "ok"}

# ── ייצוא הלוח לאקסל ────────────────────────────────────────────────
# The client renders the board; the export therefore ships the grid it is
# already showing (current filters, sort, column structure and the values it
# computes — formulas, per-column status labels, linked-item titles) and this
# endpoint only turns that grid into a real .xlsx. The caller can never see
# more than the board API already handed it, so no data is widened there; the
# limits below just keep a malformed payload from eating memory.
#
# The conversation is the exception, and it has to be. A board's comments are
# not on screen — the client holds only the threads whose panel someone opened —
# so there is no grid to ship and the sheet is read here. It is not a widening:
# this endpoint already refuses anyone who is not a member of the board, and a
# member may read every one of these comments through the comments API. What is
# gathered is what that API would answer, in the same order the board is read.
XLSX_MAX_ROWS, XLSX_MAX_COLS, XLSX_MAX_TEXT = 20000, 80, 4000
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def _xlsx_argb(hex_color):
    """#rrggbb → opaque ARGB. Without the explicit FF alpha openpyxl writes 00,
    which some viewers read as a fully transparent fill."""
    return "FF" + hex_color[1:].upper()

def _xlsx_luma(hex_color):
    """Perceived brightness of #rrggbb (0–255) — picks black or white text."""
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return 255
    return 0.299 * r + 0.587 * g + 0.114 * b

def _xlsx_cell(ws, row, col, spec):
    """Write one exported cell. `spec` is a scalar, or {v,c,t} with an optional
    background colour and type hint. Text is always written as text — a value
    starting with '=' must never become a live formula in the exported file."""
    from openpyxl.styles import Alignment, Font, PatternFill

    val, color, kind = spec, None, None
    if isinstance(spec, dict):
        val, color, kind = spec.get("v"), spec.get("c"), spec.get("t")
    cell = ws.cell(row=row, column=col)
    if val is None or val == "":
        cell.value = None
    elif kind in ("date", "datetime"):
        try:
            cell.value = datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=None)
            cell.number_format = "DD/MM/YYYY" if kind == "date" else "DD/MM/YYYY HH:MM"
        except ValueError:
            cell.value = str(val)[:XLSX_MAX_TEXT]
            cell.data_type = "s"
    elif isinstance(val, bool):
        cell.value = "כן" if val else ""
        cell.data_type = "s"
    elif isinstance(val, (int, float)):
        cell.value = val
    else:
        cell.value = str(val)[:XLSX_MAX_TEXT]
        cell.data_type = "s"          # never a formula, whatever the text is
    if color and _valid_hex(color):
        cell.fill = PatternFill("solid", fgColor=_xlsx_argb(color))
        # one regular weight everywhere, as in the app — colour carries the meaning
        cell.font = Font(color="FFFFFFFF" if _xlsx_luma(color) < 150 else "FF1F2937")
    cell.alignment = Alignment(vertical="center", wrap_text=False)
    return cell

# The conversation sheet's columns, in the order they are written.
TALK_HEADERS = ["מספר מזהה", "פריט", "סוג", "מאת", "נכתב", "תוכן",
                "לייקים", "קבצים", "מזהה הודעה", "בתגובה להודעה"]


# The sheet that carries the attachments. A file cell shows the file's NAME, and
# that is what a grid can hold — so exported as a grid, a board's files become a
# list of names, and re-imported they are names with nothing behind them. The
# names stay in the cell where a reader expects them, and the sheet below carries
# what a cell cannot: which item, which column, and where the bytes are.
FILE_HEADERS = ["מספר מזהה", "פריט", "עמודה", "שם הקובץ", "כתובת"]


def _export_files(db, board_id):
    """Every file attached to a cell of this board: one row per file.

    Read from the board rather than from the grid the browser sent, because the
    grid holds the rendered cell — the names — and the address of each file is
    exactly the half it drops.
    """
    b = db.query(Board).filter(Board.id == board_id).first()
    cols = [c for c in ((b.settings or {}).get("columns") or [])
            if c.get("type") == "files"] if b else []
    if not cols:
        return []
    titles = {c["id"]: (c.get("title") or "") for c in cols}
    rows = []
    for t in (db.query(Task).filter(Task.board_id == board_id)
              .order_by(Task.id).limit(XLSX_MAX_ROWS).all()):
        for cid, title in titles.items():
            for f in (t.custom_fields or {}).get(cid) or []:
                if not isinstance(f, dict) or not (f.get("name") or f.get("url")):
                    continue
                rows.append([t.item_uid or "", t.title or "", title,
                             f.get("name") or "", f.get("url") or ""])
                if len(rows) >= XLSX_MAX_ROWS:
                    return rows
    return rows


def _export_conversation(db, board_id):
    """Every comment on the board's items, threaded, oldest first.

    One row per message. A reply is a row of its own, marked as one and carrying
    the id of the message it answers, so the thread can be rebuilt from the file
    without the reader having to guess from indentation or order. Sub-items are
    items here too: their conversations are on the board and would otherwise be
    the one part of it the export loses.
    """
    tasks = {t.id: t for t in db.query(Task).filter(Task.board_id == board_id).all()}
    if not tasks:
        return []
    names = {u.id: u.name for u in db.query(User).all()}
    rows = []
    comments = (db.query(Comment)
                .filter(Comment.task_id.in_(list(tasks)))
                .order_by(Comment.task_id, Comment.created_at, Comment.id)
                .limit(XLSX_MAX_ROWS).all())
    for c in comments:
        t = tasks.get(c.task_id)
        if t is None:                      # a comment whose item has since gone
            continue
        files = [f.get("name") for f in (c.attachments or []) if isinstance(f, dict) and f.get("name")]
        rows.append([
            t.item_uid or "",
            t.title or "",
            "תגובה" if c.parent_id else "עדכון",
            names.get(c.user_id, ""),
            {"v": c.created_at.isoformat() if c.created_at else "", "t": "datetime"},
            c.content or "",
            len(c.likes or []),
            ", ".join(files),
            c.id,
            c.parent_id or "",
        ])
    return rows


@app.post("/api/boards/{board_id}/export/xlsx")
def export_board_xlsx(board_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Board → .xlsx. Two sheets: the board, with sub-items nested and
    collapsible under their item and their own columns named in a header of
    their own; and the conversation, one row per comment and per reply. See the
    note above on where each of the two comes from."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "board not found")
        # export is a full read of the board — require membership unconditionally
        # (this used to skip the check when the caller omitted user_id)
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        board_color = b.color if _valid_hex(b.color) else "#0073ea"
        talk = _export_conversation(db, board_id)
        attached = _export_files(db, board_id)

    headers = [str(h)[:XLSX_MAX_TEXT] for h in (data.get("columns") or [])][:XLSX_MAX_COLS]
    rows = (data.get("rows") or [])[:XLSX_MAX_ROWS]
    if not headers:
        raise HTTPException(400, "אין עמודות לייצוא")

    wb = Workbook()
    ws = wb.active
    ws.title = (re.sub(r"[\\/*?:\[\]]", " ", b.name or "לוח").strip() or "לוח")[:31]
    ws.sheet_view.rightToLeft = True
    # the parent row sits ABOVE its detail rows, so Excel's collapse arrows line
    # up with the board: a group folds its items, an item folds its sub-items
    ws.sheet_properties.outlinePr.summaryBelow = False

    head_fill = PatternFill("solid", fgColor=_xlsx_argb(board_color))
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.data_type = "s"
        c.font = Font(color="FFFFFFFF")     # regular weight; the fill marks the header
        c.fill = head_fill
        c.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    widths = [len(h) + 2 for h in headers]
    r = 1
    for row in rows:
        if not isinstance(row, dict):
            continue
        r += 1
        level = row.get("level")
        level = level if isinstance(level, int) and 0 <= level <= 2 else 0
        cells = (row.get("cells") or [])[:len(headers)]
        for i, spec in enumerate(cells, start=1):
            cell = _xlsx_cell(ws, r, i, spec)
            if row.get("group"):
                # The group's own colour, not the board's: it is what the group
                # is headed with here, and writing it is also what lets the file
                # be imported back as the same board — the importer reads a
                # group row's colour as the group's. A row that did not bring
                # one falls back to the board's, which is how this read before.
                gc = row.get("gcolor")
                cell.font = Font(color=_xlsx_argb(gc if _valid_hex(gc) else board_color))
            # A sub-item block names its own columns, because they are not the
            # item's: a board can give its sub-items columns that exist nowhere
            # else, and under the item's header those values had no heading to
            # sit under and were left out of the file altogether. Grey, so it
            # reads as a header without competing with the sheet's own.
            if row.get("subhead"):
                cell.fill = PatternFill("solid", fgColor="FFEDEFF5")
                cell.font = Font(color="FF505A72")
            if i == 1 and level:
                cell.alignment = Alignment(vertical="center", indent=level * 2)
            text = "" if cell.value is None else str(cell.value)
            widths[i - 1] = max(widths[i - 1], min(len(text) + 2 + level * 2, 60))
        if level:
            ws.row_dimensions[r].outlineLevel = level
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── sheet 2: the conversation ──────────────────────────────────────────
    # Always written, even empty: a file with a predictable shape is one that
    # can be read by something other than a person, and "no messages yet" is an
    # answer worth being able to read.
    ts = wb.create_sheet("שיחות")
    ts.sheet_view.rightToLeft = True
    for i, h in enumerate(TALK_HEADERS, start=1):
        c = ts.cell(row=1, column=i, value=h)
        c.data_type = "s"
        c.font = Font(color="FFFFFFFF")
        c.fill = head_fill
        c.alignment = Alignment(vertical="center")
    ts.freeze_panes = "A2"
    ts.auto_filter.ref = f"A1:{get_column_letter(len(TALK_HEADERS))}1"
    twidths = [len(h) + 2 for h in TALK_HEADERS]
    for n, trow in enumerate(talk, start=2):
        for i, spec in enumerate(trow, start=1):
            cell = _xlsx_cell(ts, n, i, spec)
            text = "" if cell.value is None else str(cell.value)
            # the message body is the one column allowed to be wide, and the only
            # one that wraps — a comment is a paragraph, not a field
            cap = 70 if TALK_HEADERS[i - 1] == "תוכן" else 26
            twidths[i - 1] = max(twidths[i - 1], min(len(text) + 2, cap))
        ts.cell(row=n, column=TALK_HEADERS.index("תוכן") + 1).alignment = Alignment(
            vertical="top", wrap_text=True)
    for i, w in enumerate(twidths, start=1):
        ts.column_dimensions[get_column_letter(i)].width = w

    # ── sheet 3: the files ─────────────────────────────────────────────────
    # Written whenever the board has a file column, empty or not, for the same
    # reason the conversation sheet always is: a predictable shape can be read
    # back, and "this board has file columns and nothing in them" is an answer.
    if attached or any(c.get("type") == "files"
                       for c in ((b.settings or {}).get("columns") or [])):
        fs = wb.create_sheet("קבצים")
        fs.sheet_view.rightToLeft = True
        for i, h in enumerate(FILE_HEADERS, start=1):
            c = fs.cell(row=1, column=i, value=h)
            c.data_type = "s"
            c.font = Font(color="FFFFFFFF")
            c.fill = head_fill
            c.alignment = Alignment(vertical="center")
        fs.freeze_panes = "A2"
        fs.auto_filter.ref = f"A1:{get_column_letter(len(FILE_HEADERS))}1"
        fwidths = [len(h) + 2 for h in FILE_HEADERS]
        for n, frow in enumerate(attached, start=2):
            for i, spec in enumerate(frow, start=1):
                cell = _xlsx_cell(fs, n, i, spec)
                text = "" if cell.value is None else str(cell.value)
                fwidths[i - 1] = max(fwidths[i - 1], min(len(text) + 2, 60))
        for i, w in enumerate(fwidths, start=1):
            fs.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    # "<שם הלוח>_<מספר הלוח>.xlsx" — the number keeps exports of same-named
    # boards apart, and says which board a file on disk came from
    fname = re.sub(r"[^\w֐-׿ .()-]", "", (b.name or "board")).strip() or "board"
    quoted = urllib.parse.quote(f"{fname}_{board_id}.xlsx")
    return Response(content=buf.getvalue(), media_type=XLSX_MIME,
                    headers={"Content-Disposition": f"attachment; filename=board_{board_id}.xlsx; "
                                                    f"filename*=UTF-8''{quoted}"})

# ── Column-level permissions (הרשאות עמודה) ─────────────────────────
@app.post("/api/boards/{board_id}/columns/{col_id}/permissions")
def set_col_permissions(board_id: int, col_id: str, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if _board_role(db, board_id, actor_id) != "admin":
            raise HTTPException(403, "רק מנהל לוח יכול לקבוע הרשאות עמודה")
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "board not found")
        s = dict(b.settings or {})
        cols = [dict(c) for c in s.get("columns", [])]
        found = False
        for c in cols:
            if c["id"] == col_id:
                perms = dict(c.get("perms") or {})
                uid = str(data.get("user_id")); perm = data.get("perm")
                if perm in ("view", "edit") and _account_blocked(db, data.get("user_id")):
                    raise HTTPException(400, "לא ניתן להגדיר הרשאת עמודה למשתמש מושבת")
                if perm in ("view", "edit", "none"):
                    perms[uid] = perm
                else:
                    perms.pop(uid, None)
                c["perms"] = perms; found = True
        if not found:
            raise HTTPException(404, "column not found")
        s["columns"] = cols; b.settings = s; db.commit()
        return {"columns": cols}

# ── Environment / workspace members (הזמנה לסביבה) ──────────────────
WS_ROLES = ("admin", "member", "viewer")

@app.get("/api/workspace/members")
def workspace_members():
    with Session(engine) as db:
        ms = db.query(WorkspaceMember).all()
        member_ids = {m.user_id for m in ms}
        out = []
        for m in ms:
            u = db.query(User).filter(User.id == m.user_id).first()
            out.append({"user_id": m.user_id, "name": u.name if u else "—",
                        "email": u.email if u else "", "role": m.role,
                        "is_active": (u.is_active is not False) if u else True})
        available = [{"id": u.id, "name": u.name} for u in db.query(User).all()
                     if u.id not in member_ids and u.is_active is not False]
        return {"members": out, "available": available}

@app.post("/api/workspace/members")
def workspace_add(data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if _ws_role(db, actor_id) != "admin":
            raise HTTPException(403, "רק מנהל סביבה יכול להזמין")
        uid = data.get("user_id"); role = data.get("role", "member")
        if _account_blocked(db, uid):
            raise HTTPException(400, "לא ניתן להזמין לסביבה משתמש מושבת")
        if role not in WS_ROLES:
            role = "member"
        m = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid).first()
        if m:
            m.role = role
        else:
            db.add(WorkspaceMember(user_id=uid, role=role))
        db.commit()
        return {"status": "ok"}

@app.patch("/api/workspace/members/{uid}")
def workspace_update(uid: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if _ws_role(db, actor_id) != "admin":
            raise HTTPException(403, "רק מנהל סביבה")
        m = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid).first()
        if not m:
            raise HTTPException(404, "member not found")
        role = data.get("role")
        if role in WS_ROLES:
            if m.role == "admin" and role != "admin":
                if db.query(WorkspaceMember).filter(WorkspaceMember.role == "admin").count() <= 1:
                    raise HTTPException(400, "חייב להישאר מנהל סביבה אחד")
            m.role = role
        db.commit()
        return {"status": "ok"}

@app.delete("/api/workspace/members/{uid}")
def workspace_remove(uid: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if _ws_role(db, actor_id) != "admin":
            raise HTTPException(403, "רק מנהל סביבה")
        m = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == uid).first()
        if m and m.role == "admin":
            if db.query(WorkspaceMember).filter(WorkspaceMember.role == "admin").count() <= 1:
                raise HTTPException(400, "לא ניתן להסיר את מנהל הסביבה האחרון")
        if m:
            db.delete(m); db.commit()
        return {"status": "removed"}

# ── Environments (Monday-style workspaces) ───────────────────────────
# Reads are open to all; create/edit/delete are restricted to system (workspace) admins.
def _env_role(db, env_id, user_id):
    """A user's role within one environment: 'admin' for a system admin
    (manages every environment), else the per-environment role (manager|member), or None.

    "System admin" here is the same one question as everywhere else about
    environments — see _can_admin_envs. It used to be the WorkspaceMember row
    alone, so someone who could delete an environment from the admin screen
    could still not open its member list.
    """
    if user_id is None:
        return None
    if _can_admin_envs(db, user_id):
        return "admin"
    m = (db.query(EnvironmentMember)
         .filter(EnvironmentMember.environment_id == env_id, EnvironmentMember.user_id == user_id).first())
    if m:
        return m.role or "member"
    # everyone is a member of the primary workspace, with or without a row
    return "member" if env_id == _primary_env_id(db) else None

def _can_manage_env(db, env_id, user_id):
    """System admins and environment managers may manage an environment."""
    return _env_role(db, env_id, user_id) in ("admin", "manager")

def _env_out(e, board_count=0, my_role=None):
    return {"id": e.id, "name": e.name, "icon": e.icon, "color": e.color,
            "position": e.position, "is_primary": bool(e.is_primary), "board_count": board_count,
            # an environment with no icon of its own is drawn as its creator's
            # avatar, so the client needs to know whose
            "created_by": e.created_by,
            "my_role": my_role, "can_manage": my_role in ("admin", "manager")}

@app.get("/api/environments")
def list_environments(user_id: int = Depends(current_user_id)):
    """System admins see every environment; managers/members see only the
    environments they were granted access to."""
    with Session(engine) as db:
        counts = dict(db.query(Board.environment_id, func.count(Board.id))
                        .filter(Board.deleted_at == None)   # noqa: E711 — skip the recycle bin
                        .group_by(Board.environment_id).all())
        # Environments always read in alphabetical (א-ב) order by name — including
        # newly created ones. Sorted in Python so SQLite (local) and Postgres (prod)
        # order Hebrew identically, regardless of the DB's collation.
        allenvs = db.query(Environment).all()
        allenvs.sort(key=lambda e: (e.name or "").strip().casefold())
        is_sysadmin = _can_admin_envs(db, user_id)
        roles = {}
        if user_id is not None:
            roles = {m.environment_id: (m.role or "member") for m in
                     db.query(EnvironmentMember).filter(EnvironmentMember.user_id == user_id).all()}
            # the primary workspace is everybody's, whether or not a row says so
            pid = _primary_env_id(db)
            if pid is not None:
                roles.setdefault(pid, "member")
        if is_sysadmin:
            envs = allenvs
        elif user_id is not None:
            envs = [e for e in allenvs if e.id in roles]
        else:
            envs = []
        def _role_for(e):
            return "admin" if is_sysadmin else roles.get(e.id)
        return {"environments": [_env_out(e, counts.get(e.id, 0), _role_for(e)) for e in envs]}

@app.post("/api/environments")
def create_environment(data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if not _cap(db, actor_id, "create_environment"):
            raise HTTPException(403, "אין לך הרשאה ליצור סביבה")
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "נדרש שם לסביבה")
        org = db.query(Organization).first()
        pos = db.query(Environment).count()
        # No icon by default: an environment with none wears its creator's
        # avatar, which is a truer first impression than the same 🏢 on every
        # one of them. The colour is still assigned, because it is the tile a
        # chosen glyph sits on later.
        e = Environment(name=name, icon=(data.get("icon") or None),
                        color=data.get("color") or _ENV_COLORS[pos % len(_ENV_COLORS)],
                        position=pos, organization_id=org.id if org else None,
                        created_by=actor_id)
        db.add(e); db.commit(); db.refresh(e)
        # Whoever makes an environment manages it — the same rule a board
        # follows ("creator becomes the board admin"). Without this row the
        # environment was created belonging to nobody: the listing shows a
        # non-workspace-admin only the environments they are a member of, so
        # the creator got a "הסביבה נוצרה" toast for something that then did
        # not appear anywhere, and nobody but a workspace admin could ever see
        # it or hand out access to it. It existed and was unreachable.
        if actor_id is not None:
            db.add(EnvironmentMember(environment_id=e.id, user_id=actor_id, role="manager"))
            db.commit()
        my_role = "admin" if _can_admin_envs(db, actor_id) else "manager"
        return _env_out(e, 0, my_role)

@app.patch("/api/environments/{env_id}")
def update_environment(env_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        actor = actor_id
        if not _can_manage_env(db, env_id, actor):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה יכול לערוך אותה")
        e = db.query(Environment).filter(Environment.id == env_id).first()
        if not e:
            raise HTTPException(404, "סביבה לא נמצאה")
        if "name" in data and (data.get("name") or "").strip():
            e.name = data["name"].strip()
        # `in data`, not truthiness: an explicit empty icon is how the editor
        # says "go back to the creator's avatar", and that has to be storable.
        if "icon" in data:
            e.icon = (data["icon"] or "").strip() or None
        if data.get("color"):
            e.color = data["color"]
        db.commit()
        return _env_out(e, my_role=_env_role(db, env_id, actor))

@app.delete("/api/environments/{env_id}")
def delete_environment(env_id: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if not _can_admin_envs(db, actor_id):
            raise HTTPException(403, "רק מנהל מערכת יכול למחוק סביבה")
        e = db.query(Environment).filter(Environment.id == env_id).first()
        if not e:
            raise HTTPException(404, "סביבה לא נמצאה")
        if e.is_primary:
            raise HTTPException(400, "לא ניתן למחוק את סביבת ברירת המחדל")
        # move boards to the primary workspace (don't delete them) so nothing disappears
        primary = db.query(Environment).filter(Environment.is_primary == True).first()
        db.query(Board).filter(Board.environment_id == env_id).update(
            {Board.environment_id: primary.id if primary else None})
        db.query(EnvironmentMember).filter(EnvironmentMember.environment_id == env_id).delete()
        db.delete(e); db.commit()
        return {"status": "deleted"}

ENV_ROLES = ("manager", "member")
ENV_ROLE_HE = {"admin": "מנהל מערכת", "manager": "מנהל סביבה", "member": "חבר"}

# ── Environment members — system admins and environment managers ──
@app.get("/api/environments/{env_id}/members")
def environment_members(env_id: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if not _can_manage_env(db, env_id, actor_id):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה")
        if not db.query(Environment).filter(Environment.id == env_id).first():
            raise HTTPException(404, "סביבה לא נמצאה")
        rows = db.query(EnvironmentMember).filter(EnvironmentMember.environment_id == env_id).all()
        users = {u.id: u for u in db.query(User).all()}
        by_row = {m.user_id: (m.role or "member") for m in rows}
        # On the primary workspace everyone is a member — so everyone is listed,
        # and a row only ever says "manager". A screen that listed the rows
        # alone would show four names for a workspace the whole organisation is
        # in, and offer to "add" people who are already there.
        everyone = (env_id == _primary_env_id(db))
        shown = users.keys() if everyone else by_row.keys()
        members = [{"user_id": uid, "name": users[uid].name,
                    "email": users[uid].email,
                    "avatar_url": users[uid].avatar_url,
                    "role": by_row.get(uid, "member"),
                    "role_he": ENV_ROLE_HE.get(by_row.get(uid, "member"), "member"),
                    "is_active": users[uid].is_active is not False}
                   for uid in shown if uid in users]
        members.sort(key=lambda x: (x["role"] != "manager", x["name"]))
        member_ids = {m["user_id"] for m in members}
        # never offer a deactivated account as somebody to add
        available = [{"id": u.id, "name": u.name} for u in users.values()
                     if u.id not in member_ids and u.is_active is not False]
        # only a system admin may hand out the manager role; a plain env manager can add members
        can_set_manager = _can_admin_envs(db, actor_id)
        return {"members": members, "available": available,
                "can_set_manager": can_set_manager, "everyone": everyone}

@app.post("/api/environments/{env_id}/members")
def environment_add_member(env_id: int, data: dict, request: Request = None,
                           actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        actor = actor_id
        if not _can_manage_env(db, env_id, actor):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה")
        if not db.query(Environment).filter(Environment.id == env_id).first():
            raise HTTPException(404, "סביבה לא נמצאה")
        uid = data.get("user_id")
        if _account_blocked(db, uid):
            raise HTTPException(400, "לא ניתן להוסיף לסביבה משתמש מושבת")
        role = data.get("role") if data.get("role") in ENV_ROLES else "member"
        # only a system admin may grant the manager role
        if role == "manager" and not _can_admin_envs(db, actor):
            role = "member"
        if not uid:
            return {"status": "ok"}
        m = db.query(EnvironmentMember).filter(
            EnvironmentMember.environment_id == env_id, EnvironmentMember.user_id == uid).first()
        is_new = m is None
        if m:
            m.role = role
        else:
            db.add(EnvironmentMember(environment_id=env_id, user_id=uid, role=role))
        env = db.query(Environment).filter(Environment.id == env_id).first()
        inviter = db.query(User).filter(User.id == actor).first()
        # Being added to a workspace said nothing to the person it happened to —
        # no mail, no notification, nothing to see. Only a board invitation ever
        # spoke, so adding someone to a workspace and waiting for them to hear
        # about it was a wait with no end.
        # Like the board invitation: only a genuine new membership, never a role
        # change, so promoting somebody does not read as a fresh invitation.
        if is_new:
            _notify(db, uid, "env_add", f"נוספת לסביבה '{env.name if env else ''}'",
                    f"{(inviter.name + ' ') if inviter else ''}הוסיף/ה אותך לסביבה בתפקיד {ENV_ROLE_HE.get(role, role)}.")
        db.commit()
        if is_new:
            invitee = db.query(User).filter(User.id == uid).first()
            if invitee and invitee.email and env:
                _send_email(invitee.email,
                            f'צורפת לסביבת העבודה "{env.name}" במערכת missions',
                            _env_invite_html(invitee.name, env.name,
                                             inviter.name if inviter else "מנהל הסביבה",
                                             _app_base_url(request)))
        return {"status": "ok", "invited": is_new}

@app.patch("/api/environments/{env_id}/members/{uid}")
def environment_set_member_role(env_id: int, uid: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Promote/demote an environment member (manager|member). System admin only —
    handing out the manager role is a system-level grant."""
    with Session(engine) as db:
        if not _can_admin_envs(db, actor_id):
            raise HTTPException(403, "רק מנהל מערכת יכול לשנות תפקיד בסביבה")
        role = data.get("role") if data.get("role") in ENV_ROLES else "member"
        m = db.query(EnvironmentMember).filter(
            EnvironmentMember.environment_id == env_id, EnvironmentMember.user_id == uid).first()
        if not m:
            # In the primary workspace a member has no row of their own — they
            # are a member by being a user — so promoting one is a row being
            # written for the first time, not a missing member.
            if env_id != _primary_env_id(db) or not db.query(User).filter(User.id == uid).first():
                raise HTTPException(404, "החבר לא נמצא בסביבה")
            m = EnvironmentMember(environment_id=env_id, user_id=uid, role=role)
            db.add(m); db.commit()
            return {"status": "ok", "role": role}
        m.role = role
        db.commit()
        return {"status": "ok", "role": role}

@app.delete("/api/environments/{env_id}/members/{uid}")
def environment_remove_member(env_id: int, uid: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        if not _can_manage_env(db, env_id, actor_id):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה")
        # a user may be removed from an environment only if they don't belong to any
        # board within it — otherwise they'd lose access to boards they're part of
        env_boards = {b.id: b.name for b in db.query(Board).filter(
            Board.environment_id == env_id, Board.is_archived == False, Board.deleted_at == None).all()}
        if env_boards:
            linked = (db.query(BoardMember)
                      .filter(BoardMember.user_id == uid,
                              BoardMember.board_id.in_(list(env_boards.keys()))).all())
            names = [env_boards[bm.board_id] for bm in linked if bm.board_id in env_boards]
            if names:
                raise HTTPException(400, "לא ניתן להסיר משתתף זה מאחר והוא משוייך ללוחות הבאים בסביבה: "
                                    + ", ".join(names))
        m = db.query(EnvironmentMember).filter(
            EnvironmentMember.environment_id == env_id, EnvironmentMember.user_id == uid).first()
        # Nobody can be taken out of the primary workspace: belonging to it is
        # what being a user here means, and the row would be back on the next
        # listing anyway. Taking a manager's row away is a real change though —
        # it is the demotion — so that one is allowed and says what it did.
        if env_id == _primary_env_id(db):
            if m and (m.role or "member") == "manager":
                db.delete(m); db.commit()
                return {"status": "demoted"}
            raise HTTPException(400, "כל משתמשי המערכת חברים בסביבה הראשית, ולכן אי אפשר להסיר מהם אותה. "
                                     "אפשר להסיר הרשאה ללוח מסוים מתוך הלוח עצמו.")
        if m:
            db.delete(m); db.commit()
        return {"status": "removed"}

# ── Folders (group boards inside an environment) — env managers + sysadmins ──
def _folder_out(db, f, user_id):
    return {"id": f.id, "environment_id": f.environment_id, "name": f.name,
            "position": f.position or 0,
            "can_manage": _can_manage_env(db, f.environment_id, user_id)}

@app.get("/api/folders")
def list_folders(user_id: int = Depends(current_user_id)):
    """Folders across every environment the user can access."""
    with Session(engine) as db:
        folders = db.query(Folder).order_by(Folder.position, Folder.id).all()
        if user_id is not None and _ws_role(db, user_id) != "admin":
            env_ids = _user_env_ids(db, user_id)
            folders = [f for f in folders if f.environment_id in env_ids]
        return {"folders": [_folder_out(db, f, user_id) for f in folders]}

@app.post("/api/folders")
def create_folder(data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        actor = actor_id
        env_id = data.get("environment_id")
        if not _can_manage_env(db, env_id, actor):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה יכול ליצור תיקייה")
        if not db.query(Environment).filter(Environment.id == env_id).first():
            raise HTTPException(404, "סביבה לא נמצאה")
        name = (data.get("name") or "").strip() or "תיקייה חדשה"
        maxpos = db.query(func.max(Folder.position)).filter(Folder.environment_id == env_id).scalar()
        f = Folder(environment_id=env_id, name=name, position=(maxpos + 1) if maxpos is not None else 0)
        db.add(f); db.commit(); db.refresh(f)
        return _folder_out(db, f, actor)

@app.patch("/api/folders/{folder_id}")
def update_folder(folder_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        f = db.query(Folder).filter(Folder.id == folder_id).first()
        if not f:
            raise HTTPException(404, "תיקייה לא נמצאה")
        if not _can_manage_env(db, f.environment_id, actor_id):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה")
        if (data.get("name") or "").strip():
            f.name = data["name"].strip()
        db.commit()
        return _folder_out(db, f, actor_id)

@app.delete("/api/folders/{folder_id}")
def delete_folder(folder_id: int, actor_id: int = Depends(current_user_id)):
    """Delete a folder. Its boards are detached to the environment root — never deleted."""
    with Session(engine) as db:
        f = db.query(Folder).filter(Folder.id == folder_id).first()
        if not f:
            raise HTTPException(404, "תיקייה לא נמצאה")
        if not _can_manage_env(db, f.environment_id, actor_id):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה")
        db.query(Board).filter(Board.folder_id == folder_id).update({Board.folder_id: None})
        db.delete(f); db.commit()
        return {"status": "deleted", "id": folder_id}

@app.post("/api/environments/{env_id}/reorder")
def reorder_environment(env_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Persist the ordering of folders and boards in an environment. Body:
    {folders:[{id,position}], boards:[{id,folder_id,position}]}. Only items that
    belong to this environment are touched. Env managers / sysadmins only."""
    with Session(engine) as db:
        if not _can_manage_env(db, env_id, actor_id):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה יכול לסדר")
        env_folder_ids = {f.id for f in db.query(Folder).filter(Folder.environment_id == env_id).all()}
        for row in (data.get("folders") or []):
            f = db.query(Folder).filter(Folder.id == row.get("id"),
                                        Folder.environment_id == env_id).first()
            if f:
                f.position = int(row.get("position", 0))
        for row in (data.get("boards") or []):
            b = db.query(Board).filter(Board.id == row.get("id"),
                                       Board.environment_id == env_id).first()
            if not b:
                continue
            b.position = int(row.get("position", 0))
            fid = row.get("folder_id")
            # only allow assigning to a folder that belongs to this environment
            b.folder_id = fid if (fid in env_folder_ids) else None
        db.commit()
        return {"status": "ok"}

@app.get("/api/tasks")
def list_tasks(board_id: Optional[int] = None, status: Optional[str] = None):
    with Session(engine) as db:
        q = db.query(Task).filter(Task.is_archived == False)
        if board_id:
            q = q.filter(Task.board_id == board_id)
        if status:
            q = q.filter(Task.status == status)
        tasks = q.order_by(Task.position).limit(100).all()
        result = []
        for t in tasks:
            assignees = [{"id": u.id, "name": u.name} for u in (t.assignees or [])]
            result.append({
                "id": t.id, "board_id": t.board_id, "group_id": t.group_id,
                "title": t.title, "description": t.description,
                "status": t.status.value if hasattr(t.status, 'value') else t.status,
                "priority": t.priority.value if hasattr(t.priority, 'value') else t.priority,
                "due_date": t.due_date,
                "location_lat": t.location_lat, "location_lng": t.location_lng,
                "assignees": assignees,
            })
        return result

@app.post("/api/boards/{board_id}/environment")
def move_board_to_environment(board_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Move a board to another environment (workspace).

    Requires managing BOTH ends: you may not push a board into a workspace you
    do not run, nor pull one out of a workspace you do not run. A board admin
    who manages neither cannot move it. The board keeps its members, items and
    settings; it only leaves its folder, which belongs to the old environment.
    """
    with Session(engine) as db:
        actor = actor_id
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "לוח לא נמצא")
        env_id = data.get("environment_id")
        target = db.query(Environment).filter(Environment.id == env_id).first()
        if not target:
            raise HTTPException(404, "סביבה לא נמצאה")
        if b.environment_id == target.id:
            raise HTTPException(400, "הלוח כבר נמצא בסביבה הזו")
        if not _can_manage_env(db, target.id, actor):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה יכול להעביר לוח לסביבה זו")
        if b.environment_id and not _can_manage_env(db, b.environment_id, actor):
            raise HTTPException(403, "רק מנהל מערכת או מנהל הסביבה הנוכחית יכול להוציא ממנה לוח")
        maxpos = db.query(func.max(Board.position)).filter(Board.environment_id == target.id).scalar()
        b.environment_id = target.id
        b.folder_id = None            # folders belong to the environment it just left
        b.position = (maxpos + 1) if maxpos is not None else 0
        db.commit()
        return {"status": "moved", "board_id": b.id,
                "environment_id": target.id, "environment_name": target.name}

@app.post("/api/tasks")
def create_task(data: dict, request: Request = None,
                actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        parent_id = data.get("parent_id")
        board_id = data.get("board_id")
        group_id = data.get("group_id")
        if parent_id:
            parent = db.query(Task).filter(Task.id == parent_id).first()
            if not parent:
                raise HTTPException(404, "parent task not found")
            # sub-items inherit board (and group if not given) from their parent
            board_id = parent.board_id
            if group_id is None:
                group_id = parent.group_id
        # a task must belong to a board (directly or via its parent) — reject
        # orphan tasks instead of silently creating board-less junk data
        if not board_id:
            raise HTTPException(422, "board_id (or a valid parent_id) is required")
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            raise HTTPException(404, "board not found")
        # Creating an item is a write, and this endpoint never checked. Anyone
        # authenticated could add an item to ANY board, including one they were
        # never invited to — the same IDOR the other board mutations already
        # close via _require_board_edit. It also has to hold now that a public
        # board grants an implicit viewer role: being able to SEE a board must
        # not mean being able to add to it.
        _require_board_edit(db, board_id, actor_id)
        # a board-defined priority is not an enum value — resolve it to the one
        # it behaves as, and carry its label/colour on the item
        prio, prio_cf = _resolve_priority(board, data.get("priority"))
        task = Task(
            board_id=board_id,
            group_id=group_id,
            parent_id=parent_id,
            title=data.get("title", "Untitled"),
            description=data.get("description", ""),
            priority=prio or "medium",
            location_lat=data.get("location_lat"),
            location_lng=data.get("location_lng"),
            address=data.get("address"),
            created_by=actor_id,  # record the creator
        )
        due = data.get("due_date")
        if due:
            try:
                task.due_date = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
            except ValueError:
                pass
        status = data.get("status")
        if status:
            try:
                task.status = TaskStatus(status)
            except ValueError:
                pass
        ids = [i for i in (data.get("assignee_ids") or [])
               if _can_be_assigned(db, board_id, i)]   # invited members only
        if ids:
            task.assignees = db.query(User).filter(User.id.in_(ids)).all()
        # Boards created before "יוצר הרשומה" became a derived column carry it as
        # a plain people column, whose value has to be written on creation. The
        # derived `created_by` column needs nothing — it reads task.created_by.
        creator = actor_id
        cf = dict(data.get("custom_fields") or {})
        _filter_people_values(db, board_id, cf, None)   # invited members only
        # Connect columns on creation. This path never had the rules the edit
        # path has, so an item could be CREATED holding links to items the
        # creator cannot see — the same hole update_task closed, one endpoint
        # over. It is also what makes duplicating an item carry its links: the
        # copy posts the original's cells, and a two-way value is not a cell at
        # all but a relationship, so it has to be replayed as one.
        _bcols = (board.settings or {}).get("columns", []) if board else []
        _pending_links = []
        for _c in _bcols:
            if _c.get("type") == "mirror":
                cf.pop(_c["id"], None)     # computed on read; never stored
                continue
            if _c.get("type") != "connect":
                continue
            _v = cf.pop(_c["id"], None)
            if not isinstance(_v, list) or not _v:
                continue
            if not _duplicate_links_enabled():
                continue                       # system policy: a copy starts unlinked
            if _is_two_way(_c):
                _pending_links.append((_c, _v))
            else:
                cf[_c["id"]] = _merge_link_ids(db, _v, [], actor_id, _is_multi(_c))
        # A new item has no status yet — it shows "טרם הוגדר" until someone picks
        # one. task.status still holds the group's value so grouping, kanban and
        # the charts behave normally; this only says a human has not chosen. It
        # is cleared the moment a status is set. A caller that names a status on
        # creation (the form, a move) is choosing one, so the flag is not set.
        if not data.get("status"):
            cf.setdefault("status_unset", True)
        # and the same for the priority column, for the same reason: task.priority
        # keeps its "medium" default so sorting and the charts behave, while the
        # cell reads "טרם הוגדר" until someone actually picks a priority.
        if not data.get("priority"):
            cf.setdefault("priority_unset", True)
        elif prio_cf:
            for k, v in prio_cf.items():
                if v is None:
                    cf.pop(k, None)
                else:
                    cf.setdefault(k, v)
        if creator:
            cols = (board.settings or {}).get("columns", []) if board else []
            for c in cols:
                if c.get("id") == "sys_created_by" and c.get("type") == "people":
                    cf.setdefault("sys_created_by", [creator])
        if cf:
            task.custom_fields = cf
        # place the new item last — bottom of its group (or its parent's sub-list)
        from sqlalchemy import func as _func
        if parent_id is not None:
            maxpos = db.query(_func.max(Task.position)).filter(Task.parent_id == parent_id).scalar()
        else:
            _q = db.query(_func.max(Task.position)).filter(Task.board_id == board_id, Task.parent_id == None)
            _q = _q.filter(Task.group_id == group_id) if group_id is not None else _q.filter(Task.group_id == None)
            maxpos = _q.scalar()
        task.position = (maxpos + 1) if maxpos is not None else 0
        db.add(task)
        db.flush()   # get task.id for assignment notifications
        # a brand-new item (or sub-item) gets its own automatic identifier — an
        # item created after another was deleted never reuses that one's number
        _ensure_item_uid(db, task)
        # record the creation itself, so the item's activity log opens with a
        # "created" entry (not undoable — it is history, not a field change)
        _audit(db, task.id, "create", field=("subitem" if parent_id else "item"),
               old=None, new=task.title, user_id=actor_id)
        # two-way links need the row to exist first, since the relationship is
        # stored against the item id rather than in the item
        for _c, _v in _pending_links:
            _set_links(db, task, _c, _v, actor_id)
        # notify anyone assigned at creation time (skip the creator), honoring the switch
        _mail = []
        if ids:
            board = db.query(Board).filter(Board.id == board_id).first()
            if _board_notify_on(board):
                actor = actor_id
                for aid in set(ids):
                    if aid != actor:
                        _notify(db, aid, "assign", "שויכת למשימה",
                                f"שויכת למשימה '{task.title}'.", board_id=board_id, task_id=task.id)
                        # and by mail, which is the half that reaches somebody
                        # who is not in the app — built now, sent after commit
                        _mail.append(_item_mail(db, aid, task, board, actor, "assign",
                                                _app_base_url(request)))
        # ── automations ── a new item can trigger rules (assign, set status, notify)
        _run_automations(db, task, {"type": "item_created"}, actor_id)
        _bid, _tid = task.board_id, task.id
        db.commit()
        _send_item_mails(_mail)
        bus.publish("task.created", board_id=_bid, task_id=_tid, actor_id=actor_id)
        db.refresh(task)
        # return the fully-serialized task so the client can insert the new row
        # in place (no full-board refetch/re-render on every add)
        my_role = _board_role(db, board_id, creator)
        cols = (db.query(Board.settings).filter(Board.id == board_id).scalar() or {}).get("columns", [])
        return _serialize_task(task, db, user_id=creator, board_role=my_role, columns=cols)

# ── two-way links ────────────────────────────────────────────────────
# A one-way connect column keeps its links in custom_fields, unchanged. A
# two-way column keeps them in item_links instead: one row per relationship,
# read by both sides. Neither side holds a copy, so they cannot fall out of step.
def _ensure_mirrors(db, board_id, col):
    """Give a two-way column its counterpart on each target board.

    The reverse link has to be shown somewhere, so every target board gets a
    connect column pointing back. An existing one that already points here is
    reused rather than duplicated. The resulting map — target board → column —
    is stored on the column, and is what the configuration screen reads back to
    tell the admin where the reverse will appear.
    """
    cfg = _connect_cfg(col)
    if not cfg.get("two_way"):
        return {}
    src = db.query(Board).filter(Board.id == board_id).first()
    mirror = dict(cfg.get("mirror") or {})
    for bid in (cfg.get("board_ids") or []):
        tb = db.query(Board).filter(Board.id == bid).first()
        if not tb or tb.deleted_at:
            continue
        cols = list((tb.settings or {}).get("columns", []))
        want = mirror.get(str(bid))
        found = next((c for c in cols if c.get("id") == want and c.get("type") == "connect"), None)
        if not found:
            # reuse a connect column that already points back at this board and
            # column, rather than adding a second one that says the same thing
            found = next((c for c in cols
                          if c.get("type") == "connect"
                          and (_connect_cfg(c).get("mirror") or {}).get(str(board_id)) == col["id"]), None)
        if not found:
            found = {"id": "col_" + uuid.uuid4().hex[:8], "type": "connect",
                     "title": (src.name if src else "קישור"),
                     "options": None, "formula": None, "copy_mode": None, "perms": {},
                     "connect": {}}
            cols.append(found)
        found["connect"] = {"board_ids": [board_id],
                            "multiple": cfg.get("multiple", True),
                            "two_way": True,
                            "mirror": {str(board_id): col["id"]}}
        st_ = dict(tb.settings or {})
        st_["columns"] = cols
        tb.settings = st_
        mirror[str(bid)] = found["id"]
        bus.publish("board.changed", board_id=bid)
    return mirror


def _connect_cfg(col):
    return (col or {}).get("connect") or {}


def _is_two_way(col):
    return bool(col and col.get("type") == "connect" and _connect_cfg(col).get("two_way"))


def _board_columns(db, board_id):
    b = db.query(Board).filter(Board.id == board_id).first()
    return (b.settings or {}).get("columns", []) if b else []


def _find_col(db, board_id, col_id):
    return next((c for c in _board_columns(db, board_id) if c.get("id") == col_id), None)


def _link_pair(a_task, a_col, b_task, b_col):
    """Canonical order, so one relationship can only be stored one way."""
    if (a_task, a_col) <= (b_task, b_col):
        return a_task, a_col, b_task, b_col
    return b_task, b_col, a_task, a_col


def _linked_ids(db, task_id, col_id):
    """The items this cell links to, from whichever side the row was written.

    Ordered by the row id, which is the order the links were made. A two-way
    cell has nowhere to keep an order of its own — that is the cost of one
    shared row for both sides — so without this the same cell comes back in
    whatever order the database felt like, and the grid shows a different
    first name on different loads.
    """
    cache = db.info.get("_links_by")
    if cache is not None and (task_id, col_id) in cache:
        return list(cache[(task_id, col_id)])
    out = []
    for l in db.query(ItemLink).filter(
            or_((ItemLink.a_task_id == task_id) & (ItemLink.a_col == col_id),
                (ItemLink.b_task_id == task_id) & (ItemLink.b_col == col_id))
            ).order_by(ItemLink.id).all():
        out.append(l.b_task_id if (l.a_task_id == task_id and l.a_col == col_id) else l.a_task_id)
    return out


# Whether copying an item copies the links in its connect columns. A
# system-level switch, defaulting to on because a duplicate that silently loses
# its relationships is the more surprising of the two. Set
# CITYOS_DUPLICATE_ITEM_LINKS=0 where the business rule says a copy starts
# unlinked.
def _duplicate_links_enabled():
    return os.getenv("CITYOS_DUPLICATE_ITEM_LINKS", "1").strip().lower() not in ("0", "false", "no")


def _matching_connect_col(target_cols, col):
    """The column on the target board that can hold this column's links, if any.

    By id first — boards cloned from one another share column ids, and that is
    the only match that is certain. Otherwise by title, type and direction,
    which is what an admin who built "the same column" on both boards means.
    Anything looser would put links in a column that was never meant for them.
    """
    cid = col.get("id")
    hit = next((c for c in target_cols
                if c.get("type") == "connect" and c.get("id") == cid), None)
    if hit:
        return hit
    title = (col.get("title") or "").strip()
    if not title:
        return None
    return next((c for c in target_cols
                 if c.get("type") == "connect"
                 and (c.get("title") or "").strip() == title
                 and bool(_is_two_way(c)) == bool(_is_two_way(col))), None)


def _links_the_column_allows(db, col, ids):
    """Of these linked ids, the ones `col` is actually configured to hold.

    A connect column names the boards it links to, so a link whose far end is
    on some other board has nowhere to live in it. For a two-way column the
    reverse also needs a column on that board to appear in.
    """
    allowed = {int(b) for b in (_connect_cfg(col).get("board_ids") or [])
               if str(b).lstrip("-").isdigit()}
    if not allowed or not ids:
        return []
    rows = {t.id: t for t in db.query(Task).filter(Task.id.in_(list(ids)))
            .execution_options(include_deleted=True).all()}
    out = []
    for i in ids:
        t = rows.get(i)
        if t is None or t.board_id not in allowed:
            continue
        if _is_two_way(col) and not _mirror_col_for(db, col, t.board_id):
            continue
        out.append(i)
    return out


def _carry_links_across_boards(db, task, src_board_id, target_board_id, actor):
    """Move an item's connect values to the target board's own columns.

    A link is stored against a COLUMN, and column ids do not survive a move:
    the item lands on a board whose columns are different ones. Left alone the
    rows kept pointing at a column that does not exist where the item now
    lives — invisible from the target board, still showing on the far side of a
    two-way link, which is the same disagreement a deleted column used to
    cause.

    So each connect value is re-homed into the matching column on the target
    board, and only the links that column is configured to hold survive. What
    cannot be carried is dropped and written to the item's history, because a
    relationship disappearing during a move is not something to discover later.
    """
    src_cols = _board_columns(db, src_board_id)
    tgt_cols = _board_columns(db, target_board_id)
    cf = dict(task.custom_fields or {})
    touched = False
    for col in src_cols:
        if col.get("type") != "connect":
            continue
        cid = col["id"]
        two_way = _is_two_way(col)
        had = _linked_ids(db, task.id, cid) if two_way else \
              [i for i in (cf.get(cid) or []) if isinstance(i, int)]
        # the source column's cell has no meaning on the target board either way
        cf.pop(cid, None)
        if two_way:
            _drop_links_for_tasks_in_column(db, task.id, cid)
        if not had:
            continue
        tgt = _matching_connect_col(tgt_cols, col)
        keep = _links_the_column_allows(db, tgt, had) if tgt else []
        if keep:
            if _is_two_way(tgt):
                _set_links(db, task, tgt, keep, actor)
            else:
                cf[tgt["id"]] = keep if _is_multi(tgt) else keep[:1]
        if sorted(keep) != sorted(had):
            _audit(db, task.id, "update", "col:" + cid,
                   json.dumps(sorted(had)), json.dumps(sorted(keep)), actor)
        touched = True
    if touched or cf != (task.custom_fields or {}):
        task.custom_fields = cf


def _drop_links_for_tasks_in_column(db, task_id, col_id):
    """Just this item's links in just this column — used when it moves away."""
    db.query(ItemLink).filter(
        or_((ItemLink.a_task_id == task_id) & (ItemLink.a_col == col_id),
            (ItemLink.b_task_id == task_id) & (ItemLink.b_col == col_id))
    ).delete(synchronize_session=False)


# ── Mirror fields (שדה מראה) ────────────────────────────────────────────────
# A mirror column shows a field of the LINKED item in the current board. The
# value is never stored: it is read through the connect column every time the
# item is serialized, so it follows the source with nothing to keep in step and
# nothing to migrate.
#
# Not to be confused with connect.mirror, which is the counterpart column that
# shows the reverse of a two-way LINK. Same word, two features: this one
# mirrors a value, that one mirrors a relationship.
#
# Config lives on the column as
#     {"type": "mirror", "mirror_of": {"connect": <connect col id>, "field": <key>}}
# where `field` is a built-in below or a custom column id on the linked board.
_MIRROR_BUILTINS = {
    "title": "שם הפריט", "status": "סטטוס", "priority": "עדיפות",
    "due": "תאריך יעד", "assignees": "אחראים",
}


def _mirror_cfg(col):
    return (col or {}).get("mirror_of") or {}


def _mirror_one(db, t, field):
    """One linked item's contribution to a mirror cell, as display entries.

    Entries carry text and, where the source has one, a colour — enough for the
    grid to render a status as a status without the reader having to know what
    kind of column it came from.
    """
    def e(text, color=None):
        return [] if text in (None, "") else [{"item_id": t.id, "text": str(text), "color": color}]

    if field == "title":
        return e(t.title)
    if field == "due":
        return e(t.due_date.isoformat() if t.due_date else None)
    if field == "assignees":
        return [{"item_id": t.id, "text": u.name, "color": None} for u in (t.assignees or [])]
    _bb = db.info.get("_board_by")
    board = (_bb.get(t.board_id) if _bb is not None and t.board_id in _bb
             else db.query(Board).filter(Board.id == t.board_id).execution_options(
                 include_deleted=True).first())
    if field == "status":
        if (t.custom_fields or {}).get("status_unset"):
            return e("טרם הוגדר", "#c4c4c4")
        key = _task_status_key(t)
        entry = next((x for x in _board_statuses(board) if x["key"] == str(key)), None) if board else None
        return e(entry["label"] if entry else key, (entry or {}).get("color"))
    if field == "priority":
        if (t.custom_fields or {}).get("priority_unset"):
            return e("טרם הוגדר", "#c4c4c4")
        key = _task_priority_key(t)
        entry = next((x for x in _board_priorities(board) if x["key"] == str(key)), None) if board else None
        return e(entry["label"] if entry else key, (entry or {}).get("color"))

    # a custom column on the linked item's own board
    col = _find_col(db, t.board_id, field) if board else None
    v = (t.custom_fields or {}).get(field)
    if col is None or v in (None, "", [], {}):
        return []
    ctype = col.get("type")
    if ctype == "status":
        return e(v.get("label") if isinstance(v, dict) else v,
                 v.get("color") if isinstance(v, dict) else None)
    if ctype == "people":
        names = {u.id: u.name for u in db.query(User).filter(
            User.id.in_([i for i in v if isinstance(i, int)])).all()} if isinstance(v, list) else {}
        return [{"item_id": t.id, "text": names[i], "color": None} for i in (v or []) if i in names]
    if ctype == "timeline" and isinstance(v, dict):
        a, b = v.get("from") or v.get("start"), v.get("to") or v.get("end")
        return e(f"{a} – {b}" if a and b else (a or b))
    if ctype == "checkbox":
        return e("כן" if v else "לא")
    if ctype == "files":
        return e(f"{len(v)} קבצים" if isinstance(v, list) else None)
    if ctype == "connect":
        return []          # a mirror of a link is its own feature, not this one
    if isinstance(v, list):
        return [{"item_id": t.id, "text": str(x), "color": None} for x in v if x not in (None, "")]
    if isinstance(v, dict):
        return e(v.get("label") or v.get("text"))
    return e(v)


def _mirror_cells(db, task, col, viewer, board_cols):
    """A mirror column's value for this item — computed, never stored.

    Only linked items the viewer may see contribute. A mirror must not become a
    way to read a field of an item they were refused: the connect column
    already withholds those ids, and this reads through the same filter.
    """
    cfg = _mirror_cfg(col)
    src_id, field = cfg.get("connect"), cfg.get("field")
    if not src_id or not field:
        return []
    src = next((c for c in board_cols
                if c.get("id") == src_id and c.get("type") == "connect"), None)
    if src is None:
        return []          # the connect column it was built on is gone
    ids = (_linked_ids(db, task.id, src_id) if _is_two_way(src)
           else [i for i in ((task.custom_fields or {}).get(src_id) or []) if isinstance(i, int)])
    ids = _visible_link_ids(db, ids, viewer)
    if not ids:
        return []
    _tb = db.info.get("_task_by") or {}
    rows = {i: _tb[i] for i in ids if i in _tb}
    _miss = [i for i in ids if i not in rows]
    if _miss:                                  # a path that never prefetched
        rows.update({t.id: t for t in db.query(Task).filter(Task.id.in_(_miss))
                     .execution_options(include_deleted=True).all()})
    out = []
    for i in ids:
        t = rows.get(i)
        if t is not None:
            out.extend(_mirror_one(db, t, field))
    return out


def _drop_links_for_tasks(db, task_ids):
    """Delete every link row touching these items.

    A link row is not owned by either side — that is the whole point of storing
    one row instead of two — so nothing cascades it away when an item is
    destroyed. Left behind, it is a row describing a relationship to something
    that no longer exists, and if that id is ever reused the dead link comes
    back attached to an unrelated item.
    """
    ids = [int(i) for i in (task_ids or [])]
    if not ids:
        return
    db.query(ItemLink).filter(
        or_(ItemLink.a_task_id.in_(ids), ItemLink.b_task_id.in_(ids))
    ).delete(synchronize_session=False)


def _drop_links_for_columns(db, col_ids):
    """Delete every link row held in these columns.

    Removing a connect column removes the place the relationship was expressed.
    Leaving the rows would keep the link alive on the OTHER board — the mirror
    cell reads by (task, column) and would still find it — so the two sides
    would disagree about whether a relationship exists at all.
    """
    ids = [str(c) for c in (col_ids or []) if c]
    if not ids:
        return
    db.query(ItemLink).filter(
        or_(ItemLink.a_col.in_(ids), ItemLink.b_col.in_(ids))
    ).delete(synchronize_session=False)


def _prefetch_links(db, tasks, columns, viewer):
    """Load a whole board's links in one pass instead of two queries per item.

    Serializing an item asked for its links, and then asked whether the viewer
    may see each of them — two round trips each, so a board of sixty items paid
    a hundred and twenty queries for a table that shows a handful of names. Both
    answers are batched here: every relationship row for these items in one
    query, and every far item's visibility warmed in one more.

    Only a read path builds this. _set_links drops it, because a cache of
    relationships is exactly the wrong thing to keep across a write.
    """
    cols = [c for c in (columns or []) if c.get("type") == "connect"]
    if not cols or not tasks:
        return
    ids = {t.id for t in tasks}
    two_way = {c["id"] for c in cols if _is_two_way(c)}
    cache = db.info.setdefault("_links_by", {})
    far = set()
    if two_way:
        for tid in ids:                    # seed, so "no links" is an answer too
            for cid in two_way:
                cache.setdefault((tid, cid), [])
        for l in (db.query(ItemLink)
                  .filter(or_(ItemLink.a_task_id.in_(ids), ItemLink.b_task_id.in_(ids)))
                  .order_by(ItemLink.id).all()):
            if l.a_task_id in ids and l.a_col in two_way:
                cache[(l.a_task_id, l.a_col)].append(l.b_task_id)
                far.add(l.b_task_id)
            if l.b_task_id in ids and l.b_col in two_way:
                cache[(l.b_task_id, l.b_col)].append(l.a_task_id)
                far.add(l.a_task_id)
    for t in tasks:                        # one-way cells hold their ids inline
        for c in cols:
            if c["id"] in two_way:
                continue
            far.update(i for i in ((t.custom_fields or {}).get(c["id"]) or [])
                       if isinstance(i, int))
    if far:
        _link_states(db, sorted(far), viewer)      # warms the per-request cache
        # A mirror column reads the linked items themselves — their title, who
        # is on them, their status — and it did that one query per item per
        # column, plus a query for the far item's board inside _mirror_one, plus
        # a lazy load of its assignees. A board of five hundred items with one
        # mirror column therefore paid about fifteen hundred queries, which no
        # amount of work on the item rows themselves would have shown up in.
        # All of it is loaded here instead, in three queries for the board.
        tb = db.info.setdefault("_task_by", {})
        need = [i for i in sorted(far) if i not in tb]
        for part in [need[i:i + _PREFETCH_CHUNK] for i in range(0, len(need), _PREFETCH_CHUNK)]:
            for ft in (db.query(Task).options(selectinload(Task.assignees))
                         .filter(Task.id.in_(part))
                         .execution_options(include_deleted=True).all()):
                tb[ft.id] = ft
        bb = db.info.setdefault("_board_by", {})
        bneed = sorted({t.board_id for t in tb.values()
                        if t.board_id is not None and t.board_id not in bb})
        if bneed:
            for fb in (db.query(Board).filter(Board.id.in_(bneed))
                         .execution_options(include_deleted=True).all()):
                bb[fb.id] = fb


def _mirror_col_for(db, col, target_board_id):
    """Which column on the target board shows the other end of this link."""
    return (_connect_cfg(col).get("mirror") or {}).get(str(target_board_id))


def _set_links(db, task, col, wanted_ids, actor_id, report=None):
    """Make this cell hold exactly `wanted_ids`, updating one shared row per pair.

    Adding from either side creates the single row; removing from either side
    deletes it, which is what makes a removal show on both boards.
    """
    col_id = col["id"]
    db.info.pop("_links_by", None)        # a write invalidates the read cache
    current_list = _linked_ids(db, task.id, col_id)
    current = set(current_list)
    # links the actor may add are only ones they may see, and links they cannot
    # see survive a save that never showed them — see _merge_link_ids
    # a list, not a set: rows are created in the order they were chosen, and
    # _linked_ids reads them back that way
    wanted_list = _merge_link_ids(db, wanted_ids, current_list, actor_id,
                                  _is_multi(col), report)
    wanted = set(wanted_list)

    for tid in [i for i in wanted_list if i not in current]:
        other = db.query(Task).filter(Task.id == tid).first()
        if not other:
            continue
        mirror = _mirror_col_for(db, col, other.board_id)
        if not mirror:
            # nowhere on that board for the reverse to appear, so there is no
            # relationship to store — said out loud rather than dropped
            if report is not None:
                report.append({"item_id": tid, "reason": "no_mirror"})
            continue
        a_t, a_c, b_t, b_c = _link_pair(task.id, col_id, other.id, mirror)
        exists = db.query(ItemLink).filter(
            ItemLink.a_task_id == a_t, ItemLink.a_col == a_c,
            ItemLink.b_task_id == b_t, ItemLink.b_col == b_c).first()
        if not exists:
            db.add(ItemLink(a_task_id=a_t, a_col=a_c, b_task_id=b_t, b_col=b_c,
                            created_by=actor_id))

    for tid in current - wanted:
        db.query(ItemLink).filter(
            or_((ItemLink.a_task_id == task.id) & (ItemLink.a_col == col_id) & (ItemLink.b_task_id == tid),
                (ItemLink.b_task_id == task.id) & (ItemLink.b_col == col_id) & (ItemLink.a_task_id == tid))
        ).delete(synchronize_session=False)


# ── Cross-board item linking (connect column) ───────────────────────
@app.get("/api/items/search")
def items_search(board_ids: str = "", q: str = "", exclude_task: Optional[int] = None,
                 status: str = "", assignee: Optional[int] = None,
                 offset: int = 0, limit: int = 40,
                 actor_id: int = Depends(current_user_id)):
    """Items available to link, for the connect-column picker.

    Returns a PAGE, not the whole board: a picker on a board with thousands of
    items must not have to load all of them before showing the first one. The
    caller asks for the next slice as it scrolls.

    This endpoint took no actor and checked nothing, so it would search — and
    return the titles of — items on boards the caller cannot open. It is now
    restricted to the boards they can already see.
    """
    ids = [int(x) for x in board_ids.split(",") if x.strip().isdigit()]
    if not ids:
        # The picker always names the column's target boards. A blank list used
        # to mean "search everything you can see", which turned a column
        # configured for one board into a workspace-wide search as soon as the
        # caller dropped the parameter.
        return {"items": [], "total": 0, "has_more": False}
    with Session(engine) as db:
        visible = _visible_board_ids(db, actor_id)
        ids = [i for i in ids if i in visible]
        if not ids:
            return {"items": [], "total": 0, "has_more": False}
        query = db.query(Task).filter(Task.is_archived == False, Task.parent_id == None,  # noqa: E712
                                      Task.board_id.in_(ids))
        # Board access is not item access: an item on a board you belong to can
        # still be closed to you individually. Excluded in the query rather than
        # from the page, so `total` and the paging stay honest.
        denied = [r[0] for r in db.query(Task.id).filter(
            Task.board_id.in_(ids),
            Task.permissions[str(actor_id)].as_string() == "none").all()]
        if denied:
            query = query.filter(~Task.id.in_(denied))
        if q.strip():
            query = query.filter(Task.title.ilike(f"%{q.strip()}%"))
        if exclude_task:
            query = query.filter(Task.id != exclude_task)
        if status.strip():
            query = query.filter(Task.status == status.strip())
        if assignee:
            query = query.filter(Task.assignees.any(User.id == assignee))
        total = query.count()
        off = max(0, offset)
        lim = max(1, min(100, limit))
        rows = query.order_by(Task.board_id, Task.position, Task.id).offset(off).limit(lim).all()
        bnames = {b.id: b.name for b in db.query(Board).filter(Board.id.in_(ids)).all()}
        return {"items": [{"id": t.id, "title": t.title, "board_id": t.board_id,
                           "board_name": bnames.get(t.board_id, ""),
                           "status": t.status.value if hasattr(t.status, "value") else t.status,
                           "assignees": [{"id": u.id, "name": u.name, "avatar_url": u.avatar_url}
                                         for u in (t.assignees or [])]}
                          for t in rows],
                "total": total, "has_more": off + len(rows) < total}

def _item_link_map(db, task, cols, viewer):
    """Every connect column on this item → the linked ids the viewer may see."""
    out = {}
    for c in cols:
        if c.get("type") != "connect":
            continue
        ids = (_linked_ids(db, task.id, c["id"]) if _is_two_way(c)
               else [i for i in ((task.custom_fields or {}).get(c["id"]) or [])
                     if isinstance(i, int)])
        ids = _visible_link_ids(db, ids, viewer)
        if ids:
            out[c["id"]] = ids
    return out


@app.get("/api/boards/{board_id}/links/report")
def board_links_report(board_id: int, actor_id: int = Depends(current_user_id)):
    """A cross-board report built from the links, not from copied data.

    Three questions a board's links can answer that no single board can:
    where the work reaches (which other boards, and how heavily), what state the
    far side is in (the breakdown by status of everything this board points at),
    and which items on this board are not connected to anything at all.

    Everything is filtered per reader by the same rule the cells use, so the
    report can never total up items the reader is not allowed to see — a count
    is information too.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        cols = [c for c in _board_columns(db, board_id) if c.get("type") == "connect"]
        tasks = db.query(Task).filter(Task.board_id == board_id,
                                      Task.parent_id == None,      # noqa: E711
                                      Task.is_archived == False).order_by(  # noqa: E712
                                          Task.position, Task.id).all()
        rows, every = [], set()
        for t in tasks:
            m = _item_link_map(db, t, cols, actor_id)
            ids = [i for v in m.values() for i in v]
            every.update(ids)
            rows.append({"task_id": t.id, "title": t.title, "by_column": m,
                         "link_count": len(ids)})
        far = {t.id: t for t in db.query(Task).filter(Task.id.in_(every))
               .execution_options(include_deleted=True).all()} if every else {}
        boards = {x.id: x for x in db.query(Board).filter(
            Board.id.in_({t.board_id for t in far.values()}))
            .execution_options(include_deleted=True).all()} if far else {}

        per_board, per_status, per_column = {}, {}, {}
        for r in rows:
            for cid, ids in r["by_column"].items():
                per_column[cid] = per_column.get(cid, 0) + len(ids)
                for i in ids:
                    t2 = far.get(i)
                    if t2 is None:
                        continue
                    tb = boards.get(t2.board_id)
                    e = per_board.setdefault(t2.board_id, {
                        "board_id": t2.board_id, "board_name": tb.name if tb else "",
                        "links": 0, "items": set()})
                    e["links"] += 1
                    e["items"].add(t2.id)
                    # the far side's state, in ITS board's vocabulary
                    if (t2.custom_fields or {}).get("status_unset"):
                        label, color = "טרם הוגדר", "#c4c4c4"
                    else:
                        key = _task_status_key(t2)
                        ent = next((x for x in _board_statuses(tb) if x["key"] == str(key)),
                                   None) if tb else None
                        label = ent["label"] if ent else str(key)
                        color = (ent or {}).get("color") or "#c4c4c4"
                    sb = per_status.setdefault(label, {"label": label, "color": color,
                                                       "items": set()})
                    sb["items"].add(t2.id)

        col_titles = {c["id"]: c.get("title") or c["id"] for c in cols}
        return {
            "board_id": board_id, "board_name": b.name,
            "connect_columns": [{"id": c["id"], "title": col_titles[c["id"]],
                                 "two_way": _is_two_way(c),
                                 "links": per_column.get(c["id"], 0)} for c in cols],
            # where the work reaches
            "by_board": sorted(({**v, "items": len(v["items"])} for v in per_board.values()),
                               key=lambda x: -x["links"]),
            # what state the far side is in
            "by_status": sorted(({"label": v["label"], "color": v["color"],
                                  "items": len(v["items"])} for v in per_status.values()),
                                key=lambda x: -x["items"]),
            "items": rows,
            "totals": {"items": len(rows),
                       "linked_items": sum(1 for r in rows if r["link_count"]),
                       "unlinked_items": sum(1 for r in rows if not r["link_count"]),
                       "links": sum(r["link_count"] for r in rows),
                       "far_items": len(every)},
        }


@app.get("/api/tasks/{task_id}/related")
def task_related(task_id: int, actor_id: int = Depends(current_user_id)):
    """Everything linked to one item, across every column and board.

    Both directions: what this item points at, and — for a two-way column —
    what points back at it. Which is the difference between "related" and
    "dependent" as far as the data can tell them apart.
    """
    with Session(engine) as db:
        task = _require_task_view(db, task_id, actor_id)
        cols = _board_columns(db, task.board_id)
        titles = {c.get("id"): c.get("title") or c.get("id") for c in cols}
        groups = []
        for cid, ids in _item_link_map(db, task, cols, actor_id).items():
            far = {t.id: t for t in db.query(Task).filter(Task.id.in_(ids))
                   .execution_options(include_deleted=True).all()}
            bnames = {x.id: x.name for x in db.query(Board).filter(
                Board.id.in_({t.board_id for t in far.values()}))
                .execution_options(include_deleted=True).all()}
            state = _link_states(db, ids, actor_id)
            groups.append({
                "column_id": cid, "column_title": titles.get(cid, cid),
                "items": [{"id": i, "title": far[i].title, "board_id": far[i].board_id,
                           "board_name": bnames.get(far[i].board_id, ""),
                           "status": _task_status_key(far[i]),
                           "deleted": state.get(i) in ("deleted", "deleted_board")}
                          for i in ids if i in far],
            })
        return {"task_id": task_id, "title": task.title, "groups": groups,
                "total": sum(len(g["items"]) for g in groups)}


@app.get("/api/boards/{board_id}/mirror-sources")
def mirror_sources(board_id: int, connect: str = "", actor_id: int = Depends(current_user_id)):
    """Which fields a mirror column on this board could show, per connect column.

    Built from the boards the connect column actually points at, so the admin
    picks from what exists rather than typing a field name and finding out later
    that nothing resolves. Fields common to several target boards are offered
    once; a custom column that exists on only one of them is labelled with the
    board it comes from, because picking it means the mirror is empty for links
    into the others.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        cols = _board_columns(db, board_id)
        conns = [c for c in cols if c.get("type") == "connect"
                 and (not connect or c.get("id") == connect)]
        out = []
        for c in conns:
            targets = [int(x) for x in (_connect_cfg(c).get("board_ids") or [])
                       if str(x).lstrip("-").isdigit()]
            visible = _visible_board_ids(db, actor_id)
            targets = [t for t in targets if t in visible]
            fields = [{"key": k, "label": v, "builtin": True} for k, v in _MIRROR_BUILTINS.items()]
            seen = {}
            for tb in targets:
                tboard = db.query(Board).filter(Board.id == tb).first()
                for tc in _board_columns(db, tb):
                    # a mirror of a link, or of another mirror, is its own
                    # feature — not offered here
                    if tc.get("type") in ("connect", "mirror") or not tc.get("id"):
                        continue
                    seen.setdefault(tc["id"], {"key": tc["id"], "label": tc.get("title") or tc["id"],
                                               "builtin": False, "type": tc.get("type"), "boards": []})
                    seen[tc["id"]]["boards"].append({"id": tb, "name": tboard.name if tboard else ""})
            fields += list(seen.values())
            out.append({"connect_id": c.get("id"), "connect_title": c.get("title") or "",
                        "target_boards": targets, "fields": fields})
        return {"sources": out}


@app.get("/api/boards/{board_id}/columns/{col_id}/impact")
def column_impact(board_id: int, col_id: str, actor_id: int = Depends(current_user_id)):
    """What deleting this column would destroy, so the confirmation can say so.

    Counted on the server rather than from the loaded board: the cell a client
    holds has already been filtered to what its viewer may see, so counting
    there would understate a destructive action for exactly the person about to
    take it.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if _board_role(db, board_id, actor_id) != "admin":
            raise HTTPException(403, "רק מנהל הלוח יכול לערוך עמודות")
        col = _find_col(db, board_id, col_id)
        if not col:
            raise HTTPException(404, "column not found")
        out = {"col_id": col_id, "title": col.get("title") or "", "type": col.get("type"),
               "two_way": _is_two_way(col), "links": 0, "items": 0, "mirrors": []}
        if col.get("type") != "connect":
            return out
        if _is_two_way(col):
            rows = db.query(ItemLink).filter(
                or_(ItemLink.a_col == col_id, ItemLink.b_col == col_id)).all()
            out["links"] = len(rows)
            out["items"] = len({l.a_task_id if l.a_col == col_id else l.b_task_id for l in rows})
        else:
            # a one-way column keeps its ids in the cell
            for t in db.query(Task).filter(Task.board_id == board_id).all():
                v = (t.custom_fields or {}).get(col_id)
                if isinstance(v, list) and v:
                    out["items"] += 1
                    out["links"] += len(v)
        # where the reverse of each relationship is shown today
        mirror = _connect_cfg(col).get("mirror") or {}
        for bid, mcol in mirror.items():
            tb = db.query(Board).filter(Board.id == int(bid)).first()
            if not tb or tb.deleted_at:
                continue
            mdef = _find_col(db, tb.id, mcol)
            out["mirrors"].append({"board_id": tb.id, "board_name": tb.name,
                                   "col_id": mcol, "col_title": (mdef or {}).get("title") or ""})
        return out


@app.get("/api/tasks/lookup")
def tasks_lookup(ids: str = "", actor_id: int = Depends(current_user_id)):
    """Resolve item ids → title/board, to display linked items in a connect cell.

    This took no actor and filtered nothing: any id turned into a title and the
    name of the board it lives on, which is the whole point of the restriction
    the picker enforces. A cell now only ever carries ids its viewer may see, so
    in normal use nothing here is refused — but the endpoint is what makes that
    true rather than merely tidy.
    """
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        return {"items": []}
    with Session(engine) as db:
        state = _link_states(db, id_list, actor_id)
        allowed = [i for i in id_list if state.get(i)]
        rows = (db.query(Task).filter(Task.id.in_(allowed))
                .execution_options(include_deleted=True).all()) if allowed else []
        bnames = {b.id: b.name for b in db.query(Board)
                  .filter(Board.id.in_({t.board_id for t in rows}))
                  .execution_options(include_deleted=True).all()}
        # A binned item keeps its title and board — the caller was already
        # allowed to see both — and is flagged so the cell can say that the
        # item was deleted rather than pretend the link was never there.
        out = [{"id": t.id, "title": t.title, "board_id": t.board_id,
                "board_name": bnames.get(t.board_id, ""),
                "deleted": state.get(t.id) in ("deleted", "deleted_board"),
                # which bin it is in decides what the reader has to do about it
                "deleted_scope": ("board" if state.get(t.id) == "deleted_board"
                                  else "item" if state.get(t.id) == "deleted" else None)}
               for t in rows]
        # Named, not silently dropped: the client needs to tell "no such item"
        # apart from "not yours", and it may render neither a title nor a board.
        out += [{"id": i, "title": None, "board_id": None, "board_name": "",
                 "restricted": True} for i in id_list if not state.get(i)]
        return {"items": out}

# Groups and statuses are not wired to each other. A board that wants an item
# filed by its status says so with an automation — status_changes_to →
# move_to_group — which is listed with every other rule on the board and can be
# switched off. What used to be here was the same rule with no name, no listing
# and no way to turn it off; it also had to guess which group a status meant on
# a board with two of them.


def _st_of(t):
    return t.status.value if hasattr(t.status, "value") else t.status


# ── Automations engine (אוטומציות) ──────────────────────────────────
# A board admin builds if-then rules from the recipe catalog in automations.py.
# Rules fire inline, inside the same transaction as the change that triggered
# them, so an item never lands in a half-automated state.
import automations as recipes   # noqa: E402  (pure data — no app imports)

# An action can itself be a trigger (set status → a status rule). That is
# deliberate and useful, but two rules can point at each other, so cascades are
# bounded rather than trusted.
AUTOMATION_MAX_DEPTH = 3

# How many rows the run history keeps per board. Old rows fall off the front so
# a busy board's log cannot grow without limit.
AUTOMATION_RUN_LOG_MAX = 500


# The five states a rule can be in. Only "active" runs — see _set_automation_status.
AUTOMATION_STATUSES = ("draft", "active", "paused", "paused_error", "deleting")
AUTOMATION_IMPORTANCE = ("critical", "high", "normal", "low")
# Failures in a row that take a rule out of service. A rule that cannot work is
# worse than no rule: it looks configured while quietly doing nothing, so it is
# suspended and its owner is told, rather than failing forever in the log.
AUTOMATION_FAIL_CUTOFF = 5


def _set_automation_status(a, status):
    """Move a rule between states, keeping the engine's switch in step.

    `status` is what a person manages; `is_active` is what the engine reads. Two
    fields that mean almost the same thing drift apart unless exactly one place
    writes both, and this is that place.
    """
    was = a.status
    a.status = status if status in AUTOMATION_STATUSES else "active"
    a.is_active = (a.status == "active")
    if a.status == "active":
        a.consecutive_failures = 0          # reactivating clears the strike count
        if was != "active":
            # an activation applies to events from here forward; it is not a
            # licence to act on what happened while the rule was off
            a.activated_at = datetime.now(timezone.utc).replace(tzinfo=None)


def _refuse_incomplete_activation(db, board, a):
    """A draft may be half-built. Switching it on may not be.

    Everything the rule needs is re-derived here: the placeholders it has not
    filled, and then the dependencies and permissions the engine checks before
    every run — so "active" cannot mean "will skip every time it fires".
    """
    missing = recipes.missing_fields(a.recipe_id, a.config or {})
    if missing:
        raise HTTPException(400, "לא ניתן להפעיל — חסרים שדות חובה: " + ", ".join(missing))
    blockers = _automation_blockers(db, board, a)
    if blockers:
        raise HTTPException(400, "לא ניתן להפעיל — " + " · ".join(b["text"] for b in blockers[:3]))


# ── rule 3: the engine's own identity and its grant ─────────────────
# The engine does not borrow the rights of whoever tripped a rule, nor of the
# person who wrote it. It acts as itself — a dedicated account — inside a grant
# that names the action types automation may perform at all. A stored rule that
# asks for anything else is refused at run time, which is what makes the grant
# a boundary rather than a comment.
AUTOMATION_IDENTITY_EMAIL = "automation@system.local"
AUTOMATION_IDENTITY_NAME = "מנוע האוטומציות"

# The action types approved for automation. Everything the recipe catalog can
# ask for today, listed here on purpose: a recipe added later, or a row edited
# by hand, cannot widen what the engine is allowed to do without this list
# being changed too.
AUTOMATION_GRANTED_ACTIONS = frozenset({
    "notify_person", "notify_assignees", "assign_person", "set_status",
    "set_priority", "move_to_group", "create_subitem", "link_to_item",
    "create_and_link",
})
# The item fields automation may write. The recipes only ever touch these, and
# an action that reached past them would be doing something nobody approved.
AUTOMATION_GRANTED_FIELDS = frozenset({
    "status", "priority", "group_id", "assignees", "custom_fields", "subitem",
})
_AUTOMATION_UID = None


def _automation_identity(db):
    """The engine's account. Read, never created here.

    Created at startup instead, in a transaction of its own, because this is
    read inside a firing — and a firing can be rolled back. A dry run ends in a
    rollback by design, and an identity created inside one would vanish with it
    while this cache went on handing out its id: every later run would sign its
    work with a row that does not exist.
    """
    global _AUTOMATION_UID
    if _AUTOMATION_UID is not None:
        return _AUTOMATION_UID
    try:
        uid = (db.query(User.id)
                 .filter(User.email == AUTOMATION_IDENTITY_EMAIL).scalar())
        if uid:
            _AUTOMATION_UID = uid
        return uid
    except Exception as e:                         # noqa: BLE001
        print(f"⚠️  automation identity unavailable: {e}", flush=True)
        return None


def _ensure_automation_identity():
    """Make the engine's account if it is not there. Startup, once, committed."""
    with Session(engine) as db:
        u = db.query(User).filter(User.email == AUTOMATION_IDENTITY_EMAIL).first()
        if u is None:
            # not a usable account: inactive, and the narrowest role there is —
            # what the engine may do comes from its grant, never from this row
            u = User(name=AUTOMATION_IDENTITY_NAME, email=AUTOMATION_IDENTITY_EMAIL,
                     role="viewer", is_active=False)
            db.add(u)
            db.commit()
            print(f"⚙️  automation identity ready ({AUTOMATION_IDENTITY_EMAIL})", flush=True)


class _Skipped(Exception):
    """A rule matched but had nothing to do — a skip, not a failure.

    The recipient left the board, the item is already in that status, the link
    already exists. Each carries the Hebrew reason the history shows, because
    "why did nothing happen?" is the question the log exists to answer.
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


_safe_startup(_ensure_automation_identity)


def _sweep_stray_audit_on_boot():
    """Clear the history that was left behind by boards destroyed before the
    delete took it with them — see _sweep_stray_audit. Self-healing rather than
    a one-time migration: the rows it removes are provably not about the items
    they point at, and leaving them means an item showing a stranger's history.
    """
    with Session(engine) as db:
        orphans, wrong = _sweep_stray_audit(db)
    if orphans or wrong:
        print(f"↻ cleared {orphans} log row(s) of deleted items"
              + (f" and {wrong} that belonged to an item since replaced" if wrong else ""),
              flush=True)

_safe_startup(_sweep_stray_audit_on_boot)


def _task_status_key(task):
    """The vocabulary key an item's status actually shows as — a board-defined
    status rides in custom_fields with the enum kept as its base."""
    return (task.custom_fields or {}).get("status_key") or _st_of(task)


def _task_priority_key(task):
    pv = task.priority.value if hasattr(task.priority, "value") else task.priority
    return (task.custom_fields or {}).get("priority_key") or pv


def _logged_status(task):
    """What a log row should say an item's status IS.

    The vocabulary key the cell shows — deliberately not the TaskStatus enum.
    Several board statuses can share one enum value: the default vocabulary has
    "תקוע" and "הקפאה" both sitting on `on_hold`. A log written from the enum
    therefore says *nothing at all* when an item moves between them, and names
    the base rather than the status somebody actually picked whenever a
    board-defined one is chosen — which is how a change could land in the column
    and leave the log reading as though only the original status ever existed.

    "" means nobody has chosen, which both logs already render as "—".
    """
    if (task.custom_fields or {}).get("status_unset"):
        return ""
    return _task_status_key(task)


def _logged_priority(task):
    """The same for the priority column, which has the same machinery."""
    if (task.custom_fields or {}).get("priority_unset"):
        return ""
    return _task_priority_key(task)


def _restore_choice(db, task, field, value):
    """Put an item's status or priority back to `value` as the cell said it.

    Undo reads a log row, and a row now holds the vocabulary key — so it cannot
    go straight at the enum any more. Three things a row can hold: "" (nobody
    had chosen), a board vocabulary key, or a bare engine value, which is what
    rows written before the log recorded keys still carry.
    """
    unset_key = field + "_unset"
    neutral = TaskStatus.TODO if field == "status" else Priority.MEDIUM
    if value in (None, ""):
        cf = dict(task.custom_fields or {})
        for k in (field + "_key", field + "_label", field + "_color"):
            cf.pop(k, None)
        cf[unset_key] = True
        task.custom_fields = cf
        setattr(task, field, neutral)
        return True
    if (_apply_status_key if field == "status" else _apply_priority_key)(db, task, value):
        return True
    # Not in the board's vocabulary any more — a status the board has since
    # deleted. Fall back to the engine value so undo still does something.
    try:
        setattr(task, field, (TaskStatus if field == "status" else Priority)(str(value)))
    except ValueError:
        return False
    cf = dict(task.custom_fields or {})
    for k in (field + "_key", field + "_label", field + "_color", unset_key):
        cf.pop(k, None)
    task.custom_fields = cf
    return True


def _automation_matches(a, event):
    r = recipes.recipe(a.recipe_id)
    if not r or r["trigger"] != event.get("type"):
        return False
    cfg = a.config or {}
    if event["type"] == "status_changes_to":
        return str(cfg.get("t_status")) == str(event.get("status"))
    if event["type"] == "priority_changes_to":
        return str(cfg.get("t_priority")) == str(event.get("priority"))
    if event["type"] == "linked_status_changes_to":
        return str(cfg.get("t_status")) == str(event.get("status"))
    return True


def _apply_status_key(db, task, key):
    """Set an item's status from a board vocabulary key. Mirrors what the board
    UI writes, so an automated change is indistinguishable from a manual one."""
    board = db.query(Board).filter(Board.id == task.board_id).first()
    entry = next((e for e in _board_statuses(board) if e["key"] == str(key)), None) if board else None
    if not entry:
        return False
    try:
        nv = TaskStatus(entry["base"])
    except ValueError:
        return False
    task.status = nv
    cf = dict(task.custom_fields or {})
    if entry["key"] in _STATUS_KEYS:              # a built-in — clear any override
        for k in ("status_key", "status_label", "status_color", "status_unset"):
            cf.pop(k, None)
    else:
        cf.update({"status_key": entry["key"], "status_label": entry["label"],
                   "status_color": entry["color"]})
        cf.pop("status_unset", None)
    task.custom_fields = cf
    return True


def _apply_priority_key(db, task, key):
    board = db.query(Board).filter(Board.id == task.board_id).first()
    pval, pcf = _resolve_priority(board, key)
    if not pval:
        return False
    try:
        task.priority = Priority(pval)
    except ValueError:
        return False
    if pcf:
        cf = dict(task.custom_fields or {})
        cf.update({k: v for k, v in pcf.items() if v is not None})
        for k, v in pcf.items():
            if v is None:
                cf.pop(k, None)
        task.custom_fields = cf
    return True


def _filter_item(db, task):
    """One item in the shape filter_ast reads — the advanced filter's own shape,
    because an automation condition about a column asks the same question of the
    same cell and must answer it the same way."""
    return {"id": task.id, "title": task.title,
            "status": _task_status_key(task), "priority": _task_priority_key(task),
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "assignees": [{"id": u.id} for u in list(task.assignees or [])],
            "custom_fields": task.custom_fields or {}}


# Israel's day, not the server's. A column condition about a date resolves
# "היום" the way everybody reading this board means it: an item written at
# 22:30 UTC is already tomorrow's in Jerusalem, and a rule that fires on "רק אם
# תאריך האספקה הוא היום" must agree with the board that shows it. The frontend
# renders every date in Asia/Jerusalem for the same reason; this is the engine's
# side of that.
_IL_TZ = ZoneInfo("Asia/Jerusalem")


def _il_day():
    """(today as YYYY-MM-DD, the zone's offset in minutes)."""
    now = datetime.now(_IL_TZ)
    return now.strftime("%Y-%m-%d"), int((now.utcoffset() or timedelta()).total_seconds() // 60)


def _column_cond_holds(db, task, spec):
    """A condition about one of the board's columns. None when it cannot be
    answered at all — the column is gone, or is no longer a kind of column
    anything can be asked about.

    A multi-value cell (a dropdown, a people column) answers "is" as "is among
    them", which is the reading of the words: "רק אם סוג הפנייה הוא «תשתיות»"
    over a cell holding two types is true of that item.
    """
    col = _find_col(db, task.board_id, str(spec.get("col") or ""))
    if not col:
        return None
    kind = recipes.column_kind(col.get("type"))
    if not kind or kind != recipes.column_kind(spec.get("type")):
        # the column changed type under the rule: the question it was written to
        # ask no longer exists, and guessing a new one is not the engine's call
        return None
    want = spec.get("value")
    raw = (task.custom_fields or {}).get(str(spec.get("col")))
    today, off = _il_day()
    if kind == "check":
        got = bool(len(raw)) if isinstance(raw, list) else bool(raw)
        return got is bool(want)
    if kind == "people":
        have = raw if isinstance(raw, list) else ([] if raw in (None, "") else [raw])
        ids = set()
        for x in have:
            try:
                ids.add(int(x.get("id") if isinstance(x, dict) else x))
            except (TypeError, ValueError):
                pass
        return int(want) in ids
    if kind == "number":
        rule = {"type": "rule", "field": str(spec["col"]), "operator": "eq", "value": want}
        return filter_ast.match_rule(_filter_item(db, task), rule,
                                     {str(spec["col"]): "number"}, today, off, None)
    if kind == "date":
        rule = {"type": "rule", "field": str(spec["col"]), "operator": "on", "value": want}
        return filter_ast.match_rule(_filter_item(db, task), rule,
                                     {str(spec["col"]): "date"}, today, off, None)
    # text and status, and a dropdown's several options at once
    vals = raw if isinstance(raw, list) else [raw]
    shown = []
    for v in vals:
        if v in (None, ""):
            continue
        shown.append(str(v.get("label") if isinstance(v, dict) else v).strip().lower())
    return str(want).strip().lower() in shown


def _condition_value_label(db, board, kind, v):
    """A condition's value as the board shows it — a status's label, a name."""
    spec = recipes.condition(kind) or {}
    t = spec.get("type")
    if t == "column":
        # the value half alone: which column it is said about is in the label
        return _column_cond_shown(db, board, v, quote=False)["value"]
    if t == "status":
        e = next((x for x in _board_statuses(board) if x["key"] == str(v)), None)
        return e["label"] if e else str(v)
    if t == "priority":
        e = next((x for x in _board_priorities(board) if x["key"] == str(v)), None)
        return e["label"] if e else str(v)
    if t == "person":
        return db.query(User.name).filter(User.id == v).scalar() or str(v)
    if t == "group":
        return db.query(Group.name).filter(Group.id == v).scalar() or str(v)
    return str(v)


# The dynamic dates, in the words the filter offers them in — a condition
# reading "«2026-10-19»" where somebody chose "היום" would be a different
# sentence from the one they wrote, and would stop being true tomorrow.
_DATE_TOKEN_HE = {
    "today": "היום", "yesterday": "אתמול", "tomorrow": "מחר",
    "this_week": "השבוע", "next_week": "שבוע הבא", "last_week": "שבוע שעבר",
    "this_month": "החודש", "next_month": "חודש הבא", "last_month": "חודש שעבר",
    "last_7": "7 הימים האחרונים", "last_30": "30 הימים האחרונים",
}


def _column_cond_shown(db, board, spec, quote=True):
    """A column condition's two halves, rendered: which column, and what value.

    The column is named even when it is gone — "העמודה «תקציב»" over a deleted
    column is what tells somebody which rule to fix, where a column id tells
    them nothing."""
    spec = spec or {}
    col = _find_col(db, board.id, str(spec.get("col") or "")) if board else None
    title = (col or {}).get("title") or str(spec.get("col") or "—")
    kind = recipes.column_kind(spec.get("type"))
    v = spec.get("value")
    if kind == "check":
        shown = "מסומן" if v else "לא מסומן"
    elif kind == "people":
        shown = db.query(User.name).filter(User.id == v).scalar() or str(v)
    elif kind == "date":
        shown = _DATE_TOKEN_HE.get(str(v)) or _fmt_day(v)
    else:
        shown = str(v)
    wrap = (lambda x: f"«{x}»") if quote else (lambda x: x)
    return {"column": wrap(title), "value": wrap(shown)}


def _fmt_day(v):
    """A stored YYYY-MM-DD as the day Israel writes."""
    try:
        return datetime.strptime(str(v), "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(v)


def _condition_phrases(db, board, conds, quote=True):
    """Each extra condition as a readable phrase, values filled in."""
    out = []
    for c in conds or []:
        kind = c.get("kind")
        spec = recipes.condition(kind)
        if not spec:
            continue
        if spec["type"] is None:
            out.append(recipes.condition_text(kind))
        elif spec["type"] == "column":
            out.append(recipes.condition_text(
                kind, _column_cond_shown(db, board, c.get("value"), quote)))
        else:
            shown = _condition_value_label(db, board, kind, c.get("value"))
            out.append(recipes.condition_text(kind, f"«{shown}»" if quote else shown))
    return out


def _condition_holds(db, task, kind, v):
    """One condition, against the item as it is right now."""
    if kind in recipes.COLUMN_CONDITIONS:
        held = _column_cond_holds(db, task, v or {})
        # A column that is gone cannot answer, and the rule holds its fire: a
        # condition that cannot be evaluated must never be read as true, which
        # would widen the rule to everything the trigger catches. The advanced
        # filter takes such a rule OUT of its tree for the same reason — see
        # filter_ast.prune — and here the rule simply does not fire, with
        # _automation_blockers saying why.
        if held is None:
            return False
        return held if kind == "column_is" else not held
    if kind in ("status_is", "status_is_not"):
        same = str(_task_status_key(task)) == str(v)
        return same if kind == "status_is" else not same
    if kind in ("priority_is", "priority_is_not"):
        same = str(_task_priority_key(task)) == str(v)
        return same if kind == "priority_is" else not same
    if kind in ("person_is", "person_is_not"):
        try:
            on = int(v) in {u.id for u in list(task.assignees or [])}
        except (TypeError, ValueError):
            on = False
        return on if kind == "person_is" else not on
    if kind in ("group_is", "group_is_not"):
        try:
            same = task.group_id is not None and int(v) == int(task.group_id)
        except (TypeError, ValueError):
            same = False
        return same if kind == "group_is" else not same
    if kind in ("has_assignee", "no_assignee"):
        any_one = bool(list(task.assignees or []))
        return any_one if kind == "has_assignee" else not any_one
    if kind in ("has_due_date", "no_due_date"):
        has = task.due_date is not None
        return has if kind == "has_due_date" else not has
    if kind in ("overdue", "not_overdue"):
        # an item with no due date is not overdue — so "תאריך היעד לא עבר" holds
        # for it, which is the reading a person expects of the words
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        late = bool(task.due_date and task.due_date < now)
        return late if kind == "overdue" else not late
    # an unknown condition is not a licence to act: a rule whose condition this
    # version cannot evaluate holds its fire rather than firing unconditionally
    return False


def _conditions_hold(db, board, task, conds):
    """(ok, why_not). The first condition that does not hold decides, and it is
    named — "why did nothing happen" is answerable only if the answer is kept."""
    for c in conds or []:
        if not _condition_holds(db, task, c.get("kind"), c.get("value")):
            phrase = (_condition_phrases(db, board, [c]) or [""])[0]
            return False, f"התנאי אינו מתקיים על הפריט: {phrase}"
    return True, ""


def _shown_value(db, board, ftype, v):
    """One value as the board shows it — a status's label, a person's name.

    Pulled out of _automation_label because an extra action's value has to be
    rendered exactly as the recipe's own: the sentence must not say «3» for the
    second action and the person's name for the first."""
    if ftype == "status":
        e = next((x for x in _board_statuses(board) if x["key"] == str(v)), None)
        return e["label"] if e else str(v)
    if ftype == "priority":
        e = next((x for x in _board_priorities(board) if x["key"] == str(v)), None)
        return e["label"] if e else str(v)
    if ftype == "person":
        return db.query(User.name).filter(User.id == v).scalar() or "—"
    if ftype == "group":
        return db.query(Group.name).filter(Group.id == v).scalar() or "—"
    if ftype == "connect":
        col = _find_col(db, board.id, str(v)) if board else None
        return (col or {}).get("title") or "—"
    if ftype == "item":
        return db.query(Task.title).filter(Task.id == v).scalar() or "—"
    if ftype == "board":
        return db.query(Board.name).filter(Board.id == v).scalar() or "—"
    return str(v)


def _action_phrases(db, board, extras, quote=True):
    """A rule's EXTRA actions, each as a filled-in phrase, in run order.

    Takes the stored list rather than the rule, so a version snapshot — which
    is a config and not a row — can be read with the same renderer the live
    sentence uses."""
    out = []
    for extra in extras or []:
        key = str((extra or {}).get("key") or "")
        values = (extra or {}).get("values") or {}
        shown = {}
        for f in recipes.action_fields(key):
            v = values.get(f["key"])
            if v in (None, ""):
                continue
            text = _shown_value(db, board, f["type"], v)
            shown[f["key"]] = f"«{text}»" if quote else text
        phrase = recipes.action_text(key, shown)
        if phrase:
            out.append(phrase)
    return out


def _automation_label(db, board, a):
    """The rule as a readable Hebrew sentence with its values filled in — shown
    in the list and quoted in the notifications it sends."""
    cfg = a.config or {}
    text = recipes.sentence(a.recipe_id,
                            _condition_phrases(db, board, cfg.get(recipes.CONDITION_KEY)),
                            _action_phrases(db, board, cfg.get(recipes.ACTIONS_KEY)))
    r = recipes.recipe(a.recipe_id)
    for f in (r or {}).get("fields", []):
        shown = _shown_value(db, board, f["type"], cfg.get(f["key"]))
        text = text.replace("{" + f["key"] + "}", f"«{shown}»")
    return text


def _run_action(db, a, task, actor_id, board):
    """Perform the rule's actions, in order. Returns (follow-up events, note).

    The events let a rule trigger another, bounded by AUTOMATION_MAX_DEPTH.

    A rule may carry up to recipes.MAX_ACTIONS actions and they are one step,
    not four: they run inside the one transaction the engine already holds, so
    an action that raises takes the whole rule back with it. A rule that
    half-happened, with a history that cannot say which half, is the thing
    worth not having.

    _Skipped is per action. A rule counts as skipped only when NOTHING it was
    asked to do had anything to do; if one action worked the rule ran, and the
    dead ends travel back as the note the history shows beside it — "why did
    nothing happen?" is still the question the log exists to answer, and with
    four actions "why did only some of it happen?" is the same question.
    """
    out, skipped = [], []
    label = _automation_label(db, board, a)
    acts = recipes.action_list(a.recipe_id, a.config or {})
    for one in acts:
        try:
            out.extend(_run_one_action(db, one["key"], one["values"],
                                       task, actor_id, board, label) or [])
        except _Skipped as sk:
            skipped.append(sk.reason)
    if acts and len(skipped) == len(acts):
        raise _Skipped(" · ".join(dict.fromkeys(skipped)))
    note = ""
    if skipped:
        done = len(acts) - len(skipped)
        note = (f"{done} מתוך {len(acts)} פעולות בוצעו · "
                + " · ".join(dict.fromkeys(skipped)))
    return out, note


def _run_one_action(db, act, cfg, task, actor_id, board, label):
    """One action of a rule. Raises _Skipped where there is nothing to do.

    `cfg` is the action's own values, keyed by the bare field name — see
    automations.action_list, which reads the recipe's `a_*` placeholders and an
    extra action's stored values into that one shape.
    """
    out = []
    body = f"אוטומציה בלוח '{board.name}': {label} — פריט '{task.title}'."

    # An automation is a stored rule: the person it names may have been chosen
    # while they were a member and removed from the board since. Re-check at run
    # time, or a rule becomes a standing way to reach someone who was taken off
    # the board on purpose.
    if act == "notify_person":
        if not _can_be_assigned(db, task.board_id, cfg.get("person")):
            raise _Skipped("נמען ההתראה מושבת"
                           if _account_blocked(db, cfg.get("person"))
                           else "נמען ההתראה אינו חבר בלוח")
        _notify(db, cfg.get("person"), "automation", "אוטומציה הופעלה", body,
                board_id=task.board_id, task_id=task.id)
    elif act == "notify_assignees":
        people = list(task.assignees)
        if not people:
            raise _Skipped("לפריט אין משויכים")
        for u in people:
            _notify(db, u.id, "automation", "אוטומציה הופעלה", body,
                    board_id=task.board_id, task_id=task.id)
    elif act == "assign_person":
        u = db.query(User).filter(User.id == cfg.get("person")).first()
        if not u or not _can_be_assigned(db, task.board_id, u.id):
            raise _Skipped("האדם שהכלל משייך מושבת" if u is not None and u.is_active is False
                           else "האדם שהכלל משייך אינו חבר בלוח")
        if u in task.assignees:
            raise _Skipped("האדם משויך לפריט כבר")
        task.assignees.append(u)
        _notify(db, u.id, "assign", "שויכת למשימה", body,
                board_id=task.board_id, task_id=task.id)
        out.append({"type": "person_assigned", "user_id": u.id})
    elif act == "set_status":
        if _task_status_key(task) == str(cfg.get("status")):
            raise _Skipped("הפריט נמצא בסטטוס הזה כבר")
        _was = _logged_status(task)
        if not _apply_status_key(db, task, cfg.get("status")):
            raise _Skipped("הסטטוס שהכלל מבקש אינו קיים בלוח")
        # In the log like anybody's change, with no user behind it — which both
        # logs already render as "מערכת". Attributing it to whoever's edit
        # tripped the rule would be a lie about who decided.
        _audit(db, task.id, "update", "status", _was, _logged_status(task), None)
        out.append({"type": "status_changes_to", "status": str(cfg.get("status"))})
    elif act == "set_priority":
        if _task_priority_key(task) == str(cfg.get("priority")):
            raise _Skipped("לפריט יש את העדיפות הזו כבר")
        _was = _logged_priority(task)
        if not _apply_priority_key(db, task, cfg.get("priority")):
            raise _Skipped("העדיפות שהכלל מבקש אינה קיימת בלוח")
        _audit(db, task.id, "update", "priority", _was, _logged_priority(task), None)
        out.append({"type": "priority_changes_to", "priority": str(cfg.get("priority"))})
    elif act == "move_to_group":
        g = db.query(Group).filter(Group.id == cfg.get("group"),
                                   Group.board_id == task.board_id).first()
        if not g:
            raise _Skipped("הקבוצה שהכלל מבקש אינה קיימת בלוח")
        if task.group_id == g.id:
            raise _Skipped("הפריט נמצא בקבוצה הזו כבר")
        task.group_id = g.id
    elif act == "create_subitem":
        db.add(Task(board_id=task.board_id, group_id=task.group_id, parent_id=task.id,
                    title=cfg.get("text") or "תת־פריט", status=TaskStatus.TODO,
                    priority=Priority.MEDIUM, created_by=actor_id))
    elif act == "link_to_item":
        col = _find_col(db, task.board_id, cfg.get("connect"))
        if not col or col.get("type") != "connect":
            raise _Skipped("עמודת הקישור אינה קיימת בלוח")
        other = db.query(Task).filter(Task.id == cfg.get("item")).first()
        if other is None:
            raise _Skipped("הפריט שהכלל מקשר אליו אינו קיים")
        if not _apply_automation_link(db, task, col, [other.id], actor_id):
            raise _Skipped("הקישור קיים כבר")
        out.append({"type": "link_added", "col": col["id"], "item_ids": [other.id]})
    elif act == "create_and_link":
        col = _find_col(db, task.board_id, cfg.get("connect"))
        if not col or col.get("type") != "connect":
            raise _Skipped("עמודת הקישור אינה קיימת בלוח")
        made = _create_linked_item(db, task, col, cfg.get("board"),
                                   cfg.get("text"), actor_id)
        if made is None:
            raise _Skipped("לוח היעד אינו אחד הלוחות שעמודת הקישור מפנה אליהם")
        out.append({"type": "link_added", "col": col["id"], "item_ids": [made.id]})
    return out


def _apply_automation_link(db, task, col, ids, actor_id):
    """Add links to a cell on behalf of a RULE. True if anything was added.

    Deliberately unscoped by viewer. A rule is board configuration written by an
    admin, not an action by whoever happened to trip it: filtering by what the
    triggering user may see would make the same rule work or not depending on
    who saved an item. What the column is structurally configured to hold still
    applies, and the person who tripped it still cannot SEE the link — the
    serializer filters per reader, as it does everywhere else.
    """
    if col.get("type") != "connect":
        return False
    ids = _links_the_column_allows(db, col, [i for i in ids if isinstance(i, int)])
    if not ids:
        return False
    if _is_two_way(col):
        current = _linked_ids(db, task.id, col["id"])
    else:
        current = [i for i in ((task.custom_fields or {}).get(col["id"]) or [])
                   if isinstance(i, int)]
    fresh = [i for i in ids if i not in current]
    if not fresh:
        return False
    wanted = current + fresh
    if not _is_multi(col):
        wanted = wanted[-1:]
    if _is_two_way(col):
        _set_links(db, task, col, wanted, None)     # None = system authority, see above
    else:
        cf = dict(task.custom_fields or {})
        cf[col["id"]] = _merge_link_ids(db, wanted, current, None, _is_multi(col))
        task.custom_fields = cf
    return True


def _create_linked_item(db, task, col, board_id, title, actor_id):
    """Make an item on the connect column's target board and link it back.

    The board has to be one the column actually points at — otherwise the new
    item would be created somewhere the link cannot reach, leaving an orphan on
    a board nobody asked to write to.
    """
    allowed = {int(b) for b in (_connect_cfg(col).get("board_ids") or [])
               if str(b).lstrip("-").isdigit()}
    try:
        board_id = int(board_id)
    except (TypeError, ValueError):
        return None
    if board_id not in allowed:
        return None
    tb = db.query(Board).filter(Board.id == board_id).first()
    if not tb or tb.deleted_at:
        return None
    grp = (db.query(Group).filter(Group.board_id == board_id)
           .order_by(Group.position, Group.id).first())
    made = Task(board_id=board_id, group_id=grp.id if grp else None,
                title=(title or "").strip() or "פריט חדש",
                status=grp.task_status if grp else TaskStatus.TODO,
                priority=Priority.MEDIUM, created_by=actor_id)
    db.add(made)
    db.flush()
    _ensure_item_uid(db, made)
    _audit(db, made.id, "create", field="item", old=None, new=made.title, user_id=actor_id)
    if not _apply_automation_link(db, task, col, [made.id], actor_id):
        return None
    return made


_runs_logged = 0


def _live_version(db, a):
    """The newest published version — the one in force when an event arrives."""
    try:
        return (db.query(func.max(AutomationVersion.version))
                  .filter(AutomationVersion.automation_id == a.id,
                          AutomationVersion.is_draft == False).scalar())     # noqa: E712
    except Exception:                              # noqa: BLE001
        return None


def _log_automation_run(db, board, a, task, event, outcome, reason="", depth=0,
                        actor_id=None, retry_of=None):
    """Record one attempt, whatever came of it.

    Never raises: the history is a record of the work, never a reason for the
    work to fail. The row copies the rule's sentence and the item's title as
    they read now, so the log still makes sense after either is rewritten.
    """
    global _runs_logged
    try:
        r = recipes.recipe(a.recipe_id) or {}
        row = AutomationRun(
            board_id=a.board_id, automation_id=a.id, recipe_id=a.recipe_id,
            sentence=_automation_label(db, board, a),
            trigger_key=r.get("trigger") or "", action_key=r.get("action") or "",
            task_id=task.id, task_title=(task.title or "")[:300],
            event=event or {}, outcome=outcome, reason=(reason or "")[:400],
            # rule 4 — which version carried this out. The config is read once,
            # when the event arrives, so this is the version that decided it.
            version=_live_version(db, a),
            depth=depth, actor_id=actor_id, retry_of=retry_of,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(row)
        db.flush()
        _runs_logged += 1
        # trimmed now and then rather than on every write — one count query per
        # hundred runs instead of one per run
        if _runs_logged % 100 == 1:
            _prune_automation_runs(db, a.board_id)
        return row
    except Exception as e:                         # noqa: BLE001
        print(f"⚠️  automation run log failed ({a.id}): {e}", flush=True)
        return None


def _prune_automation_runs(db, board_id):
    """Keep the newest AUTOMATION_RUN_LOG_MAX rows for the board."""
    n = db.query(AutomationRun).filter(AutomationRun.board_id == board_id).count()
    if n <= AUTOMATION_RUN_LOG_MAX:
        return
    cut = (db.query(AutomationRun.id).filter(AutomationRun.board_id == board_id)
           .order_by(AutomationRun.id.desc()).offset(AUTOMATION_RUN_LOG_MAX).first())
    if cut:
        (db.query(AutomationRun)
           .filter(AutomationRun.board_id == board_id, AutomationRun.id <= cut[0])
           .delete(synchronize_session=False))


# ── ownership ───────────────────────────────────────────────────────
# The creator owns a rule when it is written, and ownership can be handed to
# another authorised manager. What follows is what happens when the owner stops
# being one — which is NOT the same event as the rule losing a permission it
# needs. The rule keeps running; it is the answerability that is missing, and
# that is a thing for people to fix rather than for the engine to act on.
AUTOMATION_OWNER_ESCALATION_DAYS = 7


def _automation_owner_state(db, board, a):
    """Who answers for this rule, and whether anybody does.

    "Nobody" means one of three things, and they read the same from the board's
    point of view: no owner recorded, an owner whose account is blocked, or an
    owner who is no longer a manager of this board. None of them stops the rule.
    """
    owner_id = a.owner_id or a.created_by
    if not owner_id:
        return {"owner_id": None, "needs_owner": True, "reason": "לאוטומציה אין בעלים"}
    u = db.query(User).filter(User.id == owner_id).first()
    if u is None:
        return {"owner_id": owner_id, "needs_owner": True,
                "reason": "הבעלים אינו קיים יותר במערכת"}
    if u.is_active is False:
        return {"owner_id": owner_id, "needs_owner": True,
                "reason": f"החשבון של {u.name} חסום"}
    if _board_role(db, a.board_id, owner_id) != "admin":
        return {"owner_id": owner_id, "needs_owner": True,
                "reason": f"{u.name} אינו מנהל הלוח יותר"}
    return {"owner_id": owner_id, "needs_owner": False, "reason": ""}


def _notify_owner_once(db, a, board, key, title, body):
    """Tell the owner about a problem, once, until it clears.

    A rule can fire hundreds of times a day, and a rule whose group was deleted
    would fire the same notification every single time. The marker lives on the
    rule, and a successful run wipes it — so the next occurrence is reported
    again rather than being suppressed forever.
    """
    who = (_automation_owner_state(db, board, a) or {}).get("owner_id")
    if not who:
        return
    st = dict(a.state or {})
    told = dict(st.get("told") or {})
    if told.get(key):
        return
    told[key] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    st["told"] = told
    a.state = st
    _notify(db, who, "automation", title, body, board_id=a.board_id)


def _clear_owner_notices(a):
    """A run that worked means the problems it was told about are over."""
    if (a.state or {}).get("told"):
        st = dict(a.state or {})
        st.pop("told", None)
        a.state = st


def _sweep_automation_ownership(db, board, actor_id=None):
    """Chase up the rules on this board that answer to nobody.

    There is no scheduler here, so this runs when the board's automations are
    read — by a board admin, which is exactly who has to act on it. The board's
    admins are told once; after AUTOMATION_OWNER_ESCALATION_DAYS the system
    admins are told too, and then daily, because an unowned rule that nobody
    picks up is the sort of thing that goes quiet for a quarter.

    Nothing here changes a rule's status. See rule 4 of the ownership rules:
    the indicator is the point, not an automatic suspension.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date().isoformat()
    rules = db.query(Automation).filter(Automation.board_id == board.id).all()
    admins = [m.user_id for m in db.query(BoardMember)
              .filter(BoardMember.board_id == board.id, BoardMember.role == "admin").all()]
    changed = False
    for a in rules:
        state = _automation_owner_state(db, board, a)
        st = dict(a.state or {})
        if not state["needs_owner"]:
            had = [st.pop(k, None) for k in ("owner_gap_since", "owner_told", "owner_escalated")]
            if any(x is not None for x in had):
                a.state = st
                changed = True
            continue
        since = st.get("owner_gap_since")
        if not since:
            since = now.isoformat()
            st["owner_gap_since"] = since
            changed = True
        label = a.name or _automation_label(db, board, a)
        # the board's own managers, once
        if not st.get("owner_told"):
            for uid in admins:
                _notify(db, uid, "automation", "אוטומציה דורשת שיוך בעלים",
                        f"בלוח '{board.name}': {state['reason']}. יש למנות בעלים חלופי "
                        f"לאוטומציה — {label}. האוטומציה ממשיכה לפעול בינתיים.",
                        board_id=board.id)
            st["owner_told"] = today
            changed = True
        # and after a week, the system admins, every day until it is settled
        try:
            days = (now - datetime.fromisoformat(since)).days
        except (TypeError, ValueError):
            days = 0
        if days >= AUTOMATION_OWNER_ESCALATION_DAYS and st.get("owner_escalated") != today:
            for uid in [u.id for u in db.query(User).filter(User.role == "admin").all()]:
                _notify(db, uid, "automation", "הסלמה — אוטומציה ללא בעלים",
                        f"{days} ימים ללא בעלים: {label} (לוח '{board.name}'). "
                        f"{state['reason']}. מנהלי הלוח קיבלו התראה ולא מונה בעלים חלופי.",
                        board_id=board.id)
            st["owner_escalated"] = today
            changed = True
        a.state = st
    if changed:
        db.commit()


def _audit_owner_change(db, a, old_owner, new_owner, actor_id):
    """Rule 7 — every handover, with both names, who did it and when.

    Written to the audit log and not only to the rule's own versions: "who made
    this person answerable, and when" is a question asked from outside the
    board, and the audit is where the rest of the system answers it.
    """
    nm = lambda uid: (db.query(User.name).filter(User.id == uid).scalar() or "—") if uid else "—"
    db.add(AuditLog(entity_type="automation", entity_id=a.id, action="transfer_owner",
                    field_name="owner_id",
                    old_value=f"{nm(old_owner)} (#{old_owner})" if old_owner else "—",
                    new_value=f"{nm(new_owner)} (#{new_owner})" if new_owner else "—",
                    changed_by=actor_id))


def _automation_blockers(db, board, a):
    """What stands between this rule and running, re-derived NOW.

    Two kinds, kept apart because they end differently (rule 5): a dependency
    that is gone — a status removed from the board, a deleted group — makes this
    one firing pointless, while a permission that is gone means the rule may no
    longer do what it says at all, and it is taken out of service.

    Deliberately re-read on every fire rather than trusted from the moment the
    rule was saved. A rule is a standing instruction: the board it acts on, the
    people it names and the columns it reads all change underneath it.
    """
    out = []
    r = recipes.recipe(a.recipe_id)
    if not r:
        return [{"kind": "dependency", "text": "המתכון אינו מוכר בגרסה הזאת"}]
    cfg = a.config or {}
    # the grant, before anything else: an action outside it is refused whatever
    # the rest of the row says — and a rule carries up to MAX_ACTIONS of them,
    # so the grant is asked of each one. An ungranted action anywhere in the
    # list stops the whole rule: the other three are not a reason to run most
    # of something nobody approved.
    acts = recipes.action_list(a.recipe_id, cfg)
    for one in acts:
        if one["key"] not in AUTOMATION_GRANTED_ACTIONS:
            return [{"kind": "permission",
                     "text": f"הפעולה '{one['key']}' אינה מאושרת לאוטומציה"}]
    _, err = recipes.validate(a.recipe_id, cfg)
    if err:
        out.append({"kind": "dependency", "text": err})
    # A condition about a column the board no longer has cannot be answered, so
    # the rule does not fire (see _condition_holds). That is the safe reading
    # and a silent one — the rule looks active and does nothing — so it is said
    # here, which is what the test screen and the "דורשות טיפול" list read.
    for c in cfg.get(recipes.CONDITION_KEY) or []:
        if c.get("kind") not in recipes.COLUMN_CONDITIONS:
            continue
        spec = c.get("value") or {}
        col = _find_col(db, a.board_id, str(spec.get("col") or ""))
        if not col:
            out.append({"kind": "dependency",
                        "text": "העמודה שהתנאי מתייחס אליה נמחקה מהלוח"})
        elif recipes.column_kind(col.get("type")) != recipes.column_kind(spec.get("type")):
            out.append({"kind": "dependency",
                        "text": f"סוג העמודה '{col.get('title') or spec.get('col')}' "
                                f"שונה מאז שהתנאי נכתב"})
    for one in acts:
        for f in recipes.action_fields(one["key"]):
            v = one["values"].get(f["key"])
            if f["type"] == "person":
                if not _can_be_assigned(db, a.board_id, v):
                    nm = db.query(User.name).filter(User.id == v).scalar() or v
                    why = _not_taggable_reason(db, a.board_id, v) or "אינו חבר בלוח"
                    out.append({"kind": "permission", "text": f"{nm} {why}"})
            elif f["type"] == "status":
                if not any(x["key"] == str(v) for x in _board_statuses(board)):
                    out.append({"kind": "dependency", "text": f"הסטטוס '{v}' אינו קיים בלוח"})
            elif f["type"] == "priority":
                if not any(x["key"] == str(v) for x in _board_priorities(board)):
                    out.append({"kind": "dependency", "text": f"העדיפות '{v}' אינה קיימת בלוח"})
            elif f["type"] == "group":
                if not db.query(Group).filter(Group.id == v, Group.board_id == a.board_id).first():
                    out.append({"kind": "dependency", "text": "הקבוצה שהכלל מפנה אליה נמחקה"})
            elif f["type"] == "connect":
                col = _find_col(db, a.board_id, str(v))
                if not col or col.get("type") != "connect":
                    out.append({"kind": "dependency", "text": "עמודת הקישור אינה קיימת בלוח"})
            elif f["type"] == "item":
                if not db.query(Task).filter(Task.id == v, Task.deleted_at == None).first():  # noqa: E711
                    out.append({"kind": "dependency", "text": "הפריט שהכלל מקשר אליו נמחק"})
            elif f["type"] == "board":
                tb = db.query(Board).filter(Board.id == v, Board.deleted_at == None).first()  # noqa: E711
                if not tb:
                    out.append({"kind": "dependency", "text": "לוח היעד נמחק"})
                else:
                    # the grant is per board too: the rule may only reach a board the
                    # connect column is still configured for
                    col = _find_col(db, a.board_id, str(one["values"].get("connect") or ""))
                    allowed = {int(x) for x in (_connect_cfg(col).get("board_ids") or [])
                               if str(x).lstrip("-").isdigit()} if col else set()
                    if int(v) not in allowed:
                        out.append({"kind": "permission",
                                    "text": f"לוח '{tb.name}' אינו מאושר יותר לעמודת הקישור"})
    return out


def _suspend_for_lost_permission(db, a, board, why):
    """Rule 5: a permission the rule needs is gone, so the rule stops.

    Not a skip. A rule that cannot do what it says, every time, is a rule
    somebody has to look at — and leaving it "active" means the board reads as
    automated when it is not.
    """
    if a.status != "active":
        return
    _set_automation_status(a, "paused_error")
    a.consecutive_failures = max(a.consecutive_failures or 0, 1)
    who = a.owner_id or a.created_by
    if who:
        _notify(db, who, "automation", "אוטומציה הושהתה — הרשאה חסרה",
                f"האוטומציה בלוח '{board.name}' הושהתה: {why}. "
                f"{_automation_label(db, board, a)}",
                board_id=a.board_id)


def _suspend_if_broken(db, a, board):
    """Take a rule out of service once it has failed AUTOMATION_FAIL_CUTOFF times
    in a row, and tell whoever is responsible for it.

    Only an active rule is suspended — a rule someone already paused, or a draft,
    has nothing to be taken away.
    """
    if a.status != "active" or (a.consecutive_failures or 0) < AUTOMATION_FAIL_CUTOFF:
        return
    _set_automation_status(a, "paused_error")
    a.consecutive_failures = AUTOMATION_FAIL_CUTOFF      # keep the count that suspended it
    who = a.owner_id or a.created_by
    if who:
        _notify(db, who, "automation", "אוטומציה הושהתה עקב שגיאות",
                f"האוטומציה בלוח '{board.name}' נכשלה {AUTOMATION_FAIL_CUTOFF} פעמים "
                f"ברצף והושהתה: {_automation_label(db, board, a)}",
                board_id=a.board_id)


def _automation_freeze(db, board_id):
    """The open freeze that covers this board — the organisation's, or its own.

    An emergency stop is checked before anything runs, not inside the rules:
    while it holds, no rule on the board fires at all. Nothing writes a run row
    for it either — a freeze can hold for hours, and a board's history is not
    the place to learn that by reading the same line four hundred times. The
    freeze itself is the record, and the board says so on screen.
    """
    return (db.query(AutomationFreeze)
              .filter(AutomationFreeze.released_at == None,          # noqa: E711
                      or_(AutomationFreeze.scope == "org",
                          and_(AutomationFreeze.scope == "board",
                               AutomationFreeze.board_id == board_id)))
              .order_by(AutomationFreeze.id.desc()).first())


def _count_automation_usage(db, board_id, outcome):
    """One month, one board, one counter. Never raises — accounting must not be
    the reason a rule that worked is recorded as having failed."""
    col = {"ran": "ran", "skipped": "skipped", "failed": "failed"}.get(outcome)
    if not col:
        return
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        row = (db.query(AutomationUsage)
                 .filter(AutomationUsage.period == period,
                         AutomationUsage.board_id == board_id).first())
        if row is None:
            row = AutomationUsage(period=period, board_id=board_id, ran=0, skipped=0, failed=0)
            db.add(row)
            db.flush()
        setattr(row, col, (getattr(row, col) or 0) + 1)
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    except Exception as e:                         # noqa: BLE001
        print(f"⚠️  automation usage not counted ({board_id}): {e}", flush=True)


def _fire_rule(db, a, task, event, actor_id, depth=0, retry_of=None):
    """Run one matching rule against one item, record what came of it, and let
    the result cascade.

    Never raises: a broken rule must not take down the edit that triggered it.
    The three outcomes the history distinguishes are decided here — the action
    did something (`ran`), it had nothing to do (`skipped`), or it blew up
    (`failed`).
    """
    board = db.query(Board).filter(Board.id == task.board_id).first()
    if not board:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # rule 4 — re-checked here, on every single firing, and never taken on trust
    # from when the rule was written
    blockers = _automation_blockers(db, board, a)
    if blockers:
        lost = next((b for b in blockers if b["kind"] == "permission"), None)
        why = " · ".join(b["text"] for b in blockers[:3])
        a.last_run_at, a.last_outcome = now, "skipped"
        a.skip_count = (a.skip_count or 0) + 1
        _count_automation_usage(db, a.board_id, "skipped")
        row = _log_automation_run(db, board, a, task, event, "skipped", why,
                                  depth, actor_id, retry_of)
        if lost:
            _suspend_for_lost_permission(db, a, board, lost["text"])
        else:
            # a dependency that is gone is the owner's to fix, and they are told
            # once rather than on every firing — see _notify_owner_once
            _notify_owner_once(db, a, board, "dependency",
                               "אוטומציה מדלגת — תלות חסרה",
                               f"האוטומציה בלוח '{board.name}' אינה מתבצעת: {why}. "
                               f"{_automation_label(db, board, a)}")
        return row
    # The other half of the "if". The trigger said what happened; the rule's
    # conditions say what also had to be true of the item, and they are read
    # here — now, off the item — not taken from when the rule was written.
    # A rule held back by one is recorded as skipped with the condition named,
    # which is the whole reason the history keeps the non-events.
    ok, why_not = _conditions_hold(db, board, task,
                                   (a.config or {}).get(recipes.CONDITION_KEY))
    if not ok:
        a.last_run_at, a.last_outcome = now, "skipped"
        a.skip_count = (a.skip_count or 0) + 1
        _count_automation_usage(db, a.board_id, "skipped")
        return _log_automation_run(db, board, a, task, event, "skipped", why_not,
                                   depth, actor_id, retry_of)
    # rule 3 — the engine acts as itself, not as whoever tripped the rule and not
    # as whoever wrote it. `actor_id` stays the record of who tripped it.
    engine_id = _automation_identity(db)
    try:
        # The rule's actions are one step. A rule may carry up to
        # recipes.MAX_ACTIONS of them, and without a savepoint an action that
        # raised halfway down the list left the ones before it written and the
        # history saying "failed" — a rule that half-happened, which is the
        # single hardest thing to work out afterwards. The savepoint is the
        # rule's own: the event that tripped it, and every other rule, are
        # untouched by this one failing.
        sp = db.begin_nested()
        try:
            follow, note = _run_action(db, a, task, engine_id, board)
            sp.commit()
        except BaseException:
            sp.rollback()
            raise
    except _Skipped as sk:
        # an attempt all the same: "הפעלה אחרונה" is when it last tried, which is
        # a different question from when it last did something
        a.last_run_at, a.last_outcome = now, "skipped"
        a.skip_count = (a.skip_count or 0) + 1
        _count_automation_usage(db, a.board_id, "skipped")
        return _log_automation_run(db, board, a, task, event, "skipped", sk.reason,
                                   depth, actor_id, retry_of)
    except Exception as e:                         # noqa: BLE001
        print(f"⚠️  automation {a.id} ({a.recipe_id}) failed: {e}", flush=True)
        a.last_run_at, a.last_failure_at, a.last_outcome = now, now, "failed"
        a.fail_count = (a.fail_count or 0) + 1
        a.consecutive_failures = (a.consecutive_failures or 0) + 1
        _count_automation_usage(db, a.board_id, "failed")
        row = _log_automation_run(db, board, a, task, event, "failed",
                                  f"{type(e).__name__}: {e}", depth, actor_id, retry_of)
        _suspend_if_broken(db, a, board)
        return row
    a.last_run_at = a.last_success_at = now
    a.last_outcome = "ran"
    a.run_count = (a.run_count or 0) + 1
    a.consecutive_failures = 0
    _clear_owner_notices(a)
    _count_automation_usage(db, a.board_id, "ran")
    row = _log_automation_run(db, board, a, task, event, "ran", note, depth, actor_id, retry_of)
    for ev in follow or []:
        _run_automations(db, task, ev, actor_id, depth + 1)
        # a rule that changed this item's status is a status change like any
        # other, so items linked to it hear about it too — bounded by the same
        # depth, or two rules pointing at each other would ping-pong
        if ev.get("type") == "status_changes_to":
            _fan_out_linked_status(db, task, ev.get("status"), actor_id, depth + 1)
    return row


def _run_one_automation(db, a, task, actor_id):
    """Run a single rule against one item — the date sweep's entry point, which
    picks its own items instead of reacting to an event."""
    _fire_rule(db, a, task, {"type": "due_date_arrives"}, actor_id, 0)


# How many fired item ids a date rule remembers. Bounded so the marker cannot
# grow without limit on a long-lived board; older entries fall off the front.
_DUE_FIRED_MAX = 500


def _sweep_due_date_automations(db, board_id, actor_id):
    """Fire "כאשר מגיע תאריך היעד" rules for items whose due date has passed.

    There is no scheduler here, so this runs when the board is read. Each rule
    remembers which items it already fired for, so re-opening a board cannot
    notify the same person about the same item twice.
    """
    if _automation_freeze(db, board_id) is not None:
        return
    rules = [a for a in db.query(Automation).filter(
                Automation.board_id == board_id,
                Automation.is_active == True)                             # noqa: E712
                .order_by(Automation.run_order, Automation.id).all()
             if (recipes.recipe(a.recipe_id) or {}).get("trigger") == "due_date_arrives"]
    if not rules:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due = db.query(Task).filter(Task.board_id == board_id, Task.is_archived == False,  # noqa: E712
                                Task.due_date != None, Task.due_date <= now).all()     # noqa: E711
    if not due:
        return
    fired_any = False
    for a in rules:
        state = dict(a.state or {})
        fired = list(state.get("fired") or [])
        seen = set(fired)
        for t in due:
            # a finished item is not "overdue" in any sense the user cares about
            if t.id in seen or _st_of(t) in ("done", "cancelled"):
                continue
            # rule 2 — the date arriving is the event, and an event from before
            # the rule was switched on is not one it gets to act on. Without
            # this, activating a due-date rule fires it at every item that was
            # already overdue, which reads as the rule inventing history.
            if a.activated_at and t.due_date and t.due_date < a.activated_at:
                continue
            _run_one_automation(db, a, t, actor_id)
            fired.append(t.id)
            seen.add(t.id)
            fired_any = True
        if len(fired) > _DUE_FIRED_MAX:
            fired = fired[-_DUE_FIRED_MAX:]
        state["fired"] = fired
        a.state = state
    if fired_any:
        db.commit()


def _fan_out_linked_status(db, task, status_key, actor_id, depth=0):
    """Tell every item linked TO this one that its status changed.

    Only through two-way columns. A one-way link is stored in the cell of the
    side that made it, so there is no index from the far item back to the items
    pointing at it — finding them would mean scanning every board that could
    link here on every status change. The trigger therefore needs a two-way
    column, which is where the relationship is a row and the lookup is cheap.
    """
    if depth >= AUTOMATION_MAX_DEPTH:
        return
    rows = db.query(ItemLink).filter(
        or_(ItemLink.a_task_id == task.id, ItemLink.b_task_id == task.id)).all()
    seen = set()
    for l in rows:
        other_id = l.b_task_id if l.a_task_id == task.id else l.a_task_id
        if other_id in seen:
            continue
        seen.add(other_id)
        other = db.query(Task).filter(Task.id == other_id).first()
        if other is None:
            continue
        _run_automations(db, other, {"type": "linked_status_changes_to",
                                     "status": str(status_key),
                                     "source_task_id": task.id}, actor_id, depth + 1)


def _run_automations(db, task, event, actor_id, depth=0):
    """Fire every active rule on the item's board that matches this event."""
    if task is None:
        return
    board = db.query(Board).filter(Board.id == task.board_id).first()
    if not board or board.deleted_at:
        return
    if _automation_freeze(db, task.board_id) is not None:
        return                                     # an emergency stop is holding
    # "סדר ביצוע" — which rule goes first when one event trips several. The id is
    # the tiebreak, so rules nobody ordered still run oldest-first as before.
    rules = (db.query(Automation)
               .filter(Automation.board_id == task.board_id, Automation.is_active == True)  # noqa: E712
               .order_by(Automation.run_order, Automation.id).all())
    matching = [a for a in rules if _automation_matches(a, event)]
    if depth >= AUTOMATION_MAX_DEPTH:
        # The cascade has gone as far as it is allowed to go. What would have run
        # here is recorded as skipped rather than dropped: a chain that stops
        # half way is exactly what someone opens the history to understand.
        for a in matching:
            _log_automation_run(db, board, a, task, event, "skipped",
                                "שרשרת האוטומציות הגיעה לעומק המקסימלי", depth, actor_id)
            # "מושהית עקב שגיאה" names a loop as one of its causes: a rule that
            # keeps being cut off by the ceiling is in one, and leaving it active
            # means the board reads as automated while this never completes
            st = dict(a.state or {})
            st["loop_hits"] = (st.get("loop_hits") or 0) + 1
            a.state = st
            if st["loop_hits"] >= AUTOMATION_FAIL_CUTOFF and a.status == "active":
                _set_automation_status(a, "paused_error")
                _notify_owner_once(db, a, board, "loop",
                                   "אוטומציה הושהתה — לולאה",
                                   f"האוטומציה בלוח '{board.name}' נקטעה שוב ושוב בעומק "
                                   f"המקסימלי של שרשרת האוטומציות והושהתה: "
                                   f"{_automation_label(db, board, a)}")
        return
    for a in matching:
        _fire_rule(db, a, task, event, actor_id, depth)


# ── Automations API ─────────────────────────────────────────────────
def _can_manage_automations(db, board, user_id):
    """Who may add, edit, switch off or delete a board's rules.

    A board admin, and a system admin (who is admin on every board by role).
    Deliberately NOT a manager of the environment, which it used to include: a
    rule rewrites the items of one board, and the person answerable for that
    board is the one who may write it. An environment manager who needs it can
    be made an admin of the board, which is a decision someone takes rather
    than a right that arrives with a workspace.
    """
    if user_id is None:
        return True                                # auth disabled → no per-user gate
    return _board_role(db, board.id, user_id) == "admin"


def _can_view_automations(db, board, user_id):
    """Who may read a board's rules, its run history and its versions.

    A board admin always may. A board EDITOR — "חבר לוח" — only where the
    `view_automations` capability is granted, which is what makes it a decision
    someone took rather than a side effect of being invited. A board VIEWER
    never does: the rules are how the board behaves, and someone who cannot
    change anything on it has no business reading its machinery.
    """
    if user_id is None:
        return True                                # auth disabled → no per-user gate
    if _can_manage_automations(db, board, user_id):
        return True
    role = _board_role(db, board.id, user_id)
    if role is None or role == "viewer":
        return False
    return _cap(db, user_id, "view_automations")


def _can_export_automations(db, board, user_id):
    """Taking the log — or a past version — out of the system.

    A board admin, and only with the data capability: an export is a copy of who
    did what on every item the rules touched, and it leaves the place where these
    permissions are enforced.
    """
    if user_id is None:
        return True
    if _ws_role(db, user_id) == "admin":
        return True
    if _board_role(db, board.id, user_id) != "admin":
        return False
    return _cap(db, user_id, "export_automation_log")


def _automation_json(db, board, a):
    r = recipes.recipe(a.recipe_id) or {}
    uname = lambda uid: (db.query(User.name).filter(User.id == uid).scalar() or "") if uid else ""
    iso = lambda d: d.isoformat() if d else None
    _own = _automation_owner_state(db, board, a) if board else {"needs_owner": False, "reason": ""}
    ran, failed, skipped = a.run_count or 0, a.fail_count or 0, a.skip_count or 0
    tried = ran + failed                  # a skip is neither a success nor a failure
    # a new rule is owned by its creator; the fallback covers rules written before
    # the column existed, which have no owner recorded at all
    owner = a.owner_id or a.created_by
    sentence = _automation_label(db, board, a)
    return {
        "id": a.id, "board_id": a.board_id, "recipe_id": a.recipe_id,
        "sentence": sentence,
        # what the list shows as the rule's heading: its name if it has one, and
        # the sentence itself if it does not, so a row is never nameless
        "name": a.name or "", "display_name": a.name or sentence.replace("«", "").replace("»", ""),
        "description": a.description or "",
        "trigger": r.get("trigger"), "action": r.get("action"),
        "fields": r.get("fields", []), "config": a.config or {},
        # the extra conditions as stored, and as read — the UI shows the second
        # and edits the first
        "conditions": (a.config or {}).get(recipes.CONDITION_KEY) or [],
        "condition_phrases": _condition_phrases(db, board, (a.config or {}).get(
            recipes.CONDITION_KEY), quote=False) if board else [],
        # the extra actions as stored, and as read — the same pairing the
        # conditions above have: the UI edits the first and shows the second
        "actions": (a.config or {}).get(recipes.ACTIONS_KEY) or [],
        "action_phrases": _action_phrases(db, board, (a.config or {}).get(
            recipes.ACTIONS_KEY), quote=False) if board else [],
        "status": a.status or ("active" if a.is_active else "paused"),
        "is_active": bool(a.is_active),
        "importance": a.importance or "normal",
        "run_order": a.run_order or 0,
        "owner_id": owner, "owner_name": uname(owner),
        "owner_is_creator": owner == a.created_by,
        # rule 4 — shown, never acted on: the rule keeps running
        "needs_owner": _own["needs_owner"], "owner_problem": _own["reason"],
        "created_by": a.created_by, "created_by_name": uname(a.created_by),
        "created_at": iso(a.created_at),
        "updated_by": a.updated_by, "updated_by_name": uname(a.updated_by),
        "updated_at": iso(a.updated_at),
        "run_count": ran, "fail_count": failed, "skip_count": skipped,
        "consecutive_failures": a.consecutive_failures or 0,
        # rule 3 — an edit waiting to be published; the rule below it is what runs
        "draft_version": a.draft_version,
        "activated_at": iso(a.activated_at),
        "missing_fields": recipes.missing_fields(a.recipe_id, a.config or {}),
        "last_run_at": iso(a.last_run_at), "last_success_at": iso(a.last_success_at),
        "last_failure_at": iso(a.last_failure_at), "last_outcome": a.last_outcome or "",
        # a rate over nothing is not 0% — it is unknown, and the UI says so
        "success_rate": round(100 * ran / tried) if tried else None,
        # what a board admin has to go and look at: a rule taken out of service,
        # and one whose last attempt failed but has not hit the cutoff yet
        "needs_attention": (a.status == "paused_error") or (a.last_outcome == "failed"),
    }


def _automation_counts(rows):
    """The tiles above the ניהול list. Always over the whole board — switching a
    filter must not change the totals it is being filtered against."""
    st_of = lambda a: a["status"]
    return {"total": len(rows),
            "active": sum(1 for a in rows if st_of(a) == "active"),
            "paused": sum(1 for a in rows if st_of(a) in ("paused", "paused_error")),
            "paused_error": sum(1 for a in rows if st_of(a) == "paused_error"),
            "draft": sum(1 for a in rows if st_of(a) == "draft"),
            "deleting": sum(1 for a in rows if st_of(a) == "deleting"),
            "needs_attention": sum(1 for a in rows if a["needs_attention"]),
            "needs_owner": sum(1 for a in rows if a.get("needs_owner"))}


def _automation_people(db, board_id, rows):
    """Who can appear in the owner and creator filters: everyone named on a rule,
    plus the board's members, so an owner can be handed over to any of them."""
    ids, out = set(), []
    for a in rows:
        ids.update([a.get("owner_id"), a.get("created_by")])
    for m in db.query(BoardMember.user_id).filter(BoardMember.board_id == board_id).all():
        ids.add(m[0])
    for uid in [i for i in ids if i]:
        u = db.query(User).filter(User.id == uid).first()
        if u:
            out.append({"id": u.id, "name": u.name, "avatar_url": u.avatar_url,
                        "is_board_admin": _board_role(db, board_id, u.id) == "admin"})
    out.sort(key=lambda x: x["name"] or "")
    return out


# The parts of a rule a version keeps, and what each is called when it changes.
_VERSIONED = {"recipe_id": "המתכון", "config": "הגדרות הכלל", "name": "השם",
              "description": "התיאור העסקי", "status": "הסטטוס", "importance": "החשיבות",
              "owner_id": "הבעלים", "run_order": "סדר הביצוע"}


def _snapshot_automation(a):
    return {k: getattr(a, k) for k in _VERSIONED}


def _record_automation_version(db, board, a, user_id, before=None, note="", draft=None):
    """Keep what the rule looks like now, and say what moved.

    A rule quietly rewrites items, so "who changed it, and to what?" has to stay
    answerable. Nothing is written when nothing actually changed — a PATCH that
    re-sends the same values is not a version.
    """
    snap = draft if draft is not None else _snapshot_automation(a)
    if before is not None:
        moved = [he for k, he in _VERSIONED.items() if before.get(k) != snap.get(k)]
        if not moved:
            return None
        if draft is not None:
            summary = note or "טיוטת עריכה: " + ", ".join(moved)
        else:
            summary = note or ("שונו: " + ", ".join(moved) if len(moved) > 1 else "שונה: " + moved[0])
    else:
        summary = note or ("טיוטת עריכה" if draft is not None else "נוצרה")
    n = db.query(AutomationVersion).filter(AutomationVersion.automation_id == a.id).count()
    row = AutomationVersion(automation_id=a.id, board_id=a.board_id, version=n + 1,
                            sentence=_automation_label(db, board, a), snapshot=snap,
                            summary=summary[:300], changed_by=user_id,
                            is_draft=bool(draft is not None),
                            changed_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(row)
    db.flush()
    if draft is not None:
        a.draft_version = row.version
    return row


@app.get("/api/automations/recipes")
def automation_recipes(user_id: int = Depends(current_user_id)):
    """What the יצירה tab is built from.

    `recipes` are the ready-made templates. `blueprint` is the same set indexed
    the other way round — trigger → the actions that may follow it — which is
    what "אוטומציה מאפס" walks through. Building from scratch therefore lands on
    a recipe too, so both paths store the same row and share one validation.
    """
    return {"recipes": recipes.catalog(), "blueprint": recipes.blueprint(),
            "triggers": {k: recipes.plain(v) for k, v in recipes.TRIGGERS.items()},
            "actions": {k: recipes.plain(v) for k, v in recipes.ACTIONS.items()},
            # the second half of the "if": what else may be required of the item
            "conditions": recipes.conditions_catalog(),
            "max_conditions": recipes.MAX_CONDITIONS,
            # which column types a condition can be written against, grouped by
            # the kind that decides what its value looks like — the builder asks
            # for a type, then a column of that type, then the value
            "column_kinds": recipes.column_types(),
            "multi_column_types": list(recipes.MULTI_COLUMN_TYPES),
            # what a second, third and fourth action may be, and how many of
            # them a rule may carry in all (the recipe's own included)
            "action_catalog": recipes.actions_catalog(),
            "max_actions": recipes.MAX_ACTIONS}


@app.get("/api/boards/{board_id}/automations")
def list_board_automations(board_id: int, user_id: int = Depends(current_user_id)):
    """Every rule on the board. Visible to any member; editable only by admins —
    the client uses can_manage to decide whether to render the controls."""
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if not _can_view_automations(db, b, user_id):
            raise HTTPException(403, "אין לך הרשאה לצפות באוטומציות של הלוח")
        # chase up anything that answers to nobody — the person reading this
        # screen is the person who has to appoint someone
        if _can_manage_automations(db, b, user_id):
            _sweep_automation_ownership(db, b, user_id)
        rows = (db.query(Automation).filter(Automation.board_id == board_id)
                  .order_by(Automation.run_order, Automation.id).all())
        out = [_automation_json(db, b, a) for a in rows]
        return {"automations": out, "counts": _automation_counts(out),
                "can_export": _can_export_automations(db, b, user_id),
                "people": _automation_people(db, board_id, out),
                "statuses": list(AUTOMATION_STATUSES), "importance": list(AUTOMATION_IMPORTANCE),
                "can_manage": _can_manage_automations(db, b, user_id)}


def _check_automation_person(db, board_id, cfg):
    """A rule may only name someone invited to the board.

    Rejected when the rule is saved rather than when it runs: a rule that
    silently does nothing is worse than one that refuses to be written, because
    nobody finds out until the notification they were counting on never arrives.
    Run time re-checks anyway (see _run_automations) — membership can change
    after the rule is stored.
    """
    # a condition may name somebody too ("רק אם X משויך"), and a rule whose
    # condition names a stranger to the board is a rule that can never hold
    for c in (cfg or {}).get(recipes.CONDITION_KEY) or []:
        spec = recipes.condition(c.get("kind")) or {}
        who = None
        if spec.get("type") == "person":
            who = c.get("value")
        elif spec.get("type") == "column":
            # a people column asks about a person too, and a rule conditioned on
            # somebody who was never invited is a rule that can never hold
            val = c.get("value") or {}
            if recipes.column_kind(val.get("type")) == "people":
                who = val.get("value")
        if who is None:
            continue
        if not _can_be_assigned(db, board_id, who):
            nm = db.query(User.name).filter(User.id == who).scalar() or "המשתמש"
            why = _not_taggable_reason(db, board_id, who) or "אינו חבר בלוח"
            raise HTTPException(400, f"{nm} {why}, ולכן לא ניתן להתנות בו")
    # every action in the rule, not only the recipe's own: a second action that
    # notifies somebody who was never invited is the same rule that silently
    # does nothing, one line further down
    people = [(cfg or {}).get("a_person")]
    for extra in (cfg or {}).get(recipes.ACTIONS_KEY) or []:
        values = (extra or {}).get("values") or {}
        for f in recipes.action_fields(str((extra or {}).get("key") or "")):
            if f["type"] == "person":
                people.append(values.get(f["key"]))
    for pid in people:
        if pid in (None, ""):
            continue
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            raise HTTPException(400, "נמען האוטומציה אינו תקין")
        if not _can_be_assigned(db, board_id, pid):
            raise HTTPException(400, "לא ניתן לבחור משתמש מושבת" if _account_blocked(db, pid)
                                else "אפשר לבחור רק משתמשים שהוזמנו ללוח")


def _automation_meta(db, board_id, data, a=None):
    """Read the management fields off a request body.

    Returns only the keys the caller actually sent, so a PATCH that changes the
    owner does not silently reset the importance. The status is deliberately NOT
    returned here — it goes through _set_automation_status, which also moves the
    engine's switch.
    """
    out = {}
    if "name" in data:
        out["name"] = (str(data.get("name") or "")).strip()[:120]
    if "description" in data:
        out["description"] = (str(data.get("description") or "")).strip()[:2000]
    if "importance" in data:
        imp = str(data.get("importance") or "normal")
        if imp not in AUTOMATION_IMPORTANCE:
            raise HTTPException(400, "דרגת חשיבות לא מוכרת")
        out["importance"] = imp
    if "run_order" in data:
        try:
            out["run_order"] = max(0, min(int(data.get("run_order") or 0), 9999))
        except (TypeError, ValueError):
            raise HTTPException(400, "סדר ביצוע חייב להיות מספר")
    if "owner_id" in data:
        oid = data.get("owner_id")
        if oid in (None, "", 0):
            out["owner_id"] = None              # unclaimed — answers to its creator
        else:
            try:
                oid = int(oid)
            except (TypeError, ValueError):
                raise HTTPException(400, "בעלים לא תקין")
            if not _can_be_assigned(db, board_id, oid):
                raise HTTPException(400, "אפשר לבחור כבעלים רק משתמשים שהוזמנו ללוח")
            # an owner answers for the rule, so an owner has to be able to change
            # it — the same bar the bulk handover holds, and the same words
            if _board_role(db, board_id, oid) != "admin":
                nm = db.query(User.name).filter(User.id == oid).scalar() or ""
                raise HTTPException(400, f"{nm} אינו מנהל הלוח — בעלות מועברת למנהל מורשה")
            out["owner_id"] = oid
    return out


def _automation_status_from(data, current="active"):
    """The state a request asks for. `status` wins; a bare `is_active` — what the
    switch in the list sends, and every older client — maps onto it."""
    if "status" in data:
        want = str(data.get("status") or "")
        if want not in AUTOMATION_STATUSES:
            raise HTTPException(400, "סטטוס אוטומציה לא מוכר")
        return want
    if "is_active" in data:
        return "active" if data.get("is_active") else "paused"
    return current


@app.post("/api/boards/{board_id}/automations")
def create_automation(board_id: int, data: dict, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול להגדיר אוטומציות")
        # a draft is allowed to be half-built; anything that will run is not
        _draft = (data.get("status") == "draft")
        cfg, err = (recipes.validate_partial if _draft else recipes.validate)(
            data.get("recipe_id"), data.get("config") or {})
        if err:
            raise HTTPException(400, err)
        _check_automation_person(db, board_id, cfg)
        _check_automation_reach(db, board_id, data["recipe_id"], cfg, user_id)
        meta = _automation_meta(db, board_id, data)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        a = Automation(board_id=board_id, recipe_id=data["recipe_id"], config=cfg,
                       created_by=user_id, updated_by=user_id,
                       created_at=now, updated_at=now, run_count=0, state={},
                       fail_count=0, skip_count=0, consecutive_failures=0, last_outcome="",
                       name=meta.get("name", ""), description=meta.get("description", ""),
                       importance=meta.get("importance", "normal"),
                       run_order=meta.get("run_order", 0),
                       # unset means the creator, so a new rule is never ownerless
                       owner_id=meta.get("owner_id", user_id))
        # a rule saved as a draft is written but does not run until someone says so
        _set_automation_status(a, _automation_status_from(data))
        db.add(a)
        db.flush()
        _record_automation_version(db, b, a, user_id)
        db.commit()
        db.refresh(a)
        return _automation_json(db, b, a)


@app.post("/api/automations/{automation_id}/duplicate")
def duplicate_automation(automation_id: int, user_id: int = Depends(current_user_id)):
    """Copy a rule, as a draft.

    A copy that started running the moment it was made would double every action
    the original takes, on a board where nobody asked for that yet. So the copy
    is written switched off, for someone to adjust and publish deliberately.
    """
    with Session(engine) as db:
        src = db.query(Automation).filter(Automation.id == automation_id).first()
        if not src:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == src.board_id).first()
        if not b or b.deleted_at or not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול לשכפל אוטומציות")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        name = (src.name or _automation_label(db, b, src).replace("«", "").replace("»", ""))[:105]
        a = Automation(board_id=src.board_id, recipe_id=src.recipe_id, config=dict(src.config or {}),
                       name=f"{name} (עותק)"[:120], description=src.description or "",
                       importance=src.importance or "normal", run_order=src.run_order or 0,
                       owner_id=src.owner_id or user_id,
                       created_by=user_id, updated_by=user_id, created_at=now, updated_at=now,
                       run_count=0, fail_count=0, skip_count=0, consecutive_failures=0,
                       last_outcome="", state={})
        _set_automation_status(a, "draft")
        db.add(a)
        db.flush()
        _record_automation_version(db, b, a, user_id, note=f"שוכפלה מאוטומציה #{src.id}")
        db.commit()
        db.refresh(a)
        return _automation_json(db, b, a)


@app.get("/api/automations/{automation_id}/versions")
def automation_versions(automation_id: int, user_id: int = Depends(current_user_id)):
    """Every version of the rule, newest first. Readable by any board member —
    the same bar as reading the rules themselves."""
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        _vb = db.query(Board).filter(Board.id == a.board_id).first()
        if not _vb or not _can_view_automations(db, _vb, user_id):
            raise HTTPException(403, "אין לך הרשאה לצפות בגרסאות האוטומציה")
        uname = lambda uid: (db.query(User.name).filter(User.id == uid).scalar() or "") if uid else ""
        rows = (db.query(AutomationVersion)
                  .filter(AutomationVersion.automation_id == automation_id)
                  .order_by(AutomationVersion.version.desc()).all())
        return {"versions": [{
            "id": v.id, "version": v.version, "summary": v.summary or "",
            "sentence": v.sentence or "", "snapshot": v.snapshot or {},
            "changed_by": v.changed_by, "changed_by_name": uname(v.changed_by),
            "changed_at": v.changed_at.isoformat() if v.changed_at else None,
        } for v in rows]}


@app.patch("/api/automations/{automation_id}")
def update_automation(automation_id: int, data: dict, user_id: int = Depends(current_user_id)):
    """Switch a rule on/off, change what it was built with, or hand it over.

    Two speeds on purpose. Metadata — the name, the description, the importance,
    the running order, the owner — applies at once: none of it changes what the
    rule does, and holding a rename for a publish would be absurd. The rule's own
    configuration does not: while the rule is ACTIVE an edit is written as a
    draft version and the live rule goes on running until someone publishes it.
    """
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == a.board_id).first()
        if not b or not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול לשנות אוטומציות")
        before = _snapshot_automation(a)
        if "is_active" in data or "status" in data:
            want = _automation_status_from(data, a.status or "active")
            # a draft may be half-built; switching it on may not be
            if want == "active" and a.status != "active":
                _refuse_incomplete_activation(db, b, a)
            _set_automation_status(a, want)
        _prev_owner = a.owner_id
        for k, v in _automation_meta(db, a.board_id, data).items():
            setattr(a, k, v)
        if "owner_id" in data and a.owner_id != _prev_owner:
            _audit_owner_change(db, a, _prev_owner, a.owner_id, user_id)
        if "config" in data:
            live = (a.status == "active") and not data.get("publish")
            cfg, err = (recipes.validate_partial if (a.status == "draft" or live)
                        else recipes.validate)(a.recipe_id, data.get("config") or {})
            if err:
                raise HTTPException(400, err)
            _check_automation_person(db, a.board_id, cfg)
            _check_automation_reach(db, a.board_id, a.recipe_id, cfg, user_id)
            if live:
                snap = _snapshot_automation(a)
                snap["config"] = cfg
                _record_automation_version(db, b, a, user_id, before=before, draft=snap)
                a.updated_by = user_id
                a.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
                db.refresh(a)
                return _automation_json(db, b, a)
            a.config = cfg
        a.updated_by = user_id
        a.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        _record_automation_version(db, b, a, user_id, before=before)
        db.commit()
        db.refresh(a)
        return _automation_json(db, b, a)


@app.delete("/api/automations/{automation_id}")
def delete_automation(automation_id: int, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == a.board_id).first()
        if not b or not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול למחוק אוטומציות")
        # the rule goes; what it did stays. Each history row already carries the
        # sentence and the item title, so it still reads without the rule behind it
        (db.query(AutomationRun).filter(AutomationRun.automation_id == a.id)
           .update({AutomationRun.automation_id: None}, synchronize_session=False))
        db.delete(a)
        db.commit()
        return {"status": "deleted", "id": automation_id}


# ── Run history (היסטוריית הפעלות) ───────────────────────────────────
RUN_OUTCOMES = ("ran", "skipped", "failed")


def _can_see_run_item(db, row, user_id):
    """May this reader see the item this run acted on?

    A run row carries the item's title and the values the rule filled in — a
    person's name, a linked item's name — and an item can be restricted to
    particular people even inside a board someone may read. The history is not a
    way around that, and neither is the export.
    """
    if user_id is None or not row.task_id:
        return True
    try:
        _require_task_view(db, row.task_id, user_id)
        return True
    except HTTPException:
        return False


def _redact_run(row_json):
    """The same row with what the reader may not see taken out, and said so."""
    row_json = dict(row_json)
    row_json["task_title"] = "פריט שאין לך הרשאה אליו"
    row_json["sentence"] = "—"
    row_json["reason"] = ""
    row_json["task_id"] = None
    row_json["redacted"] = True
    row_json["can_retry"] = False
    return row_json


def _automation_run_json(db, row):
    uname = lambda uid: (db.query(User.name).filter(User.id == uid).scalar() or "") if uid else ""
    return {
        "id": row.id, "automation_id": row.automation_id, "recipe_id": row.recipe_id,
        "sentence": row.sentence or "",
        "trigger": row.trigger_key or "", "action": row.action_key or "",
        "task_id": row.task_id, "task_title": row.task_title or "",
        "outcome": row.outcome or "ran", "reason": row.reason or "",
        "depth": row.depth or 0, "event_type": (row.event or {}).get("type") or "",
        "actor_id": row.actor_id, "actor_name": uname(row.actor_id),
        "is_retry": row.retry_of is not None, "retry_of": row.retry_of,
        "retried_at": row.retried_at.isoformat() if row.retried_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        # which version of the rule carried this out
        "version": row.version,
        "is_test": bool(row.is_test),
        # a rule that is gone, or an item that is gone, cannot be run again — and
        # a test was rolled back on purpose, so "try again" would do it for real
        "can_retry": (row.outcome in ("skipped", "failed")) and row.automation_id is not None
                     and not row.is_test,
    }


@app.get("/api/boards/{board_id}/automations/runs")
def list_automation_runs(board_id: int, outcome: str = "", automation_id: int = 0,
                         limit: int = 150, user_id: int = Depends(current_user_id)):
    """Every attempt the board's rules made, newest first.

    Filterable by outcome, because the three questions are different ones: what
    ran, what was skipped and why, and what failed. `counts` is always over the
    whole board, so switching filters never changes the totals above them.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if not _can_view_automations(db, b, user_id):
            raise HTTPException(403, "אין לך הרשאה לצפות בהיסטוריית ההפעלות")
        q = db.query(AutomationRun).filter(AutomationRun.board_id == board_id)
        if outcome in RUN_OUTCOMES:
            q = q.filter(AutomationRun.outcome == outcome)
        elif outcome == "retried":
            q = q.filter(AutomationRun.retry_of != None)                   # noqa: E711
        if automation_id:
            q = q.filter(AutomationRun.automation_id == automation_id)
        rows = q.order_by(AutomationRun.id.desc()).limit(max(1, min(limit, 500))).all()
        # an item-level restriction holds in the history too — see _redact_run
        seen = {}
        for r in rows:
            if r.task_id not in seen:
                seen[r.task_id] = _can_see_run_item(db, r, user_id)
        base = db.query(AutomationRun).filter(AutomationRun.board_id == board_id)
        counts = {k: base.filter(AutomationRun.outcome == k).count() for k in RUN_OUTCOMES}
        counts["retried"] = base.filter(AutomationRun.retry_of != None).count()   # noqa: E711
        counts["total"] = sum(counts[k] for k in RUN_OUTCOMES)
        return {"runs": [_automation_run_json(db, r) if seen.get(r.task_id, True)
                         else _redact_run(_automation_run_json(db, r))
                         for r in rows], "counts": counts,
                "can_manage": _can_manage_automations(db, b, user_id),
                "can_export": _can_export_automations(db, b, user_id)}


@app.post("/api/automation-runs/{run_id}/retry")
def retry_automation_run(run_id: int, user_id: int = Depends(current_user_id)):
    """Run the rule again against the same item, replaying the same trigger.

    Only a run that did not do anything — skipped or failed — can be retried;
    replaying a run that already worked would apply its action a second time.
    The retry is its own history row pointing back at the one it replayed, so
    the record shows both attempts rather than overwriting the first.
    """
    with Session(engine) as db:
        row = db.query(AutomationRun).filter(AutomationRun.id == run_id).first()
        if not row:
            raise HTTPException(404, "run not found")
        b = db.query(Board).filter(Board.id == row.board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול להפעיל אוטומציה שוב")
        if row.is_test:
            raise HTTPException(400, "בדיקה אינה מופעלת שוב — הריצו בדיקה חדשה")
        if row.outcome not in ("skipped", "failed"):
            raise HTTPException(400, "אפשר להפעיל שוב רק הפעלה שדילגה או נכשלה")
        a = (db.query(Automation).filter(Automation.id == row.automation_id).first()
             if row.automation_id else None)
        if not a:
            raise HTTPException(400, "האוטומציה נמחקה — אין מה להפעיל שוב")
        task = db.query(Task).filter(Task.id == row.task_id).first()
        if not task or task.deleted_at:
            raise HTTPException(400, "הפריט אינו קיים עוד")
        event = row.event or {"type": (recipes.recipe(a.recipe_id) or {}).get("trigger")}
        made = _fire_rule(db, a, task, event, user_id, 0, retry_of=row.id)
        row.retried_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        if not made:
            raise HTTPException(400, "ההפעלה החוזרת לא נרשמה")
        db.refresh(made)
        return {"run": _automation_run_json(db, made)}


@app.get("/api/boards/{board_id}/automations/runs/export")
def export_automation_runs(board_id: int, outcome: str = "", automation_id: int = 0,
                           user_id: int = Depends(current_user_id)):
    """The run history as a .csv — the same filters the screen uses."""
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if not _can_export_automations(db, b, user_id):
            raise HTTPException(403, "ייצוא לוג ההפעלות דורש הרשאת נתונים")
        q = db.query(AutomationRun).filter(AutomationRun.board_id == board_id)
        if outcome in RUN_OUTCOMES:
            q = q.filter(AutomationRun.outcome == outcome)
        elif outcome == "retried":
            q = q.filter(AutomationRun.retry_of != None)                   # noqa: E711
        if automation_id:
            q = q.filter(AutomationRun.automation_id == automation_id)
        rows = q.order_by(AutomationRun.id.desc()).limit(20000).all()
        uname = lambda uid: (db.query(User.name).filter(User.id == uid).scalar() or "") if uid else ""
        # the export is a file that leaves the system, so the same restriction
        # holds here — more so, not less
        seen = {}
        for r in rows:
            if r.task_id not in seen:
                seen[r.task_id] = _can_see_run_item(db, r, user_id)
        _OUT_HE = {"ran": "הופעלה", "skipped": "דילוג", "failed": "כשל"}
        buf = io.StringIO()
        buf.write("﻿")
        w = csv.writer(buf)
        w.writerow(["מועד", "תוצאה", "האוטומציה", "גרסה", "הפריט", "הסיבה",
                    "גורם מפעיל", "פעולה", "עומק", "ניסיון חוזר", "מי הפעיל"])
        for r in rows:
            ok = seen.get(r.task_id, True)
            w.writerow([(r.created_at.isoformat() if r.created_at else "")[:19].replace("T", " "),
                        _OUT_HE.get(r.outcome, r.outcome or ""),
                        (r.sentence or "").replace("«", "").replace("»", "") if ok else "—",
                        r.version or "",
                        (r.task_title or "") if ok else "פריט שאין לך הרשאה אליו",
                        (r.reason or "") if ok else "",
                        r.trigger_key or "", r.action_key or "", r.depth or 0,
                        "כן" if r.retry_of else "", uname(r.actor_id)])
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="automation-runs-{board_id}.csv"'})


@app.post("/api/automations/{automation_id}/restore/{version}")
def restore_automation_version(automation_id: int, version: int,
                               user_id: int = Depends(current_user_id)):
    """Offer an earlier version's configuration back — as a draft.

    The rule as it stands goes on running, and putting the old wording into
    force is a separate, deliberate act that gets checked like any activation.
    What comes back is the rule's own configuration, never its counters or its
    history: those are a record of what happened, not part of the settings.
    """
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == a.board_id).first()
        if not b or not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול לשחזר גרסה")
        if not _can_export_automations(db, b, user_id):
            raise HTTPException(403, "שחזור גרסה דורש הרשאת נתונים")
        v = (db.query(AutomationVersion)
               .filter(AutomationVersion.automation_id == automation_id,
                       AutomationVersion.version == version).first())
        if not v:
            raise HTTPException(404, "גרסה לא נמצאה")
        snap = v.snapshot if isinstance(v.snapshot, dict) else {}
        if snap.get("recipe_id") and snap["recipe_id"] != a.recipe_id:
            # the trigger-and-action pair is what the rule IS; a version that
            # changes it is a different rule wearing the same row
            raise HTTPException(400, "הגרסה בנויה על מתכון אחר ולא ניתן לשחזר אותה")
        before = _snapshot_automation(a)
        want = dict(before)
        for key in ("config", "name", "description", "importance", "run_order"):
            if key in snap:
                want[key] = snap[key]
        if snap.get("owner_id") and _can_be_assigned(db, a.board_id, snap["owner_id"]):
            want["owner_id"] = snap["owner_id"]
        # never the status: the state it was in three versions ago is not a
        # decision about now, and a rule that starts running again because its
        # wording was restored is the surprise this screen exists to prevent
        want["status"] = before["status"]
        a.updated_by = user_id
        a.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        _record_automation_version(db, b, a, user_id, before=before, draft=want,
                                   note=f"טיוטה משוחזרת מגרסה {version}")
        db.commit()
        db.refresh(a)
        return _automation_json(db, b, a)


# ── what a rule touches, and what a test finds out ──────────────────────
# Two questions asked at two moments. Before switching a rule on: what will this
# read, what will it write, who will hear about it, and what else is already
# writing the same things. And on one chosen item: would it fire, and what
# exactly would it do. Neither writes anything.
AUTOMATION_TEST_LOG_DAYS = 30

# What each action writes. Named here rather than inferred, because "which rules
# write the same field" is the question the conflict warning answers.
AUTOMATION_ACTION_WRITES = {
    "notify_person":    [],
    "notify_assignees": [],
    "assign_person":    ["אחראים"],
    "set_status":       ["סטטוס"],
    "set_priority":     ["עדיפות"],
    "move_to_group":    ["קבוצה"],
    "create_subitem":   ["תתי־פריטים"],
    "link_to_item":     ["קישור בין לוחות"],
    "create_and_link":  ["קישור בין לוחות"],
}
# What each trigger reads.
AUTOMATION_TRIGGER_READS = {
    "item_created":             ["הפריט עצמו"],
    "status_changes_to":        ["סטטוס"],
    "priority_changes_to":      ["עדיפות"],
    "person_assigned":          ["אחראים"],
    "due_date_arrives":         ["תאריך יעד"],
    "link_added":               ["קישור בין לוחות"],
    "link_removed":             ["קישור בין לוחות"],
    "linked_status_changes_to": ["סטטוס של פריט מקושר"],
}


def _automation_impact(db, board, a):
    """Everything the rule reaches, for the screen shown before it is switched on.

    A rule is a standing instruction that edits items by itself, and the moment
    to understand its reach is before it starts — not from the log afterwards.
    """
    r = recipes.recipe(a.recipe_id) or {}
    cfg = a.config or {}
    trig = r.get("trigger", "")
    # what the rule writes is what ALL of its actions write — the screen is
    # read as "what will this rule do to my board", and an answer naming only
    # the first of four is worse than no answer
    acts = recipes.action_list(a.recipe_id, cfg)
    boards = [{"id": board.id, "name": board.name, "mode": "read_write",
               "why": "הלוח שהאוטומציה יושבת בו"}]
    reads = list(AUTOMATION_TRIGGER_READS.get(trig, []))
    writes = [w for one in acts for w in AUTOMATION_ACTION_WRITES.get(one["key"], [])]
    links, recipients, missing = [], [], []

    for one in acts:
        for f in recipes.action_fields(one["key"]):
            v = one["values"].get(f["key"])
            if v in (None, "", []):
                continue
            if f["type"] == "person":
                u = db.query(User).filter(User.id == v).first()
                recipients.append({"name": u.name if u else str(v),
                                   "kind": "נמען מוגדר",
                                   "ok": _can_be_assigned(db, board.id, v)})
            elif f["type"] == "connect":
                col = _find_col(db, board.id, str(v))
                title = (col or {}).get("title") or str(v)
                targets = [int(x) for x in (_connect_cfg(col).get("board_ids") or [])
                           if str(x).lstrip("-").isdigit()] if col else []
                links.append({"kind": "connect", "column": title,
                              "two_way": bool(_is_two_way(col)) if col else False,
                              "boards": [{"id": t, "name": db.query(Board.name)
                                          .filter(Board.id == t).scalar() or str(t)}
                                         for t in targets]})
                for t in targets:
                    tb = db.query(Board).filter(Board.id == t).first()
                    if tb and not any(x["id"] == t for x in boards):
                        boards.append({"id": t, "name": tb.name, "mode": "write",
                                       "why": f"עמודת הקישור '{title}' מפנה אליו"})
                # a mirror column reading through this connect column moves with it
                for mc in (board.settings or {}).get("columns", []):
                    if mc.get("type") == "mirror" and (mc.get("mirror_of") or {}).get("col") == (col or {}).get("id"):
                        links.append({"kind": "mirror", "column": mc.get("title") or mc.get("id"),
                                      "through": title, "boards": []})
                        reads.append(f"עמודת מראה '{mc.get('title') or mc.get('id')}'")
            elif f["type"] == "board":
                tb = db.query(Board).filter(Board.id == v).first()
                if tb and not any(x["id"] == tb.id for x in boards):
                    boards.append({"id": tb.id, "name": tb.name, "mode": "write",
                                   "why": "האוטומציה יוצרת בו פריטים"})
            elif f["type"] == "item":
                t = db.query(Task).filter(Task.id == v).first()
                if t:
                    tb = db.query(Board).filter(Board.id == t.board_id).first()
                    if tb and not any(x["id"] == tb.id for x in boards):
                        boards.append({"id": tb.id, "name": tb.name, "mode": "write",
                                       "why": "האוטומציה מקשרת אל פריט בו"})
    if any(one["key"] == "notify_assignees" for one in acts):
        recipients.append({"name": "משויכי הפריט", "kind": "נמענים דינמיים", "ok": True})

    for b in _automation_blockers(db, board, a):
        if b["kind"] == "permission":
            missing.append(b["text"])

    # ── other rules that write the same fields ──
    others = []
    same = set(writes)
    if same:
        for o in (db.query(Automation)
                    .filter(Automation.board_id == board.id, Automation.id != a.id)
                    .order_by(Automation.run_order, Automation.id).all()):
            ow = {w for x in recipes.action_list(o.recipe_id, o.config or {})
                  for w in AUTOMATION_ACTION_WRITES.get(x["key"], [])}
            if not (ow & same):
                continue
            others.append({"id": o.id,
                           "name": o.name or _automation_label(db, board, o)
                                             .replace("«", "").replace("»", ""),
                           "status": o.status or ("active" if o.is_active else "paused"),
                           "run_order": o.run_order or 0,
                           "fields": sorted(ow & same),
                           # the one that runs first decides, and the other overwrites
                           "runs_before": (o.run_order or 0, o.id) < (a.run_order or 0, a.id)})
    return {"boards": boards, "reads": sorted(set(reads)), "writes": sorted(set(writes)),
            "links": links, "recipients": recipients, "missing_permissions": missing,
            "others": others,
            "loop_risk": _automation_loop_risk(db, board, a)}


def _automation_loop_risk(db, board, a):
    """Rules whose trigger is the very thing this rule's action produces.

    Not a proof of a loop — two rules can feed each other harmlessly — but it is
    the shape a loop has, and it is worth seeing before switching one on rather
    than from the depth-ceiling skips afterwards.
    """
    r = recipes.recipe(a.recipe_id) or {}
    PRODUCES = {"set_status": "status_changes_to", "set_priority": "priority_changes_to",
                "assign_person": "person_assigned", "link_to_item": "link_added",
                "create_and_link": "link_added"}
    # every action the rule carries, because any one of them is enough to start
    # the rule on the other side
    produces = {PRODUCES[x["key"]] for x in recipes.action_list(a.recipe_id, a.config or {})
                if x["key"] in PRODUCES}
    if not produces:
        return []
    out = []
    for o in db.query(Automation).filter(Automation.board_id == board.id,
                                         Automation.id != a.id).all():
        ro = recipes.recipe(o.recipe_id) or {}
        if ro.get("trigger") not in produces:
            continue
        # and does IT produce what this one listens for? then it is a cycle
        back = {PRODUCES.get(x["key"]) for x in recipes.action_list(o.recipe_id, o.config or {})}
        out.append({"id": o.id,
                    "name": o.name or _automation_label(db, board, o)
                                      .replace("«", "").replace("»", ""),
                    "status": o.status or ("active" if o.is_active else "paused"),
                    "cycle": r.get("trigger") in back})
    return out


@app.get("/api/automations/{automation_id}/impact")
def automation_impact(automation_id: int, user_id: int = Depends(current_user_id)):
    """What this rule reads, writes, notifies and collides with — shown before
    it is switched on, and before a waiting draft is published."""
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == a.board_id).first()
        if not b or not _can_view_automations(db, b, user_id):
            raise HTTPException(403, "אין לך הרשאה לצפות באוטומציה")
        return {"automation_id": a.id, "sentence": _automation_label(db, b, a),
                "status": a.status, "missing_fields": recipes.missing_fields(a.recipe_id, a.config or {}),
                **_automation_impact(db, b, a)}


def _condition_actual(db, board, task, kind, v=None):
    """What the item shows for the thing a condition asks about."""
    spec = recipes.condition(kind) or {}
    t = spec.get("type")
    if t == "column":
        return _column_cell_text(db, board, task, v or {})
    if t == "status":
        return _condition_value_label(db, board, kind, _task_status_key(task))
    if t == "priority":
        return _condition_value_label(db, board, kind, _task_priority_key(task))
    if t == "person":
        names = [u.name for u in list(task.assignees or [])]
        return ", ".join(names) if names else "אין משויכים"
    if t == "group":
        return db.query(Group.name).filter(Group.id == task.group_id).scalar() or "—"
    if kind in ("has_assignee", "no_assignee"):
        return "יש משויכים" if list(task.assignees or []) else "אין משויכים"
    if kind in ("has_due_date", "no_due_date", "overdue", "not_overdue"):
        return task.due_date.strftime("%d/%m/%Y") if task.due_date else "אין תאריך יעד"
    return "—"


def _column_cell_text(db, board, task, spec):
    """What the cell a column condition asks about actually holds, in words —
    the other half of a test that says which condition held it up."""
    col = _find_col(db, board.id, str(spec.get("col") or "")) if board else None
    if not col:
        return "העמודה אינה קיימת בלוח"
    kind = recipes.column_kind(col.get("type"))
    raw = (task.custom_fields or {}).get(str(spec.get("col")))
    if kind == "check":
        return "מסומן" if (len(raw) if isinstance(raw, list) else raw) else "לא מסומן"
    vals = raw if isinstance(raw, list) else [raw]
    out = []
    for x in vals:
        if x in (None, ""):
            continue
        if kind == "people":
            try:
                out.append(db.query(User.name).filter(User.id == int(
                    x.get("id") if isinstance(x, dict) else x)).scalar() or str(x))
            except (TypeError, ValueError):
                out.append(str(x))
        elif isinstance(x, dict):
            out.append(str(x.get("label") or x.get("from") or x.get("value") or ""))
        elif kind == "date":
            out.append(_fmt_day(str(x)[:10]))
        else:
            out.append(str(x))
    return ", ".join([o for o in out if o]) or "ריק"


def _dry_run_automation(db, board, a, task):
    """Work out what the rule WOULD do to this item. Nothing is written.

    Deliberately an analysis and not an execution-and-rollback. A rollback still
    creates rows and notifications for the length of a transaction, and it can
    only ever report the one outcome the engine reached — where what a person
    testing a rule needs is each condition separately, the values the actions
    would write, and what is in the way.
    """
    r = recipes.recipe(a.recipe_id) or {}
    cfg = a.config or {}
    trig = r.get("trigger", "")
    label = lambda key, v: _automation_value_label(db, board, r, key, v)

    # ── the trigger ──
    cur_status, cur_prio = _task_status_key(task), _task_priority_key(task)
    trigger = {"key": trig, "label": recipes.plain(recipes.TRIGGERS.get(trig, trig)),
               "matches": True, "note": ""}
    if trig == "item_created":
        trigger["note"] = "מתקיים בכל יצירת פריט"
    elif trig == "due_date_arrives":
        trigger["matches"] = bool(task.due_date)
        trigger["note"] = ("תאריך היעד " + task.due_date.strftime("%d/%m/%Y")) if task.due_date \
            else "לפריט אין תאריך יעד"
    elif trig == "status_changes_to":
        trigger["matches"] = str(cfg.get("t_status")) == str(cur_status)
        trigger["note"] = f"הסטטוס בפריט: {label('t_status', cur_status)}"
    elif trig == "priority_changes_to":
        trigger["matches"] = str(cfg.get("t_priority")) == str(cur_prio)
        trigger["note"] = f"העדיפות בפריט: {label('t_priority', cur_prio)}"
    elif trig == "person_assigned":
        trigger["matches"] = bool(list(task.assignees))
        trigger["note"] = "לפריט משויכים" if list(task.assignees) else "לפריט אין משויכים"
    elif trig in ("link_added", "link_removed", "linked_status_changes_to"):
        trigger["note"] = "נבדק מול האירוע בפועל; בבדיקה מונח שהאירוע התרחש"

    # ── each condition on its own ──
    conditions = []
    for f in r.get("fields", []):
        if not f["key"].startswith("t_"):
            continue
        want = cfg.get(f["key"])
        have = cur_status if f["type"] == "status" else cur_prio
        conditions.append({"label": f["label"], "expected": label(f["key"], want),
                           "actual": label(f["key"], have), "ok": str(want) == str(have)})
    # the rule's own "רק אם" conditions, each answered separately — a test that
    # reported only a verdict would leave the asker to guess which one held it
    for c in (cfg.get(recipes.CONDITION_KEY) or []):
        spec = recipes.condition(c.get("kind")) or {}
        held = _condition_holds(db, task, c.get("kind"), c.get("value"))
        conditions.append({
            "label": (_condition_phrases(db, board, [c], quote=False) or [""])[0],
            "expected": _condition_value_label(db, board, c.get("kind"), c.get("value"))
                        if spec.get("type") else "—",
            "actual": _condition_actual(db, board, task, c.get("kind"), c.get("value")),
            "ok": held})

    # ── what it would do, with the values — every action, in run order ──
    actions = []
    for one in recipes.action_list(a.recipe_id, cfg):
        row = _test_action_row(db, board, task, one["key"], one["values"],
                               cur_status, cur_prio)
        if row:
            actions.append(dict(row, order=one["index"] + 1))

    blockers = _automation_blockers(db, board, a)
    missing = [b["text"] for b in blockers if b["kind"] == "permission"]
    broken = [b["text"] for b in blockers if b["kind"] == "dependency"]
    impact = _automation_impact(db, board, a)
    # a condition that does not hold stops the rule exactly as a trigger that
    # does not match does, so the test may not answer "would run" over one
    unmet = [c for c in conditions if not c.get("ok")]
    fires = trigger["matches"] and not unmet
    would = (fires and not blockers
             and not all(x.get("no_op") for x in actions or [{}]))
    verdict = "blocked" if blockers else ("would_run" if (fires and not
                                          all(x.get("no_op") for x in actions or [{}]))
                                          else "would_skip")
    if verdict == "would_run":
        summary = "הכלל היה מתבצע"
    elif verdict == "blocked":
        summary = "הכלל חסום: " + " · ".join((missing + broken)[:2])
    elif not trigger["matches"]:
        summary = "הגורם המפעיל אינו מתקיים על הפריט הזה"
    elif unmet:
        summary = "התנאי אינו מתקיים על הפריט: " + unmet[0]["label"]
    else:
        summary = "הכלל היה מתאים אך לא משנה דבר"
    return {"verdict": verdict, "summary": summary, "trigger": trigger,
            "conditions": conditions, "actions": actions,
            "missing_permissions": missing, "broken_dependencies": broken,
            "conflicts": impact["others"], "loop_risk": impact["loop_risk"],
            "notified": [x for x in impact["recipients"]]}


def _test_action_row(db, board, task, key, values, cur_status, cur_prio):
    """One action as the test screen shows it: what it would write, what is
    there now, and whether it would do nothing.

    Per action rather than per rule, because a rule carries up to
    recipes.MAX_ACTIONS of them and a test that described only the first would
    be answering about a different rule than the one being tested. `values` are
    the action's own, keyed by the bare field name (automations.action_list).
    """
    shown = lambda t, v: "—" if v in (None, "", []) else _shown_value(db, board, t, v)
    if key == "set_status":
        same = str(values.get("status")) == str(cur_status)
        return {"what": "שינוי סטטוס", "to": shown("status", values.get("status")),
                "from": shown("status", cur_status), "no_op": same,
                "note": "הפריט נמצא בסטטוס הזה כבר" if same else ""}
    if key == "set_priority":
        same = str(values.get("priority")) == str(cur_prio)
        return {"what": "שינוי עדיפות", "to": shown("priority", values.get("priority")),
                "from": shown("priority", cur_prio), "no_op": same,
                "note": "לפריט יש את העדיפות הזו כבר" if same else ""}
    if key == "assign_person":
        u = db.query(User).filter(User.id == values.get("person")).first()
        already = bool(u and u in list(task.assignees))
        return {"what": "שיוך אדם", "to": u.name if u else "—", "from": "",
                "no_op": already, "note": "האדם משויך לפריט כבר" if already else ""}
    if key == "move_to_group":
        g = db.query(Group).filter(Group.id == values.get("group")).first()
        same = bool(g and task.group_id == g.id)
        return {"what": "העברה לקבוצה", "to": g.name if g else "—",
                "from": db.query(Group.name).filter(Group.id == task.group_id).scalar() or "",
                "no_op": same, "note": "הפריט בקבוצה הזו כבר" if same else ""}
    if key == "create_subitem":
        return {"what": "יצירת תת־פריט", "to": values.get("text") or "", "from": "",
                "no_op": False, "note": ""}
    if key in ("notify_person", "notify_assignees"):
        if key == "notify_person":
            u = db.query(User).filter(User.id == values.get("person")).first()
            who = u.name if u else "—"
            no_op = not _can_be_assigned(db, board.id, values.get("person"))
            note = "הנמען אינו חבר בלוח — לא תישלח התראה" if no_op else ""
        else:
            people = [u.name for u in list(task.assignees)]
            who = ", ".join(people) if people else "—"
            no_op = not people
            note = "לפריט אין משויכים" if no_op else ""
        return {"what": "שליחת התראה", "to": who, "from": "", "no_op": no_op,
                "note": note + (" · בבדיקה לא נשלחת התראה" if not no_op else "")}
    if key in ("link_to_item", "create_and_link"):
        return {"what": "קישור בין לוחות",
                "to": shown("item", values.get("item")) if key == "link_to_item"
                      else (values.get("text") or ""),
                "from": "", "no_op": False,
                "note": f"בעמודה {shown('connect', values.get('connect'))}"}
    return None


def _automation_value_label(db, board, r, key, v):
    """A value as the board shows it — a status's label, a person's name."""
    t = next((f["type"] for f in r.get("fields", []) if f["key"] == key), None)
    if v in (None, "", []):
        return "—"
    if t == "status" or key in ("t_status", "a_status"):
        e = next((x for x in _board_statuses(board) if x["key"] == str(v)), None)
        return e["label"] if e else str(v)
    if t == "priority" or key in ("t_priority", "a_priority"):
        e = next((x for x in _board_priorities(board) if x["key"] == str(v)), None)
        return e["label"] if e else str(v)
    if t == "person":
        return db.query(User.name).filter(User.id == v).scalar() or str(v)
    if t == "group":
        return db.query(Group.name).filter(Group.id == v).scalar() or str(v)
    if t == "item":
        return db.query(Task.title).filter(Task.id == v).scalar() or str(v)
    if t == "board":
        return db.query(Board.name).filter(Board.id == v).scalar() or str(v)
    if t == "connect":
        col = _find_col(db, board.id, str(v))
        return (col or {}).get("title") or str(v)
    return str(v)


def _prune_test_runs(db):
    """A test is a working note. After AUTOMATION_TEST_LOG_DAYS it goes."""
    cut = (datetime.now(timezone.utc).replace(tzinfo=None)
           - timedelta(days=AUTOMATION_TEST_LOG_DAYS))
    db.query(AutomationTestRun).filter(AutomationTestRun.created_at < cut)\
      .delete(synchronize_session=False)


@app.get("/api/boards/{board_id}/automations/tests")
def list_automation_tests(board_id: int, automation_id: int = 0, limit: int = 50,
                          user_id: int = Depends(current_user_id)):
    """The test log — separate from the run history, and only the last 30 days."""
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if not _can_view_automations(db, b, user_id):
            raise HTTPException(403, "אין לך הרשאה לצפות בבדיקות")
        _prune_test_runs(db)
        db.commit()
        q = db.query(AutomationTestRun).filter(AutomationTestRun.board_id == board_id)
        if automation_id:
            q = q.filter(AutomationTestRun.automation_id == automation_id)
        rows = q.order_by(AutomationTestRun.id.desc()).limit(max(1, min(limit, 200))).all()
        uname = lambda uid: (db.query(User.name).filter(User.id == uid).scalar() or "") if uid else ""
        return {"tests": [{"id": t.id, "automation_id": t.automation_id,
                           "task_id": t.task_id, "task_title": t.task_title or "",
                           "sentence": t.sentence or "", "version": t.version,
                           "verdict": t.verdict, "summary": t.summary or "",
                           "details": t.details or {},
                           "tested_by": t.tested_by, "tested_by_name": uname(t.tested_by),
                           "created_at": t.created_at.isoformat() if t.created_at else None}
                          for t in rows],
                "retention_days": AUTOMATION_TEST_LOG_DAYS}


@app.post("/api/automations/{automation_id}/publish")
def publish_automation_draft(automation_id: int, data: dict = None,
                             user_id: int = Depends(current_user_id)):
    """Put the waiting draft into force — the explicit activation rule 3 asks for.

    Until this is called the live rule has gone on running unchanged, which is
    the whole point: an edit made at eleven does not change what the board does
    at eleven-oh-one. The draft is checked the way an activation is checked, so
    publishing cannot put a rule into service that will skip every time.
    """
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == a.board_id).first()
        if not b or not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול להפעיל גרסה")
        v = (db.query(AutomationVersion)
               .filter(AutomationVersion.automation_id == automation_id,
                       AutomationVersion.version == (a.draft_version or 0),
                       AutomationVersion.is_draft == True).first())            # noqa: E712
        if not v:
            raise HTTPException(400, "אין טיוטת גרסה שממתינה להפעלה")
        snap = v.snapshot if isinstance(v.snapshot, dict) else {}
        if snap.get("recipe_id") and snap["recipe_id"] != a.recipe_id:
            raise HTTPException(400, "הטיוטה בנויה על מתכון אחר")
        cfg, err = recipes.validate(a.recipe_id, snap.get("config") or a.config or {})
        if err:
            raise HTTPException(400, f"לא ניתן להפעיל את הטיוטה: {err}")
        _check_automation_person(db, a.board_id, cfg)
        _check_automation_reach(db, a.board_id, a.recipe_id, cfg, user_id)
        before = _snapshot_automation(a)
        a.config = cfg
        for key in ("name", "description", "importance", "run_order"):
            if key in snap:
                setattr(a, key, snap[key])
        _refuse_incomplete_activation(db, b, a)
        v.is_draft = False
        v.published_at = datetime.now(timezone.utc).replace(tzinfo=None)
        a.draft_version = None
        a.updated_by = user_id
        a.updated_at = v.published_at
        # the rule was already active — publishing changes what it does, and the
        # clock on "events from the activation onwards" starts again here
        if a.status == "active":
            a.activated_at = v.published_at
        _record_automation_version(db, b, a, user_id, before=before,
                                   note=f"גרסה {v.version} הופעלה")
        db.commit()
        db.refresh(a)
        return _automation_json(db, b, a)


@app.post("/api/automations/{automation_id}/discard-draft")
def discard_automation_draft(automation_id: int, user_id: int = Depends(current_user_id)):
    """Throw the waiting edit away. The live rule never moved, so there is
    nothing to undo — the draft version stays in the history, marked as one."""
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == a.board_id).first()
        if not b or not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול לבטל טיוטה")
        if not a.draft_version:
            raise HTTPException(400, "אין טיוטה לבטל")
        a.draft_version = None
        a.updated_by = user_id
        a.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(a)
        return _automation_json(db, b, a)


# What a comparison groups changes into. The spec asks for exactly these five,
# and they are the five a reader is deciding between: what sets the rule off,
# what narrows it, what it does, who it acts as, and when it goes.
_VERSION_GROUPS = [
    ("trigger", "גורם מפעיל", lambda k, f: k == "recipe_id"),
    ("conditions", "תנאים", lambda k, f: k.startswith("t_") or k == recipes.CONDITION_KEY),
    ("actions", "פעולות", lambda k, f: (k.startswith("a_") and f != "person")
                                       or k == recipes.ACTIONS_KEY),
    ("permissions", "הרשאות", lambda k, f: k == "owner_id" or (k.startswith("a_") and f == "person")),
    ("order", "סדר", lambda k, f: k in ("run_order", "importance")),
]


@app.get("/api/automations/{automation_id}/versions/compare")
def compare_automation_versions(automation_id: int, a: int = 0, b: int = 0,
                                user_id: int = Depends(current_user_id)):
    """What changed between two versions, grouped the way the spec asks.

    Values are rendered as the board shows them — a status label, a person's
    name — because "from 3 to 7" is not a comparison anyone can act on when 3
    and 7 are user ids.
    """
    with Session(engine) as db:
        auto = db.query(Automation).filter(Automation.id == automation_id).first()
        if not auto:
            raise HTTPException(404, "automation not found")
        board = db.query(Board).filter(Board.id == auto.board_id).first()
        if not board or not _can_view_automations(db, board, user_id):
            raise HTTPException(403, "אין לך הרשאה לצפות בגרסאות האוטומציה")
        rows = {v.version: v for v in db.query(AutomationVersion)
                .filter(AutomationVersion.automation_id == automation_id).all()}
        if not rows:
            raise HTTPException(404, "אין גרסאות להשוואה")
        newest = max(rows)
        va, vb = rows.get(a or (newest - 1 if newest > 1 else newest)), rows.get(b or newest)
        if not va or not vb:
            raise HTTPException(404, "גרסה לא נמצאה")
        r = recipes.recipe(auto.recipe_id) or {}
        ftype = {f["key"]: f["type"] for f in r.get("fields", [])}
        labels = {f["key"]: f["label"] for f in r.get("fields", [])}

        def shown(key, value):
            t = ftype.get(key)
            if value in (None, "", []):
                return "—"
            if key == recipes.CONDITION_KEY:
                # a list of {kind,value} is unreadable as a diff; the clause is not
                return " וגם ".join(_condition_phrases(db, board, value, quote=False)) or "—"
            if key == recipes.ACTIONS_KEY:
                # same reasoning for the extra actions: the stored list is JSON,
                # and what changed has to be readable as the sentence it is
                return " וגם ".join(_action_phrases(db, board, value, quote=False)) or "—"
            if t == "person" or key == "owner_id":
                return db.query(User.name).filter(User.id == value).scalar() or str(value)
            if t == "status":
                e = next((x for x in _board_statuses(board) if x["key"] == str(value)), None)
                return e["label"] if e else str(value)
            if t == "priority":
                e = next((x for x in _board_priorities(board) if x["key"] == str(value)), None)
                return e["label"] if e else str(value)
            if t == "group":
                return db.query(Group.name).filter(Group.id == value).scalar() or str(value)
            if t == "board":
                return db.query(Board.name).filter(Board.id == value).scalar() or str(value)
            if t == "item":
                return db.query(Task.title).filter(Task.id == value).scalar() or str(value)
            if t == "connect":
                col = _find_col(db, auto.board_id, str(value))
                return (col or {}).get("title") or str(value)
            if key == "importance":
                return {"critical": "קריטית", "high": "גבוהה",
                        "normal": "רגילה", "low": "נמוכה"}.get(value, str(value))
            return str(value)

        sa, sb = (va.snapshot or {}), (vb.snapshot or {})
        # config is compared key by key, everything else field by field
        flat = lambda snap: {**{k: v for k, v in snap.items() if k != "config"},
                             **(snap.get("config") or {})}
        fa, fb = flat(sa), flat(sb)
        groups = []
        for gid, ghe, belongs in _VERSION_GROUPS:
            items = []
            for key in sorted(set(fa) | set(fb)):
                if not belongs(key, ftype.get(key)):
                    continue
                if fa.get(key) == fb.get(key):
                    continue
                items.append({"key": key,
                              "label": ("תנאים נוספים" if key == recipes.CONDITION_KEY
                                        else "פעולות נוספות" if key == recipes.ACTIONS_KEY
                                        else labels.get(key) or _VERSIONED.get(key) or key),
                              "from": shown(key, fa.get(key)), "to": shown(key, fb.get(key))})
            if items:
                groups.append({"id": gid, "label": ghe, "changes": items})
        # anything the five groups do not claim — the name, the description
        rest = [{"key": k, "label": _VERSIONED.get(k, k),
                 "from": shown(k, fa.get(k)), "to": shown(k, fb.get(k))}
                for k in sorted(set(fa) | set(fb))
                if fa.get(k) != fb.get(k)
                and not any(belongs(k, ftype.get(k)) for _, _, belongs in _VERSION_GROUPS)]
        if rest:
            groups.append({"id": "other", "label": "פרטים", "changes": rest})
        return {"a": {"version": va.version, "is_draft": bool(va.is_draft),
                      "changed_at": va.changed_at.isoformat() if va.changed_at else None,
                      "sentence": va.sentence or ""},
                "b": {"version": vb.version, "is_draft": bool(vb.is_draft),
                      "changed_at": vb.changed_at.isoformat() if vb.changed_at else None,
                      "sentence": vb.sentence or ""},
                "groups": groups, "identical": not groups}


@app.post("/api/automations/{automation_id}/test")
def test_automation(automation_id: int, data: dict, user_id: int = Depends(current_user_id)):
    """A Dry Run on one item: would it fire, and what exactly would it do.

    Nothing is written and nothing is sent. This used to run the rule for real
    inside a transaction and roll it back, which did answer "what happened" —
    but it created rows and notifications for the length of that transaction,
    and it could only ever report the single outcome the engine reached. What a
    person testing a rule needs is each condition on its own, the values the
    actions would write, the permissions in the way, and whether anything else
    is writing the same fields. So it is worked out rather than performed.

    The result goes to a log of its own, kept AUTOMATION_TEST_LOG_DAYS days — a
    test is not something the board did, and mixing the two makes the run
    history unreadable exactly when someone is trying to see what really did.
    """
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == a.board_id).first()
        if not b or b.deleted_at or not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול להריץ בדיקה")
        task = db.query(Task).filter(Task.id == data.get("task_id"),
                                     Task.board_id == a.board_id).first()
        if not task or task.deleted_at:
            raise HTTPException(400, "יש לבחור פריט מהלוח הזה")
        found = _dry_run_automation(db, b, a, task)
        row = AutomationTestRun(
            automation_id=a.id, board_id=a.board_id, task_id=task.id,
            task_title=(task.title or "")[:300],
            sentence=_automation_label(db, b, a), version=_live_version(db, a),
            verdict=found["verdict"], summary=found["summary"][:400], details=found,
            tested_by=user_id,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(row)
        _prune_test_runs(db)
        db.commit()
        db.refresh(row)
        return {"test_id": row.id, "task_title": row.task_title,
                "retention_days": AUTOMATION_TEST_LOG_DAYS,
                "changed_nothing": True, "notified_nobody": True, **found}


@app.post("/api/automations/{automation_id}/run")
def run_automation_now(automation_id: int, data: dict, user_id: int = Depends(current_user_id)):
    """Run a rule against one item for real — "הפעלה ידנית".

    The sibling of the test above, and deliberately a separate endpoint rather
    than a flag on it: one of the two keeps what it did and the other throws it
    away, and that is not a difference to hide in a parameter. It runs even on a
    paused rule — checking a rule by hand before switching it on is the point —
    but never while an emergency stop is holding, which is the point of that.
    """
    with Session(engine) as db:
        a = db.query(Automation).filter(Automation.id == automation_id).first()
        if not a:
            raise HTTPException(404, "automation not found")
        b = db.query(Board).filter(Board.id == a.board_id).first()
        if not b or b.deleted_at or not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול להפעיל אוטומציה ידנית")
        if _automation_freeze(db, a.board_id) is not None:
            raise HTTPException(400, "האוטומציות בלוח מושהות בהשהיית חירום")
        task = db.query(Task).filter(Task.id == data.get("task_id"),
                                     Task.board_id == a.board_id).first()
        if not task or task.deleted_at:
            raise HTTPException(400, "יש לבחור פריט מהלוח הזה")
        trig = (recipes.recipe(a.recipe_id) or {}).get("trigger") or ""
        row = _fire_rule(db, a, task, {"type": trig, "manual": True}, user_id, 0)
        db.commit()
        if not row:
            raise HTTPException(400, "ההפעלה לא נרשמה")
        db.refresh(row)
        return {"run": _automation_run_json(db, row)}


def _check_automation_reach(db, board_id, recipe_id, cfg, actor_id):
    """A rule that writes on ANOTHER board needs its author authorised there.

    A connect recipe can create and link items on a second board. Saved by
    someone with rights only here, it would be a way to write onto a board they
    were never given — with the rule, not their own hands, doing the writing.
    So every board the rule can reach is checked against the author, at the bar
    that writing an item takes: admin or editor there.
    """
    if actor_id is None or _ws_role(db, actor_id) == "admin":
        return                                     # a system admin reaches every board
    r = recipes.recipe(recipe_id) or {}
    targets = set()
    for f in r.get("fields", []):
        v = (cfg or {}).get(f["key"])
        if f["type"] == "board" and v:
            targets.add(int(v))
        elif f["type"] == "item" and v:
            t = db.query(Task).filter(Task.id == v).first()
            if t and t.board_id != board_id:
                targets.add(t.board_id)
        elif f["type"] == "connect" and v:
            col = _find_col(db, board_id, str(v))
            for bid in (_connect_cfg(col).get("board_ids") or []) if col else []:
                if str(bid).lstrip("-").isdigit() and int(bid) != board_id:
                    targets.add(int(bid))
    blocked = [t for t in targets
               if _board_role(db, t, actor_id) not in ("admin", "editor")]
    if blocked:
        names = ", ".join((db.query(Board.name).filter(Board.id == t).scalar() or str(t))
                          for t in blocked)
        raise HTTPException(403, "אוטומציה בין לוחות דורשת הרשאה בכל הלוחות שהיא נוגעת בהם. "
                                 f"אין לך הרשאה ב: {names}")


# ── Organisational view of the automations (ניהול ארגוני) ────────────
# A board admin sees their own board. Nobody could see the organisation: how
# many rules exist, which of them answer to nobody, which have not fired in
# months, which are failing, and how much they are consuming. That is the view
# that makes automations governable rather than merely configurable.
AUTOMATION_STALE_DAYS = 90
# The monthly allowance a whole organisation's automations run under. Shown as
# consumption, not enforced: a hard stop in the middle of a month would quietly
# break the boards that depend on rules, which is a decision for a person.
AUTOMATION_MONTHLY_QUOTA = int(os.getenv("AUTOMATION_MONTHLY_QUOTA", "20000"))
# What an org-wide stop must be given before it takes effect.
FREEZE_MIN_REASON = 10


def _require_sys_admin(db, user_id):
    """The organisational view is every board's rules at once, including boards
    the reader was never invited to. That is a system-admin view by definition."""
    if user_id is None:
        return                                     # auth disabled → no per-user gate
    if _ws_role(db, user_id) != "admin":
        raise HTTPException(403, "רק מנהל מערכת יכול לצפות בניהול האוטומציות הארגוני")


def _automation_health(db, board, a):
    """What is wrong with this rule, in words, or [] when nothing is.

    Read before switching a rule back on in bulk: a rule that names a status the
    board no longer has, or a person who left it, is a rule that will skip every
    time it fires — and switching a screenful of those back on looks like it
    worked until someone reads the history.
    """
    problems = []
    r = recipes.recipe(a.recipe_id)
    if not r:
        return ["המתכון אינו מוכר בגרסה הזאת"]
    cfg = a.config or {}
    _, err = recipes.validate(a.recipe_id, cfg)
    if err:
        problems.append(err)
    for f in r.get("fields", []):
        v = cfg.get(f["key"])
        if f["type"] == "person" and not _can_be_assigned(db, a.board_id, v):
            nm = db.query(User.name).filter(User.id == v).scalar() or v
            why = _not_taggable_reason(db, a.board_id, v) or "אינו חבר בלוח"
            problems.append(f"{nm} {why}")
        elif f["type"] == "status" and not any(
                x["key"] == str(v) for x in _board_statuses(board)):
            problems.append(f"הסטטוס '{v}' אינו קיים בלוח")
        elif f["type"] == "priority" and not any(
                x["key"] == str(v) for x in _board_priorities(board)):
            problems.append(f"העדיפות '{v}' אינה קיימת בלוח")
        elif f["type"] == "group" and not db.query(Group).filter(
                Group.id == v, Group.board_id == a.board_id).first():
            problems.append("הקבוצה שהכלל מפנה אליה נמחקה")
        elif f["type"] == "connect":
            col = _find_col(db, a.board_id, str(v))
            if not col or col.get("type") != "connect":
                problems.append("עמודת הקישור אינה קיימת בלוח")
        elif f["type"] == "item" and not db.query(Task).filter(Task.id == v).first():
            problems.append("הפריט שהכלל מקשר אליו נמחק")
        elif f["type"] == "board" and not db.query(Board).filter(
                Board.id == v, Board.deleted_at == None).first():           # noqa: E711
            problems.append("לוח היעד נמחק")
    return problems


def _org_automation_row(db, a, board, dept_names, now):
    """One rule as the organisational table reads it: which board and which unit
    it belongs to, who answers for it, and the two things that make it worth
    looking at — is it failing, and has it done anything lately."""
    ran, failed = a.run_count or 0, a.fail_count or 0
    _own = (_automation_owner_state(db, board, a) if board
            else {"needs_owner": True, "reason": "הלוח נמחק"})
    owner = a.owner_id or a.created_by
    last = a.last_run_at
    stale_days = (now - last).days if last else None
    return {
        "id": a.id, "board_id": a.board_id, "board_name": board.name if board else "—",
        "environment_id": board.environment_id if board else None,
        "department_id": board.department_id if board else None,
        "department_name": dept_names.get(board.department_id if board else None, ""),
        "sentence": _automation_label(db, board, a) if board else "",
        "name": a.name or "",
        "display_name": a.name or (_automation_label(db, board, a) if board else ""),
        "status": a.status or ("active" if a.is_active else "paused"),
        "is_active": bool(a.is_active),
        "importance": a.importance or "normal",
        "owner_id": owner,
        "owner_name": (db.query(User.name).filter(User.id == owner).scalar() or "") if owner else "",
        # one definition of "answers to nobody", shared with the board's own
        # screen: no owner, a blocked account, or an owner who is no longer a
        # manager of the board — see _automation_owner_state
        "ownerless": _own["needs_owner"], "owner_problem": _own["reason"],
        "run_count": ran, "fail_count": failed, "skip_count": a.skip_count or 0,
        "success_rate": round(100 * ran / (ran + failed)) if (ran + failed) else None,
        "last_run_at": last.isoformat() if last else None,
        "last_outcome": a.last_outcome or "",
        "stale_days": stale_days,
        "stale": (stale_days is None) or (stale_days >= AUTOMATION_STALE_DAYS),
        "needs_attention": (a.status == "paused_error") or (a.last_outcome == "failed"),
    }


@app.get("/api/admin/automations")
def admin_automations(board_id: int = 0, department_id: int = 0, environment_id: int = 0,
                      owner_id: int = 0, status: str = "", flag: str = "", q: str = "",
                      user_id: int = Depends(current_user_id)):
    """Every automation in the organisation, with the three questions the page
    exists to answer: what has no owner, what needs attention, and what has not
    run in AUTOMATION_STALE_DAYS.

    Filters narrow the list; the tiles and the quota are always over the whole
    organisation, so narrowing never changes the totals being narrowed.
    """
    with Session(engine) as db:
        _require_sys_admin(db, user_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        boards = {b.id: b for b in db.query(Board).filter(Board.deleted_at == None).all()}  # noqa: E711
        dept_names = {d.id: d.name for d in db.query(Department).all()}
        for _b in boards.values():
            _sweep_automation_ownership(db, _b, user_id)
        rows = [_org_automation_row(db, a, boards.get(a.board_id), dept_names, now)
                for a in db.query(Automation).order_by(Automation.board_id, Automation.run_order,
                                                       Automation.id).all()
                if a.board_id in boards]
        totals = {
            "total": len(rows),
            "active": sum(1 for r in rows if r["status"] == "active"),
            "paused": sum(1 for r in rows if r["status"] in ("paused", "paused_error")),
            "draft": sum(1 for r in rows if r["status"] == "draft"),
            "ownerless": sum(1 for r in rows if r["ownerless"]),
            "needs_attention": sum(1 for r in rows if r["needs_attention"]),
            "stale": sum(1 for r in rows if r["stale"]),
            "boards": len({r["board_id"] for r in rows}),
            "failures": sum(r["fail_count"] for r in rows),
        }
        shown = _filter_org_automations(rows, board_id, department_id, environment_id,
                                        owner_id, status, flag, q)
        period = now.strftime("%Y-%m")
        usage = db.query(AutomationUsage).filter(AutomationUsage.period == period).all()
        by_board = {u.board_id: u for u in usage}
        used = sum((u.ran or 0) + (u.skipped or 0) + (u.failed or 0) for u in usage)
        owners = sorted({(r["owner_id"], r["owner_name"]) for r in rows if r["owner_id"]},
                        key=lambda x: x[1] or "")
        return {
            "automations": shown, "totals": totals,
            "quota": {"period": period, "used": used, "limit": AUTOMATION_MONTHLY_QUOTA,
                      "percent": round(100 * used / AUTOMATION_MONTHLY_QUOTA)
                                 if AUTOMATION_MONTHLY_QUOTA else None,
                      "ran": sum(u.ran or 0 for u in usage),
                      "failed": sum(u.failed or 0 for u in usage),
                      "skipped": sum(u.skipped or 0 for u in usage),
                      # the boards consuming the most of it, which is the only
                      # actionable half of a quota reading
                      "top_boards": sorted(
                          [{"board_id": bid, "board_name": boards[bid].name if bid in boards else "—",
                            "runs": (u.ran or 0) + (u.skipped or 0) + (u.failed or 0)}
                           for bid, u in by_board.items() if bid in boards],
                          key=lambda x: -x["runs"])[:5]},
            "stale_days": AUTOMATION_STALE_DAYS,
            "departments": [{"id": d.id, "name": d.name} for d in db.query(Department).order_by(Department.name).all()],
            "environments": [{"id": e.id, "name": e.name} for e in db.query(Environment).order_by(Environment.name).all()],
            "boards": sorted([{"id": b.id, "name": b.name} for b in boards.values()],
                             key=lambda x: x["name"] or ""),
            "owners": [{"id": i, "name": n} for i, n in owners],
            "freezes": [_freeze_json(db, f) for f in db.query(AutomationFreeze)
                        .filter(AutomationFreeze.released_at == None)      # noqa: E711
                        .order_by(AutomationFreeze.id.desc()).all()],
        }


def _filter_org_automations(rows, board_id, department_id, environment_id,
                            owner_id, status, flag, q):
    out = rows
    if board_id:
        out = [r for r in out if r["board_id"] == board_id]
    if department_id:
        out = [r for r in out if r["department_id"] == department_id]
    if environment_id:
        out = [r for r in out if r["environment_id"] == environment_id]
    if owner_id:
        out = [r for r in out if r["owner_id"] == owner_id]
    if status == "paused":
        out = [r for r in out if r["status"] in ("paused", "paused_error")]
    elif status:
        out = [r for r in out if r["status"] == status]
    if flag == "ownerless":
        out = [r for r in out if r["ownerless"]]
    elif flag == "attention":
        out = [r for r in out if r["needs_attention"]]
    elif flag == "stale":
        out = [r for r in out if r["stale"]]
    if q:
        needle = q.strip().lower()
        out = [r for r in out
               if needle in " ".join([r["display_name"], r["sentence"], r["board_name"],
                                      r["owner_name"], r["department_name"]]).lower()]
    return out


@app.get("/api/admin/automations/export")
def admin_automations_export(board_id: int = 0, department_id: int = 0, environment_id: int = 0,
                             owner_id: int = 0, status: str = "", flag: str = "", q: str = "",
                             user_id: int = Depends(current_user_id)):
    """The filtered list as a .csv — the same filters, so what is exported is
    what is on screen rather than a second query that might disagree."""
    with Session(engine) as db:
        _require_sys_admin(db, user_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        boards = {b.id: b for b in db.query(Board).filter(Board.deleted_at == None).all()}  # noqa: E711
        dept_names = {d.id: d.name for d in db.query(Department).all()}
        rows = [_org_automation_row(db, a, boards.get(a.board_id), dept_names, now)
                for a in db.query(Automation).order_by(Automation.board_id, Automation.id).all()
                if a.board_id in boards]
        rows = _filter_org_automations(rows, board_id, department_id, environment_id,
                                       owner_id, status, flag, q)
        buf = io.StringIO()
        buf.write("﻿")                        # BOM so Excel reads Hebrew UTF-8
        w = csv.writer(buf)
        w.writerow(["לוח", "יחידה ארגונית", "שם האוטומציה", "המשפט", "סטטוס", "חשיבות",
                    "בעלים", "ללא בעלים", "דורשת טיפול", "הפעלה אחרונה", "ימים מאז",
                    "הצלחות", "כשלים", "דילוגים", "שיעור הצלחה"])
        _ST_HE = {"draft": "טיוטה", "active": "פעילה", "paused": "מושהית",
                  "paused_error": "מושהית עקב שגיאה", "deleting": "בתהליך מחיקה"}
        _IMP_HE = {"critical": "קריטית", "high": "גבוהה", "normal": "רגילה", "low": "נמוכה"}
        for r in rows:
            w.writerow([r["board_name"], r["department_name"], r["name"],
                        r["sentence"].replace("«", "").replace("»", ""),
                        _ST_HE.get(r["status"], r["status"]),
                        _IMP_HE.get(r["importance"], r["importance"]),
                        r["owner_name"], "כן" if r["ownerless"] else "",
                        "כן" if r["needs_attention"] else "",
                        (r["last_run_at"] or "")[:16].replace("T", " "),
                        "" if r["stale_days"] is None else r["stale_days"],
                        r["run_count"], r["fail_count"], r["skip_count"],
                        "" if r["success_rate"] is None else f'{r["success_rate"]}%'])
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 'attachment; filename="automations-org.csv"'})


def _freeze_json(db, f):
    uname = lambda uid: (db.query(User.name).filter(User.id == uid).scalar() or "") if uid else ""
    b = db.query(Board).filter(Board.id == f.board_id).first() if f.board_id else None
    return {"id": f.id, "scope": f.scope, "board_id": f.board_id,
            "board_name": b.name if b else None, "reason": f.reason or "",
            "created_by": f.created_by, "created_by_name": uname(f.created_by),
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "released_at": f.released_at.isoformat() if f.released_at else None,
            "released_by_name": uname(f.released_by),
            "release_reason": f.release_reason or ""}


@app.post("/api/admin/automations/freeze")
def admin_automations_freeze(data: dict, user_id: int = Depends(current_user_id)):
    """Stop automations — one board's, or the whole organisation's.

    An organisation-wide stop takes two things a board-level one does not: a
    written reason and an explicit second confirmation. It is the one action
    here that can halt work on every board at once, and it is recorded in the
    audit log so that "who turned everything off, and why" has an answer that
    does not depend on anyone remembering.

    Nothing releases it but a person. There is no timer.
    """
    with Session(engine) as db:
        _require_sys_admin(db, user_id)
        scope = (data.get("scope") or "").strip()
        if scope not in ("org", "board"):
            raise HTTPException(400, "יש לבחור היקף: ארגון או לוח")
        reason = (str(data.get("reason") or "")).strip()
        board = None
        if scope == "board":
            board = db.query(Board).filter(Board.id == data.get("board_id"),
                                           Board.deleted_at == None).first()   # noqa: E711
            if not board:
                raise HTTPException(404, "board not found")
        else:
            if len(reason) < FREEZE_MIN_REASON:
                raise HTTPException(400, f"השבתה ארגונית מחייבת סיבה (לפחות {FREEZE_MIN_REASON} תווים)")
            if not data.get("confirm"):
                raise HTTPException(400, "השבתה ארגונית מחייבת אישור נוסף")
        if not reason:
            raise HTTPException(400, "יש לציין סיבה")
        open_one = (db.query(AutomationFreeze)
                      .filter(AutomationFreeze.released_at == None,            # noqa: E711
                              AutomationFreeze.scope == scope,
                              AutomationFreeze.board_id == (board.id if board else None))
                      .first())
        if open_one:
            raise HTTPException(400, "השהיה כזאת פעילה כבר")
        f = AutomationFreeze(scope=scope, board_id=board.id if board else None,
                             reason=reason[:2000], created_by=user_id,
                             created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(f)
        db.flush()
        db.add(AuditLog(entity_type="automation_freeze", entity_id=f.id,
                        action="create", field_name=scope,
                        old_value=None,
                        new_value=f"{'ארגון' if scope == 'org' else board.name}: {reason}"[:2000],
                        changed_by=user_id))
        # the affected rules are counted for the report, not switched: releasing
        # the freeze has to put the board back exactly as it was
        n = db.query(Automation).filter(Automation.is_active == True)           # noqa: E712
        if scope == "board":
            n = n.filter(Automation.board_id == board.id)
        affected = n.count()
        db.commit()
        db.refresh(f)
        return {"freeze": _freeze_json(db, f), "affected": affected}


@app.post("/api/admin/automations/release")
def admin_automations_release(data: dict, user_id: int = Depends(current_user_id)):
    """End a freeze. Explicit, audited, and the only way one ends."""
    with Session(engine) as db:
        _require_sys_admin(db, user_id)
        f = db.query(AutomationFreeze).filter(AutomationFreeze.id == data.get("freeze_id"),
                                              AutomationFreeze.released_at == None).first()  # noqa: E711
        if not f:
            raise HTTPException(404, "השהיה לא נמצאה")
        f.released_at = datetime.now(timezone.utc).replace(tzinfo=None)
        f.released_by = user_id
        f.release_reason = (str(data.get("reason") or "")).strip()[:2000]
        db.add(AuditLog(entity_type="automation_freeze", entity_id=f.id,
                        action="release", field_name=f.scope,
                        old_value=f.reason, new_value=f.release_reason or "—",
                        changed_by=user_id))
        db.commit()
        db.refresh(f)
        return {"freeze": _freeze_json(db, f)}


# ── Bulk actions for a board admin (פעולות מרובות) ───────────────────
# Deliberately without delete. Everything here is reversible — a rule switched
# off can be switched on, an owner handed over can be handed back — and a
# screenful of checkboxes is exactly the wrong place to make an irreversible
# choice. See the MVP note in the spec.
AUTOMATION_BULK_ACTIONS = ("pause", "activate", "transfer")


@app.post("/api/boards/{board_id}/automations/bulk")
def bulk_automations(board_id: int, data: dict, user_id: int = Depends(current_user_id)):
    """Act on several rules at once, and say what happened to each.

    `dry_run` answers the question the confirmation dialog asks — how many rules
    this touches and what is worrying about them — without touching anything. The
    real call then returns one line per rule, because "12 rules updated" hides
    the two that did not.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if not _can_manage_automations(db, b, user_id):
            raise HTTPException(403, "רק מנהל הלוח יכול לבצע פעולות על אוטומציות")
        action = (data.get("action") or "").strip()
        if action not in AUTOMATION_BULK_ACTIONS:
            raise HTTPException(400, "פעולה לא מוכרת")
        ids = [i for i in (data.get("ids") or []) if isinstance(i, int)][:500]
        rules = (db.query(Automation).filter(Automation.board_id == board_id,
                                             Automation.id.in_(ids)).all() if ids else [])
        if not rules:
            raise HTTPException(400, "לא נבחרו אוטומציות")
        owner_id = None
        if action == "transfer":
            try:
                owner_id = int(data.get("owner_id"))
            except (TypeError, ValueError):
                raise HTTPException(400, "יש לבחור בעלים")
            # the same bar as naming someone inside a rule: a manager who was
            # never invited to the board cannot be made answerable for it
            if not _can_be_assigned(db, board_id, owner_id):
                raise HTTPException(400, "אפשר להעביר בעלות רק למי שהוזמן ללוח")
            if _board_role(db, board_id, owner_id) != "admin" and not data.get("force_owner"):
                nm = db.query(User.name).filter(User.id == owner_id).scalar() or ""
                raise HTTPException(400, f"{nm} אינו מנהל הלוח — בעלות מועברת למנהל מורשה")

        frozen = _automation_freeze(db, board_id)
        warnings, results = [], []
        if frozen is not None and action == "activate":
            warnings.append("האוטומציות בלוח מושהות בהשהיית חירום — הפעלה לא תיכנס לתוקף עד שתוסר")
        for a in rules:
            problems = _automation_health(db, b, a) if action == "activate" else []
            name = a.name or _automation_label(db, b, a).replace("«", "").replace("»", "")
            row = {"id": a.id, "name": name, "ok": True, "message": ""}
            if action == "pause":
                if a.status in ("paused", "paused_error"):
                    row.update(ok=True, message="מושהית כבר")
                else:
                    _set_automation_status(a, "paused")
                    row["message"] = "הושהתה"
            elif action == "activate":
                if problems:
                    # the health check is the point of this action: a rule that
                    # cannot work is left off and says why
                    row.update(ok=False, message=" · ".join(problems[:3]))
                elif a.status == "active":
                    row["message"] = "פעילה כבר"
                else:
                    _set_automation_status(a, "active")
                    row["message"] = "הופעלה"
            else:
                if a.owner_id == owner_id:
                    row["message"] = "הבעלות כבר שלו"
                else:
                    _prev = a.owner_id
                    a.owner_id = owner_id
                    _audit_owner_change(db, a, _prev, owner_id, user_id)
                    row["message"] = "הבעלות הועברה"
            if row["ok"] and row["message"] not in ("מושהית כבר", "פעילה כבר", "הבעלות כבר שלו"):
                a.updated_by = user_id
                a.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                _record_automation_version(db, b, a, user_id,
                                           note={"pause": "הושהתה בפעולה מרובה",
                                                 "activate": "הופעלה בפעולה מרובה",
                                                 "transfer": "הבעלות הועברה בפעולה מרובה"}[action])
            results.append(row)

        if data.get("dry_run"):
            db.rollback()
            # what the confirmation has to show: the count, and what will not work
            bad = [r for r in results if not r["ok"]]
            if action == "activate" and bad:
                warnings.append(f"{len(bad)} אוטומציות לא יעברו בדיקת תקינות ויישארו כבויות")
            if action == "pause":
                live = [r for r in results if r["message"] == "הושהית"]
                warnings.append(f"{len(live)} אוטומציות יפסיקו לפעול על הלוח הזה")
            return {"dry_run": True, "affected": len(rules), "warnings": warnings,
                    "results": results}
        db.commit()
        return {"dry_run": False, "affected": len(rules), "warnings": warnings,
                "results": results,
                "ok": sum(1 for r in results if r["ok"]),
                "failed": sum(1 for r in results if not r["ok"])}


@app.get("/api/boards/{board_id}/automations/export")
def export_board_automations(board_id: int, user_id: int = Depends(current_user_id)):
    """The board's rules as a .csv, for whoever has to review them off screen."""
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if not _can_export_automations(db, b, user_id):
            raise HTTPException(403, "ייצוא נתוני אוטומציות דורש הרשאת נתונים")
        rows = (db.query(Automation).filter(Automation.board_id == board_id)
                  .order_by(Automation.run_order, Automation.id).all())
        buf = io.StringIO()
        buf.write("﻿")
        w = csv.writer(buf)
        w.writerow(["שם", "המשפט", "תיאור עסקי", "סטטוס", "חשיבות", "סדר ביצוע", "בעלים",
                    "נוצר על ידי", "עדכון אחרון", "הפעלה אחרונה", "הצלחות", "כשלים",
                    "דילוגים", "שיעור הצלחה"])
        _ST_HE = {"draft": "טיוטה", "active": "פעילה", "paused": "מושהית",
                  "paused_error": "מושהית עקב שגיאה", "deleting": "בתהליך מחיקה"}
        _IMP_HE = {"critical": "קריטית", "high": "גבוהה", "normal": "רגילה", "low": "נמוכה"}
        uname = lambda uid: (db.query(User.name).filter(User.id == uid).scalar() or "") if uid else ""
        for a in rows:
            ran, failed = a.run_count or 0, a.fail_count or 0
            w.writerow([a.name or "", _automation_label(db, b, a).replace("«", "").replace("»", ""),
                        a.description or "", _ST_HE.get(a.status, a.status or ""),
                        _IMP_HE.get(a.importance, a.importance or ""), a.run_order or 0,
                        uname(a.owner_id or a.created_by), uname(a.created_by),
                        (a.updated_at.isoformat() if a.updated_at else "")[:16].replace("T", " "),
                        (a.last_run_at.isoformat() if a.last_run_at else "")[:16].replace("T", " "),
                        ran, failed, a.skip_count or 0,
                        f"{round(100 * ran / (ran + failed))}%" if (ran + failed) else ""])
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="automations-board-{board_id}.csv"'})


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, user_id: int = Depends(current_user_id)):
    """One item, serialized exactly as the board serializes it.

    This is what a client calls after an event tells it something changed, so
    it is the place per-item and per-column permissions are enforced — the event
    itself carries no data.
    """
    with Session(engine) as db:
        t = db.query(Task).filter(Task.id == task_id).first()
        if not t:
            raise HTTPException(404, "task not found")
        board = db.query(Board).filter(Board.id == t.board_id).first()
        if not board or board.deleted_at:
            raise HTTPException(404, "task not found")
        role = _board_role(db, t.board_id, user_id)
        if user_id is not None and role is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        if user_id is not None and _item_perm(t, user_id, role) == "none":
            raise HTTPException(403, "אין לך גישה לפריט זה")
        cols = (board.settings or {}).get("columns", [])
        return _serialize_task(t, db, user_id=user_id, board_role=role, columns=cols)


@app.get("/api/events")
async def events_stream(request: Request, user_id: int = Depends(current_user_id)):
    """Server-sent events: the doorbell for live updates.

    Deliberately `async def`. Almost every other endpoint here is a sync `def`,
    which FastAPI runs on a bounded worker thread pool — a sync stream would
    hold one of those threads for the entire life of the connection and starve
    the whole API after a few dozen viewers. This coroutine holds no thread and
    no database session while idle.
    """
    if not EVENTS_ENABLED:
        raise HTTPException(503, "live updates disabled")
    # Bound once, here, because this is the only place we are certainly on the
    # serving loop; publish() runs on worker threads and needs it to hop over.
    bus.bind_loop(asyncio.get_running_loop())
    # Which boards this connection is allowed to hear about. Taken once, at
    # connect: it only decides which doorbells ring, never what they carry, and
    # the refetch re-checks access anyway. A board shared with you mid-session
    # starts streaming on the next reconnect.
    with Session(engine) as db:
        visible = _visible_board_ids(db, user_id)

    q = bus.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"      # keep proxies from closing an idle stream
                    continue
                bid = ev.get("board_id")
                if ev.get("type") != "resync" and bid is not None and bid not in visible:
                    continue
                yield (f"id: {ev['seq']}\nevent: {ev['type']}\n"
                       f"data: {json.dumps(ev, ensure_ascii=False)}\n\n")
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",     # without this a proxy buffers and nothing arrives
    })


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, data: dict, request: Request = None,
                actor_id: int = Depends(current_user_id)):
    """Generic item update — title, priority, status, due_date, and custom column
    values (merged into custom_fields). Used by the editable board columns."""
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        actor = actor_id
        # mail built as the edit goes, sent once the edit is committed
        _mail = []
        # ── permission enforcement (item level, and column level for custom_fields) ──
        # Previously the whole block was skipped when the caller omitted user_id,
        # so an anonymous PATCH could edit any item on any board.
        actor_role = _board_role(db, task.board_id, actor)
        editing_builtin = any(k in data for k in ("title", "description", "priority", "status", "due_date"))
        iperm = _item_perm(task, actor, actor_role)
        if editing_builtin and iperm not in ("edit", "delete"):
            raise HTTPException(403, "אין לך הרשאת עריכה לפריט זה")
        if "custom_fields" in data and isinstance(data["custom_fields"], dict):
            cols = {c["id"]: c for c in (db.query(Board).filter(Board.id == task.board_id).first().settings or {}).get("columns", [])}
            # Optimistic concurrency, for connect cells only. The client sends
            # the whole desired list, so two people editing the same cell means
            # the second save silently erases the first — the picker was opened
            # against a value that no longer exists. `expect` is what the client
            # believes is there now; if the cell has moved under it, nothing is
            # written and the current value comes back with the refusal.
            _expect = data.get("expect")
            if isinstance(_expect, dict):
                for _k, _want in _expect.items():
                    _c2 = cols.get(_k)
                    if not _c2 or _c2.get("type") != "connect":
                        continue
                    _now = (_linked_ids(db, task.id, _k) if _is_two_way(_c2)
                            else [i for i in ((task.custom_fields or {}).get(_k) or [])
                                  if isinstance(i, int)])
                    _now = _visible_link_ids(db, _now, actor)
                    if sorted(_now) != sorted(i for i in (_want or []) if isinstance(i, int)):
                        raise HTTPException(409, {
                            "message": "הקישורים בתא זה עודכנו בינתיים על ידי משתמש אחר",
                            "column": _k, "current": _now})
            for k in list(data["custom_fields"].keys()):
                col = cols.get(k)
                # A mirror field is a view of the linked item, not a field of
                # this one. Accepting a write would store a value that the next
                # read discards — the cell would appear to change and then snap
                # back, which is worse than refusing.
                if col is not None and col.get("type") == "mirror":
                    del data["custom_fields"][k]
                    continue
                if col is not None and _col_perm(col, actor, actor_role) != "edit":
                    del data["custom_fields"][k]      # silently drop cols the user can't edit
            if iperm not in ("edit", "delete"):
                data["custom_fields"] = {}
            # people columns may only name board members (see _can_be_assigned)
            _filter_people_values(db, task.board_id, data["custom_fields"], task.custom_fields or {})
        # what the item shows now — compared after the edit so automations fire on
        # the real change, whichever route set it (built-in or board-defined value)
        _before_status = _task_status_key(task)
        _before_priority = _task_priority_key(task)
        # What the LOG compares — the same two columns read as the cell reads
        # them, which is not the same question the automations above ask (an
        # unset status still groups as `todo`; a log must say it is nobody's
        # choice). See _logged_status.
        _was_status = _logged_status(task)
        _was_priority = _logged_priority(task)
        _before_assignees = {u.id for u in task.assignees}
        _link_delta = {}          # col id → (added, removed), for the link triggers
        _link_report = []         # ids that did not take, and why
        if data.get("title") is not None and data["title"] != task.title:
            _audit(db, task_id, "update", "title", task.title, data["title"], actor)
            task.title = data["title"]
        if data.get("description") is not None:
            task.description = data["description"]
        if data.get("priority"):
            # a board-defined priority arrives as its own key: store the engine
            # value it behaves as, and let its label/colour ride on the item
            pboard = db.query(Board).filter(Board.id == task.board_id).first()
            pval, pcf = _resolve_priority(pboard, data["priority"])
            try:
                nv = Priority(pval)
                _cfu = dict(task.custom_fields or {})    # same reasoning as status, below
                if _cfu.pop("priority_unset", None) is not None:
                    task.custom_fields = _cfu
                task.priority = nv
                if pcf:
                    cfd = data.get("custom_fields")
                    if not isinstance(cfd, dict):
                        cfd = {}
                        data["custom_fields"] = cfd
                    for k, v in pcf.items():
                        cfd.setdefault(k, v)
            except ValueError:
                pass
        elif "priority" in data and data["priority"] in (None, ""):
            # Back to "טרם הוגדר" — the same gap the status column had, in the
            # column beside it. The five engine values were the only things
            # sayable, and none of them means "nobody has chosen", so a priority
            # set by mistake was permanent: changeable to another priority, never
            # back to undecided.
            #
            # The engine value returns to `medium`, exactly where a new item's
            # priority sits (see create_task) — sorting, the kanban and every
            # chart read this field, so a cleared item has to read as
            # unremarkable rather than as whatever it was before, and must never
            # hold a null that belongs in no bucket at all.
            #
            # In the API and not only in the picker, for the reason the status
            # branch below records: a priority set by an import or a script used
            # to leave the cell reading "טרם הוגדר" while task.priority said
            # otherwise. Clearing deserves the same treatment both ways.
            _cfu = dict(task.custom_fields or {})
            for _k in ("priority_key", "priority_label", "priority_color"):
                _cfu.pop(_k, None)
            _cfu["priority_unset"] = True
            task.custom_fields = _cfu
            task.priority = Priority.MEDIUM
        if data.get("status"):
            try:
                nv = TaskStatus(data["status"])
                # Naming a status IS choosing one, so the "nothing picked yet"
                # flag goes — but only once the value is accepted, or a rejected
                # status would still make the cell claim one was chosen. Only the
                # board UI used to clear it, by sending it in custom_fields, so a
                # status set through the API, an import or a script left the cell
                # reading "טרם הוגדר" while task.status said otherwise.
                _cfu = dict(task.custom_fields or {})
                if _cfu.pop("status_unset", None) is not None:
                    task.custom_fields = _cfu
                task.status = nv
                # Nothing else follows from a status. It does not move the item
                # between groups, and finishing the last sub-item does not finish
                # the parent — both were rules nobody wrote, on every board, absent
                # from the board's own automations list and with no switch. Each
                # has a recipe waiting in the catalog for a board that wants it.
            except ValueError:
                pass
        elif "status" in data and data["status"] in (None, ""):
            # Back to "טרם הוגדר" — the grey default every item starts on.
            # The cell could always SHOW it and nothing could ever put an item
            # back there, so a status picked by mistake was permanent: the seven
            # engine values were the only things sayable. An explicit null is a
            # different statement from all of them — nobody has chosen — and the
            # engine value returns to the neutral todo, exactly where a new item
            # sits, so the kanban and the charts read it as unstarted rather
            # than as whatever it was before someone cleared it.
            _cfu = dict(task.custom_fields or {})
            for _k in ("status_key", "status_label", "status_color"):
                _cfu.pop(_k, None)
            _cfu["status_unset"] = True
            task.custom_fields = _cfu
            task.status = TaskStatus.TODO
        if "due_date" in data:
            due = data["due_date"]
            old_due = task.due_date.isoformat() if task.due_date else None
            if due:
                try:
                    task.due_date = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                except ValueError:
                    pass
            else:
                task.due_date = None
            _audit(db, task_id, "update", "due_date", old_due,
                   task.due_date.isoformat() if task.due_date else None, actor)
        if "custom_fields" in data and isinstance(data["custom_fields"], dict):
            board = db.query(Board).filter(Board.id == task.board_id).first()
            coldefs = {c["id"]: c for c in ((board.settings or {}).get("columns", []) if board else [])}
            notify_on = _board_notify_on(board)
            def _ids(val):
                out = set()
                for x in (val or []) if isinstance(val, list) else []:
                    try:
                        out.add(int(x))
                    except (TypeError, ValueError):
                        pass
                return out
            cf = dict(task.custom_fields or {})
            for k, v in data["custom_fields"].items():
                _c = coldefs.get(k)
                if _is_two_way(_c):
                    # both ends of the pair change together, because there is only
                    # one row behind them
                    before = sorted(_linked_ids(db, task.id, k))
                    _set_links(db, task, _c, v, actor, _link_report)
                    after = sorted(_linked_ids(db, task.id, k))
                    if before != after:
                        _link_delta[k] = ([i for i in after if i not in before],
                                          [i for i in before if i not in after])
                        _audit(db, task_id, "update", "col:" + k,
                               json.dumps(before), json.dumps(after), actor)
                    continue
                old = cf.get(k)
                if _c and _c.get("type") == "connect" and isinstance(v, list):
                    # one-way links live in the cell itself rather than in
                    # item_links, so the two-way guard in _set_links does not
                    # cover them. Same rule, applied here.
                    _was = [i for i in (cf.get(k) or []) if isinstance(i, int)]
                    v = _merge_link_ids(db, v, cf.get(k) or [], actor, _is_multi(_c),
                                        _link_report)
                    if sorted(_was) != sorted(v):
                        _link_delta[k] = ([i for i in v if i not in _was],
                                          [i for i in _was if i not in v])
                if v is None:
                    cf.pop(k, None)
                else:
                    cf[k] = v
                if json.dumps(old, ensure_ascii=False) != json.dumps(v, ensure_ascii=False):
                    _audit(db, task_id, "update", "col:" + k,
                           json.dumps(old, ensure_ascii=False), json.dumps(v, ensure_ascii=False), actor)
                    # people column: notify each user newly added to this cell
                    col = coldefs.get(k)
                    if col and col.get("type") == "people" and notify_on:
                        added = _ids(v) - _ids(old)
                        added.discard(actor)
                        for uid2 in added:
                            _notify(db, uid2, "assign", "שויכת לפריט",
                                    f"שויכת לעמודת '{col.get('title', 'אנשים')}' במשימה '{task.title}'.",
                                    board_id=task.board_id, task_id=task_id)
                            # being named in a people column IS being put on the
                            # record; the mail says so in the same words the
                            # אחראי column's does
                            _mail.append(_item_mail(db, uid2, task, board, actor,
                                                    "assign", _app_base_url(request)))
            task.custom_fields = cf
        # One log row per column that changed, named the way the cell is named.
        # Written here rather than inside each branch above: a board-defined
        # status or priority is stored as its engine base in one part of the
        # request and as a key in custom_fields in another, so nothing earlier
        # than this knows what the cell ends up saying. Logged even where the
        # engine value does not move — "תקוע" → "הקפאה" shares a base, and so
        # does clearing `medium` back to undecided; what changed is what the
        # board shows and who chose it.
        for _f, _old, _new in (("status", _was_status, _logged_status(task)),
                               ("priority", _was_priority, _logged_priority(task))):
            if _old != _new:
                _audit(db, task_id, "update", _f, _old, _new, actor)
        # ── automations ── fire on what actually changed, before the commit so a
        # rule's own writes land in the same transaction as the edit
        if _task_status_key(task) != _before_status:
            _run_automations(db, task, {"type": "status_changes_to",
                                        "status": _task_status_key(task)}, actor)
        if _task_priority_key(task) != _before_priority:
            _run_automations(db, task, {"type": "priority_changes_to",
                                        "priority": _task_priority_key(task)}, actor)
        if {u.id for u in task.assignees} - _before_assignees:
            _run_automations(db, task, {"type": "person_assigned"}, actor)
        # a link being made or unmade is an event in its own right, and one edit
        # can do both in the same cell (a replacement), so both are reported
        for _k, (_added, _removed) in _link_delta.items():
            if _added:
                _run_automations(db, task, {"type": "link_added", "col": _k,
                                            "item_ids": _added}, actor)
            if _removed:
                _run_automations(db, task, {"type": "link_removed", "col": _k,
                                            "item_ids": _removed}, actor)
        # and the items pointing at this one hear that its status moved
        if _task_status_key(task) != _before_status:
            _fan_out_linked_status(db, task, _task_status_key(task), actor)
        _bid, _tid = task.board_id, task.id
        db.commit()
        _send_item_mails(_mail)
        # the write landed — only now is it safe to tell anyone, or a listener
        # could refetch and read the pre-commit row
        bus.publish("task.changed", board_id=_bid, task_id=_tid, actor_id=actor)
        # group_id, because an automation may have filed the item somewhere: the
        # person who made the change is the one client the live stream does not
        # tell (it would echo their own edit back at them), so the answer to
        # "where is it now" has to come back with the write itself.
        out = {"id": task.id, "group_id": task.group_id,
               "custom_fields": task.custom_fields or {}}
        if _link_report:
            # The rules already refused these. Saying so is the difference
            # between a link that did not take and a link that vanished.
            seen, msgs = set(), []
            for r in _link_report:
                if r["reason"] in seen:
                    continue
                seen.add(r["reason"])
                msgs.append(LINK_REJECT_HE.get(r["reason"], LINK_REJECT_HE["rejected"]))
            out["link_warnings"] = _link_report
            out["link_message"] = " · ".join(msgs)
        return out

# ── File uploads (for the Files column) ─────────────────────────────
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB per file.
# NOTE: on Vercel the serverless edge rejects request bodies larger than ~4.5MB
# before they reach us, so the full 10MB only applies on hosts without that cap
# (e.g. Azure Container Apps). Larger files would need external blob storage.

# Only these render in the browser. Anything else is served as a download, so an
# uploaded .html/.svg cannot execute script on our origin and steal the session.
# SVG is deliberately NOT here — it can carry <script> and would run same-origin.
INLINE_SAFE_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    "application/pdf", "text/plain",
}


def _safe_media_type(declared: str) -> tuple[str, bool]:
    """Normalise a client-declared content type into (media_type, may_inline)."""
    ct = (declared or "application/octet-stream").split(";")[0].strip().lower()
    if ct in INLINE_SAFE_TYPES:
        return ct, True
    # Never echo back an active type — text/html, image/svg+xml and friends
    # become an opaque download instead.
    return "application/octet-stream", False


@app.post("/api/upload")
def upload_file(file: UploadFile = File(...), actor_id: int = Depends(current_user_id)):
    """Store the upload in the DB so it persists and is shared across serverless
    instances (Vercel's local filesystem is ephemeral and per-instance).

    Deliberately a plain `def`: writing several megabytes into the database is a
    blocking call, and on the event loop it holds up every other request for as
    long as the write takes — against a remote database, that is the whole app
    pausing while one person attaches a photo. FastAPI runs a sync endpoint in a
    worker thread, where the wait costs only the person waiting.
    """
    content = file.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "הקובץ גדול מדי (מקסימום 10MB)")
    media_type, _ = _safe_media_type(file.content_type)
    token = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(UploadedFile(token=token, name=file.filename or "file",
                            content_type=media_type,
                            data=content, size=len(content)))
        db.commit()
    return {"name": file.filename, "url": f"/api/files/{token}", "type": media_type}

@app.get("/api/files/{token}")
def serve_file(token: str, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        f = db.query(UploadedFile).filter(UploadedFile.token == token).first()
        if not f:
            raise HTTPException(404, "file not found")
        from urllib.parse import quote
        media_type, may_inline = _safe_media_type(f.content_type)
        how = "inline" if may_inline else "attachment"
        disp = f"{how}; filename*=UTF-8''{quote(f.name or 'file')}"
        return Response(content=f.data, media_type=media_type,
                        headers={"Content-Disposition": disp,
                                 # stop the browser sniffing a download back into HTML
                                 "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "default-src 'none'; sandbox",
                                 # attachments are per-user now — keep them out of shared caches
                                 "Cache-Control": "private, max-age=31536000"})

@app.post("/api/tasks/{task_id}/permissions")
def set_item_permissions(task_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Set/clear a per-user permission on a single item. Board managers (admin) only.
    perm ∈ view|edit|delete|none  (none = pass to null to remove the override)."""
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        actor = actor_id
        if _board_role(db, task.board_id, actor) != "admin":
            raise HTTPException(403, "רק מנהל לוח יכול לקבוע הרשאות פריט")
        perms = dict(task.permissions or {})
        uid = str(data.get("user_id"))
        perm = data.get("perm")
        # clearing an override stays open — that is how a blocked user's old
        # grant gets cleaned up; handing out a new one does not
        if perm in ("view", "edit", "delete") and _account_blocked(db, data.get("user_id")):
            raise HTTPException(400, "לא ניתן להגדיר הרשאת פריט למשתמש מושבת")
        if perm in ("view", "edit", "delete", "none"):
            perms[uid] = perm
        else:
            perms.pop(uid, None)   # clear override → falls back to board role
        task.permissions = perms
        db.commit()
        return {"id": task.id, "permissions": task.permissions}

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        if user_id is not None:
            role = _board_role(db, task.board_id, user_id)
            if _item_perm(task, user_id, role) != "delete":
                raise HTTPException(403, "אין לך הרשאת מחיקה לפריט זה")
        # To the board's recycle bin, not gone. Sub-items follow their parent so
        # restoring the parent brings the whole thing back — and so a sub-item is
        # never left orphaned under an item that is no longer there.
        _bid = task.board_id
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for sub in db.query(Task).filter(Task.parent_id == task_id).all():
            sub.deleted_at = now
            sub.deleted_by = user_id
        task.deleted_at = now
        task.deleted_by = user_id
        _audit(db, task_id, "delete", field="item", old=task.title, new=None, user_id=user_id)
        db.commit()
        bus.publish("task.deleted", board_id=_bid, task_id=task_id, actor_id=user_id)
        return {"status": "deleted"}

# ── Item conversation (comments), files & activity log ──────────────

def _acting_user(db, uid):
    """The User row for the authenticated caller. `uid` now always comes from the
    auth dependency — it used to be read from the request body."""
    return db.query(User).filter(User.id == uid).first() if uid is not None else None

def _can_comment(db, board, user):
    """Board-scoped: only members who are not view-only may comment.
    A user who isn't a board member has no access at all."""
    if not user or not board:
        return False
    role = _board_role(db, board.id, user.id)
    if role is None:          # not invited to this board
        return False
    if role == "viewer":      # view-only at the board level
        return False
    if (board.settings or {}).get("view_only"):
        return role == "admin"
    return True

def _audit(db, entity_id, action, field=None, old=None, new=None, user_id=None):
    db.add(AuditLog(entity_type="task", entity_id=entity_id, action=action,
                    field_name=field,
                    old_value=(None if old is None else str(old)),
                    new_value=(None if new is None else str(new)),
                    changed_by=user_id))

def _serialize_comment(c, db):
    u = db.query(User).filter(User.id == c.user_id).first()
    # read receipts: everyone who saw the message except its own author
    seen_ids = [i for i in (c.seen_by or []) if i != c.user_id]
    seen_users = []
    if seen_ids:
        for su in db.query(User).filter(User.id.in_(seen_ids)).all():
            seen_users.append({"id": su.id, "name": su.name, "avatar_url": su.avatar_url})
    org = c.origin if isinstance(c.origin, dict) else None
    return {
        "id": c.id, "task_id": c.task_id, "parent_id": c.parent_id,
        "content": c.content, "attachments": c.attachments or [],
        "mentions": c.mentions or [], "likes": c.likes or [],
        "seen_users": seen_users,
        # an imported message whose author has no account here is still theirs:
        # the name comes off the import, and the message says where it came from
        "origin": org,
        "user_id": c.user_id,
        "user_name": u.name if u else ((org or {}).get("author") or "—"),
        # the author's photo travels with the comment. avatarInner resolves by id
        # against the loaded users first, so this is the fallback for an author
        # who is not in that list — without it they could only ever be initials.
        "avatar_url": u.avatar_url if u else None,
        "user_role": u.role if u else None, "created_at": c.created_at,
    }

@app.get("/api/tasks/{task_id}/comments")
def list_comments(task_id: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        _require_task_view(db, task_id, actor_id)
        cs = db.query(Comment).filter(Comment.task_id == task_id).order_by(Comment.created_at).all()
        items = [_serialize_comment(c, db) for c in cs]
        by_id = {i["id"]: {**i, "replies": []} for i in items}
        roots = []
        for i in items:
            node = by_id[i["id"]]
            if i["parent_id"] and i["parent_id"] in by_id:
                by_id[i["parent_id"]]["replies"].append(node)
            else:
                roots.append(node)
        # newest main comment pinned on top
        roots.sort(key=lambda x: str(x["created_at"]), reverse=True)
        return {"comments": roots, "count": len(items)}

@app.post("/api/tasks/{task_id}/comments")
def add_comment(task_id: int, data: dict, request: Request = None,
                actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        board = db.query(Board).filter(Board.id == task.board_id).first()
        user = _acting_user(db, actor_id)
        if not _can_comment(db, board, user):
            raise HTTPException(403, "אין הרשאת תגובה (צפייה בלבד)")
        content = (data.get("content") or "").strip()
        atts = data.get("attachments") or []
        if not content and not atts:
            raise HTTPException(400, "תגובה ריקה")
        # Who is being tagged: explicit @-picks plus any @Name typed into the text.
        mentioned = set()
        for x in (data.get("mentions") or []):
            try:
                mentioned.add(int(x))
            except (TypeError, ValueError):
                continue
        if content:
            for u in sorted(db.query(User).all(), key=lambda x: -len(x.name or "")):
                if u.name and ("@" + u.name) in content:
                    mentioned.add(u.id)
        # Only people invited to this board may be tagged. Tagging an outsider
        # sent them a notification for a board they cannot open, and put their
        # name on an item whose owner had no way to reach them. Filtering here
        # rather than in the picker is the point: the client cannot be trusted
        # to have filtered, and typing "@Name" bypasses the picker entirely.
        mentioned = {uid for uid in mentioned if _can_be_assigned(db, task.board_id, uid)}
        mentioned.discard(user.id)
        c = Comment(task_id=task_id, user_id=user.id, parent_id=data.get("parent_id"),
                    content=content, attachments=atts,
                    # store only the tags that survived, so the comment never
                    # claims to have tagged someone who was never notified
                    mentions=sorted(mentioned), likes=[], seen_by=[])
        db.add(c)
        _audit(db, task_id, "comment", field="reply" if data.get("parent_id") else "comment",
               new=(content[:120] or "(קובץ)"), user_id=user.id)
        _mail = []
        if mentioned and _board_notify_on(board):
            for mid in mentioned:
                _notify(db, mid, "mention", "תויגת בשיחה",
                        f"{user.name} תייג/ה אותך במשימה '{task.title}'.",
                        board_id=task.board_id, task_id=task_id)
                # a tag is addressed at somebody who is not reading the board
                # right now — that is the whole of what tagging is for
                _mail.append(_item_mail(db, mid, task, board, user.id, "mention",
                                        _app_base_url(request)))
        _bid = task.board_id if task else None
        db.commit(); db.refresh(c)
        _send_item_mails(_mail)
        bus.publish("comment.added", board_id=_bid, task_id=task_id, actor_id=actor_id)
        return _serialize_comment(c, db)

@app.post("/api/comments/{cid}/like")
def like_comment(cid: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        c = db.query(Comment).filter(Comment.id == cid).first()
        if not c:
            raise HTTPException(404, "comment not found")
        user = _acting_user(db, actor_id)
        if not user:
            raise HTTPException(403, "אין משתמש")
        likes = list(c.likes or [])
        liked_now = user.id not in likes
        if liked_now:
            likes.append(user.id)
        else:
            likes.remove(user.id)
        c.likes = likes
        # A like is the one thing in the conversation that said nothing to the
        # person it was about. In-app only, deliberately: the mail this system
        # sends is an invitation to a board or a workspace, and a thumbs-up is
        # not that. _notify writes a row and nothing more — no mail leaves here.
        if liked_now and c.user_id and c.user_id != user.id:
            task = db.query(Task).filter(Task.id == c.task_id).first()
            board = (db.query(Board).filter(Board.id == task.board_id).first()
                     if task else None)
            if task and _board_notify_on(board):
                body = f"{user.name} סימן/ה לייק להערה שלך בפריט '{task.title}'."
                # Liking, unliking and liking again is one person fidgeting, not
                # three pieces of news. While the first one is still unread, it
                # stands for all of them.
                already = (db.query(Notification)
                             .filter(Notification.user_id == c.user_id,
                                     Notification.type == "comment_like",
                                     Notification.task_id == c.task_id,
                                     Notification.body == body,
                                     Notification.is_read == False)   # noqa: E712
                             .first())
                if not already:
                    _notify(db, c.user_id, "comment_like", "סימנו לייק להערה שלך",
                            body, board_id=task.board_id, task_id=c.task_id)
        _bid = (db.query(Task.board_id).filter(Task.id == c.task_id).scalar()
                if c.task_id else None)
        db.commit()
        # the recipient's bell is the only thing this changes, and it learns from
        # the event stream rather than waiting out the reconcile interval
        bus.publish("comment.liked", board_id=_bid, task_id=c.task_id, actor_id=actor_id)
        return {"id": cid, "likes": likes}

@app.post("/api/tasks/{task_id}/comments/seen")
def mark_comments_seen(task_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Mark every message in the item as seen by the acting user (read receipts).
    A user's own messages are skipped — you don't 'see' your own."""
    with Session(engine) as db:
        user = _acting_user(db, actor_id)
        if not user:
            raise HTTPException(403, "אין משתמש")
        changed = False
        for c in db.query(Comment).filter(Comment.task_id == task_id).all():
            if c.user_id == user.id:
                continue
            seen = list(c.seen_by or [])
            if user.id not in seen:
                seen.append(user.id)
                c.seen_by = seen
                changed = True
        if changed:
            db.commit()
        return {"ok": True}

@app.patch("/api/comments/{cid}")
def update_comment(cid: int, data: dict, request: Request = None,
                   actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        c = db.query(Comment).filter(Comment.id == cid).first()
        if not c:
            raise HTTPException(404, "comment not found")
        user = _acting_user(db, actor_id)
        if not user or (c.user_id != user.id and user.role not in ("admin", "manager")):
            raise HTTPException(403, "אין הרשאה לערוך תגובה")

        _c_board_id = None
        _t = db.query(Task).filter(Task.id == c.task_id).first()
        if _t:
            _c_board_id = _t.board_id

        def _mentioned(content, explicit, members_only=True):
            """Users tagged either explicitly or via '@Name' inside the text.

            members_only mirrors the rule in create_comment: an edit may not tag
            somebody who was never invited to the board. It is off when reading
            the tags that were *already* on the comment, so a tag stored before
            this rule still counts as pre-existing and does not re-notify.
            """
            s = set()
            for x in (explicit or []):
                try:
                    s.add(int(x))
                except (TypeError, ValueError):
                    continue
            if content:
                for u in db.query(User).all():
                    if u.name and ("@" + u.name) in content:
                        s.add(u.id)
            if members_only and _c_board_id is not None:
                s = {uid for uid in s if _can_be_assigned(db, _c_board_id, uid)}
            return s

        # pre-existing tags are read unfiltered: someone tagged before this rule
        # must not be re-notified just because they are not a member today
        before = _mentioned(c.content, c.mentions, members_only=False)
        if "content" in data:
            c.content = data["content"]
        if "attachments" in data:
            c.attachments = data.get("attachments") or []
        if "mentions" in data:
            kept = [uid for uid in (c.mentions or []) if uid in (data.get("mentions") or [])]
            c.mentions = sorted({uid for uid in (data.get("mentions") or [])
                                 if uid in kept or (_c_board_id is not None
                                                    and _can_be_assigned(db, _c_board_id, uid))})
        # notify anyone newly tagged in this edit (not the editor, honoring the switch)
        newly = _mentioned(c.content, c.mentions) - before
        newly.discard(user.id)
        _mail = []
        if newly:
            task = db.query(Task).filter(Task.id == c.task_id).first()
            board = db.query(Board).filter(Board.id == task.board_id).first() if task else None
            if task and _board_notify_on(board):
                for mid in newly:
                    _notify(db, mid, "mention", "תויגת בשיחה",
                            f"{user.name} תייג/ה אותך במשימה '{task.title}'.",
                            board_id=task.board_id, task_id=task.id)
                    _mail.append(_item_mail(db, mid, task, board, user.id, "mention",
                                            _app_base_url(request)))
        db.commit()
        _send_item_mails(_mail)
        return _serialize_comment(c, db)

@app.delete("/api/comments/{cid}")
def delete_comment(cid: int, user_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        c = db.query(Comment).filter(Comment.id == cid).first()
        if not c:
            raise HTTPException(404, "comment not found")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or (c.user_id != user.id and user.role not in ("admin", "manager")):
            raise HTTPException(403, "אין הרשאה למחוק תגובה")
        for r in db.query(Comment).filter(Comment.parent_id == cid).all():
            db.delete(r)
        db.delete(c)
        db.commit()
        return {"status": "deleted"}

@app.get("/api/tasks/{task_id}/files")
def task_files(task_id: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        task = _require_task_view(db, task_id, actor_id)
        out = []
        for c in db.query(Comment).filter(Comment.task_id == task_id).order_by(Comment.created_at.desc()).all():
            u = db.query(User).filter(User.id == c.user_id).first()
            for f in (c.attachments or []):
                out.append({**f, "source": "שיחה", "user_name": u.name if u else None,
                            "user_id": c.user_id, "created_at": c.created_at})
        board = db.query(Board).filter(Board.id == task.board_id).first()
        cols = (board.settings or {}).get("columns", []) if board else []
        cf = task.custom_fields or {}
        for col in [c for c in cols if c.get("type") == "files"]:
            for f in (cf.get(col["id"]) or []):
                out.append({**f, "source": "עמודה: " + (col.get("title") or ""), "user_name": None,
                            "user_id": None, "created_at": task.updated_at})
        return {"files": out}

@app.post("/api/tasks/{task_id}/files/delete")
def delete_task_file(task_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Remove a file from the item — from the comment it's attached to or a files
    column — and delete the stored blob. The uploader or a board admin/manager may
    delete a chat attachment; a board editor+/admin may delete a column file."""
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        user = _acting_user(db, actor_id)
        if not user:
            raise HTTPException(403, "אין משתמש")
        url = (data.get("url") or "").strip()
        if not url:
            raise HTTPException(400, "חסר קובץ למחיקה")
        role = _board_role(db, task.board_id, user.id)
        is_priv = role == "admin" or user.role in ("admin", "manager")
        removed = False
        # 1) chat attachment: find the owning comment (uploader or admin may delete)
        for c in db.query(Comment).filter(Comment.task_id == task_id).all():
            atts = c.attachments or []
            if any((a or {}).get("url") == url for a in atts):
                if not (is_priv or c.user_id == user.id):
                    raise HTTPException(403, "רק מעלה הקובץ או מנהל הלוח יכול למחוק אותו")
                c.attachments = [a for a in atts if (a or {}).get("url") != url]
                removed = True
        # 2) files-column value (board editor+/admin)
        board = db.query(Board).filter(Board.id == task.board_id).first()
        cols = (board.settings or {}).get("columns", []) if board else []
        cf = dict(task.custom_fields or {})
        for col in [c for c in cols if c.get("type") == "files"]:
            arr = cf.get(col["id"]) or []
            if any((a or {}).get("url") == url for a in arr):
                if not (is_priv or role in ("editor",)):
                    raise HTTPException(403, "אין לך הרשאה למחוק קובץ זה")
                cf[col["id"]] = [a for a in arr if (a or {}).get("url") != url] or None
                task.custom_fields = cf
                removed = True
        # 3) delete the stored blob (best-effort, by token in the url)
        token = url.rsplit("/", 1)[-1]
        uf = db.query(UploadedFile).filter(UploadedFile.token == token).first()
        if uf:
            db.delete(uf)
        db.commit()
        return {"status": "deleted", "removed": removed}

@app.get("/api/tasks/{task_id}/activity")
def task_activity(task_id: int, actor_id: int = Depends(current_user_id),
                  user_id: Optional[int] = None, date: Optional[str] = None):
    """One item's history.

    `user_id` is the person to FILTER BY, from the query string. It used to be
    bound to Depends(current_user_id), which meant it was always the caller —
    so the log silently showed only your own changes and the "all users" option
    in the filter did nothing. The actor is now a separate parameter.
    """
    with Session(engine) as db:
        task = _require_task_view(db, task_id, actor_id)
        cols = {c.get("id"): c for c in _board_columns(db, task.board_id)}
        q = db.query(AuditLog).filter(AuditLog.entity_type == "task", AuditLog.entity_id == task_id)
        if user_id:
            q = q.filter(AuditLog.changed_by == user_id)
        out = []
        for l in q.order_by(AuditLog.created_at.desc()).all():
            if l.field_name in _INTERNAL_LOG_FIELDS:
                continue
            if date and (not l.created_at or str(l.created_at)[:10] != date):
                continue
            vals = _log_link_row(db, l.field_name, l.old_value, l.new_value, cols, actor_id)
            if vals is None:
                continue                      # the change was invisible to this viewer
            u = db.query(User).filter(User.id == l.changed_by).first()
            og = l.origin if isinstance(l.origin, dict) else None
            out.append({"id": l.id, "action": l.action, "field": l.field_name,
                        "old": vals[0], "new": vals[1],
                        "origin": (og or {}).get("source") or "",
                        "user_id": l.changed_by,
                        "user_name": (u.name if u else None) or (og or {}).get("author") or "מערכת",
                        # imported history is read-only — see the note in
                        # _board_activity_rows
                        "can_undo": l.action == "update" and not og,
                        "created_at": l.created_at})
        return {"activity": out}

# The board-defined status/priority machinery stores its bookkeeping in
# custom_fields — the key, the label, the colour and an "unset" flag. Changing
# one status therefore writes four audit rows whose values are raw JSON. They
# are implementation detail, and a person reading a log wants one line saying
# the status changed, not four saying its colour did.
_INTERNAL_LOG_FIELDS = {
    "col:status_key", "col:status_label", "col:status_color", "col:status_unset",
    "col:priority_key", "col:priority_label", "col:priority_color", "col:priority_unset",
}


def _log_link_row(db, field, old, new, cols, viewer):
    """A log row's before/after for a connect column, as `viewer` may see it.

    Two jobs. The stored values are raw id lists, so the history is a second way
    to read the ids the cell withholds — and worse, a way to notice that hidden
    links exist at all, which the cell is careful not to reveal. So both sides
    are cut down to what this viewer may see.

    And then named: an id in a log is not a record of what happened to anyone
    reading it, so each surviving id is returned as {"id","title"}. Which item
    was added or removed is the part of a link change worth writing down.

    Returns None when the row then says nothing: if what changed was invisible
    to them, a "changed from [] to []" line is noise that also confirms
    something happened.
    """
    if not str(field or "").startswith("col:"):
        return old, new
    col = cols.get(str(field)[4:])
    if not col or col.get("type") != "connect":
        return old, new

    def ids_of(v):
        try:
            got = json.loads(v) if v else []
        except (ValueError, TypeError):
            return None
        # a cell that held nothing is audited as JSON null, not as [] — a
        # one-way column's very first link looks like that, and reading it as
        # "not a list" left the row raw while every later one was named
        if got is None:
            return []
        return [i for i in got if isinstance(i, int)] if isinstance(got, list) else None

    before, after = ids_of(old), ids_of(new)
    if before is None or after is None:
        return old, new
    before = _visible_link_ids(db, before, viewer)
    after = _visible_link_ids(db, after, viewer)
    if before == after:
        return None
    titles = {}
    every = list({*before, *after})
    if every:
        titles = {t.id: t.title for t in db.query(Task).filter(Task.id.in_(every))
                  .execution_options(include_deleted=True).all()}
    name = lambda ids: json.dumps(
        [{"id": i, "title": titles.get(i, "#%d" % i)} for i in ids], ensure_ascii=False)
    return name(before), name(after)


def _board_task_ids(db, board_id):
    """Ids of every item on the board, sub-items included — they are Tasks too."""
    return [i for (i,) in db.query(Task.id).filter(Task.board_id == board_id).all()]


def _board_activity_rows(db, board_id, user_id=None, date=None, limit=400, viewer=None):
    """Every audited change on the board, newest first.

    Same records the item log reads — AuditLog rows for tasks — only gathered
    across the whole board instead of one item. Each row carries the item it
    belongs to, because at board level "changed status" means nothing without
    saying of what.
    """
    ids = _board_task_ids(db, board_id)
    if not ids:
        return []
    q = db.query(AuditLog).filter(AuditLog.entity_type == "task", AuditLog.entity_id.in_(ids))
    if user_id:
        q = q.filter(AuditLog.changed_by == user_id)
    titles = {i: t for (i, t) in db.query(Task.id, Task.title).filter(Task.id.in_(ids)).all()}
    users = {u.id: u.name for u in db.query(User).all()}
    cols = {c.get("id"): c for c in _board_columns(db, board_id)}
    out = []
    for l in q.order_by(AuditLog.created_at.desc()).limit(max(1, min(2000, limit * 3))).all():
        if l.field_name in _INTERNAL_LOG_FIELDS:
            continue
        if date and (not l.created_at or str(l.created_at)[:10] != date):
            continue
        vals = _log_link_row(db, l.field_name, l.old_value, l.new_value, cols, viewer)
        if vals is None:
            continue                          # the change was invisible to this viewer
        og = l.origin if isinstance(l.origin, dict) else None
        out.append({"id": l.id, "action": l.action, "field": l.field_name,
                    "old": vals[0], "new": vals[1],
                    "task_id": l.entity_id, "task_title": titles.get(l.entity_id, "—"),
                    "user_id": l.changed_by,
                    # an imported row's author may have no account here; the name
                    # it came with is better than "מערכת"
                    "user_name": (users.get(l.changed_by)
                                  or (og or {}).get("author") or "מערכת"),
                    # Nothing imported offers an undo. The change happened in
                    # monday, possibly a year ago, and reverting it would write
                    # that value onto the item now — from a button that looks
                    # exactly like every other undo on the page.
                    "origin": (og or {}).get("source") or "",
                    "can_undo": l.action == "update" and not og,
                    "created_at": l.created_at})
        if len(out) >= limit:
            break
    return out


def _board_log_people(db, board_id):
    """Who the log's person-filter may offer.

    Everyone invited to the board — anyone else cannot act on it, so listing the
    whole workspace fills the menu with names that can only ever return nothing.

    Plus anyone who actually appears in this board's log. A member who was
    removed after doing work is still in the history, and dropping them from the
    filter would leave rows nobody can filter to. So the rule is "could have
    acted, or did".
    """
    members = (db.query(User)
                 .join(BoardMember, BoardMember.user_id == User.id)
                 .filter(BoardMember.board_id == board_id).all())
    people = {u.id: {"id": u.id, "name": u.name, "avatar_url": u.avatar_url} for u in members}
    ids = _board_task_ids(db, board_id)
    if ids:
        actor_ids = {a for (a,) in db.query(AuditLog.changed_by)
                     .filter(AuditLog.entity_type == "task",
                             AuditLog.entity_id.in_(ids)).distinct().all() if a}
        missing = actor_ids - set(people)
        if missing:
            for u in db.query(User).filter(User.id.in_(missing)).all():
                people[u.id] = {"id": u.id, "name": u.name, "avatar_url": u.avatar_url}
    return sorted(people.values(), key=lambda p: (p["name"] or ""))


@app.get("/api/boards/{board_id}/activity")
def board_activity(board_id: int, actor_id: int = Depends(current_user_id),
                   user_id: Optional[int] = None, date: Optional[str] = None,
                   limit: int = 400):
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        # seeing the log means seeing the board — the same gate the board itself uses
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        return {"activity": _board_activity_rows(db, board_id, user_id, date, limit,
                                                 viewer=actor_id),
                # sent alongside so the filter's options never depend on what the
                # current filter happens to have returned
                "people": _board_log_people(db, board_id)}


@app.post("/api/boards/{board_id}/seen")
def mark_board_seen(board_id: int, actor_id: int = Depends(current_user_id)):
    """Record that this person just opened the board.

    Deliberately its own endpoint rather than a side effect of GET
    /api/boards/{id}: that runs on every background refetch — after a two-way
    link is saved, after a live event — and counting those would make "נצפה
    לאחרונה" a log of the app talking to itself. Only the act of opening a
    board calls this.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        row = db.query(BoardView).filter(BoardView.board_id == board_id,
                                         BoardView.user_id == actor_id).first()
        if row:
            row.seen_at = now
        else:
            db.add(BoardView(board_id=board_id, user_id=actor_id, seen_at=now))
        try:
            db.commit()
        except IntegrityError:
            # two tabs opening the board at once both missed the row and both
            # inserted; the unique constraint is what makes that a no-op
            db.rollback()
            row = db.query(BoardView).filter(BoardView.board_id == board_id,
                                             BoardView.user_id == actor_id).first()
            if row:
                row.seen_at = now
                db.commit()
        return {"status": "ok", "seen_at": now.isoformat()}


@app.get("/api/boards/{board_id}/seen")
def board_seen_by(board_id: int, actor_id: int = Depends(current_user_id)):
    """Who has opened this board, most recent first.

    Anyone on the board may read it — the same gate as the activity log, since
    it answers a question of the same kind. People who have since left the board
    stay listed: they did look, and a history that quietly drops them is not a
    history.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        rows = (db.query(BoardView).filter(BoardView.board_id == board_id)
                .order_by(BoardView.seen_at.desc()).all())
        users = {u.id: u for u in db.query(User).filter(
            User.id.in_([r.user_id for r in rows]))} if rows else {}
        members = {m.user_id for m in db.query(BoardMember).filter(
            BoardMember.board_id == board_id).all()}
        out = []
        for r in rows:
            u = users.get(r.user_id)
            if not u:
                continue                     # the account is gone; so is the row's meaning
            out.append({"user_id": u.id, "name": u.name, "avatar_url": u.avatar_url,
                        "seen_at": r.seen_at.isoformat() if r.seen_at else None,
                        "is_member": u.id in members})
        # who has never opened it, so "nobody has looked" is answerable too
        never = [{"user_id": u.id, "name": u.name, "avatar_url": u.avatar_url}
                 for u in db.query(User).filter(User.id.in_(members)).all()
                 if u.id not in {r.user_id for r in rows}]
        return {"seen": out, "never": never, "total_members": len(members)}


@app.get("/api/boards/{board_id}/activity/export")
def export_board_activity(board_id: int, actor_id: int = Depends(current_user_id),
                          user_id: Optional[int] = None, date: Optional[str] = None):
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        if _board_role(db, board_id, actor_id) is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        rows = _board_activity_rows(db, board_id, user_id, date, limit=5000, viewer=actor_id)
        buf = io.StringIO()
        buf.write("\ufeff")  # BOM so Excel reads Hebrew UTF-8
        w = csv.writer(buf)
        w.writerow(["תאריך", "פריט", "משתמש", "פעולה", "שדה", "מ-", "ל-"])
        for r in rows:
            w.writerow([r["created_at"], r["task_title"], r["user_name"],
                        r["action"], r["field"] or "", r["old"] or "", r["new"] or ""])
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="board-{board_id}-activity.csv"'})


@app.get("/api/tasks/{task_id}/activity/export")
def export_activity(task_id: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        task = _require_task_view(db, task_id, actor_id)
        cols = {c.get("id"): c for c in _board_columns(db, task.board_id)}
        logs = db.query(AuditLog).filter(AuditLog.entity_type == "task", AuditLog.entity_id == task_id)\
                 .order_by(AuditLog.created_at.desc()).all()
        logs = [l for l in logs
                if _log_link_row(db, l.field_name, l.old_value, l.new_value, cols, actor_id) is not None]
        buf = io.StringIO()
        buf.write("﻿")  # BOM so Excel reads Hebrew UTF-8
        w = csv.writer(buf)
        w.writerow(["תאריך", "משתמש", "פעולה", "שדה", "מ-", "ל-"])
        for l in logs:
            u = db.query(User).filter(User.id == l.changed_by).first()
            w.writerow([str(l.created_at)[:19], u.name if u else "מערכת", l.action,
                        l.field_name or "", l.old_value or "", l.new_value or ""])
        return Response(content=buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=activity_task_{task_id}.csv"})

def _revert_field(db, task, field, old):
    if field == "title":
        task.title = old or ""; return True
    # These two rows hold the vocabulary key the cell showed, not the enum
    # value — which is what makes "הקפאה → תקוע" legible in the first place —
    # so putting one back goes through the board's vocabulary.
    if field in ("status", "priority"):
        return _restore_choice(db, task, field, old)
    if field == "due_date":
        task.due_date = datetime.fromisoformat(old) if old else None; return True
    if field and field.startswith("col:"):
        cid = field[4:]; cf = dict(task.custom_fields or {})
        val = json.loads(old) if old not in (None, "", "null") else None
        if val is None: cf.pop(cid, None)
        else: cf[cid] = val
        task.custom_fields = cf; return True
    return False

@app.post("/api/activity/{log_id}/undo")
def undo_activity(log_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        user = _acting_user(db, actor_id)
        if not user or user.role not in ("admin", "manager"):
            raise HTTPException(403, "רק מנהל יכול לבצע ביטול")
        log = db.query(AuditLog).filter(AuditLog.id == log_id).first()
        if not log or log.entity_type != "task" or log.action != "update":
            raise HTTPException(400, "לא ניתן לבטל פעולה זו")
        # The gate, not the hint. The row's button is hidden, and a request that
        # arrives anyway — an old page, a script, a guessed id — is refused
        # here: undoing a change that happened in monday would write a value
        # from the board's past onto the item as it stands now.
        if isinstance(log.origin, dict) and log.origin.get("source"):
            raise HTTPException(400, "השורה הזאת היא היסטוריה מיובאת — אין מה לבטל כאן")
        task = db.query(Task).filter(Task.id == log.entity_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        # A two-way connect cell is not stored on the item, so the generic
        # revert wrote the old ids into custom_fields where the serializer
        # ignores them: the undo reported success and changed nothing. Links go
        # back the way they were set, through the relationship rows.
        _col = _find_col(db, task.board_id, (log.field_name or "")[4:]) \
            if (log.field_name or "").startswith("col:") else None
        if _col is not None and _col.get("type") == "connect":
            try:
                _old = json.loads(log.old_value) if log.old_value not in (None, "", "null") else []
            except (ValueError, TypeError):
                _old = []
            _old = [i for i in _old if isinstance(i, int)]
            if _is_two_way(_col):
                _set_links(db, task, _col, _old, None)     # system authority: an admin is undoing
            else:
                _cf = dict(task.custom_fields or {})
                _cf[_col["id"]] = _merge_link_ids(db, _old, _cf.get(_col["id"]) or [],
                                                  None, _is_multi(_col))
                task.custom_fields = _cf
        elif not _revert_field(db, task, log.field_name, log.old_value):
            raise HTTPException(400, "שדה לא נתמך לביטול")
        _audit(db, task.id, "undo", field=log.field_name, old=log.new_value, new=log.old_value, user_id=user.id)
        db.commit()
        return {"status": "reverted", "field": log.field_name}

@app.post("/api/tasks/{task_id}/assignees")
def task_assignees(task_id: int, data: dict, request: Request = None,
                   actor_id: int = Depends(current_user_id)):
    """Add or remove a user from a task (monday-style people column)."""
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        user = db.query(User).filter(User.id == data.get("user_id")).first()
        if not user:
            raise HTTPException(404, "user not found")
        actor = actor_id
        _require_board_edit(db, task.board_id, actor)   # only board editors may (un)assign
        was = user in task.assignees
        _mail = []
        # removal stays open regardless, so an assignment made before this rule
        # existed can still be taken off the item
        if data.get("action") != "remove" and not was and not _can_be_assigned(db, task.board_id, user.id):
            raise HTTPException(403, "לא ניתן לשייך משתמש מושבת" if user.is_active is False
                                else "אפשר לשייך רק משתמשים שהוזמנו ללוח")
        if data.get("action") == "remove":
            if was:
                task.assignees.remove(user)
        else:
            if not was:
                task.assignees.append(user)
                # notify the newly-assigned person (skip self-assignment / re-adds)
                if user.id != actor:
                    board = db.query(Board).filter(Board.id == task.board_id).first()
                    if _board_notify_on(board):
                        actor_u = db.query(User).filter(User.id == actor).first()
                        _notify(db, user.id, "assign", "שויכת למשימה",
                                f"{(actor_u.name + ' ') if actor_u else ''}שייך/ה אותך למשימה '{task.title}'.",
                                board_id=task.board_id, task_id=task_id)
                        _mail.append(_item_mail(db, user.id, task, board, actor, "assign",
                                                _app_base_url(request)))
                _run_automations(db, task, {"type": "person_assigned",
                                            "user_id": user.id}, actor)
        _bid = task.board_id
        db.commit()
        _send_item_mails(_mail)
        bus.publish("task.changed", board_id=_bid, task_id=task_id, actor_id=actor)
        return {"assignees": [{"id": u.id, "name": u.name, "avatar_url": u.avatar_url}
                              for u in task.assignees]}

# Sentinel: "the caller named no anchor at all", which is not the same as
# `after_id: null` — that one means "put it at the very top".
_NO_ANCHOR = object()


def _group_items(db, board_id, group_id, exclude_id=None):
    """One group's top-level items, in the order the board shows them."""
    q = (db.query(Task)
         .filter(Task.board_id == board_id, Task.parent_id == None,   # noqa: E711
                 Task.is_archived == False, Task.group_id == group_id))  # noqa: E712
    if exclude_id is not None:
        q = q.filter(Task.id != exclude_id)
    return q.order_by(Task.position, Task.id).all()


def _renumber_group(db, board_id, group_id):
    for i, t in enumerate(_group_items(db, board_id, group_id)):
        t.position = i


def _place_item(db, task, position=None, after_id=_NO_ANCHOR):
    """Put an item where the drag left it — and renumber the whole group.

    Writing only the moved item's new position was the bug: the group ended up
    with two items claiming the same number, and the board reads back ordered
    by position alone, so the tie went to whichever row the database happened to
    return first. That was usually the one already sitting there, so the dragged
    item sprang back and the drag looked like it had done nothing at all.
    Renumbering every sibling is what makes the new order the order that returns.

    `after_id` is what a drag sends: the item this one now sits below. An index
    cannot say that faithfully, because the rows on screen can be a filtered
    subset of the group — "dropped third" is then not "third item". `position`
    stays supported for callers holding the whole list, and both end in the same
    dense 0..n-1 sequence.
    """
    siblings = _group_items(db, task.board_id, task.group_id, exclude_id=task.id)
    if after_id is not _NO_ANCHOR:
        if after_id is None:
            idx = 0                                   # dropped above everything
        else:
            ids = [t.id for t in siblings]
            # an id from another group, or one that has since moved, says
            # nothing about where this item belongs — last beats guessing
            idx = ids.index(after_id) + 1 if after_id in ids else len(siblings)
    elif position is not None:
        idx = max(0, min(int(position), len(siblings)))
    else:
        idx = len(siblings)
    for i, t in enumerate(siblings[:idx] + [task] + siblings[idx:]):
        t.position = i


@app.post("/api/tasks/{task_id}/move")
def move_task(task_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404)
        actor = actor_id
        _require_board_edit(db, task.board_id, actor)
        _src_board = task.board_id          # remembered before any reassignment
        _src_group = task.group_id
        target = data.get("board_id")
        if target and int(target) != task.board_id:
            # ── move the item to another board ──
            target = int(target)
            if task.parent_id:
                raise HTTPException(400, "תת-פריט עובר יחד עם הפריט שלו")
            tb = db.query(Board).filter(Board.id == target).first()
            if not tb:
                raise HTTPException(404, "לוח היעד לא נמצא")
            _require_board_edit(db, target, actor)
            groups = db.query(Group).filter(Group.board_id == target).order_by(Group.position).all()
            wanted = data.get("group_id")
            grp = next((g for g in groups if g.id == wanted), None) or (groups[0] if groups else None)
            subs = db.query(Task).filter(Task.parent_id == task.id).all()
            # while the item still belongs to the source board, whose columns
            # are the ones its links are keyed on
            for t in [task] + subs:
                _carry_links_across_boards(db, t, _src_board, target, actor)
            for t in [task] + subs:
                t.board_id = target
                t.group_id = grp.id if grp else None
            # The group it lands in does not restamp its status. A group is where
            # an item sits; the status is what someone said about it, and it
            # survives the move like every other field on the item. A board that
            # wants the two tied together says so in its automations.
            maxpos = (db.query(func.max(Task.position))
                      .filter(Task.board_id == target, Task.parent_id == None,
                              Task.group_id == (grp.id if grp else None)).scalar())
            task.position = (maxpos + 1) if maxpos is not None else 0
            # the identifier belongs to the board it was minted for: the item (and
            # its sub-items) get new ones here, and new ones again if they return
            for t in [task] + subs:
                _ensure_item_uid(db, t)
            _renumber_group(db, _src_board, _src_group)   # close the gap behind it
            db.commit()
            # the item left one board and arrived on another — both need telling
            bus.publish("task.deleted", board_id=_src_board, task_id=task_id, actor_id=actor)
            bus.publish("task.created", board_id=target, task_id=task_id, actor_id=actor)
            return {"status": "moved", "board_id": target, "item_uid": task.item_uid}
        src_group = task.group_id
        if "group_id" in data:
            task.group_id = data["group_id"]
        if "after_id" in data:
            _place_item(db, task, after_id=data.get("after_id"))
        elif "position" in data:
            _place_item(db, task, position=data["position"])
        elif "group_id" in data and task.group_id != src_group:
            _place_item(db, task)                     # no anchor named: last
        if task.group_id != src_group:
            _renumber_group(db, task.board_id, src_group)   # close the gap behind it
        if "status" in data:
            # The kanban drag, the sub-item status cell and the console `move`
            # command all set a status through here. This used to assign the raw
            # string onto the enum column: nothing ever reached the log, and any
            # board-defined label still riding in custom_fields was left behind,
            # so the cell went on painting a status the item no longer had.
            _was = _logged_status(task)
            if not _apply_status_key(db, task, data["status"]):
                # Not in the board's vocabulary. `todo` and `review` are real
                # engine values the default vocabulary does not offer, and the
                # sub-item cell cycles through exactly those, so they are taken
                # here. Anything else is left alone, the way the PATCH endpoint
                # leaves an unknown status alone.
                try:
                    task.status = TaskStatus(str(data["status"]))
                except ValueError:
                    pass
                else:
                    _cf = dict(task.custom_fields or {})
                    for _k in ("status_key", "status_label", "status_color", "status_unset"):
                        _cf.pop(_k, None)
                    task.custom_fields = _cf
            _now = _logged_status(task)
            if _now != _was:
                _audit(db, task_id, "update", "status", _was, _now, actor)
        db.commit()
        bus.publish("task.changed", board_id=_src_board, task_id=task_id, actor_id=actor)
        return {"status": "moved"}

@app.post("/api/boards/{board_id}/items/move")
def move_items_bulk(board_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Move several items into one group — one request, one transaction.

    Why this exists rather than calling /tasks/{id}/move per item: that endpoint
    renumbers the whole group an item leaves AND the whole group it joins, so
    twelve selected items were twelve round trips and twenty-four renumbers, and
    the client then refetched the entire board on top of it. Nor can those calls
    be fired in parallel to make them quick: two of them renumbering one group at
    the same time leave two items claiming the same position, and the board reads
    back ordered by position alone — which is how a row springs back to where it
    was and a move looks like it did nothing.

    So: one authorisation, one query for the items, each group renumbered once,
    one event. The answer carries the new order of every group it touched, so
    the caller can place the rows it already holds instead of asking for the
    board again — and it names the ids it did NOT move, because "12 moved" hides
    the two that were not.
    """
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b or b.deleted_at:
            raise HTTPException(404, "board not found")
        _require_board_edit(db, board_id, actor_id)
        gid = data.get("group_id")
        if gid is not None:
            if not db.query(Group).filter(Group.id == gid, Group.board_id == board_id).first():
                raise HTTPException(404, "הקבוצה לא נמצאה בלוח הזה")
        ids = [i for i in (data.get("ids") or []) if isinstance(i, int)][:500]
        if not ids:
            raise HTTPException(400, "לא נבחרו פריטים")
        # top-level items of THIS board only: a sub-item travels with its parent,
        # and an id from somewhere else is not this board's business to move
        found = {t.id: t for t in db.query(Task).filter(
            Task.board_id == board_id, Task.parent_id == None,          # noqa: E711
            Task.is_archived == False, Task.id.in_(ids)).all()}         # noqa: E712
        picked = [found[i] for i in ids if i in found]                  # the caller's order
        missing = [i for i in ids if i not in found]
        # an item already in the target group is left exactly where it is —
        # re-appending it would reorder a group nobody asked to reorder
        moving = [t for t in picked if t.group_id != gid]
        unchanged = [t.id for t in picked if t.group_id == gid]
        if not moving:
            return {"moved": [], "unchanged": unchanged, "missing": missing, "order": []}
        src_groups = {t.group_id for t in moving}
        # they land at the end of the target group, in the order they were given
        tail = max([t.position or 0 for t in _group_items(db, board_id, gid)], default=-1)
        for i, t in enumerate(moving):
            t.group_id = gid
            t.position = tail + 1 + i
        db.flush()
        touched = {gid} | src_groups
        for g in touched:
            _renumber_group(db, board_id, g)       # dense 0..n-1, order preserved
        db.commit()
        order = [{"group_id": g,
                  "ids": [t.id for t in _group_items(db, board_id, g)]} for g in touched]
        # One event, not one per item. A move between groups changes the list
        # itself, which every client answers with a full refresh anyway — so
        # twelve task.changed events would be twelve refetches of the same board.
        bus.publish("board.changed", board_id=board_id, actor_id=actor_id)
        return {"moved": [{"id": t.id, "group_id": t.group_id, "position": t.position}
                          for t in moving],
                "unchanged": unchanged, "missing": missing, "order": order}

@app.post("/api/tasks/{parent_id}/subitems/reorder")
def reorder_subitems(parent_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Persist a new ordering for one parent's sub-items. data = {order: [subId, ...]}.
    Only ids that truly belong to this parent are repositioned, so a crafted
    payload can never drag a sub-item across parents — the reorder stays inside
    the parent's own frame, exactly like the drag does in the UI."""
    with Session(engine) as db:
        parent = db.query(Task).filter(Task.id == parent_id).first()
        if not parent:
            raise HTTPException(404, "פריט האב לא נמצא")
        _require_board_edit(db, parent.board_id, actor_id)
        order = data.get("order") or []
        subs = {s.id: s for s in db.query(Task).filter(Task.parent_id == parent_id).all()}
        idx = 0
        for sid in order:
            s = subs.get(sid)
            if s is not None:
                s.position = idx
                idx += 1
        db.commit()
        return {"status": "reordered", "order": [sid for sid in order if sid in subs]}

# ── Groups (board columns / קבוצות) ─────────────────────────────────

def _group_dict(g):
    return {"id": g.id, "name": g.name, "position": g.position, "color": g.color,
            "task_status": g.task_status.value if hasattr(g.task_status, 'value') else g.task_status}

@app.post("/api/groups")
def create_group_api(data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        board_id = data.get("board_id")
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            raise HTTPException(404, "board not found")
        # A group is structure, not content — the same kind of decision as a
        # column, and the board's admin makes it. An editor fills the board in:
        # items, values, who is on what. They no longer decide what shelves the
        # board has.
        _require_board_edit(db, board_id, actor_id, need="admin",
                            msg="רק מנהל הלוח יכול להוסיף קבוצות")
        pos = data.get("position")
        if pos is None:
            pos = db.query(Group).filter(Group.board_id == board_id).count()
        try:
            task_status = TaskStatus(data.get("task_status", "todo"))
        except ValueError:
            task_status = TaskStatus.TODO
        g = Group(
            board_id=board_id,
            name=data.get("name", "קבוצה חדשה"),
            position=pos,
            color=data.get("color", "#0073ea"),
            task_status=task_status,
        )
        db.add(g)
        db.commit()
        bus.publish("board.changed", board_id=board_id, actor_id=actor_id)
        db.refresh(g)
        return _group_dict(g)

@app.patch("/api/groups/{group_id}")
def update_group_api(group_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        g = db.query(Group).filter(Group.id == group_id).first()
        if not g:
            raise HTTPException(404, "group not found")
        _require_board_edit(db, g.board_id, actor_id)
        if data.get("name") is not None:
            g.name = data["name"]
        if data.get("color") is not None:
            g.color = data["color"]
        if data.get("position") is not None:
            g.position = data["position"]
        _bid = g.board_id
        db.commit()
        bus.publish("board.changed", board_id=_bid, actor_id=actor_id)
        db.refresh(g)
        return _group_dict(g)

@app.post("/api/groups/reorder")
def reorder_groups_api(data: dict, actor_id: int = Depends(current_user_id)):
    """Persist a new group ordering. data = {order: [groupId, ...]}"""
    with Session(engine) as db:
        order = data.get("order") or []
        actor = actor_id
        if order and actor is not None:
            first = db.query(Group).filter(Group.id == order[0]).first()
            if first:
                _require_board_edit(db, first.board_id, actor)
        _bid = None
        for idx, gid in enumerate(order):
            g = db.query(Group).filter(Group.id == gid).first()
            if g:
                g.position = idx
                _bid = g.board_id
        db.commit()
        bus.publish("board.changed", board_id=_bid, actor_id=actor_id)
        return {"status": "reordered", "order": order}

@app.delete("/api/groups/{group_id}")
def delete_group_api(group_id: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        g = db.query(Group).filter(Group.id == group_id).first()
        if not g:
            raise HTTPException(404, "group not found")
        _require_board_edit(db, g.board_id, actor_id)   # board editors+ only
        # Detach tasks instead of deleting them — they fall back to "ללא קבוצה"
        _bid = g.board_id
        for t in db.query(Task).filter(Task.group_id == group_id).all():
            t.group_id = None
        db.delete(g)
        db.commit()
        bus.publish("board.changed", board_id=_bid, actor_id=actor_id)
        return {"status": "deleted"}

# ── Citizens & Permits ──────────────────────────────────────────────

@app.get("/api/citizen-requests")
def list_citizen_requests():
    with Session(engine) as db:
        reqs = db.query(CitizenRequest).order_by(CitizenRequest.created_at.desc()).limit(50).all()
        return [{
            "id": r.id, "request_type": r.request_type.value if hasattr(r.request_type, 'value') else r.request_type,
            "citizen_name": r.citizen_name, "title": r.title,
            "description": r.description,
            "location_lat": r.location_lat, "location_lng": r.location_lng,
            "address": r.address, "status": r.status,
            "priority": r.priority.value if hasattr(r.priority, 'value') else r.priority,
            "created_at": r.created_at,
        } for r in reqs]

@app.get("/api/permits")
def list_permits():
    with Session(engine) as db:
        permits = db.query(Permit).order_by(Permit.created_at.desc()).limit(50).all()
        return [{
            "id": p.id, "permit_type": p.permit_type.value if hasattr(p.permit_type, 'value') else p.permit_type,
            "permit_number": p.permit_number,
            "applicant_name": p.applicant_name,
            "property_address": p.property_address,
            "description": p.description,
            "status": p.status,
            "submitted_at": p.submitted_at,
        } for p in permits]

# ── GIS / Transport ─────────────────────────────────────────────────

@app.get("/api/transport/stops")
def transport_stops():
    with Session(engine) as db:
        stops = db.query(PublicTransportStop).all()
        features = []
        for s in stops:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
                "properties": {
                    "id": s.id, "stop_code": s.stop_code,
                    "name": s.name, "routes": s.routes or []
                }
            })
        return {"type": "FeatureCollection", "features": features}

@app.get("/api/infrastructure/assets")
def list_assets():
    with Session(engine) as db:
        assets = db.query(InfrastructureAsset).all()
        features = []
        for a in assets:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [a.location_lng, a.location_lat]},
                "properties": {
                    "id": a.id, "name": a.name,
                    "asset_type": a.asset_type, "condition": a.condition,
                    "status": a.status, "properties": a.properties or {}
                }
            })
        return {"type": "FeatureCollection", "features": features}

def _utc_iso(dt):
    """A stored timestamp as an ISO string that says which zone it is in.

    These are written with datetime.now(timezone.utc), but the column is a plain
    DateTime, so SQLAlchemy drops the offset and hands the value back naive. It
    was then serialised naive too — "2026-10-15T08:22:02" with nothing to say
    that is UTC — and ECMAScript reads a date-time with no offset as LOCAL time.
    Every login therefore displayed three hours early in Israel: not a different
    zone, a wrong time.

    Naive means UTC here, because that is what wrote it. An aware value is left
    alone, so a column later migrated to timezone=True needs no change.
    """
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ── Users ────────────────────────────────────────────────────────────

@app.get("/api/users")
def list_users():
    with Session(engine) as db:
        users = db.query(User).all()
        dept_names = {d.id: d.name for d in db.query(Department).all()}
        # most-recent login per user (for the admin directory "last login" column)
        from sqlalchemy import func as _func
        last_logins = dict(
            db.query(LoginEvent.user_id, _func.max(LoginEvent.logged_in_at)).group_by(LoginEvent.user_id).all()
        )
        _iso = _utc_iso
        return [{
            "id": u.id, "name": u.name, "email": u.email,
            "role": u.role, "avatar_url": u.avatar_url,
            "department_id": u.department_id,
            "department_name": dept_names.get(u.department_id),
            "is_active": bool(u.is_active) if u.is_active is not None else True,
            "phone": u.phone, "title": u.title,
            "last_login": _iso(last_logins.get(u.id)),
            "email_notifications": bool(u.email_notifications) if u.email_notifications is not None else True,
            "notif_prefs": u.notif_prefs or {},
        } for u in users]

@app.post("/api/auth/login")
async def record_login(request: Request, actor_id: int = Depends(current_user_id)):
    """Record a successful login for the admin login-history view.

    The recorded identity is the authenticated one — the client used to name the
    user it wanted logged, which made the audit trail forgeable."""
    with Session(engine) as db:
        u = db.query(User).filter(User.id == actor_id).first()
        if not u:
            raise HTTPException(404, "user not found")
        ev = LoginEvent(
            user_id=actor_id,
            ip=(request.client.host if request.client else None),
            user_agent=(request.headers.get("user-agent") or "")[:400],
        )
        db.add(ev)
        db.commit()
        return {"status": "ok", "logged_in_at": _utc_iso(ev.logged_in_at)}

@app.get("/api/auth/me")
def whoami(request: Request):
    """The signed-in user, resolved from the Entra identity on the request.
    The SPA calls this at boot instead of letting the visitor pick a user."""
    u = current_user(request)
    with Session(engine) as db:
        return {
            "id": u.id, "name": u.name, "email": u.email, "role": u.role,
            "avatar_url": u.avatar_url, "title": u.title,
            "ws_role": _ws_role(db, u.id),
            "auth_mode": auth_mode(),
        }


@app.get("/api/auth/dev-users")
def dev_picker_users():
    """The directory the local picker offers. Dev mode only.

    Signed out there is no identity to read /api/users with, and the way round
    it was for the picker to sign in as user 1, then 2, then 3 and try each. Those
    are the ids the demo seed happens to create: on a database whose demo users
    have been removed — which is what a real local database looks like after a
    while — all three are refused, the picker's list comes back empty, and the
    login screen says "אין משתמשים" with no way past it.

    Not an opening: dev mode already accepts any user id from a header or a
    cookie, so anyone who can reach this server can already act as anyone on it.
    That is why dev mode must never be on in production (main prints the warning
    at boot), and why this route answers 404 — not 403 — in every other mode:
    outside dev it does not exist.
    """
    if auth_mode() != "dev":
        raise HTTPException(404, "not found")
    with Session(engine) as db:
        users = (db.query(User).filter(User.is_active.isnot(False))
                 .order_by(User.id).all())
        return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role,
                 "avatar_url": u.avatar_url} for u in users]


@app.get("/api/users/{uid}/login-history")
def login_history(uid: int, actor_id: int = Depends(current_user_id), limit: int = 50):
    """Login history for a user — visible to system (workspace) admins only."""
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול לראות היסטוריית התחברות")
        if not db.query(User.id).filter(User.id == uid).scalar():
            raise HTTPException(404, "user not found")
        evs = (db.query(LoginEvent).filter(LoginEvent.user_id == uid)
               .order_by(LoginEvent.logged_in_at.desc()).limit(max(1, min(limit, 200))).all())
        return [{
            "logged_in_at": _utc_iso(e.logged_in_at),
            "ip": e.ip, "user_agent": e.user_agent,
        } for e in evs]

@app.get("/api/login-history")
def all_login_history(actor_id: int = Depends(current_user_id), limit: int = 100):
    """Consolidated login history across all users — system admins only."""
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול לראות היסטוריית התחברות")
        names = {u.id: (u.name, u.avatar_url) for u in db.query(User).all()}
        evs = (db.query(LoginEvent).order_by(LoginEvent.logged_in_at.desc())
               .limit(max(1, min(limit, 500))).all())
        return [{
            "user_id": e.user_id,
            "user_name": names.get(e.user_id, ("—", None))[0],
            "avatar_url": names.get(e.user_id, ("—", None))[1],
            "logged_in_at": _utc_iso(e.logged_in_at),
            "ip": e.ip, "user_agent": e.user_agent,
        } for e in evs]

@app.post("/api/users")
def create_user(data: dict, actor_id: int = Depends(current_user_id)):
    """Create a new user in the workspace directory. System (workspace) admin only."""
    with Session(engine) as db:
        actor = actor_id
        if not _cap(db, actor, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול להוסיף משתמש")
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        if not name:
            raise HTTPException(400, "חסר שם משתמש")
        if not email:
            raise HTTPException(400, "חסרה כתובת מייל")
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(409, "כתובת המייל כבר קיימת במערכת")
        role = data.get("role") if data.get("role") in ("admin", "manager", "member", "viewer", "guest") else "member"
        dept_id = data.get("department_id") or None
        # inherit the organization of an existing user so the new user is in the same workspace
        org_id = db.query(User.organization_id).filter(User.organization_id != None).limit(1).scalar()
        u = User(name=name, email=email, role=role, department_id=dept_id,
                 organization_id=org_id, is_active=True)
        db.add(u)
        db.flush()
        # also register workspace membership so the role actually takes effect
        # (system-admin capabilities key off workspace_members, not User.role)
        db.add(WorkspaceMember(user_id=u.id, role=_ws_role_for(role)))
        db.commit()
        db.refresh(u)
        dept_name = db.query(Department.name).filter(Department.id == u.department_id).scalar() if u.department_id else None
        return {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
                "department_id": u.department_id, "department_name": dept_name,
                "is_active": True, "avatar_url": u.avatar_url}

@app.patch("/api/users/{uid}")
def update_user(uid: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Update a user's profile. A user may edit their own profile; a system
    (workspace) admin may edit anyone's."""
    with Session(engine) as db:
        actor = actor_id
        if actor != uid and not _cap(db, actor, "manage_system"):
            raise HTTPException(403, "אפשר לעדכן רק את הפרופיל שלך")
        u = db.query(User).filter(User.id == uid).first()
        if not u:
            raise HTTPException(404, "user not found")
        for f in ("avatar_url", "phone", "title", "name", "email_notifications"):
            if f in data:
                setattr(u, f, data[f])
        if "email" in data:
            new_email = (data["email"] or "").strip().lower()
            if new_email and new_email != u.email:
                if db.query(User).filter(User.email == new_email, User.id != uid).first():
                    raise HTTPException(409, "כתובת המייל כבר קיימת במערכת")
                u.email = new_email
        if "notif_prefs" in data and isinstance(data["notif_prefs"], dict):
            u.notif_prefs = {**(u.notif_prefs or {}), **data["notif_prefs"]}
        # sensitive fields (role / department / active status) — system admin only,
        # never editable on one's own profile via this path
        admin_fields = {"role", "department_id", "is_active"}
        if admin_fields & set(data):
            if not _cap(db, actor, "manage_system"):
                raise HTTPException(403, "רק מנהל מערכת יכול לשנות תפקיד, מחלקה או סטטוס")
            if "role" in data and data["role"] in ("admin", "manager", "member", "viewer", "guest"):
                u.role = data["role"]
                _sync_ws_role(db, u)   # the row the rest of the system reads
            if "department_id" in data:
                u.department_id = data["department_id"]
            if "is_active" in data:
                if u.id == actor and not data["is_active"]:
                    raise HTTPException(400, "אי אפשר להשבית את המשתמש שלך")
                u.is_active = bool(data["is_active"])
        db.commit()
        dept_name = None
        if u.department_id:
            d = db.query(Department).filter(Department.id == u.department_id).first()
            dept_name = d.name if d else None
        return {"id": u.id, "name": u.name, "email": u.email, "avatar_url": u.avatar_url,
                "phone": u.phone, "title": u.title, "role": u.role,
                "department_id": u.department_id, "department_name": dept_name,
                "is_active": bool(u.is_active),
                "email_notifications": bool(u.email_notifications),
                "notif_prefs": u.notif_prefs or {}}


# ── Guests (external people, invited into Entra ID) ──────────────────
# The screen behind these lives in the system-administration modal. Inviting is
# two directory operations and one row of ours, deliberately in that order: the
# tenant is the thing that decides whether a person can sign in at all, so if it
# refuses we have not left a local account that can never be used.
#
# See backend/entra_guests.py for the Graph calls and scripts/ENTRA_GUESTS.md
# for the app-registration permissions and the QA configuration.

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def _guest_row(u: User, dept_names: dict, directory: dict, directory_read: bool):
    """One guest, as the screen shows them: our row plus what Entra says.

    `directory_read` is separate from `directory` being non-empty on purpose. A
    group somebody has just emptied and a Graph call that failed both arrive
    here as {}, and they mean opposite things — "this person lost their access"
    versus "we do not currently know". Only the first should light up the screen.
    """
    d = directory.get((u.entra_object_id or "").lower(), {})
    return {
        "id": u.id, "name": u.name, "email": u.email,
        "role": u.role, "avatar_url": u.avatar_url,
        "department_id": u.department_id,
        "department_name": dept_names.get(u.department_id),
        "is_active": bool(u.is_active) if u.is_active is not None else True,
        "entra_object_id": u.entra_object_id,
        # Only the directory knows these, and only when Graph answered.
        "in_group": bool(d) if directory_read else None,
        "invite_state": d.get("invite_state"),
    }


@app.get("/api/guests")
def list_guests(actor_id: int = Depends(current_user_id)):
    """The invited guests, and whether this deployment can invite any.

    The directory read is best-effort on purpose: when Graph is unreachable or
    unconsented the screen still lists who we invited and says why the live
    state is missing, instead of showing nothing at all.
    """
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול לנהל אורחים")
        dept_names = {d.id: d.name for d in db.query(Department).all()}
        users = (db.query(User).filter(User.entra_object_id != None)  # noqa: E711
                 .order_by(User.name).all())

    directory, directory_error, directory_read = {}, None, False
    if entra_guests.is_enabled() and entra_guests.is_configured():
        try:
            directory = {m["object_id"].lower(): m for m in entra_guests.group_members()
                         if m.get("object_id")}
            directory_read = True
        except HTTPException as exc:
            directory_error = str(exc.detail)
        except Exception as exc:                      # never break the screen
            directory_error = str(exc)

    return {
        "enabled": entra_guests.is_enabled(),
        "configured": entra_guests.is_configured(),
        "group": entra_guests.group_name(),
        "directory_error": directory_error,
        "guests": [_guest_row(u, dept_names, directory, directory_read) for u in users],
    }


@app.post("/api/guests")
def invite_guest(data: dict, actor_id: int = Depends(current_user_id)):
    """Invite an external address as an Entra ID guest, into the guests group,
    and give it an account here. System (workspace) admin only."""
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול להזמין אורחים")

    entra_guests.require_available()

    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    if not email:
        raise HTTPException(400, "חסרה כתובת מייל")
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "כתובת המייל אינה תקינה")
    if not name:
        name = email.split("@")[0]

    # An address that already belongs to a regular member of the organization is
    # not a guest, and quietly converting one into the other would take away
    # whatever they had. Re-inviting somebody who IS a guest is fine — that is
    # how an invitation gets resent.
    with Session(engine) as db:
        existing = db.query(User).filter(func.lower(User.email) == email).first()
        if existing and not existing.entra_object_id:
            raise HTTPException(409, "כתובת המייל כבר קיימת כמשתמש רגיל במערכת")
        existing_id = existing.id if existing else None

    invited = entra_guests.invite(
        email, name,
        send_email=data.get("send_invitation_email", True) is not False,
        message=(data.get("message") or "").strip(),
    )
    try:
        added = entra_guests.add_to_group(invited["object_id"])
    except HTTPException as exc:
        # The person now exists in the tenant but is not in the group, so they
        # are not a guest of *this* system yet. Say exactly that: pressing
        # invite again is safe, because both directory calls are idempotent.
        raise HTTPException(exc.status_code,
                            f"ההזמנה נוצרה ב-Entra אך הוספה לקבוצה "
                            f"'{entra_guests.group_name()}' נכשלה — אפשר לנסות שוב. "
                            f"{exc.detail}")

    dept_id = data.get("department_id") or None
    with Session(engine) as db:
        u = db.query(User).filter(User.id == existing_id).first() if existing_id else None
        if u:
            u.entra_object_id = invited["object_id"]
            if dept_id is not None:
                u.department_id = dept_id
            u.is_active = True          # re-inviting a revoked guest restores them
        else:
            org_id = db.query(User.organization_id).filter(User.organization_id != None).limit(1).scalar()  # noqa: E711
            u = User(name=name, email=email, role="guest", department_id=dept_id,
                     organization_id=org_id, is_active=True,
                     entra_object_id=invited["object_id"])
            db.add(u)
            db.flush()
        # Same as create_user: the row most of the system actually reads for a
        # role is the workspace membership, not User.role.
        if not db.query(WorkspaceMember).filter(WorkspaceMember.user_id == u.id).first():
            db.add(WorkspaceMember(user_id=u.id, role=_ws_role_for("guest")))
        db.commit()
        db.refresh(u)
        dept_names = {d.id: d.name for d in db.query(Department).all()}
        row = _guest_row(u, dept_names, {}, False)

    row["added_to_group"] = added
    row["in_group"] = True
    row["invite_state"] = invited.get("invite_state")
    # Present only when the admin chose not to have Entra send the mail; then
    # this link IS the invitation and somebody has to pass it on.
    row["redeem_url"] = invited.get("redeem_url")
    return row


@app.delete("/api/guests/{uid}")
def revoke_guest(uid: int, actor_id: int = Depends(current_user_id)):
    """Take a guest out of the guests group and deactivate their account here.

    The directory account itself is left alone. Deleting a person from the
    tenant is a directory-wide act with consequences outside this system — other
    apps, other groups, their files — and it is not this screen's to make. What
    this screen granted, it revokes: membership of the group, and the ability to
    sign in here.
    """
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול להסיר אורחים")
        u = db.query(User).filter(User.id == uid).first()
        if not u:
            raise HTTPException(404, "המשתמש לא נמצא")
        if not u.entra_object_id:
            raise HTTPException(400, "המשתמש אינו אורח שהוזמן דרך המסך הזה")
        object_id = u.entra_object_id

    entra_guests.require_available()
    removed = entra_guests.remove_from_group(object_id)

    with Session(engine) as db:
        u = db.query(User).filter(User.id == uid).first()
        if u:
            u.is_active = False
            db.commit()
    return {"status": "ok", "id": uid, "removed_from_group": removed}


# ── deleting a person, for good ──────────────────────────────────────
# What an irreversible deletion has to decide, per table: does the row GO, or
# does it merely stop naming this person?
#
# It goes when the row IS the person's relationship to something — a membership,
# an assignment, a notification, a saved view — or something they authored that
# was asked to be erased with them: their messages, and the log rows recording
# what they did.
#
# It only stops naming them when the row belongs to the municipality and would
# be destroyed with them: the item somebody created, the board they deleted, the
# permit assigned to them, the automation they own. Deleting a person is not
# deleting their work, so the pointer is cleared and the object stays. An
# automation left without an owner is already a case the system knows (it shows
# as "דורשת שיוך בעלים"); an item without a creator reads as "טרם הוגדר", like
# one imported from elsewhere.
USER_PURGE_DELETE = [
    # the person's own place in things
    ("board_members", "user_id"), ("environment_members", "user_id"),
    ("workspace_members", "user_id"), ("task_assignees", "user_id"),
    ("notifications", "user_id"), ("board_views", "user_id"),
    ("login_events", "user_id"),
    # what they wrote and what they did
    ("comments", "user_id"), ("audit_logs", "changed_by"),
    ("automation_runs", "actor_id"), ("automation_versions", "changed_by"),
    ("automation_test_runs", "tested_by"),
]
USER_PURGE_NULL = [
    ("tasks", "created_by"), ("tasks", "deleted_by"), ("boards", "deleted_by"),
    ("environments", "created_by"), ("item_links", "created_by"),
    ("documents", "uploaded_by"),
    ("automations", "created_by"), ("automations", "updated_by"),
    ("automations", "owner_id"),
    ("automation_freezes", "created_by"), ("automation_freezes", "released_by"),
    ("permits", "assigned_to"), ("citizen_requests", "assigned_to"),
    ("projects", "manager_id"), ("project_steps", "owner_id"),
    ("approvals", "approver_user_id"),
    ("change_requests", "requested_by"), ("change_requests", "approved_by"),
]


@app.delete("/api/users/{uid}")
def delete_user(uid: int, actor_id: int = Depends(current_user_id)):
    """Erase a person from the system. Irreversible, and system admin only.

    The system could only ever deactivate somebody — `is_active=False`, the
    account kept in the directory — which is the right default and was the only
    thing on offer. An account that should never have existed here, or a person
    who has asked to be removed, needs the other thing, and there was no way to
    do it but by hand in the database.

    Three accounts it refuses: your own (an admin locking themselves out of the
    system by accident), the last workspace admin (nobody left who could undo
    it), and the automation engine's identity, which is not a person at all and
    is what the engine's own writes are attributed to.

    The answer reports what went, table by table, because "the user is gone" is
    not something anyone should have to take on trust.

    Deliberately NOT reachable from the UI. It was built with a button in the
    system-admin screen and used once, for an account that should never have
    existed here; the button came out immediately afterwards, because a rare
    irreversible act does not belong one click away from a rename. Reaching this
    takes an explicit call, which is the friction it should have.
    """
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול למחוק משתמש")
        u = db.query(User).filter(User.id == uid).first()
        if not u:
            raise HTTPException(404, "המשתמש לא נמצא")
        if actor_id is not None and int(uid) == int(actor_id):
            raise HTTPException(400, "אי אפשר למחוק את החשבון שאיתו אתה מחובר")
        if (u.email or "").lower() == AUTOMATION_IDENTITY_EMAIL:
            raise HTTPException(400, "זהות מנוע האוטומציות אינה אדם ואינה נמחקת")
        if _ws_role(db, uid) == "admin":
            admins = (db.query(WorkspaceMember)
                        .filter(WorkspaceMember.role == "admin").count())
            if admins <= 1:
                raise HTTPException(400, "חייב להישאר מנהל מערכת אחד לפחות")
        who = {"id": u.id, "email": u.email, "name": u.name, "role": u.role}

        report = {}
        for table, col in USER_PURGE_DELETE:
            n = _purge_rows(db, f"DELETE FROM {table} WHERE {col} = :uid", uid)
            if n:
                report[f"{table}.{col}"] = {"deleted": n}
        for table, col in USER_PURGE_NULL:
            n = _purge_rows(db, f"UPDATE {table} SET {col} = NULL WHERE {col} = :uid", uid)
            if n:
                report[f"{table}.{col}"] = {"cleared": n}

        # The one trace that must survive: that this person was erased, by whom
        # and when. It is attributed to the actor, so it is not swept up by the
        # audit rows being deleted above.
        _audit(db, uid, "delete", "user",
               f"{who['name']} <{who['email']}>", "", actor_id)
        db.delete(u)
        db.commit()
        print(f"[users] purged #{who['id']} {who['email']} by {actor_id}: "
              f"{sum(v.get('deleted', 0) for v in report.values())} row(s) deleted, "
              f"{sum(v.get('cleared', 0) for v in report.values())} cleared", flush=True)
        return {"status": "ok", "deleted": who, "affected": report}


def _purge_rows(db, sql, uid):
    """One statement of the purge. A table this deployment does not have is not
    an error — the schema grew over time and an older database may predate it."""
    from sqlalchemy import text
    try:
        return db.execute(text(sql), {"uid": uid}).rowcount or 0
    except Exception as e:                           # noqa: BLE001
        db.rollback()
        print(f"[users] purge skipped ({e.__class__.__name__}): {sql}", flush=True)
        return 0


@app.get("/api/departments")
def list_departments():
    with Session(engine) as db:
        depts = db.query(Department).order_by(Department.name).all()
        from sqlalchemy import func as _func
        ucount = dict(db.query(User.department_id, _func.count(User.id))
                      .filter(User.department_id != None).group_by(User.department_id).all())
        bcount = dict(db.query(Board.department_id, _func.count(Board.id))
                      .filter(Board.department_id != None).group_by(Board.department_id).all())
        return [{
            "id": d.id, "name": d.name, "code": d.code, "color": d.color,
            "organization_id": d.organization_id,
            "user_count": ucount.get(d.id, 0), "board_count": bcount.get(d.id, 0),
        } for d in depts]

DEPT_COLORS = ("#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
               "#06b6d4", "#ef4444", "#6366f1", "#14b8a6", "#f97316")


@app.post("/api/departments")
def create_department(data: dict, actor_id: int = Depends(current_user_id)):
    """Create an organizational unit (department). System (workspace) admin only."""
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול להוסיף יחידה ארגונית")
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "חסר שם ליחידה הארגונית")
        if db.query(Department).filter(func.lower(Department.name) == name.lower()).first():
            raise HTTPException(409, "יחידה ארגונית בשם זה כבר קיימת")
        org_id = db.query(User.organization_id).filter(User.organization_id != None).limit(1).scalar()
        color = (data.get("color") or "").strip() or DEPT_COLORS[db.query(Department).count() % len(DEPT_COLORS)]
        d = Department(name=name, code=(data.get("code") or "").strip() or None,
                       color=color, organization_id=org_id)
        db.add(d)
        db.commit()
        db.refresh(d)
        return {"id": d.id, "name": d.name, "code": d.code, "color": d.color,
                "organization_id": d.organization_id, "user_count": 0, "board_count": 0}


@app.patch("/api/departments/{dept_id}")
def update_department(dept_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    """Rename / recolor an organizational unit. System (workspace) admin only."""
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול לערוך יחידה ארגונית")
        d = db.query(Department).filter(Department.id == dept_id).first()
        if not d:
            raise HTTPException(404, "יחידה ארגונית לא נמצאה")
        if "name" in data:
            name = (data["name"] or "").strip()
            if not name:
                raise HTTPException(400, "חסר שם ליחידה הארגונית")
            if db.query(Department).filter(func.lower(Department.name) == name.lower(),
                                           Department.id != dept_id).first():
                raise HTTPException(409, "יחידה ארגונית בשם זה כבר קיימת")
            d.name = name
        if "code" in data:
            d.code = (data["code"] or "").strip() or None
        if "color" in data and data["color"]:
            d.color = data["color"].strip()
        db.commit()
        return {"id": d.id, "name": d.name, "code": d.code, "color": d.color}


@app.delete("/api/departments/{dept_id}")
def delete_department(dept_id: int, actor_id: int = Depends(current_user_id)):
    """Delete an organizational unit. System admin only. Any users/boards attached
    to it are detached (department set to none) rather than deleted."""
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול למחוק יחידה ארגונית")
        d = db.query(Department).filter(Department.id == dept_id).first()
        if not d:
            raise HTTPException(404, "יחידה ארגונית לא נמצאה")
        # detach references so nothing is orphaned or violates a FK
        db.query(User).filter(User.department_id == dept_id).update({User.department_id: None})
        db.query(Board).filter(Board.department_id == dept_id).update({Board.department_id: None})
        db.query(Project).filter(Project.department_id == dept_id).update({Project.department_id: None})
        db.delete(d)
        db.commit()
        return {"status": "deleted", "id": dept_id}

# ── Role permissions (capability matrix) ─────────────────────────────

@app.get("/api/role-permissions")
def get_role_permissions():
    """The capability matrix. Readable by anyone so the client can gate features.
    'admin' is returned as an always-on, locked row."""
    with Session(engine) as db:
        matrix = _role_perms(db)
    roles = [{"key": "admin", "he": ROLE_HE_BE["admin"], "locked": True}] + \
            [{"key": r, "he": ROLE_HE_BE.get(r, r), "locked": False} for r in EDITABLE_ROLES]
    matrix_out = {"admin": {cap: True for cap in CAPABILITIES}, **matrix}
    return {
        "capabilities": [{"key": c, "he": CAP_HE[c]} for c in CAPABILITIES],
        "roles": roles,
        "matrix": matrix_out,
    }

@app.put("/api/role-permissions")
def set_role_permission(data: dict, actor_id: int = Depends(current_user_id)):
    """Toggle one (role, capability) cell. System-management capability required."""
    with Session(engine) as db:
        if not _cap(db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול לשנות הרשאות תפקידים")
        role = data.get("role")
        cap = data.get("capability")
        if role not in EDITABLE_ROLES:
            raise HTTPException(400, "תפקיד לא ניתן לעריכה")
        if cap not in CAPABILITIES:
            raise HTTPException(400, "יכולת לא מוכרת")
        allowed = bool(data.get("allowed"))
        row = (db.query(RolePermission)
               .filter(RolePermission.role == role, RolePermission.capability == cap).first())
        if row:
            row.allowed = allowed
        else:
            db.add(RolePermission(role=role, capability=cap, allowed=allowed))
        db.commit()
        return {"role": role, "capability": cap, "allowed": allowed, "matrix": _role_perms(db)}

# ── Agent Swarm ───────────────────────────────────────────────────────

from swarm import get_swarm

@app.get("/api/swarm/agents")
def list_agents():
    swarm = get_swarm()
    return {"agents": [
        {"id": k, "name": v.name, "role": v.role}
        for k, v in swarm.agents.items()
    ]}

@app.post("/api/swarm/think")
def swarm_think(data: dict, actor_id: int = Depends(current_user_id)):
    """Run agents on a task. mode: single|all|coordinated"""
    from swarm import swarm_api
    result = swarm_api(
        agent=data.get("agent", ""),
        task=data.get("task", ""),
        context=data.get("context"),
        mode=data.get("mode", "single")
    )
    return result

# ── Form Templates ──────────────────────────────────────────────────

FORM_TEMPLATES = {
    "building_permit": {
        "name": "בקשה להיתר בנייה",
        "fields": [
            {"id": "applicant_name", "label": "שם המבקש", "type": "text", "required": True},
            {"id": "applicant_id", "label": "תז", "type": "text", "required": True},
            {"id": "phone", "label": "טלפון", "type": "tel", "required": True},
            {"id": "email", "label": "אימייל", "type": "email"},
            {"id": "property_address", "label": "כתובת הנכס", "type": "text", "required": True},
            {"id": "gush", "label": "גוש", "type": "text"},
            {"id": "helka", "label": "חלקה", "type": "text"},
            {"id": "permit_type", "label": "סוג היתר", "type": "select", "options": ["בנייה חדשה", "הרחבה", "שינוי ייעוד", "הריסה", "עבודות תשתית"]},
            {"id": "description", "label": "תיאור העבודות", "type": "textarea", "required": True},
            {"id": "area_sqm", "label": "שטח (מטר)", "type": "number"},
            {"id": "attachments", "label": "קבצים מצורפים", "type": "file", "multiple": True},
        ]
    },
    "citizen_request": {
        "name": "פניית תושב",
        "fields": [
            {"id": "citizen_name", "label": "שם מלא", "type": "text", "required": True},
            {"id": "phone", "label": "טלפון", "type": "tel", "required": True},
            {"id": "email", "label": "אימייל", "type": "email"},
            {"id": "request_type", "label": "סוג פנייה", "type": "select", "options": ["תקלה בכביש", "תאורת רחוב", "פסולת/ניקיון", "מים/ביוב", "גינה ציבורית", " רעש", "תחבורה ציבורית", "אחר"]},
            {"id": "title", "label": "כותרת", "type": "text", "required": True},
            {"id": "description", "label": "תיאור", "type": "textarea", "required": True},
            {"id": "address", "label": "כתובת מדויקת", "type": "text"},
            {"id": "location", "label": "מיקום במפה", "type": "location"},
            {"id": "photo", "label": "צילום", "type": "file"},
        ]
    },
    "event_permit": {
        "name": "בקשה לאישור אירוע",
        "fields": [
            {"id": "organizer_name", "label": "שם המארגן", "type": "text", "required": True},
            {"id": "organizer_phone", "label": "טלפון", "type": "tel", "required": True},
            {"id": "event_name", "label": "שם האירוע", "type": "text", "required": True},
            {"id": "event_type", "label": "סוג אירוע", "type": "select", "options": ["הרצאה", "מוזיקה", "ספורט", "יריד", "הפגנה", "אחר"]},
            {"id": "expected_attendees", "label": "משתתפים צפויים", "type": "number"},
            {"id": "event_date", "label": "תאריך האירוע", "type": "date", "required": True},
            {"id": "event_time", "label": "שעה", "type": "time"},
            {"id": "location", "label": "מיקום", "type": "text", "required": True},
            {"id": "description", "label": "תיאור האירוע", "type": "textarea"},
        ]
    },
}

@app.get("/api/forms/templates")
def list_form_templates():
    return {"templates": [
        {"id": k, "name": v["name"], "fields_count": len(v["fields"])}
        for k, v in FORM_TEMPLATES.items()
    ]}

@app.get("/api/forms/templates/{template_id}")
def get_form_template(template_id: str):
    if template_id not in FORM_TEMPLATES:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return FORM_TEMPLATES[template_id]

@app.post("/api/forms/submit")
def submit_form(data: dict):
    """Submit form data and create a task."""
    template_id = data.get("template_id", "")
    form_data = data.get("form_data", {})
    with Session(engine) as db:
        task = Task(
            board_id=data.get("board_id", 3),  # Default to citizen requests
            title=form_data.get("title") or form_data.get("applicant_name") or f"טופס: {template_id}",
            description=json.dumps(form_data, ensure_ascii=False),
            custom_fields=form_data,
        )
        db.add(task)
        db.commit()
        return {"id": task.id, "status": "submitted"}

# ── Visualization Engine ─────────────────────────────────────────────

@app.get("/api/viz/board-insights")
def board_insights(user_id: int = Depends(current_user_id)):
    """Generate visualization data and insights for boards the user may see."""
    with Session(engine) as db:
        visible = _visible_board_ids(db, user_id)
        boards = db.query(Board).filter(
            Board.is_archived == False, Board.deleted_at == None, Board.id.in_(visible)
        ).all() if visible else []
        insights = []
        for b in boards:
            tasks = db.query(Task).filter(Task.board_id == b.id).all()
            if not tasks:
                continue
            
            # Status distribution
            status_dist = {}
            priority_dist = {}
            overdue = 0
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
            
            for t in tasks:
                s = t.status.value if hasattr(t.status, 'value') else t.status
                p = t.priority.value if hasattr(t.priority, 'value') else t.priority
                status_dist[s] = status_dist.get(s, 0) + 1
                priority_dist[p] = priority_dist.get(p, 0) + 1
                due = t.due_date
                if due and hasattr(due, 'tzinfo') and due.tzinfo:
                    due = due.replace(tzinfo=None)
                if due and due < now and s not in ("done", "cancelled"):
                    overdue += 1
            
            insights.append({
                "board_id": b.id,
                "board_name": b.name,
                "icon": b.icon,
                "department": dept_name,
                "total_tasks": len(tasks),
                "status_distribution": status_dist,
                "priority_distribution": priority_dist,
                "overdue_count": overdue,
                "completion_rate": round(status_dist.get("done", 0) / max(len(tasks), 1) * 100, 1),
            })
        
        return {"boards": insights, "total": len(insights)}

@app.get("/api/viz/timeline")
def viz_timeline(days: int = 30):
    """Task timeline data for Gantt-like visualization."""
    with Session(engine) as db:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        tasks = db.query(Task).filter(
            Task.created_at >= cutoff
        ).order_by(Task.created_at).all()
        
        # Group by day
        daily = {}
        for t in tasks:
            day = t.created_at.strftime("%Y-%m-%d") if t.created_at else "unknown"
            if day not in daily:
                daily[day] = 0
            daily[day] += 1
        
        return {"timeline": [{"date": d, "count": c} for d, c in sorted(daily.items())]}

# ── Obsidian-like Graph ─────────────────────────────────────────────

@app.get("/api/graph/context")
def graph_context():
    """Generate a knowledge graph of all tasks, boards, and their connections."""
    with Session(engine) as db:
        boards = db.query(Board).filter(Board.is_archived == False, Board.deleted_at == None).all()
        tasks = db.query(Task).filter(Task.is_archived == False).all()
        users = db.query(User).all()
        
        nodes = []
        edges = []
        
        # Board nodes
        for b in boards:
            nodes.append({
                "id": f"board_{b.id}", "label": b.name, "type": "board",
                "icon": b.icon, "color": b.color
            })
        
        # Task nodes
        for t in tasks:
            nodes.append({
                "id": f"task_{t.id}", "label": t.title[:30], "type": "task",
                "status": t.status.value if hasattr(t.status, 'value') else t.status,
                "priority": t.priority.value if hasattr(t.priority, 'value') else t.priority,
            })
            edges.append({
                "source": f"task_{t.id}", "target": f"board_{t.board_id}",
                "type": "belongs_to"
            })
        
        # User nodes
        for u in users:
            nodes.append({
                "id": f"user_{u.id}", "label": u.name, "type": "user",
                "role": u.role
            })
        
        # Assignee edges
        for t in tasks:
            if t.assignees:
                for a in t.assignees:
                    edges.append({
                        "source": f"user_{a.id}", "target": f"task_{t.id}",
                        "type": "assigned_to"
                    })
        
        return {"nodes": nodes, "edges": edges}

# ── AI Assistant ─────────────────────────────────────────────────────

# ── Tool Definitions ────────────────────────────────────────────────

AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_boards",
            "description": "רשימת כל הלוחות (boards) במערכת",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_board",
            "description": "קבלת פרטי לוח לפי ID",
            "parameters": {
                "type": "object",
                "properties": {"board_id": {"type": "integer", "description": "מזהה הלוח"}},
                "required": ["board_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "רשימת פרויקטים (ניתן לסנן לפי department_id)",
            "parameters": {
                "type": "object",
                "properties": {
                    "department_id": {"type": "integer", "description": "מזהה אגף (אופציונלי)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_board",
            "description": "יצירת לוח חדש במערכת",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "שם הלוח"},
                    "department_id": {"type": "integer", "description": "מזהה האגף (השתמש ב-1 כברירת מחדל)"},
                    "description": {"type": "string", "description": "תיאור הלוח"},
                    "icon": {"type": "string", "description": "אימוג'י ללוח, ברירת מחדל 📋"},
                    "color": {"type": "string", "description": "צבע לוח. מותר: #0073ea, #00c875, #fdab3d, #e2445c, #579bfc, #c4c4c4"},
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_group",
            "description": "יצירת עמודה/קבוצה בלוח",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {"type": "integer", "description": "מזהה הלוח"},
                    "name": {"type": "string", "description": "שם הקבוצה/עמודה"},
                    "position": {"type": "integer", "description": "מיקום (0 = ראשון)"},
                    "color": {"type": "string", "description": "צבע"},
                    "task_status": {"type": "string", "description": "סטטוס: backlog/todo/in_progress/review/done/cancelled/on_hold"},
                },
                "required": ["board_id", "name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "יצירת משימה (פריט) חדשה בלוח. חובה רק board_id ו-title. אם לא צוינה קבוצה — המשימה תיכנס לקבוצה הראשונה בלוח. מלא רק שדות שהמשתמש ביקש במפורש.",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {"type": "integer", "description": "מזהה הלוח"},
                    "group_id": {"type": "integer", "description": "מזהה הקבוצה/עמודה (אופציונלי; ברירת מחדל: הקבוצה הראשונה בלוח)"},
                    "title": {"type": "string", "description": "כותרת המשימה"},
                    "description": {"type": "string", "description": "תיאור המשימה (אופציונלי — השאר ריק אם לא צוין)"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical", "emergency"], "description": "עדיפות (אופציונלי; ברירת מחדל: medium)"},
                    "status": {"type": "string", "enum": ["backlog", "todo", "in_progress", "review", "done", "cancelled", "on_hold"], "description": "סטטוס (אופציונלי; ברירת מחדל: backlog)"},
                    "due_date": {"type": "string", "description": "תאריך יעד בפורמט ISO (אופציונלי)"},
                },
                "required": ["board_id", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "עדכון משימה קיימת",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "מזהה המשימה"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["backlog", "todo", "in_progress", "review", "done", "cancelled", "on_hold"]},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical", "emergency"]},
                    "due_date": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "מחיקת משימה (ארכון)",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "מזהה המשימה למחיקה"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_departments",
            "description": "רשימת כל האגפים במערכת",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_users",
            "description": "רשימת כל המשתמשים במערכת",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_project",
            "description": "יצירת פרויקט חדש במסגרת תוכנית העבודה",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "שם הפרויקט"},
                    "department_id": {"type": "integer", "description": "מזהה האגף"},
                    "work_plan_id": {"type": "integer", "description": "מזהה תוכנית עבודה, ברירת מחדל 1"},
                    "planned_budget": {"type": "number", "description": "תקציב מתוכנן"},
                    "status": {"type": "string", "enum": ["draft", "planning", "in_progress", "completed", "cancelled", "on_hold"]},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "manager_name": {"type": "string", "description": "שם מנהל הפרויקט (יחפש משתמש לפי שם)"}
                },
                "required": ["name", "department_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_detail",
            "description": "קבלת פרטי פרויקט מלאים (עם שלבים, תקציב, KPI, אישורים)",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "integer"}},
                "required": ["project_id"]
            }
        }
    },
]


def _ai_board_guard(db, board_id, actor, need="editor"):
    """Board permission check for the AI tools. Returns a Hebrew refusal string
    (not an exception) so the model can relay it, or None when allowed."""
    role = _board_role(db, board_id, actor)
    if role is None:
        return "❌ אין לך גישה ללוח זה."
    if _BROLE_ORDER.get(role, -1) < _BROLE_ORDER.get(need, 1):
        return "❌ אין לך הרשאת עריכה בלוח זה."
    return None


def execute_ai_tool(name: str, args: dict, actor: Optional[int] = None) -> str:
    """Execute an AI tool by name with the given arguments. Returns a descriptive Hebrew result string.

    Every tool runs with the *caller's* permissions. These tools used to ignore
    `actor` entirely, so anyone who could reach the chat endpoint could read or
    delete items on boards they were never invited to — including by way of
    prompt injection planted in a task description the model later read."""
    from datetime import datetime, timezone

    if actor is None:
        return "❌ נדרשת התחברות."

    if name == "list_boards":
        with Session(engine) as db:
            visible = _visible_board_ids(db, actor)
            boards = [b for b in db.query(Board).filter(Board.is_archived == False, Board.deleted_at == None).all()
                      if b.id in visible]
            if not boards:
                return "❌ לא נמצאו לוחות במערכת."
            lines = []
            for b in boards:
                dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
                task_count = db.query(Task).filter(Task.board_id == b.id).count()
                lines.append(f"  🆔 {b.id} | {b.icon or '📋'} **{b.name}** | אגף: {dept_name} | {task_count} משימות")
            return "📋 **כל הלוחות במערכת:**\n" + "\n".join(lines)

    elif name == "get_board":
        board_id = args.get("board_id")
        with Session(engine) as db:
            b = db.query(Board).filter(Board.id == board_id).first()
            if not b:
                return f"❌ לוח {board_id} לא נמצא."
            if _board_role(db, board_id, actor) is None:
                return "❌ אין לך גישה ללוח זה."
            dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
            groups = db.query(Group).filter(Group.board_id == b.id).order_by(Group.position).all()
            tasks = db.query(Task).filter(Task.board_id == b.id, Task.is_archived == False).all()
            lines = [
                f"📋 **{b.name}**",
                f"   תיאור: {b.description or 'אין תיאור'}",
                f"   אגף: {dept_name}",
                f"   סוג: {b.board_type.value if hasattr(b.board_type, 'value') else b.board_type}",
                f"   צבע: {b.color}",
                f"   סה״כ משימות: {len(tasks)}",
            ]
            if groups:
                lines.append(f"   **עמודות ({len(groups)})**:")
                for g in groups:
                    g_tasks = [t for t in tasks if t.group_id == g.id]
                    lines.append(f"      • {g.name} ({len(g_tasks)} משימות)")
            return "\n".join(lines)

    elif name == "list_projects":
        dept_id = args.get("department_id")
        with Session(engine) as db:
            q = db.query(Project)
            if dept_id:
                q = q.filter(Project.department_id == dept_id)
            projects = q.order_by(Project.id).all()
            if not projects:
                return "❌ לא נמצאו פרויקטים."
            lines = []
            for p in projects:
                dept_name = db.query(Department.name).filter(Department.id == p.department_id).scalar() or ""
                s = p.status.value if hasattr(p.status, 'value') else p.status
                lines.append(f"  🆔 {p.id} | **{p.name}** | אגף: {dept_name} | סטטוס: {s} | תקציב: ₪{p.planned_budget or 0:,}")
            return "📋 **כל הפרויקטים:**\n" + "\n".join(lines)

    elif name == "create_board":
        name = args.get("name", "לוח חדש")
        dept_id = args.get("department_id", 1)
        description = args.get("description", "")
        icon = args.get("icon", "📋")
        color = args.get("color", "#0073ea")
        with Session(engine) as db:
            # same rule as the UI: only a system (workspace) admin may create a
            # board, and the creator is registered as its admin — never orphaned.
            if _ws_role(db, actor) != "admin":
                return "❌ רק מנהל מערכת יכול ליצור לוח חדש."
            b = Board(
                name=name,
                description=description,
                department_id=dept_id,
                board_type=BoardType.KANBAN,
                icon=icon,
                color=color,
                settings={"views": ["table"]},  # new boards start with only the main table
            )
            db.add(b)
            db.flush()

            # Create default groups
            g1 = Group(board_id=b.id, name="בתכנון", position=0, color="#579bfc", task_status=TaskStatus.BACKLOG)
            g2 = Group(board_id=b.id, name="בתהליך", position=1, color="#fdab3d", task_status=TaskStatus.IN_PROGRESS)
            g3 = Group(board_id=b.id, name="הושלם", position=2, color="#00c875", task_status=TaskStatus.DONE)
            db.add_all([g1, g2, g3])
            db.add(BoardMember(board_id=b.id, user_id=actor, role="admin"))
            db.commit()
            db.refresh(b)
            return f"✅ לוח '{name}' נוצר בהצלחה (מזהה: {b.id}) — אתה מוגדר כמנהל הלוח."

    elif name == "create_group":
        board_id = args.get("board_id")
        name = args.get("name", "קבוצה חדשה")
        position = args.get("position", 0)
        color = args.get("color", "#c4c4c4")
        task_status_str = args.get("task_status", "todo")
        try:
            task_status = TaskStatus(task_status_str)
        except ValueError:
            task_status = TaskStatus.TODO
        with Session(engine) as db:
            board = db.query(Board).filter(Board.id == board_id).first()
            if not board:
                return f"❌ לוח {board_id} לא נמצא."
            denied = _ai_board_guard(db, board_id, actor)
            if denied:
                return denied
            g = Group(
                board_id=board_id,
                name=name,
                position=position,
                color=color,
                task_status=task_status,
            )
            db.add(g)
            db.commit()
            db.refresh(g)
            return f"✅ עמודה '{name}' נוצרה בלוח {board_id} (מזהה: {g.id})."

    elif name == "create_task":
        board_id = args.get("board_id")
        group_id = args.get("group_id")
        title = args.get("title", "משימה חדשה")
        description = args.get("description", "")
        # defaults for an item created via the agent: medium priority, "בתכנון"
        # (backlog) status, no assignees, everything else empty.
        priority_str = args.get("priority", "medium")
        status_str = args.get("status", "backlog")
        due_date_str = args.get("due_date")
        try:
            priority = Priority(priority_str)
        except ValueError:
            priority = Priority.MEDIUM
        try:
            status = TaskStatus(status_str)
        except ValueError:
            status = TaskStatus.BACKLOG
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.fromisoformat(due_date_str)
            except Exception:
                pass
        with Session(engine) as db:
            board = db.query(Board).filter(Board.id == board_id).first()
            if not board:
                return f"❌ לוח {board_id} לא נמצא."
            denied = _ai_board_guard(db, board_id, actor)
            if denied:
                return denied
            # group_id is optional — fall back to the board's first group so the
            # agent can add an item without needing to resolve column ids first.
            g = None
            if group_id:
                g = db.query(Group).filter(Group.id == group_id, Group.board_id == board_id).first()
            if not g:
                g = db.query(Group).filter(Group.board_id == board_id).order_by(Group.position).first()
            group_id = g.id if g else None
            t = Task(
                board_id=board_id,
                group_id=group_id,
                title=title,
                description=description,
                priority=priority,
                status=status,
                due_date=due_date,
            )
            db.add(t)
            db.commit()
            db.refresh(t)
            due_str = f" (יעד: {due_date_str})" if due_date_str else ""
            return f"✅ משימה '{title}' נוצרה בהצלחה{due_str} (מזהה: {t.id})."

    elif name == "update_task":
        task_id = args.get("task_id")
        with Session(engine) as db:
            t = db.query(Task).filter(Task.id == task_id).first()
            if not t:
                return f"❌ משימה {task_id} לא נמצאה."
            role = _board_role(db, t.board_id, actor)
            if _item_perm(t, actor, role) not in ("edit", "delete"):
                return "❌ אין לך הרשאת עריכה לפריט זה."
            changed = []
            for field in ["title", "description", "due_date"]:
                if field in args:
                    old_val = getattr(t, field)
                    if field == "due_date" and args[field]:
                        try:
                            setattr(t, field, datetime.fromisoformat(args[field]))
                        except Exception:
                            pass
                    else:
                        setattr(t, field, args[field])
                    if old_val != getattr(t, field):
                        changed.append(field)
            if "status" in args:
                try:
                    ns = TaskStatus(args["status"])
                    t.status = ns
                    changed.append("status")
                except ValueError:
                    pass
            if "priority" in args:
                try:
                    np = Priority(args["priority"])
                    t.priority = np
                    changed.append("priority")
                except ValueError:
                    pass
            for c in changed:
                db.add(AuditLog(
                    entity_type="task", entity_id=task_id,
                    action="update", field_name=c,
                    new_value=str(getattr(t, c)),
                ))
            db.commit()
            if changed:
                return f"✅ משימה {task_id} עודכנה בהצלחה. שדות שהשתנו: {', '.join(changed)}."
            return f"ℹ️ לא בוצעו שינויים במשימה {task_id}."

    elif name == "delete_task":
        task_id = args.get("task_id")
        with Session(engine) as db:
            t = db.query(Task).filter(Task.id == task_id).first()
            if not t:
                return f"❌ משימה {task_id} לא נמצאה."
            role = _board_role(db, t.board_id, actor)
            if _item_perm(t, actor, role) != "delete":
                return "❌ אין לך הרשאת מחיקה לפריט זה."
            t.is_archived = True
            db.add(AuditLog(
                entity_type="task", entity_id=task_id,
                action="archive", field_name="is_archived",
                new_value="True", changed_by=actor,
            ))
            db.commit()
            return f"✅ משימה '{t.title}' (מזהה: {task_id}) אורכבה בהצלחה."

    elif name == "list_departments":
        with Session(engine) as db:
            depts = db.query(Department).all()
            if not depts:
                return "❌ לא נמצאו אגפים במערכת."
            lines = []
            for d in depts:
                proj_count = db.query(Project).filter(Project.department_id == d.id).count()
                lines.append(f"  🆔 {d.id} | **{d.name}** | קוד: {d.code or '-'} | {proj_count} פרויקטים")
            return "🏢 **כל האגפים:**\n" + "\n".join(lines)

    elif name == "list_users":
        with Session(engine) as db:
            users = db.query(User).all()
            if not users:
                return "❌ לא נמצאו משתמשים במערכת."
            lines = []
            for u in users:
                dept_name = db.query(Department.name).filter(Department.id == u.department_id).scalar() or ""
                lines.append(f"  🆔 {u.id} | **{u.name}** | תפקיד: {u.role or '-'} | אגף: {dept_name}")
            return "👥 **כל המשתמשים:**\n" + "\n".join(lines)

    elif name == "create_project":
        name = args.get("name", "פרויקט חדש")
        dept_id = args.get("department_id")
        work_plan_id = args.get("work_plan_id", 1)
        planned_budget = args.get("planned_budget", 0)
        status_str = args.get("status", "draft")
        priority_str = args.get("priority", "medium")
        manager_name = args.get("manager_name")
        with Session(engine) as db:
            dept = db.query(Department).filter(Department.id == dept_id).first()
            if not dept:
                dept_id = 1
            manager_id = None
            if manager_name:
                user = db.query(User).filter(User.name.ilike(f"%{manager_name}%")).first()
                if user:
                    manager_id = user.id
            try:
                p_status = ProjectStatus(status_str)
            except ValueError:
                p_status = ProjectStatus.DRAFT
            try:
                p_priority = Priority(priority_str)
            except ValueError:
                p_priority = Priority.MEDIUM
            p = Project(
                work_plan_id=work_plan_id,
                department_id=dept_id,
                name=name,
                planned_budget=planned_budget,
                status=p_status,
                priority=p_priority,
                manager_id=manager_id,
            )
            db.add(p)
            db.commit()
            db.refresh(p)
            mgr_text = f" (מנהל: {manager_name})" if manager_id else ""
            return f"✅ פרויקט '{name}' נוצר בהצלחה{mgr_text} (מזהה: {p.id})."

    elif name == "get_project_detail":
        project_id = args.get("project_id")
        with Session(engine) as db:
            p = db.query(Project).filter(Project.id == project_id).first()
            if not p:
                return f"❌ פרויקט {project_id} לא נמצא."
            dept_name = db.query(Department.name).filter(Department.id == p.department_id).scalar() or ""
            mgr_name = ""
            if p.manager_id:
                u = db.query(User).filter(User.id == p.manager_id).first()
                if u:
                    mgr_name = u.name
            s = p.status.value if hasattr(p.status, 'value') else p.status
            pri = p.priority.value if hasattr(p.priority, 'value') else p.priority
            steps = db.query(ProjectStep).filter(ProjectStep.project_id == p.id).order_by(ProjectStep.position).all()
            budget_items = db.query(BudgetLineItem).filter(BudgetLineItem.project_id == p.id).all()
            kpis = db.query(KPI).filter(KPI.project_id == p.id).all()
            lines = [
                f"📊 **{p.name}** (מזהה: {p.id})",
                f"   אגף: {dept_name}",
                f"   מנהל: {mgr_name or 'לא הוגדר'}",
                f"   סטטוס: {s} | עדיפות: {pri}",
                f"   התקדמות: {p.progress_percentage or 0}%",
                f"   תקציב: מתוכנן ₪{p.planned_budget or 0:,} | מאושר ₪{p.approved_budget or 0:,} | בפועל ₪{p.actual_budget or 0:,}",
                f"   תאריכים: {p.start_date.strftime('%d/%m/%Y') if p.start_date else '?'} → {p.end_date.strftime('%d/%m/%Y') if p.end_date else '?'}",
            ]
            if steps:
                lines.append(f"   **שלבים ({len(steps)})**:")
                for st in steps:
                    lines.append(f"      • {st.name} - {st.progress or 0}% ({st.status})")
            if kpis:
                lines.append(f"   **KPI ({len(kpis)})**:")
                for k in kpis:
                    ach = round(k.actual / max(k.target, 1) * 100, 1)
                    lines.append(f"      • {k.name}: {k.actual}/{k.target} {k.unit or ''} ({ach}%)")
            if budget_items:
                lines.append(f"   **תקציב לפי סעיף ({len(budget_items)})**:")
                for bi in budget_items:
                    bt = bi.item_type.value if hasattr(bi.item_type, 'value') else bi.item_type
                    lines.append(f"      • {bi.name or bt}: מאושר ₪{bi.approved_amount or 0:,} | בפועל ₪{bi.actual_amount or 0:,}")
            return "\n".join(lines)

    return f"❌ פונקציה '{name}' לא מוכרת."


@app.post("/api/ai/query")
def ai_query(data: dict, actor_id: int = Depends(current_user_id)):
    """CODE-CAL MISSIONS agent — DeepSeek (cloud) with tool calling, Gemini fallback, or local Ollama."""
    import subprocess
    prompt = data.get("prompt", "")
    context = data.get("context", "")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    model = data.get("model") or ("kremer" if deepseek_key else "gemma4-coder")

    # Model alias mapping: kremer = DeepSeek, elaine = Gemini
    model_internal = model.lower()

    system = """אתה CODE-CAL MISSIONS, עוזר עירוני חכם לניהול תוכניות עבודה ותקציב.
אתה יכול לשוחח עם המשתמש בעברית וגם לבצע פעולות במערכת באמצעות tools.

הכללים:
1. כשמשתמש מבקש ליצור/לעדכן/למחוק משהו - השתמש ב-tools המתאימים
2. כשמשתמש שואל שאלה - ענה מידע מהמערכת
3. תמיד אשר למשתמש אחרי ביצוע פעולה
4. כשאתה יוצר לוח חדש, צור גם קבוצות (עמודות) מתאימות: "לתכנון" (backlog), "בתהליך" (in_progress), "הושלם" (done)
5. יצירת פריט (משימה): צריך רק **שם**. קח את הלוח מההקשר — בהקשר יש "מזהה הלוח הפעיל" ורשימת קבוצות; העבר את ה-board_id הזה ל-create_task (group_id אופציונלי, ברירת מחדל היא הקבוצה הראשונה). אם אין לוח פעיל בהקשר - בקש מהמשתמש לאיזה לוח.
6. ברירות מחדל לפריט חדש: עדיפות **medium**, סטטוס **backlog** (בתכנון), **בלי אחראים**, ושאר השדות ריקים. אל תמלא תיאור/תאריך/תגיות אלא אם המשתמש ביקש במפורש - אל תמציא.
7. דבר בעברית תמיד
8. השתמש באימוג'ים במידה
9. אם אתה לא יודע איזה department_id או board_id - השתמש ברשימה קודם"""

    if model_internal == "kremer":
        # DeepSeek with tool calling
        if not deepseek_key:
            return {"response": "קרמר לא זמין כרגע (מפתח חסר).", "success": False, "model": model}
        try:
            import httpx
            messages = [
                {"role": "system", "content": system},
            ]
            user_msg = prompt
            if context:
                user_msg = f"הקשר: {context}\n\n{user_msg}"
            messages.append({"role": "user", "content": user_msg})

            r = httpx.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "temperature": 0.7,
                    "messages": messages,
                    "tools": AI_TOOLS,
                    "tool_choice": "auto",
                },
                timeout=60,
            )
            r.raise_for_status()
            resp_data = r.json()
            choice = resp_data["choices"][0]
            msg = choice["message"]

            tool_calls = msg.get("tool_calls", [])
            executed = []
            tool_results = []

            if tool_calls:
                max_rounds = 5
                rounds = 0
                final_text = ""

                while rounds < max_rounds:
                    rounds += 1
                    # Execute each tool call
                    for tc in tool_calls:
                        fn_name = tc["function"]["name"]
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except Exception:
                            fn_args = {}
                        result_text = execute_ai_tool(fn_name, fn_args, actor_id)
                        tool_results.append({
                            "tool_call_id": tc.get("id", ""),
                            "function_name": fn_name,
                            "arguments": fn_args,
                            "result": result_text,
                        })
                        executed.append({
                            "name": fn_name,
                            "arguments": fn_args,
                            "result": result_text,
                        })

                    # Send results back to the model
                    messages.append(msg)
                    for tr in tool_results:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tr["tool_call_id"],
                            "content": tr["result"],
                        })

                    r2 = httpx.post(
                        "https://api.deepseek.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"},
                        json={
                            "model": "deepseek-chat",
                            "temperature": 0.7,
                            "messages": messages,
                            "tools": AI_TOOLS,
                            "tool_choice": "auto",
                        },
                        timeout=60,
                    )
                    r2.raise_for_status()
                    resp_data2 = r2.json()
                    msg = resp_data2["choices"][0]["message"]
                    tool_calls = msg.get("tool_calls", [])
                    tool_results = []

                    if not tool_calls:
                        # No more tools to call
                        final_text = msg.get("content", "").strip()
                        break

                    final_text = msg.get("content", "") or ""

                return {
                    "response": final_text or "הפעולות בוצעו בהצלחה.",
                    "success": True,
                    "tool_calls": executed,
                    "model": model,
                    "provider": "kremer",
                }

            # No tool calls — just a regular chat response
            txt = msg.get("content", "").strip()
            return {
                "response": txt or "לא התקבלה תשובה",
                "success": True,
                "tool_calls": [],
                "model": model,
                "provider": "kremer",
            }

        except Exception as e:
            return {"response": f"קרמר לא זמין: {str(e)[:200]}", "success": False, "model": model, "tool_calls": []}

    if model_internal == "elaine":
        # Gemini (elaine) — no tool calling, just Q&A
        if not gemini_key:
            return {"response": "איליין לא זמינה כרגע (מפתח חסר).", "success": False, "model": model, "tool_calls": []}
        import httpx, time
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
        combined = prompt
        if context:
            combined = f"הקשר: {context}\n\n{prompt}"
        body = {"contents": [{"parts": [{"text": f"{system}\n\n{combined}"}]}]}
        max_retries = 3
        last_error = ""
        for attempt in range(max_retries):
            try:
                r = httpx.post(url, json=body, timeout=60)
                if r.status_code == 429 and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    last_error = f"rate limited (429), retrying in {wait}s"
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                data_r = r.json()
                candidates = data_r.get("candidates", [])
                if candidates:
                    txt = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return {"response": txt.strip() or "לא התקבלה תשובה", "success": True, "tool_calls": [], "model": model, "provider": "elaine"}
                return {"response": "איליין לא החזירה תוכן.", "success": True, "tool_calls": [], "model": model, "provider": "elaine"}
            except Exception as e:
                if "429" in str(e) and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    last_error = str(e)[:100]
                    time.sleep(wait)
                    continue
                last_error = str(e)[:200]
                break
        # Fallback to DeepSeek (kremer) if available
        if deepseek_key:
            try:
                import httpx
                r = httpx.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {deepseek_key}"},
                    json={"model": "deepseek-chat", "temperature": 0.7, "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": f"הקשר: {context}\n\nשאלה: {prompt}"},
                    ]},
                    timeout=60,
                )
                r.raise_for_status()
                txt = r.json()["choices"][0]["message"]["content"].strip()
                return {"response": txt or "לא התקבלה תשובה", "success": True, "model": "kremer", "fallback": True, "provider": "kremer", "tool_calls": []}
            except Exception:
                pass
        return {"response": f"איליין לא זמינה (מוגבל): {last_error}", "success": False, "model": model, "tool_calls": []}

    # Local Ollama models — no tool calling
    full_prompt = f"{system}\n\nContext: {context}\n\nQuestion: {prompt}\n\nAnswer:"
    try:
        result = subprocess.run(
            ["ollama", "run", model, full_prompt],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "OLLAMA_NUM_THREADS": "8"},
        )
        return {"response": result.stdout.strip() or "לא התקבלה תשובה", "success": True, "tool_calls": [], "model": model, "provider": "ollama"}
    except FileNotFoundError:
        return {"response": "שירות ה-AI המקומי אינו זמין בשרת זה. אפשר לחבר מודל ענן דרך הגדרות המערכת.", "success": False, "model": model, "tool_calls": []}
    except subprocess.TimeoutExpired:
        return {"response": "מודל ה-AI לא הגיב בזמן. נסה שוב או בחר מודל אחר.", "success": False, "model": model, "tool_calls": []}
    except Exception:
        return {"response": "שירות ה-AI אינו זמין כרגע. נסה שוב מאוחר יותר.", "success": False, "model": model, "tool_calls": []}


@app.get("/api/ai/models")
def ai_models():
    """List available LLMs: kremer (DeepSeek), elaine (Gemini), local models."""
    import subprocess
    models = []
    default = "gemma4-coder"
    if os.environ.get("DEEPSEEK_API_KEY"):
        models += [{"name": "kremer", "size": "ענן · DeepSeek"}]
        default = "kremer"
    if os.environ.get("GEMINI_API_KEY"):
        models += [{"name": "elaine", "size": "ענן · Gemini"}]
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=15)
        for line in out.stdout.splitlines()[1:]:
            parts = line.split()
            if parts:
                models.append({"name": parts[0], "size": (parts[2] + " " + parts[3]) if len(parts) > 3 else "מקומי"})
    except Exception:
        pass
    return {"models": models, "available": bool(models), "default": default}

@app.post("/api/llm/v1/chat/completions")
async def llm_proxy(request: Request, actor_id: int = Depends(current_user_id)):
    """Server-side LLM proxy so in-browser clients (e.g. page-agent) can use the
    model WITHOUT ever seeing the API key. Frontend sets baseURL=/api/llm/v1 and a
    dummy apiKey; the real DEEPSEEK_API_KEY is injected here, server-side only."""
    import httpx
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise HTTPException(503, "שירות ה-AI אינו מוגדר בשרת")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    payload["model"] = "deepseek-chat"              # force a supported model
    if payload.get("tool_choice") == "required":     # DeepSeek rejects 'required'
        payload["tool_choice"] = "auto"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
            )
        return Response(content=r.content, status_code=r.status_code,
                        media_type="application/json")
    except Exception as e:
        raise HTTPException(502, "LLM upstream error")

@app.post("/api/ai/train")
def ai_train(data: dict, actor_id: int = Depends(current_user_id)):
    """Prepare a LOCAL fine-tuning dataset (JSONL) from board data.
    Data stays on-device and is used only to train the user's own local models."""
    import json as _json
    if not data.get("confirm"):
        raise HTTPException(400, "training requires explicit confirmation")
    # this bulk-exports item content to disk — system admins only
    with Session(engine) as _db:
        if not _cap(_db, actor_id, "manage_system"):
            raise HTTPException(403, "רק מנהל מערכת יכול לייצא נתוני אימון")
    board_id = data.get("board_id")
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "training")
    os.makedirs(out_dir, exist_ok=True)
    with Session(engine) as db:
        q = db.query(Task).filter(Task.is_archived == False)
        if board_id:
            q = q.filter(Task.board_id == board_id)
        tasks = q.all()
        rows = []
        for t in tasks:
            s = t.status.value if hasattr(t.status, 'value') else t.status
            p = t.priority.value if hasattr(t.priority, 'value') else t.priority
            cf = t.custom_fields or {}
            rows.append({
                "instruction": "סווג משימה עירונית: קבע סטטוס, עדיפות ותגיות.",
                "input": f"{t.title}. {t.description or ''}",
                "output": _json.dumps({"status": cf.get("status_label", s),
                                       "priority": p}, ensure_ascii=False),
            })
        fname = f"cityos_train_board_{board_id or 'all'}.jsonl"
        fpath = os.path.join(out_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(_json.dumps(r, ensure_ascii=False) + "\n")
    return {"status": "dataset_ready", "examples": len(rows), "file": fpath,
            "scope": "local-only",
            "disclaimer": "המידע משמש לאימון המודלים המקומיים שלך בלבד ואינו נשלח לצד שלישי."}

# ── BIM Bridge ───────────────────────────────────────────────────────

_IFC_CACHE = {}

@app.get("/api/bim/generate")
def bim_generate(board_id: Optional[int] = None):
    """Generate IFC model from board tasks."""
    from bim_bridge import IFCBuilder
    with Session(engine) as db:
        if board_id:
            tasks = db.query(Task).filter(Task.board_id == board_id).all()
            board_name = db.query(Board.name).filter(Board.id == board_id).scalar() or "Board"
        else:
            tasks = db.query(Task).filter(Task.is_archived == False).all()
            board_name = "All CityOS Tasks"
        
        builder = IFCBuilder(f"CityOS BIM - {board_name}")
        task_list = []
        for t in tasks:
            task_list.append({
                "id": t.id, "title": t.title, "description": t.description,
                "status": t.status.value if hasattr(t.status, 'value') else t.status,
                "priority": t.priority.value if hasattr(t.priority, 'value') else t.priority,
                "location_lat": t.location_lat, "location_lng": t.location_lng,
            })
        
        count = builder.generate_from_tasks(task_list)
        ifc_path = f"/tmp/cityos_bim_board_{board_id or 'all'}.ifc"
        builder.save(ifc_path)
        
        # Generate BCF topics
        topics = builder.generate_bcf(task_list)
        
        _IFC_CACHE[f"board_{board_id or 'all'}"] = {
            "path": ifc_path,
            "elements": len(task_list),
            "ifc_elements": count,
            "bcf_topics": [t.to_dict() for t in topics],
        }
        
        return {
            "status": "generated",
            "elements": count,
            "bcf_topics": len(topics),
            "ifc_file": ifc_path,
        }

@app.get("/api/bim/viewer-data")
def bim_viewer_data():
    """Get IFC data as Three.js-compatible JSON."""
    from bim_bridge import IFCBuilder
    import ifcopenshell, ifcopenshell.geom
    
    # Use latest generated IFC file
    bims = [v for k, v in _IFC_CACHE.items() if os.path.exists(v.get("path", ""))]
    if not bims:
        # Generate a default one
        with Session(engine) as db:
            tasks = db.query(Task).filter(Task.is_archived == False).all()
            task_list = [{
                "id": t.id, "title": t.title,
                "location_lat": t.location_lat, "location_lng": t.location_lng,
                "priority": t.priority.value if hasattr(t.priority, 'value') else t.priority,
                "status": t.status.value if hasattr(t.status, 'value') else t.status,
            } for t in tasks if t.location_lat]
            if task_list:
                builder = IFCBuilder("CityOS BIM Viewer")
                builder.generate_from_tasks(task_list)
                ifc_path = "/tmp/cityos_bim_viewer.ifc"
                builder.save(ifc_path)
                _IFC_CACHE["viewer"] = {"path": ifc_path}
                bims = [_IFC_CACHE["viewer"]]
    
    if bims:
        try:
            f = ifcopenshell.open(bims[0]["path"])
            objects = []
            settings = ifcopenshell.geom.settings()
            for elem in f.by_type("IfcBuildingElementProxy"):
                try:
                    shape = ifcopenshell.geom.create_shape(settings, elem)
                    verts = shape.geometry.verts
                    faces = shape.geometry.faces
                    task_id = ""
                    for rel in elem.IsDefinedBy or []:
                        if rel.is_a("IfcRelDefinesByProperties"):
                            ps = rel.RelatingPropertyDefinition
                            for p in ps.HasProperties or []:
                                if p.Name == "TaskID" and p.NominalValue:
                                    task_id = str(p.NominalValue.wrappedValue or "")
                    objects.append({
                        "guid": elem.GlobalId,
                        "name": elem.Name or "",
                        "type": elem.ObjectType or "",
                        "task_id": task_id,
                        "positions": list(verts),
                        "faces": list(faces),
                    })
                except:
                    pass
            return {"objects": objects, "count": len(objects)}
        except Exception as e:
            return {"error": str(e)}
    return {"objects": [], "count": 0}

@app.get("/api/bim/bcf-topics")
def bim_bcf_topics():
    """Get BCF topics for the current BIM model."""
    for k, v in _IFC_CACHE.items():
        if "bcf_topics" in v:
            return {"topics": v["bcf_topics"], "board": k}
    return {"topics": []}

# ── CEO Dashboard — City-Wide Command Center ─────────────────────────

@app.get("/api/ceo/dashboard")
def ceo_dashboard(user_id: int = Depends(current_user_id)):
    """Comprehensive CEO dashboard — city-wide view across boards the user may see."""
    with Session(engine) as db:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # ── Board & Task Breakdown (membership-scoped, no leaks) ──
        visible = _visible_board_ids(db, user_id)
        boards = db.query(Board).filter(
            Board.is_archived == False, Board.deleted_at == None, Board.id.in_(visible)
        ).all() if visible else []
        all_tasks = db.query(Task).filter(
            Task.is_archived == False, Task.board_id.in_(visible)
        ).all() if visible else []

        board_breakdown = []
        total_tasks = 0
        total_done = 0
        total_overdue = 0
        total_high_critical = 0

        for b in boards:
            tasks = [t for t in all_tasks if t.board_id == b.id]
            if not tasks:
                continue
            total_tasks += len(tasks)
            by_status = {}
            by_priority = {}
            overdue = 0
            dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
            dept_color = db.query(Department.color).filter(Department.id == b.department_id).scalar() or "#6366f1"

            for t in tasks:
                s = t.status.value if hasattr(t.status, 'value') else t.status
                p = t.priority.value if hasattr(t.priority, 'value') else t.priority
                by_status[s] = by_status.get(s, 0) + 1
                by_priority[p] = by_priority.get(p, 0) + 1
                due = t.due_date
                if due and hasattr(due, 'tzinfo') and due.tzinfo:
                    due = due.replace(tzinfo=None)
                if due and due < now and s not in ("done", "cancelled"):
                    overdue += 1
                    total_overdue += 1
                if p in ("high", "critical", "emergency"):
                    total_high_critical += 1

            done_count = by_status.get("done", 0)
            total_done += done_count

            board_breakdown.append({
                "board_id": b.id,
                "board_name": b.name,
                "icon": b.icon or "📋",
                "department_name": dept_name,
                "department_color": dept_color,
                "total_tasks": len(tasks),
                "done": done_count,
                "overdue": overdue,
                "completion_rate": round(done_count / max(len(tasks), 1) * 100, 1),
                "status_distribution": by_status,
                "priority_distribution": by_priority,
            })

        # ── Citizen Requests Stats ──
        citizen_reqs = db.query(CitizenRequest).all()
        citizen_open = sum(1 for r in citizen_reqs if r.status in ("new", "assigned", "in_progress"))
        citizen_emergency = sum(1 for r in citizen_reqs if hasattr(r.priority, 'value') and r.priority.value in ("critical", "emergency") and r.status not in ("resolved", "closed")) or 0
        citizen_by_type = {}
        for r in citizen_reqs:
            rt = r.request_type.value if hasattr(r.request_type, 'value') else str(r.request_type)
            citizen_by_type[rt] = citizen_by_type.get(rt, 0) + 1

        # ── Permit Stats ──
        permits = db.query(Permit).all()
        permits_pending = sum(1 for p in permits if p.status in ("draft", "submitted", "in_review"))
        permits_approved = sum(1 for p in permits if p.status == "approved")
        permits_rejected = sum(1 for p in permits if p.status == "rejected")

        # ── Infrastructure Stats ──
        assets = db.query(InfrastructureAsset).all()
        assets_poor = sum(1 for a in assets if a.condition == "poor" or a.status == "maintenance_needed")
        assets_by_type = {}
        for a in assets:
            assets_by_type[a.asset_type] = assets_by_type.get(a.asset_type, 0) + 1

        # ── Transport Stats ──
        stops = db.query(PublicTransportStop).count()

        # ── City Health Score ──
        completion_rate = round(total_done / max(total_tasks, 1) * 100, 1)
        overdue_penalty = min(total_overdue * 3, 30)
        citizen_penalty = min(citizen_open * 2, 20)
        health_score = max(0, min(100, round(
            30 * (completion_rate / 100)
            + 20 * (1 - overdue_penalty / 100)
            + 20 * (1 - citizen_penalty / 100)
            + 15 * (permits_approved / max(len(permits), 1))
            + 15 * (1 - assets_poor / max(len(assets), 1))
        )))

        # Health level
        if health_score >= 80:
            health_level = "excellent"
            health_emoji = "🟢"
        elif health_score >= 60:
            health_level = "good"
            health_emoji = "🟡"
        elif health_score >= 40:
            health_level = "fair"
            health_emoji = "🟠"
        else:
            health_level = "critical"
            health_emoji = "🔴"

        return {
            "city_name": "הוד השרון",
            "timestamp": now.isoformat(),
            "health_score": health_score,
            "health_level": health_level,
            "health_emoji": health_emoji,
            "totals": {
                "departments": db.query(Department).count(),
                "boards": len(boards),
                "tasks": total_tasks,
                "done": total_done,
                "overdue": total_overdue,
                "high_priority": total_high_critical,
                "completion_rate": completion_rate,
                "users": db.query(User).count(),
                "citizen_requests": len(citizen_reqs),
                "citizen_open": citizen_open,
                "permits": len(permits),
                "permits_pending": permits_pending,
                "assets": len(assets),
                "transport_stops": stops,
            },
            "board_breakdown": board_breakdown,
            "citizen": {
                "total": len(citizen_reqs),
                "open": citizen_open,
                "emergency": citizen_emergency,
                "by_type": citizen_by_type,
            },
            "permits": {
                "total": len(permits),
                "pending": permits_pending,
                "approved": permits_approved,
                "rejected": permits_rejected,
            },
            "infrastructure": {
                "total": len(assets),
                "needs_maintenance": assets_poor,
                "by_type": assets_by_type,
            },
        }

# ── Work Plan & Budget Module – API Routes ───────────────────────────
# These routes are inserted into main.py. They implement the 5-level
# hierarchy: AnnualWorkPlan → Department → Project → Step → Task
# plus budget, approvals, KPI, Gantt, dashboards, documents, audit & AI.

# ── 1. Annual Work Plans ────────────────────────────────────────────

@app.get("/api/work-plans")
def list_work_plans():
    with Session(engine) as db:
        wps = db.query(AnnualWorkPlan).order_by(AnnualWorkPlan.year.desc()).all()
        result = []
        for wp in wps:
            depts = db.query(Department).filter(Department.organization_id == wp.organization_id).all()
            dept_count = len(depts)
            projects = db.query(Project).filter(Project.work_plan_id == wp.id).all()
            total_projects = len(projects)
            total_planned = sum(p.planned_budget or 0 for p in projects)
            total_approved = sum(p.approved_budget or 0 for p in projects)
            total_actual = sum(p.actual_budget or 0 for p in projects)
            completed = sum(1 for p in projects if p.status == ProjectStatus.COMPLETED)
            in_progress = sum(1 for p in projects if p.status == ProjectStatus.IN_PROGRESS)
            result.append({
                "id": wp.id, "name": wp.name, "year": wp.year,
                "total_budget": wp.total_budget,
                "strategic_goals": wp.strategic_goals or [],
                "municipal_kpis": wp.municipal_kpis or [],
                "overall_status": wp.overall_status,
                "departments_count": dept_count,
                "total_projects": total_projects,
                "completed_projects": completed,
                "in_progress_projects": in_progress,
                "budget_planned": total_planned,
                "budget_approved": total_approved,
                "budget_actual": total_actual,
                "budget_utilization": round(total_actual / max(total_approved, 1) * 100, 1),
                "created_at": wp.created_at.isoformat() if wp.created_at else None,
            })
        return result

@app.get("/api/work-plans/{wp_id}")
def get_work_plan(wp_id: int):
    with Session(engine) as db:
        wp = db.query(AnnualWorkPlan).filter(AnnualWorkPlan.id == wp_id).first()
        if not wp:
            raise HTTPException(404, "Work plan not found")
        depts = db.query(Department).filter(Department.organization_id == wp.organization_id).all()
        dept_breakdown = []
        for d in depts:
            projects = db.query(Project).filter(
                Project.department_id == d.id, Project.work_plan_id == wp.id
            ).all()
            dept_planned = sum(p.planned_budget or 0 for p in projects)
            dept_approved = sum(p.approved_budget or 0 for p in projects)
            dept_actual = sum(p.actual_budget or 0 for p in projects)
            avg_progress = round(sum(p.progress_percentage or 0 for p in projects) / max(len(projects), 1), 1)
            dept_breakdown.append({
                "id": d.id, "name": d.name, "code": d.code, "color": d.color,
                "manager_name": d.manager_name or "",
                "annual_budget": d.annual_budget or 0,
                "project_count": len(projects),
                "budget_planned": dept_planned,
                "budget_approved": dept_approved,
                "budget_actual": dept_actual,
                "budget_utilization": round(dept_actual / max(dept_approved, 1) * 100, 1),
                "avg_progress": avg_progress,
                "planned_projects": d.planned_projects or 0,
                "completed_projects": d.completed_projects or 0,
            })
        return {
            "id": wp.id, "name": wp.name, "year": wp.year,
            "total_budget": wp.total_budget,
            "strategic_goals": wp.strategic_goals or [],
            "municipal_kpis": wp.municipal_kpis or [],
            "overall_status": wp.overall_status,
            "created_at": wp.created_at.isoformat() if wp.created_at else None,
            "departments": dept_breakdown,
        }

@app.post("/api/work-plans")
def create_work_plan(data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        wp = AnnualWorkPlan(
            organization_id=data.get("organization_id", 1),
            name=data.get("name", "תוכנית עבודה"),
            year=data.get("year", datetime.now(timezone.utc).year),
            total_budget=data.get("total_budget", 0),
            strategic_goals=data.get("strategic_goals", []),
            municipal_kpis=data.get("municipal_kpis", []),
            overall_status=data.get("overall_status", "draft"),
        )
        db.add(wp)
        db.commit()
        db.refresh(wp)
        # Audit log
        db.add(AuditLog(entity_type="work_plan", entity_id=wp.id,
            action="create", field_name="name", new_value=wp.name,
            changed_by=actor_id))
        db.commit()
        return {"id": wp.id, "status": "created", "name": wp.name}

# ── 2. Projects ──────────────────────────────────────────────────────

@app.get("/api/projects")
def list_projects(work_plan_id: Optional[int] = None, department_id: Optional[int] = None, status: Optional[str] = None):
    with Session(engine) as db:
        q = db.query(Project)
        if work_plan_id:
            q = q.filter(Project.work_plan_id == work_plan_id)
        if department_id:
            q = q.filter(Project.department_id == department_id)
        if status:
            q = q.filter(Project.status == status)
        projects = q.order_by(Project.id).all()
        result = []
        for p in projects:
            mgr_name = ""
            if p.manager_id:
                u = db.query(User).filter(User.id == p.manager_id).first()
                if u:
                    mgr_name = u.name
            dept_name = ""
            if p.department_id:
                d = db.query(Department).filter(Department.id == p.department_id).first()
                if d:
                    dept_name = d.name
            step_count = db.query(ProjectStep).filter(ProjectStep.project_id == p.id).count()
            util = round(p.actual_budget / max(p.approved_budget, 1) * 100, 1)
            result.append({
                "id": p.id, "name": p.name, "description": p.description,
                "work_plan_id": p.work_plan_id, "department_id": p.department_id,
                "department_name": dept_name,
                "manager_id": p.manager_id, "manager_name": mgr_name,
                "planned_budget": p.planned_budget, "approved_budget": p.approved_budget,
                "actual_budget": p.actual_budget, "budget_utilization": util,
                "progress_percentage": p.progress_percentage,
                "start_date": p.start_date.isoformat() if p.start_date else None,
                "end_date": p.end_date.isoformat() if p.end_date else None,
                "status": p.status.value if hasattr(p.status, 'value') else p.status,
                "priority": p.priority.value if hasattr(p.priority, 'value') else p.priority,
                "tags": p.tags or [], "color": p.color,
                "step_count": step_count,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            })
        return result

@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    with Session(engine) as db:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "Project not found")
        mgr_name = ""
        if p.manager_id:
            u = db.query(User).filter(User.id == p.manager_id).first()
            if u:
                mgr_name = u.name
        dept_name = ""
        if p.department_id:
            d = db.query(Department).filter(Department.id == p.department_id).first()
            if d:
                dept_name = d.name
        steps = db.query(ProjectStep).filter(ProjectStep.project_id == p.id).order_by(ProjectStep.position).all()
        budget_items = db.query(BudgetLineItem).filter(BudgetLineItem.project_id == p.id).all()
        kpis = db.query(KPI).filter(KPI.project_id == p.id).all()
        change_requests = db.query(ChangeRequest).filter(ChangeRequest.project_id == p.id).all()
        approvals = db.query(Approval).filter(
            Approval.entity_type == "project", Approval.entity_id == p.id
        ).order_by(Approval.step_order).all()
        documents = db.query(Document).filter(Document.project_id == p.id).all()
        return {
            "id": p.id, "name": p.name, "description": p.description,
            "work_plan_id": p.work_plan_id, "department_id": p.department_id,
            "department_name": dept_name,
            "manager_id": p.manager_id, "manager_name": mgr_name,
            "planned_budget": p.planned_budget, "approved_budget": p.approved_budget,
            "actual_budget": p.actual_budget,
            "budget_utilization": round(p.actual_budget / max(p.approved_budget, 1) * 100, 1),
            "progress_percentage": p.progress_percentage,
            "start_date": p.start_date.isoformat() if p.start_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "status": p.status.value if hasattr(p.status, 'value') else p.status,
            "priority": p.priority.value if hasattr(p.priority, 'value') else p.priority,
            "tags": p.tags or [], "color": p.color,
            "steps": [{
                "id": s.id, "name": s.name, "description": s.description,
                "owner_id": s.owner_id,
                "owner_name": (db.query(User.name).filter(User.id == s.owner_id).scalar() or "") if s.owner_id else "",
                "start_date": s.start_date.isoformat() if s.start_date else None,
                "end_date": s.end_date.isoformat() if s.end_date else None,
                "progress": s.progress, "position": s.position,
                "status": s.status,
                "task_count": db.query(Task).filter(Task.step_id == s.id).count(),
            } for s in steps],
            "budget_items": [{
                "id": bi.id, "item_type": bi.item_type.value if hasattr(bi.item_type, 'value') else bi.item_type,
                "name": bi.name, "planned_amount": bi.planned_amount,
                "approved_amount": bi.approved_amount, "actual_amount": bi.actual_amount,
                "notes": bi.notes,
            } for bi in budget_items],
            "kpis": [{
                "id": k.id, "name": k.name, "description": k.description,
                "target": k.target, "actual": k.actual, "unit": k.unit,
                "achievement": round(k.actual / max(k.target, 1) * 100, 1),
            } for k in kpis],
            "change_requests": [{
                "id": cr.id, "title": cr.title, "description": cr.description,
                "amount_change": cr.amount_change, "reason": cr.reason,
                "status": cr.status.value if hasattr(cr.status, 'value') else cr.status,
                "requester_name": (db.query(User.name).filter(User.id == cr.requested_by).scalar() or "") if cr.requested_by else "",
            } for cr in change_requests],
            "approvals": [{
                "id": a.id, "approver_role": a.approver_role,
                "status": a.status.value if hasattr(a.status, 'value') else a.status,
                "step_order": a.step_order,
                "approver_name": (db.query(User.name).filter(User.id == a.approver_user_id).scalar() or "") if a.approver_user_id else "",
                "notes": a.notes,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "approved_at": a.approved_at.isoformat() if a.approved_at else None,
            } for a in approvals],
            "documents": [{
                "id": d.id, "document_type": d.document_type.value if hasattr(d.document_type, 'value') else d.document_type,
                "name": d.name, "description": d.description,
                "file_url": d.file_url, "file_size": d.file_size,
                "uploader_name": (db.query(User.name).filter(User.id == d.uploaded_by).scalar() or "") if d.uploaded_by else "",
                "created_at": d.created_at.isoformat() if d.created_at else None,
            } for d in documents],
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }

@app.post("/api/projects")
def create_project(data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        status_val = data.get("status", "draft")
        try:
            p_status = ProjectStatus(status_val)
        except ValueError:
            p_status = ProjectStatus.DRAFT
        priority_val = data.get("priority", "medium")
        try:
            p_priority = Priority(priority_val)
        except ValueError:
            p_priority = Priority.MEDIUM
        p = Project(
            work_plan_id=data.get("work_plan_id"),
            department_id=data.get("department_id"),
            name=data.get("name", "פרויקט חדש"),
            description=data.get("description", ""),
            manager_id=data.get("manager_id"),
            planned_budget=data.get("planned_budget", 0),
            approved_budget=data.get("approved_budget", 0),
            actual_budget=data.get("actual_budget", 0),
            progress_percentage=data.get("progress_percentage", 0),
            start_date=datetime.fromisoformat(data["start_date"]) if data.get("start_date") else None,
            end_date=datetime.fromisoformat(data["end_date"]) if data.get("end_date") else None,
            status=p_status,
            priority=p_priority,
            tags=data.get("tags", []),
            color=data.get("color"),
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        db.add(AuditLog(entity_type="project", entity_id=p.id,
            action="create", field_name="name", new_value=p.name,
            changed_by=actor_id))
        db.commit()
        return {"id": p.id, "status": "created", "name": p.name}

@app.patch("/api/projects/{project_id}")
def update_project(project_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "Project not found")
        updatable = ["name", "description", "manager_id", "planned_budget", "approved_budget",
                     "actual_budget", "progress_percentage", "start_date", "end_date", "tags", "color"]
        for field in updatable:
            if field in data:
                old_val = getattr(p, field, None)
                if field in ("start_date", "end_date") and data.get(field):
                    setattr(p, field, datetime.fromisoformat(data[field]))
                else:
                    setattr(p, field, data[field])
                if old_val != data.get(field):
                    db.add(AuditLog(entity_type="project", entity_id=p.id,
                        action="update", field_name=field,
                        old_value=str(old_val) if old_val else None,
                        new_value=str(data[field]) if data.get(field) else None,
                        changed_by=actor_id))
        if "status" in data:
            try:
                p.status = ProjectStatus(data["status"])
            except ValueError:
                pass
            db.add(AuditLog(entity_type="project", entity_id=p.id,
                action="update", field_name="status",
                new_value=data["status"],
                changed_by=actor_id))
        if "priority" in data:
            try:
                p.priority = Priority(data["priority"])
            except ValueError:
                pass
        db.commit()
        return {"id": p.id, "status": "updated"}

@app.post("/api/projects/{project_id}/recalculate")
def recalculate_project_budget(project_id: int):
    with Session(engine) as db:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404)
        items = db.query(BudgetLineItem).filter(BudgetLineItem.project_id == project_id).all()
        p.planned_budget = sum(i.planned_amount or 0 for i in items)
        p.approved_budget = sum(i.approved_amount or 0 for i in items)
        p.actual_budget = sum(i.actual_amount or 0 for i in items)
        db.commit()
        return {
            "planned_budget": p.planned_budget,
            "approved_budget": p.approved_budget,
            "actual_budget": p.actual_budget,
            "utilization": round(p.actual_budget / max(p.approved_budget, 1) * 100, 1),
        }

# ── 3. Project Steps ─────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/steps")
def list_steps(project_id: int):
    with Session(engine) as db:
        steps = db.query(ProjectStep).filter(ProjectStep.project_id == project_id).order_by(ProjectStep.position).all()
        return [{
            "id": s.id, "project_id": s.project_id,
            "name": s.name, "description": s.description,
            "owner_id": s.owner_id,
            "owner_name": (db.query(User.name).filter(User.id == s.owner_id).scalar() or "") if s.owner_id else "",
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "progress": s.progress, "position": s.position,
            "status": s.status,
            "task_count": db.query(Task).filter(Task.step_id == s.id).count(),
        } for s in steps]

@app.post("/api/projects/{project_id}/steps")
def create_step(project_id: int, data: dict):
    with Session(engine) as db:
        step = ProjectStep(
            project_id=project_id,
            name=data.get("name", "שלב חדש"),
            description=data.get("description"),
            owner_id=data.get("owner_id"),
            start_date=datetime.fromisoformat(data["start_date"]) if data.get("start_date") else None,
            end_date=datetime.fromisoformat(data["end_date"]) if data.get("end_date") else None,
            progress=data.get("progress", 0),
            position=data.get("position", 0),
            status=data.get("status", "pending"),
        )
        db.add(step)
        db.commit()
        db.refresh(step)
        return {"id": step.id, "status": "created"}

@app.patch("/api/steps/{step_id}")
def update_step(step_id: int, data: dict):
    with Session(engine) as db:
        s = db.query(ProjectStep).filter(ProjectStep.id == step_id).first()
        if not s:
            raise HTTPException(404)
        for field in ["name", "description", "owner_id", "progress", "position", "status"]:
            if field in data:
                setattr(s, field, data[field])
        if "start_date" in data:
            s.start_date = datetime.fromisoformat(data["start_date"]) if data["start_date"] else None
        if "end_date" in data:
            s.end_date = datetime.fromisoformat(data["end_date"]) if data["end_date"] else None
        db.commit()
        return {"id": s.id, "status": "updated"}

@app.get("/api/steps/{step_id}/tasks")
def list_step_tasks(step_id: int):
    with Session(engine) as db:
        tasks = db.query(Task).filter(Task.step_id == step_id, Task.is_archived == False).all()
        return [{
            "id": t.id, "title": t.title, "description": t.description,
            "status": t.status.value if hasattr(t.status, 'value') else t.status,
            "priority": t.priority.value if hasattr(t.priority, 'value') else t.priority,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "assignees": [{"id": u.id, "name": u.name} for u in (t.assignees or [])],
        } for t in tasks]

# ── 4. Budget Line Items ─────────────────────────────────────────────

@app.get("/api/projects/{project_id}/budget-items")
def list_budget_items(project_id: int):
    with Session(engine) as db:
        items = db.query(BudgetLineItem).filter(BudgetLineItem.project_id == project_id).all()
        totals = {"planned": 0, "approved": 0, "actual": 0}
        for i in items:
            totals["planned"] += i.planned_amount or 0
            totals["approved"] += i.approved_amount or 0
            totals["actual"] += i.actual_amount or 0
        return {
            "items": [{
                "id": bi.id, "item_type": bi.item_type.value if hasattr(bi.item_type, 'value') else bi.item_type,
                "name": bi.name, "planned_amount": bi.planned_amount,
                "approved_amount": bi.approved_amount, "actual_amount": bi.actual_amount,
                "notes": bi.notes,
            } for bi in items],
            "totals": totals,
            "utilization": round(totals["actual"] / max(totals["approved"], 1) * 100, 1),
        }

@app.post("/api/projects/{project_id}/budget-items")
def create_budget_item(project_id: int, data: dict):
    with Session(engine) as db:
        item_type_str = data.get("item_type", "other")
        try:
            item_type = BudgetItemType(item_type_str)
        except ValueError:
            item_type = BudgetItemType.OTHER
        bi = BudgetLineItem(
            project_id=project_id,
            item_type=item_type,
            name=data.get("name"),
            planned_amount=data.get("planned_amount", 0),
            approved_amount=data.get("approved_amount", 0),
            actual_amount=data.get("actual_amount", 0),
            notes=data.get("notes"),
        )
        db.add(bi)
        db.commit()
        db.refresh(bi)
        return {"id": bi.id, "status": "created"}

# ── 4b. Budget — Department & Work Plan Level ────────────────────────

@app.get("/api/budget/department/{dept_id}")
def department_budget(dept_id: int):
    with Session(engine) as db:
        dept = db.query(Department).filter(Department.id == dept_id).first()
        if not dept:
            raise HTTPException(404)
        projects = db.query(Project).filter(Project.department_id == dept_id).all()
        total_planned = sum(p.planned_budget or 0 for p in projects)
        total_approved = sum(p.approved_budget or 0 for p in projects)
        total_actual = sum(p.actual_budget or 0 for p in projects)
        return {
            "department_id": dept.id, "department_name": dept.name,
            "annual_budget": dept.annual_budget or 0,
            "total_planned": total_planned,
            "total_approved": total_approved,
            "total_actual": total_actual,
            "utilization": round(total_actual / max(total_approved, 1) * 100, 1),
            "budget_vs_annual": round(total_approved / max(dept.annual_budget or 1, 1) * 100, 1),
            "project_count": len(projects),
        }

@app.get("/api/budget/work-plan/{wp_id}")
def work_plan_budget(wp_id: int):
    with Session(engine) as db:
        wp = db.query(AnnualWorkPlan).filter(AnnualWorkPlan.id == wp_id).first()
        if not wp:
            raise HTTPException(404)
        projects = db.query(Project).filter(Project.work_plan_id == wp_id).all()
        total_planned = sum(p.planned_budget or 0 for p in projects)
        total_approved = sum(p.approved_budget or 0 for p in projects)
        total_actual = sum(p.actual_budget or 0 for p in projects)
        depts = db.query(Department).filter(Department.organization_id == wp.organization_id).all()
        dept_breakdown = []
        for d in depts:
            dp = [p for p in projects if p.department_id == d.id]
            dept_breakdown.append({
                "department_id": d.id, "department_name": d.name,
                "annual_budget": d.annual_budget or 0,
                "planned": sum(p.planned_budget or 0 for p in dp),
                "approved": sum(p.approved_budget or 0 for p in dp),
                "actual": sum(p.actual_budget or 0 for p in dp),
                "project_count": len(dp),
            })
        return {
            "work_plan_id": wp.id, "work_plan_name": wp.name,
            "total_budget": wp.total_budget,
            "total_planned": total_planned,
            "total_approved": total_approved,
            "total_actual": total_actual,
            "utilization": round(total_actual / max(total_approved, 1) * 100, 1),
            "departments": dept_breakdown,
        }

# ── 5. Approvals ─────────────────────────────────────────────────────

@app.get("/api/approvals")
def list_approvals(entity_type: Optional[str] = None, entity_id: Optional[int] = None, status: Optional[str] = None):
    with Session(engine) as db:
        q = db.query(Approval)
        if entity_type:
            q = q.filter(Approval.entity_type == entity_type)
        if entity_id:
            q = q.filter(Approval.entity_id == entity_id)
        if status:
            q = q.filter(Approval.status == status)
        approvals = q.order_by(Approval.created_at.desc()).limit(100).all()
        return [{
            "id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id,
            "approver_role": a.approver_role,
            "approver_user_id": a.approver_user_id,
            "approver_name": (db.query(User.name).filter(User.id == a.approver_user_id).scalar() or "") if a.approver_user_id else "",
            "status": a.status.value if hasattr(a.status, 'value') else a.status,
            "notes": a.notes, "step_order": a.step_order,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "approved_at": a.approved_at.isoformat() if a.approved_at else None,
        } for a in approvals]

@app.post("/api/approvals")
def create_approval_chain(data: dict):
    with Session(engine) as db:
        roles = data.get("approver_roles", [])
        created = []
        for i, role in enumerate(roles):
            existing = db.query(Approval).filter(
                Approval.entity_type == data["entity_type"],
                Approval.entity_id == data["entity_id"],
                Approval.approver_role == role
            ).first()
            if existing:
                continue
            a = Approval(
                entity_type=data["entity_type"],
                entity_id=data["entity_id"],
                approver_role=role,
                status=ApprovalStatus.PENDING,
                step_order=i,
            )
            db.add(a)
            created.append({"role": role, "step_order": i})
        db.commit()
        return {"created": created, "count": len(created)}

@app.post("/api/approvals/{approval_id}/approve")
def approve_step(approval_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        a = db.query(Approval).filter(Approval.id == approval_id).first()
        if not a:
            raise HTTPException(404)
        try:
            a.status = ApprovalStatus(data.get("status", "approved"))
        except ValueError:
            a.status = ApprovalStatus.APPROVED
        a.approver_user_id = actor_id   # the approver is whoever is signed in
        a.notes = data.get("notes", "")
        a.approved_at = datetime.now(timezone.utc)
        db.add(AuditLog(
            entity_type=f"approval.{a.entity_type}", entity_id=a.entity_id,
            action=data.get("status", "approved"),
            field_name=f"approval.{a.approver_role}",
            new_value=data.get("status", "approved"),
            changed_by=actor_id,
        ))
        db.commit()
        return {"id": a.id, "status": a.status.value, "approved_at": a.approved_at.isoformat()}

@app.get("/api/projects/{project_id}/approval-chain")
def project_approval_chain(project_id: int):
    with Session(engine) as db:
        approvals = db.query(Approval).filter(
            Approval.entity_type == "project", Approval.entity_id == project_id
        ).order_by(Approval.step_order).all()
        chain_status = "approved"
        current_step = None
        for a in approvals:
            s = a.status.value if hasattr(a.status, 'value') else a.status
            if s == "pending":
                chain_status = f"awaiting_{a.approver_role}"
                current_step = a.step_order
                break
            elif s == "rejected":
                chain_status = f"rejected_by_{a.approver_role}"
                current_step = a.step_order
                break
        return {
            "project_id": project_id,
            "chain_status": chain_status,
            "current_step": current_step,
            "approvals": [{
                "id": a.id, "approver_role": a.approver_role,
                "status": a.status.value if hasattr(a.status, 'value') else a.status,
                "step_order": a.step_order,
                "approver_name": (db.query(User.name).filter(User.id == a.approver_user_id).scalar() or "") if a.approver_user_id else "",
                "notes": a.notes,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "approved_at": a.approved_at.isoformat() if a.approved_at else None,
            } for a in approvals],
        }

# ── 6. Change Requests ──────────────────────────────────────────────

@app.get("/api/change-requests")
def list_change_requests(project_id: Optional[int] = None, status: Optional[str] = None):
    with Session(engine) as db:
        q = db.query(ChangeRequest)
        if project_id:
            q = q.filter(ChangeRequest.project_id == project_id)
        if status:
            try:
                q = q.filter(ChangeRequest.status == ChangeRequestStatus(status))
            except ValueError:
                pass
        crs = q.order_by(ChangeRequest.created_at.desc()).all()
        return [{
            "id": cr.id, "project_id": cr.project_id,
            "title": cr.title, "description": cr.description,
            "amount_change": cr.amount_change, "reason": cr.reason,
            "status": cr.status.value if hasattr(cr.status, 'value') else cr.status,
            "requester_name": (db.query(User.name).filter(User.id == cr.requested_by).scalar() or "") if cr.requested_by else "",
            "approver_name": (db.query(User.name).filter(User.id == cr.approved_by).scalar() or "") if cr.approved_by else "",
            "created_at": cr.created_at.isoformat() if cr.created_at else None,
            "approved_at": cr.approved_at.isoformat() if cr.approved_at else None,
        } for cr in crs]

@app.post("/api/change-requests")
def create_change_request(data: dict):
    with Session(engine) as db:
        try:
            cr_status = ChangeRequestStatus(data.get("status", "submitted"))
        except ValueError:
            cr_status = ChangeRequestStatus.SUBMITTED
        cr = ChangeRequest(
            project_id=data["project_id"],
            title=data.get("title", "בקשת שינוי"),
            description=data.get("description"),
            amount_change=data.get("amount_change", 0),
            reason=data.get("reason", ""),
            status=cr_status,
            requested_by=data.get("requested_by"),
        )
        db.add(cr)
        db.commit()
        db.refresh(cr)
        return {"id": cr.id, "status": "created"}

@app.patch("/api/change-requests/{cr_id}")
def update_change_request(cr_id: int, data: dict, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        cr = db.query(ChangeRequest).filter(ChangeRequest.id == cr_id).first()
        if not cr:
            raise HTTPException(404)
        if "status" in data:
            try:
                cr.status = ChangeRequestStatus(data["status"])
            except ValueError:
                pass
            if data["status"] in ("approved", "rejected"):
                cr.approved_by = actor_id
                cr.approved_at = datetime.now(timezone.utc)
        for field in ["title", "description", "amount_change", "reason"]:
            if field in data:
                setattr(cr, field, data[field])
        db.commit()
        return {"id": cr.id, "status": "updated"}

# ── 7. KPIs ─────────────────────────────────────────────────────────

@app.get("/api/kpis")
def list_kpis(project_id: Optional[int] = None, work_plan_id: Optional[int] = None):
    with Session(engine) as db:
        q = db.query(KPI)
        if project_id:
            q = q.filter(KPI.project_id == project_id)
        if work_plan_id:
            q = q.filter(KPI.work_plan_id == work_plan_id)
        kpis = q.all()
        return [{
            "id": k.id, "project_id": k.project_id, "work_plan_id": k.work_plan_id,
            "name": k.name, "description": k.description,
            "target": k.target, "actual": k.actual, "unit": k.unit,
            "achievement": round(k.actual / max(k.target, 1) * 100, 1),
            "measurement_date": k.measurement_date.isoformat() if k.measurement_date else None,
        } for k in kpis]

@app.post("/api/kpis")
def create_kpi(data: dict):
    with Session(engine) as db:
        kpi = KPI(
            project_id=data.get("project_id"),
            work_plan_id=data.get("work_plan_id"),
            name=data.get("name", "KPI"),
            description=data.get("description"),
            target=data.get("target", 100),
            actual=data.get("actual", 0),
            unit=data.get("unit", ""),
            measurement_date=datetime.fromisoformat(data["measurement_date"]) if data.get("measurement_date") else None,
        )
        db.add(kpi)
        db.commit()
        db.refresh(kpi)
        return {"id": kpi.id, "status": "created"}

@app.patch("/api/kpis/{kpi_id}")
def update_kpi(kpi_id: int, data: dict):
    with Session(engine) as db:
        k = db.query(KPI).filter(KPI.id == kpi_id).first()
        if not k:
            raise HTTPException(404)
        if "actual" in data:
            k.actual = data["actual"]
        if "target" in data:
            k.target = data["target"]
        if "measurement_date" in data:
            k.measurement_date = datetime.fromisoformat(data["measurement_date"]) if data["measurement_date"] else None
        db.commit()
        return {"id": k.id, "achievement": round(k.actual / max(k.target, 1) * 100, 1)}

# ── 8. Dependencies (for Gantt) ──────────────────────────────────────

@app.get("/api/dependencies")
def list_dependencies(project_id: Optional[int] = None):
    with Session(engine) as db:
        q = db.query(Dependency)
        if project_id:
            q = q.filter(
                (Dependency.source_type == "project" and Dependency.source_id == project_id) |
                (Dependency.target_type == "project" and Dependency.target_id == project_id)
            )
        deps = q.all()
        result = []
        for dep in deps:
            dep_type = dep.dependency_type.value if hasattr(dep.dependency_type, 'value') else dep.dependency_type
            source_name = ""
            target_name = ""
            if dep.source_type == "project" and dep.source_id:
                source_name = db.query(Project.name).filter(Project.id == dep.source_id).scalar() or ""
            if dep.target_type == "project" and dep.target_id:
                target_name = db.query(Project.name).filter(Project.id == dep.target_id).scalar() or ""
            result.append({
                "id": dep.id, "source_type": dep.source_type, "source_id": dep.source_id,
                "source_name": source_name,
                "target_type": dep.target_type, "target_id": dep.target_id,
                "target_name": target_name,
                "dependency_type": dep_type,
                "lag_days": dep.lag_days,
            })
        return result

@app.post("/api/dependencies")
def create_dependency(data: dict):
    with Session(engine) as db:
        try:
            dep_type = DependencyType(data.get("dependency_type", "finish_to_start"))
        except ValueError:
            dep_type = DependencyType.FINISH_TO_START
        dep = Dependency(
            source_type=data.get("source_type", "project"),
            source_id=data["source_id"],
            target_type=data.get("target_type", "project"),
            target_id=data["target_id"],
            dependency_type=dep_type,
            lag_days=data.get("lag_days", 0),
        )
        db.add(dep)
        db.commit()
        db.refresh(dep)
        return {"id": dep.id, "status": "created"}

@app.delete("/api/dependencies/{dep_id}")
def delete_dependency(dep_id: int):
    with Session(engine) as db:
        dep = db.query(Dependency).filter(Dependency.id == dep_id).first()
        if not dep:
            raise HTTPException(404)
        db.delete(dep)
        db.commit()
        return {"status": "deleted"}

# ── 9. Documents ─────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/documents")
def list_documents(project_id: int):
    with Session(engine) as db:
        docs = db.query(Document).filter(Document.project_id == project_id).all()
        # Group by document_type
        grouped = {}
        for d in docs:
            dt = d.document_type.value if hasattr(d.document_type, 'value') else d.document_type
            if dt not in grouped:
                grouped[dt] = []
            grouped[dt].append({
                "id": d.id, "name": d.name, "description": d.description,
                "file_url": d.file_url, "file_size": d.file_size,
                "uploader_name": (db.query(User.name).filter(User.id == d.uploaded_by).scalar() or "") if d.uploaded_by else "",
                "created_at": d.created_at.isoformat() if d.created_at else None,
            })
        return {"documents": grouped, "total": len(docs)}

@app.post("/api/projects/{project_id}/documents")
def create_document(project_id: int, data: dict):
    with Session(engine) as db:
        try:
            doc_type = DocumentType(data.get("document_type", "other"))
        except ValueError:
            doc_type = DocumentType.OTHER
        doc = Document(
            project_id=project_id,
            document_type=doc_type,
            name=data.get("name", "מסמך"),
            description=data.get("description"),
            file_url=data.get("file_url"),
            file_size=data.get("file_size"),
            uploaded_by=data.get("uploaded_by"),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return {"id": doc.id, "status": "created"}

# ── 10. Audit Log ────────────────────────────────────────────────────

@app.get("/api/audit-log")
def list_audit_log(entity_type: Optional[str] = None, entity_id: Optional[int] = None, limit: int = 50):
    with Session(engine) as db:
        q = db.query(AuditLog)
        if entity_type:
            q = q.filter(AuditLog.entity_type == entity_type)
        if entity_id:
            q = q.filter(AuditLog.entity_id == entity_id)
        entries = q.order_by(AuditLog.created_at.desc()).limit(min(limit, 200)).all()
        return [{
            "id": e.id, "entity_type": e.entity_type, "entity_id": e.entity_id,
            "field_name": e.field_name, "old_value": e.old_value,
            "new_value": e.new_value, "action": e.action,
            "changed_by": e.changed_by,
            "changer_name": (db.query(User.name).filter(User.id == e.changed_by).scalar() or "") if e.changed_by else "",
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in entries]

# ── 11. Director Dashboard ──────────────────────────────────────────

@app.get("/api/director/dashboard/{dept_id}")
def director_dashboard(dept_id: int):
    with Session(engine) as db:
        dept = db.query(Department).filter(Department.id == dept_id).first()
        if not dept:
            raise HTTPException(404)
        projects = db.query(Project).filter(Project.department_id == dept_id).all()
        now = datetime.now(timezone.utc)
        total = len(projects)
        in_progress = sum(1 for p in projects if p.status == ProjectStatus.IN_PROGRESS)
        completed = sum(1 for p in projects if p.status == ProjectStatus.COMPLETED)
        drafting = sum(1 for p in projects if p.status == ProjectStatus.DRAFT)
        overdue = 0
        overdue_projects = []
        for p in projects:
            if p.end_date and p.status not in (ProjectStatus.COMPLETED, ProjectStatus.CANCELLED):
                ed = p.end_date
                if hasattr(ed, 'tzinfo') and ed.tzinfo:
                    ed = ed.replace(tzinfo=None)
                now_naive = now.replace(tzinfo=None)
                if ed < now_naive:
                    overdue += 1
                    overdue_projects.append({
                        "id": p.id, "name": p.name,
                        "end_date": p.end_date.isoformat() if p.end_date else None,
                        "progress": p.progress_percentage,
                        "days_overdue": (now_naive - ed).days,
                    })
        total_approved = sum(p.approved_budget or 0 for p in projects)
        total_actual = sum(p.actual_budget or 0 for p in projects)
        # Budget breakdown by item type
        all_items = db.query(BudgetLineItem).filter(
            BudgetLineItem.project_id.in_([p.id for p in projects])
        ).all() if projects else []
        budget_by_type = {}
        for bi in all_items:
            bt = bi.item_type.value if hasattr(bi.item_type, 'value') else bi.item_type
            if bt not in budget_by_type:
                budget_by_type[bt] = {"planned": 0, "approved": 0, "actual": 0}
            budget_by_type[bt]["planned"] += bi.planned_amount or 0
            budget_by_type[bt]["approved"] += bi.approved_amount or 0
            budget_by_type[bt]["actual"] += bi.actual_amount or 0
        return {
            "department_id": dept.id, "department_name": dept.name,
            "manager_name": dept.manager_name or "",
            "annual_budget": dept.annual_budget or 0,
            "projects": {
                "total": total,
                "in_progress": in_progress,
                "completed": completed,
                "draft": drafting,
                "overdue": overdue,
            },
            "budget": {
                "approved": total_approved,
                "actual": total_actual,
                "utilization": round(total_actual / max(total_approved, 1) * 100, 1),
                "budget_vs_annual": round(total_approved / max(dept.annual_budget or 1, 1) * 100, 1),
                "by_type": budget_by_type,
            },
            "overdue_projects": overdue_projects,
            "project_list": [{
                "id": p.id, "name": p.name,
                "status": p.status.value if hasattr(p.status, 'value') else p.status,
                "progress": p.progress_percentage,
                "planned_budget": p.planned_budget,
                "approved_budget": p.approved_budget,
                "actual_budget": p.actual_budget,
                "end_date": p.end_date.isoformat() if p.end_date else None,
                "priority": p.priority.value if hasattr(p.priority, 'value') else p.priority,
            } for p in projects],
        }

# ── 12. CEO Enhanced Dashboard ──────────────────────────────────────

@app.get("/api/ceo/dashboard-enhanced")
def ceo_dashboard_enhanced():
    with Session(engine) as db:
        # Get latest work plan
        wp = db.query(AnnualWorkPlan).order_by(AnnualWorkPlan.year.desc()).first()
        wp_data = None
        if wp:
            projects = db.query(Project).filter(Project.work_plan_id == wp.id).all()
            total_planned = sum(p.planned_budget or 0 for p in projects)
            total_approved = sum(p.approved_budget or 0 for p in projects)
            total_actual = sum(p.actual_budget or 0 for p in projects)
            wp_data = {
                "id": wp.id, "name": wp.name, "year": wp.year,
                "total_budget": wp.total_budget,
                "total_projects": len(projects),
                "budget_planned": total_planned,
                "budget_approved": total_approved,
                "budget_actual": total_actual,
                "utilization": round(total_actual / max(total_approved, 1) * 100, 1),
            }
        # Per-department breakdown
        depts = db.query(Department).all()
        dept_breakdown = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        total_overdue_cross = 0
        for d in depts:
            projects = db.query(Project).filter(Project.department_id == d.id).all()
            if not projects:
                continue
            avg_progress = round(sum(p.progress_percentage or 0 for p in projects) / len(projects), 1)
            total_dept_approved = sum(p.approved_budget or 0 for p in projects)
            total_dept_actual = sum(p.actual_budget or 0 for p in projects)
            completed = sum(1 for p in projects if p.status == ProjectStatus.COMPLETED)
            in_progress = sum(1 for p in projects if p.status == ProjectStatus.IN_PROGRESS)
            overdue = 0
            for p in projects:
                if p.end_date and p.status not in (ProjectStatus.COMPLETED, ProjectStatus.CANCELLED):
                    ed = p.end_date
                    if hasattr(ed, 'tzinfo') and ed.tzinfo:
                        ed = ed.replace(tzinfo=None)
                    if ed and ed < now:
                        overdue += 1
            total_overdue_cross += overdue
            dept_breakdown.append({
                "department_id": d.id, "department_name": d.name,
                "color": d.color or "#6366f1",
                "project_count": len(projects),
                "completed": completed,
                "in_progress": in_progress,
                "overdue": overdue,
                "avg_progress": avg_progress,
                "budget_approved": total_dept_approved,
                "budget_actual": total_dept_actual,
                "budget_utilization": round(total_dept_actual / max(total_dept_approved, 1) * 100, 1),
            })
        total_all_projects = sum(d["project_count"] for d in dept_breakdown)
        total_all_completed = sum(d["completed"] for d in dept_breakdown)
        total_all_approved = sum(d["budget_approved"] for d in dept_breakdown)
        total_all_actual = sum(d["budget_actual"] for d in dept_breakdown)
        # All overdue projects list
        all_projects = db.query(Project).all()
        overdue_list = []
        for p in all_projects:
            if p.end_date and p.status not in (ProjectStatus.COMPLETED, ProjectStatus.CANCELLED):
                ed = p.end_date
                if hasattr(ed, 'tzinfo') and ed.tzinfo:
                    ed = ed.replace(tzinfo=None)
                if ed and ed < now:
                    dept_name = db.query(Department.name).filter(Department.id == p.department_id).scalar() or ""
                    mgr_name = db.query(User.name).filter(User.id == p.manager_id).scalar() or "" if p.manager_id else ""
                    overdue_list.append({
                        "project_id": p.id, "project_name": p.name,
                        "department_name": dept_name,
                        "manager_name": mgr_name,
                        "progress": p.progress_percentage,
                        "end_date": p.end_date.isoformat() if p.end_date else None,
                        "days_overdue": (now - ed).days,
                        "priority": p.priority.value if hasattr(p.priority, 'value') else p.priority,
                    })
        overdue_list.sort(key=lambda x: x["days_overdue"], reverse=True)
        return {
            "work_plan": wp_data,
            "summary": {
                "total_departments": len(dept_breakdown),
                "total_projects": total_all_projects,
                "total_completed": total_all_completed,
                "total_overdue": total_overdue_cross,
                "completion_rate": round(total_all_completed / max(total_all_projects, 1) * 100, 1),
                "budget_approved": total_all_approved,
                "budget_actual": total_all_actual,
                "budget_utilization": round(total_all_actual / max(total_all_approved, 1) * 100, 1),
            },
            "departments": dept_breakdown,
            "overdue_projects": overdue_list[:20],
        }

# ── 13. Gantt Data ──────────────────────────────────────────────────

@app.get("/api/gantt/data")
def gantt_data(work_plan_id: Optional[int] = None):
    if work_plan_id is None:
        raise HTTPException(400, "work_plan_id query parameter is required")
    with Session(engine) as db:
        wp = db.query(AnnualWorkPlan).filter(AnnualWorkPlan.id == work_plan_id).first()
        if not wp:
            raise HTTPException(404, "work plan not found")
        items = []
        # Work Plan level
        items.append({
            "id": f"wp_{wp.id}", "parent_id": None, "type": "work_plan",
            "name": wp.name, "start_date": None, "end_date": None,
            "progress": 0, "level": 0,
        })
        depts = db.query(Department).filter(Department.organization_id == wp.organization_id).all()
        for d in depts:
            projects = db.query(Project).filter(
                Project.department_id == d.id, Project.work_plan_id == wp.id
            ).all()
            if not projects:
                continue
            # Department level - use min/max dates from projects
            dept_dates = [p for p in projects if p.start_date or p.end_date]
            dept_start = min((p.start_date for p in dept_dates if p.start_date), default=None)
            dept_end = max((p.end_date for p in dept_dates if p.end_date), default=None)
            dept_progress = round(sum(p.progress_percentage or 0 for p in projects) / len(projects), 1) if projects else 0
            items.append({
                "id": f"dept_{d.id}", "parent_id": f"wp_{wp.id}", "type": "department",
                "name": d.name,
                "start_date": dept_start.isoformat() if dept_start else None,
                "end_date": dept_end.isoformat() if dept_end else None,
                "progress": dept_progress, "level": 1,
            })
            for p in projects:
                items.append({
                    "id": f"proj_{p.id}", "parent_id": f"dept_{d.id}", "type": "project",
                    "name": p.name,
                    "start_date": p.start_date.isoformat() if p.start_date else None,
                    "end_date": p.end_date.isoformat() if p.end_date else None,
                    "progress": p.progress_percentage or 0,
                    "status": p.status.value if hasattr(p.status, 'value') else p.status,
                    "level": 2, "project_id": p.id,
                })
                steps = db.query(ProjectStep).filter(ProjectStep.project_id == p.id).order_by(ProjectStep.position).all()
                for s in steps:
                    items.append({
                        "id": f"step_{s.id}",
                        "parent_id": f"proj_{p.id}",
                        "type": "step",
                        "name": s.name,
                        "start_date": s.start_date.isoformat() if s.start_date else None,
                        "end_date": s.end_date.isoformat() if s.end_date else None,
                        "progress": s.progress or 0,
                        "status": s.status,
                        "level": 3,
                    })
        # Dependencies
        deps = db.query(Dependency).all()
        dependencies = []
        for dep in deps:
            dep_type = dep.dependency_type.value if hasattr(dep.dependency_type, 'value') else dep.dependency_type
            source_icon = f"proj_{dep.source_id}" if dep.source_type == "project" else f"step_{dep.source_id}"
            target_icon = f"proj_{dep.target_id}" if dep.target_type == "project" else f"step_{dep.target_id}"
            dependencies.append({
                "id": dep.id,
                "from": source_icon,
                "to": target_icon,
                "type": dep_type,
                "lag_days": dep.lag_days,
            })
        return {"items": items, "dependencies": dependencies}

# ── 14. AI Project Insights ──────────────────────────────────────────

@app.post("/api/ai/project-insights/{project_id}")
def ai_project_insights(project_id: int, actor_id: int = Depends(current_user_id)):
    with Session(engine) as db:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "Project not found")
        insights = {"summary": "", "risks": [], "recommendations": [], "budget_health": "good", "schedule_health": "good"}
        mgr_name = db.query(User.name).filter(User.id == p.manager_id).scalar() or "לא הוגדר" if p.manager_id else "לא הוגדר"
        dept_name = db.query(Department.name).filter(Department.id == p.department_id).scalar() or ""
        status = p.status.value if hasattr(p.status, 'value') else p.status
        progress = p.progress_percentage or 0
        now = datetime.now(timezone.utc)
        budget_util = round(p.actual_budget / max(p.approved_budget, 1) * 100, 1)
        # Summary
        summary_parts = [
            f"פרויקט: {p.name}",
            f"אגף: {dept_name}",
            f"מנהל: {mgr_name}",
            f"סטטוס: {status}",
            f"התקדמות: {progress}%",
        ]
        # Schedule analysis
        if p.end_date and p.status not in (ProjectStatus.COMPLETED, ProjectStatus.CANCELLED):
            end = p.end_date
            if hasattr(end, 'tzinfo') and end.tzinfo:
                end = end.replace(tzinfo=None)
            now_naive = now.replace(tzinfo=None)
            if end < now_naive:
                days_overdue = (now_naive - end).days
                insights["schedule_health"] = "critical"
                insights["risks"].append(f"⚠️ הפרויקט באיחור של {days_overdue} ימים")
                insights["recommendations"].append("נדרשת עדכון לוח זמנים ואישור מנהל אגף")
                summary_parts.append(f"איחור: {days_overdue} ימים")
            elif progress < 90 and (end - now_naive).days < 30:
                insights["schedule_health"] = "warning"
                insights["risks"].append(f"⚠️ צפוי איחור - נותרו {(end - now_naive).days} ימים בלבד")
                insights["recommendations"].append("האץ את הקצב או עדכן את לוח הזמנים")
                summary_parts.append(f"נותרו {(end - now_naive).days} ימים")
            else:
                days_left = (end - now_naive).days
                summary_parts.append(f"נראה בלוח זמנים, נותרו {max(days_left, 0)} ימים")
        else:
            summary_parts.append("לוח זמנים: הושלם או לא מוגדר")
        # Budget analysis
        if budget_util > 100:
            insights["budget_health"] = "critical"
            insights["risks"].append(f"💰 חריגת תקציב: מנוצל {budget_util}% (התקציב המאושר {p.approved_budget:,} ₪)")
            insights["recommendations"].append("דרוש אישור גזבר לחריגת תקציב")
            summary_parts.append(f"חריגת תקציב: {budget_util}%")
        elif budget_util > 85:
            insights["budget_health"] = "warning"
            insights["risks"].append(f"💰 ניצול תקציב גבוה: {budget_util}%")
            insights["recommendations"].append("מומלץ לבצע עדכון תקציבי בהקדם")
            summary_parts.append(f"ניצול תקציב: {budget_util}%")
        else:
            summary_parts.append(f"ניצול תקציב: {budget_util}%")
        # Line item analysis
        items = db.query(BudgetLineItem).filter(BudgetLineItem.project_id == project_id).all()
        for bi in items:
            item_util = round(bi.actual_amount / max(bi.approved_amount, 1) * 100, 1)
            if item_util > 100:
                item_name = bi.name or (bi.item_type.value if hasattr(bi.item_type, 'value') else bi.item_type)
                insights["risks"].append(f"💰 סעיף '{item_name}' חורג: {item_util}% ניצול")
                insights["recommendations"].append(f"בדוק את סעיף '{item_name}' - נדרשת אישור לחריגה")
        # Step analysis
        steps = db.query(ProjectStep).filter(ProjectStep.project_id == project_id).order_by(ProjectStep.position).all()
        for s in steps:
            if s.status == "pending" and s.position > 0:
                prev = db.query(ProjectStep).filter(
                    ProjectStep.project_id == project_id,
                    ProjectStep.position == s.position - 1
                ).first()
                if prev and prev.status != "completed" and prev.end_date and prev.end_date < now.replace(tzinfo=None):
                    insights["risks"].append(f"שלב '{s.name}' ממתין לשלב קודם שלא הושלם")
        if not insights["risks"]:
            insights["summary"] = "✅ " + " · ".join(summary_parts)
        else:
            insights["summary"] = " · ".join(summary_parts)
        if not insights["recommendations"] and insights["schedule_health"] == "good" and insights["budget_health"] == "good":
            insights["recommendations"].append("הפרויקט במצב תקין, אין צורך בפעולה מיידית")
        return insights
# ── Main ─────────────────────────────────────────────────────────────

# Serve frontend
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 CityOS running on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
