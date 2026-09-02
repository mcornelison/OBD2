################################################################################
# File Name: maintenance_seed.py
# Purpose/Description: ARCH-020 -- read the version-controlled maintenance seed
#                      and land it into maintenance_log / maintenance_schedule.
#                      IDEMPOTENT by construction: re-running the one-time load
#                      does not duplicate the record.
# Author: Atlas (Architect)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Atlas        | ARCH-020 initial -- CIO-directed build.
# ================================================================================
################################################################################

"""Load the assembled vehicle maintenance record into ``obd2db``.

The data lives in :data:`SEED_PATH` as JSON, deliberately NOT inline in this
module.  Two reasons, both learned the hard way on this project:

* A script that carries its own data gets edited to change the data, and an
  ``open(path, "w")`` that raises before writing leaves a zero-byte file.  That
  destroyed a 22,588-byte record on the share in S41; the only surviving copy was
  the one that lived in the database.
* The share holding the human-readable master has **no snapshots and no undo of
  any kind** (ext4 on RAID 5; Synology snapshots require Btrfs and none were ever
  taken).  A version-controlled copy in the repo is the second home, and the
  database is the third.

Idempotency is by natural key, not by a flag
--------------------------------------------

Rows are matched on ``(event_date, work_performed)``.  A stored "already loaded"
flag would be a claim about a previous run rather than a measurement of the
current table, and this project has catalogued five guards that went inert
exactly that way.  Asking the table what it holds cannot go stale.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.server.db.models import (
    DATE_CERTAINTY_VALUES,
    EVENT_DATE_PRECISION_VALUES,
    ODOMETER_SOURCE_VALUES,
    MaintenanceLog,
    MaintenanceSchedule,
)

__all__ = [
    'SEED_PATH',
    'SeedError',
    'loadSeedDocument',
    'loadSeedEvents',
    'loadSeedSchedule',
    'loadSeedIntoSession',
]

SEED_PATH: Path = (
    Path(__file__).resolve().parent / 'maintenance_seed_2026-09-01.json'
)

# Who the loader records as having landed these rows.  The rows are Spool's
# assembly; ARCH-020 is the mechanism that put them in the database.
RECORDED_BY: str = 'ARCH-020 seed (assembled by Spool 2026-09-01)'


class SeedError(RuntimeError):
    """The seed document is not loadable as written."""


def loadSeedDocument() -> dict[str, Any]:
    """Parse the seed JSON, or fail with a diagnosis rather than a KeyError."""
    if not SEED_PATH.exists():
        raise SeedError(
            f'maintenance seed not found at {SEED_PATH}.  This file is the '
            f'version-controlled copy of the record; without it the only copies '
            f'are the share (no undo) and the database.',
        )
    try:
        return json.loads(SEED_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:  # pragma: no cover - corrupt file
        raise SeedError(
            f'maintenance seed at {SEED_PATH} is not valid JSON: {exc}',
        ) from exc


def loadSeedEvents() -> list[dict[str, Any]]:
    """Return the event rows, validated against the column contracts.

    Validation happens HERE rather than only at the database boundary so a bad
    row is named by sequence number.  A MariaDB CHECK violation reports a
    constraint name and no row identity, which is the wrong end of the telescope
    when 47 rows go in at once.
    """
    doc = loadSeedDocument()
    events = doc.get('events')
    if not isinstance(events, list):
        raise SeedError("seed document has no 'events' list")

    for event in events:
        seq = event.get('seq', '?')
        precision = event.get('event_date_precision')
        if precision not in EVENT_DATE_PRECISION_VALUES:
            raise SeedError(
                f'event {seq}: event_date_precision={precision!r} is not one of '
                f'{EVENT_DATE_PRECISION_VALUES}.  Precision is never implied.',
            )

        certainty = event.get('event_date_certainty')
        if certainty not in DATE_CERTAINTY_VALUES:
            raise SeedError(
                f'event {seq}: event_date_certainty={certainty!r} is not one of '
                f'{DATE_CERTAINTY_VALUES}. Say whether a source RECORDED this '
                f'date or somebody ESTIMATED it.',
            )
        if precision != 'day' and certainty != 'estimated':
            raise SeedError(
                f'event {seq}: precision={precision!r} cannot be '
                f'{certainty!r}. A non-day precision stores an anchor whose '
                f'finer components were invented by this loader, so calling it '
                f'exact would assert a day no source ever gave.',
            )

        hasReading = event.get('odometer_mi') is not None
        hasSource = event.get('odometer_source') is not None
        if hasReading != hasSource:
            raise SeedError(
                f'event {seq}: an odometer reading and its source are ONE fact.  '
                f'Got odometer_mi={event.get("odometer_mi")!r} with '
                f'odometer_source={event.get("odometer_source")!r}.  There is no '
                f'odometer PID on this vehicle, so an unattributed mileage is '
                f'indistinguishable from a guess.',
            )
        if hasSource and event['odometer_source'] not in ODOMETER_SOURCE_VALUES:
            raise SeedError(
                f'event {seq}: odometer_source='
                f'{event["odometer_source"]!r} is not a known tier '
                f'{ODOMETER_SOURCE_VALUES}.',
            )

        isRange = precision == 'range'
        hasEnd = event.get('event_date_end') is not None
        if isRange != hasEnd:
            raise SeedError(
                f'event {seq}: precision={precision!r} with '
                f'event_date_end={event.get("event_date_end")!r}.  Only a range '
                f'carries an end, and a range without one is not a range -- it '
                f'is an unstated assumption.',
            )

        if not event.get('provenance'):
            raise SeedError(
                f'event {seq}: provenance is mandatory.  Every figure in this '
                f'record is human- or shop-supplied; a row that does not say '
                f'where its facts came from cannot be checked later.',
            )

    return events


def loadSeedSchedule() -> list[dict[str, Any]]:
    """Return the schedule rows from the seed document."""
    doc = loadSeedDocument()
    schedule = doc.get('schedule')
    if not isinstance(schedule, list):
        raise SeedError("seed document has no 'schedule' list")
    return schedule


def _asDate(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _existingKeys(session: Session) -> set[tuple[date, str]]:
    """Natural keys already present -- measured, never remembered."""
    rows = session.execute(
        select(MaintenanceLog.event_date, MaintenanceLog.work_performed),
    ).all()
    return {(r[0], r[1]) for r in rows}


def loadSeedIntoSession(session: Session) -> dict[str, int]:
    """Land the seed. Returns counts of what was inserted vs already present.

    Idempotent: a second call inserts nothing.  The caller owns the transaction
    boundary -- this function flushes but never commits, so the seed can be run
    inside the backup -> dry-run -> review -> commit protocol.
    """
    events = loadSeedEvents()
    schedule = loadSeedSchedule()

    present = _existingKeys(session)
    seqToRow: dict[int, MaintenanceLog] = {}
    inserted = 0

    for event in events:
        eventDate = _asDate(event['event_date'])
        key = (eventDate, event['work_performed'])
        if key in present:
            existing = session.execute(
                select(MaintenanceLog).where(
                    MaintenanceLog.event_date == eventDate,
                    MaintenanceLog.work_performed == event['work_performed'],
                ),
            ).scalars().first()
            if existing is not None:
                seqToRow[event['seq']] = existing
            continue

        row = MaintenanceLog(
            event_date=eventDate,
            event_date_precision=event['event_date_precision'],
            event_date_certainty=event['event_date_certainty'],
            event_date_end=_asDate(event.get('event_date_end')),
            odometer_mi=event.get('odometer_mi'),
            odometer_source=event.get('odometer_source'),
            work_performed=event['work_performed'],
            source_verbatim=event.get('source_verbatim'),
            dtc_code=event.get('dtc_code'),
            venue=event.get('venue'),
            document_ref=event.get('document_ref'),
            source_document_path=event.get('source_document_path'),
            parts=event.get('parts'),
            part_customer_supplied=event.get('part_customer_supplied'),
            cost_usd=event.get('cost_usd'),
            is_epoch_boundary=bool(event.get('is_epoch_boundary', False)),
            provenance=event['provenance'],
            notes=event.get('notes'),
            recorded_by=RECORDED_BY,
        )
        session.add(row)
        seqToRow[event['seq']] = row
        present.add(key)
        inserted += 1

    session.flush()

    existingItems = {
        r[0] for r in session.execute(select(MaintenanceSchedule.item)).all()
    }
    scheduled = 0
    for item in schedule:
        if item['item'] in existingItems:
            continue
        lastDoneSeq = item.get('last_done_seq')
        lastDoneRow = seqToRow.get(lastDoneSeq) if lastDoneSeq else None
        session.add(
            MaintenanceSchedule(
                item=item['item'],
                interval_miles=item.get('interval_miles'),
                interval_months=item.get('interval_months'),
                interval_engine_hours=item.get('interval_engine_hours'),
                last_done_log_id=lastDoneRow.id if lastDoneRow else None,
                last_done_confidence=item['last_done_confidence'],
                notes=item.get('notes'),
                recorded_by=RECORDED_BY,
            ),
        )
        scheduled += 1

    session.flush()
    return {
        'events_inserted': inserted,
        'events_total': len(events),
        'schedule_inserted': scheduled,
        'schedule_total': len(schedule),
    }
