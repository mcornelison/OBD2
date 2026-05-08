################################################################################
# File Name: test_self_update_e2e_production.py
# Purpose/Description: US-293 (B-047 production e2e drill).  Real
#                      ``UpdateChecker`` + ``UpdateApplier`` run end-to-end
#                      against a tmp_path-backed real ``ObdDatabase``.  Mock
#                      surface = HTTP transport edge (``urllib.request.
#                      urlopen``-shaped) + subprocess edge (``subprocess.
#                      run``-shaped) only; everything else is production
#                      code.  Sister test ``test_self_update_e2e.py``
#                      (US-258, Sprint 21) covered the marker-file handoff
#                      already; this drill closes the operator-observability
#                      gap by asserting that on SUCCESS a ``connection_log``
#                      row with ``event_type='auto_update_applied'`` is
#                      written -- the only off-Pi signal the server side
#                      gets that an auto-update happened.  Pre-fix this
#                      test FAILS because ``UpdateApplier.apply()`` clears
#                      the marker on SUCCESS but never logs the event.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex          | Initial -- US-293 production e2e drill
# ================================================================================
################################################################################

"""US-293 -- B-047 production e2e drill (Driving Season Open).

The gap this closes
-------------------
US-258 (Sprint 21) shipped ``test_self_update_e2e.py`` -- a synthetic drill
that exercises the marker-file handoff between ``UpdateChecker`` and
``UpdateApplier`` with HTTP + subprocess seams faked out.  That test
proves the two classes cooperate; it does NOT prove the operator-facing
observability contract from B-047 line 104:

    Acceptance: drive 7+ post-deploy includes a ``connection_log`` row with
    ``event_type=auto_update_applied`` + new ``.deploy-version`` content
    captured.

The Pi-wiring this weekend (Spool 2026-05-06) flips the update-trigger to
fire on every key-on.  Without that ``connection_log`` row, server-side
analytics has no way to know whether a given Pi has self-updated -- the
same risk class as Sprint 25's engine-telemetry regression (shipped,
deployed, never observed in prod).  This drill is the durable regression
gate.

Mock surface
------------
Per US-293 invariant "Mock surface = HTTP transport edge only (urllib
mocks); UpdateChecker + UpdateApplier internals real":

* HTTP via ``UpdateChecker(httpOpener=...)`` -- same seam as US-258.
* Subprocesses via ``UpdateApplier(subprocessRun=...)`` -- same seam.
* Database is a REAL ``ObdDatabase`` writing to ``tmp_path``.  Schema
  initialized via ``initialize()``.  No DB mock; the test reads the
  ``connection_log`` table back to assert the row landed.

Why a real database (not a mock)
--------------------------------
US-258's mock surface stopped at the marker file.  The SUCCESS path
writes nothing else to disk that production observability cares about
-- the new ``connection_log`` write IS production observability for
this feature.  Mocking it at the writer-helper boundary would let a
silently-broken sqlite INSERT slip through (the same bug class as the
US-267 fsync gap that Sprint 22 closed).
"""

from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.update.update_applier import (
    ApplyOutcome,
    UpdateApplier,
)
from src.pi.update.update_checker import (
    CheckOutcome,
    UpdateChecker,
)

# =============================================================================
# Fakes -- HTTP + subprocess seams (mirror US-258 fixtures verbatim where
# possible so a future maintainer reading both files sees a consistent shape)
# =============================================================================


