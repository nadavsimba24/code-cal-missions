"""
CityOS — FastAPI Backend Server
"""
import os, sys, json, uuid, csv, io
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
import os
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(__file__))
from models import (
    Organization, Department, User, Board, Group, Task, Comment, BoardMember, WorkspaceMember,
    Permit, CitizenRequest, PublicTransportStop, InfrastructureAsset,
    TaskStatus, Priority, BoardType, init_db,
    AnnualWorkPlan, Project, ProjectStep, BudgetLineItem,
    Approval, ChangeRequest, KPI, Dependency, Document, AuditLog,
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def no_cache_html(request, call_next):
    resp = await call_next(request)
    if "text/html" in resp.headers.get("content-type", ""):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
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

def _migrate():
    """Lightweight additive migrations for SQLite (create_all won't ALTER)."""
    from sqlalchemy import text
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(comments)"))}
        for name, ddl in [("parent_id", "INTEGER"), ("mentions", "JSON"), ("likes", "JSON"), ("seen_by", "JSON")]:
            if name not in cols:
                conn.execute(text(f"ALTER TABLE comments ADD COLUMN {name} {ddl}"))
        tcols = {r[1] for r in conn.execute(text("PRAGMA table_info(tasks)"))}
        if "permissions" not in tcols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN permissions JSON"))
        # notifications table may predate the task_id column (created before mentions)
        ncols = {r[1] for r in conn.execute(text("PRAGMA table_info(notifications)"))}
        if ncols and "task_id" not in ncols:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN task_id INTEGER"))
        # users: job title + contact phone (for the profile card)
        ucols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)"))}
        if "title" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN title VARCHAR(120)"))
        if "email_notifications" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_notifications BOOLEAN DEFAULT 1"))
        if "notif_prefs" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN notif_prefs JSON"))
        if "is_active" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
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
    # Postgres: create_all builds new tables fully, but seen_by (read receipts)
    # was added to the already-existing comments table — add it if missing.
    from sqlalchemy import text as _text
    try:
        with engine.begin() as _conn:
            _conn.execute(_text("ALTER TABLE comments ADD COLUMN IF NOT EXISTS seen_by JSON"))
            _conn.execute(_text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS task_id INTEGER"))
    except Exception:
        pass

# Seed on first run only — on a persistent DB (Postgres) skip if data exists,
# so real data isn't duplicated or overwritten on every cold start.
from seed import seed_database, seed_work_plan
with Session(engine) as _seed_db:
    _db_empty = _seed_db.query(Board).count() == 0
if _db_empty:
    seed_database(engine)
    seed_work_plan(engine)

def _seed_memberships():
    """One-time: give existing boards their members so nothing disappears.
    New boards start private to their creator (see create_board)."""
    with Session(engine) as db:
        users = db.query(User).all()
        # workspace/environment members
        if db.query(WorkspaceMember).count() == 0:
            for u in users:
                erole = "admin" if u.role in ("admin", "manager") else ("viewer" if u.role == "viewer" else "member")
                db.add(WorkspaceMember(user_id=u.id, role=erole))
            db.commit()
        # board members
        if db.query(BoardMember).count() == 0:
            for b in db.query(Board).all():
                for u in users:
                    role = "viewer" if u.role == "viewer" else ("admin" if u.role in ("admin", "manager") else "editor")
                    db.add(BoardMember(board_id=b.id, user_id=u.id, role=role))
            db.commit()
_seed_memberships()

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
    tags: list; custom_fields: dict; is_archived: bool
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

@app.get("/api/status")
def status():
    return {"status": "ok", "app": "CODE-CAL MISSIONS", "version": "0.1.0"}

@app.get("/api/dashboard")
def dashboard(user_id: Optional[int] = None):
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
# group auto-move, parent roll-up, kanban and charts keep working (they all key
# off task.status) while a board admin may rename/recolor/reorder the statuses
# and expose only the ones the board actually uses.
STATUS_DEFAULTS = [
    {"key": "backlog", "label": "בתכנון", "color": "#9699a6"},
    {"key": "todo", "label": "לביצוע", "color": "#c4c4c4"},
    {"key": "in_progress", "label": "בתהליך", "color": "#fdab3d"},
    {"key": "review", "label": "בבדיקה", "color": "#579bfc"},
    {"key": "on_hold", "label": "בהמתנה", "color": "#808080"},
    {"key": "done", "label": "הושלם", "color": "#00c875"},
    {"key": "cancelled", "label": "בוטל", "color": "#e2445c"},
]
_STATUS_KEYS = {s["key"] for s in STATUS_DEFAULTS}

def _valid_hex(c):
    c = str(c or "")
    if len(c) == 7 and c[0] == "#":
        try:
            int(c[1:], 16); return True
        except ValueError:
            return False
    return False

def _board_statuses(b):
    """The board's ordered status list (defaults when the admin hasn't customised)."""
    raw = (b.settings or {}).get("statuses")
    if not raw:
        return [dict(x) for x in STATUS_DEFAULTS]
    out, seen = [], set()
    for it in raw:
        k = (it or {}).get("key")
        if k in _STATUS_KEYS and k not in seen:
            seen.add(k)
            out.append({"key": k, "label": (it.get("label") or k), "color": (it.get("color") or "#c4c4c4")})
    return out or [dict(x) for x in STATUS_DEFAULTS]

def _board_role(db, board_id, user_id):
    """Board-scoped role (admin/editor/viewer) for a user, or None if not a member."""
    if user_id is None:
        return None
    m = db.query(BoardMember).filter(BoardMember.board_id == board_id,
                                     BoardMember.user_id == user_id).first()
    return m.role if m else None

def _is_board_admin(db, board_id, user_id):
    return _board_role(db, board_id, user_id) == "admin"

def _visible_board_ids(db, user_id):
    """Set of board IDs a user is allowed to see (membership-based).
    Mirrors /api/boards visibility so aggregate views (dashboard, CEO,
    insights) never leak boards the user was not invited to.
    user_id=None keeps legacy 'all boards' behavior for internal callers."""
    all_ids = {b for (b,) in db.query(Board.id).filter(Board.is_archived == False).all()}
    if user_id is None:
        return all_ids
    member_ids = {m.board_id for m in db.query(BoardMember).filter(BoardMember.user_id == user_id).all()}
    return {i for i in all_ids if i in member_ids}

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

def _col_perm(col, user_id, board_role):
    """Effective permission on a column for a user: none|view|edit."""
    ov = (col.get("perms") or {}).get(str(user_id))
    if ov in ("none", "view", "edit"):
        return ov
    caps = _board_caps(board_role)
    return "edit" if "edit" in caps else ("view" if "view" in caps else "none")

@app.get("/api/boards")
def list_boards(user_id: Optional[int] = None):
    with Session(engine) as db:
        boards = db.query(Board).filter(Board.is_archived == False).all()
        if user_id is not None:
            # membership-based visibility: you only see boards you were invited to
            member_ids = {m.board_id for m in db.query(BoardMember).filter(BoardMember.user_id == user_id).all()}
            boards = [b for b in boards if b.id in member_ids]
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
                "task_count": task_count,
                "my_role": _board_role(db, b.id, user_id) if user_id is not None else None,
                "groups": [{"id": g.id, "name": g.name, "position": g.position, "color": g.color, "task_status": g.task_status.value if hasattr(g.task_status, 'value') else g.task_status} for g in groups],
            })
        return result

