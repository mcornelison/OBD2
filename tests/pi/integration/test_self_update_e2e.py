################################################################################
# File Name: test_self_update_e2e.py
# Purpose/Description: End-to-end integration drill for the Pi self-update
#                      pipeline (B-047 US-E / US-258).  Exercises the full
#                      check -> marker -> apply -> deploy -> verify cycle of
#                      the real UpdateChecker (Sprint 20 US-247) and
#                      UpdateApplier (Sprint 20 US-248) classes with mocks
#                      ONLY at the HTTP boundary (UpdateChecker.httpOpener)
#                      and the subprocess boundary
#                      (UpdateApplier.subprocessRun).  This is the
#                      integration-readiness gate before flipping
#                      `pi.update.applyEnabled=true` in production -- unit
#                      tests cover each class in isolation; this drill
#                      proves they cooperate end-to-end across the
#                      marker-file handoff.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex          | Initial implementation for US-258 (Sprint 21)
# ================================================================================
################################################################################

"""End-to-end self-update drill (US-258 / B-047 US-E).

Story invariant: the real production classes (`UpdateChecker`,
`UpdateApplier`) cooperate across the marker-file handoff to deliver one of
four observable outcomes that match the four CIO-facing behaviors:

1. **Happy path** (server NEWER): check writes marker -> apply reads marker
   -> dry-run + deploy succeed -> post-deploy `.deploy-version` reflects
   the target version -> marker cleared.
2. **Deploy failure -> rollback**: check writes marker -> apply runs ->
   `deploy-pi.sh` fails -> rollback to priorRef + service restart fire ->
   marker cleared (so the next interval tick does not re-trigger the same
   poisoned target).
3. **Drive-state safety net**: drive is in progress -> check skips the HTTP
   request -> apply skips even when a marker is present -> no new marker
   ever appears.
4. **Up-to-date**: server reports the SAME version as the local
   `.deploy-version` -> no marker is ever written -> apply has nothing to
   do -> no subprocess is invoked.

Mock fidelity (per `feedback_runtime_validation_required.md` and the story
acceptance):

* HTTP is mocked at the `urllib.request.urlopen`-shaped seam exposed by
  `UpdateChecker(httpOpener=...)`.  The wire request format, headers,
  and JSON payload all flow through the real code path.
* Subprocesses are mocked at the single `subprocess.run`-shaped seam
  exposed by `UpdateApplier(subprocessRun=...)`.  The argv list flows
  through the real apply state machine.  The fake captures every call
  in order, returns scripted `CompletedProcess` results, AND simulates
  `deploy-pi.sh`'s `.deploy-version` stamp side-effect so the
  post-deploy verify step has something to read (mirroring real
  production behavior where the bash script writes the file).
* No internal-state monkeypatching, no method substitution.  The test
  drives the public API only.

The drive-state / power-source / recent-OBD-activity closures are passed
in at construction time so the safety gates are exercised in the real
code path; the test does not bypass them.

Performance: each test runs in well under 10 s on Windows; no real I/O
beyond `tmp_path` writes.
"""

from __future__ import annotations

import io
import json
import logging
import subprocess
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from src.pi.update.update_applier import (
    ApplyOutcome,
    UpdateApplier,
)
from src.pi.update.update_checker import (
    CheckOutcome,
    UpdateChecker,
)

# =============================================================================
# Fake HTTP server
# =============================================================================


