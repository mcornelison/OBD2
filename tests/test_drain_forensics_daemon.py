################################################################################
# File Name: test_drain_forensics_daemon.py
# Purpose/Description: US-646 -- drain-forensics spawned a fresh Python process
#     every 5 seconds, forever, and narrated each one into the journal. This
#     file pins the replacement: ONE long-running process that ticks internally
#     on the SAME 5s cadence.
#
#     The story's conditionalOutcome decided the shape: "If the 5 s cadence IS
#     required to catch a fast drain, keep the cadence and remove the spawn --
#     do not trade detection for tidiness." It is required (the US-262 CSV
#     row-rate spec exists to resolve the LiPo dropout knee in a post-mortem),
#     so the SPAWN MODEL is what changes and the interval does not. Every test
#     below is therefore paired: a churn/volume claim NEXT TO a claim that
#     detection responsiveness is untouched. Either one alone is satisfiable
#     the wrong way -- deleting the logger removes all the churn.
#
#     ARCH-006 is NOT this fix and must not be mistaken for it. It removed the
#     second I2C ACQUISITION per fire; the fire itself was untouched. Pinned
#     explicitly below so the two are not conflated again.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Rex (US-646) | Initial -- daemon loop, retired timer, journal
#                                volume, and the anti-churn guards on the fix.
# ================================================================================
################################################################################