def _serialize_task(t, db, with_subs=True, user_id=None, board_role=None, columns=None):
    assignees = [{"id": u.id, "name": u.name, "avatar_url": u.avatar_url} for u in t.assignees] if t.assignees else []
    subtask_count = db.query(Task).filter(Task.parent_id == t.id).count()
    comment_count = db.query(Comment).filter(Comment.task_id == t.id).count()
    my_perm = _item_perm(t, user_id, board_role) if user_id is not None else "delete"
    cf = dict(t.custom_fields or {})
    col_perms = {}
    if user_id is not None:
        for c in (columns or []):
            cp = _col_perm(c, user_id, board_role)
            col_perms[c["id"]] = cp
            if cp == "none":         # view-restricted column → mask its value
                cf.pop(c["id"], None)
    d = {
        "id": t.id, "board_id": t.board_id, "group_id": t.group_id,
        "parent_id": t.parent_id,
        "title": t.title, "description": t.description,
        "status": t.status.value if hasattr(t.status, 'value') else t.status,
        "priority": t.priority.value if hasattr(t.priority, 'value') else t.priority,
        "position": t.position, "due_date": t.due_date,
        "start_date": t.start_date,
        "estimated_hours": t.estimated_hours, "actual_hours": t.actual_hours,
        "location_lat": t.location_lat, "location_lng": t.location_lng,
        "address": t.address, "tags": t.tags or [],
        "custom_fields": cf,
        "permissions": t.permissions or {},
        "my_perm": my_perm,
        "col_perms": col_perms,
        "is_archived": t.is_archived,
        "created_by": t.created_by,
        "created_at": t.created_at, "updated_at": t.updated_at,
        "assignees": assignees,
        "subtask_count": subtask_count,
        "comment_count": comment_count,
    }
    if with_subs:
        subs = db.query(Task).filter(Task.parent_id == t.id, Task.is_archived == False).order_by(Task.position).all()
        subs = [s for s in subs if user_id is None or _item_perm(s, user_id, board_role) != "none"]
        d["subtasks"] = [_serialize_task(s, db, with_subs=False, user_id=user_id, board_role=board_role, columns=columns) for s in subs]
    return d

@app.get("/api/boards/{board_id}")
def get_board(board_id: int, user_id: Optional[int] = None):
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "Board not found")
        my_role = _board_role(db, board_id, user_id)
        if user_id is not None and my_role is None:
            raise HTTPException(403, "אין לך גישה ללוח זה")
        groups = db.query(Group).filter(Group.board_id == b.id).order_by(Group.position).all()
        # only top-level items as rows; sub-items are nested under their parent
        tasks = db.query(Task).filter(Task.board_id == b.id, Task.is_archived == False,
                                      Task.parent_id == None).order_by(Task.position).all()
        dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
        columns = (b.settings or {}).get("columns", [])
        # hide items the user has no view permission on
        if user_id is not None:
            tasks = [t for t in tasks if _item_perm(t, user_id, my_role) != "none"]
        tasks_out = [_serialize_task(t, db, user_id=user_id, board_role=my_role, columns=columns) for t in tasks]

        # board owners = members with the board-scoped admin role (creator + any
        # promoted admin). Exposed to every member so anyone can see who manages it.
        owners = []
        for m in db.query(BoardMember).filter(BoardMember.board_id == b.id, BoardMember.role == "admin").all():
            ou = db.query(User).filter(User.id == m.user_id).first()
            if ou:
                owners.append({"id": ou.id, "name": ou.name, "avatar_url": ou.avatar_url})

        return {
            "id": b.id, "name": b.name, "description": b.description,
            "board_type": b.board_type.value if hasattr(b.board_type, 'value') else b.board_type,
            "icon": b.icon, "color": b.color,
            "is_archived": b.is_archived,
            "department_name": dept_name,
            "views": _board_views(b),
            "view_only": (b.settings or {}).get("view_only", False),
            "my_role": my_role,
            "owners": owners,
            "columns": (b.settings or {}).get("columns", []),
            "col_widths": (b.settings or {}).get("col_widths", {}),
            "col_labels": (b.settings or {}).get("col_labels", {}),
            "notifications_enabled": bool((b.settings or {}).get("notifications_enabled", True)),
            "statuses": _board_statuses(b),
            "form": (b.settings or {}).get("form"),
            "groups": [{"id": g.id, "name": g.name, "position": g.position, "color": g.color, "task_status": g.task_status.value if hasattr(g.task_status, 'value') else g.task_status} for g in groups],
            "tasks": tasks_out,
        }

