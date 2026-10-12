################################################################################
# File Name: test_schema_diff.py
# Purpose/Description: Unit tests for scripts/schema_diff.py (US-249 / TD-039
#     close).  Pure-function tests for computeDiff + thin smoke tests for the
#     real loadPiSchema / loadServerSchema integration sites.  Mocks both
#     schemas as plain dicts so the tests don't need sqlite or sqlalchemy.
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex (US-249) | Initial -- TDD coverage for schema_diff script.
# 2026-05-01    | Rex (US-256) | Sprint 19/20 retro -- TD-043 rule coverage.
#               |              | Add TestComputeDiffServerRequiredColumns +
#               |              | extend TestMainExitCode with the new gate trip
#               |              | scenario.  The new rule fires when the server
#               |              | has a NOT-NULL no-default column that the Pi
#               |              | sync writer never populates (silent-sync-
#               |              | failure direction).
# 2026-09-09    | Rex (US-607) | TD-079 -- the DDL registry was blind to
#               |              | dtc_freeze_frame.  Add TestSyncedPiTables,
#               |              | TestPiLoaderSeesEverySyncedTable and
#               |              | TestBlindSpotGate: a predicate over the WHOLE
#               |              | synced set, not an entry for one table.  The
#               |              | four TestMainExitCode tests that substitute a
#               |              | synthetic Pi schema now substitute the synced
#               |              | registry to match it (see that class docstring).
# 2026-09-09    | Rex (US-711) | F-138 -- US-607's restored sight produced a
#               |              | FALSE TD-039 trip on dtc_freeze_frame, whose
#               |              | US-369 resolver renames vehicle_info_vin and
#               |              | drops data_source by design.  Add the THIRD
#               |              | by-design class (CROSS_TIER_RESOLVED_COLUMNS,
#               |              | MOVED here from audit_sync_contract_parity --
#               |              | reading it there would be a circular import).
#               |              | Add TestComputeDiffCrossTierResolvedColumns,
#               |              | TestCrossTierResolvedColumnsIsDeclaredOnce and
#               |              | TestRealTreeCrossTierResolution.
# 2026-09-10    | Rex (US-712) | F-138 -- the exit code collapsed three rules
#               |              | into one bit and TWO stand red here, so
#               |              | `main() == 1` could not attribute a trip.  Add
#               |              | TestGateTripsNameTheCondition,
#               |              | TestExitCodeIsDerivedFromTheNamedTrips (the
#               |              | structural guard: main may not restate a rule
#               |              | key) and
#               |              | TestRealTreeStandingConditionsAreIndividually-
#               |              | Identifiable.  Mutation-verified: deleting the
#               |              | TD-039 term leaves the real gate at exit 1 and
#               |              | still fails a test BY NAME.
# ================================================================================
################################################################################

