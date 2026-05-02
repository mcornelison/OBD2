################################################################################
# File Name: test_release_reader.py
# Purpose/Description: Tests for src/server/services/release_reader.py
#                      (B-047 US-B / US-246). Covers readCurrent (delegates to
#                      version_helpers.readDeployVersion), readHistory (JSONL
#                      parse + maxEntries truncation + invalid-line skip), and
#                      fromSettings factory + fallback defaults.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial TDD tests for US-246 (Sprint 20)
# ================================================================================
################################################################################

"""Unit tests for ``ReleaseReader`` (B-047 US-B / US-246).

Tests use ``tmp_path`` to write tier-realistic .deploy-version + history files
and assert the reader's current/history/fromSettings behaviour. No fastapi
dependency -- this is a pure Python service module.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.server.services.release_reader import (
    DEFAULT_CURRENT_PATH,
    DEFAULT_HISTORY_MAX_ENTRIES,
    DEFAULT_HISTORY_PATH,
    ReleaseReader,
)

# ---- Helpers -----------------------------------------------------------------


def _validRecord(version: str = "V0.19.0", description: str = "Sprint 19 close") -> dict:
    """Return a record matching the US-241 schema (parses + validates clean)."""
    return {
        "version": version,
        "releasedAt": "2026-04-29T14:32:00Z",
        "gitHash": "5025508",
        "theme": "test sprint",
        "description": description,
    }


def _writeJson(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _writeJsonl(path: Path, payloads: list[object]) -> None:
    lines = [json.dumps(p) if not isinstance(p, str) else p for p in payloads]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- readCurrent -------------------------------------------------------------


class TestReadCurrent:
    """ReleaseReader.readCurrent delegates to version_helpers.readDeployVersion."""

    def test_missingFile_returnsNone(self, tmp_path: Path) -> None:
        reader = ReleaseReader(
            currentPath=tmp_path / "missing.json",
            historyPath=tmp_path / "history.jsonl",
        )
        assert reader.readCurrent() is None

    def test_validFile_returnsRecord(self, tmp_path: Path) -> None:
        currentPath = tmp_path / ".deploy-version"
        record = _validRecord()
        _writeJson(currentPath, record)
        reader = ReleaseReader(
            currentPath=currentPath,
            historyPath=tmp_path / "history.jsonl",
        )
        result = reader.readCurrent()
        assert result == record

    def test_malformedJson_returnsNone(self, tmp_path: Path) -> None:
        currentPath = tmp_path / ".deploy-version"
        currentPath.write_text("{not valid json", encoding="utf-8")
        reader = ReleaseReader(
            currentPath=currentPath,
            historyPath=tmp_path / "history.jsonl",
        )
        assert reader.readCurrent() is None

    def test_invalidSchema_returnsNone(self, tmp_path: Path) -> None:
        """Missing 'description' fails validateRelease -> None."""
        currentPath = tmp_path / ".deploy-version"
        bad = {"version": "V0.19.0", "releasedAt": "2026-04-29T14:32:00Z", "gitHash": "abc"}
        _writeJson(currentPath, bad)
        reader = ReleaseReader(
            currentPath=currentPath,
            historyPath=tmp_path / "history.jsonl",
        )
        assert reader.readCurrent() is None


# ---- readHistory -------------------------------------------------------------


class TestReadHistory:
    """ReleaseReader.readHistory parses JSONL + truncates to last N."""

    def test_missingFile_returnsEmptyList(self, tmp_path: Path) -> None:
        reader = ReleaseReader(
            currentPath=tmp_path / "current.json",
            historyPath=tmp_path / "missing-history.jsonl",
        )
        assert reader.readHistory() == []

    def test_emptyFile_returnsEmptyList(self, tmp_path: Path) -> None:
        historyPath = tmp_path / "history.jsonl"
        historyPath.write_text("", encoding="utf-8")
        reader = ReleaseReader(
            currentPath=tmp_path / "current.json",
            historyPath=historyPath,
        )
        assert reader.readHistory() == []

    def test_validJsonl_returnsAllRecordsInOrder(self, tmp_path: Path) -> None:
        historyPath = tmp_path / "history.jsonl"
        records = [
            _validRecord("V0.16.0", "Sprint 16"),
            _validRecord("V0.17.0", "Sprint 17"),
            _validRecord("V0.18.0", "Sprint 18"),
        ]
        _writeJsonl(historyPath, records)
        reader = ReleaseReader(
            currentPath=tmp_path / "current.json",
            historyPath=historyPath,
        )
        result = reader.readHistory()
        assert result == records

    def test_returnsLastNWhenLimitSmallerThanFile(self, tmp_path: Path) -> None:
        historyPath = tmp_path / "history.jsonl"
        records = [_validRecord(f"V0.{i}.0", f"Sprint {i}") for i in range(10, 20)]
        _writeJsonl(historyPath, records)
        reader = ReleaseReader(
            currentPath=tmp_path / "current.json",
            historyPath=historyPath,
            historyMaxEntries=3,
        )
        result = reader.readHistory()
        assert len(result) == 3
        assert result == records[-3:]

    def test_explicitMaxEntriesArgOverridesDefault(self, tmp_path: Path) -> None:
        historyPath = tmp_path / "history.jsonl"
        records = [_validRecord(f"V0.{i}.0", f"Sprint {i}") for i in range(10, 20)]
        _writeJsonl(historyPath, records)
        reader = ReleaseReader(
            currentPath=tmp_path / "current.json",
            historyPath=historyPath,
            historyMaxEntries=10,
        )
        assert len(reader.readHistory(maxEntries=2)) == 2

    def test_zeroOrNegativeMaxEntries_returnsEmptyList(self, tmp_path: Path) -> None:
        historyPath = tmp_path / "history.jsonl"
        _writeJsonl(historyPath, [_validRecord()])
        reader = ReleaseReader(
            currentPath=tmp_path / "current.json",
            historyPath=historyPath,
        )
        assert reader.readHistory(maxEntries=0) == []
        assert reader.readHistory(maxEntries=-5) == []

    def test_invalidLinesSkippedNotRaised(self, tmp_path: Path) -> None:
        """A single malformed JSONL line cannot blank the rest of the response."""
        historyPath = tmp_path / "history.jsonl"
        valid1 = _validRecord("V0.16.0", "valid 1")
        valid2 = _validRecord("V0.17.0", "valid 2")
        # Mix valid records with garbage; reader must keep the two good ones.
        lines = [
            json.dumps(valid1),
            "{not json at all",
            json.dumps({"version": "V0.99.0"}),  # invalid schema (missing keys)
            json.dumps(valid2),
        ]
        historyPath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        reader = ReleaseReader(
            currentPath=tmp_path / "current.json",
            historyPath=historyPath,
        )
        result = reader.readHistory()
        assert result == [valid1, valid2]

    def test_blankLinesSkipped(self, tmp_path: Path) -> None:
        historyPath = tmp_path / "history.jsonl"
        valid = _validRecord()
        historyPath.write_text(f"\n{json.dumps(valid)}\n\n", encoding="utf-8")
        reader = ReleaseReader(
            currentPath=tmp_path / "current.json",
            historyPath=historyPath,
        )
        assert reader.readHistory() == [valid]


# ---- fromSettings factory ----------------------------------------------------


class TestFromSettings:
    """fromSettings builds a reader from a Settings-like object with fallbacks."""

    def test_defaultsAppliedWhenSettingsLackFields(self) -> None:
        reader = ReleaseReader.fromSettings(object())
        assert reader.currentPath == Path(DEFAULT_CURRENT_PATH)
        assert reader.historyPath == Path(DEFAULT_HISTORY_PATH)
        assert reader.historyMaxEntries == DEFAULT_HISTORY_MAX_ENTRIES

    def test_settingsValuesOverrideDefaults(self) -> None:
        settings = SimpleNamespace(
            RELEASE_VERSION_PATH="/etc/eclipse-obd/.deploy-version",
            RELEASE_HISTORY_PATH="/var/lib/eclipse-obd/release-history.jsonl",
            RELEASE_HISTORY_MAX=25,
        )
        reader = ReleaseReader.fromSettings(settings)
        assert reader.currentPath == Path("/etc/eclipse-obd/.deploy-version")
        assert reader.historyPath == Path("/var/lib/eclipse-obd/release-history.jsonl")
        assert reader.historyMaxEntries == 25

    def test_partialSettingsFallsBackPerField(self) -> None:
        """Each missing attribute falls back to its module default independently."""
        settings = SimpleNamespace(RELEASE_HISTORY_MAX=5)
        reader = ReleaseReader.fromSettings(settings)
        assert reader.currentPath == Path(DEFAULT_CURRENT_PATH)
        assert reader.historyPath == Path(DEFAULT_HISTORY_PATH)
        assert reader.historyMaxEntries == 5
