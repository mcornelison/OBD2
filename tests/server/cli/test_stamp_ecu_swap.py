################################################################################
# File Name: test_stamp_ecu_swap.py
# Purpose/Description: Sprint 43 V0.28.0 (US-366 / F-108) -- tests for the
#                      stamp_ecu_swap server CLI.  The CLI atomically CLOSES the
#                      currently-active vehicle_info row (sets
#                      ecu_removal_timestamp_utc) and OPENS a new row, honouring
#                      the append-only ECU-lineage invariant landed in US-365.
#                      Covers: clean swap (close+open in one transaction);
#                      idempotent re-run (same signature + as-of -> no-op);
#                      same-signature-different-as-of refusal (no silent
#                      timestamp rewrite); bootstrap graceful error (no active
#                      row); pre-migration graceful error (no ECU columns);
#                      identity-immutability refusal (--update-existing-signature).
#                      Real in-memory-file SQLite + real ORM, no mocks (post-I-040
#                      discipline); only the DB-URL resolver is redirected.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-366) | Initial -- stamp_ecu_swap writer-path CLI tests.
# ================================================================================
################################################################################

"""US-366 / F-108 tests: stamp_ecu_swap close-prior + open-new writer CLI."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli import stamp_ecu_swap as cli  # noqa: E402
from src.server.db.models import Base, VehicleInfo  # noqa: E402

_PRIOR_INSTALL = datetime(2026, 5, 22, 14, 0, 0)


@pytest.fixture
def dbPath():
    """Temp-file SQLite path carrying the full server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    eng.dispose()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


def _seedActive(dbPath: str, *, signature: str, install: datetime) -> None:
    """Seed exactly one currently-active vehicle_info row."""
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        session.add(
            VehicleInfo(
                source_id=1,
                source_device="chi-eclipse-01",
                vin="4A3AK34T0XE000000",
                ecu_signature=signature,
                ecu_install_timestamp_utc=install,
                ecu_removal_timestamp_utc=None,
            )
        )
        session.commit()
    eng.dispose()


def _runCli(monkeypatch, dbPath: str, argv: list[str]) -> int:
    monkeypatch.setattr(
        cli, "resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
    )
    return cli.main(argv)


def _rows(dbPath: str) -> list[VehicleInfo]:
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        rows = (
            session.query(VehicleInfo)
            .order_by(VehicleInfo.ecu_install_timestamp_utc)
            .all()
        )
        session.expunge_all()
    eng.dispose()
    return rows


# =========================================================================
# Clean swap (AC#1, V-1, V-7) + atomicity (AC#4, V-5)
# =========================================================================


def test_cleanSwap_closesPriorAndOpensNew(monkeypatch, dbPath):
    """V-1: close active row at --as-of, open new active row."""
    _seedActive(dbPath, signature="old-ECU", install=_PRIOR_INSTALL)

    rc = _runCli(
        monkeypatch, dbPath,
        [
            "--signature", "new-test-ECU",
            "--cal-signature", "tune-v1",
            "--as-of", "2026-06-01T12:00:00Z",
        ],
    )

    assert rc == 0
    rows = _rows(dbPath)
    assert len(rows) == 2
    prior = next(r for r in rows if r.ecu_signature == "old-ECU")
    fresh = next(r for r in rows if r.ecu_signature == "new-test-ECU")
    # Prior row closed at the as-of instant.
    assert prior.ecu_removal_timestamp_utc == datetime(2026, 6, 1, 12, 0, 0)
    # New row is the sole currently-active row.
    assert fresh.ecu_removal_timestamp_utc is None
    assert fresh.cal_signature == "tune-v1"
    assert fresh.ecu_install_timestamp_utc == datetime(2026, 6, 1, 12, 0, 0)


def test_cleanSwap_exactlyOneActiveAfter(monkeypatch, dbPath):
    """After a swap exactly one row is currently-active (invariant holds)."""
    _seedActive(dbPath, signature="old-ECU", install=_PRIOR_INSTALL)

    rc = _runCli(
        monkeypatch, dbPath,
        ["--signature", "new-ECU", "--as-of", "2026-06-01T12:00:00Z"],
    )

    assert rc == 0
    active = [r for r in _rows(dbPath) if r.ecu_removal_timestamp_utc is None]
    assert len(active) == 1
    assert active[0].ecu_signature == "new-ECU"


# =========================================================================
# Idempotency (AC#3, V-2, V-9)
# =========================================================================


