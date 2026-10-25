"""סינון מתקדם — עץ תנאים על עמודות הלוח.

The toolbar's filters answer one question each: this person, that status. An
advanced filter answers a question made of several, and the shape that
expresses it is a tree — "A and (B or C)" is a different question from
"(A and B) or C", and a flat list cannot tell them apart.

The engine is what is pinned, because the engine is what can be silently
wrong: a filter that hides the wrong rows looks exactly like one that works,
and the rows it hides are the ones nobody goes looking for. The harness runs
the real functions out of index.html — the operator table, the cell reader,
the rule evaluator, the tree — and the real builder's path editing, which is
where a tree editor goes wrong.

Two kinds of value are deliberately not literals. "אני (דינמי)" and the dates
(היום, השבוע, חודש הבא…) are kept as tokens and resolved when the filter RUNS:
stored as the id or the dates they happen to mean today, a saved filter would
quietly become somebody else's filter, or last week's.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


# The operators the spec gives each column type, word for word.
SPEC = {
    "text":   ["שווה ל", "לא שווה ל", "מכיל", "לא מכיל", "ריק", "אינו ריק"],
    "status": ["שווה ל", "לא שווה ל", "ריק", "אינו ריק"],
    "number": ["שווה ל", "לא שווה ל", "גדול מ", "קטן מ", "בטווח"],
    "people": ["מוקצה ל", "לא מוקצה ל"],
    "date":   ["ביום", "לפני", "אחרי", "בטווח"],
}


def _balanced(text, start, open_ch, close_ch):
    """From the opening bracket at `start`, the text up to its match. An entry
    in this table runs over several lines, so a line-anchored regex reads half
    of it and the assertion then passes on a table that is wrong."""
    d = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            d += 1
        elif text[i] == close_ch:
            d -= 1
            if not d:
                return text[start:i + 1]
    raise AssertionError("unbalanced")


def _ops(kind):
    i = SRC.index("const ADV_OPS = {")
    table = _balanced(SRC, SRC.index("{", i), "{", "}")
    at = table.index(kind + ":")
    block = _balanced(table, table.index("[", at), "[", "]")
    return re.findall(r"'[\w]+','([^']+)'", block)


@pytest.mark.parametrize("kind,wanted", SPEC.items())
def test_each_column_type_offers_the_operators_the_spec_gives_it(kind, wanted):
    got = _ops(kind)
    assert got[:len(wanted)] == wanted, f"{kind}: {got}"


def test_a_people_rule_can_mean_me_and_a_date_rule_can_mean_this_week():
    """Not stored as the id or the dates they resolve to — a filter saved on
    Sunday still has to mean "this week" on Thursday, and "mine" still has to
    mean the person looking."""
    assert "'me'" in SRC, "the people token is gone"
    # the label says it is not a person but a thing that resolves — the whole
    # reason to pick it over one's own name, and what makes it travel inside a
    # saved view somebody else opens
    assert "אני (דינמי)" in SRC, "nothing offers the viewer as a value"
    m = re.search(r"const ADV_DATES = \[(.*?)\];", SRC, re.S)
    assert m, "the dynamic dates moved"
    for tok in ("today", "this_week", "next_month", "last_7"):
        assert f"'{tok}'" in m.group(1), tok
    # resolved at match time, inside the rule evaluator — not frozen at build
    rule = re.search(r"function advRuleMatch\(t,r\)\{(.*?)\n\}", SRC, re.S)
    assert rule and "advSpan(r.v)" in rule.group(1)
    assert "meId()" in rule.group(1), "[אני] is resolved somewhere other than at match time"


def test_the_tree_joins_the_filters_already_on_the_toolbar():
    """It narrows alongside them rather than replacing them, it counts towards
    "is anything filtering?", and נקה סינון clears it like the rest."""
    i = SRC.index("function applyFilters(tasks){")
    body = _balanced(SRC, SRC.index("{", i + 10), "{", "}")
    assert "advMatch(t,f.adv)" in body
    i = SRC.index("function filtersActive(){")
    assert "advCount" in _balanced(SRC, SRC.index("{", i + 10), "{", "}")
    i = SRC.index("function clearFilters(){")
    assert "adv:null" in _balanced(SRC, SRC.index("{", i + 10), "{", "}")


def test_an_unfinished_filter_never_empties_the_board():
    """A rule with no value chosen, a group with no rules, a column deleted
    since — each of them hiding every row is the one failure a filter must not
    have, because an empty board reads as a board with nothing on it."""
    m = re.search(r"function advMatch\(t,node\)\{(.*?)\n\}", SRC, re.S)
    assert m and "return true" in m.group(1)
    m = re.search(r"function advRuleMatch\(t,r\)\{(.*?)\n\}", SRC, re.S)
    assert m and "if(!f) return true" in m.group(1), \
        "a rule on a deleted column hides the board"


def test_the_engine_and_the_builder_behave():
    """Driven harness: tests/frontend/advanced_filter.mjs."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    h = ROOT / "tests" / "frontend" / "advanced_filter.mjs"
    r = subprocess.run([node, str(h)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_the_specs_own_example_is_expressible():
    """"(Group A: Status=Done AND Date=This Week) OR (Group B: Priority=High)"

    Two groups side by side under an OR root, each with an AND inside. A tree
    builder that can express every shape EXCEPT the one the specification uses
    as its illustration is one nobody will trust — so it is built through the
    real builder in the harness, not written down, and run against items that
    match each half, both halves and neither.
    """
    h = (ROOT / "tests" / "frontend" / "advanced_filter.mjs").read_text(encoding="utf-8")
    assert "Group A: Status=Done AND Date=This Week" in h, \
        "the spec's example is no longer the thing being proved"


def test_groups_are_named_the_way_the_spec_names_them():
    """Group A, Group B — and a group inside A is AA, so a name says where it
    sits. Lettered among the GROUPS and not among all the rules: adding a
    plain condition beside a group must not rename it, because a name that
    moves is worse than no name."""
    m = re.search(r"  label\(path\)\{(.*?)\n  \},", SRC, re.S)
    assert m, "group naming is gone"
    body = m.group(1)
    assert "k.rules!==undefined" in body, "groups are lettered among the plain rules too"
    assert "if(path==='')return ''" in body, "the root is named as though it were a group"
    assert "adv-grp-name" in SRC, "the name is computed and never drawn"


# ── the builder as something a person reads ────────────────────────────────
def test_a_condition_reads_as_a_sentence():
    """כאשר «עמודה» «שאלה» «ערך», then וגם or או before each one after it.
    The gap above the first condition used to be blank, which left the reader
    to work out that the box under it was a condition at all — and the and/or
    was a toggle in a header a line above, saying the same thing in a second
    place that could be read as disagreeing with the first."""
    i = SRC.index("  groupHTML(g,path){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "כאשר" in body, "the first condition opens with nothing again"
    assert "adv-joiner" in body, "the joining word is gone"
    assert "adv-joiner-sel" in body and "Adv.setOp(" in body, \
        "the and/or left the column it joins"
    assert "adv-join-wrap" not in SRC, "the old toggle is back beside the word"


def test_the_column_wears_its_own_type():
    """Three identical dropdowns in a row, and the column — the part that
    decides what the other two will even offer — was the hardest of them to
    find. It now carries the icon the board draws it with."""
    assert "function advIcon(" in SRC, "the column type is no longer shown"
    i = SRC.index("  ruleHTML(r,path){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "advIcon(f)" in body, "the rule row dropped the column's icon"
    assert "avatarInner(" in body, "a person is back to being only a name"


def test_a_condition_without_a_value_says_it_is_not_filtering():
    """It matches every item — it widens the filter rather than narrowing it —
    and it did so in silence: three conditions on screen, one of them doing
    nothing, and a row count nobody could account for."""
    assert "ruleDone(r){" in SRC and "todoNote(){" in SRC, \
        "an unfinished condition is silent again"
    assert ".adv-rule.adv-todo" in SRC, "nothing marks it on the row"
    assert ".adv-warn" in SRC, "nothing says it above a tree that scrolls"


def test_the_count_is_beside_the_title():
    """How many items the filter being built would leave is the whole point of
    the dialog. It was in grey at the foot of a list that scrolls."""
    i = SRC.index("  html(){")
    head = SRC[i:SRC.index("\n  },", i)]
    assert 'id="adv-count"' in head, "the live count left the title row"
    i = SRC.index("  stamp(){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "adv-count" in body and "adv-note" in body, \
        "the count and the warning stopped following the draft"


def test_the_door_turns_both_ways():
    """The quick panel's foot opens the builder. Without this, getting back to
    picking values meant closing the dialog and finding the filter button
    again — and what had been built would be lost on the trip."""
    assert "toQuick()" in SRC, "there is no way back to the quick panel"
    i = SRC.index("  async toQuick(){")
    assert "this.apply()" in SRC[i:i + 200], \
        "going back to the quick panel throws away what was built"
    assert 'onclick="Adv.toQuick()"' in SRC, "nothing offers the way back"


def test_the_dialog_looks_like_three_controls_and_not_a_card():
    """Three plain outlined boxes on the dialog's own white — not a card with
    a grey fill holding them. Every filled box is another rectangle competing
    with the thing being looked for, and the row already has four."""
    assert ".adv-box{" in SRC, "the controls lost their own outline"
    assert "background:none}" in SRC.split(".adv-grp{")[1][:80], \
        "the group is drawing a filled card again"
    i = SRC.index("  box(cls,inner){")
    assert "adv-cv" in SRC[i:i + 300], \
        "the chevron is back to whatever the browser draws"


def test_a_chosen_value_is_shown_the_way_the_board_shows_it():
    """A person by their face, a status in its own colour. It was a line of
    plain text indistinguishable from the question beside it."""
    assert ".adv-chip{" in SRC and ".adv-chip-x{" in SRC, "the value chip is gone"
    i = SRC.index("function advChoices(")
    body = SRC[i:SRC.index("\n}", i)]
    assert "color:s.c" in body, "a status choice stopped carrying its colour"


def test_the_window_actions_sit_opposite_the_title():
    """Clearing as a word, saving as the one outlined thing up there — and the
    foot down to the two that decide what happens to the draft."""
    i = SRC.index("  html(){")
    head = SRC[i:SRC.index("\n  },", i)]
    assert "adv-h-acts" in head and "נקה הכול" in head, "the header actions are gone"
    assert "Adv.saveView()" in head, "the cut can no longer be saved as a view"
    # …and nothing else up there. The ? carried its explanation in a title
    # attribute, which showed nothing on hover where it was placed — a help
    # affordance that does not help is worse than none.
    assert "adv-help" not in SRC, "the question mark is back"


def test_saving_a_view_applies_the_draft_first():
    """A view holds the filter the BOARD is under. Storing a draft the board
    was never shown under would save a cut nobody has seen."""
    i = SRC.index("  async saveView(){")
    body = SRC[i:SRC.index("\n  },", i)]
    assert "await this.apply()" in body, "a draft can be saved without being applied"
    assert "Views.update()" in body and "Views.saveNew()" in body, \
        "saving no longer answers the question the tab strip answers"


def test_the_builder_opens_on_a_row_and_never_applies_a_blank_one():
    """The first thing anybody does here is pick a column; asking for the row
    before they can do it is a click that answers nothing. It costs nothing to
    offer, because a condition still missing its value matches every item —
    applying it would buy a badge counting a question nobody is asking, and a
    saved view that carries it — so it is dropped on the way out."""
    adv = SRC[SRC.index("const Adv = {"):]
    i = adv.index("  open(){")
    body = adv[i:adv.index("\n  },", i)]
    assert "this.newRule()" in body, "the builder opens on no conditions again"
    i = adv.index("  async apply(){")
    body = adv[i:adv.index("\n  },", i)]
    assert "this.asked(this.draft)" in body, "a half-built condition reaches the board"
    i = adv.index("  preview(){")
    body = adv[i:adv.index("\n  },", i)]
    assert "this.asked(this.draft)" in body, \
        "the count predicts a board the apply will not produce"


def test_the_value_list_can_be_opened_after_a_value_is_in_it():
    """The chip stands where the select's text would be and the select is laid
    OVER the whole box, invisible. Shrunk to zero width instead, the box had
    nothing in it to click: a value once picked could only be cleared, never
    changed."""
    assert ".adv-box-val.picked .adv-bare{position:absolute" in SRC, \
        "the value select is back to being shrunk away"
    assert ".adv-box{position:relative" in SRC, "the overlay has nothing to sit in"
    assert ".adv-chip-x{position:relative;z-index:2;pointer-events:auto}" in SRC, \
        "the × that clears a value is behind the select"


def test_the_builder_has_a_door_from_the_toolbar():
    """One filter control with two doors: the button opens the panel of
    values, the caret beside it opens the builder straight away. Not a second
    filter button — no label, no badge of its own — so the badge on «סינון»
    goes on counting the whole filter whichever door wrote it."""
    assert 'class="tb-caret"' in SRC, "the way straight to the builder is gone"
    assert "ctl-adv" not in SRC and "badge-adv" not in SRC, \
        "the caret grew into a second filter button with a badge of its own"
    i = SRC.index('class="tb-caret"')
    assert "Adv.open()" in SRC[i:i + 400], "the caret opens something else"
