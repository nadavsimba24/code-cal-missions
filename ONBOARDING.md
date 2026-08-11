# CityOS / CODE-CAL MISSIONS — מדריך למפתח/ת חדש/ה

מסמך התמצאות מהיר בקוד. קרא/י אותו לפני שאת/ה נוגע/ת בקוד.

---

## 1. מה זה?

פלטפורמת ניהול עבודה לעיריות בישראל ("Monday.com עירוני"). ממשק **RTL בעברית**, קוד פתוח.
משלב ניהול פרויקטים, מפות GIS, מודל תלת-ממד (BIM), סוכני AI ונתוני תחבורה בזמן אמת.

## 2. הסטאק

| שכבה | טכנולוגיה |
|------|-----------|
| Backend | Python **FastAPI** + **SQLAlchemy** (SQLite; ניתן להחליף ל-Postgres) |
| Frontend | **Vanilla JS SPA** — קובץ `index.html` אחד (~284KB), בלי framework ובלי build |
| מפות | MapLibre GL JS |
| BIM/3D | IfcOpenShell (יצירת IFC) + Three.js (viewer) |
| AI | DeepSeek (ענן) דרך proxy בצד-שרת · page-agent (שליטה בממשק) · swarm/Ollama (מקומי, בד"כ לא פעיל) |
| תחבורה | פרוטוקול SIRI (תחבורה ציבורית בזמן אמת) |

## 3. הרצה מהירה

```bash
cd backend && python main.py     # (בתוך venv) → http://localhost:8000
```
- השרת מגיש **גם API וגם ה-frontend** מאותו פורט (8000).
- ה-DB **נזרע אוטומטית** בהרצה ראשונה (SQLite). איפוס: מחיקת `backend/cityos.db` והרצה מחדש.
- שינויי frontend נטענים ב-**refresh** (אין build). שינויי backend דורשים הפעלה מחדש של השרת.

### משתני סביבה (`.env` בשורש — gitignored)
| משתנה | לשם מה |
|-------|--------|
| `DEEPSEEK_API_KEY` | מפתח ל-AI (הצ'אט ו-page-agent). בלעדיו ה-AI מחזיר 503. |
| `CITYOS_DB_PATH` | override לנתיב ה-DB (משמש בבדיקות ובפרודקשן serverless). |
| `CITYOS_UPLOAD_DIR` | override לתיקיית העלאות. |

## 4. מבנה הפרויקט

```
backend/
  main.py        ← כל השרת: 99 routes, seed, migrations, AI, proxy (~3850 שורות)
  models.py      ← 24 טבלאות SQLAlchemy
  seed.py        ← נתוני הדגמה (עיריית הוד השרון)
  swarm.py       ← 6 סוכני AI (Ollama מקומי)
  bim_bridge.py  ← מחולל IFC/BCF
frontend/
  index.html     ← כל ה-SPA: CSS + JS inline (~3800 שורות)
  avatars/       ← 30 אווטרים מצוירים (SVG סטטי, BigHeads)
tests/           ← סוויטת pytest (~58 בדיקות) + README
GeoLibre/        ← reference בלבד (לא נוגעים)
hod-hasharon-siri/ ← קליינט SIRI לתחבורה
```

## 5. ארכיטקטורת ה-Backend

- **הכל ב-`main.py`.** 99 endpoints תחת `/api/...`. חפש/י `@app.get`/`@app.post`.
- **DB:** SQLAlchemy + SQLite. אתחול ב-`init_db()` (`create_all`).
- **Migrations:** אין Alembic בפועל. יש בלוק "additive migrations" ידני ב-`main.py` שמריץ `ALTER TABLE` ל-SQLite (כי `create_all` לא מוסיף עמודות לטבלה קיימת). **מוסיפים עמודה חדשה? הוסיפו שם גם ALTER.**
- **מודל הרשאות רב-שכבתי:** `סביבה (workspace) → לוח (board) → פריט (item) → עמודה (column)`.
  - `_ws_role(db, user_id)` → תפקיד סביבה (admin/member/viewer). "מנהל מערכת" = ws-admin.
  - `_board_role(db, board_id, user_id)` → תפקיד בלוח (admin/editor/viewer). גישה מבוססת-חברוּת: רואים רק לוחות שהוזמנת אליהם.
  - `_is_board_admin`, `_item_perm`, `_can_comment` — בדיקות נוספות.

## 6. ארכיטקטורת ה-Frontend

- **קובץ יחיד `index.html`** — CSS ב-`<style>`, JS ב-`<script>`. אין bundler, אין import של קבצים מקומיים.
- **State גלובלי** באובייקט `st` (למשל `st.me`, `st.board`, `st.boards`, `st.users`, `st.wsMembers`).
- **קריאות API** דרך helper: `const api = async (p,o)=>{...}` (זורק Error עם הסטטוס אם לא-ok).
- **תבנית קוד:** אובייקטים גדולים לכל תחום — `AI`, `SysAdmin`, `Workspace`, `Members`, `Chat`, `Profile`, `Auth`, `ItemPerms`. UI נבנה כ-template strings ומוזרק ל-DOM. `showModal(html)` לחלונות.
- **עוזרים שימושיים:** `esc()` (escape), `avatarInner(user)` (אווטר), `toast()`, `askConfirm()`, `meId()`, `renderSidebar()`, `loadBoards()`, `openBoard(id)`.
- **תצוגות:** Dashboard, Kanban/טבלה, מפה, גרף, ויזואליזציות, בונה טפסים, Gantt, BIM 3D — כולן נבנות client-side מ-JSON.

## 7. אימות (Auth) — חשוב לדעת

**אין אימות אמיתי עדיין.** מסך ה-login הוא בחירת "בתור מי אני פועל/ת" (`Auth.login(id)` → נשמר ב-`localStorage.cc_uid`). כל קריאות ה-API מקבלות `user_id`/`actor_id` כפרמטר, והשרת אוכף הרשאות לפיו. כל התחברות מתועדת (`LoginEvent`) לצורך היסטוריית התחברות.

## 8. AI — שני מנגנונים (לא לבלבל!)

1. **הצ'אט שלנו (`AI` object)** — ווידג'ט צ'אט לבן (מסרגל הצד "CODE-CAL Agent"). פונה ל-`POST /api/ai/query` עם המודל **`kremer`** = DeepSeek עם **tool-calling בצד-שרת** (10 כלים: `create_board`, `create_task`, `update_task`, `delete_task`, `create_group`, `create_project`, `list_*`). השרת מבצע את הפעולות בפועל דרך `execute_ai_tool()`. אחרי פעולה ה-UI מתרענן (`AI.refreshUI`).
2. **page-agent** — כפתור הרובוט הצף (FAB). ספריית צד-שלישי (`alibaba/page-agent`) שנטענת מ-CDN ו**מפעילה את ה-DOM ויזואלית**. מדובקת לאייקון דרך `_paDock()`.
3. **ה-proxy:** `POST /api/llm/v1/chat/completions` — מזריק את `DEEPSEEK_API_KEY` **בצד-שרת בלבד**, כך שהמפתח לעולם לא מגיע לדפדפן. שני המנגנונים מדברים דרכו.
4. **swarm / Ollama** (`/api/swarm/think`, ה-path של `gemma4-coder` ב-`/api/ai/query`) — דורש Ollama מקומי, **בד"כ לא זמין** — נכשל בחן.

> ה-system prompt של הסוכן (ב-`ai_query`) מכוון: לפעול עם ברירות-מחדל כשיש מידע בסיסי, לא להמציא תוכן, ולשאול רק כשחסר משהו קריטי.

## 9. אווטרים

משתמש בלי תמונה מקבל אווטר מצויר מ**פּוּל מקומי** (`frontend/avatars/00.svg`..`29.svg`, סגנון BigHeads/MIT). השיוך דטרמיניסטי לפי שם, דרך `avatarInner(user)`. תמונה שהועלתה גוברת. הכל offline.

## 10. פיצ'רים עיקריים

ניהול לוחות/משימות/קבוצות/תגובות · תצוגות (טבלה/Kanban/לוח שנה/Gantt) · טפסים · מפה + תחבורה · גרף ידע · ויזואליזציות · BIM · פרויקטים/תקציב/אישורים/בקשות שינוי/KPIs/תלויות/מסמכים/תוכניות עבודה · דשבורדים (ראשי/מנכ"ל/מנהל אגף) · **אזור ניהול מערכת** (admin-only: דירקטורי משתמשים, שינוי תפקיד/מחלקה, טוגל פעיל/לא-פעיל, טאב היסטוריית התחברות) · צ'יפ בעלי לוח · אווטרים.

## 11. בדיקות

```bash
./run_tests.sh            # ~58 בדיקות pytest (רגרסיה)
./run_tests.sh -v         # מפורט
```
- **DB מבודד** (temp SQLite) — לא נוגע ב-`cityos.db` האמיתי.
- מריצים **לפני כל עליית גרסה**. פירוט מלא ב-[tests/README.md](tests/README.md).

## 12. Deployment

- **Git:** remote `mashcal` → `Mashcal-Projects/code-cal-missions` (העיקרי). קיים גם `origin` (fork אחר).
- **פרודקשן:** Vercel — https://code-cal-missions.vercel.app (serverless: `api/index.py` + `vercel.json`).
  - ⚠️ **הנתונים לא נשמרים בפרודקשן!** ה-DB יושב ב-`/tmp` ומתאפס ב-cold start. זה **דמו**. ל-persistence אמיתי צריך **Postgres חיצוני** (Neon/Supabase).
  - ⚠️ **לא לעשות deploy אוטומטי** — רק כשמבקשים במפורש.
- קיים גם config ל-**Railway** (`Procfile`, `railway.json`, `nixpacks.toml`) — הוסט מתאים יותר (שרת רץ-רציף, SQLite עובד).

## 13. מלכודות (Gotchas)

- **Frontend זה קובץ ענק אחד** — ערכו בזהירות, בדקו תחביר עם `node --check` על ה-JS הפנימי.
- **אין build** — לא לחפש webpack/vite. שינוי = refresh.
- **Migrations ידניות** — עמודה חדשה במודל דורשת גם `ALTER TABLE` בבלוק ה-migrations.
- **DeepSeek הוא ה-AI שעובד**; Ollama/swarm בד"כ לא. אל תסמכו על ה-path המקומי.
- **פרודקשן מאבד נתונים** ב-cold start — אל תבדקו persistence מול Vercel.
- **הרשאות נאכפות בשרת** — כל פעולה רגישה מקבלת `actor_id`/`user_id` ומאומתת מול `_ws_role`/`_board_role`.
