################################################################################
# File Name: test_post_drive_review_sh.py
# Purpose/Description: Smoke tests for scripts/post_drive_review.sh (US-219).
#                      Drives the bash orchestrator via subprocess, asserting
#                      help, flag parsing, four-step ordering, and graceful
#                      behavior when Ollama is offline (via --dry-run).
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

"""Tests for :mod:`scripts.post_drive_review.sh`.

Follows the test_replay_pi_fixture_sh.py precedent -- we invoke the bash
driver via ``subprocess.run(['bash', ...])`` and assert on its stdout /
stderr / exit code.  The driver's inner Python calls are forced into
``--dry-run`` so no Ollama / network access is required.

A temporary SQLite fixture is supplied via ``DATABASE_URL`` so report.py
can open a valid schema without crashing.  The fixture is populated with
one ``drive_summary`` row and a handful of ``realtime_data`` samples --
enough to exercise both Step 1 (report.py) and Step 2 (spool_prompt_invoke
--dry-run) without requiring the server's MariaDB.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.server.db.models import Base, DriveSummary, RealtimeData  # noqa: E402

# ---------------------------------------------------------------------------
# Environment gate -- bash must be available.
# ---------------------------------------------------------------------------
_BASH_PATH = shutil.which("bash")
_skipWithoutBash = pytest.mark.skipif(
    _BASH_PATH is None,
    reason="bash not on PATH; post_drive_review.sh needs a POSIX shell",
)

_DRIVER = _REPO_ROOT / "scripts" / "post_drive_review.sh"


# ==============================================================================
# Fixture DB -- populated with one drive + enough realtime rows
# ==============================================================================


@pytest.fixture
def populatedDbUrl(tmp_path: Path) -> Iterator[str]:
    """A SQLite file pre-seeded with one drive + 10 samples / 2 parameters."""
    dbPath = tmp_path / "us219_review.db"
    url = f"sqlite:///{dbPath.as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    start = datetime(2026, 4, 21, 10, 0, 0)
    end = start + timedelta(minutes=5)
    with Session(engine) as session:
        drive = DriveSummary(
            device_id="chi-eclipse-01",
            start_time=start,
            end_time=end,
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
        nextId = 1
        for i in range(10):
            ts = start + timedelta(seconds=i * 5)
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
    yield url


# ==============================================================================
# Helpers
# ==============================================================================


def _runDriver(
    args: Sequence[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the bash driver with ``args`` and return the completed process."""
    runEnv = dict(os.environ)
    # Force the driver to use whichever python the test harness is on -- the
    # system ``python`` may not have the server-side deps installed.
    runEnv["POST_DRIVE_REVIEW_PYTHON"] = sys.executable
    if env:
        runEnv.update(env)
    # text=True + encoding='utf-8' forces the reader thread off Windows cp1252,
    # which can't decode the box-drawing glyphs our headers emit.
    return subprocess.run(  # noqa: S603 -- curated args to our own driver
        [str(_BASH_PATH), str(_DRIVER), *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=runEnv,
    )


# ==============================================================================
# --help / flag parsing
# ==============================================================================


@_skipWithoutBash
class TestHelp:
    def test_help_exitsZero_printsUsage(self) -> None:
        result = _runDriver(["--help"])
        assert result.returncode == 0
        assert "Usage: bash scripts/post_drive_review.sh" in result.stdout
        assert "--drive-id" in result.stdout
        assert "--dry-run" in result.stdout

    def test_shortH_sameAsLongForm(self) -> None:
        result = _runDriver(["-h"])
        assert result.returncode == 0
        assert "Usage: bash scripts/post_drive_review.sh" in result.stdout


@_skipWithoutBash
class TestFlagParsing:
    def test_unknownFlag_exitsTwo(self) -> None:
        result = _runDriver(["--no-such-flag"])
        assert result.returncode == 2
        assert "Unknown flag" in result.stderr

    def test_driveIdWithoutValue_exitsTwo(self) -> None:
        result = _runDriver(["--drive-id"])
        assert result.returncode == 2
        assert "--drive-id requires a value" in result.stderr

    def test_driveIdEqualsSyntax_accepted(self, populatedDbUrl) -> None:
        result = _runDriver(
            ["--drive-id=1", "--dry-run"],
            env={"DATABASE_URL": populatedDbUrl},
        )
        assert result.returncode == 0, result.stderr


# ==============================================================================
# Four-step flow
# ==============================================================================


@_skipWithoutBash
class TestDryRunFlow:
    """Full four-step orchestration against a populated SQLite fixture."""

    def test_allFourHeadersEmit_inOrder(self, populatedDbUrl) -> None:
        result = _runDriver(
            ["--drive-id", "1", "--dry-run"],
            env={"DATABASE_URL": populatedDbUrl},
        )
        assert result.returncode == 0, result.stderr

        expected = [
            "Step 1 / 4 -- Numeric drive report",
            "Step 2 / 4 -- Spool AI prompt + Ollama response",
            "Step 3 / 4 -- Drive review checklist",
            "Step 4 / 4 -- Record your findings",
        ]
        cursor = 0
        for header in expected:
            idx = result.stdout.find(header, cursor)
            assert idx >= 0, (
                f"missing header {header!r} after offset {cursor}\n"
                f"stdout: {result.stdout[:400]}"
            )
            cursor = idx + len(header)

    def test_dryRun_noOllamaCalled(self, populatedDbUrl) -> None:
        """``--dry-run`` propagates to step 2 so no HTTP is attempted."""
        result = _runDriver(
            ["--drive-id", "1", "--dry-run"],
            env={"DATABASE_URL": populatedDbUrl},
        )
        assert result.returncode == 0
        assert "Dry run" in result.stdout
        assert "Raw Ollama response" not in result.stdout

    def test_step3_printsChecklistContent(self, populatedDbUrl) -> None:
        """Step 3 must include the Spool checklist's canonical heading."""
        result = _runDriver(
            ["--drive-id", "1", "--dry-run"],
            env={"DATABASE_URL": populatedDbUrl},
        )
        assert result.returncode == 0
        # Content from offices/tuner/drive-review-checklist.md
        assert "Section A — Pipeline Integrity" in result.stdout

    def test_step4_includesReviewNotePointer(self, populatedDbUrl) -> None:
        result = _runDriver(
            ["--drive-id", "1", "--dry-run"],
            env={"DATABASE_URL": populatedDbUrl},
        )
        assert result.returncode == 0
        assert "offices/tuner/reviews/drive-1-review.md" in result.stdout
        assert "offices/pm/inbox/" in result.stdout

    def test_latestDefault_whenNoDriveIdProvided(self, populatedDbUrl) -> None:
        """Absent ``--drive-id`` resolves to 'latest' and still runs clean."""
        result = _runDriver(
            ["--dry-run"],
            env={"DATABASE_URL": populatedDbUrl},
        )
        assert result.returncode == 0
        # Pointer uses the literal 'latest' token when that's what was passed.
        assert "offices/tuner/reviews/drive-latest-review.md" in result.stdout


# ==============================================================================
# Entry-point sanity
# ==============================================================================


@_skipWithoutBash
def test_driverFileExists_isExecutable() -> None:
    """Catch a regression where the driver is deleted but tests still collect."""
    assert _DRIVER.exists(), f"driver missing at {_DRIVER}"
