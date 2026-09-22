################################################################################
# File Name: sync_contract.py
# Purpose/Description: The EDR tables in Pi->server sync scope, and the set the
#                      power-loss shutdown drain must NOT carry. Declared once
#                      here so the Pi sync registry, the backlog counter,
#                      powerwatch and the server read one membership. A
#                      declaration only: nothing is wired to it by US-764.
# Author: Rex (US-764)
# Creation Date: 2026-09-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-15    | Rex (US-764) | Initial -- EDR sync scope + shutdown-drain
#               |              | exclusion set (US-734 spec section 5, D5).
# ================================================================================
################################################################################
"""EDR sync-scope membership (US-764, US-734 design).

``EDR_SYNC_TABLES`` names the EDR raw tables that ride the existing id-cursor
delta sync. ``SHUTDOWN_DRAIN_EXCLUDED_TABLES`` is the set powerwatch's
power-loss drain skips: the drain budget is for drive data, and EDR catches up
on the next ordinary sync tick. Every EDR table is in the exclusion set.
"""

from __future__ import annotations

EDR_SYNC_TABLES: tuple[str, ...] = (
    "edr_imu_sample",
    "edr_light_sample",
    # US-805: the PitchFusion-output sibling. It is EDR data on the same
    # terms as the raw tables -- id-cursor delta synced, and skipped by the
    # power-loss drain, whose budget is for drive data.
    "edr_imu_derived",
)

SHUTDOWN_DRAIN_EXCLUDED_TABLES: frozenset[str] = frozenset(EDR_SYNC_TABLES)

__all__ = ["EDR_SYNC_TABLES", "SHUTDOWN_DRAIN_EXCLUDED_TABLES"]
