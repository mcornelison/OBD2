################################################################################
# File Name: test_mil_rising_edge.py
# Purpose/Description: Tests for the MilRisingEdgeDetector used by the
#                      orchestrator to fire DtcLogger.logMilEventDtcs on
#                      0->1 transitions of the MIL_ON parameter (US-204).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- MIL rising-edge detector tests.
# ================================================================================
################################################################################

"""Tests for :class:`src.pi.obdii.mil_edge.MilRisingEdgeDetector`."""

from __future__ import annotations

from src.pi.obdii.mil_edge import MilRisingEdgeDetector


class TestRisingEdgeDetection:
    """Detector observes 0->1 once per session-up transition."""

    def test_initialZeroIsNotAnEdge(self) -> None:
        det = MilRisingEdgeDetector()
        assert det.observe(0.0) is False

    def test_initialOneIsRisingEdge(self) -> None:
        """First observation of 1 with no prior reading = rising edge."""
        det = MilRisingEdgeDetector()
        assert det.observe(1.0) is True

    def test_zeroToOneIsRisingEdge(self) -> None:
        det = MilRisingEdgeDetector()
        det.observe(0.0)
        assert det.observe(1.0) is True

    def test_oneToOneIsNotEdge(self) -> None:
        """Sustained MIL on does NOT re-trigger; only transitions count."""
        det = MilRisingEdgeDetector()
        det.observe(1.0)
        assert det.observe(1.0) is False

    def test_oneToZeroIsNotEdge(self) -> None:
        """Falling edge ignored -- DTC re-fetch is rising-edge-only."""
        det = MilRisingEdgeDetector()
        det.observe(1.0)
        assert det.observe(0.0) is False

    def test_zeroOneZeroOneFiresTwice(self) -> None:
        det = MilRisingEdgeDetector()
        assert det.observe(0.0) is False
        assert det.observe(1.0) is True
        assert det.observe(0.0) is False
        assert det.observe(1.0) is True


class TestNumericCoercion:
    """Tolerate ints, floats, None inputs gracefully."""

    def test_intsAccepted(self) -> None:
        det = MilRisingEdgeDetector()
        assert det.observe(0) is False
        assert det.observe(1) is True

    def test_noneIgnored(self) -> None:
        """A None reading carries no MIL info; do NOT update state."""
        det = MilRisingEdgeDetector()
        det.observe(0.0)
        assert det.observe(None) is False
        # Subsequent 1.0 still reads as a transition from the LAST
        # known value (0), not from the None observation.
        assert det.observe(1.0) is True


class TestReset:
    """Reset clears prior state so the next observation starts fresh."""

    def test_resetClearsHistory(self) -> None:
        det = MilRisingEdgeDetector()
        det.observe(1.0)
        det.reset()
        # First post-reset observation of 1.0 fires again.
        assert det.observe(1.0) is True
