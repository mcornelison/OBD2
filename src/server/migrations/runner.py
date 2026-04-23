################################################################################
# File Name: runner.py
# Purpose/Description: Server schema migration registry + runner (US-213, closes
#                      TD-029). Every schema-changing story appends a Migration
#                      to ALL_MIGRATIONS. The runner bookkeeps applied versions
#                      in a schema_migrations table on the live MariaDB and
#                      applies pending migrations in order. deploy-server.sh
#                      invokes apply_server_migrations.py --run-all on every
#                      deploy (init AND default flow) so SQLAlchemy model
#                      changes that shipped in a prior story can't silently
#                      diverge the live DB from the code.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex          | Initial -- Sprint 16 US-213 (TD-029 closure,
#               |              | Path B explicit registry).
# ================================================================================
################################################################################

"""Explicit server schema migration registry (US-213 / TD-029 closure).

A single DDL gap in Sprint 14 (US-195 + US-200 model changes that never ran
against live MariaDB) was caught only when the US-205 truncate script halted
on a missing column. US-209 closed the one-shot gap but left the underlying
flow unprotected -- the next schema-touching story would reproduce the bug.
This module is the deploy-time gate: every schema change gets a numbered
migration module under :mod:`src.server.migrations.versions`, which is
appended to :data:`src.server.migrations.ALL_MIGRATIONS`. On every deploy,
:func:`MigrationRunner.runAll` walks the registry, skipping versions already
recorded in ``schema_migrations`` and applying the remainder in order.

Design choices (documented for future agents):

* **Explicit registry over Alembic.**  Path B in TD-029 -- matches CIO's
  "single deploy script, keep it simple" directive, zero new runtime
  dependencies, same style as :mod:`src.pi.obdii.data_source` /
  :mod:`src.pi.obdii.drive_id` Pi-side ``ensure*`` idempotent migrations.
* **Per-migration idempotency is the migration author's responsibility.**
  The runner guarantees "apply once" by recording the version after success;
  it does NOT inspect schema state.  Migration ``apply`` functions should
  probe INFORMATION_SCHEMA (see :mod:`scripts.apply_server_migrations`
  helpers) so a stray re-run on an already-migrated DB is safe.
* **No rollback machinery.**  MariaDB DDL is implicit-commit so a mid-plan
  failure leaves the DB in a partial state.  The operator restores from
  the mysqldump backup taken by the individual migration (or by ``--run-all``
  in a future enhancement) and re-runs after fixing the underlying cause.
* **HARD fail on migration failure.**  :func:`MigrationRunner.runAll`
  propagates the exception; ``deploy-server.sh`` runs under ``set -e`` so
  the deploy halts before the service restart.  No half-deployed state.

Usage::

    from src.server.migrations import ALL_MIGRATIONS, MigrationRunner
    from scripts.apply_server_migrations import (
        loadAddresses, loadServerCreds, _defaultRunner,
    )
    addrs = loadAddresses(Path('deploy/addresses.sh'))
    creds = loadServerCreds(addrs)
    ctx = RunnerContext(addrs=addrs, creds=creds, runner=_defaultRunner)
    runner = MigrationRunner(ALL_MIGRATIONS)
    report = runner.runAll(ctx)
    print(f'applied {len(report.applied)} new migration(s)')
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
)

if TYPE_CHECKING:
    from scripts.apply_server_migrations import (
        CommandRunner,
        HostAddresses,
        ServerCreds,
    )

__all__ = [
    'SCHEMA_MIGRATIONS_TABLE',
    'SCHEMA_MIGRATIONS_TABLE_DDL',
    'Migration',
    'MigrationRunner',
    'RegistryError',
    'RunReport',
    'RunnerContext',
]


# ================================================================================
# Tracking-table constants
# ================================================================================

SCHEMA_MIGRATIONS_TABLE: str = 'schema_migrations'

# version         -- primary key; string so migrations can adopt any naming
#                    convention (0001, 2026_04_21_01, alembic-style, etc.)
# description     -- human-readable, matches the Migration.description field
# applied_at      -- server-side timestamp; defaults to CURRENT_TIMESTAMP
SCHEMA_MIGRATIONS_TABLE_DDL: str = (
    f'CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATIONS_TABLE} ('
    '    version VARCHAR(64) NOT NULL PRIMARY KEY,'
    '    description VARCHAR(512) NOT NULL,'
    '    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP'
    ')'
)


# ================================================================================
# Exceptions (registry-local; execution errors reuse asm.MigrationError)
# ================================================================================

class RegistryError(MigrationError):
    """Raised when the migration registry itself is malformed (duplicate versions)."""


# ================================================================================
# Migration + RunnerContext + RunReport dataclasses
# ================================================================================

MigrationApplyFn = Callable[['RunnerContext'], None]


@dataclass(slots=True)
class RunnerContext:
    """Bundle of addresses, creds, and command runner passed to apply functions."""

    addrs: HostAddresses
    creds: ServerCreds
    runner: CommandRunner


@dataclass(frozen=True, slots=True)
class Migration:
    """One versioned schema migration.

    * ``version`` -- unique string identifier; sort-order defines application
      order (e.g., ``'0001'`` before ``'0002'``).
    * ``description`` -- short human-readable summary; written to the
      schema_migrations row for later audit.
    * ``applyFn`` -- callable taking a :class:`RunnerContext`; must be
      idempotent (safe to re-run on a fully-migrated DB without side effects)
      because future safety re-runs may replay it.  Raise
      :class:`MigrationError` from ``scripts.apply_server_migrations`` on
      failure; anything else propagates as an unexpected system error.
    """

    version: str
    description: str
    applyFn: MigrationApplyFn


@dataclass(slots=True)
class RunReport:
    """Outcome of a :meth:`MigrationRunner.runAll` invocation."""

    applied: list[str] = field(default_factory=list)
    alreadyApplied: list[str] = field(default_factory=list)

    @property
    def isEmpty(self) -> bool:
        """True when no NEW migrations were applied this run (idempotent no-op)."""
        return len(self.applied) == 0


# ================================================================================
# MigrationRunner
# ================================================================================

class MigrationRunner:
    """Bookkeep applied migrations and apply the pending set in order."""

    def __init__(self, migrations: Sequence[Migration]) -> None:
        self._migrations = tuple(migrations)
        self._validateVersions()

    def _validateVersions(self) -> None:
        seen: set[str] = set()
        for m in self._migrations:
            if m.version in seen:
                raise RegistryError(
                    f'duplicate migration version: {m.version!r}',
                )
            seen.add(m.version)

    # -- bookkeeping ---------------------------------------------------------

    def ensureTracking(self, ctx: RunnerContext) -> None:
        """Create ``schema_migrations`` if missing (idempotent)."""
        res = _runServerSql(
            ctx.addrs, ctx.creds, SCHEMA_MIGRATIONS_TABLE_DDL + ';', ctx.runner,
        )
        if res.returncode != 0:
            raise SchemaProbeError(
                f'ensure {SCHEMA_MIGRATIONS_TABLE} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    def getApplied(self, ctx: RunnerContext) -> set[str]:
        """Return the set of version strings currently recorded as applied."""
        sql = f'SELECT version FROM {SCHEMA_MIGRATIONS_TABLE};'
        res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
        if res.returncode != 0:
            raise SchemaProbeError(
                f'read {SCHEMA_MIGRATIONS_TABLE} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )
        return {
            line.strip()
            for line in res.stdout.splitlines()
            if line.strip()
        }

    def _recordApplied(self, ctx: RunnerContext, migration: Migration) -> None:
        # Double single quotes -- MariaDB / ANSI SQL string-literal escape.
        # Defence-in-depth: description + version are author-controlled, but
        # we apply the escape anyway so the runner can never be the injection
        # site if a future migration author leaves a stray apostrophe.
        safeVer = migration.version.replace("'", "''")
        safeDesc = migration.description.replace("'", "''")
        sql = (
            f'INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, description) '
            f"VALUES ('{safeVer}', '{safeDesc}');"
        )
        res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'record {migration.version!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # -- planning ------------------------------------------------------------

    def planPending(self, applied: set[str]) -> list[Migration]:
        """Return ALL_MIGRATIONS entries whose version is not in ``applied``.

        Preserves registry order so callers can apply sequentially.
        """
        return [m for m in self._migrations if m.version not in applied]

    # -- orchestration -------------------------------------------------------

    def runAll(self, ctx: RunnerContext) -> RunReport:
        """Ensure the tracking table exists, then apply every pending migration.

        Halts on the first failure.  On success, the applied version is
        recorded immediately -- partial success is observable in
        schema_migrations for post-mortem.
        """
        self.ensureTracking(ctx)
        applied = self.getApplied(ctx)
        report = RunReport(alreadyApplied=sorted(applied))
        pending = self.planPending(applied)
        for m in pending:
            m.applyFn(ctx)
            self._recordApplied(ctx, m)
            report.applied.append(m.version)
        return report
