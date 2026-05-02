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
#                      Coverage: idempotency (no-op when setting absent or
#                      already =0), rewrite-when-different (=1 or =2 -> 0),
#                      tool-missing fail (exit 1), apply-failure fail
#                      (exit 2), and a two-run idempotency drill.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex          | Initial implementation (Sprint 21 US-253)
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
    rpi-eeprom-config:
      1. setting absent              -> no-op (defaults to 0)
      2. setting =0                  -> no-op (already correct)
      3. setting =1                  -> rewrite via --apply
      4. setting =2                  -> rewrite via --apply
      5. tool missing                -> exit 1
      6. tool --apply fails          -> exit 2
      7. two-run idempotency drill   -> first applies, second is no-op

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
        timeout=10,
        env={"RPI_EEPROM_CONFIG": "/nonexistent/rpi-eeprom-config", "PATH": ""},
    )
    assert result.returncode == 1, (
        f"expected exit 1 (tool missing); got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()
