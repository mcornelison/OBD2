################################################################################
# File Name: test_self_update_rollback_drill.py
# Purpose/Description: US-294 (B-047 auto-rollback drill).  Synthetic
#                      "broken release" e2e drill: deploy returns rc=0,
#                      .deploy-version is stamped to the new version, but
#                      ``systemctl is-active eclipse-obd`` reports
#                      ``inactive`` for the entire 60-sec watchdog window.
#                      Asserts (a) rollback fires, (b) ``.deploy-version``
#                      reverts to the prior good content (raw-bytes
#                      restore), (c) the service is ``active`` after the
#                      rollback's own restart -- the three contracts that
#                      D3 of B-047 mandates and that pre-fix are entirely
#                      unwired (the existing US-248 rollback only fires on
#                      subprocess rc!=0; a syntax error in main.py would
#                      land deploy-pi.sh rc=0 + a poisoned service that
#                      this drill catches via the new
#                      ``ApplyOutcome.SERVICE_HEALTH_FAILED`` path).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex          | Initial -- US-294 auto-rollback drill
# ================================================================================
################################################################################

"""US-294 -- B-047 auto-rollback drill (Driving Season Open).

The gap this closes
-------------------
US-248 (Sprint 20) shipped a rollback that fires on subprocess ``rc != 0``
in any of the deploy phases (fetch / checkout / dry-run / deploy / version
verify).  But a deploy can succeed at the subprocess level AND stamp the
correct ``.deploy-version`` AND still leave a poisoned service -- a syntax
error in ``main.py`` lets ``deploy-pi.sh`` exit cleanly, the systemctl
restart command itself returns rc=0, and the service then crash-loops
silently.  D3 of B-047 mandates::

    Pi watches eclipse-obd.service health post-update; if the service
    fails to reach `active` within a configured timeout (proposal:
    60 sec), Pi automatically rolls back to the previous .deploy-version
    snapshot.

Pre-fix the entire watchdog mechanism is missing.  This drill is the
durable regression gate: with the watchdog wired, a broken release
recovers within 60 sec; without it, the bug class that motivated the
story (auto-update fires every key-on once Pi is car-coupled, Spool
2026-05-06) would silently brick the Pi until CIO physical intervention.

Mock surface
------------
Per US-294 invariant "Rollback triggers ONLY on service-not-active within
60s; does NOT trigger on application-level errors that don't crash the
service":

* HTTP via ``UpdateChecker(httpOpener=...)`` -- same seam as US-258 /
  US-293 fixtures (mirrored verbatim where possible so a future
  maintainer reading all three files sees a consistent shape).
* Subprocesses via ``UpdateApplier(subprocessRun=...)`` -- same seam.
* Wall clock via ``UpdateApplier(nowFn=..., sleepFn=...)`` -- new test
  seams added by US-294 so the 60-sec watchdog runs in zero wallclock.
  The ``_FakeClock`` advances time by the requested sleep duration and
  exposes a list of every recorded sleep so the test can pin both the
  cumulative budget AND the poll cadence.

Why a real ``systemctl is-active`` simulation
---------------------------------------------
Mocking at the ``_verifyServiceHealth`` boundary would let a silently
broken poll loop slip through (the same bug class as the US-267 fsync
gap).  The fake instead scripts the literal stdout that
``systemctl is-active`` produces -- ``"active"`` for healthy,
``"inactive"`` / ``"failed"`` / ``"activating"`` for the broken-release
case -- and returns those through the same ``subprocess.run``-shaped
seam every other phase uses.
"""

from __future__ import annotations

import json
import subprocess
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
# Fakes -- HTTP, subprocess, clock seams
# =============================================================================


class _FakeReleaseEndpoint:
    """``urlopen``-shaped fake serving a scripted server-release record.

    Mirrors the US-258 / US-293 fixture verbatim so a future maintainer
    reading all three files sees the same shape.
    """

    def __init__(self, *, payload: dict[str, Any]) -> None:
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


