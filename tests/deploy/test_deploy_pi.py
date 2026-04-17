################################################################################
# File Name: test_deploy_pi.py
# Purpose/Description: pytest wrapper for deploy/deploy-pi.sh smoke test.
#                      Drives the bash test_deploy_pi.sh via subprocess so the
#                      flag-parsing + dry-run safety checks run automatically
#                      inside the existing test suite. The bash script remains
#                      the canonical, runnable-by-hand smoke test (per
#                      Sprint 10 US-176 acceptance criterion).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex          | Initial implementation (Sprint 10 US-176)
# ================================================================================
################################################################################

"""pytest wrapper around tests/deploy/test_deploy_pi.sh.

The .sh script is the source of truth for what's verified — see that file for
the assertion catalog. This wrapper exists so `pytest tests/` exercises it
automatically and so a regression in deploy-pi.sh shows up in the same fast
suite as the rest of the project.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SMOKE_TEST = REPO_ROOT / "tests" / "deploy" / "test_deploy_pi.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_smokeTestPasses():
    """The bash smoke test (test_deploy_pi.sh) must exit 0 on a clean tree.

    Forwards stdout to the pytest captured output so any assertion failure
    inside the .sh test is visible from `pytest -v`.
    """
    assert SMOKE_TEST.is_file(), f"Missing smoke test at {SMOKE_TEST}"
    assert DEPLOY_SCRIPT.is_file(), f"Missing script under test at {DEPLOY_SCRIPT}"
    result = subprocess.run(
        ["bash", str(SMOKE_TEST)],
        capture_output=True,
        text=True,
        # Generous timeout: the .sh test forks ~10 sub-bash invocations of
        # deploy-pi.sh, and a NAS-mounted repo (chi-nas-01 SMB) makes each
        # invocation noticeably slower than local-disk. 90s is comfortable
        # headroom for both local-disk runs (~5s) and NAS runs (~35-50s).
        timeout=90,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
    assert result.returncode == 0, (
        f"deploy-pi.sh smoke test failed (exit={result.returncode})"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_helpFlagExitsCleanly():
    """`deploy-pi.sh --help` must exit 0 and print usage."""
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "Usage: bash deploy/deploy-pi.sh" in result.stdout
    assert "--init" in result.stdout
    assert "--restart" in result.stdout
    assert "--dry-run" in result.stdout


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_unknownFlagRejected():
    """Unknown flags must exit 2 and name the offending arg."""
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--nope"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "--nope" in result.stderr or "--nope" in result.stdout
