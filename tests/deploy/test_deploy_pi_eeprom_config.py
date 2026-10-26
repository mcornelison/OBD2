################################################################################
# File Name: test_deploy_pi_eeprom_config.py
# Purpose/Description: pytest wrapper for the US-253 EEPROM POWER_OFF_ON_HALT
#                      enforcement script. Drives tests/deploy/test_eeprom_
#                      power_off_on_halt.sh via subprocess so the bash
#                      scenarios (PATH-mocked rpi-eeprom-config) run in the
#                      fast suite. Mirrors the test_journald_persistent_
#                      install.py + test_deploy_pi.py pattern: bash script
#                      is the source of truth for assertions; this Python
#                      file is the pytest entry point.
#
#                      Coverage: rewrite-to-=1 when setting absent / =0 / =2;
#                      no-op when already =1; tool-missing fail (exit 1);
#                      apply-failure fail (exit 2); two-run idempotency drill.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex          | Initial implementation (Sprint 21 US-253)
# 2026-05-19    | Plan SS-T8   | Inverted target: =1 (Pi 5 + X1209-HAT) per the
#                                CIO-locked decision 2026-05-18 + Check-B
#                                empirical confirmation. The prior force-=0 was
#                                a defect (F-6) that reverted the correct
#                                setting every deploy. See
#                                offices/architect/findings/2026-05-18-
#                                architecture-md-corrections-definitive.md §11.
# 2026-10-25    | Rex          | US-926-a: key-table guards (exact four pairs, no
#                                never-key, source comments, no update -a) and
#                                the deploy step's dry-run/header key labels.
# ================================================================================
################################################################################

