# CityOS — React POC (מסך Kanban)

הוכחת יכולת למעבר ה-frontend ל-**React + Vite**. מממש את מסך ה-Kanban בלבד, וצורך את ה-API הקיים **ללא שום שינוי ב-backend**. האפליקציה הישנה (`frontend/index.html`) לא נגעה.

## הרצה

```bash
# 1. הפעל את ה-backend (בטרמינל אחר)
cd ../backend && python main.py        # http://localhost:8000

# 2. הפעל את ה-POC
npm install
npm run dev                            # http://localhost:5173 (מדלג לפורט פנוי הבא אם תפוס)
```

ה-dev server מבצע proxy ל-`/api`, `/avatars`, `/uploads` אל ה-backend על :8000 (ראה `vite.config.js`), כך שאין CORS ואין צורך בשינויי שרת.

## מבנה

```
src/
  main.jsx              נקודת כניסה
  App.jsx               טעינת לוחות + לוח פעיל (state)
  api.js                helper ל-fetch + STATUS/PRIORITY + avatarUrl
  styles.css            עיצוב (RTL)
  components/
    Sidebar.jsx         רשימת לוחות
    BoardView.jsx       Kanban — קבוצות כעמודות
    TaskCard.jsx        כרטיס משימה (סטטוס, עדיפות, אחראים, יעד)
```

## מה זה מוכיח
- אפשר לבנות React מודרני (קומפוננטות + state) מעל ה-API הקיים.
- ה-backend נשאר כמו שהוא — המעבר הוא frontend בלבד.
- feature parity מלא = כתיבה מחדש של כל התצוגות/המודלים (מאמץ רב) — זה המדגם למסך אחד.
