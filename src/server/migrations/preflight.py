################################################################################
# File Name: preflight.py
# Purpose/Description: US-462 (F-104 / A-10) applied-schema FK topology preflight.
#                      A-10 ORM-vs-live-DB drift -- the ORM/migration declares a
#                      foreign key the deployed MariaDB never actually got -- has
#                      now shipped THREE times (BL-018/019/020).  US-461 made
#                      v0022 survive it defensively; this guard is the tripwire:
#                      a deploy-preflight that asserts the APPLIED FK topology
#                      (information_schema.KEY_COLUMN_USAGE, NEVER create_all /
#                      ORM-metadata -- the US-459 theater trap) and fails the
#                      deploy fast with a message naming the table + column +
#                      expected FK target, instead of surfacing mid-migration.
#
#                      Wired into scripts.apply_server_migrations.runRegistry
#                      BEFORE the migration set.  The expected FK set is gated by
#                      the applied-migration ledger (schema_migrations): a
#                      still-pending migration's own output FK is not required
#                      yet, so the BL-020 resume-deploy (v0022 pending) is not
#                      deadlocked -- the guard fires only when an ALREADY-applied
#                      migration's promised topology has regressed.  When MariaDB
#                      is unreachable (the Windows bench), it SKIPS HONESTLY --
#                      never a false pass over an un-probed DB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-13    | Rex (US-462) | Initial -- applied-schema FK topology preflight.
# ================================================================================
################################################################################