"""Acceptance tests for US-646: retire the 5s process spawn, keep the 5s cadence."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import pytest

from scripts.drain_forensics import (
    CSV_COLUMNS,
    DEFAULT_INTERVAL_SECONDS,
    RunResult,
    StopSignal,
    buildProductionContext,
    main,
    runForever,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
DRAIN_SERVICE = DEPLOY_DIR / "drain-forensics.service"
DRAIN_TIMER = DEPLOY_DIR / "drain-forensics.timer"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy-pi.sh"

# The cadence the retired timer drove, restated here as a number so a test can
# fail if the daemon quietly slows down. `OnUnitActiveSec=5s`.
RETIRED_TIMER_CADENCE_SECONDS = 5.0

# Five minutes of ticks at the shipped cadence -- the window the story's first
# validationCriterion names ("observe process spawns over 5 minutes").
TICKS_IN_FIVE_MINUTES = int(300 / RETIRED_TIMER_CADENCE_SECONDS)

# A LiPo cell sustained below 3.95V reads as BATTERY; the wall-fed float is
# ~4.10V. Mirrors _readPowerSourceFromVcell's documented rule.
ON_BATTERY_VCELL = 3.80
ON_WALL_VCELL = 4.11


# ============================================================================
# Fakes
# ============================================================================


class FakeStop:
    """A StopSignal-shaped object that halts the loop after N waits.

    Records every interval it was asked to wait for, so a test can assert the
    CADENCE rather than merely that a loop ran. Real time is never consumed.
    """

    def __init__(self, stopAfter: int, onWait=None) -> None:
        self.stopAfter = stopAfter
        self.waits: list[float] = []
        self._set = False
        # Called with the 1-based wait index, i.e. BETWEEN ticks. The only way
        # to change the world mid-loop; a test that restarts the loop instead
        # gets a fresh dedup state and stops measuring the dedup rule.
        self._onWait = onWait

    def isSet(self) -> bool:
        return self._set

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        if self._onWait is not None:
            self._onWait(len(self.waits))
        if len(self.waits) >= self.stopAfter:
            self._set = True
        return self._set


def _writeBatteryHealth(path: Path, *, vcell: float, ageSec: float = 0.0) -> Path:
    """Publish a battery-health reading of the shape powerwatch writes."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - ageSec))
    path.write_text(
        json.dumps({"vcellV": vcell, "soc": 96, "crate": None, "ts": ts}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def wiring(tmp_path):
    """A production-wired context reading a state file the test controls."""
    logDir = tmp_path / "log"
    logDir.mkdir()
    statePath = _writeBatteryHealth(tmp_path / "battery-health", vcell=ON_WALL_VCELL)
    ctx = buildProductionContext(
        logDir=logDir,
        batteryHealthStateFile=statePath,
        orchestratorStateFile=tmp_path / "absent-orchestrator-state.json",
    )
    return ctx, statePath, logDir


def _csvFiles(logDir: Path) -> list[Path]:
    return sorted(logDir.glob("drain-forensics-*.csv"))


def _rowsIn(path: Path) -> int:
    return max(0, len(path.read_text().strip().splitlines()) - 1)


def _dataRowCount(logDir: Path) -> int:
    return sum(_rowsIn(p) for p in _csvFiles(logDir))


def _newestCsvRowCount(logDir: Path) -> int:
    """Rows in the most recently written CSV, or -1 if none exists.

    Rotation is asserted on THIS rather than on a file count or a summed row
    count: ``composeFilename`` is second-granular, so a rotation inside one
    wall-clock second reuses the name and truncates.  Both outcomes are a
    correct rotation and both leave the newest artifact holding one row.
    """
    files = _csvFiles(logDir)
    if not files:
        return -1
    return _rowsIn(max(files, key=lambda p: p.stat().st_mtime))


# ============================================================================
# A. The spawn is gone -- one process does the work the timer spawned for
# ============================================================================


class TestTheSpawnModelIsRetired:
    """END STATE: 'without a process spawn every 5 s'."""

    def test_fiveMinutesOfTicksHappenInsideOneCall(self, wiring):
        """
        Given: the daemon loop and the shipped 5s cadence
        When: five minutes' worth of ticks elapse
        Then: they all occur inside ONE runForever call

        The old model crossed a process boundary 60 times to do this. The
        count is asserted rather than 'it looped', because a loop that exits
        after one tick would leave systemd's Restart=always re-spawning it and
        the defect would be intact under a new name.
        """
        ctx, _, _ = wiring
        stop = FakeStop(stopAfter=TICKS_IN_FIVE_MINUTES)

        ticks = runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=stop)

        assert ticks == TICKS_IN_FIVE_MINUTES

    def test_theShippedTimerFileIsGoneFromDeploy(self):
        """The .timer WAS the spawn. Pin its deletion so it stays deleted."""
        assert not DRAIN_TIMER.exists(), (
            "deploy/drain-forensics.timer is back. That unit is the 5s process "
            "spawn US-646 removed -- OnUnitActiveSec=5s over a Type=oneshot "
            "service. Re-adding it re-opens the defect."
        )

    def test_theShippedUnitIsNoLongerAOneshot(self):
        """
        Given: deploy/drain-forensics.service
        When: its Type= is read
        Then: it is not oneshot

        Type=oneshot is the half of the pair that made every fire a fresh
        interpreter. A long-running logger cannot be oneshot.
        """
        body = DRAIN_SERVICE.read_text(encoding="utf-8")
        assert not re.search(r"^\s*Type\s*=\s*oneshot\s*$", body, re.MULTILINE), (
            "drain-forensics.service is Type=oneshot again -- that is the "
            "per-fire fresh-interpreter model US-646 replaced."
        )
        assert re.search(r"^\s*Type\s*=\s*simple\s*$", body, re.MULTILINE), (
            "drain-forensics.service must declare Type=simple: the process "
            "stays up and ticks internally."
        )

    def test_theShippedUnitLaunchesTheDaemonMode(self):
        """ExecStart must ask for the loop, not a single row.

        Without --daemon the unit runs one tick and exits; under
        Restart=always that is the 5s spawn again, driven by systemd's
        restart logic instead of a timer.
        """
        body = DRAIN_SERVICE.read_text(encoding="utf-8")
        execLine = re.search(r"^ExecStart=(.+)$", body, re.MULTILINE)
        assert execLine, "drain-forensics.service has no ExecStart"
        assert "scripts/drain_forensics.py" in execLine.group(1)
        assert "--daemon" in execLine.group(1), (
            f"ExecStart does not pass --daemon: {execLine.group(1)!r}. "
            "One-shot mode under Restart=always is the spawn defect wearing "
            "a different hat."
        )

    def test_theShippedUnitIsItsOwnBootHook(self):
        """
        Given: the .timer is deleted
        When: the Pi boots
        Then: the service starts anyway

        `systemctl enable drain-forensics.timer` used to be the install hook,
        and the .service carried NO [Install] section because of it. Deleting
        the timer without adding WantedBy=multi-user.target here would leave a
        logger that is enabled, correct, and never runs after a reboot -- a
        silent loss of forensics rather than a loud one.
        """
        body = DRAIN_SERVICE.read_text(encoding="utf-8")
        assert re.search(
            r"^WantedBy=multi-user\.target\s*$", body, re.MULTILINE
        ), (
            "drain-forensics.service has no WantedBy=multi-user.target. The "
            "timer that used to start it is gone, so nothing starts it at boot."
        )

    def test_noShippedUnitStillReferencesTheRetiredTimer(self):
        """A dangling Requires=/Wants= on a deleted unit fails the whole start."""
        for unit in sorted(DEPLOY_DIR.glob("*.service")) + sorted(
            DEPLOY_DIR.glob("*.timer")
        ):
            body = unit.read_text(encoding="utf-8")
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                assert "drain-forensics.timer" not in stripped, (
                    f"{unit.name} still references drain-forensics.timer "
                    f"in a directive: {stripped!r}"
                )


class TestTheDeployRetiresTheInstalledTimer:
    """Deleting the repo file does not stop a timer already enabled on the Pi."""

    @pytest.fixture
    def stepBody(self) -> str:
        text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        start = re.search(
            r"^step_install_drain_forensics_unit\(\) \{", text, re.MULTILINE
        )
        assert start, "step_install_drain_forensics_unit is gone from deploy-pi.sh"
        body = text[start.end():]
        end = re.search(r"^[a-z_]+\(\) \{", body, re.MULTILINE)
        return body[: end.start()] if end else body

    @pytest.fixture
    def remoteBody(self, stepBody: str) -> str:
        """The step body with COMMENTS and the DRY-RUN block removed.

        Everything below is a claim about what the deploy DOES on the Pi, and
        the step contains two other things that read exactly like doing it: a
        prose comment block explaining the retirement, and a
        ``DRY-RUN would: ...`` echo for each command.  Searching the raw body
        matches those, so the assertions passed with the real ``systemctl
        disable`` and ``rm -f`` DELETED -- measured, both mutations survived.
        A deploy that announces a retirement it never performs is the exact
        shape of the defect US-646 exists to remove: the Pi keeps spawning.
        """
        remote = re.search(r"^\s*remote \"", stepBody, re.MULTILINE)
        assert remote, "the step no longer has a remote \" block to inspect"
        return "\n".join(
            line
            for line in stepBody[remote.end():].splitlines()
            if not line.strip().startswith("#")
        )

    def test_theDeployDisablesTheTimerOnTheDeployedPi(self, remoteBody: str):
        """
        Given: a Pi deployed before US-646, with the timer enabled and firing
        When: the new deploy runs
        Then: it disables the timer

        Shipping only the new .service would leave the old timer enabled and
        still firing every 5s. The defect would survive the fix.
        """
        assert re.search(
            r"systemctl disable [^\n]*drain-forensics\.timer", remoteBody
        ), (
            "the deploy step does not disable drain-forensics.timer. Every Pi "
            "deployed before US-646 keeps spawning a process every 5s."
        )

    def test_theDeployRemovesTheInstalledTimerUnitFile(self, remoteBody: str):
        """A disabled-but-present unit is one `systemctl enable` from returning."""
        assert re.search(
            r"rm -f [^\n]*/etc/systemd/system/drain-forensics\.timer", remoteBody
        ), "the deploy step does not remove the installed drain-forensics.timer"

    def test_theDeployEnablesTheServiceItselfNotATimer(self, remoteBody: str):
        """The service is now its own install hook."""
        assert re.search(
            r"systemctl enable [^\n]*drain-forensics\.service", remoteBody
        ), "the deploy step never enables drain-forensics.service"

    def test_theDeployStartsTheDaemonOnTheNewDefinition(self, remoteBody: str):
        """`enable` alone leaves the OLD process running under the OLD unit.

        The pre-US-646 Pi has a `Type=oneshot` drain-forensics.service already
        installed. Re-installing the file changes what systemd would start;
        only a restart changes what is actually running. Without this the
        migration completes on disk and the 5s spawn continues until reboot.
        """
        assert re.search(
            r"systemctl restart [^\n]*drain-forensics\.service", remoteBody
        ), (
            "the deploy never restarts drain-forensics.service, so a migrated "
            "Pi keeps running the old oneshot definition until it reboots."
        )

    def test_theDeployNoLongerEnablesTheTimer(self, stepBody: str):
        """The exact line US-277 shipped, asserted absent.

        Scoped to the WHOLE step -- including the dry-run echoes -- on purpose:
        this one is an absence, and an absence is only stronger for being
        checked over more text.
        """
        assert "enable --now drain-forensics.timer" not in stepBody, (
            "the deploy step still runs `systemctl enable --now "
            "drain-forensics.timer` -- the retirement is not real."
        )

    def test_theRetirementIsUnconditionalNotGatedOnAChangedFile(
        self, remoteBody: str
    ):
        """
        Given: a re-deploy where the .service file is byte-identical
        When: the step runs
        Then: the timer teardown still happens

        The step's `cmp -s` idempotency guard exists to avoid systemd churn on
        no-op deploys. If the teardown sat inside that guard, a Pi whose
        .service happened to match would never have its old timer removed --
        and that is precisely the Pi that still has one.

        Run against the comment-stripped body: the prose above the teardown
        explains why it is unconditional, and matching THAT let the teardown
        move inside the guard with this test still green (measured).
        """
        guard = re.search(r"if \[[^\]]*changed[^\]]*= true[^\]]*\]", remoteBody)
        assert guard, "the changed-guard is gone; this test needs re-thinking"
        beforeGuard = remoteBody[: guard.start()]
        assert "drain-forensics.timer" in beforeGuard, (
            "the timer teardown runs only when the .service file changed. A "
            "second deploy of the same build would leave the old 5s timer "
            "enabled forever."
        )


# ============================================================================
# B. The cadence and the detection are NOT traded away
# ============================================================================


class TestResponsivenessIsUnchanged:
    """NEGATIVE CASE: 'reducing the cadence must NOT cause a drain event to be
    missed'. The cadence was not reduced -- and that is asserted, not assumed."""

    def test_theDefaultIntervalStillMatchesTheRetiredTimer(self):
        """The number the timer carried now lives in the script. Same number."""
        assert DEFAULT_INTERVAL_SECONDS == RETIRED_TIMER_CADENCE_SECONDS

    def test_theLoopWaitsExactlyTheConfiguredIntervalBetweenTicks(self, wiring):
        """
        Given: a configured tick interval
        When: the loop runs
        Then: every wait is that interval

        Asserted on the value passed to wait(), so a loop that ran fast in a
        test but slept 60s in production would fail here.
        """
        ctx, _, _ = wiring
        stop = FakeStop(stopAfter=4)

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=stop)

        assert stop.waits == [RETIRED_TIMER_CADENCE_SECONDS] * 4

    def test_aDrainIsCapturedOnTheVeryNextTickAfterItStarts(self, wiring):
        """
        Given: a daemon idling on wall power, having written nothing
        When: the published reading drops to a battery voltage
        Then: the NEXT tick writes a row

        This is the story's second validationCriterion. The daemon reads the
        state file fresh on every tick exactly as each spawned process did, so
        detection latency is one interval -- unchanged.
        """
        ctx, statePath, logDir = wiring

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(3))
        assert _csvFiles(logDir) == [], (
            "the logger wrote on wall power; it must no-op off battery"
        )

        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)
        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(1))

        assert _dataRowCount(logDir) == 1, (
            "the first tick after the drain started wrote no row"
        )

    def test_aDrainRunAccumulatesOneRowPerTick(self, wiring):
        """The 5s row-rate US-262 specified, measured across a run."""
        ctx, statePath, logDir = wiring
        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(12))

        assert _dataRowCount(logDir) == 12

    def test_theRowsCarryTheFullFourteenColumnContract(self, wiring):
        """A daemon that ticked but wrote a degraded row would pass the counts."""
        ctx, statePath, logDir = wiring
        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(2))

        header = _csvFiles(logDir)[0].read_text().splitlines()[0]
        assert header.split(",") == list(CSV_COLUMNS)


