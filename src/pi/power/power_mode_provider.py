################################################################################
# File Name: power_mode_provider.py
# Purpose/Description: Single Source of Truth for the "power mode" fact -- the
#                      Pi's DEPLOYMENT mode (in-car vs bench/wall), NOT the
#                      AC-vs-battery power SOURCE (that is PowerSourceProvider).
#                      The ONLY place in the codebase that acquires power-mode.
#                      Acquisition is a swappable seam behind the SSOT interface:
#                      today a static config key (pi.power.mode), later a GPIO
#                      sense line -- consumers call getPowerMode() and never
#                      change (BL-014 ruling, Atlas 2026-07-01, CIO-ratified).
#                      Honest-instrument by contract: an undeterminable / stale /
#                      invalid acquisition resolves to `unknown`, never a
#                      confident wrong mode (specs/ssot-design-pattern.md).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Ralph (Rex)  | Initial (US-421 / BL-014): config-key SSOT, honest
#               |              | unknown, GPIO-swap seam (do NOT build GPIO yet).
# 2026-08-08    | Ralph (Rex)  | US-533 (F-126): OverlayConfigPowerModeSource --
#               |              | re-reads the EFFECTIVE key per acquire() so a
#               |              | settings-band write lands on the next cycle.
# ================================================================================
################################################################################
"""SSOT for the power-mode (in-car vs wall) deployment fact."""
from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# The three -- and only three -- honest power-mode values. `unknown` is a
# first-class value, not an error: it is what we render when the mode cannot be
# determined confidently (BL-014: never a confident wrong car/wall).
POWER_MODE_CAR = "car"
POWER_MODE_WALL = "wall"
POWER_MODE_UNKNOWN = "unknown"
VALID_POWER_MODES = frozenset({POWER_MODE_CAR, POWER_MODE_WALL})

__all__ = [
    "POWER_MODE_CAR",
    "POWER_MODE_UNKNOWN",
    "POWER_MODE_WALL",
    "VALID_POWER_MODES",
    "ConfigPowerModeSource",
    "OverlayConfigPowerModeSource",
    "PowerModeProvider",
    "PowerModeSource",
]


class PowerModeSource(Protocol):
    """The swappable acquisition seam behind the SSOT.

    An implementation returns the raw candidate mode, or ``None`` when it
    cannot determine one. It NEVER coerces or invents -- validation and the
    honest ``unknown`` fallback belong to :class:`PowerModeProvider`, so a new
    backend (e.g. a GPIO sense line) is a drop-in with zero provider change.
    """

    def acquire(self) -> str | None:  # pragma: no cover - structural Protocol
        ...


class ConfigPowerModeSource:
    """Acquire the power mode from the static ``pi.power.mode`` config key.

    This is the current (only) acquisition path -- the operator sets the key on
    a bench<->car deploy (config edit + restart). A GPIO-backed source is the
    intended future swap (see module docstring); it implements this same
    ``acquire()`` seam, so nothing downstream changes.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Args:
            config: The validated config dict (tier-aware shape).
        """
        self._config = config

    def acquire(self) -> str | None:
        """Return the raw ``pi.power.mode`` value, or None if absent.

        Reads defensively (a non-dict along the path -> None) so a malformed
        config surfaces as ``unknown`` at the provider, not a crash.
        """
        pi = self._config.get("pi") if isinstance(self._config, dict) else None
        power = pi.get("power") if isinstance(pi, dict) else None
        if not isinstance(power, dict):
            return None
        return power.get("mode")


class OverlayConfigPowerModeSource:
    """Acquire the power mode by RE-READING ``pi.power.mode`` on every call.

    The live acquisition path (US-533 / F-126). :class:`ConfigPowerModeSource`
    closes over a config dict, which on the Pi is the snapshot the orchestrator
    loaded at boot -- so an operator toggling CAR/WALL in the settings band saw
    nothing change until the capture service restarted. This source instead
    resolves the key from disk through the US-530 shared overlay seam each time
    it is asked, so the card-state emitter's next cycle carries the new mode.

    Reading a small JSON file per emitter cycle is deliberate and cheap: the
    cycle is seconds apart, and the alternative (an in-process cache with an
    invalidation hook from the HTTP write route) would put a second, drifting
    copy of the fact in play -- the A-4 divergence US-530 exists to prevent.

    It is an ordinary :class:`PowerModeSource`: no coercion, no validation, just
    the raw candidate or ``None``. The honest-``unknown`` contract stays with
    :class:`PowerModeProvider`, so this is a drop-in swap exactly like the
    future GPIO source will be.
    """

    def __init__(self, configPath: str) -> None:
        """Args:
            configPath: Path to config.json (relative paths resolve against the
                process CWD -- the systemd unit's WorkingDirectory). Its sibling
                overlay is what the settings band writes.
        """
        self._configPath = configPath

    def acquire(self) -> str | None:
        """Return the current EFFECTIVE ``pi.power.mode``, or None if unreadable.

        ``None`` covers every way the read can fail -- absent/malformed
        config.json, the key missing, a non-dict branch in the way -- because
        the provider turns all of them into the honest ``unknown``. An
        unresolvable mode must never fall through to a stale prior value: the
        deployment context is exactly the fact we would be guessing about.
        """
        # Imported here rather than at module scope: this module is imported on
        # the Pi's hot path and the overlay seam is only needed by this source.
        from common.config.overlay import POWER_MODE_KEY, readEffectiveValue

        found, value = readEffectiveValue(self._configPath, POWER_MODE_KEY)
        return value if found else None


class PowerModeProvider:
    """The single authoritative provider of the power-mode fact.

    Consumers call :meth:`getPowerMode` and never acquire the mode any other
    way. The result is always one of ``car`` / ``wall`` / ``unknown``: anything
    the source cannot resolve to an exact known value -- absent, stale, invalid,
    or an acquisition error -- becomes ``unknown`` (honest-instrument; never a
    confident wrong mode, BL-014).
    """

    def __init__(self, source: PowerModeSource) -> None:
        """Args:
            source: The acquisition backend (see :class:`PowerModeSource`).
        """
        self._source = source

    @classmethod
    def fromConfig(cls, config: dict[str, Any]) -> PowerModeProvider:
        """Build the provider over the static config-key acquisition path.

        The value is whatever the caller's config SNAPSHOT holds, so an operator
        override written after that snapshot is not seen. Prefer
        :meth:`fromConfigPath` wherever a config path is available.
        """
        return cls(ConfigPowerModeSource(config))

    @classmethod
    def fromConfigPath(cls, configPath: str) -> PowerModeProvider:
        """Build the provider over the LIVE re-reading acquisition path (US-533).

        Args:
            configPath: Path to config.json; its sibling overlay carries the
                operator's setting-band override.
        """
        return cls(OverlayConfigPowerModeSource(configPath))

    def getPowerMode(self) -> str:
        """Return the honest power mode: ``car`` / ``wall`` / ``unknown``."""
        try:
            raw = self._source.acquire()
        except Exception as exc:  # noqa: BLE001 -- honest-instrument: never crash
            logger.warning(
                "power-mode acquisition failed (%s) -- reporting unknown", exc
            )
            return POWER_MODE_UNKNOWN
        if raw in VALID_POWER_MODES:
            return raw  # type: ignore[return-value]  # narrowed by the set membership
        if raw not in (None, POWER_MODE_UNKNOWN):
            logger.warning(
                "power-mode value %r is not one of %s -- reporting unknown",
                raw,
                sorted(VALID_POWER_MODES),
            )
        return POWER_MODE_UNKNOWN
