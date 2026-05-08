################################################################################
# File Name: test_release_registry_retention.py
# Purpose/Description: Tests for B-047 D4 release-registry retention enforcement
#                      (US-297 / Sprint 26). Covers pruneHistory truncation +
#                      appendRelease append-then-prune semantics + default cap
#                      of 10 records + configurability via constructor /
#                      Settings (RELEASE_HISTORY_MAX).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex          | Initial TDD tests for US-297 (Sprint 26)
# ================================================================================
################################################################################

"""Unit tests for B-047 D4 retention enforcement (US-297).

D4 invariant (verbatim): "Server keeps last 10 releases ... Older releases
auto-pruned when count exceeds the cap. Configurable via server-side env or
config."

Pre-fix the prune surface does not exist; the AC discriminator
``test_12Records_pruneRetains10_oldest2Removed`` fails with AttributeError.
Post-fix the same test asserts byte-for-byte that the oldest two release lines
are gone and the newest ten are preserved in original order.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.server.services.release_reader import (
    DEFAULT_HISTORY_MAX_ENTRIES,
    ReleaseReader,
)

# ---- Helpers -----------------------------------------------------------------


def _validRecord(version: str, description: str = "test sprint") -> dict:
    """US-241-shaped release record (version monotonically encodes 'age')."""
    return {
        "version": version,
        "releasedAt": "2026-04-29T14:32:00Z",
        "gitHash": "5025508",
        "theme": "test sprint",
        "description": description,
    }


def _writeJsonl(path: Path, records: list[dict]) -> None:
    """Write records oldest-first, one JSON object per line, trailing newline."""
    lines = [json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _readJsonlVersions(path: Path) -> list[str]:
    """Read the JSONL file and return the ordered list of version strings."""
    if not path.is_file():
        return []
    versions: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        versions.append(json.loads(line)["version"])
    return versions


# ---- pruneHistory: the AC discriminators -------------------------------------


class TestPruneHistoryEnforcesRetention:
    """``ReleaseReader.pruneHistory`` truncates the JSONL trail to last N records.

    These are the load-bearing AC tests for US-297 -- each one fails pre-fix
    (AttributeError on missing method) and passes post-fix.
    """

    def test_12Records_pruneRetains10_oldest2Removed(self, tmp_path: Path) -> None:
        """B-047 D4 verbatim acceptance: 12 releases pushed, oldest 2 pruned.

        Versions encode age: V0.10.0 = oldest, V0.21.0 = newest. After prune
        with default cap 10 the file must contain exactly V0.12.0..V0.21.0
        (oldest two -- V0.10.0 + V0.11.0 -- are gone).
        """
        historyPath = tmp_path / ".deploy-version-history"
        records = [_validRecord(f"V0.{i}.0", f"Sprint {i}") for i in range(10, 22)]
        _writeJsonl(historyPath, records)

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        prunedCount = reader.pruneHistory()

        assert prunedCount == 2
        kept = _readJsonlVersions(historyPath)
        assert kept == [f"V0.{i}.0" for i in range(12, 22)]
        assert "V0.10.0" not in kept
        assert "V0.11.0" not in kept

    def test_belowCap_pruneIsNoop(self, tmp_path: Path) -> None:
        """5 records < cap 10 -- file untouched, return 0."""
        historyPath = tmp_path / ".deploy-version-history"
        records = [_validRecord(f"V0.{i}.0") for i in range(20, 25)]
        _writeJsonl(historyPath, records)
        beforeBytes = historyPath.read_bytes()

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        prunedCount = reader.pruneHistory()

        assert prunedCount == 0
        assert historyPath.read_bytes() == beforeBytes

    def test_atCap_pruneIsNoop(self, tmp_path: Path) -> None:
        """Boundary: exactly 10 records -- no prune; return 0."""
        historyPath = tmp_path / ".deploy-version-history"
        records = [_validRecord(f"V0.{i}.0") for i in range(20, 30)]
        _writeJsonl(historyPath, records)

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        prunedCount = reader.pruneHistory()

        assert prunedCount == 0
        assert _readJsonlVersions(historyPath) == [f"V0.{i}.0" for i in range(20, 30)]

    def test_missingHistoryFile_pruneIsNoop(self, tmp_path: Path) -> None:
        """Fresh server: no history file yet -- return 0, do not create file."""
        historyPath = tmp_path / "absent.jsonl"
        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        assert reader.pruneHistory() == 0
        assert not historyPath.exists()


# ---- pruneHistory: configurability + observability ---------------------------


class TestPruneHistoryConfigurable:
    """Retention cap is overridable via constructor, fromSettings, or call kwarg."""

    def test_defaultRetentionIs10(self) -> None:
        """Module default cap matches B-047 D4 stated default."""
        assert DEFAULT_HISTORY_MAX_ENTRIES == 10

    def test_explicitMaxEntriesArgOverridesDefault(self, tmp_path: Path) -> None:
        """Per-call kwarg wins over reader default."""
        historyPath = tmp_path / ".deploy-version-history"
        records = [_validRecord(f"V0.{i}.0") for i in range(20, 32)]  # 12 records
        _writeJsonl(historyPath, records)

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        # Override to keep only 5
        prunedCount = reader.pruneHistory(maxEntries=5)

        assert prunedCount == 7
        assert _readJsonlVersions(historyPath) == [f"V0.{i}.0" for i in range(27, 32)]

    def test_constructorMaxOverridesModuleDefault(self, tmp_path: Path) -> None:
        """historyMaxEntries=3 ctor-set caps prune to 3 by default."""
        historyPath = tmp_path / ".deploy-version-history"
        records = [_validRecord(f"V0.{i}.0") for i in range(20, 30)]  # 10 records
        _writeJsonl(historyPath, records)

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
            historyMaxEntries=3,
        )
        prunedCount = reader.pruneHistory()

        assert prunedCount == 7
        assert _readJsonlVersions(historyPath) == ["V0.27.0", "V0.28.0", "V0.29.0"]

    def test_settingsRetentionRoundTrip(self, tmp_path: Path) -> None:
        """Settings.RELEASE_HISTORY_MAX flows through fromSettings -> pruneHistory."""
        historyPath = tmp_path / ".deploy-version-history"
        records = [_validRecord(f"V0.{i}.0") for i in range(20, 28)]  # 8 records
        _writeJsonl(historyPath, records)

        settings = SimpleNamespace(
            RELEASE_VERSION_PATH=str(tmp_path / ".deploy-version"),
            RELEASE_HISTORY_PATH=str(historyPath),
            RELEASE_HISTORY_MAX=4,
        )
        reader = ReleaseReader.fromSettings(settings)
        prunedCount = reader.pruneHistory()

        assert prunedCount == 4
        assert _readJsonlVersions(historyPath) == [f"V0.{i}.0" for i in range(24, 28)]

    def test_zeroOrNegativeMax_skipsPrune(self, tmp_path: Path) -> None:
        """Foot-gun guard: max<=0 returns 0 + leaves file intact (does NOT empty it)."""
        historyPath = tmp_path / ".deploy-version-history"
        records = [_validRecord(f"V0.{i}.0") for i in range(20, 25)]
        _writeJsonl(historyPath, records)
        beforeBytes = historyPath.read_bytes()

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        assert reader.pruneHistory(maxEntries=0) == 0
        assert reader.pruneHistory(maxEntries=-3) == 0
        assert historyPath.read_bytes() == beforeBytes

    def test_pruneEmitsInfoLog_withCount(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Operator observability per B-047 D4 'logged' invariant."""
        historyPath = tmp_path / ".deploy-version-history"
        records = [_validRecord(f"V0.{i}.0") for i in range(20, 33)]  # 13 records
        _writeJsonl(historyPath, records)

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        with caplog.at_level(logging.INFO, logger="src.server.services.release_reader"):
            reader.pruneHistory()

        # The log line must name BOTH the count (3) and the retained-cap (10)
        # so post-deploy journal greps can audit either signal.
        infoMessages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any("3" in msg and "10" in msg for msg in infoMessages), (
            f"Expected INFO log naming pruned-count=3 + cap=10; got: {infoMessages}"
        )