class _FakeClock:
    """Deterministic clock -- ``__call__`` reads, ``sleep`` advances.

    The watchdog loop polls + sleeps in a tight pattern; injecting both
    seams as a single fake lets the test assert (a) total elapsed budget,
    (b) per-sleep cadence, without spinning real wallclock seconds.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _BrokenReleaseRunner:
    """``subprocess.run``-shaped fake that scripts the post-deploy
    "service never reaches active" failure mode.

    Every deploy-pipeline subprocess returns rc=0 with the realistic
    side-effect (``.deploy-version`` stamp on full deploy).  Every
    ``systemctl is-active eclipse-obd`` call BEFORE the rollback-restart
    completes returns ``inactive`` (D3's broken-release pathology).
    AFTER the rollback git-checkout + restart, subsequent ``is-active``
    queries return ``active`` -- modeling the prior-version recovery.
    """

    def __init__(
        self,
        *,
        priorRefStdout: str = "abc1234\n",
        deployStampPath: Path,
        deployStampVersion: str,
        priorRef: str = "abc1234",
    ) -> None:
        self.calls: list[list[str]] = []
        self._priorRefStdout = priorRefStdout
        self._deployStampPath = deployStampPath
        self._deployStampVersion = deployStampVersion
        self._priorRef = priorRef
        self._rolledBack = False

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

        if joined.startswith("git rev-parse HEAD"):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout=self._priorRefStdout, stderr="",
            )

        if joined == f"git checkout {self._priorRef}":
            # rollback's own checkout to priorRef; mark the inflection
            # point so subsequent is-active queries return "active"
            self._rolledBack = True
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr="",
            )

        if joined.startswith("systemctl is-active"):
            stdout = "active\n" if self._rolledBack else "inactive\n"
            # rc=0 only for "active"; the convention systemctl follows
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0 if self._rolledBack else 3,
                stdout=stdout, stderr="",
            )

        if (
            "deploy-pi.sh" in joined
            and "--dry-run" not in joined
        ):
            # Full deploy stamps .deploy-version with the BAD version
            # (the file IS overwritten before the silent service crash).
            self._stampDeployVersion()

        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        )

    def _stampDeployVersion(self) -> None:
        record = {
            "version": self._deployStampVersion,
            "releasedAt": "2026-05-08T12:00:00Z",
            "gitHash": "badbeef",
            "theme": "Sprint 26 broken-release fixture",
            "description": "fake deploy-pi.sh stamp for US-294 drill",
        }
        self._deployStampPath.parent.mkdir(parents=True, exist_ok=True)
        self._deployStampPath.write_text(json.dumps(record))


# =============================================================================
# Helpers / fixtures
# =============================================================================


_LOCAL_VERSION = "V0.20.0"
_TARGET_VERSION = "V0.21.0"


def _writeLocalDeployVersion(
    path: Path,
    version: str,
    *,
    gitHash: str = "d8583d3",
) -> str:
    """Write a US-241-shaped local ``.deploy-version`` and return the raw text."""
    record = {
        "version": version,
        "releasedAt": "2026-04-29T08:29:24Z",
        "gitHash": gitHash,
        "theme": "Sprint 25 (prior good)",
        "description": "local deploy stamp pre-update",
    }
    text = json.dumps(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def _serverRecord(version: str) -> dict[str, Any]:
    return {
        "version": version,
        "releasedAt": "2026-05-08T12:00:00Z",
        "gitHash": "badbeef",
        "theme": "Sprint 26",
        "description": "server release",
    }


def _e2eConfig(
    *,
    localVersionPath: str,
    markerFilePath: str,
    serviceHealthTimeoutSeconds: float = 60.0,
    serviceHealthPollIntervalSeconds: float = 2.0,
) -> dict[str, Any]:
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
                "applyEnabled": True,
                "rollbackEnabled": True,
                "stagingPath": "/tmp/eclipse-obd-staging-test",
                "serviceHealthTimeoutSeconds": serviceHealthTimeoutSeconds,
                "serviceHealthPollIntervalSeconds": serviceHealthPollIntervalSeconds,
            },
        },
    }


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-us294")
    return "test-key-us294"


@pytest.fixture(autouse=True)
def _isolatedCooldownPath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-test isolation for the US-296 cooldown timestamp file.

    US-294 rollback drills exercise the real UpdateChecker; US-296
    added an on-disk cooldown side effect.  Stub the default path
    to a per-test tmp_path so a successful check in one test does
    not bleed cooldown into the next test's run.
    """
    isolated = tmp_path / "_us296_cooldown_unused.timestamp"
    monkeypatch.setattr(
        "src.pi.update.update_checker._DEFAULT_COOLDOWN_TIMESTAMP_PATH",
        str(isolated),
    )


@pytest.fixture
def e2ePaths(tmp_path: Path) -> dict[str, Path]:
    return {
        "local": tmp_path / ".deploy-version",
        "marker": tmp_path / "var" / "lib" / "eclipse-obd" / "update-pending.json",
    }


# =============================================================================
# Test 1 -- DISCRIMINATOR: broken release triggers SERVICE_HEALTH_FAILED +
#                        rollback restores .deploy-version + service is active
# =============================================================================


@pytest.mark.integration
class TestRollbackOnBrokenReleaseDrill:
    """The B-047 D3 contract -- pre-fix this class FAILS.

    Pre-fix failure mode: the entire ``ApplyOutcome.SERVICE_HEALTH_FAILED``
    enumeration value does not exist (ImportError on test collection),
    AND the production code never polls ``systemctl is-active``.  Even
    if the test is rewritten to use an existing outcome, the bare deploy
    succeeds and the apply returns SUCCESS -- the rollback never fires.
    """

    def test_brokenRelease_serviceNeverActive_rollbackRestoresDeployVersion(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
    ) -> None:
        """
        Given: local V0.20.0; server returns V0.21.0; deploy-pi.sh succeeds
               and stamps .deploy-version V0.21.0 BUT systemctl reports
               inactive for the entire 60-sec watchdog window
        When: UpdateChecker writes the marker; UpdateApplier.apply()
              runs with applyEnabled=True; clock injected so the 60-sec
              watchdog completes in zero wallclock
        Then:
          - outcome == ApplyOutcome.SERVICE_HEALTH_FAILED
          - rollbackOutcome == "ok"
          - .deploy-version content reverts to the prior good record
            (D3 invariant: rollback restores prior snapshot)
          - subprocess sequence after deploy includes a series of
            systemctl is-active polls (watchdog), then the rollback chain
            (git checkout priorRef + systemctl restart eclipse-obd) AND
            a confirming systemctl is-active that returns active
          - cumulative slept time ~60 sec (configured budget)
          - marker is cleared (rollback path always clears marker)
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        priorRecordText = _writeLocalDeployVersion(
            local, version=_LOCAL_VERSION,
        )
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )

        # Phase 1: real UpdateChecker writes the marker.
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        checkResult = UpdateChecker(
            config, httpOpener=opener, isDrivingFn=lambda: False,
        ).check_for_updates()
        assert checkResult.outcome == CheckOutcome.UPDATE_AVAILABLE
        assert marker.is_file()

        # Phase 2: real UpdateApplier with broken-release runner +
        # injectable clock so the 60-sec watchdog runs in zero wallclock.
        clock = _FakeClock()
        runner = _BrokenReleaseRunner(
            priorRefStdout="abc1234\n",
            deployStampPath=local,
            deployStampVersion=_TARGET_VERSION,
            priorRef="abc1234",
        )
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
            nowFn=clock,
            sleepFn=clock.sleep,
        )
        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.SERVICE_HEALTH_FAILED, (
            "broken release with deploy rc=0 + service-never-active "
            "must surface SERVICE_HEALTH_FAILED, NOT a successful SUCCESS "
            "(the bug class US-294 closes); got "
            f"{applyResult.outcome} ({applyResult.rationale})"
        )
        assert applyResult.rollbackOutcome == "ok", (
            "rollback must succeed (priorRef checkout + systemctl restart "
            "+ post-rollback service-health verify); got "
            f"{applyResult.rollbackOutcome}"
        )

        # The .deploy-version reverts to the prior good content.
        # Compare the parsed record so json key ordering does not bite.
        currentRecord = json.loads(local.read_text())
        priorRecord = json.loads(priorRecordText)
        assert currentRecord == priorRecord, (
            f"rollback must restore .deploy-version to the prior content "
            f"(D3 invariant); pre-rollback target was {_TARGET_VERSION}, "
            f"post-rollback expected {priorRecord['version']}, "
            f"got {currentRecord.get('version')!r}"
        )

        # Subprocess phase ordering: deploy -> watchdog polls inactive*
        # -> rollback git checkout abc1234 -> systemctl restart eclipse-obd
        # -> confirming is-active = active.
        cmds = [" ".join(c) for c in runner.calls]
        deployIdx = next(
            i for i, c in enumerate(cmds)
            if c == "bash deploy/deploy-pi.sh"
        )
        rollbackCheckoutIdx = next(
            i for i, c in enumerate(cmds) if c == "git checkout abc1234"
        )
        rollbackRestartIdx = next(
            i for i, c in enumerate(cmds)
            if "systemctl restart eclipse-obd" in c
        )
        # Watchdog polls happen between deploy and rollback checkout.
        watchdogPollIndices = [
            i for i, c in enumerate(cmds)
            if c.startswith("systemctl is-active")
            and deployIdx < i < rollbackCheckoutIdx
        ]
        assert deployIdx < rollbackCheckoutIdx < rollbackRestartIdx, (
            f"phase ordering violated: {cmds}"
        )
        assert len(watchdogPollIndices) >= 2, (
            f"watchdog must poll multiple times across the 60-sec window; "
            f"saw {len(watchdogPollIndices)} polls"
        )

        # Confirming is-active after rollback restart MUST return active.
        postRollbackPolls = [
            i for i, c in enumerate(cmds)
            if c.startswith("systemctl is-active") and i > rollbackRestartIdx
        ]
        assert postRollbackPolls, (
            "post-rollback service-health verify must run a confirming "
            "systemctl is-active (asserts service active after rollback); "
            f"saw none after restart at index {rollbackRestartIdx}"
        )

        # Cumulative slept time should land near the configured budget
        # (60s) -- watchdog polled until the deadline.  Allow >=58s
        # because the loop checks deadline AFTER the poll, so the final
        # iteration may sleep past 60 only if the implementation chose
        # to.  Strict 60-sec cap is documented in the production-side
        # invariant; this assertion just confirms we waited near the
        # full budget rather than bailing on poll #1.
        totalSlept = sum(clock.sleeps)
        assert totalSlept >= 58.0, (
            f"watchdog should have slept near the 60-sec budget; "
            f"total slept = {totalSlept:.1f}s (sleeps={clock.sleeps})"
        )

        # Marker cleared on rollback (existing US-248 invariant preserved).
        assert not marker.exists()


# =============================================================================
# Test 2 -- GUARDRAIL: happy-path service-active doesn't trigger rollback
# =============================================================================


@pytest.mark.integration
class TestHappyPathServiceActiveDoesNotTriggerRollback:
    """The watchdog must be a SAFETY net, not a regression hazard.

    A successful deploy whose service comes up active on the first poll
    must complete with SUCCESS, no rollback, no extra wallclock.  Pin
    this contract here so a future regression that flips the watchdog's
    "active" / "inactive" inference (e.g., comparing rc instead of
    stdout) is caught immediately.
    """

    def test_serviceActiveOnFirstPoll_returnsSuccess_noRollback(
        self,
        e2ePaths: dict[str, Path],
        stubApiKey: str,
    ) -> None:
        """
        Given: deploy-pi.sh stamps .deploy-version V0.21.0 + the very
               first systemctl is-active poll returns "active"
        Then:
          - outcome == SUCCESS
          - rollbackOutcome is None
          - exactly ONE systemctl is-active poll fired (first poll wins)
          - cumulative slept time == 0 (no inactive sleeps)
          - .deploy-version remains V0.21.0
        """
        local = e2ePaths["local"]
        marker = e2ePaths["marker"]
        _writeLocalDeployVersion(local, version=_LOCAL_VERSION)
        config = _e2eConfig(
            localVersionPath=str(local),
            markerFilePath=str(marker),
        )
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        UpdateChecker(
            config, httpOpener=opener, isDrivingFn=lambda: False,
        ).check_for_updates()

        clock = _FakeClock()
        runner = _BrokenReleaseRunner(
            priorRefStdout="abc1234\n",
            deployStampPath=local,
            deployStampVersion=_TARGET_VERSION,
            priorRef="abc1234",
        )
        # Force the runner to behave as if rollback already happened so
        # is-active returns "active" on first poll -- this models the
        # happy path without standing up a separate fake class.
        runner._rolledBack = True

        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
            nowFn=clock,
            sleepFn=clock.sleep,
        )
        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.SUCCESS, (
            f"first-poll-active must succeed; got {applyResult.outcome} "
            f"({applyResult.rationale})"
        )
        assert applyResult.rollbackOutcome is None, (
            f"happy path must NOT trigger rollback; got "
            f"{applyResult.rollbackOutcome}"
        )

        cmds = [" ".join(c) for c in runner.calls]
        deployIdx = next(
            i for i, c in enumerate(cmds)
            if c == "bash deploy/deploy-pi.sh"
        )
        postDeployPolls = [
            i for i, c in enumerate(cmds)
            if c.startswith("systemctl is-active") and i > deployIdx
        ]
        assert len(postDeployPolls) == 1, (
            f"first-poll-active must short-circuit; saw "
            f"{len(postDeployPolls)} polls after deploy"
        )
        assert clock.sleeps == [], (
            f"first-poll-active must not sleep; got sleeps={clock.sleeps}"
        )

        # No rollback subprocess fired.
        assert not any("git checkout abc1234" == c for c in cmds), (
            f"happy path must NOT run rollback git checkout; "
            f"saw {cmds}"
        )

        # .deploy-version remains the new version (deploy stamped it).
        currentRecord = json.loads(local.read_text())
        assert currentRecord["version"] == _TARGET_VERSION


# =============================================================================
# Test 3 -- GUARDRAIL: rollback's restart fails -> rollbackOutcome="failed"
# =============================================================================


class _RollbackRestartFailsRunner(_BrokenReleaseRunner):
    """Variant: rollback's git-checkout succeeds but the post-checkout
    systemctl restart fails.  Models a corrupted prior version that
    cannot start either -- the pathological "rollback to a broken
    snapshot" scenario.  Confirms rollbackOutcome="failed" propagates.
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
        joined = " ".join(cmd)
        if joined.startswith("sudo systemctl restart eclipse-obd"):
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout="",
                stderr="fake fail: rollback restart",
            )
        return super().__call__(
            cmd,
            capture_output=capture_output,
            text=text,
            check=check,
            timeout=timeout,
        )


