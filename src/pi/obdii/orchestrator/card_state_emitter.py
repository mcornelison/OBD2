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
# 2026-08-02    | Ralph (Rex)  | US-518: re-anchor the derived altitude to the
#               |              | home elevation from _recordSyncOutcome -- the
#               |              | one seam both sync-success paths converge on.
# ================================================================================
################################################################################

"""Card-state emitter mixin: wire the carousel emitters to run (US-480-a)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("pi.obdii.orchestrator")

# Package-relative default path to the P1xxx severity SSOT markdown.
# This module lives at <repo>/src/pi/obdii/orchestrator/card_state_emitter.py,
# so parents[2] is the `pi` package root and the table ships INSIDE the tier
# it serves.  Previously this anchored on parents[4] (the repo root) and
# reached into offices/tuner/ -- an agent workspace that is not part of the
# deployed product, so the table was only present by accident of the deploy
# rsync copying the whole tree.
_DEFAULT_SEVERITY_TABLE_PATH = str(
    Path(__file__).resolve().parents[2]
    / "resources" / "dsm-p1xxx-severity-table.md"
)

# Default tmpfs states dir (matches boot_state_emitter + the states-http unit).
_DEFAULT_STATES_DIR = "/run/eclipse-obd/states"

# US-632: "no reason has been observed yet" -- distinct from an observed None
# (which means the verdict RESOLVED). A plain None default would swallow the
# first log line whenever the producer starts out resolved and later degrades.
_REASON_UNSET: Any = object()


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
    # US-533: config.json's path, when the composer knows it. A CLASS default of
    # None (rather than a getattr) so every composer -- including the standalone
    # ones that never had a path -- keeps working while the orchestrator sets a
    # real value; see _initializeCardStateEmitters for what it buys.
    _configPath: str | None = None
    _cardStateEmitEnabled: bool
    _cardStateEmitInterval: float
    _cardSyncStaleThresholdS: float
    _lastCardStateEmitTime: datetime | None
    _lastSyncOkTsIso: str | None
    _lastSyncRows: int
    # US-518: built lazily by _getAltitudeAnchor, never in __init__ -- declared
    # here for mypy only. Read through getattr so an absent attribute is fine.
    _altitudeAnchor: Any | None
    # US-632: last battery-health unknown-reason logged, so the journal records
    # transitions rather than one line per emit tick. A CLASS default (not an
    # __init__ assignment) so every existing composer keeps working unchanged.
    _lastBatteryHealthReason: Any = _REASON_UNSET

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
            if not severityTable:
                # The table now ships inside src/pi/resources/, so an empty
                # parse is a broken deploy, not the expected "not installed
                # yet" state it was when this lived under offices/.  Still
                # fail soft -- a missing table must never take the display
                # down mid-drive, and un-tabled codes render an honest
                # `unknown` -- but say so LOUDLY instead of silently.
                logger.error(
                    "P1xxx severity table empty/missing at %s -- DTC severities "
                    "will render `unknown`; check the deploy",
                    severityTablePath,
                )
            self._dtcEmitter = makeDtcEmitter(
                statesDir, severityTable=severityTable
            )
            # Deployment-context provider (car/wall/unknown) for the power tile.
            #
            # US-533: prefer the LIVE source when we know where config.json is.
            # fromConfig() closes over the boot-time snapshot, so an operator
            # switching the F-126 power-mode control saw nothing change until
            # this service restarted -- and the band now labels that row
            # "applies now", which is only true because of this branch.
            # No path (standalone composers) -> the US-421 snapshot source:
            # degrade to stale, never to no power tile at all.
            if self._configPath:
                self._cardPowerModeProvider = PowerModeProvider.fromConfigPath(
                    self._configPath
                )
            else:
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
        # US-518 (WP-3, F-125): a reached server means the Pi is on the home
        # network, i.e. the car is home -- the verified "at home" event that
        # re-anchors the derived altitude. Hooked HERE rather than at the two
        # call sites in core.py on purpose: this is the one place both the
        # interval and drive-end paths converge, so a future third sync path
        # cannot silently skip the re-anchor (the US-512 "missing call site (b)"
        # failure mode).
        self._reanchorDerivedAltitude()

    # ------------------------------------------------------- US-518 altitude

    def _getAltitudeAnchor(self) -> Any | None:
        """Return the process-wide altitude accumulator, building it on demand.

        Built LAZILY here rather than in :meth:`_initializeCardStateEmitters`
        for two reasons: that method is gated on ``pi.dashboard.stateEmitEnabled``
        (drift control must not depend on a display flag), and lazy construction
        sidesteps the boot-order trap entirely -- there is no window in which a
        captured reference is None.

        Returns:
            The cached :class:`AltitudeAnchor`, or None if it cannot be built.
        """
        anchor = getattr(self, "_altitudeAnchor", None)
        if anchor is not None:
            return anchor
        try:
            from pi.location.altitude_anchor import AltitudeAnchor

            anchor = AltitudeAnchor.fromConfig(self._config)
        except Exception as e:  # noqa: BLE001 -- never break the sync path
            logger.debug("Altitude anchor unavailable: %s", e)
            return None
        self._altitudeAnchor = anchor
        return anchor

    def _reanchorDerivedAltitude(self) -> bool:
        """Re-anchor the derived altitude to home after a successful sync.

        Best-effort and fully exception-isolated: drift control is cosmetic,
        the sync is not, so a failure here can never turn a successful push
        into a reported failure (I-038 lesson).

        Returns:
            True when the altitude was re-anchored; False otherwise.
        """
        try:
            anchor = self._getAltitudeAnchor()
            if anchor is None:
                return False
            return bool(anchor.onSyncSuccess())
        except Exception as e:  # noqa: BLE001 -- sync must never fail on this
            logger.debug("Altitude re-anchor failed: %s", e)
            return False

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
            # US-564: NOT MEASURED HERE -> None, never 0. A pending-row count is
            # not tracked at this layer, and `0` is the single most reassuring
            # value this field can take -- "everything is backed up" -- so
            # emitting it was a confident claim about data safety that nobody
            # had checked. The load-bearing un-backed-up signal remains the
            # stale-while-driving amber flag the emitter derives from
            # syncLastOkTs. (TD: acquire a real pending count.)
            syncPending=None,
            powerMode=powerMode,
            powerSource=powerSource,
            driveState=driveState,
            driveId=driveId,
            lastDrive=self._gatherLastDriveSummary(),
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

    def _gatherLastDriveSummary(self) -> dict[str, Any] | None:
        """Read the most recent COMPLETED drive from Pi-local ``drive_summary``.

        A DIFFERENT fact from ``_gatherDriveState``, which reports the ACTIVE
        drive and is None whenever nothing is recording. That is precisely why
        the idle card read "No recent drive" permanently rather than only until
        the next drive: there was no producer for the completed-drive fact at
        all (US-505).

        The database is resolved through ``getattr`` AT USE TIME, never captured
        when the emitters are constructed. This sprint has hit that boot-order
        trap in US-501, US-502 and US-504b: the emitters are built in
        ``_initializeAllComponents`` while their dependencies land later, so a
        captured reference is None for the life of the process -- a permanently
        empty tile with fully green unit tests. Re-reading per tick also means a
        drive recorded while the orchestrator runs reaches the card without a
        service restart.

        Returns:
            The ``{"driveId", "startedAtTs"}`` block, or None when no real drive
            is on record / the log is unreadable (renders the honest
            "No recent drive").
        """
        try:
            from pi.obdii.last_drive_summary import readLastDriveSummary

            return readLastDriveSummary(
                database=getattr(self, "_database", None)
            ).toStatePayload()
        except Exception as e:  # noqa: BLE001 -- never block the emit loop
            logger.debug("last-drive summary unavailable: %s", e)
            return None

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
            # The verdict's source is the drain LOG, not the gauge, so a dead
            # MAX17048 must not blank a health history that is still real.
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

    def _gatherBatteryHealthVerdict(
        self,
    ) -> tuple[str, str | None, int | None, str | None]:
        """Read the US-504 verdict + last-health-check from battery_health_log.

        The database is resolved through ``getattr`` AT USE TIME, never captured
        when the emitters are constructed: ``_database`` is built earlier in the
        boot order today, but a captured reference is the exact trap US-501 and
        US-502 both hit this sprint, and the log also has to be RE-read each
        tick so a drain recorded while the orchestrator runs reaches the card
        without a restart.

        US-632 adds the fourth element, ``reason``. The verdict is recomputed on
        EVERY emit tick -- there is no separate health-producer unit or timer --
        so an `unknown` here means "we ran, just now, and cannot say", which is
        a different fact from "nothing has run since May". The reason is what
        carries that distinction.

        Returns:
            ``(verdict, lastHealthCheckTs, medianRuntimeS, reason)`` -- honest
            ``("unknown", None, None, <reason>)`` whenever the log is absent,
            unreadable, too thin (< 3 qualifying drains) or stale (> 90 days).
            ``reason`` is None only when the verdict actually resolved.
        """
        try:
            from pi.power.battery_health_verdict import (
                REASON_LOG_UNREADABLE,
                VERDICT_UNKNOWN,
                readBatteryHealthVerdict,
            )

            result = readBatteryHealthVerdict(
                database=getattr(self, "_database", None),
                nowIso=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        except Exception as e:  # noqa: BLE001 -- never block the emit loop
            logger.debug("battery-health verdict unavailable: %s", e)
            # The import itself failed, or the reader raised out. Either way the
            # producer could not read the log -- report that, not silence.
            return ("unknown", None, None, "log_unreadable")
        return (
            result.verdict or VERDICT_UNKNOWN,
            result.lastHealthCheckTs,
            result.medianRuntimeS,
            result.reason if result.verdict != VERDICT_UNKNOWN
            else (result.reason or REASON_LOG_UNREADABLE),
        )

    def _recordBatteryHealthReason(self, reason: str | None) -> None:
        """Log WHY the battery-health verdict is unknown, on CHANGE only.

        US-632's conditionalOutcome: "If the producer is scheduled but failing
        silently, that silent failure IS the defect -- record it where it can
        be seen." The reason cannot reach the state file from here (the
        ``battery-health`` payload is assembled in ``src/pi/splash/``, outside
        this bench's surface -- see BL-us632), so until that lands the journal
        is where it can be seen.

        On CHANGE only, deliberately: this runs on every emit tick, and an
        unconditional log line would make the producer a continuous journal
        writer. US-646 is an open story about exactly that cost, and US-644 is
        about a journal probe that already times out because the journal is too
        large. A steady state is not news; a transition is.
        """
        if reason == getattr(self, "_lastBatteryHealthReason", _REASON_UNSET):
            return
        self._lastBatteryHealthReason = reason
        if reason is None:
            logger.info("battery-health verdict resolved (reason cleared)")
        else:
            logger.warning(
                "battery-health verdict is unknown: %s "
                "(the verdict producer DID run -- it recomputes every emit "
                "tick; this names what it could not conclude)",
                reason,
            )

    def _batteryHealthKwargs(
        self,
        *,
        upsAvailable: bool,
        vcellV: float | None = None,
        soc: int | None = None,
        crate: float | None = None,
        charging: bool = False,
        draining: bool = False,
    ) -> dict[str, Any]:
        """Assemble the battery-health emit kwargs with HONEST unknown defaults.

        ``health`` / ``lastHealthCheckTs`` / ``runtimeToCutoffS`` come from the
        US-504 ``battery_health_log`` producer (Spool [EXACT] spec) and are
        ``unknown`` / null whenever it has nothing real to say. Every remaining
        field still has no in-process producer and stays a conservative honest
        value: no claimed calibration, no claimed full-charge, no rested
        history, no ladder. ``ambientTempC`` stays null by design -- the
        MAX17048 has NO temperature register, so US-504 removed the TEMP tile
        rather than invent a source; the column survives for a future BMP390.
        """
        health, lastHealthCheckTs, medianRuntimeS, reason = (
            self._gatherBatteryHealthVerdict()
        )
        # US-632: the reason cannot be added to the payload from here -- the
        # emit callable's signature lives in src/pi/splash/, outside this
        # bench's surface (BL-us632). Record it where it CAN be seen instead.
        self._recordBatteryHealthReason(reason)
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
            "health": health,
            "fullChargeReached": False,
            "runtimeToCutoffS": medianRuntimeS,
            "ambientTempC": None,
            "lastHealthCheckTs": lastHealthCheckTs,
            "ladder": None,
            "upsAvailable": upsAvailable,
        }
