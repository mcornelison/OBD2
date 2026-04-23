################################################################################
# File Name: v0001_us195_us200_catch_up.py
# Purpose/Description: Retroactive registration of US-209's one-shot DDL
#                      (US-195 data_source + US-200 drive_id/drive_counter
#                      catch-up) under the US-213 migration registry. On a
#                      server that already ran US-209 manually, this runs as a
#                      no-op (scanServerSchema returns a clean state, plan is
#                      empty) and records schema_migrations.version='0001' for
#                      audit traceability. On a fresh server (first deploy
#                      post-US-213), the scan-plan-apply cycle runs normally.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex          | Initial -- Sprint 16 US-213 (TD-029 closure).
# ================================================================================
################################################################################

"""Migration 0001: US-195 data_source + US-200 drive_id/drive_counter catch-up.

Delegates to the US-209 scan-plan-apply helpers in
:mod:`scripts.apply_server_migrations` so the DDL definition lives in exactly
one place.  Idempotent: the planner returns an empty plan on a fully-migrated
DB, in which case ``applyPlan`` is not called.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    applyPlan,
    planMigrations,
    scanServerSchema,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = ['MIGRATION', 'VERSION', 'DESCRIPTION', 'apply']


VERSION: str = '0001'
DESCRIPTION: str = (
    'US-195 data_source + US-200 drive_id / drive_counter catch-up '
    '(retroactive wrapper of scripts/apply_server_migrations.py US-209)'
)


def apply(ctx: RunnerContext) -> None:
    """Scan, plan, and apply the US-209 DDL.  No-op on a fully-migrated DB."""
    state = scanServerSchema(ctx.addrs, ctx.creds, ctx.runner)
    plan = planMigrations(state)
    if plan.isEmpty:
        # Already-migrated: nothing to do.  The caller will still record
        # schema_migrations.version='0001' so operators see it in the audit
        # trail after this story lands.
        return
    applyPlan(ctx.addrs, ctx.creds, ctx.runner, plan)


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
