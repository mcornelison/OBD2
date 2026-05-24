################################################################################
# File Name: test_backfill_pi_historical_drains.py
# Purpose/Description: TDD tests for
#                      scripts/backfill_pi_battery_health_log_historical_drains.py
#                      (US-335 / Spool Story E).  Covers the pure planBackfill /
#                      matchStageTrigger / runtime-derivation API + the CLI
#                      --execute / --drain-event-ids flags + idempotency + the
#                      "leave already-closed rows untouched" guard + the
#                      "more NULL-end rows than the configured set" warning.
# Author: Agent2 (Ralph agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Agent2       | Initial -- TDD coverage for the Pi-side
#                  (US-335)      historical-drain backfill (drain_event_id 1+9).
# ================================================================================
################################################################################

"""TDD tests for the US-335 / Spool Story E Pi-side historical-drain backfill.

The Pi-side ``battery_health_log`` carries two stranded rows
(``drain_event_id`` 1 and 9) whose ``end_timestamp`` is NULL: drain 1 predates
the V0.24.1 ladder's recorder and drain 9's close-event did not flush before
``systemctl poweroff`` (pre-V0.27.2 root cause).  The contemporaneous
``power_log`` ``stage_trigger`` rows are the timing-truth source for the
close-time -- this script replays them into the stranded rows so the
(US-326 + US-331-fixed) sync UPDATE path can propagate them to the server.

These tests use a synthetic on-disk SQLite DB built from the real schema
constants so the script is exercised against the live table shape.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from src.pi.obdii.database_schema import SCHEMA_POWER_LOG
from src.pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG

# ================================================================================
# Module loader (scripts/ is not a package)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = (
    _PROJECT_ROOT / 'scripts' / 'backfill_pi_battery_health_log_historical_drains.py'
)


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'backfill_pi_battery_health_log_historical_drains', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['backfill_pi_battery_health_log_historical_drains'] = mod
    spec.loader.exec_module(mod)
    return mod


bp = _loadScript()


# ================================================================================
# Synthetic Pi DB fixture
# ================================================================================

# drain_event_id -> (start_timestamp, end_timestamp, start_soc, start_vcell_v)
_DRAIN_ROWS = {
    1: ('2026-05-04T13:21:08Z', None, 3.60, None),       # pre-US-289 row, NULL end
    9: ('2026-05-09T01:47:10Z', None, 3.70, 3.70),       # post-US-289 row, NULL end
    15: ('2026-05-10T13:57:00Z', '2026-05-10T14:10:06Z', 3.99, 3.99),  # already closed
}

# (timestamp, event_type, vcell) power_log rows in time order.
_POWER_LOG_ROWS = [
    ('2026-05-04T13:24:00Z', 'stage_warning', 3.69),
    ('2026-05-04T13:31:00Z', 'stage_imminent', 3.54),
    ('2026-05-04T13:34:09Z', 'stage_trigger', 3.42),   # drain 1 close
    ('2026-05-09T01:50:00Z', 'stage_warning', 3.65),
    ('2026-05-09T01:56:00Z', 'stage_imminent', 3.50),
    ('2026-05-09T01:59:30Z', 'stage_trigger', 3.41),   # drain 9 close
    ('2026-05-10T14:10:06Z', 'stage_trigger', 3.445),  # drain 15 close (already closed)
]

# Expected derived close values for the two stranded drains.
_EXPECT_DRAIN_1 = {'end_timestamp': '2026-05-04T13:34:09Z', 'end_soc': 3.42, 'runtime_seconds': 781}
_EXPECT_DRAIN_9 = {'end_timestamp': '2026-05-09T01:59:30Z', 'end_soc': 3.41, 'runtime_seconds': 740}


def _seedDb(dbPath: Path) -> None:
    conn = sqlite3.connect(str(dbPath))
    try:
        conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        conn.execute(SCHEMA_POWER_LOG)
        for drainId, (startTs, endTs, startSoc, startVcell) in _DRAIN_ROWS.items():
            endSoc = startSoc if endTs is not None else None
            runtimeSec = 786 if endTs is not None else None
            conn.execute(
                'INSERT INTO battery_health_log '
                '(drain_event_id, start_timestamp, end_timestamp, start_soc, '
                ' end_soc, start_vcell_v, end_vcell_v, runtime_seconds, '
                ' load_class, data_source) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (drainId, startTs, endTs, startSoc, endSoc, startVcell,
                 startVcell if endTs is not None else None, runtimeSec,
                 'production', 'real'),
            )
        for ts, eventType, vcell in _POWER_LOG_ROWS:
            conn.execute(
                'INSERT INTO power_log '
                '(timestamp, event_type, power_source, on_ac_power, vcell) '
                'VALUES (?, ?, ?, ?, ?)',
                (ts, eventType, 'battery', 0, vcell),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def piDb(tmp_path: Path) -> Path:
    dbPath = tmp_path / 'obd.db'
    _seedDb(dbPath)
    return dbPath


def _readDrainRow(dbPath: Path, drainId: int) -> dict:
    conn = sqlite3.connect(str(dbPath))
    try:
        row = conn.execute(
            'SELECT end_timestamp, end_soc, end_vcell_v, runtime_seconds '
            'FROM battery_health_log WHERE drain_event_id = ?',
            (drainId,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return {
        'end_timestamp': row[0],
        'end_soc': row[1],
        'end_vcell_v': row[2],
        'runtime_seconds': row[3],
    }


# ================================================================================
# Pure helpers: matchStageTrigger / _computeRuntimeSeconds
# ================================================================================

class TestMatchStageTrigger:
    def test_matchStageTrigger_picksFirstTriggerAtOrAfterStart_boundedByNextDrain(self) -> None:
        """
        Given: a list of stage_trigger rows spanning two drain windows
        When: matching for drain 1 with the upper bound = drain 9's start
        Then: only drain 1's trigger qualifies (the later one is past the bound)
        """
        triggers = [
            bp.StageTriggerRow(timestamp='2026-05-04T13:34:09Z', vcell=3.42),
            bp.StageTriggerRow(timestamp='2026-05-09T01:59:30Z', vcell=3.41),
        ]
        matched = bp.matchStageTrigger(
            '2026-05-04T13:21:08Z', triggers, upperBoundTs='2026-05-09T01:47:10Z',
        )
        assert matched is not None
        assert matched.timestamp == '2026-05-04T13:34:09Z'
        assert matched.vcell == 3.42

    def test_matchStageTrigger_noTriggerInWindow_returnsNone(self) -> None:
        triggers = [bp.StageTriggerRow(timestamp='2026-05-01T00:00:00Z', vcell=3.4)]
        assert bp.matchStageTrigger(
            '2026-05-04T13:21:08Z', triggers, upperBoundTs=None,
        ) is None

    def test_matchStageTrigger_unboundedPicksFirstAtOrAfterStart(self) -> None:
        triggers = [
            bp.StageTriggerRow(timestamp='2026-05-04T13:34:09Z', vcell=3.42),
            bp.StageTriggerRow(timestamp='2026-05-09T01:59:30Z', vcell=3.41),
        ]
        matched = bp.matchStageTrigger(
            '2026-05-09T01:47:10Z', triggers, upperBoundTs=None,
        )
        assert matched is not None
        assert matched.timestamp == '2026-05-09T01:59:30Z'

    def test_computeRuntimeSeconds_canonicalIso(self) -> None:
        assert bp._computeRuntimeSeconds('2026-05-04T13:21:08Z', '2026-05-04T13:34:09Z') == 781
        assert bp._computeRuntimeSeconds('2026-05-09T01:47:10Z', '2026-05-09T01:59:30Z') == 740

    def test_computeRuntimeSeconds_unparseable_returnsNone(self) -> None:
        assert bp._computeRuntimeSeconds('not-a-date', '2026-05-04T13:34:09Z') is None


# ================================================================================
# planBackfill
# ================================================================================

class TestPlanBackfill:
    def test_planBackfill_twoNullEndDrains_plansBothFromTriggerRows(self, piDb: Path) -> None:
        """
        Given: the synthetic DB with drains 1 + 9 NULL-end and matching triggers
        When: planBackfill runs over drain_event_ids (1, 9)
        Then: both rows are planned with values derived from the trigger rows
        """
        conn = sqlite3.connect(str(piDb))
        try:
            allDrains = bp.readDrainRows(conn)
            triggers = bp.readStageTriggerRows(conn)
        finally:
            conn.close()
        targets = [r for r in allDrains if r.drainEventId in (1, 9)]
        plan = bp.planBackfill(targets, allDrains, triggers, drainEventIds=(1, 9))
        assert plan.skipped == []
        byId = {r.drainEventId: r for r in plan.toUpdate}
        assert set(byId) == {1, 9}
        assert byId[1].endTimestamp == _EXPECT_DRAIN_1['end_timestamp']
        assert byId[1].endSoc == _EXPECT_DRAIN_1['end_soc']
        assert byId[1].runtimeSeconds == _EXPECT_DRAIN_1['runtime_seconds']
        assert byId[9].endTimestamp == _EXPECT_DRAIN_9['end_timestamp']
        assert byId[9].endSoc == _EXPECT_DRAIN_9['end_soc']
        assert byId[9].runtimeSeconds == _EXPECT_DRAIN_9['runtime_seconds']

    def test_planBackfill_alreadyClosedRow_skippedAsIdempotent(self, piDb: Path) -> None:
        conn = sqlite3.connect(str(piDb))
        try:
            allDrains = bp.readDrainRows(conn)
            triggers = bp.readStageTriggerRows(conn)
        finally:
            conn.close()
        targets = [r for r in allDrains if r.drainEventId == 15]
        plan = bp.planBackfill(targets, allDrains, triggers, drainEventIds=(15,))
        assert plan.toUpdate == []
        assert len(plan.skipped) == 1
        assert plan.skipped[0].drainEventId == 15
        assert 'already' in plan.skipped[0].reason.lower()

    def test_planBackfill_missingPowerLogTrigger_skipsWithReason(self, piDb: Path) -> None:
        conn = sqlite3.connect(str(piDb))
        try:
            # Delete every stage_trigger row so drain 1 has no timing source.
            conn.execute("DELETE FROM power_log WHERE event_type = 'stage_trigger'")
            conn.commit()
            allDrains = bp.readDrainRows(conn)
            triggers = bp.readStageTriggerRows(conn)
        finally:
            conn.close()
        targets = [r for r in allDrains if r.drainEventId in (1, 9)]
        plan = bp.planBackfill(targets, allDrains, triggers, drainEventIds=(1, 9))
        assert plan.toUpdate == []
        assert {s.drainEventId for s in plan.skipped} == {1, 9}
        assert all('stage_trigger' in s.reason for s in plan.skipped)

    def test_planBackfill_drainRowMissing_skipsWithReason(self, piDb: Path) -> None:
        conn = sqlite3.connect(str(piDb))
        try:
            allDrains = bp.readDrainRows(conn)
            triggers = bp.readStageTriggerRows(conn)
        finally:
            conn.close()
        plan = bp.planBackfill([], allDrains, triggers, drainEventIds=(99,))
        assert plan.toUpdate == []
        assert len(plan.skipped) == 1
        assert plan.skipped[0].drainEventId == 99
        assert 'battery_health_log' in plan.skipped[0].reason


# ================================================================================
# CLI: --execute / dry-run / idempotency / already-closed guard
# ================================================================================

class TestCli:
    def test_main_dryRun_default_makesNoChanges(self, piDb: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = bp.main(['--db-path', str(piDb)])
        assert rc == 0
        assert _readDrainRow(piDb, 1)['end_timestamp'] is None
        assert _readDrainRow(piDb, 9)['end_timestamp'] is None
        out = capsys.readouterr().out
        assert 'dry-run' in out.lower()
        assert 'would' in out.lower()

    def test_main_execute_populatesBothRows(self, piDb: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = bp.main(['--db-path', str(piDb), '--execute', '--no-backup'])
        assert rc == 0
        row1 = _readDrainRow(piDb, 1)
        assert row1['end_timestamp'] == _EXPECT_DRAIN_1['end_timestamp']
        assert row1['end_soc'] == _EXPECT_DRAIN_1['end_soc']
        assert row1['end_vcell_v'] == _EXPECT_DRAIN_1['end_soc']  # vcell mirrors end_soc
        assert row1['runtime_seconds'] == _EXPECT_DRAIN_1['runtime_seconds']
        row9 = _readDrainRow(piDb, 9)
        assert row9['end_timestamp'] == _EXPECT_DRAIN_9['end_timestamp']
        assert row9['end_soc'] == _EXPECT_DRAIN_9['end_soc']
        assert row9['end_vcell_v'] == _EXPECT_DRAIN_9['end_soc']
        assert row9['runtime_seconds'] == _EXPECT_DRAIN_9['runtime_seconds']

    def test_main_execute_doesNotTouchAlreadyClosedRow(self, piDb: Path) -> None:
        # Request id 15 explicitly -- the `AND end_timestamp IS NULL` guard
        # must still leave it alone.
        rc = bp.main(['--db-path', str(piDb), '--execute', '--no-backup',
                      '--drain-event-ids', '1,9,15'])
        assert rc == 0
        row15 = _readDrainRow(piDb, 15)
        assert row15['end_timestamp'] == '2026-05-10T14:10:06Z'
        assert row15['runtime_seconds'] == 786

    def test_main_execute_idempotent_rerunIsNoOp(self, piDb: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert bp.main(['--db-path', str(piDb), '--execute', '--no-backup']) == 0
        first1 = _readDrainRow(piDb, 1)
        capsys.readouterr()
        rc = bp.main(['--db-path', str(piDb), '--execute', '--no-backup'])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'nothing to backfill' in out.lower()
        assert _readDrainRow(piDb, 1) == first1

    def test_main_execute_makesBackupByDefault(self, piDb: Path) -> None:
        rc = bp.main(['--db-path', str(piDb), '--execute'])
        assert rc == 0
        backups = list(piDb.parent.glob('obd.db.*backup*'))
        assert backups, 'expected a .bak copy alongside the DB on --execute'

    def test_main_missingDb_returnsError(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = bp.main(['--db-path', str(tmp_path / 'does-not-exist.db')])
        assert rc == 2
        assert 'ERROR' in capsys.readouterr().err

    def test_main_extraNullEndRows_warnsButProceeds(self, piDb: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # Add a 3rd NULL-end drain row outside the configured {1, 9} set.
        conn = sqlite3.connect(str(piDb))
        try:
            conn.execute(
                'INSERT INTO battery_health_log '
                '(drain_event_id, start_timestamp, start_soc, load_class, data_source) '
                'VALUES (?, ?, ?, ?, ?)',
                (20, '2026-05-13T00:00:00Z', 3.8, 'production', 'real'),
            )
            conn.commit()
        finally:
            conn.close()
        rc = bp.main(['--db-path', str(piDb)])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'WARNING' in out
        assert '20' in out
