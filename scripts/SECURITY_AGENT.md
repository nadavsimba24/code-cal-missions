# Security Agent — סוכן גילוי ותיקון פרצות (SAST)

כלי פיתוח שרץ מהטרמינל (לא חלק מהאפליקציה הרצה). מריץ ארבעה מנועי סריקה סטטיים,
מדרג ממצאים לפי חומרה, ומתקן **רק אחרי אישור פר-ממצא**.

## מנועי הסריקה
| מנוע | מה בודק | כלי |
|------|---------|-----|
| `sast` | דפוסי קוד מסוכנים (injection, eval, shell=True) | bandit |
| `deps` | תלויות עם CVE ידוע | pip-audit |
| `secrets` | מפתחות/סיסמאות מוקשחים בקבצי git | regex פנימי |
| `authz` | endpoints שמשנים נתונים בלי בדיקת הרשאה (IDOR) | ניתוח AST של הראוטים |

## התקנה (חד-פעמית)
```bash
./venv/bin/pip install -r requirements-dev.txt   # כולל bandit
```

## שימוש
```bash
# גילוי בלבד — כל הסורקים, דוח מדורג
./venv/bin/python scripts/security_agent.py scan

# סורק בודד / כמה סורקים
./venv/bin/python scripts/security_agent.py scan --only authz
./venv/bin/python scripts/security_agent.py scan --only sast,secrets

# תיקון עם אישור — לכל תיקון מכני: מציג diff ושואל y/N לפני החלה
./venv/bin/python scripts/security_agent.py fix

# פלט גולמי (JSON)
./venv/bin/python scripts/security_agent.py scan --json
```

## איך זה עובד
1. **גילוי** — `bandit -r backend scripts` → ממצאים עם חומרה, קובץ, שורה ותיאור.
2. **דירוג** — לפי חומרה (גבוה→נמוך) ואז ודאות.
3. **המלצה** — לכל ממצא מוצגת המלצת תיקון מתוך בסיס-ידע פנימי (לפי מזהה bandit).
4. **תיקון מבוקר** — לתת-קבוצה של ממצאים עם תיקון **מכני ובטוח** (למשל MD5/SHA1→SHA256,
   `yaml.load`→`yaml.safe_load`, החזרת `verify=True`) הכלי מציג diff ומחיל **רק** אחרי `y`.
   ממצאים שדורשים שיפוט (למשל `shell=True`, SQL דינמי) מקבלים המלצה בלבד — לא נערכים אוטומטית.

## עקרונות בטיחות
- **שום שינוי בלי אישור מפורש** (`y`) פר-תיקון.
- שינויים מכניים בלבד ובשורה שדווחה — לעולם לא כתיבה-מחדש של לוגיקה.
- אחרי כל תיקון: בדקו `git diff` והריצו `./run_tests.sh`.
- **קוד היציאה** = מספר ממצאי החומרה הגבוהה (0 = נקי) — נוח לשער CI.

## הרחבה
להוספת המלצה: ערכו את `REMEDIATION` ב-[security_agent.py](security_agent.py).
להוספת תיקון-אוטומטי בטוח: הוסיפו פונקציית `_fix_*` ורשומה ב-`FIXERS`.
