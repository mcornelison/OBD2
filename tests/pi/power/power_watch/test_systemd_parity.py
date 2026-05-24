################################################################################
# File Name: test_systemd_parity.py
# Purpose/Description: SS-T7 orchestration-proof: the "highest-value gate of
#                      the chain" (Atlas 2026-05-19) -- a DOA tripwire that
#                      runs `python -m src.pi.power.power_watch` as a real
#                      SUBPROCESS with EXACTLY the eclipse-powerwatch unit's
#                      declared dual-path PYTHONPATH (read from the unit file
#                      itself; Pi prefix remapped to the local repo) +
#                      inherited PYTHONPATH overridden so pytest/conftest's
#                      sys.path cannot mask a broken import. Reproduces the
#                      systemd unit's real invocation end-to-end (real
#                      controller/pipeline/task/outcome chain). POSITIVE
#                      execution evidence required (marker file + outcome
#                      record), not absence-of-error -- the structural answer
#                      to "is the code actually wired/running, or just
#                      written?" that V0.27.12 lacked.
# Author: (implementation plan 2026-05-17 / consolidated to SS-T7 2026-05-19)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T8 real systemd-invocation guard.
# 2026-05-19    | Plan SS-T7 | Renamed test_real_invocation.py ->
#                              test_systemd_parity.py to match the SS-T7
#                              canonical filename. The P2-T8 predecessor
#                              already satisfied all of Atlas's SS-T7
#                              substantive criteria (real subprocess; unit's
#                              exact PYTHONPATH; positive marker + outcome
#                              record evidence; stdout/stderr in assertion
#                              messages; Windows-reliable). Consolidation,
#                              not duplication. No production edits.
# ================================================================================
################################################################################
"""SS-T7: systemd-parity orchestration-proof (the DOA tripwire)."""
import json
import os
import subprocess
import sys
from pathlib import Path

# tests/pi/power/power_watch/<this> -> parents[4] == repo root.
REPO = Path(__file__).resolve().parents[4]
PI_PREFIX = "/home/mcornelison/Projects/Eclipse-01"
SVC = (REPO / "deploy/eclipse-powerwatch.service").read_text(encoding="utf-8")


def _unitPythonPath() -> str:
    for line in SVC.splitlines():
        if line.startswith("Environment=PYTHONPATH="):
            return line.split("=", 1)[1].split("PYTHONPATH=", 1)[-1]
    raise AssertionError("eclipse-powerwatch.service has no PYTHONPATH line")


def test_entrypoint_runs_exactly_as_systemd_invokes_it(tmp_path):
    """SS-T7 / Atlas 2026-05-19: the DOA tripwire. Run the entrypoint as
    systemd would: the unit's exact dual-path PYTHONPATH (read FROM the unit
    file -- Pi prefix remapped to the local repo), inherited PYTHONPATH
    overridden so conftest cannot mask a missing module. Deterministic
    PW_TEST_ONESHOT scenario: sync fails transiently twice ->
    SYNC_FAILED_AFTER_RETRY -> a real outcome record is produced and the
    (stubbed) poweroff fires once.

    Positive execution evidence (Atlas criterion #4): both a poweroff
    marker AND an outcome record must EXIST -- absence of an error is
    explicitly NOT accepted as proof. Stdout+stderr captured into the
    assertion error messages (criterion #8) so a future failure tells the
    next reader WHY the chain didn't execute, not just "marker missing."

    Deliberately NOT marked slow -- it must run in the standard gate;
    absence of exactly this kind of test is why V0.27.12 shipped DOA.
    """
    declared = _unitPythonPath().split("=", 1)[-1]
    local_entries = [
        e.replace(PI_PREFIX, str(REPO)) for e in declared.split(":")
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(local_entries)

    db = tmp_path / "obd.db"
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "protocolVersion": "1",
                "schemaVersion": "1",
                "deviceId": "test-device",
                "pi": {"database": {"path": str(db)}},
                "server": {},
            }
        ),
        encoding="utf-8",
    )
    envFile = tmp_path / ".env"
    envFile.write_text("", encoding="utf-8")
    marker = tmp_path / "poweroff.marker"
    env["PW_TEST_ONESHOT"] = "1"
    env["PW_TEST_POWEROFF_MARKER"] = str(marker)

    proc = subprocess.run(
        [
            sys.executable, "-m", "src.pi.power.power_watch",
            "--config", str(cfg), "--env-file", str(envFile),
        ],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=180,
    )
    blob = proc.stdout + proc.stderr
    assert "No module named 'pi'" not in blob, blob
    assert "Traceback (most recent call last)" not in blob, blob
    assert proc.returncode == 0, blob

    # The real outcome-record producer ran (sync_failed_after_retry path).
    outcome = tmp_path / "powerwatch_outcome.json"
    assert outcome.exists(), blob
    rec = json.loads(outcome.read_text(encoding="utf-8"))
    assert rec["kind"] == "sync_failed_after_retry"
    assert rec["task"] == "sync_with_server"

    # The bounded controller reached the (stubbed) poweroff exactly once.
    assert marker.exists(), blob
    assert marker.read_text(encoding="utf-8") == "poweroff-invoked"