@app.post("/api/boards")
def create_board(data: dict):
    with Session(engine) as db:
        # only a system (workspace) admin may create boards; the creator becomes
        # the board's first admin, so a board is never created without a manager.
        creator = data.get("user_id")
        if _ws_role(db, creator) != "admin":
            raise HTTPException(403, "רק מנהל מערכת יכול ליצור לוח חדש")
        dept_id = data.get("department_id")
        if not dept_id:
            dept_id = db.query(Department.id).order_by(Department.id).limit(1).scalar()
        b = Board(
            name=data.get("name", "לוח חדש"),
            description=data.get("description", ""),
            department_id=dept_id,
            board_type=BoardType.KANBAN,
            icon=data.get("icon", "📋"),
            color=data.get("color", "#0073ea"),
            settings={"views": ["table"]},  # new boards start with only the main table
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
        # 3 starter items in the first group so the board isn't blank
        for i in range(1, 4):
            db.add(Task(board_id=b.id, group_id=g1.id, title=f"פריט {i}",
                        status=TaskStatus.BACKLOG, priority=Priority.MEDIUM, position=i))
        # creator becomes the board admin; the board is private until they invite others
        db.add(BoardMember(board_id=b.id, user_id=creator, role="admin"))
        db.commit()
        db.refresh(b)
        return {"id": b.id, "name": b.name, "icon": b.icon, "views": _board_views(b), "my_role": "admin"}

@app.patch("/api/boards/{board_id}")
def update_board(board_id: int, data: dict):
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
        if "form" in data:
            # only a board admin can add/update the form
            if _board_role(db, board_id, data.get("user_id")) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לערוך את הטופס")
            s = dict(b.settings or {})
            s["form"] = data["form"]
            b.settings = s
        if data.get("col_widths") is not None:
            # only a board admin may set column widths (drag-to-resize)
            if _board_role(db, board_id, data.get("user_id")) != "admin":
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
            # rename a built-in column header (e.g. "פריט") — workspace admin only
            if _ws_role(db, data.get("user_id")) != "admin":
                raise HTTPException(403, "רק מנהל מערכת יכול לשנות שם עמודה")
            builtin = {"item", "assignees", "status", "priority", "due", "tags"}
            labels = {}
            for k, v in (data["col_labels"] or {}).items():
                if k in builtin:
                    lv = str(v or "").strip()[:40]
                    if lv:
                        labels[str(k)] = lv
            s = dict(b.settings or {})
            s["col_labels"] = labels
            b.settings = s
        if "notifications_enabled" in data:
            # board admin toggles all notifications for this board on/off
            if _board_role(db, board_id, data.get("user_id")) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לשנות התראות ללוח")
            s = dict(b.settings or {})
            s["notifications_enabled"] = bool(data["notifications_enabled"])
            b.settings = s
        if data.get("statuses") is not None:
            # only a board admin may rename/recolor/reorder/add statuses
            if _board_role(db, board_id, data.get("user_id")) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לערוך סטטוסים")
            out, seen = [], set()
            for it in data["statuses"]:
                if not isinstance(it, dict):
                    continue
                k = it.get("key")
                if k not in _STATUS_KEYS or k in seen:
                    continue
                seen.add(k)
                label = (str(it.get("label") or "").strip())[:40] or k
                color = it.get("color") if _valid_hex(it.get("color")) else "#c4c4c4"
                out.append({"key": k, "label": label, "color": color})
            if not out:
                raise HTTPException(400, "חובה סטטוס אחד לפחות")
            s = dict(b.settings or {})
            s["statuses"] = out
            b.settings = s
        if data.get("columns") is not None:
            # only a board admin may add/edit/remove columns and their options
            if _board_role(db, board_id, data.get("user_id")) != "admin":
                raise HTTPException(403, "רק מנהל הלוח יכול לערוך עמודות")
            # full replacement of the custom-column definitions
            allowed = {"timeline", "text", "number", "date", "rating", "status",
                       "people", "dropdown", "files", "accounts", "checkbox", "formula",
                       "connect"}
            old_cols = {c.get("id"): c for c in (b.settings or {}).get("columns", [])}
            is_ws_admin = _ws_role(db, data.get("user_id")) == "admin"
            cols = []
            for c in data["columns"]:
                if not isinstance(c, dict) or c.get("type") not in allowed:
                    continue
                cid = c.get("id") or ("col_" + uuid.uuid4().hex[:8])
                if c["type"] == "connect":
                    # only a workspace (system) admin may create/change a connect column
                    prev = old_cols.get(cid)
                    changed = (not prev) or prev.get("type") != "connect" or prev.get("connect") != c.get("connect")
                    if changed and not is_ws_admin:
                        raise HTTPException(403, "רק מנהל מערכת יכול להוסיף או לשנות עמודת קישור בין לוחות")
                cols.append({
                    "id": cid,
                    "type": c["type"],
                    "title": c.get("title") or c["type"],
                    "options": c.get("options"),
                    "formula": c.get("formula"),
                    "connect": c.get("connect") if c["type"] == "connect" else None,
                    "perms": c.get("perms") or {},
                })
            s = dict(b.settings or {})
            s["columns"] = cols
            b.settings = s
        db.commit()
        db.refresh(b)
        return {"id": b.id, "name": b.name, "icon": b.icon, "color": b.color,
                "views": _board_views(b), "columns": (b.settings or {}).get("columns", [])}

@app.delete("/api/boards/{board_id}")
def delete_board(board_id: int, user_id: Optional[int] = None):
    """Delete a board and everything under it (groups, items, comments,
    memberships). Only a board admin may delete it."""
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "board not found")
        if user_id is not None and _board_role(db, board_id, user_id) != "admin":
            raise HTTPException(403, "רק מנהל הלוח יכול למחוק אותו")
        tasks = db.query(Task).filter(Task.board_id == board_id).all()
        task_ids = [t.id for t in tasks]
        if task_ids:
            db.query(Comment).filter(Comment.task_id.in_(task_ids)).delete(synchronize_session=False)
        for t in tasks:          # clear assignee links via the ORM relationship
            t.assignees = []
        db.flush()
        db.query(Task).filter(Task.board_id == board_id).delete(synchronize_session=False)
        db.query(Group).filter(Group.board_id == board_id).delete(synchronize_session=False)
        db.query(BoardMember).filter(BoardMember.board_id == board_id).delete(synchronize_session=False)
        db.delete(b)
        db.commit()
        return {"status": "deleted", "id": board_id}

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