"""TDD tests for the US-249 schema_diff script (TD-039 close).

The diff script has three responsibilities:

1. Load the Pi schema from the canonical CREATE TABLE strings under
   ``src/pi/`` (executed in an in-memory sqlite3 connection so column
   parsing is delegated to SQLite itself, not a regex).
2. Load the server schema from SQLAlchemy ``Base.metadata.tables``.
3. Compute a deterministic JSON diff that:
   - Lists tables present only on one side (Pi-only / server-only --
     expected, since each tier owns operational and analytics tables).
   - For tables present on both sides, lists per-side column-set drift
     (Pi-only columns = Pi added a column without a server migration =
     the silent-data-loss class TD-039 is closing).
   - Recognizes server-side mirror columns (``source_id``,
     ``source_device``, ``synced_at``, ``sync_batch_id``) so they are
     never flagged as drift.

Tests prove (1) by mocking dicts directly (computeDiff is pure), (2) by
exercising the real loaders against the live schema (smoke), and (3) by
asserting deterministic ordering so CI diffs stay readable.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ================================================================================
# Module loader (scripts/ is not a package -- mirrors test_apply_server_migrations)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'schema_diff.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'schema_diff', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['schema_diff'] = mod
    spec.loader.exec_module(mod)
    return mod


sd = _loadScript()


# ================================================================================
# computeDiff -- pure-function tests (no sqlite, no sqlalchemy)
# ================================================================================


class TestComputeDiffCleanSchemas:
    """Both sides agree -- no drift reported."""

    def test_computeDiff_emptyOnBothSides_returnsEmptyDiff(self) -> None:
        """Given: empty Pi + empty server. Then: every category empty."""
        result = sd.computeDiff({}, {})

        assert result['tablesOnlyInPi'] == []
        assert result['tablesOnlyInServer'] == []
        assert result['sharedTableDrift'] == {}
        assert result['summary']['piTableCount'] == 0
        assert result['summary']['serverTableCount'] == 0
        assert result['summary']['sharedTableCount'] == 0
        assert result['summary']['tablesWithDrift'] == []

    def test_computeDiff_identicalSingleTable_noDrift(self) -> None:
        """Given: same table same columns on both sides. Then: zero drift."""
        pi = {'realtime_data': {'id', 'timestamp', 'value'}}
        server = {'realtime_data': {'id', 'timestamp', 'value'}}

        result = sd.computeDiff(pi, server)

        assert result['sharedTableDrift'] == {}
        assert result['summary']['tablesWithDrift'] == []

    def test_computeDiff_piPkRenamedToId_notFlagged(self) -> None:
        """Documented PK rename pairs (Pi name -> server `id`) don't trip gate.

        battery_health_log.drain_event_id and calibration_sessions.session_id
        are renamed to `id` by the sync client per the producing modules'
        docstrings.  Diff must recognize them as equivalent.
        """
        pi = {
            'battery_health_log': {
                'drain_event_id', 'start_timestamp', 'start_soc',
            },
        }
        server = {
            'battery_health_log': {
                'id', 'start_timestamp', 'start_soc',
            },
        }

        result = sd.computeDiff(pi, server)

        assert result['sharedTableDrift'] == {}
        assert result['summary']['tablesWithDrift'] == []
        assert result['summary']['tablesWithPiOnlyDrift'] == []

    def test_computeDiff_serverMirrorColumns_notFlagged(self) -> None:
        """Given: server has source_id/source_device/synced_at/sync_batch_id.
        Then: those four columns are recognized as expected mirror surface,
        not drift.
        """
        pi = {'realtime_data': {'id', 'timestamp', 'value'}}
        server = {
            'realtime_data': {
                'id', 'timestamp', 'value',
                # Server-side mirror surface (US-CMP-003 sync convention)
                'source_id', 'source_device', 'synced_at', 'sync_batch_id',
            },
        }

        result = sd.computeDiff(pi, server)

        # Mirror columns must NOT appear in the drift list.
        assert result['sharedTableDrift'] == {}
        assert result['summary']['tablesWithDrift'] == []


class TestComputeDiffTablePresence:
    """Tables present on only one tier."""

    def test_computeDiff_tableOnlyInPi_listedSeparately(self) -> None:
        pi = {'pi_state': {'id', 'no_new_drives'}}
        server: dict[str, set[str]] = {}

        result = sd.computeDiff(pi, server)

        assert result['tablesOnlyInPi'] == ['pi_state']
        assert result['tablesOnlyInServer'] == []
        assert result['sharedTableDrift'] == {}

    def test_computeDiff_tableOnlyInServer_listedSeparately(self) -> None:
        pi: dict[str, set[str]] = {}
        server = {'sync_history': {'id', 'device_id', 'started_at'}}

        result = sd.computeDiff(pi, server)

        assert result['tablesOnlyInPi'] == []
        assert result['tablesOnlyInServer'] == ['sync_history']
        assert result['sharedTableDrift'] == {}

    def test_computeDiff_outputIsSorted_deterministic(self) -> None:
        """CI compatibility: same inputs -> same output ordering."""
        pi = {'zebra': {'id'}, 'alpha': {'id'}, 'mike': {'id'}}
        server: dict[str, set[str]] = {}

        result = sd.computeDiff(pi, server)

        assert result['tablesOnlyInPi'] == ['alpha', 'mike', 'zebra']


class TestComputeDiffColumnDrift:
    """Tables present on both sides but with column-set divergence."""

    def test_computeDiff_piHasExtraColumn_flaggedAsDrift(self) -> None:
        """The TD-039 case: Pi added a column, no server migration shipped.

        Pi has ``ambient_temp_at_start_c`` (US-206), server doesn't ->
        diff flags it as ``columnsOnlyInPi``.
        """
        pi = {
            'drive_summary': {
                'drive_id', 'drive_start_timestamp',
                'ambient_temp_at_start_c',
            },
        }
        server = {
            'drive_summary': {'drive_id', 'drive_start_timestamp'},
        }

        result = sd.computeDiff(pi, server)

        assert 'drive_summary' in result['sharedTableDrift']
        drift = result['sharedTableDrift']['drive_summary']
        assert drift['columnsOnlyInPi'] == ['ambient_temp_at_start_c']
        assert drift['columnsOnlyInServer'] == []
        assert result['summary']['tablesWithDrift'] == ['drive_summary']

    def test_computeDiff_serverHasExtraColumn_flaggedAsDrift(self) -> None:
        """Server has a column Pi doesn't (and it's NOT a mirror col).

        E.g. ``device_id`` on drive_summary is server-only by design.
        We still surface it -- operator decides whether to delete or
        document.
        """
        pi = {'drive_summary': {'drive_id'}}
        server = {'drive_summary': {'drive_id', 'device_id'}}

        result = sd.computeDiff(pi, server)

        assert 'drive_summary' in result['sharedTableDrift']
        drift = result['sharedTableDrift']['drive_summary']
        assert drift['columnsOnlyInPi'] == []
        assert drift['columnsOnlyInServer'] == ['device_id']

    def test_computeDiff_bothSidesHaveExtraColumns_bothFlagged(self) -> None:
        pi = {'realtime_data': {'id', 'pi_only_col'}}
        server = {'realtime_data': {'id', 'server_only_col'}}

        result = sd.computeDiff(pi, server)

        drift = result['sharedTableDrift']['realtime_data']
        assert drift['columnsOnlyInPi'] == ['pi_only_col']
        assert drift['columnsOnlyInServer'] == ['server_only_col']

    def test_computeDiff_columnDriftListsAreSorted(self) -> None:
        """Deterministic ordering inside per-table drift lists."""
        pi = {'t': {'id', 'zulu', 'alpha', 'mike'}}
        server = {'t': {'id'}}

        result = sd.computeDiff(pi, server)

        assert result['sharedTableDrift']['t']['columnsOnlyInPi'] == [
            'alpha', 'mike', 'zulu',
        ]


class TestComputeDiffSummary:
    """Summary block carries counts + drift-table list for quick scanning."""

    def test_computeDiff_summaryCounts_correct(self) -> None:
        pi = {'a': {'id'}, 'b': {'id'}, 'c': {'id'}}
        server = {'b': {'id'}, 'c': {'id'}, 'd': {'id'}}

        result = sd.computeDiff(pi, server)

        assert result['summary']['piTableCount'] == 3
        assert result['summary']['serverTableCount'] == 3
        # Shared = b, c -> 2
        assert result['summary']['sharedTableCount'] == 2

    def test_computeDiff_tablesWithDriftSorted(self) -> None:
        pi = {
            'zebra': {'id', 'extra_zebra_col'},
            'alpha': {'id', 'extra_alpha_col'},
        }
        server = {'zebra': {'id'}, 'alpha': {'id'}}

        result = sd.computeDiff(pi, server)

        assert result['summary']['tablesWithDrift'] == ['alpha', 'zebra']


# ================================================================================
# TD-043 rule: server NOT-NULL no-default + Pi omits column (US-256)
# ================================================================================


class TestComputeDiffServerRequiredColumns:
    """The TD-043 silent-sync-failure rule.

    Fires when the server declares a column as NOT NULL with no default
    (Python or server-side) AND the Pi schema does not have the column.
    Every Pi INSERT into that table fails with MariaDB-1364 / SQLite
    NOT-NULL-constraint -- the exact production failure that hit
    chi-srv-01 on 2026-05-01 and motivated v0006.
    """

    def test_computeDiff_serverRequiredColumnPiOmits_flagged(self) -> None:
        """The TD-043 case: server has device_id NOT NULL, Pi omits.

        Pre-v0006 production state: server's drive_summary had legacy
        device_id NOT NULL with no default; Pi sync writer always
        omitted it.  Rule must flag it as a high-severity gate trip.
        """
        pi = {'drive_summary': {'drive_id', 'drive_start_timestamp'}}
        server = {
            'drive_summary': {
                'drive_id', 'drive_start_timestamp', 'device_id',
            },
        }
        # device_id is the only NOT-NULL no-default column on the
        # server side (the production TD-043 trap).
        serverRequired = {'drive_summary': {'device_id'}}

        result = sd.computeDiff(pi, server, serverRequired)

        assert (
            result['serverRequiredColumnsMissingOnPi']['drive_summary']
            == ['device_id']
        )
        assert (
            result['summary']['tablesWithRequiredColumnGap']
            == ['drive_summary']
        )

    def test_computeDiff_serverRequiredColumnPiHas_notFlagged(self) -> None:
        """No gate trip when Pi populates the required column.

        If the Pi sync writer DOES populate the NOT-NULL column, the
        INSERT succeeds and the rule must NOT fire.
        """
        pi = {'realtime_data': {'id', 'timestamp', 'value'}}
        server = {'realtime_data': {'id', 'timestamp', 'value'}}
        # timestamp is required server-side AND Pi sends it -- no trip.
        serverRequired = {'realtime_data': {'timestamp'}}

        result = sd.computeDiff(pi, server, serverRequired)

        assert result['serverRequiredColumnsMissingOnPi'] == {}
        assert result['summary']['tablesWithRequiredColumnGap'] == []

    def test_computeDiff_mirrorColumnsExempt_notFlagged(self) -> None:
        """Mirror columns (source_id/synced_at/...) never trip the rule.

        The server populates ``source_id``, ``source_device``,
        ``synced_at``, ``sync_batch_id`` itself at INSERT time per the
        US-CMP-003 sync convention.  A NOT-NULL declaration on those
        columns is by-design and must not surface as a gate trip even
        though the Pi schema lacks them.
        """
        pi = {'t': {'id', 'value'}}
        server = {'t': {'id', 'value', 'source_id', 'source_device'}}
        # Server treats source_id and source_device as required in
        # its own DDL -- but they're mirror cols, never Pi's job.
        serverRequired = {'t': {'source_id', 'source_device'}}

        result = sd.computeDiff(pi, server, serverRequired)

        assert result['serverRequiredColumnsMissingOnPi'] == {}
        assert result['summary']['tablesWithRequiredColumnGap'] == []

    def test_computeDiff_omitsRule_whenNoServerRequiredKwarg(self) -> None:
        """Back-compat: 2-arg callers see the old shape exactly.

        Sprint 20 / pre-US-256 callers call ``computeDiff(pi, server)``
        without the new kwarg.  The output dict must NOT include the
        new keys so existing snapshot tests / consumer code don't
        break.
        """
        pi = {'t': {'id'}}
        server = {'t': {'id', 'extra'}}

        result = sd.computeDiff(pi, server)

        assert 'serverRequiredColumnsMissingOnPi' not in result
        assert 'tablesWithRequiredColumnGap' not in result['summary']

    def test_computeDiff_multipleTablesAndColumns_allFlagged(self) -> None:
        """Multi-table + multi-column drift surfaces fully + sorted."""
        pi = {
            'drive_summary': {'drive_id'},
            'realtime_data': {'id', 'timestamp', 'value'},
        }
        server = {
            'drive_summary': {'drive_id', 'device_id', 'start_time'},
            'realtime_data': {'id', 'timestamp', 'value', 'pii_token'},
        }
        serverRequired = {
            'drive_summary': {'device_id', 'start_time'},
            'realtime_data': {'pii_token'},
        }

        result = sd.computeDiff(pi, server, serverRequired)

        gap = result['serverRequiredColumnsMissingOnPi']
        assert gap['drive_summary'] == ['device_id', 'start_time']
        assert gap['realtime_data'] == ['pii_token']
        assert (
            result['summary']['tablesWithRequiredColumnGap']
            == ['drive_summary', 'realtime_data']
        )


# ================================================================================
# JSON output -- shape contract for downstream tooling
# ================================================================================


class TestRenderJson:
    """The diff dict serialises to clean JSON (sets are converted to lists)."""

    def test_renderJson_emptyDiff_validJson(self) -> None:
        diff = sd.computeDiff({}, {})
        payload = sd.renderJson(diff)

        # Must round-trip through json.loads -- no set objects leaked.
        parsed = json.loads(payload)
        assert parsed['tablesOnlyInPi'] == []
        assert parsed['summary']['piTableCount'] == 0

    def test_renderJson_isIndented_humanReadable(self) -> None:
        """JSON output is indented for grep-ability + git-diff readability."""
        diff = sd.computeDiff({'a': {'id'}}, {})
        payload = sd.renderJson(diff)

        # Indent of 2 spaces -> "  " appears in output.
        assert '\n  ' in payload


# ================================================================================
# Loader smoke tests -- exercise the real Pi + server schema-load paths
# ================================================================================


class TestLoadPiSchemaSmoke:
    """The real Pi loader returns a non-empty dict with expected tables."""

    def test_loadPiSchema_returnsKnownPiTables(self) -> None:
        """All canonical Pi capture tables appear in the loader output."""
        schema = sd.loadPiSchema()

        # Spot-check load coverage (not exhaustive -- catches loader regressions).
        for table in ('realtime_data', 'profiles', 'connection_log',
                      'alert_log', 'drive_counter', 'drive_summary',
                      'dtc_log', 'battery_health_log',
                      'pi_state', 'sync_log'):
            assert table in schema, f'{table!r} missing from loadPiSchema()'

    def test_loadPiSchema_realtimeDataColumns(self) -> None:
        """realtime_data should carry the canonical column set."""
        schema = sd.loadPiSchema()

        rt = schema['realtime_data']
        # Spot-check the load-bearing columns.
        for col in ('id', 'timestamp', 'parameter_name', 'value', 'unit',
                    'profile_id', 'data_source', 'drive_id'):
            assert col in rt, f'realtime_data missing {col!r}'


class TestLoadServerSchemaSmoke:
    """The real server loader returns a non-empty dict with expected tables."""

    def test_loadServerSchema_returnsKnownServerTables(self) -> None:
        try:
            schema = sd.loadServerSchema()
        except ImportError:
            pytest.skip('SQLAlchemy not available in this env')

        # Spot-check load coverage.
        for table in ('realtime_data', 'profiles', 'sync_history',
                      'drive_summary', 'baselines'):
            assert table in schema, f'{table!r} missing from loadServerSchema()'

    def test_loadServerSchema_realtimeDataIncludesMirrorColumns(self) -> None:
        try:
            schema = sd.loadServerSchema()
        except ImportError:
            pytest.skip('SQLAlchemy not available in this env')

        rt = schema['realtime_data']
        for col in ('source_id', 'source_device', 'synced_at',
                    'sync_batch_id'):
            assert col in rt, f'server realtime_data missing {col!r}'


class TestLoadServerNotNullNoDefaultSmoke:
    """Live ORM check: post-v0006 drive_summary is TD-043 clean."""

    def test_loadServerNotNullNoDefault_returnsDict(self) -> None:
        """The new loader returns a clean dict shape."""
        try:
            required = sd.loadServerNotNullNoDefault()
        except ImportError:
            pytest.skip('SQLAlchemy not available in this env')

        assert isinstance(required, dict)
        for tableName, cols in required.items():
            assert isinstance(tableName, str)
            assert isinstance(cols, set)

    def test_loadServerNotNullNoDefault_postV0006_driveSummaryClean(
        self,
    ) -> None:
        """Post-v0006 invariant: drive_summary has zero TD-043-class cols.

        After v0006 ALTERed device_id and start_time to nullable, the
        ORM model declares all 6 legacy columns as ``Mapped[X | None]``
        so the new rule must NOT report drive_summary anymore.
        Discriminator: if v0006 ever rolls back, this test fails.
        """
        try:
            required = sd.loadServerNotNullNoDefault()
        except ImportError:
            pytest.skip('SQLAlchemy not available in this env')

        driveSummaryRequired = required.get('drive_summary', set())
        # The 6 legacy columns must NOT be required after v0006.
        for col in ('device_id', 'start_time', 'end_time',
                    'duration_seconds', 'profile_id', 'row_count'):
            assert col not in driveSummaryRequired, (
                f'drive_summary.{col} is NOT-NULL no-default in the live '
                f'ORM -- v0006 may have rolled back, restoring TD-043 '
                f'(would FAIL Pi sync INSERT).'
            )

    def test_loadServerNotNullNoDefault_autoIncrementPkExempt(self) -> None:
        """Auto-increment integer PKs are exempt from the rule.

        The ``id`` column on every synced table is autoincrement +
        primary_key.  The DB supplies the value at INSERT, so the
        Pi-omits-it scenario is by design.  Filter must exclude these
        or the report drowns in by-design noise.
        """
        try:
            required = sd.loadServerNotNullNoDefault()
        except ImportError:
            pytest.skip('SQLAlchemy not available in this env')

        # Spot-check tables that have autoinc id PKs.
        for tableName in (
            'realtime_data', 'connection_log', 'sync_history',
            'drive_summary',
        ):
            cols = required.get(tableName, set())
            assert 'id' not in cols, (
                f'{tableName}.id is auto-increment PK -- must be exempt '
                f'from the NOT-NULL no-default rule'
            )


# ================================================================================
# main() -- CLI integration
# ================================================================================


class TestMainExitCode:
    """Exit-code contract: 0 = no drift in shared tables, 1 = drift present.

    US-607 note on the ``syncedPiTables`` substitutions below.  These tests hand
    ``main()`` a SYNTHETIC two-table world, so they must hand it a synthetic
    sync registry too.  Left unsubstituted, the live registry would name a dozen
    real tables that the synthetic Pi schema does not contain and every case
    here would trip the new TD-079 blind-spot gate -- which would be the gate
    working correctly over a fixture that lies about what the Pi syncs, not a
    finding.  The gate's teeth are pinned against the REAL registry in
    :class:`TestBlindSpotGate` instead.
    """

    def test_main_cleanSchemas_exits0(self, monkeypatch, capsys) -> None:
        """When loaders return drift-free shared tables, main exits 0."""
        monkeypatch.setattr(sd, 'loadPiSchema',
                            lambda: {'t': {'id', 'value'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {'t': {'id', 'value'}})
        monkeypatch.setattr(sd, 'syncedPiTables', lambda: frozenset({'t'}))

        rc = sd.main([])

        assert rc == 0
        out = capsys.readouterr().out
        # Output is JSON on stdout.
        parsed = json.loads(out)
        assert parsed['summary']['tablesWithDrift'] == []

    def test_main_driftPresent_exits1(self, monkeypatch, capsys) -> None:
        """When a shared table has Pi-only columns, main exits 1."""
        monkeypatch.setattr(sd, 'loadPiSchema',
                            lambda: {'t': {'id', 'pi_extra'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'syncedPiTables', lambda: frozenset({'t'}))

        rc = sd.main([])

        assert rc == 1
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed['summary']['tablesWithDrift'] == ['t']

    def test_main_tableOnlyOnOneSide_exits0(self, monkeypatch, capsys) -> None:
        """Pi-only / server-only tables are reported but DON'T fail the exit code.

        Tier-owned tables are expected (pi_state on Pi, sync_history on
        server).  Only shared-table drift is gate-worthy.
        """
        monkeypatch.setattr(sd, 'loadPiSchema',
                            lambda: {'pi_only': {'id'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {'server_only': {'id'}})
        monkeypatch.setattr(sd, 'syncedPiTables',
                            lambda: frozenset({'pi_only'}))

        rc = sd.main([])

        assert rc == 0

    def test_main_serverOnlyExtraColumns_exits0(self, monkeypatch, capsys) -> None:
        """Server has columns Pi lacks (analytics extras, PK renames).

        TD-039 is about Pi-add-without-server-migration silent data loss.
        The reverse direction (server-only columns) does NOT risk data
        loss -- the column just sits empty until analytics populates it.
        Gate must NOT trip on this direction or it will fire constantly
        on the existing drive_summary / profiles / vehicle_info /
        battery_health_log / calibration_sessions intentional designs.
        """
        monkeypatch.setattr(sd, 'loadPiSchema',
                            lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {'t': {'id', 'analytics_only_col'}})
        # Empty NOT-NULL no-default state -- analytics_only_col is
        # nullable, so no TD-043 trip either.
        monkeypatch.setattr(sd, 'loadServerNotNullNoDefault',
                            lambda: {})
        monkeypatch.setattr(sd, 'syncedPiTables', lambda: frozenset({'t'}))

        rc = sd.main([])

        assert rc == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        # Drift IS reported for visibility...
        assert parsed['summary']['tablesWithDrift'] == ['t']
        # ...but the gate-trip list is empty.
        assert parsed['summary']['tablesWithPiOnlyDrift'] == []
        assert parsed['summary']['tablesWithRequiredColumnGap'] == []

    def test_main_serverRequiresColumnPiOmits_exits1(
        self, monkeypatch, capsys,
    ) -> None:
        """The TD-043 production scenario: server requires column Pi omits.

        Mirrors the 2026-05-01 chi-srv-01 state pre-v0006: server has
        ``device_id NOT NULL`` (no default), Pi sync writer omits it,
        every INSERT fails.  Gate must trip exit-1 so CI catches it
        before next deploy.
        """
        monkeypatch.setattr(sd, 'loadPiSchema',
                            lambda: {'drive_summary': {'drive_id'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {
                                'drive_summary': {'drive_id', 'device_id'},
                            })
        monkeypatch.setattr(sd, 'loadServerNotNullNoDefault',
                            lambda: {'drive_summary': {'device_id'}})
        monkeypatch.setattr(sd, 'syncedPiTables',
                            lambda: frozenset({'drive_summary'}))

        rc = sd.main([])

        assert rc == 1
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert (
            parsed['summary']['tablesWithRequiredColumnGap']
            == ['drive_summary']
        )
        assert (
            parsed['serverRequiredColumnsMissingOnPi']['drive_summary']
            == ['device_id']
        )


# ================================================================================
# US-607 / TD-079 -- the Pi loader must see every SYNCED Pi table
# ================================================================================


def _syncRegistries():  # noqa: ANN202 -- test helper
    """Return the two live sync registries, or skip if the Pi stack won't import."""
    root = str(_PROJECT_ROOT)
    src = str(_PROJECT_ROOT / 'src')
    added = [p for p in (root, src) if p not in sys.path]
    for path in added:
        sys.path.insert(0, path)
    try:
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC
        from src.pi.data.sync_log import PK_COLUMN
    except ImportError as err:  # pragma: no cover -- env guard
        pytest.skip(f'Pi sync registries not importable: {err}')
    finally:
        for path in added:
            try:
                sys.path.remove(path)
            except ValueError:
                pass
    return PK_COLUMN, SNAPSHOT_SYNC


