"""The formula engine, and the importer's judgement of what it can run.

A migrated board arrives with IF, ROUND and CONCATENATE in its formulas. Those
used to be unrunnable here, so the column came in as monday's frozen answer.
The engine now implements them — and the importer's list of what it implements
has to stay equal to the engine's own, or a formula is either imported and blank
or frozen when it would have worked.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

import import_monday

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "formula_engine.mjs"
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_the_engine_computes_what_it_claims_to():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def _engine_function_names():
    """The keys of FORMULA_FUNCS, read out of the page itself."""
    start = SRC.index("const FORMULA_FUNCS = {")
    depth, i = 0, SRC.index("{", start)
    for j in range(i, len(SRC)):
        if SRC[j] == "{":
            depth += 1
        elif SRC[j] == "}":
            depth -= 1
            if depth == 0:
                body = SRC[i:j]
                break
    # a key is a NAME at the start of a line inside the table
    return {m.group(1) for m in re.finditer(r"^\s{2}([A-Z_][A-Z_0-9]*)\s*:", body, re.M)}


def test_the_importer_and_the_engine_agree_on_the_function_list():
    engine = _engine_function_names()
    importer = set(import_monday.FORMULA_FUNCS)
    assert engine, "the engine's function table was not found"
    assert engine == importer, (
        f"only in the engine: {sorted(engine - importer)} · "
        f"only in the importer: {sorted(importer - engine)}")


def test_the_functions_a_monday_board_arrives_with_are_supported():
    """The ones that actually showed up in the board being migrated."""
    for f in ("IF", "ROUND", "CONCATENATE", "DAYS", "TODAY", "SUM", "AVERAGE", "MAX"):
        assert f in import_monday.FORMULA_FUNCS


def test_a_formula_using_only_supported_functions_is_computable():
    for expr in ('{א} * 2',
                 'IF({ימים} < 30, "בזמן", "באיחור")',
                 'ROUND({א} / {ב}, 2)',
                 'CONCATENATE({א}, " - ", {ב})',
                 'IF(AND({א} > 0, {ב} > 0), ROUND({א} / {ב}, 1), "—")',
                 'DAYS(TODAY(), {תאריך})',
                 'MAX({א}, {ב}) - MIN({א}, {ב})'):
        assert import_monday.formula_unsupported(expr) == [], expr


def test_an_unsupported_function_is_named_not_just_refused():
    """"uses SWITCH" is actionable; "not supported" is not."""
    assert import_monday.formula_unsupported('SWITCH({א}, 1, "a")') == ["SWITCH"]
    assert import_monday.formula_unsupported('VLOOKUP({א}) + WORKDAYS({ב})') == \
        ["VLOOKUP", "WORKDAYS"]
    assert import_monday.formula_unsupported("") == ["—"]


def test_a_string_argument_is_not_read_as_a_function_name():
    """A label inside quotes is data. Read as code, every Hebrew status label
    would come back as an unknown function."""
    assert import_monday.formula_unsupported('IF({סטטוס} = "SWITCH", 1, 0)') == []
    assert import_monday.formula_unsupported("IF({x} = 'DONE', 1, 0)") == []
