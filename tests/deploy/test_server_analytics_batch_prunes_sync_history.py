################################################################################
# File Name: test_server_analytics_batch_prunes_sync_history.py
# Purpose/Description: US-418 -- the nightly analytics batch prunes
#   sync_history FIRST, and a prune failure cannot stop the recompute.
#   (CIO 2026-10-08: retention lives inside the nightly batch.)
# Author: Atlas (Architect)
# Creation Date: 2026-10-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-08    | Atlas (US-418)| Initial.
# ================================================================================
################################################################################

"""US-418: the batch unit's ExecStart order and failure isolation."""

from __future__ import annotations

from pathlib import Path

UNIT = Path(__file__).resolve().parents[2] / "deploy" / "server-analytics-batch.service"
PRUNE = "-m src.server.cli.prune_sync_history"
RECOMPUTE = "-m src.server.cli.recompute_drive_analytics --all-stale"


def _execStarts() -> list[str]:
    return [
        line.split("=", 1)[1].strip()
        for line in UNIT.read_text(encoding="utf-8").splitlines()
        if line.startswith("ExecStart=")
    ]


def test_thePruneRunsFirst_thenTheRecompute() -> None:
    starts = _execStarts()
    assert len(starts) == 2, starts
    assert PRUNE in starts[0]
    assert RECOMPUTE in starts[1]


def test_aPruneFailureCannotSkipTheRecompute() -> None:
    # systemd: a leading '-' ignores the command's failure, so a oneshot
    # carries on to the next ExecStart. The prune's own journal line is the
    # failure record (US-840: the unit status proves nothing either way).
    prune, recompute = _execStarts()
    assert prune.startswith("-"), prune
    assert not recompute.startswith("-"), recompute


def test_bothStepsUseTheSameInterpreter() -> None:
    prune, recompute = _execStarts()
    assert prune.lstrip("-").split()[0] == recompute.split()[0]
