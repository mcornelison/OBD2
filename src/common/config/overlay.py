################################################################################
# File Name: overlay.py
# Purpose/Description: F-126 (US-530) Pi-local config OVERLAY + the SHARED
#   effective-config resolver. config.json is the read-only SHIPPED DEFAULT and
#   nothing writes it at runtime; a gitignored, deploy-excluded overlay file
#   (config.local.json, beside config.json) layers OVER it so an operator toggle
#   set on the Pi survives a deploy. Effective value = allow-listed overlay
#   override ELSE the config.json default. This module is the ONE seam every
#   config reader calls (orchestrator loadConfigWithSecrets AND the state
#   server's _loadDisplaySection) so no consumer can diverge [Atlas A-4].
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-07    | Rex (US-530) | Initial -- flat dot-path overlay, Slice-1
#               |              | allow-list, shared resolveEffectiveConfig.
# ================================================================================
################################################################################

"""Pi-local config overlay: the layer that lets operator settings survive deploys.

Why an overlay instead of writing config.json
---------------------------------------------
config.json is shipped by the deploy (rsync ``--delete``), so anything written
into it on the Pi is destroyed by the next deploy. The overlay is excluded from
the sync exactly like ``.env``, so it is the only durable place for a setting the
operator changes on the box.

Shape
-----
The overlay is a FLAT dot-path map::

    {"pi.display.carousel.autoRotateS": 0, "pi.power.mode": "wall"}

Flat keys make the allow-list a literal key comparison, so the SAME gate runs at
the read seam (:func:`resolveEffectiveConfig`) and at the US-531 write endpoint
-- defense in depth with no second, drifting implementation.

Honest-instrument rules
-----------------------
* Absent or malformed overlay -> the config.json default, never a guess.
* Key outside the allow-list -> ignored and logged; it never writes anything,
  and it never invents a config branch that the shipped default lacks.
* Wrong-typed value on an allow-listed key -> the shipped default stands.
* ``pi.power.mode`` is the one COERCION: an invalid stored mode resolves to
  ``unknown`` rather than to the shipped default, because a corrupt mode means
  we do not know the deployment context -- and a confident wrong mode (bench Pi
  reporting CAR) is worse than an honest unknown.

Auto-rotate has ONE truth
-------------------------
There is deliberately no ``autoRotate`` boolean. ``autoRotateS`` (seconds; 0=off,
>0=on) is the single key; the UI derives the toggle state from ``> 0``.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The overlay always sits beside config.json under this fixed name. Deterministic
# (not configurable) so the deploy exclude, the .gitignore entry, and every
# reader agree without a config key of their own -- same posture as `.env`.
OVERLAY_FILENAME = "config.local.json"

# The only deployment contexts pi.power.mode may express. `unknown` is the honest
# default AND the fallback for anything unrecognised.
POWER_MODES = ("car", "wall", "unknown")
UNKNOWN_POWER_MODE = "unknown"
POWER_MODE_KEY = "pi.power.mode"


def _isNonNegativeNumber(value: Any) -> bool:
    """True for a real, non-negative int/float (bool is NOT a number here)."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float)) and value >= 0


def _isBool(value: Any) -> bool:
    """True only for a real bool -- 1 / "true" are not booleans."""
    return isinstance(value, bool)


def _isPowerMode(value: Any) -> bool:
    """True only for an exact member of :data:`POWER_MODES` (case-sensitive)."""
    return isinstance(value, str) and value in POWER_MODES


# Slice-1 overridable keys. Adding a key here is the ONLY way to make a setting
# operator-writable -- both the read gate and the US-531 write gate consult this
# one table, so a key cannot become writable without also becoming readable.
_VALIDATORS = {
    "pi.display.carousel.autoRotateS": _isNonNegativeNumber,
    POWER_MODE_KEY: _isPowerMode,
    "pi.alerts.audioAlerts": _isBool,
    "pi.calibration.mode": _isBool,
    "pi.analysis.triggerAfterDrive": _isBool,
}

OVERRIDABLE_KEYS: tuple[str, ...] = tuple(_VALIDATORS)


