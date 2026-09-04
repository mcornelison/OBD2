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
# 2026-08-31    | Ralph (Rex)  | US-663 (I-us637): _gatherObdLinkState returns the
#               |              | typed-NA reason with the availability -- one word
#               |              | per cause, so "OBD: off" (a claim about the CAR)
#               |              | stops being published for two causes that are
#               |              | claims about US.
# 2026-09-01    | Ralph (Rex)  | US-632: hand the battery-health unknown-reason to
#               |              | the emitter as well as the journal -- the state
#               |              | file is the SSOT the card polls; the journal line
#               |              | stays because it records the TRANSITION.
# 2026-09-03    | Ralph (Rex)  | US-672: availability describes the link's
#               |              | CONDITION, never the retry loop's phase -- one
#               |              | decision point, taken before the phase is read.
#               |              | And the THIRD cause gets its own word: "never
#               |              | connected", not "OBD: off" (Atlas, the half
#               |              | US-663 missed).
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

# US-661: how often the `ltft-trend` producer re-aggregates. Five minutes, not
# the 2 s card cadence: LTFT is a MULTI-DRIVE signal whose published value
# cannot change until a drive ENDS, so a faster cadence buys nothing and costs a
# multi-drive scan of `realtime_data` -- the table the logger is concurrently
# writing to -- on every tick.
_DEFAULT_LTFT_TREND_INTERVAL_S = 300.0

# US-632: "no reason has been observed yet" -- distinct from an observed None
# (which means the verdict RESOLVED). A plain None default would swallow the
# first log line whenever the producer starts out resolved and later degrades.
_REASON_UNSET: Any = object()

# US-663 (I-us637) -- the OBD-link ACQUISITION's own failure reasons.
#
# `_gatherObdLinkState` reaches `available: false` down three paths and used to
# publish `REASON_OBD_OFF` for all three. "OBD: off" is a claim about the CAR;
# two of the three are claims about US, and a driver in a running car whose
# adapter handle died was being told the car was off. One cause, one word.
#
# They live HERE rather than in `pi.splash.source_availability` because that
# module is the home of the reasons SHARED between emitters, and these two name
# failures only this acquisition path can suffer (no other emitter holds an
# ObdConnection). `buildSourceState` accepts any reason string by contract, and
# keeping each word beside the branch that can actually produce it is what stops
# a shared vocabulary drifting away from its causes.
REASON_OBD_LINK_NOT_READ = "not read yet"  # nothing has looked at the link yet
REASON_OBD_LINK_UNREADABLE = "link unreadable"  # we looked; getStatus() raised

# US-672 (Atlas ruling 2026-09-02, the half US-663 missed) -- the THIRD cause.
#
# US-663 kept `REASON_OBD_OFF` for this branch and recorded it as "the one case
# where 'OBD: off' is true". Atlas overruled that: the branch is reached from
# `totalConnections == 0`, which is a fact about US -- we have never connected --
# and "OBD: off" is a claim about the CAR. *"That is an assertion about the world
# drawn from an absence of evidence about ourselves."* With the key ON it is
# simply false, which is US-663's own original defect surviving inside US-663's
# fix. The honest word is what we actually know.
REASON_OBD_NEVER_CONNECTED = "never connected"  # we have never reached this car

# US-628 -- the POWER-SOURCE acquisition's own failure reasons.
#
# `_gatherPowerSource` reaches `unknown` down three paths and published the bare
# string `unknown` for all three. Atlas read that on the live Pi (punch list
# H3 / 3.3) and could not tell an unwired bench from a Pi whose GPIO line is
# being held by another process -- two facts with completely different fixes.
#
# SHAPE: snake_case MACHINE words, following `reasons.altitude: no_source`
# (imu_state_bridge) and the six-word vocabulary US-632 built for the battery
# health verdict. Deliberately NOT the spaced human text used by the two OBD
# constants above: those travel in the `source.*` block, which the card renders
# VERBATIM, whereas these travel in a `reasons` map a consumer maps to display
# text (carousel.js `IMU_REASON_TEXT` is the existing example). Two shapes doing
# two different jobs -- keeping them apart is what stops one being rendered raw.
#
# They live HERE, beside the branch that produces them, for the reason the
# US-663 block above states: a vocabulary kept away from its causes drifts.

