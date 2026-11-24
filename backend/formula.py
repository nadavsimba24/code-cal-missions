"""The formula column, evaluated here as well as in the browser.

A formula reads "{שם עמודה}" references and works out one value per item.
Until now it was worked out in ONE place — `evalFormula` in index.html — and
the server said so in as many words: a formula column could not be asked
about at all. That was tenable while a formula was something you looked at.
It stops being tenable the moment a dashboard sums one, because R03 requires
the calculation to run "על כל הרשומות המתאימות, לא על עמוד הרשימה או על
נתונים שנטענו לדפדפן" and R01 requires permissions enforced on the server.

So this is a second engine, and the obligation that comes with a second
engine is that it agrees with the first. `tests/test_formula_parity.py`
compares the two expression by expression rather than trusting that they
were kept in step by hand — the same arrangement `tests/test_filter_ast.py`
has for the filter's operator table.

── three differences from the browser's engine, each of them deliberate ──

**A formula that fails is not empty.** `evalFormula` ends in
`catch(e){ return null; }`, so a reference to a deleted column, a division by
zero and a syntax error all come back as a blank cell. In a grid that is a
reasonable thing to show. In a sum it is a lie: DASH-09.1 — "פלט נוסחה שאינו
מספרי או שיש בו שגיאה אינו ערך תקין לחישוב; אין להתייחס אליו כאל ריק בלי
להתריע" — so the three states are kept apart here and the caller is told
which one it got.

**Nothing is rounded.** The browser rounds to two decimals on the way out,
because that is a display. R03 forbids intermediate rounding, and a sum of
rounded values is not the rounded sum.

**"היום" is not the server's day.** `TODAY()` is passed in rather than read
off the clock, because R07 puts periods in the organisation's timezone and a
formula that disagreed with the filter beside it would make two numbers on
one screen contradict each other.
"""
import datetime as _dt
import math
import re

MAX_LEN = 2000          # a formula longer than this is not one anybody typed
MAX_DEPTH = 32          # untrusted text shaped like a program — see filter_ast


class FormulaError(ValueError):
    """The formula could not be worked out. Never silently a blank."""


# ── value coercions, ported from the browser one for one ────────────────────

def _fnum(v):
    if v is True:
        return 1
    if v is False or v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else 0
    try:
        n = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0
    return n if math.isfinite(n) else 0


def _ftext(v):
    if v is None:
        return ""
    if v is True:
        return "TRUE"
    if v is False:
        return "FALSE"
    if isinstance(v, (int, float)):
        # the browser prints a number without its float noise, and a whole
        # number without a trailing ".0" — `String(12)` is "12", not "12.0"
        r = round(float(v) * 1e10) / 1e10
        return str(int(r)) if r == int(r) else repr(r)
    return str(v)


def _ftruthy(v):
    """blank, zero and FALSE are false; everything else is true."""
    if v is None or v is False or v == "":
        return False
    if v is True:
        return True
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip()
    return s != "" and s != "0" and s.upper() != "FALSE"


_ISO_D = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _fdate(v):
    if v is None or v == "":
        return None
    s = str(v).strip()
    m = _ISO_D.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DMY.match(s)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return _dt.date(y, mo, d)
    except ValueError:
        return None


_NUMERIC_TEXT = re.compile(r"^[\d.,\s-]+$")


