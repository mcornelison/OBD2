################################################################################
# File Name: altitude_anchor.py
# Purpose/Description: US-518 (WP-3, F-125) -- the derived-altitude accumulator
#   and its re-anchor to the home elevation on every successful server sync.
#
#   A successful push to the companion service means the Pi reached the home
#   network, which means the car is home. That is a VERIFIED "at home" event,
#   so it is the moment to discard accumulated integration drift and reset the
#   derived altitude to the known home elevation -- bounding the error to a
#   single drive between syncs (Spool's altitude ruling, 2026-08-01, item 4:
#   "your sync-reset to PI_HOME_ELEVATION_M is sound and correctly bounds error
#   to a single drive").
#
#   SCOPE, stated plainly because it is easy to misread: this module owns the
#   ACCUMULATOR and the RESET only. It does NOT integrate, and it does NOT
#   publish. The integrator that advances the value (altitude = home +
#   integral of sin(pitch) * speed dt) is US-519 and is DEFERRED pending
#   Spool's sigma sizing on US-521's gyro-fused pitch; the display is US-520.
#   Until US-519 lands, nothing calls setDerivedAltitudeM in production, the
#   accumulator simply holds the anchor, and `states/imu.altitude` stays a
#   typed NULL with reason "no_source" (imu_state_bridge). That is deliberate:
#   publishing home-elevation-forever as an altitude would be a confident wrong
#   number, which is strictly worse than the honest "no source" shown today.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial -- US-518 sync-success altitude
#               |              | re-anchor over the US-517 home-elevation SSOT.
# ================================================================================
################################################################################

"""US-518: derived-altitude accumulator + re-anchor on successful server sync."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ['AltitudeAnchor']


class AltitudeAnchor:
    """Holds the derived altitude and re-anchors it to home on sync-success.

    The accumulator starts at an honest ``None`` -- unknown, not ``0.0``. Sea
    level is a 209 m error in Chicagoland, so a zero default would be a
    fabricated reading rather than an absent one.

    Two failure directions are guarded deliberately:

    * **Never anchor to a value it cannot vouch for.** When the home elevation
      is unknown (the Pi's real state today -- ``deploy-pi.sh`` excludes
      ``.env``, so ``PI_HOME_ELEVATION_M`` is unresolved on the box), the
      re-anchor is a NO-OP that reports it did not fire.
    * **Never destroy a value it does not own.** The accumulator's value comes
      from the future US-519 integrator. Failing to improve an estimate is not
      licence to delete it, so an unanchorable sync leaves it untouched.

    The home elevation is read LAZILY on every re-anchor rather than cached at
    construction -- the boot-order trap that bit US-501, US-502, US-504b and
    US-505 this sprint. It also means the anchor starts working on a Pi whose
    ``.env`` gains the value later, without a code change.
    """

    def __init__(self, homeLocationProvider: Any) -> None:
        """Args:
            homeLocationProvider: The US-517 home-location SSOT. Only
                ``getHomeElevationM()`` is used -- the coordinate pair is a
                separate fact this module has no need of.
        """
        self._homeLocationProvider = homeLocationProvider
        self._altitudeM: float | None = None
        self._lastAnchoredAtIso: str | None = None

    @classmethod
    def fromConfig(cls, config: dict[str, Any]) -> AltitudeAnchor:
        """Build the anchor over the ``pi.location.home`` config section.

        Args:
            config: The validated config dict (tier-aware shape).

        Returns:
            An anchor reading through a fresh :class:`HomeLocationProvider`.
        """
        from pi.location.home_location_provider import HomeLocationProvider

        return cls(HomeLocationProvider.fromConfig(config))

    def getAltitudeM(self) -> float | None:
        """Return the current derived altitude in metres ASL, or None.

        Returns:
            The accumulator's value, or None when it is genuinely unknown.
        """
        return self._altitudeM

    def getLastAnchoredAtIso(self) -> str | None:
        """Return when the altitude was last actually re-anchored, or None.

        Stamped only on a re-anchor that FIRED. A stamp advanced by a no-op
        would claim a freshness the value does not have.

        Returns:
            A UTC ISO-8601 timestamp, or None if it has never anchored.
        """
        return self._lastAnchoredAtIso

    def onSyncSuccess(self) -> bool:
        """Re-anchor the derived altitude -- the sync-success seam hook.

        Called from the orchestrator's sync-outcome recorder, which runs only
        after a push completed past the offline route gate. Both the interval
        and drive-end trigger paths funnel through that one recorder.

        Returns:
            True when the altitude was re-anchored; False when it was not.
        """
        return self.reanchorToHome()

    def reanchorToHome(self) -> bool:
        """Reset the accumulator to the configured home elevation.

        Best-effort by construction: any failure to resolve the anchor leaves
        the accumulator exactly as it was and reports False. This is on the
        sync path, which must never be broken by drift control (I-038 lesson).

        Returns:
            True when the altitude was re-anchored; False on an unknown or
            unreadable home elevation.
        """
        try:
            elevationM = self._homeLocationProvider.getHomeElevationM()
        except Exception as e:  # noqa: BLE001 -- never break the sync path
            logger.debug(
                "Altitude re-anchor skipped: home-elevation read failed "
                "(%s: %s); derived altitude left unchanged",
                type(e).__name__, e,
            )
            return False

        if elevationM is None:
            # Not a fault -- the shipped state. Report the ACTUAL remedy: an
            # unresolved placeholder and a typo'd number have different fixes
            # (US-517). Debug, not warning: this fires on every sync until the
            # anchor is configured, and a per-sync warning would cry wolf.
            logger.debug(
                "Altitude re-anchor skipped: home elevation unknown "
                "(set PI_HOME_ELEVATION_M in this host's .env); "
                "derived altitude left unchanged",
            )
            return False

        self._altitudeM = float(elevationM)
        self._lastAnchoredAtIso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.debug(
            "Derived altitude re-anchored to home elevation on sync success",
        )
        return True

    def setDerivedAltitudeM(self, value: Any) -> bool:
        """Set the accumulator -- the write seam for the US-519 integrator.

        Rejects anything that is not a finite real number, leaving the prior
        value in place. ``float('nan')`` and ``float('inf')`` both SUCCEED as
        floats, and a NaN altitude propagates silently through every later sum
        while never comparing unequal to itself, so nothing downstream would
        detect it. ``bool`` is rejected before coercion because ``float(True)``
        is ``1.0`` -- a plausible-looking near-sea-level reading.

        Args:
            value: The new altitude in metres ASL, or None to return the
                accumulator to an honest unknown (the integrator losing
                confidence is a legitimate state transition).

        Returns:
            True when the value was accepted; False when it was rejected.
        """
        if value is None:
            self._altitudeM = None
            return True

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            logger.warning(
                "Derived altitude rejected: expected a real number, got %s",
                type(value).__name__,
            )
            return False

        coerced = float(value)
        if not math.isfinite(coerced):
            logger.warning(
                "Derived altitude rejected: value is not finite",
            )
            return False

        self._altitudeM = coerced
        return True
