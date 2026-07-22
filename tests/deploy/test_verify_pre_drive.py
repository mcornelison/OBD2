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
# 2026-07-22    | Rex (US-487) | Static assertions for the hardened gate:
#               |              | production-path verification after restart,
#               |              | non-authoritative exit codes (bench/koeo-only),
#               |              | and the DoD honesty note (no live race detection).
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


# --- US-487: pre-drive green-light hardening -----------------------------------


def test_wrapper_verifiesProductionPathAfterRestart():
    """FOLLOW-UP 1: after restarting eclipse-obd, the gate must prove the PRODUCTION
    path is capturing -- the unit is active AND new realtime_data rows land in
    data/obd.db -- so a GREEN can never coexist with a dead production service."""
    text = WRAPPER.read_text(encoding="utf-8")
    assert "systemctl is-active" in text, (
        "wrapper must confirm eclipse-obd is active after the restart"
    )
    assert "data/obd.db" in text, (
        "wrapper must check the PRODUCTION db (data/obd.db), not just the throwaway probe db"
    )
    assert "realtime_data" in text, "wrapper must count production realtime_data rows"
    # The production result must feed the final verdict (a dead service => no green).
    assert "PROD_RC" in text, "the production-capture result must gate the final verdict"
    # The final PASS is gated on the production result.
    assert 'PROD_RC" = "0"' in text, (
        "the final green verdict must require the production check to have passed"
    )


def test_wrapper_nonAuthoritativeModesReturnDistinctExit():
    """FOLLOW-UP 2: --bench and --koeo-only must NOT return the green exit 0 -- they
    return a distinct non-authoritative exit so they can't be mistaken for the gate."""
    text = WRAPPER.read_text(encoding="utf-8")
    assert "EXIT_NONAUTH=3" in text, (
        "wrapper must define a distinct non-authoritative exit code (3)"
    )
    assert 'exit "$EXIT_NONAUTH"' in text, (
        "bench + koeo-only successes must exit the non-authoritative code, not 0"
    )
    assert "NON-AUTHORITATIVE PASS" in text, (
        "wrapper must label bench/koeo-only passes as non-authoritative"
    )
    # The documented exit codes must mention the new code.
    assert "3 -- " in text, "the header exit-code table must document exit 3"


def test_wrapper_doesNotOverclaimLiveRaceDetection():
    """FOLLOW-UP 3 (DoD honesty): the gate must not claim live race DETECTION -- the
    interleave detector is a test-fake-only attribute, inert outside pytest. A live
    green rests on the single-connection I/O lock + the row/coverage floors."""
    lowered = WRAPPER.read_text(encoding="utf-8").lower()
    assert "iolock" in lowered, (
        "wrapper header must note live green rests on the I/O lock, not live race detection"
    )
    assert "interleave" in lowered, (
        "wrapper header must acknowledge the interleave detector is not the live signal"
    )
