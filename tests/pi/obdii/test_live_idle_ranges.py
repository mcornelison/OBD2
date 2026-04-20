################################################################################
# File Name: test_live_idle_ranges.py
# Purpose/Description: Range-check assertions against the Session 23 Eclipse
#                      idle fixture (US-197).  Asserts the 149 real-capture
#                      rows stay inside Spool-approved tolerance bands so
#                      future regenerations of the fixture (or any accidental
#                      tampering with the committed .db) surface immediately.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex (US-197) | Initial -- range-check asserts + fixture sanity
# ================================================================================
################################################################################

"""Range-check regression for the Session 23 Eclipse idle fixture.

The fixture lives at ``data/regression/pi-inputs/eclipse_idle.db`` and
holds the 149 realtime_data rows captured during the 2026-04-19 warm-idle
drill.  These tests protect against silent corruption of the fixture
(e.g. a future schema migration reshuffles columns; someone edits values
by hand) by reasserting Spool-approved warm-idle ranges on every CI run.

Tolerance bands come from Spool's first-drive review + Session 24
grounded-knowledge entries:

* RPM: 700-900 warm idle (observed 761-852)
* Coolant: 70-80 C warm (observed 73-74; conservative band so
  future drills with a fully-warm engine don't break the test)
* LTFT: +/-1% (observed 0.00 flat; +/-1% gives tolerance for ECU noise)
* STFT: +/-3% (observed -0.78 to +1.56; Spool tolerance band)
* O2 B1S1: must demonstrate switching -- min<=0.1, max>=0.5 in the window
* Timing advance: 0-20 deg BTDC (observed 5-9; wider band because
  community norm is 10-15 and we don't want to break if the baseline
  shifts with a future ECMLink tune)
* MAF: 1-10 g/s (observed 3.49-3.68; band covers warm idle across
  different ambient temps)

Invariants honoured:
* Do NOT over-assert.  Use Spool's tolerance bands, not hard equality.
* Do NOT modify the fixture -- tests read via a sqlite3 connection
  opened in immutable mode where possible, plain SELECT otherwise.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / 'data' / 'regression' / 'pi-inputs' / 'eclipse_idle.db'
METADATA_PATH = REPO_ROOT / 'data' / 'regression' / 'pi-inputs' / 'eclipse_idle.metadata.json'

# Spool-approved tolerance bands for this specific car at warm idle.
# (minInclusive, maxInclusive) for simple min/max bounds; special cases
# documented inline.
RANGE_BANDS: dict[str, tuple[float, float]] = {
    'RPM': (700.0, 900.0),
    'COOLANT_TEMP': (70.0, 80.0),
    'LONG_FUEL_TRIM_1': (-1.0, 1.0),
    'SHORT_FUEL_TRIM_1': (-3.0, 3.0),
    'TIMING_ADVANCE': (0.0, 20.0),
    'MAF': (1.0, 10.0),
    'THROTTLE_POS': (0.0, 5.0),
    'ENGINE_LOAD': (10.0, 35.0),
    'INTAKE_TEMP': (0.0, 40.0),
    'SPEED': (0.0, 1.0),
}

# Parameters the fixture must contain (subset of the 11 Session 23 PIDs).
EXPECTED_PARAMETERS: frozenset[str] = frozenset({
    'COOLANT_TEMP',
    'ENGINE_LOAD',
    'INTAKE_TEMP',
    'LONG_FUEL_TRIM_1',
    'MAF',
    'O2_B1S1',
    'RPM',
    'SHORT_FUEL_TRIM_1',
    'SPEED',
    'THROTTLE_POS',
    'TIMING_ADVANCE',
})

# Fixture provenance invariants.
EXPECTED_ROW_COUNT: int = 149
EXPECTED_DATA_SOURCE: str = 'real'


@pytest.fixture(scope='module')
def fixtureConn() -> sqlite3.Connection:
    """Open the committed fixture read-only for per-test querying.

    Yields a plain sqlite3.Connection opened read-only via URI.  Uses the
    triple-slash ``file:///`` prefix so a Windows drive letter (``Z:``) is
    not mistakenly parsed as a URI authority.
    """
    if not FIXTURE_PATH.exists():
        pytest.fail(
            f'Missing Session 23 fixture: {FIXTURE_PATH}\n'
            'Run scripts/export_regression_fixture.sh to regenerate from Pi.'
        )
    posix = FIXTURE_PATH.as_posix()
    if not posix.startswith('/'):
        # Windows absolute path: Z:/o/OBD2v2/... -- prefix a slash so the
        # URI becomes file:///Z:/... (empty authority).  Without this the
        # URI parser treats "Z:" as authority and rejects it.
        posix = '/' + posix
    uri = f'file://{posix}?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    yield conn
    conn.close()


class TestFixturePresence:
    """Fixture file + companion metadata exist and are well-formed."""

    def test_fixtureFile_exists(self) -> None:
        assert FIXTURE_PATH.exists(), f'Missing fixture: {FIXTURE_PATH}'

    def test_fixtureFile_reasonableSize(self) -> None:
        # 149 rows across 11 params + indices + schema -> ~100-300 KB.
        # Guard against balloon (>500 KB) per Invariant #6 and against
        # empty / zero-byte regression.
        size = FIXTURE_PATH.stat().st_size
        assert 50_000 < size < 500_000, f'Fixture size anomaly: {size} bytes'

    def test_metadataFile_exists(self) -> None:
        assert METADATA_PATH.exists(), f'Missing metadata: {METADATA_PATH}'

    def test_metadataFile_parsesAsJson(self) -> None:
        import json
        with METADATA_PATH.open() as handle:
            meta = json.load(handle)
        assert isinstance(meta, dict)

    def test_metadataFile_hasRequiredFields(self) -> None:
        import json
        with METADATA_PATH.open() as handle:
            meta = json.load(handle)
        required = {
            'fixture_name',
            'captured_date',
            'vehicle',
            'pids_captured',
            'sampling_rate_per_sec',
            'data_source',
            'row_count',
            'tune_context',
            'source_drill',
        }
        missing = required - set(meta.keys())
        assert not missing, f'metadata missing required fields: {missing}'

    def test_metadataFile_pidsCapturedMatchesExpected(self) -> None:
        import json
        with METADATA_PATH.open() as handle:
            meta = json.load(handle)
        pidsInMeta = set(meta['pids_captured'])
        assert pidsInMeta == set(EXPECTED_PARAMETERS), (
            f'PID set drift: {pidsInMeta.symmetric_difference(EXPECTED_PARAMETERS)}'
        )

    def test_metadataFile_rowCountMatches(self) -> None:
        import json
        with METADATA_PATH.open() as handle:
            meta = json.load(handle)
        assert meta['row_count'] == EXPECTED_ROW_COUNT


class TestFixtureProvenance:
    """Schema + row-count + tagging invariants from the capture."""

    def test_realtimeData_rowCount_matchesSession23(
        self, fixtureConn: sqlite3.Connection,
    ) -> None:
        row = fixtureConn.execute(
            'SELECT COUNT(*) FROM realtime_data'
        ).fetchone()
        assert row[0] == EXPECTED_ROW_COUNT

    def test_realtimeData_hasDataSourceColumn(
        self, fixtureConn: sqlite3.Connection,
    ) -> None:
        cols = {
            row[1] for row in
            fixtureConn.execute('PRAGMA table_info(realtime_data)').fetchall()
        }
        assert 'data_source' in cols, (
            "fixture must have post-US-195 schema -- rerun migration "
            "on raw Pi db before export"
        )

    def test_realtimeData_allRowsTaggedReal(
        self, fixtureConn: sqlite3.Connection,
    ) -> None:
        # Per Invariant #3: 'Do NOT strip data_source from the fixture --
        # leave real tag; replay harness is expected to retag replay on
        # replay path.'
        nonRealCount = fixtureConn.execute(
            "SELECT COUNT(*) FROM realtime_data "
            "WHERE data_source != ? OR data_source IS NULL",
            (EXPECTED_DATA_SOURCE,),
        ).fetchone()[0]
        assert nonRealCount == 0, (
            f'{nonRealCount} rows are not tagged data_source=real'
        )

    def test_realtimeData_parameterSetMatchesSession23(
        self, fixtureConn: sqlite3.Connection,
    ) -> None:
        rows = fixtureConn.execute(
            'SELECT DISTINCT parameter_name FROM realtime_data '
            'ORDER BY parameter_name'
        ).fetchall()
        actual = frozenset(row[0] for row in rows)
        assert actual == EXPECTED_PARAMETERS, (
            f'PID drift: missing={EXPECTED_PARAMETERS - actual} '
            f'extra={actual - EXPECTED_PARAMETERS}'
        )

    def test_realtimeData_timestampWindowMatchesSession23(
        self, fixtureConn: sqlite3.Connection,
    ) -> None:
        # Session 23 drill ran on 2026-04-19; all rows must fall on that
        # date regardless of timestamp format (post-TD-027 canonical ISO
        # OR pre-TD-027 space-separator -- both prefix '2026-04-19').
        row = fixtureConn.execute(
            'SELECT MIN(timestamp), MAX(timestamp) FROM realtime_data'
        ).fetchone()
        assert row[0].startswith('2026-04-19')
        assert row[1].startswith('2026-04-19')


class TestWarmIdleRanges:
    """Spool-approved warm-idle tolerance bands (PM Rule 7 grounded data)."""

    @pytest.mark.parametrize('parameterName,lowerBound,upperBound', [
        (name, bounds[0], bounds[1]) for name, bounds in RANGE_BANDS.items()
    ])
    def test_parameterValues_insideToleranceBand(
        self,
        fixtureConn: sqlite3.Connection,
        parameterName: str,
        lowerBound: float,
        upperBound: float,
    ) -> None:
        rows = fixtureConn.execute(
            'SELECT MIN(value), MAX(value), COUNT(*) FROM realtime_data '
            'WHERE parameter_name = ?',
            (parameterName,),
        ).fetchone()
        minValue, maxValue, count = rows
        if count == 0:
            pytest.fail(f'No rows for parameter {parameterName}')
        assert lowerBound <= minValue, (
            f'{parameterName} min {minValue} < lower bound {lowerBound}'
        )
        assert maxValue <= upperBound, (
            f'{parameterName} max {maxValue} > upper bound {upperBound}'
        )

    def test_o2B1S1_demonstrates_closedLoopSwitching(
        self, fixtureConn: sqlite3.Connection,
    ) -> None:
        # O2 sensor must show range indicating stoich-crossing during the
        # capture window.  Hard equality on min=0/max=0.82 would be too
        # strict; assert the variance instead.
        row = fixtureConn.execute(
            'SELECT MIN(value), MAX(value) FROM realtime_data '
            "WHERE parameter_name = 'O2_B1S1'"
        ).fetchone()
        minV, maxV = row
        assert minV <= 0.1, f'O2 min {minV} too high -- should touch stoich low'
        assert maxV >= 0.5, f'O2 max {maxV} too low -- should touch stoich high'
        assert (maxV - minV) >= 0.5, (
            f'O2 variance {maxV - minV:.3f} too small -- not switching'
        )

    def test_ltft_flat_perSpoolBaseline(
        self, fixtureConn: sqlite3.Connection,
    ) -> None:
        # Spool observed LTFT=0.00 flat (tune is dialed).  Assert the
        # observed flat pattern holds at the fixture.
        rows = fixtureConn.execute(
            'SELECT DISTINCT value FROM realtime_data '
            "WHERE parameter_name = 'LONG_FUEL_TRIM_1'"
        ).fetchall()
        values = {row[0] for row in rows}
        assert values == {0.0}, (
            f'LTFT not flat at 0.00 -- fixture drift? values={values}'
        )
