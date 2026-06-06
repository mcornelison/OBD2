################################################################################
# File Name: test_sync_log_dtc_freeze_frame.py
# Purpose/Description: Sprint 43 V0.28.0 (US-369 / F-109) -- the Pi-side
#                      dtc_freeze_frame capture table must be registered in the
#                      sync_log delta-sync registry so MIL_ON freeze-frames are
#                      pushed to the server.  US-368 created the table but left
#                      it out of PK_COLUMN; US-369 wires it in.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-369) | Initial -- dtc_freeze_frame delta-sync
#               |              | registration.
# ================================================================================
################################################################################

"""US-369 / F-109: Pi-side dtc_freeze_frame delta-sync registration.

The freeze-frame is an append-only capture table with an integer ``id`` PK, so
it joins the delta-by-PK sync set exactly like ``dtc_log``.  These tests pin
the registry entries so a future refactor cannot silently drop the table from
the sync sweep (the V0.27.18 class of "captured but never synced" defects).
"""

from __future__ import annotations

from src.pi.data import sync_log


def test_dtcFreezeFrame_inPkColumn_withIntegerIdPk():
    """dtc_freeze_frame registers with the canonical integer ``id`` PK."""
    assert sync_log.PK_COLUMN.get("dtc_freeze_frame") == "id"


def test_dtcFreezeFrame_inDeltaSyncTables():
    """The table is delta-eligible (append-only event stream)."""
    assert "dtc_freeze_frame" in sync_log.DELTA_SYNC_TABLES


def test_dtcFreezeFrame_inInScopeTables():
    """It rides the in-scope union the server payload whitelist trusts."""
    assert "dtc_freeze_frame" in sync_log.IN_SCOPE_TABLES


def test_dtcFreezeFrame_notSnapshotTable():
    """It is NOT a snapshot/upsert table -- delta-by-PK applies."""
    assert "dtc_freeze_frame" not in sync_log.SNAPSHOT_TABLES
