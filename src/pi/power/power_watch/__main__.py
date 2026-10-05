################################################################################
# File Name: __main__.py
# Purpose/Description: Phase-2 power-watch service entrypoint
#                      (`python -m src.pi.power.power_watch`). Wires the
#                      PowerSourceProvider SSOT (X1209 GPIO6 PLD) as the
#                      trigger, the documented pre-shutdown sync
#                      (SyncClient.forcePush), and the home-network reachability
#                      probe into the bounded ShutdownSequencer (renamed from
#                      PowerWatch in SS-T5), then blocks on the GPIO6 watch
#                      loop. Battery-health VCELL backstop is the UpsMonitor's
#                      role only (post-SS-T4, getPowerSource is a tripwire).
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T6 service entrypoint + real wiring.
# 2026-05-19    | Plan SS-T5 | Wired PowerSourceProvider SSOT as the trigger
#                              (isOnBattery=provider.isPowerLost, the boot-grace
#                              watch loop reads through the SAME provider --
#                              one acquisition site, criterion #3). Renamed
#                              local class refs PowerWatch -> ShutdownSequencer
#                              + confirm*->smoothing* config reads. Arm check
#                              goes through provider.startupArmCheck().
# 2026-05-20    | US-344 F-7  | Sprint 40 / V0.27.16 boot-grace latch fix.
#                              Extracted _pldWatchLoop closure into module-level
#                              _runPldWatchLoop with injected isPowerLostFn /
#                              stop / monotonicFn for unit-testability. Replaced
#                              edge-only post-boot-grace trigger (lost AND not
#                              prevLost) with level-based check (lost AND not
#                              firedAlready). An in-grace transient that leaves
#                              the HAT latched LOW therefore re-fires correctly
#                              the first post-grace tick instead of latching
#                              the sequencer blind for the rest of the boot --
#                              the bug bound (cold-start + in-grace transient +
#                              no alternator recovery before key-off) reproduced
#                              live in-car 2026-05-20 (Atlas + CIO Test 2). The
#                              smoothing path (handleOnBattery internal VCELL
#                              averaging) remains the abort surface for
#                              transients that resolve mid-window; GPIO6
#                              acquisition + boot-grace duration + EEPROM
#                              POWER_OFF_ON_HALT=1 are all unchanged. See
#                              offices/architect/findings/2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md.
# 2026-08-21    | US-566  | Sprint 75 / V0.29.30 arm-decision observability.
#                           MEASURED on chi-eclipse-01 2026-08-21: across 8
#                           service starts the journal holds ZERO
#                           "powerwatch service up" lines, while WARNING lines
#                           from the SAME pids are present throughout. The
#                           story's premise ("emits zero application log
#                           lines") is therefore too broad -- WARNING+ has
#                           always worked. The real defect: this module never
#                           configured logging, so logging.lastResort (level
#                           WARNING, stderr) was the only sink and the ENTIRE
#                           INFO TIER was discarded. The arm-success line was
#                           INFO, so it never appeared; the arm-failure line
#                           is ERROR, so it would have appeared -- it has just
#                           never fired. Absence of the ERROR was thus
#                           indistinguishable from "logging is broken", which
#                           is exactly why nobody could tell whether safety
#                           armed. Fixes: (1) main() installs the project
#                           logging config, (2) the arm decision is emitted
#                           unconditionally on BOTH branches at WARNING/ERROR
#                           behind one greppable prefix, (3) the disarmed hold
#                           re-states its cause instead of falling silent
#                           forever. OBSERVABILITY ONLY -- not the GPIO6
#                           single-ownership refactor (Atlas SPEC 2, deferred)
#                           and not the X1209 hold-up path (CIO hardware).
# 2026-08-29    | US-621  | Sprint 77 / V0.29.34 shutdown sync CUSTODY.
#                           PREMISE CORRECTION, MEASURED: the story states "no
#                           shutdown stage attempts a final drain", citing a
#                           NON-RECURSIVE grep of src/pi/power/*.py. A drain
#                           does exist -- SyncWithServerTask -> forcePush, one
#                           directory down and wired here since P2-T6. The real
#                           defect is narrower and worse: forcePush moves at
#                           most pi.companionService.batchSize (500) rows PER
#                           TABLE PER CALL, so ONE pass against the observed
#                           ~15,000-row backlog returned OK -- "sync succeeded"
#                           -- with ~14,500 rows still on the Pi. A confident
#                           wrong answer, not a missing one.
#                           Fixes: (1) _buildRunSync drains in repeated passes,
#                           bounded by MEASURED pass duration against the
#                           existing perTaskTimeoutSec (no new tunable), always
#                           making at least one pass so it cannot regress below
#                           the previous behaviour; (2) a pre-poweroff custody
#                           record states DELIVERED / OUTSTANDING / UNKNOWN on
#                           EVERY poweroff path -- including the VCELL-floor
#                           fast path that skips the pipeline entirely, which is
#                           why it is a prePowerOffFn hook and not a
#                           ShutdownTask (the US-526 Option C argument, applied
#                           to sync custody); (3) composePrePowerOffHooks
#                           isolates each hook so a failing US-526 drain close
#                           cannot silently delete the custody record.
# 2026-09-13    | US-666  | Sprint 85 / V0.29.48. The startup check proves the
#                           PLD pin READS, never that it CHANGES, so a readable
#                           pin with no witnessed transition now logs
#                           ARM_DECISION_UNVERIFIED ("PIN READABLE, TRANSITION
#                           UNVERIFIED"), not ARMED (UNPROVEN). The read is named
#                           a readability check, not an "arm self-check PASSED".
#                           The PROVEN line says its proof is a PRIOR run's
#                           witness and that the line prints at every start.
#                           Wording only: the armed/not-armed disposition and
#                           the watch loop are unchanged.
# 2026-09-14    | US-748  | Sprint 86 / V0.29.50. Wires the 1 Hz power-loss
#                           heartbeat (loss_heartbeat.py) into the sequencer's
#                           powerLossObservedFn, and reports the previous loss's
#                           surviving rows at every start (LOSS HEARTBEAT line),
#                           so time-to-death after a cut is read from SQLite
#                           instead of inferred from a journal that cannot see
#                           the last seconds. No trigger, budget or poweroff
#                           change.
# 2026-09-17    | US-788  | Sprint 89 / V0.29.57. bootGrace stops gating the
#                           TRIGGER: an in-grace PLD loss (edge) now calls
#                           handleOnBattery(suppressFloorFastPath=True), so the
#                           shed, heartbeat, smoothing, pipeline and graceful
#                           poweroff all run. Post-grace branch unchanged. No
#                           constant changed.
# 2026-09-17    | US-789  | Sprint 89 / V0.29.57. The drain close records the
#                           drain_event_id it wrote in an OwnDrainCloseSlot; the
#                           custody hook excludes that ONE row from its verdict
#                           and reports it beside it. The close does not move;
#                           hook isolation is unchanged.
# 2026-09-17    | US-776-a  | Sprint 89 / V0.29.57. The drain is bounded by the
#                           battery, not by three timers: _buildRunSync loses its
#                           budgetSec pass-fitting bound and pushes until the
#                           shared backlog reader reads 0; runPipeline joins the
#                           sync task without perTaskTimeoutSec (never
#                           abandoned); the sequencer polls the VCELL floor
#                           instead of waiting totalWindowCapSec.
# 2026-09-21    | US-796-a  | Sprint 90 / V0.29.59. The default shed set gained
#                           splash-grace.path + splash-grace.service. REVERSED
#                           by US-796 (Sprint 95): the stop failed on every cut
#                           and the CIO kept the animation, so the shed set no
#                           longer names a splash unit.
# 2026-09-25    | US-790  | Sprint 94. The sequencer feeds a
#                           DrainVcellTrajectoryWriter (one row per drain poll,
#                           stamped with pi.power.cellEpoch); the ids it commits
#                           form an OwnTrajectoryRows set that the drain's exit
#                           check and custody both exclude.
# 2026-10-01    | US-776-c  | Sprint 95. The sync task is gated on
#                           detector.getHomeNetworkState, not on one
#                           isServerReachable probe: a positive AWAY skips with
#                           no wait; AT_HOME_* drains; UNKNOWN (a dead SSID/IP
#                           reader) drains as UNKNOWN_NETWORK at WARNING.
# 2026-10-01    | US-776-g  | Sprint 95. The sync task gets
#                           pi.homeNetwork.shutdownSyncCeilingSec: a transient
#                           failure is retried with backoff until the ceiling.
#                           PW_TEST_ONESHOT walks it on a virtual clock.
# 2026-10-01    | US-776-d  | Sprint 95. makeOutcomeSink: every sync run writes
#                           one durable record (sync_outcome + backlog_start/end
#                           from the shared US-621 reader); the task reads the
#                           detector's lastProbe to tell a misconfigured probe
#                           from a down server.
# 2026-10-01    | US-741    | Sprint 95. HomeStateAtLoss: every power loss asks
#                           the detector once (its own thread, started by the
#                           loss hook) and persists the state name into the
#                           durable shutdown record; the sync task reuses that
#                           answer, and the floor fast path records UNKNOWN
#                           rather than wait for it.
# 2026-10-03    | Atlas (ARCH-065a) | Drain writer built with cellEpoch from pi.power.cellEpoch.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T3: the sync task takes joinWaitSec + stallSec
#                           (pi.homeNetwork) in place of shutdownSyncCeilingSec.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T2: WallVcellCache (15 s max age) fed from the
#                           UpsMonitor poll while the PLD reads present (PLD loop
#                           stays GPIO-only); the outcome sink writes the drain's
#                           start/end and the pre-cut VCELL.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T4: pi.powerWatch.drainFloorDwellReads feeds the
#                           sequencer; a floor-ended drain writes RESERVE_FLOOR
#                           through HomeStateAtLoss.recordFloorEnd (pre-poweroff
#                           hook, before ensureRecorded) and later sync records
#                           for that loss are dropped.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T5: MonthlyTestHoldTask joins buildV1Tasks after
#                           the sync task (sequencer-bounded); HomeStateAtLoss stamps the
#                           loss on the monotonic clock (secondsSinceLoss); cellEpoch via
#                           resolveCellEpoch. Fix round 1: lossIso() (wall stamp) scopes
#                           the monthly-test row mark.
# 2026-10-03    | Atlas (ARCH-065a) | Ruling 19: HomeStateAtLoss.lossGeneration (moves in
#                           observe); wrapSink drops a record of an older loss; the
#                           sync and hold tasks capture it at run start; the hold is
#                           gated on the loss's home state and marks with the lossIso
#                           it snapshotted; recordFloorEnd logs what it overwrites.
# 2026-10-05    | Atlas (US-833) | No poweroff leaves the shutdown-sync record silent:
#                           one serialised sink (syncRecordSink) takes the sync task's
#                           final AND provisional INTERRUPTED records; ensureRecorded
#                           writes INTERRUPTED + the backlog when no sync record exists
#                           (the backstop fast path); recordFloorEnd carries the
#                           provisional's backlog_start / sync_started_at forward.
#                           HomeStateAtLoss takes the task's backlogReader. CIO-directed.
# ================================================================================
################################################################################
"""Phase-2 power-watch service entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

# Resolve project paths relative to this file (NOT cwd) and put BOTH the repo
# root and <repo>/src on sys.path -- the project-wide bare `from pi.X` /
# `from common.X` convention needs <repo>/src; `-m src.pi...` needs the repo
# root. This mirrors src/pi/main.py:46-57 and is the belt to the systemd
# unit's Environment=PYTHONPATH brace (the V0.27.12-DOA lesson).
_srcDir = Path(__file__).resolve().parents[3]
_projectRoot = _srcDir.parent
for _p in (str(_srcDir), str(_projectRoot)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DEFAULT_CONFIG = str(_projectRoot / "config.json")
_DEFAULT_ENV = str(_projectRoot / ".env")

from src.common.config.secrets_loader import (  # noqa: E402
    getSecret,
    loadConfigWithSecrets,
)
from src.common.config.validator import ConfigValidator  # noqa: E402
from src.common.edr.sync_contract import (  # noqa: E402
    EDR_SYNC_TABLES,
    SHUTDOWN_DRAIN_EXCLUDED_TABLES,
)
from src.common.logging.setup import setupLogging  # noqa: E402
from src.common.time.helper import utcIsoNow  # noqa: E402
from src.pi.hardware.pld_sensor import PldSensor  # noqa: E402
from src.pi.hardware.ups_monitor import UpsMonitor  # noqa: E402
from src.pi.network.home_detector import (  # noqa: E402
    HomeNetworkDetector,
    HomeNetworkState,
)
from src.pi.power.battery_health import resolveCellEpoch  # noqa: E402
from src.pi.power.drain_event_writer import (  # noqa: E402
    CLOSE_REASON_SHUTDOWN,
    makeDrainEventWriterForPath,
)
from src.pi.power.power_db import DrainVcellTrajectoryWriter  # noqa: E402
from src.pi.power.power_source_provider import PowerSourceProvider  # noqa: E402
from src.pi.power.power_source_pubsub import (  # noqa: E402
    POWER_SOURCE_FILENAME,
    publishPowerSource,
)
from src.pi.power.power_watch.contract import OutcomeKind  # noqa: E402
from src.pi.power.power_watch.controller import ShutdownSequencer  # noqa: E402
from src.pi.power.power_watch.load_shed import (  # noqa: E402
    DEFAULT_SHED_UNITS,
    LoadShedder,
)
from src.pi.power.power_watch.loss_heartbeat import (  # noqa: E402
    LossHeartbeatSummary,
    PowerLossHeartbeat,
    readLatestLossHeartbeat,
)
from src.pi.power.power_watch.outcome import writeOutcomeRecord  # noqa: E402
from src.pi.power.power_watch.pipeline import runPipeline  # noqa: E402
from src.pi.power.power_watch.pld_witness import readWitness  # noqa: E402
from src.pi.power.power_watch.sync_custody import (  # noqa: E402
    CUSTODY_RECORD_FILENAME,
    OwnDrainCloseSlot,
    OwnTrajectoryRows,
    makeSyncCustodyHook,
)
from src.pi.power.power_watch.tasks.monthly_test_hold import (  # noqa: E402
    MonthlyTestHoldTask,
    isMonthlyTestDue,
    markOpenDrainMonthlyTest,
)
from src.pi.power.power_watch.tasks.sync_with_server import (  # noqa: E402
    SyncOutcomeRecord,
    SyncWithServerTask,
)
from src.pi.power.soc_calibration import (  # noqa: E402
    readSystemUptimeSeconds,
    resolveColdStartWindowSeconds,
)
from src.pi.power.types import DRAIN_TERMINATION_DRAIN_FLOOR  # noqa: E402
from src.pi.splash.shutdown_state_emitter import (  # noqa: E402
    makeShutdownPhaseEmitter,
)
from src.pi.sync.backlog import SyncBacklog, countOutstandingRows  # noqa: E402
from src.pi.sync.client import SyncClient  # noqa: E402

logger = logging.getLogger(__name__)

# --- Arm-decision observability (US-566) -------------------------------------
# The arm decision is the single most load-bearing fact this service reports:
# "is safe-shutdown protection ON or OFF?". Until US-566 it was UNFINDABLE, and
# the mechanism was NOT a missing log call -- both branches were already
# unconditional on their branches. This module never configured logging, so
# Python's logging.lastResort handler (level WARNING, stderr) was the only sink
# and the entire INFO tier went on the floor. The success line was INFO
# (invisible); the failure line is ERROR (visible, but it has never fired). So
# silence meant either "armed fine" or "the instrument is broken" and there was
# no way to tell them apart -- the same false-healthy shape US-561 removed from
# the kiosk watchdog one story earlier in this sprint.
#
# Both branches are emitted at WARNING (armed) / ERROR (not-armed), NOT INFO.
# The decision fires EXACTLY ONCE per service start, so severity costs no
# journal volume -- and pinning a safety fact to a tier that a config change
# can silence is precisely how it went missing. Defence in depth: the line
# survives even if logging configuration regresses to lastResort again.
#
# Both branches carry ARM_DECISION_PREFIX, so ONE grep answers the question:
#   journalctl -u eclipse-powerwatch.service --grep='ARM DECISION'
ARM_DECISION_PREFIX = "powerwatch: ARM DECISION ="
ARM_DECISION_ARMED = "ARMED"
ARM_DECISION_NOT_ARMED = "NOT-ARMED"
# US-666: the verdict for a pin that READS but has never been seen to CHANGE.
# A stuck pin gives the startup check the same single reading as a live one,
# so readability alone must not earn ARMED. The watch still runs.
ARM_DECISION_UNVERIFIED = "PIN READABLE, TRANSITION UNVERIFIED"

# A disarmed service is `systemctl is-active` == active and otherwise silent --
# indistinguishable from a healthy armed one. Announcing the refusal once at
# boot is not enough: that line ages out of the journal and leaves a
# green-looking unit that will never power anything off. Re-state on an
# interval instead. 300s is a named constant rather than a config key because
# it is a log cadence on a path that should never be taken, not a tunable.
DISARMED_RESTATE_SEC = 300.0


def buildArmDecisionMessage(
    *,
    armed: bool,
    pldGpioPin: int,
    pldAvailable: bool,
    readsPowerPresent: bool,
    lastTransitionUtc: str | None = None,
) -> str:
    """Compose the one arm-decision line for either branch.

    A SINGLE formatting site for both dispositions, so the two can never drift
    apart in wording or in the evidence they carry. Each line states what was
    MEASURED (pin, line readability, the actual reading), not just the verdict:
    a bare "NOT-ARMED" cannot be diagnosed, and a bare "ARMED" is an assertion
    rather than an instrument reading.

    Args:
        armed: The startupArmCheck() result.
        pldGpioPin: The configured X1209 PLD pin (pi.powerWatch.pldGpioPin).
        pldAvailable: Whether the PLD line is readable at all.
        readsPowerPresent: The instantaneous power-present reading.
        lastTransitionUtc: When a PLD transition was last OBSERVED, or None if
            one never has been. ARCH-019: the arm check reads the pin once and
            proves it is READABLE. It does not prove the pin CHANGES, and a
            signal that reads but has never been seen to move is
            indistinguishable from a wire that is not connected. So the ARMED
            line only PREDICTS what a power loss will do once a real transition
            has been witnessed; until then it states what it actually verified.
            US-666: without a witness the verdict is ARM_DECISION_UNVERIFIED,
            not ARMED. With one, the line says the proof came from a PRIOR run,
            because this start cannot exercise a power loss in software.

    Returns:
        The exact line to log -- prefixed with ARM_DECISION_PREFIX on both
        branches so one grep finds either.
    """
    evidence = (
        f"gpio={pldGpioPin} pld.available={pldAvailable} reads-power-present={readsPowerPresent}"
    )
    readability = f"GPIO{pldGpioPin} PLD readability check PASSED ({evidence})"
    if armed and lastTransitionUtc:
        return (
            f"{ARM_DECISION_PREFIX} {ARM_DECISION_ARMED} (PROVEN) -- safe-shutdown "
            f"protection is ON and its detection path has been OBSERVED to fire "
            f"(last transition {lastTransitionUtc}, observed on a PRIOR run). "
            f"{readability} -- THIS start verified readability only. This line "
            f"is printed at every start and is not itself a transition event. A "
            f"sustained external-power loss will run the bounded pre-shutdown "
            f"pipeline and then poweroff."
        )
    if armed:
        return (
            f"{ARM_DECISION_PREFIX} {ARM_DECISION_UNVERIFIED} -- safe-shutdown "
            f"protection is UNVERIFIED: the watch is RUNNING, but its detection "
            f"path has NEVER been observed to fire. {readability} -- that proves "
            f"the pin READS, not that it CHANGES. No power-loss transition has "
            f"ever been witnessed on this install, and a pin that reads but has "
            f"never been seen to move is indistinguishable from a wire that is "
            f"not connected."
        )
    return (
        f"{ARM_DECISION_PREFIX} {ARM_DECISION_NOT_ARMED} -- safe-shutdown "
        f"protection is OFF. CAUSE: GPIO{pldGpioPin} PLD SSOT arm self-check "
        f"FAILED ({evidence}). The Pi booted on a live feed so GPIO"
        f"{pldGpioPin} must read power-present at startup; it does not (wrong "
        f"pin/polarity, or the line is unreadable). REFUSING to arm -- service "
        f"stays up disarmed, OBD collector unaffected, NOTHING will be powered "
        f"off. Fix pi.powerWatch.pldGpioPin / pldPowerPresentHigh and redeploy."
    )


def emitArmDecision(
    *,
    armed: bool,
    pldGpioPin: int,
    pldAvailable: bool,
    readsPowerPresent: bool,
    lastTransitionUtc: str | None = None,
) -> str:
    """Emit the arm decision UNCONDITIONALLY, on whichever branch was taken.

    Never silent: there is no input for which this logs nothing. The level is
    chosen by disposition -- WARNING for armed (a once-per-start operational
    fact this module already uses WARNING for elsewhere, e.g. the power-loss
    trigger), ERROR for not-armed (a refusal). Both clear lastResort's WARNING
    floor, so the decision reaches the journal even with no logging
    configuration installed at all.

    Args:
        armed: The startupArmCheck() result.
        pldGpioPin: The configured X1209 PLD pin.
        pldAvailable: Whether the PLD line is readable at all.
        readsPowerPresent: The instantaneous power-present reading.

    Returns:
        The exact line logged, so the caller can re-state it verbatim without
        recomposing it (and without re-reading the hardware to do so).
    """
    message = buildArmDecisionMessage(
        armed=armed,
        pldGpioPin=pldGpioPin,
        pldAvailable=pldAvailable,
        readsPowerPresent=readsPowerPresent,
        lastTransitionUtc=lastTransitionUtc,
    )
    if armed:
        logger.warning(message)
    else:
        logger.error(message)
    return message


def runDisarmedHold(
    *,
    message: str,
    waitFn,
    restateSec: float = DISARMED_RESTATE_SEC,
) -> int:
    """Hold the process alive DISARMED, re-stating the cause on an interval.

    Replaces a bare ``threading.Event().wait()``, which announced the refusal
    once and then went quiet forever -- leaving an `active` unit that looks
    exactly like a healthy armed one. Declining to arm is not a claim that the
    shutdown path is well, so the instrument must keep saying so.

    Args:
        message: The not-armed decision line, re-stated verbatim (never
            recomposed -- one formatting site).
        waitFn: One-arg callable ``(timeoutSec) -> bool``. Production passes
            ``threading.Event().wait``, which never returns True, so the hold
            is permanent. Tests pass a bounded stub.
        restateSec: Seconds between re-statements.

    Returns:
        0 -- reached only if waitFn returns True, which no production caller
        does.
    """
    while not waitFn(restateSec):
        logger.error("%s [STILL NOT-ARMED]", message)
    return 0


def _parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase-2 power-watch service (bounded pre-shutdown pipeline)."
    )
    parser.add_argument("--config", default=_DEFAULT_CONFIG)
    parser.add_argument("--env-file", default=_DEFAULT_ENV)
    return parser.parse_args(argv)


def _buildRunSync(
    syncClient: SyncClient,
    *,
    backlogReader=None,
    excludeTables=(),
):
    """Adapt SyncClient.forcePush() to the SyncWithServerTask runSync contract.

    forcePush() is the documented pre-`systemctl poweroff` flush (US-216): it
    never raises on a sync failure -- it returns a PushSummary. Map it to the
    raise-on-transient contract the task expects:
      * disabled        -> benign no-op (return; nothing to sync)
      * tablesFailed > 0 -> transport failure, retries exhausted -> RuntimeError
                            (TRANSIENT: the task retries with backoff to the
                            ceiling, then records why it failed -- US-776-d)
      * otherwise        -> success (return)
    A non-transport fault (e.g. ConfigurationError, sqlite corruption) raises
    out of forcePush as a non-RuntimeError and propagates -- the task then
    classifies it REAL_ERROR. We deliberately do NOT catch those here.

    US-621 -- MULTI-PASS, AND WHY. One forcePush() is NOT a drained queue: it
    moves at most ``pi.companionService.batchSize`` (500) rows PER TABLE PER
    CALL. Measured against the 2026-08-28 incident, a ~15,000-row backlog needs
    ~30 passes, so the single-pass drain returned OK -- "sync succeeded" -- with
    ~14,500 rows still on the Pi. A confident wrong answer, not merely a
    missing one. This now keeps pushing while rows remain.

    US-776-a -- NO TIME BOUND HERE. The drain makes passes until the backlog
    reader says 0 (the server has ACKNOWLEDGED every drive row), a pass fails
    or moves nothing, or the backlog cannot be read. It used to stop when the
    next pass would not fit ``perTaskTimeoutSec`` (20 s); the CIO ruled the
    drain ends on confirmation or the battery floor, never a timer. The floor
    is enforced by ``ShutdownSequencer``'s poll from ANOTHER thread, which is
    the only place it can be: one pass can block inside forcePush for ~25 min
    and never reach a pass boundary where this loop could check anything.

    Args:
        syncClient: The live SyncClient.
        backlogReader: Zero-arg reader returning a
            :class:`~src.pi.sync.backlog.SyncBacklog`. ``None`` disables
            multi-pass entirely (exactly one pass -- the legacy path).
        excludeTables: Tables the drain must NOT carry (US-766). Production
            passes the EDR set. The drain budget is seconds; the EDR backlog
            was measured at 15.16M rows and grows ~1.77M/day, so a single pass
            over it could not finish and every pass would crowd out the drive
            data this window exists to save. EDR catches up on the next
            ordinary sync tick, where there is no deadline.
            NOTE the backlogReader must exclude the same set, or the loop below
            sees a backlog it is not pushing and keeps spending passes on rows
            that will never move.
    """

    def runSync() -> None:
        passes = 0
        while True:
            summary = syncClient.forcePush(excludeTables=excludeTables)
            passes += 1
            if summary.disabled:
                logger.info("powerwatch sync: companion service disabled -- no-op")
                return
            if summary.tablesFailed > 0:
                raise RuntimeError(f"{summary.tablesFailed} table(s) failed to sync after retries")
            if backlogReader is None:
                return
            backlog = backlogReader()
            if backlog.total <= 0:
                # Either fully delivered, or unreadable -- neither is a reason
                # to keep pushing. UNKNOWN is not "empty", but it is also not
                # evidence that another pass would help. Custody re-reads the
                # SAME reader and records UNKNOWN, never DELIVERED, for the
                # unreadable case.
                logger.info(
                    "powerwatch sync: drain finished after %d pass(es) -- %s",
                    passes,
                    backlog.describe(),
                )
                return
            if summary.rowsPushed <= 0:
                # The queue is not shrinking (quarantined/skipped table). Do
                # not burn the rest of the shutdown window on a no-op.
                logger.warning(
                    "powerwatch sync: drain made NO progress on pass %d with "
                    "%d row(s) outstanding -- stopping rather than spinning",
                    passes,
                    backlog.total,
                )
                return

    return runSync


def composePrePowerOffHooks(*hooks):
    """Compose several pre-poweroff hooks into the sequencer's single slot.

    ``ShutdownSequencer`` guards ``prePowerOffFn`` as ONE unit, so a naive
    ``lambda: (a(), b())`` would let a failing US-526 drain close silently
    delete the US-621 custody record -- one shutdown bug quietly disabling
    another's fix. Each hook is therefore isolated here as well.

    Args:
        *hooks: Zero-arg callables, or ``None`` for an unwired one.

    Returns:
        A single zero-arg callable running every wired hook in order, or
        ``None`` when none are wired (so the sequencer keeps its exact legacy
        path).
    """
    wired = [h for h in hooks if h is not None]
    if not wired:
        return None

    def _runAll() -> None:
        for hook in wired:
            try:
                hook()
            except Exception as exc:  # noqa: BLE001 -- one hook must not eat another
                logger.error(
                    "powerwatch: pre-poweroff hook %r failed (%s) -- ignored, "
                    "remaining hooks still run",
                    getattr(hook, "__name__", hook),
                    exc,
                )

    return _runAll


def buildFloorEndHook(
    lastDrainEndReason: Callable[[], str | None], homeStateAtLoss: HomeStateAtLoss
) -> Callable[[], None]:
    """ARCH-065: pre-poweroff hook -- a drain the reserve floor ended is recorded.

    Runs BEFORE ``ensureRecorded`` so the record says RESERVE_FLOOR, not UNKNOWN
    or a sync outcome. Any other drain end is a no-op.
    """

    def _hook() -> None:
        if lastDrainEndReason() == DRAIN_TERMINATION_DRAIN_FLOOR:
            homeStateAtLoss.recordFloorEnd()

    return _hook


def backlogCount(backlog: SyncBacklog) -> int | None:
    """The count the sync outcome record carries (US-776-d), or None.

    A database that could not be opened, or a table that could not be read,
    makes ``total`` a lower bound; the record then says nothing (it lands
    NULL) rather than a number that looks exact.
    """
    if backlog.error is not None or not backlog.isComplete:
        return None
    return backlog.total


#: ARCH-065: a cached on-wall VCELL older than this reads as absent. 3x the
#: UpsMonitor's 5 s poll, so one missed poll is tolerated and a stale value is not.
WALL_VCELL_MAX_AGE_S = 15.0


class WallVcellCache:
    """ARCH-065: the last VCELL sampled while on wall power (for cut_step_mv).

    Fed from the UpsMonitor's existing poll (``makeWallVcellFeed``), never from
    a new I2C read; read once at the loss. ``last()`` is None when the value is
    older than ``WALL_VCELL_MAX_AGE_S``. Never raises.
    """

    def __init__(self, monotonicFn: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._monotonic = monotonicFn
        self._v: float | None = None
        self._at: float = 0.0

    def update(self, v: float | None) -> None:
        if v is None:
            return
        with self._lock:
            self._v = float(v)
            self._at = self._monotonic()

    def last(self) -> float | None:
        with self._lock:
            if self._v is None or self._monotonic() - self._at > WALL_VCELL_MAX_AGE_S:
                return None
            return self._v


def makeWallVcellFeed(
    cache: WallVcellCache,
    isPowerLostFn: Callable[[], bool],
    record: Callable[..., object],
) -> Callable[..., None]:
    """Wrap the UpsMonitor's per-poll ``recordHistorySample`` to feed ``cache``.

    ARCH-065: no new I2C read. The monitor's own poll has just read ``vcell``;
    it is cached only when the GPIO PLD still reads power PRESENT *after* that
    read, so a post-cut value is never cached as on-wall. The original record
    call runs first and unchanged; the feed never raises into the poll.
    """

    def _record(sampleTime: float, vcell: float, soc: object) -> None:
        record(sampleTime, vcell, soc)
        try:
            if not isPowerLostFn():
                cache.update(vcell)
        except Exception as exc:  # noqa: BLE001 -- never break the UpsMonitor poll
            logger.debug("powerwatch: wall VCELL feed failed (%s)", exc)

    return _record


def makeOutcomeSink(
    outcomePath: str,
    *,
    homeState: Callable[[], str] | None = None,
    wallVcell: Callable[[], float | None] | None = None,
    lossAt: Callable[[], str | None] | None = None,
) -> Callable[[SyncOutcomeRecord], None]:
    """The sync task's ``writeRecord``: one durable shutdown record per run.

    US-776-d: the record carries the outcome NAME as ``sync_outcome`` and both
    backlog counts -- the keys the next boot lands into startup_log's
    ``prior_boot_*`` columns (US-776-f). An unknown count is omitted, so it
    lands NULL. ``writeOutcomeRecord`` never raises.

    Args:
        outcomePath: The durable shutdown record (powerwatch_outcome.json).
        homeState: US-741 -- optional zero-arg read of the home state NAME at
            the power loss (``HomeStateAtLoss.stateName``). The sync record
            overwrites the file, so it must carry the name forward.
        wallVcell: ARCH-065 -- optional zero-arg read of powerwatch's last
            on-wall VCELL (``WallVcellCache.last``); written as
            ``vcell_before_cut_v``.
        lossAt: ARCH-065 -- optional zero-arg read of this loss's wall time
            (``HomeStateAtLoss.lossIso``); written as ``loss_at``.
    """

    def _write(record: SyncOutcomeRecord) -> None:
        writeOutcomeRecord(
            outcomePath,
            record.kind,
            detail=record.detail,
            task="sync_with_server",
            homeState=homeState() if homeState is not None else None,
            syncOutcome=record.kind.name,
            backlogStart=record.backlogStart,
            backlogEnd=record.backlogEnd,
            syncStartedAt=record.startedAt,
            syncEndedAt=record.endedAt,
            vcellBeforeCutV=wallVcell() if wallVcell is not None else None,
            lossAt=lossAt() if lossAt is not None else None,
        )

    return _write


def _startDaemonThread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="pw-home-state", daemon=True).start()


class HomeStateAtLoss:
    """US-741: ask the home detector ONCE per power loss and persist the answer.

    ``observe`` is a ``powerLossObservedFn`` hook: it starts the detector read
    on its own thread and returns at once, so the load shed and the smoothing
    window are never held up by nmcli or the HTTP probe. The answer's NAME goes
    into the durable shutdown record, which the next boot lands as
    ``startup_log.prior_boot_home_state`` (US-776-f).

    The record is written on every path a loss can take, exactly once per
    loss with this loss's state:

    * the answer arrives -- written then (a blip that cancels is covered);
    * the sync task records its outcome -- its record carries the name, since
      it overwrites the same file (``makeOutcomeSink(homeState=stateName)``);
    * the poweroff comes first (the VCELL floor fast path skips the
      pipeline) -- ``ensureRecorded`` writes ``INTERRUPTED`` (US-833) with the
      backlog left behind and the state as known (``UNKNOWN`` until the
      detector answers). The poweroff never waits for the detector; a late
      answer does not overwrite that record.

    US-833: the sync task's PROVISIONAL ``INTERRUPTED`` records pass through
    ``wrapSink`` too, so a hard cut mid-sync leaves them on disk, and a
    floor end carries their ``backlog_start`` / ``sync_started_at`` forward.

    The sync task's first home-state read IS this loss's answer
    (``stateForSync``), so the detector is called once per loss, not twice.
    Its later reads (the US-776-e JOINING polls) go to the detector live.
    """

    def __init__(
        self,
        readState: Callable[[], HomeNetworkState],
        *,
        outcomePath: str,
        startFn: Callable[[Callable[[], None]], None] | None = None,
        vcellBeforeCut: Callable[[], float | None] | None = None,
        monotonicFn: Callable[[], float] = time.monotonic,
        wallIsoFn: Callable[[], str] = utcIsoNow,
        backlogReader: Callable[[], int | None] | None = None,
    ) -> None:
        """Args:
        readState: Zero-arg detector read (``HomeNetworkDetector.
            getHomeNetworkState``); every call behind it is timeout-bounded.
        outcomePath: The durable shutdown record (powerwatch_outcome.json).
        startFn: Runs the observation off the caller's thread; a daemon
            thread when None. Tests pass a synchronous one.
        vcellBeforeCut: ARCH-065 -- ``WallVcellCache.last``. Read ONCE per loss
            (``observe``) so its age check applies at the loss, not minutes
            later; every record carries that snapshot as ``vcell_before_cut_v``.
        monotonicFn: ARCH-065 T5 -- the clock behind ``secondsSinceLoss``; the
            loss is stamped once, in ``observe``, so there is one loss time.
        backlogReader: US-833 -- the sync task's own unsynced-row count, read
            ONLY when a record must be written for a loss whose sync never
            wrote one (the fast path, or a floor end before the first
            provisional record). ``None`` or a failed read lands NULL.
        """
        self._monotonic = monotonicFn
        self._backlogReader = backlogReader
        #: US-833: this loss's sync has written a record (provisional or final),
        #: and the backlog_start / sync_started_at it carried.
        self._syncRecorded = False
        self._syncBacklogStart: int | None = None
        self._syncStartedAt: str | None = None
        self._lossAt: float | None = None
        self._wallIso = wallIsoFn
        self._lossIso: str | None = None
        self._readState = readState
        self._outcomePath = outcomePath
        self._startFn = startFn if startFn is not None else _startDaemonThread
        self._vcellSource = vcellBeforeCut
        #: Snapshot of the on-wall VCELL taken ONCE per loss, in observe().
        self._vcellSnapshot: float | None = None
        # Re-entrant: the sync sink runs under it and reads stateName.
        self._lock = threading.RLock()
        self._loss: threading.Event | None = None
        self._answer: HomeNetworkState | None = None
        self._handedToSync = False
        self._written = False
        #: True once RESERVE_FLOOR is written for this loss; the sink then drops
        #: any later (abandoned sync thread) record for the same loss.
        self._floorEnded = False
        #: Ruling 19: moves on every loss (observe). A pipeline thread left
        #: running by a CANCELLED loss carries the old value, so its record is
        #: dropped (wrapSink) and its hold labels nothing.
        self._generation = 0
        #: What this loss's last record was, for the floor-end overwrite log (M4).
        self._writtenKind: str | None = None

    def lossGeneration(self) -> int:
        """The current loss's generation (0 before any loss); +1 per ``observe``."""
        with self._lock:
            return self._generation

    def lossIso(self) -> str | None:
        """This loss's wall time, canonical UTC ISO (None before any loss)."""
        with self._lock:
            return self._lossIso

    def secondsSinceLoss(self) -> float:
        """Seconds since this loss was observed (0.0 before any loss)."""
        with self._lock:
            at = self._lossAt
        return 0.0 if at is None else max(0.0, self._monotonic() - at)

    def observe(self) -> None:
        """Start this loss's detector read. Returns at once; never raises."""
        loss = threading.Event()
        snapshot = self._snapshotVcell()
        with self._lock:
            self._lossAt = self._monotonic()
            self._lossIso = self._wallIso()
            self._vcellSnapshot = snapshot
            self._loss = loss
            self._answer = None
            self._handedToSync = False
            self._written = False
            self._writtenKind = None
            self._floorEnded = False
            self._syncRecorded = False
            self._syncBacklogStart = None
            self._syncStartedAt = None
            self._generation += 1
        try:
            self._startFn(lambda: self._observeLoss(loss))
        except Exception as exc:  # noqa: BLE001 -- never block the loss path
            # No thread: the sync task's first read asks the detector itself.
            logger.error("powerwatch: home-state read could not start (%s)", exc)
            loss.set()

    def _observeLoss(self, loss: threading.Event) -> None:
        try:
            state = self._readOnce()
            with self._lock:
                if self._loss is not loss:
                    return  # a newer loss owns the record now
                self._answer = state
                if not self._written:
                    self._writeHomeStateRecord(state.name, "home state at the power loss")
        finally:
            loss.set()

    def _snapshotVcell(self) -> float | None:
        """The on-wall VCELL as of this loss; None when absent or stale. Never raises."""
        if self._vcellSource is None:
            return None
        try:
            return self._vcellSource()
        except Exception as exc:  # noqa: BLE001 -- never block the loss path
            logger.debug("powerwatch: pre-cut VCELL snapshot failed (%s)", exc)
            return None

    def vcellBeforeCut(self) -> float | None:
        """This loss's pre-cut VCELL snapshot (None before any loss)."""
        with self._lock:
            return self._vcellSnapshot

    def _readOnce(self) -> HomeNetworkState:
        """One detector call; UNKNOWN when it raises."""
        try:
            return self._readState()
        except Exception as exc:  # noqa: BLE001 -- a dead detector is UNKNOWN
            logger.warning("powerwatch: home detector failed (%s) -- recording UNKNOWN", exc)
            return HomeNetworkState.UNKNOWN

    def stateForSync(self) -> HomeNetworkState:
        """The sync task's ``homeState``: this loss's answer, then live reads."""
        with self._lock:
            loss = self._loss
            first = loss is not None and not self._handedToSync
            self._handedToSync = True
        if not first:
            return self._readState()
        loss.wait()
        with self._lock:
            answer = self._answer if self._loss is loss else None
        if answer is None:
            # The observation never ran (its thread could not start): this is
            # the loss's one call. Outside the lock, so a poweroff never waits.
            answer = self._readOnce()
            with self._lock:
                if self._loss is loss and self._answer is None:
                    self._answer = answer
        return answer

    def stateName(self) -> str:
        """This loss's state name, ``UNKNOWN`` until it is known; never empty."""
        answer = self._answer
        return answer.name if answer is not None else HomeNetworkState.UNKNOWN.name

    def wrapSink(
        self, sink: Callable[[SyncOutcomeRecord], None]
    ) -> Callable[[SyncOutcomeRecord], None]:
        """Serialise the sync task's record with this one's (one file)."""

        def _write(record: SyncOutcomeRecord) -> None:
            with self._lock:
                generation = getattr(record, "lossGeneration", None)
                if generation is not None and generation != self._generation:
                    logger.info(
                        "powerwatch: stale record from a cancelled loss dropped "
                        "(sync %s of loss generation %s; current %s)",
                        record.kind.name,
                        generation,
                        self._generation,
                    )
                    return
                if self._floorEnded:
                    logger.info(
                        "powerwatch: sync record %s dropped -- the reserve floor "
                        "already ended this loss",
                        record.kind.name,
                    )
                    return
                sink(record)
                self._written = True
                self._writtenKind = f"sync_with_server {record.kind.name}"
                self._syncRecorded = True
                self._syncBacklogStart = record.backlogStart
                self._syncStartedAt = record.startedAt

        return _write

    def ensureRecorded(self) -> None:
        """Pre-poweroff hook: no loss powers off without a shutdown-sync record.

        US-833: a loss whose sync never wrote a record (the backstop fast path
        skips the pipeline) is recorded ``INTERRUPTED`` with the backlog it left
        and the home state as known -- ``UNKNOWN`` if the detector has not
        answered. A loss the sync or the floor already recorded is left alone.
        The backlog is read outside the lock, so the sync thread's sink is
        never held up by it.
        """
        with self._lock:
            if self._loss is None or self._syncRecorded or self._floorEnded:
                return
        backlog = self._readBacklog()
        with self._lock:
            if self._syncRecorded or self._floorEnded:
                return
            state = self.stateName()
            logger.warning(
                "powerwatch: no shutdown-sync record for this loss by the poweroff "
                "(the pipeline never ran) -- recording INTERRUPTED, home state %s, "
                "backlog %s",
                state,
                backlog,
            )
            self._writeRecord(
                OutcomeKind.INTERRUPTED,
                "the shutdown sync never ran: the poweroff came before the pipeline",
                "sync_with_server",
                state,
                syncOutcome=OutcomeKind.INTERRUPTED.name,
                backlogStart=backlog,
            )

    def recordFloorEnd(self) -> None:
        """The reserve floor ended this loss's drain: record RESERVE_FLOOR.

        Same file, same fields as the home-state record (home state from this
        class, pre-cut VCELL from this loss's snapshot). Later records for the
        same loss are dropped (``wrapSink``) and ``ensureRecorded`` returns
        early. Never raises (``writeOutcomeRecord`` does not).

        US-833: the record keeps the ``backlog_start`` / ``sync_started_at`` of
        the sync's own (provisional) record for this loss; with none yet, the
        backlog is read here.
        """
        with self._lock:
            synced = self._syncRecorded
            backlog, startedAt = self._syncBacklogStart, self._syncStartedAt
        if not synced:
            backlog = self._readBacklog()
        with self._lock:
            if self._written:
                logger.info(
                    "powerwatch: RESERVE_FLOOR overwrites the %s record already "
                    "written for this loss",
                    self._writtenKind,
                )
            self._writeRecord(
                OutcomeKind.RESERVE_FLOOR,
                "the reserve floor ended the drain",
                "sync_with_server",
                self.stateName(),
                syncOutcome=OutcomeKind.RESERVE_FLOOR.name,
                backlogStart=backlog,
                syncStartedAt=startedAt,
            )
            self._floorEnded = True
        logger.warning("powerwatch: the reserve floor ended the drain -- RESERVE_FLOOR recorded")

    def _writeHomeStateRecord(self, name: str, detail: str) -> None:
        self._writeRecord(OutcomeKind.OK, detail, "home_state_at_loss", name)
        logger.info("powerwatch: home state at the power loss = %s", name)

    def _writeRecord(
        self,
        kind: OutcomeKind,
        detail: str,
        task: str,
        homeState: str,
        *,
        syncOutcome: str | None = None,
        backlogStart: int | None = None,
        syncStartedAt: str | None = None,
    ) -> None:
        """The one write path for this class's records (SSOT for its fields)."""
        writeOutcomeRecord(
            self._outcomePath,
            kind,
            detail=detail,
            task=task,
            homeState=homeState,
            syncOutcome=syncOutcome,
            backlogStart=backlogStart,
            syncStartedAt=syncStartedAt,
            vcellBeforeCutV=self.vcellBeforeCut(),
            lossAt=self.lossIso(),
        )
        self._written = True
        self._writtenKind = f"{task} {kind.name}"

    def _readBacklog(self) -> int | None:
        """US-833: the unsynced-row count, or None (no reader, or it failed). Never raises."""
        if self._backlogReader is None:
            return None
        try:
            return self._backlogReader()
        except Exception as exc:  # noqa: BLE001 -- an unread count lands NULL
            logger.warning("powerwatch: backlog read for the shutdown record failed (%s)", exc)
            return None


