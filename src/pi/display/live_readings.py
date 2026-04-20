################################################################################
# File Name: live_readings.py
# Purpose/Description: Poll realtime_data SQLite for the latest value per
#                      dashboard parameter and map collector-side aliases
#                      (e.g., BATTERY_V from US-199) to display-side gauge
#                      names (BATTERY_VOLTAGE).  Used by the HDMI live render
#                      harness (scripts/render_primary_screen_live.py
#                      --from-db) and by scripts/verify_hdmi_live.sh.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-192 (Sprint 14)
# ================================================================================
################################################################################
"""
Live-render readings polling for the HDMI primary screen.

The orchestrator writes realtime_data rows to the Pi's local SQLite
(``data/obd.db``) as OBD readings arrive.  The HDMI render harness runs as a
peer process (not inside the orchestrator) and polls this table each frame
so the six primary-screen gauges advance as fresh rows land.

``PARAMETER_ALIASES`` bridges the collector-side name to the display-side
name: US-199 writes ``BATTERY_V`` rows (adapter-level ELM_VOLTAGE path on the
2G Eclipse), but the basic-tier screen (``BASIC_TIER_DISPLAY_ORDER``) reads
the Volts gauge under ``BATTERY_VOLTAGE``.  The poll layer owns that rename
so neither the collector nor the screen need to change.

Data-source filtering: only ``real`` rows surface (plus ``NULL`` for
pre-US-195 BC).  Replay / physics_sim rows are intentionally excluded -- the
HDMI display is a live-cockpit read and showing simulated values would
undermine the signal.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)


PARAMETER_ALIASES: dict[str, str] = {
    "BATTERY_V": "BATTERY_VOLTAGE",
}


def resolveGaugeName(parameterName: str) -> str:
    """Return the display-side gauge name for a collector-side parameter.

    Unknown / unaliased names pass through unchanged.  The alias map is
    deliberately tiny -- the great majority of parameter_name values already
    match the display's gauge names (RPM, COOLANT_TEMP, SPEED, BOOST, AFR).
    """
    return PARAMETER_ALIASES.get(parameterName, parameterName)


def buildReadingsFromDb(
    dbPath: Path,
    parameterNames: Iterable[str],
) -> dict[str, float]:
    """Return latest-value-per-gauge from realtime_data.

    For each gauge in ``parameterNames``:

    * Look for rows whose parameter_name matches the gauge name directly.
    * Also look for rows whose parameter_name aliases to this gauge
      (e.g., ``BATTERY_V`` rows surface under ``BATTERY_VOLTAGE``).
    * Keep the row with the highest ``id`` (append-only PK -> newest row wins,
      independent of timestamp string formatting).
    * Only rows with ``data_source IN ('real')`` or NULL (pre-US-195 BC)
      qualify.  Replay / physics_sim rows are excluded -- the HDMI display is
      a live-cockpit surface.

    Args:
        dbPath: Path to the Pi's ``data/obd.db``.  Missing file returns {}.
        parameterNames: Display-side gauge names to poll for (typically
            ``BASIC_TIER_DISPLAY_ORDER``).

    Returns:
        Dict of gauge name -> latest value.  Gauges without a row are absent
        from the dict (caller renders ``---`` placeholder for missing keys).
    """
    requestedGauges = list(parameterNames)
    if not requestedGauges:
        return {}

    if not Path(dbPath).exists():
        logger.debug("live_readings: %s does not exist; returning empty", dbPath)
        return {}

    # Collect parameter_name values to query: each gauge plus any collector
    # name that aliases to it.  This lets BATTERY_V rows count for the
    # BATTERY_VOLTAGE gauge without leaking BATTERY_V as a standalone key.
    reverseAliases: dict[str, list[str]] = {name: [name] for name in requestedGauges}
    for collectorName, gaugeName in PARAMETER_ALIASES.items():
        if gaugeName in reverseAliases:
            reverseAliases[gaugeName].append(collectorName)

    queryNames: list[str] = []
    for names in reverseAliases.values():
        queryNames.extend(names)

    placeholders = ",".join("?" for _ in queryNames)
    query = (
        "SELECT parameter_name, value FROM realtime_data "
        f"WHERE parameter_name IN ({placeholders}) "
        "AND (data_source = 'real' OR data_source IS NULL) "
        "AND id = (SELECT MAX(id) FROM realtime_data r2 "
        "          WHERE r2.parameter_name = realtime_data.parameter_name "
        "          AND (r2.data_source = 'real' OR r2.data_source IS NULL))"
    )

    try:
        with sqlite3.connect(f"file:{Path(dbPath).as_posix()}?mode=ro", uri=True) as conn:
            cursor = conn.execute(query, queryNames)
            rawRows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        # Missing realtime_data table, bad schema, locked db -- degrade gracefully
        logger.debug("live_readings: sqlite error on %s: %s", dbPath, e)
        return {}

    # Collapse rows to (gaugeName, value, rowId-like ordering).  Since we
    # filtered to MAX(id) per parameter_name above, each parameter_name
    # contributes at most one row, but BATTERY_V and BATTERY_VOLTAGE can
    # both produce a row -- pick the higher-id one by re-querying.
    readings: dict[str, float] = {}

    # For gauges with aliases, we need a tiebreak between direct-name row and
    # aliased-name row.  Re-issue a targeted "most recent row for this gauge
    # across its alias family" query.
    for gaugeName, aliasFamily in reverseAliases.items():
        if len(aliasFamily) == 1:
            # No alias family; use whatever the bulk query returned
            for paramName, value in rawRows:
                if paramName == gaugeName:
                    readings[gaugeName] = float(value)
                    break
        else:
            # Alias family -- find the single newest row across all family members
            familyPlaceholders = ",".join("?" for _ in aliasFamily)
            familyQuery = (
                "SELECT value FROM realtime_data "
                f"WHERE parameter_name IN ({familyPlaceholders}) "
                "AND (data_source = 'real' OR data_source IS NULL) "
                "ORDER BY id DESC LIMIT 1"
            )
            try:
                with sqlite3.connect(
                    f"file:{Path(dbPath).as_posix()}?mode=ro", uri=True
                ) as conn:
                    row = conn.execute(familyQuery, aliasFamily).fetchone()
                    if row is not None:
                        readings[gaugeName] = float(row[0])
            except sqlite3.OperationalError as e:
                logger.debug("live_readings: alias query failed: %s", e)

    return readings


__all__ = [
    "PARAMETER_ALIASES",
    "buildReadingsFromDb",
    "resolveGaugeName",
]
