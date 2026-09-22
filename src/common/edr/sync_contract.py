################################################################################
# File Name: sync_contract.py
# Purpose/Description: The EDR tables in Pi->server sync scope, and the set the
#                      power-loss shutdown drain must NOT carry. Declared once
#                      here so the Pi sync registry, the backlog counter,
#                      powerwatch and the server read one membership.
#                      CONSUMED IN PRODUCTION -- see the docstring below.
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
# 2026-09-22    | Rex (US-773) | Docs only: the "nothing is wired to it" claim
#               |              | was stale -- three modules import this now.
# ================================================================================
################################################################################
"""EDR sync-scope membership (US-764, US-734 design).

``EDR_SYNC_TABLES`` names the EDR raw tables that ride the existing id-cursor
delta sync. ``SHUTDOWN_DRAIN_EXCLUDED_TABLES`` is the set powerwatch's
power-loss drain skips: the drain budget is for drive data, and EDR catches up
on the next ordinary sync tick. Every EDR table is in the exclusion set.

US-773 removed US-764's "a declaration only: nothing is wired to it" note. It
IS wired: ``server_ddl.py`` generates the MariaDB DDL from it,
``power_watch/__main__.py`` reads the exclusion at both drain call sites, and
migration ``v0026_us765_edr_raw_tables.py`` builds the server tables from it.
Everything else about this contract -- the why, the tiers, the status of each
story -- lives in ``specs/architecture.md`` section 10.8.3 and is deliberately
not restated here (Rule 4: one fact, one home).
"""

from __future__ import annotations

EDR_SYNC_TABLES: tuple[str, ...] = ("edr_imu_sample", "edr_light_sample")

SHUTDOWN_DRAIN_EXCLUDED_TABLES: frozenset[str] = frozenset(EDR_SYNC_TABLES)

__all__ = ["EDR_SYNC_TABLES", "SHUTDOWN_DRAIN_EXCLUDED_TABLES"]