def _send_email(to_email, subject, html):
    """Send a transactional email via Resend. No-ops (logs) when RESEND_API_KEY
    isn't configured, so an invite never fails just because email isn't set up."""
    import urllib.request, json as _json
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key or not to_email:
        print(f"[email] skipped (no RESEND_API_KEY) → {to_email}: {subject}")
        return False
    from_addr = os.environ.get("INVITE_FROM_EMAIL", "CityOS <onboarding@resend.dev>")
    # development mode: until a domain is verified in Resend, real recipients are
    # blocked. Redirect every message to a single verified inbox so invites can be
    # tested end-to-end, keeping the original recipient visible in the email.
    redirect = os.environ.get("EMAIL_DEV_REDIRECT")
    actual_to = to_email
    if redirect:
        actual_to = redirect
        subject = f"[פיתוח · נועד ל-{to_email}] {subject}"
        html = (f"<div dir='rtl' style='background:#fff3cd;border:1px solid #ffe08a;"
                f"border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:12.5px;"
                f"font-family:Arial'>⚙️ מצב פיתוח — הנמען המקורי של ההזמנה הוא "
                f"<b>{to_email}</b>. מייל זה הופנה אליך לצורכי בדיקה.</div>") + html
    payload = _json.dumps({"from": from_addr, "to": [actual_to],
                           "subject": subject, "html": html}).encode("utf-8")
    req = urllib.request.Request("https://api.resend.com/emails", data=payload,
                                 headers={"Authorization": f"Bearer {api_key}",
                                          "Content-Type": "application/json",
                                          "User-Agent": "CityOS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        print(f"[email] sent → {actual_to}: {subject}")
        return True
    except Exception as e:
        print(f"[email] send failed → {actual_to}: {e}")
        return False


def _board_invite_html(invitee_name, board_name, inviter_name, role):
    role_he = BROLE_HE.get(role, role)
    base = os.environ.get("APP_BASE_URL", "https://code-cal-missions.vercel.app")
    return f"""<div dir="rtl" style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#1a1a2e">
      <div style="background:#0073ea;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0">
        <h2 style="margin:0;font-size:20px">הוזמנת ללוח ב-CityOS</h2>
      </div>
      <div style="border:1px solid #e6e9ef;border-top:none;border-radius:0 0 12px 12px;padding:22px">
        <p style="font-size:15px">שלום {invitee_name},</p>
        <p style="font-size:15px"><b>{inviter_name}</b> הזמין/ה אותך ללוח <b>{board_name}</b> במערכת CityOS של עיריית הוד השרון.</p>
        <table style="width:100%;font-size:14px;border-collapse:collapse;margin:16px 0">
          <tr><td style="padding:8px 0;color:#676879">שם הלוח</td><td style="padding:8px 0;font-weight:600">{board_name}</td></tr>
          <tr><td style="padding:8px 0;color:#676879">ההרשאה שלך</td><td style="padding:8px 0;font-weight:600">{role_he}</td></tr>
          <tr><td style="padding:8px 0;color:#676879">הוזמנת על ידי</td><td style="padding:8px 0;font-weight:600">{inviter_name}</td></tr>
        </table>
        <a href="{base}" style="display:inline-block;background:#0073ea;color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;font-size:15px">כניסה למערכת</a>
        <p style="color:#9699a6;font-size:12px;margin-top:22px">מייל זה נשלח אוטומטית ממערכת CityOS. אם לא ציפית לו, אפשר להתעלם ממנו.</p>
      </div>
    </div>"""

@app.get("/api/boards/{board_id}/members")
def list_board_members(board_id: int):
    with Session(engine) as db:
        ms = db.query(BoardMember).filter(BoardMember.board_id == board_id).all()
        member_ids = {m.user_id for m in ms}
        out = []
        for m in ms:
            u = db.query(User).filter(User.id == m.user_id).first()
            out.append({"user_id": m.user_id, "name": u.name if u else "—",
                        "email": u.email if u else "", "role": m.role})
        # users who could still be invited
        available = [{"id": u.id, "name": u.name} for u in db.query(User).all() if u.id not in member_ids]
        return {"members": out, "available": available}

@app.post("/api/boards/{board_id}/members")
def add_board_member(board_id: int, data: dict):
    with Session(engine) as db:
        if not _is_board_admin(db, board_id, data.get("actor_id")):
            raise HTTPException(403, "רק מנהל הלוח יכול לנהל הרשאות")
        uid = data.get("user_id")
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
        inviter = db.query(User).filter(User.id == data.get("actor_id")).first()
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
                            f"הוזמנת ללוח '{board.name}' ב-CityOS",
                            _board_invite_html(invitee.name, board.name,
                                               inviter.name if inviter else "מנהל הלוח", role))
        return {"status": "ok", "invited": is_new}

@app.patch("/api/boards/{board_id}/members/{uid}")
def update_board_member(board_id: int, uid: int, data: dict):
    with Session(engine) as db:
        if not _is_board_admin(db, board_id, data.get("actor_id")):
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
def remove_board_member(board_id: int, uid: int, actor_id: Optional[int] = None):
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
def list_notifications(user_id: Optional[int] = None, limit: int = 30):
    if user_id is None:
        raise HTTPException(400, "user_id required")
    with Session(engine) as db:
        q = db.query(Notification).filter(Notification.user_id == user_id)
        unread = q.filter(Notification.is_read == False).count()
        items = q.order_by(Notification.created_at.desc()).limit(max(1, min(100, limit))).all()
        return {"notifications": [_serialize_notif(n) for n in items], "unread_count": unread}

@app.post("/api/notifications/{nid}/read")
def read_notification(nid: int, data: dict):
    with Session(engine) as db:
        n = db.query(Notification).filter(Notification.id == nid,
                                          Notification.user_id == data.get("user_id")).first()
        if n and not n.is_read:
            n.is_read = True
            db.commit()
        return {"status": "ok"}

@app.post("/api/notifications/read-all")
def read_all_notifications(data: dict):
    uid = data.get("user_id")
    if uid is None:
        raise HTTPException(400, "user_id required")
    with Session(engine) as db:
        db.query(Notification).filter(Notification.user_id == uid,
                                      Notification.is_read == False).update({Notification.is_read: True})
        db.commit()
        return {"status": "ok"}

# ── Column-level permissions (הרשאות עמודה) ─────────────────────────
@app.post("/api/boards/{board_id}/columns/{col_id}/permissions")
def set_col_permissions(board_id: int, col_id: str, data: dict):
    with Session(engine) as db:
        if _board_role(db, board_id, data.get("actor_id")) != "admin":
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
                        "email": u.email if u else "", "role": m.role})
        available = [{"id": u.id, "name": u.name} for u in db.query(User).all() if u.id not in member_ids]
        return {"members": out, "available": available}

@app.post("/api/workspace/members")
def workspace_add(data: dict):
    with Session(engine) as db:
        if _ws_role(db, data.get("actor_id")) != "admin":
            raise HTTPException(403, "רק מנהל סביבה יכול להזמין")
        uid = data.get("user_id"); role = data.get("role", "member")
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
def workspace_update(uid: int, data: dict):
    with Session(engine) as db:
        if _ws_role(db, data.get("actor_id")) != "admin":
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
def workspace_remove(uid: int, actor_id: Optional[int] = None):
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
                "tags": t.tags or [],
                "assignees": assignees,
            })
        return result

