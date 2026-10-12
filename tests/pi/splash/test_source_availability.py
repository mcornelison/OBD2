################################################################################
# File Name: test_source_availability.py
# Purpose/Description: US-429 tests for the honest-availability SSOT builder
#   (pi.splash.source_availability). Verifies the one source-availability block
#   shape: available -> reason forced None (a live source has no NA reason);
#   unavailable -> the typed reason travels with it; a reasonless absence falls
#   back to "unavailable" (never a reasonless NA); and NA is NULL + reason, never
#   a numeric sentinel.
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

"""Tests for ``pi.splash.source_availability`` (US-429)."""

from pi.splash.source_availability import (
    REASON_OBD_OFF,
    buildSourceState,
)


def test_buildSourceState_available_hasNullReason():
    """A live source has no NA reason -- reason is forced None even if supplied,
    because the reason only exists to explain an absence."""
    assert buildSourceState(True, REASON_OBD_OFF) == {"available": True, "reason": None}


def test_buildSourceState_unavailable_carriesTypedReason():
    """An unavailable source carries its typed reason verbatim (the reason
    travels with the NULL so the surface is honest about WHY)."""
    assert buildSourceState(False, REASON_OBD_OFF) == {
        "available": False,
        "reason": "OBD: off",
    }


def test_buildSourceState_unavailableNoReason_fallsBackToUnavailable():
    """A reasonless absence still names a reason ("unavailable") -- a NA is
    never reasonless."""
    assert buildSourceState(False) == {"available": False, "reason": "unavailable"}


def test_buildSourceState_reasonIsNeverNumericSentinel():
    """NA is NULL + a string reason -- never a numeric sentinel (no pd_stage=-1
    trap). The reason field is either None (available) or a str (unavailable)."""
    avail = buildSourceState(True)
    unavail = buildSourceState(False, "gauge unreadable")
    assert avail["reason"] is None
    assert isinstance(unavail["reason"], str)
    for block in (avail, unavail):
        assert not isinstance(block["reason"], (int, float))
