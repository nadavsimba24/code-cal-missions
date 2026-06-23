"""
CityOS — Municipal Work Management Platform
Database Models
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, JSON, Enum as SAEnum, Table
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone
import enum

Base = declarative_base()

# ── Enums ─────────────────────────────────────────────────────────────

class BoardType(str, enum.Enum):
    KANBAN = "kanban"
    LIST = "list"
    CALENDAR = "calendar"
    TIMELINE = "timeline"
    MAP = "map"
    FORM = "form"

class TaskStatus(str, enum.Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"

class Priority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    EMERGENCY = "emergency"  # municipal-specific

class PermitType(str, enum.Enum):
    BUILDING = "building_permit"
    BUSINESS = "business_license"
    EVENT = "event_permit"
    SIGN = "sign_permit"
    RENOVATION = "renovation_permit"
    DEMOLITION = "demolition_permit"
    OTHER = "other"

class CitizenRequestType(str, enum.Enum):
    ROAD_ISSUE = "road_issue"
    STREET_LIGHT = "street_light"
    WASTE = "waste"
    WATER = "water"
    SEWAGE = "sewage"
    PARK = "park"
    NOISE = "noise"
    PUBLIC_TRANSPORT = "public_transport"
    GENERAL = "general"

# ── Work Plan & Budget Enums ─────────────────────────────────────────

class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"

class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class ChangeRequestStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"

class DependencyType(str, enum.Enum):
    FINISH_TO_START = "finish_to_start"
    START_TO_START = "start_to_start"
    FINISH_TO_FINISH = "finish_to_finish"
    START_TO_FINISH = "start_to_finish"

class BudgetItemType(str, enum.Enum):
    PLANNING = "planning"  # תכנון
    SUPERVISION = "supervision"  # פיקוח
    CONTRACTOR = "contractor"  # קבלן
    EQUIPMENT = "equipment"  # ציוד
    PROCUREMENT = "procurement"  # רכש
    OTHER = "other"

class DocumentType(str, enum.Enum):
    TENDER = "tender"  # מכרז
    AGREEMENT = "agreement"  # הסכם
    PLANS = "plans"  # תכניות
    PROTOCOL = "protocol"  # פרוטוקולים
    INVOICE = "invoice"  # חשבונות
    OTHER = "other"

# ── Association Tables ───────────────────────────────────────────────

task_assignees = Table(
    'task_assignees', Base.metadata,
    Column('task_id', Integer, ForeignKey('tasks.id')),
    Column('user_id', Integer, ForeignKey('users.id'))
)

task_watchers = Table(
    'task_watchers', Base.metadata,
    Column('task_id', Integer, ForeignKey('tasks.id')),
    Column('user_id', Integer, ForeignKey('users.id'))
)

# ── Models ────────────────────────────────────────────────────────────

class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    logo_url = Column(String(500))
    municipality_code = Column(String(20))  # Israeli municipality code
    address = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    users = relationship("User", back_populates="organization")
    boards = relationship("Board", back_populates="organization")

class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    work_plan_id = Column(Integer, ForeignKey("annual_work_plans.id"), nullable=True)
    name = Column(String(200), nullable=False)
    code = Column(String(50))
    color = Column(String(7), default="#3b82f6")
    annual_budget = Column(Float, default=0)
    planned_projects = Column(Integer, default=0)
    completed_projects = Column(Integer, default=0)
    manager_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    organization = relationship("Organization")
    work_plan = relationship("AnnualWorkPlan", back_populates="departments")
    boards = relationship("Board", back_populates="department")
    users = relationship("User", back_populates="department")
    projects = relationship("Project", back_populates="department")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    email = Column(String(200), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    role = Column(String(50), default="member")  # admin, manager, member, viewer
    avatar_url = Column(String(500))
    phone = Column(String(20))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    organization = relationship("Organization", back_populates="users")
    department = relationship("Department", back_populates="users")

class Board(Base):
    __tablename__ = "boards"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    name = Column(String(200), nullable=False)
    description = Column(Text)
    board_type = Column(SAEnum(BoardType), default=BoardType.KANBAN)
    icon = Column(String(50), default="📋")
    color = Column(String(7), default="#6366f1")
    is_archived = Column(Boolean, default=False)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    organization = relationship("Organization", back_populates="boards")
    department = relationship("Department", back_populates="boards")
    groups = relationship("Group", back_populates="board", order_by="Group.position")
    tasks = relationship("Task", back_populates="board")

class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"))
    name = Column(String(200), nullable=False)
    position = Column(Integer, default=0)
    color = Column(String(7))
    task_status = Column(SAEnum(TaskStatus), default=TaskStatus.TODO)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    board = relationship("Board", back_populates="groups")
    tasks = relationship("Task", back_populates="group", order_by="Task.position")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    parent_id = Column(Integer, ForeignKey("tasks.id"))
    step_id = Column(Integer, ForeignKey("project_steps.id"), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    status = Column(SAEnum(TaskStatus), default=TaskStatus.TODO)
    priority = Column(SAEnum(Priority), default=Priority.MEDIUM)
    position = Column(Integer, default=0)
    due_date = Column(DateTime)
    start_date = Column(DateTime)
    estimated_hours = Column(Float)
    actual_hours = Column(Float)
    location_lat = Column(Float)  # GIS integration
    location_lng = Column(Float)
    address = Column(String(500))
    gis_layer_id = Column(String(100))  # Reference to GeoLibre layer
    custom_fields = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    is_archived = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    board = relationship("Board", back_populates="tasks")
    group = relationship("Group", back_populates="tasks")
    step = relationship("ProjectStep", back_populates="tasks")
    assignees = relationship("User", secondary=task_assignees)
    watchers = relationship("User", secondary=task_watchers)
    subtasks = relationship("Task", backref="parent", remote_side=[id])
    comments = relationship("Comment", back_populates="task")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    attachments = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    task = relationship("Task", back_populates="comments")

# ── Municipal-Specific Models ────────────────────────────────────────

class Permit(Base):
    __tablename__ = "permits"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    permit_type = Column(SAEnum(PermitType), nullable=False)
    permit_number = Column(String(100), unique=True)
    applicant_name = Column(String(200))
    applicant_phone = Column(String(20))
    applicant_email = Column(String(200))
    property_address = Column(String(500))
    property_gush = Column(String(20))  # Israeli land registry
    property_helka = Column(String(20))
    description = Column(Text)
    status = Column(String(50), default="draft")  # draft, submitted, review, approved, rejected
    assigned_to = Column(Integer, ForeignKey("users.id"))
    task_id = Column(Integer, ForeignKey("tasks.id"))
    submitted_at = Column(DateTime)
    decided_at = Column(DateTime)
    decision_notes = Column(Text)
    attachments = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class CitizenRequest(Base):
    __tablename__ = "citizen_requests"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    request_type = Column(SAEnum(CitizenRequestType), nullable=False)
    citizen_name = Column(String(200))
    citizen_phone = Column(String(20))
    citizen_email = Column(String(200))
    title = Column(String(500))
    description = Column(Text)
    location_lat = Column(Float)
    location_lng = Column(Float)
    address = Column(String(500))
    photo_urls = Column(JSON, default=list)
    status = Column(String(50), default="new")  # new, assigned, in_progress, resolved, closed
    priority = Column(SAEnum(Priority), default=Priority.MEDIUM)
    assigned_to = Column(Integer, ForeignKey("users.id"))
    task_id = Column(Integer, ForeignKey("tasks.id"))
    resolution_notes = Column(Text)
    citizen_rating = Column(Integer)  # 1-5
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime)

class PublicTransportStop(Base):
    __tablename__ = "public_transport_stops"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    stop_code = Column(String(20))
    name = Column(String(200))
    latitude = Column(Float)
    longitude = Column(Float)
    routes = Column(JSON, default=list)
    last_siri_update = Column(DateTime)
    siri_data = Column(JSON)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class InfrastructureAsset(Base):
    __tablename__ = "infrastructure_assets"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    asset_type = Column(String(100))  # road, street_light, water_pipe, park, etc.
    name = Column(String(200))
    location_lat = Column(Float)
    location_lng = Column(Float)
    geometry = Column(JSON)  # GeoJSON geometry
    condition = Column(String(50))  # excellent, good, fair, poor, critical
    install_date = Column(DateTime)
    last_inspection = Column(DateTime)
    status = Column(String(50), default="active")
    properties = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# ── Work Plan & Budget Models ────────────────────────────────────────

class AnnualWorkPlan(Base):
    """Level 1 — Annual work plan for a municipality."""
    __tablename__ = "annual_work_plans"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    year = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)
    total_budget = Column(Float, default=0)
    strategic_goals = Column(JSON, default=list)
    municipal_kpis = Column(JSON, default=list)
    overall_status = Column(String(50), default="draft")  # draft, active, completed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    organization = relationship("Organization")
    departments = relationship("Department", back_populates="work_plan")
    projects = relationship("Project", back_populates="work_plan")
    kpis = relationship("KPI", back_populates="work_plan")


class Project(Base):
    """Level 3 — A project within an annual work plan (not a Task)."""
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    work_plan_id = Column(Integer, ForeignKey("annual_work_plans.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    name = Column(String(500), nullable=False)
    description = Column(Text)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    planned_budget = Column(Float, default=0)
    approved_budget = Column(Float, default=0)
    actual_budget = Column(Float, default=0)
    progress_percentage = Column(Float, default=0)  # 0-100
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    status = Column(SAEnum(ProjectStatus), default=ProjectStatus.DRAFT)
    priority = Column(SAEnum(Priority), default=Priority.MEDIUM)
    tags = Column(JSON, default=list)
    color = Column(String(7), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    work_plan = relationship("AnnualWorkPlan", back_populates="projects")
    department = relationship("Department", back_populates="projects")
    manager = relationship("User", foreign_keys=[manager_id])
    steps = relationship("ProjectStep", back_populates="project", order_by="ProjectStep.position")
    budget_items = relationship("BudgetLineItem", back_populates="project")
    kpis = relationship("KPI", back_populates="project")
    change_requests = relationship("ChangeRequest", back_populates="project")
    dependencies_as_source = relationship(
        "Dependency",
        foreign_keys="Dependency.source_id",
        primaryjoin="and_(Dependency.source_type=='project', Dependency.source_id==Project.id)",
        viewonly=True
    )
    dependencies_as_target = relationship(
        "Dependency",
        foreign_keys="Dependency.target_id",
        primaryjoin="and_(Dependency.target_type=='project', Dependency.target_id==Project.id)",
        viewonly=True
    )
    documents = relationship("Document", back_populates="project")


class ProjectStep(Base):
    """Level 4 — A step/milestone within a project."""
    __tablename__ = "project_steps"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    progress = Column(Float, default=0)  # 0-100
    position = Column(Integer, default=0)
    status = Column(String(50), default="pending")  # pending, in_progress, completed, delayed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    project = relationship("Project", back_populates="steps")
    owner = relationship("User", foreign_keys=[owner_id])
    tasks = relationship("Task", back_populates="step")


class BudgetLineItem(Base):
    """Budget breakdown for a project."""
    __tablename__ = "budget_line_items"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    item_type = Column(SAEnum(BudgetItemType), nullable=False)
    name = Column(String(200), nullable=True)
    planned_amount = Column(Float, default=0)
    approved_amount = Column(Float, default=0)
    actual_amount = Column(Float, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    project = relationship("Project", back_populates="budget_items")


class Approval(Base):
    """Approval workflow record."""
    __tablename__ = "approvals"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String(50), nullable=False)  # "project", "change_request", "work_plan"
    entity_id = Column(Integer, nullable=False)
    approver_role = Column(String(100), nullable=False)  # "מנהל מחלקה", "מנהל אגף", "גזבר", "מנכ"ל", "ראש רשות"
    approver_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(SAEnum(ApprovalStatus), default=ApprovalStatus.PENDING)
    notes = Column(Text, nullable=True)
    step_order = Column(Integer, default=0)  # order in the approval chain
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime, nullable=True)
    approver = relationship("User", foreign_keys=[approver_user_id])


class ChangeRequest(Base):
    """A request to change a project's scope, budget, or timeline."""
    __tablename__ = "change_requests"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    title = Column(String(300), nullable=False)
    description = Column(Text)
    amount_change = Column(Float)  # positive=increase, negative=decrease
    reason = Column(Text)
    status = Column(SAEnum(ChangeRequestStatus), default=ChangeRequestStatus.SUBMITTED)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime, nullable=True)
    project = relationship("Project", back_populates="change_requests")
    requester = relationship("User", foreign_keys=[requested_by])
    approver = relationship("User", foreign_keys=[approved_by])


