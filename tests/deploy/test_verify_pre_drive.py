################################################################################
# File Name: test_verify_pre_drive.py
# Purpose/Description: pytest wrapper around tests/deploy/test_verify_pre_drive.sh
#                      (US-479). Drives the bash driver via subprocess so the
#                      CIO-runnable pre-drive green-light wrapper is exercised
#                      inside the suite, plus static assertions that the wrapper
#                      composes verify_bt_pair.sh + the connect-edge capture probe
#                      and reports the ordered steps + a final CAPTURE verdict.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-20    | Rex (US-479) | Initial implementation.
# ================================================================================
################################################################################

"""pytest wrapper + static wiring assertions for the pre-drive green-light gate."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BASH_TEST = REPO_ROOT / "tests" / "deploy" / "test_verify_pre_drive.sh"
WRAPPER = REPO_ROOT / "scripts" / "verify_pre_drive.sh"
PROBE = REPO_ROOT / "scripts" / "pre_drive_greenlight.py"


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_verifyPreDrive_bashDriverPasses():
    """The bash driver (incl. a real --bench run) must exit 0."""
    assert BASH_TEST.is_file(), f"Missing bash test at {BASH_TEST}"
    assert WRAPPER.is_file(), f"Missing wrapper at {WRAPPER}"
    result = subprocess.run(
        ["bash", str(BASH_TEST)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
    assert result.returncode == 0, (
        f"verify_pre_drive.sh bash driver failed (exit={result.returncode})"
    )


def test_wrapper_composesVerifyBtPairAndProbe():
    """The gate must compose verify_bt_pair.sh (BT/rfcomm) with the capture probe."""
    text = WRAPPER.read_text(encoding="utf-8")
    assert "verify_bt_pair.sh" in text, "wrapper must run verify_bt_pair.sh"
    assert "pre_drive_greenlight.py" in text, "wrapper must run the capture probe"
    # The canonical MAC comes from the SSOT, never hardcoded in the wrapper.
    assert 'MAC="${OBD_BT_MAC:-}"' in text, (
        "wrapper must default the MAC to the $OBD_BT_MAC SSOT (addresses.sh)"
    )
    assert "00:04:3E:85:0D:FB" not in text, (
        "wrapper must NOT hardcode the OBDLink MAC literal (SSOT is addresses.sh)"
    )


def test_wrapper_koeoBeforeLiveWindow():
    """The KOEO (engine-off) sub-check must precede the authoritative live window."""
    text = WRAPPER.read_text(encoding="utf-8")
    koeoIdx = text.index("--koeo-only")
    liveIdx = text.index("--live --duration")
    assert koeoIdx < liveIdx, "KOEO sub-check should be reported before the live window"


def test_probe_exercisesConnectEdge():
    """The probe must drive the connect-edge capture (logger + DTC on one conn)."""
    text = PROBE.read_text(encoding="utf-8")
    assert "runConnectEdgeCapture" in text, (
        "the probe must call runConnectEdgeCapture (the A-17 connect-edge exercise)"
    )
    assert "evaluateGate" in text, "the probe must apply the PASS/FAIL gate logic"