def test_idempotentReRun_sameSignatureSameAsOf_noOp(
    monkeypatch, dbPath, caplog,
):
    """V-2/V-9: re-running with identical signature + as-of is a no-op."""
    _seedActive(dbPath, signature="old-ECU", install=_PRIOR_INSTALL)
    # First swap.
    _runCli(
        monkeypatch, dbPath,
        ["--signature", "new-ECU", "--as-of", "2026-06-01T12:00:00Z"],
    )
    before = _rows(dbPath)

    with caplog.at_level(logging.INFO):
        rc = _runCli(
            monkeypatch, dbPath,
            ["--signature", "new-ECU", "--as-of", "2026-06-01T12:00:00Z"],
        )

    assert rc == 0
    assert "no-op" in caplog.text.lower() or "already stamped" in caplog.text.lower()
    after = _rows(dbPath)
    # No duplicate row; state unchanged.
    assert len(after) == len(before) == 2


# =========================================================================
# Same-signature-different-as-of refusal (V-3, conditionalOutcome 2)
# =========================================================================


def test_sameSignatureDifferentAsOf_refusesAndLeavesStateUnchanged(
    monkeypatch, dbPath, caplog,
):
    """V-3: identical signature but different as-of -> error, no rewrite."""
    _seedActive(dbPath, signature="old-ECU", install=_PRIOR_INSTALL)
    _runCli(
        monkeypatch, dbPath,
        ["--signature", "new-ECU", "--as-of", "2026-06-01T12:00:00Z"],
    )
    before = _rows(dbPath)

    with caplog.at_level(logging.ERROR):
        rc = _runCli(
            monkeypatch, dbPath,
            ["--signature", "new-ECU", "--as-of", "2026-07-01T09:00:00Z"],
        )

    assert rc != 0
    after = _rows(dbPath)
    # The active row's install timestamp was NOT silently rewritten.
    active = next(r for r in after if r.ecu_removal_timestamp_utc is None)
    assert active.ecu_install_timestamp_utc == datetime(2026, 6, 1, 12, 0, 0)
    assert len(after) == len(before)


# =========================================================================
# Bootstrap graceful error -- no currently-active row (AC#5)
# =========================================================================


def test_bootstrap_noActiveRow_gracefulError(monkeypatch, dbPath, caplog):
    """No currently-active row -> graceful error (US-367 bootstrap script)."""
    with caplog.at_level(logging.ERROR):
        rc = _runCli(
            monkeypatch, dbPath,
            ["--signature", "first-ECU", "--as-of", "2026-05-22T14:00:00Z"],
        )

    assert rc != 0
    assert "currently-active" in caplog.text.lower()
    # Nothing inserted.
    assert _rows(dbPath) == []


# =========================================================================
# Pre-migration graceful error -- vehicle_info has no ECU columns (AC#5)
# =========================================================================


def test_preMigration_noEcuColumns_gracefulError(monkeypatch, caplog):
    """A pre-v0010 vehicle_info (no ECU columns) -> graceful error, no crash."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    with eng.begin() as conn:
        # Legacy shape: VIN columns only, no ECU lineage columns.
        conn.execute(
            text(
                "CREATE TABLE vehicle_info ("
                "id INTEGER PRIMARY KEY, source_id INTEGER, "
                "source_device TEXT, vin TEXT)"
            )
        )
    eng.dispose()

    try:
        with caplog.at_level(logging.ERROR):
            rc = _runCli(
                monkeypatch, tmp.name,
                ["--signature", "x", "--as-of", "2026-06-01T12:00:00Z"],
            )
        assert rc != 0
        assert "migration" in caplog.text.lower()
    finally:
        Path(tmp.name).unlink(missing_ok=True)


# =========================================================================
# Identity-immutability refusal (AC#7, V-8) -- the US-365 AC#9 deferral
# =========================================================================


def test_updateExistingSignatureFlag_refusedWithDocumentedError(
    monkeypatch, dbPath, caplog,
):
    """V-8: --update-existing-signature is refused; identity is append-only."""
    _seedActive(dbPath, signature="old-ECU", install=_PRIOR_INSTALL)

    with caplog.at_level(logging.ERROR):
        rc = _runCli(
            monkeypatch, dbPath,
            [
                "--signature", "rewritten-ECU",
                "--as-of", "2026-06-01T12:00:00Z",
                "--update-existing-signature",
            ],
        )

    assert rc != 0
    assert "append-only" in caplog.text.lower()
    # The identity row is unchanged (no in-place rewrite, no new row).
    rows = _rows(dbPath)
    assert len(rows) == 1
    assert rows[0].ecu_signature == "old-ECU"
    assert rows[0].ecu_removal_timestamp_utc is None


# =========================================================================
# Bad --as-of value -> graceful error
# =========================================================================


def test_unparseableAsOf_gracefulError(monkeypatch, dbPath, caplog):
    """A non-ISO --as-of value errors gracefully (no traceback / no write)."""
    _seedActive(dbPath, signature="old-ECU", install=_PRIOR_INSTALL)

    with caplog.at_level(logging.ERROR):
        rc = _runCli(
            monkeypatch, dbPath,
            ["--signature", "new-ECU", "--as-of", "not-a-timestamp"],
        )

    assert rc != 0
    assert len(_rows(dbPath)) == 1
