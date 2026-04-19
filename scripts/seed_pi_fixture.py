################################################################################
# File Name: seed_pi_fixture.py
# Purpose/Description: Build deterministic Pi-shape SQLite fixtures for the
#                      flat-file replay test harness (B-045 / US-191).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-191 (Sprint 13)
# ================================================================================
################################################################################

"""
Deterministic Pi-shape SQLite fixture generator for :mod:`scripts.replay_pi_fixture`.

Writes a fresh SQLite file matching the Pi's production schema
(:mod:`src.pi.obdii.database_schema` plus :mod:`src.pi.data.sync_log`) with
every in-scope sync table present but only ``realtime_data`` /
``connection_log`` / ``statistics`` populated.  The values are produced by
pure arithmetic seeded on the (drive, parameter, sample) triplet so two
invocations with the same arguments produce byte-identical files -- no
``random`` module, no ``datetime.now()``, no wall-clock references.

Rationale (B-045 + US-191 stopCondition)::

    "if existing seed_scenarios.py can't easily be extended to emit Pi-shape
     fixtures (different schema enough that --target=pi is more work than
     building fresh) -- write a small standalone seed_pi_fixture.py instead,
     surface design choice to PM"

seed_scenarios.py runs the physics simulator (noise_enabled=True -> non-
deterministic) and covers only 3 tables.  This story requires all 8 in-scope
sync tables, deterministic output, and explicit sync_log seeding.  Extending
seed_scenarios would have meant gutting it; a fresh standalone is cleaner.

Usage::

    # Build one fixture.
    python scripts/seed_pi_fixture.py --fixture cold_start \\
        --output data/regression/pi-inputs/cold_start.db

    # Build all three canonical fixtures in one shot.
    python scripts/seed_pi_fixture.py --all --output-dir data/regression/pi-inputs

Each canonical fixture:

* ``cold_start.db``  -- one drive, ~5 min, ~150 realtime_data rows
* ``local_loop.db``  -- one drive, ~15 min, ~900 realtime_data rows
* ``errand_day.db``  -- three drives with parked gaps, ~2000 realtime_data rows

All three write:

* full Pi schema (:data:`ALL_SCHEMAS` + :data:`ALL_INDEXES`)
* profiles row ``daily`` (FK target for realtime_data / statistics)
* vehicle_info row for the Eclipse VIN (grounding reference)
* empty ai_recommendations / alert_log / calibration_sessions tables
  (SyncClient iterates all 8 in-scope tables; empty table = empty push, OK)
* sync_log initialised with all 8 in-scope tables at ``last_synced_id=0``
  so :meth:`SyncClient.pushDelta` treats every row as pending

Invariants:

* No ``random``; no ``time.time()`` / ``datetime.now()``.  Every value is
  a closed-form function of (fixture name, drive index, parameter index,
  sample index).
* ``sqlite_sequence`` rows are normalised at the end so AUTOINCREMENT
  counters round-trip identically across machines.
* PRAGMA ``journal_mode`` is left at ``delete`` (the default) rather than
  WAL, so the fixture is a single self-contained ``.db`` file with no
  sidecar ``-wal`` / ``-shm`` files.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path bootstrap so absolute imports resolve when invoked from anywhere.
# src/ also needs to be on the path because src/pi/obdii/__init__.py does
# ``from pi.display import ...`` (relative to src/), mirroring seed_scenarios.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from src.pi.data import sync_log  # noqa: E402
from src.pi.obdii.database_schema import ALL_INDEXES, ALL_SCHEMAS  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = [
    "FIXTURES",
    "FixtureSpec",
    "buildFixture",
    "main",
    "parseArguments",
]


# ================================================================================
# Fixture specs
# ================================================================================

# Deterministic base timestamp used as the origin for every fixture.  A fixed
# ISO instant keeps generated timestamps stable across runs (no wall-clock).
# Formatted exactly as the Pi writes via ObdDatabase ("YYYY-MM-DD HH:MM:SS").
_BASE_ISO: str = "2026-04-19 08:00:00"

# Profile the fixtures tag their rows with.  Matches the "daily" default the
# Pi ships with so the SyncClient path exercises FK-present rows.
_PROFILE_ID: str = "daily"

# Grounded VIN for the Eclipse (MEMORY.md / grounded-knowledge.md).  Included
# so vehicle_info sync pushes a realistic row on first replay.
_ECLIPSE_VIN: str = "4A3AK54F8WE122916"


# Five base parameters used when a fixture enables "small" parameter coverage,
# ten when it enables "full".  Match the Pi production PID naming (uppercase).
_PARAMS_SMALL: tuple[tuple[str, str], ...] = (
    ("RPM", "rpm"),
    ("COOLANT_TEMP", "°C"),
    ("THROTTLE_POS", "%"),
    ("SPEED", "km/h"),
    ("INTAKE_TEMP", "°C"),
)

_PARAMS_FULL: tuple[tuple[str, str], ...] = _PARAMS_SMALL + (
    ("ENGINE_LOAD", "%"),
    ("MAF", "g/s"),
    ("CONTROL_MODULE_VOLTAGE", "V"),
    ("SHORT_FUEL_TRIM_1", "%"),
    ("LONG_FUEL_TRIM_1", "%"),
)


class FixtureSpec:
    """Declarative shape of a single Pi fixture.

    Attributes:
        name: Fixture identifier (used as output filename stem).
        driveDurations: List of drive durations in seconds.  One entry per
            drive session in the fixture.
        gapSeconds: Parked time between consecutive drives.  Length must be
            ``len(driveDurations) - 1``.
        sampleCadenceSeconds: Fixed wall-clock cadence between realtime
            samples.  Every parameter emits one row per sample.
        paramSet: Tuple of (parameter_name, unit) pairs used for realtime
            rows.  Size drives total row count.
    """

    __slots__ = (
        "name",
        "driveDurations",
        "gapSeconds",
        "sampleCadenceSeconds",
        "paramSet",
    )

    def __init__(
        self,
        name: str,
        driveDurations: tuple[int, ...],
        gapSeconds: tuple[int, ...],
        sampleCadenceSeconds: int,
        paramSet: tuple[tuple[str, str], ...],
    ) -> None:
        if len(gapSeconds) != max(0, len(driveDurations) - 1):
            raise ValueError(
                f"gapSeconds length must be {max(0, len(driveDurations) - 1)} "
                f"(one fewer than driveDurations); got {len(gapSeconds)}",
            )
        self.name = name
        self.driveDurations = driveDurations
        self.gapSeconds = gapSeconds
        self.sampleCadenceSeconds = sampleCadenceSeconds
        self.paramSet = paramSet


# Canonical fixtures per US-191 AC.  Counts balance "approximately the AC
# target" against "nice round numbers that are easy to explain".
#
# cold_start  : 1 drive x 300s @ 10s cadence x 5 params   =  150 rows
# local_loop  : 1 drive x 900s @ 10s cadence x 10 params  =  900 rows
# errand_day  : 3 drives (360+720+360)s @ 3s cadence x 5  = 2000 rows
#                 (sample totals: 120 + 240 + 120 = 480 samples * 5 params)
#
# Drive timestamps include drive_start / drive_end connection_log events
# so the server-side ``detectDriveDataReceived`` logic triggers as it would
# with real data.
FIXTURES: dict[str, FixtureSpec] = {
    "cold_start": FixtureSpec(
        name="cold_start",
        driveDurations=(300,),
        gapSeconds=(),
        sampleCadenceSeconds=10,
        paramSet=_PARAMS_SMALL,
    ),
    "local_loop": FixtureSpec(
        name="local_loop",
        driveDurations=(900,),
        gapSeconds=(),
        sampleCadenceSeconds=10,
        paramSet=_PARAMS_FULL,
    ),
    "errand_day": FixtureSpec(
        name="errand_day",
        driveDurations=(360, 720, 360),
        gapSeconds=(300, 600),
        sampleCadenceSeconds=3,
        paramSet=_PARAMS_SMALL,
    ),
}


# ================================================================================
# Deterministic value synthesis
# ================================================================================

# Baseline values + amplitudes per parameter.  Chosen to land safely inside
# the ranges in specs/grounded-knowledge.md (idle RPM ~800, warm coolant
# ~180°F = 82°C, etc.).  The whole point of deterministic is they're not
# "realistic drive shape" -- they're reproducible nonsense shaped to fall
# in range so any range-checker downstream (US-168) doesn't trip.
_BASELINE: dict[str, tuple[float, float, float]] = {
    # name -> (center, amplitude, slow_period_samples)
    "RPM":                     (900.0,  200.0, 30.0),
    "COOLANT_TEMP":            ( 82.0,    3.0, 45.0),
    "THROTTLE_POS":            ( 15.0,    8.0, 20.0),
    "SPEED":                   (  0.0,    0.0, 10.0),
    "INTAKE_TEMP":             ( 30.0,    5.0, 60.0),
    "ENGINE_LOAD":             ( 20.0,    5.0, 25.0),
    "MAF":                     (  5.0,    1.5, 15.0),
    "CONTROL_MODULE_VOLTAGE":  ( 14.0,    0.3, 50.0),
    "SHORT_FUEL_TRIM_1":       (  0.0,    4.0, 40.0),
    "LONG_FUEL_TRIM_1":        (  2.0,    2.0, 80.0),
}


def _computeValue(paramName: str, driveIndex: int, sampleIndex: int) -> float:
    """Deterministic value for (paramName, drive, sample).

    Closed-form sinusoid + per-drive phase offset so different drives in a
    multi-drive fixture don't produce identical traces.  Rounded to 2 dp so
    float representation is stable across platforms.
    """
    center, amplitude, period = _BASELINE.get(paramName, (0.0, 0.0, 30.0))
    phase = 0.37 * driveIndex  # arbitrary irrational-ish offset per drive
    angle = (2.0 * math.pi * sampleIndex / period) + phase
    return round(center + amplitude * math.sin(angle), 2)


def _formatTimestamp(baseOffsetSeconds: int) -> str:
    """Render ``_BASE_ISO + baseOffsetSeconds`` as a Pi-schema timestamp.

    Hand-rolled to avoid ``datetime.now()`` creeping in via a default
    argument and to keep the generator dependency-light.  ``_BASE_ISO`` is
    a known-good string, offset never exceeds a day in practice -- we just
    parse + add via the timetuple math below.
    """
    from datetime import datetime, timedelta
    base = datetime.strptime(_BASE_ISO, "%Y-%m-%d %H:%M:%S")
    return (base + timedelta(seconds=baseOffsetSeconds)).strftime(
        "%Y-%m-%d %H:%M:%S",
    )


# ================================================================================
# Database construction
# ================================================================================


def _createSchema(conn: sqlite3.Connection) -> None:
    """Apply every Pi schema statement + sync_log to ``conn``.

    Tables + indexes come from the canonical schema module so there's no
    chance of drift.  :func:`sync_log.initDb` adds the ``sync_log`` table
    on top.  No index on sync_log is needed (PK is the table name).
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    for _, ddl in ALL_SCHEMAS:
        conn.execute(ddl)
    for _, ddl in ALL_INDEXES:
        conn.execute(ddl)
    sync_log.initDb(conn)


