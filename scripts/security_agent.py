#!/usr/bin/env python3
"""
Security Agent — multi-scanner discovery + human-approved fixes (developer tool).

Scanners (all static / deterministic, no LLM):
  • sast    — source-code patterns via bandit (injection, eval, shell=True, …)
  • deps    — dependencies with known CVEs via pip-audit
  • secrets — hardcoded keys/passwords/tokens in git-tracked files
  • authz   — FastAPI endpoints that mutate data with no visible permission check
              (potential IDOR / missing-authorization)

Nothing is ever changed without an explicit per-fix "y". Only a small set of
mechanically-safe SAST fixes can be auto-applied; everything else is advice.

Usage:
  python scripts/security_agent.py scan                  # run every scanner
  python scripts/security_agent.py scan --only authz     # one scanner
  python scripts/security_agent.py scan --only sast,secrets
  python scripts/security_agent.py fix                   # approve mechanical SAST fixes
  python scripts/security_agent.py scan --json           # machine-readable

Exit code = number of HIGH findings (0 = clean) so it can gate CI.
"""
import argparse
import ast
import difflib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAST_TARGETS = ["backend", "scripts"]
ALL_SCANNERS = ["sast", "deps", "secrets", "authz"]

# ── terminal colour (auto-disabled when piped) ───────────────────────
_C = sys.stdout.isatty()
def c(t, code): return f"\033[{code}m{t}\033[0m" if _C else t
RED, YEL, GRN, DIM, BOLD, CYAN, MAG = "31", "33", "32", "2", "1", "36", "35"
SEV_COLOR = {"HIGH": RED, "MEDIUM": YEL, "LOW": DIM}
SEV_ICON = {"HIGH": "●", "MEDIUM": "●", "LOW": "○"}
SEV_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def rel(p):
    try: return os.path.relpath(p, ROOT)
    except ValueError: return p

def finding(scanner, severity, fid, title, file="", line=0, detail="", advice="", test_id=""):
    return {"scanner": scanner, "severity": severity, "id": fid, "title": title,
            "file": rel(file) if file else "", "line": line, "detail": detail,
            "advice": advice, "test_id": test_id}


# ════════════════════════ 1) SAST (bandit) ══════════════════════════
REMEDIATION = {
    "B101": "אל תשתמש ב-assert לאימות — מושמט ב-python -O. בדיקה מפורשת + חריגה.",
    "B105": "סוד מוקשח בקוד. העבר ל-משתנה סביבה (os.environ).",
    "B106": "סוד מוקשח כארגומנט. העבר ל-משתנה סביבה.",
    "B108": "נתיב /tmp צפוי. השתמש ב-tempfile.mkstemp/NamedTemporaryFile.",
    "B110": "except:pass מבליע שגיאות. תפוס חריגה ספציפית ורשום לוג.",
    "B112": "except:continue מבליע שגיאות. תפוס ספציפית ורשום לוג.",
    "B303": "hash לא בטוח (MD5/SHA1). לאבטחה עבור ל-hashlib.sha256.",
    "B324": "hash לא בטוח. עבור ל-sha256 (או usedforsecurity=False אם לא אבטחתי).",
    "B307": "eval() מסוכן. השתמש ב-ast.literal_eval.",
    "B310": "urlopen תומך גם ב-file://. ודא סכימה http/https בלבד לפני קריאה.",
    "B311": "random אינו קריפטוגרפי. לטוקנים השתמש ב-secrets.",
    "B404": "תזכורת: subprocess דורש זהירות (בלי shell=True, קלט מסונן).",
    "B602": "subprocess עם shell=True — הזרקת פקודות. העבר רשימת ארגומנטים בלי shell=True.",
    "B603": "subprocess עם קלט לא מהימן — סנן והימנע מ-shell.",
    "B608": "בניית SQL במחרוזת — SQL injection. השתמש בשאילתות פרמטריות / ORM.",
    "B501": "verify=False מבטל אימות אישור TLS. הסר.",
    "B113": "requests ללא timeout עלול להיתקע. הוסף timeout=<שניות>.",
    "B506": "yaml.load לא בטוח. השתמש ב-yaml.safe_load.",
    "B104": "האזנה ל-0.0.0.0 חושפת. הגבל ל-127.0.0.1 היכן שאפשר (בפרוד לרוב נדרש).",
}

