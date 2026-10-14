################################################################################
# File Name: band_producer.py
# Purpose/Description: US-875 (F-159) the band producer for states/obd-live.
#                      Derives each live PID's band {band, since, reason} -- or
#                      null with a machine-code noBandReason -- so pages colour
#                      engine numbers without holding a threshold: coolant
#                      threshold + dwell + clear hysteresis, battery RED/GREEN
#                      gated on the engine running, RPM bar cues, and no band
#                      for everything else.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-875) | Initial -- coolant dwell, battery engine gate,
#                                RPM cues and scale.
# 2026-10-14    | Rex (US-881-b) | Public engineRunningAt(ts) wrapper (no logic
#                                change) for the fuel-economy producer.
# ================================================================================
################################################################################

"""Derive the live band of every PID in ``states/obd-live`` (US-875).

Pages render; providers compute (Atlas 08-20 rule). Every number below is a
``pi.bands.*`` config key whose default and source live in the validator; this
module holds none.

Three rules are load-bearing:

* **A dwell is CONSECUTIVE readings on EVENT time.** It resets when a reading
  arrives more than ``pi.display.stale.obdLiveSec`` after the previous one (a
  stale gap) or when a null reading arrives. A sliding window is not a dwell.
* **The battery is banded only while the engine runs.** Engine-off means RPM
  STOPS reporting, not that it reads 0, so a last-known RPM > 0 is not
  "running": the latest RPM must be fresh relative to the battery reading.
  Readings are paired by event time, so an RPM that arrives after a battery
  reading with the same timestamp re-evaluates it.
* **The band is decided per reading, then frozen.** Staleness is the emitter's
  decision at emit time; a stale PID publishes ``band: null`` with
  ``noBandReason: 'stale'`` and this band under ``last``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = [
    "BAND_AMBER",
    "BAND_GREEN",
    "BAND_RED",
    "NO_BAND_AMBER_NOT_SHIPPED",
    "NO_BAND_ENGINE_NOT_RUNNING",
    "NO_BAND_NOT_READ",
    "NO_BAND_NO_BAND_DEFINED",
    "NO_BAND_REASONS",
    "NO_BAND_STALE",
    "PID_BATTERY",
    "PID_COOLANT",
    "PID_RPM",
    "BandProducer",
    "BandResult",
    "BandSettings",
]

BAND_GREEN = "green"
BAND_AMBER = "amber"
BAND_RED = "red"

# noBandReason vocabulary (Atlas ruling 2026-10-13 on Iris S-5).
NO_BAND_NOT_READ = "not_read"
NO_BAND_STALE = "stale"
NO_BAND_NO_BAND_DEFINED = "no_band_defined"
NO_BAND_ENGINE_NOT_RUNNING = "engine_not_running"
NO_BAND_AMBER_NOT_SHIPPED = "amber_not_shipped"
NO_BAND_REASONS = (
    NO_BAND_NOT_READ,
    NO_BAND_STALE,
    NO_BAND_NO_BAND_DEFINED,
    NO_BAND_ENGINE_NOT_RUNNING,
    NO_BAND_AMBER_NOT_SHIPPED,
)

PID_COOLANT = "COOLANT_TEMP"
PID_BATTERY = "BATTERY_V"
PID_RPM = "RPM"


@dataclass(frozen=True)
class BandResult:
    """The band of one PID at its latest reading.

    Exactly one of the two fields is set.

    Attributes:
        band: ``{band, since, reason}`` or None.
        noBandReason: A ``NO_BAND_REASONS`` code when ``band`` is None.
    """

    band: dict[str, str] | None
    noBandReason: str | None


@dataclass(frozen=True)
class BandSettings:
    """Every ``pi.bands.*`` number, plus the stale window that resets a dwell."""

    coolantAmberC: float
    coolantAmberDwellSec: float
    coolantRedC: float
    coolantRedDwellSec: float
    coolantClearBelowC: float
    coolantClearHoldSec: float
    batteryRpmMaxAgeSec: float
    batteryRunningRpmMin: float
    batteryCrankGuardSec: float
    batteryGreenMinV: float
    batteryGreenMaxV: float
    batteryRedBelowV: float
    batteryRedAboveV: float
    rpmAmberRpm: float
    rpmRedRpm: float
    staleSec: float

    @classmethod
    def fromConfig(cls, config: dict[str, Any]) -> BandSettings:
        """Read the settings from a config, falling back to the validator defaults.

        Args:
            config: Configuration mapping (validated or raw).

        Returns:
            The resolved settings.
        """
        from common.config.validator import DEFAULTS

        def read(path: str) -> float:
            node: Any = config
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    return float(DEFAULTS[path])
                node = node[part]
            return float(DEFAULTS[path] if node is None else node)

        return cls(
            coolantAmberC=read("pi.bands.coolant.amberC"),
            coolantAmberDwellSec=read("pi.bands.coolant.amberDwellSec"),
            coolantRedC=read("pi.bands.coolant.redC"),
            coolantRedDwellSec=read("pi.bands.coolant.redDwellSec"),
            coolantClearBelowC=read("pi.bands.coolant.clearBelowC"),
            coolantClearHoldSec=read("pi.bands.coolant.clearHoldSec"),
            batteryRpmMaxAgeSec=read("pi.bands.battery.rpmMaxAgeSec"),
            batteryRunningRpmMin=read("pi.bands.battery.runningRpmMin"),
            batteryCrankGuardSec=read("pi.bands.battery.crankGuardSec"),
            batteryGreenMinV=read("pi.bands.battery.greenMinV"),
            batteryGreenMaxV=read("pi.bands.battery.greenMaxV"),
            batteryRedBelowV=read("pi.bands.battery.redBelowV"),
            batteryRedAboveV=read("pi.bands.battery.redAboveV"),
            rpmAmberRpm=read("pi.bands.rpm.amberRpm"),
            rpmRedRpm=read("pi.bands.rpm.redRpm"),
            staleSec=read("pi.display.stale.obdLiveSec"),
        )


def _num(x: float) -> str:
    """A number as prose: 104.0 -> '104', 13.5 -> '13.5'."""
    return f"{x:g}"


def _iso(ts: datetime) -> str:
    from common.time.helper import toCanonicalIso

    return toCanonicalIso(ts)


@dataclass(frozen=True)
class _RpmSample:
    ts: datetime
    rpm: float
    # True when this sample entered RPM >= runningRpmMin: its predecessor was
    # below it, absent, or older than rpmMaxAgeSec (the engine was off).
    isRunningTransition: bool


class _Tracked:
    """The band of one PID; ``since`` and ``reason`` change only on a transition."""

    def __init__(self) -> None:
        self.result = BandResult(band=None, noBandReason=NO_BAND_NOT_READ)

    def set(self, band: str | None, reason: str, ts: datetime) -> None:
        """Record ``band`` (or the no-band code in ``reason``) as of ``ts``."""
        if band is None:
            self.result = BandResult(band=None, noBandReason=reason)
            return
        current = self.result.band
        if current is not None and current["band"] == band:
            return
        self.result = BandResult(
            band={"band": band, "since": _iso(ts), "reason": reason}, noBandReason=None
        )

    @property
    def bandName(self) -> str | None:
        return None if self.result.band is None else self.result.band["band"]


class BandProducer:
    """Per-PID band state, fed every reading in event-time order per PID.

    Not thread-safe: the caller (``ObdLiveTracker``) holds its own lock.
    """

    def __init__(self, settings: BandSettings) -> None:
        """
        Args:
            settings: The resolved ``pi.bands.*`` numbers.
        """
        self._s = settings
        self._bands: dict[str, _Tracked] = {}
        # Coolant dwell clocks: start of the current consecutive run.
        self._coolantLastTs: datetime | None = None
        self._coolantAboveAmberSince: datetime | None = None
        self._coolantBelowClearSince: datetime | None = None
        # RPM history long enough to pair a battery reading and see its guard.
        self._rpmSamples: deque[_RpmSample] = deque()
        self._battery: tuple[float, datetime] | None = None

    @property
    def rpmScale(self) -> dict[str, float]:
        """The RPM bar zones, from the SAME keys the RPM band uses."""
        return {"amberFrom": self._s.rpmAmberRpm, "redFrom": self._s.rpmRedRpm}

    def resultFor(self, name: str) -> BandResult:
        """The band of ``name`` at its latest reading.

        Args:
            name: PID name.

        Returns:
            The band, ``no_band_defined`` for a PID with no band rule, or
            ``not_read`` for a banded PID with no reading yet.
        """
        if name not in (PID_COOLANT, PID_BATTERY, PID_RPM):
            return BandResult(band=None, noBandReason=NO_BAND_NO_BAND_DEFINED)
        tracked = self._bands.get(name)
        if tracked is None:
            return BandResult(band=None, noBandReason=NO_BAND_NOT_READ)
        return tracked.result

    def observe(self, name: str, value: Any, ts: datetime) -> None:
        """Feed one reading.

        Args:
            name: PID name.
            value: The reading's value; None is a null reading, which resets
                every dwell of that PID.
            ts: Aware UTC event time of the reading (sub-second precision kept).
        """
        if name == PID_COOLANT:
            self._observeCoolant(value, ts)
        elif name == PID_RPM:
            self._observeRpm(value, ts)
        elif name == PID_BATTERY:
            if value is None:
                self._battery = None
                return
            self._battery = (float(value), ts)
            self._classifyBattery()

    def _tracked(self, name: str) -> _Tracked:
        return self._bands.setdefault(name, _Tracked())

    # ------------------------------------------------------------- coolant

    def _observeCoolant(self, value: Any, ts: datetime) -> None:
        s = self._s
        if value is None:
            self._coolantLastTs = None
            self._coolantAboveAmberSince = None
            self._coolantBelowClearSince = None
            return
        if (
            self._coolantLastTs is not None
            and (ts - self._coolantLastTs).total_seconds() > s.staleSec
        ):
            # A stale gap resets every dwell; the band itself carries over.
            self._coolantAboveAmberSince = None
            self._coolantBelowClearSince = None
        self._coolantLastTs = ts

        temp = float(value)
        if temp >= s.coolantAmberC:
            self._coolantAboveAmberSince = self._coolantAboveAmberSince or ts
        else:
            self._coolantAboveAmberSince = None
        if temp < s.coolantClearBelowC:
            self._coolantBelowClearSince = self._coolantBelowClearSince or ts
        else:
            self._coolantBelowClearSince = None

        aboveFor = (
            None
            if self._coolantAboveAmberSince is None
            else (ts - self._coolantAboveAmberSince).total_seconds()
        )
        clearFor = (
            None
            if self._coolantBelowClearSince is None
            else (ts - self._coolantBelowClearSince).total_seconds()
        )
        tracked = self._tracked(PID_COOLANT)
        current = tracked.bandName

        if current != BAND_RED:
            if temp >= s.coolantRedC:
                tracked.set(BAND_RED, f"coolant >= {_num(s.coolantRedC)} C", ts)
                return
            if aboveFor is not None and aboveFor >= s.coolantRedDwellSec:
                tracked.set(
                    BAND_RED,
                    f"coolant >= {_num(s.coolantAmberC)} C for "
                    f"{_num(s.coolantRedDwellSec)} s",
                    ts,
                )
                return
        if current in (BAND_AMBER, BAND_RED):
            if clearFor is not None and clearFor >= s.coolantClearHoldSec:
                tracked.set(
                    BAND_GREEN,
                    f"coolant below {_num(s.coolantClearBelowC)} C for "
                    f"{_num(s.coolantClearHoldSec)} s",
                    ts,
                )
            return
        if aboveFor is not None and aboveFor >= s.coolantAmberDwellSec:
            tracked.set(
                BAND_AMBER,
                f"coolant >= {_num(s.coolantAmberC)} C for {_num(s.coolantAmberDwellSec)} s",
                ts,
            )
            return
        tracked.set(
            BAND_GREEN,
            f"coolant has not held >= {_num(s.coolantAmberC)} C for "
            f"{_num(s.coolantAmberDwellSec)} s",
            ts,
        )

    # ----------------------------------------------------------------- RPM

    def _observeRpm(self, value: Any, ts: datetime) -> None:
        s = self._s
        if value is None:
            return
        rpm = float(value)
        previous = self._rpmSamples[-1] if self._rpmSamples else None
        isTransition = rpm >= s.batteryRunningRpmMin and (
            previous is None
            or previous.rpm < s.batteryRunningRpmMin
            or (ts - previous.ts).total_seconds() > s.batteryRpmMaxAgeSec
        )
        self._rpmSamples.append(_RpmSample(ts, rpm, isTransition))
        # Keep what a battery reading up to rpmMaxAgeSec behind the newest RPM
        # could still need: its own pairing window plus its crank guard.
        horizon = 2.0 * (s.batteryRpmMaxAgeSec + s.batteryCrankGuardSec)
        while (
            len(self._rpmSamples) > 1
            and (ts - self._rpmSamples[0].ts).total_seconds() > horizon
        ):
            self._rpmSamples.popleft()

        tracked = self._tracked(PID_RPM)
        if rpm >= s.rpmRedRpm:
            tracked.set(BAND_RED, f"rpm >= {_num(s.rpmRedRpm)}", ts)
        elif rpm >= s.rpmAmberRpm:
            tracked.set(BAND_AMBER, f"rpm >= {_num(s.rpmAmberRpm)}", ts)
        else:
            tracked.set(BAND_GREEN, f"rpm below {_num(s.rpmAmberRpm)}", ts)

        # An RPM at or before the latest battery reading may change its pairing.
        if self._battery is not None and ts <= self._battery[1]:
            self._classifyBattery()

    # ------------------------------------------------------------- battery

    def engineRunningAt(self, ts: datetime) -> bool:
        """Public read of the engine-running gate at event time ``ts`` (US-881-b).

        A wrapper with no logic of its own: the fuel-economy producer asks the
        same question the battery band asks, through ``ObdLiveTracker``, which
        holds this producer behind its lock.

        Args:
            ts: Aware UTC event time.

        Returns:
            True when the engine was running at ``ts``.
        """
        return self._engineRunningAt(ts)

    def _engineRunningAt(self, ts: datetime) -> bool:
        """The engine-running gate (Spool, measured 2026-10-13) at event time ``ts``."""
        s = self._s
        paired = [sample for sample in self._rpmSamples if sample.ts <= ts]
        if not paired:
            return False
        latest = paired[-1]
        if (ts - latest.ts).total_seconds() > s.batteryRpmMaxAgeSec:
            return False
        if latest.rpm < s.batteryRunningRpmMin:
            return False
        anchors = [
            sample.ts
            for sample in paired
            if sample.isRunningTransition or 0 < sample.rpm < s.batteryRunningRpmMin
        ]
        return not (
            anchors and (ts - max(anchors)).total_seconds() <= s.batteryCrankGuardSec
        )

    def _classifyBattery(self) -> None:
        s = self._s
        if self._battery is None:
            return
        volts, ts = self._battery
        tracked = self._tracked(PID_BATTERY)
        if not self._engineRunningAt(ts):
            tracked.set(None, NO_BAND_ENGINE_NOT_RUNNING, ts)
        elif volts < s.batteryRedBelowV:
            tracked.set(
                BAND_RED,
                f"battery below {_num(s.batteryRedBelowV)} V with the engine running",
                ts,
            )
        elif volts > s.batteryRedAboveV:
            tracked.set(
                BAND_RED,
                f"battery above {_num(s.batteryRedAboveV)} V with the engine running",
                ts,
            )
        elif s.batteryGreenMinV <= volts <= s.batteryGreenMaxV:
            tracked.set(
                BAND_GREEN,
                f"battery {_num(s.batteryGreenMinV)}-{_num(s.batteryGreenMaxV)} V "
                "with the engine running",
                ts,
            )
        else:
            tracked.set(None, NO_BAND_AMBER_NOT_SHIPPED, ts)
