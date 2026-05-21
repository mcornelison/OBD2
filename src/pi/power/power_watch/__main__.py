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
from src.pi.hardware.pld_sensor import PldSensor  # noqa: E402
from src.pi.hardware.ups_monitor import UpsMonitor  # noqa: E402
from src.pi.network.home_detector import HomeNetworkDetector  # noqa: E402
from src.pi.power.power_source_provider import PowerSourceProvider  # noqa: E402
from src.pi.power.power_watch.controller import ShutdownSequencer  # noqa: E402
from src.pi.power.power_watch.outcome import writeOutcomeRecord  # noqa: E402
from src.pi.power.power_watch.pipeline import runPipeline  # noqa: E402
from src.pi.power.power_watch.tasks.sync_with_server import (  # noqa: E402
    SyncWithServerTask,
)
from src.pi.sync.client import SyncClient  # noqa: E402

logger = logging.getLogger(__name__)


def _parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase-2 power-watch service (bounded pre-shutdown pipeline)."
    )
    parser.add_argument("--config", default=_DEFAULT_CONFIG)
    parser.add_argument("--env-file", default=_DEFAULT_ENV)
    return parser.parse_args(argv)


def _buildRunSync(syncClient: SyncClient):
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
    """

    def runSync() -> None:
        summary = syncClient.forcePush()
        if summary.disabled:
            logger.info("powerwatch sync: companion service disabled -- no-op")
            return
        if summary.tablesFailed > 0:
            raise RuntimeError(
                f"{summary.tablesFailed} table(s) failed to sync after retries"
            )

    return runSync


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
        writeOutcomeRecord(
            outcomePath, kind, detail=str(detail), task="sync_with_server"
        )

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
                    "powerwatch: PLD power-loss %.0fs into boot-grace "
                    "(%.0fs) -- ignoring", graceElapsed, bootGraceSec,
                )
        elif lost and not firedAlready:
            if handleLock.acquire(blocking=False):
                try:
                    logger.warning(
                        "powerwatch: GPIO%d PLD => external power LOST -- "
                        "entering bounded pre-shutdown window", pldGpioPin,
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
    outcomePath = os.path.join(
        os.path.dirname(dbPath), "powerwatch_outcome.json"
    )

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
        writeOutcomeRecord(
            outcomePath, kind, detail=str(detail), task="sync_with_server"
        )

    syncTask = SyncWithServerTask(
        serverReachable=detector.isServerReachable,
        runSync=_buildRunSync(syncClient),
        writeRecord=writeRecord,
    )

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
    if not provider.startupArmCheck():
        logger.error(
            "powerwatch: PowerSourceProvider GPIO%d arm self-check FAILED "
            "(pld.available=%s, reads-power-present=%s). The Pi booted on a "
            "live feed so GPIO%d must read power-present at startup; it does "
            "not. REFUSING to arm -- service stays up, OBD collector "
            "unaffected, NOTHING will be powered off. Fix "
            "pi.powerWatch.pldGpioPin / pldPowerPresentHigh and redeploy.",
            pldGpioPin, pld.isAvailable, pld.isExternalPowerPresent(), pldGpioPin,
        )
        threading.Event().wait()  # stay alive, disarmed
        return 0

    monitor.startPolling()  # vcell-backstop telemetry only; NOT the trigger
    logger.info(
        "powerwatch service up (GPIO%d PLD SSOT trigger): perTask=%.0fs "
        "totalCap=%.0fs vcellFloor=%.2fV smoothing=%.0fs bootGrace=%.0fs",
        pldGpioPin, perTaskTimeoutSec, totalWindowCapSec, vcellFloorVolts,
        smoothingSec, bootGraceSec,
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

    # Block forever -- the watch + UpsMonitor threads are daemons.
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
