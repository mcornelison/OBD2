################################################################################
# File Name: maintenance.py
# Purpose/Description: ARCH-020 -- the team's contribution path. Any agent (or
#                      the CIO) records a maintenance event as it happens,
#                      without hand-writing SQL and without being able to land
#                      an unattributed figure.
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

"""Add a maintenance event to ``obd2db``.

Usage::

    python -m src.server.cli.maintenance add \\
        --date 2026-09-02 --precision day \\
        --work "Timing belt replaced" \\
        --odometer 78950 --odometer-source shop_record \\
        --venue "Peter's Highline Automotive" --document-ref 84xxx \\
        --provenance "date+odometer+work: Highline invoice (exact tier)" \\
        --recorded-by spool

    python -m src.server.cli.maintenance list
    python -m src.server.cli.maintenance due

Why the validation is here and not only in the database
-------------------------------------------------------

A MariaDB CHECK violation reports a constraint name and no row identity.  An
agent adding one event deserves a sentence explaining which rule it broke and
why the rule exists -- the errno names the symptom and hides the cause.  The
database constraints stay as the backstop; these are the diagnosis.

Every refusal below is a refusal to record something the record cannot support:
an odometer with no stated origin, a precision nobody chose, a range with no end,
a row nobody signed.  None of them are style checks.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.server.db.models import (
    DATE_CERTAINTY_ESTIMATED,
    DATE_CERTAINTY_VALUES,
    EVENT_DATE_PRECISION_DAY,
    EVENT_DATE_PRECISION_RANGE,
    EVENT_DATE_PRECISION_VALUES,
    ODOMETER_SOURCE_VALUES,
    MaintenanceLog,
    MaintenanceSchedule,
    formatEventDate,
)

__all__ = [
    'MaintenanceInputError',
    'addEvent',
    'buildParser',
    'main',
]


class MaintenanceInputError(ValueError):
    """An event as described cannot be honestly recorded."""


def addEvent(
    session: Session,
    *,
    eventDate: str,
    precision: str,
    certainty: str,
    workPerformed: str,
    provenance: str,
    recordedBy: str,
    eventDateEnd: str | None = None,
    odometerMi: int | None = None,
    odometerSource: str | None = None,
    sourceVerbatim: str | None = None,
    dtcCode: str | None = None,
    venue: str | None = None,
    documentRef: str | None = None,
    sourceDocumentPath: str | None = None,
    parts: str | None = None,
    partCustomerSupplied: bool | None = None,
    costUsd: float | None = None,
    isEpochBoundary: bool = False,
    notes: str | None = None,
) -> MaintenanceLog:
    """Validate and land one maintenance event. Flushes; does not commit."""
    if precision not in EVENT_DATE_PRECISION_VALUES:
        raise MaintenanceInputError(
            f'precision {precision!r} is not one of {EVENT_DATE_PRECISION_VALUES}. '
            f"Precision is never implied: this record holds exact days, a bare "
            f"month ('May 2025') and a four-year window, and storing a month as a "
            f'day would state something no source recorded.',
        )

    if certainty not in DATE_CERTAINTY_VALUES:
        raise MaintenanceInputError(
            f'certainty {certainty!r} is not one of {DATE_CERTAINTY_VALUES}. '
            f'Say whether a source RECORDED this date or somebody ESTIMATED it '
            f'-- that is a different question from how precise it is.',
        )
    if precision != EVENT_DATE_PRECISION_DAY and certainty != DATE_CERTAINTY_ESTIMATED:
        raise MaintenanceInputError(
            f'a {precision!r} precision cannot be {certainty!r}. The stored date '
            f"anchor's finer components are invented by this tool, so marking it "
            f'exact would assert a day no source gave you. (A DAY precision MAY '
            f'be estimated -- that is a confident recollection, and it stays '
            f'distinguishable from a dealer record.)',
        )

    hasReading = odometerMi is not None
    hasSource = odometerSource is not None
    if hasReading != hasSource:
        raise MaintenanceInputError(
            'an odometer reading and its source are ONE fact -- supply both or '
            'neither. There is no odometer PID on this vehicle; every figure is '
            'operator- or shop-supplied, so an unattributed mileage cannot be '
            f'told apart from a guess. Tiers: {ODOMETER_SOURCE_VALUES}',
        )
    if hasSource and odometerSource not in ODOMETER_SOURCE_VALUES:
        raise MaintenanceInputError(
            f'odometer source {odometerSource!r} is not a known tier '
            f'{ODOMETER_SOURCE_VALUES}. The tier is load-bearing: state-agency '
            f'readings are rounded to the nearest 1,000 and that rounding '
            f'manufactures an apparent odometer rollback in this history.',
        )

    isRange = precision == EVENT_DATE_PRECISION_RANGE
    hasEnd = bool(eventDateEnd)
    if isRange and not hasEnd:
        raise MaintenanceInputError(
            'a range precision needs an end date. A range without one is not a '
            'range, it is an unstated assumption.',
        )
    if hasEnd and not isRange:
        raise MaintenanceInputError(
            "an end date is only meaningful with precision 'range'.",
        )

    if not (provenance or '').strip():
        raise MaintenanceInputError(
            'provenance is mandatory, and it is per FIELD not per row. Say where '
            'each fact came from -- e.g. "odometer: CIO-declared fact; oil brand: '
            'recollection; viscosity: absent". A row that does not say where its '
            'facts came from cannot be checked later, and this record has already '
            'had one claim corrected precisely because it said which part rested '
            'on recollection.',
        )

    if not (recordedBy or '').strip():
        raise MaintenanceInputError(
            'recorded_by is mandatory -- name who is landing this row. CIO data '
            'rule 2026-08-29: land it, stamp it, and put it on the server.',
        )

    if not (workPerformed or '').strip():
        raise MaintenanceInputError('work_performed is mandatory.')

    row = MaintenanceLog(
        event_date=date.fromisoformat(eventDate),
        event_date_precision=precision,
        event_date_certainty=certainty,
        event_date_end=date.fromisoformat(eventDateEnd) if eventDateEnd else None,
        odometer_mi=odometerMi,
        odometer_source=odometerSource,
        work_performed=workPerformed,
        source_verbatim=sourceVerbatim,
        dtc_code=dtcCode,
        venue=venue,
        document_ref=documentRef,
        source_document_path=sourceDocumentPath,
        parts=parts,
        part_customer_supplied=partCustomerSupplied,
        cost_usd=costUsd,
        is_epoch_boundary=isEpochBoundary,
        provenance=provenance,
        notes=notes,
        recorded_by=recordedBy,
    )
    session.add(row)
    session.flush()
    return row


def renderLog(session: Session) -> str:
    """The record, newest last, at the precision each row actually has."""
    rows = session.execute(
        select(MaintenanceLog).order_by(MaintenanceLog.event_date),
    ).scalars().all()

    lines = []
    for row in rows:
        when = formatEventDate(
            row.event_date, row.event_date_precision, row.event_date_end,
        )
        odo = (
            f'{row.odometer_mi:,} mi ({row.odometer_source})'
            if row.odometer_mi is not None
            else '-'
        )
        lines.append(f'{when:<24} {odo:<32} {row.work_performed}')
    return '\n'.join(lines)


def renderDue(session: Session) -> str:
    """What is due, with the confidence of each last-done attached.

    The confidence is printed on the SAME line as the date deliberately.  A due
    report that shows "timing belt -- last done 2008-05-08" without the word
    ``inferred`` beside it is the exact false-confidence this table was built to
    prevent.
    """
    rows = session.execute(
        select(MaintenanceSchedule).order_by(MaintenanceSchedule.item),
    ).scalars().all()

    lines = []
    for row in rows:
        intervals = []
        if row.interval_miles:
            intervals.append(f'{row.interval_miles:,} mi')
        if row.interval_months:
            intervals.append(f'{row.interval_months} mo')
        if row.interval_engine_hours:
            intervals.append(f'{row.interval_engine_hours} h')

        lastDone = '-'
        if row.last_done_log_id is not None:
            log = session.get(MaintenanceLog, row.last_done_log_id)
            if log is not None:
                lastDone = formatEventDate(
                    log.event_date, log.event_date_precision, log.event_date_end,
                )
        lines.append(
            f'{row.item:<26} every {" / ".join(intervals):<20} '
            f'last: {lastDone:<14} [{row.last_done_confidence.upper()}]',
        )
    return '\n'.join(lines)


def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python -m src.server.cli.maintenance',
        description='Record and read the vehicle maintenance history.',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    add = sub.add_parser('add', help='record one maintenance event')
    add.add_argument('--date', required=True, help='ISO date, or the range start')
    add.add_argument(
        '--precision', required=True, choices=list(EVENT_DATE_PRECISION_VALUES),
        help='how precisely the SOURCE knows this date -- never guess upward',
    )
    add.add_argument(
        '--certainty', required=True, choices=list(DATE_CERTAINTY_VALUES),
        help='did a SOURCE record this date (exact) or did someone ESTIMATE it '
             '(estimated)? Orthogonal to --precision: a recalled specific day is '
             'day precision AND estimated.',
    )
    add.add_argument('--date-end', help="range end (only with --precision range)")
    add.add_argument('--work', required=True, help='what was done (normalised)')
    add.add_argument(
        '--verbatim',
        help="the source document's EXACT wording, if it differs from --work",
    )
    add.add_argument('--odometer', type=int)
    add.add_argument('--odometer-source', choices=list(ODOMETER_SOURCE_VALUES))
    add.add_argument('--dtc')
    add.add_argument('--venue')
    add.add_argument('--document-ref', help='invoice or repair-order number')
    add.add_argument('--document-path', help='path to the primary document')
    add.add_argument('--parts')
    add.add_argument('--customer-supplied', action='store_true', default=None)
    add.add_argument('--cost', type=float)
    add.add_argument(
        '--epoch-boundary', action='store_true',
        help='this event invalidates before/after comparison (oil, O2, '
             'reflash, battery disconnect)',
    )
    add.add_argument(
        '--provenance', required=True,
        help='PER FIELD: where each fact came from',
    )
    add.add_argument('--notes')
    add.add_argument('--recorded-by', required=True, help='who is landing this')

    sub.add_parser('list', help='print the whole record')
    sub.add_parser('due', help='print the schedule with last-done confidence')

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Commits on success -- the CLI owns one event's transaction."""
    args = buildParser().parse_args(argv)

    # Same acquisition path as add_ecu_note / backfill_ecu_lineage / compare_drives.
    # Imported locally so `--help` works without a reachable database.
    from sqlalchemy import create_engine

    from src.server.cli._ecu_lineage_support import resolveSyncDatabaseUrl

    engine = create_engine(resolveSyncDatabaseUrl(), future=True)
    with Session(engine) as session:
        if args.command == 'add':
            try:
                row = addEvent(
                    session,
                    eventDate=args.date,
                    precision=args.precision,
                    certainty=args.certainty,
                    eventDateEnd=args.date_end,
                    workPerformed=args.work,
                    sourceVerbatim=args.verbatim,
                    odometerMi=args.odometer,
                    odometerSource=args.odometer_source,
                    dtcCode=args.dtc,
                    venue=args.venue,
                    documentRef=args.document_ref,
                    sourceDocumentPath=args.document_path,
                    parts=args.parts,
                    partCustomerSupplied=args.customer_supplied,
                    costUsd=args.cost,
                    isEpochBoundary=args.epoch_boundary,
                    provenance=args.provenance,
                    notes=args.notes,
                    recordedBy=args.recorded_by,
                )
            except MaintenanceInputError as exc:
                print(f'REFUSED: {exc}', file=sys.stderr)
                return 2
            session.commit()
            print(f'recorded maintenance_log id={row.id}')
            return 0

        if args.command == 'list':
            print(renderLog(session))
            return 0

        print(renderDue(session))
        return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
