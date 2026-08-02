################################################################################
# File Name: home_location_provider.py
# Purpose/Description: Single Source of Truth for the "home location" fact --
#                      the Pi's home reference point (lat/lon + elevation ASL).
#                      THE only read path for pi.location.home.*; consumers call
#                      this provider and never parse the config keys themselves
#                      (specs/ssot-design-pattern.md).
#                      Honest-instrument by contract: absent, blank, unresolved,
#                      unparseable or physically-impossible values all resolve to
#                      None -- never a fabricated coordinate or anchor.
#                      PII: the real values live ONLY in the gitignored .env and
#                      arrive via ${PI_HOME_*} placeholders. This module never
#                      logs a coordinate value (see _rejectionLog).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial (US-517 / F-125): config binding read
#               |              | path for the altitude anchor (US-518) + the
#               |              | future GPS home-geofence.
# ================================================================================
################################################################################
"""SSOT for the home-location reference (US-517 / F-125)."""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Physical bounds. A value outside these cannot be a real place on Earth, so it
# is a typo or a units error -- and an out-of-band anchor is worse than none.
# Grounding: WGS-84 defines latitude on [-90, 90] and longitude on [-180, 180].
# The elevation band is padded around the extremes of dry land -- the Dead Sea
# shore (~-430 m, lowest exposed land) and Everest (8849 m, highest point).
LAT_MIN_DEG = -90.0
LAT_MAX_DEG = 90.0
LON_MIN_DEG = -180.0
LON_MAX_DEG = 180.0
ELEVATION_MIN_M = -500.0
ELEVATION_MAX_M = 9000.0

# secrets_loader leaves the placeholder VERBATIM when the env var is unset and
# no inline default is given, so `"${PI_HOME_LAT}"` is the literal value a Pi
# without those .env entries actually carries. It is a truthy non-None string,
# so the validator's None-default never fires -- this module is what absorbs it.
_PLACEHOLDER_PATTERN = re.compile(r'^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$')

__all__ = [
    'ELEVATION_MAX_M',
    'ELEVATION_MIN_M',
    'LAT_MAX_DEG',
    'LAT_MIN_DEG',
    'LON_MAX_DEG',
    'LON_MIN_DEG',
    'HomeLocation',
    'HomeLocationProvider',
]


@dataclass(frozen=True)
class HomeLocation:
    """A complete home reference: all three facts present and valid.

    Attributes:
        lat: Latitude in decimal degrees (WGS-84).
        lon: Longitude in decimal degrees (WGS-84).
        elevationM: Elevation above sea level in metres.
    """

    lat: float
    lon: float
    elevationM: float


