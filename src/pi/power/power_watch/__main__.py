################################################################################
# File Name: __main__.py
# Purpose/Description: Phase-2 power-watch service entrypoint
#                      (`python -m src.pi.power.power_watch`). Wires the proven
#                      UpsMonitor detector, the documented pre-shutdown sync
#                      (SyncClient.forcePush), and the home-network reachability
#                      probe into the bounded PowerWatch controller, then blocks
#                      while the UpsMonitor polling thread pushes BATTERY
#                      transitions in.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T6 service entrypoint + real wiring.
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
from src.pi.hardware.ups_monitor import PowerSource, UpsMonitor  # noqa: E402
from src.pi.network.home_detector import HomeNetworkDetector  # noqa: E402
from src.pi.power.power_watch.controller import PowerWatch  # noqa: E402
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


def _buildIsOnBattery(monitor: UpsMonitor):
    """Production isOnBattery: getPowerSource() == BATTERY.

    The controller does NOT wrap isOnBattery() in try/except (spec: only the
    VCELL read is wrapped). A failed power-state read therefore must fail to
    the SAFE direction here: treat it as STILL on battery so the bounded
    graceful poweroff proceeds. Spuriously reporting "power returned" would
    abort the shutdown and strand a draining Pi -- the dangerous direction.
    """

    def isOnBattery() -> bool:
        try:
            return monitor.getPowerSource() == PowerSource.BATTERY
        except Exception as exc:  # noqa: BLE001 -- uncertain -> safe (still on battery)
            logger.error(
                "powerwatch: power-source read failed (%s) -- assume on battery",
                exc,
            )
            return True

    return isOnBattery


def main(argv: list[str] | None = None) -> int:
    """Build the real PowerWatch and block while UpsMonitor pushes transitions."""
    args = _parseArgs(argv)
    config = loadConfigWithSecrets(args.config, args.env_file)
    config = ConfigValidator().validate(config)

    pw_cfg = config["pi"]["powerWatch"]
    perTaskTimeoutSec = float(pw_cfg["perTaskTimeoutSec"])
    totalWindowCapSec = float(pw_cfg["totalWindowCapSec"])
    vcellFloorVolts = float(pw_cfg["vcellFloorVolts"])
    poweroffTimeoutSec = float(pw_cfg["poweroffTimeoutSec"])

    # Outcome record sits next to the SQLite db (the existing data/ dir) --
    # reuse pi.database.path rather than hardcode or add an un-specced key.
    dbPath = config["pi"]["database"]["path"]
    outcomePath = os.path.join(
        os.path.dirname(dbPath), "powerwatch_outcome.json"
    )

    companion = config.get("pi", {}).get("companionService", {}) or {}
    apiKey = getSecret(str(companion.get("apiKeyEnv") or "COMPANION_API_KEY"))

    monitor = UpsMonitor()
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

    powerWatch = PowerWatch(
        isOnBattery=_buildIsOnBattery(monitor),
        vcell=monitor.getVcell,
        runPipelineFn=lambda: runPipeline(
            [syncTask], perTaskTimeoutSec=perTaskTimeoutSec
        ),
        powerOffFn=lambda: subprocess.run(
            ["systemctl", "poweroff"], timeout=poweroffTimeoutSec, check=False
        ),
        vcellFloor=vcellFloorVolts,
        totalCapSec=totalWindowCapSec,
    )

    # One handleOnBattery() at a time; a future BATTERY transition after a
    # power-return resume may legitimately re-fire it.
    handleLock = threading.Lock()

    def onSourceChange(newSource: PowerSource) -> None:
        if newSource != PowerSource.BATTERY:
            return
        if not handleLock.acquire(blocking=False):
            logger.info("powerwatch: already handling on-battery -- ignoring")
            return
        try:
            logger.warning(
                "powerwatch: sustained-on-battery -- entering pre-shutdown window"
            )
            powerWatch.handleOnBattery()
        finally:
            handleLock.release()

    monitor.registerSourceChangeCallback(onSourceChange)
    monitor.startPolling()
    logger.info(
        "powerwatch service up: perTask=%.0fs totalCap=%.0fs vcellFloor=%.2fV",
        perTaskTimeoutSec, totalWindowCapSec, vcellFloorVolts,
    )

    # Block forever -- the UpsMonitor polling thread is a daemon, so the main
    # thread must stay alive for the service to keep watching.
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
