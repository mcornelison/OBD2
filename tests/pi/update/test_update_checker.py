################################################################################
# File Name: test_update_checker.py
# Purpose/Description: Outcome tests for the Pi UpdateChecker (US-247 / B-047
#                      US-C). Asserts the marker-write decision under newer-
#                      server / same-version / older-server / network-error /
#                      drive-in-progress / disabled scenarios.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial implementation for US-247
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.update.update_checker`.

The story invariant for US-247 is the marker-file write decision: a marker
must appear on disk only when the server reports a NEWER version than the
local ``.deploy-version`` AND no drive is in progress.  The disabled /
drive-active / same-version / older-server / network-error paths must all
leave the marker untouched.

All tests inject a fake ``httpOpener`` so no sockets open.  Local
``.deploy-version`` and the marker file are both written into ``tmp_path``
so each test runs in isolation.
"""

from __future__ import annotations

import io
import json
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.pi.update.update_checker import (
    CheckOutcome,
    CheckResult,
    UpdateChecker,
)

# =============================================================================
# Helpers / fixtures
# =============================================================================


def _writeLocalDeployVersion(path: Path, version: str = "V0.19.0") -> None:
    """Write a US-241-shaped record at ``path`` for the local-version source."""
    record = {
        "version": version,
        "releasedAt": "2026-04-29T08:29:24Z",
        "gitHash": "d8583d3",
        "theme": "test sprint",
        "description": "local deploy stamp",
    }
    path.write_text(json.dumps(record))


def _serverRecord(version: str = "V0.20.0") -> dict[str, Any]:
    """Build a server release record matching GET /api/v1/release/current."""
    return {
        "version": version,
        "releasedAt": "2026-04-30T12:00:00Z",
        "gitHash": "abcdef0",
        "theme": "test sprint",
        "description": "server release",
    }


def _baseConfig(
    *,
    enabled: bool = True,
    localVersionPath: str = ".deploy-version",
    markerFilePath: str = "/var/lib/eclipse-obd/update-pending.json",
    intervalMinutes: int = 60,
    apiKeyEnv: str = "COMPANION_API_KEY",
    baseUrl: str = "http://10.27.27.10:8000",
) -> dict[str, Any]:
    """Pi config dict carrying the keys UpdateChecker reads."""
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "companionService": {
                "enabled": True,
                "baseUrl": baseUrl,
                "apiKeyEnv": apiKeyEnv,
                "syncTimeoutSeconds": 30,
            },
            "update": {
                "enabled": enabled,
                "intervalMinutes": intervalMinutes,
                "markerFilePath": markerFilePath,
                "localVersionPath": localVersionPath,
            },
        },
    }


class _FakeResponse:
    """Minimal context-manager wrapper that mimics ``urllib`` response."""

    def __init__(self, body: bytes = b"{}", status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _jsonOpener(payload: dict[str, Any], status: int = 200) -> Callable[..., Any]:
    """Opener that returns ``payload`` JSON-encoded; records each request."""
    calls: list[Any] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(req)
        return _FakeResponse(
            body=json.dumps(payload).encode("utf-8"),
            status=status,
        )

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _httpErrorOpener(code: int, reason: str = "Server Error") -> Callable[..., Any]:
    """Opener that always raises ``urllib.error.HTTPError`` with ``code``."""
    calls: list[int] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(code)
        raise urllib.error.HTTPError(
            url=getattr(req, "full_url", "http://test/"),
            code=code,
            msg=reason,
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _urlErrorOpener() -> Callable[..., Any]:
    """Opener that always raises ``URLError`` (DNS / connection refused)."""
    calls: list[int] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(1)
        raise urllib.error.URLError("Connection refused")

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-xyz")
    return "test-key-xyz"


# =============================================================================
# Newer / same / older version decision
# =============================================================================


class TestVersionComparisonDecision:
    """The core marker-write decision under varying server / local versions."""

    def test_checkForUpdates_serverNewer_writesMarkerFile(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """
        Given: local V0.19.0 + server V0.20.0
        When: check_for_updates runs
        Then: marker file written with {target_version, server_url, rationale, checked_at}
              AND result is UPDATE_AVAILABLE
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UPDATE_AVAILABLE
        assert marker.is_file()
        body = json.loads(marker.read_text())
        assert body["target_version"] == "V0.20.0"
        assert body["server_url"].startswith("http://10.27.27.10:8000")
        assert body["rationale"]
        assert body["checked_at"].endswith("Z")

    def test_checkForUpdates_serverSameVersion_noMarkerWritten(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """
        Given: local V0.19.0 + server V0.19.0
        Then: no marker on disk; result is UP_TO_DATE
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.19.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UP_TO_DATE
        assert not marker.exists()

    def test_checkForUpdates_serverOlder_noMarkerWritten(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """
        Given: local V0.19.0 + server V0.18.0 (downgrade scenario)
        Then: no marker on disk; result is UP_TO_DATE
              (downgrade is never auto-applied; rollback is operator-initiated)
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.18.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UP_TO_DATE
        assert not marker.exists()

    def test_checkForUpdates_existingMarkerOverwritten_onNewerServerVersion(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """
        Given: a prior marker file exists from an earlier check
        When: server now reports an even-newer version
        Then: marker is rewritten (target_version reflects the latest)
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "update-pending.json"
        marker.write_text(json.dumps({"target_version": "V0.20.0", "stale": True}))
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.21.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        checker.check_for_updates()

        body = json.loads(marker.read_text())
        assert body["target_version"] == "V0.21.0"
        assert "stale" not in body


# =============================================================================
# HTTP request shape
# =============================================================================


class TestHttpRequestShape:
    """The wire request must hit the registry endpoint with the API-key header."""

    def test_checkForUpdates_sendsXApiKeyHeader(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(tmp_path / "marker.json"),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        checker.check_for_updates()

        assert len(opener.calls) == 1  # type: ignore[attr-defined]
        req = opener.calls[0]  # type: ignore[attr-defined]
        # urllib normalizes header names to title-case ("X-Api-Key"); match
        # case-insensitively to keep the test independent of the quirk.
        headers = {k.lower(): v for k, v in req.header_items()}
        assert headers.get("x-api-key") == stubApiKey

    def test_checkForUpdates_hitsReleaseCurrentEndpoint(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(tmp_path / "marker.json"),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        checker.check_for_updates()

        req = opener.calls[0]  # type: ignore[attr-defined]
        assert req.full_url.endswith("/api/v1/release/current")
        assert req.get_method() == "GET"


# =============================================================================
# Network errors
# =============================================================================


class TestNetworkErrors:
    """Network failures must be non-fatal -- log + return NETWORK_ERROR, no marker."""

    def test_checkForUpdates_connectionRefused_returnsNetworkError(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "marker.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _urlErrorOpener()
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.NETWORK_ERROR
        assert not marker.exists()

    def test_checkForUpdates_serverHttp500_returnsNetworkError(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "marker.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _httpErrorOpener(500)
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.NETWORK_ERROR
        assert not marker.exists()

    def test_checkForUpdates_server503NoRecord_returnsServerNoRecord(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """
        Server reports 503 (no record stamped yet -- US-246 contract).
        The Pi must treat this as 'no update available' and skip cleanly.
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "marker.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _httpErrorOpener(503, reason="Service Unavailable")
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.SERVER_NO_RECORD
        assert not marker.exists()


# =============================================================================
# Drive-state gating
# =============================================================================


class TestDriveStateGating:
    """The 'drive-state-is-sacred' invariant -- never check during active drive."""

    def test_checkForUpdates_isDrivingTrue_skipsRequest(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "marker.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: True,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.SKIPPED_DRIVING
        assert len(opener.calls) == 0  # type: ignore[attr-defined]
        assert not marker.exists()

    def test_checkForUpdates_isDrivingFalse_proceedsNormally(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "marker.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UPDATE_AVAILABLE
        assert marker.is_file()


# =============================================================================
# Disabled / misconfigured paths
# =============================================================================


class TestDisabledPaths:
    """Configuration gates -- disabled, missing local file, missing API key."""

    def test_checkForUpdates_disabled_noRequestNoMarker(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "marker.json"
        config = _baseConfig(
            enabled=False,
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.DISABLED
        assert len(opener.calls) == 0  # type: ignore[attr-defined]
        assert not marker.exists()

    def test_checkForUpdates_localVersionMissing_returnsLocalVersionUnavailable(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """
        Pi has no .deploy-version yet (fresh untouched bench Pi).
        We cannot determine an update is needed without a local baseline,
        so the check skips with LOCAL_VERSION_UNAVAILABLE.
        """
        marker = tmp_path / "marker.json"
        config = _baseConfig(
            localVersionPath=str(tmp_path / "missing.json"),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.LOCAL_VERSION_UNAVAILABLE
        assert not marker.exists()

    def test_checkForUpdates_apiKeyMissing_returnsConfigError(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        COMPANION_API_KEY env var unset.  The check returns CONFIG_ERROR
        and writes no marker -- a misconfigured env must never produce a
        spurious update marker.
        """
        monkeypatch.delenv("COMPANION_API_KEY", raising=False)
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "marker.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.CONFIG_ERROR
        assert not marker.exists()


# =============================================================================
# Marker file parent-dir creation
# =============================================================================


class TestMarkerFileParentCreation:
    """The marker path may include a directory that does not yet exist."""

    def test_checkForUpdates_markerParentDirCreatedIfMissing(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        marker = tmp_path / "nested" / "subdir" / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UPDATE_AVAILABLE
        assert marker.is_file()


# =============================================================================
# CheckResult shape
# =============================================================================


class TestCheckResultShape:
    """CheckResult must carry the local + server versions when applicable."""

    def test_checkResult_carriesLocalAndServerVersions_onUpdateAvailable(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.19.0")
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(tmp_path / "marker.json"),
        )
        opener = _jsonOpener(_serverRecord(version="V0.20.0"))
        checker = UpdateChecker(config, httpOpener=opener)

        result: CheckResult = checker.check_for_updates()

        assert result.localVersion == "V0.19.0"
        assert result.serverVersion == "V0.20.0"
