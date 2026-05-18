################################################################################
# File Name: test_units.py
# Purpose/Description: Static guard on the eclipse-powerwatch systemd unit:
#                      the mandatory dual-path PYTHONPATH (repo root AND
#                      <repo>/src -- the V0.27.12-DOA root cause), the
#                      module entrypoint, the run user, and Restart=always.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T6 eclipse-powerwatch unit static guard.
# ================================================================================
################################################################################
"""Static checks for the eclipse-powerwatch systemd unit file."""
from pathlib import Path

# tests/pi/power/power_watch/<this> -> parents[4] == repo root.
REPO = Path(__file__).resolve().parents[4]
PI = "/home/mcornelison/Projects/Eclipse-01"
SVC = (REPO / "deploy/eclipse-powerwatch.service").read_text(encoding="utf-8")


def test_dualpath_pythonpath_and_entrypoint():
    # The V0.27.12-DOA root cause: PYTHONPATH must be repo root AND <repo>/src.
    assert f"Environment=PYTHONPATH={PI}:{PI}/src" in SVC
    assert f"WorkingDirectory={PI}" in SVC
    assert "ExecStart=" in SVC and "-m src.pi.power.power_watch" in SVC
    assert "User=mcornelison" in SVC
    assert "Restart=always" in SVC  # a watcher that dies must come back
