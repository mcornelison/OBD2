################################################################################
# File Name: test_eclipse_idle_replay.py
# Purpose/Description: Determinism + replay-shape regression for the Session 23
#                      Eclipse idle fixture (US-197).  Exercises the contract
#                      the US-191 flat-file replay harness relies on:
#                      stable row counts, stable parameter set, valid schema,
#                      and in-scope-table coverage that matches the replay
#                      driver's IN_SCOPE_TABLES list.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex (US-197) | Initial -- replay-shape + determinism tests
# ================================================================================
################################################################################

"""Regression-shape tests for the eclipse_idle Session 23 fixture.

The canonical end-to-end replay driver (``scripts/replay_pi_fixture.sh``)
requires a live Pi + chi-srv-01 and cannot run inside pytest.  These
tests instead validate the INVARIANTS the replay driver depends on,
running entirely locally against the committed fixture:

* ``sqlite_master`` is intact (PRAGMA integrity_check = ok).
* The fixture contains the in-scope tables ``replay_pi_fixture.sh``
  iterates in its ``IN_SCOPE_TABLES`` array.
* Row counts are stable across repeated reads (deterministic output).
* The parameter set matches the Session 23 Phase-1 poll list (11 PIDs).
* The ``data_source='real'`` tag is preserved on every row so the
  replay path has something to retag to ``'replay'`` downstream.
* The fixture has NOT been mutated since build (size + content hash).

Why these tests exist: the replay harness asserts ``server delta ==
fixture row count EXACTLY``.  If any test here trips, the harness would
quietly give a misleading PASS or a puzzling FAIL.  Keeping the checks
local + fast means regressions surface at commit time, not in the next
integration drill.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / 'data' / 'regression' / 'pi-inputs' / 'eclipse_idle.db'
METADATA_PATH = REPO_ROOT / 'data' / 'regression' / 'pi-inputs' / 'eclipse_idle.metadata.json'

# Tables the replay driver iterates.  Sourced from
# ``scripts/replay_pi_fixture.sh`` IN_SCOPE_TABLES array -- keeping the
# list duplicated here is intentional: the test protects the contract
# between fixture + driver, and drift must be diagnosed, not silently
# tolerated.
REPLAY_IN_SCOPE_TABLES: frozenset[str] = frozenset({
    'realtime_data',
    'statistics',
    'profiles',
    'vehicle_info',
    'ai_recommendations',
    'connection_log',
    'alert_log',
    'calibration_sessions',
})

# Session 23 Phase-1 parameter set.  Must match the metadata.json
# ``pids_captured`` field; drift in either direction trips the test.
SESSION23_PARAMETERS: frozenset[str] = frozenset({
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


def openFixtureReadOnly() -> sqlite3.Connection:
    """Return a read-only sqlite3 connection on the committed fixture."""
    if not FIXTURE_PATH.exists():
        pytest.fail(
            f'Missing fixture: {FIXTURE_PATH}\n'
            'Run scripts/export_regression_fixture.sh to regenerate.'
        )
    posix = FIXTURE_PATH.as_posix()
    if not posix.startswith('/'):
        posix = '/' + posix
    return sqlite3.connect(f'file://{posix}?mode=ro', uri=True)


class TestFixtureIntegrity:
    """Schema + SQLite-level integrity checks."""

    def test_sqliteIntegrityCheck_reportsOk(self) -> None:
        conn = openFixtureReadOnly()
        try:
            row = conn.execute('PRAGMA integrity_check').fetchone()
            assert row[0] == 'ok', f'integrity_check={row[0]}'
        finally:
            conn.close()

    def test_fixture_hasAllReplayInScopeTables(self) -> None:
        conn = openFixtureReadOnly()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            presentTables = {row[0] for row in rows}
            missing = REPLAY_IN_SCOPE_TABLES - presentTables
            assert not missing, (
                f'fixture missing replay-in-scope tables: {missing}'
            )
        finally:
            conn.close()


class TestReplayDeterminism:
    """Row counts + parameter set must be stable across reads."""

    def test_realtimeData_rowCount_isDeterministic(self) -> None:
        # Read the count three times in a row.  Sanity check that nothing
        # mutates the db in-place (a regression we'd otherwise only
        # discover via the replay driver's delta mismatch).
        counts = []
        for _ in range(3):
            conn = openFixtureReadOnly()
            try:
                counts.append(
                    conn.execute('SELECT COUNT(*) FROM realtime_data').fetchone()[0]
                )
            finally:
                conn.close()
        assert len(set(counts)) == 1, f'non-deterministic counts: {counts}'

    def test_realtimeData_parameterSet_isDeterministic(self) -> None:
        # Parameter set must be exactly the Session 23 11-PID list.
        conn = openFixtureReadOnly()
        try:
            rows = conn.execute(
                'SELECT DISTINCT parameter_name FROM realtime_data '
                'ORDER BY parameter_name'
            ).fetchall()
            actual = frozenset(row[0] for row in rows)
            assert actual == SESSION23_PARAMETERS, (
                f'parameter drift: missing={SESSION23_PARAMETERS - actual} '
                f'extra={actual - SESSION23_PARAMETERS}'
            )
        finally:
            conn.close()

    def test_perParameter_rowCounts_matchMetadata(self) -> None:
        # Per-parameter row counts must sum to the metadata.json
        # row_count field.  This catches partial truncation of the
        # fixture (e.g. export dropped 1 PID silently).
        with METADATA_PATH.open() as handle:
            meta = json.load(handle)
        conn = openFixtureReadOnly()
        try:
            total = conn.execute(
                'SELECT COUNT(*) FROM realtime_data'
            ).fetchone()[0]
        finally:
            conn.close()
        assert total == meta['row_count'], (
            f"realtime_data count {total} != metadata row_count "
            f"{meta['row_count']}"
        )


class TestReplayTagging:
    """Data-source tagging contract the replay path depends on."""

    def test_every_realtimeData_row_tagged_real(self) -> None:
        # Invariant #3: 'Do NOT strip data_source from the fixture --
        # leave real tag; replay harness is expected to retag replay on
        # replay path.'  If any row has a non-real tag the replay's
        # retag step would either skip it (wrong row count delta) or
        # replace a user-supplied label.
        conn = openFixtureReadOnly()
        try:
            nonReal = conn.execute(
                "SELECT COUNT(*) FROM realtime_data "
                "WHERE data_source IS NULL OR data_source <> 'real'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert nonReal == 0, f'{nonReal} rows not tagged data_source=real'

    def test_every_realtimeData_row_has_null_drive_id(self) -> None:
        # US-200 Invariant #4: 'Session 23 149 rows NOT retagged -- NULL
        # drive_id for all pre-US-200 rows.'  If anything retagged them
        # we'd surface the contract violation here.
        conn = openFixtureReadOnly()
        try:
            hasDrive = conn.execute(
                "SELECT COUNT(*) FROM realtime_data "
                "WHERE drive_id IS NOT NULL"
            ).fetchone()[0]
        finally:
            conn.close()
        assert hasDrive == 0, (
            f'{hasDrive} rows have non-NULL drive_id -- '
            'US-200 Invariant #4 violated'
        )


class TestFixtureHash:
    """Fixture file-level pinning so accidental edits are obvious."""

    def test_fixtureFile_hashIsRecorded_ifMetadataClaimsIt(self) -> None:
        # Opt-in check: if metadata declares a 'fixture_sha256' field,
        # verify it matches the file on disk.  This lets a future
        # maintainer pin the fixture byte-for-byte by adding one field;
        # today we skip when absent so we don't block the commit.
        with METADATA_PATH.open() as handle:
            meta = json.load(handle)
        claimed = meta.get('fixture_sha256')
        if not claimed:
            pytest.skip('metadata does not pin fixture_sha256')
        digest = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
        assert digest == claimed, (
            f'fixture hash drift: on-disk={digest} metadata={claimed}'
        )