"""pytest wrapper around tests/deploy/test_eeprom_power_off_on_halt.sh.

The .sh script is the canonical assertion catalog (PATH-mocks rpi-eeprom-config
across all real-world states: setting absent, =0, =1, =2, tool missing, apply
fails, two-run idempotency). This wrapper exists so `pytest tests/` exercises
the deploy enforcement script automatically and a regression in either the
production script (deploy/enforce-eeprom-power-off-on-halt.sh) or the test
harness shows up in the same fast suite.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = REPO_ROOT / "tests" / "deploy" / "test_eeprom_power_off_on_halt.sh"
ENFORCE_SCRIPT = REPO_ROOT / "deploy" / "enforce-eeprom-power-off-on-halt.sh"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_eepromPowerOffOnHalt_allScenariosPass():
    """The bash test (test_eeprom_power_off_on_halt.sh) must exit 0.

    The bash script runs 7 scenarios end-to-end with PATH-mocked
    rpi-eeprom-config (SS-T8: target value is =1, not =0):
      1. setting absent              -> rewrite to =1 (default 0 is WRONG on HAT)
      2. setting =0                  -> rewrite to =1 (the F-6 defect class)
      3. setting =1                  -> no-op (already correct on HAT)
      4. setting =2                  -> rewrite to =1
      5. tool missing                -> exit 1
      6. tool --apply fails          -> exit 2
      7. two-run idempotency drill   -> first applies =1, second is no-op

    Failure inside any scenario propagates as a non-zero exit from the .sh
    script, which this wrapper assert-fails on. stdout is forwarded to
    pytest captured output so individual scenario PASS/FAIL lines are
    visible from `pytest -v`.
    """
    assert TEST_SCRIPT.is_file(), f"Missing test script at {TEST_SCRIPT}"
    assert ENFORCE_SCRIPT.is_file(), f"Missing script under test at {ENFORCE_SCRIPT}"

    result = subprocess.run(
        ["bash", str(TEST_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        # The .sh test forks ~14 sub-bash invocations across 7 scenarios.
        # Local-disk runs finish in ~3s; a NAS-mounted repo (chi-nas-01 SMB)
        # makes each fork noticeably slower. 90s matches the established
        # test_deploy_pi.py headroom.
        timeout=90,
    )

    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)

    assert result.returncode == 0, (
        f"EEPROM POWER_OFF_ON_HALT enforcement test failed (exit={result.returncode})"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_enforceScript_syntaxValid():
    """`bash -n deploy/enforce-eeprom-power-off-on-halt.sh` must succeed.

    Catches shell-syntax regressions even when the runtime mock is unavailable.
    """
    result = subprocess.run(
        ["bash", "-n", str(ENFORCE_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0, (
        f"bash -n syntax check failed: {result.stderr}"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_enforceScript_toolMissingExitCode():
    """Direct invocation with $RPI_EEPROM_CONFIG pointing at /nonexistent.

    Exit code is 1 (tool-missing class) and stderr names the missing binary.
    Independent assertion against the integration scenarios in the .sh file
    so a regression in this specific failure path doesn't hide behind the
    aggregated bash-test pass/fail.
    """
    result = subprocess.run(
        ["bash", str(ENFORCE_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        env={"RPI_EEPROM_CONFIG": "/nonexistent/rpi-eeprom-config", "PATH": ""},
    )
    assert result.returncode == 1, (
        f"expected exit 1 (tool missing); got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()


# --------------------------------------------------------------------------
# US-926-a: the boot-speed key table -- static VC and the deploy step label
# --------------------------------------------------------------------------

DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
STEP_NAME = "step_enforce_eeprom_power_off_on_halt"
TABLE_START = "# >>> EEPROM_KEY_TABLE"
TABLE_END = "# <<< EEPROM_KEY_TABLE"
REQUIRED_KEYS = {
    "POWER_OFF_ON_HALT": "1",
    "NET_INSTALL_AT_POWER_ON": "0",
    "NET_INSTALL_ENABLED": "0",
    "BOOT_UART": "0",
}
NEVER_KEYS = ("PSU_MAX_CURRENT", "max_framebuffers", "BOOT_ORDER")


def _keyTable() -> str:
    """Return the text between the key-table markers, comments included."""
    text = ENFORCE_SCRIPT.read_text(encoding="utf-8")
    assert text.count(TABLE_START) == 1 and text.count(TABLE_END) == 1, (
        "the enforcer must hold exactly ONE marked key table"
    )
    return text[text.index(TABLE_START) : text.index(TABLE_END)]


def _codeLines(text: str) -> list[str]:
    """Return non-blank, non-comment lines, stripped."""
    return [
        ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]


def test_keyTable_holdsExactlyTheFourRequiredPairs():
    """
    Given: the enforcer's one key table
    When: its quoted KEY=VALUE entries are read
    Then: they are exactly the four US-926-a pairs, each once
    """
    entries = re.findall(r'"([A-Za-z_]+)=([^"]*)"', _keyTable())
    assert dict(entries) == REQUIRED_KEYS
    assert len(entries) == len(REQUIRED_KEYS), f"a key is listed twice: {entries}"


def test_keyTable_namesNoNeverKey():
    """
    Given: the key table, comments included (the grep VC)
    When: it is searched for PSU_MAX_CURRENT, max_framebuffers and BOOT_ORDER
    Then: none of the three appears
    """
    table = _keyTable()
    found = [key for key in NEVER_KEYS if re.search(key, table)]
    assert not found, f"never-keys in the EEPROM key table: {found}"


def test_keyTable_everyEntryCarriesASourceComment():
    """
    Given: the key table
    When: each entry line is checked against the line above it
    Then: every KEY=VALUE entry is preceded by a comment naming its source
    """
    lines = [ln.strip() for ln in _keyTable().splitlines()]
    for i, line in enumerate(lines):
        if re.match(r'"[A-Z_]+=', line):
            assert lines[i - 1].startswith("#"), f"no source comment above {line}"


def test_enforcer_neverRunsEepromUpdateApply():
    """
    Given: the enforcer's executable lines
    When: they are searched for an `rpi-eeprom-update -a`
    Then: none exists -- --apply already installs the image; -a is never ours
    """
    offenders = [
        ln
        for ln in _codeLines(ENFORCE_SCRIPT.read_text(encoding="utf-8"))
        if re.search(r"(rpi-eeprom-update|UPDATE_TOOL\"?)\s+.*-a\b", ln)
    ]
    assert not offenders, f"the enforcer must never run rpi-eeprom-update -a: {offenders}"


def _stepBody() -> str:
    """Return deploy-pi.sh's step function text, header comment included."""
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = text.index(f"{STEP_NAME}()")
    end = text.index("\n}\n", start)
    return text[start : end + 3]


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployStep_dryRunNamesEveryEnforcedKey():
    """
    Given: the real step function from deploy-pi.sh, run with DRY_RUN=true
    When: its output is read
    Then: every enforced KEY=VALUE is named, the stale =0 label is gone, and
          nothing reaches the Pi
    """
    script = (
        'remote() { echo "REMOTE-CALLED"; }\n'
        "DRY_RUN=true\n"
        "PI_PATH=/home/pi/obd2\n" + _stepBody() + f"{STEP_NAME}\n"
    )
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert result.returncode == 0, result.stderr
    for key, value in REQUIRED_KEYS.items():
        assert f"{key}={value}" in result.stdout, f"dry-run never names {key}={value}"
    assert "POWER_OFF_ON_HALT=0" not in result.stdout
    assert "REMOTE-CALLED" not in result.stdout


def test_deployStep_headerCommentNamesEveryEnforcedKey():
    """
    Given: the step's header comment in deploy-pi.sh
    When: it is read
    Then: it names every table key and no longer claims POWER_OFF_ON_HALT=0
    """
    comments = "\n".join(
        ln for ln in _stepBody().splitlines() if ln.strip().startswith("#")
    )
    for key, value in REQUIRED_KEYS.items():
        assert f"{key}={value}" in comments, f"step header never names {key}={value}"
    assert "POWER_OFF_ON_HALT=0" not in _stepBody()
