################################################################################
# File Name: test_sync_vehicle_info_ecu_preserve.py
# Purpose/Description: Sprint 43 V0.28.0 (US-365 / F-108) -- assert the
#                      server-only vehicle_info ECU-lineage columns are in
#                      sync.py::_PRESERVE_ON_UPDATE so a Pi sync upsert can
#                      never clobber them (matches the drive_summary §10.7
#                      _PRESERVE_ON_UPDATE pattern).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-365) | Initial -- preserve ECU columns on Pi-sync.
# ================================================================================
################################################################################

"""US-365 / F-108: vehicle_info ECU columns survive Pi-sync upserts.

The Pi never sends the ECU-lineage columns (its vehicle_info schema is
unchanged -- only VIN-decoded columns).  Adding them to
``sync.py::_PRESERVE_ON_UPDATE`` is the defensive belt-and-braces fix per
US-365 conditionalOutcome: even if a regression ever put an ECU column in a
Pi payload, the server upsert's ``on_duplicate_key_update`` excludes preserved
columns, so the server-authored ECU lineage is never overwritten.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from src.server.api.sync import _PRESERVE_ON_UPDATE  # noqa: E402


class TestVehicleInfoEcuColumnsPreserved:
    """Every server-only ECU column is preserved across a sync upsert."""

    @pytest.mark.parametrize(
        "column",
        [
            "ecu_signature",
            "cal_signature",
            "ecu_install_timestamp_utc",
            "ecu_removal_timestamp_utc",
            "notes",
            "ecu_active_marker",
        ],
    )
    def test_ecuColumnIsPreserved(self, column: str) -> None:
        assert column in _PRESERVE_ON_UPDATE, (
            f"{column!r} must be in _PRESERVE_ON_UPDATE so a Pi sync upsert "
            f"cannot clobber the server-authored ECU lineage"
        )

    def test_preExistingPreservedColumnsStillPresent(self) -> None:
        """The original sync-key preserved columns are not lost (additive)."""
        for column in ("id", "source_id", "source_device", "synced_at"):
            assert column in _PRESERVE_ON_UPDATE
