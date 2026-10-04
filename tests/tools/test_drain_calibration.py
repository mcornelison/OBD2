################################################################################
# File Name: test_drain_calibration.py
# Purpose/Description: ARCH-065a T8 -- pin the drain calibration / seed tool to
#                      the real epoch-3 witness log head (fixture) and to a
#                      synthetic drain that reaches dropout.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a) | Initial -- summary, refusals, backup+insert,
#               |              | dry-run, CLI validation.
# ================================================================================
################################################################################
"""Tests for tools/power/drain_calibration (ARCH-065a T8)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.pi.power.battery_health import (
    ensureBatteryHealthLogCapacityColumns,
    ensureBatteryHealthLogTable,
)
from src.pi.power.battery_health_verdict import RESERVE_S
from tools.power.drain_calibration import main, parseWitnessLog, summarise

_FIX = Path(__file__).parent / "fixtures" / "epoch3_drain_head.log"


def _synthetic() -> list[tuple[float, str, float]]:
    return [(float(t), "0" if t else "1", 4.2 - 0.00005 * t) for t in range(0, 20001)]


def _db(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    ensureBatteryHealthLogTable(conn)
    ensureBatteryHealthLogCapacityColumns(conn)
    conn.commit()
    conn.close()
    return str(path)


def _args(db: str, *extra: str, log: str | None = None, mode: str = "monthly_test") -> list[str]:
    return ["--log", log or str(_FIX), "--date", "2026-09-27", "--mode", mode,
            "--cell-epoch", "18650-pack", "--db", db, *extra]


def test_parsesTheCutAndTheWindowRate_fromTheRealEpoch3Log() -> None:
    rows = parseWitnessLog(str(_FIX), "2026-09-27")
    s = summarise(rows, "monthly_test")
    assert s["start_timestamp"] == "2026-09-27T14:06:59Z"     # first PLD=0
    assert round(s["start_vcell_v"], 4) == 4.1000             # 1 s after the cut
    assert round(s["cut_step_mv"], 1) == 118.8                # 4.2188 - 4.1000
    assert -0.10 < s["drain_rate_mv_s"] < -0.02               # measured 2026-10-02: steep early window
    assert (s["window_start_s"], s["window_end_s"]) == (60, 660)


def test_monthlyTestRow_endsAtWindowEnd_notAtTheLastLine() -> None:
    rows = parseWitnessLog(str(_FIX), "2026-09-27")
    s = summarise(rows, "monthly_test")
    cutT = next(t for t, p, _ in rows if p == "0")
    atEnd = next(v for t, _, v in rows if t - cutT >= 660)
    assert s["end_vcell_v"] == atEnd
    assert s["runtime_seconds"] == 900
    assert "t_floor_s" not in s


def test_calibration_needsADropout_andSetsTheFloorAt10MinLeft() -> None:
    s = summarise(_synthetic(), "calibration")
    assert RESERVE_S == 600
    # the cut is the first PLD=0 row (t=1 here), so runtime = 20000 - 1
    assert s["t_floor_s"] == (20000 - 1) - 600
    assert abs(s["floor_vcell_v"] - (4.2 - 0.00005 * 19400)) < 1e-6
    assert abs(s["cutoff_vcell_v"] - (4.2 - 0.00005 * 20000)) < 1e-6


def test_calibration_refusesADrainTooShortToHaveAFloor() -> None:
    rows = [(float(t), "0" if t else "1", 4.2 - 0.00005 * t) for t in range(0, 1000)]
    with pytest.raises(ValueError, match="floor"):
        summarise(rows, "calibration")


def test_refusesAWindowTheFinaliserWouldRefuse() -> None:
    rows = [(float(t), "0" if t else "1", 4.1) for t in range(0, 300)]
    with pytest.raises(ValueError, match="window"):
        summarise(rows, "monthly_test")


def test_refusesALogWithNoCut() -> None:
    rows = [(float(t), "1", 4.2) for t in range(0, 900)]
    with pytest.raises(ValueError, match="cut"):
        summarise(rows, "monthly_test")


def test_dryRun_printsJson_andWritesNothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = _db(tmp_path / "obd.db")
    assert main(_args(db, "--dry-run")) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["drain_trigger"] == "monthly_test"
    assert out["cell_epoch"] == "18650-pack"
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM battery_health_log").fetchone()[0] == 0
    conn.close()
    assert not list(tmp_path.glob("obd.db.bak-*"))


def test_write_backsUpFirst_thenInsertsACountableRow(tmp_path: Path) -> None:
    db = _db(tmp_path / "obd.db")
    assert main(_args(db)) == 0
    backups = list(tmp_path.glob("obd.db.bak-*"))
    assert len(backups) == 1
    bk = sqlite3.connect(str(backups[0]))
    assert bk.execute("SELECT COUNT(*) FROM battery_health_log").fetchone()[0] == 0
    bk.close()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM battery_health_log").fetchall()
    assert len(r) == 1
    row = r[0]
    assert row["drain_trigger"] == "monthly_test"
    assert row["cell_epoch"] == "18650-pack"
    assert row["load_class"] == "test" and row["data_source"] == "real"
    assert row["close_reason"] == "clean"
    assert row["start_timestamp"] == "2026-09-27T14:06:59Z"
    assert row["end_timestamp"] == "2026-09-27T14:21:59Z"
    assert (row["window_start_s"], row["window_end_s"]) == (60, 660)
    assert row["drain_rate_mv_s"] < 0 and row["cut_step_mv"] > 100
    assert row["end_vcell_v"] is not None and row["runtime_seconds"] == 900
    assert "epoch3_drain_head.log" in row["notes"] and "sha256 " in row["notes"]
    assert "powerwatch stopped, dashboard NOT shed" in row["notes"]
    conn.close()


def test_calibrationWrite_carriesTheFloorFields(tmp_path: Path) -> None:
    db = _db(tmp_path / "obd.db")
    lines = ["# header"]
    for t, p, v in _synthetic():
        lines.append(f"10:00:00.000Z seq={int(t)} up={t + 100:.1f} rung=x PLD={p} VCELL={v:.4f} SOC=1")
    log = tmp_path / "cal.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(_args(db, log=str(log), mode="calibration")) == 0
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT drain_trigger, t_floor_s, floor_vcell_v, cutoff_vcell_v FROM battery_health_log"
    ).fetchone()
    assert row[0] == "calibration" and row[1] == 19399
    assert row[2] > row[3] > 0
    conn.close()


def test_unknownCellEpoch_isRejected(tmp_path: Path) -> None:
    db = _db(tmp_path / "obd.db")
    args = _args(db)
    args[args.index("--cell-epoch") + 1] = "bogus"
    with pytest.raises(SystemExit):
        main(args)


def test_corruptBackup_abortsBeforeAnyWrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path / "obd.db")
    import tools.power.drain_calibration as dc
    monkeypatch.setattr(dc, "_quickCheck", lambda p: False)
    with pytest.raises(RuntimeError, match="backup"):
        main(_args(db))
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM battery_health_log").fetchone()[0] == 0
    conn.close()
