"""The two formula engines must agree, expression by expression.

A formula is now worked out in two places: `evalFormula` in index.html, which
draws the cell, and `backend/formula.py`, which a dashboard sums. Two engines
that drift apart are worse than one engine that cannot do the job, because
the disagreement shows up as a total that does not match the column it was
added from — and neither number looks wrong on its own.

So this does not test the server engine against expectations somebody typed.
It runs every case through the REAL browser engine, cut out of index.html by
`tests/frontend/formula_compare.mjs`, and compares. The same arrangement
`tests/test_filter_ast.py` has for the filter's operator table, and for the
same reason: a table kept in step by hand stops being in step.

The deliberate differences are asserted separately at the bottom, so that
"these two disagree here, on purpose, for this reason" is written down
rather than left as a gap in the coverage.
"""
import json
import subprocess
import pathlib
import pytest

import formula

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "formula_compare.mjs"

# Each case is (expression, references). The references are what the item
# holds, so a blank cell is a None and a number is a number.
CASES = [
    # ── arithmetic and precedence ──
    ("1+2*3", {}),
    ("(1+2)*3", {}),
    ("10-4-3", {}),
    ("2*3/4", {}),
    ("-5+2", {}),
    ("-{a}", {"a": 7}),
    ("2.5*4", {}),
    # ── references ──
    ("{a}+{b}", {"a": 10, "b": 32}),
    ("{a}*2", {"a": 21}),
    ("{a}+1", {"a": None}),           # a blank reference is zero in arithmetic
    ("{a}+1", {"a": ""}),
    ("{a}+1", {"a": "12"}),           # a numeric string is a number
    ("{a}+1", {"a": "1,200"}),        # thousands separators are not text
    ("{שעות בפועל}*2", {"שעות בפועל": 3}),   # Hebrew names, spaces included
    # ── rounding ──
    ("ROUND(2.345,2)", {}),
    ("ROUND(2.5)", {}),               # half-up in both, not half-to-even
    ("ROUND(-2.5)", {}),
    ("ROUNDUP(2.01,1)", {}),
    ("ROUNDDOWN(2.09,1)", {}),
    ("ABS(-7)", {}),
    ("SQRT(16)", {}),
    ("POWER(2,10)", {}),
    # ── aggregates over arguments ──
    ("SUM(1,2,3)", {}),
    ("AVERAGE(2,4,6)", {}),
    ("MIN(3,1,2)", {}),
    ("MAX(3,1,2)", {}),
    ("ADD(1,2)", {}),
    ("SUBTRACT(5,2)", {}),
    ("MULTIPLY(3,4)", {}),
    ("DIVIDE(10,4)", {}),
    ("DIVIDE(1,0)", {}),              # the function answers null, it does not throw
    # ── logic ──
    ('IF({a}>5,"גבוה","נמוך")', {"a": 9}),
    ('IF({a}>5,"גבוה","נמוך")', {"a": 1}),
    ("IF({a}>5,1,0)", {"a": 9}),
    ("IF({a},1,0)", {"a": 0}),        # zero is false
    ("IF({a},1,0)", {"a": "0"}),      # and so is the string "0"
    ("AND(1,1)", {}),
    ("OR(0,1)", {}),
    ("NOT(0)", {}),
    # ── comparison: numbers as numbers, everything else as text ──
    ("{a}>8", {"a": 9}),
    ("{a}=8", {"a": 8}),
    ("{a}<>8", {"a": 9}),
    ('{s}="בוצע"', {"s": "בוצע"}),
    ('{s}="בוצע"', {"s": "בטיפול"}),
    # ── text ──
    ('CONCATENATE("א","ב")', {}),
    ('LEN("שלום")', {}),
    ('LEFT("שלום",2)', {}),
    ('RIGHT("שלום",2)', {}),
    ('UPPER("abc")', {}),
    ('LOWER("ABC")', {}),
    ('TRIM("  x  ")', {}),
    ('SEARCH("ל","שלום")', {}),
    ('SEARCH("z","שלום")', {}),
    ('TEXT({a})', {"a": 12}),
    # ── dates ──
    ('DAYS("2026-03-10","2026-03-01")', {}),
    ('ADD_DAYS("2026-03-01",9)', {}),
    ('YEAR("2026-03-10")', {}),
    ('MONTH("2026-03-10")', {}),
    ('DAY("2026-03-10")', {}),
    ('FORMAT_DATE("2026-03-10")', {}),
    ('YEAR("לא תאריך")', {}),
    # ── nesting ──
    ("ROUND(AVERAGE({a},{b}),1)", {"a": 1, "b": 2}),
    ('IF(AND({a}>0,{b}>0),DIVIDE({a},{b}),0)', {"a": 10, "b": 4}),
    # ── things that are wrong ──
    ("1/0", {}),                      # the operator throws where DIVIDE does not
    ("{missing}", {}),                # a reference the item has no column for
    ("NOPE(1)", {}),                  # a function neither engine has
    ("1+", {}),
    ("(1+2", {}),
    ("1 2", {}),
    ('"unclosed', {}),
    ("{unclosed", {}),
    ("@", {}),
]