def overlayPathFor(configPath: str) -> str:
    """Derive the overlay path for a given config.json path.

    Args:
        configPath: Path to config.json (relative paths resolve against the
            process CWD -- the systemd unit's WorkingDirectory).

    Returns:
        Path to the sibling overlay file.
    """
    return str(Path(configPath).parent / OVERLAY_FILENAME)


def loadOverlay(overlayPath: str) -> dict[str, Any]:
    """Read the overlay file, fail-safe.

    ANY problem (absent -- the shipped state -- unreadable, malformed, or a
    non-object top level) yields an empty overlay so the caller falls back to the
    config.json defaults. An overlay must never be able to crash a consumer or
    produce a partial guess.

    Args:
        overlayPath: Path to the overlay file.

    Returns:
        The flat dot-path override map, or ``{}``.
    """
    try:
        with open(overlayPath, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def validateOverlayValue(key: str, value: Any) -> tuple[bool, Any]:
    """Gate one overlay entry against the allow-list AND its value type.

    Shared by the read seam and the US-531 write endpoint so an entry that
    cannot be stored can also never be honoured, and vice versa.

    Args:
        key: Dot-path config key.
        value: Proposed value.

    Returns:
        ``(True, value)`` when the entry is allow-listed and well-typed,
        otherwise ``(False, None)``.
    """
    validator = _VALIDATORS.get(key)
    if validator is None or not validator(value):
        return False, None
    return True, value


def _setDotPath(target: dict[str, Any], key: str, value: Any) -> bool:
    """Write ``value`` at the dot-path ``key``, creating intermediate dicts.

    Returns False without writing when an intermediate exists but is not a dict
    -- overwriting a populated non-dict branch would destroy shipped config to
    honour an overlay, which is never the honest trade.
    """
    parts = key.split(".")
    cursor = target
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if nxt is None:
            nxt = {}
            cursor[part] = nxt
        elif not isinstance(nxt, dict):
            return False
        cursor = nxt
    cursor[parts[-1]] = value
    return True


def resolveEffectiveConfig(
    base: dict[str, Any],
    overlay: dict[str, Any],
    allowlist: Sequence[str] | Iterable[str] | None = None,
) -> dict[str, Any]:
    """Merge an overlay over a base config -- THE shared effective-config seam.

    Every config consumer resolves through this function so the effective config
    is identical for all of them (Atlas A-4: no per-reader merge).

    Args:
        base: The config.json contents (shipped defaults). Never mutated.
        overlay: Flat dot-path override map (see :func:`loadOverlay`).
        allowlist: Overridable dot-paths; defaults to :data:`OVERRIDABLE_KEYS`.

    Returns:
        A new config dict with allow-listed, well-typed overrides applied.
    """
    allowed = frozenset(OVERRIDABLE_KEYS if allowlist is None else allowlist)
    effective = copy.deepcopy(base)

    for key, value in overlay.items():
        if key not in allowed:
            logger.warning("Overlay key not overridable, ignoring: %s", key)
            continue

        isValid, stored = validateOverlayValue(key, value)
        if isValid:
            if not _setDotPath(effective, key, stored):
                logger.warning("Overlay key blocked by a non-dict branch: %s", key)
            continue

        if key == POWER_MODE_KEY:
            # Honest-unknown: a corrupt mode means we do NOT know the deployment
            # context, so report unknown rather than the shipped default.
            logger.warning(
                "Overlay power mode %r invalid, resolving to %s",
                value,
                UNKNOWN_POWER_MODE,
            )
            _setDotPath(effective, key, UNKNOWN_POWER_MODE)
            continue

        logger.warning("Overlay value for %s is invalid, using default: %r", key, value)

    return effective


def applyConfigOverlay(config: dict[str, Any], configPath: str) -> dict[str, Any]:
    """Apply the Pi-local overlay that sits beside ``configPath``.

    The one-call seam for config readers: locate the overlay, read it fail-safe,
    and resolve. Callers do not know the overlay's filename or shape.

    Args:
        config: The freshly-loaded config.json contents.
        configPath: Path config.json was read from.

    Returns:
        The effective config (a new dict; ``config`` is not mutated).
    """
    return resolveEffectiveConfig(config, loadOverlay(overlayPathFor(configPath)))
