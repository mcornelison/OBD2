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
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from scripts.version_helpers import parseVersion, readDeployVersion

__all__ = ["ApplyOutcome", "ApplyResult", "UpdateApplier"]

logger = logging.getLogger(__name__)


# Recent OBD activity threshold: 5 minutes per US-248 acceptance.  An event
# inside this window means the engine has been on recently, so we skip
# apply even when other safety gates are clear.  Hardcoded (not config)
# because the boundary is load-bearing for the safety contract; a story
# follow-up can lift it to config if the value needs vehicle-by-vehicle
# tuning.
_RECENT_OBD_ACTIVITY_THRESHOLD_SECONDS: float = 300.0


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
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        subprocessRun: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        isDrivingFn: Callable[[], bool] | None = None,
        getPowerSourceFn: Callable[[], str] | None = None,
        getLastObdActivitySecondsAgoFn: Callable[[], float | None] | None = None,
    ) -> None:
        self._config = config
        piConfig: dict[str, Any] = config.get("pi", {}) or {}
        self._update: dict[str, Any] = piConfig.get("update", {}) or {}

        self._subprocessRun = subprocessRun or subprocess.run
        self._isDrivingFn = isDrivingFn
        self._getPowerSourceFn = getPowerSourceFn
        self._getLastObdActivitySecondsAgoFn = getLastObdActivitySecondsAgoFn

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

        # 5. Fetch + checkout to staging.  Failure rolls back to priorRef
        # (idempotent for fetch -- a partial fetch leaves the working
        # tree unchanged; checkout failure may leave a half-applied
        # state, hence the rollback).
        if not self._runFetch():
            rollback = self._maybeRollback(priorRef)
            return ApplyResult(
                outcome=ApplyOutcome.DEPLOY_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale="git fetch failed",
                rollbackOutcome=rollback,
            )
        if not self._runCheckout(targetVersion):
            rollback = self._maybeRollback(priorRef)
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
            rollback = self._maybeRollback(priorRef)
            return ApplyResult(
                outcome=ApplyOutcome.DRY_RUN_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale="deploy-pi.sh --dry-run failed",
                rollbackOutcome=rollback,
            )

        # 7. Full deploy.
        if not self._runDeploy():
            rollback = self._maybeRollback(priorRef)
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
            rollback = self._maybeRollback(priorRef)
            return ApplyResult(
                outcome=ApplyOutcome.POST_DEPLOY_VERIFY_FAILED,
                targetVersion=targetVersion,
                priorRef=priorRef,
                rationale=(
                    f"post-deploy .deploy-version did not match {targetVersion}"
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

    # ---- rollback ----------------------------------------------------------

    def _maybeRollback(self, priorRef: str) -> str | None:
        """Run rollback when ``rollbackEnabled``; clear marker either way.

        Returns ``"ok"`` when rollback ran cleanly, ``"failed"`` when
        rollback itself errored, ``"skipped (disabled)"`` when
        ``rollbackEnabled=False``.  The marker is cleared in every
        branch so a poisoned target version cannot re-trigger on the
        next interval tick.
        """
        if not self.rollbackEnabled:
            self._clearMarker()
            logger.warning(
                "Update apply: rollback skipped (pi.update.rollbackEnabled=false); "
                "marker cleared anyway to prevent re-trigger"
            )
            return "skipped (disabled)"
        ok = self._rollback(priorRef)
        self._clearMarker()
        return "ok" if ok else "failed"

    def _rollback(self, priorRef: str) -> bool:
        """Restore working tree to ``priorRef`` and restart the service."""
        checkout = self._runDeployCommand(
            ["git", "checkout", priorRef],
            description=f"rollback git checkout {priorRef}",
        )
        restart = self._runDeployCommand(
            ["sudo", "systemctl", "restart", "eclipse-obd"],
            description="rollback systemctl restart eclipse-obd",
        )
        return checkout and restart

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
