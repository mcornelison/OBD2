################################################################################
# File Name: update_applier.py
# Purpose/Description: Pi auto-update apply step (B-047 US-D / US-248).  Reads
#                      the marker file written by US-247's UpdateChecker,
#                      enforces safety preconditions (no apply during a drive,
#                      on battery power, or shortly after recent OBD activity),
#                      stages a git checkout of the target version, runs the
#                      Pi deploy script in --dry-run mode, and on success
#                      runs the full deploy with post-deploy verification.
#                      Any failure rolls back to the prior git ref and
#                      restarts the eclipse-obd service; the marker file is
#                      cleared on either success or rollback.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial implementation (Sprint 20 US-248)
# 2026-05-08    | Rex (US-293) | Add ``database`` constructor param + write a
#                              | ``connection_log`` row with event_type
#                              | ``auto_update_applied`` on SUCCESS.  Closes
#                              | B-047 line-104 production-observability gap
#                              | before Pi-wiring activates the trigger every
#                              | key-on (Spool 2026-05-06).
# 2026-05-08    | Rex (US-294) | Auto-rollback drill: poll
#                              | ``systemctl is-active eclipse-obd`` for 60s
#                              | post-deploy; on inactive, restore
#                              | ``.deploy-version`` from captured prior
#                              | content + run rollback (B-047 D3).  Adds
#                              | ``ApplyOutcome.SERVICE_HEALTH_FAILED`` plus
#                              | ``nowFn`` / ``sleepFn`` constructor seams.
# ================================================================================
################################################################################

