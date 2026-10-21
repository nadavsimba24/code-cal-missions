"""קריטריוני קבלה — עשרים שורות, ומה מוכיח כל אחת.

A traceability file. Most of these are already proved somewhere specific, and
re-proving them here would be two tests that can disagree; what this file does
instead is name the proof, and carry a real assertion only where the criterion
is not covered anywhere else.

TC16 is the one that is NOT met. The mobile interface is not built, and saying
so in a docstring is worth less than a case that fails until it is — so that
is what it is. It is marked xfail(strict), which means the day somebody builds
the mobile sheet this file goes RED and forces the marker off, rather than
quietly staying green and letting the criterion be forgotten.
"""
import pathlib
import re
import sys

import pytest
from sqlalchemy.orm import Session

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import main as cityos_main  # noqa: E402
from models import SavedView  # noqa: E402

from test_saved_views import CUT, _board, _mk, _list, _cfg  # noqa: E402
from test_view_hierarchy import _item, _query, _on, _h  # noqa: E402

SRC = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


# Where each criterion is proved. Named, not re-proved: two tests of one rule
# are two tests that can disagree about it.
PROVEN_BY = {
    "TC01": ["test_view_vs_item_data.py::test_saving_a_view_for_everyone_changes_no_item",
             "test_view_server_contract.py::test_the_database_itself_refuses_a_duplicate_name"],
    "TC02": ["test_saved_views.py::test_an_editor_may_change_any_unlocked_view_on_the_board",
             "test_saved_views.py::test_a_viewer_may_look_and_may_not_overwrite"],
    "TC04": ["test_table_views.py::test_only_the_board_owner_turns_the_lock_either_way",
             "test_table_views.py::test_deleting_a_locked_view_is_the_board_owners_too"],
    "TC05": ["test_table_views.py::test_a_copy_carries_no_lock_and_no_pin"],
    "TC06": ["test_view_column_permissions.py::test_a_blocked_view_is_not_copied_either",
             "test_view_column_permissions.py::"
             "test_the_block_does_not_say_which_column_or_what_the_condition_was"],
    "TC08": ["test_view_save_for_everyone.py::test_every_component_lands_in_one_write"],
    "TC09": ["test_saved_views.py::test_a_saved_view_never_holds_a_search"],
    "TC10": ["test_view_config_scope.py::test_nothing_temporary_is_stored_on_a_view",
             "test_view_vs_item_data.py::test_an_edit_outlives_the_view_it_was_made_in"],
    "TC11": ["test_view_hierarchy.py::test_the_four_rows_together"],
    "TC12": ["test_view_hierarchy.py::test_the_wrapper_discloses_nothing_about_the_parent"],
    "TC13": ["test_view_delete_restore.py::test_and_not_after_it"],
    "TC14": ["test_view_navigation.py::test_pinning_does_not_decide_where_anybody_lands"],
    "TC15": ["test_view_navigation.py::test_the_personal_order_is_kept_on_the_server",
             "test_view_navigation.py::test_the_owner_orders_the_pinned_ones_among_themselves"],
    "TC17": ["test_view_sort_structure_counts.py::"
             "test_deleting_a_column_a_view_SORTS_by_needs_fixing"],
    "TC18": ["test_view_concurrency.py::test_a_save_naming_an_older_version_is_refused",
             "test_view_states.py::test_a_failed_save_never_advances_what_unsaved_is_measured_against"],
    "TC19": ["test_view_preflight.py::test_the_sort_spans_the_pages"],
}


def test_every_criterion_is_accounted_for():
    """Twenty rows, and each one either has a proof named above or a case
    below. A criterion with neither is one nobody is checking."""
    here = {m.group(1) for m in re.finditer(r"def test_(TC\d\d)_", open(__file__).read())}
    covered = set(PROVEN_BY) | here
    assert covered == {f"TC{i:02d}" for i in range(1, 21)}, \
        sorted({f"TC{i:02d}" for i in range(1, 21)} - covered)


@pytest.mark.parametrize("tc", sorted(PROVEN_BY))
def test_the_named_proof_exists(tc):
    """A pointer at a test that was renamed is a criterion nobody is
    checking any more, with a file that says otherwise."""
    for ref in PROVEN_BY[tc]:
        f, case = ref.split("::")
        body = (ROOT / "tests" / f).read_text(encoding="utf-8")
        assert f"def {case}(" in body, ref


# ── TC03 — the main table cannot be deleted OR hidden ──────────────────────
def test_TC03_the_main_table_cannot_be_removed_from_the_board(client, admin_id):
    """Deletion is covered elsewhere; HIDING is the half that is easy to
    forget, because hiding a view is an ordinary thing to do to the others."""
    bid = _board(client, admin_id)
    r = client.patch(f"/api/boards/{bid}",
                     json={"user_id": admin_id, "views": ["kanban"]}, headers=_h(admin_id))
    assert r.status_code == 200, r.text
    assert "table" in r.json()["views"], "the main table was switched off"

    # and there is no row standing for it that somebody could delete instead
    with Session(cityos_main.engine) as db:
        assert db.query(SavedView).filter(SavedView.board_id == bid).count() == 0


