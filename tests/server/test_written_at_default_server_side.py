################################################################################
# File Name: test_written_at_default_server_side.py
# Purpose/Description: US-809-b2, server tier -- the schema supplies the write
#                      instant, the column stays NULLABLE so history keeps an
#                      honest absence, and the capture column still refuses to
#                      be omitted.
# Author: Ralph (US-809-b2)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author            | Description
# ================================================================================
# 2026-09-24    | Ralph (US-809-b2) | Initial -- CIO resolution (A).
# ================================================================================
################################################################################
"""The write-time default on the server tier (US-809-b2).

Both tiers must agree, or the column means two different things depending on
which side you read it from -- the same hazard US-809-a's "BOTH WRITERS"
criterion exists to prevent, one layer up.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.server.db.models import Base, RealtimeData

WRITTEN_AT = "written_at"


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return eng


class TestTheSchemaSuppliesTheWriteInstant:
    def test_theModelDeclaresAServerDefault(self) -> None:
        """
        Given: the RealtimeData model
        When:  the write column is inspected
        Then:  it carries a server-side default

        Asserted on the MODEL because that is what generates the DDL on a
        fresh install, and what the migration has to agree with.
        """
        column = RealtimeData.__table__.columns[WRITTEN_AT]

        assert column.server_default is not None

    def test_anInsertOmittingItLandsAWriteTime(self, engine) -> None:
        """
        Given: an INSERT supplying only the capture instant
        When:  the row is read back
        Then:  the write instant was filled by the schema
        """
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO realtime_data "
                "(source_id, source_device, timestamp, parameter_name, value) "
                "VALUES (1, 'chi-eclipse-01', '2026-09-23 18:00:00', 'RPM', 3500.0)"
            ))

        with Session(engine) as session:
            assert session.query(RealtimeData).one().written_at is not None


class TestTheColumnStaysNullable:
    """CIO ruling 2026-09-24 -- history keeps an honest absence."""

    def test_theWriteColumnIsNullable(self) -> None:
        """
        Given: the model
        When:  the write column is inspected
        Then:  it is nullable

        NOT NULL was unsatisfiable: the Pi holds 405,536 rows whose write time
        was never recorded, and the constraint could only be met by inventing
        one for each.
        """
        assert RealtimeData.__table__.columns[WRITTEN_AT].nullable

    def test_anExplicitNullSurvivesTheSyncPath(self, engine) -> None:
        """
        Given: a synced row whose write time is explicitly unknown
        When:  it is inserted the way sync.py inserts (Core executemany)
        Then:  it reads back as NULL -- the default does NOT overwrite it

        THIS IS THE CASE THAT MATTERS, and it is the one the sync path takes.
        Every pre-column row on the car has an unknown write time; if the
        server default overwrote an explicit NULL, syncing them would stamp
        405,536 fabricated write times -- the exact defect the nullable ruling
        exists to prevent, reappearing one layer down.
        """
        from sqlalchemy import insert, select

        with engine.begin() as conn:
            conn.execute(insert(RealtimeData), [{
                "source_id": 2, "source_device": "chi-eclipse-01",
                "timestamp": datetime(2026, 4, 23, 3, 14, 40),
                "parameter_name": "RPM", "value": 3500.0,
                "written_at": None,
            }])

        with engine.connect() as conn:
            assert conn.execute(select(RealtimeData.written_at)).scalar_one() is None

    def test_anABSENTKeyFiresTheDefault_whichIsADEPLOYORDERHAZARD(
        self, engine
    ) -> None:
        """
        Given: an INSERT that does not mention the write column at all
        When:  the row is read back
        Then:  the default fired

        PINNED BECAUSE IT IS A HAZARD, not because it is desirable. MEASURED
        2026-09-24: SQLAlchemy distinguishes an EXPLICIT None (stored as NULL)
        from an ABSENT key (default fires). Both tiers deploy server-first by
        architectural decision 6, so there is a window in which the server has
        this default and the Pi has not yet been upgraded to send the column.
        Rows synced in that window get a write time equal to the moment they
        LANDED -- which is a fabrication, and indistinguishable afterwards
        from a measured one.

        The window is one deploy step and it closes when the Pi ships. It is
        recorded here so the behaviour is known rather than discovered, and so
        a deploy that leaves the Pi behind is understood to be writing
        fabricated write times for as long as it lasts.

        ALSO: the ORM path behaves like the ABSENT case even when you pass
        written_at=None explicitly -- SQLAlchemy omits the column so the
        default applies. Anything that must preserve an unknown write time
        has to go through Core, as sync.py does.
        """
        from sqlalchemy import select, text

        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO realtime_data "
                "(source_id, source_device, timestamp, parameter_name, value) "
                "VALUES (9, 'old-pi', '2026-04-23 03:14:40', 'RPM', 3500.0)"
            ))

        with engine.connect() as conn:
            landed = conn.execute(
                select(RealtimeData.written_at).where(RealtimeData.source_id == 9)
            ).scalar_one()

        assert landed is not None  # the default fired -- documented hazard


class TestTheCaptureColumnStillRefusesToBeOmitted:
    def test_theCaptureColumnIsNotNull(self) -> None:
        """
        Given: the model
        When:  the capture column is inspected
        Then:  it is NOT NULL with no default

        Unchanged by the nullable ruling, and it is the half that matters: a
        missing capture time is a code defect, not a data state.
        """
        column = RealtimeData.__table__.columns["timestamp"]

        assert not column.nullable
        assert column.server_default is None

    def test_anInsertOmittingTheCaptureTimeRaises(self, engine) -> None:
        with Session(engine) as session:
            session.add(RealtimeData(
                source_id=3, source_device="chi-eclipse-01",
                parameter_name="RPM", value=3500.0,
            ))
            with pytest.raises(IntegrityError):
                session.commit()


class TestTheMigrationMatchesTheModel:
    def test_v0030IsRegisteredAndModifiesRatherThanAdds(self) -> None:
        """
        Given: the v0030 migration
        When:  its DDL is read
        Then:  it MODIFIES the existing column rather than adding one

        v0029 created the column; adding it again would fail. And MariaDB can
        change a default in place, so unlike SQLite this needs no rebuild.
        """
        from src.server.migrations.versions.v0030_us809b2_written_at_default import (
            MIGRATION,
            SET_WRITTEN_AT_DEFAULT_DDL,
        )

        assert MIGRATION.version == "0030"
        assert "MODIFY COLUMN" in SET_WRITTEN_AT_DEFAULT_DDL
        assert "DEFAULT CURRENT_TIMESTAMP" in SET_WRITTEN_AT_DEFAULT_DDL
        assert "NOT NULL" not in SET_WRITTEN_AT_DEFAULT_DDL

    def test_theMigrationDoesNotBackfill(self) -> None:
        """
        Given: the v0030 module
        When:  it is scanned for row-touching statements
        Then:  there are none

        No UPDATE, no INSERT: a row that predates the column has no known
        write time and keeps saying so. This is the criterion the whole
        nullable ruling exists to preserve.
        """
        import ast
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "src/server/migrations/versions/v0030_us809b2_written_at_default.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))

        docstrings = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and body:
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))

        offenders = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings
            and any(v in node.value.upper() for v in ("UPDATE ", "INSERT "))
        ]

        assert not offenders, f"v0030 touches rows: {offenders}"

    def test_bothTiersAgreeOnNullability(self, engine) -> None:
        """
        Given: the server DDL generated from the model
        When:  the write column is inspected
        Then:  it is nullable, matching the Pi schema

        Both tiers must agree or the column means two different things
        depending on which side you read it from.
        """
        columns = {c["name"]: c for c in inspect(engine).get_columns("realtime_data")}

        assert columns[WRITTEN_AT]["nullable"] is True
        assert columns["timestamp"]["nullable"] is False
