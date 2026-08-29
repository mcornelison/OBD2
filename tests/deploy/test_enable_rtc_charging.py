################################################################################
# File Name: test_enable_rtc_charging.py
# Purpose/Description: pytest wrapper + deploy-wiring guards for the US-620 Pi 5
#                      RTC trickle-charge boot-config step. Drives
#                      tests/deploy/test_enable_rtc_charging.sh via subprocess so
#                      the bash scenarios (fixture config.txt files behind the
#                      $PI_CONFIG_TXT seam) run in the fast suite, and pins that
#                      deploy-pi.sh actually DEFINES and CALLS the step after
#                      sync_tree, on every deploy, with the script inside the
#                      rsync whitelist that puts it on the Pi.
#
#                      Mirrors the test_set_gpu_cma.py pattern: the bash script
#                      is the source of truth for behavioural assertions; this
#                      file is the pytest entry point and adds the static wiring
#                      guards bash cannot express cleanly.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex          | Initial implementation (Sprint 77 US-620)
# ================================================================================
################################################################################

"""pytest wrapper around tests/deploy/test_enable_rtc_charging.sh + wiring guards.

The .sh script is the canonical assertion catalog (14 scenarios over synthetic
/boot/firmware/config.txt fixtures: the live Pi's shape, idempotent re-run, a
foreign charge voltage, an explicit `=0`, a non-applicable EOF section, a
commented-out line, a param stranded in [cm4], missing file, an out-of-range and
a non-numeric voltage, pristine-backup semantics, and coexistence with the
set-gpu-cma.sh edits to the same file).

The Python guards here cover the OTHER half of the story, which the bash catalog
structurally cannot: a byte-perfect enable-rtc-charging.sh that deploy-pi.sh
never invokes -- or that the rsync whitelist never copies to the Pi -- ships
nothing. That is the recurring "two correct halves, never connected" defect
class (US-494/499/502/503/505/513), and US-573 records the whitelist variant of
it explicitly: a whitelist omission fails by SILENCE, because the file is simply
absent on the target.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = REPO_ROOT / "tests" / "deploy" / "test_enable_rtc_charging.sh"
RTC_SCRIPT = REPO_ROOT / "deploy" / "enable-rtc-charging.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"

STEP_NAME = "step_enable_rtc_charging"

# The fix, exactly as US-620 specifies it.
GROUNDED_VCHG_UV = "3000000"

# /sys/class/rtc/rtc0/charging_voltage_max, measured on chi-eclipse-01
# 2026-08-28. The only grounded bound the story supplies.
MEASURED_CHARGING_VOLTAGE_MAX_UV = "4400000"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _readDeployScript() -> str:
    """Return deploy-pi.sh text."""
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _codeLines(text: str) -> list[str]:
    """Return only executable-looking lines: comments and blanks stripped.

    US-501/US-513/US-522 lesson: a guard that greps raw file text is satisfied
    by the explanatory COMMENT that documents the thing it is checking for. All
    wiring assertions below run against this stripped view so a comment
    mentioning `step_enable_rtc_charging` can never make them pass.
    """
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


# --------------------------------------------------------------------------
# Behavioural catalog (the real gate)
# --------------------------------------------------------------------------


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_enableRtcCharging_allScenariosPass():
    """The bash test (test_enable_rtc_charging.sh) must exit 0.

    Given: 14 synthetic config.txt fixtures behind the $PI_CONFIG_TXT seam
    When: deploy/enable-rtc-charging.sh is run against each
    Then: every scenario's exit code, file mutation and message assertion holds
    """
    assert TEST_SCRIPT.exists(), f"missing bash catalog: {TEST_SCRIPT}"
    result = subprocess.run(
        ["bash", str(TEST_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"enable-rtc-charging bash catalog failed (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert re.search(r"===\s*Results:\s*\d+\s*passed,\s*0\s*failed", result.stdout), (
        f"expected a zero-failure summary, got:\n{result.stdout[-600:]}"
    )


# --------------------------------------------------------------------------
# Wiring guards -- the half the bash catalog cannot see
# --------------------------------------------------------------------------


def test_enableRtcCharging_scriptExistsAndIsExecutableBash():
    """The production script exists and is a bash script."""
    assert RTC_SCRIPT.exists(), f"missing production script: {RTC_SCRIPT}"
    firstLine = RTC_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert firstLine.startswith("#!"), "enable-rtc-charging.sh needs a shebang"
    assert "bash" in firstLine, f"expected a bash shebang, got: {firstLine}"


def test_deployPi_definesAndCallsTheRtcStep():
    """deploy-pi.sh must both DEFINE and CALL step_enable_rtc_charging.

    A definition with no call site is the exact shape of a fix that passes
    every test and ships nothing.
    """
    lines = _codeLines(_readDeployScript())
    definitions = [ln for ln in lines if ln.startswith(f"{STEP_NAME}()")]
    calls = [ln for ln in lines if ln == STEP_NAME]
    assert len(definitions) == 1, f"expected exactly 1 definition of {STEP_NAME}, got {definitions}"
    assert len(calls) == 1, f"expected exactly 1 call to {STEP_NAME}, got {calls}"


def test_deployPi_callsRtcStepAfterSyncTree():
    """The call site must come AFTER sync_tree.

    enable-rtc-charging.sh is executed ON THE PI from ${PI_PATH}/deploy/. If the
    step ran before the tree was rsynced, a first-ever deploy would invoke a file
    that is not there yet. Asserted against deploy-pi.sh's own call order -- the
    artifact that ENFORCES the ordering, not a manifest that describes it
    (US-513 lesson).
    """
    lines = _codeLines(_readDeployScript())
    callIdx = [i for i, ln in enumerate(lines) if ln == STEP_NAME]
    syncIdx = [i for i, ln in enumerate(lines) if ln == "sync_tree"]
    assert callIdx, f"{STEP_NAME} is never called"
    assert syncIdx, "sync_tree is never called -- ordering guard cannot be evaluated"
    assert min(syncIdx) < callIdx[0], (
        f"{STEP_NAME} (line index {callIdx[0]}) must run after sync_tree "
        f"(line index {min(syncIdx)})"
    )


def test_deployPi_rtcStepRunsEveryDeploy_notInitOnly():
    """The step must run unconditionally, not gated behind `if $INIT`.

    US-620 AC6: the fix "must survive a config.txt rewritten by an OS image
    update". config.txt is OS-shipped and can be rewritten out-of-band by
    rpi-update, an image upgrade or raspi-config, so the re-assertion only works
    if it happens on the ROUTINE re-deploy that follows the drift. Gating it
    behind --init would mean a drifted Pi keeps stamping 1970 until someone
    remembers to --init.

    A top-level (column-0, unindented) invocation proves the call is in the
    every-deploy orchestration; a call inside `if $INIT; then` would be indented,
    like `    step_install_rfcomm_bind`. Same guard as US-477's
    test_reassert_obd_mac.
    """
    text = _readDeployScript()
    assert f"\n{STEP_NAME}\n" in text, (
        f"{STEP_NAME} must be invoked unindented at top level (runs on every "
        "deploy), NOT gated behind `if $INIT`."
    )


def test_deployPi_rtcStepHonoursDryRun():
    """The step must have a DRY_RUN branch that returns before touching the Pi.

    A deploy --dry-run that rewrites the boot partition would be a genuinely
    destructive surprise.
    """
    text = _readDeployScript()
    start = text.index(f"{STEP_NAME}()")
    end = text.index("\nstep_", start + 1)
    body = text[start:end]
    assert "$DRY_RUN" in body, f"{STEP_NAME} has no DRY_RUN branch"
    dryIdx = body.index("$DRY_RUN")
    remoteIdx = body.index("remote ")
    assert dryIdx < remoteIdx, "the DRY_RUN guard must precede the remote invocation"
    assert "return 0" in body[dryIdx:remoteIdx], "the DRY_RUN branch must return before remote"
    assert "enable-rtc-charging.sh" in body, (
        f"{STEP_NAME} must invoke deploy/enable-rtc-charging.sh"
    )


def test_deployPi_syncWhitelistCarriesTheRtcScript():
    """The rsync whitelist must actually copy the script to the Pi.

    US-573: Pi sync is a WHITELIST, and "a whitelist omission fails by SILENCE
    -- the file is simply absent". A perfectly wired step that invokes a file
    the sync never sent fails on the Pi, at deploy time, with the boot config
    left untouched. `--include=deploy/*.sh` is what carries this script; pin it,
    and pin that no later `--exclude` singles the script back out.
    """
    lines = _codeLines(_readDeployScript())
    includes = [ln for ln in lines if "--include=deploy/*.sh" in ln]
    assert includes, (
        "the Pi rsync whitelist must carry `--include=deploy/*.sh` -- without it "
        "enable-rtc-charging.sh never reaches the Pi and the step invokes a "
        "missing file."
    )
    offenders = [
        ln for ln in lines if "--exclude=" in ln and "enable-rtc-charging" in ln
    ]
    assert not offenders, (
        f"enable-rtc-charging.sh is explicitly excluded from the Pi sync: {offenders}"
    )


def test_enableRtcCharging_defaultsToTheGroundedVoltage():
    """The default charge voltage is the US-620 value, 3000000 uV (3.000 V)."""
    text = RTC_SCRIPT.read_text(encoding="utf-8")
    assert re.search(rf"ECLIPSE_RTC_BBAT_VCHG_UV:-{GROUNDED_VCHG_UV}\b", text), (
        f"enable-rtc-charging.sh must default to {GROUNDED_VCHG_UV} uV "
        "(US-620: `dtparam=rtc_bbat_vchg=3000000`)"
    )


def test_enableRtcCharging_ceilingIsPinnedToTheMeasuredRegister():
    """The upper bound is the hardware's own stated maximum, not a guess.

    Grounded on /sys/class/rtc/rtc0/charging_voltage_max = 4400000 read from
    chi-eclipse-01 on 2026-08-28. Pinned so a later edit cannot quietly raise
    the ceiling above what the hardware reports it will accept.
    """
    text = RTC_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"MEASURED_CHARGING_VOLTAGE_MAX_UV=(\d+)", text)
    assert match, "enable-rtc-charging.sh must declare MEASURED_CHARGING_VOLTAGE_MAX_UV"
    assert match.group(1) == MEASURED_CHARGING_VOLTAGE_MAX_UV, (
        f"ceiling drifted from the measured register: {match.group(1)} "
        f"(expected {MEASURED_CHARGING_VOLTAGE_MAX_UV})"
    )


def test_enableRtcCharging_neverWritesCmdlineTxt():
    """The script must not touch cmdline.txt.

    Same surface choice US-524 pinned for set-gpu-cma.sh: a bad config.txt
    param is recoverable (the firmware skips it -- SSH still alive), while a
    corrupted cmdline.txt can break root= on a headless Pi. rtc_bbat_vchg is a
    dtparam and belongs in config.txt; pin the choice so a later edit cannot
    quietly move to the unrecoverable surface. Comments are stripped first so
    the rationale text does not satisfy the guard.
    """
    lines = _codeLines(RTC_SCRIPT.read_text(encoding="utf-8"))
    offenders = [ln for ln in lines if "cmdline.txt" in ln]
    assert not offenders, (
        f"enable-rtc-charging.sh must not reference cmdline.txt: {offenders}"
    )