class TestSyncedPiTables:
    """``syncedPiTables()`` is the two live registries, never a hand-kept list.

    TD-079's class is "a hand-kept inventory of a growing set".  A guard whose
    OWN subject is a second hand-kept list would reproduce the defect inside the
    fix for it, so the subject is computed from the registries the sync client
    itself reads, on every call.
    """

    def test_syncedPiTables_isExactlyTheDeltaAndSnapshotRegistries(self) -> None:
        pkColumn, snapshotSync = _syncRegistries()

        assert sd.syncedPiTables() == frozenset(pkColumn) | frozenset(snapshotSync)

    def test_syncedPiTables_agreesWithTheA4AuditsSyncedSet(self) -> None:
        """The residual: TWO modules now read these registries, so pin agreement.

        ``scripts/audit_sync_contract_parity.syncedTables()`` derives the same
        set for the US-543 gate.  Neither is a copy of the other's declaration
        -- both read the same SSOT -- but two readers can still drift if one
        gains a third wire path and the other does not.  That is the only way
        this guard can go quietly wrong, so it is asserted rather than assumed.
        """
        try:
            from scripts.audit_sync_contract_parity import syncedTables
        except ImportError as err:  # pragma: no cover -- env guard
            pytest.skip(f'A-4 audit module not importable: {err}')

        assert sd.syncedPiTables() == frozenset(syncedTables())

    def test_syncedPiTables_newDeltaRegistration_isSeenWithoutEditingTheGuard(
        self, monkeypatch,
    ) -> None:
        """A table registered for sync tomorrow is in the subject the same day."""
        pkColumn, _ = _syncRegistries()
        monkeypatch.setitem(pkColumn, 'edr_event_vault', 'id')

        assert 'edr_event_vault' in sd.syncedPiTables()

    def test_syncedPiTables_newSnapshotRegistration_isAlsoSeen(
        self, monkeypatch,
    ) -> None:
        """US-416 added a SECOND wire path; watching only one is not the set."""
        _, snapshotSync = _syncRegistries()
        from src.common.sync.snapshot_registry import SnapshotSyncSpec

        monkeypatch.setitem(
            snapshotSync, 'edr_snapshot',
            SnapshotSyncSpec(naturalKeyCols=('event_id',), cursorCol='recorded_at'),
        )

        assert 'edr_snapshot' in sd.syncedPiTables()


