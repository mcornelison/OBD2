################################################################################
# File Name: boot_progress.py
# Purpose/Description: Crash-surviving boot-progress breadcrumb instrument.
#                      Replaces the journald-based boot canary (I-037). A
#                      dirty-by-default append-only file records the furthest
#                      milestone the shutdown sequence reached; the next boot
#                      derives a positive-proof-only verdict. Only the systemd
#                      shutdown-finalizer writes CLEAN_COMPLETE, so a hard crash
#                      can never forge 'clean'. See
#                      $FLEET_SHARE/knowledge/superpowers/specs/2026-05-15-honest-boot-progress-instrument-design.md.
# Author: (implementation plan 2026-05-15)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-15    | Plan    | Initial -- Bug 2 honest instrument.
# 2026-05-15    | Plan    | T2 -- add fail-safe markMilestone.
# 2026-05-15    | Plan    | T3 -- readPriorTrail + positive-proof deriveVerdict.
# 2026-05-15    | Plan    | T5 -- arm reader (verdict -> startup_log -> NAS -> re-arm).
# 2026-05-15    | Plan    | T5r -- extract _fdatasyncBestEffort (portable durability); markMilestone+arm reuse; type _writeStartupLogRow.
# 2026-05-15    | Plan    | T6 -- finalize (delegates to markMilestone) + --arm/--finalize CLI.
# 2026-05-15    | Plan    | T6r -- lazy-import database_schema into _writeStartupLogRow so the finalize/CLI path is import-robust (systemd ExecStop).
# 2026-05-15    | Plan    | T8r -- _readBootId -> public readBootId (shared with orchestrator; DRY).
# 2026-05-21    | Rex     | US-353 -- markMilestone auto-trims oldest lines instead
#                          of refusing to write (Argus's drill found refuse-to-write
#                          blocking first post-deploy reboot when trail accumulated
#                          from F-8-broken regime; every rung must land on disk).
# 2026-09-30    | Rex     | US-776-f -- arm lands powerwatch's shutdown-sync record
#                          (home state, sync outcome, backlog start/end) into four
#                          prior_boot_* columns, only when the record's boot_id is
#                          the prior boot's; otherwise NULL.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T2: also lands sync start/end and the pre-cut
#                          VCELL (three more prior_boot_* columns).
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T6: arm finalises the prior drain (cut step, window rate),
#                          best-effort.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T6 fix: also lands the loss wall time
#                          (prior_boot_loss_at) and keys the finaliser on it.
# 2026-10-03    | Atlas (ARCH-065a) | T7 fix 1: passes the prior sync outcome + home
#                          state to the finaliser (floor-ended at home -> replace).
# 2026-10-03    | Atlas (ARCH-065a) | Ruling 19: _asIso parses with CANONICAL_ISO_FORMAT
#                          (one owner of the format) instead of a literal.
# ================================================================================
################################################################################
"""Crash-surviving boot-progress breadcrumb instrument (replaces I-037 canary)."""

from __future__ import annotations

import argparse
import enum
import json
import logging
import os
import shutil
import sqlite3
from collections.abc import Callable
from datetime import datetime

from src.common.time.helper import CANONICAL_ISO_FORMAT, utcIsoNow
from src.pi.diagnostics.clock_sync import assessClockQuality

logger = logging.getLogger(__name__)

__all__ = [
    "Stage",
    "MILESTONE_ORDER",
    "CLEAN_COMPLETE_RUNG",
    "markMilestone",
    "readPriorTrail",
    "deriveVerdict",
    "arm",
    "finalize",
    "readBootId",
    "readPriorShutdownRecord",
    "main",
    "DEFAULT_FILE_PATH",
    "DEFAULT_MAX_TRAIL_BYTES",
    "OUTCOME_RECORD_FILENAME",
]