def _is_numberish(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if v is None or v == "":
        return False
    s = str(v)
    if not _NUMERIC_TEXT.match(s):
        return False
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


def _fcmp(a, b):
    """Numbers compare as numbers, everything else as text — so {סטטוס}="בוצע"
    works and {שעות}>8 does too."""
    if _is_numberish(a) and _is_numberish(b):
        x, y = _fnum(a), _fnum(b)
        return -1 if x < y else (1 if x > y else 0)
    x, y = _ftext(a), _ftext(b)
    return -1 if x < y else (1 if x > y else 0)


def _fround(n, d=0):
    k = 10 ** max(0, min(10, int(_fnum(d))))
    x = _fnum(n) * k
    # JS Math.round is half-up, Python's round() is half-to-even: round(0.5)
    # is 1 there and 0 here, so ROUND(0.5) would disagree between the two
    # engines on exactly the value anybody would test it with.
    return math.floor(x + 0.5) / k


def _fceilfloor(n, d, how):
    k = 10 ** max(0, min(10, int(_fnum(d))))
    return how(_fnum(n) * k) / k


def _fflat(args):
    out = []
    for a in args:
        out.extend(a) if isinstance(a, list) else out.append(a)
    return out


def _pad(n):
    return str(n).zfill(2)


def _div(a, b):
    d = _fnum(b)
    return None if d == 0 else _fnum(a) / d


def _search(needle, hay):
    """1-based like a spreadsheet, 0 when it is not there."""
    return _ftext(hay).lower().find(_ftext(needle).lower()) + 1


def _days(a, b):
    x, y = _fdate(a), _fdate(b)
    return (x - y).days if (x and y) else None


def _add_days(d, n):
    x = _fdate(d)
    return (x + _dt.timedelta(days=int(_fnum(n)))).isoformat() if x else None


def _average(*a):
    v = _fflat(a)
    return (sum(_fnum(x) for x in v) / len(v)) if v else None


def _minmax(a, how):
    v = [_fnum(x) for x in _fflat(a)]
    return how(v) if v else None


def _if(c, a, b=None):
    return a if _ftruthy(c) else b


def _left(a, n=1):
    return _ftext(a)[:max(0, int(_fnum(n)))]


def _right(a, n=1):
    k = max(0, int(_fnum(n)))
    return _ftext(a)[-k:] if k else ""


def _sqrt(n):
    x = _fnum(n)
    return math.sqrt(x) if x >= 0 else None


def _subtract(a, b):
    return _fnum(a) - _fnum(b)


def _format_date(d):
    x = _fdate(d)
    return f"{_pad(x.day)}/{_pad(x.month)}/{x.year}" if x else None


# The function table, and it is the contract: the importer reads the browser's
# copy of this to decide whether a formula can live in this system at all, so
# a name here that is not there (or the other way round) is a formula that
# imports and then cannot be computed. The parity test compares the two.
FUNCS = {
    # ── numbers ──
    "ROUND": _fround,
    "ROUNDUP": lambda n, d=0: _fceilfloor(n, d, math.ceil),
    "ROUNDDOWN": lambda n, d=0: _fceilfloor(n, d, math.floor),
    "ABS": lambda n: abs(_fnum(n)),
    "SQRT": _sqrt,
    "POWER": lambda a, b: _fnum(a) ** _fnum(b),
    "SUM": lambda *a: sum(_fnum(x) for x in _fflat(a)),
    "AVERAGE": _average,
    "MIN": lambda *a: _minmax(a, min),
    "MAX": lambda *a: _minmax(a, max),
    "ADD": lambda a, b: _fnum(a) + _fnum(b),
    "SUBTRACT": _subtract,
    # monday calls the same thing MINUS, and a board that was written there
    # arrives using it. The same implementation under both names: two of them
    # would be two places for the next change to the first one to miss.
    "MINUS": _subtract,
    "MULTIPLY": lambda a, b: _fnum(a) * _fnum(b),
    "DIVIDE": _div,
    # ── logic ──
    "IF": _if,
    "AND": lambda *a: all(_ftruthy(x) for x in _fflat(a)),
    "OR": lambda *a: any(_ftruthy(x) for x in _fflat(a)),
    "NOT": lambda a: not _ftruthy(a),
    "TRUE": lambda: True,
    "FALSE": lambda: False,
    # ── text ──
    "CONCATENATE": lambda *a: "".join(_ftext(x) for x in _fflat(a)),
    "TEXT": _ftext,
    "LEN": lambda a: len(_ftext(a)),
    "LEFT": _left,
    "RIGHT": _right,
    "UPPER": lambda a: _ftext(a).upper(),
    "LOWER": lambda a: _ftext(a).lower(),
    "TRIM": lambda a: _ftext(a).strip(),
    "SEARCH": _search,
    # ── dates ── a date is an ISO string, which is how the board stores one ──
    "TODAY": None,          # bound per evaluation — see `today` below
    "DAYS": _days,
    "ADD_DAYS": _add_days,
    "YEAR": lambda d: (_fdate(d).year if _fdate(d) else None),
    "MONTH": lambda d: (_fdate(d).month if _fdate(d) else None),
    "DAY": lambda d: (_fdate(d).day if _fdate(d) else None),
    "FORMAT_DATE": _format_date,
}

_OPS = ("<=", ">=", "<>", "!=", "==", "+", "-", "*", "/", "(", ")", ",", "<", ">", "=")
# The browser's character classes, spelled out: Latin letters, digits and the
# Hebrew block U+0590–U+05FF, which is what `֐-׿` is in that regex.
_NAME_START = re.compile(r"[A-Za-z_֐-׿]")
_NAME_CHAR = re.compile(r"[A-Za-z0-9_.֐-׿]")


def tokens(src):
    out, i = [], 0
    s = str(src or "")
    if len(s) > MAX_LEN:
        raise FormulaError("הנוסחה ארוכה מדי")
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "{":
            j = s.find("}", i)
            if j < 0:
                raise FormulaError("סוגר } חסר")
            out.append(("ref", s[i + 1:j].strip()))
            i = j + 1
            continue
        if ch in ('"', "'"):
            j = s.find(ch, i + 1)
            if j < 0:
                raise FormulaError("מרכאות לא נסגרו")
            out.append(("str", s[i + 1:j]))
            i = j + 1
            continue
        if ch.isdigit() or ch == ".":
            n = ""
            while i < len(s) and (s[i].isdigit() or s[i] == "."):
                n += s[i]
                i += 1
            try:
                out.append(("num", float(n)))
            except ValueError:
                raise FormulaError("מספר לא תקין: " + n)
            continue
        if _NAME_START.match(ch):
            w = ""
            while i < len(s) and _NAME_CHAR.match(s[i]):
                w += s[i]
                i += 1
            out.append(("name", w))
            continue
        op = next((o for o in _OPS if s.startswith(o, i)), None)
        if op is None:
            raise FormulaError("תו לא מוכר: " + ch)
        out.append(("op", op))
        i += len(op)
    return out


_CMP = {
    "=": lambda c: c == 0, "==": lambda c: c == 0,
    "<>": lambda c: c != 0, "!=": lambda c: c != 0,
    ">": lambda c: c > 0, "<": lambda c: c < 0,
    ">=": lambda c: c >= 0, "<=": lambda c: c <= 0,
}


def evaluate(src, lookup, today=None):
    """Work the formula out, or raise FormulaError. Never returns "probably".

    `lookup(reference)` is handed each "{…}" and answers with that column's
    value for this item. It is expected to RAISE for a reference it cannot
    resolve: a formula over a column that is gone is wrong, and answering 0
    for it would show a confident number computed from something missing.
    """
    tk = tokens(src)
    pos = [0]
    depth = [0]

    def peek():
        return tk[pos[0]] if pos[0] < len(tk) else None

    def eat(v):
        t = peek()
        if not t or t[0] != "op" or t[1] != v:
            raise FormulaError("חסר " + v)
        pos[0] += 1

    def expr():
        depth[0] += 1
        if depth[0] > MAX_DEPTH:
            raise FormulaError("הנוסחה מקוננת עמוק מדי")
        try:
            v = add()
            while True:
                t = peek()
                if not (t and t[0] == "op" and t[1] in _CMP):
                    return v
                op = tk[pos[0]][1]
                pos[0] += 1
                v = _CMP[op](_fcmp(v, add()))
        finally:
            depth[0] -= 1

    def add():
        v = mul()
        while True:
            t = peek()
            if not (t and t[0] == "op" and t[1] in ("+", "-")):
                return v
            op = tk[pos[0]][1]
            pos[0] += 1
            r = mul()
            v = _fnum(v) + _fnum(r) if op == "+" else _fnum(v) - _fnum(r)

    def mul():
        v = unary()
        while True:
            t = peek()
            if not (t and t[0] == "op" and t[1] in ("*", "/")):
                return v
            op = tk[pos[0]][1]
            pos[0] += 1
            r = unary()
            if op == "*":
                v = _fnum(v) * _fnum(r)
            else:
                d = _fnum(r)
                if d == 0:
                    raise FormulaError("חלוקה באפס")
                v = _fnum(v) / d

    def unary():
        t = peek()
        if t and t[0] == "op" and t[1] == "-":
            pos[0] += 1
            return -_fnum(unary())
        return primary()

    def primary():
        t = peek()
        if t is None:
            raise FormulaError("ביטוי חסר")
        kind, val = t
        if kind in ("num", "str"):
            pos[0] += 1
            return val
        if kind == "ref":
            pos[0] += 1
            return lookup(val)
        if kind == "op" and val == "(":
            pos[0] += 1
            v = expr()
            eat(")")
            return v
        if kind == "name":
            name = val.upper()
            pos[0] += 1
            if name not in FUNCS:
                raise FormulaError("פונקציה לא מוכרת: " + val)
            args = []
            t2 = peek()
            if t2 and t2[0] == "op" and t2[1] == "(":
                pos[0] += 1
                t3 = peek()
                if not (t3 and t3[0] == "op" and t3[1] == ")"):
                    args.append(expr())
                    while True:
                        t4 = peek()
                        if not (t4 and t4[0] == "op" and t4[1] == ","):
                            break
                        pos[0] += 1
                        args.append(expr())
                eat(")")
            if name == "TODAY":
                # Never the server's own day — see the module docstring.
                return (today or _dt.date.today()).isoformat()
            try:
                return FUNCS[name](*args)
            except FormulaError:
                raise
            except TypeError:
                raise FormulaError(f"מספר ארגומנטים שגוי ל־{val}")
            except (ValueError, ArithmeticError, OverflowError) as e:
                raise FormulaError(f"שגיאה ב־{val}: {e}")
        raise FormulaError("ביטוי לא תקין")

    out = expr()
    if pos[0] < len(tk):
        raise FormulaError("טקסט מיותר בסוף הנוסחה")
    return out


def number_of(src, lookup, today=None):
    """The formula as a number, or why it is not one.

    Returns ("value", float) · ("empty", None) · ("error", reason).

    The three are kept apart because a sum has to treat them differently and
    only the caller knows how: a blank is governed by the widget's empty
    policy (R03), and an error is not a blank at all — "שגיאה והרשאה חסרה
    אינן ערך ריק".
    """
    try:
        v = evaluate(src, lookup, today)
    except FormulaError as e:
        return ("error", str(e))
    if v is None or v == "":
        return ("empty", None)
    if isinstance(v, bool):
        # A formula that answers TRUE is not a quantity. The grid prints a
        # tick for it; a sum must say so rather than silently counting it 1.
        return ("error", "פלט הנוסחה אינו מספר")
    if isinstance(v, (int, float)):
        return ("value", float(v)) if math.isfinite(v) else ("error", "פלט הנוסחה אינו סופי")
    if _is_numberish(v):
        return ("value", _fnum(v))
    return ("error", "פלט הנוסחה אינו מספר")