class _FakeReleaseEndpoint:
    """``urlopen``-shaped fake serving a scripted server-release record."""

    def __init__(
        self,
        *,
        payload: dict[str, Any],
    ) -> None:
        self._payload = payload
        self.calls: list[Any] = []

    def __call__(self, req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG002
        self.calls.append(req)
        return _FakeResponse(
            body=json.dumps(self._payload).encode("utf-8"),
            status=200,
        )


class _FakeResponse:
    """Minimal context-manager that mimics ``urllib`` response."""

    def __init__(self, body: bytes = b"{}", status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _Fake5xxEndpoint:
    """Raises HTTP 503 to model the 'no record stamped' transient state."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG002
        self.calls.append(req)
        raise urllib.error.HTTPError(
            url=getattr(req, "full_url", "http://test/"),
            code=503,
            msg="Service Unavailable",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )


class _FakeDeployRunner:
    """``subprocess.run``-shaped fake that scripts the apply pipeline.

    The fake additionally simulates the bash deploy script's
    ``.deploy-version`` write so the post-deploy verify step has a
    realistic file to read -- this is the same pattern US-258 used.
    """

    def __init__(
        self,
        *,
        priorRefStdout: str = "abc1234\n",
        deployStampPath: Path | None = None,
        deployStampVersion: str = "V0.21.0",
        failures: dict[str, int] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._priorRefStdout = priorRefStdout
        self._deployStampPath = deployStampPath
        self._deployStampVersion = deployStampVersion
        self._failures = failures or {}

    def __call__(
        self,
        cmd: list[str],
        *,
        capture_output: bool = False,  # noqa: ARG002 -- match subprocess.run
        text: bool = False,  # noqa: ARG002
        check: bool = False,  # noqa: ARG002
        timeout: float | None = None,  # noqa: ARG002
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        joined = " ".join(cmd)

        for needle, rc in self._failures.items():
            if needle in joined:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=rc, stdout="",
                    stderr=f"fake fail: {needle}",
                )

        if joined.startswith("git rev-parse HEAD"):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout=self._priorRefStdout, stderr="",
            )

        # US-294 service-health watchdog default-happy probe.
        if joined.startswith("systemctl is-active"):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="active\n", stderr="",
            )

        if (
            "deploy-pi.sh" in joined
            and "--dry-run" not in joined
            and self._deployStampPath is not None
        ):
            self._stampDeployVersion()

        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        )

    def _stampDeployVersion(self) -> None:
        assert self._deployStampPath is not None
        record = {
            "version": self._deployStampVersion,
            "releasedAt": "2026-05-08T12:00:00Z",
            "gitHash": "abcdef0",
            "theme": "Sprint 26",
            "description": "fake deploy-pi.sh stamp (US-293 production drill)",
        }
        self._deployStampPath.parent.mkdir(parents=True, exist_ok=True)
        self._deployStampPath.write_text(json.dumps(record))


class _FailFullDeployRunner(_FakeDeployRunner):
    """Variant runner that fails ONLY the full deploy phase.

    Mirrors the US-258 ``_FailFullDeployRunner`` shape: argv-length
    discriminates ``[bash, deploy-pi.sh]`` (full, 2 args) from
    ``[bash, deploy-pi.sh, --dry-run]`` (dry-run, 3 args).
    """

    def __call__(
        self,
        cmd: list[str],
        *,
        capture_output: bool = False,  # noqa: ARG002
        text: bool = False,  # noqa: ARG002
        check: bool = False,  # noqa: ARG002
        timeout: float | None = None,  # noqa: ARG002
    ) -> subprocess.CompletedProcess[str]:
        if (
            len(cmd) == 2
            and cmd[0] == "bash"
            and cmd[1].endswith("deploy-pi.sh")
        ):
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout="",
                stderr="fake fail: full deploy",
            )
        return super().__call__(
            cmd,
            capture_output=capture_output,
            text=text,
            check=check,
            timeout=timeout,
        )


# =============================================================================
# Helpers / fixtures
# =============================================================================


_LOCAL_VERSION = "V0.20.0"
_TARGET_VERSION = "V0.21.0"


def _writeLocalDeployVersion(path: Path, version: str) -> None:
    """Write a US-241-shaped local ``.deploy-version`` record."""
    record = {
        "version": version,
        "releasedAt": "2026-04-29T08:29:24Z",
        "gitHash": "d8583d3",
        "theme": "Sprint 25",
        "description": "local deploy stamp",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))


def _serverRecord(version: str) -> dict[str, Any]:
    """Build a US-246-shaped ``GET /api/v1/release/current`` payload."""
    return {
        "version": version,
        "releasedAt": "2026-05-08T12:00:00Z",
        "gitHash": "abcdef0",
        "theme": "Sprint 26",
        "description": "server release",
    }


def _e2eConfig(
    *,
    localVersionPath: str,
    markerFilePath: str,
    applyEnabled: bool = True,
) -> dict[str, Any]:
    """Pi config dict shared across UpdateChecker + UpdateApplier."""
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
                "applyEnabled": applyEnabled,
                "rollbackEnabled": True,
                "stagingPath": "/tmp/eclipse-obd-staging-test",
            },
        },
    }


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-us293")
    return "test-key-us293"


@pytest.fixture(autouse=True)
def _isolatedCooldownPath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-test isolation for the US-296 cooldown timestamp file.

    US-293 production e2e drills exercise the real UpdateChecker;
    US-296 added an on-disk cooldown side effect.  Stub the default
    path to a per-test tmp_path so a successful check in one test
    does not bleed cooldown into the next test's run.
    """
    isolated = tmp_path / "_us296_cooldown_unused.timestamp"
    monkeypatch.setattr(
        "src.pi.update.update_checker._DEFAULT_COOLDOWN_TIMESTAMP_PATH",
        str(isolated),
    )


@pytest.fixture
def realDatabase(tmp_path: Path) -> ObdDatabase:
    """A real ObdDatabase writing to a tmp_path SQLite file.

    Initialized via ``initialize()`` so all schemas (including
    ``connection_log``) are present.  WAL mode disabled to keep the
    test footprint to a single ``.db`` file (no -wal/-shm sidecars
    cluttering tmp_path) -- functional behavior is identical for the
    INSERT-and-readback path under test.
    """
    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture
def e2ePaths(tmp_path: Path) -> dict[str, Path]:
    return {
        "local": tmp_path / ".deploy-version",
        "marker": tmp_path / "var" / "lib" / "eclipse-obd" / "update-pending.json",
    }


def _readConnectionLogRows(database: ObdDatabase) -> list[sqlite3.Row]:
    """Return every connection_log row in insertion order.

    Used by every assertion that reasons about the auto_update_applied
    observability contract.  Returning sqlite3.Row gives column-name
    access (`row['event_type']`) which makes the assertions read like
    documentation.
    """
    with database.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, event_type, success, error_message, drive_id
            FROM connection_log
            ORDER BY id ASC
            """
        )
        return list(cursor.fetchall())


# =============================================================================
# Test 1 -- DISCRIMINATOR: SUCCESS path writes the auto_update_applied row
# =============================================================================


@pytest.mark.integration
class TestProductionE2EAutoUpdateAppliedRow:
    """The B-047 line-104 contract -- pre-fix this class FAILS."""

    def test_e2e_serverNewer_appliesSuccessfully_writesAutoUpdateAppliedRow(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
        realDatabase: ObdDatabase,
    ) -> None:
        """
        Given: local V0.20.0; server returns V0.21.0; safety gates open;
               real ObdDatabase with connection_log table initialized
        When: UpdateChecker.check_for_updates() runs, then
              UpdateApplier.apply() runs (with database= injected) and
              succeeds
        Then:
          - ApplyOutcome.SUCCESS
          - .deploy-version reflects V0.21.0
          - connection_log has exactly one row with
            event_type='auto_update_applied' and success=1
          - row.error_message records the version transition
            (operator-observability requirement)
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=True,
        )

        # Phase 1: real UpdateChecker writes the marker.
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
        )
        checkResult = checker.check_for_updates()
        assert checkResult.outcome == CheckOutcome.UPDATE_AVAILABLE
        assert marker.is_file()

        # Phase 2: real UpdateApplier with REAL database injected.
        runner = _FakeDeployRunner(
            priorRefStdout="abc1234\n",
            deployStampPath=local,
            deployStampVersion=_TARGET_VERSION,
        )
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
            database=realDatabase,
        )
        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.SUCCESS, (
            f"e2e apply must SUCCEED on the production-path drill; got "
            f"{applyResult.outcome} (rationale: {applyResult.rationale})"
        )
        assert applyResult.targetVersion == _TARGET_VERSION

        # Sanity: the .deploy-version stamp landed (US-241 contract).
        postRecord = json.loads(local.read_text())
        assert postRecord["version"] == _TARGET_VERSION

        # The discriminator: the connection_log row is the
        # production-observability gap this story closes.
        rows = _readConnectionLogRows(realDatabase)
        autoUpdateRows = [r for r in rows if r["event_type"] == "auto_update_applied"]
        assert len(autoUpdateRows) == 1, (
            f"SUCCESS apply must write exactly one connection_log row "
            f"with event_type='auto_update_applied'; saw "
            f"event_types={[r['event_type'] for r in rows]}"
        )
        row = autoUpdateRows[0]
        assert row["success"] == 1, (
            "auto_update_applied row must record success=1 "
            "(operator dashboard filters on success)"
        )
        # The diagnostic message must let the operator reconstruct the
        # transition without grepping local Pi logs.
        msg = row["error_message"] or ""
        assert _LOCAL_VERSION in msg, (
            f"auto_update_applied diagnostic must record prior version "
            f"{_LOCAL_VERSION}; saw {msg!r}"
        )
        assert _TARGET_VERSION in msg, (
            f"auto_update_applied diagnostic must record target version "
            f"{_TARGET_VERSION}; saw {msg!r}"
        )

    def test_e2e_serverNewer_apiesSuccessfully_marketCleared_priorRefRecorded(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
        realDatabase: ObdDatabase,
    ) -> None:
        """Companion guardrail: the SUCCESS-path side-effects on disk.

        Given:  same as the discriminator above
        Then:
          - marker file deleted on SUCCESS (no perma-trigger on next tick)
          - priorRef captured (rollback would have a target if needed)
          - subprocess sequence: rev-parse -> fetch -> checkout -> dry-run
            -> deploy in that order
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=True,
        )
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        UpdateChecker(
            config, httpOpener=opener, isDrivingFn=lambda: False,
        ).check_for_updates()
        runner = _FakeDeployRunner(
            priorRefStdout="abc1234\n",
            deployStampPath=local,
            deployStampVersion=_TARGET_VERSION,
        )
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
            database=realDatabase,
        )

        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.SUCCESS
        assert applyResult.priorRef == "abc1234"
        assert not marker.exists()
        cmds = [" ".join(c) for c in runner.calls]
        revIdx = next(i for i, c in enumerate(cmds) if c.startswith("git rev-parse"))
        fetchIdx = next(i for i, c in enumerate(cmds) if c.startswith("git fetch"))
        checkoutIdx = next(
            i for i, c in enumerate(cmds)
            if c.startswith(f"git checkout {_TARGET_VERSION}")
        )
        dryRunIdx = next(
            i for i, c in enumerate(cmds) if "deploy-pi.sh --dry-run" in c
        )
        deployIdx = next(
            i for i, c in enumerate(cmds)
            if c.endswith("deploy-pi.sh")
        )
        assert revIdx < fetchIdx < checkoutIdx < dryRunIdx < deployIdx, (
            f"production phase ordering violated: {cmds}"
        )


# =============================================================================
# Test 2 -- GUARDRAIL: failed apply does NOT write a SUCCESS row
# =============================================================================


@pytest.mark.integration
class TestProductionE2EFailedApplyDoesNotWriteSuccessRow:
    """A rolled-back apply must NOT leave an auto_update_applied row.

    Without this guardrail, a future regression that moves the writer
    above the SUCCESS branch (e.g., into ``apply()``-entry instrumentation)
    would silently mislead operators into thinking a failed apply
    succeeded.  Pin the contract here.
    """

    def test_e2e_fullDeployFails_rollbackOk_noAutoUpdateRowWritten(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
        realDatabase: ObdDatabase,
    ) -> None:
        """
        Given: full deploy returns rc=1; rollback succeeds
        Then:
          - outcome DEPLOY_FAILED, rollbackOutcome 'ok'
          - connection_log has ZERO rows with
            event_type='auto_update_applied'
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=True,
        )
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        UpdateChecker(
            config, httpOpener=opener, isDrivingFn=lambda: False,
        ).check_for_updates()

        runner = _FailFullDeployRunner(priorRefStdout="abc1234\n")
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
            database=realDatabase,
        )

        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.DEPLOY_FAILED
        assert applyResult.rollbackOutcome == "ok"
        rows = _readConnectionLogRows(realDatabase)
        autoUpdateRows = [r for r in rows if r["event_type"] == "auto_update_applied"]
        assert autoUpdateRows == [], (
            f"failed apply MUST NOT write an auto_update_applied row; "
            f"saw {[(r['event_type'], r['success']) for r in autoUpdateRows]}"
        )


