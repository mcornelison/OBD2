################################################################################
# File Name: test_calibrate_max17048.py
# Purpose/Description: Outcome-based tests for scripts/calibrate_max17048.py
#                      (US-431 / F-048).  The bench calibration script samples the
#                      MAX17048 register SoC% from a cold power-up and measures how
#                      long the ModelGauge takes to settle -- the empirical value
#                      that feeds the US-234/US-427 cold-start guard threshold with
#                      real data instead of the guessed 180s constant.  Tests pin
#                      the pure settling analysis, the injected-clock sampler, the
#                      CSV writer, argparse defaults, and a hardware-free run().
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex (US-431) | Initial -- settling analysis + sampler + CSV +
#                                argparse + hardware-free run() coverage.
# ================================================================================
################################################################################

"""Tests for :mod:`scripts.calibrate_max17048`.

The MAX17048 fuel gauge mis-reads SoC% by 30-40 points for the first few
minutes after a cold power-up (F-048).  US-431 builds the bench tool that
*measures* how long that settling takes so the ~180s cold-start guard
(:data:`scripts.record_drain_test.COLD_START_CALIBRATION_WINDOW_SECONDS`)
can be set from data rather than guessed.  These tests exercise the
hardware-independent core (analysis, injected-clock sampling, CSV output)
so the whole script is verifiable off-Pi.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pi.hardware.ups_monitor import UpsMonitorError
from scripts import calibrate_max17048

# Repo root: tests/scripts/test_calibrate_max17048.py -> parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]


# =============================================================================
# Helpers / doubles
# =============================================================================


class _FakeUps:
    """Minimal UpsMonitor double returning fixed telemetry or raising."""

    def __init__(
        self,
        socPct: int = 80,
        vcellV: float = 4.10,
        cratePctPerHr: float | None = None,
        raiseError: bool = False,
    ) -> None:
        self._socPct = socPct
        self._vcellV = vcellV
        self._cratePctPerHr = cratePctPerHr
        self._raiseError = raiseError
        self.socCalls = 0

    def getBatteryPercentage(self) -> int:
        self.socCalls += 1
        if self._raiseError:
            raise UpsMonitorError("UPS not available (bench double)")
        return self._socPct

    def getBatteryVoltage(self) -> float:
        if self._raiseError:
            raise UpsMonitorError("UPS not available (bench double)")
        return self._vcellV

    def getChargeRatePercentPerHour(self) -> float | None:
        return self._cratePctPerHr


def _sample(elapsed: float, soc: int | None) -> calibrate_max17048.CalibrationSample:
    """Build a CalibrationSample with only the fields the analysis reads."""
    return calibrate_max17048.CalibrationSample(
        elapsedSeconds=elapsed, vcellV=4.10, socPct=soc, cratePctPerHr=None,
    )


def _runEntryPointCleanEnv(*args: str) -> subprocess.CompletedProcess[str]:
    """Run scripts/calibrate_max17048.py as an operator does (no PYTHONPATH)."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts/calibrate_max17048.py"), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


# =============================================================================
# analyzeSettling -- the core hardware-free settling detector
# =============================================================================


