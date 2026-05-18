################################################################################
# File Name: test_outcome.py
# Purpose/Description: Tests: power_watch outcome-record producer is typed,
#                      atomic, and never raises on a draining Pi.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T2 outcome producer tests.
# ================================================================================
################################################################################
"""Tests: power_watch outcome producer (typed, atomic, never raises)."""
import json
import logging

from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.outcome import writeOutcomeRecord


def test_writes_typed_record(tmp_path):
    p = tmp_path / "powerwatch_outcome.json"
    writeOutcomeRecord(str(p), OutcomeKind.REAL_ERROR, detail="boom", task="sync_with_server")
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert rec["kind"] == "real_error"
    assert rec["detail"] == "boom"
    assert rec["task"] == "sync_with_server"
    assert rec["schema"] == 1 and "ts" in rec


def test_never_raises_on_unwritable_path(caplog):
    caplog.set_level(logging.WARNING)
    writeOutcomeRecord("/proc/cpuinfo/nope/x.json", OutcomeKind.REAL_ERROR, detail="d", task="t")
    assert any("powerwatch outcome" in r.message for r in caplog.records)
