################################################################################
# File Name: source_availability.py
# Purpose/Description: US-429 honest-availability SSOT [F-092]. The ONE shape for
#   a source-availability fact shared by every carousel emitter, built to
#   specs/ssot-design-pattern.md "Honest availability -- the unavailable-source
#   -> typed-NA pattern" (Atlas-ratified 2026-07-01). Availability is ONE truth
#   per SOURCE (obd-link / ups / dtc), NOT per parameter: every value a source
#   produces inherits its one `state.source.<x> = {available, reason}` fact. A
#   typed absence is NULL + a reason string that travels with it ("OBD: off" /
#   "gauge unreadable" / "not read yet") -- NEVER a numeric sentinel (no
#   pd_stage=-1-class trap). Defining the block here once is the SSOT enforcement:
#   the three emitters reference this builder instead of each hand-writing a
#   possibly-divergent copy (the exact "N divergent copies of one fact" bug the
#   design pattern kills).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Ralph (Rex)  | Initial -- US-429 honest-availability SSOT.
# ================================================================================
################################################################################

"""The one source-availability block shape shared by the carousel emitters."""

from __future__ import annotations

__all__ = [
    "REASON_DTC_NOT_READ",
    "REASON_NO_OBD",
    "REASON_OBD_OFF",
    "REASON_UPS_UNREADABLE",
    "SOURCE_DTC",
    "SOURCE_OBD",
    "SOURCE_UPS",
    "buildSourceState",
]

# The three carousel sources (one availability truth apiece). These are the
# `<x>` in the spec's retained `state.source.<x>` STATE topic.
SOURCE_OBD = "obd"
SOURCE_UPS = "ups"
SOURCE_DTC = "dtc"

# Common typed-NA reasons (human-readable; they travel WITH the NULL so the
# surface is honest about *why* -- a driver reads "OBD: off" very differently
# from "gauge unreadable"). Callers may supply any reason string; these are the
# shared defaults so the emitters + tests agree.
REASON_OBD_OFF = "OBD: off"  # car off / on wall power -> no link expected
REASON_NO_OBD = "no OBD"  # a derived value whose OBD source is down
REASON_UPS_UNREADABLE = "gauge unreadable"  # MAX17048 read failed / absent
REASON_DTC_NOT_READ = "not read yet"  # no KOEO/drive DTC read has happened


def buildSourceState(available: bool, reason: str | None = None) -> dict:
    """Return the one-truth-per-source availability block (pure).

    A live source has no NA reason, so ``reason`` is forced ``None`` whenever
    ``available`` is True -- the reason only exists to explain an absence. An
    unavailable source with no supplied reason falls back to the bare
    ``"unavailable"`` label so a NA is never reasonless.

    Args:
        available: Whether the source is currently producing real data.
        reason: The typed-NA reason (why the source is unavailable). Ignored
            when ``available`` is True.

    Returns:
        ``{"available": bool, "reason": str | None}`` -- ``reason`` is None when
        available, else the supplied reason (or ``"unavailable"``).
    """
    isAvailable = bool(available)
    return {
        "available": isAvailable,
        "reason": None if isAvailable else (reason or "unavailable"),
    }
