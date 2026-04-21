################################################################################
# File Name: test_ralph_promise_tag_contract.py
# Purpose/Description: Guard test for TD-028 -- asserts the set of <promise>TAG</promise>
#                      tokens documented in offices/ralph/prompt.md matches the
#                      set of branches in offices/ralph/ralph.sh.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Ralph Agent  | US-207 TD-028: codify prompt.md <-> ralph.sh
#               |              | promise-tag parity so drift is a test failure,
#               |              | not a silent spec gap.
# ================================================================================
################################################################################

"""
TD-028 guard: promise-tag set in prompt.md must match ralph.sh branches.

If you add a new <promise>TAG</promise> to either file, add it to the other.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = PROJECT_ROOT / "offices" / "ralph" / "prompt.md"
RALPH_SH_PATH = PROJECT_ROOT / "offices" / "ralph" / "ralph.sh"

PROMISE_RE = re.compile(r"<promise>([A-Z_]+)</promise>")
# Documentation placeholders, not real tags
_PLACEHOLDERS = {"TAG"}


def _extractTags(path: Path) -> set[str]:
    return set(PROMISE_RE.findall(path.read_text(encoding="utf-8"))) - _PLACEHOLDERS


def test_promptMdAndRalphShDocumentSamePromiseTags():
    """
    Given: prompt.md §Stop Condition lists the agent-emittable tags and
           ralph.sh branches on handled tags.
    When:  both files are scanned for <promise>TAG</promise> occurrences.
    Then:  the sets are identical -- no silent undocumented branches, no
           spec-only ghost tags.
    """
    promptTags = _extractTags(PROMPT_PATH)
    shellTags = _extractTags(RALPH_SH_PATH)

    missingFromPrompt = shellTags - promptTags
    missingFromShell = promptTags - shellTags

    assert not missingFromPrompt, (
        f"ralph.sh branches on tags not documented in prompt.md: {sorted(missingFromPrompt)}. "
        "Either add them to prompt.md §Stop Condition or remove the branches in ralph.sh."
    )
    assert not missingFromShell, (
        f"prompt.md documents tags not handled by ralph.sh: {sorted(missingFromShell)}. "
        "Either add branches to ralph.sh or remove the documentation entries."
    )


def test_promptMdDocumentsAtLeastTheCoreTags():
    """Regression: the core tags must exist so Ralph knows which tokens to emit."""
    promptTags = _extractTags(PROMPT_PATH)
    coreTags = {"COMPLETE", "SPRINT_BLOCKED", "PARTIAL_BLOCKED"}
    missing = coreTags - promptTags
    assert not missing, f"prompt.md is missing core promise tags: {sorted(missing)}"