class Stage(enum.Enum):
    """Ordered shutdown-progress milestones. Single source of truth shared by
    the writer (orchestrator + shutdown_handler), the reader (arm), and the
    US-343 audit script. Making this config-mutable would re-create the
    US-308/US-342 silent-drift bug (spec sec 4.4)."""

    RUNNING = "RUNNING"
    WARNING = "WARNING"
    IMMINENT = "IMMINENT"
    TRIGGER = "TRIGGER"
    DRAIN_CLOSED = "DRAIN_CLOSED"
    TRIGGER_ROW_WRITTEN = "TRIGGER_ROW_WRITTEN"
    POWEROFF_INVOKED = "POWEROFF_INVOKED"
    POWEROFF_RC0 = "POWEROFF_RC0"
    CLEAN_COMPLETE = "CLEAN_COMPLETE"


#: The ladder in strict monotonic order. Index = rung height.
MILESTONE_ORDER: tuple[Stage, ...] = (
    Stage.RUNNING,
    Stage.WARNING,
    Stage.IMMINENT,
    Stage.TRIGGER,
    Stage.DRAIN_CLOSED,
    Stage.TRIGGER_ROW_WRITTEN,
    Stage.POWEROFF_INVOKED,
    Stage.POWEROFF_RC0,
    Stage.CLEAN_COMPLETE,
)

#: The ONLY rung that proves a graceful shutdown actually completed.
CLEAN_COMPLETE_RUNG: Stage = Stage.CLEAN_COMPLETE

#: Defaults mirror the config keys (later task wires config). These keep the
#: module usable standalone.
DEFAULT_FILE_PATH = "data/boot_progress"
DEFAULT_MAX_TRAIL_BYTES = 65536

#: powerwatch's durable shutdown record, written beside the DB
#: (power_watch/__main__.py derives the same path from its dbPath).
OUTCOME_RECORD_FILENAME = "powerwatch_outcome.json"


def _fdatasyncBestEffort(fileno: int) -> None:
    """Best-effort durability hint: fdatasync the fd, never raise.

    ``os.fdatasync`` is POSIX-only and absent on the Windows dev box. A
    platform without it (or a transient ``OSError``) must not break the
    surrounding write -- the Pi/Linux target keeps the durability
    guarantee; dev platforms degrade visibly at DEBUG. Mirrors the
    ``os.fsync``-in-its-own-try/except precedent in
    ``src/pi/power/power_db.py``.

    Args:
        fileno: Open file descriptor (int) to flush to stable storage.
    """
    try:
        os.fdatasync(fileno)
    except (OSError, AttributeError) as exc:  # noqa: BLE001 -- best-effort
        logger.debug("boot_progress: fdatasync skipped: %s", exc)


def markMilestone(
    stage: Stage,
    *,
    vcell: float | None,
    filePath: str = DEFAULT_FILE_PATH,
    bootId: str,
    maxTrailBytes: int = DEFAULT_MAX_TRAIL_BYTES,
) -> None:
    """Append one milestone line and fdatasync it. FAIL-SAFE.

    Never raises into the caller: the orchestrator/shutdown path must keep
    trying to power off even if this write fails under the I/O storm. A lost
    breadcrumb only degrades fidelity; the no-false-clean invariant holds
    because only the finalizer writes CLEAN_COMPLETE.

    When the trail would exceed ``maxTrailBytes``, the oldest complete
    lines are trimmed to fit and a WARN log is emitted -- the new
    milestone is ALWAYS written. Refusing to log a rung (the prior
    guard) created the observability hole Argus's V0.27.16 drill found:
    a trail that had accumulated past the cap from the F-8-broken
    regime caused the next boot to drop POWEROFF_INVOKED + every other
    subsequent rung. Trimming oldest preserves the MAX(rank) verdict
    (deriveVerdict already takes the highest-ranked rung) and keeps the
    most recent rung -- the load-bearing signal -- intact.
    """
    try:
        line = json.dumps(
            {"boot_id": bootId, "stage": stage.value,
             "ts": utcIsoNow(), "vcell": vcell},
            separators=(",", ":"),
        ) + "\n"
        lineBytes = line.encode("utf-8")
        currentSize = (os.path.getsize(filePath)
                       if os.path.exists(filePath) else 0)

        if currentSize + len(lineBytes) > maxTrailBytes:
            _autoTrimAndAppend(filePath, lineBytes, maxTrailBytes,
                               currentSize, stage)
            return

        fd = os.open(filePath, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, lineBytes)
            _fdatasyncBestEffort(fd)
        finally:
            os.close(fd)
    except Exception as exc:  # noqa: BLE001 -- fail-safe by contract
        logger.warning("boot_progress markMilestone(%s) failed: %s",
                        stage.value, exc)


