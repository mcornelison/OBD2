################################################################################
# File Name: mil_edge.py
# Purpose/Description: MIL_ON 0->1 rising-edge detector for the orchestrator.
#                      Used to dispatch DtcLogger.logMilEventDtcs (US-204) on
#                      mid-drive MIL illumination events.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- MIL rising-edge detector.
# ================================================================================
################################################################################

"""Trivial 0->1 rising-edge detector for the MIL_ON parameter (US-204).

The orchestrator's reading dispatcher (``_handleReading``) feeds every
``MIL_ON`` observation into :meth:`MilRisingEdgeDetector.observe` --
when the call returns ``True``, the orchestrator fires
:meth:`~src.pi.obdii.dtc_logger.DtcLogger.logMilEventDtcs` to refresh
the stored DTC set.

Why a class instead of a free function: the detector needs per-process
state (the previous reading) and we want a clean reset hook for
session-restart edge cases.  Per US-204 stopCondition #4, this is the
minimal integration pattern -- no orchestrator event-loop refactor.
"""

from __future__ import annotations

__all__ = ['MilRisingEdgeDetector']


class MilRisingEdgeDetector:
    """Detect 0->1 transitions of the MIL_ON parameter.

    The detector is stateful (last seen value).  ``observe`` returns
    ``True`` exactly once per rising edge -- subsequent reads of 1
    return ``False`` until a 0 has been observed in between.  None
    inputs are silently ignored (no state change).

    Initial state: the very first observation of ``1`` after
    construction or :meth:`reset` is treated as a rising edge so a
    fresh process that connects mid-drive to an already-illuminated
    MIL still triggers the DTC re-fetch.
    """

    def __init__(self) -> None:
        self._lastValue: int | None = None  # 0 / 1 / None (never observed)

    def observe(self, value: float | int | None) -> bool:
        """Feed one MIL_ON sample.  Returns True on rising edge.

        Args:
            value: Numeric reading (typically 0.0 or 1.0; the decoder
                produces those magnitudes).  ``None`` is treated as
                "no fresh data" and does NOT update state.
        """
        if value is None:
            return False
        bit = 1 if float(value) >= 0.5 else 0
        previous = self._lastValue
        self._lastValue = bit
        if previous is None:
            # First observation: only 1 counts as a rising edge (an
            # already-on MIL on a fresh connection should fire the
            # DTC re-fetch; a 0 simply seeds the baseline).
            return bit == 1
        return previous == 0 and bit == 1

    def reset(self) -> None:
        """Forget prior state.  Next observation re-evaluates from scratch."""
        self._lastValue = None