class TestPiLoaderSeesEverySyncedTable:
    """The acceptance predicate, over the WHOLE set rather than one table."""

    def test_loadPiSchema_seesEverySyncedPiTable(self) -> None:
        """TD-079's standing gate: no synced Pi table is invisible to the loader.

        This is the assertion the story asks for, and it is the one that cannot
        go stale: adding ``dtc_freeze_frame`` to the registry fixes today, this
        fails loudly on the next ensureX-only table instead of reporting the
        gate clean over a table it cannot see.
        """
        invisible = sorted(sd.syncedPiTables() - set(sd.loadPiSchema()))

        assert not invisible, (
            f'tables registered for sync that scripts/schema_diff.loadPiSchema '
            f'cannot see: {invisible}. The Pi<->server drift gate reports '
            f'nothing about these -- worse, it reads the server copy and '
            f'classifies them as SERVER-ONLY, which is documented as '
            f'tier-owned and gate-exempt. Add each one to the registry in '
            f'loadPiSchema().'
        )

    def test_loadPiSchema_includesDtcFreezeFrameWithItsCaptureColumns(self) -> None:
        """The live instance TD-079 was filed for (US-368 ensureDtcFreezeFrameTable).

        Named explicitly as well as covered by the predicate above: the
        7-column shape is what US-543 measured as ``appliedOnly`` when the two
        Pi loaders disagreed, so pinning it here makes the two records
        comparable by column and not just by table name.
        """
        columns = sd.loadPiSchema()['dtc_freeze_frame']

        assert columns == {
            'id', 'dtc_log_id', 'captured_at_timestamp_utc',
            'pid_responses_json', 'vehicle_info_vin', 'notes', 'data_source',
        }


