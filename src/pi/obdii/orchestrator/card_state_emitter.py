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
# 2026-09-07    | Ralph (Rex)  | US-687-b: _emitGearState hands the gear producer
#               |              | the link health it already computes next door,
#               |              | so PARK cannot be published on a dead dongle.
#               |              | RECONNECTING is NOT healthy -- it reports
#               |              | available:true by US-672's own (correct) rule.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T7: the battery-health verdict is
#               |              | T vs J; the card gains timeToFloorS / jobAvgS /
#               |              | jobMaxS / provisional; smoothingSec from config.
# 2026-10-03    | Atlas (ARCH-065a) | Ruling 19: the verdict's pack is
#               |              | resolveCellEpoch(config) and its provisional floor
#               |              | is config pi.powerWatch.drainFloorVolts, both passed
#               |              | in (one owner each; no row-derived pack).
# 2026-10-13    | Rex (US-873) | Capture-health `feeds`: gather each feed's first
#               |              | sample this process and last sample age (OBD
#               |              | rows, IMU/light bridges, the UPS VCELL read).
# 2026-10-13    | Rex (US-860-a)| Boot milestones: the orchestrator start arms
#               |              | kernel_start; the capture-health emit writes each
#               |              | feed's first_sample_* rung from its feeds block.
# 2026-10-13    | Rex (US-874) | states/obd-live: observeObdLiveReading on the
#               |              | reading seam; the card tick publishes each PID's
#               |              | latest value/unit/event time and decides stale.
# 2026-10-14    | Rex (US-901-b)| system-status runMode from pi.replay.active and
#               |              | the orchestrator's --simulate flag.
# 2026-10-14    | Rex (US-880-a)| observeTripSpeed: SPEED while recording feeds
#               |              | the ONE speed integrator; drive start resets it;
#               |              | system-status drive.distanceKm/distanceSinceTs.
# 2026-10-14    | Rex (US-881-b)| observeFuelReading: MAF/FUEL_SYSTEM_STATUS while
#               |              | recording feed the fuel integrator; the card tick
#               |              | publishes states/fuel-economy beside obd-live.
# 2026-10-14    | Rex (US-881-c)| Since-reset fuel totals: the card tick persists
#               |              | this drive's change since its watermark to the
#               |              | Pi-local fuel_since_reset row (drive end + every
#               |              | pi.fuel.persistSec) and publishes sinceReset.
# 2026-10-15    | Rex (US-889-a)| states/engine-history: written at the obd-live
#               |              | tick when a bucket closed; _resetEngineHistory
#               |              | opens the window at drive start.
# 2026-10-15    | Rex (US-890-e)| fuel-economy recent: a RecentWindow under
#               |              | _fuelLock fed MAF air + the SPEED km delta (taken
#               |              | after the trip lock is released; Atlas G2).
# 2026-10-18    | Rex (US-892-a)| _resetImuPeaks: drive start clears the states/imu
#               |              | peaks, labelled by _tripEventTs (== distanceSinceTs).
# 2026-10-18    | Rex (US-896-b)| _markTripEnded: drive end freezes drive.elapsedSec;
#               |              | drive.distancePartial from the restart branch.
# 2026-10-19    | Rex (US-897-a2)| The dtc read times are seeded from the tmpfs
#               |              | states/dtc BEFORE the boot write, which carries them.
# 2026-10-20    | Rex (US-897-b2)| states/alerts: the alerts arbiter runs after
#               |              | obd-live on the SAME payload that emit returned.
# 2026-10-20    | Rex (US-897-b4)| observeObdLiveReading hands each RPM reading +
#               |              | its band to the arbiter's peak; the alerts tick
#               |              | passes its own recording -> idle edge.
# 2026-10-20    | Rex (US-897-b5)| the boot dtc payload reaches the arbiter; the
#               |              | alerts tick publishes its code source.
# 2026-10-20    | Rex (US-897-c)| the alerts ack store: every alerts emit hands
#               |              | in this boot's matching acks and prunes; the
#               |              | tick caches its inputs for emitNow (Atlas G2).
# 2026-10-21    | Rex (US-897-e)| the restart seed also carries the pending set
#               |              | its pendingCheckedAtTs dates (one read).
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


