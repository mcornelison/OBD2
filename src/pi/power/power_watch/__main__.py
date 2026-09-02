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
from src.common.logging.setup import setupLogging  # noqa: E402
from src.pi.hardware.pld_sensor import PldSensor  # noqa: E402
from src.pi.hardware.ups_monitor import UpsMonitor  # noqa: E402
from src.pi.network.home_detector import HomeNetworkDetector  # noqa: E402
from src.pi.power.drain_event_writer import (  # noqa: E402
    CLOSE_REASON_SHUTDOWN,
    makeDrainEventWriterForPath,
)
from src.pi.power.power_source_provider import PowerSourceProvider  # noqa: E402
from src.pi.power.power_source_pubsub import (  # noqa: E402
    POWER_SOURCE_FILENAME,
    publishPowerSource,
)
from src.pi.power.power_watch.controller import ShutdownSequencer  # noqa: E402
from src.pi.power.power_watch.outcome import writeOutcomeRecord  # noqa: E402
from src.pi.power.power_watch.pipeline import runPipeline  # noqa: E402
from src.pi.power.power_watch.pld_witness import readWitness  # noqa: E402
from src.pi.power.power_watch.sync_custody import (  # noqa: E402
    CUSTODY_RECORD_FILENAME,
    makeSyncCustodyHook,
)
from src.pi.power.power_watch.tasks.sync_with_server import (  # noqa: E402
    SyncWithServerTask,
)
from src.pi.power.soc_calibration import (  # noqa: E402
    readSystemUptimeSeconds,
    resolveColdStartWindowSeconds,
)
from src.pi.splash.shutdown_state_emitter import (  # noqa: E402
    makeShutdownPhaseEmitter,
)
from src.pi.sync.backlog import countOutstandingRows  # noqa: E402
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

    Returns:
        The exact line to log -- prefixed with ARM_DECISION_PREFIX on both
        branches so one grep finds either.
    """
    evidence = (
        f"gpio={pldGpioPin} pld.available={pldAvailable} reads-power-present={readsPowerPresent}"
    )
    if armed and lastTransitionUtc:
        return (
            f"{ARM_DECISION_PREFIX} {ARM_DECISION_ARMED} (PROVEN) -- safe-shutdown "
            f"protection is ON and its detection path has been OBSERVED to fire "
            f"(last transition {lastTransitionUtc}). GPIO{pldGpioPin} PLD SSOT "
            f"arm self-check PASSED ({evidence}). A sustained external-power "
            f"loss will run the bounded pre-shutdown pipeline and then poweroff."
        )
    if armed:
        return (
            f"{ARM_DECISION_PREFIX} {ARM_DECISION_ARMED} (UNPROVEN) -- safe-shutdown "
            f"protection is ON, but its detection path has NEVER been observed to "
            f"fire. GPIO{pldGpioPin} PLD SSOT arm self-check PASSED ({evidence}) "
            f"-- that proves the pin READS, not that it CHANGES. No power-loss "
            f"transition has ever been witnessed on this install, and a pin that "
            f"reads but has never been seen to move is indistinguishable from a "
            f"wire that is not connected."
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
    budgetSec: float = 0.0,
    monotonicFn=time.monotonic,
):
    """Adapt SyncClient.forcePush() to the SyncWithServerTask runSync contract.

    forcePush() is the documented pre-`systemctl poweroff` flush (US-216): it
    never raises on a sync failure -- it returns a PushSummary. Map it to the
    raise-on-transient contract the task expects:
      * disabled        -> benign no-op (return; nothing to sync)
      * tablesFailed > 0 -> transport failure, retries exhausted -> RuntimeError
                            (TRANSIENT: the task retries once, then records
                            SYNC_FAILED_AFTER_RETRY and continues)
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

    THE BOUND IS MEASURED, NOT INVENTED. An unbounded drain would fight the
    power budget the sequencer exists to respect (conditionalOutcome 1), so a
    further pass only starts when the budget still has room for one that lasts
    as long as the LAST one did. That derives the bound from the observed link
    speed and ``perTaskTimeoutSec`` -- both already grounded -- rather than
    inventing a new tunable or a pass count. A slow link self-limits; a fast
    one drains fully.

    The first pass ALWAYS runs, so the behaviour can never regress below the
    single-pass drain this replaced.

    Args:
        syncClient: The live SyncClient.
        backlogReader: Zero-arg reader returning a
            :class:`~src.pi.sync.backlog.SyncBacklog`. ``None`` disables
            multi-pass entirely (exactly one pass -- the legacy path).
        budgetSec: Wall-clock budget for the whole drain. Production passes the
            shutdown path's own ``perTaskTimeoutSec``.
        monotonicFn: DI monotonic clock.
    """

    def runSync() -> None:
        # The clock is read exactly ONCE per pass: `now` is both the end of the
        # pass just finished and the start of the next one, so `passElapsed` is
        # real push time and never accumulates bookkeeping reads.
        now = monotonicFn()
        deadline = now + budgetSec
        passes = 0
        while True:
            passStart = now
            summary = syncClient.forcePush()
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
                # evidence that another pass would help.
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
            now = monotonicFn()
            passElapsed = now - passStart
            if now + passElapsed > deadline:
                logger.warning(
                    "powerwatch sync: drain BOUNDED after %d pass(es) with "
                    "%d row(s) still outstanding -- another pass (~%.1fs) does "
                    "not fit the remaining shutdown budget",
                    passes,
                    backlog.total,
                    passElapsed,
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


def buildV1Tasks(syncTask: SyncWithServerTask) -> list:
    """The ordered V1 ShutdownTask list (the plugin-seam registry, SS-T6).

    V1 ships **exactly one** task -- ``SyncWithServerTask`` -- per the locked
    Option A scope (spec sec 9). This function is the **SINGLE EDIT POINT**
    for future plugin tasks (e.g. update-check, staged apply-decision): a new
    task appends here and that is the ONLY production change. ``ShutdownSequencer``
    and ``runPipeline`` are untouched when new tasks land.

    The order matters -- tasks run sequentially under the bounded pipeline,
    each within its own per-task timeout. Sync first is V1's chosen ordering
    (CIO directive: best-effort sync of the local drive log before poweroff).
    """
    return [syncTask]


def buildDrainCloseHook(
    *,
    config: dict,
    upsResolver,
    uptimeReader=None,
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
    )

    def _closeDrain() -> None:
        # The writer swallows its own faults (it must never break a poweroff);
        # the sequencer guards this call as well -- belt and braces on the one
        # path where a raise would be worst.
        writer.closeOpenDrainEvent(reason=CLOSE_REASON_SHUTDOWN)

    return _closeDrain


def _runOneShotForTest(
    *,
    outcomePath: str,
    perTaskTimeoutSec: float,
    totalWindowCapSec: float,
    vcellFloorVolts: float,
) -> int:
    """PW_TEST_ONESHOT hook: exercise the REAL import + controller/pipeline/
    task/outcome chain EXACTLY as systemd invokes the entrypoint, but WITHOUT
    real I2C, network, or poweroff.

    Active ONLY when the env var is set (production path never reaches here).
    This is the institutionalized V0.27.12-DOA guard: a missing/renamed import
    in this module's transitive graph fails this test loudly because it runs
    the real `python -m src.pi.power.power_watch` under the unit's PYTHONPATH.

    Deterministic scenario: server reachable, sync raises (transient) on both
    the call and the retry -> SYNC_FAILED_AFTER_RETRY -> a real outcome record
    is produced; the bounded controller then reaches the (stubbed) poweroff.
    """

    def _failingSync() -> None:
        raise RuntimeError("PW_TEST_ONESHOT injected transient sync failure")

    def _writeRecord(kindDetail: object) -> None:
        kind, detail = kindDetail  # type: ignore[misc]
        writeOutcomeRecord(outcomePath, kind, detail=str(detail), task="sync_with_server")

    def _stubPoweroff() -> None:
        marker = os.environ["PW_TEST_POWEROFF_MARKER"]
        Path(marker).write_text("poweroff-invoked", encoding="utf-8")

    syncTask = SyncWithServerTask(
        serverReachable=lambda: True,
        runSync=_failingSync,
        writeRecord=_writeRecord,
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
    """
    # Edge-triggered on a present->lost transition via the SSOT provider during
    # boot-grace (kept edge-only there so the "ignoring" log fires once per
    # fresh in-grace transient). Post-boot-grace fires on level (lost AND not
    # firedAlready) so a level-stuck LOW state cannot leave the sequencer blind.
    prevLost = isPowerLostFn()
    firedAlready = False
    while not stop.wait(timeout=pldPollSec):
        lost = isPowerLostFn()
        graceElapsed = monotonicFn() - serviceStartMono
        if graceElapsed < bootGraceSec:
            if lost and not prevLost:
                logger.warning(
                    "powerwatch: PLD power-loss %.0fs into boot-grace (%.0fs) -- ignoring",
                    graceElapsed,
                    bootGraceSec,
                )
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
    poweroffTimeoutSec = float(pw_cfg["poweroffTimeoutSec"])
    bootGraceSec = float(pw_cfg["bootGraceSec"])
    smoothingSec = float(pw_cfg["smoothingSec"])
    smoothingPollSec = float(pw_cfg["smoothingPollSec"])
    pldGpioPin = int(pw_cfg["pldGpioPin"])
    pldPowerPresentHigh = bool(pw_cfg["pldPowerPresentHigh"])
    pldPollSec = float(pw_cfg["pldPollSec"])

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

    def writeRecord(kindDetail: object) -> None:
        kind, detail = kindDetail  # type: ignore[misc]
        writeOutcomeRecord(outcomePath, kind, detail=str(detail), task="sync_with_server")

    # US-621: ONE backlog reader, shared by the drain (to decide whether
    # another pass is worth making) and by the custody record (to state what
    # remains). Two readers could disagree, and a shutdown that pushed until
    # "empty" then recorded a different number would be worse than either.
    def readSyncBacklog():
        return countOutstandingRows(dbPath, busyTimeoutSec=perTaskTimeoutSec)

    syncTask = SyncWithServerTask(
        serverReachable=detector.isServerReachable,
        runSync=_buildRunSync(
            syncClient,
            backlogReader=readSyncBacklog,
            budgetSec=perTaskTimeoutSec,
        ),
        writeRecord=writeRecord,
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
    drainCloseFn = buildDrainCloseHook(
        config=config,
        upsResolver=lambda: monitor,
    )

    # US-621 [same placement argument as US-526 Option C]: the custody record
    # is a PRE-POWEROFF hook, NOT a pipeline ShutdownTask. Two reasons, both
    # measured. (1) The VCELL-floor fast path SKIPS the pipeline entirely
    # (controller.py) -- and that run-to-cutoff shutdown is exactly the one
    # carrying the most undelivered rows, so a task-based record would miss
    # every case that matters most. (2) runPipeline ABANDONS a task that
    # exceeds perTaskTimeoutSec, and an abandoned thread writes nothing; a
    # custody record that disappears precisely when the queue is too big to
    # drain would be silent in its own failure mode.
    custodyFn = makeSyncCustodyHook(
        recordPath=os.path.join(os.path.dirname(dbPath), CUSTODY_RECORD_FILENAME),
        backlogReader=readSyncBacklog,
    )
    prePowerOffFn = composePrePowerOffHooks(drainCloseFn, custodyFn)

    shutdownSequencer = ShutdownSequencer(
        isOnBattery=provider.isPowerLost,
        vcell=monitor.getVcell,
        runPipelineFn=lambda: runPipeline(
            buildV1Tasks(syncTask), perTaskTimeoutSec=perTaskTimeoutSec
        ),
        powerOffFn=lambda: subprocess.run(
            ["systemctl", "poweroff"], timeout=poweroffTimeoutSec, check=False
        ),
        vcellFloor=vcellFloorVolts,
        totalCapSec=totalWindowCapSec,
        smoothingSec=smoothingSec,
        smoothingPollSec=smoothingPollSec,
        phaseEmitFn=phaseEmitFn,
        prePowerOffFn=prePowerOffFn,
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
    # self-check actually established -- that the pin READS.
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
        # is cheap insurance. Loop body extracted into _runPldWatchLoop for
        # unit-test access (US-344 F-7 fix).
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