class TestBlindSpotGate:
    """A synced table the Pi loader cannot see must FAIL, never read as clean."""

    def test_computeDiff_syncedTableMissingFromPiSchema_isReported(self) -> None:
        result = sd.computeDiff(
            {'t': {'id'}}, {'t': {'id'}},
            syncedTables={'t', 'ghost_table'},
        )

        assert (
            result['summary']['syncedTablesInvisibleToPiLoader']
            == ['ghost_table']
        )

    def test_computeDiff_everySyncedTableVisible_reportsEmptyNotAbsent(
        self,
    ) -> None:
        """Positive control: the key is present and empty, so green is legible.

        An absent key and a clean result must not look the same -- that
        ambiguity is how a rule silently stops running.
        """
        result = sd.computeDiff(
            {'t': {'id'}}, {'t': {'id'}}, syncedTables={'t'},
        )

        assert result['summary']['syncedTablesInvisibleToPiLoader'] == []

    def test_computeDiff_withoutSyncedTablesArg_ruleIsOmitted(self) -> None:
        """Back-compat with the US-249/US-256 callers, as the TD-043 rule did."""
        result = sd.computeDiff({'t': {'id'}}, {'t': {'id'}})

        assert 'syncedTablesInvisibleToPiLoader' not in result['summary']

    def test_computeDiff_blindSpotIsSortedAndDeterministic(self) -> None:
        result = sd.computeDiff(
            {}, {}, syncedTables={'zulu', 'alpha', 'mike'},
        )

        assert (
            result['summary']['syncedTablesInvisibleToPiLoader']
            == ['alpha', 'mike', 'zulu']
        )

    def test_main_syncedTableInvisibleToPiLoader_exits1AndNamesIt(
        self, monkeypatch, capsys,
    ) -> None:
        """A blind spot alone trips the gate, with no column drift anywhere.

        The discriminator against the pre-US-607 behaviour: the shared tables
        really ARE clean here, so the ONLY thing that can produce a non-zero
        exit is the blindness itself.
        """
        monkeypatch.setattr(sd, 'loadPiSchema', lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {'t': {'id'}, 'ghost_table': {'id'}})
        monkeypatch.setattr(sd, 'loadServerNotNullNoDefault', lambda: {})
        monkeypatch.setattr(sd, 'syncedPiTables',
                            lambda: frozenset({'t', 'ghost_table'}))

        rc = sd.main([])

        parsed = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert parsed['summary']['tablesWithPiOnlyDrift'] == []
        assert parsed['summary']['tablesWithRequiredColumnGap'] == []
        assert (
            parsed['summary']['syncedTablesInvisibleToPiLoader']
            == ['ghost_table']
        )

    def test_main_blindSpotIsNamedInTheHumanSummary(
        self, monkeypatch, capsys,
    ) -> None:
        """The operator reading --verbose must see the table name, not a count."""
        monkeypatch.setattr(sd, 'loadPiSchema', lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'loadServerSchema', lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'loadServerNotNullNoDefault', lambda: {})
        monkeypatch.setattr(sd, 'syncedPiTables',
                            lambda: frozenset({'t', 'ghost_table'}))

        sd.main(['--verbose'])

        assert 'ghost_table' in capsys.readouterr().err

    def test_realGate_newEnsureXTableRegisteredForSync_isNotReportedClean(
        self, monkeypatch, capsys,
    ) -> None:
        """US-607 validationCriterion 2, executed against the REAL loaders.

        Register a table for sync the way a real story would -- an ``ensureX``
        helper creates it and ``PK_COLUMN`` gains an entry -- WITHOUT adding it
        to ``loadPiSchema``'s registry, which is precisely what US-368/US-369
        did.  The gate must not report 'shared tables clean'.

        The whole-set predicate, not an entry for one table: this drill uses a
        name that appears nowhere in ``schema_diff.py``, so it can only pass by
        the rule being general.

        NOTE ON WHAT IS *NOT* ASSERTED, and it is a finding rather than an
        omission.  The obvious assertion here is ``main() == 1``.  It is not
        made, because on this tree it is TRUE EITHER WAY: the real gate already
        exits 1 on pre-existing ``power_log`` / ``startup_log`` / ``vehicle_info``
        drift, so an exit code cannot distinguish "the blind spot was caught"
        from "the gate was already red for unrelated reasons".  Measured, not
        assumed -- a mutation that removed the blind-spot term from main()'s
        return left this test GREEN while the hermetic sibling above died.  The
        summary key is the discriminator, so the summary key is the assertion.
        """
        pkColumn, _ = _syncRegistries()
        monkeypatch.setitem(pkColumn, 'edr_event_vault', 'id')
        try:
            sd.main([])
        except ImportError as err:  # pragma: no cover -- env guard
            pytest.skip(f'server stack not importable: {err}')

        parsed = json.loads(capsys.readouterr().out)
        assert 'edr_event_vault' in (
            parsed['summary']['syncedTablesInvisibleToPiLoader']
        )
        # ...and it is NOT filed under the category that means "tier-owned,
        # nothing to check here", which is where dtc_freeze_frame sat for four
        # sprints.  Being listed somewhere harmless is how this defect hid.
        assert 'edr_event_vault' not in parsed['tablesOnlyInServer']