#: No power-source provider exists on this process at all -- the bench case, or
#: hardware that never started. There is nothing here that COULD be read, which
#: is a different fact (and a different fix) from a line we failed to read.
REASON_POWER_SOURCE_PROVIDER_ABSENT = "provider_absent"

#: The provider exists and reports that it cannot read the line. THIS IS THE
#: LIVE PI'S STATE as measured 2026-08-31: eclipse-powerwatch.service and
#: eclipse-obd.service both construct PldSensor on BCM GPIO6, a GPIO line is
#: claimed exclusively per-process, and the loser's sensor sets `_dev = None`
#: so `isAvailable` is False for the life of the process. See
#: offices/pm/issues/I-us628-two-services-both-claim-gpio6-so-the-collector-is-
#: blind.md -- this word makes that diagnosable from the state file, it does
#: NOT fix it.
REASON_POWER_SOURCE_UNREADABLE = "source_unreadable"

#: We had a provider, we asked it, and the ask raised. An instrument fault
#: rather than an absent or blocked instrument.
REASON_POWER_SOURCE_READ_FAILED = "read_failed"

#: Every reason an unresolved `power.source` may carry. A RESOLVED source
#: carries None: a reason explains an absence and must never stand beside a
#: real measurement.
POWER_SOURCE_UNKNOWN_REASONS: tuple[str, ...] = (
    REASON_POWER_SOURCE_PROVIDER_ABSENT,
    REASON_POWER_SOURCE_UNREADABLE,
    REASON_POWER_SOURCE_READ_FAILED,
)


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
    # US-630: the derived-gear producer. CLASS defaults (not __init__
    # assignments) so every existing composer -- including the standalone ones
    # in tests/ -- keeps working unchanged and simply never derives a gear.
    _gearDeriver: Any = None
    _gearStateEmitter: Any = None
    _lastSpeedReading: Any = None
    _lastRpmReading: Any = None
    # US-661: the `ltft-trend` producer. CLASS defaults for the same reason as
    # the gear pair above. Its own cadence -- the trend is a MULTI-DRIVE signal
    # that cannot change more than once per drive, and recomputing it on the 2 s
    # card tick would put a multi-drive aggregation over the Pi's hottest write
    # table into the run loop 30 times a minute for an answer that is identical
    # every time.
    _ltftTrendEmitter: Any = None
    _lastLtftTrendEmitTime: datetime | None = None
    _ltftTrendIntervalS: float = _DEFAULT_LTFT_TREND_INTERVAL_S
    # Injectable monotonic clock for the gear freshness/debounce windows. A
    # seam rather than an ambient time.monotonic() because those two windows are
    # the whole substance of the derivation, and a test that had to sleep 2 s to
    # exercise them would be a test nobody runs.
    _gearClock: Any = None

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
        self._initializeGearProducer(statesDir)
        self._initializeLtftTrendProducer(statesDir)
        severityTablePath = dtcConfig.get(
            "severityTablePath", _DEFAULT_SEVERITY_TABLE_PATH
        )
        try:
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

    # -------------------------------------------------------- derived gear
    #
    # US-630 (punch-list 1.4). This car exposes no gear PID, so the GEAR tile
    # read `-- / no source` permanently. Gear is DERIVED here, once, from the
    # realtime SPEED/RPM SSOT and published to states/gear -- never recomputed
    # per consumer (ssot-design-pattern rule B).
    #
    # Constructed in its OWN try/except, deliberately outside the block that
    # builds the three splash emitters: the two failure modes are unrelated, and
    # a missing severity table must not also take the gear tile down (nor a bad
    # band table the DTC card).

    def _initializeGearProducer(self, statesDir: str) -> None:
        """Build the gear deriver + its states/gear emitter, or stay dark."""
        try:
            from pi.obdii.gear_derivation import createGearDeriverFromConfig
            from pi.obdii.gear_state_emitter import makeGearStateEmitter

            deriver = createGearDeriverFromConfig(self._config)
            if deriver is None:
                # pi.gear.enabled false -> NO producer and NO file. An absent
                # states/gear is what the carousel already renders as an honest
                # "-- / no source"; a file saying available:false would be a
                # producer claiming to have looked when it never ran.
                logger.info("Gear derivation dark (pi.gear.enabled=false)")
                return
            self._gearDeriver = deriver
            self._gearStateEmitter = makeGearStateEmitter(statesDir)
            logger.info(
                "Gear derivation wired (%d measured bands); states_dir=%s",
                len(deriver._bands), statesDir,
            )
        except Exception as e:  # noqa: BLE001 -- dashboard wiring must not fail boot
            logger.warning(
                "Gear producer init skipped: %s (type=%s)", e, type(e).__name__
            )
            self._gearDeriver = None
            self._gearStateEmitter = None

    # ---------------------------------------------------------- ltft-trend
    #
    # US-661 (punch-list 5.2). The `ltft-trend` emitter module has existed since
    # US-420 but NOTHING EVER CALLED IT, so the Fuel Trim card has never had
    # data. Same shape as US-494/495/498/US-630: both halves built, no join.
    #
    # Constructed in its OWN try/except beside the gear producer, for the same
    # reason -- these failure modes are unrelated and a missing DB must not also
    # take the DTC card down.

    def _initializeLtftTrendProducer(self, statesDir: str) -> None:
        """Build the `ltft-trend` emitter, or stay dark."""
        dashConfig = self._config.get("pi", {}).get("dashboard", {})
        self._ltftTrendIntervalS = float(
            dashConfig.get(
                "ltftTrendIntervalSeconds", _DEFAULT_LTFT_TREND_INTERVAL_S
            )
        )
        try:
            from pi.splash.ltft_trend_emitter import (
                makeLtftTrendEmitter,
                readLtftDriveRowsFrom,
            )

            def readDriveRows() -> dict:
                # The database is resolved through getattr AT USE TIME, never
                # captured here. This sprint's predecessors hit that boot-order
                # trap three times (US-501/502/504b): the emitters are built in
                # _initializeAllComponents while their dependencies land later,
                # so a captured reference stays None for the life of the process
                # -- a permanently empty tile with fully green unit tests.
                #
                # The handle is OPENED inside the reader module, not here. The
                # A-17 static guard forbids any connection-opening call in this
                # file (it is a text sweep, so it cannot tell a DB handle from
                # an OBD one -- which is precisely why every reader delegates);
                # `_gatherLastDriveSummary` delegates for the same reason.
                return readLtftDriveRowsFrom(getattr(self, "_database", None))

            self._ltftTrendEmitter = makeLtftTrendEmitter(
                statesDir, driveRowsReader=readDriveRows
            )
            logger.info(
                "LTFT trend producer wired (every %.0fs); states_dir=%s",
                self._ltftTrendIntervalS, statesDir,
            )
        except Exception as e:  # noqa: BLE001 -- dashboard wiring must not fail boot
            logger.warning(
                "LTFT trend producer init skipped: %s (type=%s)",
                e, type(e).__name__,
            )
            self._ltftTrendEmitter = None

    def _emitLtftTrendState(self) -> None:
        """Re-aggregate + publish `ltft-trend` when its own cadence has elapsed.

        Silent when the database handle is absent. That is deliberate and it is
        the US-672 lesson applied one card over: writing a file that says "no
        real drives recorded" when we could not even OPEN the log would be a
        claim about the CAR drawn from an absence of evidence about US. An
        absent state file already renders the honest "no data -- trend not
        computed"; a producer that never ran must not answer as though it had.
        """
        emitter = self._ltftTrendEmitter
        if emitter is None:
            return
        if getattr(self, "_database", None) is None:
            return
        now = datetime.now()
        last = self._lastLtftTrendEmitTime
        if last is not None:
            if (now - last).total_seconds() < self._ltftTrendIntervalS:
                return
        self._lastLtftTrendEmitTime = now
        emitter()

    def _gearNowS(self) -> float:
        """Monotonic seconds for the gear freshness + debounce windows."""
        clock = self._gearClock
        if clock is not None:
            return float(clock())
        import time

        return time.monotonic()

    def observeGearInput(self, paramName: str, value: Any) -> None:
        """Route one realtime reading into the gear derivation.

        Called from the orchestrator's reading callback for every parameter;
        returns immediately for the ones gear does not consume.

        WHY THE READING SEAM AND NOT THE 2 s CARD CADENCE: the freshness window
        is 2 s, so derived on the card tick the newest sample would routinely be
        as old as the window itself and a perfectly healthy cruise would flicker
        to `stale`. The ratio is two floats and a table walk, so deriving it at
        the ~4-5 PID/s poll rate is cheaper than the state-file write it feeds.

        Args:
            paramName: The realtime parameter's name (e.g. ``SPEED``).
            value: Its latest value, in the units realtime_data stores.
        """
        if self._gearDeriver is None:
            return
        if paramName not in ("SPEED", "RPM"):
            return
        from pi.obdii.gear_derivation import Reading

        reading = Reading(value=None if value is None else float(value),
                          tsS=self._gearNowS())
        if paramName == "SPEED":
            self._lastSpeedReading = reading
        else:
            self._lastRpmReading = reading
        self._emitGearState()

    def _emitGearState(self) -> None:
        """Derive the gear from the latest inputs and publish it.

        Also invoked from the card-state tick, which is what makes a DEAD feed
        honest: with no readings arriving nothing would rewrite the file, and
        the panel would hold the last real gear indefinitely -- the one outcome
        the story forbids. The tick re-derives against a moving clock, so the
        stored readings age out and the tile drops to a typed `stale`.
        """
        deriver = self._gearDeriver
        emitter = self._gearStateEmitter
        if deriver is None or emitter is None:
            return
        emitter(
            deriver.update(
                speed=self._lastSpeedReading,
                rpm=self._lastRpmReading,
                nowS=self._gearNowS(),
            )
        )

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
        try:
            # US-630: re-publish the gear against a MOVED clock even when no
            # reading has arrived. This is the only thing that decays a stopped
            # OBD feed to a typed `stale` -- without it the last real gear would
            # sit on the panel for as long as the pipe stayed quiet.
            self._emitGearState()
        except Exception as e:  # noqa: BLE001 -- never crash the loop
            logger.debug("gear card emit failed: %s", e)
        try:
            # US-661: self-throttled to its own multi-minute cadence, so this
            # call is a cheap timestamp compare on all but one tick in 150.
            self._emitLtftTrendState()
        except Exception as e:  # noqa: BLE001 -- never crash the loop
            logger.debug("ltft-trend card emit failed: %s", e)
        return True

    # -------------------------------------------------------- system-status

    def _emitSystemStatusState(self) -> None:
        """Gather truthful link/sync/power/drive readings + emit system-status."""
        emitter = self._systemStatusEmitter
        if emitter is None:
            return

        obdLinkState, obdRetries, obdAvailable, obdReason = self._gatherObdLinkState()
        powerSource, powerSourceReason = self._gatherPowerState()
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
            powerSource=powerSource,
            # US-628: the typed reason travels WITH the unresolved source, so
            # the state file distinguishes "no acquisition path" from "the line
            # is held by another process" -- the live Pi is the second, and the
            # bare `unknown` it published named neither.
            powerSourceReason=powerSourceReason,
            driveState=driveState,
            driveId=driveId,
            lastDrive=self._gatherLastDriveSummary(),
            obdAvailable=obdAvailable,
            obdUnavailableReason=obdReason,
        )

    def _gatherObdLinkState(self) -> tuple[str, int, bool, str | None]:
        """Map the ObdConnection state -> (linkState, retries, available, reason).

        available is False (US-429 typed NA) exactly when the OBD source is
        ABSENT -- i.e. we have NEVER connected (totalConnections == 0): car off /
        no dongle / bench. A dropped-but-previously-seen link stays AVAILABLE (we
        are retrying a real car), whether or not an attempt happens to be in
        flight at this instant. Connected -> linked; retrying a car we have seen
        -> reconnecting/down by phase. A missing connection is unavailable.

        US-672: the RETRY PHASE is deliberately not an input to `available`. It
        used to be, on one of the two not-connected branches only, and that is
        the whole defect -- see the comment at the decision below.

        US-663: the fourth element is the typed-NA reason that TRAVELS WITH the
        absence -- one word per cause, never one word for three. It is None on
        every available branch, which the emitter needs: a reason sitting beside
        a real link state would let `sourceUnavailable()` blank a working panel
        (US-637's override makes the source block win outright).

        The first element is still `OBD_DOWN` on both unknown branches and is
        DISCARDED by the emitter, which blanks the whole block whenever the
        source is unavailable. It is left alone rather than given a fourth token
        because the link-state vocabulary is owned by `system_status_emitter`;
        `down` is a MEASUREMENT ("we looked, there is no signal") and inventing
        an unknown token here would be a second vocabulary for one fact.
        """
        from pi.splash.system_status_emitter import (
            OBD_DOWN,
            OBD_LINKED,
            OBD_RECONNECTING,
        )

        conn = self._connection
        if conn is None:
            # Nothing has looked at the link yet -- the pre-first-read payload of
            # a boot. Saying "OBD: off" here would be a claim about a car nobody
            # has queried.
            return (OBD_DOWN, 0, False, REASON_OBD_LINK_NOT_READ)
        try:
            status = conn.getStatus()
        except Exception:  # noqa: BLE001 -- unreadable status -> unavailable
            # We looked and could not read our own connection. A fault in the Pi,
            # not in the car, and the two have different fixes.
            return (OBD_DOWN, 0, False, REASON_OBD_LINK_UNREADABLE)

        connected = bool(getattr(status, "connected", False))
        retries = int(getattr(status, "retryCount", 0) or 0)
        totalConns = int(getattr(status, "totalConnections", 0) or 0)
        rawState = getattr(status, "state", None)
        stateStr = str(getattr(rawState, "value", rawState) or "").lower()

        if connected:
            return (OBD_LINKED, retries, True, None)

        # US-672 -- ONE question, ONE place it is answered. Availability asks
        # "is the source ABSENT" (US-429), and the answer is whether this Pi has
        # ever spoken to this car. It is decided HERE, once, BEFORE the retry
        # phase is looked at, so the two not-connected branches below cannot
        # disagree about it.
        #
        # They used to. The reconnect branch returned True unconditionally while
        # the fall-through gated on `totalConns > 0`, so a car we have never
        # reached published available:true mid-attempt and available:false
        # between attempts -- 45 AMBER / 38 GREY over 5.5 minutes on a PARKED
        # car with the key OUT (CIO, 2026-09-01), nothing about the world
        # changing. Retry phase is a fact about our CLIENT; availability is a
        # fact about the CAR, and an answer that changes every 100 seconds was
        # answering the wrong question.
        if totalConns == 0:
            return (OBD_DOWN, retries, False, REASON_OBD_NEVER_CONNECTED)

        # Available: we HAVE reached this car, so the source is present and we
        # are failing to hold it. The link-state token still carries the retry
        # PHASE, which is where Atlas said a "trying now" fact may live so long
        # as it does not ride on `available` -- the OBD LINK tile's
        # "RECONNECTING / retry 3" is a diagnostic the operator goes looking for.
        # The GLYPH does not strobe on it because dashboard.css paints `down` and
        # `reconnecting` with the same token (US-488), which is asserted in
        # tests/ui/test_carousel_obd_availability_holds_one_value.py rather than
        # left as a coincidence.
        if "reconnect" in stateStr or "connecting" in stateStr:
            return (OBD_RECONNECTING, retries, True, None)
        return (OBD_DOWN, retries, True, None)

    def _gatherPowerState(self) -> tuple[str, str | None]:
        """Return (powerSource, powerSourceReason) from the power-source SSOT.

        US-668 (CIO 2026-09-02): the operator-declared ``powerMode``
        (car/wall/unknown) is GONE, and with it PowerModeProvider. It was a fact
        the operator typed into Settings so that this card could display it back
        to them; verified before removal, ``card_state_emitter`` was its ONLY
        consumer and no shutdown or lifecycle policy branched on it. The CIO's
        argument is the shorter one: *if you can see the screen, the power is on*
        -- car versus wall changed nothing anybody or anything acted on.

        ``powerSource`` STAYS, and the distinction is the point of this story.
        It is SENSED, not declared, and it answers the one power question the
        display cannot answer by existing: am I on external power, or on the UPS
        battery? During the 2026-08-31 UPS test the panel stayed lit for the
        whole time the Pi ran on battery toward a graceful poweroff.

        The reason is returned from this ONE call rather than from a second
        ``_gatherPowerSourceReason()`` on purpose: two reads can disagree, and a
        reason describing a different read than the value beside it is worse
        than no reason at all. One acquisition, one answer (rule B).
        """
        return self._gatherPowerSource()

    def _gatherPowerSource(self) -> tuple[str, str | None]:
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

        Returns:
            ``(source, reason)``. ``source`` is ``external`` / ``battery`` /
            ``unknown``; ``reason`` is None on the two resolved branches and one
            of :data:`POWER_SOURCE_UNKNOWN_REASONS` otherwise (US-628). All
            three unknown branches used to publish the same bare word, so a
            reader of the state file could not tell an unwired bench from a
            GPIO line another process is holding.
        """
        source = getattr(self, "_powerSourceProvider", None)
        if source is None:
            return ("unknown", REASON_POWER_SOURCE_PROVIDER_ABSENT)
        try:
            if not source.isAvailable:
                return ("unknown", REASON_POWER_SOURCE_UNREADABLE)
            present = source.isExternalPowerPresent()
        except Exception:  # noqa: BLE001 -- honest unknown on read failure
            return ("unknown", REASON_POWER_SOURCE_READ_FAILED)
        return ("external" if present else "battery", None)

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
        powerSource, _ = self._gatherPowerState()
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
        be seen."

        The reason ALSO reaches the ``battery-health`` state file now, in
        ``reasons.health`` (BL-us632 granted the splash surface). This line is
        not redundant with it, and the distinction is the reason to keep both:
        the state file holds only NOW, so it can say the verdict is stale but
        never say SINCE WHEN it became stale. The journal is the only place a
        reader can see the cause CHANGE -- which is exactly the question
        punch-list 4.2 was really asking.

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
        # US-632: the reason travels BOTH ways. `reasons.health` in the payload
        # is the SSOT the card polls (BL-us632, since granted); the journal line
        # stays because it is a TRANSITION record -- it says WHEN the cause
        # changed, which a state file that only ever holds "now" cannot.
        self._recordBatteryHealthReason(reason)
        return {
            "healthReason": reason,
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
