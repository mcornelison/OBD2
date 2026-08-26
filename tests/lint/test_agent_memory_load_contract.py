################################################################################
# File Name: test_agent_memory_load_contract.py
# Purpose/Description: M2 standing-rule lint -- shared agent memory moved out of
#     Claude Code's cwd-keyed auto-load directory into the fleet share, because
#     per-ticket worktrees would each resolve to their own EMPTY memory dir and
#     boot with no project memory, silently. The move only works while the
#     /init-<role> commands load it EXPLICITLY. At the time of the move NO init
#     command referenced MEMORY.md at all -- memory reached agents purely by
#     auto-load -- so deleting these lines would restore that silent failure with
#     nothing to catch it. This lint is that catch.
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
# ================================================================================
################################################################################

"""Lint: the shared-memory explicit-load contract survives edits.

Shared memory lives at ``$FLEET_SHARE/knowledge/memory/MEMORY.md``. It is loaded
explicitly rather than by Claude Code's auto-load, which is keyed to the working
directory and therefore empty inside every per-ticket bench worktree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

COMMANDS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "commands"

MEMORY_REF = "knowledge/memory/MEMORY.md"

# The interactive roles. Ralph is deliberately absent -- see the test below.
INTERACTIVE_INIT_COMMANDS = [
    "init-arch.md",
    "init-pm.md",
    "init-tester.md",
    "init-tuner.md",
    "init-uidev.md",
]

# The pre-M2 auto-load directory, matched by its cwd-derived slug so the check
# is blind to path style and case. Any command still naming it points at a
# tombstone; the 63 files beside it are orphans nothing indexes.
DEAD_AUTOLOAD_SLUG = "z--o-obd2v2"  # the cwd-derived project-dir slug, any path style


@pytest.mark.parametrize("commandName", INTERACTIVE_INIT_COMMANDS)
def test_initCommand_loadsSharedMemoryExplicitly(commandName: str) -> None:
    """
    Given: an interactive /init-<role> command
    When: its text is read
    Then: it names the share copy of MEMORY.md

    Auto-load cannot be relied on: it resolves per working directory, and fleet
    benches are per-ticket worktrees. Without this line the role boots with no
    project memory and nothing says so.
    """
    path = COMMANDS_DIR / commandName
    assert path.is_file(), f"missing init command: {path}"

    assert MEMORY_REF in path.read_text(encoding="utf-8"), (
        f"{commandName} no longer loads shared memory. "
        f"Expected a reference to {MEMORY_REF!r}."
    )


def test_initRalph_doesNotLoadSharedMemory() -> None:
    """
    Given: Ralph's init command
    When: its text is read
    Then: it does NOT load MEMORY.md

    This is a carve-out, not an omission. Ralph runs headless per iteration under
    the scope.filesToRead rule -- the sprint contract IS his context. Adding a
    memory load here would contradict that rule and bloat every iteration. This
    test exists so the carve-out reads as deliberate to the next person.
    """
    text = (COMMANDS_DIR / "init-ralph.md").read_text(encoding="utf-8")

    assert MEMORY_REF not in text, (
        "init-ralph.md now loads shared memory. That contradicts the "
        "scope.filesToRead rule. If this is intended, delete this test and say why."
    )


def test_noCommand_pointsAtTheDeadAutoloadDirectory() -> None:
    """
    Given: every slash command
    When: their text is read
    Then: none names the pre-M2 auto-load memory directory

    That path now holds a tombstone plus 63 orphaned copies. A command that reads
    it gets stale facts; a command that WRITES it silently reaches no agent.
    """
    offenders = [
        p.name
        for p in sorted(COMMANDS_DIR.glob("*.md"))
        if DEAD_AUTOLOAD_SLUG in p.read_text(encoding="utf-8").lower()
    ]

    assert not offenders, (
        f"commands still naming the dead auto-load memory dir: {offenders}. "
        f"Use $FLEET_SHARE/{MEMORY_REF} instead."
    )