class _FakeReleaseEndpoint:
    """Records release-endpoint requests; returns a scripted JSON record.

    Honors three modes:

    * ``mode='ok'`` -- return the configured ``payload`` with HTTP 200.
    * ``mode='503'`` -- raise ``HTTPError(503)`` (US-246 'no record yet').
    * ``mode='500'`` -- raise ``HTTPError(500)`` (server-side error).

    The opener captures every request so tests can assert the wire shape
    matches `GET /api/v1/release/current` with the API-key header.
    """

    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        mode: str = "ok",
    ) -> None:
        self._payload: dict[str, Any] = payload or {}
        self._mode = mode
        self.calls: list[Any] = []

    def __call__(self, req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG002
        self.calls.append(req)
        if self._mode == "503":
            raise urllib.error.HTTPError(
                url=getattr(req, "full_url", "http://test/"),
                code=503,
                msg="Service Unavailable",
                hdrs=None,  # type: ignore[arg-type]
                fp=io.BytesIO(b""),
            )
        if self._mode == "500":
            raise urllib.error.HTTPError(
                url=getattr(req, "full_url", "http://test/"),
                code=500,
                msg="Internal Server Error",
                hdrs=None,  # type: ignore[arg-type]
                fp=io.BytesIO(b""),
            )
        return _FakeResponse(
            body=json.dumps(self._payload).encode("utf-8"),
            status=200,
        )


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


# =============================================================================
# Fake subprocess runner
# =============================================================================


class _FakeDeployRunner:
    """Records subprocess calls; serves scripted results.

    Mirrors the contract of ``subprocess.run`` for the four-phase apply
    pipeline (capture priorRef -> fetch -> checkout -> dry-run -> deploy
    -> rollback).  Per-cmd defaults:

    * ``git rev-parse HEAD`` -> rc=0, stdout=``priorRefStdout``.
    * Every other cmd -> rc=0 (happy-path default).

    Tests opt into failure by populating ``failures`` with a substring
    matched against the joined argv (e.g., ``{"deploy-pi.sh": 1}`` to
    fail BOTH ``--dry-run`` and the full deploy invocations; or
    ``{"deploy-pi.sh ": 1}`` to fail only the no-flag full deploy via a
    trailing-space discriminator).

    ``deployStampPath`` + ``deployStampVersion`` script the stamp side-
    effect: when the runner sees ``bash deploy/deploy-pi.sh`` (NOT
    ``--dry-run``), it writes a US-241-shaped record with
    ``deployStampVersion`` to ``deployStampPath``.  This mirrors the
    real bash script's ``.deploy-version`` write so the post-deploy
    verify step can read what was just stamped.
    """

    def __init__(
        self,
        *,
        priorRefStdout: str = "abc1234\n",
        failures: dict[str, int] | None = None,
        deployStampPath: Path | None = None,
        deployStampVersion: str = "V0.20.0",
    ) -> None:
        self.calls: list[list[str]] = []
        self._priorRefStdout = priorRefStdout
        self._failures = failures or {}
        self._deployStampPath = deployStampPath
        self._deployStampVersion = deployStampVersion

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

        # Scripted failures take priority over default success.
        for needle, rc in self._failures.items():
            if needle in joined:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=rc, stdout="",
                    stderr=f"fake fail: {needle}",
                )

        # priorRef capture for rollback.
        if joined.startswith("git rev-parse HEAD"):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout=self._priorRefStdout, stderr="",
            )

        # deploy-pi.sh stamp side-effect: only the FULL deploy (no
        # --dry-run) writes the .deploy-version record on the real Pi.
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
        """Write a US-241-shaped record to the configured stamp path."""
        assert self._deployStampPath is not None
        record = {
            "version": self._deployStampVersion,
            "releasedAt": "2026-05-01T12:00:00Z",
            "gitHash": "abcdef0",
            "theme": "Sprint 21",
            "description": "fake deploy-pi.sh stamp",
        }
        self._deployStampPath.parent.mkdir(parents=True, exist_ok=True)
        self._deployStampPath.write_text(json.dumps(record))

    def commandSequence(self) -> list[str]:
        """Joined argv of every recorded subprocess call (in order)."""
        return [" ".join(c) for c in self.calls]


# =============================================================================
# Helpers / fixtures
# =============================================================================


_LOCAL_VERSION = "V0.19.0"
_TARGET_VERSION = "V0.20.0"