def _insertProfileAndVehicle(conn: sqlite3.Connection) -> None:
    """Seed the one-row ``profiles`` and ``vehicle_info`` tables.

    Deterministic ``created_at`` / ``updated_at`` columns are set to
    ``_BASE_ISO`` to avoid the schema's ``DEFAULT CURRENT_TIMESTAMP``
    poisoning reproducibility.
    """
    conn.execute(
        "INSERT INTO profiles (id, name, description, polling_interval_ms, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (_PROFILE_ID, "Daily", "Deterministic fixture profile", 1000,
         _BASE_ISO, _BASE_ISO),
    )
    conn.execute(
        "INSERT INTO vehicle_info (vin, make, model, year, engine, fuel_type, "
        "transmission, drive_type, body_class, plant_city, plant_country, "
        "raw_api_response, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_ECLIPSE_VIN, "MITSUBISHI", "Eclipse", 1998, "4G63",
         "Gasoline", "Manual", "FWD", "Coupe", "Normal", "Japan",
         "{}", _BASE_ISO, _BASE_ISO),
    )


def _insertRealtimeAndConnection(
    conn: sqlite3.Connection,
    spec: FixtureSpec,
) -> tuple[int, int]:
    """Insert all realtime + connection_log rows for ``spec``.

    Returns:
        (realtime_rows_inserted, connection_log_rows_inserted)
    """
    wallOffset = 0
    realtimeRows: list[tuple[str, str, float, str, str]] = []
    connLogRows: list[tuple[str, str, int]] = []

    for driveIdx, durationSeconds in enumerate(spec.driveDurations):
        # drive_start event
        connLogRows.append(
            (_formatTimestamp(wallOffset), "drive_start", 1),
        )
        driveStartOffset = wallOffset

        sampleCount = durationSeconds // spec.sampleCadenceSeconds
        for sampleIdx in range(sampleCount):
            sampleOffset = driveStartOffset + (
                sampleIdx * spec.sampleCadenceSeconds
            )
            ts = _formatTimestamp(sampleOffset)
            for paramName, unit in spec.paramSet:
                value = _computeValue(paramName, driveIdx, sampleIdx)
                realtimeRows.append(
                    (ts, paramName, value, unit, _PROFILE_ID),
                )

        wallOffset = driveStartOffset + durationSeconds
        # drive_end event
        connLogRows.append(
            (_formatTimestamp(wallOffset), "drive_end", 1),
        )

        # Parked gap (if any more drives follow)
        if driveIdx < len(spec.gapSeconds):
            wallOffset += spec.gapSeconds[driveIdx]

    conn.executemany(
        "INSERT INTO realtime_data (timestamp, parameter_name, value, unit, "
        "profile_id) VALUES (?, ?, ?, ?, ?)",
        realtimeRows,
    )
    conn.executemany(
        "INSERT INTO connection_log (timestamp, event_type, success) "
        "VALUES (?, ?, ?)",
        connLogRows,
    )
    return len(realtimeRows), len(connLogRows)