def buildV1Tasks(
    syncTask: SyncWithServerTask, holdTask: MonthlyTestHoldTask | None = None
) -> list:
    """The ordered V1 ShutdownTask list (the plugin-seam registry, SS-T6).

    V1 ships ``SyncWithServerTask`` -- per the locked Option A scope (spec
    sec 9) -- and, since ARCH-065, the ``MonthlyTestHoldTask`` after it (when
    given; the one-arg form is the sync-only list). This function is the **SINGLE EDIT POINT**
    for future plugin tasks (e.g. update-check, staged apply-decision): a new
    task appends here and that is the ONLY production change. ``ShutdownSequencer``
    and ``runPipeline`` are untouched when new tasks land.

    The order matters -- tasks run sequentially under the bounded pipeline,
    each within its own per-task timeout. Sync first is V1's chosen ordering
    (CIO directive: best-effort sync of the local drive log before poweroff).
    """
    tasks: list = [syncTask]
    if holdTask is not None:
        tasks.append(holdTask)
    return tasks


def buildDrainCloseHook(
    *,
    config: dict,
    upsResolver,
    uptimeReader=None,
    ownDrainCloseSlot: OwnDrainCloseSlot | None = None,
):
    """Build the pre-poweroff drain-event close (US-526 PRIMARY close).

    Atlas Option C ruling (2026-08-02): the ShutdownSequencer close is PRIMARY
    because, under Spool's depth gate (``end_vcell_v <= 3.50`` V), the
    run-to-cutoff drain is the only qualifying drain and it ends on this path.
    The collector opens the row at wall-power loss; this closes it with the real
    depth the pack actually reached.

    Deliberately NOT built on ``ObdDatabase``: this service is
    shutdown-critical and importing ``pi.obdii`` would drag that whole package
    (display imports included) into its graph for the sake of a ``connect()``
    -- the V0.27.12-DOA import class. ``makeDrainEventWriterForPath`` uses
    stdlib sqlite3 only, and takes the sqlite busy timeout from
    ``pi.powerWatch.perTaskTimeoutSec`` -- the bound the shutdown path already
    defines for one unit of work -- so a locked database cannot delay poweroff.

    Args:
        config: Validated config. Needs ``pi.database.path``; reads
            ``pi.powerWatch.perTaskTimeoutSec`` and the cold-start window.
        upsResolver: Zero-arg callable returning the live ``UpsMonitor`` (or
            None). Resolved at CLOSE time, never captured.
        uptimeReader: Optional uptime reader for the SoC%% cold-start guard;
            defaults to the real ``/proc/uptime`` reader.
        ownDrainCloseSlot: US-789 -- cleared before the close and given the
            drain_event_id only when the close actually wrote the row, so the
            custody hook that runs next can exclude exactly that one row.

    Returns:
        A zero-arg callable for ``ShutdownSequencer(prePowerOffFn=...)``, or
        None when ``pi.database.path`` is absent (no path is ever guessed).
    """
    dbPath = config.get("pi", {}).get("database", {}).get("path")
    if not dbPath:
        logger.warning(
            "powerwatch: pi.database.path absent -- drain-event close on the "
            "shutdown path is DISABLED (a run-to-cutoff drain will be left "
            "open and reaped as interrupted at next boot)"
        )
        return None

    pwCfg = config.get("pi", {}).get("powerWatch", {}) or {}
    busyTimeoutSec = float(pwCfg.get("perTaskTimeoutSec", 5.0))
    writer = makeDrainEventWriterForPath(
        dbPath=str(dbPath),
        upsResolver=upsResolver,
        busyTimeoutSec=busyTimeoutSec,
        uptimeReader=uptimeReader or readSystemUptimeSeconds,
        coldStartWindowSeconds=resolveColdStartWindowSeconds(config),
        cellEpoch=resolveCellEpoch(config),
    )

    def _closeDrain() -> None:
        # The writer swallows its own faults (it must never break a poweroff);
        # the sequencer guards this call as well -- belt and braces on the one
        # path where a raise would be worst.
        #
        # US-789: cleared FIRST, so a close that finds nothing, fails, or
        # raises leaves custody counting every row -- it can never exclude a
        # row that was never written.
        if ownDrainCloseSlot is not None:
            ownDrainCloseSlot.clear()
        result = writer.closeOpenDrainEvent(reason=CLOSE_REASON_SHUTDOWN)
        if ownDrainCloseSlot is not None and result is not None and result.closed:
            ownDrainCloseSlot.record(result.drainEventId)

    return _closeDrain