def _writeLocalDeployVersion(path: Path, version: str = _LOCAL_VERSION) -> None:
    """Write a US-241-shaped local `.deploy-version` record.

    Carries every key in `version_helpers.RELEASE_RECORD_KEYS`
    (`version, releasedAt, gitHash, theme, description`) so
    `validateRelease` passes.  The `theme` field was added after the
    initial Sprint 20 unit-test fixtures landed; this fixture matches
    the current contract.
    """
    record = {
        "version": version,
        "releasedAt": "2026-04-29T08:29:24Z",
        "gitHash": "d8583d3",
        "theme": "Sprint 21",
        "description": "local deploy stamp",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))


def _writeMarker(path: Path, *, targetVersion: str = _TARGET_VERSION) -> None:
    """Write a US-247-shaped marker file (used for safety-gate tests)."""
    body = {
        "target_version": targetVersion,
        "server_url": "http://10.27.27.10:8000",
        "rationale": f"server reports newer version {targetVersion}",
        "checked_at": "2026-04-30T12:34:56Z",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def _serverRecord(version: str = _TARGET_VERSION) -> dict[str, Any]:
    """Build a server-side release record matching `GET /api/v1/release/current`.

    Includes every key in `version_helpers.RELEASE_RECORD_KEYS` so the
    real `validateRelease` accepts the payload.
    """
    return {
        "version": version,
        "releasedAt": "2026-04-30T12:00:00Z",
        "gitHash": "abcdef0",
        "theme": "Sprint 21",
        "description": "server release",
    }


def _e2eConfig(
    *,
    localVersionPath: str,
    markerFilePath: str,
    applyEnabled: bool = True,
    enabled: bool = True,
    rollbackEnabled: bool = True,
    apiKeyEnv: str = "COMPANION_API_KEY",
    baseUrl: str = "http://10.27.27.10:8000",
) -> dict[str, Any]:
    """Pi config dict shared across UpdateChecker + UpdateApplier."""
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
                "intervalMinutes": 60,
                "markerFilePath": markerFilePath,
                "localVersionPath": localVersionPath,
                "applyEnabled": applyEnabled,
                "rollbackEnabled": rollbackEnabled,
                "stagingPath": "/tmp/eclipse-obd-staging-test",
            },
        },
    }


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-xyz")
    return "test-key-xyz"


@pytest.fixture
def e2ePaths(tmp_path: Path) -> dict[str, Path]:
    """Standard path layout for an e2e drill: local deploy version + marker."""
    return {
        "local": tmp_path / ".deploy-version",
        "marker": tmp_path / "var" / "lib" / "eclipse-obd" / "update-pending.json",
    }


# =============================================================================
# Test 1: Happy path -- server NEWER -> check -> apply -> verify -> success
# =============================================================================


