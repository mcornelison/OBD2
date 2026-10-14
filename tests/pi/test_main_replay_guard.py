################################################################################
# File Name: test_main_replay_guard.py
# Purpose/Description: US-901-a (CIO R37) -- main.py refuses to start a replay
#                      (pi.replay.active) or a --simulate run aimed at the
#                      production database (data/obd.db under the repo root) or
#                      the production states dir, before anything opens them;
#                      and rows a replay run writes carry data_source 'replay'.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-901-a)| Initial -- start-up guard, Iris S-4 desk check,
#                               replay row tag.
# ================================================================================
################################################################################

"""Tests for the US-901-a start-up guard in ``src/pi/main.py``."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import pi.main as piMain
from pi.main import (
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    PRODUCTION_STATES_DIR,
    checkReplayStartGuard,
    main,
)

# =============================================================================
# Helpers
# =============================================================================


def _config(
    *,
    replayActive: bool = False,
    dbPath: str | None = None,
    statesDir: str | None = None,
) -> dict[str, Any]:
    pi: dict[str, Any] = {"replay": {"active": replayActive}}
    if dbPath is not None:
        pi["database"] = {"path": dbPath}
    if statesDir is not None:
        pi["splash"] = {"statesDir": statesDir}
    return {"deviceId": "chi-eclipse-01", "pi": pi}


@pytest.fixture
def fakeRepo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo root holding a production database file, as the working dir."""
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "data" / "obd.db").write_bytes(b"production rows")
    monkeypatch.setattr(piMain, "projectRoot", root)
    monkeypatch.chdir(root)
    return root


def _runMain(argv: list[str], config: dict[str, Any]) -> tuple[int, MagicMock]:
    """Run main() with ``config`` as the loaded config; runWorkflow is a spy."""
    with (
        patch("sys.argv", ["main.py", *argv]),
        patch("pi.main.setupLogging"),
        patch("pi.main.loadConfiguration", return_value=config),
        patch("pi.main.runWorkflow", return_value=EXIT_SUCCESS) as runWorkflow,
    ):
        exitCode = main()
    return exitCode, runWorkflow


# =============================================================================
# The pure guard
# =============================================================================


class TestCheckReplayStartGuard:
    @pytest.mark.parametrize(
        ("replayActive", "simulate", "mode"),
        [(True, False, "replay"), (False, True, "--simulate"), (True, True, "replay")],
    )
    def test_productionDatabase_relativePath_isRefused_namingThePath(
        self, fakeRepo: Path, replayActive: bool, simulate: bool, mode: str,
    ) -> None:
        refusal = checkReplayStartGuard(
            _config(replayActive=replayActive, dbPath="./data/obd.db"), simulate,
        )

        assert refusal == (
            f"REFUSED: {mode} will not open the production database ./data/obd.db"
        )

    def test_productionDatabase_absolutePath_isRefused(self, fakeRepo: Path) -> None:
        dbPath = str(fakeRepo / "data" / "obd.db")

        refusal = checkReplayStartGuard(_config(replayActive=True, dbPath=dbPath), False)

        assert refusal is not None and dbPath in refusal

    def test_productionDatabase_dottedPath_isRefused(self, fakeRepo: Path) -> None:
        refusal = checkReplayStartGuard(
            _config(dbPath="./data/../data/obd.db"), simulate=True,
        )

        assert refusal is not None

    def test_otherDatabase_isAllowed(self, fakeRepo: Path, tmp_path: Path) -> None:
        assert checkReplayStartGuard(
            _config(replayActive=True, dbPath=str(tmp_path / "replay.db")), True,
        ) is None
        assert checkReplayStartGuard(_config(dbPath=":memory:"), True) is None

    def test_productionRun_isNeverRefused(self, fakeRepo: Path) -> None:
        """Replay off and not --simulate: production start-up is unchanged."""
        assert checkReplayStartGuard(
            _config(dbPath="./data/obd.db", statesDir=PRODUCTION_STATES_DIR), False,
        ) is None

    @pytest.mark.parametrize(
        "statesDir", [PRODUCTION_STATES_DIR, PRODUCTION_STATES_DIR + "/"],
    )
    def test_productionStatesDir_isRefused(
        self, fakeRepo: Path, statesDir: str,
    ) -> None:
        refusal = checkReplayStartGuard(
            _config(replayActive=True, statesDir=statesDir), False,
        )

        assert refusal == (
            f"REFUSED: replay will not write the production states dir {statesDir}"
        )

    def test_tmpStatesDir_isAllowed(self, fakeRepo: Path, tmp_path: Path) -> None:
        assert checkReplayStartGuard(
            _config(replayActive=True, statesDir=str(tmp_path / "states")), True,
        ) is None


# =============================================================================
# main.py run (validation criteria 2 and 3)
# =============================================================================


