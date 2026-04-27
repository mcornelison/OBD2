################################################################################
# File Name: test_journald_persistent_install.py
# Purpose/Description: pytest wrapper for the US-230 journald install-time
#                      acceptance test. Runs the bash script via subprocess
#                      so the fast suite surfaces a regression in Pi-side
#                      persistent-journal state. The bash script is the
#                      source of truth (runnable by hand during a live
#                      deploy drill); this wrapper is the CI/pytest
#                      integration point matching test_deploy_pi.py.
#
#                      Skip semantics: when the underlying bash script
#                      exits 77 (autotools SKIP convention -- triggered
#                      when SSH to the Pi is unreachable), pytest records
#                      the test as skipped rather than failed. That keeps
#                      CI runners without Pi access green while still
#                      exercising the assertions on the CIO workstation.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex          | Initial implementation (Sprint 18 US-230)
# ================================================================================
################################################################################

"""pytest wrapper for tests/deploy/test_journald_persistent_install.sh."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = REPO_ROOT / "tests" / "deploy" / "test_journald_persistent_install.sh"
SKIP_EXIT_CODE = 77


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_journaldPersistentInstall_postDeployState():
    """Verify persistent journald state on the Pi post-deploy (US-230).

    Delegates to the bash script. If SSH to the Pi is unreachable the bash
    script exits 77 (autotools SKIP convention) and this test is reported
    as skipped, not failed -- that keeps CI runners without Pi access from
    flagging the sprint suite red.
    """
    assert TEST_SCRIPT.is_file(), f"Missing test script at {TEST_SCRIPT}"

    result = subprocess.run(
        ["bash", str(TEST_SCRIPT)],
        capture_output=True,
        text=True,
        # The bash script does two SSH calls (5s + 10s connect timeouts).
        # On a healthy Pi the whole test finishes in ~15-25s; 45s is
        # comfortable headroom for slow first-hops (fresh key cache,
        # NAS-mounted repo, etc.).
        timeout=45,
    )

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode == SKIP_EXIT_CODE:
        pytest.skip("SSH to Pi unreachable (bash test exited 77)")

    assert result.returncode == 0, (
        f"journald persistent-install test failed (exit={result.returncode})"
    )
