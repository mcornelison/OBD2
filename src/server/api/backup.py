################################################################################
# File Name: backup.py
# Purpose/Description: POST /api/v1/backup multipart file receiver for
#                      Pi-side database / log / config snapshots. Validates
#                      type + deviceId + extension + size, writes files under
#                      BACKUP_DIR/{deviceId}/{type}/ with an ISO-timestamped
#                      filename, and enforces per-bucket retention rotation.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-007 — backup
#               |              | receiver endpoint with rotation
# ================================================================================
################################################################################

"""
Backup receiver endpoint for the Eclipse OBD-II companion server.

Accepts ``multipart/form-data`` uploads from Pi devices containing a
disaster-recovery snapshot of one of three buckets:

* ``database`` — SQLite archive of on-Pi state (``.db`` / ``.gz``)
* ``logs``     — service logs (``.log`` / ``.gz``)
* ``config``   — configuration files (``.json`` / ``.gz``)

Route (server spec §3.4, sprint US-CMP-007):

* API key required (attached via ``Depends(requireApiKey)`` at router include
  time in ``src/server/api/app.py``).
* Extensions outside ``{.db, .log, .json, .gz}`` → 415.
* Unknown ``type`` values → 422.
* ``deviceId`` outside ``[A-Za-z0-9_.-]+`` → 422 (path-traversal guard).
* Files larger than ``MAX_BACKUP_SIZE_MB`` (default 100 MB) → 413. Enforced
  both at the ``Content-Length`` header (fast reject) and while streaming
  the body (authoritative — the header may be missing or wrong).
* Stored at
  ``{BACKUP_DIR}/{deviceId}/{type}/{stem}-{ISO8601 timestamp}.{ext}``.
  The timestamp uses ``-`` in place of ``:`` so the filename is valid on
  Windows filesystems.
* After each successful write, files under the
  ``{deviceId}/{type}`` bucket are sorted by mtime and trimmed to the
  configured retention count. At least one file is always kept — the
  "never delete the last remaining file" invariant from the sprint.
* Response envelope: ``{status, path, bytes, rotated}``.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ==============================================================================
# Constants
# ==============================================================================

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".db", ".log", ".json", ".gz"})
ALLOWED_TYPES: frozenset[str] = frozenset({"database", "logs", "config"})

_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")

_UNKNOWN_TYPE_DETAIL = "Unknown backup type"
_INVALID_DEVICE_ID_DETAIL = "Invalid deviceId"
_DISALLOWED_EXTENSION_DETAIL = "Disallowed file extension"
_PAYLOAD_TOO_LARGE_DETAIL = "Backup exceeds max size"
_STORAGE_FAILURE_DETAIL = "Backup storage failed"

_READ_CHUNK_BYTES = 1024 * 1024  # 1 MB streaming chunks


# ==============================================================================
# Response model
# ==============================================================================


class BackupResponse(BaseModel):
    """Response envelope for POST /backup."""

    status: str
    path: str
    bytes: int
    rotated: int


# ==============================================================================
# Pure helpers
# ==============================================================================


def _validateType(backupType: str) -> str:
    """Return the canonical backup type or raise 422."""
    if backupType not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{_UNKNOWN_TYPE_DETAIL}: {backupType!r}. "
            f"Accepted: {sorted(ALLOWED_TYPES)}.",
        )
    return backupType


def _validateDeviceId(deviceId: str) -> str:
    """Return the validated deviceId or raise 422. Guards against path-traversal."""
    if not deviceId or not _DEVICE_ID_PATTERN.match(deviceId):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{_INVALID_DEVICE_ID_DETAIL}: {deviceId!r}. "
            "Must match [A-Za-z0-9_.-]+.",
        )
    return deviceId


def _validateExtension(filename: str) -> str:
    """Return the lower-cased allowed extension or raise 415."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"{_DISALLOWED_EXTENSION_DETAIL}: {ext!r}. "
            f"Accepted: {sorted(ALLOWED_EXTENSIONS)}.",
        )
    return ext


def _timestamp() -> str:
    """ISO 8601 UTC timestamp with microseconds, Windows-safe (no ``:``)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S.%f")


def _sanitizeStem(stem: str) -> str:
    """
    Strip any character that could escape the target directory from a stem.

    The route supplies ``Path(upload.filename).stem`` which is already
    directory-stripped by :class:`pathlib.Path`, but we defend in depth here:
    everything outside ``[A-Za-z0-9_.-]`` collapses to ``_``. The result is
    clipped to 100 characters so pathologically long names don't blow past
    filesystem limits.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_.\-]", "_", stem) or "backup"
    return cleaned[:100]


def _buildDestinationPath(
    backupDir: Path,
    deviceId: str,
    backupType: str,
    stem: str,
    ext: str,
) -> Path:
    """Compose the per-bucket timestamped destination path."""
    safeStem = _sanitizeStem(stem)
    filename = f"{safeStem}-{_timestamp()}{ext}"
    return Path(backupDir) / deviceId / backupType / filename


