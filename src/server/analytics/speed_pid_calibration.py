################################################################################
# File Name: speed_pid_calibration.py
# Purpose/Description: Server-side writer-path + analytics gate for the
#                      speed_pid_calibration table (US-370 / F-076).  Provides
#                      insert_speed_pid_calibration() -- the writer-path guard
#                      that enforces non-empty ecu_signature + provenance
#                      (empty-string forbidden, matching the vehicle_info
#                      identity-immutability discipline) -- and
#                      select_empirical_calibrations(), the analytics gate that
#                      returns only empirically-derived calibration rows
#                      (provenance prefixed 'empirical-'), excluding rough seeds.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-29    | Rex (US-370) | Initial -- F-076 speed_pid_calibration writer-path
#               |              | guard (non-empty provenance/ecu_signature) +
#               |              | empirical-provenance-prefix analytics gate.
# ================================================================================
################################################################################

"""Writer-path guard + analytics prefix gate for ``speed_pid_calibration``.

The ``speed_pid_calibration`` table (US-370 / F-076) is the SSOT for per-ECU
multiplicative SPEED-PID correction.  This module owns the two policy seams over
it:

* :func:`insert_speed_pid_calibration` -- the writer path.  The DB enforces
  ``provenance NOT NULL``, but an empty / whitespace-only string slips past a
  NOT NULL constraint; this guard rejects it (and an empty ``ecu_signature``)
  with a :class:`ValueError`, matching the vehicle_info identity-immutability
  writer discipline (US-365).
* :func:`select_empirical_calibrations` -- the analytics gate.  Returns only
  rows whose ``provenance`` begins with ``'empirical-'`` so aggregations that
  demand a measured calibration exclude rough bootstrap seeds (the prior-ECU
  ``gear-math-...`` and new-ECU ``rough-seed-...`` v0010 seed rows).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.server.db.models import (
    SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX,
    SpeedPidCalibration,
)


def insert_speed_pid_calibration(
    session: Session,
    *,
    ecu_signature: str,
    correction_factor: float,
    provenance: str,
    capture_method: str | None = None,
    captured_at: datetime | None = None,
    captured_by: str | None = None,
    notes: str | None = None,
) -> SpeedPidCalibration:
    """Insert a per-ECU SPEED-PID calibration row, enforcing non-empty grounding.

    The DB layer enforces ``provenance NOT NULL`` and the ``ecu_signature``
    UNIQUE natural key, but a NOT NULL column still accepts an empty string.
    This writer path rejects an empty / whitespace-only ``provenance`` or
    ``ecu_signature`` so every persisted calibration records both *which* ECU it
    corrects and *how* the factor was derived -- the same discipline the
    vehicle_info identity columns use (US-365).

    Args:
        session: An active SQLAlchemy session bound to the server schema.
        ecu_signature: The ECU signature this factor corrects (natural key).
        correction_factor: Multiplicative factor; ``OBD reading x factor =
            ground truth``.
        provenance: Non-empty grounding string (how the factor was derived,
            e.g. ``'empirical-gps-correlation-2026-06-15'``).
        capture_method: Optional method tag (see
            ``SPEED_PID_CALIBRATION_CAPTURE_METHOD_VALUES``).
        captured_at: Optional capture timestamp (UTC).
        captured_by: Optional capturer identifier.
        notes: Optional free-text notes.

    Returns:
        The added :class:`SpeedPidCalibration` instance (not yet flushed).

    Raises:
        ValueError: If ``ecu_signature`` or ``provenance`` is empty or only
            whitespace.
    """
    if not ecu_signature or not ecu_signature.strip():
        raise ValueError(
            "speed_pid_calibration ecu_signature must be a non-empty string; "
            "every calibration must name the ECU it corrects.",
        )
    if not provenance or not provenance.strip():
        raise ValueError(
            "speed_pid_calibration provenance must be a non-empty string; "
            "every correction factor must record how it was derived "
            "(empty string forbidden, matching the identity-immutability "
            "writer discipline).",
        )

    row = SpeedPidCalibration(
        ecu_signature=ecu_signature,
        correction_factor=correction_factor,
        capture_method=capture_method,
        captured_at_timestamp_utc=captured_at,
        captured_by=captured_by,
        provenance=provenance,
        notes=notes,
    )
    session.add(row)
    return row


def select_empirical_calibrations(session: Session) -> list[SpeedPidCalibration]:
    """Return only empirically-derived calibration rows (provenance gate).

    Filters on ``provenance LIKE 'empirical-%'`` so callers that require a
    measured calibration exclude rough bootstrap seeds (the prior-ECU
    ``gear-math-...`` and new-ECU ``rough-seed-...`` v0010 seed rows).  The
    prefix is the SSOT constant
    ``SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX``.

    Args:
        session: An active SQLAlchemy session bound to the server schema.

    Returns:
        A list of :class:`SpeedPidCalibration` rows whose ``provenance``
        begins with the empirical prefix; ``[]`` when none qualify.
    """
    pattern = f"{SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX}%"
    return list(
        session.execute(
            select(SpeedPidCalibration).where(
                SpeedPidCalibration.provenance.like(pattern),
            )
        ).scalars()
    )


__all__ = [
    "insert_speed_pid_calibration",
    "select_empirical_calibrations",
]
