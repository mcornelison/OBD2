################################################################################
# File Name: test_deploy_invariants.py
# Purpose/Description: Unit tests for scripts/deploy_invariants.py -- the
#                      US-389 single-instance matched-pair deploy invariant
#                      (Atlas C-5). The guard config flag
#                      (pi.runtime.singleInstanceGuard.enabled) and the systemd
#                      RuntimeDirectory=eclipse-obd are a MATCHED PAIR: neither
#                      may ship without the other, or the non-root orchestrator
#                      crash-loops on boot (EPERM on mkdir(/run/eclipse-obd)).
#                      These tests prove the invariant FAILS LOUDLY when either
#                      half is missing -- the "test fails the deploy" half of
#                      US-389 AC#1, runnable on the dev box with no Pi.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-28    | Rex (US-389) | Initial -- matched-pair invariant + summary
#               |              | helper; CLI check-pair / summarize exit codes.
# ================================================================================
################################################################################

"""Tests for the US-389 single-instance matched-pair deploy invariant.

The deploy gate (deploy-pi.sh step_assert_single_instance_matched_pair) shells
out to scripts/deploy_invariants.py so the assertion logic lives in one
testable Python module rather than a bash heredoc. These tests exercise the
helpers directly AND drive the CLI subcommands the deploy script calls.
"""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INVARIANTS_PATH = REPO_ROOT / "scripts" / "deploy_invariants.py"
REAL_CONFIG = REPO_ROOT / "config.json"
REAL_UNIT = REPO_ROOT / "deploy" / "eclipse-obd.service"


def _loadModule():
    """Import scripts/deploy_invariants.py without polluting sys.path globally."""
    spec = spec_from_file_location("deploy_invariants", INVARIANTS_PATH)
    assert spec and spec.loader, f"cannot import {INVARIANTS_PATH}"
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _writeConfig(tmp: Path, guardEnabled) -> Path:
    """Write a minimal config.json with the given guard-enabled value.

    Passing ``None`` for guardEnabled omits the singleInstanceGuard block
    entirely (simulates a config that never enabled the guard).
    """
    runtime: dict = {}
    if guardEnabled is not None:
        runtime["singleInstanceGuard"] = {
            "enabled": guardEnabled,
            "lockPath": "/run/eclipse-obd/orchestrator.lock",
        }
    config = {"pi": {"runtime": runtime}}
    path = tmp / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _writeUnit(tmp: Path, runtimeDirectory: str | None) -> Path:
    """Write a minimal eclipse-obd.service unit.

    ``runtimeDirectory=None`` omits the RuntimeDirectory= line (simulates the
    half of the pair that crash-loops the non-root service).
    """
    lines = ["[Service]", "Type=simple", "User=mcornelison"]
    if runtimeDirectory is not None:
        lines.insert(1, f"RuntimeDirectory={runtimeDirectory}")
    path = tmp / "eclipse-obd.service"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---- readGuardEnabled / readUnitRuntimeDirectory --------------------------


class TestReaders:
    def test_readGuardEnabled_true_whenConfigEnablesGuard(self, tmp_path):
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=True)
        assert mod.readGuardEnabled(cfg) is True

    def test_readGuardEnabled_false_whenConfigDisablesGuard(self, tmp_path):
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=False)
        assert mod.readGuardEnabled(cfg) is False

    def test_readGuardEnabled_none_whenBlockAbsent(self, tmp_path):
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=None)
        assert mod.readGuardEnabled(cfg) is None

    def test_readUnitRuntimeDirectory_returnsValue(self, tmp_path):
        mod = _loadModule()
        unit = _writeUnit(tmp_path, runtimeDirectory="eclipse-obd")
        assert mod.readUnitRuntimeDirectory(unit) == "eclipse-obd"

    def test_readUnitRuntimeDirectory_none_whenAbsent(self, tmp_path):
        mod = _loadModule()
        unit = _writeUnit(tmp_path, runtimeDirectory=None)
        assert mod.readUnitRuntimeDirectory(unit) is None

    def test_readUnitRuntimeDirectory_ignoresCommentedLine(self, tmp_path):
        mod = _loadModule()
        path = tmp_path / "eclipse-obd.service"
        path.write_text(
            "[Service]\n# RuntimeDirectory=eclipse-obd (doc note)\nType=simple\n",
            encoding="utf-8",
        )
        assert mod.readUnitRuntimeDirectory(path) is None


# ---- summarizeSingleInstanceState -----------------------------------------


