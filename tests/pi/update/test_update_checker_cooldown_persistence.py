################################################################################
# File Name: test_update_checker_cooldown_persistence.py
# Purpose/Description: B-047 D7 cooldown persistence audit (US-296).
#                      Asserts that UpdateChecker.check_for_updates honors a
#                      24-hour cooldown that survives reboots via a
#                      persisted timestamp file.  Pre-fix RED: the
#                      ``SKIPPED_COOLDOWN`` outcome does not exist + no
#                      timestamp persistence is wired -- a freshly-
#                      constructed UpdateChecker behaves as if the prior
#                      check never happened.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (US-296) | Initial -- 7 tests across 3 classes:
#               |              | reboot-persistence (3) + write-contract
#               |              | (2 -- success writes; failed-check does
#               |              | NOT) + defensive (2 -- no file / malformed).
# ================================================================================
################################################################################

"""B-047 D7 cooldown-persistence tests for :class:`UpdateChecker` (US-296).

Per B-047 D7 (CIO 2026-05-05): after EACH check completes -- regardless of
whether the server says ``UPDATE_AVAILABLE`` / ``UP_TO_DATE`` /
``SERVER_NO_RECORD`` -- a **24-hour cooldown** prevents subsequent checks.
Failed-check (``NETWORK_ERROR``) does NOT enter cooldown; the next eligible
trigger retries.  The cooldown survives reboots because the timestamp is
persisted to ``~/.cache/eclipse-obd/last-update-check.timestamp`` (path
configurable for tests + non-Pi hosts).

The story acceptance is "simulate-reboot scenario passes; would FAIL
pre-fix if no persistence is wired".  Each test below uses ``tmp_path`` for
both the local ``.deploy-version`` and the cooldown timestamp file, and
constructs a fresh :class:`UpdateChecker` after the on-disk timestamp is
written -- mirroring a Pi reboot where the in-memory state is lost but the
filesystem state survives.
"""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.pi.update.update_checker import (
    CheckOutcome,
    UpdateChecker,
)

# =============================================================================
# Helpers
# =============================================================================


def _writeLocalDeployVersion(path: Path, version: str = "V0.25.0") -> None:
    """Write a US-241-shaped record at ``path`` for the local-version source."""
    record = {
        "version": version,
        "releasedAt": "2026-05-07T08:29:24Z",
        "gitHash": "5e37494",
        "theme": "Sprint 25 close",
        "description": "local deploy stamp",
    }
    path.write_text(json.dumps(record))


def _serverRecord(version: str = "V0.26.0") -> dict[str, Any]:
    """Build a server release record matching GET /api/v1/release/current."""
    return {
        "version": version,
        "releasedAt": "2026-05-08T12:00:00Z",
        "gitHash": "abcdef0",
        "theme": "Sprint 26 candidate",
        "description": "server release",
    }


def _baseConfig(
    *,
    localVersionPath: str,
    markerFilePath: str,
    cooldownTimestampPath: str,
    cooldownHours: float = 24.0,
) -> dict[str, Any]:
    """Pi config dict carrying the keys UpdateChecker reads (cooldown + transport)."""
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.10:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
            },
            "update": {
                "enabled": True,
                "intervalMinutes": 60,
                "markerFilePath": markerFilePath,
                "localVersionPath": localVersionPath,
                "cooldownTimestampPath": cooldownTimestampPath,
                "cooldownHours": cooldownHours,
            },
        },
    }


class _FakeResponse:
    """Minimal context-manager wrapper that mimics ``urllib`` response."""

    def __init__(self, body: bytes = b"{}") -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _jsonOpener(payload: dict[str, Any]) -> Callable[..., Any]:
    """Opener that returns ``payload`` JSON-encoded; records each request."""
    calls: list[Any] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(req)
        return _FakeResponse(body=json.dumps(payload).encode("utf-8"))

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


def _raisingOpener(exc: Exception) -> Callable[..., Any]:
    """Opener that raises ``exc`` on every call; records call count."""
    calls: list[Any] = []

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        calls.append(req)
        raise exc

    _opener.calls = calls  # type: ignore[attr-defined]
    return _opener


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-xyz")
    return "test-key-xyz"


# =============================================================================
# Reboot-persistence acceptance: timestamp survives instance boundary
# =============================================================================