def _runOneShotForTest(
    *,
    outcomePath: str,
    perTaskTimeoutSec: float,
    totalWindowCapSec: float,
    vcellFloorVolts: float,
    joinWaitSec: float,
    stallSec: float,
) -> int:
    """PW_TEST_ONESHOT hook: exercise the REAL import + controller/pipeline/
    task/outcome chain EXACTLY as systemd invokes the entrypoint, but WITHOUT
    real I2C, network, or poweroff.

    Active ONLY when the env var is set (production path never reaches here).
    This is the institutionalized V0.27.12-DOA guard: a missing/renamed import
    in this module's transitive graph fails this test loudly because it runs
    the real `python -m src.pi.power.power_watch` under the unit's PYTHONPATH.

    Deterministic scenario: at home (server reachable), sync raises (transient) on
    every attempt up to the ceiling -> AT_HOME_SERVER_DOWN -> a real outcome record
    is produced; the bounded controller then reaches the (stubbed) poweroff.
    """

    def _failingSync() -> None:
        raise RuntimeError("PW_TEST_ONESHOT injected transient sync failure")

    def _stubPoweroff() -> None:
        marker = os.environ["PW_TEST_POWEROFF_MARKER"]
        Path(marker).write_text("poweroff-invoked", encoding="utf-8")

    # US-776-g: the retry backoff runs on a virtual clock that only its own
    # waits advance, so the guard walks the whole ceiling without sleeping.
    virtualNow = [0.0]

    def _virtualSleep(seconds: float) -> None:
        virtualNow[0] += seconds

    syncTask = SyncWithServerTask(
        homeState=lambda: HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        runSync=_failingSync,
        writeRecord=makeOutcomeSink(outcomePath),
        joinWaitSec=joinWaitSec,
        stallSec=stallSec,
        sleepFn=_virtualSleep,
        monotonic=lambda: virtualNow[0],
    )
    shutdownSequencer = ShutdownSequencer(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: runPipeline(
            buildV1Tasks(syncTask), perTaskTimeoutSec=perTaskTimeoutSec
        ),
        powerOffFn=_stubPoweroff,
        vcellFloor=vcellFloorVolts,
        totalCapSec=totalWindowCapSec,
        smoothingSec=0.0,  # guard test stays fast; smoothing covered by unit tests
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
    )
    logger.warning("powerwatch PW_TEST_ONESHOT: single bounded handle, no I2C")
    shutdownSequencer.handleOnBattery()
    return 0


