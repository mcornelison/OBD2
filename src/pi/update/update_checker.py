################################################################################
# File Name: update_checker.py
# Purpose/Description: Pi update-checker daemon (B-047 US-C / US-247).  Polls
#                      the server's GET /api/v1/release/current endpoint,
#                      compares the returned record's version to the Pi's
#                      local .deploy-version, and writes a marker file when
#                      a newer version is available.  Honors the
#                      "drive-state-is-sacred" invariant -- never checks
#                      while a drive is in progress.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial implementation (Sprint 20 US-247)
# 2026-05-08    | Rex (US-295) | B-047 D2 safety-precondition audit:
#               |              | add isSyncCaughtUpFn + isDtcRetrievalActiveFn
#               |              | constructor kwargs + SKIPPED_SYNC_LAGGING +
#               |              | SKIPPED_DTC_ACTIVE outcomes.  Three gates now
#               |              | enforce logical AND (drive / sync / dtc) before
#               |              | any HTTP call.  Closures default to None
#               |              | meaning the gate is OPEN -- backward-compatible
#               |              | for the US-247 callsite.
# 2026-05-08    | Rex (US-296) | B-047 D7 cooldown persistence: add 24h
#               |              | cooldown gate + on-disk timestamp persistence
#               |              | at ~/.cache/eclipse-obd/last-update-check.
#               |              | timestamp.  New SKIPPED_COOLDOWN outcome.
#               |              | Completed checks (UPDATE_AVAILABLE / UP_TO_DATE
#               |              | / SERVER_NO_RECORD) burn cooldown; failed
#               |              | checks (NETWORK_ERROR) + safety SKIPPED_*
#               |              | preserve OPEN cooldown per D7 invariant.
# ================================================================================
################################################################################

