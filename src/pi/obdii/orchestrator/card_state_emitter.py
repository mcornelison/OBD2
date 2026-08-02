################################################################################
# File Name: card_state_emitter.py
# Purpose/Description: US-480-a carousel card-state emitter mixin for the
#   orchestrator (F-092 system-status / F-097 battery-health / F-111 dtc). The
#   F-092/097/111 emitter code shipped but was never wired to execute -- only
#   eclipse-boot-state.service ran, so /run/eclipse-obd/states/ held only
#   boot-state and the carousel cards starved (the NA/unavailable wall behind
#   the phantom "Check Engine"). This mixin constructs the three emitters and
#   INVOKES them in-process from the orchestrator's runLoop.
#
#   Run-model (Atlas Q-1, load-bearing): the OBD-fed emitters (system-status +
#   dtc) MUST be orchestrator-invoked inside THIS process -- the single owner
#   of the one ObdConnection -- never a standalone systemd unit that would open
#   a SECOND connection to the non-thread-safe python-obd port and re-introduce
#   the A-17 race US-474 just closed. battery-health reads the MAX17048 (I2C,
#   not the OBD port) so it is safe either way; it runs in-process here for
#   cadence coherence. The emitters are PURE consumers of data the orchestrator
#   already holds (ssot-design-pattern.md): this mixin opens no connection and
#   fabricates no reading -- an unreadable source emits a typed-NA (available:
#   false), never a stale or invented value (honest-instrument).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-21    | Ralph (Rex)  | Initial -- US-480-a wire the F-092/097/111
#               |              | emitters to RUN (orchestrator-invoked, Atlas Q-1).
# ================================================================================
################################################################################

