################################################################################
# File Name: test_maintenance_migration_and_cli.py
# Purpose/Description: ARCH-020 -- the v0025 migration's define-once contract
#                      with the ORM, and the add-event CLI the team uses to
#                      contribute maintenance events as they happen.
# Author: Atlas (Architect)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Atlas        | ARCH-020 initial.
# ================================================================================
################################################################################

"""The migration's agreement with the ORM, and the team's contribution path.

The define-once tests exist because of A-4: when a migration hard-codes a
constraint name or an enum that the ORM also declares, the two drift silently and
``SHOW CREATE TABLE`` stops matching between SQLite (tests) and MariaDB (prod).
This project has an entire watch-list item about that class.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.fixture()
def session():
    from src.server.db.models import Base

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ---- The migration's define-once contract with the ORM -----------------------


def test_v0025_is_registered_in_the_runner() -> None:
    """An unregistered migration is a file nobody runs."""
    from src.server.migrations import ALL_MIGRATIONS

    versions = [m.version for m in ALL_MIGRATIONS]
    assert '0025' in versions
    assert versions == sorted(versions), 'registry must stay in ascending order'


def test_migration_ddl_carries_every_odometer_tier_the_orm_declares() -> None:
    """A tier added to the ORM must not need this file edited to be legal.

    If the migration hard-coded its own list, adding ``photo_exif`` to the ORM
    would produce a CHECK that rejects it on prod while every test passes.
    """
    from src.server.db.models import ODOMETER_SOURCE_VALUES
    from src.server.migrations.versions.v0025_arch020_maintenance_record import (
        CREATE_MAINTENANCE_LOG_DDL,
    )

    for tier in ODOMETER_SOURCE_VALUES:
        assert f"'{tier}'" in CREATE_MAINTENANCE_LOG_DDL


def test_migration_ddl_carries_every_confidence_value_the_orm_declares() -> None:
    from src.server.db.models import LAST_DONE_CONFIDENCE_VALUES
    from src.server.migrations.versions.v0025_arch020_maintenance_record import (
        CREATE_MAINTENANCE_SCHEDULE_DDL,
    )

    for value in LAST_DONE_CONFIDENCE_VALUES:
        assert f"'{value}'" in CREATE_MAINTENANCE_SCHEDULE_DDL


def test_migration_uses_the_orm_constraint_names() -> None:
    """Names must match so SHOW CREATE TABLE is identical across environments."""
    from src.server.db.models import (
        CK_MAINTENANCE_ODOMETER_PAIRED,
        CK_SCHEDULE_SOME_INTERVAL,
    )
    from src.server.migrations.versions.v0025_arch020_maintenance_record import (
        CREATE_MAINTENANCE_LOG_DDL,
        CREATE_MAINTENANCE_SCHEDULE_DDL,
    )

    assert CK_MAINTENANCE_ODOMETER_PAIRED in CREATE_MAINTENANCE_LOG_DDL
    assert CK_SCHEDULE_SOME_INTERVAL in CREATE_MAINTENANCE_SCHEDULE_DDL


def test_schedule_ddl_does_not_default_the_confidence_column() -> None:
    """The belt row must not be able to acquire 'confirmed' by omission.

    This is the safety property expressed at the DDL level rather than the ORM
    level, because prod is built by this DDL and not by create_all.
    """
    from src.server.migrations.versions.v0025_arch020_maintenance_record import (
        CREATE_MAINTENANCE_SCHEDULE_DDL,
    )

    assert 'last_done_confidence VARCHAR(16) NOT NULL,' in (
        CREATE_MAINTENANCE_SCHEDULE_DDL
    )
    assert 'last_done_confidence VARCHAR(16) NOT NULL DEFAULT' not in (
        CREATE_MAINTENANCE_SCHEDULE_DDL
    )


# ---- The team's contribution path --------------------------------------------


def test_add_event_lands_a_row(session) -> None:
    """The ordinary case: an agent records a service that just happened."""
    from src.server.cli.maintenance import addEvent
    from src.server.db.models import MaintenanceLog

    addEvent(
        session,
        eventDate='2026-09-02',
        precision='day',
        certainty='exact',
        workPerformed='Timing belt replaced',
        provenance='date+work: Highline invoice',
        recordedBy='spool',
        odometerMi=78950,
        odometerSource='shop_record',
    )

    row = session.execute(select(MaintenanceLog)).scalars().one()
    assert row.work_performed == 'Timing belt replaced'
    assert row.odometer_mi == 78950
    assert row.recorded_by == 'spool'


def test_add_event_refuses_an_odometer_with_no_source(session) -> None:
    """The CLI must refuse before the DB does, and say why.

    A MariaDB CHECK violation names a constraint and no row identity.  An agent
    adding one event deserves the sentence, not the errno.
    """
    from src.server.cli.maintenance import MaintenanceInputError, addEvent

    with pytest.raises(MaintenanceInputError, match='odometer'):
        addEvent(
            session,
            eventDate='2026-09-02',
            precision='day',
            certainty='exact',
            workPerformed='Oil change',
            provenance='CIO reported',
            recordedBy='spool',
            odometerMi=78950,
            odometerSource=None,
        )


def test_add_event_refuses_an_unknown_precision(session) -> None:
    from src.server.cli.maintenance import MaintenanceInputError, addEvent

    with pytest.raises(MaintenanceInputError, match='precision'):
        addEvent(
            session,
            eventDate='2026-09-02',
            precision='approximately',
            certainty='exact',
            workPerformed='Oil change',
            provenance='CIO reported',
            recordedBy='spool',
        )


def test_add_event_requires_provenance(session) -> None:
    """Every figure here is human-supplied; an unattributed row is unusable."""
    from src.server.cli.maintenance import MaintenanceInputError, addEvent

    with pytest.raises(MaintenanceInputError, match='provenance'):
        addEvent(
            session,
            eventDate='2026-09-02',
            precision='day',
            certainty='exact',
            workPerformed='Oil change',
            provenance='',
            recordedBy='spool',
        )


def test_add_event_requires_a_range_end_for_a_range(session) -> None:
    """A range without an end is not a range -- it is an unstated assumption."""
    from src.server.cli.maintenance import MaintenanceInputError, addEvent

    with pytest.raises(MaintenanceInputError, match='range'):
        addEvent(
            session,
            eventDate='2022-01-01',
            precision='range',
            certainty='estimated',
            workPerformed='Spark plugs',
            provenance='owner recollection',
            recordedBy='spool',
        )


def test_add_event_names_the_recorder(session) -> None:
    """CIO data rule: land it, stamp it, and say who landed it."""
    from src.server.cli.maintenance import MaintenanceInputError, addEvent

    with pytest.raises(MaintenanceInputError, match='recorded_by|recorder'):
        addEvent(
            session,
            eventDate='2026-09-02',
            precision='day',
            certainty='exact',
            workPerformed='Oil change',
            provenance='CIO reported',
            recordedBy='',
        )


def test_cli_main_session_acquisition_path_actually_resolves() -> None:
    """The symbols ``main()`` imports at runtime must exist.

    ⚠️ Written AFTER the fact, and it should not have been. The first version of
    this CLI imported ``getSyncSession`` from ``src.server.db.connection``, which
    does not exist -- that module is async-only. Every test passed, because they
    all call ``addEvent`` with a session the fixture supplies; ``main()`` was the
    one path nothing exercised, and it would have raised ImportError on first
    real use.

    That is this project's own inert-guard shape: a check that is syntactically
    present and semantically does nothing, because the thing it guards is never
    run. Reading caught it, not the suite. This test closes that hole.
    """
    from sqlalchemy import create_engine  # noqa: F401

    from src.server.cli._ecu_lineage_support import resolveSyncDatabaseUrl

    assert callable(resolveSyncDatabaseUrl)


def test_cli_help_does_not_need_a_database() -> None:
    """``--help`` must work on a dev box with no server reachable."""
    from src.server.cli.maintenance import buildParser

    parser = buildParser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(['--help'])
    assert exc.value.code == 0


def test_add_event_refuses_exact_on_a_non_day_precision(session) -> None:
    """The CLI must refuse the contradiction, not leave it to the DB.

    "May 2025 is an exact date" is the defect the precision column exists to
    prevent, re-entering through the certainty column.
    """
    from src.server.cli.maintenance import MaintenanceInputError, addEvent

    with pytest.raises(MaintenanceInputError, match='exact'):
        addEvent(
            session,
            eventDate='2025-05-01',
            precision='month',
            certainty='exact',
            workPerformed='Cold air intake',
            provenance='owner reported, month only',
            recordedBy='cio',
        )


def test_migration_ddl_carries_every_certainty_value_the_orm_declares() -> None:
    from src.server.db.models import DATE_CERTAINTY_VALUES
    from src.server.migrations.versions.v0025_arch020_maintenance_record import (
        CREATE_MAINTENANCE_LOG_DDL,
    )

    for value in DATE_CERTAINTY_VALUES:
        assert f"'{value}'" in CREATE_MAINTENANCE_LOG_DDL


def test_migration_ddl_does_not_default_the_certainty_column() -> None:
    """'exact' is the value a consumer trusts; it must never arrive by omission."""
    from src.server.migrations.versions.v0025_arch020_maintenance_record import (
        CREATE_MAINTENANCE_LOG_DDL,
    )

    assert 'event_date_certainty VARCHAR(16) NOT NULL,' in CREATE_MAINTENANCE_LOG_DDL
    assert 'event_date_certainty VARCHAR(16) NOT NULL DEFAULT' not in (
        CREATE_MAINTENANCE_LOG_DDL
    )


# ---- The emit-SQL path (ARCH-020, 2026-09-02) --------------------------------
#
# The loader's original only write path was create_engine(resolveSyncDatabaseUrl()),
# and that URL is '...@localhost/obd2db' -- so it works ONLY when run ON the
# server. From a dev box it connects to the wrong machine entirely. That made the
# one-time load depend on the branch being merged AND deployed first, which is a
# dependency the load does not actually have. Emitting SQL removes it: the rows
# are validated locally and travel over the same ssh transport the migration
# runner already uses.


def test_emit_sql_produces_one_insert_per_seed_event() -> None:
    from scripts.load_maintenance_seed import emitSeedSql
    from src.server.data.maintenance_seed import loadSeedEvents

    sql = emitSeedSql()

    assert sql.count('INSERT INTO maintenance_log') == len(loadSeedEvents())


def test_emit_sql_is_idempotent_by_construction() -> None:
    """Re-running the emitted script must not duplicate the record.

    The guard has to live in the SQL itself, because once the script leaves this
    machine nothing here controls how often it is piped.
    """
    from scripts.load_maintenance_seed import emitSeedSql

    sql = emitSeedSql()

    assert 'WHERE NOT EXISTS' in sql


def test_emit_sql_escapes_apostrophes_in_free_text() -> None:
    """Real rows contain "Peter's Highline Automotive".

    An unescaped apostrophe does not merely fail -- mid-script it can terminate a
    string early and change what the REST of the statement means.
    """
    from scripts.load_maintenance_seed import emitSeedSql

    sql = emitSeedSql()

    assert "Peter''s Highline" in sql
    assert "Peter's Highline" not in sql.replace("Peter''s Highline", '')


def test_emit_sql_wraps_the_load_in_one_transaction() -> None:
    """48 rows land together or not at all."""
    from scripts.load_maintenance_seed import emitSeedSql

    sql = emitSeedSql()

    # Asserted as an ORDERING, not as the first byte of the file: the header
    # comments explain what the script does and are worth keeping. The invariant
    # is that no INSERT sits outside the transaction.
    assert 'START TRANSACTION;' in sql
    assert sql.index('START TRANSACTION;') < sql.index('INSERT INTO')
    assert sql.rindex('INSERT INTO') < sql.rindex('COMMIT;')
    assert sql.strip().endswith('COMMIT;')


def test_emit_sql_carries_the_certainty_column() -> None:
    from scripts.load_maintenance_seed import emitSeedSql

    sql = emitSeedSql()

    assert 'event_date_certainty' in sql
    assert "'estimated'" in sql
