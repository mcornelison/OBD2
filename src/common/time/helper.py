################################################################################
# File Name: helper.py
# Purpose/Description: Canonical ISO-8601 UTC timestamp helpers for every
#                      capture-table writer in the Pi tree.  Fixes TD-027
#                      (US-202): eliminates format/tz drift between
#                      DEFAULT CURRENT_TIMESTAMP, naive datetime.now(), and
#                      the legacy sync_log helper.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-202 (TD-027 fix)
# ================================================================================
################################################################################

"""Canonical ISO-8601 UTC timestamp helpers.

Post-US-202, every row written to a Pi capture table (``connection_log``,
``alert_log``, ``power_log``, ``realtime_data``, ``statistics``) MUST carry
a timestamp in the canonical format
``%Y-%m-%dT%H:%M:%SZ`` -- ISO-8601 UTC with ``T`` separator and trailing
``Z``.  The SQLite ``DEFAULT`` clause on each capture table mirrors this
format via ``strftime('%Y-%m-%dT%H:%M:%SZ', 'now')``.

This module is the single point through which all Python-side explicit
writers must route.  It deliberately rejects naive ``datetime`` objects
at the boundary to prevent America/Chicago-local strings from leaking
into capture rows (the original TD-027 Thread 2 bug).

See ``specs/standards.md`` 'Canonical Timestamp Format' and
``offices/pm/tech_debt/TD-027-timestamp-accuracy-and-format-consistency.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = [
    'CANONICAL_ISO_FORMAT',
    'CANONICAL_ISO_REGEX',
    'utcIsoNow',
    'toCanonicalIso',
]


# strftime format string for the canonical timestamp.  Exported so callers
# that need to format pre-existing datetime values without going through
# toCanonicalIso() still produce identical strings.
CANONICAL_ISO_FORMAT: str = '%Y-%m-%dT%H:%M:%SZ'

# Regex pattern matching the canonical format.  Shared with tests so the
# "canonical shape" definition lives in exactly one place.
CANONICAL_ISO_REGEX: str = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'


def utcIsoNow() -> str:
    """Return the current UTC wall-clock time as a canonical ISO-8601 string.

    This is the preferred helper for capture-table writes: the caller
    simply wants "now" in canonical form and has no pre-existing
    :class:`datetime.datetime` object to preserve.

    Returns:
        A string of the form ``YYYY-MM-DDTHH:MM:SSZ``.  Always UTC,
        second-resolution, never naive, never local.
    """
    return datetime.now(UTC).strftime(CANONICAL_ISO_FORMAT)


def toCanonicalIso(dt: datetime) -> str:
    """Format a tz-aware :class:`datetime.datetime` as a canonical ISO-8601 string.

    Intended for callers that already hold a meaningful datetime (e.g.,
    the moment a drive started, or a reading's capture instant) and want
    to serialize it for a capture-table row.  The caller is responsible
    for ensuring the datetime carries ``tzinfo`` -- naive datetimes are
    rejected at this boundary so that local-time strings (the TD-027
    Thread 2 bug) cannot silently enter a capture row.

    Args:
        dt: A :class:`datetime.datetime` with a non-``None`` ``tzinfo``.
            If the value is not already in UTC, it is converted.

    Returns:
        A string of the form ``YYYY-MM-DDTHH:MM:SSZ``.  Microseconds are
        truncated; the canonical format is second-resolution.

    Raises:
        ValueError: If ``dt.tzinfo`` is ``None`` (naive datetime).
    """
    if dt.tzinfo is None:
        raise ValueError(
            'toCanonicalIso() refuses naive datetime -- callers must pass a '
            'tz-aware value (see TD-027 invariant). Use '
            'datetime.now(UTC) or attach tzinfo explicitly.'
        )
    return dt.astimezone(UTC).strftime(CANONICAL_ISO_FORMAT)