def _rotateBackups(directory: Path, retention: int) -> int:
    """
    Trim ``directory`` to the most-recent ``retention`` files (by mtime).

    Returns the number of files deleted.

    Invariants:
        * At least one file is always kept (protects against a misconfigured
          ``retention=0`` wiping the bucket).
        * Unlink failures are swallowed and logged; the endpoint must not
          500 because rotation couldn't clean up.
    """
    if not directory.exists():
        return 0

    keep = max(retention, 1)
    # Sort files newest-first. stat() can raise if the file vanished between
    # the glob and the stat — filter those out.
    entries: list[tuple[Path, float]] = []
    for p in directory.iterdir():
        if not p.is_file():
            continue
        try:
            entries.append((p, p.stat().st_mtime))
        except OSError:
            continue
    entries.sort(key=lambda item: item[1], reverse=True)

    deleted = 0
    for path, _ in entries[keep:]:
        try:
            path.unlink()
            deleted += 1
        except OSError as exc:
            logger.warning("Failed to rotate backup %s: %s", path, exc)
    return deleted


# ==============================================================================
# Streaming write
# ==============================================================================


async def _streamToDisk(upload: UploadFile, destination: Path, maxBytes: int) -> int:
    """
    Stream ``upload`` to ``destination`` with a running byte cap.

    Returns the number of bytes written. Raises:
        HTTPException(413): when the cap is exceeded mid-stream. Partial
            file is unlinked before the exception propagates.
        HTTPException(500): on OS-level write errors. A clean message is
            surfaced to the client; the exception is re-raised as 500.
    """
    bytesWritten = 0
    try:
        with destination.open("wb") as sink:
            while True:
                chunk = await upload.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                bytesWritten += len(chunk)
                if bytesWritten > maxBytes:
                    sink.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            f"{_PAYLOAD_TOO_LARGE_DETAIL}: "
                            f"{maxBytes // (1024 * 1024)} MB"
                        ),
                    )
                sink.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        logger.error("Backup write failed for %s: %s", destination, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_STORAGE_FAILURE_DETAIL,
        ) from exc
    return bytesWritten


# ==============================================================================
# Route
# ==============================================================================


router = APIRouter()


def _resolveBackupDir(request: Request) -> Path:
    settings = getattr(request.app.state, "settings", None)
    backupDir = getattr(settings, "BACKUP_DIR", "./data/backups") if settings else "./data/backups"
    return Path(backupDir)


def _resolveMaxBytes(request: Request) -> int:
    settings = getattr(request.app.state, "settings", None)
    maxMb = getattr(settings, "MAX_BACKUP_SIZE_MB", 100) if settings else 100
    return int(maxMb) * 1024 * 1024


def _resolveRetention(request: Request) -> int:
    settings = getattr(request.app.state, "settings", None)
    return int(getattr(settings, "BACKUP_RETENTION_COUNT", 30)) if settings else 30


@router.post("/backup", response_model=BackupResponse)
async def postBackup(
    request: Request,
    file: UploadFile = File(...),
    type: str = Form(...),  # noqa: A002 — matches spec's multipart field name
    deviceId: str = Form(...),
) -> BackupResponse:
    """Accept a Pi backup upload and store it under the configured backup tree."""
    # 1) Request-level validation (order: type → deviceId → extension).
    _validateType(type)
    _validateDeviceId(deviceId)
    ext = _validateExtension(file.filename or "")

    # 2) Size limit — fast reject via Content-Length when provided.
    maxBytes = _resolveMaxBytes(request)
    contentLength = request.headers.get("content-length")
    if contentLength is not None:
        try:
            if int(contentLength) > maxBytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=(
                        f"{_PAYLOAD_TOO_LARGE_DETAIL}: "
                        f"{maxBytes // (1024 * 1024)} MB"
                    ),
                )
        except ValueError:
            # Bad header — fall through to streaming-cap enforcement.
            pass

    # 3) Compute destination and ensure the bucket directory exists.
    backupDir = _resolveBackupDir(request)
    stem = Path(file.filename or "backup").stem
    destination = _buildDestinationPath(
        backupDir=backupDir,
        deviceId=deviceId,
        backupType=type,
        stem=stem,
        ext=ext,
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Could not create backup dir %s: %s", destination.parent, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_STORAGE_FAILURE_DETAIL,
        ) from exc

    # 4) Stream body to disk with running byte cap.
    bytesWritten = await _streamToDisk(file, destination, maxBytes)

    # 5) Rotation — invariant preserves at least one file per bucket.
    retention = _resolveRetention(request)
    rotated = _rotateBackups(destination.parent, retention)

    logger.info(
        "Stored backup for device=%s type=%s bytes=%d rotated=%d path=%s",
        deviceId,
        type,
        bytesWritten,
        rotated,
        destination,
    )

    return BackupResponse(
        status="ok",
        path=str(destination),
        bytes=bytesWritten,
        rotated=rotated,
    )


# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    "ALLOWED_EXTENSIONS",
    "ALLOWED_TYPES",
    "BackupResponse",
    "postBackup",
    "router",
]