@app.post("/api/tasks")
def create_task(data: dict):
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
        if not db.query(Board.id).filter(Board.id == board_id).scalar():
            raise HTTPException(404, "board not found")
        task = Task(
            board_id=board_id,
            group_id=group_id,
            parent_id=parent_id,
            title=data.get("title", "Untitled"),
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            tags=data.get("tags", []),
            location_lat=data.get("location_lat"),
            location_lng=data.get("location_lng"),
            address=data.get("address"),
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
        ids = data.get("assignee_ids") or []
        if ids:
            task.assignees = db.query(User).filter(User.id.in_(ids)).all()
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
        # notify anyone assigned at creation time (skip the creator), honoring the switch
        if ids:
            board = db.query(Board).filter(Board.id == board_id).first()
            if _board_notify_on(board):
                actor = data.get("actor_id") or data.get("user_id")
                for aid in set(ids):
                    if aid != actor:
                        _notify(db, aid, "assign", "שויכת למשימה",
                                f"שויכת למשימה '{task.title}'.", board_id=board_id, task_id=task.id)
        db.commit()
        return {"id": task.id, "status": "created"}

# ── Cross-board item linking (connect column) ───────────────────────
@app.get("/api/items/search")
def items_search(board_ids: str = "", q: str = "", exclude_task: Optional[int] = None, limit: int = 60):
    """Top-level items across the given boards, for the connect-column picker."""
    ids = [int(x) for x in board_ids.split(",") if x.strip().isdigit()]
    with Session(engine) as db:
        query = db.query(Task).filter(Task.is_archived == False, Task.parent_id == None)
        if ids:
            query = query.filter(Task.board_id.in_(ids))
        if q.strip():
            query = query.filter(Task.title.ilike(f"%{q.strip()}%"))
        if exclude_task:
            query = query.filter(Task.id != exclude_task)
        rows = query.order_by(Task.board_id, Task.position).limit(max(1, min(200, limit))).all()
        bnames = {b.id: b.name for b in db.query(Board).all()}
        return {"items": [{"id": t.id, "title": t.title, "board_id": t.board_id,
                           "board_name": bnames.get(t.board_id, ""),
                           "status": t.status.value if hasattr(t.status, "value") else t.status}
                          for t in rows]}

@app.get("/api/tasks/lookup")
def tasks_lookup(ids: str = ""):
    """Resolve item ids → title/board, to display linked items in a connect cell."""
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        return {"items": []}
    with Session(engine) as db:
        rows = db.query(Task).filter(Task.id.in_(id_list)).all()
        bnames = {b.id: b.name for b in db.query(Board).all()}
        return {"items": [{"id": t.id, "title": t.title, "board_id": t.board_id,
                           "board_name": bnames.get(t.board_id, "")} for t in rows]}

# each status belongs to a coarse stage, so a status change can still find a
# sensible group even when the board has fewer groups than statuses (e.g. the
# 3 default groups). Exact task_status match is always preferred over the stage.
STATUS_STAGE = {
    "backlog": "todo", "todo": "todo",
    "in_progress": "active", "review": "active", "on_hold": "active",
    "done": "done", "cancelled": "done",
}


def _group_for_status(db, board_id, status_val):
    """Return the group a top-level item should move to for the given status:
    first a group whose task_status matches exactly, else one in the same stage."""
    sv = status_val.value if hasattr(status_val, "value") else status_val
    groups = db.query(Group).filter(Group.board_id == board_id).order_by(Group.position).all()
    gs_of = lambda g: (g.task_status.value if hasattr(g.task_status, "value") else g.task_status)
    for g in groups:                       # 1) exact status match
        if gs_of(g) == sv:
            return g
    stage = STATUS_STAGE.get(sv)           # 2) same-stage fallback
    if stage:
        for g in groups:
            if STATUS_STAGE.get(gs_of(g)) == stage:
                return g
    return None


def _st_of(t):
    return t.status.value if hasattr(t.status, "value") else t.status


def _rollup_parent(db, parent_id):
    """When every sub-item of a parent is done, mark the parent done too and move
    it to the matching group."""
    parent = db.query(Task).filter(Task.id == parent_id).first()
    if not parent:
        return
    subs = db.query(Task).filter(Task.parent_id == parent_id).all()
    if not subs:
        return
    if all(_st_of(s) == "done" for s in subs) and _st_of(parent) != "done":
        parent.status = TaskStatus.DONE
        g = _group_for_status(db, parent.board_id, TaskStatus.DONE)
        if g:
            parent.group_id = g.id


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, data: dict):
    """Generic item update — title, priority, status, due_date, and custom column
    values (merged into custom_fields). Used by the editable board columns."""
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        actor = data.get("user_id")
        # ── permission enforcement (item level, and column level for custom_fields) ──
        actor_role = _board_role(db, task.board_id, actor) if actor is not None else None
        editing_builtin = any(k in data for k in ("title", "description", "priority", "status", "due_date", "tags"))
        if actor is not None:
            iperm = _item_perm(task, actor, actor_role)
            if editing_builtin and iperm not in ("edit", "delete"):
                raise HTTPException(403, "אין לך הרשאת עריכה לפריט זה")
            if "custom_fields" in data and isinstance(data["custom_fields"], dict):
                cols = {c["id"]: c for c in (db.query(Board).filter(Board.id == task.board_id).first().settings or {}).get("columns", [])}
                for k in list(data["custom_fields"].keys()):
                    col = cols.get(k)
                    if col is not None and _col_perm(col, actor, actor_role) != "edit":
                        del data["custom_fields"][k]      # silently drop cols the user can't edit
                if iperm not in ("edit", "delete"):
                    data["custom_fields"] = {}
        st_val = lambda v: (v.value if hasattr(v, "value") else v)
        if data.get("title") is not None and data["title"] != task.title:
            _audit(db, task_id, "update", "title", task.title, data["title"], actor)
            task.title = data["title"]
        if data.get("description") is not None:
            task.description = data["description"]
        if data.get("priority"):
            try:
                nv = Priority(data["priority"])
                if st_val(task.priority) != st_val(nv):
                    _audit(db, task_id, "update", "priority", st_val(task.priority), st_val(nv), actor)
                task.priority = nv
            except ValueError:
                pass
        if data.get("status"):
            try:
                nv = TaskStatus(data["status"])
                if st_val(task.status) != st_val(nv):
                    _audit(db, task_id, "update", "status", st_val(task.status), st_val(nv), actor)
                task.status = nv
                # auto-move a top-level item to the group that matches its status
                # (exact status first, else same stage — e.g. "done" → "הושלם")
                if task.parent_id is None:
                    g = _group_for_status(db, task.board_id, nv)
                    if g:
                        task.group_id = g.id
                else:
                    # roll up: parent auto-completes once all its sub-items are done
                    _rollup_parent(db, task.parent_id)
            except ValueError:
                pass
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
        if "tags" in data and isinstance(data["tags"], list):
            old_tags = task.tags or []
            if old_tags != data["tags"]:
                _audit(db, task_id, "update", "tags", ", ".join(old_tags), ", ".join(data["tags"]), actor)
            task.tags = data["tags"]
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
                old = cf.get(k)
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
            task.custom_fields = cf
        db.commit()
        return {"id": task.id, "custom_fields": task.custom_fields or {}}

