################################################################################
# File Name: test_reassert_obd_mac.py
# Purpose/Description: pytest wrapper around tests/deploy/test_reassert_obd_mac.sh
#                      (US-477). Drives the bash self-heal test via subprocess so
#                      the fixture-based MAC-correction scenarios run inside the
#                      suite. Also statically asserts deploy-pi.sh wires the
#                      canonical-MAC re-assert on every deploy (not just --init)
#                      and that step_install_rfcomm_bind binds the repo-canonical
#                      MAC rather than the Pi's (possibly drifted) .env.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-20    | Rex (US-477) | Initial implementation.
# ================================================================================
################################################################################

"""pytest wrapper + static wiring assertions for the OBDLink MAC self-heal."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BASH_TEST = REPO_ROOT / "tests" / "deploy" / "test_reassert_obd_mac.sh"
REASSERT_SCRIPT = REPO_ROOT / "deploy" / "reassert-obd-mac.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


def _deployText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_reassertObdMac_bashSuitePasses():
    """The bash self-heal test (fixture scenarios) must exit 0."""
    assert BASH_TEST.is_file(), f"Missing bash test at {BASH_TEST}"
    assert REASSERT_SCRIPT.is_file(), f"Missing script under test at {REASSERT_SCRIPT}"
    result = subprocess.run(
        ["bash", str(BASH_TEST)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
    assert result.returncode == 0, (
        f"reassert-obd-mac.sh bash suite failed (exit={result.returncode})"
    )


def test_deployPi_reassertStep_runsEveryDeploy_notInitOnly():
    """The MAC re-assert must run unconditionally, not gated behind `if $INIT`.

    Self-heal only works if it runs on the routine re-deploy that follows a
    drift -- gating it behind --init (like step_install_rfcomm_bind) would mean
    a drifted Pi stays broken until someone remembers to --init.
    """
    text = _deployText()
    assert "step_reassert_obd_mac() {" in text, (
        "deploy-pi.sh must define step_reassert_obd_mac"
    )
    # A top-level (column-0, unindented) invocation proves the call is in the
    # every-deploy orchestration -- a call gated behind `if $INIT; then` would be
    # indented (like `    step_install_rfcomm_bind`). This is the self-heal that
    # must run on routine re-deploys, mirroring step_enforce_eeprom_power_off_on_halt.
    assert "\nstep_reassert_obd_mac\n" in text, (
        "step_reassert_obd_mac must be invoked unindented at top level (runs on "
        "every deploy), NOT gated behind `if $INIT`."
    )
    # And it must precede the --init-only rfcomm bind in the orchestration.
    callIdx = text.index("\nstep_reassert_obd_mac\n")
    rfcommCallIdx = text.index("\n    step_install_rfcomm_bind")
    assert callIdx < rfcommCallIdx, (
        "step_reassert_obd_mac should run before the --init-only rfcomm bind."
    )


def test_deployPi_rfcommBind_usesCanonicalMac_notPiEnv():
    """step_install_rfcomm_bind must bind the repo-canonical $OBD_BT_MAC.

    Trusting the Pi's own .env (the old piEnvMac ssh-pull) is exactly how the
    2026-07-17 phantom propagated into the rfcomm bind. The bind MAC is now the
    SSOT ($OBD_BT_MAC from deploy/addresses.sh).
    """
    text = _deployText()
    needle = "step_install_rfcomm_bind() {"
    start = text.find(needle)
    assert start > -1, "step_install_rfcomm_bind not found"
    body = text[start : text.find("\n}\n", start) + 2]
    assert "$OBD_BT_MAC" in body, (
        "step_install_rfcomm_bind must pass the canonical $OBD_BT_MAC to "
        "install-rfcomm-bind.sh"
    )
    assert "piEnvMac" not in body, (
        "step_install_rfcomm_bind must NOT re-introduce the piEnvMac .env-trust "
        "pull -- that is the drift-propagation path US-477 closes."
    )