#: One greppable prefix for the next-boot time-to-death report (US-748):
#:   journalctl -u eclipse-powerwatch.service --grep='LOSS HEARTBEAT'
LOSS_HEARTBEAT_PREFIX = "powerwatch: LOSS HEARTBEAT ="


def emitPriorLossHeartbeat(dbPath: str) -> LossHeartbeatSummary | None:
    """Report what the most recent power loss's heartbeat rows say (US-748).

    The last surviving row is how long the machine was OBSERVED alive after the
    PLD loss. It is time-to-death when the previous boot has no CLEAN_COMPLETE,
    and time-to-poweroff when it does -- this line states the number and names
    both readings rather than choosing one it cannot see from here.

    Args:
        dbPath: ``pi.database.path``.

    Returns:
        The summary that was reported, or None when no loss has been recorded.
    """
    summary = readLatestLossHeartbeat(dbPath)
    if summary is None:
        logger.info("%s none recorded (no power loss has been measured)", LOSS_HEARTBEAT_PREFIX)
        return None
    vcellText = f"{summary.minVcellV:.3f} V" if summary.minVcellV is not None else "unread"
    if summary.windowCompleted:
        logger.warning(
            "%s loss at %s: alive through the WHOLE %d-row window (last row %.1fs) "
            "-- the machine outlived the instrument; min VCELL %s, %d row(s) saw "
            "power return",
            LOSS_HEARTBEAT_PREFIX,
            summary.lossStartedUtc,
            summary.rowCount,
            summary.lastElapsedS,
            vcellText,
            summary.powerReturnedRows,
        )
    else:
        logger.warning(
            "%s loss at %s: last row %.1fs after the PLD loss (%d row(s), min VCELL "
            "%s, %d row(s) saw power return) -- TIME-TO-DEATH if the prior boot has "
            "no CLEAN_COMPLETE, time-to-poweroff if it does; understated by at "
            "most one row interval",
            LOSS_HEARTBEAT_PREFIX,
            summary.lossStartedUtc,
            summary.lastElapsedS,
            summary.rowCount,
            vcellText,
            summary.powerReturnedRows,
        )
    return summary


