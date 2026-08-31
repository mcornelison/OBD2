################################################################################
# File Name: test_panel_liveness.py
# Purpose/Description: US-654 (F-139) acceptance gate for the display-liveness
#                      probe.  The panel was frozen for 7h27m and NOTHING
#                      reported it: the kiosk watchdog is MARKER-ONLY and is
#                      structurally blind to the freeze class that emits no
#                      markers, so it logged "healthy" throughout.
#
#                      THE SIGNAL IS A PAIR, AND NEITHER HALF ALONE IS IT:
#                      chromium's CUMULATIVE CPU going flat WHILE the state
#                      files keep advancing.  Every negative case in this file
#                      exists because one half of that pair, read on its own,
#                      would have produced a confident wrong answer.
#
#                      The load-bearing negatives, each its own test:
#                        - a legitimately IDLE panel (parked, nothing flowing)
#                          is NOT dead -- if the state files are static there is
#                          nothing to render and the panel is not at fault;
#                        - producers that died mid-window, and producers that
#                          only STARTED mid-window, are both "idle" -- the
#                          window has to be live at BOTH ends or the CPU average
#                          is taken over time the panel was right to be quiet;
#                        - an observation SHORTER than the window yields NO
#                          verdict.  This is the sprint's own correction: the
#                          original 8-second reading could not discriminate,
#                          because a healthy ~3% page also reads flat at that
#                          span.  A short sample must be withheld, never
#                          rounded to "healthy";
#                        - an NTP clock STEP must not manufacture a dead panel.
#                          This Pi's RTC starts at 1970 and is stepped later
#                          (A-23), so a wall-clock elapsed of ~56 years against
#                          a few seconds of CPU is a guaranteed false positive.
#                          Same root as US-644-b, fourth surface;
#                        - chromium being REPLACED resets its CPU counter, so a
#                          differenced reading across a restart is meaningless.
#
#                      SCOPE FENCES, pinned mechanically rather than trusted:
#                        - this module RESTARTS NOTHING (the story: restarting
#                          is itself under suspicion as a cause of class B);
#                        - it is NOT folded into kiosk_watchdog.py (Atlas,
#                          explicit -- a marker-only detector must not be
#                          stretched to claim a coverage it cannot have).
#
#                      Offline-safe: no /proc, no systemctl, no clock -- every
#                      external read is a tmp_path fixture or an injected fake.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Rex          | Initial implementation (Sprint 78 US-654)
# ================================================================================
################################################################################

"""Decision-table + seam tests for pi.display.panel_liveness (US-654)."""

from __future__ import annotations

import ast
import logging
import os
import subprocess
from pathlib import Path

import pytest

from pi.display import panel_liveness as pl

# ----------------------------------------------------------------------------
# The MEASURED bands this detector stands on.  Both are quoted from the sprint
# record so a future edit that moves a constant has to argue with a measurement
# rather than with a preference.
#
# FROZEN (US-654 acceptance + the sprint bigDefinitionOfDone, 2026-08-31):
#   14s CPU over 26,817s            = 0.052%
#   35s CPU over 7.4h (26,640s)     = 0.131%
#   1s  CPU over 600s               = 0.167%   <- the highest measured frozen
# HEALTHY (bigDefinitionOfDone, "a healthy 3-7%"):
#   3% .. 7%
# ----------------------------------------------------------------------------
MEASURED_FROZEN_FRACTIONS = (14.0 / 26_817.0, 35.0 / 26_640.0, 1.0 / 600.0)
MEASURED_HEALTHY_FRACTIONS = (0.03, 0.07)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _policy(**overrides: object) -> pl.LivenessPolicy:
    """A policy at shipped defaults unless a test deliberately moves one."""
    fields: dict[str, object] = {
        "observationSeconds": pl.DEFAULT_OBSERVATION_SECONDS,
        "liveCpuFraction": pl.DEFAULT_LIVE_CPU_FRACTION,
        "stateFreshnessSeconds": pl.DEFAULT_STATE_FRESHNESS_SECONDS,
    }
    fields.update(overrides)
    return pl.LivenessPolicy(**fields)  # type: ignore[arg-type]


def _sample(
    *,
    monotonic: float,
    cpuSeconds: float,
    epoch: float = 1_756_000_000.0,
    pid: int = 4242,
    startTicks: int = 999,
    newestStateMtime: float | None = 1_756_000_000.0,
    statesFresh: bool = True,
) -> pl.PanelSample:
    """One observation, with every field defaulted to the HEALTHY-shaped case."""
    return pl.PanelSample(
        epoch=epoch,
        monotonic=monotonic,
        pid=pid,
        startTicks=startTicks,
        cpuSeconds=cpuSeconds,
        newestStateMtime=newestStateMtime,
        statesFresh=statesFresh,
    )


def _pair(
    *,
    cpuFraction: float,
    elapsed: float = float(pl.DEFAULT_OBSERVATION_SECONDS),
    baselineOverrides: dict[str, object] | None = None,
    currentOverrides: dict[str, object] | None = None,
) -> tuple[pl.PanelSample, pl.PanelSample]:
    """A (baseline, current) pair separated by ``elapsed`` at a given CPU rate.

    The state files ADVANCE by default -- that is the half of the signal the
    CPU reading is only meaningful against.
    """
    baseline = _sample(monotonic=1_000.0, cpuSeconds=100.0, **(baselineOverrides or {}))
    currentFields: dict[str, object] = {
        "monotonic": 1_000.0 + elapsed,
        "cpuSeconds": 100.0 + cpuFraction * elapsed,
        "epoch": baseline.epoch + elapsed,
        "newestStateMtime": (baseline.newestStateMtime or 0.0) + elapsed,
    }
    currentFields.update(currentOverrides or {})
    return baseline, _sample(**currentFields)  # type: ignore[arg-type]


def _writeProcStat(
    procRoot: Path,
    pid: int,
    *,
    utimeTicks: int,
    stimeTicks: int,
    startTicks: int = 999,
    comm: str = "chromium",
) -> None:
    """Write a /proc/<pid>/stat with the real field layout.

    Fields 1..52; only comm (2), utime (14), stime (15) and starttime (22)
    matter here. Every other slot is filled with a distinct sentinel so an
    off-by-one in the parser reads a wrong number rather than coincidentally
    reading the right one.
    """
    procDir = procRoot / str(pid)
    procDir.mkdir(parents=True, exist_ok=True)
    fields = [str(7_000 + i) for i in range(52)]
    fields[0] = str(pid)
    fields[1] = f"({comm})"
    fields[2] = "S"
    fields[13] = str(utimeTicks)
    fields[14] = str(stimeTicks)
    fields[21] = str(startTicks)
    (procDir / "stat").write_text(" ".join(fields) + "\n", encoding="utf-8")


# ============================================================================
# The grounded constants.  These pin the NUMBERS to the measurements above, so
# a retune has to break a test that cites its own source.
# ============================================================================


def test_liveCpuFraction_sitsInTheGapBetweenTheMeasuredBands_us654():
    """
    Given: the measured frozen band (<=0.167%) and healthy band (>=3%)
    When: the shipped CPU floor is compared against both
    Then: it lies strictly BETWEEN them -- inside neither

    US-561's lesson, applied before the fact rather than after it: a threshold
    placed INSIDE a signal's own operating band is a coin-flip, not a
    discriminator. The two bands here do not overlap, so a floor exists that is
    outside both, and this test is what stops a future retune moving it into
    one.
    """
    assert max(MEASURED_FROZEN_FRACTIONS) < pl.DEFAULT_LIVE_CPU_FRACTION
    assert pl.DEFAULT_LIVE_CPU_FRACTION < min(MEASURED_HEALTHY_FRACTIONS)


def test_liveCpuFraction_keepsAMarginOnBothSides_us654():
    """
    Given: the floor sits between the bands
    When: its distance from each band is measured
    Then: it clears both by a wide margin, not by a hair

    "Between the bands" is satisfied by a value one ULP above the frozen band,
    which would flip on ordinary jitter. The margins are the actual claim. As
    shipped they are 3x above the worst frozen reading and 6x below the mildest
    healthy one; the bounds asserted here are looser so the exact float is not
    pinned, because the strict "inside neither band" guard above is the hard
    one and this test is about headroom.
    """
    assert pl.DEFAULT_LIVE_CPU_FRACTION > 2.0 * max(MEASURED_FROZEN_FRACTIONS)
    assert pl.DEFAULT_LIVE_CPU_FRACTION < 0.5 * min(MEASURED_HEALTHY_FRACTIONS)


def test_observationWindow_spansAtLeastTwoTimerTicks_us654():
    """
    Given: the timer cadence mirrored from the .timer unit
    When: the observation window is divided by it
    Then: a window spans at least two ticks

    Mirrors the kiosk watchdog's dwell-vs-cadence guard: a window shorter than
    the cadence can never be reached, so the detector would withhold forever
    and look exactly like a healthy one.
    """
    assert pl.DEFAULT_OBSERVATION_SECONDS >= 2 * pl.TIMER_CADENCE_SECONDS


def test_observationWindow_isTheSpanThatActuallyDiscriminated_us654():
    """
    Given: the sprint recorded an 8s sample as unable to discriminate and a
           600s delta as the correct evidence
    When: the shipped window is compared to both
    Then: it is at least the 600s span, and far more than the 8s one

    This is the number the bigDefinitionOfDone corrected itself on. Shrinking
    it is not a tuning choice -- it re-enters the regime where a healthy page
    and a frozen one produce the same reading.
    """
    assert pl.DEFAULT_OBSERVATION_SECONDS >= 600
    assert pl.DEFAULT_OBSERVATION_SECONDS > 8


def test_stateFreshness_isManyTimesTheMeasuredStateCadence_us654():
    """
    Given: states/imu was measured advancing every ~3s
    When: the freshness bound is compared against that cadence
    Then: it is at least 10x it

    The bound answers "were the producers alive when the window closed". It
    must never fire on a live producer's ordinary jitter, so it is decided by
    the measured cadence and not by taste.
    """
    measuredStateCadenceSeconds = 3.0
    assert pl.DEFAULT_STATE_FRESHNESS_SECONDS >= 10 * measuredStateCadenceSeconds


# ============================================================================
# The pure decision.  VC-1, VC-2 and VC-3 live here.
# ============================================================================


def test_decideLiveness_frozenPanelWhileStatesAdvance_reportsDead_us654():
    """
    Given: state files advancing across a full window
    When: chromium's CPU is flat at the measured frozen rate
    Then: the panel is reported DEAD

    VC-1. This is the pair that was measured by hand on the real 7h27m freeze.
    """
    baseline, current = _pair(cpuFraction=14.0 / 26_817.0)

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is True
    assert verdict.reason == pl.REASON_PANEL_DEAD


def test_decideLiveness_healthyPanel_reportsAliveNotDead_us654():
    """
    Given: state files advancing across a full window
    When: chromium is burning CPU at the measured healthy rate
    Then: nothing is reported -- the panel is alive

    VC-2. The false-positive case, and the one the story says is worse than
    having no detector at all.
    """
    baseline, current = _pair(cpuFraction=0.03)

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PANEL_ALIVE


def test_decideLiveness_statesStatic_isNotADeadPanel_us654():
    """
    Given: chromium's CPU is as flat as it is during a real freeze
    When: the state files did NOT advance either
    Then: it is NOT reported as a dead panel

    VC-3, and the story's stated negative case: a parked car with the screen
    off and nothing flowing has nothing to render, so a quiet page is correct
    behaviour rather than a fault.
    """
    baseline, current = _pair(cpuFraction=0.0)
    current = pl.PanelSample(**{**current.__dict__, "newestStateMtime": baseline.newestStateMtime})

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PRODUCERS_IDLE


@pytest.mark.parametrize("frozenFraction", MEASURED_FROZEN_FRACTIONS)
def test_decideLiveness_everyMeasuredFrozenRate_reportsDead_us654(frozenFraction: float):
    """
    Given: each of the three CPU rates measured on a genuinely frozen panel
    When: state files advance across a full window
    Then: every one of them is reported dead

    A detector calibrated to catch only the worst of the three would have
    missed the 0.167% boot, which is the one the sprint calls the strongest
    evidence it has.
    """
    baseline, current = _pair(cpuFraction=frozenFraction)

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is True


@pytest.mark.parametrize("healthyFraction", MEASURED_HEALTHY_FRACTIONS)
def test_decideLiveness_everyMeasuredHealthyRate_reportsAlive_us654(healthyFraction: float):
    """
    Given: each end of the cited healthy CPU band
    When: state files advance across a full window
    Then: neither is reported dead

    The discriminating partner to the frozen parametrize above. Without it, a
    detector that called EVERYTHING dead would pass that one and look green.
    """
    baseline, current = _pair(cpuFraction=healthyFraction)

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False


def test_decideLiveness_cpuExactlyAtTheFloor_isAlive_us654():
    """
    Given: CPU exactly at the configured floor
    When: the verdict is taken
    Then: the panel is ALIVE -- the floor is inclusive on the live side

    Stated explicitly because "dead" is the reporting direction: a boundary
    that is ambiguous should resolve toward not accusing a working display.
    """
    baseline, current = _pair(cpuFraction=pl.DEFAULT_LIVE_CPU_FRACTION)

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PANEL_ALIVE


# ----------------------------------------------------------------------------
# The producer-liveness gate: the window must be live at BOTH ends.
# ----------------------------------------------------------------------------


def test_decideLiveness_producersDiedMidWindow_isNotADeadPanel_us654():
    """
    Given: state files advanced early in the window, then the producers stopped
    When: chromium's CPU is flat across the whole window
    Then: it is NOT reported as a dead panel

    "The mtime advanced" alone is satisfied by a single write in the first
    second of a 600s window, after which the panel is RIGHT to be quiet. The
    end-of-window freshness check is what distinguishes the two.
    """
    baseline, current = _pair(
        cpuFraction=0.0,
        currentOverrides={"statesFresh": False},
    )

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PRODUCERS_IDLE


def test_decideLiveness_producersStartedMidWindow_isNotADeadPanel_us654():
    """
    Given: the producers were already stale when the window OPENED
    When: they come back late in the window and chromium's average is low
    Then: it is NOT reported as a dead panel

    The mirror of the test above, and it must be its own case: the CPU average
    is taken over the whole window, so most of it covers time the panel had
    nothing to draw. Judging that average as a freeze accuses the display of
    the producers' downtime.
    """
    baseline, current = _pair(
        cpuFraction=0.0,
        baselineOverrides={"statesFresh": False},
    )

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PRODUCERS_IDLE


def test_decideLiveness_noStateFilesAtAll_isNotADeadPanel_us654():
    """
    Given: the states directory holds nothing to read
    When: chromium's CPU is flat
    Then: it is NOT reported as a dead panel

    An absent producer is the strongest possible form of "nothing to render".
    A detector that treated a missing states dir as evidence would fire on
    every box where the emitters have not started yet.
    """
    baseline, current = _pair(
        cpuFraction=0.0,
        baselineOverrides={"newestStateMtime": None, "statesFresh": False},
        currentOverrides={"newestStateMtime": None, "statesFresh": False},
    )

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PRODUCERS_IDLE


# ----------------------------------------------------------------------------
# Withheld verdicts.  Each of these must be distinguishable from "alive".
# ----------------------------------------------------------------------------


def test_decideLiveness_noBaseline_withholdsAnyVerdict_us654():
    """
    Given: no prior sample (first tick after a boot wipes the tmpfs)
    When: a sample is taken
    Then: no verdict is reached and nothing is reported

    A rate needs two readings. One reading is a number, not a rate.
    """
    verdict = pl.decideLiveness(
        baseline=None, current=_sample(monotonic=10.0, cpuSeconds=1.0), policy=_policy()
    )

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_NO_BASELINE
    assert verdict.cpuFraction is None


def test_decideLiveness_observationShorterThanWindow_withholdsAnyVerdict_us654():
    """
    Given: only 8 seconds have elapsed since the baseline
    When: chromium accrued no measurable CPU in that span
    Then: NO verdict is reached -- it is not called dead, and not called alive

    THE SPRINT'S OWN CORRECTION. The original freeze evidence was "CPU flat
    across an 8s sample", and the bigDefinitionOfDone retracted it: a healthy
    ~3% page also reads flat over 8s. A short sample carries no information in
    EITHER direction, so it must be withheld rather than rounded to whichever
    answer the caller finds convenient.
    """
    baseline, current = _pair(cpuFraction=0.0, elapsed=8.0)

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_OBSERVATION_TOO_SHORT


def test_decideLiveness_shortObservationOfAHealthyPanel_alsoWithholds_us654():
    """
    Given: only 8 seconds elapsed, and the panel is in fact healthy
    When: the verdict is taken
    Then: it is withheld for the SAME reason as the frozen short sample

    The discriminating partner. If a short sample resolved to "alive", the two
    cases above would differ -- and the whole point of the retraction is that
    at 8s they are indistinguishable. Identical input span, identical verdict.
    """
    baseline, current = _pair(cpuFraction=0.03, elapsed=8.0)

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.reason == pl.REASON_OBSERVATION_TOO_SHORT


def test_decideLiveness_processReplaced_withholdsAnyVerdict_us654():
    """
    Given: chromium's pid differs from the one the baseline recorded
    When: the samples are differenced
    Then: no verdict -- the CPU counter restarted from zero

    Differencing across a restart yields a NEGATIVE or meaningless delta. The
    kiosk watchdog restarts this very unit, so a replaced process is an
    ordinary event here, not an exotic one.
    """
    baseline, current = _pair(cpuFraction=0.0, currentOverrides={"pid": 5555})

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PROCESS_REPLACED


def test_decideLiveness_pidReusedByANewProcess_withholdsAnyVerdict_us654():
    """
    Given: the same pid, but a different process start time
    When: the samples are differenced
    Then: no verdict -- this is a DIFFERENT process wearing a recycled pid

    A pid check alone is satisfied by reuse, which is exactly what makes the
    counter reset invisible. The start time is what makes the identity real.
    """
    baseline, current = _pair(cpuFraction=0.0, currentOverrides={"startTicks": 123_456})

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.reason == pl.REASON_PROCESS_REPLACED


def test_decideLiveness_cpuCounterWentBackwards_withholdsAnyVerdict_us654():
    """
    Given: the current CPU total is LOWER than the baseline's
    When: the samples are differenced
    Then: no verdict is reached

    A monotonic counter that decreased means the identity check above did not
    catch a replacement. Reporting a negative rate as "below the floor" would
    turn an instrument fault into a confident accusation.
    """
    baseline, current = _pair(cpuFraction=0.0)
    current = pl.PanelSample(**{**current.__dict__, "cpuSeconds": baseline.cpuSeconds - 5.0})

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PROCESS_REPLACED


def test_decideLiveness_ntpStepDoesNotManufactureADeadPanel_us654():
    """
    Given: a baseline stamped before NTP stepped the clock from 1970 to 2026
    When: a healthy panel is sampled 600 MONOTONIC seconds later
    Then: the panel is ALIVE -- the ~56-year wall-clock jump changes nothing

    A-23, and the same root as US-644-b at a fourth surface. This Pi's RTC
    starts at 1970 and is stepped by NTP. An elapsed time taken from the wall
    clock would read ~1.8e9 seconds against ~18 seconds of CPU -- a fraction of
    1e-8, far below any floor -- and the detector would report a perfectly
    healthy display as dead, at every boot, forever. Elapsed MUST come from the
    monotonic clock; the wall clock survives only to compare file mtimes.
    """
    elapsed = float(pl.DEFAULT_OBSERVATION_SECONDS)
    baseline = _sample(monotonic=1_000.0, cpuSeconds=100.0, epoch=0.0, newestStateMtime=0.0)
    current = _sample(
        monotonic=1_000.0 + elapsed,
        cpuSeconds=100.0 + 0.03 * elapsed,
        epoch=1_756_000_000.0,
        newestStateMtime=1_756_000_000.0,
    )

    verdict = pl.decideLiveness(baseline=baseline, current=current, policy=_policy())

    assert verdict.panelDead is False
    assert verdict.reason == pl.REASON_PANEL_ALIVE


# ============================================================================
# Seams: /proc, systemctl, the states dir, the baseline file.
# ============================================================================


def test_readProcessCpu_sumsUserAndSystemTime_us654(tmp_path: Path):
    """
    Given: a process that has accrued 700 user and 300 system ticks
    When: its CPU is read at 100 ticks per second
    Then: the total is 10.0 seconds

    Both halves count: a frozen renderer can still burn system time, and
    reading only utime would under-report a page that is spinning in syscalls.
    """
    _writeProcStat(tmp_path, 4242, utimeTicks=700, stimeTicks=300)

    reading = pl.readProcessCpu(4242, procRoot=tmp_path, ticksPerSecond=100.0)

    assert reading is not None
    assert reading.cpuSeconds == pytest.approx(10.0)


def test_readProcessCpu_readsTheProcessStartTime_us654(tmp_path: Path):
    """
    Given: a process whose stat records a start time
    When: its CPU is read
    Then: the start time comes back alongside the CPU total

    The start time is what makes the pid identity real across reuse, so it has
    to survive the parse rather than being re-derived later.
    """
    _writeProcStat(tmp_path, 4242, utimeTicks=1, stimeTicks=1, startTicks=8_675_309)

    reading = pl.readProcessCpu(4242, procRoot=tmp_path, ticksPerSecond=100.0)

    assert reading is not None
    assert reading.startTicks == 8_675_309


