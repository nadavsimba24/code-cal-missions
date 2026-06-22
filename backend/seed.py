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