# ---- appendRelease: D4 'after each new release lands' ------------------------


class TestAppendReleaseEnforcesRetention:
    """``appendRelease`` appends a new record AND enforces retention atomically.

    D4 verbatim trigger phrase: "After each new release lands ... server prunes
    oldest releases beyond config-configured retention."
    """

    def test_appendBelowCap_noPrune_recordAtTail(self, tmp_path: Path) -> None:
        """5 records exist, append 1, file has 6, new record at the tail."""
        historyPath = tmp_path / ".deploy-version-history"
        existing = [_validRecord(f"V0.{i}.0") for i in range(20, 25)]
        _writeJsonl(historyPath, existing)

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        newRecord = _validRecord("V0.99.0", "shiny new release")
        reader.appendRelease(newRecord)

        versions = _readJsonlVersions(historyPath)
        assert len(versions) == 6
        assert versions[-1] == "V0.99.0"
        assert versions[0] == "V0.20.0"

    def test_appendAtCap_prunesOldest_newestPreserved(self, tmp_path: Path) -> None:
        """10 records exist, append 1 -> file has 10 (oldest gone, new at tail)."""
        historyPath = tmp_path / ".deploy-version-history"
        existing = [_validRecord(f"V0.{i}.0") for i in range(20, 30)]
        _writeJsonl(historyPath, existing)

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        newRecord = _validRecord("V0.99.0", "shiny new release")
        reader.appendRelease(newRecord)

        versions = _readJsonlVersions(historyPath)
        assert len(versions) == 10
        assert "V0.20.0" not in versions  # oldest pruned
        assert versions[-1] == "V0.99.0"  # newest at tail
        assert versions[0] == "V0.21.0"  # second-oldest now at head

    def test_appendInvalidRecord_raisesValueError_fileUntouched(
        self, tmp_path: Path
    ) -> None:
        """Schema-invalid record must NOT pollute the history file."""
        historyPath = tmp_path / ".deploy-version-history"
        existing = [_validRecord(f"V0.{i}.0") for i in range(20, 23)]
        _writeJsonl(historyPath, existing)
        beforeBytes = historyPath.read_bytes()

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        with pytest.raises(ValueError):
            reader.appendRelease({"version": "V0.99.0"})  # missing required fields

        assert historyPath.read_bytes() == beforeBytes

    def test_appendCreatesFileWhenAbsent(self, tmp_path: Path) -> None:
        """First-ever release on a fresh server creates the JSONL file."""
        historyPath = tmp_path / ".deploy-version-history"
        assert not historyPath.exists()

        reader = ReleaseReader(
            currentPath=tmp_path / ".deploy-version",
            historyPath=historyPath,
        )
        reader.appendRelease(_validRecord("V0.99.0", "first ever"))

        assert historyPath.is_file()
        assert _readJsonlVersions(historyPath) == ["V0.99.0"]
