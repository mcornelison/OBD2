# Honest Boot-Progress Instrument — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the journald-based boot canary with a crash-surviving append-only breadcrumb file + a systemd shutdown-finalizer, so the next boot reports the unambiguous truth about whether the prior shutdown completed and exactly which rung it died on.

**Architecture:** A tiny module `src/pi/diagnostics/boot_progress.py` owns a dirty-by-default progress file on the SD card. The orchestrator and shutdown handler append monotonic milestones (each `fdatasync`'d) immediately before each contended action. A systemd `ExecStop` unit writes the single `CLEAN_COMPLETE` rung — unreachable by a hard crash. A boot-time arm unit reads the prior trail, derives a positive-proof-only verdict into `startup_log`, archives to NAS when home, then re-arms. The journal scan in `boot_reason.py` is deleted, not repaired.

**Tech Stack:** Python 3.11 (stdlib only: `os`, `json`, `enum`, `argparse`, `subprocess`), SQLite (`startup_log`), systemd units, bash deploy step, pytest. Spec: `docs/superpowers/specs/2026-05-15-honest-boot-progress-instrument-design.md`.

**Scope:** Bug 2 (the honest instrument) ONLY. Bug 1 (the I/O-storm shutdown failure) is explicitly deferred until this instrument is bench-proven + one real drain yields the verified rung (spec §7).

**Conventions (match existing code):** camelCase functions/vars, PascalCase classes, UPPER_SNAKE constants; project file header block on new files; Google-style docstrings; `from __future__ import annotations`; runtime imports use the `src.*` form (matches `boot_reason.py`'s `from src.common.time.helper import utcIsoNow` and `drain-forensics.service`'s `PYTHONPATH=<repo root>`); tests AAA + pytest under `tests/pi/...`. Run `make lint` (ruff) on touched files only; `pytest tests/` before each commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/pi/diagnostics/boot_progress.py` (NEW) | Stage enum, `CLEAN_COMPLETE` sentinel, `markMilestone`, `readPriorTrail`, `deriveVerdict`, `arm`, `finalize`, `__main__` (`--arm`/`--finalize`) |
| `deploy/boot-progress-finalize.service` (NEW) | `ExecStop` writes `CLEAN_COMPLETE` at end of shutdown |
| `deploy/boot-progress-arm.service` (NEW) | Boot-time oneshot: read prior trail → verdict → re-arm |
| `tests/pi/diagnostics/test_boot_progress.py` (NEW) | Failure-shape + verdict-mapping unit tests |
| `tests/pi/diagnostics/test_boot_progress_contract.py` (NEW) | Shared-constant + runtime-emit contract tests |
| `tests/pi/diagnostics/test_boot_progress_integration.py` (NEW) | Real-chain orchestrator→writer→reader test |
| `docs/runbooks/2026-05-15-bench-hard-crash-drill.md` (NEW) | Layer-4 human verification runbook |
| `scripts/bench_crash_drill.sh` (NEW) | Helper for the bench drill loop |
| `src/common/config/validator.py` (MOD) | `pi.bootProgress.*` + `pi.shutdown.poweroffTimeoutSeconds` DEFAULTS + `_validateBootProgress` |
| `src/pi/obdii/database_schema.py` (MOD) | `startup_log` gains `prior_boot_last_stage`, `prior_boot_reason`; idempotent migrator |
| `src/pi/power/orchestrator.py` (MOD) | inject writer; mark WARNING/IMMINENT/TRIGGER/DRAIN_CLOSED/TRIGGER_ROW_WRITTEN |
| `src/pi/hardware/shutdown_handler.py` (MOD) | mark POWEROFF_INVOKED/POWEROFF_RC0; `poweroffTimeoutSeconds` from config |
| `src/pi/diagnostics/boot_reason.py` (MOD) | strip journal scan; keep boot-id helpers |
| `deploy/deploy-pi.sh` (MOD) | `step_install_boot_progress_units()` + call site |
| `offices/pm/scripts/audit_historical_drain_canary.py` (MOD) | import shared Stage/marker constant |
| `tests/pi/diagnostics/test_boot_reason*.py` (DELETE journal-scan tests) | replaced by `test_boot_progress*.py` |

---

## Task 1: Stage vocabulary — the single shared contract

**Files:**
- Create: `src/pi/diagnostics/boot_progress.py`
- Test: `tests/pi/diagnostics/test_boot_progress_contract.py`

- [ ] **Step 1: Write the failing contract test**

```python
# tests/pi/diagnostics/test_boot_progress_contract.py
"""Contract tests: the stage vocabulary is one shared source of truth."""
from src.pi.diagnostics.boot_progress import Stage, MILESTONE_ORDER, CLEAN_COMPLETE_RUNG


def test_milestoneOrder_isMonotonicAndComplete():
    # Arrange / Act
    names = [s.value for s in MILESTONE_ORDER]
    # Assert: exact ordered ladder from spec §4.2
    assert names == [
        "RUNNING", "WARNING", "IMMINENT", "TRIGGER", "DRAIN_CLOSED",
        "TRIGGER_ROW_WRITTEN", "POWEROFF_INVOKED", "POWEROFF_RC0",
        "CLEAN_COMPLETE",
    ]


def test_cleanCompleteRung_isTheOnlyCleanProof():
    assert CLEAN_COMPLETE_RUNG is Stage.CLEAN_COMPLETE
    assert MILESTONE_ORDER[-1] is Stage.CLEAN_COMPLETE
    assert MILESTONE_ORDER[0] is Stage.RUNNING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_progress_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pi.diagnostics.boot_progress'`

- [ ] **Step 3: Create the module skeleton with the shared contract**

```python
# src/pi/diagnostics/boot_progress.py
################################################################################
# File Name: boot_progress.py
# Purpose/Description: Crash-surviving boot-progress breadcrumb instrument.
#                      Replaces the journald-based boot canary (I-037).  A
#                      dirty-by-default append-only file records the furthest
#                      milestone the shutdown sequence reached; the next boot
#                      derives a positive-proof-only verdict.  Only the
#                      systemd shutdown-finalizer writes CLEAN_COMPLETE, so a
#                      hard crash can never forge "clean".  See
#                      docs/superpowers/specs/2026-05-15-honest-boot-progress-
#                      instrument-design.md.
# Author: (implementation plan 2026-05-15)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-15    | Plan    | Initial -- Bug 2 honest instrument.
# ================================================================================
################################################################################

"""Crash-surviving boot-progress breadcrumb instrument (replaces I-037 canary)."""

from __future__ import annotations

import enum

__all__ = ["Stage", "MILESTONE_ORDER", "CLEAN_COMPLETE_RUNG"]


class Stage(enum.Enum):
    """Ordered shutdown-progress milestones. Single source of truth shared by
    the writer (orchestrator + shutdown_handler), the reader (arm), and the
    US-343 audit script. Making this config-mutable would re-create the
    US-308/US-342 silent-drift bug (spec §4.4)."""

    RUNNING = "RUNNING"
    WARNING = "WARNING"
    IMMINENT = "IMMINENT"
    TRIGGER = "TRIGGER"
    DRAIN_CLOSED = "DRAIN_CLOSED"
    TRIGGER_ROW_WRITTEN = "TRIGGER_ROW_WRITTEN"
    POWEROFF_INVOKED = "POWEROFF_INVOKED"
    POWEROFF_RC0 = "POWEROFF_RC0"
    CLEAN_COMPLETE = "CLEAN_COMPLETE"


#: The ladder in strict monotonic order. Index = rung height.
MILESTONE_ORDER: tuple[Stage, ...] = (
    Stage.RUNNING,
    Stage.WARNING,
    Stage.IMMINENT,
    Stage.TRIGGER,
    Stage.DRAIN_CLOSED,
    Stage.TRIGGER_ROW_WRITTEN,
    Stage.POWEROFF_INVOKED,
    Stage.POWEROFF_RC0,
    Stage.CLEAN_COMPLETE,
)

#: The ONLY rung that proves a graceful shutdown actually completed.
CLEAN_COMPLETE_RUNG: Stage = Stage.CLEAN_COMPLETE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/diagnostics/test_boot_progress_contract.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pi/diagnostics/boot_progress.py tests/pi/diagnostics/test_boot_progress_contract.py
git commit -m "feat(boot_progress): shared Stage contract (honest instrument T1)"
```

---

## Task 2: `markMilestone` — fail-safe append + fdatasync

**Files:**
- Modify: `src/pi/diagnostics/boot_progress.py`
- Test: `tests/pi/diagnostics/test_boot_progress.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pi/diagnostics/test_boot_progress.py
"""Failure-shape + behavior tests for the honest boot-progress instrument."""
import json
from src.pi.diagnostics.boot_progress import Stage, markMilestone


def test_markMilestone_appendsOneJsonLineWithFields(tmp_path):
    # Arrange
    f = tmp_path / "boot_progress"
    # Act
    markMilestone(Stage.TRIGGER, vcell=3.446, filePath=str(f), bootId="abc123")
    # Assert
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["stage"] == "TRIGGER"
    assert rec["vcell"] == 3.446
    assert rec["boot_id"] == "abc123"
    assert "ts" in rec


def test_markMilestone_isAppendOnly(tmp_path):
    f = tmp_path / "boot_progress"
    markMilestone(Stage.WARNING, vcell=3.70, filePath=str(f), bootId="b")
    markMilestone(Stage.IMMINENT, vcell=3.55, filePath=str(f), bootId="b")
    assert len(f.read_text(encoding="utf-8").splitlines()) == 2


def test_markMilestone_neverRaisesOnUnwritablePath(caplog):
    # Arrange: a path that cannot be created (parent is a non-dir)
    bad = "/proc/cpuinfo/cannot/write/here"
    # Act / Assert: MUST NOT raise into the shutdown path
    markMilestone(Stage.POWEROFF_INVOKED, vcell=3.4, filePath=bad, bootId="b")
    assert any("boot_progress" in r.message for r in caplog.records)


def test_markMilestone_stopsAtMaxTrailBytes(tmp_path, caplog):
    f = tmp_path / "boot_progress"
    for _ in range(50):
        markMilestone(Stage.RUNNING, vcell=3.9, filePath=str(f),
                       bootId="b", maxTrailBytes=120)
    # File never grows past the cap by more than one record
    assert f.stat().st_size <= 120 + 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_progress.py -v`
Expected: FAIL — `ImportError: cannot import name 'markMilestone'`

- [ ] **Step 3: Implement `markMilestone`**

Add to `src/pi/diagnostics/boot_progress.py` (extend `__all__` with `"markMilestone"`, `"DEFAULT_FILE_PATH"`, `"DEFAULT_MAX_TRAIL_BYTES"`):

```python
import json
import logging
import os

from src.common.time.helper import utcIsoNow

logger = logging.getLogger(__name__)

#: Defaults mirror the config keys (spec §4.4). Production passes the
#: validated config value; these defaults keep the module usable standalone.
DEFAULT_FILE_PATH = "data/boot_progress"
DEFAULT_MAX_TRAIL_BYTES = 65536


def markMilestone(
    stage: Stage,
    *,
    vcell: float | None,
    filePath: str = DEFAULT_FILE_PATH,
    bootId: str,
    maxTrailBytes: int = DEFAULT_MAX_TRAIL_BYTES,
) -> None:
    """Append one milestone line and fdatasync it. FAIL-SAFE.

    Never raises into the caller: the orchestrator/shutdown path must keep
    trying to power off even if this write fails under the I/O storm. A lost
    breadcrumb only degrades fidelity; the no-false-clean invariant holds
    because only the finalizer writes CLEAN_COMPLETE (spec §4.2).
    """
    try:
        if os.path.exists(filePath) and os.path.getsize(filePath) >= maxTrailBytes:
            logger.warning(
                "boot_progress trail at %s exceeds maxTrailBytes=%d -- "
                "not appending %s (restart-loop guard)",
                filePath, maxTrailBytes, stage.value,
            )
            return
        line = json.dumps(
            {"boot_id": bootId, "stage": stage.value,
             "ts": utcIsoNow(), "vcell": vcell},
            separators=(",", ":"),
        ) + "\n"
        fd = os.open(filePath, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fdatasync(fd)
        finally:
            os.close(fd)
    except Exception as exc:  # noqa: BLE001 -- fail-safe by contract
        logger.warning("boot_progress markMilestone(%s) failed: %s",
                        stage.value, exc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/diagnostics/test_boot_progress.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pi/diagnostics/boot_progress.py tests/pi/diagnostics/test_boot_progress.py
git commit -m "feat(boot_progress): fail-safe fdatasync'd markMilestone (T2)"
```

---

## Task 3: `readPriorTrail` + `deriveVerdict` — positive-proof verdict

**Files:**
- Modify: `src/pi/diagnostics/boot_progress.py`
- Test: `tests/pi/diagnostics/test_boot_progress.py`

- [ ] **Step 1: Write the failing tests (the Drain-26 shape MUST be 0)**

```python
# append to tests/pi/diagnostics/test_boot_progress.py
import pytest
from src.pi.diagnostics.boot_progress import deriveVerdict, readPriorTrail


def _writeTrail(path, stages):
    import json as _j
    path.write_text(
        "".join(_j.dumps({"boot_id": "b", "stage": s, "ts": "t",
                           "vcell": 3.5}) + "\n" for s in stages),
        encoding="utf-8",
    )


@pytest.mark.parametrize("stages,clean,reason", [
    (["RUNNING", "WARNING", "IMMINENT", "TRIGGER", "DRAIN_CLOSED",
      "TRIGGER_ROW_WRITTEN", "POWEROFF_INVOKED", "POWEROFF_RC0",
      "CLEAN_COMPLETE"], 1, "graceful"),
    (["RUNNING", "WARNING", "IMMINENT", "TRIGGER", "DRAIN_CLOSED",
      "TRIGGER_ROW_WRITTEN", "POWEROFF_INVOKED", "POWEROFF_RC0"],
     0, "poweroff_accepted_unfinalized"),
    # The Drain-26 shape: poweroff invoked, never returned. Old canary said 1.
    (["RUNNING", "WARNING", "IMMINENT", "TRIGGER", "DRAIN_CLOSED",
      "TRIGGER_ROW_WRITTEN", "POWEROFF_INVOKED"],
     0, "poweroff_invoked_never_returned"),
    (["RUNNING", "WARNING", "IMMINENT", "TRIGGER"],
     0, "wedged_before_poweroff"),
    (["RUNNING", "WARNING", "IMMINENT"], 0, "died_mid_drain"),
    (["RUNNING"], 0, "crashed_during_operation"),
])
def test_deriveVerdict_positiveProofOnly(tmp_path, stages, clean, reason):
    f = tmp_path / "boot_progress"
    _writeTrail(f, stages)
    trail = readPriorTrail(str(f))
    priorClean, priorStage, priorReason = deriveVerdict(trail)
    assert priorClean == clean
    assert priorReason == reason
    assert priorStage == stages[-1]


def test_deriveVerdict_missingFileIsNullNotClean(tmp_path):
    trail = readPriorTrail(str(tmp_path / "nope"))
    priorClean, priorStage, priorReason = deriveVerdict(trail)
    assert priorClean is None
    assert priorReason == "indeterminate_no_record"


def test_deriveVerdict_corruptLinesIgnored_highestStillWins(tmp_path):
    f = tmp_path / "boot_progress"
    f.write_text('{"stage":"TRIGGER"}\nGARBAGE NOT JSON\n'
                 '{"stage":"POWEROFF_INVOKED"}\n', encoding="utf-8")
    priorClean, priorStage, priorReason = deriveVerdict(readPriorTrail(str(f)))
    assert priorClean == 0
    assert priorStage == "POWEROFF_INVOKED"


def test_deriveVerdict_lowerRungAfterHigherIsIgnored(tmp_path):
    f = tmp_path / "boot_progress"
    _writeTrail(f, ["RUNNING", "TRIGGER", "WARNING"])  # WARNING < TRIGGER
    priorClean, priorStage, _ = deriveVerdict(readPriorTrail(str(f)))
    assert priorStage == "TRIGGER"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_progress.py -k deriveVerdict -v`
Expected: FAIL — `ImportError: cannot import name 'deriveVerdict'`

- [ ] **Step 3: Implement reader + verdict (extend `__all__`)**

```python
#: Verdict mapping (spec §4.4) -- ONLY CLEAN_COMPLETE => clean. Positive proof.
_VERDICT_BY_STAGE: dict[Stage, tuple[int, str]] = {
    Stage.CLEAN_COMPLETE: (1, "graceful"),
    Stage.POWEROFF_RC0: (0, "poweroff_accepted_unfinalized"),
    Stage.POWEROFF_INVOKED: (0, "poweroff_invoked_never_returned"),
    Stage.TRIGGER_ROW_WRITTEN: (0, "wedged_before_poweroff"),
    Stage.DRAIN_CLOSED: (0, "wedged_before_poweroff"),
    Stage.TRIGGER: (0, "wedged_before_poweroff"),
    Stage.IMMINENT: (0, "died_mid_drain"),
    Stage.WARNING: (0, "died_mid_drain"),
    Stage.RUNNING: (0, "crashed_during_operation"),
}
_RANK: dict[Stage, int] = {s: i for i, s in enumerate(MILESTONE_ORDER)}


def readPriorTrail(filePath: str = DEFAULT_FILE_PATH) -> list[dict]:
    """Read the prior boot's trail. Malformed lines are skipped (defensive);
    a missing/empty file returns []."""
    try:
        with open(filePath, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return []
    records: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(rec, dict) and rec.get("stage"):
            records.append(rec)
    return records


def deriveVerdict(trail: list[dict]) -> tuple[int | None, str | None, str]:
    """Return ``(prior_boot_clean, prior_boot_last_stage, prior_boot_reason)``.

    Positive proof only: clean==1 iff CLEAN_COMPLETE is present. Anything
    else is 0; an empty/unreadable trail is NULL (never inferred clean).
    """
    highest: Stage | None = None
    for rec in trail:
        try:
            st = Stage(rec["stage"])
        except (ValueError, KeyError):
            continue
        if highest is None or _RANK[st] > _RANK[highest]:
            highest = st
    if highest is None:
        return (None, None, "indeterminate_no_record")
    clean, reason = _VERDICT_BY_STAGE[highest]
    return (clean, highest.value, reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/diagnostics/test_boot_progress.py -v`
Expected: PASS (all parametrized cases + edge cases green)

- [ ] **Step 5: Commit**

```bash
git add src/pi/diagnostics/boot_progress.py tests/pi/diagnostics/test_boot_progress.py
git commit -m "feat(boot_progress): positive-proof verdict mapping (T3)"
```

---

## Task 4: Schema — `startup_log` forensic columns + idempotent migrator

**Files:**
- Modify: `src/pi/obdii/database_schema.py:570-593` (`SCHEMA_STARTUP_LOG`)
- Modify: `src/pi/obdii/database_schema.py` (add `ensureStartupLogForensicColumns`)
- Test: `tests/pi/diagnostics/test_boot_progress.py`

- [ ] **Step 1: Write the failing test (legacy DB gains columns idempotently)**

```python
# append to tests/pi/diagnostics/test_boot_progress.py
import sqlite3
from src.pi.obdii.database_schema import (
    SCHEMA_STARTUP_LOG, ensureStartupLogForensicColumns,
)


def test_ensureStartupLogForensicColumns_addsColumnsOnLegacyDb(tmp_path):
    db = tmp_path / "obd.db"
    conn = sqlite3.connect(db)
    # Legacy table WITHOUT the new columns
    conn.execute("""CREATE TABLE startup_log (
        boot_id TEXT PRIMARY KEY, prior_boot_clean INTEGER,
        prior_last_entry_ts TEXT, current_boot_first_entry_ts TEXT,
        recorded_at TEXT NOT NULL DEFAULT '')""")
    conn.commit()
    # Act: run twice -- must be idempotent
    ensureStartupLogForensicColumns(conn)
    ensureStartupLogForensicColumns(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(startup_log)")}
    assert "prior_boot_last_stage" in cols
    assert "prior_boot_reason" in cols
    conn.close()


def test_schemaStartupLog_freshDbHasForensicColumns(tmp_path):
    conn = sqlite3.connect(tmp_path / "fresh.db")
    conn.executescript(SCHEMA_STARTUP_LOG)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(startup_log)")}
    assert {"prior_boot_last_stage", "prior_boot_reason"} <= cols
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_progress.py -k StartupLog -v`
Expected: FAIL — `ImportError: cannot import name 'ensureStartupLogForensicColumns'`

- [ ] **Step 3: Update `SCHEMA_STARTUP_LOG` and add the migrator**

In `src/pi/obdii/database_schema.py`, inside `SCHEMA_STARTUP_LOG` add two columns before the closing `);` (after `current_boot_first_entry_ts TEXT,`):

```sql
    -- Honest-instrument forensic fields (spec 2026-05-15). Highest
    -- boot_progress milestone reached + its decoded reason.
    prior_boot_last_stage TEXT,
    prior_boot_reason TEXT,
```

Then add a migrator (mirror the `drive_id.ensureDriveIdColumn()` legacy-DB pattern referenced at `database_schema.py:683-686`):

```python
def ensureStartupLogForensicColumns(conn) -> None:
    """Idempotently add prior_boot_last_stage / prior_boot_reason to an
    existing startup_log. Legacy Pi DBs predate these columns; fresh DBs
    get them from SCHEMA_STARTUP_LOG. Mirrors drive_id.ensureDriveIdColumn:
    PRAGMA-guarded ALTER so re-runs and fresh DBs are no-ops."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(startup_log)")}
    for col in ("prior_boot_last_stage", "prior_boot_reason"):
        if col not in existing:
            conn.execute(f"ALTER TABLE startup_log ADD COLUMN {col} TEXT")
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/diagnostics/test_boot_progress.py -k StartupLog -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pi/obdii/database_schema.py tests/pi/diagnostics/test_boot_progress.py
git commit -m "feat(schema): startup_log forensic columns + idempotent migrator (T4)"
```

---

## Task 5: `arm` — read prior → verdict → startup_log → NAS → re-arm

**Files:**
- Modify: `src/pi/diagnostics/boot_progress.py`
- Test: `tests/pi/diagnostics/test_boot_progress.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/pi/diagnostics/test_boot_progress.py
from src.pi.diagnostics.boot_progress import arm


def test_arm_writesVerdictRow_thenReArmsRunning(tmp_path):
    f = tmp_path / "boot_progress"
    _writeTrail(f, ["RUNNING", "WARNING", "IMMINENT", "TRIGGER",
                    "POWEROFF_INVOKED"])  # Drain-26 shape
    db = tmp_path / "obd.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_STARTUP_LOG)
    conn.close()

    arm(filePath=str(f), dbPath=str(db), bootId="newboot1",
        nasArchiveDir=str(tmp_path / "nas"), nasArchiveEnabled=True)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT prior_boot_clean, prior_boot_last_stage, prior_boot_reason "
        "FROM startup_log WHERE boot_id='newboot1'").fetchone()
    conn.close()
    assert row == (0, "POWEROFF_INVOKED", "poweroff_invoked_never_returned")
    # Re-armed: file now holds exactly one RUNNING line for the new boot
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["stage"] == "RUNNING"
    assert json.loads(lines[0])["boot_id"] == "newboot1"
    # Prior trail archived to NAS
    assert any((tmp_path / "nas").iterdir())


def test_arm_idempotentInsertOrIgnore(tmp_path):
    f = tmp_path / "boot_progress"
    _writeTrail(f, ["RUNNING"])
    db = tmp_path / "obd.db"
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)
    arm(filePath=str(f), dbPath=str(db), bootId="dup",
        nasArchiveDir=str(tmp_path / "n"), nasArchiveEnabled=False)
    _writeTrail(f, ["RUNNING", "WARNING"])
    arm(filePath=str(f), dbPath=str(db), bootId="dup",
        nasArchiveDir=str(tmp_path / "n"), nasArchiveEnabled=False)
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM startup_log WHERE boot_id='dup'").fetchone()[0]
    conn.close()
    assert n == 1  # INSERT OR IGNORE -- one row per boot_id


def test_arm_stillReArmsWhenDbWriteFails(tmp_path, caplog):
    f = tmp_path / "boot_progress"
    _writeTrail(f, ["RUNNING", "TRIGGER"])
    arm(filePath=str(f), dbPath="/proc/cannot/write.db", bootId="x",
        nasArchiveDir=str(tmp_path / "n"), nasArchiveEnabled=False)
    # The critical invariant: the new boot is armed even if DB write failed
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["stage"] == "RUNNING"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_progress.py -k arm -v`
Expected: FAIL — `ImportError: cannot import name 'arm'`

- [ ] **Step 3: Implement `arm`**

```python
import shutil
import sqlite3

from src.pi.obdii.database_schema import ensureStartupLogForensicColumns


def _writeStartupLogRow(dbPath, bootId, clean, lastStage, reason) -> None:
    """Idempotent INSERT OR IGNORE -- mirrors the legacy boot_reason writer."""
    conn = sqlite3.connect(dbPath, timeout=5.0)
    try:
        ensureStartupLogForensicColumns(conn)
        conn.execute(
            "INSERT OR IGNORE INTO startup_log "
            "(boot_id, prior_boot_clean, prior_last_entry_ts, "
            " current_boot_first_entry_ts, recorded_at, "
            " prior_boot_last_stage, prior_boot_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bootId, clean, None, None, utcIsoNow(), lastStage, reason),
        )
        conn.commit()
    finally:
        conn.close()


def arm(
    *,
    filePath: str = DEFAULT_FILE_PATH,
    dbPath: str,
    bootId: str,
    nasArchiveDir: str,
    nasArchiveEnabled: bool,
) -> None:
    """Boot-time: read prior trail -> verdict -> startup_log -> archive ->
    truncate + write RUNNING. Re-arming the new boot is the most critical
    step and happens even if the DB write or archive failed (spec §4.5)."""
    trail = readPriorTrail(filePath)
    clean, lastStage, reason = deriveVerdict(trail)

    try:
        _writeStartupLogRow(dbPath, bootId, clean, lastStage, reason)
    except Exception as exc:  # noqa: BLE001 -- never block boot
        logger.error("boot_progress: startup_log write failed: %s", exc)

    if nasArchiveEnabled and trail:
        try:
            os.makedirs(nasArchiveDir, exist_ok=True)
            shutil.copy2(
                filePath,
                os.path.join(nasArchiveDir, f"boot_progress.{bootId}.jsonl"),
            )
        except Exception as exc:  # noqa: BLE001 -- best-effort
            logger.warning("boot_progress: NAS archive skipped: %s", exc)

    # Re-arm: atomic replace then RUNNING line (always, even on prior failure)
    try:
        tmp = filePath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("")
            fh.flush()
            os.fdatasync(fh.fileno())
        os.replace(tmp, filePath)
    except Exception as exc:  # noqa: BLE001
        logger.error("boot_progress: re-arm truncate failed: %s", exc)
    markMilestone(Stage.RUNNING, vcell=None, filePath=filePath, bootId=bootId)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/diagnostics/test_boot_progress.py -k arm -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/pi/diagnostics/boot_progress.py tests/pi/diagnostics/test_boot_progress.py
git commit -m "feat(boot_progress): arm/reader -> startup_log + NAS + re-arm (T5)"
```

---

## Task 6: `finalize` + `__main__` entrypoint (invoked exactly as the units invoke it)

**Files:**
- Modify: `src/pi/diagnostics/boot_progress.py`
- Test: `tests/pi/diagnostics/test_boot_progress_contract.py`

- [ ] **Step 1: Write the failing test (the entrypoint emits the exact rung)**

```python
# append to tests/pi/diagnostics/test_boot_progress_contract.py
import json, subprocess, sys, sqlite3
from src.pi.diagnostics.boot_progress import finalize
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG


def test_finalize_appendsCleanCompleteVerbatim(tmp_path):
    f = tmp_path / "boot_progress"
    f.write_text('{"boot_id":"b","stage":"POWEROFF_RC0","ts":"t","vcell":3.4}\n',
                 encoding="utf-8")
    finalize(filePath=str(f), bootId="b")
    last = json.loads(f.read_text(encoding="utf-8").splitlines()[-1])
    assert last["stage"] == "CLEAN_COMPLETE"


def test_cli_finalize_invokedAsTheUnitInvokesIt(tmp_path):
    """Runs `python -m src.pi.diagnostics.boot_progress --finalize` exactly
    as boot-progress-finalize.service ExecStop does -- guards the US-277
    silent-import-failure class."""
    f = tmp_path / "boot_progress"
    f.write_text('{"boot_id":"b","stage":"POWEROFF_RC0","ts":"t","vcell":3}\n',
                 encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "src.pi.diagnostics.boot_progress",
         "--finalize", "--file", str(f), "--boot-id", "b"],
        capture_output=True, text=True, cwd=".",
    )
    assert r.returncode == 0, r.stderr
    assert "CLEAN_COMPLETE" in f.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_progress_contract.py -k finalize -v`
Expected: FAIL — `ImportError: cannot import name 'finalize'`

- [ ] **Step 3: Implement `finalize` + argparse `__main__`**

```python
import argparse


def finalize(*, filePath: str = DEFAULT_FILE_PATH, bootId: str) -> None:
    """Append the single CLEAN_COMPLETE rung. Called ONLY by the systemd
    finalizer ExecStop -- a hard crash never reaches this (spec §4.3)."""
    markMilestone(Stage.CLEAN_COMPLETE, vcell=None,
                  filePath=filePath, bootId=bootId)


def _readBootId() -> str:
    """Current boot id (reuses the kernel surface boot_reason reads)."""
    try:
        from src.pi.diagnostics.boot_reason import readCurrentBootId
        return readCurrentBootId() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Boot-progress instrument")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--arm", action="store_true")
    g.add_argument("--finalize", action="store_true")
    p.add_argument("--file", default=DEFAULT_FILE_PATH)
    p.add_argument("--db", default="data/obd.db")
    p.add_argument("--boot-id", default=None)
    p.add_argument("--nas-dir", default="")
    p.add_argument("--nas-enabled", action="store_true")
    a = p.parse_args(argv)
    bootId = a.boot_id or _readBootId()
    if a.finalize:
        finalize(filePath=a.file, bootId=bootId)
    else:
        arm(filePath=a.file, dbPath=a.db, bootId=bootId,
            nasArchiveDir=a.nas_dir, nasArchiveEnabled=a.nas_enabled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `"finalize"`, `"main"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/diagnostics/test_boot_progress_contract.py -v`
Expected: PASS (all contract + finalize/CLI tests green)

- [ ] **Step 5: Commit**

```bash
git add src/pi/diagnostics/boot_progress.py tests/pi/diagnostics/test_boot_progress_contract.py
git commit -m "feat(boot_progress): finalize + --arm/--finalize CLI (T6)"
```

---

## Task 7: Config — DEFAULTS + validator

**Files:**
- Modify: `src/common/config/validator.py` (`DEFAULTS` dict, add `_validateBootProgress`, call it in `validate`)
- Test: `tests/common/config/test_validator.py` (new test fn appended)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/common/config/test_validator.py
from src.common.config.validator import ConfigValidator, ConfigValidationError
import pytest


def _baseCfg():
    return {"protocolVersion": "1", "schemaVersion": "1", "deviceId": "d",
            "pi": {}, "server": {}}


def test_bootProgress_defaultsApplied():
    cfg = ConfigValidator().validate(_baseCfg())
    bp = cfg["pi"]["bootProgress"]
    assert bp["filePath"] == "data/boot_progress"
    assert bp["nasArchiveEnabled"] is True
    assert bp["maxTrailBytes"] == 65536
    assert cfg["pi"]["shutdown"]["poweroffTimeoutSeconds"] == 30


def test_bootProgress_rejectsNonPositiveTimeout():
    cfg = _baseCfg()
    cfg["pi"] = {"shutdown": {"poweroffTimeoutSeconds": 0}}
    with pytest.raises(ConfigValidationError):
        ConfigValidator().validate(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/common/config/test_validator.py -k bootProgress -v`
Expected: FAIL — `KeyError: 'bootProgress'`

- [ ] **Step 3: Add DEFAULTS + validator**

In `src/common/config/validator.py` `DEFAULTS` dict, add after the `pi.power.power_monitor.enabled` entry (~line 142):

```python
    # Honest boot-progress instrument (spec 2026-05-15). filePath is
    # relative to the Pi project root (WorkingDirectory); nasArchiveDir is
    # the home-only NAS mount; maxTrailBytes bounds the file against a
    # restart loop. poweroffTimeoutSeconds replaces the hardcoded literal
    # at shutdown_handler.py subprocess.run(timeout=...).
    'pi.bootProgress.filePath': 'data/boot_progress',
    'pi.bootProgress.nasArchiveDir': '/mnt/projects/O/OBD2v2/boot-progress',
    'pi.bootProgress.nasArchiveEnabled': True,
    'pi.bootProgress.maxTrailBytes': 65536,
    'pi.shutdown.poweroffTimeoutSeconds': 30,
```

Add a validator method (mirror `_validatePiSync`'s bool-then-type-then-range idiom) and call it from `validate()` next to the others (after `self._validatePiSync(config)`):

```python
    def _validateBootProgress(self, config: dict[str, Any]) -> None:
        """Validate pi.bootProgress.maxTrailBytes and
        pi.shutdown.poweroffTimeoutSeconds are positive numbers. A zero/
        negative poweroff timeout would silently break the shutdown path."""
        mtb = self._getNestedValue(config, 'pi.bootProgress.maxTrailBytes')
        if mtb is not None and (
            isinstance(mtb, bool) or not isinstance(mtb, int) or mtb <= 0
        ):
            raise ConfigValidationError(
                f"pi.bootProgress.maxTrailBytes must be a positive int "
                f"(got {mtb!r})",
                missingFields=['pi.bootProgress.maxTrailBytes'],
            )
        pto = self._getNestedValue(config, 'pi.shutdown.poweroffTimeoutSeconds')
        if pto is not None and (
            isinstance(pto, bool)
            or not isinstance(pto, (int, float))
            or pto <= 0
        ):
            raise ConfigValidationError(
                f"pi.shutdown.poweroffTimeoutSeconds must be a positive "
                f"number (got {pto!r})",
                missingFields=['pi.shutdown.poweroffTimeoutSeconds'],
            )
```

Add `self._validateBootProgress(config)` immediately after `self._validatePiSync(config)` in `validate()`.

- [ ] **Step 4: Run tests + the config gate**

Run: `pytest tests/common/config/test_validator.py -k bootProgress -v && python validate_config.py`
Expected: PASS (2 passed) and `validate_config.py` exits 0

- [ ] **Step 5: Commit**

```bash
git add src/common/config/validator.py tests/common/config/test_validator.py
git commit -m "feat(config): pi.bootProgress.* + poweroffTimeoutSeconds defaults (T7)"
```

---

## Task 8: Orchestrator integration — mark WARNING/IMMINENT/TRIGGER/DRAIN_CLOSED/TRIGGER_ROW_WRITTEN

**Files:**
- Modify: `src/pi/power/orchestrator.py` (constructor DI + `_enterWarning`:843, `_enterImminent`:877, `_enterTrigger`:886-908)
- Test: `tests/pi/power/test_orchestrator_boot_progress.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
# tests/pi/power/test_orchestrator_boot_progress.py
"""Orchestrator emits the exact boot-progress rungs at the exact seams."""
from src.pi.power.orchestrator import PowerDownOrchestrator
from src.pi.power.ups_monitor import PowerState  # adjust import if needed


def test_enterTrigger_marksTrigger_thenDrainClosed_thenRowWritten():
    marks = []
    orch = _makeOrchestrator(  # helper: see existing orchestrator tests
        bootProgressWriter=lambda stage, vcell: marks.append(stage.value),
    )
    orch._enterTrigger(3.446)
    # Spec §4.2: TRIGGER before _closeDrainEvent; DRAIN_CLOSED after;
    # TRIGGER_ROW_WRITTEN after _writePowerLogStage.
    assert marks[:3] == ["TRIGGER", "DRAIN_CLOSED", "TRIGGER_ROW_WRITTEN"]
```

> Use the same orchestrator construction helper/fixtures the existing
> `tests/pi/power/test_*orchestrator*` files use (recorder/callback fakes).
> If none exists, build a minimal fake `_recorder` with
> `startDrainEvent`/`endDrainEvent` no-ops and stub `_writePowerLogStage`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/power/test_orchestrator_boot_progress.py -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'bootProgressWriter'`

- [ ] **Step 3: Wire the injected writer + the five marks**

In `PowerDownOrchestrator.__init__`, add a constructor kwarg (DI, matching the codebase pattern; default binds the real module fn):

```python
from src.pi.diagnostics.boot_progress import Stage as _BpStage
from src.pi.diagnostics.boot_progress import markMilestone as _bpMark

# in __init__ signature, add:  bootProgressWriter=None
self._bootProgressWriter = bootProgressWriter or (
    lambda stage, vcell: _bpMark(stage, vcell=vcell, bootId=_bpBootId())
)
```

Add a thin helper near `_writePowerLogStage`:

```python
def _markBootProgress(self, stage, vcell: float | None) -> None:
    try:
        self._bootProgressWriter(stage, vcell)
    except Exception as e:  # noqa: BLE001 -- never block the ladder
        logger.error("PowerDownOrchestrator: boot_progress mark failed: %s", e)
```

Insert marks at the exact seams:
- `_enterWarning` (after the `logger.warning(...)`, line ~847): `self._markBootProgress(_BpStage.WARNING, vcell)`
- `_enterImminent` (after `logger.warning(...)`, line ~880): `self._markBootProgress(_BpStage.IMMINENT, vcell)`
- `_enterTrigger`: `TRIGGER` immediately after the `logger.warning(...)` (line ~890) and **before** `self._closeDrainEvent(...)` (line 893); `DRAIN_CLOSED` immediately after `self._closeDrainEvent(...)` returns; `TRIGGER_ROW_WRITTEN` immediately after `self._writePowerLogStage("stage_trigger", vcell)` (line 899) and before the `_shutdownFired` guard.

(`_bpBootId` is a tiny module-level helper in orchestrator: `from src.pi.diagnostics.boot_reason import readCurrentBootId` → `readCurrentBootId() or "unknown"`.)

- [ ] **Step 4: Run test + full power suite**

Run: `pytest tests/pi/power/ -m "not slow" -q`
Expected: PASS (new test green; no regressions)

- [ ] **Step 5: Commit**

```bash
git add src/pi/power/orchestrator.py tests/pi/power/test_orchestrator_boot_progress.py
git commit -m "feat(orchestrator): emit boot_progress ladder rungs (T8)"
```

---

## Task 9: shutdown_handler integration — POWEROFF_INVOKED/POWEROFF_RC0 + config timeout

**Files:**
- Modify: `src/pi/hardware/shutdown_handler.py` (`__init__`, `_executeShutdown`:265-335)
- Test: `tests/pi/hardware/test_shutdown_handler_boot_progress.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
# tests/pi/hardware/test_shutdown_handler_boot_progress.py
from unittest.mock import patch, MagicMock
from src.pi.hardware.shutdown_handler import ShutdownHandler


def test_executeShutdown_marksInvokedThenRc0OnSuccess():
    marks = []
    h = ShutdownHandler(suppressLegacyTriggers=True,
                        poweroffTimeoutSeconds=12,
                        bootProgressWriter=lambda s, v: marks.append(s.value))
    with patch("src.pi.hardware.shutdown_handler.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        h._executeShutdown()
        # config timeout threaded through
        assert run.call_args.kwargs["timeout"] == 12
    assert marks == ["POWEROFF_INVOKED", "POWEROFF_RC0"]


def test_executeShutdown_marksInvokedButNotRc0OnFailure():
    marks = []
    h = ShutdownHandler(suppressLegacyTriggers=True,
                        bootProgressWriter=lambda s, v: marks.append(s.value))
    with patch("src.pi.hardware.shutdown_handler.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stderr="auth fail")
        try:
            h._executeShutdown()
        except Exception:
            pass
    assert marks == ["POWEROFF_INVOKED"]  # never reaches RC0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/hardware/test_shutdown_handler_boot_progress.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'poweroffTimeoutSeconds'`

- [ ] **Step 3: Implement**

In `ShutdownHandler.__init__`, add kwargs `poweroffTimeoutSeconds: int = 30` and `bootProgressWriter=None`; store `self._poweroffTimeoutSeconds` and `self._bootProgressWriter` (default lambda → `boot_progress.markMilestone` with current boot id, same helper pattern as Task 8). In `_executeShutdown`:
- Immediately **before** `subprocess.run(['systemctl','poweroff'], ...)` (line ~289): emit `POWEROFF_INVOKED` via a fail-safe `self._markBootProgress(...)` helper (same try/except shape as orchestrator).
- Change `timeout=30` (line 294) → `timeout=self._poweroffTimeoutSeconds`.
- Immediately after `if result.returncode == 0:` (line 314), before the `logger.warning(SHUTDOWN_SUCCESS_MARKER)`: emit `POWEROFF_RC0`.

Production wiring passes `config['pi']['shutdown']['poweroffTimeoutSeconds']` where `ShutdownHandler` is constructed (search the construction site; pass the validated config value).

- [ ] **Step 4: Run test + handler suite**

Run: `pytest tests/pi/hardware/ -m "not slow" -q`
Expected: PASS (new test green; existing handler tests unaffected — they don't pass the new kwargs so defaults preserve behavior)

- [ ] **Step 5: Commit**

```bash
git add src/pi/hardware/shutdown_handler.py tests/pi/hardware/test_shutdown_handler_boot_progress.py
git commit -m "feat(shutdown_handler): POWEROFF_INVOKED/RC0 + config timeout (T9)"
```

---

## Task 10: Strip the journal scan from `boot_reason.py`

**Files:**
- Modify: `src/pi/diagnostics/boot_reason.py`
- Delete: journal-scan tests in `tests/pi/diagnostics/test_boot_reason*.py`
- Test: `tests/pi/diagnostics/test_boot_reason_boot_id.py` (NEW — keeps the surviving helpers covered)

- [ ] **Step 1: Write the failing test (the kept helpers still work; the deleted ones are gone)**

```python
# tests/pi/diagnostics/test_boot_reason_boot_id.py
import src.pi.diagnostics.boot_reason as br


def test_readCurrentBootId_normalizes(tmp_path):
    f = tmp_path / "bid"
    f.write_text("ABCD-1234\n", encoding="ascii")
    assert br.readCurrentBootId(str(f)) == "abcd1234"


def test_journalScanSymbolsRemoved():
    for gone in ("detectBootReason", "_probeLadderGraceful", "_readBootList",
                 "_hasShutdownMarker", "parseListBoots", "runJournalctl",
                 "SHUTDOWN_MARKERS", "LADDER_GRACEFUL_GREP_PATTERN"):
        assert not hasattr(br, gone), f"{gone} should be deleted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_reason_boot_id.py -v`
Expected: FAIL — `test_journalScanSymbolsRemoved` fails (symbols still present)

- [ ] **Step 3: Strip the module**

In `src/pi/diagnostics/boot_reason.py` delete: `runJournalctl`, `parseListBoots`, `_hasShutdownMarker`, `_probeLadderGraceful`, `_readBootList`, `detectBootReason`, `writeStartupLog`, `recordBootReason`, `BootListEntry`, `BootReasonReport`, and constants `JOURNALCTL_TIMEOUT_SECONDS`, `PRIOR_BOOT_TAIL_LINES`, `SHUTDOWN_MARKERS`, `LADDER_GRACEFUL_GREP_PATTERN`, `LADDER_GRACEFUL_PROBE_LIMIT`, `LIST_BOOTS_RETRY_ATTEMPTS`, `LIST_BOOTS_RETRY_SLEEP_SECONDS`, `_LIST_BOOTS_LINE`. Keep: `readCurrentBootId`, `_normalizeBootId`, `BOOT_ID_PATH`. Trim `__all__` to `['BOOT_ID_PATH', '_normalizeBootId', 'readCurrentBootId']`. Add a modification-history row noting "I-037: journal scan removed, replaced by src/pi/diagnostics/boot_progress.py (spec 2026-05-15)". Delete obsolete journal-scan test files: `tests/pi/diagnostics/test_boot_reason.py`, `test_boot_reason_canary.py`, `test_boot_reason_v0276_graceful.py` (and any `test_boot_reason*` that imports the deleted symbols — `git rm` them).

- [ ] **Step 4: Run the diagnostics suite**

Run: `pytest tests/pi/diagnostics/ -m "not slow" -q`
Expected: PASS (boot_id test green; no import errors from deleted symbols anywhere — if any non-test module imported them, repoint it to `boot_progress`)

- [ ] **Step 5: Commit**

```bash
git add src/pi/diagnostics/boot_reason.py tests/pi/diagnostics/
git rm tests/pi/diagnostics/test_boot_reason.py tests/pi/diagnostics/test_boot_reason_canary.py tests/pi/diagnostics/test_boot_reason_v0276_graceful.py
git commit -m "refactor(boot_reason): delete journal scan; keep boot-id helpers (T10)"
```

---

## Task 11: systemd units

**Files:**
- Create: `deploy/boot-progress-finalize.service`
- Create: `deploy/boot-progress-arm.service`
- Test: `tests/pi/diagnostics/test_boot_progress_units.py` (NEW — static unit-file assertions)

- [ ] **Step 1: Write the failing test**

```python
# tests/pi/diagnostics/test_boot_progress_units.py
from pathlib import Path

FIN = Path("deploy/boot-progress-finalize.service").read_text()
ARM = Path("deploy/boot-progress-arm.service").read_text()


def test_finalizer_ordering_and_pythonpath():
    assert "DefaultDependencies=no" in FIN
    assert "After=eclipse-obd.service drain-forensics.service" in FIN
    assert "Before=shutdown.target" in FIN
    assert "RemainAfterExit=yes" in FIN
    assert "ExecStop=" in FIN and "--finalize" in FIN
    # US-277 silent-import guard: PYTHONPATH + WorkingDirectory mandatory
    assert "Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01" in FIN
    assert "WorkingDirectory=/home/mcornelison/Projects/Eclipse-01" in FIN


def test_arm_runs_before_eclipse_obd():
    assert "Before=eclipse-obd.service" in ARM
    assert "--arm" in ARM
    assert "Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01" in ARM
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_progress_units.py -v`
Expected: FAIL — `FileNotFoundError: deploy/boot-progress-finalize.service`

- [ ] **Step 3: Create the unit files**

`deploy/boot-progress-finalize.service`:

```ini
[Unit]
Description=Eclipse OBD shutdown breadcrumb finalizer (honest instrument)
DefaultDependencies=no
After=eclipse-obd.service drain-forensics.service
Before=shutdown.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=mcornelison
WorkingDirectory=/home/mcornelison/Projects/Eclipse-01
Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01
ExecStart=/bin/true
ExecStop=/home/mcornelison/obd2-venv/bin/python -m src.pi.diagnostics.boot_progress --finalize --file /home/mcornelison/Projects/Eclipse-01/data/boot_progress

[Install]
WantedBy=multi-user.target
```

`deploy/boot-progress-arm.service`:

```ini
[Unit]
Description=Eclipse OBD boot-progress arm/reader (honest instrument)
After=local-fs.target
Before=eclipse-obd.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=mcornelison
WorkingDirectory=/home/mcornelison/Projects/Eclipse-01
Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01
ExecStart=/home/mcornelison/obd2-venv/bin/python -m src.pi.diagnostics.boot_progress --arm --file /home/mcornelison/Projects/Eclipse-01/data/boot_progress --db /home/mcornelison/Projects/Eclipse-01/data/obd.db --nas-dir /mnt/projects/O/OBD2v2/boot-progress --nas-enabled

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/diagnostics/test_boot_progress_units.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add deploy/boot-progress-finalize.service deploy/boot-progress-arm.service tests/pi/diagnostics/test_boot_progress_units.py
git commit -m "feat(deploy): boot-progress arm + finalize systemd units (T11)"
```

---

## Task 12: `deploy-pi.sh` install step

**Files:**
- Modify: `deploy/deploy-pi.sh` (add `step_install_boot_progress_units()` after `step_install_orphan_cleanup_unit`; call it where the other unit-install steps are called)
- Test: manual `--dry-run` + `bash -n`

- [ ] **Step 1: Add the step (mirror `step_install_drain_forensics_unit`, deploy-pi.sh:717-800)**

```bash
step_install_boot_progress_units() {
    # Honest instrument (spec 2026-05-15): idempotent sync-if-changed install
    # of boot-progress-finalize.service + boot-progress-arm.service. Mirrors
    # step_install_drain_forensics_unit byte-for-byte. Both units are
    # enabled --now: arm runs at boot (Before=eclipse-obd), finalize must be
    # 'active' so its ExecStop fires at shutdown.
    echo "--- Step: Installing boot-progress systemd units (sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/boot-progress-finalize.service /etc/systemd/system/boot-progress-finalize.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/boot-progress-arm.service /etc/systemd/system/boot-progress-arm.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable --now boot-progress-finalize.service boot-progress-arm.service"
        return 0
    fi
    remote "
        set -e
        SRC_FIN='${PI_PATH}/deploy/boot-progress-finalize.service'
        DST_FIN='/etc/systemd/system/boot-progress-finalize.service'
        SRC_ARM='${PI_PATH}/deploy/boot-progress-arm.service'
        DST_ARM='/etc/systemd/system/boot-progress-arm.service'
        if [ ! -f \"\$SRC_FIN\" ] || [ ! -f \"\$SRC_ARM\" ]; then
            echo 'WARN: boot-progress unit files not present in deploy/ -- skipping.' >&2
            exit 0
        fi
        changed=false
        if sudo test -f \"\$DST_FIN\" && sudo cmp -s \"\$SRC_FIN\" \"\$DST_FIN\"; then
            echo 'boot-progress-finalize.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_FIN\" \"\$DST_FIN\"; echo 'finalize installed.'; changed=true
        fi
        if sudo test -f \"\$DST_ARM\" && sudo cmp -s \"\$SRC_ARM\" \"\$DST_ARM\"; then
            echo 'boot-progress-arm.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_ARM\" \"\$DST_ARM\"; echo 'arm installed.'; changed=true
        fi
        if [ \"\$changed\" = true ]; then
            sudo systemctl daemon-reload; echo 'daemon-reload complete.'
        fi
        sudo systemctl enable --now boot-progress-finalize.service boot-progress-arm.service
        echo 'boot-progress units enabled + active.'
    "
}
```

Add `step_install_boot_progress_units` to the main deploy flow next to the existing `step_install_drain_forensics_unit` / `step_install_orphan_cleanup_unit` call sites (grep for `step_install_orphan_cleanup_unit` in the main body and add the new call immediately after it).

- [ ] **Step 2: Verify syntax + dry-run**

Run: `bash -n deploy/deploy-pi.sh && bash deploy/deploy-pi.sh --dry-run 2>&1 | grep -A2 boot-progress`
Expected: no syntax error; dry-run prints the boot-progress install lines

- [ ] **Step 3: Commit**

```bash
git add deploy/deploy-pi.sh
git commit -m "feat(deploy): step_install_boot_progress_units (T12)"
```

---

## Task 13: Real-chain integration test (the L9 lesson institutionalized)

**Files:**
- Create: `tests/pi/diagnostics/test_boot_progress_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/pi/diagnostics/test_boot_progress_integration.py
"""Real chain: real orchestrator ladder -> real boot_progress file ->
real arm/reader -> verdict. Only the OS edges (poweroff subprocess, file
path, db path) are faked. Had this existed, US-308/330/342 fail at PR."""
import json, sqlite3
from src.pi.diagnostics.boot_progress import markMilestone, arm, Stage
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG


def test_hardCrashAfterPoweroffInvoked_readsBackZero(tmp_path):
    f = str(tmp_path / "boot_progress")
    db = str(tmp_path / "obd.db")
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)

    # Boot N: arm, then drive the real ladder rungs, then SIMULATE A HARD
    # CRASH right after POWEROFF_INVOKED (no CLEAN_COMPLETE ever written).
    markMilestone(Stage.RUNNING, vcell=None, filePath=f, bootId="N")
    for s, v in [(Stage.WARNING, 3.70), (Stage.IMMINENT, 3.55),
                 (Stage.TRIGGER, 3.45), (Stage.DRAIN_CLOSED, 3.45),
                 (Stage.TRIGGER_ROW_WRITTEN, 3.44),
                 (Stage.POWEROFF_INVOKED, 3.44)]:
        markMilestone(s, vcell=v, filePath=f, bootId="N")
    # <-- crash here: process dies, finalizer ExecStop never runs

    # Boot N+1: arm reads the prior trail
    arm(filePath=f, dbPath=db, bootId="N1",
        nasArchiveDir=str(tmp_path / "nas"), nasArchiveEnabled=False)

    row = sqlite3.connect(db).execute(
        "SELECT prior_boot_clean, prior_boot_last_stage, prior_boot_reason "
        "FROM startup_log WHERE boot_id='N1'").fetchone()
    assert row == (0, "POWEROFF_INVOKED", "poweroff_invoked_never_returned")


def test_gracefulShutdown_readsBackOne(tmp_path):
    f = str(tmp_path / "boot_progress")
    db = str(tmp_path / "obd.db")
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)
    markMilestone(Stage.RUNNING, vcell=None, filePath=f, bootId="N")
    for s in [Stage.WARNING, Stage.IMMINENT, Stage.TRIGGER,
              Stage.DRAIN_CLOSED, Stage.TRIGGER_ROW_WRITTEN,
              Stage.POWEROFF_INVOKED, Stage.POWEROFF_RC0,
              Stage.CLEAN_COMPLETE]:
        markMilestone(s, vcell=3.4, filePath=f, bootId="N")
    arm(filePath=f, dbPath=db, bootId="N1",
        nasArchiveDir=str(tmp_path / "n"), nasArchiveEnabled=False)
    row = sqlite3.connect(db).execute(
        "SELECT prior_boot_clean, prior_boot_reason FROM startup_log "
        "WHERE boot_id='N1'").fetchone()
    assert row == (1, "graceful")
```

- [ ] **Step 2: Run it**

Run: `pytest tests/pi/diagnostics/test_boot_progress_integration.py -v`
Expected: PASS (2 passed)

- [ ] **Step 3: Commit**

```bash
git add tests/pi/diagnostics/test_boot_progress_integration.py
git commit -m "test(boot_progress): real-chain integration (L9) (T13)"
```

---

## Task 14: Repoint the US-343 audit script to the shared constant

**Files:**
- Modify: `offices/pm/scripts/audit_historical_drain_canary.py:58-59`
- Test: `tests/pi/diagnostics/test_boot_progress_contract.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/pi/diagnostics/test_boot_progress_contract.py
def test_auditScript_usesSharedSuccessConstant():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "audit", "offices/pm/scripts/audit_historical_drain_canary.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    from src.pi.hardware.shutdown_handler import SHUTDOWN_SUCCESS_MARKER
    # The audit's SUCCESS_MARKER must be a substring of the canonical one
    assert mod.SUCCESS_MARKER in SHUTDOWN_SUCCESS_MARKER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/diagnostics/test_boot_progress_contract.py -k auditScript -v`
Expected: PASS or FAIL depending on current literal — if it passes already, still do Step 3 to make the coupling explicit (import, not a copied literal).

- [ ] **Step 3: Make the coupling explicit**

In `offices/pm/scripts/audit_historical_drain_canary.py` replace the hand-copied literals (lines 58-59) with an import from the canonical source, falling back to the literal only if `src` is not importable in the PM tooling context:

```python
try:
    from src.pi.hardware.shutdown_handler import SHUTDOWN_SUCCESS_MARKER as _SM
    SUCCESS_MARKER = _SM
except Exception:  # noqa: BLE001 -- PM tooling may run outside the venv
    SUCCESS_MARKER = "PowerDownOrchestrator: poweroff accepted by systemd"
INTENT_MARKER = "PowerDownOrchestrator: TRIGGER at"  # historical-only
```

- [ ] **Step 4: Run test + the script dry-run**

Run: `pytest tests/pi/diagnostics/test_boot_progress_contract.py -k auditScript -v && python offices/pm/scripts/audit_historical_drain_canary.py --dry-run`
Expected: PASS; dry-run prints SSH commands without executing

- [ ] **Step 5: Commit**

```bash
git add offices/pm/scripts/audit_historical_drain_canary.py tests/pi/diagnostics/test_boot_progress_contract.py
git commit -m "refactor(audit): couple US-343 to canonical SUCCESS marker (T14)"
```

---

## Task 15: Bench hard-crash drill — Layer-4 runbook + helper (the human gate)

**Files:**
- Create: `docs/runbooks/2026-05-15-bench-hard-crash-drill.md`
- Create: `scripts/bench_crash_drill.sh`

- [ ] **Step 1: Write the helper script**

```bash
#!/usr/bin/env bash
# scripts/bench_crash_drill.sh -- Layer-4 honest-instrument verification.
# Read-only except for the deliberate crash it induces. Run from a host
# with SSH to chi-eclipse-01, Pi on BENCH PSU (not the battery).
# Usage: scripts/bench_crash_drill.sh <crash-after-stage>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../deploy/addresses.sh"
STAGE="${1:?usage: bench_crash_drill.sh <STAGE e.g. POWEROFF_INVOKED>}"
echo "1. Confirm armed:"
ssh "${PI_USER}@${PI_HOST}" "tail -n1 ${PI_PATH}/data/boot_progress || echo NONE"
echo "2. Inducing hard crash after ${STAGE} (sysrq-b -- immediate reboot, no shutdown)..."
echo "   Run on the Pi at the chosen moment:  echo b | sudo tee /proc/sysrq-trigger"
echo "3. After reboot, read the verdict the arm unit wrote:"
echo "   ssh ${PI_USER}@${PI_HOST} \"sqlite3 ${PI_PATH}/data/obd.db \\\"SELECT boot_id,prior_boot_clean,prior_boot_last_stage,prior_boot_reason FROM startup_log ORDER BY recorded_at DESC LIMIT 1;\\\"\""
echo "PASS criteria: prior_boot_clean=0 and prior_boot_reason matches the rung crashed at."
```

- [ ] **Step 2: Write the runbook**

`docs/runbooks/2026-05-15-bench-hard-crash-drill.md` — document, with exact commands: (a) deploy via `deploy-pi.sh`; (b) confirm both units enabled (`systemctl is-enabled boot-progress-arm.service boot-progress-finalize.service`); (c) the three required cases from spec §4.6 acceptance gate — Drain-26-shape crash → `0/poweroff_invoked_never_returned`; real `sudo systemctl poweroff` → `1/graceful`; PSU-yank mid-drive → `0`; (d) the SQL to read the verdict; (e) PASS/FAIL recording table. State explicitly: **the instrument is NOT trusted until all three pass IRL** (this is the human gate the chain kept skipping; per dev-only-sprint-scope, running it is a human action item, not code).

- [ ] **Step 3: Verify + commit**

Run: `bash -n scripts/bench_crash_drill.sh`
Expected: no syntax error

```bash
git add scripts/bench_crash_drill.sh docs/runbooks/2026-05-15-bench-hard-crash-drill.md
git commit -m "docs(runbook): bench hard-crash drill (Layer-4 gate) (T15)"
```

---

## Final verification (before declaring the plan complete)

- [ ] Run full Pi suite: `pytest tests/pi/ -m "not slow" -q` — expected: green, no regressions from the boot_reason strip.
- [ ] Run `pytest tests/common/config/test_validator.py -q` and `python validate_config.py` — expected: green / exit 0.
- [ ] Run `make lint` on touched files only (ruff) — expected: clean.
- [ ] `bash -n deploy/deploy-pi.sh && bash deploy/deploy-pi.sh --dry-run` — expected: boot-progress step prints, no error.
- [ ] Confirm no module still imports the deleted `boot_reason` journal symbols: `rg "detectBootReason|_probeLadderGraceful|SHUTDOWN_MARKERS|recordBootReason" src/` — expected: no hits outside history comments.
- [ ] **Human gate (post-deploy, not code):** the Task-15 bench drill — all three cases pass IRL before the instrument is trusted and before Bug 1 work begins (spec §4.6, §7).

---

## Self-Review (completed by plan author)

- **Spec coverage:** §4.1 core model → T1–T6; §4.2 ladder → T2/T3/T8/T9; §4.3 units → T11/T12; §4.4 reader/verdict/config → T3/T5/T7; §4.5 error handling + boot_reason replacement → T2/T5/T10; §4.6 verification (4 layers) → T1/T3/T6/T13/T15; §5 file plan → all tasks; §6 open items → noted, non-blocking; §7 Bug 1 out of scope → no task, explicitly deferred. No gaps.
- **Placeholder scan:** every code step has complete code; every command has expected output. The one "use the existing orchestrator test fixture" note (T8) is a pointer to real existing infrastructure, with a concrete fallback spelled out — not a placeholder.
- **Type consistency:** `markMilestone(stage, *, vcell, filePath, bootId, maxTrailBytes)`, `readPriorTrail(filePath)`, `deriveVerdict(trail) -> (clean, lastStage, reason)`, `arm(*, filePath, dbPath, bootId, nasArchiveDir, nasArchiveEnabled)`, `finalize(*, filePath, bootId)`, `Stage` enum + `MILESTONE_ORDER` + `CLEAN_COMPLETE_RUNG`, `ensureStartupLogForensicColumns(conn)` — names consistent across T1–T15.
