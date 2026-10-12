################################################################################
# File Name: dtc_last_known.py
# Purpose/Description: US-752 (F-123) -- the resting-state reader for the `dtc`
#   state. When no live DTC read is possible (boot / key-off / process restart)
#   the panel must still show the codes the system ALREADY HOLDS, labelled as
#   remembered and dated. They are read from the persisted `dtc_log` record --
#   the ECU is never queried (SSOT rule B: one acquisition path). The module also
#   writes the `cleared` watermark a successful Mode-04 clear leaves, so a
#   remembered code can never outlive the clear that wiped it.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Ralph (Rex)  | Initial -- US-752 last-known DTC reader + Mode-04
#               |              | clear watermark.
# ================================================================================
################################################################################

"""Last-known DTCs from ``dtc_log`` + the Mode-04 clear watermark (US-752).

Atlas ruling 2026-09-14: an unavailable ``dtc`` payload carries honest nulls in
its live fields and a SEPARATE ``lastKnown`` block. This module is that block's
only source.

Selection rules:

* Only ``data_source = 'real'`` rows -- a replay or fixture row is not something
  the car ever reported.
* Only ``stored`` / ``pending`` rows written AFTER the newest ``cleared`` row.
  "After" is by ``id`` (insert order), or by ``last_seen_timestamp`` for an older
  row the drive-scoped upsert re-read after the clear.
* One entry per code, the most recently seen row winning.

``asOfTs`` is ``last_seen_timestamp`` -- the DB stamps it at the read and bumps
it on every re-read, so it is a read time, not an insert time.

Known limit: a read that finds NO codes writes no row, so a code that stopped
reporting without a Mode 04 stays remembered (dated) until a clear.
"""

from __future__ import annotations

import logging
from typing import Any

from .dtc_log_schema import DTC_LOG_TABLE

__all__ = [
    'LAST_KNOWN_SOURCE',
    'readLastKnownDtcs',
    'recordClearWatermark',
]

logger = logging.getLogger(__name__)

# The provenance label the `lastKnown` block carries (Atlas 2026-09-14).
LAST_KNOWN_SOURCE: str = 'dtc_log'

# The dtc_log status reserved for clear events (dtc_log_schema.py).
_STATUS_CLEARED = 'cleared'

# Only rows the car actually reported (US-195 origin tag).
_REAL_DATA_SOURCE = 'real'


def readLastKnownDtcs(database: Any) -> dict | None:
    """Read the codes the system last saw from ``dtc_log`` (no ECU query).

    Args:
        database: An ``ObdDatabase``-like object whose ``connect()`` yields a
            sqlite3 connection. ``None`` -> nothing to read.

    Returns:
        ``{"codes": [...], "asOfTs": str, "source": "dtc_log"}`` where each code
        is ``{code, status, description, driveId, lastSeenTs}``, newest first;
        or ``None`` when nothing is remembered (never read, cleared since, or the
        log could not be read -- logged, never raised, so the resting state
        falls back to the honest "not read").
    """
    if database is None:
        return None
    try:
        with database.connect() as conn:
            markerId, markerTs = conn.execute(
                f"SELECT MAX(id), MAX(last_seen_timestamp) FROM {DTC_LOG_TABLE} "
                "WHERE status = ? AND data_source = ?",
                (_STATUS_CLEARED, _REAL_DATA_SOURCE),
            ).fetchone()
            rows = conn.execute(
                "SELECT dtc_code, description, status, drive_id, last_seen_timestamp "
                f"FROM {DTC_LOG_TABLE} "
                "WHERE data_source = ? AND status IN ('stored', 'pending') "
                "AND (? IS NULL OR id > ? OR last_seen_timestamp > ?) "
                "ORDER BY last_seen_timestamp DESC, id DESC",
                (_REAL_DATA_SOURCE, markerId, markerId, markerTs),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 -- a resting display must never crash boot
        logger.warning(
            "last-known DTC read from dtc_log failed (%s) -- resting state "
            "renders 'not read'",
            exc,
        )
        return None

    seen: set[str] = set()
    codes: list[dict] = []
    for dtcCode, description, status, driveId, lastSeenTs in rows:
        code = str(dtcCode).upper()
        if code in seen:
            continue
        seen.add(code)
        codes.append(
            {
                'code': code,
                'status': status,
                'description': description or '',
                'driveId': driveId,
                'lastSeenTs': None if lastSeenTs is None else str(lastSeenTs),
            }
        )
    if not codes:
        return None
    return {
        'codes': codes,
        'asOfTs': codes[0]['lastSeenTs'],
        'source': LAST_KNOWN_SOURCE,
    }


def recordClearWatermark(database: Any) -> int:
    """Write one ``cleared`` row per remembered code after a Mode-04 clear.

    Mode 04 is all-or-nothing, so every remembered code was wiped. The rows are
    the watermark :func:`readLastKnownDtcs` filters on, and an audit of what the
    clear took. A code that re-sets is logged again by the next read, after the
    watermark, and so becomes remembered again.

    Args:
        database: An ``ObdDatabase``-like object. ``None`` -> no-op.

    Returns:
        The number of ``cleared`` rows written (0 when nothing was remembered).
    """
    lastKnown = readLastKnownDtcs(database)
    if lastKnown is None:
        return 0
    codes = [c['code'] for c in lastKnown['codes']]
    with database.connect() as conn:
        for code in codes:
            conn.execute(
                f"INSERT INTO {DTC_LOG_TABLE} "
                "(dtc_code, description, status, drive_id) VALUES (?, '', ?, NULL)",
                (code, _STATUS_CLEARED),
            )
    return len(codes)