# ── File uploads (for the Files column) ─────────────────────────────
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB per file

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Store the upload in the DB so it persists and is shared across serverless
    instances (Vercel's local filesystem is ephemeral and per-instance)."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "הקובץ גדול מדי (מקסימום 10MB)")
    token = uuid.uuid4().hex
    with Session(engine) as db:
        db.add(UploadedFile(token=token, name=file.filename or "file",
                            content_type=file.content_type or "application/octet-stream",
                            data=content, size=len(content)))
        db.commit()
    return {"name": file.filename, "url": f"/api/files/{token}"}

@app.get("/api/files/{token}")
def serve_file(token: str):
    with Session(engine) as db:
        f = db.query(UploadedFile).filter(UploadedFile.token == token).first()
        if not f:
            raise HTTPException(404, "file not found")
        from urllib.parse import quote
        disp = f"inline; filename*=UTF-8''{quote(f.name or 'file')}"
        return Response(content=f.data, media_type=f.content_type or "application/octet-stream",
                        headers={"Content-Disposition": disp, "Cache-Control": "public, max-age=31536000"})

@app.post("/api/tasks/{task_id}/permissions")
def set_item_permissions(task_id: int, data: dict):
    """Set/clear a per-user permission on a single item. Board managers (admin) only.
    perm ∈ view|edit|delete|none  (none = pass to null to remove the override)."""
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        actor = data.get("actor_id")
        if _board_role(db, task.board_id, actor) != "admin":
            raise HTTPException(403, "רק מנהל לוח יכול לקבוע הרשאות פריט")
        perms = dict(task.permissions or {})
        uid = str(data.get("user_id"))
        perm = data.get("perm")
        if perm in ("view", "edit", "delete", "none"):
            perms[uid] = perm
        else:
            perms.pop(uid, None)   # clear override → falls back to board role
        task.permissions = perms
        db.commit()
        return {"id": task.id, "permissions": task.permissions}

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, user_id: Optional[int] = None):
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        if user_id is not None:
            role = _board_role(db, task.board_id, user_id)
            if _item_perm(task, user_id, role) != "delete":
                raise HTTPException(403, "אין לך הרשאת מחיקה לפריט זה")
        # remove sub-items along with the parent
        for s in db.query(Task).filter(Task.parent_id == task_id).all():
            db.delete(s)
        db.delete(task)
        db.commit()
        return {"status": "deleted"}

# ── Item conversation (comments), files & activity log ──────────────

def _acting_user(db, data=None, uid=None):
    if data and data.get("user_id") is not None:
        uid = data.get("user_id")
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
    return {
        "id": c.id, "task_id": c.task_id, "parent_id": c.parent_id,
        "content": c.content, "attachments": c.attachments or [],
        "mentions": c.mentions or [], "likes": c.likes or [],
        "seen_users": seen_users,
        "user_id": c.user_id, "user_name": u.name if u else "—",
        "user_role": u.role if u else None, "created_at": c.created_at,
    }

@app.get("/api/tasks/{task_id}/comments")
def list_comments(task_id: int):
    with Session(engine) as db:
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
def add_comment(task_id: int, data: dict):
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        board = db.query(Board).filter(Board.id == task.board_id).first()
        user = _acting_user(db, data)
        if not _can_comment(db, board, user):
            raise HTTPException(403, "אין הרשאת תגובה (צפייה בלבד)")
        content = (data.get("content") or "").strip()
        atts = data.get("attachments") or []
        if not content and not atts:
            raise HTTPException(400, "תגובה ריקה")
        c = Comment(task_id=task_id, user_id=user.id, parent_id=data.get("parent_id"),
                    content=content, attachments=atts,
                    mentions=data.get("mentions") or [], likes=[], seen_by=[])
        db.add(c)
        _audit(db, task_id, "comment", field="reply" if data.get("parent_id") else "comment",
               new=(content[:120] or "(קובץ)"), user_id=user.id)
        # notify every tagged user (explicit @-picks + any @Name typed in the text),
        # excluding the author, honoring the board's notification switch
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
        mentioned.discard(user.id)
        if mentioned and _board_notify_on(board):
            for mid in mentioned:
                _notify(db, mid, "mention", "תויגת בשיחה",
                        f"{user.name} תייג/ה אותך במשימה '{task.title}'.",
                        board_id=task.board_id, task_id=task_id)
        db.commit(); db.refresh(c)
        return _serialize_comment(c, db)

@app.post("/api/comments/{cid}/like")
def like_comment(cid: int, data: dict):
    with Session(engine) as db:
        c = db.query(Comment).filter(Comment.id == cid).first()
        if not c:
            raise HTTPException(404, "comment not found")
        user = _acting_user(db, data)
        if not user:
            raise HTTPException(403, "אין משתמש")
        likes = list(c.likes or [])
        if user.id in likes:
            likes.remove(user.id)
        else:
            likes.append(user.id)
        c.likes = likes
        db.commit()
        return {"id": cid, "likes": likes}

@app.post("/api/tasks/{task_id}/comments/seen")
def mark_comments_seen(task_id: int, data: dict):
    """Mark every message in the item as seen by the acting user (read receipts).
    A user's own messages are skipped — you don't 'see' your own."""
    with Session(engine) as db:
        user = _acting_user(db, data)
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
def update_comment(cid: int, data: dict):
    with Session(engine) as db:
        c = db.query(Comment).filter(Comment.id == cid).first()
        if not c:
            raise HTTPException(404, "comment not found")
        user = _acting_user(db, data)
        if not user or (c.user_id != user.id and user.role not in ("admin", "manager")):
            raise HTTPException(403, "אין הרשאה לערוך תגובה")
        if "content" in data:
            c.content = data["content"]
        db.commit()
        return _serialize_comment(c, db)

@app.delete("/api/comments/{cid}")
def delete_comment(cid: int, user_id: Optional[int] = None):
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
def task_files(task_id: int):
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        out = []
        for c in db.query(Comment).filter(Comment.task_id == task_id).order_by(Comment.created_at.desc()).all():
            u = db.query(User).filter(User.id == c.user_id).first()
            for f in (c.attachments or []):
                out.append({**f, "source": "שיחה", "user_name": u.name if u else None, "created_at": c.created_at})
        board = db.query(Board).filter(Board.id == task.board_id).first()
        cols = (board.settings or {}).get("columns", []) if board else []
        cf = task.custom_fields or {}
        for col in [c for c in cols if c.get("type") == "files"]:
            for f in (cf.get(col["id"]) or []):
                out.append({**f, "source": "עמודה: " + (col.get("title") or ""), "user_name": None, "created_at": task.updated_at})
        return {"files": out}

@app.get("/api/tasks/{task_id}/activity")
def task_activity(task_id: int, user_id: Optional[int] = None, date: Optional[str] = None):
    with Session(engine) as db:
        q = db.query(AuditLog).filter(AuditLog.entity_type == "task", AuditLog.entity_id == task_id)
        if user_id:
            q = q.filter(AuditLog.changed_by == user_id)
        out = []
        for l in q.order_by(AuditLog.created_at.desc()).all():
            if date and (not l.created_at or str(l.created_at)[:10] != date):
                continue
            u = db.query(User).filter(User.id == l.changed_by).first()
            out.append({"id": l.id, "action": l.action, "field": l.field_name,
                        "old": l.old_value, "new": l.new_value,
                        "user_id": l.changed_by, "user_name": u.name if u else "מערכת",
                        "can_undo": l.action == "update", "created_at": l.created_at})
        return {"activity": out}

