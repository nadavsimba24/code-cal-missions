"""The sync guard's file reader must not escape the project directory.

Mend reported the open() in backend/sync.py as a path-traversal sink (CWE-22,
High): the helper joined its argument onto the repo root and opened whatever
came out, so "../../.ssh/id_rsa" — or any absolute path, which os.path.join
lets win outright — would have been read and matched against the invariant
checks. Every call site passes a literal today, which is exactly how such a
helper quietly becomes dangerous later. These pin the containment rule.
"""
import sync


def test_it_reads_a_file_that_lives_in_the_repo():
    """The legitimate case still works — this is a guard, not a wall."""
    assert "CODE-CAL MISSIONS" in sync.read_in_app("CONVENTIONS.md")


def test_a_climbing_relative_path_reads_nothing():
    """`../` sequences land outside the root and must come back empty."""
    for attempt in ("../../../etc/passwd", "frontend/../../../../etc/hosts"):
        assert sync.read_in_app(attempt) == "", f"{attempt} escaped the repo root"


def test_an_absolute_path_reads_nothing():
    """os.path.join lets an absolute argument discard the root it was anchored
    to, so the check has to run on the resolved result, not on the fragment."""
    assert sync.read_in_app("/etc/passwd") == ""


def test_a_symlink_pointing_out_of_the_tree_reads_nothing(tmp_path):
    """realpath is what makes the containment check survive a symlink."""
    import os
    import pathlib

    secret = tmp_path / "secret.txt"
    secret.write_text("sk-not-for-you", encoding="utf-8")
    link = pathlib.Path(sync.APP) / ".pytest-sync-escape-link"
    try:
        os.symlink(secret, link)
        assert sync.read_in_app(link.name) == ""
    finally:
        if link.is_symlink():
            link.unlink()


def test_a_missing_file_still_reads_as_empty():
    """The original helper swallowed a missing file and callers rely on that."""
    assert sync.read_in_app("no/such/file.txt") == ""
