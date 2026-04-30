################################################################################
# File Name: __init__.py
# Purpose/Description: Public API for the server-side schema migration registry
#                      (US-213 / TD-029 closure). Every schema-changing story
#                      appends a new Migration module to ALL_MIGRATIONS; this
#                      file is the import point for callers.
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
# 2026-04-23    | Rex          | US-223 (TD-031 close) -- registered v0003
#               |              | (drop battery_log).
# 2026-04-29    | Rex          | US-237 (V-1 + V-4 close) -- registered v0004
#               |              | (drive_summary reconcile + sim row truncate).
# 2026-04-29    | Rex          | US-238 (V-2 close) -- registered v0005
#               |              | (create dtc_log table on live MariaDB).
# ================================================================================
################################################################################

"""Server-side schema migration registry (US-213 / TD-029 closure).

``ALL_MIGRATIONS`` is the authoritative ordered list.  To add a migration:

1. Create ``src/server/migrations/versions/vNNNN_<slug>.py`` following
   :mod:`src.server.migrations.versions.v0001_us195_us200_catch_up` as the
   template.  The module exports ``VERSION``, ``DESCRIPTION``, ``apply``, and
   a module-level ``MIGRATION`` :class:`Migration` instance.
2. Import the ``MIGRATION`` symbol here and append to ``ALL_MIGRATIONS``.
3. Ship.  ``deploy-server.sh`` applies pending migrations on next deploy.

Ordering matters: versions are applied in tuple order on a fresh DB.
Keep them numerically ascending so new entries go at the end.
"""

from __future__ import annotations

from src.server.migrations.runner import (
    SCHEMA_MIGRATIONS_TABLE,
    SCHEMA_MIGRATIONS_TABLE_DDL,
    Migration,
    MigrationRunner,
    RegistryError,
    RunnerContext,
    RunReport,
)
from src.server.migrations.versions.v0001_us195_us200_catch_up import (
    MIGRATION as _V0001,
)
from src.server.migrations.versions.v0002_us217_battery_health_log import (
    MIGRATION as _V0002,
)
from src.server.migrations.versions.v0003_us223_drop_battery_log import (
    MIGRATION as _V0003,
)
from src.server.migrations.versions.v0004_us237_drive_summary_reconcile import (
    MIGRATION as _V0004,
)
from src.server.migrations.versions.v0005_us238_create_dtc_log import (
    MIGRATION as _V0005,
)

# ================================================================================
# Registry -- append new migrations to the end, in ascending version order
# ================================================================================

ALL_MIGRATIONS: tuple[Migration, ...] = (
    _V0001,
    _V0002,
    _V0003,
    _V0004,
    _V0005,
)


__all__ = [
    'ALL_MIGRATIONS',
    'Migration',
    'MigrationRunner',
    'RegistryError',
    'RunReport',
    'RunnerContext',
    'SCHEMA_MIGRATIONS_TABLE',
    'SCHEMA_MIGRATIONS_TABLE_DDL',
]
