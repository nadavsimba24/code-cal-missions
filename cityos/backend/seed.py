"""
CityOS — Seed Data for Demo
Creates a sample municipality with departments, boards, tasks, and GIS data.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from models import (
    Organization, Department, User, Board, Group, Task,
    Permit, CitizenRequest, PublicTransportStop, InfrastructureAsset,
    init_db, BoardType, TaskStatus, Priority,
    PermitType, CitizenRequestType
)

def seed_database(engine):
    with Session(engine) as session:
        # Check if already seeded
        if session.query(Organization).first():
            return

        # ── Municipality ────────────────────────────────────────────
        city = Organization(
            name="עיריית הוד השרון",
            slug="hod-hasharon",
            municipality_code="2420",
            address="דרך רמתיים 45, הוד השרון"
        )
        session.add(city)
        session.flush()

        # ── Departments ─────────────────────────────────────────────
        depts_data = [
            ("הנדסה ותשתיות", "eng", "#dc2626"),
            ("תחבורה", "trans", "#2563eb"),
            ("פיתוח עסקי", "biz", "#059669"),
            ("שירות לתושב", "citizen", "#d97706"),
            ("חינוך", "edu", "#7c3aed"),
            ("תברואה ואיכות סביבה", "env", "#0891b2"),
        ]
        depts = {}
        for name, code, color in depts_data:
            dept = Department(
                organization_id=city.id, name=name, code=code, color=color
            )
            session.add(dept)
            session.flush()
            depts[code] = dept

        # ── Users ───────────────────────────────────────────────────
        users_data = [
            ("admin@hodhasharon.gov.il", "משה כהן", "admin", "הנדסה ותשתיות"),
            ("rachel@hodhasharon.gov.il", "רחל לוי", "manager", "תחבורה"),
            ("dan@hodhasharon.gov.il", "דן מזרחי", "manager", "פיתוח עסקי"),
            ("sarah@hodhasharon.gov.il", "שרה ברק", "member", "שירות לתושב"),
            ("yossi@hodhasharon.gov.il", "יוסי אברהם", "member", "הנדסה ותשתיות"),
            ("noa@hodhasharon.gov.il", "נעה שטרן", "member", "תחבורה"),
            ("omer@hodhasharon.gov.il", "עומר גולן", "member", "תברואה ואיכות סביבה"),
        ]
        users = {}
        for email, name, role, dept_name in users_data:
            dept = session.query(Department).filter_by(name=dept_name).first()
            user = User(
                organization_id=city.id, department_id=dept.id,
                email=email, name=name, role=role
            )
            session.add(user)
            session.flush()
            users[name] = user

        # ── Boards ──────────────────────────────────────────────────
        boards_data = [
            ("פרויקטי תשתית", "הנדסה ותשתיות", "🏗️", BoardType.KANBAN, "#dc2626"),
            ("תחבורה ציבורית", "תחבורה", "🚌", BoardType.MAP, "#2563eb"),
            ("בקשות תושבים", "שירות לתושב", "📋", BoardType.KANBAN, "#d97706"),
            ("אישורי בנייה", "הנדסה ותשתיות", "📐", BoardType.FORM, "#7c3aed"),
            ("פיתוח עסקי בעיר", "פיתוח עסקי", "💼", BoardType.KANBAN, "#059669"),
            ("תחזוקת פארקים", "תברואה ואיכות סביבה", "🌳", BoardType.MAP, "#0891b2"),
            ("לוח שנה תשתיות", "הנדסה ותשתיות", "📅", BoardType.CALENDAR, "#6366f1"),
        ]
        boards = {}
        for name, dept_name, icon, btype, color in boards_data:
            dept = session.query(Department).filter_by(name=dept_name).first()
            board = Board(
                organization_id=city.id, department_id=dept.id,
                name=name, icon=icon, board_type=btype, color=color
            )
            session.add(board)
            session.flush()
            boards[name] = board

        # ── Groups (Columns) ────────────────────────────────────────
        groups_data = {
            "פרויקטי תשתית": [
                ("לתכנון", TaskStatus.BACKLOG, "#94a3b8"),
                ("בביצוע", TaskStatus.IN_PROGRESS, "#2563eb"),
                ("בסקירה", TaskStatus.REVIEW, "#d97706"),
                ("הושלם", TaskStatus.DONE, "#059669"),
            ],
            "בקשות תושבים": [
                ("חדש", TaskStatus.BACKLOG, "#ef4444"),
                ("בטיפול", TaskStatus.IN_PROGRESS, "#2563eb"),
                ("ממתין לאישור", TaskStatus.REVIEW, "#d97706"),
                ("טופל", TaskStatus.DONE, "#059669"),
            ],
            "אישורי בנייה": [
                ("טיוטה", TaskStatus.BACKLOG, "#94a3b8"),
                ("הוגש", TaskStatus.TODO, "#3b82f6"),
                ("בבדיקה", TaskStatus.IN_PROGRESS, "#f59e0b"),
                ("לאישור מהנדס", TaskStatus.REVIEW, "#8b5cf6"),
                ("מאושר", TaskStatus.DONE, "#059669"),
                ("נדחה", TaskStatus.CANCELLED, "#ef4444"),
            ],
            "תחבורה ציבורית": [
                ("מעקב", TaskStatus.IN_PROGRESS, "#2563eb"),
                ("מתוכנן", TaskStatus.BACKLOG, "#94a3b8"),
                ("הושלם", TaskStatus.DONE, "#059669"),
            ],
        }

        for board_name, cols in groups_data.items():
            board = boards.get(board_name)
            if not board:
                continue
            for i, (name, status, color) in enumerate(cols):
                group = Group(
                    board_id=board.id, name=name,
                    position=i, task_status=status, color=color
                )
                session.add(group)
                session.flush()
                # Store groups on board for reference
                if not hasattr(board, '_groups'):
                    board._groups = {}
                board._groups[name] = group

        # ── Tasks ───────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        tasks_data = [
            # Infrastructure projects
            {
                "board": "פרויקטי תשתית", "group": "בביצוע",
                "title": "שיקום כביש רמתיים — קטע מרכזי",
                "desc": "שיקום יסודי של קטע הכביש מרחוב הרצל עד צומת סוקולוב. כולל החלפת תשתיות תת-קרקעיות.",
                "priority": Priority.CRITICAL, "location": (34.8930, 32.1587),
                "assignees": ["יוסי אברהם"], "due": now + timedelta(days=45),
                "tags": ["כבישים", "תשתית", "דחוף"]
            },
            {
                "board": "פרויקטי תשתית", "group": "לתכנון",
                "title": "הקמת שביל אופניים — ציר ז'בוטינסקי",
                "desc": "תכנון שביל אופניים דו-כיווני לאורך רחוב ז'בוטינסקי, באורך 2.3 ק\"מ.",
                "priority": Priority.HIGH, "location": (34.8900, 32.1550),
                "assignees": ["משה כהן"], "due": now + timedelta(days=90),
                "tags": ["תחבורה", "אופניים", "תכנון"]
            },
            {
                "board": "פרויקטי תשתית", "group": "הושלם",
                "title": "חידוש תאורה — פארק גורדון",
                "desc": "החלפת 24 עמודי תאורה לפאנלים סולאריים בפארק ע\"ש גורדון.",
                "priority": Priority.MEDIUM, "location": (34.8860, 32.1600),
                "assignees": ["יוסי אברהם"], "due": now - timedelta(days=5),
                "tags": ["תאורה", "פארק", "סולארי"]
            },
            # Citizen requests
            {
                "board": "בקשות תושבים", "group": "חדש",
                "title": "בור בכביש — רחוב העצמאות 12",
                "desc": "בור בעומק 15 ס\"מ ליד מעבר חציה. סיכון להולכי רגל.",
                "priority": Priority.EMERGENCY, "location": (34.8950, 32.1530),
                "tags": ["כבישים", "בטיחות", "דחוף"]
            },
            {
                "board": "בקשות תושבים", "group": "בטיפול",
                "title": "פנס רחוב לא עובד — רחוב הנרקיסים",
                "desc": "פנס רחוב מספר 14-22 לא דולק כבר שבוע. רחוב חשוך.",
                "priority": Priority.HIGH, "location": (34.8880, 32.1620),
                "assignees": ["שרה ברק"], "tags": ["תאורה", "רחוב"]
            },
            {
                "board": "בקשות תושבים", "group": "טופל",
                "title": "גינה ציבורית — ניקוי פסולת",
                "desc": "דווח על הצטברות פסולת בגינה הציבורית ברחוב השושנים.",
                "priority": Priority.LOW, "location": (34.8850, 32.1570),
                "assignees": ["שרה ברק"],
                "tags": ["גינה", "ניקיון"]
            },
            # Building permits
            {
                "board": "אישורי בנייה", "group": "בבדיקה",
                "title": "היתר הרחבה — רחוב הארזים 8",
                "desc": "בקשה להרחבת דירת גג בשטח 65 מ\"ר. כולל תוכניות הנדסיות.",
                "priority": Priority.MEDIUM, "location": (34.8910, 32.1605),
                "assignees": ["משה כהן"], "due": now + timedelta(days=21),
                "tags": ["הרחבה", "גג"]
            },
            {
                "board": "אישורי בנייה", "group": "מאושר",
                "title": "היתר שינוי ייעוד — מסעדה ברחוב המרכזי",
                "desc": "שינוי ייעוד מקומפרסיה למסעדה. אושר על ידי הוועדה.",
                "priority": Priority.MEDIUM,
                "assignees": ["משה כהן"],
                "tags": ["מסעדה", "שינוי ייעוד"]
            },
            # Business development
            {
                "board": "פיתוח עסקי בעיר", "group": "לביצוע",
                "title": "יריד עסקים שנתי 2026",
                "desc": "ארגון יריד העסקים העירוני בגני התערוכה. צפויים 50+ מציגים.",
                "priority": Priority.HIGH,
                "assignees": ["דן מזרחי"], "due": now + timedelta(days=60),
                "tags": ["יריד", "עסקים", "אירוע"]
            },
        ]

        board_groups_cache = {}
        for t in tasks_data:
            bname = t["board"]
            gname = t["group"]
            board = boards[bname]
            cache_key = f"{bname}:{gname}"
            if cache_key not in board_groups_cache:
                grp = session.query(Group).join(Board).filter(
                    Board.name == bname, Group.name == gname
                ).first()
                board_groups_cache[cache_key] = grp

            grp = board_groups_cache[cache_key]
            # Infer status from group
            inferred_status = grp.task_status if grp else TaskStatus.TODO
            task = Task(
                board_id=board.id,
                group_id=grp.id if grp else None,
                title=t["title"],
                description=t.get("desc", ""),
                status=t.get("status", inferred_status),
                priority=t.get("priority", Priority.MEDIUM),
                position=0,
                due_date=t.get("due"),
                location_lat=t.get("location", [None, None])[1] if t.get("location") else None,
                location_lng=t.get("location", [None, None])[0] if t.get("location") else None,
                tags=t.get("tags", []),
                created_by=users.get(t.get("assignees", [None])[0], users["משה כהן"]).id if t.get("assignees") else users["משה כהן"].id,
            )
            session.add(task)
            session.flush()

            # Add assignees
            for assignee_name in t.get("assignees", []):
                user = users.get(assignee_name)
                if user:
                    task.assignees.append(user)

        # ── Permits ─────────────────────────────────────────────────
        permits = [
            Permit(
                organization_id=city.id, permit_type=PermitType.BUILDING,
                permit_number="B-2026-00142",
                applicant_name="אברהם שלום",
                applicant_phone="050-1234567",
                property_address="הארזים 8, הוד השרון",
                property_gush="6622", property_helka="85",
                description="הרחבת דירת גג 65 מ\"ר",
                status="in_review", assigned_to=users["משה כהן"].id,
                submitted_at=now - timedelta(days=14),
            ),
            Permit(
                organization_id=city.id, permit_type=PermitType.BUSINESS,
                permit_number="B-2026-00089",
                applicant_name="רותי ירקוני",
                applicant_phone="054-9876543",
                property_address="המרכזי 22, הוד השרון",
                description="רישיון עסק למסעדה",
                status="approved", assigned_to=users["משה כהן"].id,
                submitted_at=now - timedelta(days=30),
                decided_at=now - timedelta(days=2),
                decision_notes="מאושר בתנאים: שערי אוורור, גלאי עשן",
            ),
        ]
        session.add_all(permits)

        # ── Citizen Requests ─────────────────────────────────────────
        citizen_reqs = [
            CitizenRequest(
                organization_id=city.id, request_type=CitizenRequestType.ROAD_ISSUE,
                citizen_name="ישראל ישראלי", citizen_phone="052-1112233",
                title="בור בכביש רחוב העצמאות",
                description="בור עמוק ליד מעבר חציה. מסוכן לילדים.",
                location_lat=32.1530, location_lng=34.8950,
                address="רחוב העצמאות 12, הוד השרון",
                status="in_progress", priority=Priority.EMERGENCY,
                assigned_to=users["יוסי אברהם"].id,
                created_at=now - timedelta(hours=3),
            ),
            CitizenRequest(
                organization_id=city.id, request_type=CitizenRequestType.STREET_LIGHT,
                citizen_name="מיכל כהן", citizen_phone="054-7654321",
                title="תאורה ברחוב הנרקיסים",
                description="3 פנסים לא דולקים. רחוב חשוך לגמרי.",
                location_lat=32.1620, location_lng=34.8880,
                address="רחוב הנרקיסים, הוד השרון",
                status="assigned", priority=Priority.HIGH,
                assigned_to=users["שרה ברק"].id,
                created_at=now - timedelta(days=2),
            ),
        ]
        session.add_all(citizen_reqs)

        # ── Public Transport Stops (SIRI) ────────────────────────────
        stops = [
            PublicTransportStop(
                organization_id=city.id, stop_code="31303",
                name="א.ד. גורדון/בן גוריון",
                latitude=32.15870, longitude=34.88452,
                routes=["1", "2", "3", "4", "47", "50"],
            ),
            PublicTransportStop(
                organization_id=city.id, stop_code="31304",
                name="בן גוריון/השיקמים",
                latitude=32.15885, longitude=34.88646,
                routes=["1", "2", "5", "47"],
            ),
            PublicTransportStop(
                organization_id=city.id, stop_code="31305",
                name="עיריית הוד השרון/דרך רמתיים",
                latitude=32.15658, longitude=34.89070,
                routes=["3", "4", "5", "6", "50", "142"],
            ),
            PublicTransportStop(
                organization_id=city.id, stop_code="31306",
                name="דרך מגדיאל/אשכול",
                latitude=32.15382, longitude=34.89828,
                routes=["1", "3", "6", "50", "142"],
            ),
        ]
        session.add_all(stops)

        # ── Infrastructure Assets ────────────────────────────────────
        assets = [
            InfrastructureAsset(
                organization_id=city.id, asset_type="park",
                name="פארק עירוני גורדון",
                location_lat=32.1600, location_lng=34.8860,
                condition="good", status="active",
                properties={"area_sqm": 8500, "playgrounds": 2, "benches": 34}
            ),
            InfrastructureAsset(
                organization_id=city.id, asset_type="road",
                name="דרך רמתיים (כביש ראשי)",
                location_lat=32.1565, location_lng=34.8907,
                condition="fair", status="active",
                properties={"length_km": 3.2, "lanes": 4, "last_repair": "2023-04"}
            ),
            InfrastructureAsset(
                organization_id=city.id, asset_type="street_light",
                name="תאורת רחוב — רחוב הרצל",
                location_lat=32.1550, location_lng=34.8930,
                condition="poor", status="maintenance_needed",
                properties={"count": 18, "type": "LED", "install_year": 2015}
            ),
        ]
        session.add_all(assets)

        session.commit()
        print(f"✅ CityOS seeded: {city.name}")
        print(f"   Departments: {len(depts)}")
        print(f"   Users: {len(users)}")
        print(f"   Boards: {len(boards)}")
        print(f"   Tasks: {len(tasks_data)}")
        print(f"   Permits: {len(permits)}")
        print(f"   Citizen Requests: {len(citizen_reqs)}")
        print(f"   Transport Stops: {len(stops)}")
        print(f"   Infrastructure Assets: {len(assets)}")

def seed_work_plan(engine):
    """Seed work plan & budget data (runs even if DB already seeded)."""

def seed_work_plan(engine):
    """Seed work plan & budget data (runs even if DB already seeded)."""
    from models import (
        AnnualWorkPlan, Project, ProjectStep, BudgetLineItem,
        Approval, ChangeRequest, KPI, Dependency, Document, AuditLog,
        ProjectStatus, ApprovalStatus, ChangeRequestStatus, DependencyType,
        BudgetItemType, DocumentType, Priority, Task, Organization, Department, User
    )
    from datetime import datetime, timezone, timedelta
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        city = session.query(Organization).first()
        if not city:
            print("⚠️  No organization found, skipping work plan seeding")
            return

        # 1. Annual Work Plan
        wp = session.query(AnnualWorkPlan).filter_by(name="תוכנית עבודה 2026", year=2026).first()
        if not wp:
            wp = AnnualWorkPlan(
                organization_id=city.id,
                name="תוכנית עבודה 2026",
                year=2026,
                total_budget=250_000_000,
                strategic_goals=[
                    "שיפור חזות העיר",
                    "הגדלת הכנסות",
                    "שיפור שירות לתושב",
                    "קיימות ואיכות סביבה"
                ],
                municipal_kpis=[
                    {"name": "שביעות רצון תושבים", "target": 85, "unit": "%"},
                    {"name": "הכנסות עירייה", "target": 300_000_000, "unit": "₪"},
                    {"name": "פרויקטים שהושלמו", "target": 120, "unit": "יחידות"}
                ],
                overall_status="active",
            )
            session.add(wp)
            session.flush()

        # 2. Update Departments with work plan, budget, manager
        dept_updates = {
            "הנדסה ותשתיות": {"annual_budget": 50_000_000, "manager": "יוסי כהן", "planned": 42, "completed": 18},
            "תחבורה": {"annual_budget": 25_000_000, "manager": "אילן אברהם", "planned": 30, "completed": 14},
            "פיתוח עסקי": {"annual_budget": 15_000_000, "manager": "רונית דהן", "planned": 10, "completed": 5},
            "שירות לתושב": {"annual_budget": 20_000_000, "manager": "שרה ברק", "planned": 15, "completed": 8},
            "חינוך": {"annual_budget": 30_000_000, "manager": "מיכל לוי", "planned": 22, "completed": 10},
            "תברואה ואיכות סביבה": {"annual_budget": 40_000_000, "manager": "אבי טל", "planned": 30, "completed": 14},
        }
        for dept_name, vals in dept_updates.items():
            d = session.query(Department).filter_by(name=dept_name).first()
            if d and not d.work_plan_id:
                d.work_plan_id = wp.id
                d.annual_budget = vals["annual_budget"]
                d.manager_name = vals["manager"]
                d.planned_projects = vals["planned"]
                d.completed_projects = vals["completed"]
        session.flush()

        def get_user(name):
            return session.query(User).filter(User.name == name).first()

        def get_dept(name):
            return session.query(Department).filter(Department.name == name).first()

        def make_project(name, dept_name, manager_name, planned, approved, actual, progress, status, priority, start_date, end_date):
            existing = session.query(Project).filter_by(name=name).first()
            if existing:
                return existing
            dept = get_dept(dept_name)
            mgr = get_user(manager_name) if manager_name else None
            try:
                p_status = ProjectStatus(status)
            except ValueError:
                p_status = ProjectStatus.IN_PROGRESS
            try:
                p_priority = Priority(priority)
            except ValueError:
                p_priority = Priority.MEDIUM
            p = Project(
                work_plan_id=wp.id,
                department_id=dept.id if dept else None,
                name=name,
                manager_id=mgr.id if mgr else None,
                planned_budget=planned,
                approved_budget=approved,
                actual_budget=actual,
                progress_percentage=progress,
                status=p_status,
                priority=p_priority,
                start_date=start_date,
                end_date=end_date,
            )
            session.add(p)
            session.flush()
            return p

        def make_step(project, name, position, progress, owner_name=None, start=None, end=None, status="pending"):
            s = ProjectStep(
                project_id=project.id, name=name, position=position,
                progress=progress, owner_id=get_user(owner_name).id if owner_name else None,
                start_date=start, end_date=end,
                status=status,
            )
            session.add(s)
            session.flush()
            return s

        def make_budget_item(project, item_type, name, planned, approved, actual):
            try:
                bit = BudgetItemType(item_type)
            except ValueError:
                bit = BudgetItemType.OTHER
            bi = BudgetLineItem(
                project_id=project.id, item_type=bit, name=name,
                planned_amount=planned, approved_amount=approved, actual_amount=actual,
            )
            session.add(bi)

        def make_kpi(project, name, target, actual, unit):
            existing = session.query(KPI).filter(
                KPI.project_id == project.id, KPI.name == name
            ).first()
            if not existing:
                session.add(KPI(
                    project_id=project.id, name=name,
                    target=target, actual=actual, unit=unit,
                ))

        now = datetime.now(timezone.utc)
        d5 = timedelta(days=5)
        d10 = timedelta(days=10)
        d15 = timedelta(days=15)
        d20 = timedelta(days=20)
        d25 = timedelta(days=25)
        d30 = timedelta(days=30)
        d35 = timedelta(days=35)
        d40 = timedelta(days=40)
        d45 = timedelta(days=45)
        d50 = timedelta(days=50)
        d60 = timedelta(days=60)
        d75 = timedelta(days=75)
        d90 = timedelta(days=90)
        d120 = timedelta(days=120)

        # ── 3. Projects ──
        # הנדסה
        p1 = make_project(
            "שיקום כביש התחמים", "הנדסה ותשתיות", "יוסי אברהם",
            2_000_000, 1_850_000, 1_200_000, 72, "in_progress", "high",
            now - d60, now + d30
        )
        for (name, pos, prog, owner, start, end, sta) in [
            ("תכנון", 1, 100, "משה כהן", now - d60, now - d50, "completed"),
            ("מכרז", 2, 100, "יוסי אברהם", now - d50, now - d35, "completed"),
            ("אישור תקציבי", 3, 100, "משה כהן", now - d35, now - d25, "completed"),
            ("ביצוע", 4, 60, "יוסי אברהם", now - d25, now + d15, "in_progress"),
            ("מסירה", 5, 0, "יוסי אברהם", now + d15, now + d30, "pending"),
        ]:
            make_step(p1, name, pos, prog, owner, start, end, sta)

        p2 = make_project(
            "הקמת גן ציבורי שכונת רמות", "הנדסה ותשתיות", "יוסי אברהם",
            1_500_000, 1_400_000, 600_000, 42, "in_progress", "high",
            now - d45, now + d45
        )
        for (name, pos, prog, owner, start, end, sta) in [
            ("תכנון נופי", 1, 100, "משה כהן", now - d45, now - d30, "completed"),
            ("מכרז גינון", 2, 100, "יוסי אברהם", now - d30, now - d15, "completed"),
            ("הקמה", 3, 30, "יוסי אברהם", now - d15, now + d30, "in_progress"),
            ("נטיעות", 4, 0, None, now + d30, now + d45, "pending"),
        ]:
            make_step(p2, name, pos, prog, owner, start, end, sta)

        p3 = make_project(
            "תכנון מרכז תחבורה חדש", "הנדסה ותשתיות", "משה כהן",
            3_000_000, 2_800_000, 0, 10, "planning", "medium",
            now, now + d90
        )
        for (name, pos, prog, owner, start, end, sta) in [
            ("סקר היתכנות", 1, 40, "משה כהן", now, now + d20, "in_progress"),
            ("תכנון ראשוני", 2, 0, None, now + d20, now + d50, "pending"),
        ]:
            make_step(p3, name, pos, prog, owner, start, end, sta)

        # תחבורה
        p4 = make_project(
            "שדרוג תאורת רחוב עירונית", "תחבורה", "נעה שטרן",
            1_800_000, 1_600_000, 1_500_000, 92, "in_progress", "high",
            now - d60, now - d5
        )
        for (name, pos, prog, owner, start, end, sta) in [
            ("סקר תאורה קיימת", 1, 100, "נעה שטרן", now - d60, now - d50, "completed"),
            ("מכרז תאורה", 2, 100, "רחל לוי", now - d50, now - d35, "completed"),
            ("התקנה", 3, 95, "נעה שטרן", now - d35, now - d10, "in_progress"),
            ("בדיקות", 4, 80, "רחל לוי", now - d10, now - d5, "in_progress"),
        ]:
            make_step(p4, name, pos, prog, owner, start, end, sta)

        p5 = make_project(
            "הקמת שבילי אופניים", "תחבורה", "רחל לוי",
            900_000, 850_000, 200_000, 24, "in_progress", "medium",
            now - d30, now + d45
        )
        for (name, pos, prog, owner, start, end, sta) in [
            ("תכנון מסלולים", 1, 100, "רחל לוי", now - d30, now - d15, "completed"),
            ("מכרז", 2, 60, None, now - d15, now + d5, "in_progress"),
            ("סלילה", 3, 0, None, now + d5, now + d40, "pending"),
        ]:
            make_step(p5, name, pos, prog, owner, start, end, sta)

        p6 = make_project(
            "פינוי מפגעים עירוני", "תחבורה", "נעה שטרן",
            500_000, 500_000, 500_000, 100, "completed", "low",
            now - d90, now - d10
        )
        for (name, pos, prog, owner, start, end, sta) in [
            ("איתור מפגעים", 1, 100, "נעה שטרן", now - d90, now - d75, "completed"),
            ("ביצוע פינוי", 2, 100, "נעה שטרן", now - d75, now - d15, "completed"),
            ("דיווח", 3, 100, None, now - d15, now - d10, "completed"),
        ]:
            make_step(p6, name, pos, prog, owner, start, end, sta)

        # Other departments
        p7 = make_project(
            "שיפוץ בית ספר יסודי ארזים", "חינוך", None,
            2_500_000, 2_300_000, 800_000, 35, "in_progress", "high",
            now - d30, now + d60
        )
        p8 = make_project(
            "הקמת ספרייה עירונית חדשה", "חינוך", None,
            4_000_000, 3_500_000, 0, 5, "planning", "medium",
            now, now + d120
        )
        p9 = make_project(
            "דיגיטציית שירות לתושב", "שירות לתושב", "שרה ברק",
            1_200_000, 1_100_000, 400_000, 38, "in_progress", "high",
            now - d45, now + d30
        )
        p10 = make_project(
            "הנגשת מבני ציבור", "שירות לתושב", "שרה ברק",
            800_000, 750_000, 750_000, 100, "completed", "medium",
            now - d90, now - d5
        )
        p11 = make_project(
            "שוק אוכל רחוב עירוני", "פיתוח עסקי", "דן מזרחי",
            600_000, 550_000, 200_000, 45, "in_progress", "medium",
            now - d30, now + d30
        )
        p12 = make_project(
            "תוכנית עידוד עסקים קטנים", "פיתוח עסקי", "דן מזרחי",
            1_000_000, 1_000_000, 1_000_000, 100, "completed", "low",
            now - d120, now - d15
        )
        p13 = make_project(
            "מערכת מיחזור עירונית", "תברואה ואיכות סביבה", "עומר גולן",
            1_800_000, 1_700_000, 600_000, 35, "in_progress", "high",
            now - d45, now + d45
        )
        p14 = make_project(
            "טיפול בשפכים תעשייתיים", "תברואה ואיכות סביבה", "עומר גולן",
            3_500_000, 3_200_000, 3_000_000, 88, "in_progress", "critical",
            now - d90, now + d20
        )

        # ── 4. Budget Items ──
        budget_data = [
            (p1, "contractor", "קבלן ראשי", 1_200_000, 1_100_000, 800_000),
            (p1, "supervision", "פיקוח", 150_000, 150_000, 90_000),
            (p1, "equipment", "ציוד", 200_000, 180_000, 120_000),
            (p1, "procurement", "רכש", 200_000, 180_000, 100_000),
            (p1, "planning", "תכנון", 250_000, 240_000, 90_000),
            (p2, "contractor", "קבלן גינון", 700_000, 650_000, 300_000),
            (p2, "supervision", "פיקוח", 100_000, 100_000, 50_000),
            (p2, "equipment", "ציוד גן", 400_000, 380_000, 150_000),
            (p2, "planning", "תכנון", 300_000, 270_000, 100_000),
            (p3, "planning", "תכנון", 1_500_000, 1_400_000, 0),
            (p3, "supervision", "פיקוח", 500_000, 500_000, 0),
            (p3, "procurement", "רכש", 1_000_000, 900_000, 0),
            (p4, "contractor", "קבלן תאורה", 1_000_000, 900_000, 850_000),
            (p4, "equipment", "עמודי תאורה", 500_000, 450_000, 420_000),
            (p4, "supervision", "פיקוח", 150_000, 120_000, 110_000),
            (p4, "planning", "תכנון", 150_000, 130_000, 120_000),
            (p5, "planning", "תכנון", 300_000, 280_000, 100_000),
            (p5, "procurement", "רכש", 400_000, 380_000, 80_000),
            (p5, "supervision", "פיקוח", 200_000, 190_000, 20_000),
            (p7, "contractor", "קבלן שיפוץ", 1_500_000, 1_400_000, 500_000),
            (p7, "equipment", "ציוד", 600_000, 550_000, 200_000),
            (p7, "supervision", "פיקוח", 400_000, 350_000, 100_000),
            (p8, "planning", "תכנון", 2_000_000, 1_800_000, 0),
            (p8, "procurement", "רכש", 2_000_000, 1_700_000, 0),
            (p9, "planning", "תכנון מערכות", 400_000, 380_000, 150_000),
            (p9, "procurement", "ציוד מחשוב", 600_000, 550_000, 200_000),
            (p9, "other", "הטמעה", 200_000, 170_000, 50_000),
            (p13, "equipment", "מכלים ותחנות", 1_000_000, 950_000, 350_000),
            (p13, "planning", "תכנון", 500_000, 480_000, 150_000),
            (p13, "supervision", "פיקוח", 300_000, 270_000, 100_000),
            (p14, "contractor", "קבלן טיהור", 2_000_000, 1_900_000, 1_800_000),
            (p14, "equipment", "ציוד טיהור", 1_000_000, 900_000, 850_000),
            (p14, "supervision", "פיקוח", 500_000, 400_000, 350_000),
        ]
        for proj, itype, name, planned, approved, actual in budget_data:
            existing = session.query(BudgetLineItem).filter(
                BudgetLineItem.project_id == proj.id,
                BudgetLineItem.name == name
            ).first()
            if not existing:
                make_budget_item(proj, itype, name, planned, approved, actual)

        # ── 5. Approvals ──
        approval_chains = [
            (p1, [("מנהל מחלקה", "approved", "משה כהן"),
                  ("מנהל אגף", "approved", "יוסי אברהם"),
                  ("גזבר", "approved", None),
                  ("מנכ\"ל", "pending", None),
                  ("ראש רשות", "pending", None)]),
            (p2, [("מנהל מחלקה", "approved", "משה כהן"),
                  ("מנהל אגף", "approved", "יוסי אברהם"),
                  ("גזבר", "approved", None),
                  ("מנכ\"ל", "pending", None),
                  ("ראש רשות", "pending", None)]),
            (p4, [("מנהל מחלקה", "approved", "רחל לוי"),
                  ("מנהל אגף", "approved", None),
                  ("גזבר", "approved", None),
                  ("מנכ\"ל", "approved", None)]),
            (p6, [("מנהל מחלקה", "approved", "רחל לוי"),
                  ("מנהל אגף", "approved", None),
                  ("גזבר", "approved", None),
                  ("מנכ\"ל", "approved", None),
                  ("ראש רשות", "approved", None)]),
            (p7, [("מנהל מחלקה", "approved", None),
                  ("מנהל אגף", "approved", None),
                  ("גזבר", "pending", None)]),
            (p14, [("מנהל מחלקה", "approved", "עומר גולן"),
                   ("מנהל אגף", "approved", None),
                   ("גזבר", "approved", None),
                   ("מנכ\"ל", "pending", None)]),
        ]
        for proj, approvers in approval_chains:
            for i, (role, status, user_name) in enumerate(approvers):
                existing = session.query(Approval).filter(
                    Approval.entity_type == "project",
                    Approval.entity_id == proj.id,
                    Approval.approver_role == role
                ).first()
                if existing:
                    continue
                try:
                    st = ApprovalStatus(status)
                except ValueError:
                    st = ApprovalStatus.PENDING
                session.add(Approval(
                    entity_type="project", entity_id=proj.id,
                    approver_role=role, status=st, step_order=i,
                    approver_user_id=(get_user(user_name) or type('',(),{'id':None})()).id if user_name else None,
                    approved_at=datetime.now(timezone.utc) if status == "approved" else None,
                ))

        # ── 6. KPIs ──
        kpi_data = [
            (p1, "שיקום כבישים (ק\"מ)", 5, 4.2, "קמ"),
            (p4, "עמודי תאורה שהוחלפו", 200, 185, "יחידות"),
            (p2, "גנים ציבוריים שהוקמו", 1, 0.4, "יחידות"),
            (p9, "טופסים דיגיטליים", 50, 19, "יחידות"),
            (p13, "תחנות מיחזור", 15, 5, "יחידות"),
            (p14, "אחוז טיפול בשפכים", 100, 88, "%"),
        ]
        for proj, name, target, actual, unit in kpi_data:
            make_kpi(proj, name, target, actual, unit)

        # ── 7. Change Requests ──
        if not session.query(ChangeRequest).first():
            session.add(ChangeRequest(
                project_id=p1.id,
                title="עדכון תקציב שיקום כביש התחמים",
                description="התייקרות חומרי גלם בשוק",
                amount_change=300_000,
                reason="התייקרות חומרי גלם",
                status=ChangeRequestStatus.SUBMITTED,
                requested_by=get_user("יוסי אברהם").id if get_user("יוסי אברהם") else None,
            ))
            session.add(ChangeRequest(
                project_id=p4.id,
                title="תוספת עמודי תאורה",
                description="בקשה לתוספת 15 עמודי תאורה בשכונת רמות",
                amount_change=150_000,
                reason="תוספת עמודי תאורה",
                status=ChangeRequestStatus.APPROVED,
                requested_by=get_user("נעה שטרן").id if get_user("נעה שטרן") else None,
                approved_by=get_user("רחל לוי").id if get_user("רחל לוי") else None,
                approved_at=now - timedelta(days=10),
            ))

        # ── 8. Dependencies ──
        if not session.query(Dependency).first():
            session.add(Dependency(
                source_type="project", source_id=p1.id,
                target_type="project", target_id=p5.id,
                dependency_type=DependencyType.FINISH_TO_START,
                lag_days=7,
            ))
            session.add(Dependency(
                source_type="project", source_id=p3.id,
                target_type="project", target_id=p1.id,
                dependency_type=DependencyType.FINISH_TO_START,
            ))

        # ── 9. Documents ──
        if not session.query(Document).first():
            doc_data = [
                (p1, "tender", "מכרז שיקום כבישים 2026", "מסמכי מכרז מלאים לשיקום כביש התחמים", "משה כהן"),
                (p1, "agreement", "הסכם קבלן ראשי", "הסכם עם קבלן השיקום", "משה כהן"),
                (p1, "plans", "תכניות הנדסיות", "תכניות ביצוע הנדסיות מאושרות", "יוסי אברהם"),
                (p4, "plans", "מפרט טכני תאורה", "מפרט טכני לעמודי תאורה מסוג LED", "רחל לוי"),
                (p4, "agreement", "הסכם תחזוקה", "הסכם תחזוקה שנתי מול קבלן תאורה", "רחל לוי"),
            ]
            for proj, doc_type, name, desc, uploader_name in doc_data:
                try:
                    dt = DocumentType(doc_type)
                except ValueError:
                    dt = DocumentType.OTHER
                uploader = get_user(uploader_name)
                session.add(Document(
                    project_id=proj.id, document_type=dt,
                    name=name, description=desc,
                    uploaded_by=uploader.id if uploader else None,
                ))

        # ── 10. Audit Log ──
        if not session.query(AuditLog).first():
            audit_data = [
                ("work_plan", wp.id, "create", "name", "תוכנית עבודה 2026", None),
                ("project", p1.id, "create", "name", p1.name, None),
                ("project", p4.id, "create", "name", p4.name, None),
                ("project", p1.id, "update", "status", "in_progress", "draft"),
                ("project", p6.id, "update", "status", "completed", "in_progress"),
                ("project", p1.id, "update", "budget", "1,850,000 ₪", "2,000,000 ₪"),
                ("approval.project", p1.id, "approve", "מנהל מחלקה", "approved", None),
                ("approval.project", p1.id, "approve", "מנהל אגף", "approved", None),
                ("approval.project", p1.id, "approve", "גזבר", "approved", None),
            ]
            for e_type, e_id, action, field, new_val, old_val in audit_data:
                session.add(AuditLog(
                    entity_type=e_type, entity_id=e_id,
                    action=action, field_name=field,
                    new_value=str(new_val) if new_val else None,
                    old_value=str(old_val) if old_val else None,
                ))

        session.commit()
        print(f"✅ Work Plan & Budget seeded:")
        print(f"   Projects: {session.query(Project).count()}")
        print(f"   Budget Line Items: {session.query(BudgetLineItem).count()}")
        print(f"   Approvals: {session.query(Approval).count()}")
        print(f"   KPIs: {session.query(KPI).count()}")
        print(f"   Change Requests: {session.query(ChangeRequest).count()}")
        print(f"   Dependencies: {session.query(Dependency).count()}")
        print(f"   Documents: {session.query(Document).count()}")
