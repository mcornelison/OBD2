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
from typing import Any
from zoneinfo import ZoneInfo

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


# ------------------------------------------------------------------------------
# The DECLARED local zone (US-809-0)
# ------------------------------------------------------------------------------
# `toCanonicalIso()` above REFUSES a naive datetime, which is correct and stays.
# But a naive value still has to come from somewhere before it can be refused,
# and the zone it is expressed in was, until this key, an undeclared property of
# whatever OS the code happened to boot on.
#
# This is a PREVENTIVE declaration, not a bug fix. Measured on chi-eclipse-01
# 2026-09-23: it already reads America/Chicago and keeps its RTC in UTC, so
# nothing is currently shifted. What the key removes is the FUTURE case -- a
# reimage or a `raspi-config` change would move every converted timestamp with
# no code change and no failing test. Declared, that becomes a config diff;
# undeclared, it is silent data corruption.
#
# One correction to the story text, measured rather than repeated: the same
# reading reported `System clock synchronized: no` (NTP active, RTC within a
# second of system time), NOT synchronised as stated. It changes nothing here
# -- a zone is not a clock -- but it is exactly why A-double-prime asks for the
# clockSynced flag to land BESIDE the event time rather than be assumed.
#
# It does NOT replace the A-54 canary. Config declares WHICH zone naive values
# are in; it cannot declare that a producer COMPLIES. A producer emitting
# naive-UTC still has tzinfo None, still takes the naive branch, and is still
# shifted. Config supplies the value; the canary enforces compliance.

LOCAL_ZONE_CONFIG_KEY: str = 'pi.time.localZone'


def resolveLocalZone(config: dict[str, Any]) -> ZoneInfo:
    """Return the DECLARED local zone, or refuse.

    The single consumer of :data:`LOCAL_ZONE_CONFIG_KEY`. It never consults the
    host: ``/etc/timezone`` is the undeclared setting this key exists to
    replace, so falling back to it would reintroduce the defect at the one site
    meant to remove it.

    Args:
        config: A validated configuration mapping.

    Returns:
        The :class:`zoneinfo.ZoneInfo` named by the declared key.

    Raises:
        ValueError: If the key is absent, empty, or not a zone the host's IANA
            database knows. The message names the key so the remedy is the
            config edit rather than a hunt through the call stack.
    """
    declared: Any = config
    for part in LOCAL_ZONE_CONFIG_KEY.split('.'):
        if not isinstance(declared, dict):
            declared = None
            break
        declared = declared.get(part)

    if not declared or not isinstance(declared, str):
        raise ValueError(
            f'{LOCAL_ZONE_CONFIG_KEY} is not declared (got {declared!r}). '
            'It has no default at this layer and the host zone is deliberately '
            'NOT consulted -- declare an IANA zone in config.json.'
        )

    try:
        return ZoneInfo(declared)
    except (KeyError, ValueError) as exc:
        # ZoneInfoNotFoundError (a KeyError) for an unknown key; ValueError for
        # a malformed one such as '../etc/passwd'. Both are refusals.
        raise ValueError(
            f'{LOCAL_ZONE_CONFIG_KEY} is {declared!r}, which this host\'s IANA '
            f'database cannot resolve ({type(exc).__name__}). No timestamp is '
            'produced; the host zone is not substituted.'
        ) from exc


def localNaiveToCanonicalIso(dt: datetime, config: dict[str, Any]) -> str:
    """Render a NAIVE local datetime as a canonical UTC string, or refuse.

    For values that are known to be expressed in the declared local zone and
    carry no ``tzinfo``. The zone comes from config; when it is not declared
    this raises and **no timestamp is produced**, because a guessed zone yields
    a plausible-looking string that is wrong by a whole-hour offset -- the
    failure mode that is hardest to notice downstream.

    A value that is ALREADY tz-aware is passed straight to
    :func:`toCanonicalIso`; attaching a second zone to it would corrupt it.

    Args:
        dt: The datetime to render. Naive values are interpreted in the
            declared zone; aware values are converted as they are.
        config: A validated configuration mapping.

    Returns:
        A string of the form ``YYYY-MM-DDTHH:MM:SSZ``.

    Raises:
        ValueError: If ``dt`` is naive and no usable zone is declared.
    """
    if dt.tzinfo is not None:
        return toCanonicalIso(dt)
    return toCanonicalIso(dt.replace(tzinfo=resolveLocalZone(config)))