class TestSummarize:
    def test_summarize_bothPresent(self, tmp_path):
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=True)
        unit = _writeUnit(tmp_path, runtimeDirectory="eclipse-obd")
        summary = mod.summarizeSingleInstanceState(cfg, unit)
        assert summary == {"guardEnabled": True, "runtimeDirectory": "eclipse-obd"}

    def test_summarize_realRepoArtifacts_areMatchedPair(self):
        """The actual config.json + eclipse-obd.service ship the matched pair.

        This is the AC#4 / VC#3 evidence: the V0.29.1 deploy stamp records
        guardEnabled=true + runtimeDirectory=eclipse-obd, no longer silent.
        """
        mod = _loadModule()
        summary = mod.summarizeSingleInstanceState(REAL_CONFIG, REAL_UNIT)
        assert summary["guardEnabled"] is True
        assert summary["runtimeDirectory"] == "eclipse-obd"


# ---- assertMatchedPair (the invariant) ------------------------------------


class TestAssertMatchedPair:
    def test_passes_whenBothPresent(self, tmp_path):
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=True)
        unit = _writeUnit(tmp_path, runtimeDirectory="eclipse-obd")
        # Must not raise.
        mod.assertMatchedPair(cfg, unit)

    def test_passes_onRealRepoArtifacts(self):
        mod = _loadModule()
        mod.assertMatchedPair(REAL_CONFIG, REAL_UNIT)

    def test_raises_whenRuntimeDirectoryMissing(self, tmp_path):
        """VC#1: RuntimeDirectory removed from the unit -> invariant FAILS."""
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=True)
        unit = _writeUnit(tmp_path, runtimeDirectory=None)
        with pytest.raises(mod.MatchedPairViolation) as exc:
            mod.assertMatchedPair(cfg, unit)
        assert "RuntimeDirectory" in str(exc.value)

    def test_raises_whenGuardFlagFalse(self, tmp_path):
        """VC#2: guard flag false -> invariant FAILS (non-root crash-loop risk)."""
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=False)
        unit = _writeUnit(tmp_path, runtimeDirectory="eclipse-obd")
        with pytest.raises(mod.MatchedPairViolation) as exc:
            mod.assertMatchedPair(cfg, unit)
        assert "singleInstanceGuard" in str(exc.value) or "guard" in str(exc.value)

    def test_raises_whenGuardBlockAbsent(self, tmp_path):
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=None)
        unit = _writeUnit(tmp_path, runtimeDirectory="eclipse-obd")
        with pytest.raises(mod.MatchedPairViolation):
            mod.assertMatchedPair(cfg, unit)

    def test_raises_whenWrongRuntimeDirectoryName(self, tmp_path):
        mod = _loadModule()
        cfg = _writeConfig(tmp_path, guardEnabled=True)
        unit = _writeUnit(tmp_path, runtimeDirectory="something-else")
        with pytest.raises(mod.MatchedPairViolation):
            mod.assertMatchedPair(cfg, unit)


# ---- CLI: check-pair / summarize ------------------------------------------


def _runCli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INVARIANTS_PATH), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestCli:
    def test_checkPair_exit0_whenMatched(self, tmp_path):
        cfg = _writeConfig(tmp_path, guardEnabled=True)
        unit = _writeUnit(tmp_path, runtimeDirectory="eclipse-obd")
        result = _runCli("check-pair", "--config", str(cfg), "--unit", str(unit))
        assert result.returncode == 0, result.stderr

    def test_checkPair_nonZero_whenRuntimeDirectoryMissing(self, tmp_path):
        cfg = _writeConfig(tmp_path, guardEnabled=True)
        unit = _writeUnit(tmp_path, runtimeDirectory=None)
        result = _runCli("check-pair", "--config", str(cfg), "--unit", str(unit))
        assert result.returncode != 0
        assert "RuntimeDirectory" in result.stderr

    def test_checkPair_nonZero_whenGuardFalse(self, tmp_path):
        cfg = _writeConfig(tmp_path, guardEnabled=False)
        unit = _writeUnit(tmp_path, runtimeDirectory="eclipse-obd")
        result = _runCli("check-pair", "--config", str(cfg), "--unit", str(unit))
        assert result.returncode != 0
        assert "guard" in result.stderr.lower()

    def test_checkPair_realRepoArtifacts_exit0(self):
        result = _runCli(
            "check-pair", "--config", str(REAL_CONFIG), "--unit", str(REAL_UNIT)
        )
        assert result.returncode == 0, result.stderr

    def test_summarize_emitsJson(self, tmp_path):
        cfg = _writeConfig(tmp_path, guardEnabled=True)
        unit = _writeUnit(tmp_path, runtimeDirectory="eclipse-obd")
        result = _runCli("summarize", "--config", str(cfg), "--unit", str(unit))
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload == {"guardEnabled": True, "runtimeDirectory": "eclipse-obd"}
