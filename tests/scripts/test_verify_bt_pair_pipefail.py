################################################################################
# File Name: test_verify_bt_pair_pipefail.py
# Purpose/Description: Regression for the rfcomm-bind "installed" false-FAIL in
#                      scripts/verify_bt_pair.sh. Under `set -o pipefail`,
#                      `systemctl ... | grep -q` lets grep exit at the first match,
#                      systemctl dies of SIGPIPE and the pipe reads as FAILED.
#                      Live on 2026-10-12 this failed 18/20 with the unit
#                      installed, enabled and active, and turned a passing
#                      pre-drive gate (US-487) into CAPTURE: FAIL.
# Author: Atlas (architect)
# Creation Date: 2026-10-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-12    | Atlas        | Initial implementation (US-487).
# ================================================================================
################################################################################

"""verify_bt_pair.sh must not read an installed rfcomm-bind unit as missing."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "verify_bt_pair.sh"
MAC = "00:04:3E:85:0D:FB"

# The match comes FIRST, then far more output than a pipe buffer holds, so a
# grep that quits early is guaranteed to leave systemctl writing into a closed pipe.
_FAKE_SYSTEMCTL = """#!/usr/bin/env bash
case "$1" in
  list-unit-files)
    echo "rfcomm-bind.service                          enabled         enabled"
    for i in $(seq 1 20000); do echo "filler-$i.service                    static          -"; done ;;
  is-enabled|is-active) exit 0 ;;
  status)
    echo "rfcomm-bind.service - OBDLink LX rfcomm bind"
    echo "  Process: 1 ExecStart=/bin/true (code=exited, status=0/SUCCESS)"
    for i in $(seq 1 20000); do echo "filler $i"; done ;;
esac
exit 0
"""


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_verifyBtPair_installedUnitWithLongListing_isNotReportedMissing(tmp_path):
    fakeBin = tmp_path / "bin"
    fakeBin.mkdir()
    fake = fakeBin / "systemctl"
    fake.write_bytes(_FAKE_SYSTEMCTL.encode())
    fake.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{fakeBin.as_posix()}{os.pathsep}{env.get('PATH', '')}"

    for _ in range(5):
        result = subprocess.run(
            ["bash", "-c", f'PATH="{fakeBin.as_posix()}:$PATH" bash "{SCRIPT.as_posix()}" {MAC}'],
            capture_output=True, text=True, encoding="utf-8", timeout=120, env=env,
        )
        out = result.stdout + result.stderr
        assert "rfcomm-bind.service installed" not in out, out
        assert "rfcomm-bind.service enabled" in out, out
