################################################################################
# File Name: vehicle_info_coherence.py
# Purpose/Description: Sprint 44 V0.28.1 (US-376 / B-076 first slice) -- the
#                      transitional-coherence guard between vehicle_info's
#                      deprecated-transitional ECU signature TEXT columns and the
#                      normalized ecu identity row they reference by FK.  While
#                      both representations coexist (this slice KEEPS the TEXT
#                      columns), every vehicle_info row's ecu_signature /
#                      cal_signature MUST equal the joined ecu row's values
#                      (zero drift).  The writer (stamp_ecu_swap) DERIVES the
#                      text columns from the ecu row to maintain this; this
#                      module is the read-side checker a regression test (and any
#                      future audit CLI) uses to assert the invariant holds.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-01    | Rex (US-376) | Initial -- ecu/vehicle_info coherence checker.
# ================================================================================
################################################################################

"""US-376 / B-076: vehicle_info <-> ecu transitional-coherence checker."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.server.db.models import Ecu, VehicleInfo


def findEcuCoherenceViolations(session: Session) -> list[dict]:
    """Return vehicle_info rows whose TEXT signatures drift from their ecu row.

    The B-076 first slice keeps the transitional ``vehicle_info.ecu_signature``
    / ``cal_signature`` TEXT columns alongside the new ``ecu_id`` FK.  They are
    a denormalized snapshot of the joined ecu row and MUST stay in lockstep with
    it; the writer derives them from the ecu row so under normal operation drift
    is impossible.  This checker surfaces any row where they diverged (a bad
    direct UPDATE, a missed writer path) so a regression test can assert zero
    drift across the whole table.

    Args:
        session: An open SQLAlchemy session bound to the server schema.

    Returns:
        One dict per drifted row with ``vehicle_info_id``, ``ecu_id``, the
        stored ``ecu_signature`` / ``cal_signature``, and the joined ecu row's
        ``expected_ecu_signature`` / ``expected_cal_signature``.  Empty list
        when every row is coherent.
    """
    rows = session.execute(
        select(
            VehicleInfo.id,
            VehicleInfo.ecu_id,
            VehicleInfo.ecu_signature,
            VehicleInfo.cal_signature,
            Ecu.ecu_signature.label("expected_ecu_signature"),
            Ecu.cal_signature.label("expected_cal_signature"),
        ).join(Ecu, VehicleInfo.ecu_id == Ecu.id),
    ).all()

    violations: list[dict] = []
    for row in rows:
        if (
            row.ecu_signature != row.expected_ecu_signature
            or row.cal_signature != row.expected_cal_signature
        ):
            violations.append(
                {
                    "vehicle_info_id": row.id,
                    "ecu_id": row.ecu_id,
                    "ecu_signature": row.ecu_signature,
                    "cal_signature": row.cal_signature,
                    "expected_ecu_signature": row.expected_ecu_signature,
                    "expected_cal_signature": row.expected_cal_signature,
                },
            )
    return violations
