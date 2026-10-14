################################################################################
# File Name: fuel_economy_emitter.py
# Purpose/Description: US-881-b (F-159) states/fuel-economy -- this drive's fuel
#                      (integrated from MAF at the fuel's stoich, no trims) and
#                      its MPG against the ONE speed integrator's distance
#                      (US-880-a), with an honest null and exactly one reason.
#                      Pure integrator + pure builder + atomic emit callable;
#                      opens no connection and reads no database.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-b) | Initial -- fuel integrator, null precedence,
#                                thisDrive payload, emit callable.
# 2026-10-14    | Rex (US-881-c) | Open-loop seconds, pi.fuel.persistSec, and
#                                sinceReset built from the fuel_since_reset row.
# ================================================================================
################################################################################

"""Publish this drive's fuel and MPG to ``states/fuel-economy`` (US-881-b).

The method is Spool's (pm/inbox 2026-10-14, sourced + measured on obd2db):

* **fuel = MAF / stoich of the FUEL, no trims.** Closed loop holds lambda 1, so
  the fuel's own stoich (``pi.fuel.stoichAfr``) is the right divisor; trims are
  below the density uncertainty and of ambiguous sign, so they are not applied.
* **Open loop uses the same math** and is reported, never skipped: the share of
  air seen in open loop is ``openLoopAirPct`` and makes the figure
  ``approximate`` past ``pi.fuel.approximateOpenLoopPct``.
* **The gap rule is the speed integrator's** (``pi.trip.gapSec``): an interval
  between MAF readings with ``dt <= 0`` or ``dt > gapSec`` adds no fuel, and its
  time counts as excluded.

The integrator reads no clock; ``tS`` is caller-supplied monotonic seconds, the
same seam ``SpeedIntegrator`` uses.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = [
    "FUEL_ECONOMY_STATE_FILENAME",
    "KM_PER_MILE",
    "LITERS_PER_US_GALLON",
    "MPG_NULL_REASONS",
    "FuelIntegrator",
    "FuelSettings",
    "FuelSnapshot",
    "buildFuelEconomyState",
    "makeFuelEconomyEmitter",
]

logger = logging.getLogger("pi.obdii.fuel_economy")

# The state name a page fetches: GET /fuel-economy.
FUEL_ECONOMY_STATE_FILENAME = "fuel-economy"

# Exact by definition, not config (NIST Handbook 44 Appendix C):
# US gallon = 231 in^3 x (2.54 cm)^3; international mile = 1609.344 m.
LITERS_PER_US_GALLON = 3.785411784
KM_PER_MILE = 1.609344

# decoders._FUEL_STATUS_ENUM: 2 = CL and 5 = CL-fault are closed loop. 1 OL,
# 3 OL-drive (decel AND enrichment), 4 OL-fault and 0/unknown are open loop.
CLOSED_LOOP_FUEL_STATUS_CODES = frozenset({2, 5})

# The mpgNullReason vocabulary, in PRECEDENCE order (Atlas G2): when several
# hold, the first one listed is the one published.
MPG_NULL_MAF_UNTRUSTED = "maf_untrusted"
MPG_NULL_MAF_STALE = "maf_stale"
MPG_NULL_MAF_ZERO_RUNNING = "maf_zero_running"
MPG_NULL_GAPS = "gaps"
MPG_NULL_TOO_SHORT = "too_short"
MPG_NULL_NO_FUEL = "no_fuel"
MPG_NULL_REASONS: tuple[str, ...] = (
    MPG_NULL_MAF_UNTRUSTED,
    MPG_NULL_MAF_STALE,
    MPG_NULL_MAF_ZERO_RUNNING,
    MPG_NULL_GAPS,
    MPG_NULL_TOO_SHORT,
    MPG_NULL_NO_FUEL,
)

_PERCENT = 100.0


@dataclass(frozen=True)
class FuelSettings:
    """The ``pi.fuel.*`` numbers plus the shared gap rule.

    Attributes:
        stoichAfr: Stoichiometric AFR of the fuel in the tank.
        densityGPerL: Fuel density, grams per litre.
        mafTrusted: False after a speed-density install: MPG is null.
        minMiles: MPG is null below this distance.
        maxExcludedPct: MPG is null when gap-excluded time exceeds this %.
        approximateOpenLoopPct: ``approximate`` at/above this open-loop air %.
        gapSec: ``pi.trip.gapSec`` -- the speed integrator's gap rule.
        persistSec: ``pi.fuel.persistSec`` -- the since-reset persist cadence
            while driving (US-881-c).
    """

    stoichAfr: float
    densityGPerL: float
    mafTrusted: bool
    minMiles: float
    maxExcludedPct: float
    approximateOpenLoopPct: float
    gapSec: float
    persistSec: float

    def litresFromAirG(self, airG: float) -> float:
        """Fuel litres for ``airG`` grams of air: air / stoich / density."""
        return airG / self.stoichAfr / self.densityGPerL

    @classmethod
    def fromConfig(cls, config: dict[str, Any]) -> FuelSettings:
        """Read the settings, each falling back to its validator default.

        Args:
            config: Validated config.

        Returns:
            The settings.
        """
        from common.config.validator import DEFAULTS

        pi = config.get("pi", {})
        fuel = pi.get("fuel", {})

        def _num(name: str) -> float:
            return float(fuel.get(name, DEFAULTS[f"pi.fuel.{name}"]))

        return cls(
            stoichAfr=_num("stoichAfr"),
            densityGPerL=_num("densityGPerL"),
            mafTrusted=bool(fuel.get("mafTrusted", DEFAULTS["pi.fuel.mafTrusted"])),
            minMiles=_num("minMiles"),
            maxExcludedPct=_num("maxExcludedPct"),
            approximateOpenLoopPct=_num("approximateOpenLoopPct"),
            gapSec=float(pi.get("trip", {}).get("gapSec", DEFAULTS["pi.trip.gapSec"])),
            persistSec=_num("persistSec"),
        )


@dataclass(frozen=True)
class FuelSnapshot:
    """One consistent read of the integrator.

    Attributes:
        started: False until a drive start or a first MAF reading opens the
            window -- nothing to report yet.
        airG: Air grams integrated over included intervals.
        openLoopAirG: The part of ``airG`` seen while not in closed loop.
        excludedS: Seconds of excluded (gap) intervals.
        windowS: Seconds from the window start to the newest MAF reading.
        lastMafGPerS: The newest MAF value, or None.
        lastMafEventUtc: Its aware UTC event time, or None.
        lastMafEngineRunning: The engine gate at that reading (None = unknown).
        openLoopS: Seconds of included intervals while not in closed loop
            (US-881-c: the since-reset open_loop_s).
    """

    started: bool
    airG: float
    openLoopAirG: float
    excludedS: float
    windowS: float
    lastMafGPerS: float | None
    lastMafEventUtc: datetime | None
    lastMafEngineRunning: bool | None
    openLoopS: float = 0.0


class FuelIntegrator:
    """Trapezoid air (and so fuel) from MAF readings, with the gap rule.

    Not thread-safe: the owner holds ONE lock around every call (Atlas G2).
    """

    def __init__(self, gapSec: float) -> None:
        """Build an integrator with no window open.

        Args:
            gapSec: An interval wider than this many seconds adds no fuel.
        """
        self._gapSec = float(gapSec)
        self._fuelStatusCode: int | None = None
        self._clear(None)

    def _clear(self, startS: float | None) -> None:
        self._started = startS is not None
        self._windowStartS = startS
        self._airG = 0.0
        self._openLoopAirG = 0.0
        self._openLoopS = 0.0
        self._excludedS = 0.0
        self._lastMafGPerS: float | None = None
        self._lastMafS: float | None = None
        self._lastMafEventUtc: datetime | None = None
        self._lastMafEngineRunning: bool | None = None

    def reset(self, tS: float) -> None:
        """Open a new window at drive start: zero fuel, forget the fuel status.

        Args:
            tS: Monotonic seconds of the drive start (the window start).
        """
        self._fuelStatusCode = None
        self._clear(tS)

    def observeFuelStatus(self, code: float | None) -> None:
        """Record the newest FUEL_SYSTEM_STATUS code (None = unknown)."""
        self._fuelStatusCode = None if code is None else int(code)

    def observeMaf(
        self,
        gPerS: float,
        tS: float,
        eventUtc: datetime,
        engineRunning: bool | None,
    ) -> None:
        """Integrate one MAF reading.

        Args:
            gPerS: Mass air flow, g/s.
            tS: The reading's monotonic seconds.
            eventUtc: Its aware UTC capture time.
            engineRunning: The engine gate at the reading, or None if unknown.
        """
        value = float(gPerS)
        if not self._started:
            # No drive start seen this process: the window opens here.
            self._clear(tS)
        lastS, lastValue = self._lastMafS, self._lastMafGPerS
        if lastS is not None and lastValue is not None:
            dt = tS - lastS
            if 0.0 < dt <= self._gapSec:
                airG = (lastValue + value) / 2.0 * dt
                self._airG += airG
                if self._fuelStatusCode not in CLOSED_LOOP_FUEL_STATUS_CODES:
                    self._openLoopAirG += airG
                    self._openLoopS += dt
            elif dt > 0.0:
                self._excludedS += dt
        self._lastMafGPerS = value
        self._lastMafS = tS
        self._lastMafEventUtc = eventUtc
        self._lastMafEngineRunning = engineRunning

    def snapshot(self) -> FuelSnapshot:
        """The integrator's state as one immutable read."""
        windowS = 0.0
        if self._windowStartS is not None and self._lastMafS is not None:
            windowS = max(0.0, self._lastMafS - self._windowStartS)
        return FuelSnapshot(
            started=self._started,
            airG=self._airG,
            openLoopAirG=self._openLoopAirG,
            excludedS=self._excludedS,
            windowS=windowS,
            lastMafGPerS=self._lastMafGPerS,
            lastMafEventUtc=self._lastMafEventUtc,
            lastMafEngineRunning=self._lastMafEngineRunning,
            openLoopS=self._openLoopS,
        )