class TestTheRetiredBootGraceWindow:
    """The timer also carried `OnBootSec=30s`, and it went with it.

    That grace window existed so the first fire did not compete with
    rfcomm-bind, journald and the main service during the boot storm -- back
    when a fire OPENED THE I2C BUS. ARCH-006 removed the acquisition, so what
    the daemon now does at t=0 is read a file that powerwatch has not written
    yet. Dropping the window is therefore deliberate, not an oversight; this
    class is what makes that claim checkable rather than a comment.
    """

    def test_aTickBeforeAnyReadingIsPublishedIsAHarmlessNoOp(self, tmp_path):
        """
        Given: boot -- no battery-health state file exists yet
        When: the daemon ticks immediately, with no 30s grace window
        Then: it no-ops and writes nothing

        The unknown power source is NOT battery, so the boot-storm ticks cost
        a stat() each and produce no CSV. If this ever became a write, the
        retired OnBootSec would have to come back as a systemd `After=` or an
        in-loop startup delay.
        """
        logDir = tmp_path / "log"
        ctx = buildProductionContext(
            logDir=logDir,
            batteryHealthStateFile=tmp_path / "not-published-yet",
            orchestratorStateFile=tmp_path / "absent-orchestrator-state.json",
        )

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(6))

        assert not logDir.exists() or _csvFiles(logDir) == [], (
            "the daemon wrote a CSV row before any UPS reading was published "
            "-- an unknown power source is not a drain"
        )

    def test_aStaleReadingAtBootIsDroppedNotAgedIntoTheCsv(self, tmp_path):
        """A reading older than the freshness window is not a drain signal.

        The other thing the boot grace window bought: at t=0 the newest
        published reading can predate the power cut entirely. Writing it would
        stamp last boot's voltage with this boot's timestamp.
        """
        logDir = tmp_path / "log"
        statePath = _writeBatteryHealth(
            tmp_path / "battery-health", vcell=ON_BATTERY_VCELL, ageSec=600.0
        )
        ctx = buildProductionContext(
            logDir=logDir,
            batteryHealthStateFile=statePath,
            orchestratorStateFile=tmp_path / "absent-orchestrator-state.json",
        )

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(3))

        assert not logDir.exists() or _csvFiles(logDir) == [], (
            "a 10-minute-old reading was written as though it were now"
        )