class HomeLocationProvider:
    """The single authoritative provider of the home-location fact.

    Reads ``pi.location.home.{lat,lon,elevationM}`` and hands back only values
    it can vouch for. Anything else -- an absent key, a blank env var, an
    unresolved ``${...}`` placeholder, a non-numeric string, a NaN/infinity, a
    boolean, or a physically impossible magnitude -- resolves to ``None``.

    The elevation and the coordinate PAIR are exposed as SEPARATE facts on
    purpose. The US-518 altitude re-anchor needs only ``elevationM``; coupling
    it to a lat/lon fix (whose GPS hardware is not even ordered yet, US-516)
    would strand it on a dependency it never needed. A half-populated
    coordinate pair, by contrast, is not a partial location but a wrong one, so
    :meth:`getHomeCoordinates` is both-or-neither.

    All reads are LAZY -- the config is re-read on every call rather than
    parsed once at construction. This provider may be built before the config
    it reads is fully populated (the boot-order trap that bit US-501, US-502,
    US-504b and US-505 this sprint), and a per-call read costs nothing here.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Args:
            config: The validated config dict (tier-aware shape).
        """
        self._config = config

    @classmethod
    def fromConfig(cls, config: dict[str, Any]) -> HomeLocationProvider:
        """Build the provider over the ``pi.location.home`` config section."""
        return cls(config)

    def getHomeElevationM(self) -> float | None:
        """Return the home elevation in metres ASL, or None if unknown.

        This is the altitude anchor: US-518 resets the derived-altitude
        accumulator to this value on every successful server sync.

        Returns:
            The elevation as a float, or None when it cannot be determined.
        """
        return self._readFloat(
            'elevationM', ELEVATION_MIN_M, ELEVATION_MAX_M
        )

    def getHomeCoordinates(self) -> tuple[float, float] | None:
        """Return the home ``(lat, lon)`` pair, or None if either is unknown.

        Both-or-neither: a latitude without a longitude does not narrow the
        location down, it points at a different place entirely.

        Returns:
            A ``(lat, lon)`` tuple of floats, or None.
        """
        lat = self._readFloat('lat', LAT_MIN_DEG, LAT_MAX_DEG)
        lon = self._readFloat('lon', LON_MIN_DEG, LON_MAX_DEG)
        if lat is None or lon is None:
            return None
        return (lat, lon)

    def getHome(self) -> HomeLocation | None:
        """Return the complete home reference, or None if any part is unknown.

        Returns:
            A :class:`HomeLocation` when all three facts are valid, else None.
        """
        coordinates = self.getHomeCoordinates()
        elevationM = self.getHomeElevationM()
        if coordinates is None or elevationM is None:
            return None
        return HomeLocation(
            lat=coordinates[0], lon=coordinates[1], elevationM=elevationM
        )

    def _readHomeSection(self) -> dict[str, Any]:
        """Return the ``pi.location.home`` dict, or an empty dict.

        Reads defensively at every hop so a malformed config surfaces as an
        honest unknown rather than an exception on a consumer's path.
        """
        node: Any = self._config
        for key in ('pi', 'location', 'home'):
            if not isinstance(node, dict):
                return {}
            node = node.get(key)
        return node if isinstance(node, dict) else {}

    def _readFloat(self, key: str, minimum: float, maximum: float) -> float | None:
        """Coerce one home-location key to a vouched-for float, or None.

        Args:
            key: The leaf key under ``pi.location.home``.
            minimum: Inclusive lower bound of the physically plausible range.
            maximum: Inclusive upper bound of the physically plausible range.

        Returns:
            The coerced value, or None when it cannot be vouched for.
        """
        raw = self._readHomeSection().get(key)

        # Absent or blank == "not configured". That is the documented shipped
        # state (.env.example carries empty PI_HOME_* lines), not a fault, so
        # it stays at debug -- a warning here would cry wolf on every read.
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            logger.debug('pi.location.home.%s is not configured', key)
            return None

        if isinstance(raw, str):
            placeholder = _PLACEHOLDER_PATTERN.match(raw.strip())
            if placeholder:
                # Distinct from a parse failure and distinct from "not set",
                # because the remedy is distinct: populate this env var on THIS
                # host. deploy-pi.sh excludes .env, so the Pi keeps its own copy
                # and a dev-machine .env does not carry over.
                self._rejectionLog(
                    key,
                    f'the {placeholder.group(1)} placeholder was never resolved '
                    f'-- set {placeholder.group(1)} in this host\'s .env',
                )
                return None

        # bool is a subclass of int: float(True) is 1.0, which would read as a
        # perfectly plausible sea-level anchor. Reject before coercing.
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            self._rejectionLog(key, f'unusable type {type(raw).__name__}')
            return None

        try:
            value = float(raw)
        except (TypeError, ValueError):
            self._rejectionLog(key, 'not a number')
            return None

        # float() accepts 'nan' and 'inf' happily. A NaN anchor is the worst
        # case of all: it propagates silently through every later sum and never
        # compares unequal to itself, so nothing downstream detects it.
        if not math.isfinite(value):
            self._rejectionLog(key, 'not a finite number')
            return None

        if not (minimum <= value <= maximum):
            self._rejectionLog(
                key, f'outside the plausible range [{minimum}, {maximum}]'
            )
            return None

        return value

    @staticmethod
    def _rejectionLog(key: str, reason: str) -> None:
        """Warn about a rejected value WITHOUT echoing the value itself.

        Coordinates are PII and the PIIMaskingFilter masks email/phone/SSN only
        (specs/architecture.md sec 8) -- a coordinate written to journald is
        PII on a surface with no mask for it. The key plus the reason is enough
        to find and fix the offending .env line; the value adds nothing but
        exposure.
        """
        logger.warning(
            'pi.location.home.%s rejected (%s) -- reporting unknown; '
            'value withheld (location PII)',
            key,
            reason,
        )