# ================================================================================
# US-711 / F-138 -- the THIRD by-design class: cross-tier RESOLVED columns
# ================================================================================


class TestComputeDiffCrossTierResolvedColumns:
    """``dtc_freeze_frame``'s bespoke resolver is by design, not silent data loss.

    US-607 restored the gate's sight of ``dtc_freeze_frame`` and the first thing
    it reported was a FALSE TD-039 trip.  The gate knew two by-design classes --
    server mirror adornments (:data:`SERVER_MIRROR_COLUMNS`) and PK rename pairs
    (:data:`PI_PK_RENAMED_TO_ID`) -- and had no mechanism for the third.

    US-369 gave ``dtc_freeze_frame`` a bespoke server resolver
    (``api/sync._syncDtcFreezeFrameRows``) which RENAMES ``vehicle_info_vin`` to
    the server's ``vehicle_info_id`` and deliberately DROPS ``data_source`` (the
    freeze frame's origin is carried by its parent ``dtc_log`` row).  The rows
    land.  Reporting them as data loss is the drift gate drifting.

    The declaration itself is policed from both sides by
    ``audit_sync_contract_parity.checkCrossTierResolverDeclaration``; these tests
    cover only what THIS gate does with it.
    """

    def test_computeDiff_crossTierRenamedColumn_notFlagged(self) -> None:
        """Given: Pi has vehicle_info_vin, server has its declared target.
        Then: neither side appears as drift -- it is one column, resolved.
        """
        pi = {'dtc_freeze_frame': {'id', 'dtc_log_id', 'vehicle_info_vin'}}
        server = {'dtc_freeze_frame': {'id', 'dtc_log_id', 'vehicle_info_id'}}

        result = sd.computeDiff(pi, server)

        assert result['sharedTableDrift'] == {}
        assert result['summary']['tablesWithDrift'] == []
        assert result['summary']['tablesWithPiOnlyDrift'] == []

    def test_computeDiff_crossTierDroppedColumn_notFlagged(self) -> None:
        """A column the resolver consumes and does not store is not data loss."""
        pi = {'dtc_freeze_frame': {'id', 'dtc_log_id', 'data_source'}}
        server = {'dtc_freeze_frame': {'id', 'dtc_log_id'}}

        result = sd.computeDiff(pi, server)

        assert result['sharedTableDrift'] == {}
        assert result['summary']['tablesWithPiOnlyDrift'] == []

    def test_computeDiff_resolverTargetMissingOnServer_stillTrips(self) -> None:
        """The suppression is CONDITIONAL on the target existing, as the PK rule is.

        This is the pairing that keeps the exemption honest.  A filter that
        suppressed ``vehicle_info_vin`` unconditionally would pass every test
        above and would ALSO hide the one case that really is data loss: a
        resolver writing a column the server does not have.  ``PI_PK_RENAMED_TO_ID``
        already works this way (``renamedPk in piCols and 'id' in serverCols``);
        the third class follows the precedent rather than inventing a looser one.
        """
        pi = {'dtc_freeze_frame': {'id', 'vehicle_info_vin'}}
        server = {'dtc_freeze_frame': {'id'}}

        result = sd.computeDiff(pi, server)

        assert (
            result['sharedTableDrift']['dtc_freeze_frame']['columnsOnlyInPi']
            == ['vehicle_info_vin']
        )
        assert result['summary']['tablesWithPiOnlyDrift'] == ['dtc_freeze_frame']

    def test_computeDiff_droppedColumnAlsoOnServer_isNotTurnedIntoServerOnlyDrift(
        self,
    ) -> None:
        """Stripping the Pi side unconditionally would MANUFACTURE drift here.

        If the server gains a column declared dropped, the two sides now AGREE
        and there is nothing to suppress.  Removing ``data_source`` from the Pi
        set anyway would leave the server's copy sitting alone in
        ``columnsOnlyInServer`` -- an exemption inventing the very finding it
        exists to remove.  (That the drop declaration is now STALE is a real
        problem, and it is ``checkCrossTierResolverDeclaration``'s to report;
        this gate must not report it as a phantom column instead.)
        """
        pi = {'dtc_freeze_frame': {'id', 'data_source'}}
        server = {'dtc_freeze_frame': {'id', 'data_source'}}

        result = sd.computeDiff(pi, server)

        assert result['sharedTableDrift'] == {}

    def test_computeDiff_unresolvedPiColumnOnResolvedTable_stillTrips(self) -> None:
        """The exemption is per COLUMN, not a blanket pass for the whole table.

        ``dtc_freeze_frame`` has a resolver, which must not make it exempt from
        the gate.  A genuinely new Pi column on that table is still TD-039.
        """
        pi = {'dtc_freeze_frame': {'id', 'vehicle_info_vin', 'invented_column'}}
        server = {'dtc_freeze_frame': {'id', 'vehicle_info_id'}}

        result = sd.computeDiff(pi, server)

        assert (
            result['sharedTableDrift']['dtc_freeze_frame']['columnsOnlyInPi']
            == ['invented_column']
        )
        assert result['summary']['tablesWithPiOnlyDrift'] == ['dtc_freeze_frame']


