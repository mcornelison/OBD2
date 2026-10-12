################################################################################
# File Name: test_agent_memory_load_contract.py
# Purpose/Description: M2 standing-rule lint -- shared agent memory lives outside
#     Claude Code's cwd-keyed auto-load directory, because per-ticket worktrees
#     would each resolve to their own EMPTY memory dir and boot with no project
#     memory, silently. The arrangement only works while the boot path loads it
#     EXPLICITLY. This lint is the catch.
# Author: Claude (M2 restructure)
# Creation Date: 2026-08-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-25    | Claude (M2)  | Initial -- explicit-load contract + Ralph carve
#               |              | out + dead auto-load path ban.
# 2026-09-03    | Claude (V2)  | Retargeted for the V1->V2 upgrade. The CONTRACT
#               |              | is unchanged; the artifact carrying it moved.
#               |              | /init-<role> was retired for the universal
#               |              | `hello` skill, and shared memory moved from
#               |              | offices/knowledge/memory/ to
#               |              | offices/_shared/knowledge/. These tests failed on
#               |              | the V2 baseline and the failure was CORRECT: it
#               |              | caught that Ralph's carve-out had been lost when
#               |              | init-ralph.md was retired.
# ================================================================================
################################################################################

"""Lint: the shared-memory explicit-load contract survives edits.

Shared memory lives at ``offices/_shared/knowledge/MEMORY.md``. It is loaded
explicitly rather than by Claude Code's auto-load, which is keyed to the working
directory and therefore empty inside every per-ticket bench worktree.

Two artifacts carry the contract now:
  * the universal ``hello`` skill master, byte-identical in every office
  * each office's own ``CLAUDE.md``, which is where office-specific deviations live
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO / ".claude" / "skills"
COMMANDS_DIR = REPO / ".claude" / "commands"

MEMORY_REF = "_shared/knowledge/MEMORY.md"

# Ralph is deliberately absent -- see the carve-out test below.
INTERACTIVE_OFFICES = ["architect", "pm", "tester", "tuner", "uideveloper"]
HEADLESS_OFFICE = "ralph"

# The pre-M2 auto-load directory, matched by its cwd-derived slug so the check is
# blind to path style and case. Any command still naming it points at a tombstone.
DEAD_AUTOLOAD_SLUG = "z--o-obd2v2"


def _officesRoot():
    """The offices tree, or None when the share is not reachable.

    Read from FLEET_SHARE, which the suite's documented invocation sets.
    """
    share = os.environ.get("FLEET_SHARE")
    if not share:
        return None
    root = Path(share)
    return root if root.is_dir() else None


def test_theShareWasActuallyChecked() -> None:
    """Guard the guard: without the share, every office test below skips.

    A suite that skips its way to green is unfalsifiable. Make the absence loud
    and state it once, here, rather than leaving five silent skips.
    """
    root = _officesRoot()
    if root is None:
        pytest.skip(
            "FLEET_SHARE unset or unreachable -- the office boot-contract tests "
            "below did NOT run. Set FLEET_SHARE to the offices root."
        )
    assert (root / "_shared" / "knowledge" / "MEMORY.md").is_file(), (
        "shared MEMORY.md missing from offices/_shared/knowledge/. Every office "
        "boot pointer at it is dangling."
    )


def test_helloSkill_loadsSharedMemoryExplicitly() -> None:
    """
    Given: the universal `hello` skill master
    When: its text is read
    Then: it names the shared MEMORY.md

    `hello` replaced the /init-<role> commands on 2026-09-03. It is model-invoked,
    so it works for a headless office with nobody present to type a command.
    """
    path = SKILLS_DIR / "hello" / "SKILL.md"
    assert path.is_file(), f"missing universal skill: {path}"
    assert MEMORY_REF in path.read_text(encoding="utf-8"), (
        f"hello no longer loads shared memory. Expected {MEMORY_REF!r}."
    )


@pytest.mark.parametrize("office", INTERACTIVE_OFFICES)
def test_interactiveOffice_loadsSharedMemoryExplicitly(office: str) -> None:
    """
    Given: an interactive office's CLAUDE.md
    When: its text is read
    Then: it names the share copy of MEMORY.md

    Without this the role boots with no project memory and nothing says so.
    """
    root = _officesRoot()
    if root is None:
        pytest.skip("FLEET_SHARE unset -- see test_theShareWasActuallyChecked")

    path = root / office / "CLAUDE.md"
    assert path.is_file(), f"missing office charter: {path}"
    assert MEMORY_REF in path.read_text(encoding="utf-8"), (
        f"{office}/CLAUDE.md no longer loads shared memory. "
        f"Expected a reference to {MEMORY_REF!r}."
    )


def test_headlessOffice_declaresTheSharedMemoryCarveOut() -> None:
    """
    Given: the headless office's CLAUDE.md
    When: its text is read
    Then: it explicitly declares that it does NOT load shared memory

    This is a carve-out, not an omission. Ralph runs headless per iteration under
    the scope.filesToRead rule -- the sprint contract IS his context. A memory
    load would contradict that rule and bloat every iteration.

    The carve-out used to live in init-ralph.md. When the init commands were
    retired on 2026-09-03 the universal `hello` skill -- which loads shared memory
    for everyone -- silently applied here too, and the carve-out was lost. This
    test now demands the deviation be stated in the office's OWN CLAUDE.md, which
    keeps `hello` byte-identical everywhere while letting one office opt out in
    writing.
    """
    root = _officesRoot()
    if root is None:
        pytest.skip("FLEET_SHARE unset -- see test_theShareWasActuallyChecked")

    text = (root / HEADLESS_OFFICE / "CLAUDE.md").read_text(encoding="utf-8").lower()

    assert "carve-out" in text, (
        f"{HEADLESS_OFFICE}/CLAUDE.md does not declare the shared-memory carve-out. "
        f"`hello` loads {MEMORY_REF} for every office, so without a stated exception "
        f"this headless office loads it too -- contradicting the scope.filesToRead "
        f"rule. If that is intended, delete this test and say why."
    )
    assert "does not load shared memory" in text, (
        f"{HEADLESS_OFFICE}/CLAUDE.md mentions a carve-out but never states plainly "
        f"that it does not load shared memory."
    )


def test_noCommand_pointsAtTheDeadAutoloadDirectory() -> None:
    """
    Given: every slash command
    When: their text is read
    Then: none names the pre-M2 auto-load memory directory

    That path holds a tombstone plus orphaned copies. A command that reads it gets
    stale facts; a command that WRITES it silently reaches no agent.
    """
    offenders = [
        p.name
        for p in sorted(COMMANDS_DIR.glob("*.md"))
        if DEAD_AUTOLOAD_SLUG in p.read_text(encoding="utf-8").lower()
    ]

    assert not offenders, (
        f"commands still naming the dead auto-load memory dir: {offenders}. "
        f"Use offices/{MEMORY_REF} instead."
    )
