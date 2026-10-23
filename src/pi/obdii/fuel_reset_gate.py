################################################################################
# File Name: fuel_reset_gate.py
# Purpose/Description: US-923 (F-159) the ONE MPG-reset predicate. Allowed when
#                      the RAW derived gear is P or N, or when SPEED is fresh and
#                      at or under pi.fuel.resetMaxSpeedKph in any gear. The
#                      orchestrator publishes it in states/fuel-economy for the
#                      page to render AND re-checks it when a POST /fuel-reset
#                      lands, so the page word and the outcome cannot disagree.
#                      Pure: no clock, no state file, no config read.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Rex (US-923) | Initial (CIO 2026-10-22, Atlas C1-C5).
# ================================================================================
################################################################################

"""Whether the since-reset MPG may be reset now (US-923).

THE RULE (CIO 2026-10-22: "speed <= 5 = slow rolling in any gear"; Atlas C1):

* **parked** -- the deriver's own GearReading, available, gear ``P`` or ``N``.
  RAW: no 8 s hold, for the reset only (Atlas C2; the page's parked debounce
  stays the gate for Clear, the code-row tap and Settings). A cached reading
  older than ``maxAgeS`` is ABSENT (Atlas Rule 13 GAP 1): a P the tick derived
  before the car moved off must never allow a reset at speed.
* **or slow** -- the deriver's own SPEED reading, fresh within ``maxAgeS``
  (``pi.gear.maxAgeSec``, the same freshness rule as ``GearDeriver._liveValue``)
  and at or under ``maxKph`` (``pi.fuel.resetMaxSpeedKph``).

Refusal reasons (Atlas C4): ``driving`` when not parked and a fresh SPEED is
over the limit; ``speed_unknown`` when not parked and SPEED is missing or
stale. Unknown speed never allows the reset.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from pi.obdii.gear_derivation import GEAR_NEUTRAL, GEAR_PARK

__all__ = [
    "REASON_DRIVING",
    "REASON_SPEED_UNKNOWN",
    "resetAllowed",
]

# The two refusal codes. `driving` is the reason core.py has always returned on
# a refused reset (US-881-d), so the page's 409 mapping keeps its key; the page
# word for it changes to "slow to reset" (Iris, fuel spec 4.3/4.6).
REASON_DRIVING = "driving"
REASON_SPEED_UNKNOWN = "speed_unknown"

_PARKED_GEARS = (GEAR_PARK, GEAR_NEUTRAL)


def _isParked(gear: tuple[Any, float] | None, nowS: float, maxAgeS: float) -> bool:
    """A cached (GearReading, derivedAtS) that is fresh and reads P or N."""
    if gear is None:
        return False
    reading, atS = gear
    if reading is None or nowS - atS > maxAgeS:
        return False
    return reading.available is True and reading.gear in _PARKED_GEARS


def _freshSpeed(speed: Any, nowS: float, maxAgeS: float) -> float | None:
    """The SPEED value when present, finite and fresh (``_liveValue``'s rule)."""
    if speed is None or speed.value is None:
        return None
    value = float(speed.value)
    if not isfinite(value) or nowS - speed.tsS > maxAgeS:
        return None
    return value


def resetAllowed(
    gearReading: tuple[Any, float] | None,
    speedReading: Any,
    nowS: float,
    maxAgeS: float,
    maxKph: float,
) -> dict[str, Any]:
    """Decide whether the since-reset MPG may be reset now.

    Args:
        gearReading: The emitter's cached ``(GearReading, derivedAtS)`` pair
            (``_lastGearReading``, ``_lastGearAtS``), or None before any
            derivation.
        speedReading: The deriver's own SPEED ``Reading`` (``_lastSpeedReading``),
            or None.
        nowS: Monotonic seconds on the clock both readings were stamped with
            (``_gearNowS``).
        maxAgeS: ``pi.gear.maxAgeSec`` -- the freshness window for both.
        maxKph: ``pi.fuel.resetMaxSpeedKph``.

    Returns:
        ``{"value": True, "reason": None}`` when allowed, else
        ``{"value": False, "reason": "driving" | "speed_unknown"}``.
    """
    if _isParked(gearReading, nowS, maxAgeS):
        return {"value": True, "reason": None}
    kph = _freshSpeed(speedReading, nowS, maxAgeS)
    if kph is None:
        return {"value": False, "reason": REASON_SPEED_UNKNOWN}
    if kph <= maxKph:
        return {"value": True, "reason": None}
    return {"value": False, "reason": REASON_DRIVING}
