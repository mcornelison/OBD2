"""Tests for the run-not-trust deploy pre-flight test gate (US-469 / SS-T7 / F-118).

Two layers, mirroring the project's gate-test discipline:

* HERMETIC (fake runner) -- proves the control flow + the "run-not-trust" wiring:
  the gate ALWAYS invokes pytest with ``-m "not slow"``, HALTs on any non-zero
  exit, and fails safe (HALT) when pytest cannot be launched. No marker file and
  no "prior report" flag can short-circuit the run.
* REAL end-to-end (nested pytest against a throwaway tmp test) -- the
  validationCriterion realized: a deliberately failing test in the target suite
  makes the gate RUN pytest, get a non-zero exit, and HALT the deploy. It targets
  a tiny isolated tmp dir (NOT the project suite) so it stays fast (TD-059).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from offices.pm.scripts import deploy_preflight_gate as gate


class _RecordingRunner:
    """A fake pytest runner: records the argv/cwd it was called with, returns a code."""

    def __init__(self, returnCode: int = 0, raises: Exception | None = None):
        self.returnCode = returnCode
        self.raises = raises
        self.calls: list[tuple[list[str], object]] = []

    def __call__(self, argv, cwd):
        self.calls.append((list(argv), cwd))
        if self.raises is not None:
            raise self.raises
        return self.returnCode


class TestBuildPytestArgv:
    def test_buildPytestArgv_default_targetsNotSlowMarker(self):
        """
        Given: no explicit marker/targets
        When: the pytest argv is built
        Then: it invokes `python -m pytest -m "not slow"` (the SS-T7-bearing suite)
        """
        argv = gate.buildPytestArgv()

        # `python -m pytest` then the pytest marker pair `-m "not slow"`
        assert argv == [sys.executable, "-m", "pytest", "-m", gate.DEFAULT_MARKER_EXPR]
        assert gate.DEFAULT_MARKER_EXPR == "not slow"

    def test_buildPytestArgv_targetPaths_appended(self):
        """Explicit target paths are appended so the gate can point at a subset."""
        argv = gate.buildPytestArgv(targetPaths=("tests/pm",))

        assert argv[-1] == "tests/pm"


class TestRunPreflightGateHermetic:
    def test_runPreflightGate_pytestGreen_passesAndMayProceed(self):
        """
        Given: pytest exits 0 (suite green)
        When: the gate runs
        Then: outcome is PASS and the deploy may proceed
        """
        runner = _RecordingRunner(returnCode=0)

        result = gate.runPreflightGate(".", runner=runner)

        assert result.outcome is gate.GateOutcome.PASS
        assert result.deployMayProceed is True
        assert result.returnCode == 0

    def test_runPreflightGate_pytestRed_haltsAndBlocksDeploy(self):
        """
        Given: pytest exits non-zero (a red test -- e.g. SS-T7 drift)
        When: the gate runs
        Then: outcome is HALT and the deploy is blocked
        """
        runner = _RecordingRunner(returnCode=1)

        result = gate.runPreflightGate(".", runner=runner)

        assert result.outcome is gate.GateOutcome.HALT
        assert result.deployMayProceed is False
        assert result.returnCode == 1

    def test_runPreflightGate_alwaysInvokesPytest_runNotTrust(self):
        """The gate RUNS pytest -- it never reads a marker or trusts a prior report."""
        runner = _RecordingRunner(returnCode=0)

        gate.runPreflightGate(".", runner=runner)

        assert len(runner.calls) == 1, "gate must actually invoke the test runner"
        argv, _cwd = runner.calls[0]
        # run-not-trust: the invocation is a real pytest run of the not-slow suite
        assert argv[:3] == [sys.executable, "-m", "pytest"]
        assert argv[-2:] == ["-m", "not slow"]

    def test_runPreflightGate_runsInRepoRoot(self):
        """pytest is launched with cwd = the repo root so it discovers the whole suite."""
        runner = _RecordingRunner(returnCode=0)

        gate.runPreflightGate("/some/repo/root", runner=runner)

        _argv, cwd = runner.calls[0]
        # the gate hands the repo root through to the runner verbatim (as cwd)
        assert cwd == "/some/repo/root"

    def test_runPreflightGate_runnerRaises_failsSafeToHalt(self):
        """
        Given: pytest cannot even be launched (OSError)
        When: the gate runs
        Then: outcome is ERROR and the deploy is BLOCKED (fail safe -- uncertainty
              never authorizes a deploy)
        """
        runner = _RecordingRunner(raises=OSError("pytest not found"))

        result = gate.runPreflightGate(".", runner=runner)

        assert result.outcome is gate.GateOutcome.ERROR
        assert result.deployMayProceed is False

    def test_runPreflightGate_noSkipHatch(self):
        """There is no argument that lets a caller bypass the actual pytest run."""
        # The public signature accepts only repoRoot + tuning of WHAT to run, never
        # a "skip"/"trust prior report" flag. Guard against a regression that adds one.
        import inspect

        params = set(inspect.signature(gate.runPreflightGate).parameters)
        forbidden = {"skip", "trust", "assumeGreen", "marker_only", "dryRun", "dry_run"}
        assert not (params & forbidden), f"gate must not grow a trust/skip hatch: {params & forbidden}"


class TestMainCli:
    def test_main_green_returnsZero(self, monkeypatch, capsys):
        monkeypatch.setattr(gate, "_defaultRunner", lambda argv, cwd: 0)

        rc = gate.main(["--repo", "."])

        assert rc == 0
        assert "PASS" in capsys.readouterr().out

    def test_main_red_returnsHaltExitCode(self, monkeypatch, capsys):
        monkeypatch.setattr(gate, "_defaultRunner", lambda argv, cwd: 1)

        rc = gate.main(["--repo", "."])

        assert rc == gate.HALT_EXIT_CODE
        assert rc != 0
        assert "HALT" in capsys.readouterr().out


@pytest.mark.integration
class TestRealEndToEnd:
    """The validationCriterion realized against a REAL nested pytest run.

    Targets a throwaway tmp test dir (isolated from the project suite) so it is
    fast and hermetic -- but it is a genuine `python -m pytest` subprocess, so it
    proves the gate observes a real non-zero exit rather than a mocked one.
    """

    def _writeTest(self, tmp_path: Path, name: str, body: str) -> None:
        (tmp_path / name).write_text(body, encoding="utf-8")

    def test_realFailingTest_gateRunsPytestAndHalts(self, tmp_path):
        """A deliberately failing test in the target suite -> the gate HALTs."""
        self._writeTest(tmp_path, "test_ok.py", "def test_ok():\n    assert True\n")
        self._writeTest(tmp_path, "test_boom.py", "def test_boom():\n    assert False\n")

        result = gate.runPreflightGate(tmp_path, targetPaths=(str(tmp_path),))

        assert result.outcome is gate.GateOutcome.HALT
        assert result.deployMayProceed is False
        assert result.returnCode != 0

    def test_realAllGreen_gatePasses(self, tmp_path):
        """An all-green target suite -> the gate PASSES (proceed)."""
        self._writeTest(tmp_path, "test_ok.py", "def test_ok():\n    assert 1 + 1 == 2\n")

        result = gate.runPreflightGate(tmp_path, targetPaths=(str(tmp_path),))

        assert result.outcome is gate.GateOutcome.PASS
        assert result.deployMayProceed is True
        assert result.returnCode == 0