class TestCooldownPersistsAcrossReboots:
    """Simulate the Pi reboot scenario by constructing TWO UpdateChecker instances.

    Instance A writes the timestamp on a successful check.  Instance B
    (fresh construction = simulated reboot) reads the timestamp from disk
    and short-circuits with ``SKIPPED_COOLDOWN`` if still inside the
    24h window.  Pre-fix this fails because no persistence exists --
    Instance B has no memory of Instance A's check + would re-fetch.
    """

    def test_freshInstance_recentTimestampOnDisk_skipsCheckNoHttp(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """The B-047 D7 acceptance: simulate reboot mid-cooldown.

        Instance A check -> writes timestamp (success outcome).
        Instance B is constructed fresh (in-memory cooldown state lost
        in a real reboot) but reads the persisted timestamp from disk
        + correctly skips the check with zero HTTP calls and no marker.
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        timestampPath = tmp_path / "last-update-check.timestamp"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            cooldownTimestampPath=str(timestampPath),
        )

        # Instance A: completes a UP_TO_DATE check, persists timestamp.
        openerA = _jsonOpener(_serverRecord(version="V0.25.0"))
        checkerA = UpdateChecker(
            config,
            httpOpener=openerA,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: False,
        )
        resultA = checkerA.check_for_updates()
        assert resultA.outcome == CheckOutcome.UP_TO_DATE
        assert timestampPath.is_file(), (
            "completed check must persist the timestamp file"
        )

        # Instance B: fresh construction (simulated reboot).  No HTTP fires.
        openerB = _jsonOpener(_serverRecord(version="V0.26.0"))  # newer release
        checkerB = UpdateChecker(
            config,
            httpOpener=openerB,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: False,
        )
        resultB = checkerB.check_for_updates()

        assert resultB.outcome == CheckOutcome.SKIPPED_COOLDOWN
        assert len(openerB.calls) == 0, (  # type: ignore[attr-defined]
            "cooldown gate must short-circuit before the HTTP call"
        )
        assert not marker.exists(), (
            "cooldown skip must not write a marker file even when "
            "the (un-fetched) server has a newer version"
        )

    def test_freshInstance_expiredTimestamp_proceedsNormally(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """Cooldown HORIZON respected: after 24h elapse, fresh check proceeds.

        Pin: the cooldown is 24h, not "forever".  An old timestamp must
        not perma-block updates.
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        timestampPath = tmp_path / "last-update-check.timestamp"
        # Hand-write a timestamp older than 24h.
        old = datetime.now(UTC) - timedelta(hours=25)
        timestampPath.write_text(old.isoformat())

        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            cooldownTimestampPath=str(timestampPath),
        )
        opener = _jsonOpener(_serverRecord(version="V0.26.0"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: False,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UPDATE_AVAILABLE
        assert len(opener.calls) == 1  # type: ignore[attr-defined]
        assert marker.is_file()

    def test_freshInstance_noTimestampFile_proceedsNormally(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """Fresh bench Pi (no prior check ever) -> cooldown gate is OPEN."""
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        timestampPath = tmp_path / "last-update-check.timestamp"
        assert not timestampPath.exists(), (
            "test precondition: no timestamp file present"
        )

        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            cooldownTimestampPath=str(timestampPath),
        )
        opener = _jsonOpener(_serverRecord(version="V0.25.0"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: False,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UP_TO_DATE
        assert len(opener.calls) == 1  # type: ignore[attr-defined]


# =============================================================================
# Write contract: completed-check writes; failed-check does NOT (D7 invariant)
# =============================================================================


class TestCooldownTimestampWriteContract:
    """D7 invariant: only completed (server-reached) outcomes burn cooldown.

    NETWORK_ERROR + SKIPPED_* must NOT write the timestamp -- otherwise a
    transient WAN hiccup or a single drive-in-progress moment would push
    the next check 24h out, defeating the "retry on next eligible event"
    contract.
    """

    def test_completedCheck_writesTimestampToConfiguredPath(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """UP_TO_DATE -> timestamp file exists + parses as ISO datetime."""
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        timestampPath = tmp_path / "last-update-check.timestamp"

        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            cooldownTimestampPath=str(timestampPath),
        )
        opener = _jsonOpener(_serverRecord(version="V0.25.0"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: False,
        )

        before = datetime.now(UTC)
        result = checker.check_for_updates()
        after = datetime.now(UTC)

        assert result.outcome == CheckOutcome.UP_TO_DATE
        assert timestampPath.is_file()
        written = datetime.fromisoformat(timestampPath.read_text().strip())
        # Window-wide -- datetime.now() may step at sub-millisecond precision.
        assert before - timedelta(seconds=1) <= written <= after + timedelta(seconds=1)

    def test_networkError_doesNotWriteTimestamp(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """D7 invariant: failed-check (server unreachable) preserves OPEN cooldown.

        The next eligible trigger must retry, not wait 24h.
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        timestampPath = tmp_path / "last-update-check.timestamp"
        assert not timestampPath.exists()

        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            cooldownTimestampPath=str(timestampPath),
        )
        # urllib URLError -> NETWORK_ERROR per the existing checker contract.
        opener = _raisingOpener(urllib.error.URLError("connection refused"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: False,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.NETWORK_ERROR
        assert not timestampPath.exists(), (
            "D7: a failed check must NOT burn the cooldown"
        )

    def test_skippedDriving_doesNotWriteTimestamp(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """SKIPPED_DRIVING -> safety short-circuit, not a "completed check".

        A drive lasting 10 minutes would otherwise burn 24h of update
        eligibility -- the next eligible trigger after engine-off must
        retry immediately.
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        timestampPath = tmp_path / "last-update-check.timestamp"

        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            cooldownTimestampPath=str(timestampPath),
        )
        opener = _jsonOpener(_serverRecord())
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: True,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: False,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.SKIPPED_DRIVING
        assert not timestampPath.exists(), (
            "D7: SKIPPED_* preserves OPEN cooldown -- safety gates do "
            "not consume the once-per-24h budget"
        )


# =============================================================================
# Defensive: the gate degrades to OPEN on filesystem oddity
# =============================================================================


class TestCooldownGateDefensive:
    """A glitch reading the timestamp must NOT perma-block updates.

    If the file is unreadable / malformed, the safer fallback is to
    proceed with the check (the worst case is one extra check; the
    failure case if we did the opposite is no updates ever ship).
    """

    def test_malformedTimestampFile_proceedsNormally(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """Garbage bytes in timestamp file -> warning logged, gate OPEN."""
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        timestampPath = tmp_path / "last-update-check.timestamp"
        timestampPath.write_text("not-a-real-iso-timestamp-just-junk-bytes")

        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            cooldownTimestampPath=str(timestampPath),
        )
        opener = _jsonOpener(_serverRecord(version="V0.25.0"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: False,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UP_TO_DATE
        assert len(opener.calls) == 1  # type: ignore[attr-defined]
