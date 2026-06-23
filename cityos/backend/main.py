"""
CityOS — FastAPI Backend Server
"""
import os, sys, json
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(__file__))
from models import (
    Organization, Department, User, Board, Group, Task, Comment,
    Permit, CitizenRequest, PublicTransportStop, InfrastructureAsset,
    TaskStatus, Priority, BoardType, init_db,
    AnnualWorkPlan, Project, ProjectStep, BudgetLineItem,
    Approval, ChangeRequest, KPI, Dependency, Document, AuditLog,
    ProjectStatus, ApprovalStatus, ChangeRequestStatus,
    DependencyType, BudgetItemType, DocumentType
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

DB_PATH = os.path.join(os.path.dirname(__file__), "cityos.db")
engine = init_db(f"sqlite:///{DB_PATH}")

# Seed on first run
from seed import seed_database, seed_work_plan
seed_database(engine)
seed_work_plan(engine)

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
def dashboard():
    with Session(engine) as db:
        tasks = db.query(Task).filter(Task.is_archived == False).all()
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

@app.get("/api/boards")
def list_boards():
    with Session(engine) as db:
        boards = db.query(Board).filter(Board.is_archived == False).all()
        result = []
        for b in boards:
            task_count = db.query(Task).filter(Task.board_id == b.id).count()
            dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
            groups = db.query(Group).filter(Group.board_id == b.id).order_by(Group.position).all()
            result.append({
                "id": b.id, "name": b.name, "description": b.description,
                "board_type": b.board_type.value if hasattr(b.board_type, 'value') else b.board_type,
                "icon": b.icon, "color": b.color,
                "is_archived": b.is_archived,
                "department_name": dept_name,
                "task_count": task_count,
                "groups": [{"id": g.id, "name": g.name, "position": g.position, "color": g.color, "task_status": g.task_status.value if hasattr(g.task_status, 'value') else g.task_status} for g in groups],
            })
        return result

@app.get("/api/boards/{board_id}")
def get_board(board_id: int):
    with Session(engine) as db:
        b = db.query(Board).filter(Board.id == board_id).first()
        if not b:
            raise HTTPException(404, "Board not found")
        groups = db.query(Group).filter(Group.board_id == b.id).order_by(Group.position).all()
        tasks = db.query(Task).filter(Task.board_id == b.id, Task.is_archived == False).order_by(Task.position).all()
        dept_name = db.query(Department.name).filter(Department.id == b.department_id).scalar() or ""
        
        tasks_out = []
        for t in tasks:
            assignees = [{"id": u.id, "name": u.name, "avatar_url": u.avatar_url} for u in t.assignees] if t.assignees else []
            subtask_count = db.query(Task).filter(Task.parent_id == t.id).count()
            comment_count = db.query(Comment).filter(Comment.task_id == t.id).count()
            tasks_out.append({
                "id": t.id, "board_id": t.board_id, "group_id": t.group_id,
                "title": t.title, "description": t.description,
                "status": t.status.value if hasattr(t.status, 'value') else t.status,
                "priority": t.priority.value if hasattr(t.priority, 'value') else t.priority,
                "position": t.position, "due_date": t.due_date,
                "start_date": t.start_date,
                "estimated_hours": t.estimated_hours, "actual_hours": t.actual_hours,
                "location_lat": t.location_lat, "location_lng": t.location_lng,
                "address": t.address, "tags": t.tags or [],
                "custom_fields": t.custom_fields or {},
                "is_archived": t.is_archived,
                "created_by": t.created_by,
                "created_at": t.created_at, "updated_at": t.updated_at,
                "assignees": assignees,
                "subtask_count": subtask_count,
                "comment_count": comment_count,
            })

        return {
            "id": b.id, "name": b.name, "description": b.description,
            "board_type": b.board_type.value if hasattr(b.board_type, 'value') else b.board_type,
            "icon": b.icon, "color": b.color,
            "is_archived": b.is_archived,
            "department_name": dept_name,
            "groups": [{"id": g.id, "name": g.name, "position": g.position, "color": g.color, "task_status": g.task_status.value if hasattr(g.task_status, 'value') else g.task_status} for g in groups],
            "tasks": tasks_out,
        }

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
        task = Task(
            board_id=data.get("board_id"),
            group_id=data.get("group_id"),
            title=data.get("title", "Untitled"),
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            tags=data.get("tags", []),
            location_lat=data.get("location_lat"),
            location_lng=data.get("location_lng"),
            address=data.get("address"),
        )
        ids = data.get("assignee_ids") or []
        if ids:
            task.assignees = db.query(User).filter(User.id.in_(ids)).all()
        db.add(task)
        db.commit()
        return {"id": task.id, "status": "created"}

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
        if data.get("action") == "remove":
            if user in task.assignees:
                task.assignees.remove(user)
        else:
            if user not in task.assignees:
                task.assignees.append(user)
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
        return [{
            "id": u.id, "name": u.name, "email": u.email,
            "role": u.role, "avatar_url": u.avatar_url,
            "department_id": u.department_id,
        } for u in users]

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
def board_insights():
    """Generate visualization data and insights for all boards."""
    with Session(engine) as db:
        boards = db.query(Board).filter(Board.is_archived == False).all()
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
            "description": "יצירת משימה חדשה בלוח",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_id": {"type": "integer", "description": "מזהה הלוח"},
                    "group_id": {"type": "integer", "description": "מזהה הקבוצה/עמודה"},
                    "title": {"type": "string", "description": "כותרת המשימה"},
                    "description": {"type": "string", "description": "תיאור המשימה"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical", "emergency"], "description": "עדיפות"},
                    "status": {"type": "string", "enum": ["backlog", "todo", "in_progress", "review", "done", "cancelled", "on_hold"], "description": "סטטוס"},
                    "due_date": {"type": "string", "description": "תאריך יעד בפורמט ISO"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "תגיות"},
                },
                "required": ["board_id", "group_id", "title"]
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


def execute_ai_tool(name: str, args: dict) -> str:
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
            b = Board(
                name=name,
                description=description,
                department_id=dept_id,
                board_type=BoardType.KANBAN,
                icon=icon,
                color=color,
            )
            db.add(b)
            db.flush()

            # Create default groups
            g1 = Group(board_id=b.id, name="לתכנון", position=0, color="#579bfc", task_status=TaskStatus.BACKLOG)
            g2 = Group(board_id=b.id, name="בתהליך", position=1, color="#fdab3d", task_status=TaskStatus.IN_PROGRESS)
            g3 = Group(board_id=b.id, name="הושלם", position=2, color="#00c875", task_status=TaskStatus.DONE)
            db.add_all([g1, g2, g3])
            db.commit()
            db.refresh(b)
            return f"✅ לוח '{name}' נוצר בהצלחה (מזהה: {b.id}) עם 3 עמודות ברירת מחדל."

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
        priority_str = args.get("priority", "medium")
        status_str = args.get("status", "todo")
        due_date_str = args.get("due_date")
        tags = args.get("tags", [])
        try:
            priority = Priority(priority_str)
        except ValueError:
            priority = Priority.MEDIUM
        try:
            status = TaskStatus(status_str)
        except ValueError:
            status = TaskStatus.TODO
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
            if group_id:
                g = db.query(Group).filter(Group.id == group_id).first()
                if not g:
                    return f"❌ עמודה {group_id} לא נמצאה."
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
5. צור משימות עם תאריכי יעד רלוונטיים
6. דבר בעברית תמיד
7. השתמש באימוג'ים במידה
8. אם אתה לא יודע איזה department_id או board_id - השתמש ברשימה קודם"""

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
                        result_text = execute_ai_tool(fn_name, fn_args)
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
    except Exception as e:
        return {"response": f"AI מקומי לא זמין: {str(e)}", "success": False, "model": model, "tool_calls": []}


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
def ceo_dashboard():
    """Comprehensive CEO dashboard — city-wide view across all boards."""
    with Session(engine) as db:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # ── Board & Task Breakdown ──
        boards = db.query(Board).filter(Board.is_archived == False).all()
        all_tasks = db.query(Task).filter(Task.is_archived == False).all()

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
def gantt_data(work_plan_id: int):
    with Session(engine) as db:
        wp = db.query(AnnualWorkPlan).filter(AnnualWorkPlan.id == work_plan_id).first()
        if not wp:
            raise HTTPException(404)
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
