################################################################################
# File Name: fuel_status.py
# Purpose/Description: US-890-c (F-127) -- the ONE closed-loop code set for
#                      FUEL_SYSTEM_STATUS (Atlas S104 total-trim ruling,
#                      2026-10-15), shared by the fuel-economy integrator and
#                      the states/obd-live fuel block so no second copy exists.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-890-c) | Initial -- moved CLOSED_LOOP_FUEL_STATUS_CODES
#                                out of fuel_economy_emitter; fuelLoopState.
# ================================================================================
################################################################################

"""Which FUEL_SYSTEM_STATUS codes mean closed loop (US-890-c).

``FUEL_SYSTEM_STATUS`` is stored and published as its NUMERIC enum code
(measured in obd.db: 1.0 / 2.0 / 3.0). Deciding which codes are closed loop is a
judgement, so it is made once, here, and every provider imports it: a page never
maps codes itself.

``ltft_trend_emitter.FUEL_SYSTEM_CLOSED_LOOP`` is a DIFFERENT rule (Spool's
code-2-only qualifying gate for the trim trend) and deliberately stays where it
is.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CLOSED_LOOP_FUEL_STATUS_CODES",
    "FUEL_LOOP_CLOSED",
    "FUEL_LOOP_OPEN",
    "fuelLoopState",
]

# decoders._FUEL_STATUS_ENUM: 2 = CL and 5 = CL-fault are closed loop. 1 OL,
# 3 OL-drive (decel AND enrichment), 4 OL-fault and 0/unknown are open loop.
CLOSED_LOOP_FUEL_STATUS_CODES = frozenset({2, 5})

# states/obd-live fuel.loop vocabulary.
FUEL_LOOP_CLOSED = "closed"
FUEL_LOOP_OPEN = "open"


def fuelLoopState(value: Any) -> str | None:
    """The loop state a FUEL_SYSTEM_STATUS value names.

    Args:
        value: The PID's value -- its numeric enum code (int, or a float such
            as ``2.0`` as realtime_data stores it).

    Returns:
        ``"closed"`` for a code in :data:`CLOSED_LOOP_FUEL_STATUS_CODES`,
        ``"open"`` for any other integral code, or None when the value is not a
        code at all (None, a bool, a string, a fractional number) -- unknown is
        never guessed as open.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return FUEL_LOOP_CLOSED if int(value) in CLOSED_LOOP_FUEL_STATUS_CODES else FUEL_LOOP_OPEN