"""Applied-schema drive-identity FK preflight (US-462 / F-104, Atlas Q3).

The guard asserts that the drive-identity foreign keys the collapse migrations
promised (``drive_statistics.summary_id`` + ``drive_derived_signals.summary_id``
-> ``drives.drive_id``) actually exist on the DEPLOYED MariaDB, read from
``information_schema`` -- never from ``create_all`` / SQLAlchemy metadata, which
already agrees with the migration and would ship GREEN over the broken live DB
(the exact A-10 drift that shipped 3x: BL-018/019/020).

Define-once: the expected FK registry and the applied-schema probe are built
directly on :mod:`v0022_us451_drive_identity_collapse`'s own constants +
``_fkNameReferencing`` KEY_COLUMN_USAGE query, so a future FK rename or probe
change trips one place instead of silently drifting the guard from the migration.

Wiring semantics (why the ledger gate):

* The guard runs BEFORE the migration set in ``runRegistry``.
* v0022 is the migration that *creates* these FKs.  On the BL-020 resume-deploy
  (``schema_migrations`` = 0021, v0022 still pending) the FKs legitimately do
  NOT exist yet -- requiring them would deadlock the very deploy that reconciles
  the drift.  So the expected set is filtered to FKs whose ``sourceVersion`` is
  already recorded applied: the guard asserts only what a *completed* migration
  promised, making it a true regression tripwire (fires when an applied
  migration's topology later vanishes) rather than a precondition that blocks
  forward progress.
* Unreachable MariaDB -> honest skip (the guard never claims GREEN over a DB it
  did not probe; ``runAll`` will itself fail loudly if the DB is truly needed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts.apply_server_migrations import MigrationError, _runServerSql
from src.server.db.models import DRIVES_TABLE
from src.server.migrations.versions import (
    v0022_us451_drive_identity_collapse as m0022,
)

if TYPE_CHECKING:
    from src.server.migrations.runner import MigrationRunner, RunnerContext

__all__ = [
    'DRIVE_IDENTITY_FKS',
    'ExpectedForeignKey',
    'PreflightError',
    'assertAppliedMigrationFkTopology',
    'assertDriveIdentityFks',
    'findMissingDriveIdentityFks',
    'probeAppliedFk',
]


# ================================================================================
# Exceptions
# ================================================================================


class PreflightError(MigrationError):
    """Raised when the applied-schema FK preflight finds drift.

    Subclasses :class:`MigrationError` so ``apply_server_migrations.main
    --run-all`` converts it to a non-zero exit and ``deploy-server.sh`` (under
    ``set -e``) halts the deploy before any service restart.
    """


# ================================================================================
# Expected-FK registry (define-once against v0022's constants)
# ================================================================================


@dataclass(frozen=True, slots=True)
class ExpectedForeignKey:
    """One drive-identity FK the applied schema must carry once its migration ran.

    * ``table`` / ``column`` -- the referencing table + column.
    * ``refTable`` / ``refColumn`` -- the referenced canonical identity.
    * ``constraintName`` -- the migration's declared FK name (audit / message).
    * ``sourceVersion`` -- the migration version that establishes this FK; the
      ledger gate asserts it only once this version is recorded applied.
    """

    table: str
    column: str
    refTable: str
    refColumn: str
    constraintName: str
    sourceVersion: str


# The canonical drive-identity FK topology, sourced from v0022's own identifiers
# so a rename in the migration is caught by the DDL-parity tests here.  Both are
# on ``summary_id`` (``m0022._SUMMARY_FK_COLUMN``) -> ``drives.drive_id``.
DRIVE_IDENTITY_FKS: tuple[ExpectedForeignKey, ...] = (
    ExpectedForeignKey(
        table=m0022.DRIVE_STATISTICS_TABLE,
        column=m0022._SUMMARY_FK_COLUMN,
        refTable=DRIVES_TABLE,
        refColumn='drive_id',
        constraintName=m0022.DRIVE_STATISTICS_FK_NAME,
        sourceVersion=m0022.VERSION,
    ),
    ExpectedForeignKey(
        table=m0022.DRIVE_DERIVED_SIGNALS_TABLE,
        column=m0022._SUMMARY_FK_COLUMN,
        refTable=DRIVES_TABLE,
        refColumn='drive_id',
        constraintName=m0022.DRIVE_DERIVED_SIGNALS_FK_NAME,
        sourceVersion=m0022.VERSION,
    ),
)


# ================================================================================
# Applied-schema probe + verdict logic
# ================================================================================


def probeAppliedFk(ctx: RunnerContext, fk: ExpectedForeignKey) -> str | None:
    """Return the applied FK constraint name for ``fk``, or ``None`` if absent.

    Reuses v0022's :func:`_fkNameReferencing` KEY_COLUMN_USAGE query (define-once)
    so the guard and the migration share one definition of "the ``summary_id``
    FK on ``table`` referencing ``refTable``".  ``None`` means the deployed
    schema carries no such FK -- the A-10 drift the guard exists to catch.

    (The reused probe is scoped to ``summary_id``; every drive-identity FK is on
    that column, so reuse is exact.  A future non-``summary_id`` FK would
    generalise :func:`_fkNameReferencing` in one place.)
    """
    return m0022._fkNameReferencing(ctx, fk.table, fk.refTable)


def findMissingDriveIdentityFks(
    ctx: RunnerContext,
    expectedFks: tuple[ExpectedForeignKey, ...],
) -> list[ExpectedForeignKey]:
    """Return the subset of ``expectedFks`` absent from the applied schema.

    An unreachable probe raises (``SchemaProbeError`` from the reused v0022
    probe) -- loud, never a silent false GREEN.
    """
    return [fk for fk in expectedFks if probeAppliedFk(ctx, fk) is None]


def assertDriveIdentityFks(
    ctx: RunnerContext,
    expectedFks: tuple[ExpectedForeignKey, ...],
) -> None:
    """Assert every FK in ``expectedFks`` exists on the APPLIED schema.

    GREEN (no raise) when the deployed schema carries them all; RED
    (:class:`PreflightError`) when any is missing, with a message naming each
    delta's table + column + expected FK target.
    """
    missing = findMissingDriveIdentityFks(ctx, expectedFks)
    if not missing:
        return
    deltas = '; '.join(
        f'{fk.table}.{fk.column} -> {fk.refTable}.{fk.refColumn} '
        f'(expected FK {fk.constraintName})'
        for fk in missing
    )
    raise PreflightError(
        'applied-schema FK preflight FAILED -- expected drive-identity FK(s) '
        f'missing on the deployed MariaDB schema: {deltas}. The migration '
        'declares these but information_schema does not carry them -- A-10 '
        'ORM-vs-DB drift.  Reconcile the applied schema before deploying.',
    )


# ================================================================================
# Reachability probe + wired deploy-preflight entry
# ================================================================================


def _mariaDbReachable(ctx: RunnerContext) -> bool:
    """Return True if a trivial ``SELECT 1`` succeeds against the server DB.

    Used so the wired preflight can SKIP HONESTLY when no MariaDB is reachable
    (the Windows bench) instead of hard-failing the deploy on an un-probed DB.
    """
    res = _runServerSql(ctx.addrs, ctx.creds, 'SELECT 1;', ctx.runner)
    return res.returncode == 0


def assertAppliedMigrationFkTopology(
    ctx: RunnerContext,
    reg: MigrationRunner,
    *,
    expectedFks: tuple[ExpectedForeignKey, ...] = DRIVE_IDENTITY_FKS,
) -> None:
    """Deploy-preflight: assert applied migrations' promised FK topology.

    Called by :func:`scripts.apply_server_migrations.runRegistry` BEFORE the
    migration set.  Steps:

    1. **Honest skip** if MariaDB is unreachable -- never a false pass.
    2. **Ledger gate**: read ``schema_migrations`` and keep only FKs whose
       ``sourceVersion`` is already applied, so a still-pending migration's own
       output FK is not required yet (no deadlock on the BL-020 resume-deploy).
    3. **Assert** the gated set on the applied schema; raise
       :class:`PreflightError` (fails the deploy) on any drift.
    """
    if not _mariaDbReachable(ctx):
        print(
            '[preflight] MariaDB unreachable -- skipping applied-schema FK '
            'topology preflight (honest skip, NOT a pass; runAll will fail '
            'loudly if the DB is truly needed and unreachable).',
        )
        return

    reg.ensureTracking(ctx)
    applied = reg.getApplied(ctx)
    gated = tuple(fk for fk in expectedFks if fk.sourceVersion in applied)
    if not gated:
        print(
            '[preflight] no applied-migration drive-identity FK to assert yet '
            '(their migration is still pending) -- deferring to the migration '
            'set.',
        )
        return
    assertDriveIdentityFks(ctx, gated)
    print(
        f'[preflight] applied-schema FK topology OK '
        f'({len(gated)} drive-identity FK(s) verified against '
        'information_schema).',
    )
