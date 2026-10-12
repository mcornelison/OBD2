################################################################################
# File Name: test_init_command_bootstrap.py
# Purpose/Description: Standing-rule lint -- every office must be able to find the
#     fleet share even when $FLEET_SHARE is unset. The variable is exported ONLY
#     by a bench's bench.ps1; it is not persisted in the user or machine
#     environment. Interactive sessions are started from an office, not from a
#     bench, so for the way this fleet is actually driven the variable is normally
#     ABSENT. Without a stated fallback the agent resolves a literal
#     "$FLEET_SHARE/..." path, fails to find its charter, and improvises.
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
# 2026-09-03    | Claude (V2)  | Retargeted for the V1->V2 upgrade. The RULE is
#               |              | unchanged; the artifact carrying it moved. The
#               |              | /init-<role> commands were retired for the
#               |              | universal `hello` skill, and the paths preamble
#               |              | they carried moved into each office's own
#               |              | CLAUDE.md Boot section. Checking commands that no
#               |              | longer exist would be a green light over an empty
#               |              | set -- so this checks the offices instead.
# ================================================================================
################################################################################

"""Lint: every office boots without $FLEET_SHARE."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# The generated path file, reached as ..\fleet.md -- one level up from every
# office. It is generated FROM fleet.json, so it cannot drift from the real layout.
FLEET_MD = "fleet.md"

# The frozen pre-migration tree. An agent sent here reads months-old charters and a
# backlog that no longer matches the repo -- and would look like it was working
# correctly while doing it.
FROZEN_V2 = r"z:\o\obd2v2"

OFFICES = ["architect", "pm", "ralph", "tester", "tuner", "uideveloper"]


def _officesRoot():
    share = os.environ.get("FLEET_SHARE")
    if not share:
        return None
    root = Path(share)
    return root if root.is_dir() else None


def _bootSection(text: str) -> str:
    """Just the ## Boot section, lower-cased.

    The frozen-tree rule is about BOOT pointers, and it used to be applied to
    init-<role>.md -- files that were nothing BUT boot instructions. A charter is
    not: architect/CLAUDE.md legitimately names z:\\o\\obd2v2 as the NAS monorepo
    the server runs from, which is a statement of fact, not a place to boot from.
    Checking the whole charter failed that line and would have pushed someone to
    either delete a true sentence or widen the warned-word list until the rule
    meant nothing. Scope the check to where the rule actually applies.
    """
    lines = text.lower().splitlines()
    out, inside = [], False
    for line in lines:
        if line.startswith("## boot"):
            inside = True
            continue
        if inside and (line.startswith("## ") or line.strip() == "---"):
            break
        if inside:
            out.append(line)
    return "\n".join(out)


def test_thereAreOfficeCharactersToCheck() -> None:
    """Guard the guard: an empty set would pass every test below.

    This replaces the old test_thereAreInitCommandsToCheck. Its job is identical
    and it is the reason the V2 upgrade did not pass silently: when the init
    commands were retired, that guard failed loudly instead of letting a
    parametrised suite report success over zero cases.
    """
    root = _officesRoot()
    if root is None:
        pytest.skip(
            "FLEET_SHARE unset or unreachable -- the office boot tests below did "
            "NOT run. Set FLEET_SHARE to the offices root."
        )
    found = [o for o in OFFICES if (root / o / "CLAUDE.md").is_file()]
    assert found == OFFICES, (
        f"expected a CLAUDE.md for every office {OFFICES}, found {found} under {root}"
    )


@pytest.mark.parametrize("office", OFFICES)
def test_officeBoot_pointsAtTheGeneratedPathFile(office: str) -> None:
    """
    Given: an office charter
    When: its text is read
    Then: it names the generated path file

    $FLEET_SHARE is exported by bench.ps1 only. It is set in neither the user nor
    the machine environment, so an interactive session launched from an office does
    not have it. The office must therefore reach the layout by a RELATIVE path it
    can always resolve.
    """
    root = _officesRoot()
    if root is None:
        pytest.skip("FLEET_SHARE unset -- see test_thereAreOfficeCharactersToCheck")

    # Scoped to the Boot section too: the pointer has to be on the path the agent
    # actually reads at startup, not merely present somewhere in a 100 KB charter.
    text = _bootSection((root / office / "CLAUDE.md").read_text(encoding="utf-8"))
    assert text.strip(), f"{office}/CLAUDE.md has no '## Boot' section"
    assert FLEET_MD in text, (
        f"{office}/CLAUDE.md never points at {FLEET_MD!r}. With $FLEET_SHARE unset "
        f"-- which is every interactive office session -- the agent has no way to "
        f"resolve the share."
    )


@pytest.mark.parametrize("office", OFFICES)
def test_officeBoot_neverPointsAtTheFrozenV2Tree(office: str) -> None:
    """
    Given: an office charter
    When: its text is read
    Then: it never sends the agent to the frozen v2 tree

    Except where it explicitly warns against it. The v2 tree still exists and still
    contains a full set of offices, so an agent pointed there boots successfully on
    stale content -- the failure looks like success.
    """
    root = _officesRoot()
    if root is None:
        pytest.skip("FLEET_SHARE unset -- see test_thereAreOfficeCharactersToCheck")

    boot = _bootSection((root / office / "CLAUDE.md").read_text(encoding="utf-8"))
    assert boot.strip(), f"{office}/CLAUDE.md has no '## Boot' section to check"

    for line in boot.splitlines():
        # Recognise a WARNING, not one exact phrase. The first version of this test
        # whitelisted only "do not" and then failed on a guard that said "Never fall
        # back to ..." -- a test too literal about how a rule is worded rejects
        # correct code for cosmetic reasons.
        warned = any(w in line for w in ("do not", "never", "frozen", "pre-migration"))
        if FROZEN_V2 in line and not warned:
            pytest.fail(
                f"{office}/CLAUDE.md references the frozen v2 tree outside a "
                f"warning: {line.strip()!r}"
            )
