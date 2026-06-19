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
    TaskStatus, Priority, BoardType, init_db
)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
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
from seed import seed_database
seed_database(engine)

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

@app.post("/api/ai/query")
def ai_query(data: dict):
    """CODE-CAL MISSIONS agent — DeepSeek (cloud) by default, or a local Ollama model."""
    import subprocess
    prompt = data.get("prompt", "")
    context = data.get("context", "")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    model = data.get("model") or ("deepseek-chat" if deepseek_key else "gemma4-coder")
    system = "You are the CODE-CAL MISSIONS agent, a municipal workflow assistant for an Israeli city. Answer concisely and helpfully in Hebrew."

    if model.startswith("deepseek"):
        if not deepseek_key:
            return {"response": "מפתח DeepSeek לא מוגדר.", "success": False, "model": model}
        try:
            import httpx
            r = httpx.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {deepseek_key}"},
                json={"model": model, "temperature": 0.7, "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"הקשר: {context}\n\nשאלה: {prompt}"},
                ]},
                timeout=60,
            )
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"].strip()
            return {"response": txt or "לא התקבלה תשובה", "success": True, "model": model, "provider": "deepseek"}
        except Exception as e:
            return {"response": f"DeepSeek לא זמין: {str(e)[:200]}", "success": False, "model": model}

    full_prompt = f"{system}\n\nContext: {context}\n\nQuestion: {prompt}\n\nAnswer:"
    try:
        result = subprocess.run(
            ["ollama", "run", model, full_prompt],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "OLLAMA_NUM_THREADS": "8"},
        )
        return {"response": result.stdout.strip() or "לא התקבלה תשובה", "success": True, "model": model, "provider": "ollama"}
    except Exception as e:
        return {"response": f"AI מקומי לא זמין: {str(e)}", "success": False, "model": model}

@app.get("/api/ai/models")
def ai_models():
    """List available LLMs: DeepSeek (cloud) + local Ollama models."""
    import subprocess
    models = []
    default = "gemma4-coder"
    if os.environ.get("DEEPSEEK_API_KEY"):
        models += [{"name": "deepseek-chat", "size": "ענן · DeepSeek"},
                   {"name": "deepseek-reasoner", "size": "ענן · DeepSeek"}]
        default = "deepseek-chat"
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