class TestCrossTierResolvedColumnsIsDeclaredOnce:
    """US-711's structural half: the declaration MOVED, it was not COPIED.

    Two copies of one by-design list is exactly the duplication that lets them
    drift -- and a drift gate that drifts is this sprint's own theme wearing a
    different hat.  The tidy fix (``schema_diff`` READS the audit module's
    declaration) is impossible: ``audit_sync_contract_parity`` already imports
    ``SERVER_MIRROR_COLUMNS`` FROM ``schema_diff`` at module level, so that
    import would be circular.  Hence the declaration moved to the module that is
    already downstream of nothing, beside the two by-design classes it joins.
    """

    def test_crossTierResolvedColumns_hasExactlyOneDefinitionInTheTree(
        self,
    ) -> None:
        """VC2: one module-level assignment, repo-wide.  Imports do not count."""
        pattern = re.compile(
            r'^CROSS_TIER_RESOLVED_COLUMNS\s*(:[^=]*)?=', re.MULTILINE,
        )
        definitions = []
        for root in ('scripts', 'src', 'tests', 'tools'):
            rootPath = _PROJECT_ROOT / root
            assert rootPath.is_dir(), (
                f'{root!r} is not a directory -- an empty walk over a missing '
                f'path is byte-identical to a clean tree'
            )
            for path in rootPath.rglob('*.py'):
                if pattern.search(path.read_text(encoding='utf-8')):
                    definitions.append(str(path.relative_to(_PROJECT_ROOT)))

        assert definitions == [str(Path('scripts') / 'schema_diff.py')], (
            f'expected exactly ONE declaration of CROSS_TIER_RESOLVED_COLUMNS, '
            f'found {definitions}. schema_diff owns it; every other module '
            f'imports it.'
        )

    def test_crossTierResolvedColumns_declaresBothTransformKinds(self) -> None:
        """Non-degeneracy: the declaration is real, and carries BOTH shapes.

        A rename (target name) and a drop (``None``) take different branches in
        ``computeDiff``.  A declaration that lost either kind would leave one
        branch untested by the real data while the synthetic tests above still
        passed.
        """
        resolved = sd.CROSS_TIER_RESOLVED_COLUMNS

        assert resolved['dtc_freeze_frame'] == {
            'vehicle_info_vin': 'vehicle_info_id',
            'data_source': None,
        }

    def test_auditModuleReadsTheSameObject_notACopy(self) -> None:
        """The audit module must hold THIS dict, identically -- not an equal one.

        Equality would pass for a copy that has not drifted yet, which is the
        state every drifted pair starts in.  Identity is the assertion.

        Both sides are read through the ``scripts`` package on purpose.  The
        module-level ``sd`` in this file is loaded by PATH under the bare
        ``schema_diff`` key, so ``sd`` and ``scripts.schema_diff`` are two
        distinct module objects with two distinct (equal) dicts -- comparing
        across them measures this file's loader, not the production wiring.
        """
        try:
            from scripts import audit_sync_contract_parity as parity
            from scripts import schema_diff as packaged
        except ImportError as err:  # pragma: no cover -- env guard
            pytest.skip(f'A-4 audit module not importable: {err}')

        assert (
            parity.CROSS_TIER_RESOLVED_COLUMNS
            is packaged.CROSS_TIER_RESOLVED_COLUMNS
        )

    def test_bothGateModulesImportCleanly_inAFreshInterpreter(self) -> None:
        """VC4: no circular import -- and it MUST be a fresh process.

        In-process this is unfalsifiable: ``sys.modules`` is already populated by
        the time any test runs, so a genuine cycle imports fine.  A subprocess is
        the only place the cycle can actually bite.
        """
        result = subprocess.run(
            [sys.executable, '-c',
             'import scripts.schema_diff; '
             'import scripts.audit_sync_contract_parity'],
            cwd=str(_PROJECT_ROOT), capture_output=True, text=True,
            encoding='utf-8', timeout=120, check=False,
        )

        assert result.returncode == 0, (
            f'circular import between the two gate modules:\n{result.stderr}'
        )


class TestRealTreeCrossTierResolution:
    """VC1, against the REAL loaders: the false trip is gone, real trips remain."""

    def test_realSchemas_dtcFreezeFrameNoLongerTripsTd039(self) -> None:
        """The measurement US-711 was filed on, re-run as a standing assertion."""
        try:
            server = sd.loadServerSchema()
        except ImportError:  # pragma: no cover -- env guard
            pytest.skip('SQLAlchemy not available in this env')

        result = sd.computeDiff(sd.loadPiSchema(), server)

        assert 'dtc_freeze_frame' not in (
            result['summary']['tablesWithPiOnlyDrift']
        )
        assert 'dtc_freeze_frame' not in result['sharedTableDrift'], (
            'both halves of the resolver pair must clear: vehicle_info_vin/'
            '_id is ONE column, so suppressing only the Pi side would leave '
            'vehicle_info_id alone in columnsOnlyInServer'
        )

    def test_realSchemas_genuineTd039TripsStillReport(self) -> None:
        """The pairing.  A filter that suppressed everything passes the test above.

        ``power_log`` and ``startup_log`` are the STANDING TD-039 trips this gate
        exists to carry (Pi columns with nowhere to land).  They have no resolver
        and must be untouched by the new exemption.
        """
        try:
            server = sd.loadServerSchema()
        except ImportError:  # pragma: no cover -- env guard
            pytest.skip('SQLAlchemy not available in this env')

        result = sd.computeDiff(sd.loadPiSchema(), server)

        assert 'power_log' in result['summary']['tablesWithPiOnlyDrift']
        assert 'startup_log' in result['summary']['tablesWithPiOnlyDrift']


# ================================================================================
# US-712 / F-138 -- WHICH condition tripped, not merely THAT one did
# ================================================================================


class TestGateTripsNameTheCondition:
    """``summary.gateTrips`` names every rule that fired, so a test can assert one.

    THE DEFECT THIS CLOSES, and it was measured inside US-607 rather than
    theorised.  ``main()`` returned ``1 if (piOnlyTrip or requiredGapTrip or
    blindSpotTrip) else 0``.  On this tree TD-039 (``power_log`` /
    ``startup_log``) and TD-043 (``vehicle_info``) are BOTH standing red, so
    ``1`` is already the answer for two unrelated reasons.  A drill asserting
    ``main() == 1`` therefore survived a mutation that deleted the blind-spot
    term from the exit code entirely -- it proved nothing it claimed to prove.

    The fix is not a cleverer exit code (see the story's conditionalOutcome).
    It is that the terms are enumerated in exactly ONE place,
    :data:`~schema_diff.GATE_RULES`, that the enumeration is REPORTED, and that
    the exit code is DERIVED from the report.  A rule cannot then be dropped
    from the exit code without disappearing from the JSON, where these tests
    name it.
    """

    def test_gateTrips_noRuleFires_isEmptyList(self) -> None:
        """Given: both tiers agree and every rule ran.
        Then: gateTrips is an empty list -- present and empty, not absent.
        """
        pi = {'t': {'id', 'value'}}
        server = {'t': {'id', 'value'}}

        result = sd.computeDiff(pi, server, {}, {'t'})

        assert result['summary']['gateTrips'] == []

    def test_gateTrips_piOnlyDrift_namesTd039AndNothingElse(self) -> None:
        """Given: Pi has a column the server lacks; the other two rules are clean.
        Then: gateTrips is exactly ['TD-039'].
        """
        pi = {'t': {'id', 'pi_extra'}}
        server = {'t': {'id'}}

        result = sd.computeDiff(pi, server, {}, {'t'})

        assert result['summary']['gateTrips'] == ['TD-039']

    def test_gateTrips_requiredColumnGap_namesTd043AndNothingElse(self) -> None:
        """Given: server requires a column the Pi never populates.
        Then: gateTrips is exactly ['TD-043'] -- TD-039 did not fire.
        """
        pi = {'t': {'id'}}
        server = {'t': {'id', 'device_id'}}

        result = sd.computeDiff(pi, server, {'t': {'device_id'}}, {'t'})

        assert result['summary']['gateTrips'] == ['TD-043']

    def test_gateTrips_blindSpotOnly_namesTd079AndNothingElse(self) -> None:
        """THE DISCRIMINATOR the old exit code could not express.

        Shared tables are genuinely clean and no required column is missing, so
        the ONLY thing that can appear here is the blindness itself.  Under the
        old ``or``-chain this scenario and the two above were all indistinguishably
        ``1``.
        """
        pi = {'t': {'id'}}
        server = {'t': {'id'}, 'ghost_table': {'id'}}

        result = sd.computeDiff(pi, server, {}, {'t', 'ghost_table'})

        assert result['summary']['gateTrips'] == ['TD-079']

    def test_gateTrips_allThreeFire_namesAllThreeDeterministically(self) -> None:
        """Given: every rule trips at once.
        Then: all three are named, in a stable order (CI diffs stay readable).
        """
        pi = {'t': {'id', 'pi_extra'}}
        server = {'t': {'id', 'device_id'}, 'ghost_table': {'id'}}

        result = sd.computeDiff(
            pi, server, {'t': {'device_id'}}, {'t', 'ghost_table'},
        )

        assert result['summary']['gateTrips'] == ['TD-039', 'TD-043', 'TD-079']

    def test_gateTrips_ruleThatDidNotRun_isNotNamed(self) -> None:
        """A rule that never RAN must not be reported as a trip.

        The two-arg back-compat call omits the TD-043 and TD-079 rules entirely.
        'Did not run' and 'ran and found nothing' are different answers; neither
        is a trip, so neither appears -- but the per-rule keys stay the place
        that distinction is readable (TD-079 reports ``[]`` vs absent).
        """
        pi = {'t': {'id', 'pi_extra'}}
        server = {'t': {'id'}}

        result = sd.computeDiff(pi, server)

        assert result['summary']['gateTrips'] == ['TD-039']
        assert 'tablesWithRequiredColumnGap' not in result['summary']
        assert 'syncedTablesInvisibleToPiLoader' not in result['summary']

    def test_gateTrips_everyRegisteredRuleKey_isARealSummaryKey(self) -> None:
        """GATE_RULES must not name a summary key that computeDiff never emits.

        A rule registered under a misspelt or renamed key would silently never
        fire -- the exact "gate that cannot see" class TD-079 is about, one level
        up.  Run with every rule enabled so all keys are expected present.
        """
        result = sd.computeDiff({'t': {'id'}}, {'t': {'id'}}, {}, {'t'})

        for ruleId, summaryKey in sd.GATE_RULES:
            assert summaryKey in result['summary'], (
                f'GATE_RULES registers {ruleId} under summary key '
                f'{summaryKey!r}, which computeDiff does not emit -- that rule '
                f'can never trip'
            )