def _runPldWatchLoop(
    *,
    isPowerLostFn,
    stop,
    serviceStartMono: float,
    bootGraceSec: float,
    pldPollSec: float,
    pldGpioPin: int,
    handleLock,
    shutdownSequencer,
    monotonicFn=time.monotonic,
) -> None:
    """The X1209 GPIO6 PLD watch loop body, separated from main() for unit tests.

    F-7 fix (US-344, Sprint 40 / V0.27.16, 2026-05-20): post-boot-grace check is
    LEVEL-based, not edge-based. A loss event ignored during boot-grace therefore
    re-fires correctly the first post-grace tick if the line is still LOW (bug
    bound: cold-start + in-grace transient + no alternator recovery before
    key-off). The smoothing path inside ShutdownSequencer.handleOnBattery remains
    the abort surface for transient glitches that resolve mid-window; this loop
    only owns trigger detection.

    Pre-fix behavior (edge-only, V0.27.15): once an in-grace loss event latched
    prevLost=True, lost AND not prevLost was permanently False post-grace if the
    HAT did not recover. The sequencer stayed silent until alternator recovery
    (which may never happen). See finding 2026-05-20-shutdown-sequencer-
    boot-grace-latch-bug.md for the in-car drill evidence (Atlas + CIO Test 2,
    5.5 min silence reproduced on demand).

    US-788: bootGrace no longer gates the TRIGGER. An in-grace loss runs the
    normal path (shed, heartbeat, smoothing, pipeline, graceful poweroff) with
    only the VCELL floor fast path suppressed. Before this, the grace gate sat on
    the branch that reaches handleOnBattery, so an in-grace loss lost the
    mitigation and the instruments along with the poweroff: three hard cuts,
    zero false positives.
    """
    # In-grace: edge-triggered on a present->lost transition, so one loss fires
    # once and a completed in-grace shutdown is not re-entered on every poll.
    # It deliberately does NOT set firedAlready: the post-grace branch below is
    # byte-identical to pre-US-788, including re-firing on a level-stuck LOW line
    # after an in-grace blip (the F-7 fix). Post-boot-grace fires on level (lost
    # AND not firedAlready) so a level-stuck LOW state cannot leave the
    # sequencer blind.
    prevLost = isPowerLostFn()
    firedAlready = False
    while not stop.wait(timeout=pldPollSec):
        lost = isPowerLostFn()
        # US-792: a PRESENT reading ends THIS loss episode and releases the
        # re-entry latch. firedAlready is set on all three exits of
        # handleOnBattery -- including CANCEL -- so without this a blip that
        # cancelled a shutdown left the trigger dead for the rest of the boot
        # and the next genuine key-off was a hard cut. The clear lives in the
        # loop because the loop owns the line, and carries NO debounce,
        # deliberately asymmetric with smoothingSec. Rationale: architecture
        # 10.6. A level-stuck LOW line never reaches here, so the guard holds.
        if not lost:
            firedAlready = False
        graceElapsed = monotonicFn() - serviceStartMono
        if graceElapsed < bootGraceSec:
            if lost and not prevLost and handleLock.acquire(blocking=False):
                try:
                    logger.warning(
                        "powerwatch: GPIO%d PLD => external power LOST %.0fs into "
                        "boot-grace (%.0fs) -- entering bounded pre-shutdown window, "
                        "VCELL floor fast path suppressed",
                        pldGpioPin,
                        graceElapsed,
                        bootGraceSec,
                    )
                    shutdownSequencer.handleOnBattery(suppressFloorFastPath=True)
                finally:
                    handleLock.release()
        elif lost and not firedAlready:
            if handleLock.acquire(blocking=False):
                try:
                    logger.warning(
                        "powerwatch: GPIO%d PLD => external power LOST -- "
                        "entering bounded pre-shutdown window",
                        pldGpioPin,
                    )
                    shutdownSequencer.handleOnBattery()
                    firedAlready = True
                finally:
                    handleLock.release()
        prevLost = lost