def _fix_hash(line):
    o = (line.replace("hashlib.md5(", "hashlib.sha256(").replace("hashlib.sha1(", "hashlib.sha256(")
            .replace(".md5(", ".sha256(").replace(".sha1(", ".sha256("))
    return o if o != line else None
def _fix_yaml(line):
    return line.replace("yaml.load(", "yaml.safe_load(") if ("yaml.load(" in line and "safe_load" not in line and "Loader" not in line) else None
def _fix_verify(line):
    for p in ("verify=False", "verify = False"):
        if p in line: return line.replace(p, "verify=True")
    return None
FIXERS = [({"B303", "B324"}, _fix_hash, "MD5/SHA1 → SHA256 (אורך ה-digest משתנה)"),
          ({"B506"}, _fix_yaml, "yaml.load → yaml.safe_load"),
          ({"B501"}, _fix_verify, "verify=False → verify=True")]
def auto_fixer(test_id):
    for ids, fn, desc in FIXERS:
        if test_id in ids: return fn, desc
    return None, None

def scan_sast(targets):
    paths = [os.path.join(ROOT, t) for t in targets if os.path.exists(os.path.join(ROOT, t))]
    if not paths: return []
    proc = subprocess.run([sys.executable, "-m", "bandit", "-r", *paths, "-f", "json", "-q"],
                          capture_output=True, text=True)
    try: results = json.loads(proc.stdout or "{}").get("results", [])
    except json.JSONDecodeError: return []
    out = []
    for r in results:
        out.append(finding("sast", r["issue_severity"], r["test_id"], r["test_name"],
                           r["filename"], r["line_number"],
                           r["issue_text"], REMEDIATION.get(r["test_id"], ""), r["test_id"]))
    return out


# ════════════════════════ 2) DEPS (pip-audit) ═══════════════════════
def scan_deps():
    req = os.path.join(ROOT, "requirements.txt")
    cmd = [sys.executable, "-m", "pip_audit", "-f", "json"]
    if os.path.exists(req): cmd += ["-r", req]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception:
        return [finding("deps", "LOW", "deps-unavailable", "סריקת תלויות לא זמינה",
                        advice="pip-audit דורש רשת (OSV). נסי שוב עם חיבור.")]
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return [finding("deps", "LOW", "deps-unavailable", "סריקת תלויות נכשלה",
                        advice=(proc.stderr or "")[:200])]
    deps = data.get("dependencies", data if isinstance(data, list) else [])
    out = []
    for d in deps:
        for v in (d.get("vulns") or []):
            fixv = ", ".join(v.get("fix_versions") or []) or "אין תיקון פורסם"
            out.append(finding("deps", "MEDIUM", v.get("id", "CVE"),
                               f"{d.get('name')} {d.get('version')} — פגיע",
                               detail=(v.get("description") or "")[:160],
                               advice=f"שדרגי ל: {fixv}"))
    return out


