################################################################################
# File Name: test_ralph_promise_tag_contract.py
# Purpose/Description: Guard test for TD-028/TD-073 -- asserts every
#                      <promise>TAG</promise> documented in offices/ralph/prompt.md
#                      is ACCOUNTED FOR in offices/ralph/ralph.sh, either by a
#                      real grep branch or by an explicit NOT_TAG_DRIVEN
#                      declaration, and that the sprint-ending mechanism stays
#                      sprint.json-derived rather than tag-driven.
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
# 2026-08-03    | Ralph Agent  | US-529 TD-073: re-ground the gate. The old
#               |              | parser counted ANY full-form tag string in
#               |              | ralph.sh as "handled", which (a) missed the
#               |              | header's abbreviated </> mentions and (b) could
#               |              | be satisfied by a comment. Now parses REAL grep
#               |              | branches vs explicit NOT_TAG_DRIVEN
#               |              | declarations, and pins the sprint.json-derived
#               |              | completion branch so COMPLETE cannot become
#               |              | tag-driven.
# ================================================================================
################################################################################

"""
TD-028/TD-073 guard: prompt.md tags must be accounted for by ralph.sh.

`ralph.sh` derives continue/stop from `sprint.json`, not from the model's
`<promise>` tag (loop-control contract rewritten 2026-05-12). So "handled"
means one of exactly two things, and this module distinguishes them:

* the tag has a real `grep` branch in `ralph.sh`, or
* `ralph.sh` explicitly declares it `NOT_TAG_DRIVEN: <promise>X</promise>`
  WITH a rationale.

If you add a new `<promise>TAG</promise>` to either file, add it to the other
(as a branch or as a declared-and-justified NOT_TAG_DRIVEN entry).
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = PROJECT_ROOT / "offices" / "ralph" / "prompt.md"
RALPH_SH_PATH = PROJECT_ROOT / "offices" / "ralph" / "ralph.sh"

PROMISE_RE = re.compile(r"<promise>([A-Z_]+)</promise>")
# `NOT_TAG_DRIVEN: <promise>X</promise> -- <why>` in a ralph.sh comment.
NOT_TAG_DRIVEN_RE = re.compile(
    r"^\s*#\s*NOT_TAG_DRIVEN:\s*<promise>([A-Z_]+)</promise>\s*(?P<reason>.*)$"
)
# Documentation placeholders, not real tags
_PLACEHOLDERS = {"TAG"}
# A declaration must carry a real reason, not a bare silencing entry.
MIN_RATIONALE_CHARS = 20


def _extractTags(path: Path) -> set[str]:
    return set(PROMISE_RE.findall(path.read_text(encoding="utf-8"))) - _PLACEHOLDERS


def _shellLines() -> list[str]:
    return RALPH_SH_PATH.read_text(encoding="utf-8").splitlines()


def _extractShellBranchTags() -> set[str]:
    """
    Tags ralph.sh genuinely BRANCHES on.

    Comments are stripped FIRST, so prose that merely mentions a tag (or the
    word "grep") can never masquerade as a branch. What remains is executable,
    and a promise tag only reaches the loop through a `grep` of the iteration
    log.
    """
    tags: set[str] = set()
    for line in _shellLines():
        if line.lstrip().startswith("#"):
            continue
        if "grep" not in line:
            continue
        tags.update(PROMISE_RE.findall(line))
    return tags - _PLACEHOLDERS


def _extractShellNotTagDriven() -> dict[str, str]:
    """Explicit `NOT_TAG_DRIVEN:` declarations mapped to their rationale."""
    declared: dict[str, str] = {}
    for line in _shellLines():
        match = NOT_TAG_DRIVEN_RE.match(line)
        if match:
            declared[match.group(1)] = match.group("reason").strip()
    return declared


def test_promptMdAndRalphShDocumentSamePromiseTags():
    """
    Given: prompt.md §Stop Condition lists the agent-emittable tags, and
           ralph.sh either branches on a tag or declares it NOT_TAG_DRIVEN.
    When:  both files are scanned -- ralph.sh for real grep branches and for
           explicit NOT_TAG_DRIVEN declarations.
    Then:  every documented tag is accounted for exactly once, with no ghost
           branch (a branch for a tag Ralph is never told to emit) and no
           silently-dropped tag.
    """
    promptTags = _extractTags(PROMPT_PATH)
    branchTags = _extractShellBranchTags()
    notTagDriven = _extractShellNotTagDriven()
    accountedFor = branchTags | set(notTagDriven)

    ghostBranches = branchTags - promptTags
    assert not ghostBranches, (
        f"ralph.sh branches on tags not documented in prompt.md: {sorted(ghostBranches)}. "
        "Either add them to prompt.md §Stop Condition or remove the branches in ralph.sh."
    )

    unaccounted = promptTags - accountedFor
    assert not unaccounted, (
        f"prompt.md documents tags ralph.sh neither branches on nor declares: "
        f"{sorted(unaccounted)}. Either add a grep branch in ralph.sh, or -- if the "
        "tag is deliberately advisory -- add a "
        "'# NOT_TAG_DRIVEN: <promise>X</promise> -- <why>' declaration. Do NOT delete "
        "the entry from prompt.md: that table is the contract Ralph is held to."
    )

    ghostDeclarations = set(notTagDriven) - promptTags
    assert not ghostDeclarations, (
        f"ralph.sh declares NOT_TAG_DRIVEN tags prompt.md never documents: "
        f"{sorted(ghostDeclarations)}. Remove the stale declaration."
    )

    contradictory = branchTags & set(notTagDriven)
    assert not contradictory, (
        f"ralph.sh both branches on and declares NOT_TAG_DRIVEN: {sorted(contradictory)}. "
        "A tag is one or the other; the declaration is now a lie."
    )


def test_promptMdDocumentsAtLeastTheCoreTags():
    """Regression: the core tags must exist so Ralph knows which tokens to emit."""
    promptTags = _extractTags(PROMPT_PATH)
    coreTags = {"COMPLETE", "SPRINT_BLOCKED", "PARTIAL_BLOCKED"}
    missing = coreTags - promptTags
    assert not missing, f"prompt.md is missing core promise tags: {sorted(missing)}"


def test_ralphShEndsTheSprintFromTheSprintJsonTally_notFromTheTag():
    """
    Given: COMPLETE is the sprint-ENDING signal, and TD-073 asked whether
           ralph.sh acts on it at all.
    When:  ralph.sh's executable lines are inspected for the completion branch.
    Then:  the tally-derived branch exists (story counts compared, "PRD
           COMPLETE" announced, exit 0).

    This is the anti-rubber-stamp guard. The gate above is satisfiable by a
    NOT_TAG_DRIVEN comment, so on its own it could be silenced without the loop
    actually being able to end a sprint. This pins the MECHANISM that makes the
    declaration true.
    """
    code = [line for line in _shellLines() if not line.lstrip().startswith("#")]
    body = "\n".join(code)

    assert '[ "$after_complete" -ge "$total" ]' in body, (
        "ralph.sh lost its sprint.json-derived completion comparison. Without it "
        "nothing ends the sprint: COMPLETE is advisory, so the tally IS the stop "
        "condition."
    )
    assert "PRD COMPLETE" in body, "ralph.sh no longer announces sprint completion."

    completionBranch = next(
        (n for n, line in enumerate(code) if '[ "$after_complete" -ge "$total" ]' in line),
        None,
    )
    assert completionBranch is not None
    following = "\n".join(code[completionBranch : completionBranch + 6])
    assert "exit 0" in following, (
        "ralph.sh's completion branch no longer exits -- the loop would keep "
        "spending iterations on a finished sprint."
    )


def test_completeTagIsNotAGrepBranch_soAModelCannotEndASprintByAssertingIt():
    """
    Given: the 2026-05-12 loop-control rewrite made the tag advisory and
           sprint.json authoritative.
    When:  ralph.sh's grep branches are enumerated.
    Then:  COMPLETE is absent from them.

    Pinning the ABSENCE is deliberate. "Fixing" TD-073 by adding
    `grep <promise>COMPLETE</promise> -> exit 0` would let a model end a sprint
    by ASSERTING completion while stories are still passes:false -- the exact
    failure the rewrite removed. That regression must fail loudly, not silently
    satisfy the parity gate.
    """
    branchTags = _extractShellBranchTags()
    assert "COMPLETE" not in branchTags, (
        "ralph.sh now branches on the COMPLETE tag. The sprint.json tally is the "
        "authority (see test_ralphShEndsTheSprintFromTheSprintJsonTally_notFromTheTag); "
        "a tag-driven stop lets the model end a sprint by claiming it is done."
    )
    assert "COMPLETE" in _extractShellNotTagDriven(), (
        "COMPLETE must be explicitly declared NOT_TAG_DRIVEN in ralph.sh so the "
        "design choice is visible to the next reader instead of looking like a "
        "missing branch."
    )


def test_notTagDrivenDeclarationsCarryARationale():
    """
    Given: NOT_TAG_DRIVEN is the escape hatch that satisfies the parity gate.
    When:  each declaration is read.
    Then:  it carries a real rationale.

    Without this, the hatch becomes a one-line silencer for any inconvenient
    tag -- the rubber stamp TD-073 explicitly warned against.
    """
    declared = _extractShellNotTagDriven()
    assert declared, "ralph.sh has no NOT_TAG_DRIVEN declarations at all."
    thin = {tag: reason for tag, reason in declared.items() if len(reason) < MIN_RATIONALE_CHARS}
    assert not thin, (
        f"NOT_TAG_DRIVEN declarations without a real rationale: {sorted(thin)}. "
        "Say WHY the tag is advisory on the same line, or add a branch instead."
    )