def _insertStatistics(conn: sqlite3.Connection, spec: FixtureSpec) -> int:
    """Write one statistics row per parameter based on the realtime rows.

    Aggregates computed from the already-inserted realtime data so the
    numbers match exactly what a post-drive engine would emit.  The
    ``analysis_date`` is the fixture base so re-running is deterministic.
    """
    analysisDate = _formatTimestamp(sum(spec.driveDurations) + sum(spec.gapSeconds))
    inserted = 0
    for paramName, _unit in spec.paramSet:
        rows = conn.execute(
            "SELECT value FROM realtime_data WHERE parameter_name = ?",
            (paramName,),
        ).fetchall()
        values = [float(r[0]) for r in rows]
        if not values:
            continue
        minVal = min(values)
        maxVal = max(values)
        avgVal = sum(values) / len(values)
        variance = sum((v - avgVal) ** 2 for v in values) / len(values)
        stdDev = math.sqrt(variance)
        conn.execute(
            "INSERT INTO statistics "
            "(parameter_name, analysis_date, profile_id, "
            "max_value, min_value, avg_value, mode_value, "
            "std_1, std_2, outlier_min, outlier_max, sample_count, "
            "created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                paramName, analysisDate, _PROFILE_ID,
                round(maxVal, 2), round(minVal, 2), round(avgVal, 2), None,
                round(stdDev, 4), round(2.0 * stdDev, 4),
                round(avgVal - 2.0 * stdDev, 4),
                round(avgVal + 2.0 * stdDev, 4),
                len(values),
                _BASE_ISO,
            ),
        )
        inserted += 1
    return inserted


