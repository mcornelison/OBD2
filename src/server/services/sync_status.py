################################################################################
# File Name: sync_status.py
# Purpose/Description: US-795(a) -- read what the server knows about each car's
#                      sync queue from sync_history, and state it through the
#                      one currency assessor. Read-only.
# Author: Atlas (Architect) -- US-795(a), CIO-directed build
# Creation Date: 2026-10-06
################################################################################
"""What the server knows about each car's sync queue (US-795(a)).

CIO rulings 2026-10-06: report EVERYTHING the car still had unsynced at its last
contact, as a total plus a drive/sensor split; state the contact's age; give no
online/offline verdict; show the stall alarm. The judgement and the words are
``src/server/api/currency``'s -- this module only turns ``sync_history`` rows
into its ``ContactRecord`` inputs, so there is one reader, not two.

The CLI (sync session) and ``GET /api/v1/sync/status`` (async session) run the
SAME select statements built here; only the transport differs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select

from src.server.api.currency import (
    ContactRecord,
    assessVehicleCurrency,
    renderCurrency,
)
from src.server.db.models import SyncHistory

__all__ = [
    'CONTACT_HISTORY_LIMIT',
    'ContactRecord',
    'DeviceSyncStatus',
    'contactsFromRows',
    'contactsSelect',
    'deviceSyncStatus',
    'devicesSelect',
    'readSyncStatus',
    'readSyncStatusAsync',
]

#: Completed contacts read per device: the newest decides the answer and the
#: stall alarm needs a short run before it. Generous, so contacts that carried
#: no residual cannot crowd the measured ones out of the window.
CONTACT_HISTORY_LIMIT: int = 20

_ISO_FORMAT: str = '%Y-%m-%dT%H:%M:%SZ'
_COMPLETED: str = 'completed'


@dataclass(frozen=True)
class DeviceSyncStatus:
    """One car's queue as of its last contact, with the sentence that states it."""

    deviceId: str
    state: str
    lastContact: str | None
    ageSeconds: int | None
    outstandingRows: int | None
    exact: bool | None
    driveRows: int | None
    sensorRows: int | None
    fault: str | None
    statement: str

    def toDict(self) -> dict[str, Any]:
        """The API's JSON shape."""
        return asdict(self)


def devicesSelect() -> Select:
    """Every device that has completed at least one contact, by name."""
    return (
        select(SyncHistory.device_id)
        .where(SyncHistory.status == _COMPLETED)
        .distinct()
        .order_by(SyncHistory.device_id)
    )


def contactsSelect(deviceId: str) -> Select:
    """A device's newest completed contacts, newest first."""
    return (
        select(SyncHistory)
        .where(SyncHistory.device_id == deviceId)
        .where(SyncHistory.status == _COMPLETED)
        .where(SyncHistory.completed_at.isnot(None))
        .order_by(SyncHistory.completed_at.desc(), SyncHistory.id.desc())
        .limit(CONTACT_HISTORY_LIMIT)
    )


def contactsFromRows(rowsNewestFirst: list[SyncHistory]) -> list[ContactRecord]:
    """Turn rows (newest first) into the assessor's input (oldest first).

    ``completed_at`` is stored as naive UTC; it is made explicitly UTC here.
    """
    return [
        ContactRecord(
            contactedAt=row.completed_at.replace(tzinfo=UTC),
            residualRows=row.residual_rows,
            residualComplete=row.residual_complete,
            residualDriveRows=row.residual_drive_rows,
            residualSensorRows=row.residual_sensor_rows,
        )
        for row in reversed(rowsNewestFirst)
    ]


def deviceSyncStatus(
    deviceId: str, contacts: list[ContactRecord], *, now: datetime,
) -> DeviceSyncStatus:
    """Assess one device and render its sentence."""
    answer = assessVehicleCurrency(contacts)
    return DeviceSyncStatus(
        deviceId=deviceId,
        state=answer.state.value,
        lastContact=None if answer.asOf is None else answer.asOf.strftime(_ISO_FORMAT),
        ageSeconds=(
            None if answer.asOf is None
            else max(0, int((now - answer.asOf).total_seconds()))
        ),
        outstandingRows=answer.outstandingRows,
        exact=answer.exact,
        driveRows=answer.driveRows,
        sensorRows=answer.sensorRows,
        fault=answer.fault,
        statement=renderCurrency(answer, now=now),
    )


def readSyncStatus(
    session: Any, *, now: datetime, deviceId: str | None = None,
) -> list[DeviceSyncStatus]:
    """Every device's status (or one device's), from a synchronous session."""
    devices = [deviceId] if deviceId else list(session.execute(devicesSelect()).scalars())
    return [
        deviceSyncStatus(
            device,
            contactsFromRows(list(session.execute(contactsSelect(device)).scalars())),
            now=now,
        )
        for device in devices
    ]


async def readSyncStatusAsync(
    engine: Any, *, now: datetime, deviceId: str | None = None,
) -> list[DeviceSyncStatus]:
    """The same read over the server's async engine (the API's transport)."""
    from src.server.db.connection import getAsyncSession

    factory = getAsyncSession(engine)
    async with factory() as session:
        if deviceId:
            devices = [deviceId]
        else:
            devices = list((await session.execute(devicesSelect())).scalars())
        statuses = []
        for device in devices:
            rows = list((await session.execute(contactsSelect(device))).scalars())
            statuses.append(deviceSyncStatus(device, contactsFromRows(rows), now=now))
        return statuses