class KPI(Base):
    """Key Performance Indicator — per project or per work plan."""
    __tablename__ = "kpis"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    work_plan_id = Column(Integer, ForeignKey("annual_work_plans.id"), nullable=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    target = Column(Float, nullable=False)
    actual = Column(Float, default=0)
    unit = Column(String(50), nullable=False)  # "קמ", "%", "יחידות", "₪", "ימים"
    measurement_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    project = relationship("Project", back_populates="kpis")
    work_plan = relationship("AnnualWorkPlan", back_populates="kpis")


class Dependency(Base):
    """Dependency between projects or steps (generic FK pattern)."""
    __tablename__ = "dependencies"
    id = Column(Integer, primary_key=True)
    source_type = Column(String(20), nullable=False)  # "project" or "step"
    source_id = Column(Integer, nullable=False)
    target_type = Column(String(20), nullable=False)  # "project" or "step"
    target_id = Column(Integer, nullable=False)
    dependency_type = Column(SAEnum(DependencyType), default=DependencyType.FINISH_TO_START)
    lag_days = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Generic foreign keys — relationships handled via the Project hybrid above


class Document(Base):
    """Project documents (tenders, agreements, plans, invoices, etc.)."""
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    document_type = Column(SAEnum(DocumentType), nullable=False)
    name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    file_url = Column(String(1000), nullable=True)
    file_size = Column(Integer, nullable=True)  # bytes
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    project = relationship("Project", back_populates="documents")
    uploader = relationship("User", foreign_keys=[uploaded_by])


class AuditLog(Base):
    """Audit trail for changes across work plan entities."""
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    field_name = Column(String(200))
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(50), nullable=False)  # "create", "update", "delete", "approve", "reject"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    changer = relationship("User", foreign_keys=[changed_by])


# ── Init DB ──────────────────────────────────────────────────────────

def init_db(db_url="sqlite:///cityos.db"):
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    return engine
