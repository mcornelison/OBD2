################################################################################
# File Name: clear_gate_cases.py
# Purpose/Description: US-919 [F-161] -- the ONE shared case table for the DTC
#   clear gate. DATA ONLY: each row is the gate's inputs (codes, the Mode 07
#   read time, the sync ack, the session lock) and the reason every copy of the
#   gate must answer. The SAME rows are run through dtc_emitter._computeClearGate
#   and dtc_clear.evaluateClearGate (tests/pi/splash/test_clear_gate_one_predicate.py)
#   and through carousel.js clearGateReason via the node probe
#   (tests/ui/test_clear_gate_one_predicate.py), so the three copies cannot drift.
#
#   The predicate (Atlas RULED 2026-10-20 Q2/Q3): relevant = status in
#   {stored, pending} AND severity != 'na'; a code both stored and pending counts
#   once. The chain (Atlas Q4, order per Atlas REVIEW 2026-10-20 G2):
#   no_codes -> severity_present -> severity_unknown -> pending_not_read ->
#   sync_pending -> session_locked -> ok.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-21    | Ralph (Rex)  | Initial -- US-919 one predicate, one table.
# ================================================================================
################################################################################

"""US-919: the shared clear-gate case table (data only, no test functions)."""

from __future__ import annotations

from typing import Any

# A Mode 07 read time ("pending set was read"). The value is the story's own
# example (sprint 111 US-919 examples[0]); only its non-null-ness is gated.
READ_TS = "2026-10-20T19:00:00Z"


def _code(code: str, status: str, severity: str | None, *, logged: bool = True) -> dict:
    return {"code": code, "status": status, "severity": severity, "logged": logged}


# Each row: id, codes (status/severity/logged per code), syncAcked (applied to
# every code), pendingCheckedAtTs, sessionResetLock, expected reason.
CLEAR_GATE_CASES: list[dict[str, Any]] = [
    # --- nothing relevant -------------------------------------------------
    {"id": "empty", "codes": [], "syncAcked": True,
     "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "no_codes"},
    {"id": "empty_pendingUnread", "codes": [], "syncAcked": True,
     "pendingCheckedAtTs": None, "lock": [], "expected": "no_codes"},
    {"id": "pendingNaOnly", "codes": [_code("P1750", "pending", "na")], "syncAcked": True,
     "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "no_codes"},
    {"id": "storedNaAndPendingNa_unread",
     "codes": [_code("P1750", "stored", "na"), _code("P1751", "pending", "na")],
     "syncAcked": True, "pendingCheckedAtTs": None, "lock": [], "expected": "no_codes"},
    # --- stored -----------------------------------------------------------
    {"id": "storedMinor", "codes": [_code("P0443", "stored", "minor")], "syncAcked": True,
     "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "ok"},
    {"id": "storedWatch", "codes": [_code("P0400", "stored", "watch")], "syncAcked": True,
     "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "severity_present"},
    {"id": "storedStop", "codes": [_code("P0301", "stored", "stop")], "syncAcked": True,
     "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "severity_present"},
    {"id": "storedUnrated", "codes": [_code("P0300", "stored", "unknown")], "syncAcked": True,
     "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "severity_unknown"},
    {"id": "storedNaBesideMinor",
     "codes": [_code("P1750", "stored", "na"), _code("P0443", "stored", "minor")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "ok"},
    # --- pending ----------------------------------------------------------
    {"id": "pendingOnlyMinor", "codes": [_code("P0443", "pending", "minor")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "ok"},
    {"id": "pendingOnlyWatch", "codes": [_code("P0400", "pending", "watch")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": [],
     "expected": "severity_present"},
    {"id": "pendingOnlyUnrated", "codes": [_code("P0300", "pending", "unknown")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": [],
     "expected": "severity_unknown"},
    {"id": "storedNaBesidePendingWatch",
     "codes": [_code("P1750", "stored", "na"), _code("P0400", "pending", "watch")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": [],
     "expected": "severity_present"},
    # --- both -------------------------------------------------------------
    {"id": "storedMinorPlusPendingWatch",
     "codes": [_code("P0443", "stored", "minor"), _code("P0400", "pending", "watch")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": [],
     "expected": "severity_present"},
    {"id": "sameCodeStoredAndPending",
     "codes": [_code("P0443", "stored", "minor"), _code("P0443", "pending", "minor")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "ok"},
    # --- pending not read (after every permanent reason, before sync) ------
    {"id": "storedMinor_pendingUnread", "codes": [_code("P0443", "stored", "minor")],
     "syncAcked": True, "pendingCheckedAtTs": None, "lock": [],
     "expected": "pending_not_read"},
    {"id": "storedWatch_pendingUnread", "codes": [_code("P0400", "stored", "watch")],
     "syncAcked": True, "pendingCheckedAtTs": None, "lock": [],
     "expected": "severity_present"},
    {"id": "storedUnrated_pendingUnread", "codes": [_code("P0300", "stored", "unknown")],
     "syncAcked": True, "pendingCheckedAtTs": None, "lock": [],
     "expected": "severity_unknown"},
    {"id": "storedMinorUnsynced_pendingUnread",
     "codes": [_code("P0443", "stored", "minor")], "syncAcked": False,
     "pendingCheckedAtTs": None, "lock": [], "expected": "pending_not_read"},
    {"id": "storedMinorLocked_pendingUnread", "codes": [_code("P0443", "stored", "minor")],
     "syncAcked": True, "pendingCheckedAtTs": None, "lock": ["P0443"],
     "expected": "pending_not_read"},
    # --- unsynced ---------------------------------------------------------
    {"id": "storedMinorUnsynced", "codes": [_code("P0443", "stored", "minor")],
     "syncAcked": False, "pendingCheckedAtTs": READ_TS, "lock": [],
     "expected": "sync_pending"},
    {"id": "storedMinorUnlogged",
     "codes": [_code("P0443", "stored", "minor", logged=False)], "syncAcked": True,
     "pendingCheckedAtTs": READ_TS, "lock": [], "expected": "sync_pending"},
    {"id": "pendingOnlyMinorUnsynced", "codes": [_code("P0443", "pending", "minor")],
     "syncAcked": False, "pendingCheckedAtTs": READ_TS, "lock": [],
     "expected": "sync_pending"},
    {"id": "storedMinorUnsyncedLocked", "codes": [_code("P0443", "stored", "minor")],
     "syncAcked": False, "pendingCheckedAtTs": READ_TS, "lock": ["P0443"],
     "expected": "sync_pending"},
    # --- locked -----------------------------------------------------------
    {"id": "storedMinorLocked", "codes": [_code("P0443", "stored", "minor")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": ["P0443"],
     "expected": "session_locked"},
    {"id": "pendingMinorLocked", "codes": [_code("P0442", "pending", "minor")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": ["P0442"],
     "expected": "session_locked"},
    {"id": "lockOnAnotherCode", "codes": [_code("P0443", "stored", "minor")],
     "syncAcked": True, "pendingCheckedAtTs": READ_TS, "lock": ["P0400"],
     "expected": "ok"},
]