class TestMainRefusesProductionDatabase:
    @pytest.mark.parametrize(
        ("argv", "replayActive", "mode"),
        [(["--config", "replay-config.json"], True, "replay"), (["--simulate"], False, "--simulate")],
    )
    def test_main_exitsNonZero_namesPath_andLeavesTheFileAlone(
        self,
        fakeRepo: Path,
        capsys: pytest.CaptureFixture[str],
        argv: list[str],
        replayActive: bool,
        mode: str,
    ) -> None:
        """
        Given: a replay (or --simulate) run with pi.database.path ./data/obd.db
        When:  main.py runs
        Then:  exit non-zero, the message names the path, the workflow never
               starts and the production file's mtime is unchanged
        """
        dbFile = fakeRepo / "data" / "obd.db"
        mtimeBefore = dbFile.stat().st_mtime_ns

        exitCode, runWorkflow = _runMain(
            argv, _config(replayActive=replayActive, dbPath="./data/obd.db"),
        )

        assert exitCode == EXIT_RUNTIME_ERROR != EXIT_SUCCESS
        assert (
            f"REFUSED: {mode} will not open the production database ./data/obd.db"
            in capsys.readouterr().err
        )
        runWorkflow.assert_not_called()
        assert dbFile.stat().st_mtime_ns == mtimeBefore
        assert dbFile.read_bytes() == b"production rows"

    def test_main_realRepoRoot_productionDatabase_isRefused(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The literal criterion: this checkout's own data/obd.db, from its root."""
        monkeypatch.chdir(piMain.projectRoot)
        dbFile = piMain.projectRoot / "data" / "obd.db"
        statBefore = dbFile.stat().st_mtime_ns if dbFile.exists() else None

        exitCode, runWorkflow = _runMain(
            ["--simulate"], _config(dbPath="./data/obd.db"),
        )

        assert exitCode == EXIT_RUNTIME_ERROR
        runWorkflow.assert_not_called()
        statAfter = dbFile.stat().st_mtime_ns if dbFile.exists() else None
        assert statAfter == statBefore

    def test_main_productionRun_isUnchanged(self, fakeRepo: Path) -> None:
        """No --simulate, replay off: main reaches runWorkflow as before."""
        exitCode, runWorkflow = _runMain([], _config(dbPath="./data/obd.db"))

        assert exitCode == EXIT_SUCCESS
        runWorkflow.assert_called_once()


class TestIrisS4StatesDirDeskCheck:
    """Iris S-4: the guard with statesDir = a tmp dir (allowed) and with the
    production /run/eclipse-obd/states (refused, non-zero, nothing written)."""

    def test_tmpStatesDir_runProceedsPastTheGuard(
        self, fakeRepo: Path, tmp_path: Path,
    ) -> None:
        exitCode, runWorkflow = _runMain(
            ["--simulate"],
            _config(dbPath=str(tmp_path / "sim.db"), statesDir=str(tmp_path / "states")),
        )

        assert exitCode == EXIT_SUCCESS
        runWorkflow.assert_called_once()

    @pytest.mark.parametrize("argv,replayActive", [(["--simulate"], False), ([], True)])
    def test_productionStatesDir_refused_nonZero_nothingWritten(
        self,
        fakeRepo: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        argv: list[str],
        replayActive: bool,
    ) -> None:
        states = Path(PRODUCTION_STATES_DIR)
        before = sorted(p.name for p in states.iterdir()) if states.exists() else None

        exitCode, runWorkflow = _runMain(
            argv,
            _config(
                replayActive=replayActive,
                dbPath=str(tmp_path / "sim.db"),
                statesDir=PRODUCTION_STATES_DIR,
            ),
        )

        assert exitCode == EXIT_RUNTIME_ERROR
        assert PRODUCTION_STATES_DIR in capsys.readouterr().err
        runWorkflow.assert_not_called()
        after = sorted(p.name for p in states.iterdir()) if states.exists() else None
        assert after == before
        assert not (tmp_path / "sim.db").exists()


# =============================================================================
# Rows a replay run writes carry data_source 'replay'
# =============================================================================


class _SimulatedConnection:
    """The replay source rides the simulated connection seam."""

    isSimulated = True


class TestReplayRowsAreTaggedReplay:
    def test_replayRun_writesRealtimeRowTaggedReplay(self, tmp_path: Path) -> None:
        from pi.obdii.data.logger import ObdDataLogger
        from pi.obdii.data.types import LoggedReading
        from pi.obdii.database import ObdDatabase

        dbPath = str(tmp_path / "replay.db")
        database = ObdDatabase(dbPath, walMode=False)
        database.initialize()
        dataLogger = ObdDataLogger(
            _SimulatedConnection(), database, config=_config(replayActive=True),
        )

        dataLogger.logReading(
            LoggedReading(parameterName="RPM", value=850.0, timestamp=datetime.now(UTC)),
        )

        conn = sqlite3.connect(dbPath)
        try:
            tags = conn.execute("SELECT data_source FROM realtime_data").fetchall()
        finally:
            conn.close()
        assert tags == [("replay",)]

    def test_simulateWithoutReplay_staysPhysicsSim(self) -> None:
        from pi.obdii.data.logger import ObdDataLogger

        dataLogger = ObdDataLogger(
            _SimulatedConnection(), None, config=_config(replayActive=False),
        )

        assert dataLogger.dataSource == "physics_sim"

    def test_explicitDataSource_stillWins(self) -> None:
        from pi.obdii.data.logger import ObdDataLogger

        dataLogger = ObdDataLogger(
            _SimulatedConnection(), None,
            dataSource="fixture", config=_config(replayActive=True),
        )

        assert dataLogger.dataSource == "fixture"
