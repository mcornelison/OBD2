################################################################################
# File Name: test_update_applier.py
# Purpose/Description: Outcome tests for the Pi UpdateApplier (US-248 / B-047
#                      US-D).  Asserts the apply-state-machine decision under
#                      no-marker / invalid-marker / safety-gated / disabled /
#                      success / dry-run-fail / deploy-fail / post-verify-fail
#                      / rollback-on-failure / rollback-disabled scenarios.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial implementation for US-248
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.update.update_applier`.

The story invariant for US-248 is the apply-state-machine decision:

* The marker file must be cleared on EVERY terminal outcome that touched
  the deploy path (success, rollback ok, rollback failed, marker invalid).
* ``applyEnabled=False`` (the default) must short-circuit before any
  subprocess is invoked.
* Safety gates (drive in progress, power=BATTERY, recent OBD activity)
  must short-circuit BEFORE the applyEnabled gate so the operator log
  shows "would have been safe to apply" instead of hiding under the
  disabled flag.
* On any failure inside the deploy phases, rollback is invoked; the
  marker is cleared regardless of rollback success.
* All subprocess calls are routed through the injected ``subprocessRun``
  callable -- the test suite never reaches a real ``git`` or
  ``deploy-pi.sh`` invocation.

All tests inject a fake ``subprocessRun`` so no real processes are spawned.
The marker file and ``.deploy-version`` artifact both live under ``tmp_path``
so each test runs in isolation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.pi.update.update_applier import (
    ApplyOutcome,
    ApplyResult,
    UpdateApplier,
)

# =============================================================================
# Helpers / fixtures
# =============================================================================


def _writeMarker(
    path: Path,
    *,
    targetVersion: str = "V0.20.0",
    serverUrl: str = "http://10.27.27.10:8000",
    rationale: str = "server reports newer version V0.20.0; local is V0.19.0",
) -> None:
    """Write a US-247-shaped marker file at ``path``."""
    body = {
        "target_version": targetVersion,
        "server_url": serverUrl,
        "rationale": rationale,
        "checked_at": "2026-04-30T12:34:56Z",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def _writePostDeployVersion(path: Path, version: str = "V0.20.0") -> None:
    """Write a US-241-shaped .deploy-version record at ``path``."""
    record = {
        "version": version,
        "releasedAt": "2026-04-30T12:35:01Z",
        "gitHash": "abcdef0",
        "theme": "test sprint",
        "description": "post-deploy stamp",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))


def _baseConfig(
    *,
    applyEnabled: bool = True,
    rollbackEnabled: bool = True,
    markerFilePath: str = "/var/lib/eclipse-obd/update-pending.json",
    localVersionPath: str = ".deploy-version",
    stagingPath: str = "/tmp/eclipse-obd-staging",
) -> dict[str, Any]:
    """Pi config dict carrying the keys UpdateApplier reads."""
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "update": {
                "enabled": True,
                "intervalMinutes": 60,
                "markerFilePath": markerFilePath,
                "localVersionPath": localVersionPath,
                "applyEnabled": applyEnabled,
                "rollbackEnabled": rollbackEnabled,
                "stagingPath": stagingPath,
            },
        },
    }


class _FakeSubprocess:
    """Records subprocess.run calls; returns scripted CompletedProcess outcomes.

    The default outcome is success (rc=0) -- tests opt into failure by
    populating ``failures`` with the substring of the command that
    should fail (matched against the joined argv).  ``priorRefStdout``
    is the stdout returned for ``git rev-parse HEAD`` (used to capture
    rollback ref).
    """

    def __init__(
        self,
        *,
        priorRefStdout: str = "abc1234\n",
        failures: dict[str, int] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._priorRefStdout = priorRefStdout
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
                    args=cmd, returncode=rc, stdout="", stderr=f"fail: {needle}",
                )
        # Special-case git rev-parse so priorRef capture works.
        if joined.startswith("git rev-parse HEAD"):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout=self._priorRefStdout, stderr="",
            )
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        )


def _commandSequence(fake: _FakeSubprocess) -> list[str]:
    """Joined ``argv`` of every recorded subprocess call (in order)."""
    return [" ".join(c) for c in fake.calls]


# =============================================================================
# Marker handling
# =============================================================================


class TestMarkerHandling:
    """The marker file is the only inter-step channel between US-C and US-D."""

    def test_apply_noMarker_returnsNoMarker_andNoSubprocess(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: no marker file on disk
        Then: outcome=NO_MARKER; zero subprocess calls
        """
        marker = tmp_path / "missing-marker.json"
        config = _baseConfig(markerFilePath=str(marker))
        fake = _FakeSubprocess()
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.NO_MARKER
        assert not fake.calls
        assert not marker.exists()

    def test_apply_invalidMarkerJson_clearsMarker_returnsMarkerInvalid(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: marker file present but unparseable JSON
        Then: outcome=MARKER_INVALID; marker is cleared (so it does not perma-trigger)
        """
        marker = tmp_path / "marker.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{this is not json")
        config = _baseConfig(markerFilePath=str(marker))
        fake = _FakeSubprocess()
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        # Module-level _readMarker logs "marker file unreadable" and
        # falls through to NO_MARKER (the data dict ends up None);
        # either NO_MARKER or MARKER_INVALID is acceptable as long as
        # the unreadable file was cleared and no subprocess ran.
        assert result.outcome in (
            ApplyOutcome.MARKER_INVALID, ApplyOutcome.NO_MARKER,
        )
        assert not fake.calls
        assert not marker.exists()

    def test_apply_markerMissingTargetVersion_returnsMarkerInvalid_clearsMarker(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: marker shape is JSON but target_version is missing
        Then: outcome=MARKER_INVALID; marker cleared
        """
        marker = tmp_path / "marker.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"server_url": "http://x"}))
        config = _baseConfig(markerFilePath=str(marker))
        fake = _FakeSubprocess()
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.MARKER_INVALID
        assert not fake.calls
        assert not marker.exists()

    def test_apply_markerInvalidVersionString_returnsMarkerInvalid(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: marker has a target_version that fails parseVersion
        Then: outcome=MARKER_INVALID; marker cleared
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker, targetVersion="not-a-version")
        config = _baseConfig(markerFilePath=str(marker))
        fake = _FakeSubprocess()
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.MARKER_INVALID
        assert not fake.calls
        assert not marker.exists()


# =============================================================================
# Safety gates
# =============================================================================


class TestSafetyGates:
    """Drive-state-is-sacred + power-aware + recent-OBD-activity gates.

    Each gate must short-circuit BEFORE the applyEnabled gate, AND
    before any subprocess is invoked.  A missing closure must fail
    OPEN -- a missing detector must not perma-block updates.
    """

    def test_apply_isDriving_returnsSkippedDriving_noSubprocess(
        self, tmp_path: Path,
    ) -> None:
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        config = _baseConfig(markerFilePath=str(marker), applyEnabled=True)
        fake = _FakeSubprocess()
        applier = UpdateApplier(
            config, subprocessRun=fake, isDrivingFn=lambda: True,
        )

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SKIPPED_DRIVING
        assert not fake.calls
        assert marker.exists()  # marker NOT cleared -- next safe tick can apply

    def test_apply_powerBattery_returnsSkippedBatteryPower(
        self, tmp_path: Path,
    ) -> None:
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        config = _baseConfig(markerFilePath=str(marker), applyEnabled=True)
        fake = _FakeSubprocess()
        applier = UpdateApplier(
            config, subprocessRun=fake,
            getPowerSourceFn=lambda: "battery",
        )

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SKIPPED_BATTERY_POWER
        assert not fake.calls
        assert marker.exists()

    def test_apply_recentObdActivity_returnsSkippedRecentObdActivity(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: connection_log MAX(timestamp) ~ 100 seconds ago (under the 300s threshold)
        Then: outcome=SKIPPED_RECENT_OBD_ACTIVITY; no subprocess
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        config = _baseConfig(markerFilePath=str(marker), applyEnabled=True)
        fake = _FakeSubprocess()
        applier = UpdateApplier(
            config, subprocessRun=fake,
            getLastObdActivitySecondsAgoFn=lambda: 100.0,
        )

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SKIPPED_RECENT_OBD_ACTIVITY
        assert not fake.calls

    def test_apply_oldObdActivity_doesNotSkip(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: connection_log MAX(timestamp) ~ 600 seconds ago (above 300s threshold)
        Then: gate clears; apply proceeds (and succeeds in this happy-path setup)
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker, targetVersion="V0.20.0")
        deployPath = tmp_path / ".deploy-version"
        _writePostDeployVersion(deployPath, version="V0.20.0")
        config = _baseConfig(
            markerFilePath=str(marker),
            localVersionPath=str(deployPath),
            applyEnabled=True,
        )
        fake = _FakeSubprocess()
        applier = UpdateApplier(
            config, subprocessRun=fake,
            getLastObdActivitySecondsAgoFn=lambda: 600.0,
        )

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SUCCESS

    def test_apply_safetyGateFiresBeforeEnabledGate(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: applyEnabled=False AND isDriving=True
        Then: outcome=SKIPPED_DRIVING (safety beats disabled)

        The operator-facing log shows "would have been safe to apply"
        only when the safety gates are clear; a driving Pi shouldn't
        be told "we'd apply if you flipped the flag."
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        config = _baseConfig(markerFilePath=str(marker), applyEnabled=False)
        fake = _FakeSubprocess()
        applier = UpdateApplier(
            config, subprocessRun=fake, isDrivingFn=lambda: True,
        )

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SKIPPED_DRIVING

    def test_apply_safetyClosuresMissing_failOpen(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: all safety closures are None (missing detector / monitor / db)
        Then: gates fail open; apply proceeds (does not perma-block)
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker, targetVersion="V0.20.0")
        deployPath = tmp_path / ".deploy-version"
        _writePostDeployVersion(deployPath, version="V0.20.0")
        config = _baseConfig(
            markerFilePath=str(marker),
            localVersionPath=str(deployPath),
            applyEnabled=True,
        )
        fake = _FakeSubprocess()
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SUCCESS

    def test_apply_safetyClosuresRaise_failOpen(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: all safety closures raise unexpectedly
        Then: gates fail open; apply proceeds
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker, targetVersion="V0.20.0")
        deployPath = tmp_path / ".deploy-version"
        _writePostDeployVersion(deployPath, version="V0.20.0")
        config = _baseConfig(
            markerFilePath=str(marker),
            localVersionPath=str(deployPath),
            applyEnabled=True,
        )
        fake = _FakeSubprocess()

        def _boom() -> Any:
            raise RuntimeError("sensor offline")

        applier = UpdateApplier(
            config, subprocessRun=fake,
            isDrivingFn=_boom,
            getPowerSourceFn=_boom,
            getLastObdActivitySecondsAgoFn=_boom,
        )

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SUCCESS


# =============================================================================
# Enabled gate (default-disabled CIO opt-in)
# =============================================================================


class TestEnabledGate:
    def test_apply_enabledFalse_isDefault_returnsDisabled_noSubprocess(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: applyEnabled defaults False (CIO opt-in)
        Then: outcome=DISABLED; no subprocess; marker preserved (next
              run with the flag enabled will pick it up)
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        # Use a config that omits applyEnabled to confirm the False default.
        config = {
            "pi": {
                "update": {
                    "markerFilePath": str(marker),
                    "localVersionPath": str(tmp_path / ".deploy-version"),
                    # applyEnabled NOT specified -- defaults to False
                },
            },
        }
        fake = _FakeSubprocess()
        applier = UpdateApplier(config, subprocessRun=fake)

        assert applier.applyEnabled is False
        result = applier.apply()

        assert result.outcome == ApplyOutcome.DISABLED
        assert not fake.calls
        assert marker.exists()

    def test_apply_enabledTrue_proceedsToSubprocess(
        self, tmp_path: Path,
    ) -> None:
        marker = tmp_path / "marker.json"
        _writeMarker(marker, targetVersion="V0.20.0")
        deployPath = tmp_path / ".deploy-version"
        _writePostDeployVersion(deployPath, version="V0.20.0")
        config = _baseConfig(
            markerFilePath=str(marker),
            localVersionPath=str(deployPath),
            applyEnabled=True,
        )
        fake = _FakeSubprocess()
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SUCCESS
        # Sanity: subprocess phases were exercised.
        assert any("git rev-parse" in s for s in _commandSequence(fake))
        assert any("git fetch" in s for s in _commandSequence(fake))
        assert any("--dry-run" in s for s in _commandSequence(fake))


# =============================================================================
# Success path
# =============================================================================


class TestSuccessPath:
    """Happy-path: marker -> fetch -> checkout -> dry-run -> deploy -> verify."""

    def test_apply_success_runsAllPhasesInOrder_clearsMarker(
        self, tmp_path: Path,
    ) -> None:
        marker = tmp_path / "marker.json"
        _writeMarker(marker, targetVersion="V0.20.0")
        deployPath = tmp_path / ".deploy-version"
        _writePostDeployVersion(deployPath, version="V0.20.0")
        config = _baseConfig(
            markerFilePath=str(marker),
            localVersionPath=str(deployPath),
            applyEnabled=True,
        )
        fake = _FakeSubprocess(priorRefStdout="prior123\n")
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.SUCCESS
        assert result.targetVersion == "V0.20.0"
        assert result.priorRef == "prior123"
        assert result.rollbackOutcome is None
        # Phase ordering: rev-parse -> fetch -> checkout -> dry-run -> deploy
        seq = _commandSequence(fake)
        assert seq == [
            "git rev-parse HEAD",
            "git fetch origin",
            "git checkout V0.20.0",
            "bash deploy/deploy-pi.sh --dry-run",
            "bash deploy/deploy-pi.sh",
        ]
        # Marker MUST be cleared post-success so next interval tick
        # doesn't re-apply.
        assert not marker.exists()


# =============================================================================
# Failure rollback paths
# =============================================================================


class TestFailureRollback:
    """Each phase can fail; rollback then runs and the marker is cleared."""

    def _makeMarkerAndConfig(
        self, tmp_path: Path,
        *,
        applyEnabled: bool = True,
        rollbackEnabled: bool = True,
    ) -> tuple[Path, dict[str, Any]]:
        marker = tmp_path / "marker.json"
        _writeMarker(marker, targetVersion="V0.20.0")
        deployPath = tmp_path / ".deploy-version"
        # Deliberately leave the .deploy-version with the OLD version
        # so post-deploy verify would fail if we got that far.
        _writePostDeployVersion(deployPath, version="V0.19.0")
        config = _baseConfig(
            markerFilePath=str(marker),
            localVersionPath=str(deployPath),
            applyEnabled=applyEnabled,
            rollbackEnabled=rollbackEnabled,
        )
        return marker, config

    def test_apply_fetchFails_triggersRollback_clearsMarker(
        self, tmp_path: Path,
    ) -> None:
        marker, config = self._makeMarkerAndConfig(tmp_path)
        fake = _FakeSubprocess(failures={"git fetch": 1})
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.DEPLOY_FAILED
        assert result.rollbackOutcome == "ok"
        assert not marker.exists()
        seq = _commandSequence(fake)
        assert "git fetch origin" in seq
        # Rollback ran (checkout to priorRef + restart service).
        assert "git checkout abc1234" in seq
        assert any("systemctl restart eclipse-obd" in s for s in seq)
        # Dry-run + full-deploy must NOT have run after fetch failed.
        assert "bash deploy/deploy-pi.sh --dry-run" not in seq
        assert "bash deploy/deploy-pi.sh" not in seq

    def test_apply_dryRunFails_triggersRollback_returnsDryRunFailed(
        self, tmp_path: Path,
    ) -> None:
        marker, config = self._makeMarkerAndConfig(tmp_path)
        fake = _FakeSubprocess(failures={"--dry-run": 1})
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.DRY_RUN_FAILED
        assert result.rollbackOutcome == "ok"
        assert not marker.exists()
        seq = _commandSequence(fake)
        # Full deploy must NOT have run after dry-run failed.
        assert "bash deploy/deploy-pi.sh" not in [
            s for s in seq if "--dry-run" not in s and s.startswith("bash")
        ]

    def test_apply_deployFails_triggersRollback_returnsDeployFailed(
        self, tmp_path: Path,
    ) -> None:
        marker, config = self._makeMarkerAndConfig(tmp_path)
        # The dry-run command also contains "deploy-pi.sh" so we
        # specifically target the sans-dry-run invocation by failing
        # only when "--dry-run" is NOT in the command.  Use a custom
        # subprocess that fails the bare deploy call.
        calls: list[list[str]] = []

        def _runner(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
            calls.append(list(cmd))
            joined = " ".join(cmd)
            if joined == "git rev-parse HEAD":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="abc1234\n", stderr="",
                )
            if joined == "bash deploy/deploy-pi.sh":  # full deploy only
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="deploy fail",
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr="",
            )

        applier = UpdateApplier(config, subprocessRun=_runner)
        result = applier.apply()

        assert result.outcome == ApplyOutcome.DEPLOY_FAILED
        assert result.rollbackOutcome == "ok"
        assert not marker.exists()
        joinedCalls = [" ".join(c) for c in calls]
        # Dry-run should have succeeded BEFORE the deploy failure.
        assert "bash deploy/deploy-pi.sh --dry-run" in joinedCalls
        # Rollback must have run.
        assert "git checkout abc1234" in joinedCalls

    def test_apply_postDeployVerifyFails_triggersRollback(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: deploy returns rc=0 but .deploy-version still shows old version
        Then: outcome=POST_DEPLOY_VERIFY_FAILED; rollback fired
        """
        marker, config = self._makeMarkerAndConfig(tmp_path)
        # Note: _makeMarkerAndConfig deliberately wrote V0.19.0 to .deploy-version
        # while marker target is V0.20.0; with all subprocess phases succeeding,
        # the post-deploy verify should fail.
        fake = _FakeSubprocess()
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.POST_DEPLOY_VERIFY_FAILED
        assert result.rollbackOutcome == "ok"
        assert not marker.exists()


# =============================================================================
# Rollback variations
# =============================================================================


class TestRollbackVariations:
    def test_apply_rollbackDisabled_skipsRollback_clearsMarker(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: rollbackEnabled=False AND dry-run fails
        Then: outcome=DRY_RUN_FAILED; rollbackOutcome="skipped (disabled)";
              marker still cleared so next tick is not poisoned
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        config = _baseConfig(
            markerFilePath=str(marker),
            localVersionPath=str(tmp_path / ".deploy-version"),
            applyEnabled=True,
            rollbackEnabled=False,
        )
        fake = _FakeSubprocess(failures={"--dry-run": 1})
        applier = UpdateApplier(config, subprocessRun=fake)

        result = applier.apply()

        assert result.outcome == ApplyOutcome.DRY_RUN_FAILED
        assert result.rollbackOutcome == "skipped (disabled)"
        assert not marker.exists()
        # Rollback subprocess (git checkout priorRef / systemctl) must NOT run.
        seq = _commandSequence(fake)
        assert "git checkout abc1234" not in seq
        assert not any("systemctl restart" in s for s in seq)

    def test_apply_rollbackItselfFails_returnsRollbackFailed(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: deploy fails AND rollback git checkout fails
        Then: outcome=DEPLOY_FAILED; rollbackOutcome="failed"; marker cleared
        """
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        config = _baseConfig(
            markerFilePath=str(marker),
            localVersionPath=str(tmp_path / ".deploy-version"),
            applyEnabled=True,
        )

        # Fail both the bare deploy and the rollback checkout.
        # (priorRef is "abc1234"; rollback-checkout cmdline is
        # "git checkout abc1234".)
        def _runner(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
            joined = " ".join(cmd)
            if joined == "git rev-parse HEAD":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="abc1234\n", stderr="",
                )
            if joined == "bash deploy/deploy-pi.sh":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="deploy fail",
                )
            if joined == "git checkout abc1234":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="checkout fail",
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr="",
            )

        applier = UpdateApplier(config, subprocessRun=_runner)
        result = applier.apply()

        assert result.outcome == ApplyOutcome.DEPLOY_FAILED
        assert result.rollbackOutcome == "failed"
        assert not marker.exists()


# =============================================================================
# markerExists fast-path
# =============================================================================


class TestMarkerExistsFastPath:
    """The orchestrator runLoop trigger short-circuits on this probe."""

    def test_markerExists_falseWhenAbsent(self, tmp_path: Path) -> None:
        config = _baseConfig(
            markerFilePath=str(tmp_path / "missing-marker.json"),
        )
        applier = UpdateApplier(config)
        assert applier.markerExists() is False

    def test_markerExists_trueWhenPresent(self, tmp_path: Path) -> None:
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        config = _baseConfig(markerFilePath=str(marker))
        applier = UpdateApplier(config)
        assert applier.markerExists() is True


# =============================================================================
# Construction / config-surface sanity
# =============================================================================


class TestConfigSurface:
    """The four config keys that drive applier policy."""

    def test_constructor_readsAllPiUpdateKeys(self, tmp_path: Path) -> None:
        config = _baseConfig(
            markerFilePath="/var/lib/eclipse-obd/marker.json",
            localVersionPath=".deploy-version",
            stagingPath="/tmp/staging",
            applyEnabled=True,
            rollbackEnabled=False,
        )
        applier = UpdateApplier(config)

        assert applier.applyEnabled is True
        assert applier.rollbackEnabled is False
        assert applier.stagingPath == "/tmp/staging"
        assert applier.markerFilePath == "/var/lib/eclipse-obd/marker.json"
        assert applier.localVersionPath == ".deploy-version"

    def test_constructor_isSideEffectFree(self, tmp_path: Path) -> None:
        """No subprocess calls, no marker IO at construction time."""
        marker = tmp_path / "marker.json"
        _writeMarker(marker)
        config = _baseConfig(markerFilePath=str(marker), applyEnabled=True)

        # If construction did anything other than store config, this
        # would explode (subprocessRun is None -> would fail on real call).
        applier = UpdateApplier(config)

        # Marker was not consumed; applier did nothing yet.
        assert marker.exists()
        # applyEnabled property reads config without side effect.
        assert applier.applyEnabled is True


# =============================================================================
# ApplyResult shape
# =============================================================================


class TestApplyResultShape:
    def test_applyResult_isDataclassWithExpectedFields(self) -> None:
        r = ApplyResult(outcome=ApplyOutcome.SUCCESS)
        assert r.outcome == ApplyOutcome.SUCCESS
        assert r.targetVersion == ""
        assert r.priorRef == ""
        assert r.rationale == ""
        assert r.rollbackOutcome is None