"""Card-state emitter mixin: wire the carousel emitters to run (US-480-a)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("pi.obdii.orchestrator")

# Repo-root-anchored default path to Spool's P1xxx severity SSOT markdown.
# This module lives at <repo>/src/pi/obdii/orchestrator/card_state_emitter.py,
# so parents[4] is the repo root.  loadP1xxxSeverityTable degrades to {} (never
# raises) when the file is absent -- un-tabled codes then show `unknown`
# severity, an honest degradation (deploy-install of the table is US-480-b).
_DEFAULT_SEVERITY_TABLE_PATH = str(
    Path(__file__).resolve().parents[4]
    / "offices" / "tuner" / "dsm-p1xxx-severity-table.md"
)

# Default tmpfs states dir (matches boot_state_emitter + the states-http unit).
_DEFAULT_STATES_DIR = "/run/eclipse-obd/states"


class CardStateEmitterMixin:
    """Mixin: construct + orchestrator-invoke the carousel card-state emitters.

    Assumes the composing class (:class:`ApplicationOrchestrator`) provides:
    ``self._config``, ``self._connection``, ``self._driveDetector``,
    ``self._hardwareManager``, and the US-480-a state attributes set in
    ``__init__`` (``self._systemStatusEmitter`` etc.). ``self.
    _powerSourceProvider`` (the US-502 power-source SSOT) is read through
    ``getattr`` because lifecycle only creates it once hardware starts, which
    is AFTER this mixin's emitters are constructed.
    """

    # These are declared/initialized on the core class; typed here for mypy.
    _config: dict[str, Any]
    _connection: Any | None
    _driveDetector: Any | None
    _hardwareManager: Any | None
    _systemStatusEmitter: Any | None
    _batteryHealthEmitter: Any | None
    _dtcEmitter: Any | None
    _cardPowerModeProvider: Any | None
    _cardStateEmitEnabled: bool
    _cardStateEmitInterval: float
    _cardSyncStaleThresholdS: float
    _lastCardStateEmitTime: datetime | None
    _lastSyncOkTsIso: str | None
    _lastSyncRows: int

    # ------------------------------------------------------------------ setup

    def _initializeCardStateEmitters(self) -> None:
        """Construct the three emitters + write the initial honest dtc state.

        Called from ``lifecycle._initializeAllComponents`` after the connection,
        hardware, drive-detector, sync-client and power-monitor exist. Best-
        effort: a construction failure logs + leaves the emitters None so the
        orchestrator boots regardless (the dashboard hook never blocks boot).
        """
        if not self._cardStateEmitEnabled:
            logger.info(
                "Card-state emitters disabled (pi.dashboard.stateEmitEnabled=false)"
            )
            return

        dtcConfig = self._config.get("pi", {}).get("dtc", {})
        statesDir = (
            self._config.get("pi", {}).get("splash", {}).get(
                "statesDir", _DEFAULT_STATES_DIR
            )
        )
        severityTablePath = dtcConfig.get(
            "severityTablePath", _DEFAULT_SEVERITY_TABLE_PATH
        )
        try:
            from pi.power.power_mode_provider import PowerModeProvider
            from pi.splash.battery_health_emitter import makeBatteryHealthEmitter
            from pi.splash.dtc_emitter import makeDtcEmitter
            from pi.splash.dtc_severity_table import loadP1xxxSeverityTable
            from pi.splash.system_status_emitter import makeSystemStatusEmitter

            self._systemStatusEmitter = makeSystemStatusEmitter(
                statesDir,
                syncStaleThresholdS=self._cardSyncStaleThresholdS,
            )
            self._batteryHealthEmitter = makeBatteryHealthEmitter(statesDir)
            severityTable = loadP1xxxSeverityTable(severityTablePath)
            self._dtcEmitter = makeDtcEmitter(
                statesDir, severityTable=severityTable
            )
            # Deployment-context provider (car/wall/unknown) for the power tile.
            self._cardPowerModeProvider = PowerModeProvider.fromConfig(self._config)
            # AC5: write an HONEST initial `dtc` state at boot so a parked-from-
            # boot Pi (no KOEO read yet) renders "DTC not read since key-off"
            # instead of starving -- kills the phantom-Check-Engine backdrop.
            self._emitInitialDtcState()
            logger.info(
                "Card-state emitters wired (system-status/battery-health/dtc); "
                "states_dir=%s severity_table=%s",
                statesDir, severityTablePath,
            )
        except Exception as e:  # noqa: BLE001 -- dashboard wiring must not fail boot
            logger.warning(
                "Card-state emitter init skipped: %s (type=%s)",
                e, type(e).__name__,
            )
            self._systemStatusEmitter = None
            self._batteryHealthEmitter = None
            self._dtcEmitter = None
            self._cardPowerModeProvider = None

    def _emitInitialDtcState(self) -> None:
        """Write the boot-time honest `dtc` state (dtcAvailable=False).

        No KOEO read has run yet at boot, so the DTC source is unavailable --
        the emitter writes a FRESH empty state (no codes, no takeover trigger)
        with ``source.dtc.available=false``. The carousel renders "DTC not read
        since key-off" (US-481 faults line) and the US-405 takeover stays hidden
        -- never a fabricated all-clear, never a phantom Check Engine.
        """
        emitter = self._dtcEmitter
        if emitter is None:
            return
        emitter(codes=[], mil=False, newSinceTs=None, dtcAvailable=False)

    def _recordSyncOutcome(self, rowsPushed: int) -> None:
        """Cache the REAL last-sync outcome for the system-status sync tile.

        Called from the sync trigger paths only AFTER a push completed past the
        route gate -- so "last synced" advances only when data actually left the
        Pi (honest: a route-gated no-op tick never claims a sync).
        """
        self._lastSyncOkTsIso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._lastSyncRows = int(rowsPushed)

    # ------------------------------------------------------------- cadence

    def _maybeEmitCardStates(self) -> bool:
        """Emit system-status + battery-health when the cadence has elapsed.

        Called once per runLoop pass. Cheap fast-path: a single ``datetime``
        subtraction + threshold compare, short-circuiting when not due. Each
        emit is exception-isolated (the emitters swallow their own write
        errors, but the DATA GATHERING -- getStatus / I2C / providers -- can
        raise) so a dashboard hiccup never crashes the loop.

        Returns:
            True when this tick actually emitted; False when disabled or not due.
        """
        if not self._cardStateEmitEnabled:
            return False
        now = datetime.now()
        last = self._lastCardStateEmitTime
        if last is not None:
            if (now - last).total_seconds() < self._cardStateEmitInterval:
                return False
        self._lastCardStateEmitTime = now

        try:
            self._emitSystemStatusState()
        except Exception as e:  # noqa: BLE001 -- never crash the loop
            logger.debug("system-status card emit failed: %s", e)
        try:
            self._emitBatteryHealthState()
        except Exception as e:  # noqa: BLE001 -- never crash the loop
            logger.debug("battery-health card emit failed: %s", e)
        return True

    # -------------------------------------------------------- system-status

    def _emitSystemStatusState(self) -> None:
        """Gather truthful link/sync/power/drive readings + emit system-status."""
        emitter = self._systemStatusEmitter
        if emitter is None:
            return
        from pi.splash.source_availability import REASON_OBD_OFF

        obdLinkState, obdRetries, obdAvailable = self._gatherObdLinkState()
        powerMode, powerSource = self._gatherPowerState()
        driveState, driveId = self._gatherDriveState()
        emitter(
            obdLinkState=obdLinkState,
            obdRetries=obdRetries,
            # No per-read timestamp is tracked at this layer, so we do not claim
            # a "seconds since last read" we cannot measure (honest-instrument).
            obdLastSeenS=None,
            syncLastOkTs=self._lastSyncOkTsIso,
            syncRows=self._lastSyncRows,
            # Pending-row count is not separately tracked here; the load-bearing
            # un-backed-up-data signal is the stale-while-driving amber flag the
            # emitter computes from syncLastOkTs vs now (TD: exact pending count).
            syncPending=0,
            powerMode=powerMode,
            powerSource=powerSource,
            driveState=driveState,
            driveId=driveId,
            obdAvailable=obdAvailable,
            obdUnavailableReason=None if obdAvailable else REASON_OBD_OFF,
        )

    def _gatherObdLinkState(self) -> tuple[str, int, bool]:
        """Map the ObdConnection state -> (linkState, retries, available).

        available is False (US-429 typed NA) only when the OBD source is ABSENT
        -- i.e. we have NEVER connected (totalConnections == 0): car off / no
        dongle / bench. A dropped-but-previously-seen link is `down` but still
        AVAILABLE (we are retrying a real car). Connected -> linked; connecting/
        reconnecting -> reconnecting. A missing connection is unavailable.
        """
        from pi.splash.system_status_emitter import (
            OBD_DOWN,
            OBD_LINKED,
            OBD_RECONNECTING,
        )

        conn = self._connection
        if conn is None:
            return (OBD_DOWN, 0, False)
        try:
            status = conn.getStatus()
        except Exception:  # noqa: BLE001 -- unreadable status -> unavailable
            return (OBD_DOWN, 0, False)

        connected = bool(getattr(status, "connected", False))
        retries = int(getattr(status, "retryCount", 0) or 0)
        totalConns = int(getattr(status, "totalConnections", 0) or 0)
        rawState = getattr(status, "state", None)
        stateStr = str(getattr(rawState, "value", rawState) or "").lower()

        if connected:
            return (OBD_LINKED, retries, True)
        if "reconnect" in stateStr or "connecting" in stateStr:
            return (OBD_RECONNECTING, retries, True)
        # disconnected / error: available iff we have EVER seen this car.
        return (OBD_DOWN, retries, totalConns > 0)

    def _gatherPowerState(self) -> tuple[str, str]:
        """Return (powerMode, powerSource) from the two SSOT providers.

        Two different facts, two different providers (architecture.md §2):
        powerMode = deployment context (car/wall/unknown) from PowerModeProvider
        (static config); powerSource = AC-vs-battery from PowerSourceProvider
        (X1209 GPIO6 PLD). Neither is ever inferred from the other.
        """
        powerMode = "unknown"
        provider = self._cardPowerModeProvider
        if provider is not None:
            try:
                powerMode = str(provider.getPowerMode())
            except Exception:  # noqa: BLE001 -- honest unknown on read failure
                powerMode = "unknown"

        return (powerMode, self._gatherPowerSource())

    def _gatherPowerSource(self) -> str:
        """Return external/battery/unknown from the power-source SSOT (US-502).

        Reads ``PowerSourceProvider`` -- the ONE authoritative acquisition path
        for the AC-vs-battery fact -- which ``lifecycle._subscribePowerMonitor
        ToPowerSourceProvider`` builds over the X1209 GPIO6 PLD line. The tile
        previously read ``PowerMonitor.readPowerStatus()``, whose reader is
        never configured in the orchestrator: it returned None forever, so the
        tile said "unavailable" and the header bolt stayed gray while the real
        fact was already flowing to ``power_log``. PowerMonitor is NOT consulted
        here -- a second path could disagree with GPIO6, which is exactly the
        SSOT violation the design gate forbids.

        LAZY on purpose: this mixin's emitters are built in
        ``_initializeAllComponents``, but the provider does not exist until
        ``_startHardwareManager`` runs later, so a reference captured at init
        time would be None for the life of the process.

        UI uncertainty policy: an UNREADABLE line resolves to ``unknown``, not
        to the provider's non-bricking "treat as present" default -- a display
        must never show a confident source it cannot actually read.
        """
        source = getattr(self, "_powerSourceProvider", None)
        if source is None:
            return "unknown"
        try:
            if not source.isAvailable:
                return "unknown"
            return "external" if source.isExternalPowerPresent() else "battery"
        except Exception:  # noqa: BLE001 -- honest unknown on read failure
            return "unknown"

    def _gatherDriveState(self) -> tuple[str, int | None]:
        """Return (driveState, driveId): recording+id while a drive runs, else idle."""
        dd = self._driveDetector
        recording = False
        if dd is not None:
            try:
                recording = bool(dd.isDriving())
            except Exception:  # noqa: BLE001 -- unknown -> idle (fail calm)
                recording = False
        if not recording:
            return ("idle", None)
        driveId: int | None = None
        try:
            from pi.obdii.drive_id import getCurrentDriveId

            driveId = getCurrentDriveId()
        except Exception:  # noqa: BLE001 -- id unknown -> None (still recording)
            driveId = None
        return ("recording", driveId)

    # ------------------------------------------------------- battery-health

    def _emitBatteryHealthState(self) -> None:
        """Gather live MAX17048 readings + emit battery-health.

        The UpsMonitor (MAX17048 fuel gauge) lives on the HardwareManager. When
        it is absent (bench / hardware disabled) or unreadable, the card emits a
        typed-NA (upsAvailable=False) -- honest, never a stale/invented reading.
        When present, live vcell/soc/crate are REAL values; the history/verdict
        fields (rested-VCELL trend, weak events, last-health-check, Spool health
        verdict) have no in-process reader yet, so they degrade honestly: health
        = "unknown" (renders neutral, NEVER a fabricated green), lastHealthCheck
        = never, no fabricated ladder/full-charge claim.
        """
        emitter = self._batteryHealthEmitter
        if emitter is None:
            return

        hw = self._hardwareManager
        ups = getattr(hw, "upsMonitor", None) if hw is not None else None
        if ups is None:
            emitter(**self._batteryHealthKwargs(upsAvailable=False))
            return
        try:
            vcellV = float(ups.getBatteryVoltage())
            soc = int(ups.getBatteryPercentage())
            crate = ups.getChargeRatePercentPerHour()
        except Exception:  # noqa: BLE001 -- gauge unreadable -> typed NA
            emitter(**self._batteryHealthKwargs(upsAvailable=False))
            return

        crateF = float(crate) if crate is not None else None
        _, powerSource = self._gatherPowerState()
        onExternal = powerSource == "external"
        charging = crateF is not None and crateF > 0
        # draining = wall power lost AND the pack is actually discharging (A-6
        # only lets the failsafe ladder render while draining; we carry no
        # ladder data, so ladder stays None regardless).
        draining = (not onExternal) and (crateF is not None and crateF < 0)
        emitter(
            **self._batteryHealthKwargs(
                upsAvailable=True,
                vcellV=vcellV,
                soc=soc,
                crate=crateF,
                charging=charging,
                draining=draining,
            )
        )

    @staticmethod
    def _batteryHealthKwargs(
        *,
        upsAvailable: bool,
        vcellV: float | None = None,
        soc: int | None = None,
        crate: float | None = None,
        charging: bool = False,
        draining: bool = False,
    ) -> dict[str, Any]:
        """Assemble the battery-health emit kwargs with HONEST unknown defaults.

        Every field with no in-process producer is a conservative honest value:
        no fabricated Spool verdict (health="unknown" -> neutral), no claimed
        calibration, no claimed full-charge, no rested history, no ladder,
        last-health-check "never". Only the live gauge reads carry real data.
        """
        return {
            "vcellV": vcellV,
            "soc": soc,
            "socCalibrated": False,
            "crate": crate,
            "charging": charging,
            "draining": draining,
            "restedVcellV": None,
            "weakEvents30d": 0,
            "restedHistory": [],
            "health": "unknown",
            "fullChargeReached": False,
            "runtimeToCutoffS": None,
            "ambientTempC": None,
            "lastHealthCheckTs": None,
            "ladder": None,
            "upsAvailable": upsAvailable,
        }
