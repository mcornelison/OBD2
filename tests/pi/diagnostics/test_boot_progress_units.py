################################################################################
# File Name: test_boot_progress_units.py
# Purpose/Description: Static + production-invocation checks on the boot-progress
#                      systemd unit files.  Statics: shutdown-finalizer ordering,
#                      mandatory dual-path PYTHONPATH (repo root AND <repo>/src),
#                      arm-before-eclipse-obd, no invalid Pi-side --nas-enabled.
#                      Dynamic: run `python -m src.pi.diagnostics.boot_progress
#                      --arm` as a subprocess with EXACTLY the arm unit's
#                      declared PYTHONPATH (no pytest/conftest sys.path leak) --
#                      the test that would have caught the V0.27.12 DOA.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- T11 unit-file static checks.
# 2026-05-17    | Plan    | V0.27.12-DOA hotfix: tighten PYTHONPATH asserts to
#                           REQUIRE <repo>/src (old substring assert passed the
#                           broken unit); assert no --nas-enabled on the Pi arm
#                           unit; add the real --arm production-invocation
#                           subprocess guard that reproduces the systemd unit's
#                           exact env -- the test that would have caught the
#                           `ModuleNotFoundError: No module named 'pi'` DOA.
# ================================================================================
################################################################################
"""Static + production-invocation checks for the boot-progress systemd units."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG

# Repo root: tests/pi/diagnostics/<this> -> parents[3] == repo root.
REPO = Path(__file__).resolve().parents[3]
# The Pi-side repo prefix the unit files hardcode (deployed layout).
PI_PREFIX = "/home/mcornelison/Projects/Eclipse-01"

FIN = (REPO / "deploy/boot-progress-finalize.service").read_text(encoding="utf-8")
ARM = (REPO / "deploy/boot-progress-arm.service").read_text(encoding="utf-8")

# The corrected, mandatory dual-path PYTHONPATH (repo root AND <repo>/src).
# This is the V0.27.12-DOA root-cause fix: the project-wide bare `from pi.X`
# convention (mirrors src/pi/main.py:47-57 / tests/conftest) needs <repo>/src
# on the path; `python -m src.pi...` needs the repo root. BOTH, or the arm
# import chain raises `No module named 'pi'`.
REQUIRED_PYTHONPATH = (
    f"Environment=PYTHONPATH={PI_PREFIX}:{PI_PREFIX}/src"
)


def _pythonPathLine(unitText: str) -> str:
    for line in unitText.splitlines():
        if line.startswith("Environment=PYTHONPATH="):
            return line.strip()
    raise AssertionError("unit has no Environment=PYTHONPATH= line")


def _execLine(unitText: str, key: str) -> str:
    """Return the ExecStart=/ExecStop= invocation line (NOT comment text --
    explanatory `#` comments may legitimately mention removed flags/paths)."""
    for line in unitText.splitlines():
        if line.startswith(key):
            return line.strip()
    raise AssertionError(f"unit has no {key} line")


def test_finalizer_ordering_and_dualpath_pythonpath():
    assert "DefaultDependencies=no" in FIN
    assert "After=eclipse-obd.service drain-forensics.service" in FIN
    assert "Before=shutdown.target" in FIN
    assert "RemainAfterExit=yes" in FIN
    assert "ExecStop=" in FIN and "--finalize" in FIN
    assert "WorkingDirectory=" + PI_PREFIX in FIN
    # MUST be the dual-path value, not repo-root-only (regression guard).
    assert _pythonPathLine(FIN) == REQUIRED_PYTHONPATH


def test_arm_before_eclipse_obd_dualpath_and_no_nas():
    assert "Before=eclipse-obd.service" in ARM
    assert _pythonPathLine(ARM) == REQUIRED_PYTHONPATH
    arm_exec = _execLine(ARM, "ExecStart=")
    assert "--arm" in arm_exec
    # /mnt/projects/O is a Chi-srv-01-only mount, unreachable from the Pi:
    # the arm INVOCATION must not pass --nas-enabled or that path (CIO
    # 2026-05-17). Explanatory `#` comments may still mention them.
    assert "--nas-enabled" not in arm_exec
    assert "/mnt/projects" not in arm_exec


def test_arm_real_production_invocation(tmp_path):
    """Run `python -m src.pi.diagnostics.boot_progress --arm` as a SUBPROCESS
    with EXACTLY the arm unit's declared PYTHONPATH (Pi prefix remapped to the
    local repo), explicitly overriding any inherited PYTHONPATH so pytest /
    conftest's sys.path cannot mask the failure.  This reproduces the systemd
    unit's real invocation -- it fails (ModuleNotFoundError: No module named
    'pi') against the pre-hotfix repo-root-only PYTHONPATH, and proves Spool's
    "one fix closes both": once the import chain resolves,
    ensureStartupLogForensicColumns runs and the forensic columns appear.

    Deliberately NOT marked slow -- it must run in the standard gate; absence
    of exactly this test is why the DOA shipped.
    """
    # Remap the unit's Pi-absolute PYTHONPATH entries to the local repo.
    declared = _pythonPathLine(ARM).split("=", 1)[1]
    local_entries = [
        e.replace(PI_PREFIX, str(REPO)) for e in declared.split(":")
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(local_entries)

    db = tmp_path / "obd.db"
    seed = sqlite3.connect(db)
    seed.executescript(SCHEMA_STARTUP_LOG)
    seed.close()
    trail = tmp_path / "boot_progress"

    proc = subprocess.run(
        [sys.executable, "-m", "src.pi.diagnostics.boot_progress", "--arm",
         "--file", str(trail), "--db", str(db)],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=180,
    )
    blob = proc.stdout + proc.stderr
    assert "No module named 'pi'" not in blob, blob
    assert "startup_log write failed" not in blob, blob
    assert proc.returncode == 0, blob

    # Spool's "one fix closes both": the schema migration only runs if the
    # import chain resolved -> the forensic columns must now exist + a row.
    conn = sqlite3.connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(startup_log)")}
        rows = conn.execute("SELECT COUNT(*) FROM startup_log").fetchone()[0]
    finally:
        conn.close()
    assert {"prior_boot_last_stage", "prior_boot_reason"} <= cols, cols
    assert rows >= 1
