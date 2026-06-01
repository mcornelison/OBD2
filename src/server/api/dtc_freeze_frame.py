################################################################################
# File Name: dtc_freeze_frame.py
# Purpose/Description: Server-side writer-path for the dtc_freeze_frame capture
#                      table (US-368 / F-109).  insertDtcFreezeFrame() is the
#                      SSOT gate that binds a Mode 02 freeze-frame to the ECU era
#                      active at capture time: it enforces the temporal invariant
#                      ecu_install <= captured_at <= ecu_removal (removal NULL =
#                      currently-active/open) and refuses a bogus vehicle_info FK
#                      BEFORE any partial insert.  The Pi cannot enforce this --
#                      its vehicle_info schema carries no ECU lineage (server-only
#                      per US-365) -- so this writer-path is where the FK is kept
#                      honest on ingest + server-side resolution.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- F-109 insertDtcFreezeFrame temporal-
#               |              | invariant writer-path.
# ================================================================================
################################################################################

"""dtc_freeze_frame writer-path (US-368 / F-109).

A freeze-frame is the 16-PID Mode 02 snapshot captured when a DTC trips.  Its
``vehicle_info_id`` FK must point at the ECU that was actually installed at
``captured_at`` -- otherwise a post-mortem would read the snapshot against the
wrong ECU's calibration.  :func:`insertDtcFreezeFrame` is the only sanctioned
server-side insert path and enforces that temporal invariant; ``vehicle_info``
is append-only (see its table comment) so the resolved row never has its
identity rewritten underneath an existing freeze-frame.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from src.server.db.models import DtcFreezeFrame, VehicleInfo

__all__ = ['insertDtcFreezeFrame']

logger = logging.getLogger(__name__)


def insertDtcFreezeFrame(
    session: Session,
    *,
    vehicle_info_id: int,
    captured_at: datetime,
    source_id: int,
    source_device: str,
    pid_responses: dict | None = None,
    dtc_log_id: int | None = None,
) -> DtcFreezeFrame:
    """Insert one dtc_freeze_frame row, enforcing the ECU-window invariant.

    The ``vehicle_info`` row is resolved + validated BEFORE any row is added to
    the session, so a rejected insert leaves zero partial state.

    Args:
        session: Open SQLAlchemy session.  Caller owns the surrounding
            transaction boundary; this function commits the insert.
        vehicle_info_id: FK to the ECU-lineage row the freeze-frame belongs to.
            Must exist and its ``[ecu_install, ecu_removal]`` window must
            contain ``captured_at``.
        captured_at: When the Mode 02 snapshot was taken (UTC).
        source_id: Pi-side row id (sync upsert key with ``source_device``).
        source_device: Originating device id.
        pid_responses: 16-PID Mode 02 snapshot dict.  ``None`` / ``{}`` is the
            graceful-degradation case (DTC tripped but Mode 02 unavailable);
            stored as ``{}``.
        dtc_log_id: FK to the parent ``dtc_log`` row, when resolved.

    Returns:
        The persisted :class:`~src.server.db.models.DtcFreezeFrame` row
        (``id`` populated).

    Raises:
        ValueError: If ``vehicle_info_id`` does not resolve to a row
            (``'vehicle_info id ... not found'``), if ``captured_at`` predates
            the ECU's install (``'predates'``), or if it postdates a CLOSED
            ECU's removal (``'postdates'``).  No row is inserted in any of
            these cases.
    """
    vehicle = session.get(VehicleInfo, vehicle_info_id)
    if vehicle is None:
        raise ValueError(
            f'vehicle_info id {vehicle_info_id!r} not found; '
            f'cannot bind a freeze-frame to a non-existent ECU row',
        )

    install = vehicle.ecu_install_timestamp_utc
    removal = vehicle.ecu_removal_timestamp_utc

    if captured_at < install:
        raise ValueError(
            f'freeze-frame captured_at {captured_at.isoformat()} predates '
            f'vehicle_info id {vehicle_info_id} ecu_install '
            f'{install.isoformat()}; the ECU was not yet installed at capture '
            f'time',
        )
    if removal is not None and captured_at > removal:
        raise ValueError(
            f'freeze-frame captured_at {captured_at.isoformat()} postdates '
            f'vehicle_info id {vehicle_info_id} ecu_removal '
            f'{removal.isoformat()}; the ECU window was already closed at '
            f'capture time',
        )

    row = DtcFreezeFrame(
        source_id=source_id,
        source_device=source_device,
        dtc_log_id=dtc_log_id,
        captured_at_timestamp_utc=captured_at,
        pid_responses_json=pid_responses or {},
        vehicle_info_id=vehicle_info_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