def _mpgNullReason(
    snap: FuelSnapshot,
    settings: FuelSettings,
    *,
    fuelL: float,
    distanceKm: float | None,
    nowUtc: datetime,
    staleSec: float,
) -> str | None:
    """The ONE reason MPG is null, by Atlas G2 precedence; None when it is not."""
    if not settings.mafTrusted:
        return MPG_NULL_MAF_UNTRUSTED
    if (
        snap.lastMafEventUtc is None
        or (nowUtc - snap.lastMafEventUtc).total_seconds() > staleSec
    ):
        return MPG_NULL_MAF_STALE
    if (
        snap.lastMafGPerS is not None
        and snap.lastMafGPerS <= 0
        and snap.lastMafEngineRunning is True
    ):
        return MPG_NULL_MAF_ZERO_RUNNING
    if snap.windowS > 0 and snap.excludedS > settings.maxExcludedPct / _PERCENT * snap.windowS:
        return MPG_NULL_GAPS
    # No distance read is no distance covered as far as MPG can tell.
    if distanceKm is None or distanceKm / KM_PER_MILE < settings.minMiles:
        return MPG_NULL_TOO_SHORT
    if fuelL <= 0:
        return MPG_NULL_NO_FUEL
    return None


def _sinceResetPayload(
    row: Mapping[str, Any] | None, settings: FuelSettings
) -> dict[str, Any] | None:
    """The ``sinceReset`` block from the fuel_since_reset row (US-881-c).

    Its ``mpg`` follows the ``maf_untrusted`` and ``too_short`` rules, and is
    null with no fuel (the ratio is undefined). None before any row.
    """
    if row is None:
        return None
    fuelL = float(row["fuel_l"] or 0.0)
    distanceKm = float(row["distance_km"] or 0.0)
    mpg = None
    if (
        settings.mafTrusted
        and distanceKm / KM_PER_MILE >= settings.minMiles
        and fuelL > 0
    ):
        mpg = (distanceKm / KM_PER_MILE) / (fuelL / LITERS_PER_US_GALLON)
    return {
        "fuelL": fuelL,
        "distanceKm": distanceKm,
        "mpg": mpg,
        "resetAtTs": row["reset_at_ts"],
    }