@pytest.mark.integration
class TestRollbackItselfFailingPropagates:
    """Service-unhealthy + rollback's own restart fails -> rollbackOutcome=failed.

    The outer outcome MUST stay SERVICE_HEALTH_FAILED -- the apply did
    fail at the service-health gate; the rollback failure is reported
    in rollbackOutcome.  This pins the contract that rollback failures
    do NOT mask the original failure cause (operator post-mortem
    requirement from B-047 line 115).
    """

    def test_serviceHealthFailed_rollbackRestartAlsoFails_rollbackOutcomeFailed(
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
        )
        opener = _FakeReleaseEndpoint(payload=_serverRecord(_TARGET_VERSION))
        UpdateChecker(
            config, httpOpener=opener, isDrivingFn=lambda: False,
        ).check_for_updates()

        clock = _FakeClock()
        runner = _RollbackRestartFailsRunner(
            priorRefStdout="abc1234\n",
            deployStampPath=local,
            deployStampVersion=_TARGET_VERSION,
            priorRef="abc1234",
        )
        applier = UpdateApplier(
            config,
            subprocessRun=runner,
            isDrivingFn=lambda: False,
            getPowerSourceFn=lambda: "external",
            getLastObdActivitySecondsAgoFn=lambda: 9999.0,
            nowFn=clock,
            sleepFn=clock.sleep,
        )
        applyResult = applier.apply()

        assert applyResult.outcome == ApplyOutcome.SERVICE_HEALTH_FAILED, (
            "outer outcome stays SERVICE_HEALTH_FAILED even when rollback "
            "itself fails (operator-post-mortem invariant); got "
            f"{applyResult.outcome}"
        )
        assert applyResult.rollbackOutcome == "failed"


__all__: list[str] = []  # nothing exported -- pure pytest module