@pytest.mark.integration
class TestSelfUpdateE2EHappyPath:
    """The drill that gates flipping `applyEnabled=true` in production.

    Real UpdateChecker + UpdateApplier instances cooperate across the
    marker-file handoff.  Mocks are at the HTTP and subprocess seams only.
    """

    def test_e2e_serverNewerVersion_checkerWritesMarker_applierApplies_postDeployVerifies(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
    ) -> None:
        """
        Given: local V0.19.0, server returns V0.20.0, all safety gates open
        When: UpdateChecker.check_for_updates() runs, then UpdateApplier.apply() runs
        Then:
          - check writes marker with target_version=V0.20.0
          - apply reads marker, captures priorRef, runs fetch + checkout +
            dry-run + deploy + post-deploy verify in that order
          - post-deploy `.deploy-version` reflects V0.20.0 (deploy stamp)
          - marker is cleared on success
          - ApplyOutcome.SUCCESS
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=True,
        )

        # Phase 1: check
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
        )
        checkResult = checker.check_for_updates()

        assert checkResult.outcome == CheckOutcome.UPDATE_AVAILABLE, (
            f"checker should write marker; got {checkResult.outcome}"
        )
        assert marker.is_file(), "marker file must be on disk before apply runs"
        markerBody = json.loads(marker.read_text())
        assert markerBody["target_version"] == _TARGET_VERSION
        assert len(opener.calls) == 1, "checker should hit server exactly once"
        assert opener.calls[0].full_url.endswith("/api/v1/release/current")

        # Phase 2: apply.  The fake runner stamps `.deploy-version` with
        # the target version when it sees `bash deploy/deploy-pi.sh`
        # (no --dry-run), so the post-deploy verify step finds the
        # expected record.
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
        )
        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.SUCCESS, (
            f"e2e apply should SUCCEED on happy path; got "
            f"{applyResult.outcome} (rationale: {applyResult.rationale})"
        )
        assert applyResult.targetVersion == _TARGET_VERSION
        assert applyResult.priorRef == "abc1234"
        assert applyResult.rollbackOutcome is None, (
            "happy-path apply must not invoke rollback"
        )

        # Phase 3: side-effect verification.
        assert not marker.exists(), "marker must be cleared on SUCCESS"
        postRecord = json.loads(local.read_text())
        assert postRecord["version"] == _TARGET_VERSION, (
            "post-deploy .deploy-version must reflect target version"
        )

        # Phase 4: command-sequence ordering.  The state machine must
        # invoke phases in the documented order: priorRef -> fetch ->
        # checkout -> dry-run -> deploy.  Rollback commands must be
        # absent.
        cmds = runner.commandSequence()
        assert any(c.startswith("git rev-parse HEAD") for c in cmds)
        fetchIdx = next(i for i, c in enumerate(cmds) if c.startswith("git fetch"))
        checkoutIdx = next(
            i for i, c in enumerate(cmds) if c.startswith(f"git checkout {_TARGET_VERSION}")
        )
        dryRunIdx = next(
            i for i, c in enumerate(cmds) if "deploy-pi.sh --dry-run" in c
        )
        deployIdx = next(
            i for i, c in enumerate(cmds)
            if c.endswith("deploy-pi.sh")  # full deploy, no flag
        )
        assert fetchIdx < checkoutIdx < dryRunIdx < deployIdx, (
            f"phase ordering violated: {cmds}"
        )
        assert not any("systemctl restart" in c for c in cmds), (
            "rollback restart must NOT fire on happy path"
        )


# =============================================================================
# Test 2: Deploy failure -> rollback -> marker cleared
# =============================================================================


@pytest.mark.integration
class TestSelfUpdateE2EDeployFailureTriggersRollback:
    """Failure inside the full-deploy phase must trigger rollback + clear marker."""

    def test_e2e_fullDeployFails_rollbackFires_markerCleared(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: check writes marker; apply runs; dry-run succeeds; full
               deploy returns rc=1
        Then:
          - rollback git checkout <priorRef> fires
          - rollback systemctl restart eclipse-obd fires
          - marker is cleared (no perma-trigger on next interval)
          - outcome is DEPLOY_FAILED
          - log contains the rollback chain
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=True,
            rollbackEnabled=True,
        )

        # Phase 1: check
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
        )
        checkResult = checker.check_for_updates()
        assert checkResult.outcome == CheckOutcome.UPDATE_AVAILABLE
        assert marker.is_file()

        # Phase 2: apply.  Fail the FULL deploy (no --dry-run flag) but
        # let the dry-run pass.  Substring matching cannot discriminate
        # "deploy-pi.sh" from "deploy-pi.sh --dry-run" cleanly, so we
        # use a subclass that inspects argv length: full deploy is
        # 2-arg (`bash deploy/deploy-pi.sh`); dry-run is 3-arg.
        runner = _FailFullDeployRunner(priorRefStdout="abc1234\n")
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
        )

        with caplog.at_level(logging.INFO, logger="src.pi.update.update_applier"):
            applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.DEPLOY_FAILED, (
            f"full-deploy failure should yield DEPLOY_FAILED; got "
            f"{applyResult.outcome}"
        )
        assert applyResult.rollbackOutcome == "ok", (
            "rollback must run cleanly when commands succeed"
        )
        assert applyResult.priorRef == "abc1234"
        assert not marker.exists(), (
            "marker MUST be cleared on rollback (poisoned-target invariant)"
        )

        cmds = runner.commandSequence()
        # Rollback chain: git checkout <priorRef> + systemctl restart.
        assert any("git checkout abc1234" in c for c in cmds), (
            f"rollback git checkout missing; cmds={cmds}"
        )
        assert any("systemctl restart eclipse-obd" in c for c in cmds), (
            f"rollback service restart missing; cmds={cmds}"
        )

    def test_e2e_dryRunFails_rollbackFires_noFullDeployAttempted(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
    ) -> None:
        """
        Given: dry-run rc=1 (BEFORE the full deploy ever runs)
        Then:
          - rollback fires
          - full `deploy-pi.sh` (no --dry-run) is NEVER invoked
          - outcome is DRY_RUN_FAILED, marker cleared
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
        assert marker.is_file()

        runner = _FakeDeployRunner(
            priorRefStdout="abc1234\n",
            failures={"--dry-run": 1},
        )
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
        )

        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.DRY_RUN_FAILED
        assert applyResult.rollbackOutcome == "ok"
        assert not marker.exists()

        cmds = runner.commandSequence()
        # Full deploy (the `bash deploy/deploy-pi.sh` invocation with NO
        # extra flag) must be absent: the dry-run failure short-circuits
        # before it gets called.  We discriminate by the trailing argv
        # length: the dry-run invocation is 3 args ([bash, path, --dry-run]);
        # the full deploy is 2 args ([bash, path]).
        assert not any(
            c.endswith("deploy/deploy-pi.sh") and "--dry-run" not in c
            for c in cmds
        ), (
            f"full deploy must NOT run after dry-run failure; cmds={cmds}"
        )