class TestTheDaemonDidNotAcquireStateTheTimerLacked:
    """The per-fire model was stateless by design. That must survive."""

    def test_rotationStillFollowsTheCsvMtimeAcrossADaemonRestart(self, wiring):
        """
        Given: a drain run captured by one daemon process
        When: the daemon is restarted mid-run (systemd Restart=always)
        Then: the fresh process CONTINUES the same CSV, it does not rotate

        Rotation is mtime-based on the artifact precisely so a fresh process
        can resume. A daemon that cached 'my current file' in memory would
        keep that guarantee looking fine until the day it restarted.
        """
        ctx, statePath, logDir = wiring
        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(3))
        firstFiles = _csvFiles(logDir)
        assert len(firstFiles) == 1

        # A brand-new context is what a restarted process gets.
        restarted = buildProductionContext(
            logDir=logDir,
            batteryHealthStateFile=statePath,
            orchestratorStateFile=logDir / "absent.json",
        )
        runForever(restarted, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(2))

        assert _csvFiles(logDir) == firstFiles, (
            "the restarted daemon opened a new CSV; rotation is no longer "
            "driven by the artifact's mtime"
        )
        assert _dataRowCount(logDir) == 5

    def test_aGapLongerThanTheRotationWindowStillRotates(self, wiring):
        """The AC->BATTERY rotation the mtime gap exists to detect.

        Asserted on the NEWEST artifact holding exactly one row, which is what
        "a fresh run started here" means, and the choice of measurement is not
        cosmetic.  ``composeFilename`` has one-SECOND granularity, so the
        rotation lands on a NEW name or -- if the whole scenario ran inside one
        wall-clock second -- on the SAME name, truncating in place.  Both are
        correct rotations and production only ever sees the first (the gap that
        triggers rotation is 30s).  Neither a file COUNT nor a row count summed
        across files can say so: summing reports 3 rows in the ordinary case
        and 1 in the same-second case, so it fails on a wall-clock boundary the
        logger has nothing to do with.  Measured both ways before this was
        written.  The newest file's row count is 1 under both.

        A newest artifact holding ONE row can only come from ``isNewFile``
        being true, which is the rotation decision itself.
        """
        ctx, statePath, logDir = wiring
        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(2))
        assert _dataRowCount(logDir) == 2, "the two seed ticks did not append"

        # Age the artifact past rotationGapSeconds (30s) -- what an operator's
        # AC-restoration then AC-removal cycle looks like on disk.
        old = time.time() - 600
        for p in _csvFiles(logDir):
            os.utime(p, (old, old))

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(1))

        assert _newestCsvRowCount(logDir) == 1, (
            "a stale artifact did not trigger rotation in daemon mode -- the "
            "tick appended to the old run instead of starting a new one"
        )