def test_TC03_only_the_board_owner_saves_the_main_tables_layout(client, admin_id, guinea_id):
    bid = _board(client, admin_id, invite=[guinea_id])
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": guinea_id, "col_widths": {"item": 300}},
                        headers=_h(guinea_id)).status_code == 403
    assert client.patch(f"/api/boards/{bid}",
                        json={"actor_id": admin_id, "col_widths": {"item": 300}},
                        headers=_h(admin_id)).status_code == 200


# ── TC07 — a restricted column is not offered for choosing ─────────────────
def test_TC07_a_restricted_column_is_not_in_the_list_a_saved_view_is_built_from():
    """"עמודות מוגבלות אינן מופיעות לבחירה", and the way to be sure is that
    there is ONE list. The table, the column picker, the filter's field list
    and the export are all built from orderedColumns — applying the rule in
    four places would be four chances to miss one, and the one missed is the
    leak.

    Scoped to a saved טבלה view, and that is the point of this case as much
    as the rule is. The board's own main table has shown restricted columns
    with their values withheld for as long as column permissions have
    existed; this feature is not the place to change how the board underneath
    it behaves."""
    i = SRC.index("function _orderedColumns()")
    body = SRC[i:SRC.index("\n}", SRC.index("return all;", i))]
    assert "advColHidden" in body, \
        "a column the reader may not see still reaches a view's table and picker"
    # the GATE, in the filter itself — asking only whether the variable exists
    # passed with the gate deleted from the expression that uses it
    flat = body.replace(" ", "")
    assert "!(inSavedView&&advColHidden(c.id))" in flat, \
        "the rule reaches the board's own main table, which it must not"


def test_TC07_setting_column_permissions_is_offered_only_inside_a_view():
    """The feature is old — it predates this work by months, and the server
    has enforced it all along. What is new is WHERE it is offered: setting
    permissions is part of what a טבלה view is for, and the board's own table
    keeps the menu it has always had — rename, and delete.

    The server side is untouched on purpose: permissions already set still
    apply everywhere, and hiding the entry does not unset anything."""
    i = SRC.index("ColPerms.open('${colId}')")
    entry = SRC[SRC.rindex("+(", 0, i):i]
    assert "Views.active!=null" in entry.replace(" ", ""), entry
    assert "isAdmin" in entry, "it is offered to somebody who may not set them"


def test_TC07_a_viewers_adjustments_never_reach_the_server(client, admin_id, member_id):
    bid = _board(client, admin_id)
    client.post(f"/api/boards/{bid}/members",
                json={"actor_id": admin_id, "user_id": member_id, "role": "viewer"},
                headers=_h(admin_id))
    vid = _mk(client, bid, admin_id, "תצוגה").json()["id"]
    assert _cfg(client, vid, member_id, dict(CUT, sort="due")).status_code == 403
    assert _mk(client, bid, member_id, "משלי").status_code == 403


# ── TC16 — the mobile interface, which is not built ────────────────────────
@pytest.mark.xfail(strict=True, reason=(
    "the mobile view interface is not implemented: no bottom sheet, no "
    "touch-sized cell editor, and the management actions are not hidden "
    "below the breakpoint. Marked strict so that building it turns this "
    "file red and forces the marker off, instead of the criterion being "
    "quietly forgotten."))
def test_TC16_the_mobile_interface_exists():
    assert "view-sheet" in SRC, "no bottom sheet for choosing a view"
    i = SRC.index("const Views = {")
    body = SRC[i:SRC.index("\n};", i)]
    assert "isMobile()" in body, "the management actions are not withheld on mobile"


# ── TC20 — what this version deliberately does NOT contain ─────────────────
def test_TC20_there_are_no_private_views(client, admin_id):
    bid = _board(client, admin_id)
    assert _mk(client, bid, admin_id, "שלי", vis="private").json()["visibility"] == "public"


def test_TC20_nothing_groups_by_a_column_value():
    """"אין קיבוץ מחדש" — groups come from the board's structure, and the
    saved configuration has no key that could express anything else."""
    assert "group" not in cityos_main.VIEW_CONFIG_KEYS
    assert set(cityos_main.VIEW_CONFIG_KEYS) == {
        "view", "cols", "adv", "people", "status", "priority", "links", "sort"}


def test_TC20_no_ai_reaches_the_views(client, admin_id):
    """"ללא רכיבי AI בתכולת גרסה זו." The app HAS an agent swarm; what this
    checks is that none of it is wired into a saved view."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    start = src.index("def _view_visible_to(")
    layer = src[start:src.index("# ── the advanced filter, evaluated here")]
    for sign in ("swarm", "ollama", "llm", "gpt", "gemma"):
        assert sign not in layer.lower(), sign