def _primeSyncLog(conn: sqlite3.Connection) -> None:
    """Seed sync_log with every in-scope table at ``last_synced_id=0``.

    Leaving sync_log empty would also yield ``last_synced_id=0`` via
    :func:`sync_log.getHighWaterMark`'s default, but explicitly seeding
    the rows makes the fixture self-documenting: any reader can
    ``SELECT * FROM sync_log`` and see the initial state rather than
    inferring it from default-behavior.  Every row uses a deterministic
    timestamp so the fixture stays bit-stable.
    """
    for tableName in sorted(sync_log.IN_SCOPE_TABLES):
        conn.execute(
            "INSERT INTO sync_log "
            "(table_name, last_synced_id, last_synced_at, last_batch_id, "
            "status) VALUES (?, ?, ?, ?, ?)",
            (tableName, 0, None, None, "pending"),
        )


def _normaliseSqliteSequence(conn: sqlite3.Connection) -> None:
    """Sort ``sqlite_sequence`` rows by name for byte-stable output.

    SQLite orders ``sqlite_sequence`` rows by insertion time by default,
    and :meth:`executemany` can emit rows in different physical order
    depending on planner internals.  Rewriting with a deterministic
    ORDER BY tightens the reproducibility invariant.
    """
    rows = conn.execute(
        "SELECT name, seq FROM sqlite_sequence ORDER BY name",
    ).fetchall()
    conn.execute("DELETE FROM sqlite_sequence")
    conn.executemany(
        "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
        rows,
    )