# =============================================================================
# Test 3 -- GUARDRAIL: server-503 short-circuit writes NO row + makes NO subproc
# =============================================================================


@pytest.mark.integration
class TestProductionE2EServerNoRecordIsNoOp:
    """503 from the server (US-246 'no record stamped') is a clean no-op.

    The production-path drill must include the no-op outcome because
    that is what fires on a fresh server with no release ever stamped --
    the literal first-trigger-after-deploy state for B-047.
    """

    def test_e2e_server503_checkerShortCircuits_noMarker_noSubprocess_noRow(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
        realDatabase: ObdDatabase,
    ) -> None:
        """
        Given: server raises HTTP 503 (no release record yet)
        When: check runs; apply runs (independently)
        Then:
          - check returns SERVER_NO_RECORD; no marker on disk
          - apply returns NO_MARKER; ZERO subprocesses spawned
          - connection_log has ZERO auto_update_applied rows
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=True,
        )

        opener = _Fake5xxEndpoint()
        checkResult = UpdateChecker(
            config, httpOpener=opener, isDrivingFn=lambda: False,
        ).check_for_updates()
        assert checkResult.outcome == CheckOutcome.SERVER_NO_RECORD
        assert not marker.exists()

        runner = _FakeDeployRunner(priorRefStdout="abc1234\n")
        applyResult = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
            database=realDatabase,
        ).apply()
        assert applyResult.outcome == ApplyOutcome.NO_MARKER
        assert runner.calls == []
        rows = _readConnectionLogRows(realDatabase)
        assert rows == [], (
            f"503 -> no-marker path must leave connection_log empty; "
            f"saw {[r['event_type'] for r in rows]}"
        )


__all__: list[str] = []  # nothing exported -- pure pytest module