def buildFuelEconomyState(
    snap: FuelSnapshot,
    settings: FuelSettings,
    *,
    distanceKm: float | None,
    distanceSinceTs: str | None,
    nowUtc: datetime,
    staleSec: float,
    sinceReset: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the states/fuel-economy payload.

    Args:
        snap: The fuel integrator's snapshot.
        settings: The fuel settings.
        distanceKm: The speed integrator's distance at this same publish.
        distanceSinceTs: Its window label; MPG's one window (Atlas G2).
        nowUtc: Aware UTC instant of this publish (judges MAF staleness).
        staleSec: ``pi.display.stale.obdLiveSec``.
        sinceReset: The fuel_since_reset row (``fuel_since_reset.read``), or
            None before any row / without a database.

    Returns:
        ``{thisDrive, sinceReset, ts}``. ``thisDrive`` is null until a window
        opens; ``mpgNullReason`` is present only when ``mpg`` is null.
        ``sinceReset`` is ``{fuelL, distanceKm, mpg, resetAtTs}`` or null.
        ``ts`` is the newest MAF reading's event time, null when none was
        integrated.
    """
    from common.time.helper import toCanonicalIso

    thisDrive: dict[str, Any] | None = None
    if snap.started:
        fuelL = settings.litresFromAirG(snap.airG)
        openLoopAirPct = (
            None if snap.airG <= 0 else snap.openLoopAirG / snap.airG * _PERCENT
        )
        reason = _mpgNullReason(
            snap,
            settings,
            fuelL=fuelL,
            distanceKm=distanceKm,
            nowUtc=nowUtc,
            staleSec=staleSec,
        )
        mpg = None
        if reason is None and distanceKm is not None:
            mpg = (distanceKm / KM_PER_MILE) / (fuelL / LITERS_PER_US_GALLON)
        thisDrive = {
            "fuelL": fuelL,
            "mpg": mpg,
            "sinceTs": distanceSinceTs,
            "approximate": (
                openLoopAirPct is not None
                and openLoopAirPct >= settings.approximateOpenLoopPct
            ),
            "openLoopAirPct": openLoopAirPct,
        }
        if mpg is None:
            thisDrive["mpgNullReason"] = reason
    return {
        "thisDrive": thisDrive,
        "sinceReset": _sinceResetPayload(sinceReset, settings),
        "ts": (
            None if snap.lastMafEventUtc is None else toCanonicalIso(snap.lastMafEventUtc)
        ),
    }


def makeFuelEconomyEmitter(statesDir: str) -> Callable[..., None]:
    """Build the states/fuel-economy emit callable.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).

    Returns:
        ``emit(snap, settings, *, distanceKm, distanceSinceTs, nowUtc,
        staleSec, sinceReset=None)`` writing the payload atomically. Best-effort by contract:
        write failures are logged, never raised.
    """
    from pi.splash import boot_state_emitter

    target = os.path.join(statesDir, FUEL_ECONOMY_STATE_FILENAME)

    def emit(
        snap: FuelSnapshot,
        settings: FuelSettings,
        *,
        distanceKm: float | None,
        distanceSinceTs: str | None,
        nowUtc: datetime,
        staleSec: float,
        sinceReset: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            boot_state_emitter.ensureStatesDir(statesDir)
            boot_state_emitter.writeStateAtomic(
                target,
                buildFuelEconomyState(
                    snap,
                    settings,
                    distanceKm=distanceKm,
                    distanceSinceTs=distanceSinceTs,
                    nowUtc=nowUtc,
                    staleSec=staleSec,
                    sinceReset=sinceReset,
                ),
            )
        except Exception as e:  # noqa: BLE001 -- never crash the run loop
            logger.error("states/fuel-economy write failed (%s) -- ignored", e)

    return emit