"""Pi self-update apply step (US-248 / B-047 US-D).

Decision flow for :meth:`UpdateApplier.apply`::

    marker file missing                      -> NO_MARKER
    marker file unparseable / target missing -> MARKER_INVALID
    isDrivingFn() == True                    -> SKIPPED_DRIVING
    getPowerSourceFn() == 'battery'          -> SKIPPED_BATTERY_POWER
    getLastObdActivitySecondsAgoFn() < 300   -> SKIPPED_RECENT_OBD_ACTIVITY
    pi.update.applyEnabled == False          -> DISABLED  (after safety gates
                                                so operator log shows
                                                "would have been safe to apply")
    git fetch / checkout fails               -> rollback -> ROLLBACK_OK / FAILED
    deploy-pi.sh --dry-run fails             -> DRY_RUN_FAILED + rollback
    deploy-pi.sh full deploy fails           -> DEPLOY_FAILED + rollback
    post-deploy .deploy-version != target    -> POST_DEPLOY_VERIFY_FAILED
                                                + rollback
    systemctl is-active eclipse-obd != active
        within serviceHealthTimeoutSeconds   -> SERVICE_HEALTH_FAILED
                                                + rollback (US-294 / B-047 D3)
    everything succeeds                      -> SUCCESS

Marker handoff
--------------
The marker file is the only inter-step channel between US-C (UpdateChecker)
and US-D (this applier).  US-C writes ``{target_version, server_url,
rationale, checked_at}``; US-D reads ``target_version``, runs the apply,
then deletes the marker on success OR rollback so the next interval tick
does not re-trigger.  An invalid marker is also deleted -- a malformed
artifact must never block the runLoop indefinitely.

Safety preconditions
--------------------
applyEnabled defaults to ``False`` (CIO opt-in).  Even when enabled the
following gates short-circuit before any subprocess is invoked:

* drive in progress (sacred -- never touch the Pi while CIO is driving),
* power source == BATTERY (don't apply mid-shutdown; could brick on poweroff),
* connection_log has an event in the last 5 minutes (recent OBD activity
  implies the engine is on, even if drive_detector hasn't fired yet).

Each gate is injected as a closure so tests can pin the boundary.  When
a gate's closure is ``None`` (or raises), the gate fails OPEN -- we do
not want a missing UpsMonitor or detector to perma-block updates.  The
load-bearing safety net is ``applyEnabled=False``.

Subprocess injection
--------------------
The single ``subprocessRun`` callable is the test seam for every
external command.  By default it points at :func:`subprocess.run`;
tests pass a fake that records calls and returns scripted outcomes.
This keeps tests at the git/subprocess boundary per the story
acceptance ("Synthetic test mocks at git/subprocess boundary, not at
apply-state-machine level").
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from scripts.version_helpers import parseVersion, readDeployVersion
from src.pi.data.connection_logger import logConnectionEvent

__all__ = ["ApplyOutcome", "ApplyResult", "UpdateApplier"]

logger = logging.getLogger(__name__)


# US-293: canonical event_type emitted on a successful self-update.  Kept
# here as a module constant rather than added to ``connection_logger``'s
# canonical frozenset to keep US-293's blast radius scoped to the update
# subsystem; ``connection_log.event_type`` is free-text per US-211, so
# the writer accepts unknown values.
EVENT_AUTO_UPDATE_APPLIED: str = "auto_update_applied"


# Recent OBD activity threshold: 5 minutes per US-248 acceptance.  An event
# inside this window means the engine has been on recently, so we skip
# apply even when other safety gates are clear.  Hardcoded (not config)
# because the boundary is load-bearing for the safety contract; a story
# follow-up can lift it to config if the value needs vehicle-by-vehicle
# tuning.
_RECENT_OBD_ACTIVITY_THRESHOLD_SECONDS: float = 300.0


# US-294 / B-047 D3: post-deploy systemctl-is-active watchdog defaults.
# Module constants so tests + production share the same numbers without
# requiring a validator.py touch (config-overridable per
# ``serviceHealthTimeoutSeconds`` / ``serviceHealthPollIntervalSeconds``
# below).  60-sec budget per B-047 PRD D3 ("if the service fails to
# reach `active` within a configured timeout (proposal: 60 sec)").
_SERVICE_HEALTH_TIMEOUT_SECONDS: float = 60.0
_SERVICE_HEALTH_POLL_INTERVAL_SECONDS: float = 2.0
_SERVICE_UNIT: str = "eclipse-obd"
# Inner systemctl-is-active subprocess cap.  The watchdog calls
# ``systemctl is-active`` repeatedly; each call must be cheap and bounded
# (the command typically returns in milliseconds, but we don't want a
# stuck systemctl to consume the entire 60-sec watchdog budget on the
# first poll).
_SYSTEMCTL_PROBE_TIMEOUT_SECONDS: float = 10.0


# ================================================================================
# Result types
# ================================================================================


class ApplyOutcome(StrEnum):
    """Terminal outcome of one :meth:`UpdateApplier.apply` call."""

    SUCCESS = "success"
    NO_MARKER = "no_marker"
    MARKER_INVALID = "marker_invalid"
    DISABLED = "disabled"
    SKIPPED_DRIVING = "skipped_driving"
    SKIPPED_BATTERY_POWER = "skipped_battery_power"
    SKIPPED_RECENT_OBD_ACTIVITY = "skipped_recent_obd_activity"
    DRY_RUN_FAILED = "dry_run_failed"
    DEPLOY_FAILED = "deploy_failed"
    POST_DEPLOY_VERIFY_FAILED = "post_deploy_verify_failed"
    SERVICE_HEALTH_FAILED = "service_health_failed"
    ROLLBACK_OK = "rollback_ok"
    ROLLBACK_FAILED = "rollback_failed"
    CONFIG_ERROR = "config_error"


@dataclass(slots=True)
class ApplyResult:
    """Outcome of one :meth:`UpdateApplier.apply` call.

    Attributes:
        outcome: See :class:`ApplyOutcome`.
        targetVersion: Marker's ``target_version`` when known; empty
            otherwise.
        priorRef: Git ref captured before fetch/checkout (used for
            rollback).  Empty when capture didn't run or failed.
        rationale: Human-readable summary embedded in the result + log.
        rollbackOutcome: ``"ok"`` when rollback ran cleanly,
            ``"failed"`` when rollback itself errored, ``None`` when
            rollback wasn't attempted (e.g. happy-path success or
            ``rollbackEnabled=False``).
    """

    outcome: ApplyOutcome
    targetVersion: str = field(default="")
    priorRef: str = field(default="")
    rationale: str = field(default="")
    rollbackOutcome: str | None = field(default=None)


# ================================================================================
# UpdateApplier
# ================================================================================


class UpdateApplier:
    """Apply (or refuse to apply) a marker-published Pi update.

    One instance is reusable across many :meth:`apply` calls.  Holds no
    open subprocess handles or mutable state between calls; the marker
    file is the only persistence.

    Construction
    ------------
    Args:
        config: Full Pi config dict (validator output).  Reads
            ``pi.update.*`` for policy.
        subprocessRun: Callable compatible with :func:`subprocess.run`;
            injected in tests.  Defaults to ``subprocess.run``.  Each
            phase issues exactly one subprocess call so tests can
            assert the call sequence cleanly.
        isDrivingFn: Zero-arg callable returning ``True`` when a drive
            is in progress.  ``None`` (or a raising closure) is treated
            as "not driving" (open) -- a missing detector must not
            perma-block updates.
        getPowerSourceFn: Zero-arg callable returning a PowerSource
            string-enum value (``"external"`` / ``"battery"`` /
            ``"unknown"``).  ``None`` (or raising) is treated as
            ``"external"`` (open) -- a missing UpsMonitor must not
            perma-block updates.
        getLastObdActivitySecondsAgoFn: Zero-arg callable returning the
            seconds-since-most-recent-connection_log-event, or ``None``
            when no such event has ever been logged.  ``None`` closure
            (or raising / returning ``None``) is treated as "no recent
            activity" (open).
        database: Optional ``ObdDatabase``-shaped object.  When provided,
            a ``connection_log`` row with ``event_type='auto_update_applied'``
            is inserted on SUCCESS so server-side analytics can observe
            self-updates (B-047 line 104 / US-293).  When ``None``, the
            SUCCESS path proceeds without the observability write.  This
            keeps existing test fixtures (e.g. ``test_self_update_e2e.py``
            from US-258) compatible without modification.
        connectionEventLogger: Test seam matching :func:`logConnectionEvent`.
            Defaults to that helper.  Tests pass a recording fake to assert
            event-type / success / errorMessage without standing up an
            ``ObdDatabase``.
        nowFn: Zero-arg callable returning a monotonic-clock float.  Defaults
            to :func:`time.monotonic`.  Tests inject a fake clock so the
            ``serviceHealthTimeoutSeconds`` watchdog runs in zero wallclock
            (US-294 / B-047 D3).
        sleepFn: Single-arg callable that sleeps the given seconds.  Defaults
            to :func:`time.sleep`.  Paired with ``nowFn`` for deterministic
            watchdog tests.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        subprocessRun: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        isDrivingFn: Callable[[], bool] | None = None,
        getPowerSourceFn: Callable[[], str] | None = None,
        getLastObdActivitySecondsAgoFn: Callable[[], float | None] | None = None,
        database: Any | None = None,
        connectionEventLogger: Callable[..., None] | None = None,
        nowFn: Callable[[], float] | None = None,
        sleepFn: Callable[[float], None] | None = None,
    ) -> None:
        self._config = config
        piConfig: dict[str, Any] = config.get("pi", {}) or {}
        self._update: dict[str, Any] = piConfig.get("update", {}) or {}

        self._subprocessRun = subprocessRun or subprocess.run
        self._isDrivingFn = isDrivingFn
        self._getPowerSourceFn = getPowerSourceFn
        self._getLastObdActivitySecondsAgoFn = getLastObdActivitySecondsAgoFn
        self._database = database
        self._connectionEventLogger = connectionEventLogger or logConnectionEvent
        self._now: Callable[[], float] = nowFn or time.monotonic
        self._sleep: Callable[[float], None] = sleepFn or time.sleep

    # ---- config surface ----------------------------------------------------

    @property
    def applyEnabled(self) -> bool:
        """``pi.update.applyEnabled`` -- defaults to False (CIO opt-in)."""
        return bool(self._update.get("applyEnabled", False))

    @property
    def rollbackEnabled(self) -> bool:
        """``pi.update.rollbackEnabled`` -- defaults to True."""
        return bool(self._update.get("rollbackEnabled", True))

    @property
    def stagingPath(self) -> str:
        """``pi.update.stagingPath`` -- where the staged checkout lives."""
        return str(self._update.get("stagingPath", "/tmp/eclipse-obd-staging"))

    @property
    def markerFilePath(self) -> str:
        """``pi.update.markerFilePath`` -- shared with US-247's UpdateChecker."""
        return str(
            self._update.get(
                "markerFilePath", "/var/lib/eclipse-obd/update-pending.json"
            )
        )

    @property
    def localVersionPath(self) -> str:
        """``pi.update.localVersionPath`` -- the .deploy-version artifact."""
        return str(self._update.get("localVersionPath", ".deploy-version"))

    @property
    def serviceHealthTimeoutSeconds(self) -> float:
        """``pi.update.serviceHealthTimeoutSeconds`` -- US-294 / B-047 D3.

        Total watchdog budget for the ``systemctl is-active`` poll loop
        after a successful deploy.  Defaults to 60 sec per the B-047
        PRD; CIO can lower in config without a code change.
        """
        return float(
            self._update.get(
                "serviceHealthTimeoutSeconds",
                _SERVICE_HEALTH_TIMEOUT_SECONDS,
            )
        )

    @property
    def serviceHealthPollIntervalSeconds(self) -> float:
        """``pi.update.serviceHealthPollIntervalSeconds`` -- watchdog cadence."""
        return float(
            self._update.get(
                "serviceHealthPollIntervalSeconds",
                _SERVICE_HEALTH_POLL_INTERVAL_SECONDS,
            )
        )

    @property
    def serviceUnit(self) -> str:
        """``pi.update.serviceUnit`` -- defaults to ``eclipse-obd``.

        Lifted to a config knob purely for testability; production code
        path always reads the default unless an operator overrides.
        """
        return str(self._update.get("serviceUnit", _SERVICE_UNIT))

    def markerExists(self) -> bool:
        """Cheap fast-path probe used by the orchestrator runLoop trigger.

        Lets the orchestrator avoid building safety closures when there
        is nothing to apply.  Mirrors the shape of
        :attr:`UpdateChecker.isEnabled` for consistency.
        """
        return Path(self.markerFilePath).is_file()

    # ---- public API --------------------------------------------------------

    def apply(self) -> ApplyResult:
        """Read the marker and (maybe) apply the published update.

        See module docstring for the full decision flow.  Never raises:
        every error path resolves to a typed :class:`ApplyOutcome` so
        the caller (orchestrator runLoop) does not need a try/except.
        """
        # 1. Marker presence + shape.
        markerData = self._readMarker()
        if markerData is None:
            return ApplyResult(
                outcome=ApplyOutcome.NO_MARKER,
                rationale="no marker file present",
            )
        targetVersion = markerData.get("target_version", "")
        if not isinstance(targetVersion, str) or not _isValidVersion(targetVersion):
            self._clearMarker()  # malformed marker should not perma-block
            logger.warning(
                "Update apply: marker invalid (target_version=%r); marker cleared",
                targetVersion,
            )
            return ApplyResult(
                outcome=ApplyOutcome.MARKER_INVALID,
                rationale="marker missing/invalid target_version",
            )

        # 2. Safety gates.  Order matters: drive-state is the most
        # operationally sacred (mid-drive apply could brick the Pi);
        # power source is the next-most consequential (apply on
        # battery risks dirty shutdown); recent OBD activity is the
        # weakest gate but still protects against "engine just turned
        # on" windows the detector hasn't reflected yet.
        gateOutcome = self._gateSafety()
        if gateOutcome is not None:
            return ApplyResult(
                outcome=gateOutcome,
                targetVersion=targetVersion,
                rationale=_safetyGateRationale(gateOutcome),
            )

        # 3. Enabled gate.  Placed AFTER safety so the operator log
        # shows "would have been safe to apply" instead of hiding that
        # under a disabled-flag short-circuit.
        if not self.applyEnabled:
            logger.warning(
                "Update apply: pi.update.applyEnabled=false -- skipping "
                "apply of %s (set the flag true to opt in)",
                targetVersion,
            )
            return ApplyResult(
                outcome=ApplyOutcome.DISABLED,
                targetVersion=targetVersion,
                rationale="pi.update.applyEnabled=false",
            )

        # 4. Capture prior ref BEFORE any state-mutating subprocess.
        # Failure here means we cannot guarantee rollback, so we abort
        # without making any changes.
        priorRef = self._capturePriorRef()
        if not priorRef:
            return ApplyResult(
                outcome=ApplyOutcome.CONFIG_ERROR,
                targetVersion=targetVersion,
                rationale="failed to capture priorRef via git rev-parse HEAD",
            )

        # 4b. Capture priorVersion for the SUCCESS-path observability
        # write (US-293).  The deploy run will overwrite .deploy-version
        # at step 7 so we cannot recover the prior value after the fact.
        # Captured optimistically -- a missing or malformed local record
        # is fine; the resulting diagnostic message just degrades to
        # "<unknown> -> targetVersion" rather than aborting the apply.
        priorVersion = self._readPriorVersion()
        # 4c. Capture FULL prior .deploy-version content (US-294 / B-047
        # D3).  ``deploy-pi.sh`` overwrites the file at step 7 with the
        # new release record; rollback needs to restore the prior
        # content byte-for-byte so a future version-check cannot believe
        # the Pi is on the broken release while git is on the prior ref.
        # ``None`` means the file did not exist pre-deploy -- rollback
        # then deletes whatever was stamped instead of writing back.
        priorDeployContent = self._capturePriorDeployContent()

        # 5. Fetch + checkout to staging.  Failure rolls back to priorRef
        # (idempotent for fetch -- a partial fetch leaves the working
        # tree unchanged; checkout failure may leave a half-applied
        # state, hence the rollback).
        if not self._runFetch():
            rollback = self._maybeRollback(priorRef, priorDeployContent)
            return ApplyResult(
                outcome=ApplyOutcome.DEPLOY_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale="git fetch failed",
                rollbackOutcome=rollback,
            )
        if not self._runCheckout(targetVersion):
            rollback = self._maybeRollback(priorRef, priorDeployContent)
            return ApplyResult(
                outcome=ApplyOutcome.DEPLOY_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale=f"git checkout {targetVersion} failed",
                rollbackOutcome=rollback,
            )

        # 6. Dry-run validates without applying.  Failure here is the
        # cleanest abort path -- nothing has been applied yet, but we
        # rolled the working tree to the target version, so we still
        # rollback to priorRef (atomicity invariant).
        if not self._runDryRun():
            rollback = self._maybeRollback(priorRef, priorDeployContent)
            return ApplyResult(
                outcome=ApplyOutcome.DRY_RUN_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale="deploy-pi.sh --dry-run failed",
                rollbackOutcome=rollback,
            )

        # 7. Full deploy.
        if not self._runDeploy():
            rollback = self._maybeRollback(priorRef, priorDeployContent)
            return ApplyResult(
                outcome=ApplyOutcome.DEPLOY_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale="deploy-pi.sh failed",
                rollbackOutcome=rollback,
            )

        # 8. Post-deploy verify: read the .deploy-version that the
        # full-deploy run is supposed to have stamped (US-241).
        if not self._verifyPostDeploy(targetVersion):
            rollback = self._maybeRollback(priorRef, priorDeployContent)
            return ApplyResult(
                outcome=ApplyOutcome.POST_DEPLOY_VERIFY_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale=(
                    f"post-deploy .deploy-version did not match {targetVersion}"
                ),
                rollbackOutcome=rollback,
            )

        # 8b. Service-health watchdog (US-294 / B-047 D3).  ``deploy-pi.sh``
        # restarts ``eclipse-obd.service`` internally; a syntax error in
        # ``main.py`` would land deploy rc=0 + a poisoned service that
        # only manifests as ``systemctl is-active`` returning anything
        # other than ``active``.  Poll for up to
        # ``serviceHealthTimeoutSeconds`` and rollback on timeout.
        if not self._verifyServiceHealth():
            rollback = self._maybeRollback(priorRef, priorDeployContent)
            return ApplyResult(
                outcome=ApplyOutcome.SERVICE_HEALTH_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale=(
                    f"{self.serviceUnit}.service did not reach 'active' "
                    f"within {self.serviceHealthTimeoutSeconds:.0f}s"
                ),
                rollbackOutcome=rollback,
            )

        # 9. Success: clear the marker so the next runLoop tick does not
        # re-apply this version.  Subsequent UpdateChecker ticks will
        # re-evaluate against the new local version.
        self._clearMarker()
        logger.info(
            "Update apply: SUCCESS -- target_version=%s priorRef=%s",
            targetVersion, priorRef,
        )
        # B-047 line-104 observability (US-293): a ``connection_log``
        # row gives server-side analytics the only off-Pi signal that an
        # auto-update happened.  Failure to write the row must NOT
        # downgrade the SUCCESS outcome -- the helper already swallows
        # exceptions, but we wrap the call here as a belt-and-suspenders.
        self._writeAutoUpdateAppliedEvent(
            priorVersion=priorVersion,
            targetVersion=targetVersion,
            priorRef=priorRef,
        )
        return ApplyResult(
            outcome=ApplyOutcome.SUCCESS,
            targetVersion=targetVersion,
            priorRef=priorRef,
            rationale=f"applied {targetVersion} successfully",
        )

    # ---- gates -------------------------------------------------------------

    def _gateSafety(self) -> ApplyOutcome | None:
        """Return a safety-gate outcome to short-circuit, or None to proceed."""
        if self._isDriving():
            return ApplyOutcome.SKIPPED_DRIVING
        if self._isOnBattery():
            return ApplyOutcome.SKIPPED_BATTERY_POWER
        if self._hasRecentObdActivity():
            return ApplyOutcome.SKIPPED_RECENT_OBD_ACTIVITY
        return None

    def _isDriving(self) -> bool:
        if self._isDrivingFn is None:
            return False
        try:
            return bool(self._isDrivingFn())
        except Exception as exc:  # noqa: BLE001 -- defensive
            logger.warning(
                "isDrivingFn raised %s: %s -- treating as 'not driving'",
                type(exc).__name__, exc,
            )
            return False

    def _isOnBattery(self) -> bool:
        if self._getPowerSourceFn is None:
            return False
        try:
            source = self._getPowerSourceFn()
        except Exception as exc:  # noqa: BLE001 -- defensive
            logger.warning(
                "getPowerSourceFn raised %s: %s -- treating as 'external'",
                type(exc).__name__, exc,
            )
            return False
        return str(source).lower() == "battery"

    def _hasRecentObdActivity(self) -> bool:
        if self._getLastObdActivitySecondsAgoFn is None:
            return False
        try:
            seconds = self._getLastObdActivitySecondsAgoFn()
        except Exception as exc:  # noqa: BLE001 -- defensive
            logger.warning(
                "getLastObdActivitySecondsAgoFn raised %s: %s -- "
                "treating as 'no recent activity'",
                type(exc).__name__, exc,
            )
            return False
        if seconds is None:
            return False
        return float(seconds) < _RECENT_OBD_ACTIVITY_THRESHOLD_SECONDS

    # ---- subprocess phases -------------------------------------------------

    def _capturePriorRef(self) -> str:
        """Run ``git rev-parse HEAD`` and return the trimmed stdout."""
        try:
            result = self._subprocessRun(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error(
                "Failed to capture prior git ref: %s", exc,
            )
            return ""
        if result.returncode != 0:
            logger.error(
                "git rev-parse HEAD failed: rc=%d stderr=%s",
                result.returncode,
                getattr(result, "stderr", "") or "",
            )
            return ""
        return (result.stdout or "").strip()

    def _runFetch(self) -> bool:
        return self._runDeployCommand(
            ["git", "fetch", "origin"],
            description="git fetch origin",
        )

    def _runCheckout(self, targetVersion: str) -> bool:
        return self._runDeployCommand(
            ["git", "checkout", targetVersion],
            description=f"git checkout {targetVersion}",
        )

    def _runDryRun(self) -> bool:
        return self._runDeployCommand(
            ["bash", "deploy/deploy-pi.sh", "--dry-run"],
            description="deploy-pi.sh --dry-run",
        )

    def _runDeploy(self) -> bool:
        return self._runDeployCommand(
            ["bash", "deploy/deploy-pi.sh"],
            description="deploy-pi.sh",
        )

    def _runDeployCommand(self, cmd: list[str], description: str) -> bool:
        """Run a deploy-phase subprocess; return True on rc=0, False otherwise.

        A non-zero return code, OSError, or subprocess timeout all map
        to False.  No exception leaves this method.
        """
        try:
            result = self._subprocessRun(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,  # 10 minutes -- worst-case full rsync deploy
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error(
                "Update apply: %s raised %s: %s",
                description, type(exc).__name__, exc,
            )
            return False
        if result.returncode != 0:
            logger.error(
                "Update apply: %s failed rc=%d stderr=%s",
                description,
                result.returncode,
                getattr(result, "stderr", "") or "",
            )
            return False
        logger.info("Update apply: %s OK", description)
        return True

    def _verifyPostDeploy(self, targetVersion: str) -> bool:
        """Read the .deploy-version stamped by the deploy run; compare versions."""
        record = readDeployVersion(self.localVersionPath)
        if record is None:
            logger.error(
                "Update apply: post-deploy .deploy-version unreadable at %s",
                self.localVersionPath,
            )
            return False
        actualVersion = record.get("version", "")
        if actualVersion != targetVersion:
            logger.error(
                "Update apply: post-deploy version mismatch -- "
                "expected %s, got %s",
                targetVersion, actualVersion,
            )
            return False
        return True

    # ---- service-health watchdog (US-294 / B-047 D3) -----------------------

    def _verifyServiceHealth(self) -> bool:
        """Poll ``systemctl is-active <unit>`` until active or timeout.

        Returns ``True`` when the service reports ``active`` within
        ``serviceHealthTimeoutSeconds``; ``False`` on timeout, on any
        ``systemctl`` error, or on an unrecognized stdout payload.  The
        first poll fires immediately (no warm-up sleep); subsequent
        polls are spaced by ``serviceHealthPollIntervalSeconds``.

        ``systemctl is-active`` exit codes (per ``man systemctl``):
        ``0`` for ``active``, ``3`` for ``inactive`` / ``failed``,
        ``4`` for ``activating``, etc.  Truth-source is the stdout
        payload (``"active"``) -- the rc check is a belt-and-suspenders
        in case a fake/broken systemctl returns rc=0 with empty stdout.
        """
        deadline = self._now() + self.serviceHealthTimeoutSeconds
        while True:
            stdout = self._probeServiceIsActive()
            if stdout == "active":
                logger.info(
                    "Update apply: %s.service is active (post-deploy "
                    "watchdog OK)", self.serviceUnit,
                )
                return True
            now = self._now()
            if now >= deadline:
                logger.error(
                    "Update apply: %s.service did not reach 'active' "
                    "within %.0fs (last status=%r); rollback will fire",
                    self.serviceUnit,
                    self.serviceHealthTimeoutSeconds,
                    stdout,
                )
                return False
            self._sleep(self.serviceHealthPollIntervalSeconds)

    def _probeServiceIsActive(self) -> str:
        """Run ``systemctl is-active <unit>`` once; return trimmed stdout.

        Returns ``""`` on any subprocess error -- the watchdog loop
        treats that as "not active yet" and continues polling until the
        deadline.
        """
        try:
            result = self._subprocessRun(
                ["systemctl", "is-active", self.serviceUnit],
                capture_output=True,
                text=True,
                check=False,
                timeout=_SYSTEMCTL_PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(
                "Update apply: systemctl is-active raised %s: %s -- "
                "treating as 'not active yet'",
                type(exc).__name__, exc,
            )
            return ""
        return (result.stdout or "").strip()

    # ---- rollback ----------------------------------------------------------

    def _capturePriorDeployContent(self) -> bytes | None:
        """Snapshot the raw bytes of ``.deploy-version`` before deploy.

        Returns the file's bytes when readable, or ``None`` when the
        file does not exist OR is unreadable.  ``None`` instructs
        rollback to delete the post-deploy stamp rather than write a
        prior version back.
        """
        path = Path(self.localVersionPath)
        if not path.is_file():
            return None
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.warning(
                "Update apply: failed to capture prior .deploy-version "
                "at %s for rollback: %s",
                path, exc,
            )
            return None

    def _maybeRollback(
        self,
        priorRef: str,
        priorDeployContent: bytes | None,
    ) -> str | None:
        """Run rollback when ``rollbackEnabled``; clear marker either way.

        Returns ``"ok"`` when rollback ran cleanly, ``"failed"`` when
        rollback itself errored, ``"skipped (disabled)"`` when
        ``rollbackEnabled=False``.  The marker is cleared in every
        branch so a poisoned target version cannot re-trigger on the
        next interval tick.

        Args:
            priorRef: git ref to restore (captured pre-fetch).
            priorDeployContent: bytes of ``.deploy-version`` captured
                pre-deploy; ``None`` when the file did not exist.
                Required for D3's "rollback restores prior snapshot"
                contract -- without it, future version-checks would
                see the broken release's stamp even after git rolls
                back.
        """
        if not self.rollbackEnabled:
            self._clearMarker()
            logger.warning(
                "Update apply: rollback skipped (pi.update.rollbackEnabled=false); "
                "marker cleared anyway to prevent re-trigger"
            )
            return "skipped (disabled)"
        ok = self._rollback(priorRef, priorDeployContent)
        self._clearMarker()
        return "ok" if ok else "failed"

    def _rollback(
        self,
        priorRef: str,
        priorDeployContent: bytes | None,
    ) -> bool:
        """Restore working tree + .deploy-version, restart, verify health.

        Sequence:
          1. ``git checkout <priorRef>`` (working tree -> prior ref).
          2. Restore ``.deploy-version`` from captured bytes (or delete
             the post-deploy stamp when nothing was captured).
          3. ``sudo systemctl restart eclipse-obd``.
          4. Poll ``systemctl is-active <unit>`` until active or
             ``serviceHealthTimeoutSeconds`` -- the prior version
             SHOULD come up clean; failure here means "rollback to a
             broken snapshot" which is operator-actionable.

        Returns ``True`` only when all four steps succeed.
        """
        checkout = self._runDeployCommand(
            ["git", "checkout", priorRef],
            description=f"rollback git checkout {priorRef}",
        )
        if not checkout:
            return False
        self._restorePriorDeployContent(priorDeployContent)
        restart = self._runDeployCommand(
            ["sudo", "systemctl", "restart", "eclipse-obd"],
            description="rollback systemctl restart eclipse-obd",
        )
        if not restart:
            return False
        # Post-rollback service-health verify: confirms the prior version
        # actually came up healthy (B-047 D3 acceptance: "service is
        # active post-rollback").  Reuses the same watchdog logic and
        # budget -- a healthy prior version returns active on the first
        # poll, so this typically costs zero wallclock.
        return self._verifyServiceHealth()

    def _restorePriorDeployContent(
        self, priorDeployContent: bytes | None,
    ) -> None:
        """Write captured prior bytes back to ``.deploy-version``.

        When ``priorDeployContent is None`` (the file did not exist
        pre-deploy), the post-deploy stamp is deleted instead.  Either
        outcome restores the version-check truth source to its
        pre-deploy state.  Best-effort: a write/unlink failure is
        logged but does not propagate -- the rollback's git checkout
        already shifted the running code; restoring the stamp is the
        observability half of the contract, not the safety half.
        """
        path = Path(self.localVersionPath)
        if priorDeployContent is None:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Update apply: failed to delete post-deploy "
                    ".deploy-version at %s during rollback: %s",
                    path, exc,
                )
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(priorDeployContent)
        except OSError as exc:
            logger.warning(
                "Update apply: failed to restore prior .deploy-version "
                "at %s during rollback: %s",
                path, exc,
            )

    # ---- observability (US-293) -------------------------------------------

    def _readPriorVersion(self) -> str:
        """Best-effort read of the local ``.deploy-version`` before deploy.

        Returns the version string when readable, or ``""`` when the
        file is missing / malformed.  Used purely for the diagnostic
        message of the SUCCESS-path connection_log row; never aborts
        the apply.
        """
        record = readDeployVersion(self.localVersionPath)
        if record is None:
            return ""
        version = record.get("version", "")
        return str(version) if isinstance(version, str) else ""

    def _writeAutoUpdateAppliedEvent(
        self,
        *,
        priorVersion: str,
        targetVersion: str,
        priorRef: str,
    ) -> None:
        """Insert one ``auto_update_applied`` row into ``connection_log``.

        No-op when ``self._database is None`` (the writer helper itself
        short-circuits on a None database, but skipping the call avoids
        the WARNING line on the no-database path).  Wrapped in a
        try/except so a sqlite glitch in the observability write cannot
        downgrade the SUCCESS outcome.
        """
        if self._database is None:
            return
        priorLabel = priorVersion or "<unknown>"
        message = (
            f"applied {priorLabel} -> {targetVersion}; priorRef={priorRef}"
        )
        try:
            self._connectionEventLogger(
                self._database,
                eventType=EVENT_AUTO_UPDATE_APPLIED,
                success=True,
                errorMessage=message,
            )
        except Exception as exc:  # noqa: BLE001 -- observability must not crash apply
            logger.warning(
                "Failed to write auto_update_applied connection_log row: %s",
                exc,
            )

    # ---- marker io ---------------------------------------------------------

    def _readMarker(self) -> dict[str, Any] | None:
        path = Path(self.markerFilePath)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Update apply: marker file unreadable at %s: %s",
                path, exc,
            )
            # Clear the malformed file so it does not perma-trigger.
            try:
                path.unlink()
            except OSError:
                pass
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _clearMarker(self) -> None:
        """Delete the marker file (no-op when absent / unlink fails).

        The runLoop trigger short-circuits on ``markerExists() == False``,
        so a stale failed-unlink is observable but harmless: the next
        tick will retry.
        """
        path = Path(self.markerFilePath)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "Update apply: failed to clear marker at %s: %s",
                path, exc,
            )


# ================================================================================
# Helpers
# ================================================================================


def _isValidVersion(version: str) -> bool:
    try:
        parseVersion(version)
    except (ValueError, TypeError):
        return False
    return True


def _safetyGateRationale(outcome: ApplyOutcome) -> str:
    if outcome == ApplyOutcome.SKIPPED_DRIVING:
        return "drive in progress"
    if outcome == ApplyOutcome.SKIPPED_BATTERY_POWER:
        return "power source is BATTERY"
    if outcome == ApplyOutcome.SKIPPED_RECENT_OBD_ACTIVITY:
        return (
            f"OBD activity within last "
            f"{int(_RECENT_OBD_ACTIVITY_THRESHOLD_SECONDS)}s"
        )
    return ""
