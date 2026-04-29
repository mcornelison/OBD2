################################################################################
# File Name: test_obd_server_service_install.py
# Purpose/Description: pytest wrapper for tests/deploy/test_obd_server_service.sh.
#                      Mirror of US-230's test_journald_persistent_install.py
#                      pattern. Exit code 77 from the bash test (SSH unreachable)
#                      maps to pytest skip so CI runners without home-lab
#                      access stay green.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-27    | Rex          | Initial implementation (Sprint 18 US-231)
# ================================================================================
################################################################################

"""pytest wrapper for tests/deploy/test_obd_server_service.sh."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = REPO_ROOT / "tests" / "deploy" / "test_obd_server_service.sh"
SKIP_EXIT_CODE = 77


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_obdServerServiceInstall_postDeployState():
    """Verify obd-server.service post-install state on chi-srv-01 (US-231).

    Delegates to the bash script. Skipped when SSH to chi-srv-01 is unreachable
    (bash exits 77). When SSH is reachable but the unit is not yet installed
    (pre-cutover state), this test fails with a clear message -- expected to
    fail until the operator runs `bash deploy/deploy-server.sh` post-US-231.
    """
    assert TEST_SCRIPT.is_file(), f"Missing test script at {TEST_SCRIPT}"

    result = subprocess.run(
        ["bash", str(TEST_SCRIPT)],
        capture_output=True,
        text=True,
        # 5 SSH calls (10s connect timeout each) + a curl. 60s headroom is
        # comfortable for slow first-hops.
        timeout=60,
    )

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode == SKIP_EXIT_CODE:
        pytest.skip("SSH to chi-srv-01 unreachable (bash test exited 77)")

    assert result.returncode == 0, (
        f"obd-server.service post-install assertions failed "
        f"(exit={result.returncode}); see stdout above for which assertion."
    )