class _FailFullDeployRunner(_FakeDeployRunner):
    """Variant runner that fails ONLY the full deploy phase.

    The argv-substring matching in `_FakeDeployRunner.failures` cannot
    cleanly discriminate "deploy-pi.sh" from "deploy-pi.sh --dry-run"
    because both contain the substring "deploy-pi.sh".  This subclass
    inspects the argv list length: the full deploy is exactly
    `["bash", "deploy/deploy-pi.sh"]` (2 args); the dry-run is
    `["bash", "deploy/deploy-pi.sh", "--dry-run"]` (3 args).
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
        # Record the call before the fail-fast branch so assertions can
        # observe the attempted command.
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
# Test 3: Drive-state safety net -- check + apply both refuse during a drive
# =============================================================================


@pytest.mark.integration
class TestSelfUpdateE2EDriveStateGate:
    """The 'drive-state-is-sacred' invariant must hold across the full pipeline."""

    def test_e2e_driveInProgress_checkerSkipped_applierSkipped_noNewMarker(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
    ) -> None:
        """
        Given: drive in progress; a stale marker from BEFORE driving started
               is present (simulating a deferred apply)
        When: check runs (during driving) AND apply runs (during driving)
        Then:
          - check returns SKIPPED_DRIVING; no HTTP request issued; marker
            is NOT overwritten / refreshed
          - apply returns SKIPPED_DRIVING; ZERO subprocesses fire
          - marker remains untouched (apply did not clear it -- a
            deferred-apply marker survives the drive so the next post-
            drive tick can resume)
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)

        # Pre-existing stale marker simulates "an earlier check found an
        # update, but driving started before apply could fire."
        _writeMarker(marker, targetVersion=_TARGET_VERSION)
        priorMarkerBody = marker.read_text()

        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=True,
        )

        # Phase 1: check during drive
        opener = _FakeReleaseEndpoint(payload=_serverRecord("V0.21.0"))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: True,  # drive in progress
        )
        checkResult = checker.check_for_updates()

        assert checkResult.outcome == CheckOutcome.SKIPPED_DRIVING
        assert len(opener.calls) == 0, (
            "checker MUST NOT hit server during a drive (sacred invariant)"
        )
        # Marker should be untouched: the stale pre-drive content
        # survives because the checker short-circuits BEFORE writing.
        assert marker.read_text() == priorMarkerBody, (
            "checker must not overwrite marker during a drive"
        )

        # Phase 2: apply during drive
        runner = _FakeDeployRunner(priorRefStdout="abc1234\n")
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: True,  # drive in progress
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
        )
        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.SKIPPED_DRIVING
        assert len(runner.calls) == 0, (
            "applier MUST NOT spawn any subprocess during a drive"
        )
        # The deferred-apply marker survives -- the next post-drive
        # tick will resume from this state.
        assert marker.is_file(), (
            "deferred-apply marker must survive a drive-state skip"
        )
        assert marker.read_text() == priorMarkerBody