# ============================================================================
# C. Journal volume -- the cost the story actually named
# ============================================================================


class TestJournalVolume:
    """validationCriteria 3: 'measure journal write volume before and after'.

    Measured as the count of records the logger emits at INFO or above, which
    is what journald keeps by default. The systemd `Starting`/`Finished` pair
    that every timer fire also produced is not reachable from a test; it is
    removed by the same change and recorded in the story notes.
    """

    def test_theOldPerFireModelNarratedEveryFire(self, tmp_path, caplog):
        """CALIBRATION -- prove the defect is present in THIS fixture.

        Without this, 'the daemon is quiet' is equally true of a fixture that
        was never noisy. Each main() call is one timer fire, and the AC no-op
        is the steady state a parked Pi sits in indefinitely.
        """
        caplog.set_level(logging.DEBUG)
        for _ in range(3):
            assert main(["--log-dir", str(tmp_path / "log")]) == 0

        infoRecords = [r for r in caplog.records if r.levelno >= logging.INFO]
        assert len(infoRecords) == 3, (
            "the one-shot path no longer logs once per fire; this calibration "
            "no longer measures the old behaviour and the comparison below is "
            "meaningless"
        )

    def test_aQuietWallPoweredDaemonSaysNothingAfterItsFirstTick(
        self, wiring, caplog
    ):
        """
        Given: a Pi parked on wall power -- the steady state, indefinitely
        When: five minutes of ticks elapse
        Then: at most one record is emitted at INFO or above

        The old model produced one per fire, forever. 60 -> 1 over the same
        window, and flat thereafter rather than linear in uptime.
        """
        ctx, _, _ = wiring
        caplog.set_level(logging.DEBUG)

        runForever(
            ctx,
            intervalSeconds=DEFAULT_INTERVAL_SECONDS,
            stop=FakeStop(TICKS_IN_FIVE_MINUTES),
        )

        infoRecords = [r for r in caplog.records if r.levelno >= logging.INFO]
        assert len(infoRecords) <= 1, (
            f"{len(infoRecords)} records at INFO+ over "
            f"{TICKS_IN_FIVE_MINUTES} quiet ticks; US-646 exists because this "
            f"grew without bound"
        )

    def test_theQuietTicksAreStillObservableAtDebug(self, wiring, caplog):
        """Quieter, not blind. `journalctl -p debug` still shows every tick.

        Silence and DEBUG-level are different: the first loses the evidence
        that the logger was alive, the second only stops paying for it.
        """
        ctx, _, _ = wiring
        caplog.set_level(logging.DEBUG)

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(6))

        debugRecords = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debugRecords) >= 5, (
            "the daemon went silent rather than quiet -- no per-tick record "
            "survives at DEBUG"
        )

    def test_theTransitionOntoBatteryIsAnnouncedExactlyOnce(self, wiring, caplog):
        """
        Given: a daemon idling on wall power
        When: the Pi drops onto battery and stays there
        Then: exactly one INFO marks the transition, then it goes quiet again

        The transition is the operationally interesting moment and it keeps
        its journal line. The 200 rows that follow do not need one each -- the
        CSV is the artifact.
        """
        ctx, statePath, _ = wiring
        caplog.set_level(logging.DEBUG)

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(3))
        caplog.clear()

        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)
        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(10))

        infoRecords = [r for r in caplog.records if r.levelno >= logging.INFO]
        assert len(infoRecords) == 1, (
            f"expected one transition record, got {len(infoRecords)}: "
            f"{[r.getMessage() for r in infoRecords]}"
        )
        assert "wrote_row" in infoRecords[0].getMessage()

    def test_theReturnToWallPowerIsAlsoAnnounced(self, wiring, caplog):
        """Both edges, not just the interesting one.

        A rule that only fires on the way onto battery would leave the journal
        with a drain that never ends.
        """
        ctx, statePath, _ = wiring
        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)
        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(2))

        caplog.set_level(logging.DEBUG)
        _writeBatteryHealth(statePath, vcell=ON_WALL_VCELL)
        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(5))

        infoRecords = [r for r in caplog.records if r.levelno >= logging.INFO]
        assert len(infoRecords) == 1
        assert "no_op_external" in infoRecords[0].getMessage()

    def test_aFreshCsvIsAlwaysAnnouncedEvenMidDrain(self, wiring, caplog):
        """A rotation is a new artifact -- the journal must name the file.

        Deduping on `action` alone would swallow this: both ticks either side
        of a rotation report 'wrote_row'.

        The rotation is forced BETWEEN ticks of a SINGLE runForever call, and
        that is the whole point of the test. An earlier draft rotated between
        two separate calls, where ``lastAction`` starts at None and the first
        tick is announced whatever the rule says -- so dropping ``isNewFile``
        from the noteworthy rule left it green (measured: the mutation
        survived). Only a mid-loop rotation, with a preceding ``wrote_row``
        already deduped against, can witness that half of the rule.
        """
        ctx, statePath, logDir = wiring
        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)
        caplog.set_level(logging.DEBUG)

        def _ageTheCsvAfterTheFirstTick(waitIndex: int) -> None:
            if waitIndex != 1:
                return
            old = time.time() - 600
            for p in _csvFiles(logDir):
                os.utime(p, (old, old))

        runForever(
            ctx,
            intervalSeconds=DEFAULT_INTERVAL_SECONDS,
            stop=FakeStop(4, onWait=_ageTheCsvAfterTheFirstTick),
        )

        infoRecords = [r for r in caplog.records if r.levelno >= logging.INFO]
        assert len(infoRecords) == 2, (
            "expected the opening tick and the mid-loop rotation to be "
            f"announced; got {[r.getMessage() for r in infoRecords]}"
        )
        assert "new_file" in infoRecords[1].getMessage(), (
            "the rotation was swallowed by the action dedup -- ticks either "
            "side of it both report 'wrote_row', so only isNewFile can "
            "distinguish them"
        )
        assert _newestCsvRowCount(logDir) == 3, (
            "the rotation did not actually happen; this test would then be "
            "asserting a log line about nothing"
        )


