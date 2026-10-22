"""
CityOS — Municipal Work Management Platform
Database Models
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, JSON, Enum as SAEnum, Table, LargeBinary,
    UniqueConstraint
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

class Environment(Base):
    """A top-level workspace/environment (Monday-style), e.g. 'עיריית הוד השרון'.
    Contains boards. Only a system (workspace) admin may create/edit/delete."""
    __tablename__ = "environments"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    name = Column(String(200), nullable=False)
    # What the switcher draws for this environment. Four shapes, and the
    # renderer tells them apart by prefix (see envIconHTML in the frontend):
    #   "fa:bolt"          a Font Awesome glyph on the colour below
    #   "/api/files/<tok>" an uploaded picture
    #   "🏛️"               an emoji, which is what every row held before
    #   empty              the creator's own avatar — the default for a new one
    icon = Column(String(50), default=None)
    color = Column(String(7), default="#6366f1")   # the tile behind an fa: glyph
    position = Column(Integer, default=0)
    is_primary = Column(Boolean, default=False)  # the default workspace that holds legacy/unassigned boards
    # Who made it. Kept so an environment with no icon of its own can wear its
    # creator's avatar, and so the thing is never again owned by nobody.
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Folder(Base):
    """A folder groups boards within an environment. Managed by the environment's
    manager (or a system admin). Deleting a folder detaches its boards, never deletes them."""
    __tablename__ = "folders"
    id = Column(Integer, primary_key=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False)
    name = Column(String(200), nullable=False)
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class EnvironmentMember(Base):
    """Which users are permitted to access an environment. System admins see
    every environment regardless; managers/members see only their own."""
    __tablename__ = "environment_members"
    id = Column(Integer, primary_key=True)
    environment_id = Column(Integer, ForeignKey("environments.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String(20), default="member")  # manager | member (env-scoped)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    email = Column(String(200), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    role = Column(String(50), default="member")  # admin, manager, member, viewer
    is_active = Column(Boolean, default=True)  # deactivated users stay in the directory
    avatar_url = Column(String(500))
    phone = Column(String(20))
    title = Column(String(120))  # job title within the organization
    email_notifications = Column(Boolean, default=True)
    notif_prefs = Column(JSON, default=dict)  # {mention, status, assign}
    # Entra ID object id, set only for external guests invited through the
    # guests screen (backend/entra_guests.py). Its presence is what marks an
    # account as "brought in from outside on purpose" — auth.is_invited_guest
    # reads it to let that person past the domain allowlist at sign-in.
    entra_object_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    organization = relationship("Organization", back_populates="users")
    department = relationship("Department", back_populates="users")

class Board(Base):
    __tablename__ = "boards"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)  # optional grouping within an environment
    position = Column(Integer, default=0)  # order within its container (folder or environment root)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    board_type = Column(SAEnum(BoardType), default=BoardType.KANBAN)
    icon = Column(String(50), default="📋")
    color = Column(String(7), default="#6366f1")
    is_archived = Column(Boolean, default=False)
    # Recycle bin: a deleted board is kept (with its groups, items and comments)
    # for RECYCLE_BIN_DAYS before being purged for good. NULL = live board.
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    organization = relationship("Organization", back_populates="boards")
    department = relationship("Department", back_populates="boards")
    groups = relationship("Group", back_populates="board", order_by="Group.position")
    tasks = relationship("Task", back_populates="board")

class SavedView(Base):
    """A saved cut of a board, shown as a tab at the top of it.

    "באגים דחופים פתוחים" is three filters somebody set once and then has to
    set again every morning. A view is that cut, named and kept — the
    advanced condition tree together with the toolbar's own filters and the
    base view it was looking at, so opening the tab restores the board the
    way it was left rather than approximately.

    `visibility` is the whole of the permission model and it has two values:

      private — only its owner sees it. Somebody's own way of reading a board
                is not a statement about the board, and it must not appear in
                anybody else's tab strip.
      public  — everyone who may open the board sees it. It is a tab on the
                board, so creating one is an edit to the board and needs the
                rights of one; a private view needs only the right to look.

    The cut is kept as JSON rather than as columns because what a cut IS keeps
    growing — the condition tree arrived after the toolbar filters did — and a
    view saved before a filter existed must keep working after it arrives.
    """
    __tablename__ = "saved_views"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    # Who made it, for the record and for nothing else: "היוצר משמש לתיעוד
    # ואינו מכתיב הרשאות ניהול". Nullable because the main table has no
    # author — it is the board, and it existed before anybody saved anything.
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String(80), nullable=False)
    # ── main | saved ──
    # The board's one fixed table is a row like any other now. It used to be
    # nothing at all — the board itself, with its layout in board.settings and
    # no record to point at — which meant it could not be named in a link,
    # could not carry a configuration version, and had to be special-cased in
    # every place that listed views. One guaranteed per board, including the
    # boards that existed before this existed: see _ensure_main_views.
    kind = Column(String(10), default="saved")
    visibility = Column(String(10), default="private")     # private | public
    # What the cut IS, and it keeps growing:
    #   {view, q, people, status, priority, sort, links, adv, cols}
    # `cols` is the table's own layout — {order, hidden, widths} — and it is
    # here rather than in the board's settings because that is the difference
    # between a view and a filter. A board's settings are one arrangement for
    # everybody; a view is "these columns, this width, this order, this cut",
    # and two views of one board are meant to disagree about all four.
    filters = Column(JSON, default=dict)
    position = Column(Integer, default=0)
    # ── נעילה ──
    # A locked view may be read and built on, never overwritten — not even by
    # the person who made it, until they unlock it. The tab strip is shared, so
    # the cut a department works off is not a thing to lose to a stray "שמור".
    locked = Column(Boolean, default=False)
    # ── הצמדה ──
    # Pinned views come first in the strip, for everyone. Belongs to the board
    # rather than to the reader: it says this cut is the important one here.
    pinned = Column(Boolean, default=False)
    # ── מחיקה ושחזור ──
    # A view is a tab other people rely on, so deleting one is reversible the
    # way deleting a board or an item is: NULL deleted_at means a live view.
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    # ── גרסת תצורה ──
    # Bumped every time the shared configuration changes, and never otherwise.
    # A timestamp nearly does this job and fails at the edges: two saves in the
    # same clock tick compare equal, and a client that has to decide whether
    # what it is holding is stale cannot afford "nearly". A counter also says
    # HOW MANY times it moved, which a timestamp cannot.
    config_version = Column(Integer, default=1)
    # ── גרסת מבנה ──
    # What shape `filters` is in. Nothing reads it yet, which is the point:
    # it is here so that the day the shape changes, the rows written before
    # that day can say so instead of being guessed at by their contents.
    schema_version = Column(Integer, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BoardViewPrefs(Base):
    """One person's own arrangement of one board's view tabs.

    Order is the one thing about a shared strip that is nobody else's business:
    which cut somebody reaches for first is a habit, not a statement about the
    board. Pinning IS a statement about the board and lives on the view itself.

    A list of view ids, most-wanted first. Ids missing from it keep the board's
    own order, after the ones named here — so a view created after somebody
    arranged their strip simply appears at the end instead of disturbing it.
    """
    __tablename__ = "board_view_prefs"
    __table_args__ = (UniqueConstraint("board_id", "user_id", name="uq_board_view_prefs"),)
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    order = Column(JSON, default=list)
    # Which view this person was last on, on this board. Beside the order and
    # for the same reason: both are "where I am on this board", and both are
    # the kind of thing somebody expects to find waiting on the next machine
    # they sign in from. NULL — never opened one — means the main table.
    #
    # It is a preference and not a right: the view it names may have been
    # deleted since, or may hold a filter this person is no longer allowed to
    # run. Resolved on the way out, never trusted on the way in.
    last_view_id = Column(Integer, ForeignKey("saved_views.id"), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    # A deleted item goes to its board's recycle bin rather than disappearing.
    # Everything it owns — sub-items, comments, files, history — stays intact, so
    # a restore brings the item back whole rather than as a husk.
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
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
    # "מזהה פריט" column: an automatic 11-digit identifier, unique inside the
    # board it was minted for. Never editable by hand; item_uid_board records
    # the board so an item that changes boards is issued a fresh identifier.
    item_uid = Column(String(11))
    item_uid_board = Column(Integer)
    custom_fields = Column(JSON, default=dict)
    permissions = Column(JSON, default=dict)  # item-level per-user perms {"<uid>":"view|edit|none"}
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

class Automation(Base):
    """A board-scoped if-then rule ("כאשר… אז…"), built from a recipe.

    `recipe_id` names the template (which trigger pairs with which action) and
    `config` holds the values the board admin filled into its placeholders — a
    status key, a user id, a group id. Keeping the recipe by id rather than
    copying its wording means a recipe's phrasing can be improved later without
    rewriting stored rules.
    """
    __tablename__ = "automations"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False)
    recipe_id = Column(String(60), nullable=False)
    # Which version of that template the rule was built from. A system template
    # is versioned so a rule goes on meaning what it meant when it was built:
    # the rule keeps its own `config`, and this says what it was answering.
    template_version = Column(Integer, default=1)
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # ── how the rule is MANAGED (the ניהול tab) ──
    # A rule is also an operational object, not only a recipe: someone owns it,
    # it matters more or less than the rule beside it, and it can be a draft
    # nobody has switched on yet.
    name = Column(String(120), default="")        # optional; the sentence stands in for it
    description = Column(Text, default="")        # תיאור עסקי — the process it serves
    # draft | active | paused | paused_error | deleting. `is_active` below is what
    # the ENGINE reads; status is what a person manages. _set_automation_status
    # is the one place that keeps the two from disagreeing.
    status = Column(String(16), default="active")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # critical|high|normal|low. For sorting and filtering ONLY — it never affects
    # which rule runs first. `run_order` below is the field that does.
    importance = Column(String(10), default="normal")
    # the actual precedence the engine reads: lower runs first when one event
    # trips several rules. Independent of `importance` above.
    run_order = Column(Integer, default=0)
    # light run telemetry — helps a board admin see whether a rule actually fires
    last_run_at = Column(DateTime, nullable=True)
    run_count = Column(Integer, default=0)
    # durable counters: the run log is pruned per board, these are not, so the
    # success rate stays honest long after the rows behind it are gone
    fail_count = Column(Integer, default=0)
    skip_count = Column(Integer, default=0)
    consecutive_failures = Column(Integer, default=0)   # what takes a rule out of service
    last_success_at = Column(DateTime, nullable=True)
    last_failure_at = Column(DateTime, nullable=True)
    last_outcome = Column(String(12), default="")       # ran | skipped | failed
    # When it was last switched on. An activation applies to events from that
    # moment forward — it is not a licence to act on everything that happened
    # while the rule was off.
    activated_at = Column(DateTime, nullable=True)
    # The version number of the edit waiting to be published. An edit to a
    # running rule does not change what runs: it is written as a draft version
    # and this points at it until someone publishes it.
    draft_version = Column(Integer, nullable=True)
    # engine bookkeeping (not user config) — e.g. which items a date trigger
    # already fired for, so a due date cannot notify the same item twice
    state = Column(JSON, default=dict)
    board = relationship("Board")


class AutomationRun(Base):
    """One attempt of one rule on one item — the "היסטוריית הפעלות" log.

    Written whatever the outcome: a rule that fired, a rule that matched but had
    nothing to do (`skipped`), and a rule that blew up (`failed`). A board admin
    reading this is usually asking "why did nothing happen?", which only a row
    for the non-events can answer.

    The row is self-describing on purpose. `sentence` is the rule as it read at
    run time and `task_title` the item as it was named then, so history survives
    both the rule being rewritten and the item being renamed; `automation_id`
    goes NULL when the rule is deleted rather than taking its history with it.
    `event` keeps the trigger's own context (which status, which link), which is
    what a retry replays.
    """
    __tablename__ = "automation_runs"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True, index=True)
    recipe_id = Column(String(60), nullable=False)
    sentence = Column(Text, default="")
    trigger_key = Column(String(40), default="")
    action_key = Column(String(40), default="")
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    task_title = Column(String(300), default="")
    event = Column(JSON, default=dict)
    # Where the change came from, and — when it came from one action over many
    # items — the id that action shares across all of them. Two different
    # questions: "what kind of change was this" and "was this one of a batch",
    # and a log that answered them with one field could answer neither.
    source = Column(String(16), default="", index=True)
    batch_id = Column(String(36), default="", index=True)
    outcome = Column(String(12), default="ran")      # ran | skipped | failed
    # a "בדיקה על פריט": the action really ran, inside a transaction that was
    # then rolled back, so the outcome is real but nothing it did survived
    is_test = Column(Boolean, default=False)
    # Which version of the rule this run was carried out under. A run is decided
    # by the version in force when the event arrived, and this is where that is
    # answerable afterwards.
    version = Column(Integer, nullable=True)
    reason = Column(Text, default="")                # why it skipped, or what failed
    depth = Column(Integer, default=0)               # 0 = the change itself, >0 = a cascade
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    retry_of = Column(Integer, ForeignKey("automation_runs.id"), nullable=True)
    retried_at = Column(DateTime, nullable=True)     # set on the run a retry replayed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AutomationVersion(Base):
    """What a rule looked like after each change — the גרסאות list.

    A rule is configuration that quietly rewrites items, so "who changed it, and
    to what?" has to be answerable later. Each row is the whole rule as it stood
    after one edit, plus the sentence it read as at the time, so an old version
    is legible without replaying anything.
    """
    __tablename__ = "automation_versions"
    id = Column(Integer, primary_key=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=False, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    version = Column(Integer, default=1)
    sentence = Column(Text, default="")
    snapshot = Column(JSON, default=dict)
    summary = Column(String(300), default="")     # what changed, in words
    # A draft version is an edit that has not been published. The live rule is
    # unchanged until someone activates it, which is what lets an active rule be
    # edited without the board changing under it mid-day.
    is_draft = Column(Boolean, default=False)
    published_at = Column(DateTime, nullable=True)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AutomationUsage(Base):
    """How much automation a board actually consumed, by calendar month.

    Counted here rather than from the run log, because that log is trimmed per
    board: a quota read off it would quietly shrink as the log rolled over, and
    a quota nobody can trust is worse than none. One row per board per month,
    incremented as rules fire.
    """
    __tablename__ = "automation_usage"
    __table_args__ = (UniqueConstraint("period", "board_id", name="uq_automation_usage"),)
    id = Column(Integer, primary_key=True)
    period = Column(String(7), nullable=False, index=True)      # "2026-09"
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    ran = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AutomationFreeze(Base):
    """An emergency stop on automations — one board's, or the whole organisation's.

    Deliberately a record and not a flag. A freeze carries the reason it was
    imposed, who imposed it and when, and it is released only by someone saying
    so: nothing here expires it, because an automation that switches itself back
    on is exactly what an emergency stop exists to prevent. `released_at` closes
    a freeze without erasing it, so the audit reads as the sequence it was.
    """
    __tablename__ = "automation_freezes"
    id = Column(Integer, primary_key=True)
    scope = Column(String(10), nullable=False)          # "org" | "board"
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True, index=True)
    reason = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    released_at = Column(DateTime, nullable=True)
    released_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    release_reason = Column(Text, default="")


class AutomationTestRun(Base):
    """A "בדיקה על פריט" — a dry run, kept in a log of its own.

    Separate from the run history on purpose: a test is not something the board
    did, and mixing the two makes the history unreadable exactly when someone is
    trying to work out what really happened. `details` holds the whole analysis
    — the trigger match, each condition, the actions and their expected values,
    the permissions that are missing and the conflicts found — so a test can be
    re-read later without being run again.

    Kept for AUTOMATION_TEST_LOG_DAYS and then swept: a test is a working note,
    not a record of the board.
    """
    __tablename__ = "automation_test_runs"
    id = Column(Integer, primary_key=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    task_title = Column(String(300), default="")
    sentence = Column(Text, default="")
    version = Column(Integer, nullable=True)
    verdict = Column(String(16), default="would_run")   # would_run|would_skip|blocked
    summary = Column(String(400), default="")
    details = Column(JSON, default=dict)
    tested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    parent_id = Column(Integer, ForeignKey("comments.id"), nullable=True)  # threaded replies
    content = Column(Text, nullable=False)
    attachments = Column(JSON, default=list)   # [{name,url}]
    mentions = Column(JSON, default=list)      # [user_id, ...]
    likes = Column(JSON, default=list)         # [user_id, ...]
    seen_by = Column(JSON, default=list)       # [user_id, ...] — read receipts
    # Where an imported message came from: {"source","author","external_id"}.
    # An import brings conversations written by people who may have no account
    # here. Attributing those to whoever ran the import would put words in a
    # colleague's mouth, so `user_id` stays empty and the original author is
    # named from here instead.
    origin = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    task = relationship("Task", back_populates="comments")
    replies = relationship("Comment", backref="parent", remote_side=[id])

class BoardMember(Base):
    """Per-board membership & role. Access is membership-based: a user only sees
    boards they are invited to. 'admin' here is board-scoped (manages that board's
    members/permissions) — it is NOT a global super-user."""
    __tablename__ = "board_members"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String(20), default="editor")  # admin | editor | viewer  (board-scoped)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User")

class WorkspaceMember(Base):
    """Environment/workspace membership. 'Invite to environment' with a default
    role that seeds the board role when a user is added to a board."""
    __tablename__ = "workspace_members"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    role = Column(String(20), default="member")  # admin | member | viewer
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User")

class RolePermission(Base):
    """Configurable capability matrix: whether a given user role (manager/member/
    viewer/guest) is granted a top-level capability. The 'admin' role always has
    every capability and is not stored here."""
    __tablename__ = "role_permissions"
    id = Column(Integer, primary_key=True)
    role = Column(String(50), nullable=False)        # manager | member | viewer | guest
    capability = Column(String(50), nullable=False)  # manage_system | create_environment | create_board
    allowed = Column(Boolean, default=False)

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


class ItemLink(Base):
    """One row per RELATIONSHIP between two items, for two-way connect columns.

    A one-way column keeps its links in the item's custom_fields, as it always
    has. A two-way column does not: neither side stores a copy, both read this
    table, and so the two sides cannot drift apart. That is what "a single
    logical relationship, not two independent ones" has to mean — mirroring two
    arrays on write only holds until something writes one of them directly.

    The pair is stored once, in a canonical order (lower task id first), so
    (A→B) and (B→A) cannot both exist.
    """
    __tablename__ = "item_links"
    id = Column(Integer, primary_key=True)
    a_task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    a_col = Column(String(64), nullable=False)     # column on A's board
    b_task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    b_col = Column(String(64), nullable=False)     # the mirror column on B's board
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)


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
    # Where this row came from, when it was not this system that did the thing.
    # An imported monday activity entry keeps its own author's name here — the
    # audit has nowhere else to put a person with no account — and the presence
    # of this field is what stops the row from offering an undo: reverting a
    # change made in monday last year would write that value onto the item now.
    # Same shape as Comment.origin, for the same reason.
    origin = Column(JSON, nullable=True)
    changer = relationship("User", foreign_keys=[changed_by])


class LoginEvent(Base):
    """A single successful login, recorded for the admin login-history view."""
    __tablename__ = "login_events"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    logged_in_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ip = Column(String(64))
    user_agent = Column(String(400))


class BoardView(Base):
    """When each person last opened each board — one row per pair, overwritten.

    A history of every visit would be the larger and less useful thing: the
    question the board asks is "who has seen this lately", not "how many times
    did they look". One row per person keeps the table proportional to the
    people, not to the traffic.
    """
    __tablename__ = "board_views"
    __table_args__ = (UniqueConstraint("board_id", "user_id", name="uq_board_view"),)
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class UploadedFile(Base):
    """File attachments stored in the DB so they persist and are shared across
    serverless instances (the local filesystem on Vercel is ephemeral/per-instance)."""
    __tablename__ = "uploaded_files"
    id = Column(Integer, primary_key=True)
    token = Column(String(40), unique=True, index=True)
    name = Column(String(300))
    content_type = Column(String(150))
    data = Column(LargeBinary)
    size = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Notification(Base):
    """In-app notification for a single recipient (e.g. added/removed from a board)."""
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)   # recipient
    type = Column(String(40))                                        # board_add | board_remove | ...
    title = Column(String(200))
    body = Column(Text)
    board_id = Column(Integer, nullable=True)                        # deep-link target, if any
    task_id = Column(Integer, nullable=True)                         # open this item's chat, if any
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ── Init DB ──────────────────────────────────────────────────────────

def init_db(db_url="sqlite:///cityos.db"):
    # pool_pre_ping keeps Postgres connections healthy across serverless cold
    # starts / idle drops; harmless for SQLite.
    engine = create_engine(db_url, echo=False, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine
