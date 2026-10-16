################################################################################
# File Name: units.py
# Purpose/Description: US-888-b (F-140) -- the ONE map from python-obd's unit
#                      names to the short canonical units states/ publishes
#                      (Atlas units ruling (a), 2026-10-15). Applied once, in
#                      ObdLiveTracker.observeReading; obd.db keeps what was
#                      captured.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-888-b) | Initial -- CANONICAL_UNITS + canonicalUnit.
# ================================================================================
################################################################################

"""Canonical short units for the states/ display contract (US-888-b).

python-obd reports pint unit names (``degree_Celsius``, ``kilometer_per_hour``).
Those are a library's implementation detail; the states/ contract is ours, so
the provider normalises them once and every page reads ``C`` / ``km/h`` / ``V``
/ ``rpm``. The database is not touched: stored history keeps the captured
strings.

A string this map does not know passes through UNCHANGED. The status PIDs carry
a label in the unit column (FUEL_SYSTEM_STATUS ``CL``/``OL-drive``, MIL_ON
``ON``/``OFF``) and are read by value, never by unit -- so passing them through
is correct, and a WARN (once per distinct string) surfaces a genuinely new unit
without flooding the journal at the polling rate.
"""

from __future__ import annotations

import logging
import threading

__all__ = ["CANONICAL_UNITS", "canonicalUnit"]

logger = logging.getLogger("pi.obdii.units")

# MEASURED python-obd names (obd2db realtime_data since 2026-10-12) -> the
# canonical unit. The map is Atlas's ruling verbatim.
CANONICAL_UNITS: dict[str, str] = {
    "degree_Celsius": "C",
    "kilometer_per_hour": "km/h",
    "volt": "V",
    "revolutions_per_minute": "rpm",
    "percent": "%",
    "degree": "deg",
    "gps": "g/s",
    "count": "count",
}

_CANONICAL_VALUES = frozenset(CANONICAL_UNITS.values())

# Unknown strings already warned about this process (WARN once per string).
_warnedUnits: set[str] = set()
_warnLock = threading.Lock()


def canonicalUnit(raw: str | None) -> str | None:
    """The canonical short unit for a reading's unit string.

    Args:
        raw: The unit as the reading carried it (a python-obd name, an
            already-canonical unit, a status label, or None).

    Returns:
        The canonical unit for a known python-obd name; otherwise ``raw``
        unchanged (None stays None).
    """
    if raw is None:
        return None
    canonical = CANONICAL_UNITS.get(raw)
    if canonical is not None:
        return canonical
    if raw not in _CANONICAL_VALUES:
        with _warnLock:
            firstSighting = raw not in _warnedUnits
            _warnedUnits.add(raw)
        if firstSighting:
            logger.warning(
                "unit %r has no canonical form -- published unchanged "
                "(further readings with it are not logged)",
                raw,
            )
    return raw