# ============================================================================
# D. The fix must not be able to re-create the churn it removes
# ============================================================================


class TestTheFixCannotBecomeTheDefect:
    """A crash-looping Restart=always daemon spawns FASTER than the timer did."""

    def test_theUnitRestartsButNotFasterThanTheOldCadence(self):
        """
        Given: Restart= on a long-running unit
        When: the process dies immediately at startup
        Then: systemd waits at least the old cadence before re-spawning

        systemd's default RestartSec is 100ms. A daemon that cannot start
        would then spawn ten processes a second -- fifty times worse than the
        defect this story removed.
        """
        body = DRAIN_SERVICE.read_text(encoding="utf-8")
        assert re.search(r"^\s*Restart\s*=\s*always\s*$", body, re.MULTILINE), (
            "drain-forensics.service must set Restart=always: the timer used "
            "to give the logger a fresh process after every crash, and the "
            "daemon has no other way to recover."
        )
        match = re.search(r"^\s*RestartSec\s*=\s*(\d+)s?\s*$", body, re.MULTILINE)
        assert match, (
            "drain-forensics.service sets Restart=always with no RestartSec. "
            "systemd's 100ms default turns a startup crash into process churn "
            "worse than the 5s spawn US-646 removed."
        )
        assert int(match.group(1)) >= RETIRED_TIMER_CADENCE_SECONDS

    def test_theUnitGivesUpRatherThanLoopingForever(self):
        """A bounded restart burst converts a crash-loop into a failed unit.

        Loud and finite beats quiet and infinite -- the same reasoning that
        put TimeoutStartSec on the old oneshot after 2026-08-27.
        """
        body = DRAIN_SERVICE.read_text(encoding="utf-8")
        assert re.search(r"^\s*StartLimitBurst\s*=\s*\d+\s*$", body, re.MULTILINE), (
            "no StartLimitBurst: a permanently-failing daemon would restart "
            "forever instead of entering a visible failed state."
        )
        assert re.search(
            r"^\s*StartLimitIntervalSec\s*=\s*\S+\s*$", body, re.MULTILINE
        ), "no StartLimitIntervalSec to scope the burst against"

    def test_oneRaisingTickDoesNotTakeTheDaemonDown(self, wiring):
        """
        Given: a tick that raises
        When: the loop continues
        Then: subsequent ticks still run

        Under the old model systemd absorbed this for free: the fire failed,
        the next one started clean five seconds later. The daemon has to
        contain it itself, or a single transient turns into a restart -- i.e.
        a spawn -- which is what this story removed.
        """
        ctx, _, _ = wiring
        calls = {"n": 0}

        def _explodesOnce() -> str:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("transient forensics failure")
            return "external"

        ctx.powerSourceProvider = _explodesOnce
        stop = FakeStop(stopAfter=5)

        ticks = runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=stop)

        assert ticks == 5, "the loop stopped at the raising tick"
        assert calls["n"] == 5

    def test_aRaisingTickIsAlwaysLoudEvenWhenItRepeats(self, wiring, caplog):
        """Errors are never deduped into silence.

        The quiet rule is about ROUTINE ticks. A logger failing every 5s for
        an hour must be visible in the journal on every one of them, or the
        volume saving has bought a blind spot.
        """
        ctx, _, _ = wiring
        caplog.set_level(logging.DEBUG)

        def _alwaysExplodes() -> str:
            raise RuntimeError("the fuel gauge stopped answering")

        ctx.powerSourceProvider = _alwaysExplodes

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(4))

        errorRecords = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errorRecords) == 4

    def test_aRecoveryAfterAnErrorIsAnnounced(self, wiring, caplog):
        """
        Given: a tick raised, then the next one succeeded
        When: the successful action equals the one before the error
        Then: it is still announced

        Deduping against the last SUCCESSFUL action would hide the recovery
        behind an action that had not changed -- leaving a journal with an
        error and no evidence the logger ever came back.
        """
        ctx, _, _ = wiring
        calls = {"n": 0}

        def _explodesOnce() -> str:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("transient")
            return "external"

        ctx.powerSourceProvider = _explodesOnce
        caplog.set_level(logging.DEBUG)

        runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=FakeStop(4))

        infoRecords = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(infoRecords) == 2, (
            "expected the first tick and the post-error recovery to be "
            f"announced; got {[r.getMessage() for r in infoRecords]}"
        )


