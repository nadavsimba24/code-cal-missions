# CityOS — סוויטת בדיקות רגרסיה (pytest)

בדיקות API אוטומטיות שנועדו לרוץ **לפני כל עליית גרסה**, כדי לוודא ששום דבר קיים לא נשבר.
הבדיקות מכסות גם את הליבה הישנה וגם כל פיצ'ר שנוסף (ניהול משתמשים, סטטוס, בעלי לוח, היסטוריית התחברות, אווטרים).

---

## הרצה

```bash
./run_tests.sh                      # כל הסוויטה
./run_tests.sh -v                   # מפורט (שם כל בדיקה)
./run_tests.sh tests/test_users.py  # קובץ בודד
./run_tests.sh -k login             # רק בדיקות ששמן מכיל "login"
```

התקנה חד-פעמית של תלויות הבדיקה:
```bash
./venv/bin/pip install -r requirements-dev.txt
```

## איך זה בנוי

- **מסגרת:** `pytest` + `fastapi.testclient.TestClient` (בדיקות HTTP אמיתיות מול האפליקציה, בלי דפדפן ובלי שרת חי).
- **DB מבודד:** `tests/conftest.py` מפנה את האפליקציה ל-SQLite זמני דרך משתנה הסביבה `CITYOS_DB_PATH` **לפני** ייבוא האפליקציה (כי `main.py` זורע נתונים בזמן ייבוא). **הבסיס נתונים האמיתי `backend/cityos.db` לעולם לא נוגע.**
- **נתוני בסיס (seed):** משתמשים 1–3 הם מנהלי-סביבה, 4–7 חברים רגילים. הבדיקות מסתמכות על נתוני ההדגמה הזרועים.
- **אידמפוטנטיות:** בדיקות שמשנות נתונים (תפקיד, סטטוס) **משחזרות** אותם בסוף — אפשר להריץ שוב ושוב ללא הצטברות.

## זהויות קבועות (מ-`conftest.py`)

| קבוע | ערך | תפקיד |
|------|-----|-------|
| `ADMIN_ID` | 1 | מנהל סביבה (workspace admin) |
| `MEMBER_ID` | 4 | חבר רגיל (לא אדמין) |
| `GUINEA_ID` | 5 | חבר שמשמש "שפן ניסיונות" — משתנה ומשוחזר |

---

## קטלוג הבדיקות

### `test_smoke.py` — קריאות ליבה (31 בדיקות)
מוודא שכל endpoints הקריאה המרכזיים חיים ומחזירים JSON תקין.

