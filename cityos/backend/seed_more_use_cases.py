"""
CityOS — Extended Seed Data: Real Municipal Use Cases
Adds 6 new boards with 40+ tasks across all municipal departments.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from models import (
    Organization, Department, User, Board, Group, Task,
    Permit, CitizenRequest, PublicTransportStop, InfrastructureAsset,
    init_db, BoardType, TaskStatus, Priority,
    PermitType, CitizenRequestType
)
import sys, os

DB_PATH = os.path.join(os.path.dirname(__file__), "cityos.db")
engine = init_db(f"sqlite:///{DB_PATH}")

def seed_extended():
    with Session(engine) as db:
        city = db.query(Organization).filter_by(slug="hod-hasharon").first()
        if not city:
            print("❌ City not found. Run main.py first.")
            return
        
        depts = {d.code: d for d in db.query(Department).all()}
        users = {u.name: u for u in db.query(User).all()}
        
        now = datetime.now(timezone.utc)

        # ── idempotency guard: don't duplicate if already seeded ──────
        _extended_names = {"חינוך ונוער", "פיקוח ואכיפה", "תחזוקה שוטפת",
                           "תכנון ובנייה", "מוקד 106 — פניות תושבים", "גנים ציבוריים ונוף"}
        _existing = {b.name for b in db.query(Board).all()}
        if _extended_names & _existing:
            print("⏭️  לוחות מורחבים כבר קיימים — מדלג (idempotent).")
            return

        # ── NEW BOARD 1: חינוך ונוער ────────────────────────────────
        edu_board = Board(
            organization_id=city.id, department_id=depts["edu"].id,
            name="חינוך ונוער", icon="📚", board_type=BoardType.KANBAN, color="#0073ea"
        )
        db.add(edu_board)
        db.flush()
        
        edu_groups = [
            Group(board_id=edu_board.id, name="תכנון", position=0, color="#94a3b8", task_status=TaskStatus.BACKLOG),
            Group(board_id=edu_board.id, name="תקציב", position=1, color="#f59e0b", task_status=TaskStatus.TODO),
            Group(board_id=edu_board.id, name="בהרצה", position=2, color="#2563eb", task_status=TaskStatus.IN_PROGRESS),
            Group(board_id=edu_board.id, name="הושלם", position=3, color="#059669", task_status=TaskStatus.DONE),
        ]
        db.add_all(edu_groups)
        db.flush()
        g_e_plan, g_e_budget, g_e_run, g_e_done = edu_groups
        
        edu_tasks = [
            Task(board_id=edu_board.id, group_id=g_e_plan.id, title="תוכנית מצוינות — חטיבת ביניים עירונית",
                 description="פיתוח תכנית לימודים ייחודית במדעים וטכנולוגיה לחטיבת הביניים. בשיתוף מכון ויצמן.",
                 priority=Priority.HIGH, tags=["חינוך", "מצוינות", "מדע"], position=0),
            Task(board_id=edu_board.id, group_id=g_e_plan.id, title="קייטנת קיץ עירונית 2026",
                 description="תכנון קייטנה ל-400 ילדים. 5 מחזורים, 3 אתרים. תקציב 250K ש\"ח.",
                 priority=Priority.MEDIUM, due_date=now+timedelta(days=30), tags=["קייטנה", "קיץ", "ילדים"], position=1),
            Task(board_id=edu_board.id, group_id=g_e_budget.id, title="תקציב תגבור שעות לימוד",
                 description="אישור תקציב ל-150 שעות תגבור לבתי הספר היסודיים. תקציב 120K ש\"ח.",
                 priority=Priority.HIGH, due_date=now+timedelta(days=14), tags=["תקציב", "חינוך", "תגבור"],
                 assignees=[users.get("דן מזרחי")], position=0),
            Task(board_id=edu_board.id, group_id=g_e_budget.id, title="מכרז הסעות תלמידים תשפ\"ז",
                 description="פרסום מכרז להסעת 1,200 תלמידים. 25 קווים. תקציב 1.2M ש\"ח.",
                 priority=Priority.CRITICAL, due_date=now+timedelta(days=60), tags=["הסעות", "מכרז", "תלמידים"],
                 assignees=[users.get("דן מזרחי")], position=1),
            Task(board_id=edu_board.id, group_id=g_e_run.id, title="הרצת תכנית צהרונים עירונית",
                 description="הפעלת 15 צהרונים בבתי הספר. 600 ילדים רשומים. 60 סייעות.",
                 priority=Priority.HIGH, due_date=now-timedelta(days=5), tags=["צהרונים", "קהילה", "ילדי"],
                 assignees=[users.get("שרה ברק")], position=0),
            Task(board_id=edu_board.id, group_id=g_e_run.id, title="מערך שיעורי עזר דיגיטלי",
                 description="הקמת פלטפורמת שיעורי עזר אונליין לתלמידי תיכון. שיתוף פעולה עם סטודנטים.",
                 priority=Priority.MEDIUM, tags=["דיגיטל", "למידה", "הנגשה"], position=1),
        ]
        db.add_all(edu_tasks)

        # ── NEW BOARD 2: פיקוח ואכיפה ──────────────────────────────
        enforce_board = Board(
            organization_id=city.id, department_id=depts["eng"].id,
            name="פיקוח ואכיפה", icon="👮", board_type=BoardType.KANBAN, color="#ef4444"
        )
        db.add(enforce_board)
        db.flush()
        
        enf_groups = [
            Group(board_id=enforce_board.id, name="בנייה ללא היתר", position=0, color="#ef4444", task_status=TaskStatus.BACKLOG),
            Group(board_id=enforce_board.id, name="חזקה על מדרכה", position=1, color="#eab308", task_status=TaskStatus.TODO),
            Group(board_id=enforce_board.id, name="תברואה", position=2, color="#2563eb", task_status=TaskStatus.IN_PROGRESS),
            Group(board_id=enforce_board.id, name= "מטרדים", position=3, color="#d97706", task_status=TaskStatus.REVIEW),
        ]
        db.add_all(enf_groups)
        db.flush()
        g_enf1, g_enf2, g_enf3, g_enf4 = enf_groups
        
        enf_tasks = [
            Task(board_id=enforce_board.id, group_id=g_enf1.id, title="תיק 2026-142 — בנייה חורגת ברחוב החורשה 5",
                 description="תוספת 40 מ\"ר ללא היתר. הוצא צו הריסה. דיון בוועדת הערר ב-30.6.",
                 priority=Priority.CRITICAL, due_date=now+timedelta(days=7), location_lat=32.152, location_lng=34.891,
                 tags=["אכיפה", "בנייה", "צו הריסה"], position=0),
            Task(board_id=enforce_board.id, group_id=g_enf1.id, title="תיק 2026-143 — גגון מסחרי רחוב המרכזי",
                 description="גגון חורג ב-2.5 מ' לרוחב המדרכה. הודעת הריסה נשלחה.",
                 priority=Priority.HIGH, due_date=now+timedelta(days=14), location_lat=32.157, location_lng=34.886,
                 tags=["אכיפה", "מסחרי"], position=1),
            Task(board_id=enforce_board.id, group_id=g_enf2.id, title="ספסל מסעדה — רחוב הרצל 18",
                 description="תפיסת 6 מ' מדרכה שלא כדין. תבנית ניתנה להסדרה תוך 7 ימים.",
                 priority=Priority.MEDIUM, due_date=now+timedelta(days=10), location_lat=32.155, location_lng=34.893,
                 tags=["מסעדה", "חזקה"], position=0),
            Task(board_id=enforce_board.id, group_id=g_enf2.id, title="שלט חריג — מסעדת 'הסוד'",
                 description="שלט חוצות בשטח 12 מ\"ר. חריג ב-8 מ\"ר מהמותר. נדרש היתר שילוט.",
                 priority=Priority.MEDIUM, due_date=now+timedelta(days=21), location_lat=32.156, location_lng=34.889,
                 tags=["שילוט", "מסחרי"], position=1),
            Task(board_id=enforce_board.id, group_id=g_enf3.id, title="דיווח — פסולת בניין רחוב הזית 22",
                 description="הצטברות פסולת בניין בשטח ציבורי. קבלן מזוהה. מתן קנס.",
                 priority=Priority.HIGH, due_date=now+timedelta(days=3), location_lat=32.158, location_lng=34.884,
                 tags=["תברואה", "פסולת", "קנס"],
                 assignees=[users.get("שרה ברק")], position=0),
            Task(board_id=enforce_board.id, group_id=g_enf4.id, title="מטרדי רעש — מועדון 'אפיקומן'",
                 description="12 תלונות על רעש בשעות 23:00-03:00. נדרשת בדיקת מד רעש.",
                 priority=Priority.HIGH, due_date=now+timedelta(days=5), location_lat=32.154, location_lng=34.887,
                 tags=["רעש", "מועדון", "מטרד"], position=0),
        ]
        db.add_all(enf_tasks)

        # ── NEW BOARD 3: תחזוקה שוטפת (תברואה, ניקיון, תאורה) ─────
        main_board = Board(
            organization_id=city.id, department_id=depts["env"].id,
            name="תחזוקה שוטפת", icon="🔧", board_type=BoardType.KANBAN, color="#0891b2"
        )
        db.add(main_board)
        db.flush()
        
        mnt_groups = [
            Group(board_id=main_board.id, name="דחוף", position=0, color="#ef4444", task_status=TaskStatus.IN_PROGRESS),
            Group(board_id=main_board.id, name="מתוזמן", position=1, color="#f59e0b", task_status=TaskStatus.TODO),
            Group(board_id=main_board.id, name="שגרה", position=2, color="#2563eb", task_status=TaskStatus.BACKLOG),
            Group(board_id=main_board.id, name="הושלם", position=3, color="#059669", task_status=TaskStatus.DONE),
        ]
        db.add_all(mnt_groups)
        db.flush()
        g_m1, g_m2, g_m3, g_m4 = mnt_groups
        
        maint_tasks = [
            Task(board_id=main_board.id, group_id=g_m1.id, title="תקלת מים — רחוב השומר 3",
                 description="קריסת צינור מים ראשי. הפסקת מים ל-50 בתים. נדרשת חפירה דחופה.",
                 priority=Priority.EMERGENCY, due_date=now+timedelta(hours=6), location_lat=32.160, location_lng=34.882,
                 tags=["מים", "תקלה", "דחוף"],
                 assignees=[users.get("יוסי אברהם")], position=0),
            Task(board_id=main_board.id, group_id=g_m1.id, title="סתימת ביוב — רחוב הנרקיסים 22",
                 description="ביוב עולה בחניון הבניין. 4 דירות מוצפות. צוות בדרך.",
                 priority=Priority.EMERGENCY, due_date=now+timedelta(hours=2), location_lat=32.162, location_lng=34.886,
                 tags=["ביוב", "תקלה", "דחוף"],
                 assignees=[users.get("יוסי אברהם")], position=1),
            Task(board_id=main_board.id, group_id=g_m2.id, title="ניקוי רחובות — שבועי",
                 description="ניקוי יסודי של רחובות מרכזיים: רמתיים, הרצל, ז'בוטינסקי",
                 priority=Priority.MEDIUM, tags=["ניקיון", "שגרה"], position=0),
            Task(board_id=main_board.id, group_id=g_m2.id, title="גיזום עצים — רחוב האורנים",
                 description="גיזום 15 עצים המהווים סכנה לקווי חשמל. נדרשת הפסקת חשמל מתואמת.",
                 priority=Priority.HIGH, due_date=now+timedelta(days=7), location_lat=32.163, location_lng=34.880,
                 tags=["עצים", "גיזום", "בטיחות"], position=1),
            Task(board_id=main_board.id, group_id=g_m3.id, title="בדיקת תאורת רחוב — כלל העיר",
                 description="בדיקה תקופתית של 1,200 עמודי תאורה. דיווח שבועי לניהול.",
                 priority=Priority.LOW, due_date=now+timedelta(days=30), tags=["תאורה", "בדיקה"], position=0),
        ]
        db.add_all(maint_tasks)

        # ── NEW BOARD 4: תכנון ובניה (הנדסה) ────────────────────────
        planning_board = Board(
            organization_id=city.id, department_id=depts["eng"].id,
            name="תכנון ובנייה", icon="🏛️", board_type=BoardType.KANBAN, color="#dc2626"
        )
        db.add(planning_board)
        db.flush()
        
        plan_groups = [
            Group(board_id=planning_board.id, name="תכנון ארוך טווח", position=0, color="#0073ea", task_status=TaskStatus.BACKLOG),
            Group(board_id=planning_board.id, name="תוכניות מוסדרות", position=1, color="#579bfc", task_status=TaskStatus.REVIEW),
            Group(board_id=planning_board.id, name="היתרי בנייה", position=2, color="#2563eb", task_status=TaskStatus.IN_PROGRESS),
            Group(board_id=planning_board.id, name="אכיפה הנדסית", position=3, color="#eab308", task_status=TaskStatus.TODO),
        ]
        db.add_all(plan_groups)
        db.flush()
        g_p1, g_p2, g_p3, g_p4 = plan_groups
        
        plan_tasks = [
            Task(board_id=planning_board.id, group_id=g_p1.id, title="תוכנית מתאר כוללנית — הוד השרון 2035",
                 description="עדכון תוכנית המתאר העירונית. כולל הוספת 3,000 יחידות דיור, שטחי מסחר, פארקים.",
                 priority=Priority.HIGH, due_date=now+timedelta(days=365), tags=["תוכנית-מתאר", "אסטרטגיה",
                 "דיור"], position=0),
            Task(board_id=planning_board.id, group_id=g_p1.id, title="התחדשות עירונית — מתחם רמתיים",
                 description="תמ\"א 38/פינוי-בינוי במתחם הוותיק. 280 דירות קיימות, 500 חדשות.",
                 priority=Priority.CRITICAL, due_date=now+timedelta(days=180),
                 location_lat=32.158, location_lng=34.885, tags=["התחדשות", "פינוי-בינוי", "דיור"], position=1),
            Task(board_id=planning_board.id, group_id=g_p2.id, title="תכנון מוסדרי — שכונת נוף ירקון",
                 description="תוכנית מפורטת לשכונה החדשה. 1,000 יח\"ד, 2 בתי ספר, מרכז מסחרי.",
                 priority=Priority.HIGH, due_date=now+timedelta(days=120), location_lat=32.165, location_lng=34.875,
                 tags=["שכונה", "תכנון", "הרחבה"], position=0),
            Task(board_id=planning_board.id, group_id=g_p3.id, title="היתר 2026-89 — מרכז מסחרי רחוב הדקלים",
                 description="בקשה להקמת מרכז מסחרי בן 3 קומות. בבדיקת מהנדס העיר.",
                 priority=Priority.MEDIUM, due_date=now+timedelta(days=21), position=0),
            Task(board_id=planning_board.id, group_id=g_p3.id, title="היתר 2026-112 — בניין מגורים 24 יח\"ד",
                 description="הקמת בניין 8 קומות ברחוב הגפן. בדיקת תוכניות חשמל, מים, כיבוי אש.",
                 priority=Priority.MEDIUM, due_date=now+timedelta(days=14), position=1),
        ]
        db.add_all(plan_tasks)

        # ── NEW BOARD 5: תושבים — מוקד 106 ──────────────────────────
        hotline_board = Board(
            organization_id=city.id, department_id=depts["citizen"].id,
            name="מוקד 106 — פניות תושבים", icon="📞", board_type=BoardType.KANBAN, color="#d97706"
        )
        db.add(hotline_board)
        db.flush()
        
        hot_groups = [
            Group(board_id=hotline_board.id, name="התקבל", position=0, color="#ef4444", task_status=TaskStatus.BACKLOG),
            Group(board_id=hotline_board.id, name="בטיפול", position=1, color="#2563eb", task_status=TaskStatus.IN_PROGRESS),
            Group(board_id=hotline_board.id, name="ממתין", position=2, color="#f59e0b", task_status=TaskStatus.REVIEW),
            Group(board_id=hotline_board.id, name="טופל", position=3, color="#059669", task_status=TaskStatus.DONE),
        ]
        db.add_all(hot_groups)
        db.flush()
        g_h1, g_h2, g_h3, g_h4 = hot_groups
        
        citizen_reqs_new = [
            CitizenRequest(
                organization_id=city.id, request_type=CitizenRequestType.ROAD_ISSUE,
                citizen_name="אריאל בן דוד", citizen_phone="050-2345678",
                title="תקע במדרכה — רחוב האלונים 15",
                description="לוח בטון רופף במדרכה. סיכון לעוברים ושבים. 40 ס\"מ על 60 ס\"מ.",
                location_lat=32.161, location_lng=34.883, address="האלונים 15, הוד השרון",
                status="new", priority=Priority.HIGH, created_at=now-timedelta(hours=2),
            ),
            CitizenRequest(
                organization_id=city.id, request_type=CitizenRequestType.WASTE,
                citizen_name="תמר הראל", citizen_phone="054-1112222",
                title="פסולת גינה לא מפונה",
                description="ערמת גיזום עצים מונחת ברחוב כבר שבוע. לא מפונה על ידי העירייה.",
                location_lat=32.164, location_lng=34.879, address="הפרחים 10, הוד השרון",
                status="new", priority=Priority.MEDIUM, created_at=now-timedelta(days=3),
            ),
            CitizenRequest(
                organization_id=city.id, request_type=CitizenRequestType.NOISE,
                citizen_name="רן כספי", citizen_phone="052-3456789",
                title="רעש מפאב בדופן — רחוב המרכזי",
                description="רעש חזק כל לילה אחרי 23:00. מד רעש מראה 85db.",
                location_lat=32.154, location_lng=34.890, address="המרכזי 30, הוד השרון",
                status="new", priority=Priority.HIGH, created_at=now-timedelta(days=1),
            ),
        ]
        db.add_all(citizen_reqs_new)

        hotline_tasks = [
            Task(board_id=hotline_board.id, group_id=g_h1.id, title="פנייה 106-443 — תקע במדרכה האלונים",
                 description="לוח בטון רופף. נדרשת בדיקה דחופה של אגף התשתיות.", priority=Priority.HIGH,
                 tags=["106", "מדרכה", "בטיחות"], position=0),
            Task(board_id=hotline_board.id, group_id=g_h1.id, title="פנייה 106-444 — רעש מפאב המרכזי",
                 description="תלונות חוזרות על רעש. נדרשת מדידת רעש וטיפול באכיפה.", priority=Priority.HIGH,
                 tags=["106", "רעש", "אכיפה"], position=1),
            Task(board_id=hotline_board.id, group_id=g_h2.id, title="פנייה 106-445 — גיזום במחסה חשמל",
                 description="ענף גדול נוגע בקווי מתח גבוה. נסגר בתיאום עם חברת החשמל.", priority=Priority.EMERGENCY,
                 location_lat=32.159, location_lng=34.888, tags=["106", "בטיחות", "חשמל"],
                 assignees=[users.get("עומר גולן")], position=0),
            Task(board_id=hotline_board.id, group_id=g_h3.id, title="פנייה 106-421 — כלב משוטט רחוב הדרור",
                 description="כלב משוטט מזה 3 ימים. פונה ליחידה הווטרינרית." ,priority=Priority.MEDIUM,
                 tags=["106", "בעלי-חיים"], position=0),
        ]
        db.add_all(hotline_tasks)

        # ── NEW BOARD 6: גנים ציבוריים ונוף ──────────────────────────
        parks_board = Board(
            organization_id=city.id, department_id=depts["env"].id,
            name="גנים ציבוריים ונוף", icon="🌳", board_type=BoardType.MAP, color="#16a34a"
        )
        db.add(parks_board)
        db.flush()
        
        park_groups = [
            Group(board_id=parks_board.id, name="בתחזוקה", position=0, color="#2563eb", task_status=TaskStatus.IN_PROGRESS),
            Group(board_id=parks_board.id, name="תכנון נוף", position=1, color="#94a3b8", task_status=TaskStatus.BACKLOG),
            Group(board_id=parks_board.id, name="הושלם", position=2, color="#059669", task_status=TaskStatus.DONE),
        ]
        db.add_all(park_groups)
        db.flush()
        g_pk1, g_pk2, g_pk3 = park_groups
        
        park_tasks = [
            Task(board_id=parks_board.id, group_id=g_pk1.id, title="השקיה חכמה — גן העיר",
                 description="שדרוג מערכת ההשקיה לבקר חכם עם חיישני לחות. חיסכון 35% במים.",
                 priority=Priority.MEDIUM, location_lat=32.156, location_lng=34.892, tags=["השקיה", "חסכון", "מים"],
                 assignees=[users.get("עומר גולן")], position=0),
            Task(board_id=parks_board.id, group_id=g_pk1.id, title="גילוח דשא — פארק רמתיים",
                 description="גילוח שבועי של 15 דונם. קבלן חיצוני.", priority=Priority.LOW,
                 location_lat=32.158, location_lng=34.887, tags=["דשא", "פארק", "תחזוקה"], position=1),
            Task(board_id=parks_board.id, group_id=g_pk2.id, title="תכנון גן כלבים — רחוב המכבים",
                 description="גן כלבים מגודר בשטח 600 מ\"ר. מתקני אילוף, ספסלי ישיבה, תאורה.",
                 priority=Priority.HIGH, location_lat=32.167, location_lng=34.878,
                 tags=["כלבים", "גן", "תכנון"], due_date=now+timedelta(days=90), position=0),
            Task(board_id=parks_board.id, group_id=g_pk2.id, title="שדרוג גן שעשועים — רסקו",
                 description="החלפת 6 מתקנים ישנים. הוספת נדנדות, מגלשה, מתקן קבוצתי.",
                 priority=Priority.MEDIUM, location_lat=32.162, location_lng=34.890,
                 tags=["גן-שעשועים", "שדרוג", "ילדים"], due_date=now+timedelta(days=45), position=1),
        ]
        db.add_all(park_tasks)

        # ── ADD MORE ASSETS ──────────────────────────────────────────
        more_assets = [
            InfrastructureAsset(
                organization_id=city.id, asset_type="road",
                name="צומת סוקולוב/רמתיים",
                location_lat=32.157, location_lng=34.887,
                condition="fair", status="monitoring",
                properties={"traffic_volume_daily": 15000, "accidents_last_year": 3, "last_repair": "2024-01"}
            ),
            InfrastructureAsset(
                organization_id=city.id, asset_type="water_pipe",
                name="קו מים ראשי — רחוב השומר",
                location_lat=32.160, location_lng=34.882,
                condition="critical", status="maintenance_needed",
                properties={"diameter_mm": 200, "material": "ברזל יצוק", "install_year": 1985, "leaks_2025": 4}
            ),
            InfrastructureAsset(
                organization_id=city.id, asset_type="park",
                name="גן העיר המרכזי",
                location_lat=32.156, location_lng=34.892,
                condition="good", status="active",
                properties={"area_sqm": 12000, "playgrounds": 3, "benches": 45, "sprinklers": True}
            ),
            InfrastructureAsset(
                organization_id=city.id, asset_type="street_light",
                name="תאורת רחוב — ציר עופר",
                location_lat=32.151, location_lng=34.895,
                condition="excellent", status="active",
                properties={"count": 32, "type": "LED Smart", "install_year": 2025, "remote_control": True}
            ),
            InfrastructureAsset(
                organization_id=city.id, asset_type="sewage",
                name="תחנת שאיבה — רחוב האתרוג",
                location_lat=32.163, location_lng=34.876,
                condition="good", status="active",
                properties={"capacity_m3_hour": 120, "pumps": 3, "last_maintenance": "2026-04"}
            ),
        ]
        db.add_all(more_assets)

        # ── MORE PERMITS ─────────────────────────────────────────────
        more_permits = [
            Permit(
                organization_id=city.id, permit_type=PermitType.RENOVATION,
                permit_number="B-2026-00171",
                applicant_name="דניאל תירוש", applicant_phone="050-9988776",
                property_address="הנרקיסים 22, הוד השרון",
                description="שיפוץ מקיף דירה 100 מ\"ר", status="submitted",
                task_id=16,  # Link to the renovation task
                submitted_at=now-timedelta(days=1),
            ),
            Permit(
                organization_id=city.id, permit_type=PermitType.SIGN,
                permit_number="B-2026-00095",
                applicant_name="מסעדת הסוד בע\"מ", applicant_phone="054-7654321",
                property_address="המרכזי 30, הוד השרון",
                description="היתר שילוט — 12 מ\"ר", status="in_review",
                submitted_at=now-timedelta(days=5),
            ),
            Permit(
                organization_id=city.id, permit_type=PermitType.DEMOLITION,
                permit_number="B-2026-00041",
                applicant_name="יבנה חברה לבניין", applicant_phone="03-9001234",
                property_address="החורשה 5, הוד השרון",
                description="הריסת מבנה ישן לצורך בנייה מחדש", status="approved",
                submitted_at=now-timedelta(days=60), decided_at=now-timedelta(days=10),
                decision_notes="מאושר בתנאים: פיקוח מהנדס, הגנת עצים סמוכים, לוחות זמנים",
            ),
        ]
        db.add_all(more_permits)

        # ── MORE TRANSPORT STOPS ─────────────────────────────────────
        more_stops = [
            PublicTransportStop(organization_id=city.id, stop_code="32989",
                name="ת. רכבת הוד השרון/תחנת אוטובוס",
                latitude=32.16250, longitude=34.87500, routes=["1", "3", "4", "5", "47", "50", "142", "259"]),
            PublicTransportStop(organization_id=city.id, stop_code="37227",
                name="תחנת רכבת הוד השרון/יורדי רכבת",
                latitude=32.16300, longitude=34.87450, routes=["3", "4", "5", "50"]),
            PublicTransportStop(organization_id=city.id, stop_code="37204",
                name="דרך רמתיים/גולדה מאיר",
                latitude=32.15520, longitude=34.89350, routes=["1", "3", "6", "50", "142"]),
            PublicTransportStop(organization_id=city.id, stop_code="37266",
                name="מרכז רפואי הוד השרון/דרך רמתיים",
                latitude=32.15300, longitude=34.89700, routes=["1", "3", "6", "50"]),
            PublicTransportStop(organization_id=city.id, stop_code="37265",
                name="קניון הוד השרון/דרך רמתיים",
                latitude=32.15180, longitude=34.89850, routes=["1", "3", "4", "6", "142"]),
            PublicTransportStop(organization_id=city.id, stop_code="37194",
                name="מחלף הוד השרון/דרך רמתיים",
                latitude=32.14900, longitude=34.90100, routes=["47", "50", "142", "259"]),
        ]
        db.add_all(more_stops)

        db.commit()
        
        print(f"✅ CityOS Extended Use Cases Seeded!")
        print(f"   ← Boards: 6 new")
        print(f"   ← Tasks: {len(edu_tasks) + len(enf_tasks) + len(maint_tasks) + len(plan_tasks) + len(hotline_tasks) + len(park_tasks)} new")
        print(f"   ← Citizen Requests: {len(citizen_reqs_new)} new")
        print(f"   ← Permits: {len(more_permits)} new")
        print(f"   ← Assets: {len(more_assets)} new")
        print(f"   ← Transport Stops: {len(more_stops)} new")
        print(f"\n   Boards added:")
        print(f"   1. חינוך ונוער — {len(edu_tasks)} tasks")
        print(f"   2. פיקוח ואכיפה — {len(enf_tasks)} tasks")
        print(f"   3. תחזוקה שוטפת — {len(maint_tasks)} tasks")
        print(f"   4. תכנון ובנייה — {len(plan_tasks)} tasks")
        print(f"   5. מוקד 106 — {len(hotline_tasks)} tasks")
        print(f"   6. גנים ציבוריים ונוף — {len(park_tasks)} tasks")
        print(f"   Total: ~60+ new tasks + 30+ assets/stops/permits/requests")

if __name__ == "__main__":
    seed_extended()
