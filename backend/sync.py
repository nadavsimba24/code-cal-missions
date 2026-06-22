#!/usr/bin/env python3
"""
CODE-CAL MISSIONS — reconciler / sync guard.
Keeps OpenClaw's data work and the dev session's product work consistent:
  1. Recolors any PURPLE board/group in the DB to the monday.com palette.
  2. Verifies the hard invariants (branding, fonts, DeepSeek agent) on disk.
Run after any change to cityos:  python backend/sync.py
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from sqlalchemy.orm import Session
from models import init_db, Board, Group

APP = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(os.path.dirname(__file__), "cityos.db")

# known purple/indigo hexes -> monday replacements (NO purple allowed)
PURPLES = {
    "#7c3aed": "#0073ea", "#6366f1": "#0073ea", "#8b5cf6": "#579bfc",
    "#a25ddc": "#579bfc", "#9333ea": "#0073ea", "#7e22ce": "#0073ea",
    "#6d28d9": "#0073ea", "#5559df": "#0073ea", "#818cf8": "#579bfc",
    "#4f46e5": "#0073ea", "#a855f7": "#579bfc", "#c084fc": "#579bfc",
}
def fix_color(c):
    return PURPLES.get((c or "").strip().lower())

def reconcile_db():
    if not os.path.exists(DB_PATH):
        print("  (no DB yet)"); return 0
    engine = init_db(f"sqlite:///{DB_PATH}")
    changed = 0
    with Session(engine) as db:
        for tbl in (Board, Group):
            for row in db.query(tbl).all():
                nc = fix_color(row.color)
                if nc:
                    print(f"  recolor {tbl.__name__} '{getattr(row,'name','')}': {row.color} -> {nc}")
                    row.color = nc; changed += 1
        if changed:
            db.commit()
    return changed

def check_invariants():
    def read(p):
        try: return open(os.path.join(APP, p), encoding="utf-8").read()
        except: return ""
    idx = read("frontend/index.html"); main = read("backend/main.py"); env = read(".env")
    checks = [
        ("שם CODE-CAL MISSIONS ב-UI", "CODE-CAL MISSIONS" in idx and "CityOS" not in idx),
        ("פונט Figtree", "Figtree" in idx), ("פונט Rubik", "Rubik" in idx),
        ("טרמינל", 'id="term"' in idx),
        ("שם CODE-CAL MISSIONS ב-backend", "CODE-CAL MISSIONS" in main),
        ("סוכן DeepSeek (קרמר)", "kremer" in main and "deepseek" in main),
        ("סוכן Gemini (איליין)", "elaine" in main and "gemini" in main),
        ("מפתח DEEPSEEK ב-.env", "DEEPSEEK_API_KEY=sk-" in env),
        ("מפתח GEMINI ב-.env", "GEMINI_API_KEY=AIzaSy" in env),
    ]
    ok = True
    for name, passed in checks:
        print(f"  {'✓' if passed else '✗ דריסה!'} {name}")
        ok = ok and passed
    return ok

if __name__ == "__main__":
    print("=== CODE-CAL MISSIONS sync ===")
    print("[1] תיקון צבעים סגולים ב-DB:")
    n = reconcile_db()
    print(f"    => {n} תוקנו" if n else "    => אין סגול, נקי")
    print("[2] אימות invariants (בדיסק):")
    ok = check_invariants()
    print("=== " + ("הכל מסונכרן ✓" if ok and True else "⚠️ יש דריסות — צריך לתקן") + " ===")
    sys.exit(0 if ok else 1)
