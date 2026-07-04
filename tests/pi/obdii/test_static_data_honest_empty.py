################################################################################
# File Name: test_static_data_honest_empty.py
# Purpose/Description: Guards the US-456 (D-5) static_data disposition -- the
#                      table is KEPT but honest-empty on a Mode-09-silent ECU.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Ralph Agent  | Initial (US-456 static_data honest-empty guard)
# ================================================================================
################################################################################

"""
Honest-empty invariant for the ``static_data`` table (US-456 / F-082 D-5).

DISPOSITION (see ``docs/static-data-disposition.md``): the ``static_data``
table is **kept**, not dropped, but stays **honest-empty** on the current
vehicle because the ECU (MD326328) is Mode-09-silent -- the VIN is
un-gettable, and ``static_data.vin`` is a NOT NULL foreign key to
``vehicle_info(vin)``.

These tests pin the load-bearing behaviour the disposition relies on: when the
VIN query returns a null response (Mode-09-silent), the collector writes
**zero** rows -- it never fabricates a placeholder VIN. That is what makes
"honest-empty" a truthful claim rather than prose. If a future refactor makes
the collector write a synthesized/placeholder VIN row, these guards fail.

Real ``ObdDatabase`` (temp SQLite) + real INSERT path (no seam mocks on the
storage side, per I-040); only the OBD *connection* is faked, because there is
no real Mode-09-silent ECU on the dev bench.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.vehicle import StaticDataCollector

# ================================================================================
# Fakes -- a Mode-09-silent OBD connection (VIN query returns a null response)
# ================================================================================


class _NullResponse:
    """python-obd response for an unsupported/silent command."""

    value: Any = None
    unit: Any = None

    def is_null(self) -> bool:
        return True


class _SilentObd:
    """Stand-in for ``connection.obd``: every query is a null (silent) response."""

    def query(self, _cmd: Any) -> _NullResponse:
        return _NullResponse()


class _SilentConnection:
    """A connected OBD link whose ECU answers Mode 09 (VIN) with silence."""

    def __init__(self) -> None:
        self.obd = _SilentObd()

    def isConnected(self) -> bool:
        return True


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def initializedDb(tmp_path: Path) -> ObdDatabase:
    """Real temp SQLite DB with the full Pi schema (static_data + vehicle_info)."""
    db = ObdDatabase(str(tmp_path / 'test_static.db'))
    db.initialize()
    return db


@pytest.fixture
def collectorConfig() -> dict[str, Any]:
    """Config that WOULD collect static data if a VIN were gettable."""
    return {
        'pi': {
            'staticData': {
                'queryOnFirstConnection': True,
                'parameters': ['VIN', 'FUEL_TYPE'],
            }
        }
    }


def _rowCount(db: ObdDatabase, table: str) -> int:
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed literal
        return int(cursor.fetchone()[0])


# ================================================================================
# Honest-empty guards
# ================================================================================


class TestStaticDataHonestEmpty:
    """US-456: a Mode-09-silent ECU leaves static_data genuinely empty."""

    def test_collectStaticData_vinUngettable_writesZeroStaticRows(
        self, initializedDb: ObdDatabase, collectorConfig: dict[str, Any]
    ) -> None:
        """
        Given: a connected OBD link whose ECU is Mode-09-silent (null VIN)
        When: collectStaticData() runs
        Then: no static_data rows are written (no fabricated VIN placeholder)
        """
        collector = StaticDataCollector(collectorConfig, _SilentConnection(), initializedDb)

        result = collector.collectStaticData()

        # The collect refuses to proceed without a real VIN...
        assert result.success is False
        assert result.vin is None
        assert result.errorMessage is not None
        assert 'VIN' in result.errorMessage

        # ...and, critically, writes NOTHING -- honest-empty, never fabricated.
        assert _rowCount(initializedDb, 'static_data') == 0
        assert _rowCount(initializedDb, 'vehicle_info') == 0

    def test_shouldCollectStaticData_vinUngettable_returnsFalse(
        self, initializedDb: ObdDatabase, collectorConfig: dict[str, Any]
    ) -> None:
        """
        Given: a Mode-09-silent ECU
        When: shouldCollectStaticData() is asked whether to collect
        Then: it declines (no VIN -> nothing honest to collect)
        """
        collector = StaticDataCollector(collectorConfig, _SilentConnection(), initializedDb)

        assert collector.shouldCollectStaticData() is False

    def test_staticData_tableStillExists_afterDisposition(
        self, initializedDb: ObdDatabase
    ) -> None:
        """
        Given: the initialized schema
        When: we inspect the tables (disposition = KEEP, not drop)
        Then: static_data still exists (kept honest-empty, not dropped)
        """
        columns = initializedDb.getTableInfo('static_data')

        # Table is present with its VIN foreign-key column -- kept, not dropped.
        assert columns, "static_data table should still exist (disposition = keep)"
        assert any(c['name'] == 'vin' for c in columns)