class TestExitCodeIsDerivedFromTheNamedTrips:
    """The structural half: main() may not re-enumerate the rules."""

    def test_main_doesNotRestateTheRuleKeys_gateTripsIsTheSingleSource(
        self,
    ) -> None:
        """WHY THIS TEST EXISTS, and it is the whole point of the story.

        Every behavioural test below can be satisfied by a ``main()`` that keeps
        its own parallel ``or``-chain and happens to agree with ``gateTrips``
        today.  That is the pre-US-712 shape with a report bolted on beside it,
        and it re-opens the defect the moment a FOURTH rule is added to one list
        and not the other -- which is precisely how the third rule arrived
        (US-607) and how the by-design list drifted (US-711).

        So the assertion is structural: ``main`` must not mention any per-rule
        summary key at all.  It reads the derived list, and nothing else.
        """
        source = inspect.getsource(sd.main)

        for ruleId, summaryKey in sd.GATE_RULES:
            assert summaryKey not in source, (
                f'main() names {summaryKey!r} ({ruleId}) directly, so the rule '
                f'set is enumerated in two places and can drift between them. '
                f'Derive the exit code from summary["gateTrips"] instead.'
            )
        assert 'gateTrips' in source, (
            "main() must derive its exit code from summary['gateTrips']"
        )

    def test_main_cleanEverything_exits0(self, monkeypatch, capsys) -> None:
        """Empty gateTrips is still exit 0 -- the contract did not change."""
        monkeypatch.setattr(sd, 'loadPiSchema', lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'loadServerSchema', lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'loadServerNotNullNoDefault', lambda: {})
        monkeypatch.setattr(sd, 'syncedPiTables', lambda: frozenset({'t'}))

        rc = sd.main([])

        assert rc == 0
        assert json.loads(capsys.readouterr().out)['summary']['gateTrips'] == []

    def test_main_blindSpotOnly_exits1AndTd079IsTheNamedReason(
        self, monkeypatch, capsys,
    ) -> None:
        """The hermetic drill: exit 1 AND the JSON says which rule earned it."""
        monkeypatch.setattr(sd, 'loadPiSchema', lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {'t': {'id'}, 'ghost_table': {'id'}})
        monkeypatch.setattr(sd, 'loadServerNotNullNoDefault', lambda: {})
        monkeypatch.setattr(sd, 'syncedPiTables',
                            lambda: frozenset({'t', 'ghost_table'}))

        rc = sd.main([])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)['summary']['gateTrips'] == [
            'TD-079',
        ]

    def test_verboseSummary_namesTheTrippedRules_forTheOperator(
        self, monkeypatch, capsys,
    ) -> None:
        """The human reading --verbose gets the same answer as the machine."""
        monkeypatch.setattr(sd, 'loadPiSchema', lambda: {'t': {'id'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {'t': {'id'}, 'ghost_table': {'id'}})
        monkeypatch.setattr(sd, 'loadServerNotNullNoDefault', lambda: {})
        monkeypatch.setattr(sd, 'syncedPiTables',
                            lambda: frozenset({'t', 'ghost_table'}))

        sd.main(['--verbose'])

        err = capsys.readouterr().err
        assert 'TD-079' in err
        assert re.search(r'TRIPPED:\s+TD-079', err), (
            f'verbose output must state the tripped rule set:\n{err}'
        )


class TestRealTreeStandingConditionsAreIndividuallyIdentifiable:
    """US-712 validationCriterion 2, executed against the REAL loaders.

    This is the general case of the US-607 finding.  On this tree the gate is
    standing red for TWO reasons at once, and the two are what a bare ``1``
    cannot tell apart.  Delete the TD-039 term and the process still exits 1 on
    TD-043 -- but THIS test fails, naming TD-039.  That is the acceptance.
    """

    def _realDiff(self):  # noqa: ANN202 -- test helper
        try:
            server = sd.loadServerSchema()
            notNull = sd.loadServerNotNullNoDefault()
        except ImportError as err:  # pragma: no cover -- env guard
            pytest.skip(f'server stack not importable: {err}')
        return sd.computeDiff(
            sd.loadPiSchema(), server, notNull, sd.syncedPiTables(),
        )

    def test_realGate_standingTd039IsNamed_notCollapsedIntoTheExitCode(
        self,
    ) -> None:
        """TD-039 stands on power_log / startup_log and must be named as itself."""
        result = self._realDiff()

        assert 'TD-039' in result['summary']['gateTrips'], (
            'power_log / startup_log carry Pi columns the server lacks; the '
            'report must attribute the trip to TD-039 by name'
        )

    def test_realGate_standingTd043IsNamed_separatelyFromTd039(self) -> None:
        """The pairing.  Two rules, two names -- this is what `1` could not say."""
        result = self._realDiff()

        assert 'TD-043' in result['summary']['gateTrips'], (
            'vehicle_info requires ecu_id / ecu_signature / '
            'ecu_install_timestamp_utc, which the Pi never populates'
        )

    def test_realGate_td079IsCleanToday_andSaysSoRatherThanBeingUnknowable(
        self,
    ) -> None:
        """The negative half, and it is load-bearing.

        Without it a gateTrips that simply named all three rules unconditionally
        would pass both tests above.  TD-079 is genuinely green on this tree
        (US-607 closed it), so it must be ABSENT from the trip list while the
        other two are present.
        """
        result = self._realDiff()

        assert 'TD-079' not in result['summary']['gateTrips']
        assert result['summary']['syncedTablesInvisibleToPiLoader'] == []
