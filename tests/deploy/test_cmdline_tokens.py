################################################################################
# File Name: test_cmdline_tokens.py
# Purpose/Description: pytest wrapper + static guards for the shared cmdline.txt
#                      token helper (deploy/lib/cmdline-tokens.sh). Drives
#                      tests/deploy/test_cmdline_tokens.sh via subprocess so the
#                      bash scenarios run in the fast suite, and adds the guards
#                      bash cannot express: the helper is a sourced library with
#                      no timed waits, and it is the ONLY cmdline.txt editor.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Rex          | Initial implementation (Sprint 113 US-885-a)
# ================================================================================
################################################################################

"""pytest wrapper around tests/deploy/test_cmdline_tokens.sh + static guards.

The .sh script is the behavioural catalog: idempotent add (twice -> one token),
remove-absent byte-identical, multi-line and root=-less files refused untouched,
root= never removable, first-write-wins backup, and two writers in either order
giving the union of their tokens. This file is the pytest entry point.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = REPO_ROOT / "tests" / "deploy" / "test_cmdline_tokens.sh"
LIB = REPO_ROOT / "deploy" / "lib" / "cmdline-tokens.sh"
MODE_SCRIPT = REPO_ROOT / "deploy" / "set-display-mode.sh"
DEPLOY_DIR = REPO_ROOT / "deploy"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _codeLines(text: str) -> list[str]:
    """Return executable-looking lines only: comments and blanks stripped."""
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_cmdlineTokens_allScenariosPass():
    """
    Given: synthetic one-line (and malformed) cmdline.txt fixtures
    When: the helper's add/remove/check functions run against each
    Then: every scenario's return code, file bytes and message assertion holds
    """
    assert TEST_SCRIPT.exists(), f"missing bash catalog: {TEST_SCRIPT}"
    result = subprocess.run(
        ["bash", str(TEST_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, (
        f"cmdline-tokens bash catalog failed (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert re.search(r"===\s*Results:\s*\d+\s*passed,\s*0\s*failed", result.stdout), (
        f"expected a zero-failure summary, got:\n{result.stdout[-600:]}"
    )


def test_cmdlineTokens_isALibraryThatNeverExits():
    """
    Given: the helper is SOURCED into its callers
    When: its executable lines are scanned
    Then: no `exit` (that would end the caller) and no `set -e`/`set -u` change
          to the caller's shell options -- every outcome is a return code
    """
    lines = _codeLines(LIB.read_text(encoding="utf-8"))
    exits = [ln for ln in lines if re.search(r"(^|[;&|]\s*)exit\b", ln)]
    assert not exits, f"a sourced helper must return, never exit: {exits}"
    setOpts = [ln for ln in lines if re.match(r"set\s+[-+]", ln)]
    assert not setOpts, f"a sourced helper must not change caller shell options: {setOpts}"


def test_cmdlineTokens_hasNoTimedWait():
    """
    Given: the CIO's NO TIMER rule (2026-10-23)
    When: the helper's executable lines are scanned
    Then: no sleep, wait or timeout appears in them
    """
    lines = _codeLines(LIB.read_text(encoding="utf-8"))
    offenders = [ln for ln in lines if re.search(r"\b(sleep|wait|timeout)\b", ln)]
    assert not offenders, f"cmdline-tokens.sh must contain no timed wait: {offenders}"


def test_cmdlineTokens_isTheOnlyCmdlineInstaller():
    """
    Given: two deploy scripts edit the one boot line
    When: every deploy/*.sh is scanned for the temp-file name the installer uses
    Then: only the helper composes and installs cmdline.txt; set-display-mode.sh
          goes through it
    """
    owners = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in DEPLOY_DIR.rglob("*.sh")
        if ".cmdline.txt.eclipse-tmp" in path.read_text(encoding="utf-8")
    )
    assert owners == ["deploy/lib/cmdline-tokens.sh"], (
        f"expected only the shared helper to install cmdline.txt, found {owners}"
    )
    modeLines = _codeLines(MODE_SCRIPT.read_text(encoding="utf-8"))
    assert any("lib/cmdline-tokens.sh" in ln for ln in modeLines), (
        "set-display-mode.sh must source the shared helper"
    )
