################################################################################
# File Name: test_annotate_orphan_production_drain_events.py
# Purpose/Description: TDD tests for
#                      scripts/annotate_orphan_production_drain_events.py
#                      (US-442 / F-062).  Covers the pure planAnnotate API +
#                      the CLI --execute / --drain-event-ids / dry-run flags +
#                      idempotency (re-run is a no-op) + the "never touch a
#                      closed row" and "never touch a non-production row"
#                      guards + the "preserve an existing note (append, do not
#                      overwrite)" behavior + the "more NULL-end production rows
#                      than the configured set" warning.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-03    | Rex (US-442) | Initial -- TDD coverage for the historical
#                               orphan-production-drain tombstone annotation.
# ================================================================================
################################################################################

"""TDD tests for the US-442 / F-062 orphan-production-drain annotation.

The live Pi-side ``battery_health_log`` carries 4 historical orphan rows
(``drain_event_id`` 1, 9, 18, 21) with ``end_timestamp IS NULL`` and
``load_class='production'``.  They were opened by the now-retired US-216
auto-write path (0 callers post TD-058 / US-427) and never closed on
poweroff.  US-442's disposition (issue Option C, PM-endorsed "annotate,
never delete"): tombstone them with a provenance ``notes`` string so they
are self-documenting historical residue -- WITHOUT fabricating an
``end_timestamp`` (honest-instrument: no timing-truth source for a close)
and WITHOUT deleting any data.

These tests build a synthetic on-disk SQLite DB from the real schema
constant so the script is exercised against the live table shape.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from src.pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG

# ================================================================================
# Module loader (scripts/ is not a package)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = (
    _PROJECT_ROOT / 'scripts' / 'annotate_orphan_production_drain_events.py'
)


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'annotate_orphan_production_drain_events', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['annotate_orphan_production_drain_events'] = mod
    spec.loader.exec_module(mod)
    return mod


ann = _loadScript()


# ================================================================================
# Synthetic Pi DB fixture
# ================================================================================

# drain_event_id -> (start_timestamp, end_timestamp, load_class, notes).
# Mirrors the US-434 finding: 1/9/18/21 are the NULL-end production orphans.
# 30 is an already-closed production drain (must never be touched).
# 40 is an open *test* drain (wrong load_class -- must never be touched).
_DRAIN_ROWS = {
    1:  ('2026-05-04T13:21:08Z', None,                   'production', None),
    9:  ('2026-05-09T01:47:10Z', None,                   'production', None),
    18: ('2026-05-12T01:37:29Z', None,                   'production', None),
    21: ('2026-05-13T19:29:08Z', None,                   'production', None),
    30: ('2026-05-15T00:00:00Z', '2026-05-15T00:12:00Z', 'production', None),
    40: ('2026-05-16T00:00:00Z', None,                   'test',       None),
}


def _seedDb(dbPath: Path) -> None:
    conn = sqlite3.connect(str(dbPath))
    try:
        conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        for drainId, (startTs, endTs, loadClass, notes) in _DRAIN_ROWS.items():
            conn.execute(
                'INSERT INTO battery_health_log '
                '(drain_event_id, start_timestamp, end_timestamp, '
                ' load_class, notes, data_source) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (drainId, startTs, endTs, loadClass, notes, 'real'),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def piDb(tmp_path: Path) -> Path:
    dbPath = tmp_path / 'obd.db'
    _seedDb(dbPath)
    return dbPath


def _readRow(dbPath: Path, drainId: int) -> dict:
    conn = sqlite3.connect(str(dbPath))
    try:
        row = conn.execute(
            'SELECT end_timestamp, load_class, notes '
            'FROM battery_health_log WHERE drain_event_id = ?',
            (drainId,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return {'end_timestamp': row[0], 'load_class': row[1], 'notes': row[2]}


# ================================================================================
# planAnnotate
# ================================================================================

class TestPlanAnnotate:
    def test_planAnnotate_fourOrphans_plansAllFourWithProvenanceNote(
        self, piDb: Path,
    ) -> None:
        """
        Given: the synthetic DB with 4 NULL-end production orphans (1/9/18/21)
        When: planAnnotate runs over the default orphan id set
        Then: all four are planned; each new note carries the provenance tag
        """
        conn = sqlite3.connect(str(piDb))
        try:
            rows = ann.readOrphanRows(conn)
        finally:
            conn.close()
        plan = ann.planAnnotate(
            rows, drainEventIds=ann.ORPHAN_DRAIN_EVENT_IDS,
        )
        assert plan.skipped == []
        assert {r.drainEventId for r in plan.toAnnotate} == {1, 9, 18, 21}
        for row in plan.toAnnotate:
            assert ann.PROVENANCE_TAG in row.newNotes

    def test_planAnnotate_closedRow_skippedNotAnnotated(self, piDb: Path) -> None:
        conn = sqlite3.connect(str(piDb))
        try:
            rows = ann.readOrphanRows(conn)
        finally:
            conn.close()
        plan = ann.planAnnotate(rows, drainEventIds=(30,))
        assert plan.toAnnotate == []
        assert len(plan.skipped) == 1
        assert plan.skipped[0].drainEventId == 30
        assert 'closed' in plan.skipped[0].reason.lower()

    def test_planAnnotate_nonProductionRow_skippedWithReason(
        self, piDb: Path,
    ) -> None:
        conn = sqlite3.connect(str(piDb))
        try:
            rows = ann.readOrphanRows(conn)
        finally:
            conn.close()
        plan = ann.planAnnotate(rows, drainEventIds=(40,))
        assert plan.toAnnotate == []
        assert len(plan.skipped) == 1
        assert plan.skipped[0].drainEventId == 40
        assert 'production' in plan.skipped[0].reason.lower()

    def test_planAnnotate_missingRow_skippedWithReason(self, piDb: Path) -> None:
        conn = sqlite3.connect(str(piDb))
        try:
            rows = ann.readOrphanRows(conn)
        finally:
            conn.close()
        plan = ann.planAnnotate(rows, drainEventIds=(99,))
        assert plan.toAnnotate == []
        assert len(plan.skipped) == 1
        assert plan.skipped[0].drainEventId == 99
        assert 'battery_health_log' in plan.skipped[0].reason

    def test_planAnnotate_alreadyTagged_skippedAsIdempotent(
        self, piDb: Path,
    ) -> None:
        # Pre-tag drain 1 so a re-plan sees it already annotated.
        conn = sqlite3.connect(str(piDb))
        try:
            conn.execute(
                'UPDATE battery_health_log SET notes = ? '
                'WHERE drain_event_id = 1',
                (ann.PROVENANCE_NOTE,),
            )
            conn.commit()
            rows = ann.readOrphanRows(conn)
        finally:
            conn.close()
        plan = ann.planAnnotate(rows, drainEventIds=(1,))
        assert plan.toAnnotate == []
        assert len(plan.skipped) == 1
        assert 'already' in plan.skipped[0].reason.lower()

    def test_planAnnotate_existingNote_appendsPreservesOriginal(
        self, piDb: Path,
    ) -> None:
        conn = sqlite3.connect(str(piDb))
        try:
            conn.execute(
                'UPDATE battery_health_log SET notes = ? '
                'WHERE drain_event_id = 9',
                ('operator drill note',),
            )
            conn.commit()
            rows = ann.readOrphanRows(conn)
        finally:
            conn.close()
        plan = ann.planAnnotate(rows, drainEventIds=(9,))
        assert len(plan.toAnnotate) == 1
        newNotes = plan.toAnnotate[0].newNotes
        assert 'operator drill note' in newNotes  # original preserved
        assert ann.PROVENANCE_TAG in newNotes      # provenance appended


# ================================================================================
# CLI: dry-run / execute / idempotency / non-destructive guards
# ================================================================================

class TestCli:
    def test_main_dryRun_default_makesNoChanges(
        self, piDb: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = ann.main(['--db-path', str(piDb)])
        assert rc == 0
        for drainId in (1, 9, 18, 21):
            assert _readRow(piDb, drainId)['notes'] is None
        out = capsys.readouterr().out
        assert 'dry-run' in out.lower()
        assert 'would' in out.lower()

    def test_main_execute_annotatesAllFourOrphans(
        self, piDb: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = ann.main(['--db-path', str(piDb), '--execute', '--no-backup'])
        assert rc == 0
        for drainId in (1, 9, 18, 21):
            row = _readRow(piDb, drainId)
            assert row['notes'] is not None
            assert ann.PROVENANCE_TAG in row['notes']
            # honest-instrument: no fabricated close.
            assert row['end_timestamp'] is None

    def test_main_execute_neverTouchesClosedOrNonProductionRows(
        self, piDb: Path,
    ) -> None:
        rc = ann.main(['--db-path', str(piDb), '--execute', '--no-backup',
                       '--drain-event-ids', '1,9,18,21,30,40'])
        assert rc == 0
        assert _readRow(piDb, 30)['notes'] is None   # closed row untouched
        assert _readRow(piDb, 40)['notes'] is None   # test-class row untouched

    def test_main_execute_neverDeletesRows(self, piDb: Path) -> None:
        ann.main(['--db-path', str(piDb), '--execute', '--no-backup'])
        conn = sqlite3.connect(str(piDb))
        try:
            count = conn.execute(
                'SELECT COUNT(*) FROM battery_health_log',
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == len(_DRAIN_ROWS)

    def test_main_execute_idempotent_rerunIsNoOp(
        self, piDb: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert ann.main(['--db-path', str(piDb), '--execute', '--no-backup']) == 0
        first = {d: _readRow(piDb, d)['notes'] for d in (1, 9, 18, 21)}
        capsys.readouterr()
        rc = ann.main(['--db-path', str(piDb), '--execute', '--no-backup'])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'nothing to annotate' in out.lower()
        assert {d: _readRow(piDb, d)['notes'] for d in (1, 9, 18, 21)} == first

    def test_main_execute_makesBackupByDefault(self, piDb: Path) -> None:
        rc = ann.main(['--db-path', str(piDb), '--execute'])
        assert rc == 0
        backups = list(piDb.parent.glob('obd.db.*backup*'))
        assert backups, 'expected a .bak copy alongside the DB on --execute'

    def test_main_missingDb_returnsError(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = ann.main(['--db-path', str(tmp_path / 'does-not-exist.db')])
        assert rc == 2
        assert 'ERROR' in capsys.readouterr().err

    def test_main_extraNullEndProductionRows_warnsButProceeds(
        self, piDb: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Add a 5th NULL-end production drain outside the configured set.
        conn = sqlite3.connect(str(piDb))
        try:
            conn.execute(
                'INSERT INTO battery_health_log '
                '(drain_event_id, start_timestamp, load_class, data_source) '
                'VALUES (?, ?, ?, ?)',
                (25, '2026-05-14T00:00:00Z', 'production', 'real'),
            )
            conn.commit()
        finally:
            conn.close()
        rc = ann.main(['--db-path', str(piDb)])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'WARNING' in out
        assert '25' in out