class _UnreadableBatteryVerdict:
    """The verdict when the producer could not even be imported or called.

    Duck-types ``BatteryHealthVerdict`` so the assembly below has ONE shape to
    read; deliberately NOT built from the producer module, whose import may be
    the very thing that failed.
    """

    verdict = "unknown"
    lastHealthCheckTs = None
    reason = "log_unreadable"
    timeToFloorS = None
    jobAvgS = None
    jobMaxS = None
    provisional = False


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
    # US-897-a2: last successful Mode 03 / Mode 07 read times this boot.
    _dtcCheckedAtTs: str | None
    _dtcPendingCheckedAtTs: str | None
    # US-897-e: the carried pending set, seeded with pendingCheckedAtTs.
    _dtcCarriedPending: list[Any]
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
    # US-688: the capture-health producer. CLASS defaults for the same reason as
    # the gear pair above -- every existing composer keeps working unchanged and
    # simply publishes no capture verdict.
    _captureHealthEmitter: Any = None
    _captureStallSeconds: float = 0.0
    # US-873: the capture-health `feeds` facts for THIS process. CLASS defaults
    # so a restart (a new instance) re-arms every one of them, and so existing
    # composers keep working. OBD's first sample is held by its writer
    # (ObdDataLogger.firstRowTs), not here.
    _upsFirstSampleTs: str | None = None
    _upsLastSampleMonotonic: float | None = None
    # Injectable monotonic clock for the feed ages; same reason as _gearClock.
    _feedClock: Any = None
    # US-860-a: the first_sample_* boot milestones this process has landed, so
    # the emit tick stops re-writing them. An immutable CLASS default, replaced
    # (never mutated) per instance, for the same reason as the defaults above.
    _bootMilestonesWritten: frozenset[str] = frozenset()
    # US-874: the states/obd-live producer. CLASS defaults for the same reason
    # as the gear pair above; a composer without one observes nothing.
    _obdLiveTracker: Any = None
    _obdLiveEmitter: Any = None
    _obdLiveStaleSec: float | None = None
    # Injectable aware-UTC wall clock: staleness compares against reading event
    # times, which are wall-clock instants, not monotonic ones.
    _obdLiveClock: Any = None
    # US-897-b2: the alerts arbiter (episodes for this boot) + its emitter.
    _alertsArbiter: Any = None
    _alertsEmitter: Any = None
    _alertsBootId: str = "unknown"
    # US-897-b4: the card tick's recording -> idle edge that ends the over-rev.
    _alertsWasRecording: bool = False
    # US-897-c: the boot-scoped ack store, and the (obdLive, nowUtc, dataSource)
    # of the last alerts tick -- what emitNow rebuilds from.
    _alertsAckStore: Any = None
    _alertsLastInputs: tuple[Any, datetime, str | None] | None = None
    # US-889-a: the states/engine-history writer; the history itself lives in
    # the obd-live tracker. CLASS default for the same reason as above.
    _engineHistoryEmitter: Any = None
    # Injectable monotonic clock for the gear freshness/debounce windows. A
    # seam rather than an ambient time.monotonic() because those two windows are
    # the whole substance of the derivation, and a test that had to sleep 2 s to
    # exercise them would be a test nobody runs.
    _gearClock: Any = None
    # US-880-a: the ONE speed integrator behind system-status drive.distanceKm.
    # CLASS defaults for the same reason as the gear pair above; a composer
    # without one integrates nothing and publishes null. The (km, sinceTs) pair
    # is read on the run loop and written on the reading callback, so it moves
    # under one lock, built with the integrator.
    _speedIntegrator: Any = None
    _tripLock: Any = None
    _tripDistanceKm: float | None = None
    _tripDistanceSinceTs: str | None = None
    # US-896-b: the drive-end mark that freezes drive.elapsedSec (None while the
    # window is open), and whether the window began at a mid-drive restart's
    # first SPEED reading (True) or a drive start (False). Under _tripLock.
    _tripDistanceEndTs: str | None = None
    _tripDistancePartial: bool | None = None
    # Injectable monotonic clock for the integrator's dt; same reason as
    # _gearClock. Never wall time: an NTP step must not add or erase distance.
    _tripClock: Any = None
    # US-881-b: the states/fuel-economy producer. CLASS defaults for the same
    # reason as the gear pair above. The integrator is written on the reading
    # callback and read by the card tick, so both sides take _fuelLock.
    _fuelIntegrator: Any = None
    _fuelSettings: Any = None
    _fuelEconomyEmitter: Any = None
    _fuelLock: Any = None
    _fuelStaleSec: float | None = None
    # US-890-e: the last-30 s window, guarded by _fuelLock like the integrator.
    _fuelRecentWindow: Any = None
    # US-881-c: since-reset persistence. The watermark is the (fuelL, km,
    # openLoopS) of THIS drive already written to fuel_since_reset, so a drive
    # is counted once however many persists it spans. It, the generation (bumped
    # at every drive start) and the last persist time move under _fuelLock with
    # the integrator. The cached row and the was-recording edge are the card
    # tick's alone.
    _fuelWatermark: tuple[float, float, float] = (0.0, 0.0, 0.0)
    _fuelGeneration: int = 0
    _fuelLastPersistS: float | None = None
    _fuelWasRecording: bool = False
    _fuelSinceReset: dict[str, Any] | None = None
    _fuelSinceResetLoaded: bool = False
    _fuelNoDatabaseWarned: bool = False

    # ------------------------------------------------------------------ setup

    def _initializeCardStateEmitters(self) -> None:
        """Construct the three emitters + write the initial honest dtc state.

        Called from ``lifecycle._initializeAllComponents`` after the connection,
        hardware, drive-detector, sync-client and power-monitor exist. Best-
        effort: a construction failure logs + leaves the emitters None so the
        orchestrator boots regardless (the dashboard hook never blocks boot).
        """
        # US-860-a: the boot record is not a dashboard card, so it is armed
        # whether or not the cards are enabled.
        self._recordKernelStartMilestone()
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
        self._initializeCaptureHealthProducer(statesDir)
        self._initializeObdLiveProducer(statesDir)
        self._initializeAlertsProducer(statesDir)
        self._initializeTripDistance()
        self._initializeFuelEconomyProducer(statesDir)
        severityTablePath = dtcConfig.get(
            "severityTablePath", _DEFAULT_SEVERITY_TABLE_PATH
        )
        try:
            from pi.splash.battery_health_emitter import makeBatteryHealthEmitter
            from pi.splash.dtc_emitter import makeDtcEmitter, readDtcCheckTimes
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
            # US-897-a2 (Atlas Q3): the states dir is per boot, so a states/dtc
            # already there was written THIS boot by a previous orchestrator.
            # Seed the read times from it BEFORE the boot write overwrites it.
            # US-897-e: the pending set is seeded from the SAME read as the
            # time that dates it -- together or not at all.
            (
                self._dtcCheckedAtTs,
                self._dtcPendingCheckedAtTs,
                self._dtcCarriedPending,
            ) = readDtcCheckTimes(statesDir)
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

    # ----------------------------------------------------- capture health
    #
    # US-688. `data_logger_last_row_seconds_ago` has gone out on the health-check
    # line every 60 s since US-302 and NOTHING has ever read it. On 2026-09-04 it
    # read `never_written` for two days while a loose dongle produced zero rows,
    # and the outage was found by a human looking at a dongle. This is the
    # consumer.

    def _initializeCaptureHealthProducer(self, statesDir: str) -> None:
        """Build the states/capture-health emitter, or stay dark.

        Its OWN try/except, like the gear producer: a failure here must not also
        take down the DTC card, and vice versa.
        """
        try:
            from pi.obdii.capture_health import (
                DEFAULT_STALL_SECONDS,
                makeCaptureHealthEmitter,
            )

            cfg = self._config.get("pi", {}).get("captureHealth", {})
            if not cfg.get("enabled", True):
                # Dark -> NO producer and NO file. An absent state file is an
                # honest absence the carousel already renders; a file saying
                # `ok` would be a producer claiming to have looked when it
                # never ran -- which is this story's own defect, inverted.
                logger.info("Capture-health dark (pi.captureHealth.enabled=false)")
                self._captureHealthEmitter = None
                return
            self._captureStallSeconds = float(
                cfg.get("stallSeconds", DEFAULT_STALL_SECONDS)
            )
            self._captureHealthEmitter = makeCaptureHealthEmitter(statesDir)
            logger.info(
                "Capture-health wired (stall_seconds=%.1f)",
                self._captureStallSeconds,
            )
        except Exception as e:  # noqa: BLE001 -- must not fail boot
            logger.warning("Capture-health producer init skipped: %s", e)
            self._captureHealthEmitter = None

    def _emitCaptureHealthState(self) -> None:
        """Publish whether capture has gone silent while the car is powered.

        NO SECOND ACQUISITION (ssot-design-pattern rule B). Both facts come off
        methods that already exist on ``self``:

        * ``_readDataLoggerRowFreshness`` (``HealthMonitorMixin``) -- the SAME
          read that feeds the US-302 health-check line, so the log and the panel
          can never disagree about capture.
        * ``_gatherPowerSource`` -- the US-502 GPIO6 SSOT for AC-vs-battery.

        🔴 AND NOTHING FROM THE OBD TRANSPORT. RPM, the alternator-voltage
        escalation and drive detection would all be natural "is the engine
        running" gates, and every one of them dies with the dongle -- which is
        the failure this alert reports. Gating on any of them would make the
        alert unable to fire in its own motivating incident.
        """
        emitter = self._captureHealthEmitter
        if emitter is None:
            return

        # Cross-mixin call (HealthMonitorMixin provides the method); matches the
        # `_checkConnectionStatus` pattern used in health_monitor.py itself.
        lastRowS, freshnessReason = self._readDataLoggerRowFreshness()  # type: ignore[attr-defined]
        powerSource, _powerReason = self._gatherPowerSource()
        feedSamples = self._gatherCaptureFeedSamples()
        emitter(
            lastRowSecondsAgo=lastRowS,
            freshnessReason=freshnessReason,
            powerSource=powerSource,
            stallSeconds=self._captureStallSeconds,
            feedSamples=feedSamples,
        )
        self._recordFirstSampleMilestones(feedSamples)

    # ------------------------------------------------------ boot milestones
    #
    # US-860-a. The forward boot record. Both writers hand the database to
    # boot_milestone, which does the SQL: this module opens no connection.

    def _recordKernelStartMilestone(self) -> None:
        """Arm this boot's kernel_start rung at the orchestrator start."""
        database = getattr(self, "_database", None)
        if database is None:
            return
        try:
            from src.pi.diagnostics.boot_milestone import recordKernelStart

            recordKernelStart(database)
        except Exception as e:  # noqa: BLE001 -- a boot record never fails boot
            logger.warning("kernel_start milestone skipped: %s", e)

    def _recordFirstSampleMilestones(
        self, feedSamples: dict[str, tuple[str | None, float | None]]
    ) -> None:
        """Write each feed's first_sample_* rung from the ts the feeds block published.

        No second detector: the time is the ``firstSampleTs`` just handed to the
        capture-health emitter. A feed with no first sample has no rung.
        """
        database = getattr(self, "_database", None)
        if database is None:
            return
        try:
            from pi.obdii.capture_health import FEED_IMU, FEED_LIGHT, FEED_OBD, FEED_UPS
            from src.pi.diagnostics.boot_milestone import (
                FIRST_SAMPLE_IMU,
                FIRST_SAMPLE_LIGHT,
                FIRST_SAMPLE_OBD,
                FIRST_SAMPLE_UPS,
                recordMilestone,
            )

            for feed, milestone in (
                (FEED_OBD, FIRST_SAMPLE_OBD),
                (FEED_IMU, FIRST_SAMPLE_IMU),
                (FEED_LIGHT, FIRST_SAMPLE_LIGHT),
                (FEED_UPS, FIRST_SAMPLE_UPS),
            ):
                if milestone in self._bootMilestonesWritten:
                    continue
                firstTs = feedSamples.get(feed, (None, None))[0]
                if firstTs is None:
                    continue
                if recordMilestone(database, milestone, firstTs):
                    self._bootMilestonesWritten = self._bootMilestonesWritten | {milestone}
        except Exception as e:  # noqa: BLE001 -- must not fail the emit tick
            logger.warning("first-sample milestones skipped: %s", e)

    # ------------------------------------------------ capture-health feeds

    def _feedNowS(self) -> float:
        """Monotonic seconds for the feed ages (the bridges' tsCapture clock)."""
        clock = self._feedClock
        if clock is not None:
            return float(clock())
        import time

        return time.monotonic()

    def _gatherCaptureFeedSamples(self) -> dict[str, tuple[str | None, float | None]]:
        """Each feed's ``(firstSampleTs, lastSampleSecondsAgo)`` this process.

        US-873. Every fact is read from the component that already owns it --
        the logger's in-process row marker, the two bus bridges, and the UPS
        read the battery-health tick already took -- so this opens no device
        and no connection. A feed that has produced nothing reports
        ``(None, None)``; nothing from a previous process is ever consulted.
        """
        from pi.obdii.capture_health import FEED_IMU, FEED_LIGHT, FEED_OBD, FEED_UPS

        nowS = self._feedNowS()
        upsAge = (
            None
            if self._upsLastSampleMonotonic is None
            else nowS - self._upsLastSampleMonotonic
        )
        return {
            FEED_OBD: self._gatherObdFeedSample(),
            FEED_IMU: self._bridgeFeedSample(getattr(self, "_imuStateBridge", None), nowS),
            FEED_LIGHT: self._bridgeFeedSample(
                getattr(self, "_lightStateBridge", None), nowS
            ),
            FEED_UPS: (self._upsFirstSampleTs, upsAge),
        }

    @staticmethod
    def _bridgeFeedSample(bridge: Any, nowS: float) -> tuple[str | None, float | None]:
        """A bus bridge's first sample ts and newest sample age, or absence."""
        if bridge is None:
            return (None, None)
        firstTs = getattr(bridge, "firstSampleTs", None)
        lastCapture = getattr(bridge, "lastSampleCapture", None)
        if not isinstance(lastCapture, (int, float)) or isinstance(lastCapture, bool):
            return (firstTs if isinstance(firstTs, str) else None, None)
        return (firstTs if isinstance(firstTs, str) else None, nowS - float(lastCapture))

    def _inProcessRowAge(self) -> float | None:
        """The logger's IN-PROCESS row age -- never the durable fallback.

        ``_readDataLoggerRowFreshness`` falls back to the table's newest row on
        a restart, which is a time from a PREVIOUS process; the feed must not
        publish that. Non-numeric stand-ins read as no sample.
        """
        dataLogger = getattr(self, "_dataLogger", None)
        if dataLogger is None:
            return None
        try:
            value = getattr(dataLogger, "lastRowWrittenSecondsAgo", None)
        except Exception:  # noqa: BLE001 -- an unreadable marker is no sample
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _gatherObdFeedSample(self) -> tuple[str | None, float | None]:
        """OBD's first row event time this process, and its in-process row age.

        ``firstSampleTs`` is ``ObdDataLogger.firstRowTs`` (Atlas option A): the
        one writer of every live realtime_data row sets it once, after its first
        committed INSERT, to the value that row's ``timestamp`` received. Read
        None-safe -- no logger (bench, before init) is no sample. No lock: one
        writer sets one reference once.
        """
        realtime = getattr(self, "_dataLogger", None)
        writer = getattr(realtime, "dataLogger", None) if realtime is not None else None
        firstRowTs = getattr(writer, "firstRowTs", None) if writer is not None else None
        firstTs = firstRowTs if isinstance(firstRowTs, str) and firstRowTs else None
        return (firstTs, self._inProcessRowAge())

    def _recordUpsSample(self, vcellV: float) -> None:
        """Note one VCELL read for ``feeds.ups`` -- unless it is the sentinel.

        Called IMMEDIATELY after the synchronous ``getBatteryVoltage()`` read,
        so ``utcIsoNow()`` here IS the sample time (Atlas G6). The MAX17048's
        unbacked-register word ``0xFFFF`` is no reading, whether it arrives raw
        or already scaled to volts, and sets nothing.
        """
        from common.time.helper import utcIsoNow
        from pi.hardware.ups_monitor import (
            MAX17048_VCELL_LSB_V,
            SOC_UNBACKED_SENTINEL,
        )

        sentinelVolts = SOC_UNBACKED_SENTINEL * MAX17048_VCELL_LSB_V
        if vcellV == SOC_UNBACKED_SENTINEL or abs(vcellV - sentinelVolts) < (
            MAX17048_VCELL_LSB_V / 2
        ):
            return
        sampleTs = utcIsoNow()
        if self._upsFirstSampleTs is None:
            self._upsFirstSampleTs = sampleTs
        self._upsLastSampleMonotonic = self._feedNowS()

    # ------------------------------------------------------------ obd-live
    #
    # US-874. Every PID's latest value, unit and event time. Readings are
    # observed at the _handleReading seam (the logger's getLatestReadings holds
    # values only, no per-PID time); the card tick publishes them and decides
    # staleness against a moving clock, so a quiet feed goes stale on the panel.

    def _initializeObdLiveProducer(self, statesDir: str) -> None:
        """Build the obd-live tracker + emitter in their own try/except."""
        try:
            from pi.obdii.obd_live_emitter import (
                DEFAULT_OBD_LIVE_STALE_S,
                ObdLiveTracker,
                makeObdLiveEmitter,
            )

            staleCfg = self._config.get("pi", {}).get("display", {}).get("stale", {})
            self._obdLiveStaleSec = float(
                staleCfg.get("obdLiveSec", DEFAULT_OBD_LIVE_STALE_S)
            )
            self._obdLiveTracker = ObdLiveTracker(self._config)
            self._obdLiveEmitter = makeObdLiveEmitter(statesDir)
            logger.info("obd-live wired (stale_sec=%.1f)", self._obdLiveStaleSec)
        except Exception as e:  # noqa: BLE001 -- must not fail boot
            logger.warning("obd-live producer init skipped: %s", e)
            self._obdLiveTracker = None
            self._obdLiveEmitter = None
        try:
            from pi.obdii.engine_history import makeEngineHistoryEmitter

            self._engineHistoryEmitter = makeEngineHistoryEmitter(statesDir)
        except Exception as e:  # noqa: BLE001 -- must not fail boot
            logger.warning("engine-history emitter init skipped: %s", e)
            self._engineHistoryEmitter = None

    def observeObdLiveReading(self, reading: Any) -> None:
        """Record one realtime reading for states/obd-live (the reading seam)."""
        tracker = self._obdLiveTracker
        if tracker is None:
            return
        tracker.observeReading(reading)
        self._observeAlertsRpmReading(tracker, reading)

    def _observeAlertsRpmReading(self, tracker: Any, reading: Any) -> None:
        """Hand an RPM reading to the alerts arbiter's peak (US-897-b4).

        AFTER the tracker observed it, so the band read back (under the
        tracker's lock) is the band producer's verdict on THIS reading -- the
        producer stays the one judge of red. Every reading, never the snapshot.
        """
        arbiter = self._alertsArbiter
        if arbiter is None or getattr(reading, "parameterName", None) != "RPM":
            return
        timestamp = getattr(reading, "timestamp", None)
        if not isinstance(timestamp, datetime):
            return
        arbiter.observeRpmReading(
            getattr(reading, "value", None),
            tracker.eventUtc(timestamp),
            tracker.bandResultFor("RPM").band,
        )

    def _obdLiveNowUtc(self) -> datetime:
        """Aware UTC now for the obd-live staleness decision."""
        clock = self._obdLiveClock
        if clock is not None:
            now: datetime = clock()
            return now
        return datetime.now(UTC)

    def _gatherObdLiveDataSource(self) -> str | None:
        """The data_source tag the logger resolved for its rows, or None.

        Read from ``ObdDataLogger.dataSource`` -- the value
        ``_resolveDataSource`` set when the writer was built -- so obd-live
        carries the same tag as the rows, never a second derivation (and never
        system-status.runMode, which is a different fact). Only a tag in the
        legal vocabulary is published.
        """
        from pi.obdii.data_source import DATA_SOURCE_VALUES

        realtime = getattr(self, "_dataLogger", None)
        writer = getattr(realtime, "dataLogger", None) if realtime is not None else None
        tag = getattr(writer, "dataSource", None) if writer is not None else None
        return tag if isinstance(tag, str) and tag in DATA_SOURCE_VALUES else None

    def _emitObdLiveState(self) -> dict[str, Any] | None:
        """Publish states/obd-live from the tracker's latest readings.

        Returns:
            The payload written (US-897-b2, Atlas Q18: the alerts arbiter reads
            it), or None when nothing was published.
        """
        tracker = self._obdLiveTracker
        emitter = self._obdLiveEmitter
        if tracker is None or emitter is None or self._obdLiveStaleSec is None:
            return None
        nowUtc = self._obdLiveNowUtc()
        payload: dict[str, Any] | None = emitter(
            tracker.snapshot(),
            nowUtc=nowUtc,
            staleSec=self._obdLiveStaleSec,
            dataSource=self._gatherObdLiveDataSource(),
        )
        # US-889-a: the history is fed at the reading seam, never from this
        # snapshot; the tick only writes it when a bucket closed (or a reset).
        historyEmitter = self._engineHistoryEmitter
        if historyEmitter is not None:
            history = tracker.engineHistoryIfChanged()
            if history is not None:
                historyEmitter(history, nowUtc=nowUtc)
        return payload

    # --------------------------------------------------------- states/alerts
    #
    # US-897-b2 (F-127). The arbiter is shown the obd-live payload the tick has
    # just published -- never a file read-back -- so the alert and the Driving
    # tile can never disagree. Its alert_log INSERT goes through the database
    # object handed to it (G2); this mixin opens nothing.

    def _initializeAlertsProducer(self, statesDir: str) -> None:
        """Build the alerts arbiter + emitter in their own try/except.

        The arbiter is handed the FULL resolved config and seeded from this
        boot's tmpfs states/alerts (Atlas G3), so a restart inside the boot
        keeps a cleared STOP listed.
        """
        try:
            import os

            from pi.diagnostics import boot_progress, boot_reason
            from pi.obdii.alerts_arbiter import (
                AlertsArbiter,
                makeAlertsEmitter,
                readAlertsSeed,
            )

            self._alertsArbiter = AlertsArbiter(
                self._config, seedEntries=readAlertsSeed(statesDir)
            )
            self._alertsEmitter = makeAlertsEmitter(statesDir)
            # The boot_milestone precedent: with no boot-id surface (off-Linux, a
            # desk simulator run) readBootId could only say 'unknown' and would
            # log an ERROR saying so; answer it without the call.
            self._alertsBootId = (
                boot_progress.readBootId()
                if os.path.exists(boot_reason.BOOT_ID_PATH)
                else "unknown"
            )
            logger.info("alerts arbiter wired (boot_id=%s)", self._alertsBootId)
        except Exception as e:  # noqa: BLE001 -- must not fail boot
            logger.warning("alerts arbiter init skipped: %s", e)
            self._alertsArbiter = None
            self._alertsEmitter = None
            return
        # US-897-c: its own try, so a store fault costs the acks, not the alerts.
        try:
            from pi.obdii.alerts_ack_store import AlertsAckStore, ackStorePathOf

            self._alertsAckStore = AlertsAckStore(ackStorePathOf(self._config))
        except Exception as e:  # noqa: BLE001 -- must not fail boot
            logger.warning("alerts ack store init skipped: %s", e)
            self._alertsAckStore = None

    def _emitAlertsState(self, obdLive: dict[str, Any] | None) -> None:
        """Move the episodes on from ``obdLive`` and publish states/alerts.

        Args:
            obdLive: The payload ``_emitObdLiveState`` just wrote, or None.
        """
        arbiter = self._alertsArbiter
        emitter = self._alertsEmitter
        if arbiter is None or emitter is None:
            return
        dataSource = self._gatherObdLiveDataSource()
        nowUtc = self._obdLiveNowUtc()
        # US-897-b4: the over-rev ends at the recording -> idle edge -- its OWN
        # flag, never the fuel persist's.
        recording = self._gatherDriveState()[0] == "recording"
        driveEnded = self._alertsWasRecording and not recording
        self._alertsWasRecording = recording
        arbiter.observe(
            obdLive,
            dataSource=dataSource,
            database=getattr(self, "_database", None),
            driveRecording=recording,
            driveEnded=driveEnded,
        )
        self._alertsLastInputs = (obdLive, nowUtc, dataSource)
        self._publishAlertsState(arbiter, emitter, obdLive, nowUtc, dataSource)

    def emitNow(self) -> dict[str, Any] | None:
        """Republish states/alerts at once with the current acks (US-897-c).

        A PURE rebuild (Atlas G2): the arbiter's episodes as they stand plus the
        obdLive / nowUtc / dataSource the last alerts tick used -- never
        ``observe`` / ``observeDtc`` / ``observeRpmReading``, so no episode
        moves, no hold timer steps and no alert_log row is written (re-observing
        a cached reading would double-count the 10 s / 60 s holds). Before any
        tick it rebuilds from no obd-live payload. Runs on the run loop, the
        thread the tick runs on, so it takes no lock.

        Returns:
            The payload written, or None when there is no arbiter or emitter,
            or the write failed.
        """
        arbiter = self._alertsArbiter
        emitter = self._alertsEmitter
        if arbiter is None or emitter is None:
            return None
        inputs = self._alertsLastInputs
        if inputs is None:
            inputs = (None, self._obdLiveNowUtc(), self._gatherObdLiveDataSource())
        return self._publishAlertsState(arbiter, emitter, *inputs)

    def _publishAlertsState(
        self,
        arbiter: Any,
        emitter: Any,
        obdLive: dict[str, Any] | None,
        nowUtc: datetime,
        dataSource: str | None,
    ) -> dict[str, Any] | None:
        """The one alerts emit: this boot's matching acks in, then the prune.

        Every emit -- the tick and emitNow -- hands the store's matching id set
        (this boot AND the entry's current firstSeenTs) to the emitter, then
        prunes the records that can never match again against the sources this
        emit assessed (the store rewrites only on a change).
        """
        episodes = arbiter.episodes()
        store = self._alertsAckStore
        bootId = self._alertsBootId
        acked = store.matchingIds(episodes, bootId=bootId) if store is not None else ()
        payload = emitter(
            episodes,
            obdLive,
            nowUtc=nowUtc,
            dataSource=dataSource,
            bootId=bootId,
            codeSource=arbiter.codeSource(),
            acknowledgedIds=acked,
        )
        if store is not None and isinstance(payload, dict):
            sources = payload.get("sources") or {}
            store.prune(
                episodes,
                bootId=bootId,
                codeAssessed=(sources.get("code") or {}).get("assessed") is True,
                engineAssessed=(sources.get("engine") or {}).get("assessed") is True,
            )
        return payload

    def _resetAlertsRpmPeak(self) -> None:
        """Drive start: the over-rev peak counts from this drive (US-897-b4)."""
        arbiter = self._alertsArbiter
        if arbiter is None:
            return
        arbiter.resetRpmPeak()

    def _resetEngineHistory(self, driveStartTime: Any) -> None:
        """Open this drive's engine-history window at drive start (US-889-a).

        Args:
            driveStartTime: The drive session's start time (its event ts).
        """
        tracker = self._obdLiveTracker
        if tracker is None:
            return
        from pi.obdii.drive_id import getCurrentDriveId

        # The detector has already published the new drive_id on the context.
        tracker.resetEngineHistory(getCurrentDriveId(), driveStartTime)

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

        WHY THE READING SEAM AND NOT ONLY THE 2 s CARD CADENCE: derived on the
        tick alone, the newest sample would routinely be nearly as old as the
        freshness window itself and a perfectly healthy cruise would flicker to
        `stale`. The ratio is two floats and a table walk, so deriving it on
        every arrival is cheaper than the state-file write it feeds.

        US-686 CORRECTED THE CADENCE THIS NOTE USED TO CITE. It gave an
        aggregate Bluetooth bus rate, which is the same fiction that produced
        the 2.0 s window this seam was sized against; the MEASURED per-PID
        period is 2.206-2.249 s (Atlas, 2026-09-06). The seam is still right --
        more right, in fact, because arrivals are 9x rarer than the note assumed
        -- but the number behind it was not, and this was the THIRD home of that
        fiction after a census twice declared complete.

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

        US-687-b: the tick is ALSO what makes PARK reachable, and the two facts
        are the same fact. Park is published when RPM has been unusable for
        longer than the dwell, which by definition means no reading arrived to
        drive the callback seam -- so without the tick the producer would never
        run at the moment it has something new to say.

        NO SECOND ACQUISITION for the link health. `_gatherObdLinkState` is an
        existing method on `self` in this very mixin (the gear producer at :450
        and the link mapping at :636 are siblings), so the fact is read from the
        one place that owns it -- no state-file read-back, no second vocabulary
        for a link state, which is `ssot-design-pattern` rule B.
        """
        deriver = self._gearDeriver
        emitter = self._gearStateEmitter
        if deriver is None or emitter is None:
            return

        from pi.splash.system_status_emitter import OBD_LINKED

        linkState, _retries, obdAvailable, _reason = self._gatherObdLinkState()
        # OBD_RECONNECTING IS NOT HEALTHY. A flapping link reports obdAvailable
        # TRUE -- US-672 made availability ask "is the source ABSENT", and a car
        # we have reached before is not absent -- so gating on availability
        # alone would publish PARK while the car drove out of Bluetooth range.
        # Park needs the link actually LINKED.
        linkHealthy = obdAvailable and linkState == OBD_LINKED

        emitter(
            deriver.update(
                speed=self._lastSpeedReading,
                rpm=self._lastRpmReading,
                nowS=self._gearNowS(),
                linkHealthy=linkHealthy,
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
        # US-752: the resting state carries the codes the system ALREADY holds,
        # read from the persisted dtc_log -- never a re-query of the ECU (SSOT
        # rule B). Null when nothing is remembered, so "not read" keeps meaning.
        from pi.obdii.dtc_last_known import readFirstSeenByCode, readLastKnownDtcs

        database = getattr(self, "_database", None)
        payload = emitter(
            codes=[],
            mil=False,
            newSinceTs=None,
            dtcAvailable=False,
            lastKnown=readLastKnownDtcs(database),
            # US-897-a3: each remembered code ages from its first sighting
            # since the last clear.
            firstSeenByCode=readFirstSeenByCode(database),
            # US-897-a2: the seeded read times -- an unavailable source never
            # nulls them.
            checkedAtTs=getattr(self, "_dtcCheckedAtTs", None),
            pendingCheckedAtTs=getattr(self, "_dtcPendingCheckedAtTs", None),
        )
        # US-897-b5: the arbiter sees the boot state too -- codes null, so its
        # lastKnown makes no entry and sources.code stays unassessed ('?').
        arbiter = self._alertsArbiter
        if arbiter is not None and isinstance(payload, dict):
            arbiter.observeDtc(payload)

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
        try:
            # US-688: re-published every tick against a MOVED clock, like the
            # gear above -- the row age climbs whether or not anything arrives,
            # and a producer wired only to a write callback would go quiet at
            # exactly the moment writes stopped, which is the alert condition.
            self._emitCaptureHealthState()
        except Exception as e:  # noqa: BLE001 -- never crash the loop
            logger.debug("capture-health card emit failed: %s", e)
        obdLive: dict[str, Any] | None = None
        try:
            # US-874: staleness is decided here, against a moving clock.
            obdLive = self._emitObdLiveState()
        except Exception as e:  # noqa: BLE001 -- never crash the loop
            logger.debug("obd-live card emit failed: %s", e)
        try:
            # US-897-b2: AFTER obd-live, on the payload that emit returned.
            self._emitAlertsState(obdLive)
        except Exception as e:  # noqa: BLE001 -- never crash the loop
            logger.debug("alerts card emit failed: %s", e)
        try:
            # US-881-b: beside obd-live; MAF staleness is decided here too.
            self._emitFuelEconomyState()
        except Exception as e:  # noqa: BLE001 -- never crash the loop
            logger.debug("fuel-economy card emit failed: %s", e)
        return True

    # -------------------------------------------------------- trip distance
    #
    # US-880-a. Trip distance and MPG need ONE distance source (Atlas gaps 1-2):
    # SPEED readings on the reading seam, while a drive is recording, feed the
    # speed integrator; system-status drive.distanceKm publishes its total.

    def _initializeTripDistance(self) -> None:
        """Build the speed integrator from pi.trip.gapSec in its own try/except."""
        try:
            import threading

            from common.config.validator import DEFAULTS
            from pi.obdii.speed_integrator import SpeedIntegrator

            tripCfg = self._config.get("pi", {}).get("trip", {})
            gapSec = float(tripCfg.get("gapSec", DEFAULTS["pi.trip.gapSec"]))
            self._speedIntegrator = SpeedIntegrator(gapSec)
            self._tripLock = threading.Lock()
            logger.info("trip distance wired (gap_sec=%.1f)", gapSec)
        except Exception as e:  # noqa: BLE001 -- must not fail boot
            logger.warning("trip distance init skipped: %s", e)
            self._speedIntegrator = None
            self._tripLock = None

    def _tripNowS(self) -> float:
        """Monotonic seconds for the speed integrator's dt."""
        clock = self._tripClock
        if clock is not None:
            return float(clock())
        import time

        return time.monotonic()

    def _tripEventTs(self, eventTime: Any) -> str | None:
        """Canonical UTC for a reading/drive event time, or None if unusable.

        The logger and the drive detector stamp NAIVE local datetimes; the
        declared zone converts them. No zone, no timestamp -- never a guess.
        """
        if not isinstance(eventTime, datetime):
            return None
        try:
            from common.time.helper import localNaiveToCanonicalIso

            return localNaiveToCanonicalIso(eventTime, self._config)
        except Exception as e:  # noqa: BLE001 -- an unlabelled ts is None, not a crash
            logger.debug("trip distance event ts unavailable: %s", e)
            return None

    def observeTripSpeed(
        self, paramName: str, value: Any, eventTime: Any = None
    ) -> None:
        """Route one realtime reading into the speed integrator.

        Called from the orchestrator's reading callback for every parameter;
        returns at once for anything but SPEED, and ignores readings while no
        drive is recording (the recording fact is :meth:`_gatherDriveState`'s,
        never a second source).

        Args:
            paramName: The realtime parameter's name.
            value: Its value in km/h; None is ignored entirely.
            eventTime: The reading's capture time (labels a partial distance
                after a mid-drive process start).
        """
        integrator = self._speedIntegrator
        if integrator is None or paramName != "SPEED" or value is None:
            return
        if self._gatherDriveState()[0] != "recording":
            return
        tS = self._tripNowS()
        with self._tripLock:
            previousKm = self._tripDistanceKm
            km = integrator.update(float(value), tS)
            if self._tripDistanceKm is None and self._tripDistanceSinceTs is None:
                # No drive start seen this process (restart mid-drive): the
                # partial distance counts from THIS reading, and says so.
                self._tripDistanceSinceTs = self._tripEventTs(eventTime)
                self._tripDistancePartial = True
                self._tripDistanceEndTs = None
            self._tripDistanceKm = km
        # US-890-e: the window gets this reading's km delta under the FUEL lock,
        # taken only now the trip lock is released (Atlas G2).
        self._feedRecentDistance(tS, km - (previousKm or 0.0))

    def _feedRecentDistance(self, tS: float, kmDelta: float) -> None:
        """Add one SPEED interval's distance to the last-30 s fuel window."""
        window = self._fuelRecentWindow
        if window is None or self._fuelLock is None:
            return
        with self._fuelLock:
            # Clamped: a drive start between the two locks zeroed the distance.
            window.add(tS, km=max(0.0, kmDelta))

    def _resetTripDistance(self, driveStartTime: Any) -> None:
        """Zero the integrator at drive start; label the distance from it.

        Args:
            driveStartTime: The drive session's start time (its event ts).
        """
        integrator = self._speedIntegrator
        if integrator is None:
            return
        with self._tripLock:
            integrator.reset()
            self._tripDistanceKm = None
            self._tripDistanceSinceTs = self._tripEventTs(driveStartTime)
            self._tripDistancePartial = False
            self._tripDistanceEndTs = None

    def _markTripEnded(self, driveEndTime: Any) -> None:
        """Freeze drive.elapsedSec at the drive end (US-896-b, Atlas Q2/G2).

        The distance and its since-point are kept (the trip resets only at the
        next drive start), so without an end mark the elapsed would go on
        counting parked time as drive time. Same conversion as the reset.
        A session with no usable end time is marked at this callback's own UTC
        wall time: DriveDetector stamps endTime = now() the instant before it
        calls back, so that is the same moment, and an open window is not.

        Args:
            driveEndTime: The drive session's end time (its event ts).
        """
        if self._speedIntegrator is None:
            return
        endTs = self._tripEventTs(driveEndTime)
        if endTs is None:
            from common.time.helper import toCanonicalIso

            endTs = toCanonicalIso(self._obdLiveNowUtc())
        with self._tripLock:
            self._tripDistanceEndTs = endTs

    def _resetImuPeaks(self, driveStartTime: Any) -> None:
        """Clear the states/imu g peaks at drive start (US-892-a, Atlas ruling 4).

        The label is built by :meth:`_tripEventTs`, the trip reset's own
        conversion, so peaks.sinceTs equals drive.distanceSinceTs byte-for-byte.
        No bridge (IMU disabled) -> nothing to reset.

        Args:
            driveStartTime: The drive session's start time (its event ts).
        """
        bridge = getattr(self, "_imuStateBridge", None)
        if bridge is None:
            return
        bridge.resetPeaks(self._tripEventTs(driveStartTime))

    def _gatherTripDistance(self) -> tuple[float | None, str | None]:
        """Return (distanceKm, distanceSinceTs); (None, None) when not wired."""
        distanceKm, distanceSinceTs, _, _ = self._gatherTripWindow()
        return (distanceKm, distanceSinceTs)

    def _gatherTripWindow(
        self,
    ) -> tuple[float | None, str | None, str | None, bool | None]:
        """Return (distanceKm, sinceTs, endTs, partial) read under ONE lock.

        One read, so a drive start between two reads can never pair a new
        since-point with the last drive's end mark. All None when not wired.
        """
        if self._speedIntegrator is None:
            return (None, None, None, None)
        with self._tripLock:
            return (
                self._tripDistanceKm,
                self._tripDistanceSinceTs,
                self._tripDistanceEndTs,
                self._tripDistancePartial,
            )

    # -------------------------------------------------------- fuel economy
    #
    # US-881-b. MAF and FUEL_SYSTEM_STATUS on the reading seam, while a drive is
    # recording, feed the fuel integrator; the card tick publishes this drive's
    # fuel and MPG against the trip distance above -- never a second integrator.

    def _initializeFuelEconomyProducer(self, statesDir: str) -> None:
        """Build the fuel integrator + its emitter in their own try/except."""
        try:
            import threading

            from pi.obdii.fuel_economy_emitter import (
                FuelIntegrator,
                FuelSettings,
                RecentWindow,
                makeFuelEconomyEmitter,
            )
            from pi.obdii.obd_live_emitter import DEFAULT_OBD_LIVE_STALE_S

            settings = FuelSettings.fromConfig(self._config)
            staleCfg = self._config.get("pi", {}).get("display", {}).get("stale", {})
            self._fuelStaleSec = float(
                staleCfg.get("obdLiveSec", DEFAULT_OBD_LIVE_STALE_S)
            )
            self._fuelSettings = settings
            self._fuelIntegrator = FuelIntegrator(settings.gapSec)
            self._fuelRecentWindow = RecentWindow(settings.recentWindowSec)
            self._fuelLock = threading.Lock()
            self._fuelEconomyEmitter = makeFuelEconomyEmitter(statesDir)
            logger.info(
                "fuel-economy wired (stoich=%.2f density=%.0f maf_trusted=%s)",
                settings.stoichAfr, settings.densityGPerL, settings.mafTrusted,
            )
        except Exception as e:  # noqa: BLE001 -- must not fail boot
            logger.warning("fuel-economy producer init skipped: %s", e)
            self._fuelIntegrator = None
            self._fuelRecentWindow = None
            self._fuelEconomyEmitter = None
            self._fuelLock = None

    def observeFuelReading(
        self, paramName: str, value: Any, reading: Any = None
    ) -> None:
        """Route one realtime reading into the fuel integrator.

        Called from the orchestrator's reading callback for every parameter;
        returns at once for anything but MAF and FUEL_SYSTEM_STATUS, and
        ignores readings while no drive is recording (the recording fact is
        :meth:`_gatherDriveState`'s).

        The engine gate is asked through the obd-live tracker BEFORE the fuel
        lock is taken, so the two locks are never held together.

        Args:
            paramName: The realtime parameter's name.
            value: MAF in g/s, or the FUEL_SYSTEM_STATUS numeric code.
            reading: The reading itself; its capture time is the MAF event ts.
        """
        integrator = self._fuelIntegrator
        if integrator is None or paramName not in ("MAF", "FUEL_SYSTEM_STATUS"):
            return
        if self._gatherDriveState()[0] != "recording":
            return
        if paramName == "FUEL_SYSTEM_STATUS":
            with self._fuelLock:
                integrator.observeFuelStatus(value)
            return
        timestamp = getattr(reading, "timestamp", None)
        if value is None or not isinstance(timestamp, datetime):
            # Not a reading of anything: no value, or no event time to stamp.
            return
        from common.time.helper import resolveLocalZone

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=resolveLocalZone(self._config))
        eventUtc = timestamp.astimezone(UTC)
        tracker = self._obdLiveTracker
        engineRunning = None if tracker is None else tracker.engineRunningAt(reading)
        tS = self._tripNowS()
        with self._fuelLock:
            airG = integrator.observeMaf(float(value), tS, eventUtc, engineRunning)
            window = self._fuelRecentWindow
            if window is not None:
                # US-890-e: the SAME trapezoid air, never a second integral.
                window.add(tS, airG=airG, isMafSample=True)

    def _resetFuelEconomy(self) -> None:
        """Open this drive's fuel window at drive start (same clock as distance)."""
        integrator = self._fuelIntegrator
        if integrator is None:
            return
        tS = self._tripNowS()
        with self._fuelLock:
            integrator.reset(tS)
            if self._fuelRecentWindow is not None:
                self._fuelRecentWindow.reset()
            # A new drive has written nothing yet; its persist clock starts now.
            self._fuelWatermark = (0.0, 0.0, 0.0)
            self._fuelGeneration += 1
            self._fuelLastPersistS = tS

    def _emitFuelEconomyState(self) -> None:
        """Publish states/fuel-economy: fuel and distance read at one publish."""
        integrator = self._fuelIntegrator
        emitter = self._fuelEconomyEmitter
        if integrator is None or emitter is None or self._fuelStaleSec is None:
            return
        with self._fuelLock:
            snap = integrator.snapshot()
            window = self._fuelRecentWindow
            recent = None if window is None else window.snapshot()
            watermark = self._fuelWatermark
            generation = self._fuelGeneration
            lastPersistS = self._fuelLastPersistS
        distanceKm, distanceSinceTs = self._gatherTripDistance()
        nowUtc = self._obdLiveNowUtc()
        self._maybePersistFuelSinceReset(
            snap, distanceKm, nowUtc, watermark, generation, lastPersistS
        )
        emitter(
            snap,
            self._fuelSettings,
            distanceKm=distanceKm,
            distanceSinceTs=distanceSinceTs,
            nowUtc=nowUtc,
            staleSec=self._fuelStaleSec,
            sinceReset=self._fuelSinceReset,
            recent=recent,
        )

    def _fuelTotals(
        self, snap: Any, distanceKm: float | None
    ) -> tuple[float, float, float]:
        """This drive's (fuelL, km, openLoopS) -- what the watermark tracks."""
        return (
            self._fuelSettings.litresFromAirG(snap.airG),
            0.0 if distanceKm is None else float(distanceKm),
            snap.openLoopS,
        )

    def _maybePersistFuelSinceReset(
        self,
        snap: Any,
        distanceKm: float | None,
        nowUtc: datetime,
        watermark: tuple[float, float, float],
        generation: int,
        lastPersistS: float | None,
    ) -> None:
        """Add this drive's change since the watermark to fuel_since_reset.

        Runs on the card tick (the run loop): at drive end, and at most once
        per ``pi.fuel.persistSec`` while recording (Atlas G3). Only the change
        since the last persist is written, so a crash loses at most persistSec
        and never doubles. The cached row it leaves is what ``sinceReset``
        publishes. No database -> one WARN and a null ``sinceReset``.
        """
        database = getattr(self, "_database", None)
        if database is None:
            if not self._fuelNoDatabaseWarned:
                self._fuelNoDatabaseWarned = True
                logger.warning("fuel_since_reset: no database -- sinceReset stays null")
            return
        from common.time.helper import toCanonicalIso
        from pi.obdii import fuel_since_reset

        if not self._fuelSinceResetLoaded:
            self._fuelSinceResetLoaded = True
            try:
                self._fuelSinceReset = fuel_since_reset.readFrom(database)
            except Exception as e:  # noqa: BLE001 -- the publish must go on
                logger.warning("fuel_since_reset read failed: %s", e)
        recording = self._gatherDriveState()[0] == "recording"
        driveEnded = self._fuelWasRecording and not recording
        self._fuelWasRecording = recording
        nowS = self._tripNowS()
        if recording and lastPersistS is None:
            # Mid-drive process start: no drive start seen, so the persist
            # clock starts at the first recording tick.
            with self._fuelLock:
                if generation == self._fuelGeneration:
                    self._fuelLastPersistS = nowS
            return
        due = driveEnded or (
            recording
            and lastPersistS is not None
            and nowS - lastPersistS >= self._fuelSettings.persistSec
        )
        if not due:
            return
        current = self._fuelTotals(snap, distanceKm)
        # Clamped: a total below its watermark means a drive start this
        # snapshot has not seen yet -- never subtract from the row.
        deltas = tuple(max(0.0, c - w) for c, w in zip(current, watermark, strict=True))
        if any(d > 0 for d in deltas):
            try:
                self._fuelSinceReset = fuel_since_reset.accumulateAndReadFrom(
                    database, *deltas, toCanonicalIso(nowUtc)
                )
            except Exception as e:  # noqa: BLE001 -- retried at the next persist
                logger.warning("fuel_since_reset persist failed: %s", e)
                return
        with self._fuelLock:
            # A drive start since the snapshot owns the watermark now.
            if generation == self._fuelGeneration:
                self._fuelWatermark = current
                self._fuelLastPersistS = nowS

    def resetSinceReset(self, resetAtTs: str) -> dict[str, Any] | None:
        """Zero fuel_since_reset, the cached sinceReset AND the watermark together.

        Everything this drive integrated before the reset is behind it, so the
        watermark moves to the integrator's current totals (Atlas G4).

        Args:
            resetAtTs: Canonical UTC of the reset.

        Returns:
            The row after the reset, or None when the fuel producer or the
            database is absent.

        Raises:
            DatabaseConnectionError: When the reset cannot be written.
        """
        integrator = self._fuelIntegrator
        database = getattr(self, "_database", None)
        if integrator is None or database is None:
            return None
        from pi.obdii import fuel_since_reset

        with self._fuelLock:
            snap = integrator.snapshot()
            generation = self._fuelGeneration
        distanceKm, _ = self._gatherTripDistance()
        current = self._fuelTotals(snap, distanceKm)
        row = fuel_since_reset.resetAndReadFrom(database, resetAtTs)
        self._fuelSinceReset = row
        self._fuelSinceResetLoaded = True
        with self._fuelLock:
            if generation == self._fuelGeneration:
                self._fuelWatermark = current
        return row

    # -------------------------------------------------------- system-status

    def _emitSystemStatusState(self) -> None:
        """Gather truthful link/sync/power/drive readings + emit system-status."""
        emitter = self._systemStatusEmitter
        if emitter is None:
            return

        obdLinkState, obdRetries, obdAvailable, obdReason = self._gatherObdLinkState()
        powerSource, powerSourceReason = self._gatherPowerState()
        driveState, driveId = self._gatherDriveState()
        distanceKm, distanceSinceTs, distanceEndTs, distancePartial = (
            self._gatherTripWindow()
        )
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
            distanceKm=distanceKm,
            distanceSinceTs=distanceSinceTs,
            # US-896-b: the end mark freezes elapsedSec; the flag labels the window.
            distanceEndTs=distanceEndTs,
            distancePartial=distancePartial,
            # US-744: the US-728 verdict was computed on every boot and then
            # discarded. The emitter has taken this parameter since US-728, but
            # nothing ever passed it -- so the car published
            # "priorShutdown": null with 296 startup_log rows on disk
            # (measured on chi-eclipse-01, 2026-09-22).
            priorShutdown=self._gatherPriorShutdown(),
            obdAvailable=obdAvailable,
            obdUnavailableReason=obdReason,
            runMode=self._gatherRunMode(),
        )

    def _gatherRunMode(self) -> str:
        """Resolve the US-901-b runMode from pi.replay.active and --simulate.

        ``_simulate`` is read through ``getattr`` because it lives on the
        orchestrator core, and the standalone composers of this mixin never
        set it; they are not simulate runs.
        """
        from pi.splash.system_status_emitter import deriveRunMode

        replayConfig = ((self._config or {}).get("pi") or {}).get("replay") or {}
        return deriveRunMode(
            replayActive=bool(replayConfig.get("active", False)),
            simulate=bool(getattr(self, "_simulate", False)),
        )

    def _gatherPriorShutdown(self) -> dict | None:
        """Return the US-728 prior-shutdown block, or None when unreadable.

        Read through the US-728 reader and transported VERBATIM: the verdict is
        the producer's and is never recomputed here -- two producers of one fact
        is the SSOT defect, not the feature.

        The database is resolved through ``getattr`` AT USE TIME for the same
        boot-order reason :meth:`_gatherLastDriveSummary` documents: the
        emitters are built before the DB lands, so a captured reference stays
        None for the life of the process -- a permanently empty tile with fully
        green unit tests.

        Returns:
            The ``toStatePayload()`` block, or None when no ``startup_log`` row
            can be read -- which the card renders as "not read", a DIFFERENT
            fact from the NO RECORD verdict.
        """
        database = getattr(self, "_database", None)
        dbPath = getattr(database, "dbPath", None)
        if not dbPath:
            return None
        try:
            from pi.diagnostics.prior_shutdown_summary import (
                readPriorShutdownSummaryFromPath,
            )

            summary = readPriorShutdownSummaryFromPath(str(dbPath))
            return summary.toStatePayload() if summary is not None else None
        except Exception as e:  # noqa: BLE001 -- never block the emit loop
            logger.debug("prior-shutdown summary unavailable: %s", e)
            return None

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
            # US-873: straight after the synchronous read -- that instant IS
            # the UPS feed's sample time. A raise above never reaches here.
            self._recordUpsSample(vcellV)
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

    def _gatherBatteryHealthVerdict(self) -> Any:
        """Read the ARCH-065 verdict (T vs J) from the drain log + startup_log.

        The database is resolved through ``getattr`` AT USE TIME, never captured
        when the emitters are constructed (the US-501/US-502 boot-order trap),
        and the log is RE-read each tick so a new monthly test or sync reaches
        the card without a restart.

        The verdict is recomputed on EVERY emit tick, so an `unknown` here means
        "we ran, just now, and cannot say" -- the reason carries which cause.

        J's confirm-wait term is config ``pi.powerWatch.smoothingSec`` (Ruling
        10) and the provisional T's floor is ``pi.powerWatch.drainFloorVolts``
        (Ruling 19); when a key is absent the validator's DEFAULT is used,
        imported rather than restated.  The current pack is
        ``resolveCellEpoch(config)`` -- the one resolver the drain writers and
        the monthly-test due check use (Ruling 19).

        Returns:
            The :class:`~pi.power.battery_health_verdict.BatteryHealthVerdict`.
            An unknown verdict always carries a reason: the import failing, or
            the reader raising out, is reported as ``log_unreadable``.
        """
        try:
            from common.config.validator import DEFAULTS
            from pi.power.battery_health import resolveCellEpoch
            from pi.power.battery_health_verdict import (
                REASON_LOG_UNREADABLE,
                VERDICT_UNKNOWN,
                BatteryHealthVerdict,
                readBatteryHealthVerdict,
            )

            powerWatchCfg = self._config.get("pi", {}).get("powerWatch", {})
            smoothingSec = float(
                powerWatchCfg.get("smoothingSec", DEFAULTS["pi.powerWatch.smoothingSec"])
            )
            drainFloorVolts = float(
                powerWatchCfg.get(
                    "drainFloorVolts", DEFAULTS["pi.powerWatch.drainFloorVolts"]
                )
            )
            result = readBatteryHealthVerdict(
                database=getattr(self, "_database", None),
                nowIso=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                smoothingSec=smoothingSec,
                cellEpoch=resolveCellEpoch(self._config),
                drainFloorVolts=drainFloorVolts,
            )
        except Exception as e:  # noqa: BLE001 -- never block the emit loop
            logger.debug("battery-health verdict unavailable: %s", e)
            return _UnreadableBatteryVerdict()
        if result.verdict == VERDICT_UNKNOWN and not result.reason:
            return BatteryHealthVerdict(
                verdict=VERDICT_UNKNOWN,
                lastHealthCheckTs=result.lastHealthCheckTs,
                reason=REASON_LOG_UNREADABLE,
            )
        return result

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

        ``health`` / ``lastHealthCheckTs`` / ``timeToFloorS`` (also published as
        ``runtimeToCutoffS``) / ``jobAvgS`` / ``jobMaxS`` / ``provisional`` come
        from the ARCH-065 verdict producer and are ``unknown`` / null whenever
        it has nothing real to say. Every remaining
        field still has no in-process producer and stays a conservative honest
        value: no claimed calibration, no claimed full-charge, no rested
        history, no ladder. ``ambientTempC`` stays null by design -- the
        MAX17048 has NO temperature register, so US-504 removed the TEMP tile
        rather than invent a source; the column survives for a future BMP390.
        """
        result = self._gatherBatteryHealthVerdict()
        reason = result.reason
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
            "health": result.verdict,
            "fullChargeReached": False,
            "runtimeToCutoffS": result.timeToFloorS,
            "ambientTempC": None,
            "lastHealthCheckTs": result.lastHealthCheckTs,
            "ladder": None,
            "upsAvailable": upsAvailable,
            "timeToFloorS": result.timeToFloorS,
            "jobAvgS": result.jobAvgS,
            "jobMaxS": result.jobMaxS,
            "provisional": result.provisional,
        }