class TestAnalyzeSettling:
    """The pure settling analysis is the value that feeds the guard threshold."""

    def test_settlesMidRun_reportsSettlePointAndRecommendation(self) -> None:
        """
        Given: SoC% that climbs out of a cold-start error then holds at 80%.
        When:  analyzeSettling runs with a +/-2% tolerance.
        Then:  it reports the moment the reading enters and stays in-band, the
               peak deviation, and a margin-padded recommended window.
        """
        samples = [
            _sample(0.0, 60), _sample(5.0, 65), _sample(10.0, 72),
            _sample(15.0, 79), _sample(20.0, 80), _sample(25.0, 81),
            _sample(30.0, 80), _sample(35.0, 80), _sample(40.0, 80),
            _sample(45.0, 80), _sample(50.0, 80), _sample(55.0, 80),
            _sample(60.0, 80),
        ]
        result = calibrate_max17048.analyzeSettling(
            samples, tolerancePct=2.0, settleWindowSeconds=30.0,
        )
        assert result.settled is True
        # 79 is the first reading inside [78, 82] that then holds to the end.
        assert result.settledAtSeconds == 15.0
        assert result.finalSocPct == 80
        assert result.maxDeviationPct == 20.0
        # ceil(15 * 1.5 / 10) * 10 == 30.
        assert result.recommendedWindowSeconds == 30.0

    def test_neverSettles_reportsUnsettled(self) -> None:
        """
        Given: SoC% oscillating outside the tolerance band the whole run.
        When:  analyzeSettling runs.
        Then:  it honestly reports no settle point and no recommendation.
        """
        samples = [
            _sample(0.0, 50), _sample(5.0, 80), _sample(10.0, 50),
            _sample(15.0, 80), _sample(20.0, 50), _sample(25.0, 80),
        ]
        result = calibrate_max17048.analyzeSettling(
            samples, tolerancePct=2.0, settleWindowSeconds=30.0,
        )
        assert result.settled is False
        assert result.settledAtSeconds is None
        assert result.recommendedWindowSeconds is None

    def test_settlesTooCloseToEnd_notConfident(self) -> None:
        """
        Given: the reading only enters the band in the final 10s.
        When:  analyzeSettling requires a 30s sustained in-band tail.
        Then:  it reports unsettled -- too little dwell to trust.
        """
        samples = [
            _sample(0.0, 50), _sample(5.0, 55), _sample(10.0, 60),
            _sample(15.0, 65), _sample(20.0, 70), _sample(25.0, 78),
            _sample(30.0, 80),
        ]
        result = calibrate_max17048.analyzeSettling(
            samples, tolerancePct=2.0, settleWindowSeconds=30.0,
        )
        assert result.settled is False
        assert result.settledAtSeconds is None

    def test_insufficientData_reportsUnsettled(self) -> None:
        """
        Given: no usable register reads (all None -- gauge absent).
        When:  analyzeSettling runs.
        Then:  it reports unsettled with a zero valid-sample count, no crash.
        """
        samples = [_sample(0.0, None), _sample(5.0, None)]
        result = calibrate_max17048.analyzeSettling(
            samples, tolerancePct=2.0, settleWindowSeconds=30.0,
        )
        assert result.settled is False
        assert result.finalSocPct is None
        assert result.sampleCount == 0

    def test_ignoresNoneSamplesInWindow(self) -> None:
        """
        Given: a dropped (None) read amid otherwise-settled samples.
        When:  analyzeSettling runs.
        Then:  the None is skipped, not treated as an out-of-band excursion.
        """
        samples = [
            _sample(0.0, 60), _sample(5.0, 80), _sample(10.0, None),
            _sample(15.0, 80), _sample(20.0, 80), _sample(25.0, 81),
            _sample(30.0, 80), _sample(35.0, 80), _sample(40.0, 80),
        ]
        result = calibrate_max17048.analyzeSettling(
            samples, tolerancePct=2.0, settleWindowSeconds=30.0,
        )
        assert result.settled is True
        assert result.settledAtSeconds == 5.0
        assert result.sampleCount == 8


# =============================================================================
# recommendWindowSeconds -- margin + rounding
# =============================================================================


class TestRecommendWindowSeconds:
    """The recommendation pads the measured settle time and rounds up."""

    def test_appliesMarginAndRoundsUp(self) -> None:
        """15s settle -> ceil(15 * 1.5 / 10) * 10 == 30s."""
        assert calibrate_max17048.recommendWindowSeconds(15.0) == 30.0

    def test_roundsToNextBucket(self) -> None:
        """60s settle -> ceil(90 / 10) * 10 == 90s."""
        assert calibrate_max17048.recommendWindowSeconds(60.0) == 90.0

    def test_immediateSettle_isZero(self) -> None:
        """A gauge that is trustworthy at t=0 needs no guard window."""
        assert calibrate_max17048.recommendWindowSeconds(0.0) == 0.0


# =============================================================================
# collectSamples -- injected clock + sleep, hardware-free
# =============================================================================


class TestCollectSamples:
    """Sampling loop is deterministic under an injected clock + sleep."""

    def test_collectsExpectedCadenceAndCount(self) -> None:
        """
        Given: a 20s run at a 5s interval with a scripted clock.
        When:  collectSamples runs against a fake gauge.
        Then:  5 samples land at 0/5/10/15/20s and sleep fires 4 times.
        """
        fake = _FakeUps(socPct=77, vcellV=4.05)
        clockValues = iter([0.0, 0.0, 5.0, 10.0, 15.0, 20.0])
        sleeps: list[float] = []
        samples = calibrate_max17048.collectSamples(
            fake,
            durationSeconds=20.0,
            intervalSeconds=5.0,
            clock=lambda: next(clockValues),
            sleep=sleeps.append,
        )
        assert len(samples) == 5
        assert [s.elapsedSeconds for s in samples] == [0.0, 5.0, 10.0, 15.0, 20.0]
        assert all(s.socPct == 77 for s in samples)
        assert len(sleeps) == 4

    def test_readErrorRecordsNoneNotCrash(self) -> None:
        """A gauge read failure records None for that sample, never propagates."""
        fake = _FakeUps(raiseError=True)
        clockValues = iter([0.0, 0.0, 5.0])
        samples = calibrate_max17048.collectSamples(
            fake,
            durationSeconds=5.0,
            intervalSeconds=5.0,
            clock=lambda: next(clockValues),
            sleep=lambda _s: None,
        )
        assert len(samples) == 2
        assert all(s.socPct is None for s in samples)
        assert all(s.vcellV is None for s in samples)


