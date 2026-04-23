################################################################################
# File Name: v0003_us223_drop_battery_log.py
# Purpose/Description: US-223 (TD-031 close) registry migration -- drops the
#                      server-side ``battery_log`` table if it exists.
#                      ``battery_log`` was Pi-only telemetry written by
#                      :class:`BatteryMonitor` (src/pi/power/battery.py) and
#                      was never synced to the server, so on a canonical
#                      server the table never existed.  This migration is
#                      defensive hygiene for any out-of-band dev/debug host
#                      that did create the table manually.  Idempotent: the
#                      DROP uses ``IF EXISTS`` and probes
#                      ``INFORMATION_SCHEMA.TABLES`` first.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex          | Initial -- Sprint 17 US-223 (TD-031 close).
# ================================================================================
################################################################################

"""Migration 0003: drop ``battery_log`` on the server (US-223 / TD-031).

Context
-------
``battery_log`` was a Pi-local health-telemetry table written by the dead
:class:`BatteryMonitor` class in ``src/pi/power/battery.py``.  It was
explicitly excluded from the delta-sync scope (see the historical
``sync_log.IN_SCOPE_TABLES`` comment), so the canonical server MariaDB
never held the table.  US-223 still ships this migration so any
developer or debug server that manually created a ``battery_log`` table
has its residue cleaned up on the next deploy.

Idempotency contract
--------------------
1. :func:`apply` probes ``INFORMATION_SCHEMA.TABLES`` via
   :func:`scripts.apply_server_migrations.serverTableExists`.
2. If the probe returns False, the migration is a no-op (no SQL emitted).
3. If the probe returns True, a ``DROP TABLE IF EXISTS battery_log``
   statement is issued.  Re-running on an already-dropped DB is safe
   because the runner's ``schema_migrations`` bookkeeping records the
   version after first success, AND the ``IF EXISTS`` guard stops the
   DDL from failing on absent tables.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = ['MIGRATION', 'VERSION', 'DESCRIPTION', 'apply']


VERSION: str = '0003'
DESCRIPTION: str = (
    'US-223 / TD-031 close -- drop battery_log (dead Pi-only BatteryMonitor '
    'table; superseded by battery_health_log in US-217)'
)


# Idempotent drop -- the ``IF EXISTS`` is belt-and-suspenders with the
# INFORMATION_SCHEMA probe in :func:`apply` below.
_DROP_BATTERY_LOG: str = 'DROP TABLE IF EXISTS battery_log;'


def apply(ctx: RunnerContext) -> None:
    """Drop ``battery_log`` if it currently exists on the server.

    No-op when the table is absent -- the pre-probe short-circuits so we
    never issue a DDL statement.  Post-condition probe confirms the drop
    actually landed on hosts where the table did exist, guarding against
    silent mysql session-context issues.
    """
    # INFORMATION_SCHEMA probe: skip the DDL entirely on the canonical
    # server where the table never existed.  This keeps the server
    # migration log clean (no DDL-run entries for no-op drops).
    if not serverTableExists(ctx.addrs, ctx.creds, 'battery_log', ctx.runner):
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, _DROP_BATTERY_LOG, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'drop battery_log failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    # Post-condition probe: ensure the DROP actually removed the table
    # before the runner records this version.  Shields future operators
    # from a silent mysql no-op case (wrong default DB, filtered replicas).
    if serverTableExists(ctx.addrs, ctx.creds, 'battery_log', ctx.runner):
        raise SchemaProbeError(
            'battery_log still present after DROP TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
