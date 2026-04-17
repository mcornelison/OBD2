################################################################################
# File Name: test_backup.py
# Purpose/Description: Tests for the POST /api/v1/backup multipart backup
#                      receiver endpoint (US-CMP-007). Covers pure-helper
#                      validation (type, deviceId, extension, destination path,
#                      rotation), and route-level behaviour (auth, validation,
#                      success shape, rotation, filesystem errors).
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-CMP-007 — backup receiver
# ================================================================================
################################################################################

"""
Tests for ``src/server/api/backup.py`` — the ``POST /api/v1/backup`` endpoint.

Split into three concerns:

1. **Pure helpers** — type/deviceId/extension validation, destination path
   layout, rotation logic (tested on a tmp directory without routing).
2. **Route behaviour** — auth, 422 on bad type, 422 on bad deviceId, 415 on
   disallowed extension, 413 on oversize, 200 success envelope shape,
   500 on unwritable destination.
3. **End-to-end rotation** — multiple uploads into the same
   (deviceId, type) directory produce exactly ``BACKUP_RETENTION_COUNT``
   survivors with the oldest files gone; the ``rotated`` count in the
   response envelope matches.

All filesystem operations happen inside a pytest-provided ``tmp_path`` so
the repo's ``./data/backups`` tree is never touched.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


# ==============================================================================
# Shared helpers
# ==============================================================================


def _makeSettings(
    apiKey: str = "valid-key",
    backupDir: str | None = None,
    maxSizeMb: int = 100,
    retention: int = 30,
):
    """Build a Settings instance with filesystem-safe defaults for tests."""
    from src.server.config import Settings

    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=apiKey,
        BACKUP_DIR=backupDir or "./data/backups",
        MAX_BACKUP_SIZE_MB=maxSizeMb,
        BACKUP_RETENTION_COUNT=retention,
    )


def _buildApp(
    apiKey: str = "valid-key",
    backupDir: str | None = None,
    maxSizeMb: int = 100,
    retention: int = 30,
):
    """Bare FastAPI app with backup router registered (via createApp)."""
    from src.server.api.app import createApp

    settings = _makeSettings(
        apiKey=apiKey,
        backupDir=backupDir,
        maxSizeMb=maxSizeMb,
        retention=retention,
    )
    app = createApp(settings=settings)
    return app


def _uploadFields(
    fileBytes: bytes,
    filename: str = "backup.db",
    fieldType: str = "database",
    deviceId: str = "chi-eclipse-01",
) -> tuple[dict, dict]:
    """Return ``(files, data)`` kwargs for httpx/TestClient multipart."""
    files = {"file": (filename, io.BytesIO(fileBytes), "application/octet-stream")}
    data = {"type": fieldType, "deviceId": deviceId}
    return files, data


# ==============================================================================
# 1) Pure helpers
# ==============================================================================


class TestValidateType:
    def test_allowedTypes_pass(self):
        from src.server.api.backup import ALLOWED_TYPES

        assert ALLOWED_TYPES == frozenset({"database", "logs", "config"})

    def test_unknownType_raises422(self):
        from fastapi import HTTPException

        from src.server.api.backup import _validateType

        with pytest.raises(HTTPException) as exc:
            _validateType("bogus")
        assert exc.value.status_code == 422


class TestValidateDeviceId:
    def test_alphanumeric_pass(self):
        from src.server.api.backup import _validateDeviceId

        _validateDeviceId("chi-eclipse-01")
        _validateDeviceId("pi_5.home")

    @pytest.mark.parametrize(
        "deviceId",
        ["", "../etc/passwd", "a/b", "a\\b", "a b", "pi$1"],
    )
    def test_pathTraversalOrInvalid_raises422(self, deviceId):
        from fastapi import HTTPException

        from src.server.api.backup import _validateDeviceId

        with pytest.raises(HTTPException) as exc:
            _validateDeviceId(deviceId)
        assert exc.value.status_code == 422


class TestValidateExtension:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("obd.db", ".db"),
            ("obd.DB", ".db"),
            ("service.log", ".log"),
            ("config.json", ".json"),
            ("archive.gz", ".gz"),
            ("archive.tar.gz", ".gz"),
        ],
    )
    def test_allowedExtensions_returnedLowercase(self, filename, expected):
        from src.server.api.backup import _validateExtension

        assert _validateExtension(filename) == expected

    @pytest.mark.parametrize(
        "filename",
        ["obd.sqlite", "notes.txt", "binary.exe", "noextension", "archive.zip"],
    )
    def test_disallowedExtension_raises415(self, filename):
        from fastapi import HTTPException

        from src.server.api.backup import _validateExtension

        with pytest.raises(HTTPException) as exc:
            _validateExtension(filename)
        assert exc.value.status_code == 415


class TestBuildDestinationPath:
    def test_layoutMatchesSpec(self, tmp_path):
        from src.server.api.backup import _buildDestinationPath

        path = _buildDestinationPath(
            backupDir=tmp_path,
            deviceId="chi-eclipse-01",
            backupType="database",
            stem="obd",
            ext=".db",
        )
        # {BACKUP_DIR}/{deviceId}/{type}/{stem}-{ISO timestamp}{ext}
        assert path.parent == tmp_path / "chi-eclipse-01" / "database"
        assert path.name.startswith("obd-")
        assert path.suffix == ".db"

    def test_timestampIsFilesystemSafe(self, tmp_path):
        """Filename must not contain ':' so Windows accepts it."""
        from src.server.api.backup import _buildDestinationPath

        path = _buildDestinationPath(
            backupDir=tmp_path,
            deviceId="dev",
            backupType="logs",
            stem="svc",
            ext=".log",
        )
        assert ":" not in path.name

    def test_pathTraversalInStem_stripped(self, tmp_path):
        """A stem including path separators would escape tree — must be sanitised."""
        from src.server.api.backup import _buildDestinationPath

        # The caller is expected to pass a pre-sanitised stem (route uses
        # Path(filename).stem), but the helper must be defensive too — any
        # separator in the stem is replaced so no traversal is possible.
        path = _buildDestinationPath(
            backupDir=tmp_path,
            deviceId="dev",
            backupType="logs",
            stem="../evil",
            ext=".log",
        )
        # The produced path must remain inside the declared tree.
        assert tmp_path in path.parents


class TestRotateBackups:
    def _makeFiles(self, directory: Path, count: int, prefix: str = "f") -> list[Path]:
        """Create count files with increasing mtime."""
        directory.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for i in range(count):
            p = directory / f"{prefix}-{i}.db"
            p.write_bytes(b"x")
            # Stagger mtimes so sort-by-mtime is deterministic.
            mtime = time.time() - (count - i)
            import os

            os.utime(p, (mtime, mtime))
            paths.append(p)
        return paths

    def test_underLimit_returnsZero(self, tmp_path):
        from src.server.api.backup import _rotateBackups

        self._makeFiles(tmp_path, 3)
        deleted = _rotateBackups(tmp_path, retention=30)
        assert deleted == 0
        assert len(list(tmp_path.iterdir())) == 3

    def test_overLimit_keepsNewestN(self, tmp_path):
        from src.server.api.backup import _rotateBackups

        files = self._makeFiles(tmp_path, 5)
        deleted = _rotateBackups(tmp_path, retention=3)
        assert deleted == 2
        remaining = sorted(tmp_path.iterdir())
        # Oldest two (index 0, 1) should be gone.
        assert files[0] not in remaining
        assert files[1] not in remaining
        assert files[2] in remaining
        assert files[3] in remaining
        assert files[4] in remaining

    def test_retentionZero_keepsAtLeastOne(self, tmp_path):
        """Rotation invariant: never delete the last remaining file."""
        from src.server.api.backup import _rotateBackups

        self._makeFiles(tmp_path, 3)
        # Nonsense retention=0 — must still keep 1 file so the backup tree
        # is never emptied out from under a running system.
        deleted = _rotateBackups(tmp_path, retention=0)
        assert deleted == 2
        assert len(list(tmp_path.iterdir())) == 1

    def test_emptyDirectory_returnsZero(self, tmp_path):
        from src.server.api.backup import _rotateBackups

        assert _rotateBackups(tmp_path, retention=3) == 0


# ==============================================================================
# 2) Route behaviour
# ==============================================================================


class TestBackupAuth:
    def test_missingApiKey_returns401(self, tmp_path):
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path))
        files, data = _uploadFields(b"binary")
        with TestClient(app) as client:
            resp = client.post("/api/v1/backup", files=files, data=data)
        assert resp.status_code == 401

    def test_invalidApiKey_returns401(self, tmp_path):
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path))
        files, data = _uploadFields(b"binary")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/backup",
                files=files,
                data=data,
                headers={"X-API-Key": "wrong"},
            )
        assert resp.status_code == 401


class TestBackupValidation:
    def test_unknownType_returns422(self, tmp_path):
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path))
        files, data = _uploadFields(b"binary", fieldType="bogus")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/backup",
                files=files,
                data=data,
                headers={"X-API-Key": "valid-key"},
            )
        assert resp.status_code == 422

    def test_invalidDeviceId_returns422(self, tmp_path):
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path))
        files, data = _uploadFields(b"binary", deviceId="../etc/passwd")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/backup",
                files=files,
                data=data,
                headers={"X-API-Key": "valid-key"},
            )
        assert resp.status_code == 422

    def test_disallowedExtension_returns415(self, tmp_path):
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path))
        files, data = _uploadFields(b"binary", filename="backup.exe")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/backup",
                files=files,
                data=data,
                headers={"X-API-Key": "valid-key"},
            )
        assert resp.status_code == 415

    def test_oversizeFile_returns413(self, tmp_path):
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path), maxSizeMb=1)
        oversize = b"x" * (2 * 1024 * 1024)  # 2 MB
        files, data = _uploadFields(oversize)
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/backup",
                files=files,
                data=data,
                headers={"X-API-Key": "valid-key"},
            )
        assert resp.status_code == 413


class TestBackupSuccess:
    def test_validUpload_returns200WithEnvelope(self, tmp_path):
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path))
        payload = b"SQLite format 3\x00" + b"x" * 100
        files, data = _uploadFields(payload, filename="obd.db")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/backup",
                files=files,
                data=data,
                headers={"X-API-Key": "valid-key"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "path" in body
        assert body["bytes"] == len(payload)
        assert body["rotated"] == 0

    def test_createsDirectoryTreeAsNeeded(self, tmp_path):
        from fastapi.testclient import TestClient

        subDir = tmp_path / "does" / "not" / "exist"
        app = _buildApp(backupDir=str(subDir))
        files, data = _uploadFields(b"content", filename="obd.db")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/backup",
                files=files,
                data=data,
                headers={"X-API-Key": "valid-key"},
            )
        assert resp.status_code == 200
        # File lives under {backupDir}/{deviceId}/{type}/
        deviceDir = subDir / "chi-eclipse-01" / "database"
        stored = list(deviceDir.glob("*.db"))
        assert len(stored) == 1
        assert stored[0].read_bytes() == b"content"

    def test_resyncSameFilename_doesNotOverwrite(self, tmp_path):
        """Two uploads of the same logical filename must produce two files."""
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path))
        with TestClient(app) as client:
            files1, data1 = _uploadFields(b"first", filename="obd.db")
            r1 = client.post(
                "/api/v1/backup",
                files=files1,
                data=data1,
                headers={"X-API-Key": "valid-key"},
            )
            # Small sleep to ensure distinct microsecond timestamps.
            time.sleep(0.002)
            files2, data2 = _uploadFields(b"second", filename="obd.db")
            r2 = client.post(
                "/api/v1/backup",
                files=files2,
                data=data2,
                headers={"X-API-Key": "valid-key"},
            )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["path"] != r2.json()["path"]
        storedDir = tmp_path / "chi-eclipse-01" / "database"
        assert len(list(storedDir.glob("*.db"))) == 2


class TestBackupRotation:
    def test_uploadsBeyondRetention_rotateOldest(self, tmp_path):
        """Upload N+3 files with retention=N; survivors are N, rotated counts correct."""
        from fastapi.testclient import TestClient

        app = _buildApp(backupDir=str(tmp_path), retention=3)
        totalUploads = 6
        responses = []
        with TestClient(app) as client:
            for i in range(totalUploads):
                files, data = _uploadFields(
                    f"payload-{i}".encode(),
                    filename=f"obd-{i}.db",
                )
                resp = client.post(
                    "/api/v1/backup",
                    files=files,
                    data=data,
                    headers={"X-API-Key": "valid-key"},
                )
                assert resp.status_code == 200
                responses.append(resp.json())
                # Ensure distinct mtimes so rotation order is deterministic.
                time.sleep(0.002)

        # Survivors match retention.
        storedDir = tmp_path / "chi-eclipse-01" / "database"
        survivors = list(storedDir.glob("*.db"))
        assert len(survivors) == 3
        # Final response must show ``rotated == 1`` — each upload rotates at
        # most one old file once we exceed the cap.
        assert responses[-1]["rotated"] == 1
        # Upload #1 (pre-cap) rotated nothing.
        assert responses[0]["rotated"] == 0
        # Upload #4 is the first to exceed the cap → rotated 1.
        assert responses[3]["rotated"] == 1


class TestBackupUnwritableDestination:
    def test_unwritableBackupDir_returns500(self, tmp_path, monkeypatch):
        """A raised OSError during write → clean 500 (no crash, no partial path leak)."""
        from fastapi.testclient import TestClient

        from src.server.api import backup as backupModule

        app = _buildApp(backupDir=str(tmp_path))

        # Simulate a filesystem that refuses writes.
        def _failingOpen(*_args, **_kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr(backupModule.Path, "open", _failingOpen)

        files, data = _uploadFields(b"payload", filename="obd.db")
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/backup",
                files=files,
                data=data,
                headers={"X-API-Key": "valid-key"},
            )
        assert resp.status_code == 500
