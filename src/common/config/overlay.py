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
# 2026-08-07    | Rex (US-531) | Write side: atomic writeOverlayValue (temp +
#               |              | os.replace) + readEffectiveValue/getDotPath, so
#               |              | the settings endpoint reports the REAL stored
#               |              | value and reuses the ONE allow-list gate.
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

Writing (US-531)
----------------
:func:`writeOverlayValue` is the ONLY writer. It runs the SAME
:func:`validateOverlayValue` gate the read seam runs -- so a value that cannot be
honoured can never be stored, and vice versa -- then lands the file atomically
(temp + :func:`os.replace`) so a failed save leaves the operator's prior settings
byte-intact rather than truncating them. :func:`readEffectiveValue` re-reads from
disk through :func:`applyConfigOverlay`, which is how a caller reports what the
readers will ACTUALLY see instead of echoing back what was requested.
"""

from __future__ import annotations

import copy
import json
import logging
import os
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


def getDotPath(config: dict[str, Any], key: str) -> tuple[bool, Any]:
    """Read the value at a dot-path, reporting absence rather than guessing.

    Args:
        config: Any config mapping (typically an effective config).
        key: Dot-path key, e.g. ``pi.power.mode``.

    Returns:
        ``(True, value)`` when every segment resolves, else ``(False, None)``.
        A non-dict intermediate is absence, not an error -- callers on the HTTP
        path must never take a TypeError from a hand-edited config file.
    """
    cursor: Any = config
    for part in key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return False, None
        cursor = cursor[part]
    return True, cursor


def readEffectiveValue(configPath: str, key: str) -> tuple[bool, Any]:
    """Re-read ONE effective value from disk, through the shared seam.

    The honest read-back behind the US-531 settings endpoint: it reloads
    config.json AND the overlay and resolves them with
    :func:`resolveEffectiveConfig`, so what it reports is what every other
    consumer will resolve -- including the ``pi.power.mode`` coercion. An
    endpoint that echoed its request instead would show the operator a setting
    that was never stored.

    Args:
        configPath: Path to config.json.
        key: Dot-path key to read.

    Returns:
        ``(True, value)``, or ``(False, None)`` when the config or the key
        cannot be resolved. Never a fabricated value.
    """
    try:
        with open(configPath, encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        return False, None
    if not isinstance(config, dict):
        return False, None
    return getDotPath(applyConfigOverlay(config, configPath), key)


def _writeOverlayAtomic(overlayPath: str, overlay: dict[str, Any]) -> bool:
    """Land the overlay atomically: write a sibling temp, fsync, then replace.

    The overlay holds settings the operator set by hand on the Pi; a truncating
    in-place write that dies midway would destroy them. ``os.replace`` is atomic
    on POSIX and Windows alike, so a reader sees either the whole old file or
    the whole new one -- never a half-written one.

    Returns:
        True on success. False on ANY OS error, with the temp cleaned up and the
        previous file untouched.
    """
    path = Path(overlayPath)
    tempPath = path.with_name(path.name + ".tmp")
    try:
        with open(tempPath, "w", encoding="utf-8") as fh:
            json.dump(overlay, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            # Durability: the Pi loses power with the ignition, so a settings
            # save must reach the medium, not just the page cache.
            os.fsync(fh.fileno())
        os.replace(tempPath, overlayPath)
    except OSError:
        logger.warning("Overlay write failed, prior settings left intact: %s", overlayPath)
        try:
            tempPath.unlink()
        except OSError:
            pass
        return False
    return True


def writeOverlayValue(overlayPath: str, key: str, value: Any) -> bool:
    """Persist ONE allow-listed override into the overlay, atomically.

    Re-runs :func:`validateOverlayValue` -- the same gate the read seam runs and
    the same gate the HTTP endpoint runs before calling here (defense in depth,
    one implementation). Existing overrides are preserved: a save merges into
    the current overlay so toggling one control cannot reset another.

    Args:
        overlayPath: Path to the overlay file (see :func:`overlayPathFor`).
        key: Dot-path config key; must be on the allow-list.
        value: Proposed value; must satisfy the key's type rule.

    Returns:
        True when the value is now stored. False when the entry was refused by
        the gate, or when the write could not be completed -- in both cases
        nothing on disk changed. Callers MUST NOT report success on False.
    """
    isValid, stored = validateOverlayValue(key, value)
    if not isValid:
        logger.warning("Refusing overlay write, not overridable/invalid: %s=%r", key, value)
        return False

    overlay = loadOverlay(overlayPath)
    overlay[key] = stored
    return _writeOverlayAtomic(overlayPath, overlay)