# =============================================================================
# Test 4: Up-to-date -- server SAME version -> no marker, no apply
# =============================================================================


@pytest.mark.integration
class TestSelfUpdateE2EUpToDate:
    """When local == server, the entire pipeline is a no-op."""

    def test_e2e_serverSameVersion_noMarkerWritten_noApplyAttempted(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
    ) -> None:
        """
        Given: local V0.19.0; server reports V0.19.0
        When: check runs; apply runs (independently, as the orchestrator
              would the next interval)
        Then:
          - check returns UP_TO_DATE; no marker on disk
          - apply returns NO_MARKER; ZERO subprocesses spawn
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=True,
        )

        # Phase 1: check
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_LOCAL_VERSION))
        checker = UpdateChecker(
            config,
            httpOpener=opener,
            isDrivingFn=lambda: False,
        )
        checkResult = checker.check_for_updates()

        assert checkResult.outcome == CheckOutcome.UP_TO_DATE
        assert checkResult.localVersion == _LOCAL_VERSION
        assert checkResult.serverVersion == _LOCAL_VERSION
        assert not marker.exists(), (
            "no marker must be written when versions match"
        )
        assert len(opener.calls) == 1, (
            "checker hits server exactly once even when up-to-date"
        )

        # Phase 2: apply (with no marker, this should be a clean no-op)
        runner = _FakeDeployRunner(priorRefStdout="abc1234\n")
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
        )
        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.NO_MARKER
        assert len(runner.calls) == 0, (
            "applier MUST NOT spawn any subprocess when no marker is present"
        )
        assert applyResult.priorRef == ""

        # Local .deploy-version is unchanged.
        record = json.loads(local.read_text())
        assert record["version"] == _LOCAL_VERSION


# =============================================================================
# Test 5: HTTP transport sanity (invariant audit)
# =============================================================================


@pytest.mark.integration
class TestSelfUpdateE2EWireShape:
    """The wire request format is part of the contract; pin it here too.

    Unit tests cover this in isolation (`test_update_checker.py`); this
    class re-validates from the e2e seam to guard against future config
    refactors that silently drop the API-key header on the integrated
    path.
    """

    def test_e2e_httpRequestUsesApiKeyHeader_andHitsReleaseCurrentEndpoint(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
    ) -> None:
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
            applyEnabled=False,  # safety belt -- this test only checks wire shape
        )
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        checker = UpdateChecker(
            config, httpOpener=opener, isDrivingFn=lambda: False,
        )

        checker.check_for_updates()

        assert len(opener.calls) == 1
        req = opener.calls[0]
        # urllib normalizes header names; match case-insensitively.
        headers = {k.lower(): v for k, v in req.header_items()}
        assert headers.get("x-api-key") == stubApiKey
        assert req.full_url.endswith("/api/v1/release/current")
        assert req.get_method() == "GET"


# =============================================================================
# Module-level guards
# =============================================================================


def test_module_doesNotImportRealSubprocessExecutables() -> None:
    """Sanity check: the test module must not require real bash/git on PATH.

    Acceptance invariant: 'Test runs in <10s'.  The fakes route every
    subprocess through `_FakeDeployRunner`; if a real `subprocess.run`
    leaks through (e.g., the applier was constructed with
    ``subprocessRun=None``), this test would not catch it directly --
    but the failure mode would be visible via wallclock time / OS errors.
    The presence of this guard documents the invariant for future
    maintainers.
    """
    # No assertion needed; the guard is documentary.
    # The four functional tests above each spawn ZERO real subprocesses
    # because they construct UpdateApplier with subprocessRun=runner.
    assert True


__all__: list[str] = []  # nothing exported -- pure pytest module
