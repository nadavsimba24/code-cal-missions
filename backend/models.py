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
    name = Column(String(200), nullable=False)
    code = Column(String(50))
    color = Column(String(7), default="#3b82f6")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    organization = relationship("Organization")
    boards = relationship("Board", back_populates="department")
    users = relationship("User", back_populates="department")

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

# ── Init DB ──────────────────────────────────────────────────────────

def init_db(db_url="sqlite:///cityos.db"):
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    return engine