"""Pi -> server update-checker (US-247 / B-047 US-C).

Decision flow for :meth:`UpdateChecker.check_for_updates`::

    isDrivingFn() == True            -> SKIPPED_DRIVING       (no request, no marker)
    isSyncCaughtUpFn() == False      -> SKIPPED_SYNC_LAGGING  (no request, no marker)
    isDtcRetrievalActiveFn() == True -> SKIPPED_DTC_ACTIVE    (no request, no marker)
    pi.update.enabled == False       -> DISABLED              (no request, no marker)
    cooldown timestamp < 24h ago     -> SKIPPED_COOLDOWN      (no request, no marker)
    pi.companionService.* misconfig  -> CONFIG_ERROR          (no request, no marker)
    local .deploy-version missing/
        invalid                      -> LOCAL_VERSION_UNAVAILABLE
                                        (no marker; informational log)
    server returns 503 (no record)   -> SERVER_NO_RECORD      (treated as
                                        'no update available' per US-246)
    server returns 5xx / network err -> NETWORK_ERROR          (transient; next
                                        interval retries)
    server.version <= local.version  -> UP_TO_DATE             (no marker)
    server.version > local.version   -> UPDATE_AVAILABLE       (marker written)

The first three outcomes encode the B-047 D2 safety-precondition gate
(US-295): an update MUST be blocked while a drive is in progress, while
the Pi -> server sync_log cursor is behind the latest realtime_data
row, or while a DTC retrieval (Mode 03 / Mode 07) is in flight.  The
gate is a logical AND -- ALL three preconditions must hold for the
check to proceed; the SKIPPED_* outcomes never write a marker file and
do not advance the orchestrator's cooldown timestamp (the next
eligible trigger retries the gate).

The ``SKIPPED_COOLDOWN`` outcome encodes the B-047 D7 24-hour cooldown
gate (US-296): after EACH check completes (server-reached terminal
outcomes ``UPDATE_AVAILABLE`` / ``UP_TO_DATE`` / ``SERVER_NO_RECORD``)
a timestamp is written to ``~/.cache/eclipse-obd/last-update-check.
timestamp`` (path overridable via ``pi.update.cooldownTimestampPath``).
Subsequent calls within the cooldown window short-circuit with
``SKIPPED_COOLDOWN`` -- without touching the network -- and the
persistence survives reboots so the orchestrator's "fire on every
key-on" trigger after Pi-wiring (Spool 2026-05-06) does not re-check
constantly.  ``NETWORK_ERROR`` and the safety ``SKIPPED_*`` outcomes
do NOT burn cooldown -- the next eligible trigger retries.

Marker-file contract (B-047 US-C -> US-D handoff)::

    {
        "target_version": "V0.20.0",
        "server_url": "http://10.27.27.10:8000",
        "rationale": "server reports newer version V0.20.0; local is V0.19.0",
        "checked_at": "2026-04-30T12:34:56Z"
    }

US-D (the apply step) reads this artifact; nothing else does.

Transport
---------
Uses stdlib :mod:`urllib.request` to keep the Pi's dependency surface narrow
(matching :class:`src.pi.sync.client.SyncClient`).  The ``httpOpener`` and
``isDrivingFn`` are constructor-injected so tests run without sockets and
without a live drive detector.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from scripts.version_helpers import (
    parseVersion,
    readDeployVersion,
    validateRelease,
)
from src.common.config.secrets_loader import getSecret

__all__ = ["CheckOutcome", "CheckResult", "UpdateChecker"]

logger = logging.getLogger(__name__)


# ================================================================================
# Result types
# ================================================================================


class CheckOutcome(StrEnum):
    """Terminal outcome of a single :meth:`UpdateChecker.check_for_updates` call."""

    UPDATE_AVAILABLE = "update_available"
    UP_TO_DATE = "up_to_date"
    SKIPPED_DRIVING = "skipped_driving"
    # US-295 / B-047 D2: sync_log cursor is behind the latest realtime_data
    # row -- a self-deploy here would orphan unsynced rows on disk, so we
    # skip the check + retry on the next eligible trigger.
    SKIPPED_SYNC_LAGGING = "skipped_sync_lagging"
    # US-295 / B-047 D2: DTC retrieval is mid-execution (Mode 03 / Mode 07).
    # DriveDetector callbacks can fire from a non-runLoop thread (drive_end
    # Mode 07 in particular) -- the gate is structural even if the present
    # production race window is microseconds.
    SKIPPED_DTC_ACTIVE = "skipped_dtc_active"
    # US-296 / B-047 D7: 24-hour cooldown is active because a completed
    # check ran inside the configured window.  Persistence survives
    # reboots via ``pi.update.cooldownTimestampPath``; failed checks
    # (NETWORK_ERROR) and safety SKIPPED_* outcomes do NOT burn the
    # cooldown -- the next eligible trigger retries.
    SKIPPED_COOLDOWN = "skipped_cooldown"
    DISABLED = "disabled"
    LOCAL_VERSION_UNAVAILABLE = "local_version_unavailable"
    SERVER_NO_RECORD = "server_no_record"
    NETWORK_ERROR = "network_error"
    CONFIG_ERROR = "config_error"


@dataclass(slots=True)
class CheckResult:
    """Outcome of one :meth:`UpdateChecker.check_for_updates` call.

    Attributes:
        outcome: See :class:`CheckOutcome`.
        localVersion: Local ``.deploy-version`` version string when known;
            empty otherwise.
        serverVersion: Server release version string when known; empty
            otherwise.
        markerPath: Filesystem path of the marker file when one was
            written; ``None`` otherwise.
        rationale: Human-readable reason embedded in the marker file +
            log line.
    """

    outcome: CheckOutcome
    localVersion: str = field(default="")
    serverVersion: str = field(default="")
    markerPath: str | None = field(default=None)
    rationale: str = field(default="")


# ================================================================================
# UpdateChecker
# ================================================================================


_RELEASE_CURRENT_PATH = "/api/v1/release/current"

# US-296 / B-047 D7 cooldown defaults.  Both are config-overridable via
# ``pi.update.cooldownHours`` and ``pi.update.cooldownTimestampPath``; the
# module-constant fallbacks let new Pi deploys honor the contract before
# config.json is updated (mirrors the US-294 service-health constants).
_DEFAULT_COOLDOWN_HOURS = 24.0
_DEFAULT_COOLDOWN_TIMESTAMP_PATH = (
    "~/.cache/eclipse-obd/last-update-check.timestamp"
)


class UpdateChecker:
    """Decide whether the Pi needs to apply a server-published release.

    One instance is reusable across many :meth:`check_for_updates` calls.
    Holds no open sockets or DB connections; opens a one-shot HTTP request
    on each call.

    Construction
    ------------
    Args:
        config: Full Pi config dict (validator output).  Reads
            ``pi.update.*`` for policy, ``pi.companionService.*`` for the
            transport (baseUrl + apiKeyEnv + syncTimeoutSeconds).
        httpOpener: Callable compatible with :func:`urllib.request.urlopen`;
            injected in tests to avoid real HTTP.  Defaults to
            ``urllib.request.urlopen``.
        isDrivingFn: Zero-arg callable returning ``True`` when a drive is
            in progress.  When ``None`` (the default), the drive-state gate
            is OPEN -- callers like the orchestrator hand in a closure
            over ``driveDetector.isDriving()``.
        isSyncCaughtUpFn: Zero-arg callable returning ``True`` when the
            Pi's sync_log cursor is at or ahead of the latest
            realtime_data row (B-047 D2 + D9).  When ``None`` (default),
            the gate is OPEN.  US-295.
        isDtcRetrievalActiveFn: Zero-arg callable returning ``True`` when
            a DTC retrieval (Mode 03 / Mode 07) is mid-execution
            (B-047 D2).  When ``None`` (default), the gate is OPEN.
            US-295.

    Notes:
        Construction is side-effect-free (no network, no DB).  All real
        work happens inside :meth:`check_for_updates`.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        httpOpener: Callable[..., Any] | None = None,
        isDrivingFn: Callable[[], bool] | None = None,
        isSyncCaughtUpFn: Callable[[], bool] | None = None,
        isDtcRetrievalActiveFn: Callable[[], bool] | None = None,
    ) -> None:
        self._config = config
        piConfig: dict[str, Any] = config.get("pi", {}) or {}
        self._update: dict[str, Any] = piConfig.get("update", {}) or {}
        self._companion: dict[str, Any] = piConfig.get("companionService", {}) or {}

        self._httpOpener = httpOpener or urllib.request.urlopen
        self._isDrivingFn = isDrivingFn
        self._isSyncCaughtUpFn = isSyncCaughtUpFn
        self._isDtcRetrievalActiveFn = isDtcRetrievalActiveFn

        # US-296 / B-047 D7: 24-hour cooldown after each completed check.
        # Persistence survives reboots via the timestamp file at
        # ``cooldownTimestampPath`` (default
        # ``~/.cache/eclipse-obd/last-update-check.timestamp``).
        self._cooldownSeconds: float = (
            float(self._update.get("cooldownHours", _DEFAULT_COOLDOWN_HOURS))
            * 3600.0
        )
        self._cooldownTimestampPath: str = str(
            self._update.get(
                "cooldownTimestampPath", _DEFAULT_COOLDOWN_TIMESTAMP_PATH
            )
        )

    # ---- config surface ----------------------------------------------------

    @property
    def isEnabled(self) -> bool:
        """``pi.update.enabled`` -- defaults to True."""
        return bool(self._update.get("enabled", True))

    @property
    def baseUrl(self) -> str:
        """Companion-service base URL with any trailing slash stripped."""
        return str(self._companion.get("baseUrl", "")).rstrip("/")

    @property
    def localVersionPath(self) -> str:
        """Filesystem path to the local ``.deploy-version`` record."""
        return str(self._update.get("localVersionPath", ".deploy-version"))

    @property
    def markerFilePath(self) -> str:
        """Filesystem path the update-pending marker is written to."""
        return str(
            self._update.get(
                "markerFilePath", "/var/lib/eclipse-obd/update-pending.json"
            )
        )

    @property
    def intervalMinutes(self) -> float:
        """Configured cadence for the orchestrator-side interval trigger."""
        return float(self._update.get("intervalMinutes", 60))

    def _readApiKey(self) -> str | None:
        """Read the API key from the configured env var; return None on miss."""
        envName = str(self._companion.get("apiKeyEnv") or "COMPANION_API_KEY")
        value = getSecret(envName)
        return value or None

    def _readTimeoutSeconds(self) -> float:
        return float(self._companion.get("syncTimeoutSeconds", 30))

    # ---- public API --------------------------------------------------------

    def check_for_updates(self) -> CheckResult:
        """Check the server for a newer release and write a marker if so.

        Honored short-circuits, in order: drive-in-progress, disabled,
        missing API key, missing local ``.deploy-version``, server 503
        (no record), server other 5xx / network error.  Only the
        ``UPDATE_AVAILABLE`` outcome writes a marker file.

        Returns:
            :class:`CheckResult` describing the outcome.  Never raises --
            every error path resolves to a typed outcome so the caller
            (orchestrator runLoop) does not need a try/except.
        """
        # Drive-state gate (highest priority -- "drive-state-is-sacred").
        if self._isDrivingFn is not None:
            try:
                if self._isDrivingFn():
                    logger.debug(
                        "Update check skipped: drive in progress"
                    )
                    return CheckResult(
                        outcome=CheckOutcome.SKIPPED_DRIVING,
                        rationale="drive in progress",
                    )
            except Exception as exc:  # noqa: BLE001 -- defensive: detector glitch
                logger.warning(
                    "isDrivingFn raised %s: %s -- treating as 'not driving'",
                    type(exc).__name__, exc,
                )

        # US-295 / B-047 D2: sync-cursor-caught-up gate.  Skipping here
        # avoids a self-deploy that would orphan unsynced realtime_data
        # rows on disk (D9: "self-deploy waits for sync_log cursor to be
        # >= current MAX(realtime_data.id)").  A glitch in the closure
        # opens the gate (warn + treat as caught up) -- mirrors the
        # isDrivingFn defensive pattern.
        if self._isSyncCaughtUpFn is not None:
            try:
                if not self._isSyncCaughtUpFn():
                    logger.info(
                        "Update check skipped: sync_log cursor lagging"
                    )
                    return CheckResult(
                        outcome=CheckOutcome.SKIPPED_SYNC_LAGGING,
                        rationale="sync_log cursor behind realtime_data MAX(id)",
                    )
            except Exception as exc:  # noqa: BLE001 -- defensive
                logger.warning(
                    "isSyncCaughtUpFn raised %s: %s -- treating as 'caught up'",
                    type(exc).__name__, exc,
                )

        # US-295 / B-047 D2: DTC-retrieval-in-flight gate.  US-292 added
        # 30s during-drive Mode 03 cadence + drive_end Mode 07 pull;
        # drive_end runs from a DriveDetector callback which can fire on
        # a thread distinct from the runLoop thread that drives the
        # update-check trigger.  A glitch in the closure opens the
        # gate (warn + treat as not active).
        if self._isDtcRetrievalActiveFn is not None:
            try:
                if self._isDtcRetrievalActiveFn():
                    logger.info(
                        "Update check skipped: DTC retrieval in flight"
                    )
                    return CheckResult(
                        outcome=CheckOutcome.SKIPPED_DTC_ACTIVE,
                        rationale="DTC retrieval in flight",
                    )
            except Exception as exc:  # noqa: BLE001 -- defensive
                logger.warning(
                    "isDtcRetrievalActiveFn raised %s: %s -- "
                    "treating as 'not active'",
                    type(exc).__name__, exc,
                )

        # Disabled gate.
        if not self.isEnabled:
            logger.debug("Update check skipped: pi.update.enabled=false")
            return CheckResult(
                outcome=CheckOutcome.DISABLED,
                rationale="pi.update.enabled=false",
            )

        # US-296 / B-047 D7: 24-hour cooldown gate.  If a completed
        # check happened within the configured cooldown window, skip
        # without touching the network; the next eligible trigger
        # after cooldown elapses will retry.  Persistence survives
        # reboots via the timestamp file -- a malformed / unreadable
        # file degrades to "no prior check" so a glitch never
        # perma-blocks updates (defense in depth).
        lastCheckedAt = self._readLastCheckTimestamp()
        if lastCheckedAt is not None:
            elapsed = (datetime.now(UTC) - lastCheckedAt).total_seconds()
            if elapsed < self._cooldownSeconds:
                logger.debug(
                    "Update check skipped: cooldown active "
                    "(elapsed=%.0fs of %.0fs)",
                    elapsed, self._cooldownSeconds,
                )
                return CheckResult(
                    outcome=CheckOutcome.SKIPPED_COOLDOWN,
                    rationale=(
                        f"24-hour cooldown active "
                        f"(elapsed={int(elapsed)}s of "
                        f"{int(self._cooldownSeconds)}s)"
                    ),
                )

        # Config gate (must have an API key configured).
        apiKey = self._readApiKey()
        if not apiKey:
            envName = str(self._companion.get("apiKeyEnv") or "COMPANION_API_KEY")
            logger.warning(
                "Update check skipped: %s env var not set (config error)",
                envName,
            )
            return CheckResult(
                outcome=CheckOutcome.CONFIG_ERROR,
                rationale=f"{envName} env var not set",
            )

        # Local version gate -- without a baseline we cannot make a
        # meaningful comparison.  We do not assume "no local file" means
        # "needs update": a fresh untouched bench Pi has no .deploy-version
        # at all and that is its own operator situation.
        localRecord = readDeployVersion(self.localVersionPath)
        if localRecord is None:
            logger.info(
                "Update check skipped: local version file not present or "
                "invalid at %s",
                self.localVersionPath,
            )
            return CheckResult(
                outcome=CheckOutcome.LOCAL_VERSION_UNAVAILABLE,
                rationale=f"local .deploy-version unreadable at {self.localVersionPath}",
            )
        localVersion: str = localRecord["version"]

        # Server fetch.
        url = f"{self.baseUrl}{_RELEASE_CURRENT_PATH}"
        req = urllib.request.Request(
            url,
            headers={"X-API-Key": apiKey},
            method="GET",
        )
        try:
            with self._httpOpener(req, timeout=self._readTimeoutSeconds()) as resp:
                rawBody = resp.read()
        except urllib.error.HTTPError as exc:
            code = getattr(exc, "code", 0) or 0
            if code == 503:
                logger.info(
                    "Update check: server reports no record stamped (503); "
                    "treating as 'no update available'"
                )
                # US-296 / D7: SERVER_NO_RECORD is a server-reached
                # terminal -- the check completed in the D7 sense; burn
                # cooldown so the next trigger waits the configured window.
                self._writeLastCheckTimestamp(datetime.now(UTC))
                return CheckResult(
                    outcome=CheckOutcome.SERVER_NO_RECORD,
                    localVersion=localVersion,
                    rationale="server returned 503 (no release record)",
                )
            logger.warning(
                "Update check network error: HTTP %d %s",
                code, getattr(exc, "reason", ""),
            )
            return CheckResult(
                outcome=CheckOutcome.NETWORK_ERROR,
                localVersion=localVersion,
                rationale=f"HTTP {code}",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning(
                "Update check network error: %s: %s",
                type(exc).__name__, exc,
            )
            return CheckResult(
                outcome=CheckOutcome.NETWORK_ERROR,
                localVersion=localVersion,
                rationale=f"{type(exc).__name__}",
            )

        # Parse + validate the server payload (US-246 contract: bare record
        # {version, releasedAt, gitHash, description}).
        try:
            serverRecord = json.loads(rawBody)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Update check: server response is not valid JSON: %s", exc,
            )
            return CheckResult(
                outcome=CheckOutcome.NETWORK_ERROR,
                localVersion=localVersion,
                rationale="server response not JSON",
            )

        if not validateRelease(serverRecord):
            logger.warning(
                "Update check: server response failed shape validation: %r",
                serverRecord,
            )
            return CheckResult(
                outcome=CheckOutcome.NETWORK_ERROR,
                localVersion=localVersion,
                rationale="server record failed shape validation",
            )
        serverVersion: str = serverRecord["version"]

        # Version comparison (single source of truth -- scripts.version_helpers).
        if parseVersion(serverVersion) <= parseVersion(localVersion):
            logger.info(
                "Update check: up to date (local=%s, server=%s)",
                localVersion, serverVersion,
            )
            # US-296 / D7: completed check (server-reached, no update needed).
            self._writeLastCheckTimestamp(datetime.now(UTC))
            return CheckResult(
                outcome=CheckOutcome.UP_TO_DATE,
                localVersion=localVersion,
                serverVersion=serverVersion,
                rationale=(
                    f"server {serverVersion} <= local {localVersion}"
                ),
            )

        # Newer -> write the marker.
        rationale = (
            f"server reports newer version {serverVersion}; "
            f"local is {localVersion}"
        )
        markerPath = self._writeMarkerFile(serverVersion, rationale)
        logger.info(
            "Update available: local=%s -> server=%s; marker=%s",
            localVersion, serverVersion, markerPath,
        )
        # US-296 / D7: completed check (server-reached, marker written).
        # Cooldown applies regardless of UPDATE_AVAILABLE vs UP_TO_DATE per
        # D7: "after EACH check completes -- regardless of outcome".
        self._writeLastCheckTimestamp(datetime.now(UTC))
        return CheckResult(
            outcome=CheckOutcome.UPDATE_AVAILABLE,
            localVersion=localVersion,
            serverVersion=serverVersion,
            markerPath=markerPath,
            rationale=rationale,
        )

    # ---- internals ---------------------------------------------------------

    def _readLastCheckTimestamp(self) -> datetime | None:
        """Read the persisted last-check timestamp (US-296 / B-047 D7).

        Returns the on-disk ``datetime`` (coerced to UTC) when the file
        exists and parses; ``None`` when the file is absent, unreadable,
        or malformed.  Defensive-by-design: a glitch must NOT
        perma-block updates -- the safer fallback is to proceed with
        the check (worst case: one extra check; the worst case for the
        opposite policy is "no updates ever ship after a transient
        filesystem hiccup").
        """
        path = Path(self._cooldownTimestampPath).expanduser()
        if not path.is_file():
            return None
        try:
            raw = path.read_text().strip()
            ts = datetime.fromisoformat(raw)
        except (OSError, ValueError) as exc:
            logger.warning(
                "Cooldown timestamp at %s is unreadable (%s: %s); "
                "treating as no prior check",
                path, type(exc).__name__, exc,
            )
            return None
        # A naive datetime would crash the gate's ``now() - ts`` arithmetic.
        # Coerce to UTC -- a malformed naive write is still safer to
        # interpret than to crash the check.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts

    def _writeLastCheckTimestamp(self, when: datetime) -> None:
        """Persist the completed-check timestamp (US-296 / B-047 D7).

        Called from the three server-reached terminal returns
        (``UPDATE_AVAILABLE`` / ``UP_TO_DATE`` / ``SERVER_NO_RECORD``)
        per D7's "after EACH check completes -- regardless of outcome".
        Best-effort: a write failure (read-only filesystem, missing
        parent dir permission) is logged + swallowed so the check
        outcome is not downgraded by an observability problem.  The
        next call resumes the cooldown discipline.
        """
        path = Path(self._cooldownTimestampPath).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(when.isoformat())
        except OSError as exc:
            logger.warning(
                "Cooldown timestamp write to %s failed (%s: %s)",
                path, type(exc).__name__, exc,
            )

    def _writeMarkerFile(self, targetVersion: str, rationale: str) -> str:
        """Write the update-pending marker; create parent dir as needed.

        The marker is the only inter-step communication channel between
        US-C (this checker) and US-D (the apply step).  An existing
        marker is overwritten so the latest decision wins.
        """
        path = Path(self.markerFilePath)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "target_version": targetVersion,
            "server_url": self.baseUrl,
            "rationale": rationale,
            "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        path.write_text(json.dumps(body, indent=2))
        return str(path)
