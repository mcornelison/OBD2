################################################################################
# File Name: test_documented_tooling_exists.py
# Purpose/Description: Standing-rule lint -- if CLAUDE.md's Bench Discipline names
#     a script as the required path, that script must exist IN THIS REPO. It named
#     New-Bench.ps1 and Invoke-FleetMerge.ps1 while they lived at
#     C:\agents\_fleet\scripts: outside the repo, outside the share, unversioned,
#     and mentioned by no file an agent reads. An agent went to lease a bench on
#     2026-08-27, could not find either script, and correctly reported that the
#     documented procedure had no implementation on disk. It blocked every agent.
#     Documentation that names a tool is a promise; this test makes it checkable.
# Author: Claude (post-incident)
# Creation Date: 2026-08-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-27    | Claude       | Initial -- named bench tooling must be present.
# ================================================================================
################################################################################

"""Lint: bench tooling named by CLAUDE.md must exist in the repo."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
FLEET_TOOLS = REPO_ROOT / "tools" / "fleet"

REQUIRED_SCRIPTS = ["New-Bench.ps1", "Invoke-FleetMerge.ps1"]


@pytest.mark.parametrize("name", REQUIRED_SCRIPTS)
def test_namedBenchScript_existsInTheRepo(name: str) -> None:
    """
    Given: a script CLAUDE.md names as the required path for bench work
    When: the repo is checked
    Then: it is present under tools/fleet/

    Being reachable on the author's machine is not enough. An agent reads
    CLAUDE.md from a bench or an office and has no way to guess an absolute path
    outside the repo.
    """
    path = FLEET_TOOLS / name

    assert path.is_file(), (
        f"CLAUDE.md names {name} as required bench tooling but it is not at "
        f"{path}. That is the 2026-08-27 failure: documented procedure, no "
        f"implementation on disk, every agent blocked."
    )
    assert path.stat().st_size > 0, f"{name} is present but empty"


@pytest.mark.parametrize("name", REQUIRED_SCRIPTS)
def test_namedBenchScript_isTracked(name: str) -> None:
    """
    Given: the same script
    When: git's index is consulted
    Then: it is tracked

    Present-but-untracked is the state that caused this: the files existed, so
    anyone checking `ls` would call it fine, while a fresh clone got nothing.
    tools/* is gitignored, so tools/fleet/ needs its negation to stay in place.
    """
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", f"tools/fleet/{name}"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, (
        f"tools/fleet/{name} is not tracked by git. It would be absent from every "
        f"fresh clone and every new bench. Check the !tools/fleet/ negation in "
        f".gitignore."
    )


def test_claudeMd_pointsAtTheInRepoToolingPath() -> None:
    """
    Given: CLAUDE.md's Bench Discipline section
    When: its lease instructions are read
    Then: they reference tools/fleet, not the old out-of-repo location

    The old path is the trap: it still exists on the author's machine, so a
    stale instruction keeps working for exactly one person.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")

    assert "tools/fleet" in text or "tools\fleet" in text, (
        "CLAUDE.md must point at tools/fleet/ for bench tooling"
    )
    assert "_fleet" not in text, (
        "CLAUDE.md still references the out-of-repo _fleet path, which "
        "only resolves on one machine"
    )