def _autoTrimAndAppend(
    filePath: str,
    lineBytes: bytes,
    maxTrailBytes: int,
    currentSize: int,
    stage: Stage,
) -> None:
    """Drop oldest complete lines to fit ``lineBytes`` under
    ``maxTrailBytes``, then rewrite the file atomically with the new
    rung at the tail. WARN-logs the trim event so operators can see it.

    Line-boundary preserving: only complete oldest lines are dropped so
    a partial JSON line can never be stranded at the head. If even the
    new line alone exceeds ``maxTrailBytes`` (pathological config),
    the new line is still written -- the contract is "every rung lands
    on disk".
    """
    try:
        with open(filePath, "rb") as fh:
            existing = fh.read()
    except OSError:
        existing = b""

    keep = existing
    while keep and len(keep) + len(lineBytes) > maxTrailBytes:
        nl = keep.find(b"\n")
        if nl < 0:
            keep = b""
            break
        keep = keep[nl + 1:]

    newSize = len(keep) + len(lineBytes)
    logger.warning(
        "boot_progress trail trimmed at %s: was %d bytes, trimmed to %d "
        "bytes, current write of %s would have exceeded maxTrailBytes=%d",
        filePath, currentSize, newSize, stage.value, maxTrailBytes,
    )

    tmp = filePath + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, keep + lineBytes)
        _fdatasyncBestEffort(fd)
    finally:
        os.close(fd)
    os.replace(tmp, filePath)


#: Verdict mapping -- ONLY CLEAN_COMPLETE => clean. Positive proof only.
_VERDICT_BY_STAGE: dict[Stage, tuple[int, str]] = {
    Stage.CLEAN_COMPLETE: (1, "graceful"),
    Stage.POWEROFF_RC0: (0, "poweroff_accepted_unfinalized"),
    Stage.POWEROFF_INVOKED: (0, "poweroff_invoked_never_returned"),
    Stage.TRIGGER_ROW_WRITTEN: (0, "wedged_before_poweroff"),
    Stage.DRAIN_CLOSED: (0, "wedged_before_poweroff"),
    Stage.TRIGGER: (0, "wedged_before_poweroff"),
    Stage.IMMINENT: (0, "died_mid_drain"),
    Stage.WARNING: (0, "died_mid_drain"),
    Stage.RUNNING: (0, "crashed_during_operation"),
}
_RANK: dict[Stage, int] = {s: i for i, s in enumerate(MILESTONE_ORDER)}


