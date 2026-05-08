################################################################################
# File Name: test_update_checker_safety_preconditions.py
# Purpose/Description: B-047 D2 safety-precondition gate audit (US-295).
#                      Asserts that UpdateChecker.check_for_updates skips the
#                      server fetch + marker write when ANY of the three
#                      D2 preconditions fails: (a) drive in progress,
#                      (b) sync_log cursor behind realtime_data MAX(id),
#                      (c) DTC retrieval mid-execution.  All three must
#                      hold (logical AND) for the check to proceed.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (US-295) | Initial -- 4 acceptance cases (each
#               |              | precondition violated alone + all-pass) +
#               |              | constructor back-compat guardrail.
# ================================================================================
################################################################################

"""B-047 D2 safety-precondition tests for :class:`UpdateChecker` (US-295).

Pi-wiring (CIO hardware task, ~5/9 weekend per Spool 2026-05-06) flips the
update-check trigger to fire on every key-on.  The D2 preconditions
(drive-state / sync-caught-up / no-DTC-retrieval) MUST hold before any
check proceeds to avoid:

* Update applying mid-drive (drive-state) -- already gated since US-247.
* Update applying with un-synced telemetry on the Pi (sync_log cursor) --
  data loss risk if the apply step rolls the disk image.
* Update applying while a DTC retrieval is in flight (US-292 added a
  30s during-drive Mode 03 cadence + drive_end Mode 07 pull) -- DTC
  retrieval can fire from DriveDetector callbacks on a non-runLoop
  thread, so the gate is structural even if the production race
  window today is microseconds.

Each gate is closure-injected so the tests can stub the precondition
state without DB / detector / dtc_logger plumbing.  Pre-fix all four
acceptance cases FAIL with ``TypeError: unexpected keyword argument
'isSyncCaughtUpFn' / 'isDtcRetrievalActiveFn'`` -- the precondition
gates do not exist yet.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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


def _baseConfig(*, localVersionPath: str, markerFilePath: str) -> dict[str, Any]:
    """Pi config dict carrying the keys UpdateChecker reads."""
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


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-xyz")
    return "test-key-xyz"


@pytest.fixture(autouse=True)
def _isolatedCooldownPath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-test isolation for the US-296 cooldown timestamp file.

    US-296 added a real on-disk side effect: completed checks write to
    ``pi.update.cooldownTimestampPath`` (default
    ``~/.cache/eclipse-obd/last-update-check.timestamp``).  These
    back-compat tests don't exercise the cooldown contract -- they
    need the default path stubbed to a per-test tmp_path so a
    successful check in one test does not bleed cooldown into the
    next test's run.
    """
    isolated = tmp_path / "_us296_cooldown_unused.timestamp"
    monkeypatch.setattr(
        "src.pi.update.update_checker._DEFAULT_COOLDOWN_TIMESTAMP_PATH",
        str(isolated),
    )


# =============================================================================
# AC: each precondition violated alone -> SKIPPED (no HTTP, no marker)
# =============================================================================


class TestSafetyPreconditionGates:
    """The B-047 D2 audit: 4 cases (drive / sync / dtc / all-pass).

    Pre-fix RED: cases 2-3 raise ``TypeError`` because the new
    ``isSyncCaughtUpFn`` / ``isDtcRetrievalActiveFn`` constructor kwargs
    do not exist.  Case 1 (drive) is shipped (US-247) -- included as a
    smoke regression so the gate-priority story stays in one file.
    Case 4 (all-pass) verifies the HTTP path is reachable when every
    gate is open.
    """

    def test_activeDriveId_skipsUpdate_noHttpCallNoMarker(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """isDrivingFn() True -> SKIPPED_DRIVING + no HTTP + no marker."""
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
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
        assert len(opener.calls) == 0  # type: ignore[attr-defined]
        assert not marker.exists()

    def test_syncCursorBehind_skipsUpdate_noHttpCallNoMarker(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """isSyncCaughtUpFn() False -> SKIPPED_SYNC_LAGGING + no HTTP + no marker."""
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord())
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: False,
            isDtcRetrievalActiveFn=lambda: False,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.SKIPPED_SYNC_LAGGING
        assert len(opener.calls) == 0  # type: ignore[attr-defined]
        assert not marker.exists()

    def test_dtcRetrievalInFlight_skipsUpdate_noHttpCallNoMarker(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """isDtcRetrievalActiveFn() True -> SKIPPED_DTC_ACTIVE + no HTTP + no marker."""
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord())
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
            isSyncCaughtUpFn=lambda: True,
            isDtcRetrievalActiveFn=lambda: True,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.SKIPPED_DTC_ACTIVE
        assert len(opener.calls) == 0  # type: ignore[attr-defined]
        assert not marker.exists()

    def test_allPreconditionsHold_proceedsToServerFetch(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """All gates open -> HTTP call fires + reaches version-comparison + writes marker.

        Discriminator that the AND-of-all-three logic does not over-block:
        every gate must be checkable independently.
        """
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
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


# =============================================================================
# Constructor back-compat: existing US-247 callsites must still work
# =============================================================================


class TestPreconditionFunctionsDefaultOpen:
    """The new closures default to None -- the gate is OPEN when unwired.

    Critical for the existing ``UpdateChecker(config, isDrivingFn=...)``
    callsite at lifecycle.py:1522 (US-247) to keep working unchanged.
    """

    def test_constructWithoutNewKwargs_defaultsOpenGates_proceedsThroughChecks(
        self,
        tmp_path: Path,
        stubApiKey: str,
    ) -> None:
        """Pre-US-295 callsite (only isDrivingFn) -> still reaches server fetch."""
        local = tmp_path / ".deploy-version"
        _writeLocalDeployVersion(local, version="V0.25.0")
        marker = tmp_path / "update-pending.json"
        config = _baseConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _jsonOpener(_serverRecord(version="V0.26.0"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
        )

        result = checker.check_for_updates()

        assert result.outcome == CheckOutcome.UPDATE_AVAILABLE
        assert len(opener.calls) == 1  # type: ignore[attr-defined]
        assert marker.is_file()

    def test_skippedSyncLagging_outcomeEnum_present(self) -> None:
        """The new CheckOutcome member is reachable via the public enum."""
        assert CheckOutcome.SKIPPED_SYNC_LAGGING.value == "skipped_sync_lagging"

    def test_skippedDtcActive_outcomeEnum_present(self) -> None:
        """The new CheckOutcome member is reachable via the public enum."""
        assert CheckOutcome.SKIPPED_DTC_ACTIVE.value == "skipped_dtc_active"
