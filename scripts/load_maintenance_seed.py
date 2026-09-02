#!/usr/bin/env python3
################################################################################
# File Name: load_maintenance_seed.py
# Purpose/Description: ARCH-020 -- the ONE-TIME load of the assembled vehicle
#                      maintenance record into obd2db. Dry-run by default;
#                      writing requires an explicit flag and takes a backup
#                      first.
# Author: Atlas (Architect)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Atlas        | ARCH-020 initial -- CIO-directed build; the
#               |              | backup -> dry-run -> review -> commit protocol
#               |              | is the CIO's own ruling, not a default.
# ================================================================================
################################################################################

"""Load the 48-row maintenance record into ``obd2db``. One time.

Usage::

    # 1. See exactly what would land. Writes NOTHING.
    python scripts/load_maintenance_seed.py

    # 2. Back up, then write.
    python scripts/load_maintenance_seed.py --commit

Why dry-run is the default
--------------------------

Writing is the unusual operation, so it is the one that needs the flag.  A script
whose default action mutates production is one fat-finger from an unwanted write,
and this database is the ONLY durable home the project has: the share it would
otherwise rely on was confirmed on 2026-09-01 to have no snapshots and no undo.

Idempotency is measured, not remembered
---------------------------------------

The loader matches existing rows on ``(event_date, work_performed)`` read back
from the table itself.  A stored "already seeded" flag would be a claim about a
previous run rather than a measurement of the current one -- and this project has
catalogued five guards that went inert in exactly that way.  Re-running is safe
and reports zero inserts.

⚠️ The ordinary way to add ONE event is NOT this script.  Use::

    python -m src.server.cli.maintenance add ...

This script exists to place the initial assembled record and then be finished.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli._ecu_lineage_support import resolveSyncDatabaseUrl  # noqa: E402
from src.server.data.maintenance_seed import (  # noqa: E402
    RECORDED_BY,
    SEED_PATH,
    loadSeedEvents,
    loadSeedIntoSession,
    loadSeedSchedule,
)
from src.server.db.models import (  # noqa: E402
    MaintenanceLog,
    MaintenanceSchedule,
    formatEventDate,
)

BACKUP_TABLES: tuple[str, ...] = ('maintenance_log', 'maintenance_schedule')


def _renderDryRun() -> str:
    """Print every row that WOULD land, at its real precision."""
    events = loadSeedEvents()
    schedule = loadSeedSchedule()

    lines: list[str] = [
        f'seed file : {SEED_PATH}',
        f'events    : {len(events)}',
        f'schedule  : {len(schedule)}',
        '',
        '',
        "EVENTS  ('~' before the date = ESTIMATED, not recorded by any source)",
        '------',
    ]
    for event in events:
        when = formatEventDate(
            datetime.fromisoformat(event['event_date']).date(),
            event['event_date_precision'],
            (
                datetime.fromisoformat(event['event_date_end']).date()
                if event.get('event_date_end')
                else None
            ),
        )
        odo = (
            f"{event['odometer_mi']:,} mi ({event['odometer_source']})"
            if event.get('odometer_mi') is not None
            else '-'
        )
        flag = ' [EPOCH]' if event.get('is_epoch_boundary') else ''
        # The certainty is printed on the SAME line as the date, deliberately.
        # A date shown without it reads as recorded fact, which is precisely the
        # false confidence the column was added to remove.
        mark = '~' if event['event_date_certainty'] == 'estimated' else ' '
        lines.append(
            f"{event['seq']:>3} {mark}{when:<22} {odo:<34} "
            f"{event['work_performed']}{flag}",
        )

    lines += ['', 'SCHEDULE', '--------']
    for item in schedule:
        intervals = []
        if item.get('interval_miles'):
            intervals.append(f"{item['interval_miles']:,} mi")
        if item.get('interval_months'):
            intervals.append(f"{item['interval_months']} mo")
        if item.get('interval_engine_hours'):
            intervals.append(f"{item['interval_engine_hours']} h")
        lines.append(
            f"     {item['item']:<26} every {' / '.join(intervals):<20} "
            f"last-done confidence: {item['last_done_confidence'].upper()}",
        )

    return '\n'.join(lines)


def _resolveServerHost() -> str:
    """Resolve the server host from ``deploy/addresses.sh`` -- the SSOT.

    ⚠️ This function exists instead of a default string, and the reason is
    A-15: the server address moved .10 -> .120 on 2026-06-18 and broke the running
    system because it was a literal held in three sanctioned mirrors that had to
    move together.  A fourth mirror in this script would be the same defect
    volunteering for a repeat, and the B-044 audit catches it -- correctly.  The
    lint failed on my first draft of this file, which is the guard working.

    A ``# b044-exempt`` pragma would also have made the lint pass.  It would not
    have made the address right.
    """
    from scripts.apply_server_migrations import loadAddresses

    return loadAddresses(REPO_ROOT / 'deploy' / 'addresses.sh').serverHost


def _backup(host: str) -> str:
    """mysqldump the two maintenance tables before writing.

    Narrow by design -- this load touches two tables and a whole-database dump
    would be slower and no safer.  On the FIRST run the tables are empty and the
    dump is nearly empty too; that is correct and still worth taking, because the
    run that matters is the SECOND one, when a mistake would land on real rows.
    """
    tag = datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')
    remotePath = f'/tmp/obd2-maintenance-backup-{tag}.sql'
    tables = ' '.join(BACKUP_TABLES)
    cmd = (
        f'mysqldump --single-transaction --skip-lock-tables '
        f'obd2db {tables} > {remotePath} 2>/dev/null; ls -l {remotePath}'
    )
    result = subprocess.run(
        ['ssh', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes',
         host, cmd],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f'BACKUP FAILED -- refusing to write.\n'
            f'{result.stderr.strip() or result.stdout.strip()}\n'
            f'A load with no backup is the one thing this protocol exists to '
            f'prevent.',
        )
    return f'{remotePath}  ({result.stdout.strip()})'



# ================================================================================
# The emit-SQL path
# ================================================================================
#
# The direct write path above uses create_engine(resolveSyncDatabaseUrl()), and
# that URL is '...@localhost/obd2db' -- so it works ONLY when this script runs ON
# chi-srv-01.  From a dev box it would connect to the wrong machine entirely.
#
# That made the one-time load depend on this branch being merged AND deployed
# first, which is a dependency the load does not actually have: the rows are
# static, already assembled and already validated.  Emitting SQL removes it.  The
# script travels over the SAME ssh transport apply_server_migrations.py already
# uses, and it is a reviewable artefact -- the CIO can read exactly what will run
# before any of it does.
#
# Idempotency has to live in the SQL, not in this process: once the script leaves
# this machine, nothing here controls how many times it is piped.


def _sqlLiteral(value: object) -> str:
    """Render one Python value as a MariaDB literal.

    ⚠️ Apostrophes are doubled, and this is not cosmetic.  Real rows contain
    "Peter's Highline Automotive"; an unescaped quote does not merely fail, it can
    terminate a string early and silently change what the REST of the statement
    means.
    """
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace('\\', '\\\\').replace("'", "''") + "'"


_LOG_COLUMNS: tuple[str, ...] = (
    'event_date', 'event_date_precision', 'event_date_certainty',
    'event_date_end', 'odometer_mi', 'odometer_source', 'work_performed',
    'source_verbatim', 'dtc_code', 'venue', 'document_ref',
    'source_document_path', 'parts', 'part_customer_supplied', 'cost_usd',
    'is_epoch_boundary', 'provenance', 'notes', 'recorded_by',
)


def emitSeedSql() -> str:
    """Render the whole seed as an idempotent, transactional SQL script.

    Every row is validated by ``loadSeedEvents`` before a single statement is
    rendered, so a bad row is named by sequence number here rather than arriving
    at MariaDB as a constraint name with no row identity.
    """
    events = loadSeedEvents()
    schedule = loadSeedSchedule()

    lines: list[str] = [
        '-- ARCH-020: the vehicle maintenance record.',
        '-- Generated by scripts/load_maintenance_seed.py --emit-sql.',
        '-- Idempotent: every INSERT is fenced by WHERE NOT EXISTS on the',
        '-- natural key (event_date, work_performed), so re-piping is a no-op.',
        '-- Transactional: 48 rows land together or not at all.',
        '',
        'START TRANSACTION;',
        '',
    ]

    for event in events:
        values = {
            'event_date': event['event_date'],
            'event_date_precision': event['event_date_precision'],
            'event_date_certainty': event['event_date_certainty'],
            'event_date_end': event.get('event_date_end'),
            'odometer_mi': event.get('odometer_mi'),
            'odometer_source': event.get('odometer_source'),
            'work_performed': event['work_performed'],
            'source_verbatim': event.get('source_verbatim'),
            'dtc_code': event.get('dtc_code'),
            'venue': event.get('venue'),
            'document_ref': event.get('document_ref'),
            'source_document_path': event.get('source_document_path'),
            'parts': event.get('parts'),
            'part_customer_supplied': event.get('part_customer_supplied'),
            'cost_usd': event.get('cost_usd'),
            'is_epoch_boundary': bool(event.get('is_epoch_boundary', False)),
            'provenance': event['provenance'],
            'notes': event.get('notes'),
            'recorded_by': RECORDED_BY,
        }
        rendered = ', '.join(_sqlLiteral(values[c]) for c in _LOG_COLUMNS)
        cols = ', '.join(_LOG_COLUMNS)
        lines.append(f"-- seq {event['seq']}")
        lines.append(
            f'INSERT INTO maintenance_log ({cols})\n'
            f'SELECT {rendered}\n'
            f'WHERE NOT EXISTS (SELECT 1 FROM maintenance_log '
            f"WHERE event_date = {_sqlLiteral(event['event_date'])} "
            f"AND work_performed = {_sqlLiteral(event['work_performed'])});",
        )

    lines.append('')
    for item in schedule:
        lastDoneSeq = item.get('last_done_seq')
        lastDoneSql = 'NULL'
        if lastDoneSeq:
            match = next(
                (e for e in events if e['seq'] == lastDoneSeq), None,
            )
            if match is not None:
                lastDoneSql = (
                    '(SELECT id FROM maintenance_log WHERE event_date = '
                    f"{_sqlLiteral(match['event_date'])} AND work_performed = "
                    f"{_sqlLiteral(match['work_performed'])} LIMIT 1)"
                )
        cols = (
            'item, interval_miles, interval_months, interval_engine_hours, '
            'last_done_log_id, last_done_confidence, notes, recorded_by'
        )
        rendered = ', '.join((
            _sqlLiteral(item['item']),
            _sqlLiteral(item.get('interval_miles')),
            _sqlLiteral(item.get('interval_months')),
            _sqlLiteral(item.get('interval_engine_hours')),
            lastDoneSql,
            _sqlLiteral(item['last_done_confidence']),
            _sqlLiteral(item.get('notes')),
            _sqlLiteral(RECORDED_BY),
        ))
        lines.append(
            f'INSERT INTO maintenance_schedule ({cols})\n'
            f'SELECT {rendered}\n'
            f'WHERE NOT EXISTS (SELECT 1 FROM maintenance_schedule '
            f"WHERE item = {_sqlLiteral(item['item'])});",
        )

    lines += ['', 'COMMIT;']
    return '\n'.join(lines)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='One-time load of the assembled vehicle maintenance record.',
    )
    parser.add_argument(
        '--commit', action='store_true',
        help='actually write (default is dry-run, which writes nothing)',
    )
    parser.add_argument(
        '--emit-sql', action='store_true',
        help='print an idempotent, transactional SQL script instead of '
             'connecting. Use this from a dev box: the direct path needs to run '
             'ON the server, because DATABASE_URL points at localhost.',
    )
    parser.add_argument(
        '--skip-backup', action='store_true',
        help='skip the pre-write mysqldump. Use only when a backup was just '
             'taken by hand -- the CIO approved backup-then-write as the '
             'protocol for this load.',
    )
    parser.add_argument(
        '--host', default=None,
        help='override the server host. Default resolves from '
             'deploy/addresses.sh, the address SSOT -- never a literal here.',
    )
    args = parser.parse_args(argv)

    if args.emit_sql:
        print(emitSeedSql())
        return 0

    if not args.commit:
        print(_renderDryRun())
        print()
        print('DRY RUN -- nothing was written. Re-run with --commit to load.')
        return 0

    if not args.skip_backup:
        print(f'backup: {_backup(args.host or _resolveServerHost())}')

    engine = create_engine(resolveSyncDatabaseUrl(), future=True)
    with Session(engine) as session:
        counts = loadSeedIntoSession(session)
        session.commit()

        landedEvents = len(
            session.execute(select(MaintenanceLog)).scalars().all(),
        )
        landedSchedule = len(
            session.execute(select(MaintenanceSchedule)).scalars().all(),
        )

    print(
        f"inserted {counts['events_inserted']}/{counts['events_total']} events, "
        f"{counts['schedule_inserted']}/{counts['schedule_total']} schedule rows",
    )
    print(f'maintenance_log now holds {landedEvents} rows')
    print(f'maintenance_schedule now holds {landedSchedule} rows')

    if landedEvents != counts['events_total']:
        print(
            f'WARNING: table holds {landedEvents} rows but the seed carries '
            f"{counts['events_total']}. Rows added by the add-event CLI would "
            f'explain a HIGHER count; a lower one means something did not land.',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
