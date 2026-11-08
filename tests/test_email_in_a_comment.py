"""An e-mail address in an item's conversation is an address, not a tag.

The comment renderer made two passes over the same line — links, then tags —
and the tag pass had nothing but a bare "@" to go on. In "shelly@mashcal.co.il"
it therefore coloured "@mashcal", up to the first dot, in tag blue: a tag of
somebody who does not exist, over half an address that was otherwise dead text.
The same bare "@" also reached inside the href the link pass had just written.

Pinned here: an address renders as one mailto: link and carries no tag
highlight, a tag still has to start a word (the rule mentionCtx already applies
before it offers the tag menu), and the composer's live overlay answers the
same question as the posted comment. Runs the real inline, markMentions,
highlightMentions, renderContent and esc out of index.html under node.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "frontend" / "email_in_a_comment.mjs"


def test_an_email_in_a_comment_is_a_link_and_not_a_tag():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