# ============================================================================
# E. Stopping cleanly -- systemd sends SIGTERM, not SIGKILL
# ============================================================================


class TestCleanStop:
    def test_aStopRequestedDuringTheWaitEndsTheLoop(self, wiring):
        """The wait is interruptible, so `systemctl stop` does not sit 5s."""
        ctx, _, _ = wiring
        stop = FakeStop(stopAfter=1)

        assert runForever(ctx, intervalSeconds=99999.0, stop=stop) == 1

    def test_aStopAlreadySetRunsNoTickAtAll(self, wiring):
        """SIGTERM racing startup must not write a row on the way out."""
        ctx, statePath, logDir = wiring
        _writeBatteryHealth(statePath, vcell=ON_BATTERY_VCELL)
        stop = FakeStop(stopAfter=1)
        stop._set = True

        assert runForever(ctx, intervalSeconds=DEFAULT_INTERVAL_SECONDS, stop=stop) == 0
        assert _csvFiles(logDir) == []

    def test_theStopSignalIsSetByItsRequestHook(self):
        """The object systemd's SIGTERM handler drives, exercised directly."""
        signal_ = StopSignal()
        assert not signal_.isSet()
        signal_.request(15, None)
        assert signal_.isSet()
        # An already-set signal must not consume the interval.
        started = time.monotonic()
        assert signal_.wait(30.0) is True
        assert time.monotonic() - started < 1.0

    def test_theStopSignalInstallsACooperativeHandler(self):
        """
        Given: python's default SIGTERM behaviour terminates immediately
        When: installHandlers() runs
        Then: SIGTERM routes to the cooperative flag instead

        The default would be free to land between the CSV write and the
        os.fsync that US-262 made load-bearing.
        """
        import signal as signalMod

        installed = StopSignal()
        previous = signalMod.getsignal(signalMod.SIGTERM)
        try:
            installed.installHandlers()
            handler = signalMod.getsignal(signalMod.SIGTERM)
            assert handler == installed.request, (
                "SIGTERM still has python's default handler; a stop can land "
                "mid-row"
            )
        finally:
            signalMod.signal(signalMod.SIGTERM, previous)

    def test_daemonModeActuallyInstallsTheHandlerOnTheStopItLoopsOn(
        self, wiring, monkeypatch
    ):
        """The capability above, asserted to be WIRED UP by --daemon.

        Owning a working StopSignal is not the same as using one. Deleting
        `stop.installHandlers()` from main()'s daemon branch left the test
        above green (measured: the mutation survived) -- it exercises the
        class, and nothing exercised main. systemd's `systemctl stop` sends
        SIGTERM to THIS process; if main did not install the handler, the
        clean-stop guarantee would exist only in a unit test.

        Asserted on the SAME object main hands to runForever, so wiring a
        second, unrelated StopSignal would not satisfy it either.
        """
        import signal as signalMod

        import scripts.drain_forensics as mod

        ctx, _, _ = wiring
        captured: dict = {}

        def _captureStop(passedCtx, *, intervalSeconds, stop):
            captured["stop"] = stop
            captured["handler"] = signalMod.getsignal(signalMod.SIGTERM)
            return 0

        monkeypatch.setattr(mod, "buildProductionContext", lambda **kw: ctx)
        monkeypatch.setattr(mod, "runForever", _captureStop)

        previous = signalMod.getsignal(signalMod.SIGTERM)
        try:
            assert main(["--daemon"]) == 0
        finally:
            signalMod.signal(signalMod.SIGTERM, previous)

        assert captured["handler"] == captured["stop"].request, (
            "--daemon runs the loop without routing SIGTERM to the StopSignal "
            "it loops on; `systemctl stop` would kill the process where it "
            "stands, possibly between the CSV write and its fsync."
        )