def readPriorTrail(filePath: str = DEFAULT_FILE_PATH) -> list[dict]:
    """Read the prior boot's breadcrumb trail into a list of records.

    Defensive by contract: a missing/empty file or any malformed line is
    NOT an error -- absence of a record is itself the signal the reader
    must classify (it must never be inferred clean). Malformed JSON lines
    and non-dict / stage-less records are skipped so a torn final write
    under the shutdown I/O storm cannot strand the whole trail.

    Args:
        filePath: Path of the append-only breadcrumb file. Defaults to
            :data:`DEFAULT_FILE_PATH`.

    Returns:
        List of decoded record dicts (each with a truthy ``stage`` key),
        in file order. ``[]`` if the file is missing, unreadable, empty,
        or contains no well-formed stage records.
    """
    try:
        with open(filePath, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return []
    records: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(rec, dict) and rec.get("stage"):
            records.append(rec)
    return records


def deriveVerdict(trail: list[dict]) -> tuple[int | None, str | None, str]:
    """Derive the prior-boot verdict using POSITIVE-PROOF-ONLY semantics.

    The highest rung reached in ``trail`` (by :data:`MILESTONE_ORDER`
    rank, so a lower rung logged after a higher one does not demote the
    result) decides the verdict. Clean (``1``) is returned ONLY when the
    finalizer-written :attr:`Stage.CLEAN_COMPLETE` rung is present; every
    other highest rung yields ``0`` with a specific reason. An empty or
    unreadable trail yields ``None`` -- never inferred clean (this is the
    bug the old journald canary had: it forged "clean" from the absence
    of a negative). The "Drain-26 shape" (trail ends at
    ``POWEROFF_INVOKED`` with no ``CLEAN_COMPLETE``) therefore returns
    ``0``, where the old canary wrongly returned ``1``.

    Args:
        trail: Record dicts as produced by :func:`readPriorTrail`. Each
            should carry a ``stage`` value; records whose ``stage`` is
            not a recognized :class:`Stage` member are ignored.

    Returns:
        A ``(priorClean, priorStage, priorReason)`` tuple:
            * ``priorClean``: ``1`` iff ``CLEAN_COMPLETE`` was reached,
              ``0`` for any other highest rung, ``None`` when the trail
              has no usable record.
            * ``priorStage``: The value of the highest rung reached, or
              ``None`` when there is no usable record.
            * ``priorReason``: Short reason code for the verdict
              (``"indeterminate_no_record"`` when the trail is empty).
    """
    highest: Stage | None = None
    for rec in trail:
        try:
            st = Stage(rec["stage"])
        except (ValueError, KeyError):
            continue
        if highest is None or _RANK[st] > _RANK[highest]:
            highest = st
    if highest is None:
        return (None, None, "indeterminate_no_record")
    clean, reason = _VERDICT_BY_STAGE[highest]
    return (clean, highest.value, reason)


def _asLabel(value: object) -> str | None:
    """A non-blank string, stripped; anything else is NULL."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _asCount(value: object) -> int | None:
    """A non-negative int (bool excluded); anything else is NULL."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _asIso(value: object) -> str | None:
    """A canonical UTC ISO second ('YYYY-MM-DDTHH:MM:SSZ'), else None."""
    if not isinstance(value, str):
        return None
    try:
        datetime.strptime(value, CANONICAL_ISO_FORMAT)
    except ValueError:
        return None
    return value


def _asVolts(value: object) -> float | None:
    """A plausible single-cell VCELL (2.5-4.5 V), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 2.5 <= value <= 4.5 else None


#: Record key -> (startup_log column, validator). A value the validator
#: rejects lands NULL: the column is never filled with a coerced guess.
_PRIOR_BOOT_SYNC_FIELDS: tuple[tuple[str, str, Callable[[object], object]], ...] = (
    ("home_state", "prior_boot_home_state", _asLabel),
    ("sync_outcome", "prior_boot_sync_outcome", _asLabel),
    ("backlog_start", "prior_boot_backlog_start", _asCount),
    ("backlog_end", "prior_boot_backlog_end", _asCount),
    ("sync_started_at", "prior_boot_sync_started_at", _asIso),
    ("sync_ended_at", "prior_boot_sync_ended_at", _asIso),
    ("vcell_before_cut_v", "prior_boot_vcell_before_cut_v", _asVolts),
    ("loss_at", "prior_boot_loss_at", _asIso),
)


def readPriorShutdownRecord(
    recordPath: str, priorBootIds: set[str],
) -> dict[str, object]:
    """Read the prior boot's shutdown-sync fields from powerwatch's record.

    US-776-f. The record is overwritten in place, so the file on disk after a
    hard cut is an OLDER boot's. Its fields are landed only when its
    ``boot_id`` is one of ``priorBootIds`` (the boot ids in the prior boot's
    breadcrumb trail); ``unknown`` -- :func:`readBootId`'s failure value --
    never matches. Otherwise every column is NULL. Never raises.

    Args:
        recordPath: Path of ``powerwatch_outcome.json``.
        priorBootIds: Boot ids found in the prior boot's breadcrumb trail.

    Returns:
        A dict with every ``prior_boot_*`` sync column, each value or None.
    """
    landed: dict[str, object] = {column: None for _, column, _ in _PRIOR_BOOT_SYNC_FIELDS}
    try:
        with open(recordPath, encoding="utf-8") as fh:
            record = json.load(fh)
    except FileNotFoundError:
        return landed
    except (OSError, ValueError) as exc:
        logger.warning("boot_progress: shutdown record unreadable (%s): %s",
                       recordPath, exc)
        return landed
    if not isinstance(record, dict):
        return landed
    recordBootId = _asLabel(record.get("boot_id"))
    owners = priorBootIds - {"unknown"}
    if recordBootId is None or recordBootId not in owners:
        logger.info("boot_progress: shutdown record boot_id %s is not the prior "
                    "boot's -- prior-boot sync fields land NULL", recordBootId)
        return landed
    for key, column, validate in _PRIOR_BOOT_SYNC_FIELDS:
        landed[column] = validate(record.get(key))
    return landed


def _writeStartupLogRow(
    dbPath: str,
    bootId: str,
    clean: int | None,
    lastStage: str | None,
    reason: str,
    clockQualityProvider: Callable[[str], str] = assessClockQuality,
    priorBootSync: dict[str, object] | None = None,
) -> None:
    """Idempotent INSERT OR IGNORE startup_log row (one row per boot_id).

    US-419 (F-080): the row is stamped with a ``data_quality`` clock verdict.
    ``startup_log`` is the canonical one-per-boot "first post-boot row", so it
    pays the full :func:`assessClockQuality` (NTP probe + sanity floor) at most
    once per boot.  ``clockQualityProvider`` is the injection seam for tests.

    US-776-f: ``priorBootSync`` carries the four ``prior_boot_*`` sync columns
    from :func:`readPriorShutdownRecord`; None lands them all NULL.
    """
    # Lazy import: keep the crash-time finalize / --finalize CLI path free
    # of the heavy src.pi.obdii package graph (its __init__ eagerly does
    # `from pi.display import ...` which is not importable in a bare
    # `python -m ... --finalize` subprocess -- the systemd ExecStop
    # invocation). Only the arm/DB path needs this. See
    # feedback-lazy-import-patch-rewiring.
    from src.pi.obdii.database_schema import (
        ensureStartupLogDataQuality,
        ensureStartupLogForensicColumns,
        ensureStartupLogPriorBootSyncColumns,
        ensureStartupLogRecordedAt,
    )

    sync = priorBootSync or {}
    conn = sqlite3.connect(dbPath, timeout=5.0)
    try:
        ensureStartupLogForensicColumns(conn)
        # US-417: guarantee the recorded_at SNAPSHOT_SYNC cursor column exists
        # before the row is written / synced.  No-op on any real Pi DB (present
        # since US-263); defensive for a legacy/partial startup_log.
        ensureStartupLogRecordedAt(conn)
        # US-419: guarantee the data_quality clock-drift flag column exists.
        ensureStartupLogDataQuality(conn)
        # US-776-f: arm may run before eclipse-obd's initialize on this boot.
        ensureStartupLogPriorBootSyncColumns(conn)
        recordedAt = utcIsoNow()
        dataQuality = clockQualityProvider(recordedAt)
        conn.execute(
            "INSERT OR IGNORE INTO startup_log "
            "(boot_id, prior_boot_clean, prior_last_entry_ts, "
            " current_boot_first_entry_ts, recorded_at, "
            " prior_boot_last_stage, prior_boot_reason, data_quality, "
            " prior_boot_home_state, prior_boot_sync_outcome, "
            " prior_boot_backlog_start, prior_boot_backlog_end, "
            " prior_boot_sync_started_at, prior_boot_sync_ended_at, "
            " prior_boot_vcell_before_cut_v, prior_boot_loss_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bootId, clean, None, None, recordedAt, lastStage, reason,
             dataQuality,
             sync.get("prior_boot_home_state"),
             sync.get("prior_boot_sync_outcome"),
             sync.get("prior_boot_backlog_start"),
             sync.get("prior_boot_backlog_end"),
             sync.get("prior_boot_sync_started_at"),
             sync.get("prior_boot_sync_ended_at"),
             sync.get("prior_boot_vcell_before_cut_v"),
             sync.get("prior_boot_loss_at")),
        )
        conn.commit()
    finally:
        conn.close()


def _finalizePriorDrain(dbPath: str, priorBootSync: dict[str, object]) -> None:
    """ARCH-065 T6: finish the prior drain's cut step / window rate. Never raises.

    Lazy-imported like :func:`_writeStartupLogRow`; arm runs in a oneshot that
    must not fail on a capacity-field problem.
    """
    try:
        from src.pi.power.battery_health import ensureBatteryHealthLogCapacityColumns
        from src.pi.power.battery_health_finalize import finalizeLatestDrain

        vcell = priorBootSync.get("prior_boot_vcell_before_cut_v")
        lossAt = priorBootSync.get("prior_boot_loss_at")
        syncOutcome = priorBootSync.get("prior_boot_sync_outcome")
        homeState = priorBootSync.get("prior_boot_home_state")
        conn = sqlite3.connect(dbPath, timeout=5.0)
        try:
            ensureBatteryHealthLogCapacityColumns(conn)
            finalizeLatestDrain(
                conn,
                priorBootVcellBeforeCutV=float(vcell) if isinstance(vcell, (int, float)) else None,
                priorBootLossAt=lossAt if isinstance(lossAt, str) else None,
                priorBootSyncOutcome=syncOutcome if isinstance(syncOutcome, str) else None,
                priorBootHomeState=homeState if isinstance(homeState, str) else None,
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 -- never block boot
        logger.warning("boot_progress: prior-drain finalise skipped: %s", exc)


def arm(
    *,
    filePath: str = DEFAULT_FILE_PATH,
    dbPath: str,
    bootId: str,
    nasArchiveDir: str,
    nasArchiveEnabled: bool,
    clockQualityProvider: Callable[[str], str] = assessClockQuality,
    outcomeRecordPath: str | None = None,
) -> None:
    """Boot-time reader: classify the prior boot, then re-arm for this one.

    Reads the prior boot's breadcrumb trail, derives the positive-proof
    verdict, writes ONE idempotent ``startup_log`` row, optionally archives
    the prior trail to the NAS, then truncates the file and writes a fresh
    :attr:`Stage.RUNNING` line for the new boot.

    CRITICAL invariant: re-arming the new boot (truncate + ``RUNNING``)
    happens EVEN IF the DB write or NAS archive failed. The verdict is
    already derived in memory before either side-effect is attempted, so a
    failed forensic write must never strand the new boot without a fresh
    breadcrumb trail -- arming the new boot is the most important step.

    Args:
        filePath: Path of the append-only breadcrumb file. Defaults to
            :data:`DEFAULT_FILE_PATH`.
        dbPath: Path to the SQLite DB whose ``startup_log`` table receives
            the prior-boot verdict row.
        bootId: Identifier for the NEW boot. Also the ``startup_log``
            primary key, so re-running ``arm`` for the same boot is a
            no-op insert (INSERT OR IGNORE).
        nasArchiveDir: Directory the prior trail is copied into when
            archiving is enabled.
        nasArchiveEnabled: When ``True`` and a prior trail exists, copy it
            to ``nasArchiveDir`` before truncation (best-effort).
        clockQualityProvider: US-419 injection seam mapping the row's
            ``recorded_at`` to a ``data_quality`` clock verdict.  Defaults to
            :func:`src.pi.diagnostics.clock_sync.assessClockQuality`.
        outcomeRecordPath: powerwatch's shutdown record (US-776-f), whose
            sync fields land as the ``prior_boot_*`` sync columns. Defaults
            to :data:`OUTCOME_RECORD_FILENAME` beside ``dbPath`` -- where
            powerwatch writes it.

    Returns:
        None.
    """
    trail = readPriorTrail(filePath)
    clean, lastStage, reason = deriveVerdict(trail)
    if outcomeRecordPath is None:
        outcomeRecordPath = os.path.join(os.path.dirname(dbPath), OUTCOME_RECORD_FILENAME)
    priorBootIds = {str(rec["boot_id"]) for rec in trail if rec.get("boot_id")}
    priorBootSync = readPriorShutdownRecord(outcomeRecordPath, priorBootIds)

    try:
        _writeStartupLogRow(
            dbPath, bootId, clean, lastStage, reason, clockQualityProvider,
            priorBootSync,
        )
    except Exception as exc:  # noqa: BLE001 -- never block boot
        logger.error("boot_progress: startup_log write failed: %s", exc)

    _finalizePriorDrain(dbPath, priorBootSync)

    if nasArchiveEnabled and trail:
        try:
            os.makedirs(nasArchiveDir, exist_ok=True)
            shutil.copy2(
                filePath,
                os.path.join(nasArchiveDir, f"boot_progress.{bootId}.jsonl"),
            )
        except Exception as exc:  # noqa: BLE001 -- best-effort
            logger.warning("boot_progress: NAS archive skipped: %s", exc)

    try:
        tmp = filePath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("")
            fh.flush()
            _fdatasyncBestEffort(fh.fileno())
        os.replace(tmp, filePath)
    except Exception as exc:  # noqa: BLE001
        logger.error("boot_progress: re-arm truncate failed: %s", exc)
    markMilestone(Stage.RUNNING, vcell=None, filePath=filePath, bootId=bootId)


def finalize(*, filePath: str = DEFAULT_FILE_PATH, bootId: str) -> None:
    """Append the single CLEAN_COMPLETE rung. Called ONLY by the systemd
    finalizer ExecStop -- a hard crash never reaches this. Delegates to
    markMilestone (which does the durable _fdatasyncBestEffort write); no
    separate I/O here.

    Args:
        filePath: Breadcrumb file path.
        bootId: Current boot id stamped on the rung.
    """
    markMilestone(Stage.CLEAN_COMPLETE, vcell=None,
                  filePath=filePath, bootId=bootId)


def readBootId() -> str:
    """Current boot id via boot_reason.readCurrentBootId; 'unknown' on any failure."""
    try:
        from src.pi.diagnostics.boot_reason import readCurrentBootId
        return readCurrentBootId() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the systemd arm + finalize units.

    Args:
        argv: Optional argument list (defaults to sys.argv when None).

    Returns:
        Process exit code (0 on success).
    """
    p = argparse.ArgumentParser(description="Boot-progress instrument")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--arm", action="store_true")
    g.add_argument("--finalize", action="store_true")
    p.add_argument("--file", default=DEFAULT_FILE_PATH)
    p.add_argument("--db", default="data/obd.db")
    p.add_argument("--boot-id", default=None)
    p.add_argument("--nas-dir", default="")
    p.add_argument("--nas-enabled", action="store_true")
    p.add_argument("--outcome-record", default=None)
    a = p.parse_args(argv)
    bootId = a.boot_id or readBootId()
    if a.finalize:
        finalize(filePath=a.file, bootId=bootId)
    else:
        outcomeRecordPath = a.outcome_record or os.path.join(
            os.path.dirname(a.db), OUTCOME_RECORD_FILENAME)
        arm(filePath=a.file, dbPath=a.db, bootId=bootId,
            nasArchiveDir=a.nas_dir, nasArchiveEnabled=a.nas_enabled,
            outcomeRecordPath=outcomeRecordPath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
