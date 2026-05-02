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
import json
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
    """Exit-code contract: 0 = no drift in shared tables, 1 = drift present."""

    def test_main_cleanSchemas_exits0(self, monkeypatch, capsys) -> None:
        """When loaders return drift-free shared tables, main exits 0."""
        monkeypatch.setattr(sd, 'loadPiSchema',
                            lambda: {'t': {'id', 'value'}})
        monkeypatch.setattr(sd, 'loadServerSchema',
                            lambda: {'t': {'id', 'value'}})

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