def main(argv: list[str] | None = None) -> int:
    """Build the real ShutdownSequencer and block on the GPIO6 PLD watch loop."""
    args = _parseArgs(argv)
    config = loadConfigWithSecrets(args.config, args.env_file)
    config = ConfigValidator().validate(config)

    # US-566: configure logging BEFORE anything reports a decision. Without a
    # root handler Python falls back to logging.lastResort (level WARNING,
    # stderr) and SILENTLY DISCARDS the whole INFO tier -- measured on
    # chi-eclipse-01 2026-08-21 as zero "powerwatch service up" lines across 8
    # service starts, while WARNING lines from the same pids came through.
    # Level only, deliberately NO logFile: this service is shutdown-critical
    # and must not open a second writer on the OBD app's log file. stdout IS
    # the journal (unit: StandardOutput=journal) and StreamHandler flushes per
    # record, so block-buffering cannot strand a line. An absent logging
    # section resolves to INFO rather than crashing the safety service.
    setupLogging(level=str((config.get("logging") or {}).get("level") or "INFO"))

    pw_cfg = config["pi"]["powerWatch"]
    perTaskTimeoutSec = float(pw_cfg["perTaskTimeoutSec"])
    totalWindowCapSec = float(pw_cfg["totalWindowCapSec"])
    vcellFloorVolts = float(pw_cfg["vcellFloorVolts"])
    drainFloorVolts = float(pw_cfg["drainFloorVolts"])
    drainFloorDwellReads = int(pw_cfg["drainFloorDwellReads"])
    poweroffTimeoutSec = float(pw_cfg["poweroffTimeoutSec"])
    bootGraceSec = float(pw_cfg["bootGraceSec"])
    smoothingSec = float(pw_cfg["smoothingSec"])
    smoothingPollSec = float(pw_cfg["smoothingPollSec"])
    pldGpioPin = int(pw_cfg["pldGpioPin"])
    pldPowerPresentHigh = bool(pw_cfg["pldPowerPresentHigh"])
    pldPollSec = float(pw_cfg["pldPollSec"])
    joinWaitSec = float(config["pi"]["homeNetwork"]["joinWaitSec"])
    stallSec = float(config["pi"]["homeNetwork"]["stallSec"])

    # Outcome record sits next to the SQLite db (the existing data/ dir) --
    # reuse pi.database.path rather than hardcode or add an un-specced key.
    dbPath = config["pi"]["database"]["path"]
    outcomePath = os.path.join(os.path.dirname(dbPath), "powerwatch_outcome.json")

    # Real-invocation guard hook (T8). Active ONLY when the env var is set;
    # the production path below is untouched.
    if os.environ.get("PW_TEST_ONESHOT"):
        return _runOneShotForTest(
            outcomePath=outcomePath,
            perTaskTimeoutSec=perTaskTimeoutSec,
            totalWindowCapSec=totalWindowCapSec,
            vcellFloorVolts=vcellFloorVolts,
            joinWaitSec=joinWaitSec,
            stallSec=stallSec,
        )

    companion = config.get("pi", {}).get("companionService", {}) or {}
    apiKey = getSecret(str(companion.get("apiKeyEnv") or "COMPANION_API_KEY"))

    monitor = UpsMonitor()
    pld = PldSensor(pin=pldGpioPin, powerPresentHigh=pldPowerPresentHigh)
    # SSOT (SS-T3/T4): all power-source acquisition routes through this single
    # provider; the sequencer + the boot-grace watch loop + the arm self-check
    # all consume it (the boot-grace + smoothing policy lives in the consumer,
    # provider stays policy-free).
    provider = PowerSourceProvider(pld=pld)
    detector = HomeNetworkDetector(config, apiKey=apiKey)
    syncClient = SyncClient(config)

    # US-621: ONE backlog reader, shared by the drain (to decide whether
    # another pass is worth making) and by the custody record (to state what
    # remains). Two readers could disagree, and a shutdown that pushed until
    # "empty" then recorded a different number would be worse than either.
    #
    # US-766: that shared reader now EXCLUDES the EDR tables, and the drain
    # excludes the SAME set when it pushes. The US-621 invariant is preserved
    # exactly -- one membership, read from the shared contract, used by both --
    # because a drain that skipped EDR while its backlog reader still counted
    # EDR would never see "empty" and would spend the entire shutdown window on
    # passes that move nothing.
    #
    # US-789: custody passes excludeRows (rows, by primary key) -- table
    # membership stays identical for both callers. US-790: the drain passes
    # this shutdown's own VCELL series rows (readDrainBacklog below).
    def readSyncBacklog(excludeRows=()):
        return countOutstandingRows(
            dbPath,
            busyTimeoutSec=perTaskTimeoutSec,
            excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
            excludeRows=excludeRows,
        )

    # A DIFFERENT question, deliberately not folded into the reader above: how
    # much archival EDR is still on the Pi? Reported beside the custody verdict
    # so it stays visible, never inside it so it can never move it.
    def readEdrBacklog():
        return countOutstandingRows(
            dbPath,
            busyTimeoutSec=perTaskTimeoutSec,
            onlyTables=EDR_SYNC_TABLES,
        )

    # US-790: the drain's own VCELL series. The sequencer hands the writer one
    # row per drain poll; each id that lands joins this APPEND-ONLY set (Atlas
    # 2026-09-19, decision 2), built empty once, here.
    #
    # The DRAIN's exit check excludes the same set as custody. The drain CARRIES
    # the table (it is not EDR), so rows written before a pass are pushed by it;
    # but a row lands every second, and without this every pass would find the
    # one written since the last push and go again -- the rows chasing
    # backlog == 0. Only this shutdown's own rows are excluded, by id, and
    # custody reports them beside the verdict: one membership, both readers.
    ownTrajectoryRows = OwnTrajectoryRows()
    cellEpoch = resolveCellEpoch(config)
    drainTrajectory = DrainVcellTrajectoryWriter(
        dbPath=dbPath,
        cellEpoch=cellEpoch,
        # One poll interval: a lock costs a row its slot, never the floor check.
        busyTimeoutSec=smoothingPollSec,
        onRowWritten=ownTrajectoryRows.add,
        # Fence 3: each drain starts the set over, so an undelivered cancelled
        # drain's rows stay backlog for the next one.
        onDrainStart=ownTrajectoryRows.beginDrain,
    )

    def readDrainBacklog():
        return readSyncBacklog(excludeRows=ownTrajectoryRows.exclusions())

    # US-741: the detector is asked ONCE per power loss, off the loss path's
    # thread, and its answer persisted (startup_log.prior_boot_home_state at
    # the next boot). The sync task's first read is that same answer.
    # ARCH-065: the last on-wall VCELL (cut_step_mv), fed from the UpsMonitor's
    # existing ~5 s poll -- NO extra I2C read, and the PLD thread stays GPIO-only.
    wallCache = WallVcellCache()
    monitor.recordHistorySample = makeWallVcellFeed(
        wallCache, provider.isPowerLost, monitor.recordHistorySample
    )

    homeStateAtLoss = HomeStateAtLoss(
        detector.getHomeNetworkState,
        outcomePath=outcomePath,
        vcellBeforeCut=wallCache.last,
        # US-833: the same count the sync task records, for a loss whose sync
        # never wrote one (the fast path; a floor end before the first record).
        backlogReader=lambda: backlogCount(readDrainBacklog()),
    )
    # US-776-d: one durable record per run -- why the sync ended. US-741: it
    # carries the loss's home state, serialised with that record. US-833: the
    # sync task's PROVISIONAL records go through this SAME sink (one file, one
    # serialiser), and the final outcome overwrites them.
    syncRecordSink = homeStateAtLoss.wrapSink(
        makeOutcomeSink(
            outcomePath,
            homeState=homeStateAtLoss.stateName,
            wallVcell=homeStateAtLoss.vcellBeforeCut,
            lossAt=homeStateAtLoss.lossIso,
        )
    )

    syncTask = SyncWithServerTask(
        # US-776-c: the drain decision. A positive AWAY skips at once (no wait,
        # no HTTP call); at home, or UNKNOWN with no positive AWAY, it drains.
        # Every nmcli / hostname -I / HTTP call behind it is timeout-bounded.
        homeState=homeStateAtLoss.stateForSync,
        # US-776-a: no budget -- the drain ends on an empty backlog or the
        # sequencer's VCELL floor poll. Every pass excludes the EDR set.
        runSync=_buildRunSync(
            syncClient,
            backlogReader=readDrainBacklog,
            excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
        ),
        # US-776-d / US-741 / US-833: the final outcome and the provisional
        # records share the one serialised sink built above.
        writeRecord=syncRecordSink,
        writeProvisional=syncRecordSink,
        # ARCH-065: the drain runs to completion -- it ends delivered, or when
        # the backlog has not fallen for stallSec; the WiFi-join wait is
        # bounded separately by joinWaitSec.
        joinWaitSec=joinWaitSec,
        stallSec=stallSec,
        # US-776-d: backlog_start / backlog_end from the shared US-621 reader,
        # with the drain's own exclusions, so 0 means what the drain's exit
        # check means by it.
        backlogReader=lambda: backlogCount(readDrainBacklog()),
        # US-776-d: the probe behind the home state, read -- never re-probed --
        # to tell a misconfigured probe from a down server.
        lastProbe=lambda: detector.lastProbe,
        # Ruling 19: the loss this run belongs to rides on its record.
        lossGeneration=homeStateAtLoss.lossGeneration,
    )

    # ARCH-065 T5: once a month, at home, hold the Pi on battery TEST_HOLD_S
    # after the cut (holdSec defaults to the SSOT). Sequencer-bounded, so the
    # drain floor and a power return still govern it.
    monthlyIntervalDays = int(config["pi"]["batteryHealth"]["monthlyIntervalDays"])
    cellEpochForTest = resolveCellEpoch(config)
    holdTask = MonthlyTestHoldTask(
        # Ruling 19: gated on the home state AT THE LOSS (one owner of "at
        # home": home_detector.AT_HOME_STATE_NAMES), never a sync-outcome proxy.
        homeStateName=homeStateAtLoss.stateName,
        isDue=lambda: isMonthlyTestDue(
            dbPath,
            cellEpoch=cellEpochForTest,
            nowIso=utcIsoNow(),
            intervalDays=monthlyIntervalDays,
        ),
        # The hold snapshots lossIso + the loss generation ONCE at run start and
        # passes that lossIso to every mark (a stale hold never re-reads it).
        markOpenDrain=lambda lossIso: markOpenDrainMonthlyTest(dbPath, lossIso=lossIso),
        lossIso=homeStateAtLoss.lossIso,
        lossGeneration=homeStateAtLoss.lossGeneration,
        secondsSinceCut=homeStateAtLoss.secondsSinceLoss,
    )

    # F-103 [A-2]: wire the shutdown-splash phase-emit hook. The sequencer emits
    # a shutdown-state phase event (grace -> cancelled | flushing -> powering_off)
    # at each transition; the splash-grace kiosk renders it. Disabled (None) when
    # pi.splash.enabled is false -- the sequencer then runs unchanged. Best-effort
    # by contract: a write failure never blocks shutdown.
    splashCfg = config.get("pi", {}).get("splash", {}) or {}
    phaseEmitFn = None
    if bool(splashCfg.get("enabled", True)):
        statesDir = splashCfg.get("statesDir", "/run/eclipse-obd/states")
        phaseEmitFn = makeShutdownPhaseEmitter(statesDir)

    # US-526 [Atlas Option C]: close the production drain row on the shutdown
    # path -- the PRIMARY close. The collector opened it at wall-power loss; the
    # depth recorded here (end_vcell_v) is what Spool's gate qualifies on. The
    # UPS is resolved at close time, never captured.
    #
    # US-789 [Atlas shape (c)]: the close runs FIRST in the composed hook and
    # writes a battery_health_log row that custody would otherwise count,
    # making every graceful shutdown read OUTSTANDING. The close stays exactly
    # where it is (end_vcell_v is its close-time depth); it just hands its
    # drain_event_id to custody through this slot, which custody excludes and
    # reports beside the verdict. Hook isolation is kept: an empty slot means
    # custody counts every row.
    ownDrainCloseSlot = OwnDrainCloseSlot()
    drainCloseFn = buildDrainCloseHook(
        config=config,
        upsResolver=lambda: monitor,
        ownDrainCloseSlot=ownDrainCloseSlot,
    )

    # US-621 [same placement argument as US-526 Option C]: the custody record
    # is a PRE-POWEROFF hook, NOT a pipeline ShutdownTask. Two reasons, both
    # measured. (1) The VCELL-floor fast path SKIPS the pipeline entirely
    # (controller.py) -- and that run-to-cutoff shutdown is exactly the one
    # carrying the most undelivered rows, so a task-based record would miss
    # every case that matters most. (2) runPipeline ABANDONS a task that
    # exceeds perTaskTimeoutSec, and an abandoned thread writes nothing; a
    # custody record that disappears precisely when the queue is too big to
    # drain would be silent in its own failure mode. (US-776-a: the sync task
    # is no longer abandoned, but the floor poll can still power off with a
    # pass in flight, and the record must be written then too.)
    custodyFn = makeSyncCustodyHook(
        recordPath=os.path.join(os.path.dirname(dbPath), CUSTODY_RECORD_FILENAME),
        backlogReader=readSyncBacklog,
        edrBacklogReader=readEdrBacklog,
        ownDrainCloseSlot=ownDrainCloseSlot,
        ownTrajectoryRows=ownTrajectoryRows,
    )
    # US-741: last, and isolated like the others -- a loss whose detector has
    # not answered (the floor fast path) still powers off with UNKNOWN written.
    # ARCH-065: a floor-ended drain is recorded RESERVE_FLOOR first, so
    # ensureRecorded (which returns once written) never lands UNKNOWN over it.
    # shutdownSequencer is bound below; the lambda reads it at poweroff time.
    prePowerOffFn = composePrePowerOffHooks(
        drainCloseFn,
        custodyFn,
        buildFloorEndHook(
            lambda: shutdownSequencer.lastDrainEndReason, homeStateAtLoss
        ),
        homeStateAtLoss.ensureRecorded,
    )

    # US-748: the previous loss's heartbeat rows, reported once per start --
    # the number the 09-14 cuts could only bound ("under 30 s").
    emitPriorLossHeartbeat(dbPath)
    # ...and this boot's instrument, started at the ENTRY of handleOnBattery.
    lossHeartbeat = PowerLossHeartbeat(
        dbPath=dbPath,
        vcellFn=monitor.getVcell,
        isPowerLostFn=provider.isPowerLost,
    )

    # ARCH-031 (US-748): shed the heavy, non-essential load the INSTANT power is
    # lost -- before smoothing decides anything. Measured over nine live cuts
    # 2026-09-16: with the chromium dashboard up the Pi drew 4.35 W bursty and
    # lasted 0.678 s on battery; with that one service stopped, 1.886 W and ~7 s.
    # Everything else the project runs adds ~0.1 W combined.
    #
    # Reversible by design: if the loss turns out to be a blip the sequencer
    # cancels and `restore` puts it back, so nothing is committed on the edge.
    # Configurable, defaulting to the dashboard alone -- never "stop
    # everything", because the remaining services are the ones that PRESERVE
    # data.
    #
    # US-796: the grace splash is NOT shed. The CIO kept the shutdown
    # animation, and the stop of splash-grace failed on every cut anyway. The
    # sequencer never learns a splash unit name (F-103).
    shedUnits = pw_cfg.get("shedUnitsOnPowerLoss", DEFAULT_SHED_UNITS)
    loadShedder = LoadShedder(shedUnits)

    shutdownSequencer = ShutdownSequencer(
        isOnBattery=provider.isPowerLost,
        vcell=monitor.getVcell,
        # US-776-a: the sync task is joined without perTaskTimeoutSec -- an
        # abandoned drain would keep pushing and writing SQLite while poweroff
        # runs. Its bound is the sequencer's floor poll. Every other task keeps
        # the per-task bound.
        runPipelineFn=lambda: runPipeline(
            buildV1Tasks(syncTask, holdTask),
            perTaskTimeoutSec=perTaskTimeoutSec,
            sequencerBoundedTasks=(syncTask.name, holdTask.name),
        ),
        powerOffFn=lambda: subprocess.run(
            ["systemctl", "poweroff"], timeout=poweroffTimeoutSec, check=False
        ),
        vcellFloor=vcellFloorVolts,
        # US-776-b: the running drain stops here; vcellFloor stays the
        # pre-pipeline backstop.
        drainFloor=drainFloorVolts,
        drainFloorDwellReads=drainFloorDwellReads,
        # US-790: the start read and every drain poll become rows.
        drainSampleFn=drainTrajectory.record,
        totalCapSec=totalWindowCapSec,
        smoothingSec=smoothingSec,
        smoothingPollSec=smoothingPollSec,
        phaseEmitFn=phaseEmitFn,
        prePowerOffFn=prePowerOffFn,
        # ⚠️ The loss-observed slot takes ONE callable and already held US-748's
        # heartbeat. Composed with the same per-hook isolation the pre-poweroff
        # slot uses, so a failing shed can never suppress the time-to-death
        # instrument -- or vice versa. US-741: the home-state read is last and
        # only starts a thread, so the shed is never behind nmcli or HTTP.
        powerLossObservedFn=composePrePowerOffHooks(
            lossHeartbeat.start, loadShedder.shed, homeStateAtLoss.observe
        ),
        powerRestoredFn=loadShedder.restore,
    )

    # TRIGGER = the X1209 GPIO6 PLD hardware line via the PowerSourceProvider
    # SSOT (deterministic "external power present"), NOT the retired VCELL-
    # trend heuristic that bricked the Pi 2026-05-18.
    #
    # Arm self-check: the service only starts because the Pi booted on a live
    # feed, so the SSOT MUST read power-present right now. If it does not
    # (wrong pin/polarity, or unreadable), REFUSE to arm -- stay up disarmed,
    # never poweroff. Fails to "do not shut down", the deliberate inverse of
    # the old "uncertain -> poweroff" mistake.
    # US-566: the decision is now reported on BOTH branches, and it is the
    # first thing this service says. Evidence is read through the PROVIDER,
    # not the raw PldSensor -- the pre-US-566 message reached around the SSOT
    # to `pld.*` for its own diagnostics, which is the one place a second
    # acquisition site could disagree with the decision it is explaining.
    armed = provider.startupArmCheck()
    # ARCH-019: the arm line may only PREDICT what a power loss will do once a
    # real PLD transition has been witnessed. Until then it states what the
    # self-check actually established -- that the pin READS. US-666: that
    # renders PIN READABLE, TRANSITION UNVERIFIED, never ARMED. The disposition
    # below is unchanged: a readable pin still runs the watch.
    decisionLine = emitArmDecision(
        armed=armed,
        pldGpioPin=pldGpioPin,
        pldAvailable=provider.isAvailable,
        readsPowerPresent=provider.isExternalPowerPresent(),
        lastTransitionUtc=readWitness(),
    )
    if not armed:
        # Stay alive, disarmed -- and keep saying so.
        return runDisarmedHold(message=decisionLine, waitFn=threading.Event().wait)

    monitor.startPolling()  # vcell-backstop telemetry only; NOT the trigger
    logger.info(
        "powerwatch service up (GPIO%d PLD SSOT trigger): perTask=%.0fs "
        "totalCap=%.0fs vcellFloor=%.2fV smoothing=%.0fs bootGrace=%.0fs",
        pldGpioPin,
        perTaskTimeoutSec,
        totalWindowCapSec,
        vcellFloorVolts,
        smoothingSec,
        bootGraceSec,
    )

    handleLock = threading.Lock()
    serviceStartMono = time.monotonic()
    stop = threading.Event()

    def _pldWatchLoop() -> None:
        # The SSOT provider is the only power-acquisition site (criterion #3);
        # the sequencer's smoothing window then re-reads the SAME line via the
        # SAME provider, so a real loss confirms and a glitch aborts. Boot-grace
        # scopes only the VCELL floor fast path (US-788), never the trigger.
        # Loop body extracted into _runPldWatchLoop for unit-test access
        # (US-344 F-7 fix).
        _runPldWatchLoop(
            isPowerLostFn=provider.isPowerLost,
            stop=stop,
            serviceStartMono=serviceStartMono,
            bootGraceSec=bootGraceSec,
            pldPollSec=pldPollSec,
            pldGpioPin=pldGpioPin,
            handleLock=handleLock,
            shutdownSequencer=shutdownSequencer,
        )

    th = threading.Thread(target=_pldWatchLoop, name="pw-pld", daemon=True)
    th.start()

    # ---- US-668: publish the power source for the collector -----------------
    # powerwatch OWNS BCM GPIO6. eclipse-obd used to open the same line, one of
    # them lost the race with EBUSY and went permanently blind (no re-open path
    # in PldSensor), and three punch-list items followed from that single cause.
    # Neither unit orders against the other, so the loser was not even stable
    # between boots -- which is why ownership is declared, not discovered.
    #
    # ⚠️ This runs on its OWN thread, deliberately. The watch loop above is the
    # safety-critical path that triggers the graceful poweroff; a slow or failing
    # filesystem write must never be able to delay it. Status I/O stays out of
    # the interlock.
    statesDir = (
        config.get("pi", {}).get("splash", {}).get("statesDir")
        or "/run/eclipse-obd/states"
    )
    powerSourcePath = os.path.join(statesDir, POWER_SOURCE_FILENAME)

    def _publishLoop() -> None:
        while not stop.is_set():
            try:
                publishPowerSource(
                    powerSourcePath,
                    externalPowerPresent=provider.isExternalPowerPresent(),
                    available=provider.isAvailable,
                    reason=getattr(pld, "unavailableReason", None),
                )
            except Exception as exc:  # noqa: BLE001 -- never break the publisher
                logger.warning("power-source publish loop error: %s", exc)
            stop.wait(pldPollSec)

    pubTh = threading.Thread(target=_publishLoop, name="pw-pub", daemon=True)
    pubTh.start()

    # Block forever -- the watch + UpsMonitor threads are daemons.
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