def test_readProcessCpu_commContainingSpacesAndParens_isParsedCorrectly_us654(tmp_path: Path):
    """
    Given: a process whose comm field itself contains spaces and parentheses
    When: its CPU is read
    Then: the numbers are still correct

    /proc/<pid>/stat's second field is unescaped, so a naive `split()` shifts
    every later field. The comm is the process name, and chromium is renamed
    at runtime -- this is not a hypothetical layout.
    """
    _writeProcStat(tmp_path, 4242, utimeTicks=500, stimeTicks=500, comm="chromium (gpu) x")

    reading = pl.readProcessCpu(4242, procRoot=tmp_path, ticksPerSecond=100.0)

    assert reading is not None
    assert reading.cpuSeconds == pytest.approx(10.0)


def test_readProcessCpu_missingProcess_isNone_us654(tmp_path: Path):
    """
    Given: no stat file for the pid (the process exited between calls)
    When: its CPU is read
    Then: None comes back rather than an exception or a zero

    The discriminating partner to the readings above: a zero would be
    indistinguishable from a frozen process, which is the exact confusion this
    whole module exists to remove.
    """
    assert pl.readProcessCpu(4242, procRoot=tmp_path, ticksPerSecond=100.0) is None


def test_readProcessCpu_malformedStat_isNone_us654(tmp_path: Path):
    """
    Given: a stat file that does not parse
    When: its CPU is read
    Then: None comes back

    Same reason as above: an unreadable instrument must not answer zero.
    """
    procDir = tmp_path / "4242"
    procDir.mkdir()
    (procDir / "stat").write_text("not a stat line\n", encoding="utf-8")

    assert pl.readProcessCpu(4242, procRoot=tmp_path, ticksPerSecond=100.0) is None


def test_clockTicksPerSecond_fallsBackWhenSysconfIsUnavailable_us654(monkeypatch):
    """
    Given: a platform with no os.sysconf (this bench is one)
    When: the clock rate is resolved
    Then: it falls back to the Linux default of 100 rather than raising

    The fallback only ever applies off-Linux, where there is no /proc to read
    anyway -- but it must not take the module down at import or on a unit-test
    box.
    """
    monkeypatch.delattr("os.sysconf", raising=False)

    assert pl.clockTicksPerSecond() == 100.0


def test_dashboardMainPid_activeUnit_returnsThePid_us654():
    """
    Given: systemd reports a MainPID for the kiosk unit
    When: the pid is read
    Then: it comes back as an int
    """

    def fakeRun(argv, **kwargs):
        assert "MainPID" in " ".join(argv)
        return _completed(stdout="4242\n")

    assert pl.dashboardMainPid("eclipse-dashboard.service", runFn=fakeRun) == 4242


def test_dashboardMainPid_inactiveUnit_isNone_us654():
    """
    Given: systemd reports MainPID=0 (the unit is not running)
    When: the pid is read
    Then: None comes back

    Zero is systemd's way of saying "no process", and it is a valid pid-shaped
    integer -- reading it as one would send the /proc read to /proc/0.
    """
    assert pl.dashboardMainPid("x.service", runFn=lambda *a, **k: _completed("0\n")) is None


def test_dashboardMainPid_systemctlUnavailable_isNone_us654():
    """
    Given: systemctl cannot be run at all
    When: the pid is read
    Then: None comes back rather than an exception
    """

    def boom(*args, **kwargs):
        raise OSError("no systemctl")

    assert pl.dashboardMainPid("x.service", runFn=boom) is None


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    """A subprocess.CompletedProcess stand-in for the systemctl seam."""
    return subprocess.CompletedProcess(args=["systemctl"], returncode=returncode, stdout=stdout)


def test_sampleStates_reportsTheNewestMtimeAcrossTheDirectory_us654(tmp_path: Path):
    """
    Given: several state files with different mtimes
    When: the states dir is sampled
    Then: the NEWEST mtime is reported

    Any single producer advancing means there is something to render, so the
    newest wins rather than an average or a specific file.
    """
    for name, mtime in (("imu", 1_000.0), ("dtc", 3_000.0), ("system", 2_000.0)):
        target = tmp_path / name
        target.write_text("{}", encoding="utf-8")
        os.utime(target, (mtime, mtime))

    reading = pl.sampleStates(tmp_path, now=3_010.0, freshnessSeconds=60)

    assert reading.newestMtime == pytest.approx(3_000.0)
    assert reading.fresh is True


def test_sampleStates_staleDirectory_isNotFresh_us654(tmp_path: Path):
    """
    Given: the newest state file is older than the freshness bound
    When: the states dir is sampled
    Then: it reports NOT fresh

    The discriminating partner to the test above -- without it, a sampler that
    always answered "fresh" would look identical.
    """
    target = tmp_path / "imu"
    target.write_text("{}", encoding="utf-8")
    os.utime(target, (1_000.0, 1_000.0))

    reading = pl.sampleStates(tmp_path, now=9_999.0, freshnessSeconds=60)

    assert reading.newestMtime == pytest.approx(1_000.0)
    assert reading.fresh is False