# ════════════════════════ 3) SECRETS (regex) ════════════════════════
SECRET_PATTERNS = [
    ("מפתח פרטי (PEM)", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b")),
    ("Stripe Secret Key", re.compile(r"\bsk_live_[0-9A-Za-z]{16,}\b")),
    ("סוד גנרי בהשמה", re.compile(
        r"""(?ix)\b\w*(?:password|passwd|secret|apikey|api[_-]?key|access[_-]?key|
            auth[_-]?token|private[_-]?key|client[_-]?secret|token)\w*\b\s*[:=]\s*
            (['"])(?P<val>[^'"]{8,})\1""")),
]
# lines that clearly READ from env or are placeholders are safe
_SAFE = re.compile(r"(?i)os\.environ|getenv|process\.env|import\.meta\.env|"
                   r"['\"]?\s*(your[_-]|xxx|placeholder|example|changeme|<[^>]+>|\.\.\.)")
_SCAN_EXT = (".py", ".js", ".ts", ".html", ".sh", ".json", ".yml", ".yaml", ".env.example", ".txt", ".md")

def _git_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
        return [l for l in out.splitlines() if l.strip()]
    except Exception:
        return []

def scan_secrets():
    out = []
    for f in _git_files():
        if any(seg in f for seg in ("node_modules/", "GeoLibre/", "venv/", "tests/")): continue
        if not f.endswith(_SCAN_EXT): continue
        p = os.path.join(ROOT, f)
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if _SAFE.search(line): continue
            for name, rx in SECRET_PATTERNS:
                m = rx.search(line)
                if m:
                    val = (m.groupdict().get("val") or m.group(0))
                    masked = val[:4] + "…" + val[-2:] if len(val) > 8 else "…"
                    out.append(finding("secrets", "HIGH", "secret", name, p, i,
                                       f"ערך חשוד: {masked}",
                                       "הסר מהקוד, העבר ל-משתנה סביבה, ובטל/החלף (rotate) את הסוד."))
                    break
    return out


# ════════════════════════ 4) AUTHZ (AST heuristic) ══════════════════
AUTH_SIGNALS = ("_ws_role", "_cap(", "_board_role", "_env_role", "_can_manage_env",
                "_acting_user", "_can_comment", "_is_board_admin", "_item_perm",
                "_col_perm", "_visible_board_ids", "_require_board_edit", "403", "401")
MUTATING = {"post", "put", "patch", "delete"}
# endpoints that are intentionally public — reduce obvious noise (still reviewable)
PUBLIC_OK = {"/api/auth/login", "/api/upload"}

def scan_authz():
    p = os.path.join(ROOT, "backend", "main.py")
    if not os.path.exists(p): return []
    src = open(p, encoding="utf-8").read()
    try: tree = ast.parse(src)
    except SyntaxError: return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)): continue
            method = dec.func.attr.lower()
            if method not in MUTATING: continue
            path = ""
            if dec.args and isinstance(dec.args[0], ast.Constant): path = str(dec.args[0].value)
            if path in PUBLIC_OK: continue
            seg = ast.get_source_segment(src, node) or ""
            if any(sig in seg for sig in AUTH_SIGNALS): continue   # has a permission check
            out.append(finding("authz", "MEDIUM", "missing-authz",
                               f"{method.upper()} {path} — ללא בדיקת הרשאה נראית",
                               p, node.lineno,
                               "endpoint שמשנה נתונים בלי קריאה למנגנון הרשאות ידוע.",
                               "הוסף בדיקת הרשאה (למשל _cap/_board_role/_can_manage_env) או ודא שהוא ציבורי בכוונה (IDOR)."))
    return out


# ════════════════════════ report + fix ══════════════════════════════
SCAN_FN = {"sast": lambda: scan_sast(SAST_TARGETS), "deps": scan_deps,
           "secrets": scan_secrets, "authz": scan_authz}
SCAN_TITLE = {"sast": "קוד מקור (SAST · bandit)", "deps": "תלויות (CVE · pip-audit)",
              "secrets": "סודות ומפתחות", "authz": "הרשאות endpoints (IDOR)"}

def run(scanners):
    findings = []
    for s in scanners:
        try: findings += SCAN_FN[s]()
        except Exception as e:
            findings.append(finding(s, "LOW", "scanner-error", f"סורק {s} נכשל", detail=str(e)[:160]))
    return findings

