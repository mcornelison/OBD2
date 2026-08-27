################################################################################
# File Name: test_init_command_bootstrap.py
# Purpose/Description: Standing-rule lint -- every /init-<role> command must be
#     able to find the fleet share even when $FLEET_SHARE is unset. The variable
#     is exported ONLY by a bench's bench.ps1; it is not persisted in the user or
#     machine environment. Interactive sessions are started from an office, not
#     from a bench, so for the way this fleet is actually driven the variable is
#     normally ABSENT -- and every init command addresses the share through it.
#     Without a stated fallback the agent resolves a literal "$FLEET_SHARE/..."
#     path, fails to find its charter, and improvises.
# Author: Claude (post-migration bootstrap fix)
# Creation Date: 2026-08-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-26    | Claude       | Initial -- fallback present, agreed, and never
#               |              | pointing at the frozen v2 tree.
# ================================================================================
################################################################################

"""Lint: the /init-<role> commands bootstrap without $FLEET_SHARE."""

from __future__ import annotations

from pathlib import Path

import pytest

COMMANDS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "commands"

# The canonical share. Lower-cased comparisons throughout: Windows paths are
# case-insensitive and the offices were normalised to lower case in the 2026-08-25
# sweep, so a case difference here is noise, not drift.
FALLBACK_SHARE = r"z:\o\obd2v3\offices"

# The frozen pre-migration tree. An agent sent here reads four-month-old
# charters and a backlog that no longer matches the repo -- and would look like
# it was working correctly while doing it.
FROZEN_V2 = r"z:\o\obd2v2"


def _initCommands() -> list[Path]:
    return sorted(COMMANDS_DIR.glob("init-*.md"))


def test_thereAreInitCommandsToCheck() -> None:
    """Guard the guard: a glob that matches nothing would pass every test below."""
    assert _initCommands(), f"no init-*.md commands found under {COMMANDS_DIR}"


@pytest.mark.parametrize("path", _initCommands(), ids=lambda p: p.name)
def test_initCommand_statesTheFallbackShare(path: Path) -> None:
    """
    Given: an /init-<role> command that addresses the share via $FLEET_SHARE
    When: its text is read
    Then: it also names the literal share path

    $FLEET_SHARE is exported by bench.ps1 only. It is set in neither the user nor
    the machine environment, so an interactive session launched from an office
    does not have it.
    """
    text = path.read_text(encoding="utf-8").lower()

    if "$fleet_share" not in text:
        pytest.skip(f"{path.name} does not address the share via $FLEET_SHARE")

    assert FALLBACK_SHARE in text, (
        f"{path.name} addresses $FLEET_SHARE but never states the literal "
        f"fallback {FALLBACK_SHARE!r}. With the variable unset the agent cannot "
        f"find its charter."
    )


@pytest.mark.parametrize("path", _initCommands(), ids=lambda p: p.name)
def test_initCommand_neverPointsAtTheFrozenV2Tree(path: Path) -> None:
    """
    Given: an /init-<role> command
    When: its text is read
    Then: it never sends the agent to the frozen v2 tree

    Except where it explicitly warns against it. The v2 tree still exists and
    still contains a full set of offices, so an agent pointed there boots
    successfully on stale content -- the failure looks like success.
    """
    for line in path.read_text(encoding="utf-8").lower().splitlines():
        if FROZEN_V2 in line and "do not" not in line:
            pytest.fail(
                f"{path.name} references the frozen v2 tree outside a warning: "
                f"{line.strip()!r}"
            )
