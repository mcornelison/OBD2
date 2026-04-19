################################################################################
# File Name: test_sync_now.py
# Purpose/Description: Outcome-based tests for the manual sync CLI
#                      (scripts/sync_now.py).  Covers the four PushResult
#                      statuses (OK, EMPTY, FAILED, DISABLED), the exit-code
#                      contract (0 on all-success, 1 on any failure), the
#                      "nothing to sync" summary, and API-key masking.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-154
# ================================================================================
################################################################################

"""
Tests for :mod:`scripts.sync_now`.

SyncClient itself is covered by :mod:`tests.pi.sync.test_sync_client` -- these
tests focus on what the CLI layer adds: output formatting, exit codes, and
config-loading + masking.  All tests inject a fake SyncClient via the
``syncClientFactory`` hook so no real HTTP or SQLite happens.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import sync_now
from src.pi.sync import PushResult, PushStatus

# =============================================================================
# Helpers / fixtures
# =============================================================================


def _baseConfig() -> dict[str, Any]:
    """Minimal Pi config the CLI needs to render its start banner + run.

    Includes the top-level sections the ConfigValidator requires
    (``pi`` + ``server`` + ``protocolVersion`` + ``schemaVersion`` +
    ``deviceId``) so the real loader round-trips without complaint.
    """
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": "/tmp/pi-test.db"},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.10:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 3,
                "retryBackoffSeconds": [1, 2, 4, 8, 16],
            },
        },
        # Server section is required by the validator even though this CLI
        # never reads it (Pi-side code).
        "server": {},
    }


def _writeConfig(tmpPath: Path, config: dict[str, Any]) -> str:
    path = tmpPath / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return str(path)


class _FakeSyncClient:
    """Records calls + returns a scripted sequence of PushResult lists."""

    def __init__(
        self,
        results: list[PushResult],
        *,
        baseUrl: str = "http://srv",
        batchSize: int = 500,
        deviceId: str = "chi-eclipse-01",
        dbPath: str = ":memory:",
    ) -> None:
        self._results = results
        self.baseUrl = baseUrl
        self.batchSize = batchSize
        self.deviceId = deviceId
        self.dbPath = dbPath
        self.pushAllDeltasCalls = 0

    def pushAllDeltas(self) -> list[PushResult]:
        self.pushAllDeltasCalls += 1
        return list(self._results)


def _factoryReturning(client: _FakeSyncClient) -> Any:
    """Build a syncClientFactory(config) hook that returns the fixed client."""

    def _factory(_config: dict[str, Any]) -> _FakeSyncClient:
        return client

    return _factory


def _makeResult(
    tableName: str,
    status: PushStatus,
    *,
    rowsPushed: int = 0,
    batchId: str = "",
    reason: str = "",
    elapsed: float = 0.01,
) -> PushResult:
    return PushResult(
        tableName=tableName,
        rowsPushed=rowsPushed,
        batchId=batchId,
        elapsed=elapsed,
        status=status,
        reason=reason,
    )


@pytest.fixture
def cfgPath(tmp_path: Path) -> str:
    return _writeConfig(tmp_path, _baseConfig())


@pytest.fixture(autouse=True)
def _stubApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    """All tests assume COMPANION_API_KEY is present in the environment."""
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-abcdef123456")


# =============================================================================
# Exit codes and basic output
# =============================================================================


class TestExitCodes:
    """Exit 0 on all-success, 1 on any failure, 0 on all-DISABLED/EMPTY."""

    def test_allOk_exitsZero(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([
            _makeResult("alert_log", PushStatus.EMPTY),
            _makeResult(
                "realtime_data", PushStatus.OK,
                rowsPushed=5, batchId="chi-eclipse-01-2026-04-18T00:00:00Z",
            ),
        ])

        rc = sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "Status: OK" in out

    def test_anyFailure_exitsOne(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([
            _makeResult(
                "realtime_data", PushStatus.OK,
                rowsPushed=5, batchId="chi-eclipse-01-...",
            ),
            _makeResult(
                "statistics", PushStatus.FAILED,
                reason="URLError: Connection refused",
            ),
        ])

        rc = sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert rc == 1
        assert "Status: FAILED" in out
        assert "URLError" in out

    def test_allDisabled_exitsZero(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([
            _makeResult(t, PushStatus.DISABLED)
            for t in ("alert_log", "realtime_data", "statistics")
        ])

        rc = sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "Status: DISABLED" in out


# =============================================================================
# Output formatting (per-table + summary lines)
# =============================================================================


class TestOutputFormat:
    def test_startLine_containsBaseUrlAndBatchSize(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient(
            [_makeResult("realtime_data", PushStatus.EMPTY)],
            baseUrl="http://10.27.27.10:8000",
            batchSize=500,
        )

        sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert "Sync started" in out
        assert "baseUrl=http://10.27.27.10:8000" in out
        assert "batchSize=500" in out

    def test_okRow_rendersAsPushedAccepted(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([_makeResult(
            "realtime_data", PushStatus.OK,
            rowsPushed=247, batchId="batch-abc123",
        )])

        sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert "realtime_data" in out
        assert "247 new rows" in out
        assert "pushed" in out
        assert "accepted" in out
        assert "batch-abc123" in out

    def test_emptyRow_rendersAsNothingToSync(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([_makeResult("alert_log", PushStatus.EMPTY)])

        sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert "alert_log" in out
        assert "nothing to sync" in out.lower()

    def test_failedRow_rendersReason(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([_makeResult(
            "statistics", PushStatus.FAILED,
            reason="HTTP 500 Internal Server Error",
        )])

        sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert "statistics" in out
        assert "failed" in out.lower()
        assert "HTTP 500" in out

    def test_totalsLine_sumsAcrossTables(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([
            _makeResult("realtime_data", PushStatus.OK,
                        rowsPushed=247, batchId="b1"),
            _makeResult("statistics", PushStatus.OK,
                        rowsPushed=12, batchId="b2"),
            _makeResult("alert_log", PushStatus.EMPTY),
        ])

        sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert "Total: 259 rows pushed" in out
        assert "2 tables" in out  # count of OK-with-rows tables


# =============================================================================
# Nothing to sync / empty DB
# =============================================================================


class TestNothingToSync:
    def test_allEmpty_exitsZeroWithSummary(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([
            _makeResult(t, PushStatus.EMPTY)
            for t in ("alert_log", "realtime_data", "statistics")
        ])

        rc = sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "Total: 0 rows pushed" in out
        assert "Status: OK" in out


# =============================================================================
# --help / --dry-run
# =============================================================================


class TestCliFlags:
    def test_help_exitsZero(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            sync_now.parseArguments(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "sync_now" in out.lower() or "usage" in out.lower()

    def test_dryRun_doesNotPush(
        self, cfgPath: str, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Give the fake a real (empty) SQLite DB so the dry-run path can
        # open the sync_log table.  It's valid for the file not to exist
        # yet -- sync_log.initDb creates the table on first open.
        import sqlite3

        from src.pi.data import sync_log
        dbPath = str(tmp_path / "dryrun.db")
        conn = sqlite3.connect(dbPath)
        sync_log.initDb(conn)
        conn.close()

        fake = _FakeSyncClient(
            [_makeResult(
                "realtime_data", PushStatus.OK, rowsPushed=5, batchId="b1",
            )],
            dbPath=dbPath,
        )

        rc = sync_now.main(
            ["--config", cfgPath, "--dry-run"],
            syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert fake.pushAllDeltasCalls == 0
        assert "dry-run" in out.lower() or "dry run" in out.lower()


# =============================================================================
# API-key masking
# =============================================================================


class TestSecretMasking:
    def test_apiKey_neverAppearsInOutput(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No stdout line may contain the raw COMPANION_API_KEY value."""
        fake = _FakeSyncClient([
            _makeResult("realtime_data", PushStatus.OK,
                        rowsPushed=1, batchId="b1"),
        ])

        sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        # _stubApiKey fixture sets the key to test-key-abcdef123456
        assert "test-key-abcdef123456" not in out


# =============================================================================
# Unreachable server (FAILED propagates all the way through)
# =============================================================================


class TestUnreachableServer:
    def test_urlError_perTable_reportedAndExitsOne(
        self, cfgPath: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _FakeSyncClient([
            _makeResult(
                "realtime_data", PushStatus.FAILED,
                reason="URLError: Connection refused",
            ),
        ])

        rc = sync_now.main(
            ["--config", cfgPath], syncClientFactory=_factoryReturning(fake),
        )
        out = capsys.readouterr().out
        assert rc == 1
        assert "Connection refused" in out
        assert "Status: FAILED" in out


# =============================================================================
# Config resolution (--config override, missing file)
# =============================================================================


class TestConfigResolution:
    def test_missingConfig_exitsNonZero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        missing = str(tmp_path / "no-such-config.json")

        fake = _FakeSyncClient([])

        rc = sync_now.main(
            ["--config", missing], syncClientFactory=_factoryReturning(fake),
        )
        err = capsys.readouterr()
        combined = err.out + err.err
        assert rc != 0
        # The CLI should surface the missing-file problem to the operator.
        assert "no-such-config" in combined or "config" in combined.lower()
