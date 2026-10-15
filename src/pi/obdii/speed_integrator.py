################################################################################
# File Name: speed_integrator.py
# Purpose/Description: US-880-a (F-159) ONE speed integrator: the distance this
#                      drive has covered, integrated from realtime SPEED by the
#                      server's own trapezoid and gap rule so the two tiers
#                      agree. Pure: no clock, no state file, no database.
# Author: Rex (US-880-a)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-880-a) | Initial -- trapezoid + server gap rule.
# ================================================================================
################################################################################

"""Integrate vehicle SPEED (km/h) over caller-supplied monotonic time (US-880-a).

THE METHOD IS THE SERVER'S, deliberately: ``src/server/analytics/
derived_signals_compute.py`` integrates the same SPEED series into
``estimated_distance_km`` with the trapezoid ``(v0 + v1) / 2 * dt / 3600`` and
skips any interval with ``dt <= 0`` or ``dt > GAP_DETECTION_THRESHOLD_SECONDS``.
Mirroring it exactly is what lets the Pi's live figure and the server's
post-drive figure be compared at all (Atlas gap 2).

The integrator reads no clock. ``tS`` is a monotonic seconds value the caller
supplies, so a wall-clock step (NTP, a timezone fix) can never inject or erase
distance, and tests drive it with plain numbers.
"""

from __future__ import annotations

import math

__all__ = ['SECONDS_PER_HOUR', 'SpeedIntegrator']

SECONDS_PER_HOUR = 3600.0


class SpeedIntegrator:
    """Cumulative trapezoid distance from SPEED readings, with a gap rule.

    An interval whose ``dt`` is ``<= 0`` or ``> gapSec`` contributes nothing,
    and the new reading becomes the next interval's start. A ``None`` speed is
    ignored entirely: it neither contributes nor becomes the interval start.
    """

    def __init__(self, gapSec: float) -> None:
        """Build an integrator at zero distance with no interval start.

        Args:
            gapSec: An interval wider than this many seconds is not continuous
                travel and is excluded (``pi.trip.gapSec``).

        Raises:
            ValueError: If ``gapSec`` is not a finite number > 0.
        """
        if not math.isfinite(gapSec) or gapSec <= 0:
            raise ValueError(f"gapSec must be a finite number > 0 (got {gapSec!r})")
        self._gapSec = float(gapSec)
        self._distanceKm = 0.0
        self._lastSpeedKmh: float | None = None
        self._lastTS: float | None = None

    @property
    def distanceKm(self) -> float:
        """The cumulative distance in km since construction or the last reset."""
        return self._distanceKm

    def update(self, speedKmh: float | None, tS: float) -> float:
        """Integrate one SPEED reading and return the cumulative distance.

        Args:
            speedKmh: The reading in km/h, or None (ignored entirely).
            tS: The reading's monotonic time in seconds.

        Returns:
            The cumulative distance in km.
        """
        if speedKmh is None:
            return self._distanceKm
        v1 = float(speedKmh)
        if self._lastTS is not None and self._lastSpeedKmh is not None:
            dt = tS - self._lastTS
            # The server's guards (derived_signals_compute.py): a non-positive
            # dt is never divided by, and a soak gap is not known travel.
            if 0.0 < dt <= self._gapSec:
                self._distanceKm += (self._lastSpeedKmh + v1) / 2.0 * (dt / SECONDS_PER_HOUR)
        self._lastSpeedKmh = v1
        self._lastTS = tS
        return self._distanceKm

    def reset(self) -> None:
        """Zero the distance and forget the interval start."""
        self._distanceKm = 0.0
        self._lastSpeedKmh = None
        self._lastTS = None