def _browser(cases):
    payload = json.dumps([{"src": s, "refs": r} for s, r in cases],
                         ensure_ascii=False)
    r = subprocess.run(["node", str(HARNESS), payload],
                       capture_output=True, text=True)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
    return json.loads(r.stdout)


def _server(src, refs):
    def lookup(ref):
        if ref not in refs:
            raise formula.FormulaError("אין עמודה בשם " + ref)
        return refs[ref]
    try:
        return {"ok": True, "value": formula.evaluate(src, lookup)}
    except formula.FormulaError as e:
        return {"ok": False, "error": str(e)}


def _same(a, b):
    """Equal, allowing for float noise and for JS printing 7 where Python
    prints 7.0 — the engines agree on the number, not on its spelling."""
    if a is None or b is None:
        return a is b or a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return str(a) == str(b)


@pytest.mark.parametrize("src,refs", CASES, ids=[c[0] for c in CASES])
def test_the_server_engine_answers_what_the_browser_engine_answers(src, refs):
    want = _browser([(src, refs)])[0]
    got = _server(src, refs)
    assert got["ok"] == want["ok"], f"{src!r}: browser={want} server={got}"
    if want["ok"]:
        assert _same(got["value"], want["value"]), \
            f"{src!r}: browser={want['value']!r} server={got['value']!r}"


def test_every_function_the_browser_offers_exists_here_too():
    """The function table is the contract the importer reads to decide whether
    a formula can live in this system. A name on one side only is a formula
    that imports and then cannot be computed."""
    src = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    block = src[src.index("const FORMULA_FUNCS = {"):]
    block = block[:block.index("\n};")]
    import re
    names = set(re.findall(r"^\s{2}([A-Z_]+):", block, re.M))
    assert names, "the browser's function table could not be read"
    assert names == set(formula.FUNCS), (
        f"only in the browser: {sorted(names - set(formula.FUNCS))} · "
        f"only on the server: {sorted(set(formula.FUNCS) - names)}")


# ── the differences that are on purpose ─────────────────────────────────────

def test_the_server_does_not_round_the_way_the_cell_does():
    """`evalFormula` ends in Math.round(r*100)/100 because it is drawing a
    cell. R03 forbids intermediate rounding, so the engine the dashboard sums
    through keeps the whole value and lets the display round it."""
    v = formula.evaluate("DIVIDE(1,3)", lambda r: None)
    assert v == pytest.approx(1 / 3)
    assert round(v, 2) != v


def test_an_error_is_not_a_blank():
    """The browser's catch(e){return null} is right for a grid and wrong for a
    total — DASH-09.1, "אין להתייחס אליו כאל ריק בלי להתריע"."""
    assert formula.number_of("1/0", lambda r: None)[0] == "error"
    assert formula.number_of("{gone}", lambda r: (_ for _ in ()).throw(
        formula.FormulaError("אין עמודה"))) [0] == "error"
    assert formula.number_of("{a}", lambda r: None)[0] == "empty"
    assert formula.number_of("{a}", lambda r: 5) == ("value", 5.0)


def test_a_formula_that_answers_text_is_not_a_quantity():
    """A sum over it must say so rather than silently counting it zero."""
    kind, why = formula.number_of('CONCATENATE("א","ב")', lambda r: None)
    assert kind == "error" and "מספר" in why


def test_today_is_passed_in_not_read_off_the_clock():
    """R07 puts periods in the organisation's timezone. A formula reading the
    server's own day would disagree with the filter beside it."""
    import datetime
    d = datetime.date(2026, 3, 10)
    assert formula.evaluate("TODAY()", lambda r: None, today=d) == "2026-03-10"
    assert formula.evaluate("YEAR(TODAY())", lambda r: None, today=d) == 2026