| בדיקה | מוודאת |
|-------|--------|
| `test_read_endpoint_ok[...]` | 28 endpoints (parametrized) מחזירים `200` + JSON תקין: status, dashboard, boards, users, projects, tasks, permits, citizen-requests, kpis, work-plans, forms, transport, graph, viz/*, gantt, audit-log, approvals, change-requests, dependencies, infrastructure, ceo/dashboard, swarm, ai/models, workspace/members |
| `test_status_shape` | `/api/status` מחזיר `status: "ok"` |
| `test_boards_list_nonempty` | `/api/boards` מחזיר רשימה לא ריקה |
| `test_board_detail_shape` | פרטי לוד מכילים `id, name, groups, tasks, my_role, owners` |

### `test_validation.py` — ולידציה וטיפול שגיאות (8 בדיקות)
שומרות שהבאגים שכבר תוקנו **לא יחזרו**.

| בדיקה | מוודאת |
|-------|--------|
| `test_create_task_empty_body_rejected` | `POST /api/tasks` עם גוף ריק → **422** (באג המשימה היתומה) |
| `test_create_task_nonexistent_board_404` | יצירת משימה על לוח לא קיים → **404** |
| `test_gantt_requires_work_plan_id` | `/api/gantt/data` בלי פרמטר → **400** (במקום 422 גנרי) |
| `test_gantt_with_param_ok` | `/api/gantt/data?work_plan_id=1` → **200** |
| `test_nonexistent_board_404` | לוד לא קיים → **404** |
| `test_nonexistent_project_404` | פרויקט לא קיים → **404** |
| `test_nonexistent_form_template_404` | תבנית טופס לא קיימת → **404** |
| `test_unknown_route_404` | ראוט לא מוכר → **404** |

### `test_tasks.py` — מחזור חיים של משימה (1 בדיקה)
| בדיקה | מוודאת |
|-------|--------|
| `test_task_lifecycle` | יצירה → מופיעה בלוח → עדכון (PATCH) → תגובה (add + read) → הזזה (move) → קריאת activity → מחיקה. מנקה אחריה. |

### `test_boards.py` — לוחות והרשאות (4 בדיקות)
| בדיקה | מוודאת |
|-------|--------|
| `test_create_board_requires_admin` | יצירת לוד בלי מנהל-סביבה → **403** (גם בלי user_id וגם עם member) |
| `test_admin_can_create_and_delete_board` | מנהל יוצר לוד → 200, ומוחק → 200 |
| `test_board_owners_present` | פרטי לוד מחזירים `owners` (≥1) עם שמות |
| `test_owners_visible_to_non_admin_member` | הבעלים גלויים גם לחבר שאינו אדמין |

### `test_users.py` — ניהול משתמשים (5 בדיקות)
| בדיקה | מוודאת |
|-------|--------|
| `test_users_list_shape` | `/api/users` מכיל `id, name, role, is_active, department_name, last_login` |
| `test_non_admin_cannot_change_role` | member שמנסה לשנות תפקיד → **403** |
| `test_admin_cannot_deactivate_self` | מנהל שמנסה להשבית את עצמו → **400** |
| `test_admin_changes_role_and_restores` | מנהל משנה תפקיד → 200 (ומשחזר) |
| `test_admin_toggles_active_and_restores` | מנהל מפעיל/משבית סטטוס → 200 (ומשחזר) |

### `test_login_history.py` — היסטוריית התחברות (5 בדיקות)
| בדיקה | מוודאת |
|-------|--------|
| `test_record_login` | `POST /api/auth/login` מתעד אירוע ומחזיר חותמת זמן |
| `test_record_login_unknown_user_404` | התחברות של משתמש לא קיים → **404** |
| `test_last_login_reflected` | `last_login` ב-`/api/users` מתעדכן אחרי כניסה |
| `test_per_user_history_admin_only` | היסטוריה פר-משתמש: אדמין → 200 עם אירועים; לא-אדמין → **403** |
| `test_consolidated_history_admin_only` | היסטוריה מרוכזת: אדמין → 200 עם שמות; לא-אדמין → **403** |

### `test_assets.py` — נכסים סטטיים ושפיות frontend (4 בדיקות)
| בדיקה | מוודאת |
|-------|--------|
| `test_avatar_pool_bundled` | 30 קבצי אווטר (`frontend/avatars/*.svg`) קיימים |
| `test_avatars_served` | `/avatars/00.svg` ו-`29.svg` מוגשים כ-SVG (200) |
| `test_index_served` | `/` מחזיר HTML עם הרכיבים `SysAdmin, avatarInner, ownerChipHTML` |
| `test_inline_js_syntax` | ה-JS הפנימי ב-index.html עובר `node --check` (מדלג אם אין node) |

---

## הוספת בדיקה חדשה

1. הוסיפי קובץ `tests/test_<נושא>.py` (pytest מגלה אוטומטית לפי `pytest.ini`).
2. השתמשי ב-fixture `client` (וב-`admin_id`/`member_id`/`guinea_id` לפי הצורך).
3. אם הבדיקה משנה נתונים — **שחזרי אותם ב-`finally`** כדי לשמור אידמפוטנטיות.

## מה עדיין לא מכוסה (הצעות להרחבה)
`forms/submit`, endpoints של תקציב, `dependencies` (POST/DELETE), ו-BIM/swarm ברמת תוכן.