def test_sampleStates_ignoresDotFiles_us654(tmp_path: Path):
    """
    Given: a states dir holding only the .http-token dotfile
    When: the dir is sampled
    Then: no state mtime is found

    /run/eclipse-obd/states/.http-token is written once by the state server and
    is NOT a producer heartbeat. Counting it would make an idle box look like a
    live one exactly once, at the worst possible moment -- right after boot.
    """
    (tmp_path / ".http-token").write_text("secret", encoding="utf-8")

    reading = pl.sampleStates(tmp_path, now=1_000.0, freshnessSeconds=60)

    assert reading.newestMtime is None
    assert reading.fresh is False


def test_sampleStates_missingDirectory_isNotFresh_us654(tmp_path: Path):
    """
    Given: the states directory does not exist
    When: it is sampled
    Then: no mtime, not fresh, and no exception

    Before the emitters have ever run this dir can be empty or absent, and that
    must read as "nothing to render", never as a signal.
    """
    reading = pl.sampleStates(tmp_path / "absent", now=1_000.0, freshnessSeconds=60)

    assert reading.newestMtime is None
    assert reading.fresh is False


def test_baselineRoundTrip_survivesTheFile_us654(tmp_path: Path):
    """
    Given: a sample written to the baseline file
    When: it is read back
    Then: every field survives

    The baseline is the ONLY thing that crosses two fires of a oneshot. A field
    lost in the round trip silently disables the check that reads it.
    """
    path = tmp_path / "baseline.json"
    sample = _sample(monotonic=42.0, cpuSeconds=7.5, pid=99, startTicks=5, statesFresh=True)

    assert pl.writeBaseline(path, sample) is True
    assert pl.readBaseline(path) == sample


def test_readBaseline_corruptFile_isNone_us654(tmp_path: Path):
    """
    Given: a baseline file that is not valid JSON
    When: it is read
    Then: None comes back, so the next tick simply re-baselines
    """
    path = tmp_path / "baseline.json"
    path.write_text("{not json", encoding="utf-8")

    assert pl.readBaseline(path) is None


