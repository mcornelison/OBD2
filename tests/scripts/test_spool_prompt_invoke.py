################################################################################
# File Name: test_spool_prompt_invoke.py
# Purpose/Description: Unit tests for scripts/spool_prompt_invoke.py (US-219).
#                      Covers config loading with env-var expansion, drive
#                      resolution, rendered-prompt structure, dry-run, and
#                      graceful handling of missing tables / Ollama offline.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex          | Initial implementation for US-219 (Sprint 16)
# ================================================================================
################################################################################

"""Tests for :mod:`scripts.spool_prompt_invoke`.

Runs purely in-process against SQLite.  Never contacts a real Ollama host --
the ``callOllamaChat`` symbol is monkey-patched per test to either return a
scripted response or raise the vocabulary of transport exceptions the
script handles gracefully.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import spool_prompt_invoke  # noqa: E402
from src.server.ai.analyzer_ollama import (  # noqa: E402
    OllamaHttpError,
    OllamaUnreachableError,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveSummary,
    RealtimeData,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def emptyDbUrl(tmp_path: Path) -> str:
    """Empty SQLite DB with schema applied -- no rows."""
    dbPath = tmp_path / "empty.db"
    url = f"sqlite:///{dbPath.as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture
def populatedDbUrl(tmp_path: Path) -> str:
    """SQLite DB with one drive + enough realtime_data rows to build a context."""
    dbPath = tmp_path / "populated.db"
    url = f"sqlite:///{dbPath.as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    driveStart = datetime(2026, 4, 21, 10, 0, 0)
    driveEnd = driveStart + timedelta(minutes=5)

    with Session(engine) as session:
        drive = DriveSummary(
            device_id="chi-eclipse-01",
            start_time=driveStart,
            end_time=driveEnd,
            duration_seconds=300,
            row_count=20,
            drive_id=1,
            source_device="chi-eclipse-01",
            source_id=1,
            data_source="real",
            is_real=True,
        )
        session.add(drive)
        session.flush()

        # Minimum rows for computeDriveStatistics to emit something non-empty.
        # Two parameters, ten samples each.
        nextId = 1
        for i in range(10):
            ts = driveStart + timedelta(seconds=i * 5)
            for name, value in (("RPM", 800.0 + i), ("COOLANT_TEMP", 80.0 + i * 0.1)):
                session.add(
                    RealtimeData(
                        source_id=nextId,
                        source_device="chi-eclipse-01",
                        timestamp=ts,
                        parameter_name=name,
                        value=value,
                        data_source="real",
                        drive_id=1,
                    ),
                )
                nextId += 1
        session.commit()
    engine.dispose()
    return url


@pytest.fixture
def ollamaConfigFile(tmp_path: Path) -> Path:
    """Minimal config.json exposing the server.ai block."""
    cfg = {
        "server": {
            "ai": {
                "enabled": True,
                "model": "${TEST_AI_MODEL:llama3.1:8b}",
                "ollamaBaseUrl": "${TEST_OLLAMA_URL:http://localhost:11434}",
                "apiTimeoutSeconds": 45,
            },
        },
    }
    cfgPath = tmp_path / "config.json"
    cfgPath.write_text(json.dumps(cfg), encoding="utf-8")
    return cfgPath


# ==============================================================================
# Placeholder expansion
# ==============================================================================


class TestExpandPlaceholders:
    """``${VAR:default}`` matches the secrets-loader semantics."""

    def test_defaultUsed_whenEnvVarAbsent(self, monkeypatch):
        monkeypatch.delenv("NO_SUCH_VAR_919", raising=False)
        result = spool_prompt_invoke._expandPlaceholders(
            "${NO_SUCH_VAR_919:fallback-value}"
        )
        assert result == "fallback-value"

    def test_envVarUsed_whenPresent(self, monkeypatch):
        monkeypatch.setenv("US219_OVERRIDE", "env-wins")
        result = spool_prompt_invoke._expandPlaceholders(
            "${US219_OVERRIDE:fallback}"
        )
        assert result == "env-wins"

    def test_emptyDefault_whenNoEnvAndNoDefault(self, monkeypatch):
        monkeypatch.delenv("NO_SUCH_VAR_920", raising=False)
        result = spool_prompt_invoke._expandPlaceholders(
            "prefix-${NO_SUCH_VAR_920}-suffix"
        )
        assert result == "prefix--suffix"

    def test_literalString_passesThrough(self):
        assert spool_prompt_invoke._expandPlaceholders("plain") == "plain"


# ==============================================================================
# loadOllamaConfig
# ==============================================================================


class TestLoadOllamaConfig:
    def test_readsBaseUrlModelAndTimeout(self, ollamaConfigFile, monkeypatch):
        monkeypatch.delenv("TEST_AI_MODEL", raising=False)
        monkeypatch.delenv("TEST_OLLAMA_URL", raising=False)
        baseUrl, model, timeout = spool_prompt_invoke.loadOllamaConfig(
            ollamaConfigFile,
        )
        assert baseUrl == "http://localhost:11434"
        assert model == "llama3.1:8b"
        assert timeout == 45

    def test_envVarOverride_appliesToBothFields(self, ollamaConfigFile, monkeypatch):
        monkeypatch.setenv("TEST_AI_MODEL", "gemma2:2b")
        monkeypatch.setenv("TEST_OLLAMA_URL", "http://10.27.27.10:11434")
        baseUrl, model, _ = spool_prompt_invoke.loadOllamaConfig(
            ollamaConfigFile,
        )
        assert baseUrl == "http://10.27.27.10:11434"
        assert model == "gemma2:2b"

    def test_missingAiBlock_raisesKeyError(self, tmp_path):
        cfgPath = tmp_path / "bad.json"
        cfgPath.write_text(json.dumps({"server": {}}), encoding="utf-8")
        with pytest.raises(KeyError):
            spool_prompt_invoke.loadOllamaConfig(cfgPath)


# ==============================================================================
# resolveDriveId
# ==============================================================================


class TestResolveDriveId:
    def test_latest_emptyDb_returnsNone(self, emptyDbUrl):
        engine = create_engine(emptyDbUrl)
        with Session(engine) as session:
            assert spool_prompt_invoke.resolveDriveId(session, "latest") is None
        engine.dispose()

    def test_latest_populatedDb_returnsMostRecent(self, populatedDbUrl):
        engine = create_engine(populatedDbUrl)
        with Session(engine) as session:
            driveId = spool_prompt_invoke.resolveDriveId(session, "latest")
            assert driveId is not None
            drive = session.get(DriveSummary, driveId)
            assert drive.device_id == "chi-eclipse-01"
        engine.dispose()

    def test_integerString_existing_returnsId(self, populatedDbUrl):
        engine = create_engine(populatedDbUrl)
        with Session(engine) as session:
            latest = spool_prompt_invoke.resolveDriveId(session, "latest")
            resolved = spool_prompt_invoke.resolveDriveId(session, str(latest))
            assert resolved == latest
        engine.dispose()

    def test_integerString_missing_returnsNone(self, populatedDbUrl):
        engine = create_engine(populatedDbUrl)
        with Session(engine) as session:
            assert spool_prompt_invoke.resolveDriveId(session, "99999") is None
        engine.dispose()

    def test_nonIntegerRef_returnsNone(self, populatedDbUrl):
        engine = create_engine(populatedDbUrl)
        with Session(engine) as session:
            assert spool_prompt_invoke.resolveDriveId(
                session, "2026-04-21",
            ) is None
        engine.dispose()


# ==============================================================================
# runReview -- end-to-end
# ==============================================================================


def _args(**overrides):
    """Build an argparse-like Namespace with the fields runReview uses."""
    import argparse
    return argparse.Namespace(
        driveId=overrides.pop("driveId", "latest"),
        dbUrl=overrides.pop("dbUrl", None),
        dryRun=overrides.pop("dryRun", False),
    )


class TestRunReviewDryRun:
    """``--dry-run`` renders the prompt but must not call Ollama."""

    def test_dryRun_printsRenderedUserMessage_exitsZero(
        self, populatedDbUrl, monkeypatch, capsys, ollamaConfigFile,
    ):
        # Point the loader at our fixture config.
        monkeypatch.setattr(spool_prompt_invoke, "_CONFIG_PATH", ollamaConfigFile)

        # Fail loud if Ollama is contacted during a dry run.
        def _boom(**kwargs):
            pytest.fail("callOllamaChat must not be called on --dry-run")

        monkeypatch.setattr(spool_prompt_invoke, "callOllamaChat", _boom)

        rc = spool_prompt_invoke.runReview(
            _args(driveId="latest", dbUrl=populatedDbUrl, dryRun=True),
        )
        assert rc == 0

        out = capsys.readouterr().out
        assert "Spool prompt" in out
        assert "Rendered user message (what Ollama sees)" in out
        assert "Dry run" in out
        # Structured tables from user_message.jinja appear for RPM + COOLANT_TEMP.
        assert "Drive ID:" in out
        assert "RPM" in out


class TestRunReviewLiveCall:
    """Scripted Ollama response path -- raw + parsed sections emit."""

    def test_validJsonArrayResponse_parsedRecsPrinted(
        self, populatedDbUrl, monkeypatch, capsys, ollamaConfigFile,
    ):
        monkeypatch.setattr(spool_prompt_invoke, "_CONFIG_PATH", ollamaConfigFile)

        scriptedResponse = json.dumps([
            {
                "rank": 1,
                "category": "Cooling",
                "recommendation": "Monitor coolant trend across the next 5 drives.",
                "confidence": 0.72,
            },
        ])

        def _fakeCall(**kwargs):
            return scriptedResponse

        monkeypatch.setattr(spool_prompt_invoke, "callOllamaChat", _fakeCall)

        rc = spool_prompt_invoke.runReview(
            _args(driveId="latest", dbUrl=populatedDbUrl, dryRun=False),
        )
        assert rc == 0

        out = capsys.readouterr().out
        assert "Raw Ollama response" in out
        assert "Parsed recommendations (1)" in out
        assert "Monitor coolant trend" in out
        assert "Cooling" in out

    def test_emptyJsonArray_parsedAsZeroRecs(
        self, populatedDbUrl, monkeypatch, capsys, ollamaConfigFile,
    ):
        monkeypatch.setattr(spool_prompt_invoke, "_CONFIG_PATH", ollamaConfigFile)

        monkeypatch.setattr(
            spool_prompt_invoke, "callOllamaChat", lambda **_k: "[]",
        )
        rc = spool_prompt_invoke.runReview(
            _args(driveId="latest", dbUrl=populatedDbUrl, dryRun=False),
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Parsed recommendations (0)" in out


class TestRunReviewGraceful:
    """Empty DB / Ollama errors / missing tables all exit 0."""

    def test_emptyDb_printsNoDriveAndExitsZero(
        self, emptyDbUrl, monkeypatch, capsys, ollamaConfigFile,
    ):
        monkeypatch.setattr(spool_prompt_invoke, "_CONFIG_PATH", ollamaConfigFile)
        rc = spool_prompt_invoke.runReview(
            _args(driveId="latest", dbUrl=emptyDbUrl),
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "No drive found" in out

    def test_missingTables_printsGracefulNotice(
        self, tmp_path, monkeypatch, capsys, ollamaConfigFile,
    ):
        monkeypatch.setattr(spool_prompt_invoke, "_CONFIG_PATH", ollamaConfigFile)
        # Empty file -> SQLite file with no schema at all.
        bareDb = tmp_path / "bare.db"
        bareDb.touch()
        rc = spool_prompt_invoke.runReview(
            _args(
                driveId="latest",
                dbUrl=f"sqlite:///{bareDb.as_posix()}",
            ),
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "missing expected tables" in out

    def test_ollamaUnreachable_nonFatal(
        self, populatedDbUrl, monkeypatch, capsys, ollamaConfigFile,
    ):
        monkeypatch.setattr(spool_prompt_invoke, "_CONFIG_PATH", ollamaConfigFile)

        def _raiseUnreachable(**kwargs):
            raise OllamaUnreachableError("Connection refused")

        monkeypatch.setattr(
            spool_prompt_invoke, "callOllamaChat", _raiseUnreachable,
        )
        rc = spool_prompt_invoke.runReview(
            _args(driveId="latest", dbUrl=populatedDbUrl, dryRun=False),
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Ollama unreachable" in out
        assert "still succeeded" in out

    def test_ollamaHttpError_nonFatal(
        self, populatedDbUrl, monkeypatch, capsys, ollamaConfigFile,
    ):
        monkeypatch.setattr(spool_prompt_invoke, "_CONFIG_PATH", ollamaConfigFile)

        def _raiseHttp(**kwargs):
            raise OllamaHttpError("server exploded", code=503)

        monkeypatch.setattr(spool_prompt_invoke, "callOllamaChat", _raiseHttp)
        rc = spool_prompt_invoke.runReview(
            _args(driveId="latest", dbUrl=populatedDbUrl, dryRun=False),
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Ollama HTTP error" in out
        assert "HTTP 503" in out

    def test_missingOllamaConfig_nonFatal(
        self, populatedDbUrl, tmp_path, monkeypatch, capsys,
    ):
        # Config file present but missing the server.ai block.
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"server": {}}), encoding="utf-8")
        monkeypatch.setattr(spool_prompt_invoke, "_CONFIG_PATH", bad)

        rc = spool_prompt_invoke.runReview(
            _args(driveId="latest", dbUrl=populatedDbUrl, dryRun=False),
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Ollama config missing" in out


# ==============================================================================
# parseArguments
# ==============================================================================


class TestParseArguments:
    def test_driveIdRequired(self):
        with pytest.raises(SystemExit):
            spool_prompt_invoke.parseArguments([])

    def test_driveIdLatest_accepted(self):
        args = spool_prompt_invoke.parseArguments(["--drive-id", "latest"])
        assert args.driveId == "latest"
        assert args.dryRun is False

    def test_dryRunFlag(self):
        args = spool_prompt_invoke.parseArguments(
            ["--drive-id", "5", "--dry-run"],
        )
        assert args.driveId == "5"
        assert args.dryRun is True

    def test_dbUrlOverride(self):
        args = spool_prompt_invoke.parseArguments(
            ["--drive-id", "5", "--db-url", "sqlite:///x.db"],
        )
        assert args.dbUrl == "sqlite:///x.db"
