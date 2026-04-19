################################################################################
# File Name: test_replay_pi_fixture_sh.py
# Purpose/Description: Smoke tests for scripts/replay_pi_fixture.sh (US-191).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-191 (Sprint 13)
# ================================================================================
################################################################################

"""
Tests for :mod:`scripts.replay_pi_fixture.sh`.

We exercise the bash driver via ``subprocess.run(['bash', ...])`` in
``--dry-run`` mode so no Pi / server is needed.  The assertions cover step
ordering (all eight headers appear in order), flag handling (help,
unknown-flag, missing-fixture), and the short-circuit behavior of
``--keep-service-stopped``.

This mirrors the US-166 precedent of writing Python tests that invoke
shell scripts via subprocess -- lets the full ``pytest tests/`` run catch
driver regressions without anyone having to plug in a Pi.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Environment gate.  Bash is always available in git-bash + on Linux / Pi;
# this gate lets the tests skip cleanly on a CI machine that somehow lacks
# bash altogether rather than erroring the collection.
# ---------------------------------------------------------------------------
_BASH_PATH = shutil.which("bash")
_skipWithoutBash = pytest.mark.skipif(
    _BASH_PATH is None,
    reason="bash not on PATH; replay_pi_fixture.sh tests need a POSIX shell",
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DRIVER = _PROJECT_ROOT / "scripts" / "replay_pi_fixture.sh"


# ==============================================================================
# Helpers
# ==============================================================================


def _runDriver(args: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the bash driver with ``args`` and return the completed process.

    Runs from the repo root by default so ``data/regression/pi-inputs/`` is
    resolvable by the script's relative path math.
    """
    # Windows Store Python subprocess cold-start can exceed 30s under load
    # (see agent.md 'Windows Store Python subprocess cold-start' pattern).
    # Bash itself is cheap -- 60s is plenty unless the whole suite is churning.
    result = subprocess.run(  # noqa: S603 -- curated args to our own script
        [str(_BASH_PATH), str(_DRIVER), *args],
        cwd=str(cwd or _PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result


# ==============================================================================
# --help
# ==============================================================================


@_skipWithoutBash
class TestHelp:
    """``--help`` and ``-h`` flag behavior."""

    def test_help_exitCodeZero(self) -> None:
        """Exit code 0 and help text on stdout (not stderr)."""
        result = _runDriver(["--help"])
        assert result.returncode == 0
        assert "Usage: bash scripts/replay_pi_fixture.sh" in result.stdout
        # The help text lists the three canonical fixture names so an operator
        # knows what's available without hunting in docs.
        for name in ("cold_start", "local_loop", "errand_day"):
            assert name in result.stdout

    def test_dashH_sameAsLongForm(self) -> None:
        """``-h`` short form produces the same output as ``--help``."""
        result = _runDriver(["-h"])
        assert result.returncode == 0
        assert "Usage: bash scripts/replay_pi_fixture.sh" in result.stdout


# ==============================================================================
# --dry-run + step ordering
# ==============================================================================


@_skipWithoutBash
class TestDryRunFlow:
    """End-to-end ``--dry-run`` flow against a real fixture."""

    def test_dryRun_allEightStepsAppearInOrder(self) -> None:
        """Steps 1..8 must be printed in numerical order."""
        result = _runDriver(["--dry-run", "cold_start"])
        assert result.returncode == 0, f"driver failed: {result.stderr}"

        expectedHeaders = [
            "Step 1 / 8",
            "Step 2 / 8",
            "Step 3 / 8",
            "Step 4 / 8",
            "Step 5 / 8",
            "Step 6 / 8",
            "Step 7 / 8",
            "Step 8 / 8",
        ]
        # Walk the output once, asserting each header appears after the
        # previous one.  This catches both a missing step and a reorder.
        cursor = 0
        for header in expectedHeaders:
            idx = result.stdout.find(header, cursor)
            assert idx >= 0, f"missing header {header!r} after offset {cursor}"
            cursor = idx + len(header)

    def test_dryRun_doesNotActuallySsh(self) -> None:
        """Dry-run emits the ``[dry-run] ssh ...`` marker, never real calls."""
        result = _runDriver(["--dry-run", "cold_start"])
        assert "[dry-run] ssh " in result.stdout
        # No real SSH error should leak through -- if the driver tried to
        # SSH for real, we'd see a connection-refused or DNS error on a CI
        # machine without network access to 10.27.27.x.
        assert "Permission denied" not in result.stderr
        assert "Could not resolve hostname" not in result.stderr

    def test_dryRun_summaryMarkerPresent(self) -> None:
        """The dry-run summary line must be emitted."""
        result = _runDriver(["--dry-run", "cold_start"])
        assert "Dry run complete -- no assertions evaluated." in result.stdout

    def test_dryRun_positionalAndFlagForm_bothWork(self) -> None:
        """Positional ``cold_start`` and ``--fixture cold_start`` are equivalent."""
        positional = _runDriver(["--dry-run", "cold_start"])
        flag = _runDriver(["--dry-run", "--fixture", "cold_start"])
        assert positional.returncode == 0
        assert flag.returncode == 0
        # Both forms should list the same fixture name in the banner.
        assert "fixture=cold_start" in positional.stdout
        assert "fixture=cold_start" in flag.stdout


# ==============================================================================
# --keep-service-stopped
# ==============================================================================


@_skipWithoutBash
class TestKeepServiceStopped:
    """``--keep-service-stopped`` short-circuits the step-8 restart."""

    def test_restartMessage_whenFlagAbsent(self) -> None:
        """Default behavior restarts eclipse-obd on the Pi in step 8."""
        result = _runDriver(["--dry-run", "cold_start"])
        assert result.returncode == 0
        assert "Restarting eclipse-obd.service on Pi" in result.stdout
        assert "left stopped" not in result.stdout

    def test_flagPresent_suppressesRestart(self) -> None:
        """With the flag, step 8 prints the 'left stopped' marker instead."""
        result = _runDriver([
            "--dry-run", "--keep-service-stopped", "cold_start",
        ])
        assert result.returncode == 0
        assert "left stopped" in result.stdout
        assert "Restarting eclipse-obd.service" not in result.stdout


# ==============================================================================
# Error handling
# ==============================================================================


@_skipWithoutBash
class TestErrorPaths:
    """Argument-parse failures exit 2 with a clear message."""

    def test_noFixtureName_exitCodeTwo(self) -> None:
        """Missing fixture -> exit 2."""
        result = _runDriver(["--dry-run"])
        assert result.returncode == 2
        assert "Fixture name is required" in result.stderr

    def test_unknownFlag_exitCodeTwo(self) -> None:
        """Unknown flag -> exit 2, usage help on stderr."""
        result = _runDriver(["--no-such-flag", "cold_start"])
        assert result.returncode == 2
        assert "Unknown flag" in result.stderr

    def test_fixtureSpecifiedTwice_exitCodeTwo(self) -> None:
        """Passing two positional fixtures -> exit 2."""
        result = _runDriver(["cold_start", "local_loop"])
        assert result.returncode == 2
        assert "specified twice" in result.stderr

    def test_nonexistentFixture_withoutDryRun_exitCodeTwo(self) -> None:
        """Non-dry-run missing-fixture path surfaces a clear path+hint."""
        result = _runDriver(["no_such_fixture"])
        assert result.returncode == 2
        assert "Fixture not found" in result.stderr
        # The hint includes how to regenerate; an operator should see the
        # exact command to run.
        assert "seed_pi_fixture.py" in result.stderr


# ==============================================================================
# Entry-point sanity (keeps collection fast if somehow the driver vanishes)
# ==============================================================================


@_skipWithoutBash
def test_driverFileExistsAndIsExecutableText() -> None:
    """Sanity check: the driver file exists and starts with the bash shebang."""
    assert _DRIVER.exists(), f"driver not found: {_DRIVER}"
    head = _DRIVER.read_text(encoding="utf-8").splitlines()[0]
    assert head.startswith("#!/usr/bin/env bash")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