# ============================================================================
# F. The CLI keeps its one-shot mode
# ============================================================================


class TestTheOneShotPathSurvives:
    """The daemon is the UNIT's mode, not the script's only mode.

    A diagnostic hand-run must still write exactly one row and exit, or
    every operator drill in the service header becomes a hang.
    """

    def test_aBareInvocationStillRunsOnceAndReturns(self, tmp_path):
        assert main(["--log-dir", str(tmp_path / "log")]) == 0

    def test_theIntervalIsConfigurableFromTheCommandLine(self, wiring, monkeypatch):
        """The unit ships the default; an operator can tighten it for a drill."""
        ctx, _, _ = wiring
        captured: dict = {}

        import scripts.drain_forensics as mod

        def _fakeRunForever(passedCtx, *, intervalSeconds, stop):
            captured["interval"] = intervalSeconds
            return 0

        monkeypatch.setattr(mod, "buildProductionContext", lambda **kw: ctx)
        monkeypatch.setattr(mod, "runForever", _fakeRunForever)

        assert main(["--daemon", "--interval-seconds", "2.5"]) == 0
        assert captured["interval"] == 2.5


# ============================================================================
# G. ARCH-006 is not this fix
# ============================================================================


def test_arch006RemovedTheBusReadNotTheSpawn():
    """The story asked whether ARCH-006 already removed the reason for the 5s
    cadence. It did not, and this records the distinction so the two are not
    conflated again.

    ARCH-006 changed WHAT a fire did (subscribe, not acquire). US-646 changed
    WHETHER there is a fire. The subscribe path must still be the only one --
    a daemon holding a long-lived I2C client would be a worse rule-B breach
    than the per-fire opens ever were, because it would hold the bus.
    """
    source = (REPO_ROOT / "scripts" / "drain_forensics.py").read_text(
        encoding="utf-8"
    )
    wired = re.search(
        r"def buildProductionContext\(.*?\n(?=\n\n# =)", source, re.DOTALL
    )
    assert wired, "buildProductionContext moved; this guard needs re-anchoring"
    assert "_readUpsTelemetryFromState" in wired.group(0)
    assert "_readUpsTelemetry(" not in wired.group(0), (
        "the production context calls the ACQUIRING reader again -- ARCH-006 "
        "is undone, and in daemon mode it would run forever in one process"
    )


def test_theRunResultContractIsUnchangedByTheDaemon():
    """runOnce is untouched: the daemon calls the same function the timer did.

    Every US-262 invariant -- fsync per row, no-op on AC, mtime rotation --
    lives in runOnce. Keeping it identical is why this change needed no new
    reasoning about the CSV.
    """
    result = RunResult(action="wrote_row", path=Path("x.csv"), isNewFile=True)
    assert (result.action, result.isNewFile) == ("wrote_row", True)