@app.get("/api/tasks/{task_id}/activity/export")
def export_activity(task_id: int):
    with Session(engine) as db:
        logs = db.query(AuditLog).filter(AuditLog.entity_type == "task", AuditLog.entity_id == task_id)\
                 .order_by(AuditLog.created_at.desc()).all()
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

def _revert_field(task, field, old):
    if field == "title":
        task.title = old or ""; return True
    if field == "status":
        try: task.status = TaskStatus(old); return True
        except ValueError: return False
    if field == "priority":
        try: task.priority = Priority(old); return True
        except ValueError: return False
    if field == "due_date":
        task.due_date = datetime.fromisoformat(old) if old else None; return True
    if field == "tags":
        task.tags = [x for x in (old or "").split(", ") if x]; return True
    if field and field.startswith("col:"):
        cid = field[4:]; cf = dict(task.custom_fields or {})
        val = json.loads(old) if old not in (None, "", "null") else None
        if val is None: cf.pop(cid, None)
        else: cf[cid] = val
        task.custom_fields = cf; return True
    return False

@app.post("/api/activity/{log_id}/undo")
def undo_activity(log_id: int, data: dict):
    with Session(engine) as db:
        user = _acting_user(db, data)
        if not user or user.role not in ("admin", "manager"):
            raise HTTPException(403, "רק מנהל יכול לבצע ביטול")
        log = db.query(AuditLog).filter(AuditLog.id == log_id).first()
        if not log or log.entity_type != "task" or log.action != "update":
            raise HTTPException(400, "לא ניתן לבטל פעולה זו")
        task = db.query(Task).filter(Task.id == log.entity_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        if not _revert_field(task, log.field_name, log.old_value):
            raise HTTPException(400, "שדה לא נתמך לביטול")
        _audit(db, task.id, "undo", field=log.field_name, old=log.new_value, new=log.old_value, user_id=user.id)
        db.commit()
        return {"status": "reverted", "field": log.field_name}

@app.post("/api/tasks/{task_id}/assignees")
def task_assignees(task_id: int, data: dict):
    """Add or remove a user from a task (monday-style people column)."""
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, "task not found")
        user = db.query(User).filter(User.id == data.get("user_id")).first()
        if not user:
            raise HTTPException(404, "user not found")
        actor = data.get("actor_id")
        was = user in task.assignees
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
        db.commit()
        return {"assignees": [{"id": u.id, "name": u.name, "avatar_url": u.avatar_url}
                              for u in task.assignees]}

@app.post("/api/tasks/{task_id}/move")
def move_task(task_id: int, data: dict):
    with Session(engine) as db:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404)
        if "group_id" in data:
            task.group_id = data["group_id"]
        if "position" in data:
            task.position = data["position"]
        if "status" in data:
            task.status = data["status"]
        db.commit()
        return {"status": "moved"}

# ── Groups (board columns / קבוצות) ─────────────────────────────────

def _group_dict(g):
    return {"id": g.id, "name": g.name, "position": g.position, "color": g.color,
            "task_status": g.task_status.value if hasattr(g.task_status, 'value') else g.task_status}

@app.post("/api/groups")
def create_group_api(data: dict):
    with Session(engine) as db:
        board_id = data.get("board_id")
        board = db.query(Board).filter(Board.id == board_id).first()
        if not board:
            raise HTTPException(404, "board not found")
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
        db.refresh(g)
        return _group_dict(g)

@app.patch("/api/groups/{group_id}")
def update_group_api(group_id: int, data: dict):
    with Session(engine) as db:
        g = db.query(Group).filter(Group.id == group_id).first()
        if not g:
            raise HTTPException(404, "group not found")
        if data.get("name") is not None:
            g.name = data["name"]
        if data.get("color") is not None:
            g.color = data["color"]
        if data.get("position") is not None:
            g.position = data["position"]
        db.commit()
        db.refresh(g)
        return _group_dict(g)

@app.post("/api/groups/reorder")
def reorder_groups_api(data: dict):
    """Persist a new group ordering. data = {order: [groupId, ...]}"""
    with Session(engine) as db:
        order = data.get("order") or []
        for idx, gid in enumerate(order):
            g = db.query(Group).filter(Group.id == gid).first()
            if g:
                g.position = idx
        db.commit()
        return {"status": "reordered", "order": order}

@app.delete("/api/groups/{group_id}")
def delete_group_api(group_id: int):
    with Session(engine) as db:
        g = db.query(Group).filter(Group.id == group_id).first()
        if not g:
            raise HTTPException(404, "group not found")
        # Detach tasks instead of deleting them — they fall back to "ללא קבוצה"
        for t in db.query(Task).filter(Task.group_id == group_id).all():
            t.group_id = None
        db.delete(g)
        db.commit()
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
        def _iso(dt):
            return dt.isoformat() if dt else None
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
async def record_login(request: Request):
    """Record a successful login for the admin login-history view."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    uid = data.get("user_id")
    with Session(engine) as db:
        u = db.query(User).filter(User.id == uid).first()
        if not u:
            raise HTTPException(404, "user not found")
        ev = LoginEvent(
            user_id=uid,
            ip=(request.client.host if request.client else None),
            user_agent=(request.headers.get("user-agent") or "")[:400],
        )
        db.add(ev)
        db.commit()
        return {"status": "ok", "logged_in_at": ev.logged_in_at.isoformat()}

@app.get("/api/users/{uid}/login-history")
def login_history(uid: int, actor_id: Optional[int] = None, limit: int = 50):
    """Login history for a user — visible to system (workspace) admins only."""
    with Session(engine) as db:
        if _ws_role(db, actor_id) != "admin":
            raise HTTPException(403, "רק מנהל מערכת יכול לראות היסטוריית התחברות")
        if not db.query(User.id).filter(User.id == uid).scalar():
            raise HTTPException(404, "user not found")
        evs = (db.query(LoginEvent).filter(LoginEvent.user_id == uid)
               .order_by(LoginEvent.logged_in_at.desc()).limit(max(1, min(limit, 200))).all())
        return [{
            "logged_in_at": e.logged_in_at.isoformat() if e.logged_in_at else None,
            "ip": e.ip, "user_agent": e.user_agent,
        } for e in evs]

@app.get("/api/login-history")
def all_login_history(actor_id: Optional[int] = None, limit: int = 100):
    """Consolidated login history across all users — system admins only."""
    with Session(engine) as db:
        if _ws_role(db, actor_id) != "admin":
            raise HTTPException(403, "רק מנהל מערכת יכול לראות היסטוריית התחברות")
        names = {u.id: (u.name, u.avatar_url) for u in db.query(User).all()}
        evs = (db.query(LoginEvent).order_by(LoginEvent.logged_in_at.desc())
               .limit(max(1, min(limit, 500))).all())
        return [{
            "user_id": e.user_id,
            "user_name": names.get(e.user_id, ("—", None))[0],
            "avatar_url": names.get(e.user_id, ("—", None))[1],
            "logged_in_at": e.logged_in_at.isoformat() if e.logged_in_at else None,
            "ip": e.ip, "user_agent": e.user_agent,
        } for e in evs]

@app.post("/api/users")
def create_user(data: dict):
    """Create a new user in the workspace directory. System (workspace) admin only."""
    with Session(engine) as db:
        actor = data.get("actor_id")
        if _ws_role(db, actor) != "admin":
            raise HTTPException(403, "רק מנהל מערכת יכול להוסיף משתמש")
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        if not name:
            raise HTTPException(400, "חסר שם משתמש")
        if not email:
            raise HTTPException(400, "חסרה כתובת מייל")
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(409, "כתובת המייל כבר קיימת במערכת")
        role = data.get("role") if data.get("role") in ("admin", "manager", "member", "viewer") else "member"
        dept_id = data.get("department_id") or None
        # inherit the organization of an existing user so the new user is in the same workspace
        org_id = db.query(User.organization_id).filter(User.organization_id != None).limit(1).scalar()
        u = User(name=name, email=email, role=role, department_id=dept_id,
                 organization_id=org_id, is_active=True)
        db.add(u)
        db.flush()
        # also register workspace membership so the role actually takes effect
        # (system-admin capabilities key off workspace_members, not User.role)
        ws_role = "admin" if role == "admin" else ("viewer" if role == "viewer" else "member")
        db.add(WorkspaceMember(user_id=u.id, role=ws_role))
        db.commit()
        db.refresh(u)
        dept_name = db.query(Department.name).filter(Department.id == u.department_id).scalar() if u.department_id else None
        return {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
                "department_id": u.department_id, "department_name": dept_name,
                "is_active": True, "avatar_url": u.avatar_url}

@app.patch("/api/users/{uid}")
def update_user(uid: int, data: dict):
    """Update a user's profile. A user may edit their own profile; a system
    (workspace) admin may edit anyone's."""
    with Session(engine) as db:
        actor = data.get("actor_id")
        if actor != uid and _ws_role(db, actor) != "admin":
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
            if _ws_role(db, actor) != "admin":
                raise HTTPException(403, "רק מנהל מערכת יכול לשנות תפקיד, מחלקה או סטטוס")
            if "role" in data and data["role"] in ("admin", "manager", "member", "viewer"):
                u.role = data["role"]
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

