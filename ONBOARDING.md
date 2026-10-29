# CODE-CAL MISSIONS — מדריך למפתח/ת חדש/ה

מסמך התמצאות בקוד. קרא/י אותו לפני שאת/ה נוגע/ת בקוד.
עודכן: 26.10.2026 — מאומת מול הקוד בפועל.

---

## 1. מה זה?

פלטפורמת ניהול עבודה בסגנון monday.com, בממשק **RTL בעברית**.
לוחות, פריטים ותתי-פריטים, עמודות מותאמות, תצוגות שמורות, טפסים ציבוריים,
אוטומציות, הרשאות רב-שכבתיות, ייבוא מ-monday.com, וסוכני AI.
יש גם שכבות ותיקות שלא בשימוש פעיל: מפות GIS, BIM/3D ותחבורה ציבורית.

> **השם הוא `CODE-CAL MISSIONS`** בכל מקום שמשתמש/ת רואה — אף פעם לא "CityOS".
> השם הישן שרד **בתוך הקוד בלבד** כפורמט-חוטים ואסור "לתקן" אותו:
> משתני הסביבה `CITYOS_*`, ה-header ‏`X-CityOS-User`, וקובץ ה-DB ‏`backend/cityos.db`.

## 2. הסטאק

| שכבה | טכנולוגיה |
|------|-----------|
| Backend | Python 3.11 · **FastAPI** + **SQLAlchemy** · SQLite (`backend/cityos.db`) |
| Frontend | **Vanilla JS SPA** — קובץ `index.html` אחד (~19,600 שורות / 1.2MB), בלי framework ובלי build |
| אימות | **Entra ID** — בתוך האפליקציה (`entra`) או דרך Azure Easy Auth (`easyauth`); בוחר-משתמש מקומי במצב `dev` |
| AI | DeepSeek ("קרמר") ו-Gemini ("איליין") דרך proxy בצד-שרת · page-agent (שליטה בממשק) · swarm/Ollama (מקומי, בד"כ לא פעיל) |
| בדיקות | pytest + `fastapi.testclient` · harnesses של node ב-`.mjs` מעל `index.html` |
| דיפלוי | Azure DevOps pipelines (QA + prod) · Vercel serverless דרך `api/index.py` |
| מפות / BIM | MapLibre (GeoLibre WASM) · IfcOpenShell + Three.js |

## 3. הרצה מהירה

```bash
bash run.sh                                 # עוצר ומפעיל מחדש את השרת על :8000, טוען .env
./venv/bin/python backend/healthcheck.py    # סריקת endpoints
```

- השרת מגיש **גם API וגם ה-frontend** מאותו פורט (8000).
- ה-DB **נזרע אוטומטית** בהרצה ראשונה.
- שינויי frontend נטענים ב-refresh. **לשינויי backend חובה `bash run.sh`** —
  ל-`python main.py` אין autoreload, וראוט חדש שמחזיר 404/405 הוא כמעט תמיד
  תהליך ישן שעדיין רץ.
- **אל תיגע/י ב-`backend/cityos.db`.** אלה נתוני עבודה אמיתיים (825MB) עם גיבויים
  ידניים לידם. שינויי סכימה נוחתים כקוד, והשרת מחיל אותם.

### משתני סביבה (`.env` בשורש — gitignored, ומוחרג מה-image ב-`.dockerignore`)

| משתנה | לשם מה |
|-------|--------|
| `CITYOS_AUTH_MODE` | `entra` / `easyauth` (ברירת מחדל) / `dev`. ראה/י סעיף 7. |
| `CITYOS_AUTH_AUTOPROVISION` | יצירת משתמש אוטומטית בכניסה ראשונה. |
| `CITYOS_DB_PATH` | override לנתיב ה-DB (בדיקות, serverless). |
| `CITYOS_CORS_ORIGINS` | רשימה מופרדת בפסיקים. ריק = אין CORS בכלל (ה-SPA באותו origin). |
| `DEEPSEEK_API_KEY` · `GEMINI_API_KEY` | מפתחות ה-AI. בלעדיהם ה-AI מחזיר 503. |
| `ENTRA_REDIRECT_URI` · `APP_BASE_URL` | SSO ולינקים במיילים. |
| `SENDGRID_API_KEY` / `RESEND_API_KEY` · `MAIL_PROVIDER` · `INVITE_FROM_EMAIL` · `EMAIL_DEV_REDIRECT` · `SENDGRID_SANDBOX` | שליחת מיילים והזמנות. |
| `MONDAY_TOKEN` | ייצוא מ-monday.com (`scripts/export_monday_board.py`). |
| `VIEW_MAX_PER_BOARD` · `VIEW_NAME_MAX` · `VIEW_RESTORE_DAYS` · `FILTER_CLIENT_MAX` · `FILTER_COLUMN_POLICY` | מכסות והתנהגות של תצוגות ופילטרים. |

## 4. מבנה הפרויקט

```
backend/
  main.py          ~24,000 שורות ← כל השרת: 221 routes, seed, מיגרציות, proxy ל-AI, SSE
  models.py        ~1,560 שורות ← 49 טבלאות SQLAlchemy
  automations.py   מנוע האוטומציות (טריגרים, תנאים, פעולות, תור, retry, incidents)
  auth.py          זהות: current_user, auth_mode, effective_auth_mode
  entra.py         SSO מלא בתוך האפליקציה   entra_guests.py  הזמנת אורחים
  filter_ast.py    עץ הביטויים של הפילטר המתקדם
  import_monday.py ייבוא ייצוא של monday.com ללוח
  seed.py / seed_more_use_cases.py   נתוני הדגמה (אידמפוטנטיים)
  healthcheck.py   סריקת endpoints      sync.py  אימות אינוריאנטים
  bim_bridge.py    מחולל IFC/BCF        swarm.py  6 סוכני Ollama (בד"כ כבוי)
frontend/
  index.html       כל ה-SPA: CSS ו-JS inline
  public-form.html הדף שזר רואה כשהוא ממלא טופס משותף
  form-paper.js    רינדור טפסים, משותף לשני הדפים
  sortable.min.js  ספרייה חיצונית — לא נוגעים
  wasm/            בילד GeoLibre — לא נוגעים
tests/             234 קבצי test_*.py + 77 harnesses ב-frontend/*.mjs + README.md
scripts/           security_agent.py, security_gate.sh, azure-deploy.sh, bench_views.py, ייצוא monday
api/index.py       entrypoint ל-Vercel סביב אותה אפליקציה
docs/              FORMS_PLAN.md, MONDAY_EXPORT_IMPORT.md, סקירת אבטחה, releases/
CONVENTIONS.md     אינוריאנטים של עיצוב ובעלוּת (source of truth)
CLAUDE.md          workflow הפיתוח והאינוריאנטים, לסוכנים ולבני אדם
```

> אין יותר `frontend/avatars/` ואין GeoLibre/SIRI כתיקיות בריפו הזה.

## 5. ארכיטקטורת ה-Backend

- **הכל ב-`main.py`.** 221 endpoints. הקובץ ענק — תמיד `grep -n` לראוט או ל-helper,
  לקרוא 50 שורות מסביב, ואז עריכה כירורגית. לא לשכתב אזור שלא קראת.
- **DB:** SQLAlchemy + SQLite, אתחול ב-`init_db()` (`create_all`).
- **מיגרציות: אין Alembic.** יש בלוק "additive migrations" ידני בראש `main.py`
  (~115 פקודות `ALTER TABLE`). **עמודה חדשה ב-`models.py` בלי `ALTER TABLE ADD COLUMN`
  מתאים עובדת על DB ריק ומחזירה 500 על כל DB קיים.** זו הטעות הנפוצה ביותר כאן.
- **כל ראוט אוכף הרשאה במפורש** — ראה/י סעיף 6.
- **קודי סטטוס:** גוף חסר → 422, הורה לא קיים → 404, אין הרשאה → 403,
  ארגומנט שגוי → 400. אף פעם לא 500 גנרי.
- **Seeds אידמפוטנטיים** — בדיקת קיום לפני הכנסה, בלי כפילויות.
- הראוטים לפי משפחה (הגדולים): `boards` 49 · `tasks` 19 · `projects` 12 ·
  `automations` 12 · `forms` 10 · `environments` 9 · `admin` 6 · `users` 5 ·
  ועוד: `views`, `groups`, `folders`, `departments`, `public`, `workspace`,
  `trash`, `notifications`, `guests`, `comments`, `dependencies`, `approvals`,
  `kpis`, `change-requests`, `automation-runs`, `ai`, `llm`, `swarm`, `bim`,
  `viz`, `ceo`, `budget`, `upload`, `auth`, `login-history`, `status`.
- מחוץ ל-`/api`: ‏`/forms/{token}` (טופס ציבורי), `/auth/login|callback|logout`
  (מ-`entra.py`), והשאר הוא `StaticFiles` שמוגש מ-`frontend/` על `/`.

### מודל הנתונים — העיקר

49 טבלאות. השלד: `Organization → Environment → Folder → Board → Group → Task`,
עם `Comment`, `BoardMember`, `WorkspaceMember`, `EnvironmentMember` ו-`RolePermission` מסביב.

- **עמודות מותאמות** מוגדרות ב-`board.settings["columns"]` (JSON), והערך לפריט
  יושב ב-`task.custom_fields` (JSON). עמודות מובנות (`title`, `status`,
  `priority`, `due_date`…) הן שדות אמיתיים על `Task`.
- `SavedView` — חתך שמור של לוח, מוצג כטאב. שומר את עץ התנאים, פילטרי הסרגל
  וסדר/רוחב העמודות כ-JSON. `BoardViewPrefs` — ההעדפות האישיות.
- `FormView` + `FormComponent` — **טופס הוא תצוגה של לוח**. הגשה יוצרת פריט
  בלוח, ו-`task.form_view_id` מצביע חזרה.
- `ItemLink` — שורה אחת לכל קשר בין שני פריטים, לעמודות connect דו-כיווניות.
- משפחת `Automation*` (12 טבלאות) — חוקים, גרסאות, תור, ריצות, ביצוע פעולות,
  תקלות (`AutomationIncident`), `EventOutbox`, הרשאות והקפאות.
- מחיקה רכה: ל-`Board` ול-`Task` יש `deleted_at`/`deleted_by` — סל מיחזור
  (`/api/trash/...`) ולא מחיקה מיידית.
- `AuditLog`, `LoginEvent`, `Notification`, `UploadedFile`, `Document`.

## 6. הרשאות — ארבע שכבות

`סביבה (workspace) → לוח (board) → פריט (item) → עמודה (column)`

| Helper ב-`main.py` | מה הוא עונה |
|---|---|
| `_ws_role(db, user_id)` | תפקיד סביבה: admin / member / viewer. "מנהל מערכת" = ws-admin. |
| `_board_role(db, board_id, user_id)` · `_board_role_or_403(...)` | תפקיד בלוח: admin / editor / viewer. |
| `_require_board_edit(db, board_id, actor, need="editor")` | זורק 403 אם אין הרשאת עריכה. |
| `_is_board_admin` · `_can_delete_board` | פעולות ניהוליות על לוח. |
| `_item_perm(task, user_id, board_role)` · `_can_see_item` · `_can_comment` | הרשאה ברמת פריט (`task.permissions` JSON). |
| `_require_sys_admin(db, user_id)` | endpoints של מנהל מערכת בלבד. |
| `_can_manage_automations` · `_can_view_automations` · `_can_export_automations` | אוטומציות. |
| `_can_manage_env` · `_can_admin_envs` | סביבות. |

**הגישה מבוססת-חברוּת:** רואים רק לוחות שהוזמנת אליהם. endpoint קריאה חדש
ששוכח את זה מדליף נתונים של סביבות אחרות.
`./venv/bin/python scripts/security_agent.py scan --only authz --json` מדווח על
endpoints בלי בדיקת הרשאה נראית — מייעץ בלבד, אבל רשומה חדשה שם צריכה הסבר.

## 7. אימות (Auth) — **יש אימות אמיתי**

כל ההיגיון ב-`backend/auth.py`. שלושה מצבים, לפי `CITYOS_AUTH_MODE`:

| מצב | איך הזהות מגיעה |
|---|---|
| `entra` | האפליקציה מבצעת SSO בעצמה מול Entra ID: `/auth/login` → Entra → `/auth/callback` → cookie חתום. עובד על כל host. ראה/י `scripts/ENTRA_SSO.md`. |
| `easyauth` *(ברירת מחדל)* | Azure Container Apps עם Entra. הפלטפורמה מסיימת את ההתחברות ב-ingress ומזריקה `X-MS-CLIENT-PRINCIPAL*`. היא גם **מסירה** את ה-headers האלה מבקשות נכנסות — וזה מה שהופך אותם לאמינים, **אבל רק אם ה-Container App מוגדר לדרוש אימות**. ראה/י `scripts/AZURE_AUTH.md`. |
| `dev` | פיתוח מקומי. הזהות מגיעה מ-header ‏`X-CityOS-User` (id או אימייל) שה-frontend שולח עבור המשתמש שנבחר. |

שתי הגנות שחשוב להבין:

1. **ברירת המחדל היא `easyauth` בכוונה** — דיפלוי לא-מוגדר **דוחה** כל בקשה
   במקום לאשר כל בקשה. failing closed זה כל הרעיון.
2. **`dev` מכובד רק כשהאפליקציה מוגשת מקומית** (`effective_auth_mode`). בלי זה,
   `.env` עם `CITYOS_AUTH_MODE=dev` שמועלה ל-host (מה ש-`vercel deploy` עושה,
   כי הוא מעלה את תיקיית העבודה) היה הופך את בוחר-המשתמש לדלת ציבורית.

> **הכלל שאסור לשבור:** הזהות מגיעה מהתעבורה, **לעולם לא מפרמטר בבקשה**.
> מפרשים את מי שפועל עם `current_user` / `current_user_id`. פרמטר `user_id`
> או `actor_id` יכול לציין **יעד** (למי לשנות תפקיד) — הוא אף פעם לא אומר מי פועל.
> `tests/test_authz.py` קיים בדיוק כדי לתפוס את זה.

`entra_guests.py` מטפל באורחים חיצוניים, כולל ה-UPN המעוות
(`person_partner.com#EXT#@host.onmicrosoft.com`) שלא מתאים לשום שורת משתמש.

## 8. ארכיטקטורת ה-Frontend

- **קובץ יחיד `index.html`** — CSS ב-`<style>`, JS ב-`<script>`. אין bundler,
  ואין import של קבצים מקומיים מעבר ל-import map שכבר יושב ב-`<head>`.
- **State גלובלי** באובייקט `st`: `st.boards`, `st.board`, `st.view`, `st.users`,
  `st.filters`, `st.selected`, `st.collapsedGroups`.
- **קריאות API** דרך `const api = async (p,o)=>{...}` — זורק `Error` עם הסטטוס
  כשהתשובה לא ok.
- **הקוד מקובץ לאובייקטים לפי תחום** — התנהגות חדשה הולכת לאובייקט שכבר מחזיק
  את האזור, לא לפונקציה חופשית:
  `Router` · `Auth` · `Folders` · `Views` · `Adv` (פילטר מתקדם) · `Paged` ·
  `BoardLog` · `BoardTrash` · `Trash` · `Env` · `Workspace` · `Members` ·
  `ItemPerms` · `ColPerms` · `Automations` · `FormEditor` · `Timeline` · `GIS` ·
  `Notif` · `Live` (SSE) · `Profile` · `Settings` · `SysAdmin` · `Chat` · `AI` · `Term`.
- **UI נבנה כ-template strings** ומוזרק ל-DOM. `showModal(html)` לחלונות,
  `askConfirm()` לפני פעולה הרסנית, `toast()` לדיווח על התוצאה.
- **עוזרים לשימוש חוזר:** `esc()` · `avatarInner(user)` · `avatarColor()` ·
  `initials()` · `meId()` · `renderSidebar()` · `loadBoards()` · `openBoard(id)` ·
  `refreshUsers(force)`.
- **אווטרים:** אין יותר פּוּל SVG. תמונה שהועלתה (`avatar_url`) גוברת; אחרת
  ראשי תיבות על צבע דטרמיניסטי לפי השם. `avatarInner` מרענן תמיד מ-`st.users`
  לפי `user_id ?? id`, כדי שתמונה שהוחלפה תתעדכן בכל מקום בבת אחת.
  `st.users` נטען מחדש לכל היותר פעם ב-120 שניות (`USERS_TTL_MS`).

### אינוריאנטים של עיצוב (מ-`CONVENTIONS.md` — נאכפים ונבדקים)

1. השם הוא **CODE-CAL MISSIONS**. אף פעם לא "CityOS" במשהו גלוי.
2. **בלי סגול.** פלטת monday בלבד, דרך משתני ה-CSS שכבר קיימים — לא hex גולמי:
   `--primary #0073ea` · `--green #00c875` · `--orange #fdab3d` · `--red #e2445c` ·
   `--blue #579bfc` · `--yellow #ffcb00` · `--grey #c4c4c4`.
3. **גופנים:** Figtree (לטינית) + Rubik (עברית). כבר נטענים; לא מוסיפים גופן.
4. **RTL כברירת מחדל** (`<html lang="he" dir="rtl">`). מאפיינים לוגיים —
   `margin-inline-start`, `inset-inline-end` — ולא `left`/`right`.
   מחרוזות ממשק בעברית, קוד והערות באנגלית.
5. **`esc()` על כל ערך שמוזרק לתבנית.** שם לוח או פריט בלי escape הוא XSS מאוחסן.
6. חייב להישאר **קריא בטלפון ושמיש במקלדת** — יש harnesses ייעודיים שייכשלו.
7. **ה-JS הפנימי חייב לעבור parse** — `tests/test_assets.py` מריץ עליו `node --check`.

## 9. AI — ארבעה מנגנונים (לא לבלבל)

1. **הצ'אט שלנו (אובייקט `AI`)** — ווידג'ט הצ'אט מסרגל הצד. פונה ל-`POST /api/ai/query`.
   המודלים: **קרמר = DeepSeek**, **איליין = Gemini**. ה-tool-calling קורה
   **בצד-שרת**: 12 כלים — `list_boards`, `get_board`, `list_projects`,
   `create_board`, `create_group`, `create_task`, `update_task`, `delete_task`,
   `list_departments`, `list_users`, `create_project`, `get_project_detail` —
   שהשרת מבצע בפועל דרך `execute_ai_tool()`. אחרי פעולה ה-UI מתרענן (`AI.refreshUI`).
2. **page-agent** — כפתור הרובוט הצף. ספריית צד-שלישי שנטענת מ-CDN ומפעילה את
   ה-DOM ויזואלית. מדובקת לאייקון דרך `_paDock()`.
3. **ה-proxy** — `POST /api/llm/v1/chat/completions` מזריק את מפתח ה-API
   **בצד-שרת בלבד**, כך שהוא לעולם לא מגיע לדפדפן. **אסור שסוד יגיע ללקוח.**
4. **swarm / Ollama** (`/api/swarm/think`) — דורש Ollama מקומי, **בד"כ לא זמין**,
   נכשל בחן.

## 10. בדיקות

- **מסגרת:** `pytest` + `fastapi.testclient.TestClient` — HTTP אמיתי מול האפליקציה
  בתוך התהליך. בלי שרת חי, בלי דפדפן.
- **היקף היום:** 234 קבצי `tests/test_*.py` ו-77 harnesses ב-`tests/frontend/*.mjs`.
  הכבדים: אוטומציות (~38 קבצים), תצוגות ופילטרים (~24), ייבוא monday (~18),
  לוחות (~15), עמודות connect (~12), טפסים (~11), פריטים (~10).

```bash
./run_tests.sh                          # הכל + שער האבטחה
./run_tests.sh -q tests/test_forms.py   # קובץ בודד
./run_tests.sh -k automation            # לפי שם
./run_tests.sh -v                       # שם כל בדיקה
SKIP_SECURITY_GATE=1 ./run_tests.sh     # בדיקות בלבד
./venv/bin/pip install -r requirements-dev.txt   # התקנה חד-פעמית
```

הריצה המלאה איטית — מתקדמים על הקובץ הממוקד, ומריצים את הכל פעם אחת לפני סיום.

- **DB מבודד:** `tests/conftest.py` מפנה את `CITYOS_DB_PATH` ו-`CITYOS_UPLOAD_DIR`
  לתיקייה זמנית **לפני** ייבוא `main` (האפליקציה זורעת בזמן ייבוא), וכופה
  `CITYOS_AUTH_MODE=dev`. **`backend/cityos.db` לא נוגע לעולם.**
- **דואר כבוי בבדיקות:** `SENDGRID_API_KEY`, `RESEND_API_KEY`, `EMAIL_DEV_REDIRECT`,
  `MAIL_PROVIDER` מוגדרים למחרוזת **ריקה** — לא נמחקים, כי `load_dotenv` היה
  ממלא מפתח חסר מה-`.env` של המפתח/ת ושולח הזמנות אמיתיות. בדיקה שאכפת לה
  מהמייל מחליפה את השולח (`tests/test_invite_tells_the_invitee.py`).
- **זהויות:** `admin_id` = 1 (מנהל סביבה), ו-`member_id` / `guinea_id` —
  משתמשים לא-אדמינים ש-`conftest.py` יוצר **דרך ה-API**, לא מזהי seed קשיחים
  (ניקוי משתמשי ההדגמה מוחק את אלה).
- **הלקוח חותם את הבקשה:** `TestClient` מקדם פרמטר `actor_id`/`user_id`
  ל-header ‏`X-CityOS-User`. למקרה האנונימי מעבירים
  `headers={"X-CityOS-User": ""}` במפורש; כדי להוכיח שפרמטר **לא** נאמן,
  קובעים את ה-header למישהו אחר (`tests/test_authz.py`).
- **אידמפוטנטיות חובה:** בדיקה שמשנה נתונים משחזרת אותם ב-`finally`.
- **שמות בדיקות הם משפטים על התנהגות**, ו-docstring המודול אומר איזה כלל מקובע ולמה.

### בדיקות frontend

התנהגות ב-UI נבדקת ב-harness של node ב-`tests/frontend/<name>.mjs` שמונע מקובץ
pytest. ה-harness קורא את `index.html` כטקסט, שולף את הפונקציות עם regex ומריץ
אותן דרך `new Function(...)` — אין DOM ואין דפדפן. הקובץ המניע:

```python
def test_the_thing_behaves():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
```

ה-harness סופר בעצמו pass/fail ויוצא בקוד שונה מאפס בכישלון. למה שה-harness
לא מגיע אליו, קובץ ה-pytest בודק ישירות מול טקסט המקור של `index.html`
(שהמטפל מחובר, שסרגל הפעולות המרובות לא מציע מחיקה).

> **אף פעם לא משנים בדיקה כדי שכישלון אמיתי יעבור.**

## 11. אבטחה

```bash
./scripts/security_gate.sh                                        # רץ אוטומטית בתוך run_tests.sh
./venv/bin/python scripts/security_agent.py scan --only sast,secrets
./venv/bin/python scripts/security_agent.py scan --only authz --json   # מייעץ
./venv/bin/python scripts/security_agent.py scan --only deps           # CVEs, דורש רשת
```

השער נכשל על כל ממצא בחומרה **גבוהה** מהסורקים הדטרמיניסטיים (SAST + סודות).
הוריסטיקת ה-authz מייעצת ולא חוסמת. ב-pipelines רצים בנוסף Mend SCA ו-Mend SAST.
ראה/י `docs/AGENTS_SECURITY_REVIEW.md`.

## 12. Git ודיפלוי

ענף `main`. Remotes: `origin` ו-`mashcal` (GitHub), `azure` (Azure DevOps).

- **דחיפה ל-`main` מריצה את pipeline ה-QA** — כלומר דחיפה היא כשלעצמה דיפלוי.
- **פרודקשן הוא pipeline ידני** (`trigger: none`) מול ענף release.
- **לשאול לפני כל דחיפה, מיזוג או דיפלוי, ולשאול לאיזו סביבה.** אף פעם לא להניח שתיהן.
- **הודעות commit הן משפטי פרוזה** שמתארים את התוצאה, לא prefix של conventional-commits.
  מההיסטוריה: *"Form View: a form is a view of a board, and a stranger can fill it in"*,
  *"Ask before the deletion, not explain after it"*.

## 13. סגנון קוד

**הערות מסבירות _למה_**, ומה השתבש קודם — פרוזה, לא פעם כמה שורות.
`# set the flag` לא במקום כאן. הקוד הקיים הוא הדוגמה: קרא/י את הסביבה לפני שמוסיפים לה.

**השאירו את ה-diff צמוד לפיצ'ר.** בלי עיצוב מחדש, בלי מיון imports מחדש,
בלי שינוי שם של משהו שבמקרה קראתם.

## 14. שני דברים שעלו לאנשים שעות

- **טאב ישן בדפדפן נראה בדיוק כמו באג.** Cmd+Shift+R לפני שחוקרים שינוי frontend
  ש"לא עובד". זה כבר בלע חקירות שלמות.
- **שרת ישן מחזיר 404 לראוט שקיים.** `bash run.sh`.

## 15. איפה להמשיך

| קובץ | מה יש בו |
|---|---|
| `CLAUDE.md` | workflow הפיתוח הרב-סוכני, האינוריאנטים והחוקים |
| `CONVENTIONS.md` | אינוריאנטים של עיצוב ובעלוּת (source of truth) |
| `tests/README.md` | קטלוג הבדיקות ואיך מוסיפים אחת |
| `docs/FORMS_PLAN.md` | האיפיון של מערכת הטפסים |
| `docs/MONDAY_EXPORT_IMPORT.md` | ייצוא מ-monday.com וייבוא ללוח |
| `docs/AGENTS_SECURITY_REVIEW.md` | סקירת אבטחה |
| `scripts/ENTRA_SSO.md` · `scripts/AZURE_AUTH.md` · `scripts/AZURE_DEPLOY.md` | אימות ודיפלוי |
| `scripts/SECURITY_AGENT.md` | סוכן האבטחה |