# =============================================================================
# writeCsv -- schema-free calibration log (no battery_health_log change)
# =============================================================================


class TestWriteCsv:
    """CSV is the calibration sink; None reads render empty; error vs reference."""

    def test_writesHeaderAndRows_withReferenceError(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: two samples and a known reference SoC of 80%.
        When:  writeCsv runs.
        Then:  the header + a per-sample soc_error_pct (soc - reference) land,
               and a dropped read leaves the numeric cells blank.
        """
        out = tmp_path / "cal.csv"
        samples = [
            calibrate_max17048.CalibrationSample(
                elapsedSeconds=0.0, vcellV=4.10, socPct=60, cratePctPerHr=None,
            ),
            calibrate_max17048.CalibrationSample(
                elapsedSeconds=5.0, vcellV=None, socPct=None, cratePctPerHr=None,
            ),
        ]
        calibrate_max17048.writeCsv(samples, str(out), referenceSocPct=80.0)

        with open(out, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == [
            "elapsed_seconds", "vcell_v", "soc_pct",
            "crate_pct_per_hr", "reference_soc_pct", "soc_error_pct",
        ]
        # First data row: soc 60 vs reference 80 -> error -20.
        assert rows[1][2] == "60"
        assert rows[1][5] == "-20.0"
        # Dropped read: numeric cells blank, no crash.
        assert rows[2][2] == ""
        assert rows[2][5] == ""


# =============================================================================
# parseArguments -- documented, grounded defaults
# =============================================================================


class TestParseArguments:
    """Defaults are grounded (see script docstring) and overridable."""

    def test_defaults(self) -> None:
        """Bare invocation carries the grounded default cadence + window."""
        args = calibrate_max17048.parseArguments([])
        assert args.duration == calibrate_max17048.DEFAULT_DURATION_SECONDS
        assert args.interval == calibrate_max17048.DEFAULT_SAMPLE_INTERVAL_SECONDS
        assert args.settle_tolerance == calibrate_max17048.DEFAULT_SETTLE_TOLERANCE_PCT
        assert args.settle_window == calibrate_max17048.DEFAULT_SETTLE_WINDOW_SECONDS

    def test_overrides(self) -> None:
        """Operator flags override every default."""
        args = calibrate_max17048.parseArguments(
            ["--duration", "120", "--interval", "2",
             "--reference-soc", "100", "--output", "x.csv"],
        )
        assert args.duration == 120.0
        assert args.interval == 2.0
        assert args.reference_soc == 100.0
        assert args.output == "x.csv"


# =============================================================================
# run() + main() -- hardware-free integration + clean-import smoke
# =============================================================================


class TestRun:
    """run() drives the full flow against an injected gauge, no hardware."""

    def test_run_writesCsvAndPrintsRecommendation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        Given: a fake gauge already settled at 80% and an injected clock.
        When:  run() executes end to end (no real sleeping).
        Then:  it exits 0, writes the CSV, and prints a recommended window.
        """
        out = tmp_path / "run.csv"
        args = calibrate_max17048.parseArguments(
            ["--duration", "60", "--interval", "5", "--output", str(out)],
        )
        fake = _FakeUps(socPct=80, vcellV=4.10)
        # 1 start read + 13 sample reads (0..60 @ 5s) of the clock.
        clockValues = iter([float(i) for i in range(20)])
        exitCode = calibrate_max17048.run(
            args, monitor=fake, clock=lambda: next(clockValues), sleep=lambda _s: None,
        )
        assert exitCode == 0
        assert out.exists()
        out_text = capsys.readouterr().out
        assert "recommended" in out_text.lower()

    def test_bareOperatorInvocation_importsWithoutModuleError(self) -> None:
        """python scripts/calibrate_max17048.py --help imports cleanly (US-397)."""
        result = _runEntryPointCleanEnv("--help")
        assert "ModuleNotFoundError" not in result.stderr, result.stderr
        assert "No module named 'pi'" not in result.stderr, result.stderr
        assert result.returncode == 0, (
            f"--help should exit 0; rc={result.returncode}\nstderr={result.stderr}"
        )

    def test_main_dryRun_printsPlanNoHardware(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--dry-run prints the run plan and exits 0 without touching the gauge."""
        exitCode = calibrate_max17048.main(
            ["--dry-run", "--duration", "60", "--interval", "5"],
        )
        assert exitCode == 0
        out = capsys.readouterr().out
        assert "DRY RUN" in out
