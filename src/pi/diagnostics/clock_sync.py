################################################################################
# File Name: clock_sync.py
# Purpose/Description: Post-reboot clock-drift honest instrument (US-419 /
#                      F-080).  The Pi's RTC coin-cell can be dead/absent, so a
#                      fresh boot may read a bogus wall-clock time (epoch /
#                      build-date) until systemd-timesyncd corrects it seconds
#                      after the network comes up.  This module is the single
#                      authoritative provider (SSOT) of the "is this boot
#                      timestamp trustworthy?" fact: boot-log writers apply its
#                      verdict as policy (flag data_quality='clock_unsynced')
#                      rather than each acquiring their own clock signal.
#                      The RTC coin-cell / timesyncd-ordering fix itself is ops
#                      (AI-1), out of this module's scope.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-07-01    | Rex     | Initial -- US-419 clock-drift guard (F-080).
# ================================================================================
################################################################################
"""Honest-instrument classifier for post-reboot clock drift (US-419).

Two signals, combined so the guard is both robust and free of false-positive
floods:

* **Sanity floor** (always available, subprocess-free): no genuine Eclipse
  OBD-II telemetry predates :data:`CLOCK_SANITY_FLOOR_ISO`.  A wall clock
  reading earlier than the floor is *definitively* a dead-RTC reset -- flag it
  regardless of anything else.  Because every capture timestamp is canonical
  fixed-width ISO-8601 UTC (``src.common.time.helper``), the comparison is a
  plain lexical string ``<`` -- the same total, never-raising ordering the
  snapshot-sync cursor relies on.
* **NTP-sync probe** (best-effort refinement): ``timedatectl`` reports whether
  systemd-timesyncd has disciplined the clock yet.  When it says *not synced*
  we flag even a plausible-looking timestamp; when the probe is unreachable
  (non-systemd / dev box) we return ``None`` and fall back to the floor alone
  -- an unreachable probe must never paint every row suspect.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from src.common.time.helper import CANONICAL_ISO_FORMAT

# data_quality enum values written to the boot-log tables.  Mirrors the
# server-side ``data_quality`` vocabulary shape (full = clean).  These are
# Pi-LOCAL honest-instrument flags -- the server computes its own data_quality
# at ingest (Pi = emitter, server = authority), so they are stripped from the
# sync wire (see src.pi.data.sync_log wire-strip).
CLOCK_QUALITY_FULL: str = "full"
CLOCK_QUALITY_CLOCK_UNSYNCED: str = "clock_unsynced"

# Canonical ISO-8601 UTC floor.  Grounded: the Eclipse OBD-II project was
# active in 2026 (project MEMORY); no genuine telemetry predates 2025.  A
# post-reboot wall clock earlier than this is a dead-RTC epoch/build-time
# reset, not real time.  Same canonical shape as every capture timestamp so
# the compare is lexical.
CLOCK_SANITY_FLOOR_ISO: str = "2025-01-01T00:00:00Z"

# timedatectl is a sub-second local query; a generous ceiling keeps a hung
# probe from ever stalling the boot-log write path.
_NTP_PROBE_TIMEOUT_SECONDS: int = 2

# Length of the canonical timestamp, e.g. "2026-07-01T12:00:00Z" (20 chars).
# A candidate that is not exactly this shape cannot be lexically compared to
# the floor with confidence, so the floor check is skipped for it.
_CANONICAL_ISO_LENGTH: int = len("YYYY-MM-DDThh:mm:ssZ")


def _looksCanonical(value: object) -> bool:
    """Return True iff ``value`` is a canonical fixed-width ISO-8601 UTC string.

    A cheap structural gate (length + ``T`` / ``Z`` anchors) -- enough to make
    the lexical floor comparison meaningful without importing a full parser or
    ever raising on garbage input.
    """
    return (
        isinstance(value, str)
        and len(value) == _CANONICAL_ISO_LENGTH
        and value[10] == "T"
        and value.endswith("Z")
    )


def classifyClockQuality(
    candidateIso: str,
    *,
    ntpSynced: bool | None = None,
    sanityFloorIso: str = CLOCK_SANITY_FLOOR_ISO,
) -> str:
    """Classify a candidate boot timestamp as trustworthy or drifted.

    Pure and total -- never raises, never spawns a subprocess.  This is the
    seam latency-sensitive / high-volume writers use (they pass only the
    timestamp; ``ntpSynced`` defaults to ``None`` so only the floor applies).

    Args:
        candidateIso: The canonical ISO-8601 UTC timestamp about to be written.
        ntpSynced: Tri-state NTP-sync signal.  ``True`` = disciplined clock,
            ``False`` = explicitly not synced, ``None`` = undeterminable.
        sanityFloorIso: The canonical floor below which any timestamp is a
            definitive dead-RTC reset.  Defaults to :data:`CLOCK_SANITY_FLOOR_ISO`.

    Returns:
        :data:`CLOCK_QUALITY_CLOCK_UNSYNCED` when the timestamp is pre-floor OR
        the NTP probe explicitly reports not-synced; otherwise
        :data:`CLOCK_QUALITY_FULL`.
    """
    # Floor wins unconditionally: a pre-floor timestamp is a definitive reset
    # even if the (post-correction) NTP probe now reads synced.
    if _looksCanonical(candidateIso) and candidateIso < sanityFloorIso:
        return CLOCK_QUALITY_CLOCK_UNSYNCED
    if ntpSynced is False:
        return CLOCK_QUALITY_CLOCK_UNSYNCED
    return CLOCK_QUALITY_FULL


def _defaultTimedatectlRunner() -> str:
    """Return raw ``timedatectl`` NTPSynchronized output ('yes'/'no').

    Raises whatever :func:`subprocess.run` raises (``FileNotFoundError`` on a
    non-systemd box, ``TimeoutExpired``, ``CalledProcessError``) -- the caller
    (:func:`isNtpSynchronized`) treats every failure as *undeterminable*.
    """
    result = subprocess.run(
        ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
        capture_output=True,
        text=True,
        timeout=_NTP_PROBE_TIMEOUT_SECONDS,
        check=True,
    )
    return result.stdout


def isNtpSynchronized(
    runner: Callable[[], str] | None = None,
) -> bool | None:
    """Best-effort probe of systemd-timesyncd's NTP-sync state.

    Args:
        runner: Injection seam returning raw ``timedatectl`` output.  Defaults
            to :func:`_defaultTimedatectlRunner`.  Tests pass a stub.

    Returns:
        ``True`` when the clock is disciplined, ``False`` when explicitly not
        synced, ``None`` when the probe is unreachable or ambiguous.  Never
        raises.
    """
    runner = runner or _defaultTimedatectlRunner
    try:
        raw = runner()
    except Exception:  # noqa: BLE001 -- any probe failure -> undeterminable
        return None
    token = (raw or "").strip().lower()
    if token in ("yes", "true", "1"):
        return True
    if token in ("no", "false", "0"):
        return False
    return None


def assessClockQuality(
    candidateIso: str,
    *,
    runner: Callable[[], str] | None = None,
) -> str:
    """Full assessment: probe NTP state, then classify (SSOT production entry).

    Used by the once-per-boot ``startup_log`` writer, where the subprocess cost
    is paid at most once and the NTP refinement is most valuable.

    Args:
        candidateIso: The canonical ISO-8601 UTC timestamp about to be written.
        runner: Injection seam forwarded to :func:`isNtpSynchronized`.

    Returns:
        The :func:`classifyClockQuality` verdict for ``candidateIso`` given the
        probed NTP state.
    """
    return classifyClockQuality(
        candidateIso, ntpSynced=isNtpSynchronized(runner=runner)
    )


# Re-exported so callers can format a datetime against the same canonical shape
# the floor comparison assumes, without reaching past this module.
__all__ = [
    "CANONICAL_ISO_FORMAT",
    "CLOCK_QUALITY_CLOCK_UNSYNCED",
    "CLOCK_QUALITY_FULL",
    "CLOCK_SANITY_FLOOR_ISO",
    "assessClockQuality",
    "classifyClockQuality",
    "isNtpSynchronized",
]
