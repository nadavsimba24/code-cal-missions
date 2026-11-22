"""
CityOS — Municipal Work Management Platform
Database Models
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, JSON, Enum as SAEnum, Table, LargeBinary,
    UniqueConstraint, CheckConstraint, ForeignKeyConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone
import enum
import os

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
    # Organisation-wide preferences. `timezone` is the one this holds today:
    # an IANA name every board inherits unless it names one of its own.
    settings = Column(JSON, default=dict)
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

# ── תצוגת טופס (Form View) ───────────────────────────────────────────
# The closed sets live here rather than in main.py because the CHECK
# constraints below are generated FROM them. One list, so the database and
# the server cannot drift apart about what a legal value is — a status the
# code accepts and the table refuses is a bug that only appears in
# production, and the reverse is a value nothing ever validates.
FORM_STATUSES = ("DRAFT", "PUBLISHED", "DISABLED")
FORM_ACCESS_MODES = ("AUTHENTICATED", "PUBLIC_LINK")
FORM_COMPONENT_KINDS = ("question", "heading", "text")


def _sql_in(values):
    """`('A', 'B')` — the IN list for a CHECK, built from the tuple above."""
    return "(" + ", ".join("'%s'" % v for v in values) + ")"


class FormView(Base):
    """A form that fills one board — the settings half of a `kind="form"` view.

    "טופס הוא תצוגה של לוח ושייך ללוח אחד בלבד." The identity, the name on the
    tab, the position in the strip, the lock, the bin and the configuration
    version are all things a view already is, and they are not rebuilt here:
    this row hangs off a `SavedView` whose `kind` is "form" and holds only what
    a form has and a saved cut does not — how it is reached, how it looks, and
    what it says once somebody has sent it.

    `board_id` is carried here as well as on the view, and not for convenience:
    it is half of the composite key `form_components` points at, which is what
    makes "a question belongs to the same board as its form" a fact about the
    shape of the data instead of a rule every writer has to remember. It is
    written once, at creation, from the view's own board and never after.

    The board itself is untouched by any of this. A form names columns; it does
    not own them, and deleting a form deletes questions and nothing else —
    "מחיקת טופס אינה מוחקת שדות או רשומות בלוח" is true because there is
    nothing here that a column or an item hangs off.
    """
    __tablename__ = "form_views"
    __table_args__ = (
        # One form per view row. The pair is 1:1 and the database says so,
        # rather than leaving a second settings row possible and a reader to
        # pick between them.
        UniqueConstraint("view_id", name="uq_form_view_view"),
        # Exists only so a component can reference the PAIR — see the class
        # below. Redundant as a uniqueness claim (id is the primary key) and
        # necessary as a target: a composite foreign key needs a unique
        # constraint on exactly the columns it names.
        UniqueConstraint("id", "board_id", name="uq_form_view_board"),
        CheckConstraint("status IN " + _sql_in(FORM_STATUSES),
                        name="ck_form_view_status"),
        CheckConstraint("access IN " + _sql_in(FORM_ACCESS_MODES),
                        name="ck_form_view_access"),
    )
    id = Column(Integer, primary_key=True)
    # The tab. NOT NULL with nothing defaulting it, which is the whole of
    # "לא ניתן ליצור טופס ללא לוח": a form cannot exist before the view does,
    # and a view cannot exist without a board.
    view_id = Column(Integer, ForeignKey("saved_views.id"), nullable=False, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)

    # ── state ──
    # DRAFT → PUBLISHED → DISABLED, and back. A draft has never been reachable;
    # a disabled form was and is not any more, which is a different answer to
    # give somebody holding the link (410, not 404).
    status = Column(String(10), nullable=False, default="DRAFT")
    # AUTHENTICATED — any active account. PUBLIC_LINK — the token is the whole
    # of the authorisation. Enforced at the endpoint, never by board role:
    # "מילוי טופס אינו מעניק גישה ללוח", and the reverse holds too — having the
    # board does not decide whether the form opens.
    access = Column(String(16), nullable=False, default="AUTHENTICATED")
    # The public identifier, and it is a CAPABILITY: whoever holds it can
    # reach the form, so it is random and unguessable rather than derived from
    # the board or the view. uuid4().hex, like UploadedFile.token.
    #
    # NULL until the first publish. A form nobody has published has no address
    # — not a secret one, none — so there is nothing to leak early and nothing
    # that quietly becomes live later. Minted once and then kept: disabling a
    # form and publishing it again returns it to the same address, because
    # "closed" is a state and not a new form.
    public_token = Column(String(40), nullable=True, unique=True, index=True)

    # ── where a submission lands ──
    # A form with no group creates items with no group, which is legal and
    # almost never meant. Nullable so a draft can be saved before the question
    # is answered; required at publish, where it is a decision and not a
    # default somebody never saw.
    target_group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)

    # ── עיצוב ──
    # Columns rather than a JSON blob, for the reason the last two entities
    # were made into tables: a setting inside a column is something no screen
    # can list, no migration can rename and no query can group by. The set is
    # typography, alignment and branding, which is what the specification
    # names; anything it adds later is one more column and one more line in
    # _migrate.
    display_title = Column(String(200), default="")
    display_description = Column(Text, default="")
    # Not a choice anybody makes. The product has one font stack — Figtree for
    # the Latin, Rubik for the Hebrew (CONVENTIONS.md) — and "no free font
    # selection" is in the specification. The column stays because rows were
    # written with it; nothing reads it as a setting.
    font_family = Column(String(60), default="Rubik")
    font_size = Column(String(10), default="medium")        # small | medium | large
    # Defaults to the direction the product is written in. The app is
    # `<html dir="rtl" lang="he">`, so a form starts reading right to left and
    # the other two are a deliberate change.
    text_align = Column(String(10), default="right")        # right | center | left
    theme_color = Column(String(7), default="#0073ea")      # monday blue — no purple
    background_color = Column(String(7), default="#ffffff")
    text_color = Column(String(7), default="#323338")
    # Branding images are uploads, referenced by the token the upload returns
    # rather than copied in: the bytes already have a home in uploaded_files.
    logo_token = Column(String(40), nullable=True)
    cover_token = Column(String(40), nullable=True)
    show_logo = Column(Boolean, default=True)

    # ── מסך הצלחה ──
    # What the person who sent the form sees. Deliberately separate from the
    # design above: it is the only screen some of them will ever read, and a
    # form that says nothing after a submission reads as one that lost it.
    success_title = Column(String(200), default="")
    success_message = Column(Text, default="")
    # Offer a second submission from the same screen. Off by default: most
    # forms are filled once, and the invitation is what turns a form into a
    # way to make twenty items by accident.
    success_allow_another = Column(Boolean, default=False)
    success_redirect_url = Column(String(500), nullable=True)
    # What the button at the bottom says. Short on purpose: it is a button.
    submit_label = Column(String(40), default="")

    # ── מיתוג ──
    # "מופעל by Missions" under the form. On by default and taken off only by
    # somebody the system says may — see the hide_form_branding capability.
    # Stored per form rather than per board: two forms on one board can be
    # one for colleagues and one for the public, and only the second one is
    # a place the product's name belongs.
    show_branding = Column(Boolean, default=True)

    # ── הגשה ──
    # "זמן ההגשה ומזהה המשתמש המגיש כאשר נדרש". The record IS the submission —
    # there is no submissions table, and a second one would start disagreeing
    # with the board the first time somebody edited the item — so the two
    # facts are the ones the item already carries: Task.created_at is when it
    # was sent and Task.created_by is who sent it. This flag is the "כאשר
    # נדרש": off, the submitter is not written even when there is one, which
    # is what an anonymous form means. Task.form_view_id is the third fact,
    # the one the item did not have: which form it came from.
    record_submitter = Column(Boolean, default=True)

    # ── פרסום ──
    published_at = Column(DateTime, nullable=True)
    published_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    view = relationship("SavedView")
    # The components go with the form and nothing else does. delete-orphan is
    # what makes removing a question from the list delete its row rather than
    # leaving it parentless.
    components = relationship("FormComponent", back_populates="form",
                              order_by="FormComponent.position",
                              cascade="all, delete-orphan")


class FormComponent(Base):
    """One row of a form, in the order the form puts it in.

    Three kinds. A `question` is bound to a field of the board — that binding
    is the only thing about it that belongs to the board. A `heading` and a
    `text` are the form's own words and are bound to nothing.

    "רכיבי הטופס נשמרים בסדר עצמאי מסדר השדות בלוח": `position` is the form's
    order and the board's column order is not consulted anywhere. Two forms on
    one board can ask the same questions in opposite orders, and reordering
    either changes nothing about the board or about the other form.

    The question's words are the form's, not the column's. `label` is stored,
    never read from the column at display time — which is the single change
    that makes "הגדרות השאלה עצמאיות מהלוח" true. The column still decides the
    TYPE, because that is the data contract and not a wording: a question that
    carried a type of its own could write a value the cell cannot read.
    """
    __tablename__ = "form_components"
    __table_args__ = (
        # The component's board is its form's board, and the database holds
        # the pair together. Declarative only on SQLite, which does not
        # enforce foreign keys unless asked — so the server checks it too
        # (_form_field_or_400). On Postgres this is the real thing.
        ForeignKeyConstraint(["form_id", "board_id"],
                             ["form_views.id", "form_views.board_id"],
                             name="fk_form_component_board",
                             ondelete="CASCADE"),
        CheckConstraint("kind IN " + _sql_in(FORM_COMPONENT_KINDS),
                        name="ck_form_component_kind"),
        # A question names a field; a heading and a text must not. Both halves
        # are written out, because only one of them is the common mistake and
        # the other is the one that would quietly orphan a binding.
        CheckConstraint("(kind = 'question' AND field_key IS NOT NULL) "
                        "OR (kind <> 'question' AND field_key IS NULL)",
                        name="ck_form_component_field"),
    )
    id = Column(Integer, primary_key=True)
    # No single-column foreign key of its own: the composite one above is the
    # reference, and a second path to the same table would leave the
    # relationship below with two ways to join and no way to choose.
    form_id = Column(Integer, nullable=False, index=True)
    # Not derived on read — it is the other half of that key.
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    kind = Column(String(10), nullable=False, default="question")
    # The board field this question is bound to — a column id from
    # board.settings["columns"], or one of the built-in keys (title,
    # assignees, status, priority, due_date). A column is not a row in this
    # system, so there is no foreign key to point at and the check is the
    # server's: see _form_field_or_400.
    field_key = Column(String(80), nullable=True, index=True)
    # Where it sits in the FORM. Not unique: a reorder that swapped two
    # positions would have to pass through a state where both rows hold the
    # same one, and a constraint that forbids the intermediate step forbids
    # the operation.
    position = Column(Integer, nullable=False, default=0)

    # ── שאלה ──
    label = Column(String(200), default="")
    description = Column(Text, default="")
    placeholder = Column(String(200), default="")
    required = Column(Boolean, default=False)
    # "גלוי" — a hidden question is not asked and not answered. Hiding wins
    # over required, and the combination is refused on save rather than
    # resolved at display: a form that cannot be submitted should not be a
    # form that can be saved.
    visible = Column(Boolean, default=True)
    # Per-type constraints the question carries and the column does not — the
    # date range the current builder already stores as min/max. JSON because
    # the set differs per column type and a column per type would be mostly
    # NULL; unlike the design settings above, nothing lists or groups by it.
    settings = Column(JSON, default=dict)

    # ── heading | text ──
    content = Column(Text, default="")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    form = relationship("FormView", back_populates="components")


# ── דשבורדים ──────────────────────────────────────────────────────────
# A dashboard is a set of measures read off boards. Two flavours, one table:
# "עצמאי בסביבת עבודה" combines up to ten boards, and "תצוגה בתוך לוח" shows
# the board it is a tab on and nothing else. The spec lists ONE field set for
# both — "מזהה, סוג, לוח מארח אם נדרש, סביבת עבודה, …" — and "אם נדרש" is the
# whole argument for one table: the two differ by which columns are filled,
# not by what a dashboard IS.
DASHBOARD_KINDS = ("standalone", "board")
# ראשי — everyone who may reach the workspace. פרטי — the people invited.
# Deliberately not the board's "public"/"private": a board's audience is its
# environment, a dashboard's is its invitees, and naming them alike would
# invite one to be read through the other's rules.
DASHBOARD_VISIBILITY = ("main", "private")
# Owners manage; viewers look. No system roles are created — DASH-03.2 —
# so this table is the whole of a dashboard's own audience.
DASHBOARD_MEMBER_ROLES = ("owner", "viewer")
# "numbers" and "chart" are the specification's two. "list" is a third,
# asked for afterwards and not excluded by it: the dashboard could say how
# MUCH and how it is DISTRIBUTED, and could not show the records themselves.
# It measures nothing — it is the same population the other two are built
# from, drawn as rows — so it inherits their sources, filters, permissions
# and blocking rather than introducing a second way to read a board.
WIDGET_TYPES = ("numbers", "chart", "list")
# "לכל ווידג׳ט בוחרים פריטים בלבד, תתי־פריטים בלבד או שניהם; ברירת מחדל פריטים."
WIDGET_SCOPES = ("items", "subitems", "both")


class Dashboard(Base):
    """A dashboard — the settings, never the numbers.

    "תוצאות מחושבות אינן מקור אמת." Nothing computed is stored here: no
    totals, no categories, no cached series. The row says what to measure and
    who may see it, and every figure is worked out from the live boards at
    read time. A stored total is a number that was true once, and a dashboard
    that shows one cannot tell the difference between data and memory.

    **A board dashboard is a tab, and reuses the tab.** `view_id` points at a
    `SavedView` whose `kind` is "dash", exactly as `FormView` does for a form:
    the name, the position in the strip, the lock, the recycle bin and the
    uniqueness of the name are all things a view already is, and rebuilding
    them here would mean two answers to "what is this tab called". A
    standalone dashboard has no tab and no board, so both are NULL.

    `config_version` is THE version of this dashboard's configuration — its
    own settings AND its widgets. One counter and not two, because the
    conflict a save has to catch is "somebody changed this dashboard", and a
    widget is part of it: two versions would let a widget rewrite land on top
    of a settings rewrite with both of them claiming to be current. The
    compute response carries this one number for the same reason (R09, R10).
    """
    __tablename__ = "dashboards"
    __table_args__ = (
        # One dashboard per view row, the same 1:1 `form_views` declares and
        # for the same reason: a second settings row for one tab leaves a
        # reader to pick between them.
        UniqueConstraint("view_id", name="uq_dashboard_view"),
        CheckConstraint("kind IN " + _sql_in(DASHBOARD_KINDS),
                        name="ck_dashboard_kind"),
        CheckConstraint("visibility IN " + _sql_in(DASHBOARD_VISIBILITY),
                        name="ck_dashboard_visibility"),
    )
    id = Column(Integer, primary_key=True)
    kind = Column(String(12), nullable=False, default="standalone")

    # ── where it lives ──
    # Both NULL for a standalone dashboard; both filled for a board one.
    # `board_id` is carried beside `view_id` rather than read through it
    # because it is the host board — "הלוח המארח יהיה המקור היחיד והקבוע"
    # (DASH-06.1) — and a source that has to be joined to be known is a source
    # that can be forgotten in the one query that matters.
    view_id = Column(Integer, ForeignKey("saved_views.id"), nullable=True, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True, index=True)
    # The workspace a standalone dashboard belongs to. NULL for a board
    # dashboard, whose environment is the board's and must not be able to
    # disagree with it.
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=True, index=True)
    position = Column(Integer, default=0)      # order within the environment

    # ── identity ──
    # A board dashboard's name is the view's; this is NULL there, so the tab
    # cannot be renamed in two places. Filled, and required, for a standalone.
    name = Column(String(80), nullable=True)

    # ── audience ──
    # Only meaningful for a standalone. A board dashboard is reached through
    # the board, by the board's own roles — DASH-03.2 — so nothing here
    # applies to it and it is left at the default.
    visibility = Column(String(10), nullable=False, default="main")
    # Who made it. They are an owner by definition and are NOT written into
    # `dashboard_members`: an owner who could be removed from their own
    # dashboard is a dashboard that can end up belonging to nobody, which is
    # the bug `Environment.created_by` was added to close.
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # ── what it measures ──
    # [{board_id, groups: null | [group_id, …]}, …] — null groups means ALL
    # groups "כולל קבוצות עתידיות" (R02), which is why it is a null and not
    # the list of ids that happen to exist today. Capped at DASHBOARD_MAX_BOARDS
    # by the endpoint, where the refusal can say what to do about it.
    sources = Column(JSON, default=list)
    # The dashboard-wide filter, in the same shape `SavedView.filters` holds —
    # so `filter_ast` reads one tree here and on a board, and a condition
    # cannot mean one thing in a view and another in a dashboard.
    filters = Column(JSON, default=dict)
    # Grid geometry for the desktop layout, by widget id. The READING ORDER
    # is the widget's own `position` — the mobile column follows it (R08) —
    # and this holds only what a grid adds on top: column, row, span.
    layout = Column(JSON, default=dict)

    # ── versions ──
    config_version = Column(Integer, default=1)
    schema_version = Column(Integer, default=1)

    # ── the bin ──
    # A dashboard other people read is deleted the way a board, an item and a
    # view are: NULL means live. "מחיקה תחייב אישור ותסיר את הגדרות הדשבורד
    # בלבד" (DASH-05.3) — nothing here owns a board, a column or an item, so
    # there is nothing for a delete to take with it.
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    widgets = relationship("DashboardWidget", back_populates="dashboard",
                           order_by="DashboardWidget.position")
    members = relationship("DashboardMember", back_populates="dashboard")


class DashboardMember(Base):
    """Who may manage a standalone dashboard, and who was invited to read it.

    "עריכה ליוצר ולבעלים נוספים שהוא מגדיר. ראשי נגיש למורשי סביבת העבודה;
    פרטי למוזמנים בלבד."

    **Being here grants nothing about data.** R01 is explicit — "בעלות או
    הזמנה אינן מעניקות הרשאות לנתוני מקור" — so every figure and every
    drill-down row is still gated by the board, column and item permissions
    the rest of the system enforces. This table answers one question only:
    may this person open this dashboard at all.
    """
    __tablename__ = "dashboard_members"
    __table_args__ = (
        # One row per person per dashboard. Without it an invitation sent
        # twice leaves two rows, and removing access removes one of them.
        UniqueConstraint("dashboard_id", "user_id", name="uq_dashboard_member"),
        CheckConstraint("role IN " + _sql_in(DASHBOARD_MEMBER_ROLES),
                        name="ck_dashboard_member_role"),
    )
    id = Column(Integer, primary_key=True)
    dashboard_id = Column(Integer, ForeignKey("dashboards.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(10), nullable=False, default="viewer")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    dashboard = relationship("Dashboard", back_populates="members")


class DashboardWidget(Base):
    """One measure on a dashboard — a number or a chart.

    Everything that decides what the figure IS lives here, and nothing that
    the figure turned out to be. The split between the JSON columns is by
    what each answers, because that is how they are read: `sources` and
    `mapping` say WHERE from, `filters` says WHICH records, `metrics` says
    WHAT is computed, and `chart` says how it is drawn.

    `mapping` is the approved column mapping and it is kept BY COLUMN ID —
    "המיפוי נשמר לפי מזהים; שינוי שם אינו שובר אותו" (R05). A proposal made
    by name and type is never stored: DASH-07.1 requires somebody to approve
    or correct it first, so what reaches this column has been agreed to.
    """
    __tablename__ = "dashboard_widgets"
    __table_args__ = (
        CheckConstraint("type IN " + _sql_in(WIDGET_TYPES),
                        name="ck_dashboard_widget_type"),
        CheckConstraint("record_scope IN " + _sql_in(WIDGET_SCOPES),
                        name="ck_dashboard_widget_scope"),
    )
    id = Column(Integer, primary_key=True)
    dashboard_id = Column(Integer, ForeignKey("dashboards.id"), nullable=False, index=True)
    type = Column(String(10), nullable=False, default="numbers")

    # ── what it says ──
    title = Column(String(120), nullable=False, default="")   # required — DASH-11.1
    description = Column(Text, default="")                    # optional — DASH-11.1
    # Reading order, and the one the mobile column follows (R08). Kept apart
    # from the desktop grid in `Dashboard.layout` because "הצגה במובייל לא
    # תשנה את גדלי הדסקטופ" (DASH-19.3) — one of them has to survive the
    # other being rearranged.
    position = Column(Integer, default=0)

    # ── where from ──
    # A SUBSET of the dashboard's sources, in the same shape — "לכל ווידג׳ט
    # תת־קבוצה מהם" (R02). Empty means every source the dashboard has, so a
    # widget does not have to be rewritten when a board is added to it.
    sources = Column(JSON, default=list)
    # {board_id: {metric_key: column_id}} — the approved mapping, by id.
    mapping = Column(JSON, default=dict)
    record_scope = Column(String(10), nullable=False, default="items")

    # ── which records ──
    # The widget's own filter. Applied as an INTERSECTION with the
    # dashboard's — "המסנן המקומי יחול יחד עם מסנן הדשבורד, בחיתוך ביניהם"
    # (DASH-16.2) — never instead of it.
    filters = Column(JSON, default=dict)

    # ── what is computed ──
    # [{key, calc: count|sum|avg, unit, scale, precision, empty_policy,
    #   mirror_agg}, …] — one entry per measure, because "כמה מדדים מותרים
    # באותה יחידה ובציר משותף" (R06). `empty_policy` is per widget in the
    # spec and per metric here: a widget with two measures over two columns
    # has two populations of blanks, and one flag could only be right about
    # one of them. `mirror_agg` is the inner sum-or-average a multi-valued
    # mirror needs BEFORE the widget's own calculation (R03).
    metrics = Column(JSON, default=list)

    # ── how it is drawn ──
    # Dimension, period, split, sort, colours by id, legend, labels and the
    # "ללא ערך" setting — DASH-02.3. Empty for a numbers widget; it is one
    # column rather than eight because every one of them is chart-only, and a
    # numbers widget carrying eight permanent NULLs says nothing truer.
    chart = Column(JSON, default=dict)

    # ── how a list widget is drawn ──
    # {columns: {board_id: [column_id, …]}, limit, sort: {field, direction}}
    # Its own column rather than a corner of `chart`, because a list is not a
    # chart with the axes removed: it carries no dimension, no series and no
    # measure, and the two configurations have nothing in common to share.
    display = Column(JSON, default=dict)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    dashboard = relationship("Dashboard", back_populates="widgets")




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
    # Which form this item arrived through, when it arrived through one. The
    # other two facts a submission has — when, and by whom — are `created_at`
    # and `created_by` above, which is why there is no submissions table: the
    # record IS the submission, and a second row holding the same three facts
    # would start disagreeing with this one the first time somebody edited the
    # item. NULL on every item made the ordinary way.
    form_view_id = Column(Integer, ForeignKey("form_views.id"), nullable=True, index=True)
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


class AutomationQueue(Base):
    """Events waiting to be delivered, at a rate somebody approved.

    An import does not set automations off — that is the rule. But a board that
    has just had four hundred items imported into it may be exactly the board
    whose rules should now run, and a manager can say so. Four hundred items
    firing at once is not a thing to do inside a request, so the events are
    written here and drained a slice at a time.

    The row is the event, not the run: what comes of it is an AutomationRun
    like any other, carrying the same batch id as the rest of its approval.
    """
    __tablename__ = "automation_queue"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    event = Column(JSON, default=dict)
    batch_id = Column(String(36), default="", index=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    done_at = Column(DateTime, nullable=True, index=True)
    # ── a waiting run, and what it has to remember ──
    # Which rule and WHICH VERSION of it: a rule edited while this was waiting
    # goes on meaning what it meant when the wait began, which is the only
    # reading under which a wait is a promise rather than a guess.
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True,
                           index=True)
    version = Column(Integer, nullable=True)
    # pending | frozen | done | cancelled. Frozen is a pause somebody can undo;
    # cancelled is a decision, and it keeps the reason it was taken.
    state = Column(String(10), default="pending", index=True)
    note = Column(Text, default="")
    resume_at = Column(DateTime, nullable=True, index=True)


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
    # The id of the event itself — what the API hands back so a caller can ask
    # afterwards what their call set off.
    event_id = Column(String(32), default="", index=True)
    # The chain this firing belongs to: one change and everything the rules did
    # because of it. A third question again — not "what kind of change" and not
    # "was this one of a batch", but "what did this one edit set off", which is
    # the question somebody asks when a board moved under them.
    chain_id = Column(String(32), default="", index=True)
    outcome = Column(String(12), default="ran")      # ran | skipped | failed
    # The fine status out of eleven — see main.RUN_STATUSES. `outcome` stays
    # the coarse three it always was and is DERIVED from this one: everything
    # already built on "ran / skipped / failed" goes on meaning what it meant,
    # and the questions three answers could never tell apart — a false
    # condition against a missing value, a crash against a refusal — are
    # answerable without rewriting any of it.
    status = Column(String(24), default="", index=True)
    # Three moments, because the gap between the first two is the queue and the
    # gap between the last two is the work, and one timestamp hid both.
    queued_at = Column(DateTime, nullable=True)      # the event arrived
    started_at = Column(DateTime, nullable=True)     # the rule began
    finished_at = Column(DateTime, nullable=True)    # and ended
    attempt = Column(Integer, default=1)             # 1, or n for the nth retry
    error_code = Column(String(40), default="")      # groupable; `reason` is prose
    # Which sub-item the event was about, where it was about one. The run acts
    # on whichever of the two the rule names (see _acting_item) and `task_id`
    # is that one — this says what set it off.
    subitem_id = Column(Integer, nullable=True)
    # a "בדיקה על פריט": the action really ran, inside a transaction that was
    # then rolled back, so the outcome is real but nothing it did survived
    is_test = Column(Boolean, default=False)
    # Which version of the rule this run was carried out under. A run is decided
    # by the version in force when the event arrived, and this is where that is
    # answerable afterwards.
    version = Column(Integer, nullable=True)
    reason = Column(Text, default="")                # why it skipped, or what failed
    # What the actions actually produced — today, the items a rule created
    # somewhere else: which board, which group, what travelled with them and
    # the id of each. A creation nobody can point at afterwards is a creation
    # nobody can undo, and the reason text is not a thing code can follow.
    result = Column(JSON, default=dict)
    depth = Column(Integer, default=0)               # 0 = the change itself, >0 = a cascade
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    retry_of = Column(Integer, ForeignKey("automation_runs.id"), nullable=True)
    retried_at = Column(DateTime, nullable=True)     # set on the run a retry replayed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AutomationCreation(Base):
    """One item a rule created on another board, for one source item.

    "ב־MVP ייווצר לכל היותר פריט יעד אחד עבור אותו פריט מקור ואותה אוטומציה" —
    and this is where that is remembered. Not the run log: the log is pruned to
    the newest rows per board, so a busy source board would start duplicating
    on the target board the moment the first run scrolled off the end.

    Kept per (rule, source item). Per rule because two rules are two different
    intentions and neither is the other's duplicate; per source item because a
    cap per rule would mean a rule that fired once and never again.
    """
    __tablename__ = "automation_creations"
    id = Column(Integer, primary_key=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=False, index=True)
    source_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    target_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True)
    group_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("automation_id", "source_task_id",
                                       name="uq_automation_creation"),)


class AutomationActionKey(Base):
    """One action, done once — the idempotency key the retry rules rest on.

    "לכל פעולה מפתח Idempotency ייחודי. יצירת פריט או שליחת התראה שהצליחו לא
    יחזרו על עצמן." Resuming at the failed action is the plan; this is what
    holds when the plan is wrong — a replayed event, a double click, a retry
    aimed a step too early.

    Scoped to the CHAIN, so a genuinely new change gets a clean sheet: without
    that the guard would quietly turn every rule into a once-per-item rule.
    """
    __tablename__ = "automation_action_keys"
    id = Column(Integer, primary_key=True)
    key = Column(String(120), nullable=False, unique=True, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True, index=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AutomationActionExecution(Base):
    """One ACTION of one run — the row the run's JSON could not be.

    The same facts already travel inside AutomationRun.result["steps"], which
    the log screen reads and which stays exactly where it is. What JSON cannot
    do is answer a question across runs: "which action fails most often on
    this board", "how long does create_and_link actually take", "show me
    every notification this rule sent last month". Those are a GROUP BY, and a
    list inside a column is not something to group by.

    `idempotency_key` is the same key the engine writes to
    AutomationActionKey, carried here so a row can be matched to the thing
    that stopped it running twice.
    """
    __tablename__ = "automation_action_executions"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("automation_runs.id"), nullable=True, index=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    action_index = Column(Integer, default=1)      # 1-based, the order it ran in
    action_key = Column(String(40), default="", index=True)
    idempotency_key = Column(String(120), default="", index=True)
    status = Column(String(24), default="")        # one of main.RUN_STATUSES
    input = Column(JSON, default=dict)             # what the action was given
    target = Column(JSON, default=dict)            # what it was pointed at
    output = Column(JSON, default=dict)            # what came of it
    error_code = Column(String(40), default="")
    error = Column(Text, default="")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class AutomationAuthorizationGrant(Base):
    """What a rule is allowed to reach on ANOTHER board, as a row.

    Until this, the grant was a constant in the source: the set of actions and
    fields approved for automation, plus the link column's own list of target
    boards. All of that is still checked — but a constant can only ever be
    read. There was no way to look at a rule and see what it had been given,
    and no way to take it back short of editing the rule.

    A row per (rule, target board, action). Revoking one stops that rule from
    writing there, and the rule is suspended at its next firing with the
    reason — rather than quietly doing less than it says.
    """
    __tablename__ = "automation_grants"
    __table_args__ = (UniqueConstraint("automation_id", "target_board_id", "action_key",
                                       name="uq_automation_grant"),)
    id = Column(Integer, primary_key=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=False, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    target_board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    action_key = Column(String(40), default="", index=True)
    fields = Column(JSON, default=list)            # the field keys it may write
    granted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime, nullable=True, index=True)
    revoked_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class AutomationIncident(Base):
    """One rule, one kind of failure, from the first notice to the fix.

    A notification used to be where the handling of a broken rule started and
    also where it ended: the owner was told once and after that nothing in the
    system knew whether anybody had looked. A rule that broke on Thursday
    afternoon and a rule that broke and was fixed in ten minutes read exactly
    the same from outside.

    One row per (automation, failure kind) while it is open. `count` is how
    many runs hit it — twenty items edited at once is twenty failures and ONE
    problem — and `notified_at` is what keeps that from being twenty messages.
    """
    __tablename__ = "automation_incidents"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True, index=True)
    # what kind of failure this is: the status and the error code together, so
    # two different things going wrong with one rule are two incidents
    signature = Column(String(80), default="", index=True)
    error_code = Column(String(40), default="")
    status = Column(String(16), default="open")      # open | acknowledged | resolved
    note = Column(Text, default="")
    count = Column(Integer, default=1)
    suspended = Column(Boolean, default=False)       # the rule was taken out of service
    attempts_exhausted = Column(Boolean, default=False)
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    last_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notified_at = Column(DateTime, nullable=True)    # the half-hour window
    escalated = Column(String(10), default="")       # "" | board | system
    escalated_at = Column(DateTime, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    acked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acked_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    last_run_id = Column(Integer, nullable=True)


class EventOutbox(Base):
    """A business event, written in the same transaction as the change.

    The live path is an in-memory fan-out to whoever has a stream open: right
    for a screen, wrong for a record. An event raised while the loop is
    shutting down, or while nobody is listening, is simply gone — and the
    write it was announcing has already been committed, so a board that missed
    the announcement looks exactly like a board where nothing happened.

    Written here first and sent afterwards, which makes delivery at-least-once
    rather than at-most-once. The second delivery is harmless because every
    consumer here already has an idempotency key (see AutomationActionKey).

    `seq` is per ITEM and starts at 1: "moved to done" then "moved back" and
    the other way round are different stories about the same item, and a
    global counter cannot say which one happened.
    """
    __tablename__ = "event_outbox"
    id = Column(Integer, primary_key=True)
    kind = Column(String(40), nullable=False, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    automation_id = Column(Integer, ForeignKey("automations.id"), nullable=True)
    run_id = Column(Integer, nullable=True)
    seq = Column(Integer, default=1)               # per task_id, in order
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    sent_at = Column(DateTime, nullable=True, index=True)
    attempts = Column(Integer, default=0)
    dead_at = Column(DateTime, nullable=True)      # the dead-letter queue
    last_error = Column(Text, nullable=True)


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


class ColumnConversion(Base):
    """One run of "turn this column into a link to that board".

    A column that already holds words — "לקוחות" typed into a text column on a
    production board — becomes a connect column by matching each cell against
    one named field of one target board. Only an exact, unambiguous, visible
    match becomes a link; everything else is an exception a person resolves by
    hand, and until they have, the words that were in the cell have to survive
    somewhere. That is what this row and its cells are: the conversion is not
    finished at the moment it is applied, it is finished when the last cell
    nobody could match has been dealt with.

    `from_col` keeps the WHOLE column definition, not just its type — the
    options of a dropdown, the colours of a status, the number's unit. A revert
    has to put the board back as it was, and a type alone cannot do that.

    One target board per conversion even though a connect column may name
    several: "exactly one record carries this value" stops meaning anything
    once two boards are being searched at the same time.
    """
    __tablename__ = "column_conversions"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), index=True, nullable=False)
    col_id = Column(String(64), index=True, nullable=False)
    target_board_id = Column(Integer, ForeignKey("boards.id"), nullable=False)
    match_field = Column(String(80), nullable=False)      # "title" | a column id on the target board
    # The field to identify a record BY when the primary one is empty on it.
    # Measured need: the target board's "שם לקוח מלא" holds the source's exact
    # format and matches 436 of 476 cells outright — and is blank on 144 of
    # the 500 records, which the item's own name covers.
    match_field_fallback = Column(String(80), nullable=True)
    from_type = Column(String(30), nullable=False)        # the type the column was
    from_col = Column(JSON)                               # the whole definition, for the revert
    status = Column(String(20), default="open")           # open | closed | reverted
    # The columns this conversion CREATED on the target board — the counterpart
    # a two-way link needs somewhere to appear. Recorded rather than inferred
    # so a revert can take back exactly what the apply added: _ensure_mirrors
    # reuses an existing column where it finds one, and deleting a column
    # somebody already had is far worse than leaving an empty one behind.
    created_cols = Column(JSON)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)


class ColumnConversionCell(Base):
    """One item's original value, kept until its exception is dealt with.

    A row per NON-EMPTY cell, matched ones included. A matched cell has nothing
    for a person to do, but it still has an original: "שמור את הערכים המקוריים
    עד להשלמת הטיפול" is a promise about the whole board, and a revert that put
    back only the cells nobody could match would restore a board that never
    existed.

    An empty cell gets no row at all — there is nothing to keep and nothing to
    resolve, and a row per blank cell would make the exception list on a sparse
    column mostly blanks.
    """
    __tablename__ = "column_conversion_cells"
    id = Column(Integer, primary_key=True)
    conversion_id = Column(Integer, ForeignKey("column_conversions.id"), index=True, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    original = Column(JSON)        # the cell exactly as custom_fields held it
    words = Column(JSON)           # what it was read as, so the dialog can show it
    outcome = Column(String(20), nullable=False)    # matched | unmatched | ambiguous
    reason = Column(String(30))                     # no_match | partial | several | too_many_values
    candidates = Column(JSON)                       # [task_id, …] when ambiguous
    # What it was linked to, when matched. Both, because a cell can hold more
    # than one link and the scalar cannot say which of them died: a dropdown
    # reading ["עיריית חיפה", "רשות העתיקות"] becomes two links, and the
    # "a deleted record is listed again" guarantee has to hold when it is the
    # SECOND one that goes. The scalar is the first id and stays because it is
    # what the exception list reports; the list is what the liveness check and
    # the re-point read.
    linked_task_id = Column(Integer, nullable=True)
    linked_task_ids = Column(JSON)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)


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
    # ── what an automation's trail needs that an item's does not ──
    # Why it was done, where it was asked for — a system admin stepping over a
    # rule's conditions has to say, and the sentence belongs here rather than
    # buried in a run's reason text.
    reason = Column(Text, nullable=True)
    # The caller's address, stored ONLY where the organisation asked for it:
    # an address is personal data and most have not.
    ip = Column(String(45), nullable=True)
    # Which version of the rule this was done to, so a row can be placed in
    # the history rather than merely dated.
    version = Column(Integer, nullable=True)
    # "משתמש או שירות": a suspension nobody chose was not done by a person,
    # and writing a person's name against it would be a lie.
    actor_service = Column(String(40), nullable=True)
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
    # ── where an upload came from, when it came from a form ──
    # A respondent uploads before they send, so there is a window in which a
    # file exists and belongs to nothing. These two columns are what that
    # window is made of, and what keeps it from being a way in.
    #
    # `form_view_id` is the upload's CONTEXT: a token minted for this form and
    # for no other. Without it, a submission could name any token in this
    # table — an attachment off somebody's board, a file from another form —
    # and have it copied onto a new record. With it, the only files a
    # submission can claim are the ones that submission uploaded. NULL on
    # every ordinary attachment, which is what makes those unclaimable.
    #
    # `claimed_at` is when a submission took it. Set once: a file belongs to
    # one record, so replaying a token cannot attach the same upload twice.
    # NULL and old is what the sweeper collects — a form somebody abandoned.
    form_view_id = Column(Integer, ForeignKey("form_views.id"), nullable=True, index=True)
    claimed_at = Column(DateTime, nullable=True, index=True)
    # ── who uploaded it ──
    # A file is readable by whoever may see the item (or comment) it is
    # attached to — see _may_read_file. Between the upload and the save that
    # attaches it there is no such item yet, and the person composing still
    # has to see their own preview. This is that person. Not a foreign key:
    # removing a user must not be held up by every file they ever attached.
    # NULL on rows from before the column, and on public-form uploads.
    uploaded_by = Column(Integer, nullable=True)


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

# How many database connections the pool may hold open, and how many more it
# may borrow under load.
#
# SQLAlchemy's defaults are 5 + 10, which is BELOW the thread pool the server
# runs its synchronous endpoints on — so past fifteen concurrent requests the
# sixteenth waits for a connection rather than for work, and after thirty
# seconds it does not get slower, it FAILS: "QueuePool limit of size 5
# overflow 10 reached, connection timed out".
#
# That is how it was found. A dashboard load measurement at the twenty
# concurrent viewers DASH-28.2 names spent most of its time in that queue and
# then raised, which read as the dashboard being slow and was the pool being
# small. It was never specific to dashboards — any twenty people doing
# anything at once would have met it.
#
# Settable because the right number depends on the database: SQLite
# connections are nearly free, a managed Postgres has a ceiling of its own
# and the pool must stay under it.
DB_POOL_SIZE = int(os.getenv("CITYOS_DB_POOL_SIZE", "20"))
DB_POOL_OVERFLOW = int(os.getenv("CITYOS_DB_POOL_OVERFLOW", "40"))
DB_POOL_TIMEOUT = int(os.getenv("CITYOS_DB_POOL_TIMEOUT", "30"))


def init_db(db_url="sqlite:///cityos.db"):
    # pool_pre_ping keeps Postgres connections healthy across serverless cold
    # starts / idle drops; harmless for SQLite.
    engine = create_engine(db_url, echo=False, pool_pre_ping=True,
                           pool_size=DB_POOL_SIZE,
                           max_overflow=DB_POOL_OVERFLOW,
                           pool_timeout=DB_POOL_TIMEOUT)
    Base.metadata.create_all(engine)
    return engine


# ── 17.1: the specification's names for two tables that were already here ──
# Renaming a live table for a word is how a migration loses rows, so the names
# are bound to the classes instead. `AutomationExecution` IS `automation_runs`
# and `AutomationScheduledExecution` IS `automation_queue` — the same rows,
# reachable under either name.
AutomationExecution = AutomationRun
AutomationScheduledExecution = AutomationQueue
