################################################################################
# File Name: test_client_config_paths.py
# Purpose/Description: Regression tests for SyncClient construction against the
#                      current tier-aware config.json shape (US-226).  Catches
#                      the class of bug that stranded Drive 3: if a config-key
#                      rename quietly broke SyncClient instantiation, these
#                      tests would fail at construction time rather than at
#                      push time days later.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Config-key regression tests for :class:`SyncClient`.

The sync pipeline stranded Drive 3 in Sprint 17 because nothing verified
that the validator-produced config shape matched what SyncClient read.
This test suite constructs a SyncClient from:

1. A real :class:`ConfigValidator` walk of a fresh Pi-shaped config.
2. The project's shipped ``config.json`` (loaded + validated) -- the
   single source of truth for the production surface.
3. Minimal-sufficient handmade configs (enabled / disabled) -- fast
   unit tests for the construction guards.

A change that drops ``pi.companionService.*`` or ``pi.database.path``
from the validator's default surface now surfaces loudly in CI.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from src.common.config.validator import ConfigValidator
from src.common.errors.handler import ConfigurationError
from src.pi.sync.client import SyncClient

# ================================================================================
# Helpers
# ================================================================================


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _stubApiKey(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-config-paths")
    return "test-key-config-paths"


def _stubDeviceId(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVICE_ID", "chi-eclipse-01")


def _stubObdBtMac(monkeypatch: pytest.MonkeyPatch) -> None:
    # Required by config.json because the pi.bluetooth.macAddress value
    # uses ``${OBD_BT_MAC}``; the secrets loader expands at load time.
    monkeypatch.setenv("OBD_BT_MAC", "00:04:3E:85:0D:FB")


def _validatedMinimalConfig(dbPath: str, *, enabled: bool = True) -> dict[str, Any]:
    """Build a minimal-valid Pi config + run it through the real validator."""
    raw = {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "companionService": {"enabled": enabled},
            "sync": {"enabled": enabled},
        },
        "server": {},
    }
    return ConfigValidator().validate(raw)


@pytest.fixture
def tempDbPath() -> Generator[str, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


# ================================================================================
# 1. Validator-produced config constructs SyncClient cleanly
# ================================================================================


class TestValidatorShapeCompatibility:
    def test_validatorOutput_constructsSyncClient(
        self, tempDbPath, monkeypatch
    ) -> None:
        """Given a fresh validator walk, SyncClient construction succeeds."""
        _stubApiKey(monkeypatch)
        config = _validatedMinimalConfig(tempDbPath, enabled=True)

        client = SyncClient(config)

        assert client.isEnabled is True
        assert client.baseUrl == "http://10.27.27.10:8000"
        assert client.deviceId == "chi-eclipse-01"
        assert client.dbPath == tempDbPath

    def test_validatorOutput_whenDisabled_noApiKeyNeeded(
        self, tempDbPath, monkeypatch
    ) -> None:
        """Construction succeeds with enabled=false even without the API key env var."""
        monkeypatch.delenv("COMPANION_API_KEY", raising=False)
        config = _validatedMinimalConfig(tempDbPath, enabled=False)

        client = SyncClient(config)

        assert client.isEnabled is False
        # Disabled-path construction must not have resolved the key.
        assert client.dbPath == tempDbPath

    def test_missingDbPath_raisesConfigurationError(self, monkeypatch) -> None:
        """pi.database.path is load-bearing: absence must fail loudly."""
        _stubApiKey(monkeypatch)
        raw = {
            "protocolVersion": "1.0.0",
            "schemaVersion": "1.0.0",
            "deviceId": "chi-eclipse-01",
            "pi": {
                "companionService": {"enabled": True},
                "sync": {"enabled": True},
            },
            "server": {},
        }
        config = ConfigValidator().validate(raw)
        # Remove the default-applied path to simulate the corruption.
        config["pi"].pop("database", None)

        with pytest.raises(ConfigurationError) as excinfo:
            SyncClient(config)

        assert "pi.database.path" in str(excinfo.value)

    def test_missingApiKeyEnv_raisesConfigurationError(
        self, tempDbPath, monkeypatch
    ) -> None:
        """An enabled client with the API key env unset must fail construction."""
        monkeypatch.delenv("COMPANION_API_KEY", raising=False)
        config = _validatedMinimalConfig(tempDbPath, enabled=True)

        with pytest.raises(ConfigurationError) as excinfo:
            SyncClient(config)

        assert "COMPANION_API_KEY" in str(excinfo.value)


# ================================================================================
# 2. Shipped config.json constructs SyncClient cleanly
# ================================================================================


class TestShippedConfigCompatibility:
    """Proves the repo's ``config.json`` still constructs a live client.

    This is the test that would have fired loudly the moment someone
    renamed or removed ``pi.companionService`` or ``pi.database.path``.
    """

    def test_shippedConfig_constructsSyncClient(self, monkeypatch) -> None:
        configPath = _PROJECT_ROOT / "config.json"
        if not configPath.exists():  # pragma: no cover -- repo integrity guard
            pytest.skip(f"config.json missing at {configPath}")

        _stubApiKey(monkeypatch)
        _stubDeviceId(monkeypatch)
        _stubObdBtMac(monkeypatch)

        with configPath.open() as fh:
            raw = json.load(fh)

        # Expand ${ENV_VAR[:default]} placeholders the same way the secrets
        # loader does in production.  Uses the public resolveSecrets API
        # so this test doubles as a smoke test for that flow.
        from src.common.config.secrets_loader import resolveSecrets

        expanded = resolveSecrets(raw)
        config = ConfigValidator().validate(expanded)

        client = SyncClient(config)

        assert client.dbPath
        # The shipped config has companionService enabled by default; the
        # env key is set via the monkeypatched COMPANION_API_KEY above.
        assert client.isEnabled is True
        assert client.baseUrl.endswith(":8000")

    def test_shippedConfig_hasPiSyncSection(self) -> None:
        """pi.sync section must exist in the shipped config (US-226)."""
        configPath = _PROJECT_ROOT / "config.json"
        with configPath.open() as fh:
            raw = json.load(fh)

        piSync = raw.get("pi", {}).get("sync")
        assert piSync is not None, "pi.sync section missing from config.json"
        assert piSync.get("enabled") is True
        assert isinstance(piSync.get("intervalSeconds"), int)
        assert piSync["intervalSeconds"] > 0
        assert "interval" in piSync.get("triggerOn", [])