def rank(fs):
    return sorted(fs, key=lambda r: (SEV_RANK.get(r["severity"], 3), r["scanner"], r["file"], r["line"]))

def print_report(findings, scanners):
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings: counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    print(c("\n══════════ דוח סריקת אבטחה ══════════", BOLD))
    print("סורקים: " + ", ".join(SCAN_TITLE[s] for s in scanners))
    print(f"סה\"כ {len(findings)} ממצאים — " + c(f"{counts['HIGH']} גבוה", RED) + " · "
          + c(f"{counts['MEDIUM']} בינוני", YEL) + " · " + c(f"{counts['LOW']} נמוך", DIM))
    for s in scanners:
        section = [f for f in findings if f["scanner"] == s]
        print(c(f"\n── {SCAN_TITLE[s]} ({len(section)}) ──", MAG))
        if not section:
            print(c("   ✓ נקי", GRN)); continue
        for i, f in enumerate(rank(section), 1):
            sev = f["severity"]
            fx = auto_fixer(f["test_id"])[0] if f["scanner"] == "sast" else None
            loc = f"  {f['file']}:{f['line']}" if f["file"] else ""
            print(f"{c(str(i)+'.', BOLD)} " + c(f"{SEV_ICON.get(sev,'•')} [{sev}]", SEV_COLOR.get(sev, DIM))
                  + f"  {f['id']} {f['title']}{loc}" + (c("  ⚙ תיקון-אוטומטי", CYAN) if fx else ""))
            if f["detail"]: print(c(f"   {f['detail']}", DIM))
            if f["advice"]: print(c(f"   ↳ {f['advice']}", GRN))
    print()

def apply_fixes(findings):
    fixable = [f for f in rank(findings) if f["scanner"] == "sast" and auto_fixer(f["test_id"])[0]]
    if not fixable:
        print(c("\nאין ממצאים עם תיקון אוטומטי בטוח — שאר הממצאים דורשים שיפוט ותיקון ידני (ראי המלצות).\n", YEL))
        return
    for f in fixable:
        fn, desc = auto_fixer(f["test_id"])
        path = os.path.join(ROOT, f["file"])
        with open(path, encoding="utf-8") as fh: lines = fh.readlines()
        idx = f["line"] - 1
        if not (0 <= idx < len(lines)): continue
        new = fn(lines[idx])
        if new is None: continue
        print(c("\n────────────────────────────", BOLD))
        print(f"[{f['severity']}] {f['id']} — {f['file']}:{f['line']} — {desc}")
        for d in difflib.unified_diff([lines[idx]], [new], fromfile="לפני", tofile="אחרי", lineterm=""):
            col = GRN if d.startswith("+") else (RED if d.startswith("-") else DIM)
            print("   " + c(d.rstrip("\n"), col))
        if input(c("   להחיל? [y/N] ", BOLD)).strip().lower() == "y":
            lines[idx] = new
            with open(path, "w", encoding="utf-8") as fh: fh.writelines(lines)
            print(c("   ✓ הוחל. בדקי git diff + הריצי טסטים.", GRN))
        else:
            print(c("   דילוג.", DIM))

def main():
    ap = argparse.ArgumentParser(description="Security agent — multi-scanner discovery + approved fixes.")
    ap.add_argument("mode", choices=["scan", "fix"])
    ap.add_argument("--only", help="רשימת סורקים מופרדת בפסיקים: " + ",".join(ALL_SCANNERS))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    scanners = [s.strip() for s in args.only.split(",")] if args.only else ALL_SCANNERS
    scanners = [s for s in scanners if s in ALL_SCANNERS] or ALL_SCANNERS
    findings = run(scanners)
    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2)); return
    print_report(findings, scanners)
    if args.mode == "fix": apply_fixes(findings)
    sys.exit(sum(1 for f in findings if f["severity"] == "HIGH"))

if __name__ == "__main__":
    main()