@app.get("/api/departments")
def list_departments():
    with Session(engine) as db:
        depts = db.query(Department).all()
        return [{
            "id": d.id, "name": d.name, "code": d.code, "color": d.color,
            "organization_id": d.organization_id,
        } for d in depts]

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
def swarm_think(data: dict):
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
            tags=["form", template_id],
            custom_fields=form_data,
        )
        db.add(task)
        db.commit()
        return {"id": task.id, "status": "submitted"}

# ── Visualization Engine ─────────────────────────────────────────────

@app.get("/api/viz/board-insights")
def board_insights(user_id: Optional[int] = None):
    """Generate visualization data and insights for boards the user may see."""
    with Session(engine) as db:
        visible = _visible_board_ids(db, user_id)
        boards = db.query(Board).filter(
            Board.is_archived == False, Board.id.in_(visible)
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
        boards = db.query(Board).filter(Board.is_archived == False).all()
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
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "תגיות (אופציונלי)"},
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
                    "tags": {"type": "array", "items": {"type": "string"}},
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


def execute_ai_tool(name: str, args: dict, actor: Optional[int] = None) -> str:
    """Execute an AI tool by name with the given arguments. Returns a descriptive Hebrew result string."""
    from datetime import datetime, timezone

    if name == "list_boards":
        with Session(engine) as db:
            boards = db.query(Board).filter(Board.is_archived == False).all()
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
        tags = args.get("tags", [])
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
                tags=tags,
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
            if "tags" in args:
                t.tags = args["tags"]
                changed.append("tags")
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
            t.is_archived = True
            db.add(AuditLog(
                entity_type="task", entity_id=task_id,
                action="archive", field_name="is_archived",
                new_value="True",
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
def ai_query(data: dict):
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
                        result_text = execute_ai_tool(fn_name, fn_args, data.get("user_id"))
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
async def llm_proxy(request: Request):
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
def ai_train(data: dict):
    """Prepare a LOCAL fine-tuning dataset (JSONL) from board data.
    Data stays on-device and is used only to train the user's own local models."""
    import json as _json
    if not data.get("confirm"):
        raise HTTPException(400, "training requires explicit confirmation")
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
                                       "priority": p, "tags": t.tags or []}, ensure_ascii=False),
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
                "tags": t.tags or [],
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
                "tags": t.tags or [],
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
def ceo_dashboard(user_id: Optional[int] = None):
    """Comprehensive CEO dashboard — city-wide view across boards the user may see."""
    with Session(engine) as db:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # ── Board & Task Breakdown (membership-scoped, no leaks) ──
        visible = _visible_board_ids(db, user_id)
        boards = db.query(Board).filter(
            Board.is_archived == False, Board.id.in_(visible)
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
def create_work_plan(data: dict):
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
            changed_by=data.get("user_id")))
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
def create_project(data: dict):
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
            changed_by=data.get("user_id")))
        db.commit()
        return {"id": p.id, "status": "created", "name": p.name}

@app.patch("/api/projects/{project_id}")
def update_project(project_id: int, data: dict):
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
                        changed_by=data.get("user_id")))
        if "status" in data:
            try:
                p.status = ProjectStatus(data["status"])
            except ValueError:
                pass
            db.add(AuditLog(entity_type="project", entity_id=p.id,
                action="update", field_name="status",
                new_value=data["status"],
                changed_by=data.get("user_id")))
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
            "tags": t.tags or [],
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
def approve_step(approval_id: int, data: dict):
    with Session(engine) as db:
        a = db.query(Approval).filter(Approval.id == approval_id).first()
        if not a:
            raise HTTPException(404)
        try:
            a.status = ApprovalStatus(data.get("status", "approved"))
        except ValueError:
            a.status = ApprovalStatus.APPROVED
        a.approver_user_id = data.get("user_id")
        a.notes = data.get("notes", "")
        a.approved_at = datetime.now(timezone.utc)
        db.add(AuditLog(
            entity_type=f"approval.{a.entity_type}", entity_id=a.entity_id,
            action=data.get("status", "approved"),
            field_name=f"approval.{a.approver_role}",
            new_value=data.get("status", "approved"),
            changed_by=data.get("user_id"),
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
def update_change_request(cr_id: int, data: dict):
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
                cr.approved_by = data.get("user_id")
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
def ai_project_insights(project_id: int):
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
