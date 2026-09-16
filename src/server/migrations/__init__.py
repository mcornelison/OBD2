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
# 2026-05-01    | Marcus       | TD-043 close -- registered v0006
#               |              | (drive_summary legacy columns -> nullable).
# 2026-05-08    | Rex          | US-300 (B-053 Story 3, BL-010 close) --
#               |              | registered v0007 (sync_history 90-day
#               |              | retention pruning).
# 2026-05-10    | Rex          | US-312 (I-018 Layer 2 close) -- registered
#               |              | v0008 (create baselines table on live
#               |              | MariaDB; calibration --apply unblocked).
# 2026-05-21    | Rex          | US-357 / I-041 close (Sprint 41 V0.27.18
#               |              | hotfix) -- registered v0009 (drive_statistics
#               |              | .data_quality ADD COLUMN per US-351 ORM).
# 2026-05-28    | Rex (US-363) | Sprint 43 V0.28.0 schema pass -- registered
#               |              | v0010 (F-107 attribution-anomaly tripwire:
#               |              | drive_summary.data_quality ADD COLUMN +
#               |              | drive_statistics CHECK enum extension).  v0010
#               |              | is the shared sprint migration; later schema
#               |              | stories append substeps to its apply().
# 2026-06-01    | Rex (US-376) | Sprint 44 V0.28.1 B-076 first slice -- registered
#               |              | v0011 (normalized ecu identity dimension +
#               |              | vehicle_info.ecu_id FK).  Forward-only; v0010
#               |              | untouched.
# 2026-06-01    | Rex (US-377) | Sprint 45 V0.28.2 hotfix -- registered v0012
#               |              | (drive_summary + drive_statistics data_quality
#               |              | VARCHAR(16)->VARCHAR(20); drill-revealed
#               |              | DataError 1406 on 'attribution_anomaly').
# 2026-07-01    | Rex (US-426) | Sprint 52 V0.29.6 -- registered v0016
#               |              | (battery_health_log: drop legacy start_soc/
#               |              | end_soc + add *_vcell_v + *_soc_pct; BL-015).
# 2026-07-01    | Rex (US-424) | Sprint 51 V0.29.5 -- registered v0015 (widen
#               |              | data_quality CHECK with 'foreign_vehicle'; F-116).
# 2026-07-01    | Rex (US-417) | Sprint 51 V0.29.5 -- registered v0014 (create
#               |              | startup_log; natural-key snapshot sync, BL-013).
# 2026-07-01    | Rex (US-412) | Sprint 50 V0.29.4 -- registered v0013 (create
#               |              | power_log table on live MariaDB; F-101 Pi
#               |              | power-event history mirror).  Forward-only.
# 2026-07-02    | Rex (US-436) | Sprint 53 V0.29.7 -- registered v0017 (create
#               |              | drive_derived_signals table; F-106 per-drive
#               |              | acceleration + estimated distance).  Forward-only.
# 2026-07-04    | Rex (US-448) | Sprint 55 V0.29.9 -- registered v0018 (create
#               |              | canonical drives identity table + subsume
#               |              | drive_summary.id as drive_id; F-104 spine).
#               |              | Forward-only.
# 2026-07-04    | Rex (US-453) | Sprint 55 V0.29.9 -- registered v0019 (create
#               |              | pi_state table; D-7/F-082 Pi operational-state
#               |              | singleton mirrored as raw forensic).  Forward-only.
# 2026-07-04    | Rex (US-454) | Sprint 55 V0.29.9 -- registered v0020 (re-map O2
#               |              | parameter_name 'O2_BANK1_SENSOR2_V' -> canonical
#               |              | 'O2_B1S2' across all parameter_name tables;
#               |              | D-3/F-082).  Forward-only.
# 2026-07-04    | Rex (US-455) | Sprint 55 V0.29.9 -- registered v0021 (re-map
#               |              | realtime_data.unit abbreviations 'V'->'volt',
#               |              | 'kPa'->'kilopascal', 's'->'second' to the
#               |              | python-obd native canonical form; D-4/F-082).
#               |              | Forward-only.
# 2026-07-05    | Rex (US-451) | Sprint 55 V0.29.9 -- registered v0022 (drive-
#               |              | identity collapse: widen drives.data_quality
#               |              | CHECK with 'unmappable_legacy' + flag NULL-key
#               |              | legacy drives + re-point drive_statistics/
#               |              | drive_derived_signals summary_id FKs to
#               |              | drives.drive_id; F-104/D-8).  Forward-only.
# 2026-07-05    | Rex (US-458) | Sprint 55 V0.29.9 -- registered v0023 (drop the
#               |              | stale live data_source CHECK US-424 never
#               |              | ALTERed away; discovery-driven schema-wide;
#               |              | F-116/BL-019 A'/A-10/TD-055).  Forward-only.
# 2026-08-21    | Rex (US-563) | Sprint 75 V0.29.30 -- registered v0024 (F-134:
#               |              | data_quality columns DEFAULT to the non-verdict
#               |              | 'unassessed'; drive_summary.is_real DEFAULTs
#               |              | NULL; ambient_temp_at_start_c renamed to
#               |              | intake_air_temp_at_start_c).  Forward-only.
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
from src.server.migrations.versions.v0006_td043_drive_summary_legacy_nullable import (
    MIGRATION as _V0006,
)
from src.server.migrations.versions.v0007_sync_history_retention import (
    MIGRATION as _V0007,
)
from src.server.migrations.versions.v0008_us312_create_baselines import (
    MIGRATION as _V0008,
)
from src.server.migrations.versions.v0009_us351_drive_statistics_data_quality_column import (  # noqa: E501
    MIGRATION as _V0009,
)
from src.server.migrations.versions.v0010_us363_attribution_anomaly_data_quality import (  # noqa: E501
    MIGRATION as _V0010,
)
from src.server.migrations.versions.v0011_us376_ecu_identity import (
    MIGRATION as _V0011,
)
from src.server.migrations.versions.v0012_us377_data_quality_widen import (
    MIGRATION as _V0012,
)
from src.server.migrations.versions.v0013_us412_power_log import (
    MIGRATION as _V0013,
)
from src.server.migrations.versions.v0014_us417_startup_log import (
    MIGRATION as _V0014,
)
from src.server.migrations.versions.v0015_us424_foreign_vehicle_data_quality import (
    MIGRATION as _V0015,
)
from src.server.migrations.versions.v0016_us426_battery_health_soc_pct import (
    MIGRATION as _V0016,
)
from src.server.migrations.versions.v0017_us436_drive_derived_signals import (
    MIGRATION as _V0017,
)
from src.server.migrations.versions.v0018_us448_canonical_drives import (
    MIGRATION as _V0018,
)
from src.server.migrations.versions.v0019_us453_pi_state import (
    MIGRATION as _V0019,
)
from src.server.migrations.versions.v0020_us454_o2_name_normalization import (
    MIGRATION as _V0020,
)
from src.server.migrations.versions.v0021_us455_unit_string_canonicalization import (
    MIGRATION as _V0021,
)
from src.server.migrations.versions.v0022_us451_drive_identity_collapse import (
    MIGRATION as _V0022,
)
from src.server.migrations.versions.v0023_us458_drop_stale_data_source_check import (
    MIGRATION as _V0023,
)
from src.server.migrations.versions.v0024_us563_unassessed_defaults_and_intake_rename import (  # noqa: E501
    MIGRATION as _V0024,
)
from src.server.migrations.versions.v0025_arch020_maintenance_record import (
    MIGRATION as _V0025,
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
    _V0006,
    _V0007,
    _V0008,
    _V0009,
    _V0010,
    _V0011,
    _V0012,
    _V0013,
    _V0014,
    _V0015,
    _V0016,
    _V0017,
    _V0018,
    _V0019,
    _V0020,
    _V0021,
    _V0022,
    _V0023,
    _V0024,
    _V0025,
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