def test_writeBaseline_unwritablePath_isFalseNotAnException_us654(tmp_path: Path):
    """
    Given: a baseline path inside a file (so the directory cannot be made)
    When: a write is attempted
    Then: it returns False rather than raising
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    sample = _sample(monotonic=1.0, cpuSeconds=1.0)

    assert pl.writeBaseline(blocker / "sub" / "baseline.json", sample) is False


# ============================================================================
# runOnce: the wiring, and the baseline-rotation policy that makes the window
# accumulate at all.
# ============================================================================


#: Distinguishes "this test did not specify a value" from "the seam returned
#: None". They are different facts, and conflating them is what made the first
#: run of test_runOnce_cpuUnreadable pass a healthy reading into a test about an
#: unreadable one -- the same collapse US-644-a removed from the watchdog.
_UNSET = object()


def _runOnce(
    *,
    pid: int | None = 4242,
    cpu: pl.ProcessCpu | None | object = _UNSET,
    states: pl.StatesReading | None = None,
    baseline: pl.PanelSample | None = None,
    writes: list[pl.PanelSample] | None = None,
    monotonic: float = 2_000.0,
    epoch: float = 1_756_000_600.0,
    policy: pl.LivenessPolicy | None = None,
    writeOk: bool = True,
) -> pl.LivenessVerdict:
    """Drive one tick with every seam faked, recording baseline writes."""
    recorded = writes if writes is not None else []

    def writeFn(sample: pl.PanelSample) -> bool:
        recorded.append(sample)
        return writeOk

    return pl.runOnce(
        policy=policy or _policy(),
        unitName="eclipse-dashboard.service",
        mainPidFn=lambda unit: pid,
        cpuFn=lambda p: (
            pl.ProcessCpu(cpuSeconds=103.0, startTicks=999) if cpu is _UNSET else cpu
        ),
        statesFn=lambda now: states
        if states is not None
        else pl.StatesReading(newestMtime=epoch, fresh=True),
        readBaselineFn=lambda: baseline,
        writeBaselineFn=writeFn,
        clockFn=lambda: epoch,
        monotonicFn=lambda: monotonic,
    )


def test_runOnce_kioskInactive_reportsNothingAndTouchesNoBaseline_us654():
    """
    Given: the dashboard unit has no running process
    When: a tick runs
    Then: no report, and the baseline is left exactly as it was

    Rewriting the baseline while the kiosk is down would stamp a sample against
    a process that does not exist, and the next live tick would difference
    against it. The kiosk watchdog leaves an inactive kiosk alone for its own
    reasons; this one does so because there is nothing to measure.
    """
    writes: list[pl.PanelSample] = []

    verdict = _runOnce(pid=None, writes=writes)

    assert verdict.reason == pl.REASON_KIOSK_INACTIVE
    assert verdict.panelDead is False
    assert writes == []


def test_runOnce_cpuUnreadable_isAFaultNotAHealthReport_us654():
    """
    Given: chromium's pid is known but /proc will not read
    When: a tick runs
    Then: the reason is an instrument fault, distinct from both alive and dead

    US-644-a's lesson carried across: a detector that cannot read its own
    signal must say so, because an INFO no-op that looks like a healthy tick is
    how a panel stayed frozen for 7h27m.
    """
    verdict = _runOnce(cpu=None)

    assert verdict.reason == pl.REASON_CPU_UNREADABLE
    assert verdict.panelDead is False


def test_runOnce_firstTick_recordsABaseline_us654():
    """
    Given: no baseline on a freshly booted tmpfs
    When: a tick runs
    Then: the current sample is written as the baseline
    """
    writes: list[pl.PanelSample] = []

    verdict = _runOnce(baseline=None, writes=writes)

    assert verdict.reason == pl.REASON_NO_BASELINE
    assert len(writes) == 1
    assert writes[0].cpuSeconds == pytest.approx(103.0)


def test_runOnce_observationTooShort_KEEPSTheOriginalBaseline_us654():
    """
    Given: a baseline only 8 monotonic seconds old
    When: a tick runs
    Then: NO baseline write happens -- the old one is kept

    THE LOAD-BEARING WIRING TEST. If a short observation rotated the baseline,
    every tick would restart the window and the 600s span could never be
    reached, so the detector would withhold forever while looking perfectly
    healthy in its own logs. That is the inert-guard shape this sprint has been
    cataloguing, and it is invisible to every decision-table test above.
    """
    baseline = _sample(monotonic=1_992.0, cpuSeconds=100.0)
    writes: list[pl.PanelSample] = []

    verdict = _runOnce(baseline=baseline, writes=writes, monotonic=2_000.0)

    assert verdict.reason == pl.REASON_OBSERVATION_TOO_SHORT
    assert writes == []


def test_runOnce_afterAVerdict_rotatesTheBaseline_us654():
    """
    Given: a completed observation window
    When: a tick reaches a verdict
    Then: the baseline is rotated to the current sample

    The discriminating partner to the test above: a detector that NEVER wrote
    would also pass "short observations keep the baseline", and would then
    measure one ever-lengthening window from boot.
    """
    baseline = _sample(monotonic=1_400.0, cpuSeconds=100.0, newestStateMtime=1_756_000_000.0)
    writes: list[pl.PanelSample] = []

    _runOnce(baseline=baseline, writes=writes, monotonic=2_000.0)

    assert len(writes) == 1
    assert writes[0].monotonic == pytest.approx(2_000.0)


def test_runOnce_producersIdle_rotatesTheBaseline_us654():
    """
    Given: a completed window in which the state files never advanced
    When: the tick declines to judge
    Then: the baseline is STILL rotated

    A parked period must not be carried into the next window. If the baseline
    were held across an hour of a sleeping car, the next window would average
    chromium's CPU over that hour and report a healthy panel dead the moment
    data started flowing again -- a false positive manufactured by the
    detector's own bookkeeping.
    """
    baseline = _sample(monotonic=1_400.0, cpuSeconds=100.0, newestStateMtime=1_756_000_600.0)
    writes: list[pl.PanelSample] = []

    verdict = _runOnce(
        baseline=baseline,
        writes=writes,
        monotonic=2_000.0,
        states=pl.StatesReading(newestMtime=1_756_000_600.0, fresh=True),
    )

    assert verdict.reason == pl.REASON_PRODUCERS_IDLE
    assert len(writes) == 1


def test_runOnce_carriesTheStatesFreshnessIntoTheSample_us654():
    """
    Given: state files that ADVANCED but are stale at the close of the window
    When: a tick runs
    Then: no verdict -- the producers were not live at the end

    A WIRING TEST, and it exists because the decision table cannot reach this.
    Every test above hands decideLiveness a hand-built sample, so a runOnce that
    stopped reading `states.fresh` and hardcoded True would leave the entire
    suite green while silently deleting the guard that stops a producer dying
    mid-window from being blamed on the panel. US-625's M13 lesson: a fix must
    not be able to ship INERT behind a green suite.
    """
    baseline = _sample(monotonic=1_400.0, cpuSeconds=100.0, newestStateMtime=1_756_000_000.0)

    verdict = _runOnce(
        baseline=baseline,
        monotonic=2_000.0,
        cpu=pl.ProcessCpu(cpuSeconds=100.3, startTicks=999),
        states=pl.StatesReading(newestMtime=1_756_000_600.0, fresh=False),
    )

    assert verdict.reason == pl.REASON_PRODUCERS_IDLE
    assert verdict.panelDead is False


def test_runOnce_deadPanel_logsAtErrorAndSaysWhatItMeasured_us654(caplog):
    """
    Given: a frozen panel across a full window
    When: the tick reports
    Then: the line is ERROR and carries the measured CPU fraction

    The shipped failure was a panel dead for 7h27m with nothing above INFO in
    the journal. A report nobody greps for is not a report, and a report
    without its own measurement cannot be audited later.
    """
    baseline = _sample(monotonic=1_400.0, cpuSeconds=100.0, newestStateMtime=1_756_000_000.0)

    with caplog.at_level(logging.INFO):
        verdict = _runOnce(
            baseline=baseline,
            monotonic=2_000.0,
            cpu=pl.ProcessCpu(cpuSeconds=100.3, startTicks=999),
        )

    assert verdict.panelDead is True
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a dead panel must be reported above INFO"
    assert "%" in errors[0].getMessage() or "cpu" in errors[0].getMessage().lower()


def test_runOnce_healthyPanel_doesNotLogAnError_us654(caplog):
    """
    Given: a healthy panel across a full window
    When: the tick reports
    Then: nothing at ERROR

    The discriminating partner: a module that logged ERROR unconditionally
    would satisfy the test above and make the journal useless.
    """
    baseline = _sample(monotonic=1_400.0, cpuSeconds=100.0, newestStateMtime=1_756_000_000.0)

    with caplog.at_level(logging.INFO):
        _runOnce(
            baseline=baseline,
            monotonic=2_000.0,
            cpu=pl.ProcessCpu(cpuSeconds=118.0, startTicks=999),
        )

    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_runOnce_baselineUnwritable_isReportedNotSilent_us654():
    """
    Given: the baseline file cannot be written
    When: a tick runs
    Then: the reason says so

    Without a baseline the detector has no memory, so it can never reach a
    window. Silently failing to write would make it permanently blind while
    every tick logged a routine no-op.
    """
    verdict = _runOnce(baseline=None, writeOk=False)

    assert verdict.reason == pl.REASON_BASELINE_UNWRITABLE
    assert verdict.panelDead is False


# ============================================================================
# CLI contract + the census guard.
# ============================================================================


def test_exitCodeTable_coversEveryDeclaredReason_us654():
    """
    Given: every REASON_* constant the module declares
    When: the exit-code table is compared against them
    Then: none is missing

    US-644-a's census guard, inherited. An exit-code table is an ENUMERATION of
    reasons, and this project has spent nine sprints cataloguing the shape
    where a citation is treated as a census. A new reason added without an
    exit-code decision would default to whatever the fallthrough happens to be.
    """
    declared = {
        value
        for name, value in vars(pl).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }

    assert declared - set(pl._EXIT_CODE_TABLE) == set()


@pytest.mark.parametrize(
    "reason,expected",
    [
        (pl.REASON_PANEL_DEAD, pl.EXIT_RUNTIME),
        (pl.REASON_CPU_UNREADABLE, pl.EXIT_RUNTIME),
        (pl.REASON_BASELINE_UNWRITABLE, pl.EXIT_RUNTIME),
        (pl.REASON_PANEL_ALIVE, pl.EXIT_OK),
        (pl.REASON_PRODUCERS_IDLE, pl.EXIT_OK),
        (pl.REASON_OBSERVATION_TOO_SHORT, pl.EXIT_OK),
        (pl.REASON_NO_BASELINE, pl.EXIT_OK),
        (pl.REASON_PROCESS_REPLACED, pl.EXIT_OK),
        (pl.REASON_KIOSK_INACTIVE, pl.EXIT_OK),
    ],
)
def test_main_exitCode_matchesTheReason_us654(reason: str, expected: int):
    """
    Given: a tick that ends with a given reason
    When: main() returns
    Then: the exit code makes a dead panel VISIBLE in `systemctl status`

    A dead panel exits non-zero on purpose: the whole finding of US-654 is that
    the freeze was invisible, and a oneshot that always exits 0 is invisible by
    construction.
    """
    verdict = pl.LivenessVerdict(reason=reason, panelDead=reason == pl.REASON_PANEL_DEAD)

    assert pl.main([], runOnceFn=lambda **kwargs: verdict) == expected


def test_main_defaultsMatchTheShippedConstants_us654():
    """
    Given: no CLI arguments
    When: the parser builds a policy
    Then: it carries the grounded defaults

    A CLI default that drifts from the module constant makes every grounding
    test above assert something the deployed unit does not use.
    """
    captured: dict[str, pl.LivenessPolicy] = {}

    def capture(**kwargs):
        captured["policy"] = kwargs["policy"]
        return pl.LivenessVerdict(reason=pl.REASON_NO_BASELINE, panelDead=False)

    pl.main([], runOnceFn=capture)

    assert captured["policy"].observationSeconds == pl.DEFAULT_OBSERVATION_SECONDS
    assert captured["policy"].liveCpuFraction == pl.DEFAULT_LIVE_CPU_FRACTION
    assert captured["policy"].stateFreshnessSeconds == pl.DEFAULT_STATE_FRESHNESS_SECONDS


# ============================================================================
# Scope fences.  Both are story clauses, made mechanical.
# ============================================================================


def test_panelLiveness_restartsNothing_us654():
    """
    Given: the module source
    When: it is searched for a restart verb
    Then: there is none

    THE STORY'S EXPLICIT SCOPE FENCE: restarting as a remedy is deliberately
    out of scope, because chromium restarts correlate with the class-B marker
    storm -- an automatic remedy here could trade a DETECTED freeze for a
    CAUSED one. An observer that acquires a remedy later has quietly become a
    second watchdog competing with the first over the same subject.

    Parsed as an AST rather than grepped: the header discusses restarts at
    length and so do these docstrings, so a substring guard would be tripped by
    prose. Bare string expressions (every docstring) are skipped; what is left
    is the strings the code can actually ACT on.
    """
    tree = ast.parse(Path(pl.__file__).read_text(encoding="utf-8"))
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }

    functionNames = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }

    # No argv element that systemctl would read as the restart verb...
    assert "restart" not in literals
    assert not [text for text in literals if "systemctl restart" in text.lower()]
    # ...and no function here is in the business of performing one.
    assert not [name for name in functionNames if "restart" in name.lower()]


def test_kioskWatchdog_wasNotWidenedToCoverThisClass_us654():
    """
    Given: the marker-only kiosk watchdog
    When: its source is checked for this detector
    Then: it neither imports nor mentions it

    ATLAS, EXPLICIT: "DO NOT WIDEN US-644 TO COVER THIS. A marker-only detector
    must not be stretched to cover a class it structurally cannot see -- that
    would produce a detector that claims a coverage it does not have, which is
    the inert-guard shape again."
    """
    from pi.display import kiosk_watchdog

    text = Path(kiosk_watchdog.__file__).read_text(encoding="utf-8")

    assert "panel_liveness" not in text