# ================================================================================
# Public API
# ================================================================================


def buildFixture(spec: FixtureSpec, outputPath: Path) -> dict[str, int]:
    """Build a single fixture at ``outputPath`` and return per-table row counts.

    Overwrites ``outputPath`` if it already exists.  Parent directory is
    created when missing.

    Args:
        spec: Fixture specification (see :data:`FIXTURES` for canonical).
        outputPath: Target SQLite file path.

    Returns:
        Mapping of table name -> row count for the populated tables.
    """
    outputPath.parent.mkdir(parents=True, exist_ok=True)
    if outputPath.exists():
        outputPath.unlink()

    conn = sqlite3.connect(outputPath)
    try:
        _createSchema(conn)
        _insertProfileAndVehicle(conn)
        realtimeCount, connLogCount = _insertRealtimeAndConnection(conn, spec)
        statsCount = _insertStatistics(conn, spec)
        _primeSyncLog(conn)
        _normaliseSqliteSequence(conn)
        conn.commit()
        conn.execute("VACUUM")  # compact the file so two runs match bytes
    finally:
        conn.close()

    return {
        "realtime_data": realtimeCount,
        "connection_log": connLogCount,
        "statistics": statsCount,
        "profiles": 1,
        "vehicle_info": 1,
        "ai_recommendations": 0,
        "alert_log": 0,
        "calibration_sessions": 0,
    }


# ================================================================================
# CLI
# ================================================================================


def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Optional argv slice for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Populated ``argparse.Namespace``.
    """
    parser = argparse.ArgumentParser(
        prog="seed_pi_fixture.py",
        description=(
            "Build deterministic Pi-shape SQLite fixtures for the "
            "replay_pi_fixture.sh test harness (US-191 / B-045)."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--fixture",
        choices=sorted(FIXTURES.keys()),
        help="Build a single named fixture.",
    )
    group.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Build every canonical fixture (cold_start, local_loop, errand_day).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Output file path (required with --fixture).",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        help="Output directory (required with --all; one .db per fixture).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argv slice; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code (0 on success).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = parseArguments(argv)

    if args.all:
        if not args.output_dir:
            print(
                "Error: --output-dir is required with --all",
                file=sys.stderr,
            )
            return 2
        outDir = Path(args.output_dir)
        for name, spec in FIXTURES.items():
            target = outDir / f"{name}.db"
            counts = buildFixture(spec, target)
            print(
                f"{name}.db -> {counts['realtime_data']} realtime, "
                f"{counts['connection_log']} connection_log, "
                f"{counts['statistics']} statistics "
                f"({os.path.getsize(target)} bytes)",
            )
        return 0

    if not args.output:
        print("Error: --output is required with --fixture", file=sys.stderr)
        return 2
    spec = FIXTURES[args.fixture]
    counts = buildFixture(spec, Path(args.output))
    print(
        f"{args.fixture} -> {counts['realtime_data']} realtime, "
        f"{counts['connection_log']} connection_log, "
        f"{counts['statistics']} statistics",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
